"""Lead pipeline service: discovery → dedupe/save → qualification (mini audit + pitch) → pipeline updates.

`qualify_lead` is used both by the API (on demand) and the scheduler (`process_lead_qualification`) so newly
discovered prospects are audited and get a pitch in the background without the user waiting.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import ColumnElement

from app.core.config import settings
from app.core.database import session_scope
from app.core.errors import NotFoundError, ValidationError
from app.core.time import aware
from app.models import Lead, Website
from app.services.leads.pitch import write_pitch
from app.services.leads.qualifier import opportunity_score, qualify_website
from app.services.leads.sources import discover, host_of

log = logging.getLogger(__name__)

STATUSES = ["new", "contacted", "replied", "qualified", "won", "lost"]


def website_ctx(website: Website) -> dict[str, Any]:
    return {"name": website.name, "url": website.url, "domain": website.domain, "industry": website.industry,
            "target_location": website.target_location, "description": website.description}


def lead_to_dict(lead: Lead) -> dict[str, Any]:
    return {
        "id": lead.id, "website_id": lead.website_id, "company": lead.company, "contact_name": lead.contact_name,
        "email": lead.email, "phone": lead.phone, "website_url": lead.website_url, "source": lead.source,
        "score": lead.score, "status": lead.status, "notes": lead.notes, "category": lead.category, "location": lead.location,
        "address": lead.address, "rating": lead.rating, "reviews": lead.reviews, "place_id": lead.place_id,
        "search_query": lead.search_query, "campaign": lead.campaign, "tags": lead.tags or [],
        "qualified_at": aware(lead.qualified_at), "website_score": lead.website_score, "audit": lead.audit or {},
        "pitch": lead.pitch or {}, "qualify_error": lead.qualify_error,
        "last_contacted_at": aware(lead.last_contacted_at), "next_follow_up_at": aware(lead.next_follow_up_at),
        "activity": lead.activity or [], "created_at": aware(lead.created_at), "updated_at": aware(lead.updated_at),
    }


async def _existing_keys(db, website_id: int) -> dict[str, Lead]:
    rows = (await db.execute(select(Lead).where(Lead.website_id == website_id))).scalars().all()
    keys: dict[str, Lead] = {}
    for l in rows:
        if l.place_id:
            keys[f"p:{l.place_id}"] = l
        h = host_of(l.website_url)
        if h:
            keys[f"h:{h}"] = l
        if l.company:
            keys[f"c:{l.company.strip().lower()}|{(l.location or '').strip().lower()}"] = l
    return keys


def _key_candidates(p: dict[str, Any], location: str) -> list[str]:
    out = []
    if p.get("place_id"):
        out.append(f"p:{p['place_id']}")
    h = host_of(p.get("website_url") or "")
    if h:
        out.append(f"h:{h}")
    if p.get("company"):
        out.append(f"c:{p['company'].strip().lower()}|{location.strip().lower()}")
    return out


async def discover_and_save(db, website: Website, query: str, location: str, mode: str = "maps", limit: int = 20,
                            exclude_own: bool = True) -> dict[str, Any]:
    """Run discovery, skip duplicates + the client's own domain, persist new leads. Returns summary + leads."""
    res = await discover(query, location, mode=mode, limit=limit)
    prospects = res["prospects"]
    own_host = host_of(website.url)
    existing = await _existing_keys(db, website.id)
    campaign = f"find-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    created: list[Lead] = []
    skipped = 0
    for p in prospects:
        if exclude_own and own_host and host_of(p.get("website_url") or "") == own_host:
            skipped += 1
            continue
        keys = _key_candidates(p, location)
        if any(k in existing for k in keys):
            skipped += 1
            continue
        listing_score = opportunity_score([], None if not p.get("website_url") else 60.0, p)  # provisional until qualified
        lead = Lead(
            website_id=website.id, company=p.get("company") or host_of(p.get("website_url") or "") or "Unknown",
            website_url=p.get("website_url") or "", phone=p.get("phone") or "", address=p.get("address") or "",
            rating=p.get("rating"), reviews=p.get("reviews"), category=p.get("category") or query, location=location,
            place_id=p.get("place_id") or "", source=p.get("source") or res["provider"], search_query=query, campaign=campaign,
            score=listing_score, status="new", notes=p.get("snippet") or "", tags=[], audit={}, pitch={}, activity=[
                {"at": datetime.now(UTC).isoformat(), "kind": "discovered", "note": f"Found via {p.get('source') or res['provider']} for “{query}” in {location or 'anywhere'}"}
            ],
        )
        db.add(lead)
        created.append(lead)
        for k in keys:
            existing[k] = lead
    await db.commit()
    for l in created:
        await db.refresh(l)
    return {"provider": res["provider"], "note": res.get("note", ""), "found": len(prospects), "created": len(created),
            "skipped": skipped, "campaign": campaign, "leads": [lead_to_dict(l) for l in created]}


async def qualify_lead(db, lead: Lead, website: Website, tone: str = "friendly", force_pitch: bool = True) -> Lead:
    """Mini-audit the lead's website (if any), compute the opportunity score and write the pitch. Commits."""
    listing = {"phone": lead.phone, "rating": lead.rating, "reviews": lead.reviews}
    audit: dict[str, Any] = {}
    website_score: float | None = None
    lead.qualify_error = ""
    if lead.website_url:
        try:
            audit = await qualify_website(lead.website_url)
            website_score = audit.get("website_score")
        except Exception as exc:  # unreachable / timeout → treated as a gap, not a crash
            log.info("lead %s qualification crawl failed: %s", lead.id, exc)
            lead.qualify_error = str(exc)[:300]
            audit = {"website_score": None, "gaps": [{"code": "HOME_UNREACHABLE", "label": "Website is down or unreachable", "pitch": "getting the site back online and stable", "weight": 30, "detail": str(exc)[:120]}], "unreachable": True, "scores": {}, "facts": {}}
    else:
        audit = {"website_score": None, "gaps": [{"code": "NO_WEBSITE", "label": "No website found", "pitch": "a professional website that shows up on Google", "weight": 30, "detail": ""}], "unreachable": False, "scores": {}, "facts": {}}
    lead.audit = audit
    lead.website_score = website_score
    lead.score = opportunity_score(audit.get("gaps") or [], website_score, listing)
    lead.qualified_at = datetime.now(UTC)
    if force_pitch or not lead.pitch:
        try:
            lead.pitch = await write_pitch(website_ctx(website), lead_to_dict(lead), tone=tone)
        except Exception as exc:  # pragma: no cover
            log.warning("pitch failed for lead %s: %s", lead.id, exc)
    lead.activity = (lead.activity or []) + [{"at": datetime.now(UTC).isoformat(), "kind": "qualified",
                                               "note": f"Website score {website_score if website_score is not None else '–'} · opportunity {lead.score}/100"}]
    await db.commit()
    await db.refresh(lead)
    return lead


def set_status(lead: Lead, status: str, note: str = "") -> None:
    if status not in STATUSES:
        raise ValidationError(f"Unknown status {status}")
    now = datetime.now(UTC)
    lead.status = status
    if status == "contacted":
        lead.last_contacted_at = now
    lead.activity = (lead.activity or []) + [{"at": now.isoformat(), "kind": "status", "note": note or f"Moved to {status}"}]


async def pipeline_summary(db, website_id: int) -> dict[str, Any]:
    counts: dict[str, int] = {status: n for status, n in (await db.execute(select(Lead.status, func.count()).where(Lead.website_id == website_id).group_by(Lead.status))).all()}
    total = sum(counts.values())
    unqualified = (await db.execute(select(func.count()).where(Lead.website_id == website_id, Lead.qualified_at.is_(None)))).scalar() or 0
    due = (await db.execute(select(func.count()).where(Lead.website_id == website_id, Lead.next_follow_up_at.isnot(None), Lead.next_follow_up_at <= datetime.now(UTC), Lead.status.notin_(["won", "lost"])))).scalar() or 0
    avg_score = (await db.execute(select(func.avg(Lead.score)).where(Lead.website_id == website_id))).scalar()
    return {"counts": {s: counts.get(s, 0) for s in STATUSES}, "total": total, "pending_qualification": unqualified,
            "follow_ups_due": due, "avg_score": round(float(avg_score), 1) if avg_score is not None else None,
            "provider": settings.resolved_lead_provider}


async def get_lead(db: AsyncSession, website_id: int, lead_id: int) -> Lead:
    lead = (await db.execute(select(Lead).where(Lead.id == lead_id, Lead.website_id == website_id))).scalar_one_or_none()
    if lead is None:
        raise NotFoundError("Lead not found")
    return lead


SORT_ORDERS: dict[str, list[ColumnElement[Any]]] = {
    "score": [Lead.score.desc(), Lead.id.desc()],
    "created": [Lead.id.desc()],
    "company": [Lead.company.asc()],
    "follow_up": [Lead.next_follow_up_at.asc().nulls_last(), Lead.id.desc()],
}


async def list_leads(db: AsyncSession, website_id: int, *, statuses: list[str] | None = None, campaign: str | None = None,
                     q: str | None = None, min_score: int = 0, sort: str = "score", limit: int = 200) -> list[Lead]:
    stmt = select(Lead).where(Lead.website_id == website_id)
    if statuses:
        stmt = stmt.where(Lead.status.in_(statuses))
    if campaign:
        stmt = stmt.where(Lead.campaign == campaign)
    if min_score:
        stmt = stmt.where(Lead.score >= min_score)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Lead.company.ilike(like) | Lead.website_url.ilike(like) | Lead.category.ilike(like) | Lead.location.ilike(like) | Lead.notes.ilike(like))
    ordering = SORT_ORDERS.get(sort) or SORT_ORDERS["score"]
    return list((await db.execute(stmt.order_by(*ordering).limit(limit))).scalars().all())


def normalize_url(u: str) -> str:
    u = (u or "").strip()
    if u and "://" not in u:
        u = "https://" + u
    return u[:2048]


async def qualify_leads_in_background(lead_ids: list[int], website_id: int) -> None:
    """FastAPI BackgroundTasks entry point: runs after the response with its own session."""
    async with session_scope() as db:
        website = await db.get(Website, website_id)
        if website is None:
            return
        for lid in lead_ids:
            lead = await db.get(Lead, lid)
            if lead is None or lead.qualified_at is not None:
                continue
            try:
                await qualify_lead(db, lead, website)
            except Exception as exc:  # pragma: no cover
                log.warning("background qualify failed for lead %s: %s", lid, exc)
                lead.qualify_error = str(exc)[:300]
                await db.commit()


async def process_lead_qualification(session_factory: Callable, limit: int | None = None) -> int:
    """Scheduler hook: qualify newly discovered leads in the background. Returns number processed."""
    limit = limit or settings.lead_qualify_per_tick
    done = 0
    async with session_factory() as db:
        rows = (await db.execute(select(Lead).where(Lead.qualified_at.is_(None), Lead.qualify_error == "").order_by(Lead.id).limit(limit))).scalars().all()
        for lead in rows:
            website = await db.get(Website, lead.website_id)
            if website is None:
                continue
            try:
                await qualify_lead(db, lead, website)
                done += 1
            except Exception as exc:  # pragma: no cover
                log.warning("lead %s qualification failed: %s", lead.id, exc)
                lead.qualify_error = str(exc)[:300]
                await db.commit()
    return done
