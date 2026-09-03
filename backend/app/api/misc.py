"""Dashboard, integrations, social drafts, system status."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app import __version__
from app.api.deps import DB, CurrentUser, OwnedWebsite
from app.core.config import settings
from app.models import Audit, AuditIssue, Integration, Keyword, ReportRun, ReportSchedule, Task, Website, Workspace
from app.schemas.all import AuditSummaryOut, DashboardOut, IntegrationOut, IntegrationUpsert, ReportScheduleOut, SystemStatus
from app.services.ai.insights import draft_social_posts

router = APIRouter(prefix="/api", tags=["dashboard & system"])

SUPPORTED_INTEGRATIONS = {
    "google_search_console": {"label": "Google Search Console", "fields": ["site_url", "service_account_json"], "status": "planned"},
    "ga4": {"label": "Google Analytics 4", "fields": ["property_id", "service_account_json"], "status": "planned"},
    "google_business_profile": {"label": "Google Business Profile", "fields": ["location_id"], "status": "planned"},
    "facebook": {"label": "Facebook Page", "fields": ["page_id", "access_token"], "status": "planned"},
    "instagram": {"label": "Instagram Business", "fields": ["account_id", "access_token"], "status": "planned"},
    "linkedin": {"label": "LinkedIn Page", "fields": ["organization_id", "access_token"], "status": "planned"},
    "x": {"label": "X (Twitter)", "fields": ["api_key", "api_secret", "access_token", "access_secret"], "status": "planned"},
}


@router.get("/system/status", response_model=SystemStatus)
async def system_status():
    return SystemStatus(
        app_name=settings.app_name, environment=settings.environment, ai_provider=settings.resolved_ai_provider,
        serp_provider=settings.resolved_serp_provider, email_backend=settings.resolved_email_backend,
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
    )


# --------------------------------------------------------------------------- #
# Integrations (credentials stored; live sync arrives in phase 2)
# --------------------------------------------------------------------------- #
@router.get("/integrations/catalog")
async def integrations_catalog():
    return SUPPORTED_INTEGRATIONS


@router.get("/websites/{website_id}/integrations", response_model=List[IntegrationOut])
async def list_integrations(website: OwnedWebsite, db: DB):
    rows = (await db.execute(select(Integration).where(Integration.website_id == website.id))).scalars().all()
    # never leak secrets back to the client
    out = []
    for r in rows:
        masked = {k: ("••••••" if any(s in k for s in ("token", "secret", "json", "password", "key")) and v else v) for k, v in (r.config or {}).items()}
        out.append(IntegrationOut(id=r.id, provider=r.provider, status=r.status, connected_at=r.connected_at, config=masked))
    return out


@router.put("/websites/{website_id}/integrations", response_model=IntegrationOut)
async def upsert_integration(payload: IntegrationUpsert, website: OwnedWebsite, db: DB):
    if payload.provider not in SUPPORTED_INTEGRATIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider. Supported: {', '.join(SUPPORTED_INTEGRATIONS)}")
    row = (await db.execute(select(Integration).where(Integration.website_id == website.id, Integration.provider == payload.provider))).scalar_one_or_none()
    if row is None:
        row = Integration(website_id=website.id, provider=payload.provider)
        db.add(row)
    row.config = {**(row.config or {}), **payload.config}
    required = SUPPORTED_INTEGRATIONS[payload.provider]["fields"]
    row.status = "connected" if all(row.config.get(f) for f in required) else "disconnected"
    row.connected_at = datetime.now(timezone.utc) if row.status == "connected" else None
    await db.commit()
    await db.refresh(row)
    masked = {k: ("••••••" if any(s in k for s in ("token", "secret", "json", "password", "key")) and v else v) for k, v in row.config.items()}
    return IntegrationOut(id=row.id, provider=row.provider, status=row.status, connected_at=row.connected_at, config=masked)


@router.delete("/websites/{website_id}/integrations/{provider}", status_code=204)
async def delete_integration(provider: str, website: OwnedWebsite, db: DB):
    row = (await db.execute(select(Integration).where(Integration.website_id == website.id, Integration.provider == provider))).scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.commit()
    return None


# --------------------------------------------------------------------------- #
# Social drafts (AI copywriter) – publishing connectors come in phase 2
# --------------------------------------------------------------------------- #
class SocialDraftRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=300)
    platforms: List[str] = Field(default_factory=lambda: ["instagram", "linkedin", "facebook"])
    tone: str = "friendly"


@router.post("/websites/{website_id}/social/draft")
async def social_draft(payload: SocialDraftRequest, website: OwnedWebsite):
    ctx = {"url": website.url, "name": website.name, "industry": website.industry, "target_location": website.target_location}
    return await draft_social_posts(ctx, payload.topic, payload.platforms[:5], payload.tone)
