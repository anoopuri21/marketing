from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.api.deps import DB, OwnedWebsite
from app.models import ReportRun, ReportSchedule
from app.schemas.all import (
    ReportRunOut,
    ReportScheduleCreate,
    ReportScheduleOut,
    ReportScheduleUpdate,
    ReportSendNowRequest,
)
from app.services.audit.engine import create_and_run_audit
from app.services.reports.generator import build_report_html, generate_and_send
from app.services.scheduler import compute_next_run

router = APIRouter(prefix="/api/websites/{website_id}/reports", tags=["reports"])


@router.get("/schedules", response_model=list[ReportScheduleOut])
async def list_schedules(website: OwnedWebsite, db: DB):
    return (await db.execute(select(ReportSchedule).where(ReportSchedule.website_id == website.id).order_by(ReportSchedule.id))).scalars().all()


@router.post("/schedules", response_model=ReportScheduleOut, status_code=201)
async def create_schedule(payload: ReportScheduleCreate, website: OwnedWebsite, db: DB):
    sched = ReportSchedule(website_id=website.id, **payload.model_dump())
    sched.recipients = [str(r).lower() for r in payload.recipients]
    sched.next_run_at = compute_next_run(sched)
    db.add(sched)
    await db.commit()
    await db.refresh(sched)
    return sched


@router.patch("/schedules/{schedule_id}", response_model=ReportScheduleOut)
async def update_schedule(schedule_id: int, payload: ReportScheduleUpdate, website: OwnedWebsite, db: DB):
    sched = await db.get(ReportSchedule, schedule_id)
    if sched is None or sched.website_id != website.id:
        raise HTTPException(status_code=404, detail="Schedule not found")
    data = payload.model_dump(exclude_unset=True)
    if "recipients" in data and data["recipients"] is not None:
        data["recipients"] = [str(r).lower() for r in data["recipients"]]
    for k, v in data.items():
        setattr(sched, k, v)
    sched.next_run_at = compute_next_run(sched)
    await db.commit()
    await db.refresh(sched)
    return sched


@router.delete("/schedules/{schedule_id}", status_code=204)
async def delete_schedule(schedule_id: int, website: OwnedWebsite, db: DB):
    sched = await db.get(ReportSchedule, schedule_id)
    if sched is None or sched.website_id != website.id:
        raise HTTPException(status_code=404, detail="Schedule not found")
    await db.delete(sched)
    await db.commit()


@router.get("/runs", response_model=list[ReportRunOut])
async def list_runs(website: OwnedWebsite, db: DB, limit: int = 30):
    return (await db.execute(
        select(ReportRun).where(ReportRun.website_id == website.id).order_by(ReportRun.created_at.desc()).limit(min(limit, 100))
    )).scalars().all()


@router.get("/runs/{run_id}/html", response_class=HTMLResponse)
async def run_html(run_id: int, website: OwnedWebsite, db: DB):
    run = await db.get(ReportRun, run_id)
    if run is None or run.website_id != website.id:
        raise HTTPException(status_code=404, detail="Report not found")
    return HTMLResponse(run.html or "<p>No content</p>")


@router.get("/preview", response_class=HTMLResponse)
async def preview(website: OwnedWebsite, db: DB, period: str = "weekly"):
    _, html, _ = await build_report_html(db, website, "monthly" if period == "monthly" else "weekly")
    return HTMLResponse(html)


@router.post("/send-now", response_model=ReportRunOut)
async def send_now(payload: ReportSendNowRequest, website: OwnedWebsite, db: DB):
    recipients = [str(r).lower() for r in (payload.recipients or [])]
    if not recipients:
        scheds = (await db.execute(select(ReportSchedule).where(ReportSchedule.website_id == website.id))).scalars().all()
        for s in scheds:
            recipients.extend(s.recipients)
    if not recipients:
        raise HTTPException(status_code=400, detail="No recipients: pass recipients or create a schedule first")
    website_id = website.id
    if payload.run_fresh_audit:
        await db.commit()
        await create_and_run_audit(website_id, trigger="report")
        website = (await db.execute(select(type(website)).where(type(website).id == website_id))).scalar_one()
    run = await generate_and_send(db, website, sorted(set(recipients)), payload.period)
    await db.commit()
    await db.refresh(run)
    return run
