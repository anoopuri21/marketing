from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.models import ReportSchedule
from app.services.scheduler import compute_next_run


def _sched(**kw) -> ReportSchedule:
    base = dict(frequency="weekly", day_of_week=0, day_of_month=1, hour=9, minute=0, timezone="Asia/Kolkata")
    base.update(kw)
    return ReportSchedule(**base)


def test_weekly_next_run_is_monday_9am_ist():
    # Wednesday 3 Sep 2026 12:00 UTC
    now = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
    nxt = compute_next_run(_sched(), after=now)
    local = nxt.astimezone(ZoneInfo("Asia/Kolkata"))
    assert local.weekday() == 0 and local.hour == 9 and local.minute == 0
    assert local.date().isoformat() == "2026-09-07"
    assert nxt == datetime(2026, 9, 7, 3, 30, tzinfo=timezone.utc)


def test_weekly_same_day_before_time_runs_today():
    # Monday 7 Sep 2026 01:00 UTC == 06:30 IST, before 09:00 IST
    now = datetime(2026, 9, 7, 1, 0, tzinfo=timezone.utc)
    nxt = compute_next_run(_sched(), after=now)
    assert nxt == datetime(2026, 9, 7, 3, 30, tzinfo=timezone.utc)


def test_weekly_same_day_after_time_rolls_a_week():
    now = datetime(2026, 9, 7, 5, 0, tzinfo=timezone.utc)  # 10:30 IST Monday
    nxt = compute_next_run(_sched(), after=now)
    assert nxt == datetime(2026, 9, 14, 3, 30, tzinfo=timezone.utc)


def test_monthly_rolls_over_year_end():
    now = datetime(2026, 12, 20, 0, 0, tzinfo=timezone.utc)
    nxt = compute_next_run(_sched(frequency="monthly", day_of_month=15, hour=10, minute=30, timezone="UTC"), after=now)
    assert nxt == datetime(2027, 1, 15, 10, 30, tzinfo=timezone.utc)


def test_unknown_timezone_falls_back_to_utc():
    now = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
    nxt = compute_next_run(_sched(timezone="Not/AZone", frequency="monthly", day_of_month=5, hour=8), after=now)
    assert nxt == datetime(2026, 9, 5, 8, 0, tzinfo=timezone.utc)
