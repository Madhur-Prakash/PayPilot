"""Structured logging for the whole backend.

Uses **Logifyx** when it is installed; otherwise falls back to an equivalent
built-in structured logger so the application never depends on an optional
package being present. Either way the public surface is identical::

    from app.core.logging import get_logger
    log = get_logger(__name__)
    log.info("agent_tool_call", tool="get_revenue_trend", duration_ms=142)

Request-scoped fields (request_id, user_id, merchant_id, agent_run_id, trace_id)
are carried in contextvars and merged into every record automatically.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from app.core.config import BACKEND_DIR, settings

#: Where Logifyx's rotating file sink writes. Git-ignored.
BACKEND_LOG_DIR = BACKEND_DIR / "logs"

# --------------------------------------------------------------------------- #
# Redaction
# --------------------------------------------------------------------------- #
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "new_password",
        "current_password",
        "password_hash",
        "hashed_password",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "api_key",
        "apikey",
        "secret",
        "jwt_secret",
        "authorization",
        "cookie",
        "set-cookie",
        "groq_api_key",
        "studio_ai_api_key",
        "langfuse_secret_key",
        "vapi_private_key",
        "supabase_anon_key",
        "tavily_api_key",
        "client_secret",
        "private_key",
        "credentials",
    }
)
REDACTED = "[redacted]"


def redact(value: Any, _depth: int = 0) -> Any:
    """Recursively strip secrets out of anything headed for a log sink."""
    if _depth > 6:
        return value
    if isinstance(value, dict):
        return {
            key: (REDACTED if str(key).lower() in SENSITIVE_KEYS else redact(val, _depth + 1))
            for key, val in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(item, _depth + 1) for item in value]
    return value


# --------------------------------------------------------------------------- #
# Request-scoped context
# --------------------------------------------------------------------------- #
# Default is None, not {}: a mutable ContextVar default is shared across every
# context and can be mutated by one request for all others.
_context: ContextVar[dict[str, Any] | None] = ContextVar("pga_log_context", default=None)


def bind_context(**fields: Any) -> None:
    """Attach fields to every subsequent log record on this task/request."""
    current = dict(_context.get() or {})
    current.update({k: v for k, v in fields.items() if v is not None})
    _context.set(current)


def get_context() -> dict[str, Any]:
    return dict(_context.get() or {})


def clear_context() -> None:
    _context.set({})


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    merged = {**(_context.get() or {}), **{k: v for k, v in fields.items() if v is not None}}
    token = _context.set(merged)
    try:
        yield
    finally:
        _context.reset(token)


# --------------------------------------------------------------------------- #
# Formatters
# --------------------------------------------------------------------------- #
_RESERVED = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()) | {
    "message",
    "asctime",
    "taskName",
}


def _safe_extra(fields: dict[str, Any]) -> dict[str, Any]:
    """Rename any field that would collide with a reserved LogRecord attribute.

    ``logging`` raises "Attempt to overwrite X in LogRecord" instead of dropping
    the key, so a stray ``module=`` kwarg would otherwise crash the caller.
    """
    return {(f"{k}_" if k in _RESERVED else k): v for k, v in fields.items()}


_LEVEL_COLORS = {
    "DEBUG": "\x1b[38;5;245m",
    "INFO": "\x1b[38;5;39m",
    "WARNING": "\x1b[38;5;214m",
    "ERROR": "\x1b[38;5;203m",
    "CRITICAL": "\x1b[48;5;203;38;5;231m",
}
_RESET = "\x1b[0m"
_DIM = "\x1b[38;5;244m"


def _record_payload(record: logging.LogRecord) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
        "level": record.levelname,
        "service": settings.app_name,
        "environment": settings.app_env,
        "logger": record.name,
        "event": record.getMessage(),
    }
    extras = {k: v for k, v in record.__dict__.items() if k not in _RESERVED}
    payload.update(extras)
    if record.exc_info:
        payload["error"] = logging.Formatter().formatException(record.exc_info)
    return redact(payload)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(_record_payload(record), default=str, separators=(",", ":"))


class LogifyxFieldsFormatter(logging.Formatter):
    """Logifyx's own layout, with the structured fields put back.

    Logifyx's text formatters (coloured console, plain file) render the message only,
    so anything passed via ``extra=`` -- ``version=``, ``duration_ms=``, ``tool=`` --
    silently disappears, which would break the structured contract this module
    promises. Its JSON formatter does emit them as real keys and needs no wrapping.

    This wraps rather than replaces, so Logifyx's colours and layout are preserved and
    the redacted key/value pairs are appended.

    Non-mutating on purpose: appending to ``record.msg`` in a filter would change what
    every *other* handler writes too, depending on the order they run in.
    """

    def __init__(self, inner: logging.Formatter, *, colour: bool) -> None:
        super().__init__()
        self._inner = inner
        self._colour = colour

    def format(self, record: logging.LogRecord) -> str:
        base = self._inner.format(record)
        extras = {k: v for k, v in record.__dict__.items() if k not in _RESERVED}
        if extras:
            fields = redact(extras).items()
            if self._colour:
                kv = " ".join(f"{_DIM}{k}={_RESET}{v}" for k, v in fields)
            else:
                kv = " ".join(f"{k}={v}" for k, v in fields)
            base = f"{base}  {kv}"
        # Logifyx's text formatters render the message alone, so an unhandled
        # exception logged by uvicorn arrived as a bare "Exception in ASGI
        # application" with nothing under it - the one line that says what
        # actually broke was being dropped. Append it, unless it is already there.
        if record.exc_info and "Traceback (most recent call last)" not in base:
            base = f"{base}\n{logging.Formatter().formatException(record.exc_info)}"
        return base


class ConsoleFormatter(logging.Formatter):
    """Human-readable dev output that still shows every structured field."""

    _HIDE = {"timestamp", "level", "service", "environment", "logger", "event", "error"}

    def format(self, record: logging.LogRecord) -> str:
        payload = _record_payload(record)
        color = _LEVEL_COLORS.get(str(payload["level"]), "")
        ts = str(payload["timestamp"])[11:23]
        head = f"{_DIM}{ts}{_RESET} {color}{payload['level']:<7}{_RESET} {payload['event']}"
        rest = {k: v for k, v in payload.items() if k not in self._HIDE}
        if rest:
            kv = " ".join(f"{_DIM}{k}={_RESET}{v}" for k, v in rest.items())
            head = f"{head}  {kv}"
        if payload.get("error"):
            head = f"{head}\n{payload['error']}"
        return head


# --------------------------------------------------------------------------- #
# Logger facade
# --------------------------------------------------------------------------- #
class StructuredLogger:
    """Thin adapter giving ``log.info("event", key=value)`` semantics."""

    __slots__ = ("_logger",)

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    def _emit(self, level: int, event: str, exc_info: Any = None, **fields: Any) -> None:
        if not self._logger.isEnabledFor(level):
            return
        self._logger.log(
            level,
            event,
            exc_info=exc_info,
            extra=_safe_extra({**get_context(), **redact(fields)}),
            # caller -> info()/warning()/... -> _emit() -> log(). Without this the
            # record points at this line, and any formatter that prints a location
            # (Logifyx's does) reports logging.py instead of the real call site.
            stacklevel=3,
        )

    def debug(self, event: str, **fields: Any) -> None:
        self._emit(logging.DEBUG, event, **fields)

    def info(self, event: str, **fields: Any) -> None:
        self._emit(logging.INFO, event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._emit(logging.WARNING, event, **fields)

    def error(self, event: str, exc_info: Any = None, **fields: Any) -> None:
        self._emit(logging.ERROR, event, exc_info=exc_info, **fields)

    def exception(self, event: str, **fields: Any) -> None:
        self._emit(logging.ERROR, event, exc_info=True, **fields)

    def critical(self, event: str, **fields: Any) -> None:
        self._emit(logging.CRITICAL, event, **fields)

    @contextmanager
    def timed(self, event: str, **fields: Any) -> Iterator[dict[str, Any]]:
        """Emit ``event`` on exit with a duration_ms field (and on failure, the error)."""
        started = time.perf_counter()
        bag: dict[str, Any] = {}
        try:
            yield bag
        except Exception as exc:
            self.error(
                event,
                exc_info=True,
                status="error",
                error_type=type(exc).__name__,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                **fields,
                **bag,
            )
            raise
        else:
            self.info(
                event,
                status="ok",
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                **fields,
                **bag,
            )


# --------------------------------------------------------------------------- #
# Setup
# --------------------------------------------------------------------------- #
_configured = False
LOGGING_BACKEND = "builtin"


def logging_backend() -> str:
    """Which sink is actually active: ``logifyx`` or ``builtin``.

    Prefer this over importing ``LOGGING_BACKEND`` directly -- ``from ... import
    LOGGING_BACKEND`` binds the value at import time, which is "builtin" for any module
    that happens to be imported before ``setup_logging()`` runs.
    """
    setup_logging()
    return LOGGING_BACKEND


def _attach_logifyx(root: logging.Logger) -> list[logging.Handler]:
    """Attach Logifyx's handlers to the root logger.

    Logifyx registers a ``logging.Logger`` subclass and configures handlers on a
    named logger; we hoist those handlers onto root so every ``get_logger(...)``
    in the backend flows through them. Fields passed via ``extra=`` surface as
    top-level keys in Logifyx's JSON output, which is exactly the structured
    contract this module promises.

    Returns the handlers it attached (empty when Logifyx is not installed).
    """
    global LOGGING_BACKEND
    try:
        import logifyx  # type: ignore
    except Exception:
        return []

    json_mode = settings.log_format == "json"
    previous_class = logging.getLoggerClass()
    try:
        # setup_logify() swaps the *global* logger class, which would otherwise give
        # every third-party logger (uvicorn, sqlalchemy, httpx) its own handlers and
        # its own log file. Register, build the one sink we want, then restore.
        logifyx.setup_logify()
        sink = logifyx.get_logify_logger(
            settings.app_name,
            json_mode=json_mode,
            color=not json_mode,
            mask=True,
            log_dir=str(BACKEND_LOG_DIR),
        )
    except Exception:
        return []
    finally:
        logging.setLoggerClass(previous_class)

    attached: list[logging.Handler] = []
    for handler in list(getattr(sink, "handlers", [])):
        is_console = isinstance(handler, logging.StreamHandler) and not hasattr(
            handler, "baseFilename"
        )
        if is_console and (json_mode or not settings.log_console_logifyx):
            # JSON mode renders stdout itself, and the built-in console renderer can be
            # preferred explicitly. Either way Logifyx contributes the file sink only.
            continue
        if not json_mode and handler.formatter is not None:
            # Logifyx's text formatters drop extra= fields; its JSON one does not.
            handler.setFormatter(LogifyxFieldsFormatter(handler.formatter, colour=is_console))
        handler.setLevel(settings.log_level)
        root.addHandler(handler)
        attached.append(handler)

    # Handlers now live on root, so records carry the real module name. Detach them
    # from the sink itself so a direct call cannot emit twice.
    sink.handlers = []
    sink.propagate = True

    if attached:
        LOGGING_BACKEND = "logifyx"
    return attached


def setup_logging() -> None:
    """Idempotently configure root logging for the process."""
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)

    logifyx_handlers = _attach_logifyx(root)

    # Only render stdout ourselves when Logifyx did not already claim it, otherwise
    # every line would appear twice.
    has_console = any(
        isinstance(h, logging.StreamHandler) and not hasattr(h, "baseFilename")
        for h in logifyx_handlers
    )
    if not has_console:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            JsonFormatter() if settings.log_format == "json" else ConsoleFormatter()
        )
        root.addHandler(handler)

    root.setLevel(settings.log_level)

    # Uvicorn/SQLAlchemy write through the root handler instead of their own.
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "httpcore"):
        lg = logging.getLogger(noisy)
        lg.handlers = []
        lg.propagate = True
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.db_echo else logging.WARNING
    )

    _configured = True


def get_logger(name: str = "app") -> StructuredLogger:
    setup_logging()
    return StructuredLogger(name)
