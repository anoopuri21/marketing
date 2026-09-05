"""Tiny in-process sliding-window rate limiter (no Redis needed for a single instance).

Used for credential endpoints (login/register) and expensive external calls (lead discovery).
For multi-instance deployments swap `_buckets` for a shared store – the interface stays the same.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import HTTPException, Request

from app.core.config import settings

_buckets: dict[str, deque[float]] = defaultdict(deque)
_MAX_TRACKED_KEYS = 10_000  # prune idle buckets past this to keep memory bounded under IP churn


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check(key: str, limit: int, window_seconds: int) -> float | None:
    """Record a hit for `key`; return seconds-to-wait when over the limit, else None."""
    now = time.monotonic()
    if len(_buckets) > _MAX_TRACKED_KEYS:
        _prune(now, window_seconds)
    bucket = _buckets[key]
    while bucket and now - bucket[0] > window_seconds:
        bucket.popleft()
    if len(bucket) >= limit:
        return round(window_seconds - (now - bucket[0]), 1)
    bucket.append(now)
    return None


def _prune(now: float, window_seconds: int) -> None:
    for stale in [k for k, b in _buckets.items() if not b or now - b[-1] > window_seconds]:
        _buckets.pop(stale, None)


def reset(key: str | None = None) -> None:
    if key is None:
        _buckets.clear()
    else:
        _buckets.pop(key, None)


def limiter(scope: str, limit: int, window_seconds: int = 60) -> Callable[[Request], None]:
    """FastAPI dependency factory: `Depends(limiter("login", 10))` → HTTP 429 when exceeded."""

    def dependency(request: Request) -> None:
        if not settings.rate_limit_enabled:
            return
        wait = check(f"{scope}:{client_ip(request)}", limit, window_seconds)
        if wait is not None:
            raise HTTPException(status_code=429, detail=f"Too many requests – try again in {wait:.0f}s", headers={"Retry-After": str(int(wait) + 1)})

    return dependency
