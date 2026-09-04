"""Lead finder API: discover prospects, qualify them (mini audit + pitch), manage the pipeline."""
from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, OwnedWebsite
from app.core.config import settings
from app.core.errors import UpstreamError
from app.models import Lead
from app.services.leads import service as leads_service
from app.services.leads.pitch import write_pitch
from app.services.leads.service import (
    discover_and_save,
    lead_to_dict,
    normalize_url,
    pipeline_summary,
    qualify_lead,
    qualify_leads_in_background,
    set_status,
    website_ctx,
)
from app.services.leads.sources import host_of

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/websites/{website_id}/leads", tags=["leads"])


# --------------------------------------------------------------------------- #
# schemas
# --------------------------------------------------------------------------- #
class DiscoverIn(BaseModel):
    query: str = Field(..., min_length=2, max_length=120, description="Business type / service, e.g. 'dentist', 'interior designer'")
    location: str = Field("", max_length=120)
    mode: str = Field("maps", pattern="^(maps|organic|both)$")
    limit: int = Field(20, ge=1, le=60)
    qualify: bool = True  # queue mini audits in the background


class LeadIn(BaseModel):
    company: str = Field(..., min_length=1, max_length=255)
    contact_name: str = ""
    email: str = ""
    phone: str = ""
    website_url: str = ""
    category: str = ""
    location: str = ""
    address: str = ""
    notes: str = ""
    tags: list[str] = Field(default_factory=list)


class LeadUpdate(BaseModel):
    company: str | None = None
    contact_name: str | None = None
    email: str | None = None
    phone: str | None = None
    website_url: str | None = None
    category: str | None = None
    location: str | None = None
    address: str | None = None
    notes: str | None = None
    tags: list[str] | None = None
    status: str | None = None
    next_follow_up_at: datetime | None = None
    activity_note: str | None = None  # append a note to the timeline


class StatusIn(BaseModel):
    status: str
    note: str = ""
    schedule_follow_up_days: int | None = Field(None, ge=0, le=90)


class BulkIn(BaseModel):
    ids: list[int]
    action: str = Field(..., pattern="^(qualify|delete|status)$")
    status: str | None = None


class PitchIn(BaseModel):
    tone: str = "friendly"


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #
@router.get("/summary")
async def summary(website: OwnedWebsite, db: DB):
    return await pipeline_summary(db, website.id)


@router.get("")
async def list_leads(website: OwnedWebsite, db: DB, status: str | None = None, campaign: str | None = None,
                     q: str | None = None, min_score: int = 0, sort: str = Query("score", pattern="^(score|created|company|follow_up)$"),
                     limit: int = Query(200, ge=1, le=1000)):
    statuses = [s for s in status.split(",") if s] if status else None
    rows = await leads_service.list_leads(db, website.id, statuses=statuses, campaign=campaign, q=q, min_score=min_score, sort=sort, limit=limit)
    return [lead_to_dict(l) for l in rows]


@router.get("/campaigns")
async def campaigns(website: OwnedWebsite, db: DB):
    rows = (await db.execute(select(Lead.campaign, Lead.search_query, Lead.location, Lead.source).where(Lead.website_id == website.id, Lead.campaign != "").distinct())).all()
    return [{"campaign": c, "query": q, "location": loc, "source": s} for c, q, loc, s in sorted(rows, key=lambda r: r[0], reverse=True)]


@router.post("/discover")
async def discover(payload: DiscoverIn, website: OwnedWebsite, db: DB, background: BackgroundTasks):
    if settings.resolved_lead_provider == "none":
        raise HTTPException(400, "Lead discovery is disabled on this server (LEAD_PROVIDER=none).")
    try:
        res = await discover_and_save(db, website, payload.query.strip(), payload.location.strip(), mode=payload.mode, limit=payload.limit)
    except Exception as exc:
        log.warning("discovery failed: %s", exc)
        raise UpstreamError(f"Discovery failed: {str(exc)[:200]}") from exc
    if payload.qualify and res["leads"]:
        background.add_task(qualify_leads_in_background, [l["id"] for l in res["leads"]], website.id)
    return res


@router.post("", status_code=201)
async def create_lead(payload: LeadIn, website: OwnedWebsite, db: DB, background: BackgroundTasks, qualify: bool = True):
    lead = Lead(website_id=website.id, company=payload.company.strip(), contact_name=payload.contact_name.strip(), email=payload.email.strip(),
                phone=payload.phone.strip(), website_url=normalize_url(payload.website_url), category=payload.category.strip(),
                location=payload.location.strip(), address=payload.address.strip(), notes=payload.notes, tags=payload.tags,
                source="manual", status="new", score=0, audit={}, pitch={},
                activity=[{"at": datetime.now(UTC).isoformat(), "kind": "created", "note": "Added manually"}])
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    if qualify:
        background.add_task(qualify_leads_in_background, [lead.id], website.id)
    return lead_to_dict(lead)


@router.post("/import")
async def import_csv(website: OwnedWebsite, db: DB, background: BackgroundTasks, file: UploadFile, qualify: bool = True):
    """CSV with headers (any order, case-insensitive): company, website, phone, email, contact, category, location, address, notes."""
    raw = await file.read()
    if len(raw) > 2 * 1024 * 1024:
        raise HTTPException(413, "CSV larger than 2 MB")
    text = raw.decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(400, "CSV has no header row")
    alias = {"company": "company", "name": "company", "business": "company", "website": "website_url", "url": "website_url", "site": "website_url",
             "phone": "phone", "mobile": "phone", "email": "email", "contact": "contact_name", "contact_name": "contact_name", "person": "contact_name",
             "category": "category", "type": "category", "industry": "category", "location": "location", "city": "location",
             "address": "address", "notes": "notes", "note": "notes"}
    existing_hosts = {host_of(l.website_url) for l in (await db.execute(select(Lead).where(Lead.website_id == website.id))).scalars().all() if l.website_url}
    created: list[Lead] = []
    skipped = 0
    for row in reader:
        data: dict[str, str] = {}
        for k, v in row.items():
            key = alias.get((k or "").strip().lower().replace(" ", "_"))
            if key and v:
                data[key] = str(v).strip()
        if not data.get("company") and not data.get("website_url"):
            skipped += 1
            continue
        url = normalize_url(data.get("website_url", ""))
        h = host_of(url)
        if h and h in existing_hosts:
            skipped += 1
            continue
        if h:
            existing_hosts.add(h)
        lead = Lead(website_id=website.id, company=data.get("company") or h, website_url=url, phone=data.get("phone", ""), email=data.get("email", ""),
                    contact_name=data.get("contact_name", ""), category=data.get("category", ""), location=data.get("location", ""),
                    address=data.get("address", ""), notes=data.get("notes", ""), source="csv", status="new", score=0, audit={}, pitch={}, tags=[],
                    activity=[{"at": datetime.now(UTC).isoformat(), "kind": "created", "note": f"Imported from {file.filename}"}])
        db.add(lead)
        created.append(lead)
        if len(created) >= 500:
            break
    await db.commit()
    for l in created:
        await db.refresh(l)
    if qualify and created:
        background.add_task(qualify_leads_in_background, [l.id for l in created], website.id)
    return {"created": len(created), "skipped": skipped, "leads": [lead_to_dict(l) for l in created]}


@router.get("/export.csv")
async def export_csv(website: OwnedWebsite, db: DB, status: str | None = None):
    stmt = select(Lead).where(Lead.website_id == website.id)
    if status:
        stmt = stmt.where(Lead.status.in_(status.split(",")))
    rows = (await db.execute(stmt.order_by(Lead.score.desc()))).scalars().all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["company", "website", "phone", "email", "contact", "category", "location", "address", "rating", "reviews", "status", "opportunity_score",
                "website_score", "top_gaps", "pitch_angle", "source", "created_at"])
    for l in rows:
        gaps = "; ".join(g.get("label", "") for g in (l.audit or {}).get("gaps", [])[:3])
        w.writerow([l.company, l.website_url, l.phone, l.email, l.contact_name, l.category, l.location, l.address, l.rating, l.reviews, l.status,
                    l.score, l.website_score, gaps, (l.pitch or {}).get("angle", ""), l.source, l.created_at.isoformat() if l.created_at else ""])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="leads-{website.domain}.csv"'})


@router.get("/{lead_id}")
async def get_lead(lead_id: int, website: OwnedWebsite, db: DB):
    return lead_to_dict(await leads_service.get_lead(db, website.id, lead_id))


@router.patch("/{lead_id}")
async def update_lead(lead_id: int, payload: LeadUpdate, website: OwnedWebsite, db: DB):
    lead = await leads_service.get_lead(db, website.id, lead_id)
    data = payload.model_dump(exclude_unset=True)
    note = data.pop("activity_note", None)
    status = data.pop("status", None)
    if "website_url" in data:
        data["website_url"] = normalize_url(data["website_url"] or "")
    for k, v in data.items():
        setattr(lead, k, v)
    if status and status != lead.status:
        set_status(lead, status)
    if note:
        lead.activity = (lead.activity or []) + [{"at": datetime.now(UTC).isoformat(), "kind": "note", "note": note[:1000]}]
    await db.commit()
    await db.refresh(lead)
    return lead_to_dict(lead)


@router.post("/{lead_id}/status")
async def change_status(lead_id: int, payload: StatusIn, website: OwnedWebsite, db: DB):
    lead = await leads_service.get_lead(db, website.id, lead_id)
    set_status(lead, payload.status, payload.note)
    if payload.schedule_follow_up_days is not None:
        lead.next_follow_up_at = datetime.now(UTC) + timedelta(days=payload.schedule_follow_up_days)
    elif payload.status == "contacted" and lead.next_follow_up_at is None:
        days = ((lead.pitch or {}).get("follow_ups") or [{}])[0].get("day", 3)
        lead.next_follow_up_at = datetime.now(UTC) + timedelta(days=int(days or 3))
    elif payload.status in ("won", "lost"):
        lead.next_follow_up_at = None
    await db.commit()
    await db.refresh(lead)
    return lead_to_dict(lead)


@router.post("/{lead_id}/qualify")
async def qualify(lead_id: int, website: OwnedWebsite, db: DB):
    lead = await leads_service.get_lead(db, website.id, lead_id)
    lead = await qualify_lead(db, lead, website)
    return lead_to_dict(lead)


@router.post("/{lead_id}/pitch")
async def regenerate_pitch(lead_id: int, payload: PitchIn, website: OwnedWebsite, db: DB):
    lead = await leads_service.get_lead(db, website.id, lead_id)
    lead.pitch = await write_pitch(website_ctx(website), lead_to_dict(lead), tone=payload.tone)
    lead.activity = (lead.activity or []) + [{"at": datetime.now(UTC).isoformat(), "kind": "pitch", "note": f"Pitch rewritten ({payload.tone})"}]
    await db.commit()
    await db.refresh(lead)
    return lead_to_dict(lead)


@router.delete("/{lead_id}", status_code=204)
async def delete_lead(lead_id: int, website: OwnedWebsite, db: DB):
    lead = await leads_service.get_lead(db, website.id, lead_id)
    await db.delete(lead)
    await db.commit()


@router.post("/bulk")
async def bulk(payload: BulkIn, website: OwnedWebsite, db: DB, background: BackgroundTasks):
    rows = (await db.execute(select(Lead).where(Lead.website_id == website.id, Lead.id.in_(payload.ids)))).scalars().all()
    if payload.action == "delete":
        for l in rows:
            await db.delete(l)
        await db.commit()
        return {"updated": len(rows)}
    if payload.action == "status":
        for l in rows:
            set_status(l, payload.status or "")
        await db.commit()
        return {"updated": len(rows)}
    # qualify (re-run even if already qualified)
    for l in rows:
        l.qualified_at = None
        l.qualify_error = ""
    await db.commit()
    background.add_task(qualify_leads_in_background, [l.id for l in rows], website.id)
    return {"updated": len(rows), "queued": True}
