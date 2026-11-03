"""Repository base classes.

All database access lives behind a repository - API handlers never build queries.
``MerchantScopedRepository`` makes tenant isolation structural rather than a thing
each caller has to remember: every read and write is filtered by ``merchant_id``,
and a cross-tenant fetch returns nothing instead of another merchant's row.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.base_class import Base

TModel = TypeVar("TModel", bound=Base)


class BaseRepository(Generic[TModel]):
    """CRUD for a model with no tenant dimension (users, roles, permissions)."""

    model: type[TModel]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ reads
    async def get(self, entity_id: uuid.UUID | str) -> TModel | None:
        return await self.session.get(self.model, _as_uuid(entity_id))

    async def get_or_404(self, entity_id: uuid.UUID | str, *, label: str | None = None) -> TModel:
        entity = await self.get(entity_id)
        if entity is None:
            raise NotFoundError(f"{label or self.model.__name__} not found.")
        return entity

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[TModel]:
        result = await self.session.execute(select(self.model).limit(limit).offset(offset))
        return list(result.scalars().all())

    async def count(self, *conditions: Any) -> int:
        stmt = select(func.count()).select_from(self.model)
        if conditions:
            stmt = stmt.where(*conditions)
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    # ------------------------------------------------------------------ writes
    def add(self, entity: TModel) -> TModel:
        self.session.add(entity)
        return entity

    def add_all(self, entities: Sequence[TModel]) -> Sequence[TModel]:
        self.session.add_all(list(entities))
        return entities

    async def create(self, **values: Any) -> TModel:
        entity = self.model(**values)
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update(self, entity: TModel, **values: Any) -> TModel:
        for key, value in values.items():
            if value is not None or key in getattr(entity, "_nullable_updates", ()):
                setattr(entity, key, value)
        await self.session.flush()
        return entity

    async def delete(self, entity: TModel) -> None:
        await self.session.delete(entity)
        await self.session.flush()

    async def flush(self) -> None:
        await self.session.flush()


class MerchantScopedRepository(BaseRepository[TModel]):
    """CRUD for a tenant-owned model. Every query is bound to one merchant."""

    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID | str) -> None:
        super().__init__(session)
        self.merchant_id = _as_uuid(merchant_id)

    # ------------------------------------------------------------------ helpers
    def scoped(self, stmt: Select[Any] | None = None) -> Select[Any]:
        """Start (or constrain) a SELECT that is already filtered to this merchant."""
        base = stmt if stmt is not None else select(self.model)
        return base.where(self.model.merchant_id == self.merchant_id)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ reads
    async def get(self, entity_id: uuid.UUID | str) -> TModel | None:
        """Scoped fetch: a row belonging to another merchant is simply not found."""
        stmt = self.scoped().where(self.model.id == _as_uuid(entity_id))  # type: ignore[attr-defined]
        return (await self.session.execute(stmt)).scalars().first()

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[TModel]:
        stmt = self.scoped().limit(limit).offset(offset)
        return list((await self.session.execute(stmt)).scalars().all())

    async def count(self, *conditions: Any) -> int:
        stmt = (
            select(func.count())
            .select_from(self.model)
            .where(
                self.model.merchant_id == self.merchant_id  # type: ignore[attr-defined]
            )
        )
        if conditions:
            stmt = stmt.where(*conditions)
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    async def exists(self, *conditions: Any) -> bool:
        return await self.count(*conditions) > 0

    # ------------------------------------------------------------------ writes
    async def create(self, **values: Any) -> TModel:
        values.setdefault("merchant_id", self.merchant_id)
        # A caller must never be able to write into another tenant.
        values["merchant_id"] = self.merchant_id
        return await super().create(**values)

    async def delete_all(self) -> int:
        stmt = delete(self.model).where(self.model.merchant_id == self.merchant_id)  # type: ignore[attr-defined]
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
