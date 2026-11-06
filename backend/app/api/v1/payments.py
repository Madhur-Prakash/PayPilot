"""Payment management: PayPal Orders v2 for approved, AI-proposed purchases.

* ``POST /payments/orders``   - create the PayPal order for an APPROVED ``MERCHANT_PURCHASE``
                                approval (``payment:execute``). Idempotent per approval; an
                                ``Idempotency-Key`` header is recorded for client retries.
* ``POST /payments/capture``  - capture after the payer approved in PayPal (``payment:execute``).
                                PayPal's order status is re-read first.
* ``GET  /payments/orders/{id}`` - the execution, the live PayPal order, its approval.
* ``GET  /payments/history``  - every PayPal money movement + open approvals (``paypal:read``).
* ``POST /payments/webhooks/paypal`` - the same verified, replay-guarded receiver as
                                ``/paypal/webhooks`` (register either URL with PayPal).

No agent can reach the create/capture routes: they need a signed-in person holding
``payment:execute``, and the approval they consume needs ``payment:approve``.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from app.api.deps import DbSession, Principal, require_permission
from app.core.exceptions import BadRequestError
from app.core.permissions import Permission
from app.schemas.common import APIResponse, SchemaBase
from app.services.paypal.orders import MerchantPaymentService
from app.services.paypal.webhooks import WebhookService
from app.services.supply.serializers import execution_out

router = APIRouter(prefix="/payments", tags=["payments"])


class CreateOrderRequest(SchemaBase):
    approval_id: uuid.UUID


class CaptureRequest(SchemaBase):
    execution_id: uuid.UUID


def _service(session: Any, principal: Principal) -> MerchantPaymentService:
    return MerchantPaymentService(session, principal.merchant_id, actor_id=principal.user_id,
                                  actor_label=principal.label, request_id=principal.request_id)


@router.post("/orders", summary="Create the PayPal order for an approved purchase (human only, idempotent)")
async def create_order(
    body: CreateOrderRequest, session: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=128)] = None,
    principal: Principal = Depends(require_permission(Permission.PAYMENT_EXECUTE)),
) -> APIResponse[dict[str, Any] | None]:
    execution = await _service(session, principal).create_order(body.approval_id, client_key=idempotency_key)
    return APIResponse(data=execution_out(execution), meta={"mode": execution.mode})


@router.post("/capture", summary="Capture a payer-approved PayPal order")
async def capture(
    body: CaptureRequest, session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PAYMENT_EXECUTE)),
) -> APIResponse[dict[str, Any] | None]:
    execution = await _service(session, principal).capture(body.execution_id)
    return APIResponse(data=execution_out(execution), meta={"mode": execution.mode})


@router.get("/orders/{execution_id}", summary="Order details, refreshed from PayPal")
async def order_details(
    execution_id: uuid.UUID, session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PAYPAL_READ)),
) -> APIResponse[dict[str, Any]]:
    return APIResponse(data=await _service(session, principal).order_details(execution_id))


@router.get("/history", summary="Payment history, status counts and open approvals")
async def history(
    session: DbSession, kind: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    principal: Principal = Depends(require_permission(Permission.PAYPAL_READ)),
) -> APIResponse[dict[str, Any]]:
    data = await _service(session, principal).history(limit=limit, kind=kind)
    data["permissions"] = {"can_approve": principal.has(Permission.PAYMENT_APPROVE),
                           "can_execute": principal.has(Permission.PAYMENT_EXECUTE)}
    return APIResponse(data=data)


@router.post("/webhooks/paypal", summary="PayPal webhook receiver (verified, idempotent) - alias of /paypal/webhooks")
async def paypal_webhook(request: Request, session: DbSession) -> Any:
    body = await request.body()
    event, outcome = await WebhookService(session).ingest(headers=dict(request.headers), body=body)
    if outcome == "invalid":
        raise BadRequestError("Malformed webhook body.")
    if outcome == "rejected":
        await session.commit()
        return JSONResponse(status_code=401, content={"success": False, "error": {
            "code": "PAYPAL_WEBHOOK_REJECTED", "message": "Webhook signature could not be verified."}})
    return APIResponse(data={"outcome": outcome, "event_id": event.event_id if event else None})
