"""Agent memory: search it, add to it, erase it.

Memory is scoped to the caller's merchant at every entry point. None of these
handlers takes a dataset or a merchant id from the request - the scope comes from
the authenticated principal, so there is no parameter to tamper with.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from app.api.deps import Principal, require_permission
from app.core.exceptions import BadRequestError
from app.core.logging import get_logger
from app.core.permissions import Permission
from app.integrations.cognee_memory import MemoryKind, memory
from app.schemas.common import APIResponse, SchemaBase

log = get_logger(__name__)
router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryHitOut(SchemaBase):
    text: str
    source: str
    kind: str
    score: float | None = None


class MemorySearchOut(SchemaBase):
    query: str
    hits: list[MemoryHitOut]
    #: False when memory is switched off or unreachable, so the UI can say
    #: "memory is off" rather than "nothing found".
    available: bool


class RememberRequest(SchemaBase):
    text: str = Field(min_length=10, max_length=8000)
    kind: str = Field(default=str(MemoryKind.NOTE), max_length=32)
    tags: list[str] = Field(default_factory=list, max_length=8)


class ForgetRequest(SchemaBase):
    #: Deliberately explicit. Erasing memory is irreversible and there is no
    #: undo, so it cannot happen through an empty body by accident.
    confirm: bool = False


@router.get(
    "/status",
    summary="Is agent memory configured and reachable?",
)
async def memory_status(
    principal: Principal = Depends(require_permission(Permission.MEMORY_READ)),
) -> APIResponse[dict]:
    return APIResponse(data=await memory.status(principal.merchant_id))


@router.get(
    "/search",
    summary="Search what the agents have learned about this merchant",
    description=(
        "Natural-language search over long-term memory. Returns an empty result "
        "with available=false when memory is disabled, rather than an error - "
        "memory is an enhancement, and callers should not have to branch on it."
    ),
)
async def search_memory(
    q: Annotated[str, Query(min_length=2, max_length=500)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    kind: Annotated[str, Query(max_length=32)] = "",
    principal: Principal = Depends(require_permission(Permission.MEMORY_READ)),
) -> APIResponse[MemorySearchOut]:
    kinds = (kind,) if kind else ()
    hits = await memory.recall(principal.merchant_id, q, top_k=limit, kinds=kinds)
    return APIResponse(
        data=MemorySearchOut(
            query=q,
            hits=[MemoryHitOut(**hit.as_dict()) for hit in hits],
            available=memory.enabled,
        )
    )


@router.post(
    "/remember",
    summary="Teach the agents something",
    description=(
        "Writes a note into long-term memory for this merchant. Accepted and "
        "queued: building the knowledge graph runs an LLM pipeline, so it "
        "completes after the response."
    ),
)
async def remember(
    payload: RememberRequest,
    principal: Principal = Depends(require_permission(Permission.MEMORY_WRITE)),
) -> APIResponse[dict]:
    if not memory.enabled:
        raise BadRequestError(
            "Agent memory is disabled. Set MEMORY_ENABLED=true to turn it on."
        )

    valid = {str(k) for k in MemoryKind}
    if payload.kind not in valid:
        raise BadRequestError(f"kind must be one of: {', '.join(sorted(valid))}.")

    text = (
        f"{payload.text.strip()}\n\n"
        f"(Recorded by {principal.label or 'a user'} for {principal.merchant.name}.)"
    )
    memory.remember_later(
        principal.merchant_id,
        text,
        kind=payload.kind,
        tags=tuple(t[:48] for t in payload.tags),
    )
    log.info(
        "memory_note_queued",
        merchant_id=str(principal.merchant_id),
        kind=payload.kind,
        characters=len(text),
    )
    return APIResponse(data={"queued": True, "kind": payload.kind})


@router.delete(
    "",
    summary="Erase this merchant's agent memory",
    description="Irreversible. Requires confirm=true in the body.",
)
async def forget_everything(
    payload: ForgetRequest,
    principal: Principal = Depends(require_permission(Permission.MEMORY_ADMIN)),
) -> APIResponse[dict]:
    if not payload.confirm:
        raise BadRequestError("Set confirm=true to erase this merchant's memory.")

    removed = await memory.forget(principal.merchant_id)
    log.warning(
        "memory_erased",
        merchant_id=str(principal.merchant_id),
        actor=principal.label,
        succeeded=removed,
    )
    return APIResponse(data={"erased": removed})
