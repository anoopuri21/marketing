from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, OwnedWebsite
from app.models import Audit
from app.schemas.all import AuditCreateResponse, AuditDetailOut, AuditSummaryOut
from app.services.audit.engine import run_audit

router = APIRouter(prefix="/api/websites/{website_id}/audits", tags=["audits"])


@router.get("", response_model=list[AuditSummaryOut])
async def list_audits(website: OwnedWebsite, db: DB, limit: int = 20):
    stmt = select(Audit).where(Audit.website_id == website.id).order_by(Audit.created_at.desc()).limit(min(limit, 100))
    return (await db.execute(stmt)).scalars().all()


@router.post("", response_model=AuditCreateResponse, status_code=202)
async def start_audit(website: OwnedWebsite, db: DB, background: BackgroundTasks):
    running = (await db.execute(
        select(Audit).where(Audit.website_id == website.id, Audit.status.in_(["queued", "running"]))
    )).scalars().first()
    if running:
        return AuditCreateResponse(audit=AuditSummaryOut.model_validate(running), message="An audit is already in progress")
    audit = Audit(website_id=website.id, status="queued", trigger="manual")
    db.add(audit)
    await db.commit()
    await db.refresh(audit)
    background.add_task(run_audit, audit.id)
    return AuditCreateResponse(audit=AuditSummaryOut.model_validate(audit), message="Audit started")


@router.get("/latest", response_model=AuditDetailOut)
async def latest_audit(website: OwnedWebsite, db: DB):
    stmt = (
        select(Audit).where(Audit.website_id == website.id, Audit.status == "completed")
        .options(selectinload(Audit.issues), selectinload(Audit.pages))
        .order_by(Audit.finished_at.desc()).limit(1)
    )
    audit = (await db.execute(stmt)).scalars().first()
    if audit is None:
        raise HTTPException(status_code=404, detail="No completed audit yet")
    return audit


@router.get("/{audit_id}", response_model=AuditDetailOut)
async def get_audit(audit_id: int, website: OwnedWebsite, db: DB):
    stmt = (
        select(Audit).where(Audit.id == audit_id, Audit.website_id == website.id)
        .options(selectinload(Audit.issues), selectinload(Audit.pages))
    )
    audit = (await db.execute(stmt)).scalars().first()
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found")
    return audit
