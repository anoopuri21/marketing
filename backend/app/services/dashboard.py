"""Cross-website dashboard aggregates for a user (counts, averages, recent activity)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.models import Audit, AuditIssue, Keyword, Lead, ReportRun, ReportSchedule, Task, Website, Workspace

OPEN_TASK_STATUSES = ("todo", "in_progress")
ACTIVE_LEAD_STATUSES = ("contacted", "replied", "qualified")
CLOSED_LEAD_STATUSES = ("won", "lost")


@dataclass
class DashboardStats:
    websites: int = 0
    verified_websites: int = 0
    audits_completed: int = 0
    open_tasks: int = 0
    tracked_keywords: int = 0
    avg_score: float | None = None
    reports_sent: int = 0
    recent_audits: list[Audit] = field(default_factory=list)
    upcoming_reports: list[ReportSchedule] = field(default_factory=list)
    open_issue_counts: dict[str, int] = field(default_factory=dict)
    leads_total: int = 0
    leads_active: int = 0
    leads_won: int = 0
    follow_ups_due: int = 0


async def user_website_ids(db: AsyncSession, user_id: int) -> list[int]:
    stmt = select(Website.id).join(Workspace, Website.workspace_id == Workspace.id).where(Workspace.owner_id == user_id)
    return [row[0] for row in (await db.execute(stmt)).all()]


async def _count(db: AsyncSession, stmt: Any) -> int:
    return int((await db.execute(stmt)).scalar_one() or 0)


async def latest_completed_audit_ids(db: AsyncSession, site_ids: list[int]) -> list[int]:
    """One (latest) completed audit id per website, in a single grouped query."""
    stmt = select(func.max(Audit.id)).where(Audit.website_id.in_(site_ids), Audit.status == "completed").group_by(Audit.website_id)
    return [row[0] for row in (await db.execute(stmt)).all()]


async def build_dashboard(db: AsyncSession, user_id: int) -> DashboardStats:
    site_ids = await user_website_ids(db, user_id)
    stats = DashboardStats(websites=len(site_ids))
    if not site_ids:
        return stats

    stats.verified_websites = await _count(db, select(func.count()).select_from(Website).where(Website.id.in_(site_ids), Website.verified.is_(True)))
    stats.audits_completed = await _count(db, select(func.count()).select_from(Audit).where(Audit.website_id.in_(site_ids), Audit.status == "completed"))
    stats.open_tasks = await _count(db, select(func.count()).select_from(Task).where(Task.website_id.in_(site_ids), Task.status.in_(OPEN_TASK_STATUSES)))
    stats.tracked_keywords = await _count(db, select(func.count()).select_from(Keyword).where(Keyword.website_id.in_(site_ids)))
    stats.reports_sent = await _count(db, select(func.count()).select_from(ReportRun).where(ReportRun.website_id.in_(site_ids), ReportRun.status == "sent"))
    avg = (await db.execute(select(func.avg(Website.last_score)).where(Website.id.in_(site_ids), Website.last_score.is_not(None)))).scalar_one()
    stats.avg_score = round(float(avg), 1) if avg is not None else None

    lead_counts: dict[str, int] = {
        status: n for status, n in (await db.execute(select(Lead.status, func.count()).where(Lead.website_id.in_(site_ids)).group_by(Lead.status))).all()
    }
    stats.leads_total = sum(lead_counts.values())
    stats.leads_active = sum(lead_counts.get(k, 0) for k in ACTIVE_LEAD_STATUSES)
    stats.leads_won = lead_counts.get("won", 0)
    stats.follow_ups_due = await _count(db, select(func.count()).select_from(Lead).where(
        Lead.website_id.in_(site_ids), Lead.next_follow_up_at.is_not(None), Lead.next_follow_up_at <= utcnow(), Lead.status.not_in(CLOSED_LEAD_STATUSES)))

    stats.recent_audits = list((await db.execute(select(Audit).where(Audit.website_id.in_(site_ids)).order_by(Audit.created_at.desc()).limit(8))).scalars().all())
    stats.upcoming_reports = list((await db.execute(
        select(ReportSchedule).where(ReportSchedule.website_id.in_(site_ids), ReportSchedule.enabled.is_(True)).order_by(ReportSchedule.next_run_at).limit(5)
    )).scalars().all())

    latest_ids = await latest_completed_audit_ids(db, site_ids)
    if latest_ids:
        rows = (await db.execute(select(AuditIssue.severity, func.count()).where(AuditIssue.audit_id.in_(latest_ids)).group_by(AuditIssue.severity))).all()
        stats.open_issue_counts = {sev: n for sev, n in rows}
    return stats
