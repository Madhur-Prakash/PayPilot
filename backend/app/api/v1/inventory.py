"""Inventory, procurement and automation endpoints.

Three audiences share this module and are deliberately separated:

* **The dashboard** reads stock, ledger, orders and automation runs.
* **n8n** posts to ``/webhooks/n8n/inventory-event`` and calls back through the
  same authenticated APIs a user would. It has no privileged path and no direct
  database access.
* **The browser** holds a websocket at ``/inventory/stream`` for live updates.

Every read and write is merchant-scoped through the existing ``Principal``.
"""

from __future__ import annotations

import io
import json
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse
from pydantic import Field
from sqlalchemy import func, select

from app.api.deps import DbSession, Principal, require_permission
from app.api.realtime import hub
from app.core.config import settings
from app.core.exceptions import AuthenticationError, BadRequestError, NotFoundError
from app.core.logging import get_logger
from app.core.permissions import Permission
from app.core.security import decode_token
from app.db.models.automation import AutomationRun, DomainEvent
from app.db.models.commerce import Product
from app.db.models.inventory import (
    InventoryBatch,
    InventoryItem,
    InventoryMovement,
    MovementType,
)
from app.db.models.procurement import (
    PurchaseOrder,
    Vendor,
    VendorProduct,
)
from app.db.session import SessionLocal
from app.repositories.merchant import AuditLogRepository, MembershipRepository
from app.repositories.user import CustomRoleRepository, UserRepository
from app.schemas.common import APIResponse, PageMeta, Paginated, SchemaBase
from app.services.growth.detector import OpportunityDetector
from app.services.inventory import events as event_bus
from app.services.inventory import import_service
from app.services.inventory.automation import InventoryAutomation
from app.services.inventory.procurement import ProcurementService, notify_vendor
from app.services.inventory.replenishment import decide_reorder
from app.services.inventory.reports import InventoryReports
from app.services.inventory.stock import InsufficientStock, StockEngine

log = get_logger(__name__)
router = APIRouter(tags=["inventory"])


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class StockAdjustRequest(SchemaBase):
    movement_type: str = Field(default=MovementType.ADJUSTMENT, max_length=32)
    quantity: float = Field(gt=0)
    note: str = Field(default="", max_length=500)
    reference_type: str = Field(default="", max_length=32)
    reference_id: str = Field(default="", max_length=64)


class PolicyRequest(SchemaBase):
    reorder_point: float | None = Field(default=None, ge=0)
    reorder_quantity: float | None = Field(default=None, ge=0)
    maximum_stock: float | None = Field(default=None, ge=0)
    minimum_stock: float | None = Field(default=None, ge=0)
    reorder_strategy: str | None = Field(default=None, max_length=24)
    automatic_ordering_enabled: bool | None = None
    expiry_tracking_enabled: bool | None = None
    default_vendor_id: uuid.UUID | None = None


class VendorRequest(SchemaBase):
    name: str = Field(min_length=2, max_length=160)
    contact_name: str = Field(default="", max_length=160)
    email: str = Field(default="", max_length=255)
    phone: str = Field(default="", max_length=32)
    ordering_method: str = Field(default="EMAIL", max_length=16)
    webhook_url: str = Field(default="", max_length=2000)
    lead_time_days: float = Field(default=3, ge=0, le=365)
    is_active: bool = True


class VendorSupplyRequest(SchemaBase):
    inventory_item_id: uuid.UUID
    unit_price: float = Field(default=0, ge=0)
    vendor_sku: str = Field(default="", max_length=64)
    minimum_order_quantity: float = Field(default=0, ge=0)
    is_preferred: bool = False
    automatic_ordering_enabled: bool = True


class ApprovalRequest(SchemaBase):
    approve: bool = True
    note: str = Field(default="", max_length=500)


class ReceiveLine(SchemaBase):
    line_id: uuid.UUID
    quantity: float = Field(gt=0)


class ReceiveRequest(SchemaBase):
    lines: list[ReceiveLine] = Field(min_length=1)
    expiry_date: str | None = None


class ImportColumnOut(SchemaBase):
    header: str
    inferred_type: str
    sample_values: list[str]


class ImportFieldOut(SchemaBase):
    key: str
    label: str
    dtype: str
    description: str
    required: bool


class ImportRowOut(SchemaBase):
    row_number: int
    action: str
    sku: str
    values: dict[str, Any]
    errors: list[str]


class ImportPreviewOut(SchemaBase):
    filename: str
    columns: list[ImportColumnOut]
    fields: list[ImportFieldOut]
    mapping: dict[str, str | None]
    rows: list[ImportRowOut]
    total_rows: int
    valid_rows: int
    error_rows: int
    to_create: int
    to_update: int


class ImportCommitOut(SchemaBase):
    total_rows: int
    created: int
    updated: int
    skipped: int
    failed: int
    row_errors: list[dict[str, Any]]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _item_dict(item: InventoryItem, *, with_value: bool) -> dict[str, Any]:
    """One item, shaped for the table. Cost is omitted without the permission."""
    data: dict[str, Any] = {
        "id": str(item.id),
        "sku": item.sku,
        "product_name": item.product_name,
        "unit": item.unit,
        "quantity_on_hand": float(item.quantity_on_hand),
        "reserved_quantity": float(item.reserved_quantity),
        "available_quantity": item.available_quantity,
        "reorder_point": float(item.reorder_point),
        "reorder_quantity": float(item.reorder_quantity),
        "maximum_stock": float(item.maximum_stock or 0),
        "reorder_strategy": item.reorder_strategy,
        "automatic_ordering_enabled": bool(item.automatic_ordering_enabled),
        "expiry_tracking_enabled": bool(item.expiry_tracking_enabled),
        "status": item.status,
        "supplier": item.supplier,
        "default_vendor_id": str(item.default_vendor_id) if item.default_vendor_id else None,
        "days_of_cover": float(item.days_of_cover) if item.days_of_cover is not None else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }
    if with_value:
        data["unit_cost"] = float(item.unit_cost or 0)
        data["stock_value"] = round(float(item.unit_cost or 0) * float(item.quantity_on_hand), 2)
    return data


async def _broadcast(principal: Principal, event: str, payload: dict[str, Any]) -> None:
    await hub.publish(merchant_id=principal.merchant_id, event=event, payload=payload)


# --------------------------------------------------------------------------- #
# Stock
# --------------------------------------------------------------------------- #
@router.get("/inventory/items", summary="List inventory")
async def list_items(
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    status: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    principal: Principal = Depends(require_permission(Permission.INVENTORY_READ)),
) -> APIResponse[Paginated[dict]]:
    filters = [InventoryItem.merchant_id == principal.merchant_id]
    if status:
        filters.append(InventoryItem.status == status)
    if q:
        term = f"%{q.strip()}%"
        filters.append(InventoryItem.sku.ilike(term) | InventoryItem.product_name.ilike(term))

    total = (
        await session.execute(
            select(func.count()).select_from(InventoryItem).where(*filters)
        )
    ).scalar_one()
    rows = list(
        (
            await session.execute(
                select(InventoryItem)
                .where(*filters)
                .order_by(InventoryItem.status, InventoryItem.sku)
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        ).scalars().all()
    )

    with_value = principal.has(Permission.INVENTORY_VALUE_READ)
    return APIResponse(
        data=Paginated(
            items=[_item_dict(item, with_value=with_value) for item in rows],
            pagination=PageMeta.build(page=page, page_size=page_size, total=int(total)),
        ),
        meta={"shows_value": with_value},
    )


@router.get("/inventory/items/{item_id}", summary="Inventory item detail")
async def get_item(
    item_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.INVENTORY_READ)),
) -> APIResponse[dict]:
    item = (
        await session.execute(
            select(InventoryItem).where(
                InventoryItem.id == item_id,
                InventoryItem.merchant_id == principal.merchant_id,
            )
        )
    ).scalars().first()
    if item is None:
        raise NotFoundError("Inventory item not found.")

    batches = list(
        (
            await session.execute(
                select(InventoryBatch)
                .where(InventoryBatch.inventory_item_id == item.id)
                .order_by(InventoryBatch.expiry_date.nulls_last())
            )
        ).scalars().all()
    )
    decision = decide_reorder(item)

    return APIResponse(
        data={
            **_item_dict(item, with_value=principal.has(Permission.INVENTORY_VALUE_READ)),
            "decision": decision.as_dict(),
            "batches": [
                {
                    "id": str(b.id),
                    "batch_code": b.batch_code,
                    "quantity": float(b.quantity),
                    "status": b.status,
                    "expiry_date": str(b.expiry_date) if b.expiry_date else None,
                    "received_at": b.received_at.isoformat() if b.received_at else None,
                }
                for b in batches
            ],
        }
    )


@router.post("/inventory/items/{item_id}/adjust", summary="Adjust stock")
async def adjust_stock(
    item_id: uuid.UUID,
    payload: StockAdjustRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.INVENTORY_WRITE)),
) -> APIResponse[dict]:
    """Move stock by hand. Every adjustment is a ledger row with a named actor."""
    engine = StockEngine(session, principal.merchant_id)
    try:
        change = await engine.apply(
            item_id=item_id,
            movement_type=payload.movement_type,
            quantity=payload.quantity,
            note=payload.note,
            reference_type=payload.reference_type,
            reference_id=payload.reference_id,
            actor_type="USER",
            actor_id=principal.user_id,
        )
    except InsufficientStock as exc:
        raise BadRequestError(str(exc)) from exc

    await AuditLogRepository(session).record(
        merchant_id=principal.merchant_id,
        action="inventory.adjust",
        actor_id=principal.user_id,
        actor_label=principal.label,
        resource="inventory_item",
        resource_id=str(item_id),
        description=(
            f"{change.item.sku}: {payload.movement_type} {payload.quantity:g} "
            f"({change.balance_before:g} -> {change.balance_after:g})"
        ),
        metadata={"correlation_id": change.correlation_id},
    )
    await session.commit()

    await _broadcast(
        principal,
        "inventory.updated",
        {
            "inventory_item_id": str(item_id),
            "sku": change.item.sku,
            "quantity_on_hand": change.balance_after,
            "available_quantity": change.item.available_quantity,
            "status": change.status_after,
            "correlation_id": change.correlation_id,
        },
    )
    return APIResponse(
        data={
            "correlation_id": change.correlation_id,
            "balance_before": change.balance_before,
            "balance_after": change.balance_after,
            "status": change.status_after,
            "events": change.events,
        }
    )


@router.patch("/inventory/items/{item_id}/policy", summary="Configure reorder policy")
async def set_policy(
    item_id: uuid.UUID,
    payload: PolicyRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.INVENTORY_CONFIGURE)),
) -> APIResponse[dict]:
    item = (
        await session.execute(
            select(InventoryItem).where(
                InventoryItem.id == item_id,
                InventoryItem.merchant_id == principal.merchant_id,
            )
        )
    ).scalars().first()
    if item is None:
        raise NotFoundError("Inventory item not found.")

    before = {
        "reorder_point": float(item.reorder_point),
        "reorder_quantity": float(item.reorder_quantity),
        "automatic_ordering_enabled": bool(item.automatic_ordering_enabled),
    }
    for field_name, value in payload.model_dump(exclude_none=True).items():
        setattr(item, field_name, value)

    item.status = StockEngine.derive_status(item)
    await session.flush()

    await AuditLogRepository(session).record(
        merchant_id=principal.merchant_id,
        action="inventory.configure",
        actor_id=principal.user_id,
        actor_label=principal.label,
        resource="inventory_item",
        resource_id=str(item_id),
        description=f"Reorder policy changed for {item.sku}.",
        metadata={"before": before, "after": payload.model_dump(exclude_none=True)},
    )
    await session.commit()

    await _broadcast(
        principal,
        "inventory.updated",
        {"inventory_item_id": str(item.id), "sku": item.sku, "status": item.status},
    )
    return APIResponse(data=_item_dict(item, with_value=True))


# --------------------------------------------------------------------------- #
# Bulk import
#
# Add inventory from an Excel/CSV export instead of one item at a time. The
# workflow is upload -> preview (auto-mapped columns, every row validated) ->
# the merchant reviews and can re-map -> commit. `import_service` owns all of
# the actual parsing/mapping/validation logic; this layer is just the HTTP
# shape and the merchant-scoped existence check the service needs.
# --------------------------------------------------------------------------- #
MAX_IMPORT_FILE_BYTES = 10 * 1024 * 1024
IMPORT_PREVIEW_SAMPLE_SIZE = 25


async def _existing_skus(session: DbSession, merchant_id: uuid.UUID) -> set[str]:
    result = await session.execute(select(Product.sku).where(Product.merchant_id == merchant_id))
    return {row[0] for row in result.all()}


def _parse_mapping_param(raw: str, headers: list[str]) -> dict[str, str | None]:
    """An empty/omitted `mapping` means "auto-suggest one"; anything else must
    be a JSON object of field key -> column header (or null to leave it blank)."""
    if not raw or not raw.strip():
        return import_service.suggest_mapping(headers)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BadRequestError("mapping must be valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise BadRequestError("mapping must be a JSON object of field key -> column header.")

    header_set = set(headers)
    mapping: dict[str, str | None] = dict.fromkeys(import_service.FIELDS_BY_KEY)
    for key, value in parsed.items():
        if key not in import_service.FIELDS_BY_KEY:
            continue  # an unknown field key is ignored, not an error - forward compatible
        if value is None or value == "":
            continue
        if not isinstance(value, str) or value not in header_set:
            raise BadRequestError(f"mapping.{key} does not match a column in this file.")
        mapping[key] = value
    return mapping


async def _read_and_parse_upload(file: UploadFile) -> import_service.ParsedSheet:
    content = await file.read()
    if len(content) > MAX_IMPORT_FILE_BYTES:
        raise BadRequestError("That file is too large (10 MB limit).")
    try:
        sheet = import_service.parse_upload(file.filename or "", content)
    except import_service.ImportParseError as exc:
        raise BadRequestError(str(exc)) from exc
    if not sheet.rows:
        raise BadRequestError("No data rows found in that file.")
    return sheet


@router.post(
    "/inventory/import/preview",
    summary="Preview a bulk inventory import",
    description=(
        "Upload a .xlsx or .csv export. With no `mapping`, columns are auto-matched to "
        "inventory fields by header text (e.g. 'Item Code' -> sku, 'Reorder Level' -> "
        "reorder_point); pass one back (edited or not) to re-validate against it before "
        "committing. Every row is validated here - nothing is written yet."
    ),
)
async def import_preview(
    session: DbSession,
    file: Annotated[UploadFile, File()],
    mapping: Annotated[str, Form()] = "",
    principal: Principal = Depends(require_permission(Permission.INVENTORY_CONFIGURE)),
) -> APIResponse[ImportPreviewOut]:
    sheet = await _read_and_parse_upload(file)
    resolved_mapping = _parse_mapping_param(mapping, sheet.headers)
    existing = await _existing_skus(session, principal.merchant_id)
    rows = import_service.validate_rows(sheet, resolved_mapping, existing_skus=existing)
    valid = [r for r in rows if r.ok]

    columns = [
        ImportColumnOut(
            header=header,
            inferred_type=import_service.infer_type([r.get(header, "") for r in sheet.rows]),
            sample_values=[r[header] for r in sheet.rows[:5] if r.get(header)],
        )
        for header in sheet.headers
    ]
    fields = [
        ImportFieldOut(
            key=f.key, label=f.label, dtype=f.dtype, description=f.description, required=f.required
        )
        for f in import_service.IMPORT_FIELDS
    ]

    return APIResponse(
        data=ImportPreviewOut(
            filename=file.filename or "upload",
            columns=columns,
            fields=fields,
            mapping=resolved_mapping,
            rows=[
                ImportRowOut(
                    row_number=r.row_number, action=r.action, sku=r.sku, values=r.values, errors=r.errors
                )
                for r in rows[:IMPORT_PREVIEW_SAMPLE_SIZE]
            ],
            total_rows=len(rows),
            valid_rows=len(valid),
            error_rows=len(rows) - len(valid),
            to_create=sum(1 for r in valid if r.action == "create"),
            to_update=sum(1 for r in valid if r.action == "update"),
        )
    )


@router.post(
    "/inventory/import/commit",
    summary="Commit a bulk inventory import",
    description=(
        "Re-validates the file against `mapping` exactly as /preview did, then writes every "
        "row that passes: a new SKU creates its product and item (with an opening RESTOCK "
        "movement if a quantity was given); an existing SKU updates its policy fields only "
        "- never its stock count, which stays under Adjust Stock. Rows that fail validation "
        "are skipped, not partially applied, and one bad row never blocks the rest."
    ),
)
async def import_commit(
    session: DbSession,
    file: Annotated[UploadFile, File()],
    mapping: Annotated[str, Form()] = "",
    principal: Principal = Depends(require_permission(Permission.INVENTORY_CONFIGURE)),
) -> APIResponse[ImportCommitOut]:
    sheet = await _read_and_parse_upload(file)
    resolved_mapping = _parse_mapping_param(mapping, sheet.headers)
    existing = await _existing_skus(session, principal.merchant_id)
    rows = import_service.validate_rows(sheet, resolved_mapping, existing_skus=existing)

    outcome = await import_service.commit_rows(
        session, merchant_id=principal.merchant_id, rows=rows, actor_id=principal.user_id
    )

    await AuditLogRepository(session).record(
        merchant_id=principal.merchant_id,
        action="inventory.import",
        actor_id=principal.user_id,
        actor_label=principal.label,
        resource="inventory_item",
        resource_id="bulk",
        description=(
            f"Imported {file.filename or 'a file'}: {outcome.created} created, "
            f"{outcome.updated} updated, {outcome.skipped} skipped, {outcome.failed} failed "
            f"(of {outcome.total_rows} rows)."
        ),
        metadata={"total_rows": outcome.total_rows, "row_errors": outcome.row_errors[:10]},
    )
    await session.commit()

    await _broadcast(
        principal,
        "inventory.updated",
        {"bulk_import": True, "created": outcome.created, "updated": outcome.updated},
    )

    return APIResponse(
        data=ImportCommitOut(
            total_rows=outcome.total_rows,
            created=outcome.created,
            updated=outcome.updated,
            skipped=outcome.skipped,
            failed=outcome.failed,
            row_errors=outcome.row_errors,
        )
    )


@router.get("/inventory/ledger", summary="Stock movement ledger")
async def ledger(
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    inventory_item_id: Annotated[uuid.UUID | None, Query()] = None,
    movement_type: Annotated[str | None, Query()] = None,
    correlation_id: Annotated[str | None, Query()] = None,
    principal: Principal = Depends(require_permission(Permission.INVENTORY_LEDGER_READ)),
) -> APIResponse[Paginated[dict]]:
    """The append-only record. Nothing here is editable through any API."""
    filters = [InventoryMovement.merchant_id == principal.merchant_id]
    if inventory_item_id:
        filters.append(InventoryMovement.inventory_item_id == inventory_item_id)
    if movement_type:
        filters.append(InventoryMovement.movement_type == movement_type)
    if correlation_id:
        filters.append(InventoryMovement.correlation_id == correlation_id)

    total = (
        await session.execute(
            select(func.count()).select_from(InventoryMovement).where(*filters)
        )
    ).scalar_one()
    rows = list(
        (
            await session.execute(
                select(InventoryMovement)
                .where(*filters)
                .order_by(InventoryMovement.created_at.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        ).scalars().all()
    )

    return APIResponse(
        data=Paginated(
            items=[
                {
                    "id": str(m.id),
                    "inventory_item_id": str(m.inventory_item_id),
                    "movement_type": m.movement_type,
                    "quantity": float(m.quantity),
                    "balance_before": float(m.balance_before),
                    "balance_after": float(m.balance_after),
                    "unit_cost": float(m.unit_cost or 0),
                    "total_value": float(m.total_value or 0),
                    "reference_type": m.reference_type,
                    "reference_id": m.reference_id,
                    "source": m.source,
                    "actor_type": m.actor_type,
                    "correlation_id": m.correlation_id,
                    "note": m.note,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in rows
            ],
            pagination=PageMeta.build(page=page, page_size=page_size, total=int(total)),
        )
    )

# --------------------------------------------------------------------------- #
# Vendors
# --------------------------------------------------------------------------- #
@router.get("/vendors", summary="List vendors")
async def list_vendors(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.VENDOR_READ)),
) -> APIResponse[list[dict]]:
    rows = list(
        (
            await session.execute(
                select(Vendor)
                .where(Vendor.merchant_id == principal.merchant_id)
                .order_by(Vendor.name)
            )
        ).scalars().all()
    )
    return APIResponse(
        data=[
            {
                "id": str(v.id),
                "name": v.name,
                "contact_name": v.contact_name,
                "email": v.email,
                "phone": v.phone,
                "ordering_method": v.ordering_method,
                "lead_time_days": float(v.lead_time_days),
                "is_active": v.is_active,
                "supplies": len(v.supplies or []),
            }
            for v in rows
        ]
    )


@router.post("/vendors", status_code=201, summary="Create a vendor")
async def create_vendor(
    payload: VendorRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.VENDOR_MANAGE)),
) -> APIResponse[dict]:
    exists = (
        await session.execute(
            select(Vendor).where(
                Vendor.merchant_id == principal.merchant_id, Vendor.name == payload.name
            )
        )
    ).scalars().first()
    if exists is not None:
        raise BadRequestError(f"A vendor named '{payload.name}' already exists.")

    vendor = Vendor(merchant_id=principal.merchant_id, **payload.model_dump())
    session.add(vendor)
    await session.flush()
    await AuditLogRepository(session).record(
        merchant_id=principal.merchant_id,
        action="vendor.create",
        actor_id=principal.user_id,
        actor_label=principal.label,
        resource="vendor",
        resource_id=str(vendor.id),
        description=f"Created vendor {vendor.name}.",
    )
    await session.commit()
    return APIResponse(data={"id": str(vendor.id), "name": vendor.name})


@router.post("/vendors/{vendor_id}/supplies", summary="Link a vendor to an item")
async def link_supply(
    vendor_id: uuid.UUID,
    payload: VendorSupplyRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.VENDOR_MANAGE)),
) -> APIResponse[dict]:
    """Record that this vendor can supply this item, and on what terms.

    Both sides are re-checked against the merchant, so a vendor id from one
    tenant can never be attached to another tenant's stock.
    """
    vendor = (
        await session.execute(
            select(Vendor).where(
                Vendor.id == vendor_id, Vendor.merchant_id == principal.merchant_id
            )
        )
    ).scalars().first()
    if vendor is None:
        raise NotFoundError("Vendor not found.")

    item = (
        await session.execute(
            select(InventoryItem).where(
                InventoryItem.id == payload.inventory_item_id,
                InventoryItem.merchant_id == principal.merchant_id,
            )
        )
    ).scalars().first()
    if item is None:
        raise NotFoundError("Inventory item not found.")

    existing = (
        await session.execute(
            select(VendorProduct).where(
                VendorProduct.vendor_id == vendor_id,
                VendorProduct.inventory_item_id == item.id,
            )
        )
    ).scalars().first()

    if existing is not None:
        for key, value in payload.model_dump(exclude={"inventory_item_id"}).items():
            setattr(existing, key, value)
        supply = existing
    else:
        supply = VendorProduct(
            merchant_id=principal.merchant_id,
            vendor_id=vendor_id,
            **payload.model_dump(),
        )
        session.add(supply)

    await session.flush()
    await session.commit()
    return APIResponse(data={"id": str(supply.id), "vendor": vendor.name, "sku": item.sku})


# --------------------------------------------------------------------------- #
# Purchase orders
# --------------------------------------------------------------------------- #
@router.get("/purchase-orders", summary="List purchase orders")
async def list_orders(
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    status: Annotated[str | None, Query()] = None,
    principal: Principal = Depends(require_permission(Permission.PURCHASE_ORDER_READ)),
) -> APIResponse[Paginated[dict]]:
    filters = [PurchaseOrder.merchant_id == principal.merchant_id]
    if status:
        filters.append(PurchaseOrder.status == status)

    total = (
        await session.execute(
            select(func.count()).select_from(PurchaseOrder).where(*filters)
        )
    ).scalar_one()
    rows = list(
        (
            await session.execute(
                select(PurchaseOrder)
                .where(*filters)
                .order_by(PurchaseOrder.created_at.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        ).scalars().all()
    )
    return APIResponse(
        data=Paginated(
            items=[
                {
                    **ProcurementService.describe(o),
                    "source": o.source,
                    "expected_at": str(o.expected_at) if o.expected_at else None,
                    "created_at": o.created_at.isoformat() if o.created_at else None,
                }
                for o in rows
            ],
            pagination=PageMeta.build(page=page, page_size=page_size, total=int(total)),
        )
    )


@router.post("/purchase-orders/{order_id}/approve", summary="Approve or reject an order")
async def approve_order(
    order_id: uuid.UUID,
    payload: ApprovalRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PURCHASE_ORDER_APPROVE)),
) -> APIResponse[dict]:
    """The human gate. Approving also releases the order to the vendor."""
    service = ProcurementService(session, principal.merchant_id)
    order = await service.approve(
        order_id=order_id, approve=payload.approve, actor_id=principal.user_id, note=payload.note
    )

    detail = ""
    if payload.approve:
        _sent, detail = await notify_vendor(order)
        await service.mark_sent(
            order_id=order.id, channel=order.vendor.ordering_method, detail=detail
        )

    await AuditLogRepository(session).record(
        merchant_id=principal.merchant_id,
        action="purchase_order.approve" if payload.approve else "purchase_order.reject",
        actor_id=principal.user_id,
        actor_label=principal.label,
        resource="purchase_order",
        resource_id=str(order.id),
        description=f"{order.reference} {'approved' if payload.approve else 'rejected'}.",
        metadata={"note": payload.note, "vendor_detail": detail},
    )
    await session.commit()

    await _broadcast(
        principal,
        "inventory.purchase_order_updated",
        {"purchase_order_id": str(order.id), "reference": order.reference, "status": order.status},
    )
    return APIResponse(data={**ProcurementService.describe(order), "vendor_detail": detail})


@router.post("/purchase-orders/{order_id}/receive", summary="Record goods received")
async def receive_order(
    order_id: uuid.UUID,
    payload: ReceiveRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PURCHASE_ORDER_RECEIVE)),
) -> APIResponse[dict]:
    """Book in a delivery. Partial receipts leave the order PARTIALLY_RECEIVED."""
    from datetime import date as _date

    expiry = _date.fromisoformat(payload.expiry_date) if payload.expiry_date else None
    service = ProcurementService(session, principal.merchant_id)
    order = await service.receive(
        order_id=order_id,
        lines=[line.model_dump() for line in payload.lines],
        actor_id=principal.user_id,
        expiry_date=expiry,
    )

    await AuditLogRepository(session).record(
        merchant_id=principal.merchant_id,
        action="purchase_order.receive",
        actor_id=principal.user_id,
        actor_label=principal.label,
        resource="purchase_order",
        resource_id=str(order.id),
        description=f"{order.reference} is now {order.status.lower().replace('_', ' ')}.",
    )
    await session.commit()

    await _broadcast(
        principal,
        "inventory.purchase_received",
        {"purchase_order_id": str(order.id), "reference": order.reference, "status": order.status},
    )
    return APIResponse(data=ProcurementService.describe(order))


# --------------------------------------------------------------------------- #
# Automation
# --------------------------------------------------------------------------- #
@router.get("/inventory/automation", summary="Automation runs")
async def automation_runs(
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    status: Annotated[str | None, Query()] = None,
    correlation_id: Annotated[str | None, Query()] = None,
    principal: Principal = Depends(require_permission(Permission.AUTOMATION_VIEW)),
) -> APIResponse[Paginated[dict]]:
    filters = [AutomationRun.merchant_id == principal.merchant_id]
    if status:
        filters.append(AutomationRun.status == status)
    if correlation_id:
        filters.append(AutomationRun.correlation_id == correlation_id)

    total = (
        await session.execute(
            select(func.count()).select_from(AutomationRun).where(*filters)
        )
    ).scalar_one()
    rows = list(
        (
            await session.execute(
                select(AutomationRun)
                .where(*filters)
                .order_by(AutomationRun.started_at.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        ).scalars().all()
    )
    return APIResponse(
        data=Paginated(
            items=[
                {
                    "id": str(r.id),
                    "workflow_name": r.workflow_name,
                    "status": r.status,
                    "correlation_id": r.correlation_id,
                    "n8n_execution_id": r.n8n_execution_id,
                    "trigger_event_type": r.trigger_event_type,
                    "entity_type": r.entity_type,
                    "entity_id": str(r.entity_id) if r.entity_id else None,
                    "steps": r.steps or [],
                    "error": r.error,
                    "is_dry_run": bool(r.is_dry_run),
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                }
                for r in rows
            ],
            pagination=PageMeta.build(page=page, page_size=page_size, total=int(total)),
        ),
        meta={"n8n_base_url": settings.n8n_base_url},
    )


@router.get("/inventory/trace/{correlation_id}", summary="One automation chain")
async def trace(
    correlation_id: str,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.AUTOMATION_VIEW)),
) -> APIResponse[dict]:
    """Every record sharing one correlation id, in order.

    This is what makes an automated decision inspectable: the event that started
    it, the workflow that ran, and the ledger rows it produced, all in one place.
    """
    scope = lambda model: model.merchant_id == principal.merchant_id  # noqa: E731

    events = list(
        (
            await session.execute(
                select(DomainEvent)
                .where(scope(DomainEvent), DomainEvent.correlation_id == correlation_id)
                .order_by(DomainEvent.created_at)
            )
        ).scalars().all()
    )
    runs = list(
        (
            await session.execute(
                select(AutomationRun)
                .where(scope(AutomationRun), AutomationRun.correlation_id == correlation_id)
                .order_by(AutomationRun.started_at)
            )
        ).scalars().all()
    )
    movements = list(
        (
            await session.execute(
                select(InventoryMovement)
                .where(
                    scope(InventoryMovement),
                    InventoryMovement.correlation_id == correlation_id,
                )
                .order_by(InventoryMovement.created_at)
            )
        ).scalars().all()
    )
    orders = list(
        (
            await session.execute(
                select(PurchaseOrder)
                .where(scope(PurchaseOrder), PurchaseOrder.correlation_id == correlation_id)
                .order_by(PurchaseOrder.created_at)
            )
        ).scalars().all()
    )

    if not (events or runs or movements or orders):
        raise NotFoundError("No automation trace for that correlation id.")

    return APIResponse(
        data={
            "correlation_id": correlation_id,
            "events": [
                {
                    "id": str(e.id),
                    "event_type": e.event_type,
                    "delivery_status": e.delivery_status,
                    "attempts": e.attempts,
                    "at": e.created_at.isoformat() if e.created_at else None,
                    "payload": e.payload,
                }
                for e in events
            ],
            "runs": [
                {
                    "id": str(r.id),
                    "workflow_name": r.workflow_name,
                    "status": r.status,
                    "steps": r.steps or [],
                    "n8n_execution_id": r.n8n_execution_id,
                }
                for r in runs
            ],
            "movements": [
                {
                    "id": str(m.id),
                    "movement_type": m.movement_type,
                    "quantity": float(m.quantity),
                    "balance_after": float(m.balance_after),
                    "at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in movements
            ],
            "purchase_orders": [ProcurementService.describe(o) for o in orders],
        }
    )


@router.post("/inventory/items/{item_id}/reorder", summary="Force a replenishment run")
async def force_reorder(
    item_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PURCHASE_ORDER_CREATE)),
) -> APIResponse[dict]:
    """Manual override: run the same engine the automation runs, on demand."""
    automation = InventoryAutomation(session, principal.merchant_id)
    result = await automation.replenish(inventory_item_id=item_id, force=True)
    await session.commit()

    await _broadcast(
        principal,
        "inventory.reorder_started",
        {"inventory_item_id": str(item_id), **result.as_dict()},
    )
    return APIResponse(data=result.as_dict())


@router.post("/inventory/automation/dispatch", summary="Flush the event outbox")
async def dispatch_events(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.AUTOMATION_MANAGE)),
) -> APIResponse[dict]:
    """Deliver pending events to n8n now, rather than waiting for the sweeper."""
    return APIResponse(data=await event_bus.dispatch_pending(session))


# --------------------------------------------------------------------------- #
# n8n webhook
# --------------------------------------------------------------------------- #
@router.post(
    "/webhooks/n8n/inventory-event",
    summary="n8n callback",
    include_in_schema=False,
)
@router.post(
    # The signed callback is no longer inventory-only. Both paths reach the same
    # handler so existing workflows keep working.
    "/webhooks/n8n/event",
    summary="n8n callback",
    include_in_schema=False,
)
async def n8n_callback(request: Request, session: DbSession) -> APIResponse[dict]:
    """Where n8n asks the backend to act on an event it routed.

    HMAC-signed and fails closed. n8n gets a decision, never a database handle -
    the business rules stay on this side of the wire.
    """
    body = await request.body()
    if not event_bus.verify(body, request.headers.get("X-Signature")):
        raise AuthenticationError("Invalid webhook signature.")

    try:
        message = json.loads(body or b"{}")
    except json.JSONDecodeError as exc:
        raise BadRequestError("Malformed webhook payload.") from exc

    action = str(message.get("action") or "")
    merchant_id = message.get("merchant_id")
    if not merchant_id:
        raise BadRequestError("merchant_id is required.")
    merchant_uuid = uuid.UUID(str(merchant_id))

    automation = InventoryAutomation(session, merchant_uuid)
    execution_id = str(message.get("n8n_execution_id") or "")

    if action == "replenish":
        item_id = message.get("inventory_item_id")
        if not item_id:
            raise BadRequestError("inventory_item_id is required for replenish.")
        event_id = message.get("event_id")
        result = await automation.replenish(
            inventory_item_id=uuid.UUID(str(item_id)),
            event_id=uuid.UUID(str(event_id)) if event_id else None,
            correlation_id=message.get("correlation_id"),
            n8n_execution_id=execution_id,
        )
        await session.commit()
        await hub.publish(
            merchant_id=merchant_uuid,
            event="inventory.workflow_completed",
            payload={"action": action, **result.as_dict()},
        )
        return APIResponse(data=result.as_dict())

    if action == "sweep_aging":
        result = await automation.sweep_aging(n8n_execution_id=execution_id)
        await session.commit()
        await hub.publish(
            merchant_id=merchant_uuid, event="inventory.aging", payload=result
        )
        return APIResponse(data=result)

    if action == "reconcile":
        result = await automation.reconcile(n8n_execution_id=execution_id)
        await session.commit()
        await hub.publish(
            merchant_id=merchant_uuid, event="inventory.reconciled", payload=result
        )
        return APIResponse(data=result)

    if action == "detect_opportunities":
        # Growth, not inventory - but it arrives through the same signed door,
        # and the detector is deterministic, so a nightly scan costs no tokens.
        days = int(message.get("days") or 30)
        detector = OpportunityDetector(session, merchant_uuid)
        found = await detector.detect_and_store(days=days)
        await session.commit()
        summary = {
            "detected": len(found),
            "days": days,
            "titles": [getattr(item, "title", "") for item in found[:5]],
        }
        await hub.publish(
            merchant_id=merchant_uuid,
            event="growth.opportunities_detected",
            payload=summary,
        )
        log.info(
            "opportunities_detected_by_schedule",
            merchant_id=str(merchant_uuid),
            detected=len(found),
            n8n_execution_id=execution_id,
        )
        return APIResponse(data=summary)

    raise BadRequestError(f"Unknown action '{action}'.")


# --------------------------------------------------------------------------- #
# Realtime
# --------------------------------------------------------------------------- #
@router.websocket("/inventory/stream")
async def inventory_stream(websocket: WebSocket, token: str = Query(default="")) -> None:
    """Live inventory for one merchant.

    The browser cannot set headers on a websocket, so the access token arrives as
    a query parameter and is verified here before the socket is accepted. The
    resolved permission set then filters every frame - a viewer without
    `inventory:value_read` is never sent a valuation, rather than being shown one
    the UI hides.
    """
    if not token:
        log.info("realtime_rejected", reason="missing_token")
        await websocket.close(code=4401)
        return

    try:
        payload = decode_token(token)
        async with SessionLocal() as session:
            user = await UserRepository(session).get_with_memberships(
                uuid.UUID(payload.subject)
            )
            if user is None or not user.is_active:
                log.info("realtime_rejected", reason="unknown_or_inactive_user")
                await websocket.close(code=4401)
                return

            memberships = MembershipRepository(session)
            merchant_uuid = uuid.UUID(payload.merchant_id) if payload.merchant_id else None
            membership = (
                await memberships.get_for_user_and_merchant(user.id, merchant_uuid)
                if merchant_uuid
                else await memberships.default_for_user(user.id)
            )
            if membership is None:
                log.info(
                    "realtime_rejected",
                    reason="no_membership",
                    user_id=str(user.id),
                    merchant_id=payload.merchant_id or "<default>",
                )
                await websocket.close(code=4403)
                return

            permissions = await CustomRoleRepository(session).permissions_for(
                membership.merchant_id, membership.role
            )
    except Exception as exc:
        # Almost always an expired or malformed token, but a database failure
        # lands here too - name which, or this is undiagnosable from the logs.
        # Uvicorn reports every pre-accept close as a bare HTTP 403.
        log.info(
            "realtime_rejected",
            reason="token_or_lookup_failed",
            detail=f"{type(exc).__name__}: {exc}"[:160],
        )
        await websocket.close(code=4401)
        return

    if str(Permission.INVENTORY_READ) not in permissions:
        log.info(
            "realtime_rejected",
            reason="missing_permission",
            required=str(Permission.INVENTORY_READ),
            user_id=str(user.id),
            merchant_id=str(membership.merchant_id),
        )
        await websocket.close(code=4403)
        return

    connection = await hub.connect(
        websocket,
        merchant_id=membership.merchant_id,
        user_id=user.id,
        permissions=permissions,
    )
    try:
        await websocket.send_json(
            {
                "event": "connected",
                "merchant_id": str(membership.merchant_id),
                "at": datetime.now(tz=UTC).isoformat(),
                "payload": {"message": "Subscribed to inventory updates."},
            }
        )
        while True:
            # The client only sends keepalives; everything meaningful is pushed.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.info("realtime_socket_closed", detail=str(exc)[:160])
    finally:
        await hub.disconnect(connection)

# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
@router.get("/inventory/book", summary="Inventory book")
async def inventory_book(
    session: DbSession,
    start: Annotated[str | None, Query()] = None,
    end: Annotated[str | None, Query()] = None,
    principal: Principal = Depends(require_permission(Permission.INVENTORY_LEDGER_READ)),
) -> APIResponse[list[dict]]:
    """Opening, movements and closing per SKU, derived from the ledger."""
    from datetime import date as _date
    from datetime import timedelta as _td

    end_date = _date.fromisoformat(end) if end else _date.today()
    start_date = _date.fromisoformat(start) if start else end_date - _td(days=30)
    reports = InventoryReports(session, principal.merchant_id)
    rows = await reports.stock_book(start=start_date, end=end_date)

    if not principal.has(Permission.INVENTORY_VALUE_READ):
        rows = [{k: v for k, v in row.items() if k not in ("unit_cost", "value")} for row in rows]

    return APIResponse(
        data=rows,
        meta={"start": str(start_date), "end": str(end_date), "skus": len(rows)},
    )


@router.get("/inventory/book/export", summary="Export the inventory book to Excel")
async def export_book(
    session: DbSession,
    start: Annotated[str | None, Query()] = None,
    end: Annotated[str | None, Query()] = None,
    principal: Principal = Depends(require_permission(Permission.INVENTORY_REPORTS_EXPORT)),
) -> StreamingResponse:
    """A multi-sheet workbook.

    Valuation columns are omitted entirely for a user without
    `inventory:value_read` - an export must not hand over what the UI withholds.
    """
    from datetime import date as _date
    from datetime import timedelta as _td

    end_date = _date.fromisoformat(end) if end else _date.today()
    start_date = _date.fromisoformat(start) if start else end_date - _td(days=30)

    reports = InventoryReports(session, principal.merchant_id)
    payload = await reports.workbook(
        merchant_name=principal.merchant.name,
        generated_by=principal.label,
        start=start_date,
        end=end_date,
        include_value=principal.has(Permission.INVENTORY_VALUE_READ),
    )

    await AuditLogRepository(session).record(
        merchant_id=principal.merchant_id,
        action="inventory.export",
        actor_id=principal.user_id,
        actor_label=principal.label,
        resource="inventory",
        description=f"Exported the inventory book for {start_date} to {end_date}.",
    )
    await session.commit()

    filename = f"inventory_book_{start_date}_{end_date}.xlsx"
    return StreamingResponse(
        io.BytesIO(payload),
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
