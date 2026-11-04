"""PayPal REST integration: real client, deterministic simulator, and the gateway
that chooses between them. See docs/PAYPAL.md."""

from app.integrations.paypal.client import MAX_SEARCH_WINDOW, PayPalClient, split_windows
from app.integrations.paypal.errors import (
    PayPalAPIError,
    PayPalAuthError,
    PayPalError,
    PayPalNotConfiguredError,
    PayPalWebhookError,
)
from app.integrations.paypal.gateway import (
    close_paypal_gateway,
    get_paypal_gateway,
    paypal_status,
    reset_paypal_gateway,
    set_paypal_gateway,
)
from app.integrations.paypal.models import (
    InvoiceDraft,
    InvoiceLine,
    Money,
    OrderItem,
    PayoutBatchRequest,
    PayoutItem,
    PayPalCapture,
    PayPalInvoice,
    PayPalOrder,
    PayPalPayoutBatch,
    PayPalPlan,
    PayPalSubscription,
    PayPalTransaction,
    TransactionSearchPage,
    money_str,
)
from app.integrations.paypal.simulator import SimulatedPayPal, sign_simulated_webhook

__all__ = [
    "MAX_SEARCH_WINDOW",
    "InvoiceDraft",
    "InvoiceLine",
    "Money",
    "OrderItem",
    "PayPalAPIError",
    "PayPalAuthError",
    "PayPalCapture",
    "PayPalClient",
    "PayPalError",
    "PayPalInvoice",
    "PayPalNotConfiguredError",
    "PayPalOrder",
    "PayPalPayoutBatch",
    "PayPalPlan",
    "PayPalSubscription",
    "PayPalTransaction",
    "PayPalWebhookError",
    "PayoutBatchRequest",
    "PayoutItem",
    "SimulatedPayPal",
    "TransactionSearchPage",
    "close_paypal_gateway",
    "get_paypal_gateway",
    "money_str",
    "paypal_status",
    "reset_paypal_gateway",
    "set_paypal_gateway",
    "sign_simulated_webhook",
    "split_windows",
]
