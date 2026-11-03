"""HTTP middleware: request ids, access logging, security headers, rate limiting."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.logging import bind_context, clear_context, get_logger
from app.core.security import new_request_id

log = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Permitted-Cross-Domain-Policies": "none",
    "Permissions-Policy": "camera=(), geolocation=(), payment=(), usb=()",
}

#: Paths that should not appear in the access log (health probes / docs assets).
_QUIET_PATHS = frozenset({"/api/v1/health", "/api/v1/health/live", "/favicon.ico", "/metrics"})


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request id, bind logging context, emit one structured access log."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or new_request_id()
        request.state.request_id = request_id
        clear_context()
        bind_context(request_id=request_id)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration = round((time.perf_counter() - started) * 1000, 2)
            log.exception(
                "http_request",
                method=request.method,
                path=request.url.path,
                status_code=500,
                duration_ms=duration,
            )
            raise
        duration = round((time.perf_counter() - started) * 1000, 2)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers["X-Response-Time-Ms"] = str(duration)

        if request.url.path not in _QUIET_PATHS:
            level = log.info if response.status_code < 500 else log.error
            level(
                "http_request",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration,
            )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        if settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-process sliding-window limiter.

    Deliberately simple and dependency-free: it establishes the limiting *seam*
    for the app. Swap the ``_hits`` store for Redis to make it multi-worker safe.
    """

    def __init__(self, app: FastAPI, *, limit: int, window_seconds: int) -> None:
        super().__init__(app)
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}

    def _bucket_key(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for", "")
        client_ip = (
            forwarded.split(",")[0].strip()
            if forwarded
            else (request.client.host if request.client else "unknown")
        )
        # Authenticated callers get their own bucket so one noisy IP cannot starve a tenant.
        auth = request.headers.get("authorization", "")
        identity = auth[-24:] if auth else client_ip
        return f"{identity}:{request.url.path.split('/')[3] if len(request.url.path.split('/')) > 3 else 'root'}"

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not settings.rate_limit_enabled or request.method == "OPTIONS":
            return await call_next(request)
        if request.url.path in _QUIET_PATHS:
            return await call_next(request)

        key = self._bucket_key(request)
        now = time.monotonic()
        window_start = now - self.window
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] < window_start:
            hits.popleft()

        if len(hits) >= self.limit:
            retry_after = max(1, int(self.window - (now - hits[0])))
            log.warning("rate_limited", path=request.url.path, limit=self.limit)
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "Too many requests. Please slow down.",
                    },
                    "request_id": getattr(request.state, "request_id", None),
                },
                headers={"Retry-After": str(retry_after)},
            )

        hits.append(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, self.limit - len(hits)))
        return response


def register_middleware(app: FastAPI) -> None:
    """Order matters: the last registered middleware runs first."""
    app.add_middleware(SecurityHeadersMiddleware)
    if settings.rate_limit_enabled:
        app.add_middleware(
            RateLimitMiddleware,
            limit=settings.rate_limit_requests,
            window_seconds=settings.rate_limit_window_seconds,
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|.*\.ngrok-free\.app|.*\.ngrok-free\.dev)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        # Content-Disposition carries the filename for downloads. Without it
        # here the browser hides the header from JavaScript, so an export saves
        # under a guessed name instead of the one the server chose.
        expose_headers=[REQUEST_ID_HEADER, "X-Response-Time-Ms", "Content-Disposition"],
        max_age=3600,
    )
    app.add_middleware(RequestContextMiddleware)
