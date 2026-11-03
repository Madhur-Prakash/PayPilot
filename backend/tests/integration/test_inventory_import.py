"""Bulk inventory import: preview, commit, and the RBAC gate on both.

The seed fixture gives each merchant one `Product` (`<slug>-SKU1`) but no
tracked `InventoryItem` for it - which is itself a real shape this feature has
to handle (a SKU that exists as a product but was never brought into
inventory), so it doubles as coverage for that path rather than needing a
second fixture.
"""

from __future__ import annotations

CSV_HEADERS = "Item Code,Item Name,Category,Qty,Cost,Sale Price,Reorder Level,Vendor\n"


def _csv(existing_sku: str, new_sku: str = "IMP-NEW-1", bad_sku: str = "IMP-BAD-1") -> bytes:
    return (
        CSV_HEADERS
        + f"{new_sku},Cold Brew,Beverages,40,15,60,10,Acme Roasters\n"
        # Existing SKU: a quantity is present but must never be applied - only
        # the reorder point (a policy field) should land.
        + f"{existing_sku},Cold Coffee Updated,beverages,999,,,25,\n"
        # New SKU with no price: must fail validation, not silently default.
        + f"{bad_sku},No Price Item,Snacks,5,10,,3,\n"
    ).encode()


class TestImportPreview:
    async def test_auto_maps_columns_and_classifies_rows(self, client, owner_headers, seeded):
        existing_sku = "test-cafe-SKU1"
        files = {"file": ("stock.csv", _csv(existing_sku), "text/csv")}

        response = await client.post("/inventory/import/preview", headers=owner_headers, files=files)
        assert response.status_code == 200, response.text
        body = response.json()["data"]

        assert body["mapping"]["sku"] == "Item Code"
        assert body["mapping"]["product_name"] == "Item Name"
        assert body["mapping"]["price"] == "Sale Price"
        assert body["mapping"]["reorder_point"] == "Reorder Level"

        assert body["total_rows"] == 3
        assert body["valid_rows"] == 2
        assert body["error_rows"] == 1
        assert body["to_create"] == 1
        assert body["to_update"] == 1

        by_sku = {row["sku"]: row for row in body["rows"]}
        assert by_sku["IMP-NEW-1"]["action"] == "create"
        assert by_sku[existing_sku]["action"] == "update"
        assert by_sku["IMP-BAD-1"]["errors"] == ["Selling price is required to create a new product."]

    async def test_an_explicit_mapping_is_honoured_over_the_suggestion(
        self, client, owner_headers, seeded
    ):
        files = {"file": ("stock.csv", _csv("test-cafe-SKU1"), "text/csv")}
        # Deliberately leave `product_name` unmapped - every row should then
        # fail on the required field, proving the server used *this* mapping
        # rather than falling back to its own suggestion.
        mapping = '{"sku": "Item Code", "price": "Sale Price"}'

        response = await client.post(
            "/inventory/import/preview",
            headers=owner_headers,
            files=files,
            data={"mapping": mapping},
        )
        assert response.status_code == 200, response.text
        body = response.json()["data"]
        assert body["mapping"]["product_name"] is None
        assert body["valid_rows"] == 0
        assert all("Product name is required." in row["errors"] for row in body["rows"])

    async def test_rejects_a_mapping_pointing_at_a_nonexistent_column(
        self, client, owner_headers, seeded
    ):
        files = {"file": ("stock.csv", _csv("test-cafe-SKU1"), "text/csv")}
        response = await client.post(
            "/inventory/import/preview",
            headers=owner_headers,
            files=files,
            data={"mapping": '{"sku": "Not A Real Column"}'},
        )
        assert response.status_code == 400

    async def test_empty_file_is_rejected(self, client, owner_headers):
        files = {"file": ("empty.csv", CSV_HEADERS.encode(), "text/csv")}
        response = await client.post("/inventory/import/preview", headers=owner_headers, files=files)
        assert response.status_code == 400


class TestImportCommit:
    async def test_creates_updates_and_skips_in_one_pass(self, client, owner_headers, seeded):
        existing_sku = "test-cafe-SKU1"
        new_sku, bad_sku = "IMP-CREATE-1", "IMP-BAD-CREATE-1"
        files = {"file": ("stock.csv", _csv(existing_sku, new_sku, bad_sku), "text/csv")}

        response = await client.post("/inventory/import/commit", headers=owner_headers, files=files)
        assert response.status_code == 200, response.text
        outcome = response.json()["data"]
        assert outcome["total_rows"] == 3
        assert outcome["created"] == 1
        assert outcome["updated"] == 1
        assert outcome["skipped"] == 1
        assert outcome["failed"] == 0

        created = await client.get("/inventory/items", headers=owner_headers, params={"q": new_sku})
        new_item = created.json()["data"]["items"][0]
        assert new_item["sku"] == new_sku
        assert new_item["product_name"] == "Cold Brew"
        assert new_item["quantity_on_hand"] == 40.0  # opening RESTOCK on a brand-new item
        assert new_item["reorder_point"] == 10.0

        updated = await client.get(
            "/inventory/items", headers=owner_headers, params={"q": existing_sku}
        )
        updated_item = updated.json()["data"]["items"][0]
        assert updated_item["reorder_point"] == 25.0  # the policy field landed
        assert updated_item["product_name"] == "Cold Coffee Updated"
        # The product existed but had no tracked item yet, so this import is
        # what starts tracking it - at zero, never at the sheet's "Qty" column.
        assert updated_item["quantity_on_hand"] == 0.0

        ledger = await client.get("/inventory/ledger", headers=owner_headers)
        movements = ledger.json()["data"]["items"]
        assert any(
            m["movement_type"] == "RESTOCK" and "Bulk import" in (m.get("note") or "")
            for m in movements
        )

    async def test_a_second_import_never_touches_an_existing_items_quantity(
        self, client, owner_headers, seeded
    ):
        # First import creates IMP-NEW-1 at 40 units (see the test above's fixture row).
        first = _csv("test-cafe-SKU1")
        await client.post(
            "/inventory/import/commit", headers=owner_headers, files={"file": ("a.csv", first, "text/csv")}
        )

        # Re-importing the same SKU with a different "Qty" must leave stock alone.
        second = (
            CSV_HEADERS + "IMP-NEW-1,Cold Brew,Beverages,999,15,60,10,Acme Roasters\n"
        ).encode()
        response = await client.post(
            "/inventory/import/commit",
            headers=owner_headers,
            files={"file": ("b.csv", second, "text/csv")},
        )
        outcome = response.json()["data"]
        assert outcome["updated"] == 1

        items = await client.get(
            "/inventory/items", headers=owner_headers, params={"q": "IMP-NEW-1"}
        )
        assert items.json()["data"]["items"][0]["quantity_on_hand"] == 40.0


class TestImportPermissions:
    async def test_staff_cannot_preview_or_commit(self, client, staff_headers):
        files = {"file": ("stock.csv", (CSV_HEADERS + "X1,Thing,General,1,1,10,1,\n").encode(), "text/csv")}
        preview = await client.post("/inventory/import/preview", headers=staff_headers, files=files)
        assert preview.status_code == 403

        files = {"file": ("stock.csv", (CSV_HEADERS + "X1,Thing,General,1,1,10,1,\n").encode(), "text/csv")}
        commit = await client.post("/inventory/import/commit", headers=staff_headers, files=files)
        assert commit.status_code == 403

    async def test_admin_can_import(self, client, admin_headers, seeded):
        files = {"file": ("stock.csv", _csv("test-cafe-SKU1"), "text/csv")}
        response = await client.post("/inventory/import/preview", headers=admin_headers, files=files)
        assert response.status_code == 200
