"""RBAC and tenant isolation.

These are the tests that matter most. Every one of them asserts something the
system must *refuse* to do.
"""

from __future__ import annotations

import uuid


class TestTenantIsolation:
    async def test_a_user_cannot_address_another_merchant(self, client, owner_headers, seeded):
        """The headline isolation guarantee: merchant A cannot read merchant B."""
        response = await client.get(
            "/dashboard/overview",
            params={"merchant_id": str(seeded["other_merchant_id"])},
            headers=owner_headers,
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "MERCHANT_SCOPE_VIOLATION"

    async def test_the_merchant_header_is_also_scoped(self, client, owner_headers, seeded):
        response = await client.get(
            "/dashboard/overview",
            headers={**owner_headers, "X-Merchant-ID": str(seeded["other_merchant_id"])},
        )
        assert response.status_code == 403

    async def test_an_unknown_merchant_id_is_refused(self, client, owner_headers):
        response = await client.get(
            "/dashboard/overview",
            params={"merchant_id": str(uuid.uuid4())},
            headers=owner_headers,
        )
        assert response.status_code == 403

    async def test_each_tenant_sees_only_its_own_figures(
        self, client, owner_headers, outsider_headers
    ):
        mine = await client.get("/dashboard/overview", headers=owner_headers)
        theirs = await client.get("/dashboard/overview", headers=outsider_headers)
        assert mine.status_code == 200 and theirs.status_code == 200

        mine_data = mine.json()["data"]
        theirs_data = theirs.json()["data"]
        assert mine_data["merchant_name"] == "Test Cafe"
        assert theirs_data["merchant_name"] == "Other Cafe"
        # The seed gives the rival exactly half the revenue - so these must differ.
        assert mine_data["summary"]["revenue"] != theirs_data["summary"]["revenue"]

    async def test_a_resource_id_from_another_tenant_is_not_found(
        self, client, owner_headers, outsider_headers
    ):
        """A scoped repository must return "not found", never the other tenant's row."""
        created = await client.post(
            "/campaigns",
            json={"name": "Outsider campaign", "objective": "should stay private"},
            headers=outsider_headers,
        )
        assert created.status_code == 201
        foreign_id = created.json()["data"]["id"]

        response = await client.get(f"/campaigns/{foreign_id}", headers=owner_headers)
        assert response.status_code == 404


class TestRolePermissions:
    async def test_viewer_can_read_the_dashboard(self, client, viewer_headers):
        response = await client.get("/dashboard/overview", headers=viewer_headers)
        assert response.status_code == 200

    async def test_viewer_cannot_create_a_campaign(self, client, viewer_headers):
        response = await client.post(
            "/campaigns", json={"name": "Nope", "objective": "x"}, headers=viewer_headers
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"

    async def test_viewer_cannot_execute_a_campaign(self, client, viewer_headers):
        response = await client.post(f"/campaigns/{uuid.uuid4()}/execute", headers=viewer_headers)
        assert response.status_code == 403

    async def test_viewer_cannot_run_an_agent(self, client, viewer_headers):
        response = await client.post(
            "/agents/ask", json={"message": "why are sales down?"}, headers=viewer_headers
        )
        assert response.status_code == 403

    async def test_analyst_can_create_but_not_approve(self, client, analyst_headers):
        created = await client.post(
            "/campaigns",
            json={"name": "Analyst proposal", "objective": "test the gate"},
            headers=analyst_headers,
        )
        assert created.status_code == 201
        campaign_id = created.json()["data"]["id"]

        approved = await client.post(
            f"/campaigns/{campaign_id}/approve", json={"approve": True}, headers=analyst_headers
        )
        assert approved.status_code == 403

    async def test_analyst_cannot_execute(self, client, analyst_headers):
        created = await client.post(
            "/campaigns",
            json={"name": "Analyst execution attempt", "objective": "x"},
            headers=analyst_headers,
        )
        campaign_id = created.json()["data"]["id"]
        response = await client.post(f"/campaigns/{campaign_id}/execute", headers=analyst_headers)
        assert response.status_code == 403

    async def test_staff_cannot_change_roles(self, client, staff_headers, seeded):
        response = await client.post(
            "/users/role",
            json={"user_id": str(seeded["users"]["VIEWER"]), "role": "ADMIN"},
            headers=staff_headers,
        )
        assert response.status_code == 403

    async def test_staff_cannot_read_the_audit_log(self, client, staff_headers):
        response = await client.get("/audit-logs", headers=staff_headers)
        assert response.status_code == 403

    async def test_owner_can_change_roles(self, client, owner_headers, seeded):
        response = await client.post(
            "/users/role",
            json={"user_id": str(seeded["users"]["STAFF"]), "role": "ANALYST"},
            headers=owner_headers,
        )
        assert response.status_code == 200
        # Put it back so later tests see the expected role.
        await client.post(
            "/users/role",
            json={"user_id": str(seeded["users"]["STAFF"]), "role": "STAFF"},
            headers=owner_headers,
        )

    async def test_the_last_owner_cannot_be_demoted(self, client, owner_headers, seeded):
        response = await client.post(
            "/users/role",
            json={"user_id": str(seeded["users"]["OWNER"]), "role": "VIEWER"},
            headers=owner_headers,
        )
        assert response.status_code == 403
        assert "only owner" in response.json()["error"]["message"].lower()


class TestApprovalGate:
    async def test_execution_without_approval_is_refused(self, client, owner_headers):
        """Even an Owner cannot execute a campaign that has no approval on record."""
        created = await client.post(
            "/campaigns",
            json={"name": "Unapproved campaign", "objective": "must not run"},
            headers=owner_headers,
        )
        campaign_id = created.json()["data"]["id"]

        response = await client.post(f"/campaigns/{campaign_id}/execute", headers=owner_headers)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "APPROVAL_REQUIRED"

    async def test_execution_succeeds_once_approved(self, client, owner_headers):
        created = await client.post(
            "/campaigns",
            json={"name": "Approved campaign", "objective": "should run"},
            headers=owner_headers,
        )
        campaign_id = created.json()["data"]["id"]

        approved = await client.post(
            f"/campaigns/{campaign_id}/approve",
            json={"approve": True, "note": "ok"},
            headers=owner_headers,
        )
        assert approved.status_code == 200

        executed = await client.post(f"/campaigns/{campaign_id}/execute", headers=owner_headers)
        assert executed.status_code == 200
        assert executed.json()["data"]["status"] == "RUNNING"
        # Delivery must always be labelled as simulated.
        assert executed.json()["data"]["is_simulated"] is True
        assert executed.json()["meta"]["simulated"] is True

    async def test_viewer_cannot_approve_an_opportunity(self, client, viewer_headers):
        response = await client.post(
            f"/agents/opportunities/{uuid.uuid4()}/approve",
            json={"approve": True},
            headers=viewer_headers,
        )
        assert response.status_code == 403


class TestPermissionCatalogue:
    async def test_roles_endpoint_matches_the_enforced_map(self, client, owner_headers):
        response = await client.get("/roles", headers=owner_headers)
        assert response.status_code == 200
        roles = {row["name"]: set(row["permissions"]) for row in response.json()["data"]}

        assert "campaign:execute" not in roles["VIEWER"]
        assert "campaign:execute" not in roles["ANALYST"]
        assert "campaign:execute" in roles["ADMIN"]
        assert "users:manage" in roles["OWNER"]
        assert "users:manage" not in roles["ADMIN"]
        # Every role can at least read the dashboard.
        for permissions in roles.values():
            assert "dashboard:read" in permissions
