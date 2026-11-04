"""Choosing between real PayPal and the simulator.

``get_paypal_gateway()`` is the only way application code reaches PayPal. It
returns a ``PayPalClient`` when credentials are configured, the deterministic
``SimulatedPayPal`` when they are not (and simulation is allowed), and raises
otherwise. Either way the returned object reports its ``mode``, and every service
persists that mode next to what it wrote.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.core.config import settings
from app.integrations.paypal.client import PayPalClient
from app.integrations.paypal.errors import PayPalNotConfiguredError
from app.integrations.paypal.simulator import SimulatedPayPal


@runtime_checkable
class PayPalGateway(Protocol):
    mode: str

    async def search_transactions(self, **kwargs: Any) -> Any: ...
    async def iter_transactions(self, **kwargs: Any) -> Any: ...
    async def create_order(self, **kwargs: Any) -> Any: ...
    async def get_order(self, order_id: str) -> Any: ...
    async def capture_order(self, order_id: str, *, request_id: str) -> Any: ...
    async def authorize_order(self, order_id: str, *, request_id: str) -> Any: ...
    async def capture_authorization(self, authorization_id: str, **kwargs: Any) -> Any: ...
    async def void_authorization(self, authorization_id: str, *, request_id: str) -> None: ...
    async def create_invoice(self, draft: Any, *, request_id: str) -> Any: ...
    async def get_invoice(self, invoice_id: str) -> Any: ...
    async def send_invoice(self, invoice_id: str, **kwargs: Any) -> Any: ...
    async def remind_invoice(self, invoice_id: str, **kwargs: Any) -> None: ...
    async def cancel_invoice(self, invoice_id: str, **kwargs: Any) -> None: ...
    async def create_payout(self, batch: Any) -> Any: ...
    async def get_payout_batch(self, payout_batch_id: str) -> Any: ...
    async def verify_webhook_signature(self, *, headers: Any, body: bytes) -> bool: ...
    async def aclose(self) -> None: ...


_gateway: PayPalClient | SimulatedPayPal | None = None


def get_paypal_gateway() -> PayPalClient | SimulatedPayPal:
    global _gateway
    if _gateway is not None:
        return _gateway
    if settings.paypal_configured:
        _gateway = PayPalClient()
    elif settings.paypal_simulation_enabled:
        _gateway = SimulatedPayPal()
    else:
        raise PayPalNotConfiguredError(
            "PayPal credentials are missing and simulation is disabled "
            "(set PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET or PAYPAL_SIMULATION_ENABLED=true)."
        )
    return _gateway


def set_paypal_gateway(gateway: PayPalClient | SimulatedPayPal | None) -> None:
    """Inject a gateway (tests) or clear it so the next call rebuilds from settings."""
    global _gateway
    _gateway = gateway


def reset_paypal_gateway() -> None:
    set_paypal_gateway(None)


async def close_paypal_gateway() -> None:
    global _gateway
    if _gateway is not None:
        await _gateway.aclose()
        _gateway = None


def paypal_status() -> dict[str, Any]:
    """What the UI and health checks may know. Never a secret."""
    mode = settings.paypal_mode
    return {
        "mode": mode,
        "environment": settings.paypal_environment,
        "configured": settings.paypal_configured,
        "webhook_configured": bool(settings.paypal_webhook_id),
        "simulation_enabled": settings.paypal_simulation_enabled,
        "base_url": settings.paypal_base_url if settings.paypal_configured else "simulated://paypal",
        "currency": settings.default_currency,
        "client_id_hint": (
            f"{settings.paypal_client_id[:6]}…" if settings.paypal_client_id else ""
        ),
        "note": (
            "Connected to the PayPal sandbox." if mode == "SANDBOX"
            else "Connected to live PayPal." if mode == "LIVE"
            else "No PayPal credentials configured - payments, invoices, payouts and "
            "transaction sync run against a deterministic simulator and are labelled SIMULATED."
        ),
    }
