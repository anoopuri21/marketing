"""Logging setup + request-id middleware.

Every request gets an `X-Request-ID` (incoming header is honoured, otherwise generated). The id is
stored in a context variable and injected into every log line emitted while handling that request,
so a failing audit or publish can be traced end-to-end in the logs.
"""
from __future__ import annotations

import contextvars
import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_NOISY_LOGGERS = ("httpx", "httpcore", "apscheduler.executors.default", "PIL")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def configure_logging(level: str = "INFO") -> None:
    """Idempotent root-logger configuration (safe to call from tests and the app)."""
    root = logging.getLogger()
    if getattr(root, "_rankpilot_configured", False):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"))
    handler.addFilter(RequestIdFilter())
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    root._rankpilot_configured = True  # type: ignore[attr-defined]


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


async def request_id_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    token = request_id_var.set(rid)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-ID"] = rid
    if not request.url.path.startswith("/media/"):  # social networks embed creatives → no frame/referrer restrictions there
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
    elapsed_ms = (time.perf_counter() - started) * 1000
    if elapsed_ms > 2000:  # slow-request breadcrumb
        logging.getLogger("rankpilot.http").warning("slow request %s %s took %.0f ms", request.method, request.url.path, elapsed_ms)
    return response
