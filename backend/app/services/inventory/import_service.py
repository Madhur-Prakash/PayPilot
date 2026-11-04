"""Bulk inventory import: spreadsheet -> validated rows -> created/updated items.

Three stages, all in this one module so the exact same validation logic backs
both the preview a merchant reviews and the commit that actually writes rows -
nothing here can drift between "what you approved" and "what happened".

  1. ``parse_upload``    - .xlsx/.csv bytes -> headers + raw string rows.
  2. ``suggest_mapping``  - fuzzy header -> target-field matching. This is the
                            "auto-fill the fields" step: pure string
                            normalisation and a greedy highest-score-first
                            assignment, not a trained model - "Item Code"
                            finds ``sku`` and "Reorder Level" finds
                            ``reorder_point`` without the merchant typing
                            either by hand, and it's auditable: you can read
                            exactly why a column matched.
  3. ``validate_rows``    - the mapping applied to every row: typed, checked
                            against the merchant's existing catalogue by SKU,
                            and classified as a create or an update.

Nothing here writes to the database - ``commit_rows`` (bottom of the file)
is the only function that does, and only ever on rows ``validate_rows``
already passed.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.inventory import MovementType

if TYPE_CHECKING:
    from app.repositories.product import InventoryRepository, ProductRepository
    from app.services.inventory.stock import StockEngine

log = get_logger(__name__)

#: Row errors are capped in the commit outcome so one badly-shaped file can't
#: balloon the response - the count is still exact, only the detail list isn't.
MAX_REPORTED_ROW_ERRORS = 50


# --------------------------------------------------------------------------- #
# Field catalogue
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ImportField:
    key: str
    label: str
    dtype: str  # "string" | "number" | "boolean"
    description: str
    required: bool = False
    max_length: int | None = None
    default: Any = None
    aliases: tuple[str, ...] = ()


#: What a row can set. ``price`` has no blanket ``required=True`` because it's
#: only needed the first time a SKU is seen - `validate_rows` enforces that
#: conditionally, since a plain "required" flag can't express it.
IMPORT_FIELDS: list[ImportField] = [
    ImportField(
        "sku", "SKU", "string",
        "Unique product code. A SKU already in your catalogue updates that item; a new one creates it.",
        required=True, max_length=64, aliases=("item code", "product code", "code"),
    ),
    ImportField(
        "product_name", "Product name", "string", "What the item is called.",
        required=True, max_length=160, aliases=("name", "item name", "product", "title", "description"),
    ),
    ImportField(
        "category", "Category", "string",
        "Grouping shown in Products. Only used when creating a new product.",
        max_length=64, default="general", aliases=("type", "group"),
    ),
    ImportField(
        "unit", "Unit", "string", "units, kg, litres…",
        max_length=24, default="units", aliases=("uom", "unit of measure"),
    ),
    ImportField(
        "price", "Selling price", "number",
        "Required the first time a SKU appears, to create the product. Ignored for an existing one.",
        aliases=("selling price", "mrp", "sale price"),
    ),
    ImportField(
        "unit_cost", "Unit cost", "number", "What you pay per unit.",
        default=0.0, aliases=("cost", "cost price", "purchase price"),
    ),
    ImportField(
        "quantity_on_hand", "Opening stock", "number",
        "Only applied when creating a new item, as a RESTOCK movement - never silently "
        "overwrites an existing item's count. Use Adjust Stock on the inventory page for that.",
        default=0.0, aliases=("quantity", "qty", "stock", "on hand", "opening stock", "current stock"),
    ),
    ImportField(
        "reorder_point", "Reorder point", "number", "Stock level that triggers a reorder.",
        default=0.0, aliases=("reorder level", "rop", "trigger point"),
    ),
    ImportField(
        "reorder_quantity", "Reorder quantity", "number", "How much to order each time.",
        default=0.0, aliases=("reorder qty", "order quantity", "eoq"),
    ),
    ImportField(
        "lead_time_days", "Lead time (days)", "number", "Days from order to delivery.",
        default=2.0, aliases=("lead time", "delivery days"),
    ),
    ImportField(
        "minimum_stock", "Minimum stock", "number", "Safety stock floor.",
        default=0.0, aliases=("min stock", "safety stock"),
    ),
    ImportField(
        "maximum_stock", "Maximum stock", "number", "Target ceiling for the TARGET_MAX_STOCK strategy.",
        default=0.0, aliases=("max stock", "target stock"),
    ),
    ImportField(
        "supplier", "Supplier", "string", "Free-text vendor name.",
        max_length=160, default="", aliases=("vendor", "vendor name"),
    ),
]

FIELDS_BY_KEY: dict[str, ImportField] = {f.key: f for f in IMPORT_FIELDS}

#: Item fields an *update* row is allowed to touch. Deliberately excludes
#: `quantity_on_hand` (see the field's description above), `sku` (identity,
#: not editable by re-import) and `category`/`price` (product-level, and
#: changing a live product's price from a stock sheet is a footgun, not a
#: feature - use Products for that).
UPDATABLE_ITEM_FIELDS = (
    "product_name", "unit", "unit_cost", "reorder_point", "reorder_quantity",
    "lead_time_days", "minimum_stock", "maximum_stock", "supplier",
)


# --------------------------------------------------------------------------- #
# 1. Parse
# --------------------------------------------------------------------------- #
@dataclass
class ParsedSheet:
    headers: list[str]
    rows: list[dict[str, str]]  # header -> raw string value ("" if blank)


class ImportParseError(ValueError):
    """The upload wasn't a readable spreadsheet. Message is shown to the user."""


def parse_upload(filename: str, content: bytes) -> ParsedSheet:
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        return _parse_xlsx(content)
    if name.endswith(".xls"):
        raise ImportParseError(
            "The old .xls format isn't supported - re-save it as .xlsx or .csv first."
        )
    return _parse_csv(content)


def _parse_xlsx(content: bytes) -> ParsedSheet:
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise ImportParseError("Could not read that file as an Excel workbook.") from exc
    try:
        sheet = workbook.active
        if sheet is None:
            raise ImportParseError("The workbook has no sheets.")
        rows_iter = sheet.iter_rows(values_only=True)
        try:
            header_row = next(rows_iter)
        except StopIteration as exc:
            raise ImportParseError("The sheet is empty.") from exc
        headers = _dedupe([_clean_header(cell, idx) for idx, cell in enumerate(header_row)])
        rows: list[dict[str, str]] = []
        for raw in rows_iter:
            if raw is None or all(cell is None or str(cell).strip() == "" for cell in raw):
                continue
            rows.append(
                {
                    headers[i]: ("" if i >= len(raw) or raw[i] is None else str(raw[i]).strip())
                    for i in range(len(headers))
                }
            )
        return ParsedSheet(headers=headers, rows=rows)
    finally:
        workbook.close()


def _parse_csv(content: bytes) -> ParsedSheet:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    reader = csv.reader(io.StringIO(text))
    try:
        header_row = next(reader)
    except StopIteration as exc:
        raise ImportParseError("The file is empty.") from exc
    headers = _dedupe([_clean_header(cell, idx) for idx, cell in enumerate(header_row)])
    rows: list[dict[str, str]] = []
    for raw in reader:
        if not raw or all(not str(cell).strip() for cell in raw):
            continue
        rows.append({headers[i]: (raw[i].strip() if i < len(raw) else "") for i in range(len(headers))})
    return ParsedSheet(headers=headers, rows=rows)


def _clean_header(cell: Any, idx: int) -> str:
    text = "" if cell is None else str(cell).strip()
    return text or f"Column {idx + 1}"


def _dedupe(headers: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result = []
    for h in headers:
        seen[h] = seen.get(h, 0) + 1
        result.append(h if seen[h] == 1 else f"{h} ({seen[h]})")
    return result


# --------------------------------------------------------------------------- #
# 2. Type inference + mapping suggestion
# --------------------------------------------------------------------------- #
_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")
_BOOL_TRUE = {"true", "yes", "y", "1"}
_BOOL_FALSE = {"false", "no", "n", "0"}


def normalize(text: str) -> str:
    return _NORMALIZE_RE.sub(" ", text.lower()).strip()


def infer_type(values: list[str]) -> str:
    """A per-column hint for the UI ('this looks numeric') - not used to reject
    anything by itself; `_coerce` is what actually validates a mapped cell."""
    sample = [v for v in values if v.strip()][:50]
    if not sample:
        return "string"
    if all(v.strip().lower() in _BOOL_TRUE | _BOOL_FALSE for v in sample):
        return "boolean"
    if all(_is_number(v) for v in sample):
        return "number"
    return "string"


def _is_number(v: str) -> bool:
    try:
        float(v.strip().replace(",", ""))
        return True
    except ValueError:
        return False


def suggest_mapping(headers: list[str]) -> dict[str, str | None]:
    """Best-effort header -> field assignment.

    Scores every (field, header) pair by exact/substring/token-overlap match
    against the field's label, key and aliases, then assigns greedily from the
    highest score down, each side used at most once - a small local search,
    not a classifier, which is why it's inspectable and never "confidently"
    wrong in a way nobody can explain.
    """
    scored: list[tuple[int, str, str]] = []  # (score, field_key, header)
    for header in headers:
        norm_header = normalize(header)
        if not norm_header:
            continue
        header_tokens = set(norm_header.split())
        for f in IMPORT_FIELDS:
            phrases = {f.label, f.key.replace("_", " "), *f.aliases}
            best = 0
            for phrase in phrases:
                norm_phrase = normalize(phrase)
                if not norm_phrase:
                    continue
                if norm_header == norm_phrase:
                    best = max(best, 100)
                elif norm_phrase in norm_header or norm_header in norm_phrase:
                    best = max(best, 80)
                else:
                    phrase_tokens = set(norm_phrase.split())
                    union = header_tokens | phrase_tokens
                    if union:
                        overlap = len(header_tokens & phrase_tokens) / len(union)
                        if overlap >= 0.5:
                            best = max(best, int(60 * overlap))
            if best:
                scored.append((best, f.key, header))

    scored.sort(key=lambda t: t[0], reverse=True)
    mapping: dict[str, str | None] = {f.key: None for f in IMPORT_FIELDS}
    used_headers: set[str] = set()
    for _score, field_key, header in scored:
        if mapping[field_key] is not None or header in used_headers:
            continue
        mapping[field_key] = header
        used_headers.add(header)
    return mapping


# --------------------------------------------------------------------------- #
# 3. Validate
# --------------------------------------------------------------------------- #
@dataclass
class ValidatedRow:
    row_number: int  # 1-based, matching the spreadsheet (header is row 1)
    action: str  # "create" | "update"
    sku: str
    #: Only fields the sheet actually provided a value for. A create fills the
    #: rest from `ImportField.default` at commit time; an update leaves the
    #: rest of the existing item alone - this dict is never defaulted itself,
    #: or "update" would silently zero out everything the sheet didn't mention.
    values: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_rows(
    sheet: ParsedSheet, mapping: dict[str, str | None], *, existing_skus: set[str]
) -> list[ValidatedRow]:
    seen_skus: set[str] = set()
    return [
        _validate_one(raw, mapping, idx + 2, existing_skus, seen_skus)
        for idx, raw in enumerate(sheet.rows)
    ]


def _validate_one(
    raw: dict[str, str],
    mapping: dict[str, str | None],
    row_number: int,
    existing_skus: set[str],
    seen_skus: set[str],
) -> ValidatedRow:
    values: dict[str, Any] = {}
    provided: set[str] = set()
    errors: list[str] = []

    for f in IMPORT_FIELDS:
        header = mapping.get(f.key)
        raw_value = raw.get(header, "") if header else ""
        parsed, err = _coerce(raw_value, f)
        if err:
            errors.append(f"{f.label}: {err}")
            continue
        if parsed is None:
            if f.required:
                errors.append(f"{f.label} is required.")
            continue
        values[f.key] = parsed
        provided.add(f.key)

    sku = str(values.get("sku") or "").strip()
    if sku:
        if sku in seen_skus:
            errors.append(f"Duplicate SKU '{sku}' elsewhere in this file.")
        seen_skus.add(sku)

    action = "update" if sku in existing_skus else "create"
    if action == "create" and "price" not in provided:
        errors.append("Selling price is required to create a new product.")

    return ValidatedRow(row_number=row_number, action=action, sku=sku, values=values, errors=errors)


def _coerce(raw_value: str, f: ImportField) -> tuple[Any, str | None]:
    text = (raw_value or "").strip()
    if not text:
        return None, None
    if f.dtype == "string":
        if f.max_length and len(text) > f.max_length:
            return None, f"too long (max {f.max_length} characters)"
        return text, None
    if f.dtype == "number":
        cleaned = text.replace(",", "").replace("$", "").replace("₹", "").replace("Rs.", "").strip()
        try:
            number = float(cleaned)
        except ValueError:
            return None, f"'{text}' is not a number"
        if number < 0:
            return None, "cannot be negative"
        return number, None
    if f.dtype == "boolean":
        lowered = text.lower()
        if lowered in _BOOL_TRUE:
            return True, None
        if lowered in _BOOL_FALSE:
            return False, None
        return None, f"'{text}' is not yes/no"
    return text, None  # pragma: no cover - every field above has a known dtype


# --------------------------------------------------------------------------- #
# 4. Commit
# --------------------------------------------------------------------------- #
@dataclass
class ImportOutcome:
    total_rows: int
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    row_errors: list[dict[str, Any]] = field(default_factory=list)


async def commit_rows(
    session: AsyncSession,
    *,
    merchant_id: uuid.UUID,
    rows: list[ValidatedRow],
    actor_id: uuid.UUID,
) -> ImportOutcome:
    """Writes every row that passed validation. Rows that didn't are counted
    as skipped, not retried or partially applied - the merchant already saw
    them flagged in the preview."""
    # Imported here, not at module load: avoids a circular import with
    # `app.api.v1.inventory`, which imports this module.
    from app.repositories.product import InventoryRepository, ProductRepository
    from app.services.inventory.stock import StockEngine

    products = ProductRepository(session, merchant_id)
    items = InventoryRepository(session, merchant_id)
    engine = StockEngine(session, merchant_id)

    outcome = ImportOutcome(total_rows=len(rows))
    for row in rows:
        if not row.ok:
            outcome.skipped += 1
            continue
        try:
            if row.action == "create":
                await _create_row(products, items, engine, row, actor_id)
                outcome.created += 1
            else:
                await _update_row(products, items, row)
                outcome.updated += 1
        except Exception as exc:  # one bad row must not sink the whole import
            log.warning(
                "inventory_import_row_failed", row=row.row_number, sku=row.sku, detail=str(exc)[:200]
            )
            outcome.failed += 1
            if len(outcome.row_errors) < MAX_REPORTED_ROW_ERRORS:
                outcome.row_errors.append(
                    {"row_number": row.row_number, "sku": row.sku, "message": str(exc)[:200]}
                )

    return outcome


def _default(row: ValidatedRow, key: str) -> Any:
    return row.values.get(key, FIELDS_BY_KEY[key].default)


async def _create_row(
    products: ProductRepository,
    items: InventoryRepository,
    engine: StockEngine,
    row: ValidatedRow,
    actor_id: uuid.UUID,
) -> None:
    from app.services.inventory.stock import StockEngine

    product = await products.create(
        sku=row.sku,
        name=row.values["product_name"],
        category=_default(row, "category"),
        price=float(row.values["price"]),
        cost_price=float(_default(row, "unit_cost")),
    )
    item = await items.create(
        product_id=product.id,
        product_name=row.values["product_name"],
        sku=row.sku,
        unit=_default(row, "unit"),
        unit_cost=float(_default(row, "unit_cost")),
        reorder_point=float(_default(row, "reorder_point")),
        reorder_quantity=float(_default(row, "reorder_quantity")),
        lead_time_days=float(_default(row, "lead_time_days")),
        minimum_stock=float(_default(row, "minimum_stock")),
        maximum_stock=float(_default(row, "maximum_stock")),
        supplier=_default(row, "supplier"),
    )
    item.status = StockEngine.derive_status(item)
    await items.flush()

    opening = float(row.values.get("quantity_on_hand") or 0)
    if opening > 0:
        await engine.apply(
            item_id=item.id,
            movement_type=MovementType.RESTOCK,
            quantity=opening,
            note="Bulk import — opening balance",
            actor_type="USER",
            actor_id=actor_id,
            source="import",
        )


async def _update_row(products: ProductRepository, items: InventoryRepository, row: ValidatedRow) -> None:
    from app.services.inventory.stock import StockEngine

    product = await products.get_by_sku(row.sku)
    if product is None:
        raise ValueError(f"SKU '{row.sku}' vanished mid-import.")

    item = await items.get_by_product(product.id)
    if item is None:
        # The product exists but was never tracked as an inventory item -
        # this import is what starts tracking it, at zero stock.
        item = await items.create(
            product_id=product.id,
            product_name=row.values.get("product_name") or product.name,
            sku=row.sku,
            unit=_default(row, "unit"),
        )

    for key in UPDATABLE_ITEM_FIELDS:
        if key in row.values:
            setattr(item, key, row.values[key])

    item.status = StockEngine.derive_status(item)
    await items.flush()
