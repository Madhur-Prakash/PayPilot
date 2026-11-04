"""PayPal integration errors.

Messages carry PayPal's error ``name``, its ``debug_id`` (what PayPal support asks
for) and the issue details - never the client secret, the Basic auth header or an
access token.
"""

from __future__ import annotations

from typing import Any

from app.core.exceptions import IntegrationError


class PayPalError(IntegrationError):
    code = "PAYPAL_ERROR"


class PayPalNotConfiguredError(PayPalError):
    code = "PAYPAL_NOT_CONFIGURED"

    def __init__(self, message: str = "PayPal credentials are not configured.") -> None:
        super().__init__(message)


class PayPalAuthError(PayPalError):
    code = "PAYPAL_AUTH_FAILED"


class PayPalAPIError(PayPalError):
    """A non-2xx answer from the PayPal REST API."""

    code = "PAYPAL_API_ERROR"

    def __init__(
        self,
        message: str,
        *,
        http_status: int,
        name: str = "",
        debug_id: str = "",
        issues: list[dict[str, Any]] | None = None,
    ) -> None:
        self.http_status = http_status
        self.name = name
        self.debug_id = debug_id
        self.issues = issues or []
        super().__init__(
            message,
            details={
                "http_status": http_status,
                "paypal_error": name,
                "debug_id": debug_id,
                "issues": self.issues[:5],
            },
        )

    @property
    def retryable(self) -> bool:
        return self.http_status == 429 or self.http_status >= 500

    def __repr__(self) -> str:  # pragma: no cover - debugging affordance
        return f"PayPalAPIError(status={self.http_status}, name={self.name!r}, debug_id={self.debug_id!r})"


class PayPalWebhookError(PayPalError):
    code = "PAYPAL_WEBHOOK_REJECTED"
