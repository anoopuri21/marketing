"""Dashboard + system status."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict

from fastapi import APIRouter
from sqlalchemy import func, select

from app import __version__
from app.api.deps import DB, CurrentUser
from app.core.config import settings
from app.models import Audit, AuditIssue, Keyword, Lead, ReportRun, ReportSchedule, Task, Website, Workspace
from app.schemas.all import AuditSummaryOut, DashboardOut, ReportScheduleOut, SystemStatus

router = APIRouter(prefix="/api", tags=["dashboard & system"])


@router.get("/system/status", response_model=SystemStatus)
async def system_status():
    return SystemStatus(
        app_name=settings.app_name, environment=settings.environment, ai_provider=settings.resolved_ai_provider,
        serp_provider=settings.resolved_serp_provider, email_backend=settings.resolved_email_backend, image_provider=settings.resolved_image_provider, lead_provider=settings.resolved_lead_provider,
        scheduler_enabled=settings.scheduler_enabled, version=__version__,
    )


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(user: CurrentUser, db: DB):
    site_ids = [r[0] for r in (await db.execute(
        select(Website.id).join(Workspace, Website.workspace_id == Workspace.id).where(Workspace.owner_id == user.id)
    )).all()]
    if not site_ids:
        return DashboardOut(websites=0, verified_websites=0, audits_completed=0, open_tasks=0, tracked_keywords=0,
                            avg_score=None, reports_sent=0, recent_audits=[], upcoming_reports=[], open_issue_counts={})
    verified = (await db.execute(select(func.count()).select_from(Website).where(Website.id.in_(site_ids), Website.verified.is_(True)))).scalar_one()
    audits_completed = (await db.execute(select(func.count()).select_from(Audit).where(Audit.website_id.in_(site_ids), Audit.status == "completed"))).scalar_one()
    open_tasks = (await db.execute(select(func.count()).select_from(Task).where(Task.website_id.in_(site_ids), Task.status.in_(["todo", "in_progress"])))).scalar_one()
    keywords = (await db.execute(select(func.count()).select_from(Keyword).where(Keyword.website_id.in_(site_ids)))).scalar_one()
    avg_score = (await db.execute(select(func.avg(Website.last_score)).where(Website.id.in_(site_ids), Website.last_score.is_not(None)))).scalar_one()
    reports_sent = (await db.execute(select(func.count()).select_from(ReportRun).where(ReportRun.website_id.in_(site_ids), ReportRun.status == "sent"))).scalar_one()
    lead_counts = dict((await db.execute(select(Lead.status, func.count()).where(Lead.website_id.in_(site_ids)).group_by(Lead.status))).all())
    follow_ups_due = (await db.execute(select(func.count()).select_from(Lead).where(
        Lead.website_id.in_(site_ids), Lead.next_follow_up_at.is_not(None), Lead.next_follow_up_at <= datetime.now(timezone.utc), Lead.status.not_in(["won", "lost"])))).scalar_one()
    recent = (await db.execute(select(Audit).where(Audit.website_id.in_(site_ids)).order_by(Audit.created_at.desc()).limit(8))).scalars().all()
    upcoming = (await db.execute(
        select(ReportSchedule).where(ReportSchedule.website_id.in_(site_ids), ReportSchedule.enabled.is_(True)).order_by(ReportSchedule.next_run_at).limit(5)
    )).scalars().all()

    # severity counts across the latest completed audit of each site
    counts: Dict[str, int] = {}
    latest_ids = []
    for sid in site_ids:
        a = (await db.execute(select(Audit.id).where(Audit.website_id == sid, Audit.status == "completed").order_by(Audit.finished_at.desc()).limit(1))).first()
        if a:
            latest_ids.append(a[0])
    if latest_ids:
        rows = (await db.execute(
            select(AuditIssue.severity, func.count()).where(AuditIssue.audit_id.in_(latest_ids)).group_by(AuditIssue.severity)
        )).all()
        counts = {sev: n for sev, n in rows}
    return DashboardOut(
        websites=len(site_ids), verified_websites=verified, audits_completed=audits_completed, open_tasks=open_tasks,
        tracked_keywords=keywords, avg_score=round(avg_score, 1) if avg_score is not None else None, reports_sent=reports_sent,
        recent_audits=[AuditSummaryOut.model_validate(a) for a in recent],
        upcoming_reports=[ReportScheduleOut.model_validate(s) for s in upcoming], open_issue_counts=counts,
        leads_total=sum(lead_counts.values()), leads_active=sum(lead_counts.get(k, 0) for k in ("contacted", "replied", "qualified")),
        leads_won=lead_counts.get("won", 0), follow_ups_due=follow_ups_due,
    )
