"""Dashboard + system status."""
from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.api.deps import DB, CurrentUser
from app.core.config import settings
from app.schemas.all import AuditSummaryOut, DashboardOut, ReportScheduleOut, SystemStatus
from app.services.dashboard import build_dashboard

router = APIRouter(prefix="/api", tags=["dashboard & system"])


@router.get("/system/status", response_model=SystemStatus)
async def system_status():
    return SystemStatus(
        app_name=settings.app_name, environment=settings.environment, ai_provider=settings.resolved_ai_provider,
        serp_provider=settings.resolved_serp_provider, email_backend=settings.resolved_email_backend, image_provider=settings.resolved_image_provider,
        lead_provider=settings.resolved_lead_provider, scheduler_enabled=settings.scheduler_enabled, version=__version__,
    )


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(user: CurrentUser, db: DB):
    stats = await build_dashboard(db, user.id)
    return DashboardOut(
        websites=stats.websites, verified_websites=stats.verified_websites, audits_completed=stats.audits_completed, open_tasks=stats.open_tasks,
        tracked_keywords=stats.tracked_keywords, avg_score=stats.avg_score, reports_sent=stats.reports_sent,
        recent_audits=[AuditSummaryOut.model_validate(a) for a in stats.recent_audits],
        upcoming_reports=[ReportScheduleOut.model_validate(s) for s in stats.upcoming_reports], open_issue_counts=stats.open_issue_counts,
        leads_total=stats.leads_total, leads_active=stats.leads_active, leads_won=stats.leads_won, follow_ups_due=stats.follow_ups_due,
    )
