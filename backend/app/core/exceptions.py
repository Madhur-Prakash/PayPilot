"""Application error taxonomy + the handlers that render it.

Clients always receive the same envelope and never a stack trace::

    {"success": false,
     "error": {"code": "PERMISSION_DENIED", "message": "...", "details": {...}},
     "request_id": "..."}
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

#: Starlette 1.0 renamed ``HTTP_422_UNPROCESSABLE_ENTITY`` to
#: ``HTTP_422_UNPROCESSABLE_CONTENT`` (RFC 9110 wording) and made the old name emit a
#: DeprecationWarning on attribute access. Both are 422; resolve whichever this
#: install provides. The ``getattr`` default short-circuits, so the deprecated name is
#: only touched on versions where it is not yet deprecated.
HTTP_422_UNPROCESSABLE: int = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", None) or getattr(
    status, "HTTP_422_UNPROCESSABLE_ENTITY", 422
)


class AppError(Exception):
    """Base class for every error the application raises deliberately."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "APP_ERROR"
    message: str = "Something went wrong."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details or {}
        super().__init__(self.message)

    def to_payload(self, request_id: str | None = None) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            error["details"] = self.details
        return {"success": False, "error": error, "request_id": request_id}


# --------------------------------------------------------------------------- #
# 4xx
# --------------------------------------------------------------------------- #
class BadRequestError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "BAD_REQUEST"
    message = "The request could not be processed."


class ValidationError(AppError):
    status_code = HTTP_422_UNPROCESSABLE
    code = "VALIDATION_ERROR"
    message = "The submitted data is invalid."


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "AUTHENTICATION_FAILED"
    message = "Authentication is required."


class InvalidCredentialsError(AuthenticationError):
    code = "INVALID_CREDENTIALS"
    message = "Incorrect email or password."


class TokenExpiredError(AuthenticationError):
    code = "TOKEN_EXPIRED"
    message = "Your session has expired. Please sign in again."


class InvalidTokenError(AuthenticationError):
    code = "INVALID_TOKEN"
    message = "The provided token is invalid."


class InactiveAccountError(AuthenticationError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "ACCOUNT_INACTIVE"
    message = "This account is not active."


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "PERMISSION_DENIED"
    message = "You do not have permission to perform this action."


class MerchantScopeError(AppError):
    """Raised when a user reaches for data belonging to another merchant."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "MERCHANT_SCOPE_VIOLATION"
    message = "You do not have access to this merchant."


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"
    message = "The requested resource was not found."


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"
    message = "The resource already exists."


class ApprovalRequiredError(AppError):
    """A financially consequential action was attempted without merchant approval."""

    status_code = status.HTTP_409_CONFLICT
    code = "APPROVAL_REQUIRED"
    message = "This action requires explicit merchant approval before it can run."


class RateLimitError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "RATE_LIMITED"
    message = "Too many requests. Please slow down."


# --------------------------------------------------------------------------- #
# 5xx / integrations
# --------------------------------------------------------------------------- #
class InternalError(AppError):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    code = "INTERNAL_ERROR"
    message = "An unexpected error occurred."


class IntegrationError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "INTEGRATION_ERROR"
    message = "An upstream service failed."


class LLMError(IntegrationError):
    code = "LLM_ERROR"
    message = "The AI service is temporarily unavailable."


class LLMTimeoutError(LLMError):
    status_code = status.HTTP_504_GATEWAY_TIMEOUT
    code = "LLM_TIMEOUT"
    message = "The AI service took too long to respond."


class LLMSchemaError(LLMError):
    code = "LLM_SCHEMA_ERROR"
    message = "The AI returned a response that did not match the expected schema."


class ServiceUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "SERVICE_UNAVAILABLE"
    message = "The service is temporarily unavailable."


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #
def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    logger = log.warning if exc.status_code < 500 else log.error
    logger(
        "request_failed",
        code=exc.code,
        status_code=exc.status_code,
        path=request.url.path,
        method=request.method,
        detail=exc.message,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_payload(_request_id(request)),
        headers={"X-Request-ID": _request_id(request) or ""},
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = {
        401: "AUTHENTICATION_FAILED",
        403: "PERMISSION_DENIED",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        429: "RATE_LIMITED",
    }.get(exc.status_code, "HTTP_ERROR")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {"code": code, "message": str(exc.detail)},
            "request_id": _request_id(request),
        },
        headers={"X-Request-ID": _request_id(request) or ""},
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    fields = [
        {
            "field": ".".join(str(part) for part in err.get("loc", ())[1:]) or "body",
            "message": err.get("msg", "invalid"),
            "type": err.get("type", "value_error"),
        }
        for err in exc.errors()
    ]
    log.info("request_validation_failed", path=request.url.path, fields=fields)
    return JSONResponse(
        status_code=HTTP_422_UNPROCESSABLE,
        content={
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "One or more fields are invalid.",
                "details": {"fields": fields},
            },
            "request_id": _request_id(request),
        },
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        error_type=type(exc).__name__,
    )
    error: dict[str, Any] = {
        "code": "INTERNAL_ERROR",
        "message": "An unexpected error occurred.",
    }
    # Stack traces never leave the process in production.
    if settings.debug and not settings.is_production:
        error["details"] = {"exception": type(exc).__name__, "detail": str(exc)[:500]}
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"success": False, "error": error, "request_id": _request_id(request)},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
