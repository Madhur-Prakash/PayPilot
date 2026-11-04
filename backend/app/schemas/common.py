"""Shared response envelope and primitives.

Every endpoint returns ``{"success": true, "data": ..., "meta": ...}`` so the
frontend's Axios interceptor can unwrap one shape everywhere.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")


class SchemaBase(BaseModel):
    model_config = ConfigDict(
        from_attributes=True, populate_by_name=True, str_strip_whitespace=True
    )


class Meta(SchemaBase):
    """Free-form response metadata (paging, period, provenance)."""

    model_config = ConfigDict(extra="allow", from_attributes=True)


class APIResponse(SchemaBase, Generic[T]):
    success: bool = True
    data: T | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class ErrorDetail(SchemaBase):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(SchemaBase):
    success: Literal[False] = False
    error: ErrorDetail
    request_id: str | None = None


class PageMeta(SchemaBase):
    page: int = 1
    page_size: int = 25
    total: int = 0
    total_pages: int = 0
    has_next: bool = False
    has_previous: bool = False

    @classmethod
    def build(cls, *, page: int, page_size: int, total: int) -> PageMeta:
        total_pages = (total + page_size - 1) // page_size if page_size else 0
        return cls(
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1,
        )


class Paginated(SchemaBase, Generic[T]):
    items: list[T] = Field(default_factory=list)
    pagination: PageMeta = Field(default_factory=PageMeta)


class PaginationParams(SchemaBase):
    page: int = Field(default=1, ge=1, le=10_000)
    page_size: int = Field(default=25, ge=1, le=200)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class DateRange(SchemaBase):
    """A closed [start, end] range plus its immediately preceding comparison window."""

    start: date
    end: date

    @model_validator(mode="after")
    def _ordered(self) -> DateRange:
        if self.start > self.end:
            raise ValueError("start must be on or before end")
        return self

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def previous(self) -> DateRange:
        from datetime import timedelta

        span = self.days
        prev_end = self.start - timedelta(days=1)
        return DateRange(start=prev_end - timedelta(days=span - 1), end=prev_end)


class TrendPoint(SchemaBase):
    date: date
    value: float
    label: str | None = None
    secondary_value: float | None = None


class MetricDelta(SchemaBase):
    """A metric with its comparison-window delta, pre-formatted for the UI."""

    key: str
    label: str
    value: float
    previous_value: float | None = None
    change_abs: float | None = None
    change_pct: float | None = None
    unit: Literal["currency", "number", "percent", "minutes", "ratio"] = "number"
    direction: Literal["UP_IS_GOOD", "DOWN_IS_GOOD", "NEUTRAL"] = "UP_IS_GOOD"
    is_anomaly: bool = False
    sample_size: int | None = None

    @property
    def is_improving(self) -> bool:
        if self.change_pct is None or self.direction == "NEUTRAL":
            return True
        return self.change_pct >= 0 if self.direction == "UP_IS_GOOD" else self.change_pct <= 0


class EvidenceItem(SchemaBase):
    """One traceable fact backing a hypothesis or recommendation."""

    metric: str
    value: str
    change: str | None = None
    source: str = "analytics"
    detail: str | None = None
    #: Where the number came from, so the UI can deep-link (e.g. "reviews?topic=waiting_time").
    reference: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class ProvenanceMeta(SchemaBase):
    """Honest labelling of where data came from. Rendered as a badge in the UI."""

    data_source: Literal["SEEDED", "LIVE", "SIMULATED", "PUBLIC_WEB"] = "SEEDED"
    is_simulated: bool = True
    note: str = "Seeded demo dataset - not computed from a live PayPal merchant account."


class ActionAck(SchemaBase):
    """Generic acknowledgement for mutations that do not return a resource."""

    ok: bool = True
    message: str = "Done."
    resource_id: str | None = None
