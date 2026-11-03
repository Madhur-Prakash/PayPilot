"""Portable column types.

Postgres is the production database (UUID / JSONB / pgvector). The test suite runs
on SQLite so the whole RBAC + tenant-isolation surface can be exercised without a
container. These decorators keep one model definition working on both.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import CHAR, DateTime, Text, TypeDecorator
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Dialect

from app.core.config import settings

__all__ = [
    "GUID",
    "JSONB",
    "VECTOR_DIMENSIONS",
    "StringArray",
    "UTCDateTime",
    "Vector",
    "new_uuid",
]

VECTOR_DIMENSIONS = settings.embedding_dimensions


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class GUID(TypeDecorator):
    """UUID on Postgres, 36-char string elsewhere. Always yields ``uuid.UUID``."""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        return value if dialect.name == "postgresql" else str(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> uuid.UUID | None:
        if value is None:
            return None
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class UTCDateTime(TypeDecorator):
    """Timestamp that is always timezone-aware UTC on the way out.

    Postgres round-trips ``TIMESTAMPTZ`` as aware datetimes; SQLite drops the
    offset and hands back naive ones. Comparing the two raises TypeError, so
    without this the same code would work in production and fail on SQLite (or,
    worse, compare wrongly). Normalising in the type keeps every call site free
    of defensive tzinfo checks.
    """

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class JSONB(TypeDecorator):
    """JSONB on Postgres, JSON-encoded TEXT elsewhere."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.JSONB(astext_type=Text()))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return json.dumps(value, default=str)

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value


class StringArray(TypeDecorator):
    """text[] on Postgres, JSON list elsewhere."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.ARRAY(Text()))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        items = [str(v) for v in value]
        return items if dialect.name == "postgresql" else json.dumps(items)

    def process_result_value(self, value: Any, dialect: Dialect) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v) for v in value]
        try:
            return list(json.loads(value))
        except (TypeError, ValueError):
            return []


class Vector(TypeDecorator):
    """pgvector column on Postgres, JSON list elsewhere.

    Degrading to JSON keeps the schema loadable when pgvector is unavailable;
    similarity search then falls back to in-Python cosine (see EmbeddingService).
    """

    impl = Text
    cache_ok = True

    def __init__(self, dimensions: int = VECTOR_DIMENSIONS) -> None:
        self.dimensions = dimensions
        super().__init__()

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            try:
                from pgvector.sqlalchemy import Vector as PGVector

                return dialect.type_descriptor(PGVector(self.dimensions))
            except Exception:  # pragma: no cover - pgvector always present in prod
                return dialect.type_descriptor(Text())
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        floats = [float(v) for v in value]
        if dialect.name == "postgresql":
            try:
                import pgvector.sqlalchemy  # noqa: F401

                return floats
            except Exception:  # pragma: no cover
                return json.dumps(floats)
        return json.dumps(floats)

    def process_result_value(self, value: Any, dialect: Dialect) -> list[float] | None:
        if value is None:
            return None
        if isinstance(value, list | tuple):
            return [float(v) for v in value]
        if hasattr(value, "tolist"):
            return [float(v) for v in value.tolist()]
        try:
            return [float(v) for v in json.loads(value)]
        except (TypeError, ValueError):
            return None
