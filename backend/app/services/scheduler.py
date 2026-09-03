"""Background scheduler.

Every tick it:
  1. sends due report schedules (optionally running a fresh audit first),
  2. runs automatic periodic audits for websites with auto_audit_enabled.

Schedules store `next_run_at` in UTC; `compute_next_run` converts from the schedule's
local timezone so "Monday 09:00 Asia/Kolkata" means exactly that.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.core.config import settings
from app.core.database import session_scope
from app.models import Audit, ReportSchedule, Website
from app.models.entities import aware
from app.services.audit.engine import create_and_run_audit, run_audit
from app.services.reports.generator import generate_and_send

log = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None
_lock = asyncio.Lock()


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def compute_next_run(schedule: ReportSchedule, after: Optional[datetime] = None) -> datetime:
    tz = _tz(schedule.timezone)
    now_local = (after or datetime.now(timezone.utc)).astimezone(tz)
    candidate = now_local.replace(hour=schedule.hour, minute=schedule.minute, second=0, microsecond=0)
    if schedule.frequency == "monthly":
        candidate = candidate.replace(day=min(schedule.day_of_month, 28))
        while candidate <= now_local:
            # move to next month
            year, month = candidate.year + (candidate.month // 12), (candidate.month % 12) + 1
            candidate = candidate.replace(year=year, month=month)
    else:  # weekly
        delta_days = (schedule.day_of_week - candidate.weekday()) % 7
        candidate = candidate + timedelta(days=delta_days)
        while candidate <= now_local:
            candidate += timedelta(days=7)
    return candidate.astimezone(timezone.utc)


async def process_due_reports() -> int:
    now = datetime.now(timezone.utc)
    sent = 0
    async with session_scope() as db:
        due = (await db.execute(
            select(ReportSchedule).where(ReportSchedule.enabled.is_(True), ReportSchedule.next_run_at <= now)
        )).scalars().all()
        due_ids = [(s.id, s.website_id, s.run_fresh_audit) for s in due]
    for sched_id, website_id, fresh in due_ids:
        try:
            if fresh:
                await create_and_run_audit(website_id, trigger="report")
            async with session_scope() as db:
                sched = await db.get(ReportSchedule, sched_id)
                website = await db.get(Website, website_id)
                if sched is None or website is None:
                    continue
                await generate_and_send(db, website, sched.recipients, sched.frequency, schedule_id=sched.id)
                sched.last_run_at = datetime.now(timezone.utc)
                sched.next_run_at = compute_next_run(sched)
                sent += 1
        except Exception:
            log.exception("scheduled report %s failed", sched_id)
            async with session_scope() as db:
                sched = await db.get(ReportSchedule, sched_id)
                if sched:
                    sched.next_run_at = compute_next_run(sched)  # don't retry in a hot loop
    return sent


async def process_auto_audits() -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.auto_audit_interval_days)
    async with session_scope() as db:
        sites = (await db.execute(select(Website).where(Website.auto_audit_enabled.is_(True)))).scalars().all()
        todo = []
        for s in sites:
            if s.last_audit_at is None or aware(s.last_audit_at) <= cutoff:
                # skip if an audit is already queued/running
                running = (await db.execute(
                    select(Audit.id).where(Audit.website_id == s.id, Audit.status.in_(["queued", "running"]))
                )).first()
                if not running:
                    todo.append(s.id)
    for website_id in todo[:5]:  # rate-limit per tick
        try:
            await create_and_run_audit(website_id, trigger="scheduled")
        except Exception:
            log.exception("auto audit failed for website %s", website_id)
    return len(todo[:5])


async def recover_stale_audits() -> None:
    """Audits left in queued/running after a restart are re-run (or failed if too old)."""
    async with session_scope() as db:
        stale = (await db.execute(select(Audit).where(Audit.status.in_(["queued", "running"])))).scalars().all()
        ids = []
        for a in stale:
            age = datetime.now(timezone.utc) - aware(a.started_at or a.created_at)
            if age > timedelta(hours=2):
                a.status = "failed"
                a.error = "Interrupted (server restart)"
            else:
                ids.append(a.id)
    for audit_id in ids:
        asyncio.create_task(run_audit(audit_id))


async def tick() -> None:
    if _lock.locked():
        return
    async with _lock:
        try:
            await process_due_reports()
            await process_auto_audits()
        except Exception:
            log.exception("scheduler tick failed")


def start_scheduler() -> None:
    global _scheduler
    if not settings.scheduler_enabled or _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(tick, IntervalTrigger(seconds=settings.scheduler_tick_seconds), id="tick", max_instances=1, coalesce=True)
    _scheduler.start()
    log.info("scheduler started (tick every %ss)", settings.scheduler_tick_seconds)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
