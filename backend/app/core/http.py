"""Shared HTTP helpers: TLS context selection + client factory.

Uses the OS trust store when available (falls back to certifi), so corporate /
sandbox proxies with custom CAs still work. `insecure=True` disables verification
for crawling sites with broken certificates (the audit reports that as an issue).
"""
from __future__ import annotations

import os
import ssl
from pathlib import Path
from typing import Optional

import httpx

from app.core.config import settings

_SYSTEM_CA_CANDIDATES = (
    os.environ.get("SSL_CERT_FILE", ""),
    os.environ.get("REQUESTS_CA_BUNDLE", ""),
    "/etc/ssl/certs/ca-certificates.crt",  # Debian/Ubuntu
    "/etc/pki/tls/certs/ca-bundle.crt",  # RHEL/CentOS
    "/etc/ssl/ca-bundle.pem",  # openSUSE
    "/etc/ssl/cert.pem",  # Alpine / macOS
)

_ctx_cache: dict[str, ssl.SSLContext] = {}


def _ca_file() -> Optional[str]:
    for candidate in _SYSTEM_CA_CANDIDATES:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def ssl_context(insecure: bool = False) -> ssl.SSLContext | bool:
    key = "insecure" if insecure else "secure"
    if key in _ctx_cache:
        return _ctx_cache[key]
    if insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    else:
        ca = _ca_file()
        ctx = ssl.create_default_context(cafile=ca) if ca else ssl.create_default_context()
        try:  # also merge certifi so we get the best of both
            import certifi

            ctx.load_verify_locations(cafile=certifi.where())
        except Exception:
            pass
    _ctx_cache[key] = ctx
    return ctx


def make_client(insecure: bool = False, timeout: Optional[float] = None, **kwargs) -> httpx.AsyncClient:
    headers = {"User-Agent": settings.user_agent, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
               "Accept-Language": "en-US,en;q=0.9"}
    headers.update(kwargs.pop("headers", {}) or {})
    return httpx.AsyncClient(
        headers=headers,
        timeout=httpx.Timeout(timeout or settings.crawl_timeout_seconds),
        follow_redirects=True,
        verify=ssl_context(insecure),
        **kwargs,
    )


def is_tls_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return "ssl" in text or "certificate" in text or "tls" in text
