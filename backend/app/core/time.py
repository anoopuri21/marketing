"""Single source of truth for "now" and timezone handling.

* Everything in RankPilot is stored and compared in UTC.
* SQLite hands back naive datetimes – `aware()` re-attaches UTC so comparisons never blow up.
* Tests can monkeypatch `utcnow` in one place instead of patching `datetime` everywhere.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import overload


def utcnow() -> datetime:
    """Timezone-aware current time in UTC."""
    return datetime.now(UTC)


@overload
def aware(dt: datetime) -> datetime: ...


@overload
def aware(dt: None) -> None: ...


@overload
def aware(dt: datetime | None) -> datetime | None: ...


def aware(dt: datetime | None) -> datetime | None:
    """Return `dt` as a timezone-aware UTC datetime (naive values are assumed to be UTC)."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def is_past(dt: datetime | None, *, now: datetime | None = None) -> bool:
    """True when `dt` is set and already in the past."""
    return dt is not None and aware(dt) <= (now or utcnow())


def age(dt: datetime | None, *, now: datetime | None = None) -> timedelta | None:
    """How long ago `dt` was (None when unset)."""
    if dt is None:
        return None
    return (now or utcnow()) - aware(dt)
