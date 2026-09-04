"""Lead pipeline service: discovery → dedupe/save → qualification (mini audit + pitch) → pipeline updates.

`qualify_lead` is used both by the API (on demand) and the scheduler (`process_lead_qualification`) so newly
discovered prospects are audited and get a pitch in the background without the user waiting.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import func, select

from app.core.config import settings
from app.models import Lead, Website
from app.models.entities import aware
from app.services.leads.pitch import write_pitch
from app.services.leads.qualifier import opportunity_score, qualify_website
from app.services.leads.sources import discover, host_of

log = logging.getLogger(__name__)

STATUSES = ["new", "contacted", "replied", "qualified", "won", "lost"]


def website_ctx(website: Website) -> Dict[str, Any]:
    return {"name": website.name, "url": website.url, "domain": website.domain, "industry": website.industry,
            "target_location": website.target_location, "description": website.description}


def lead_to_dict(lead: Lead) -> Dict[str, Any]:
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


async def _existing_keys(db, website_id: int) -> Dict[str, Lead]:
    rows = (await db.execute(select(Lead).where(Lead.website_id == website_id))).scalars().all()
    keys: Dict[str, Lead] = {}
    for l in rows:
        if l.place_id:
            keys[f"p:{l.place_id}"] = l
        h = host_of(l.website_url)
        if h:
            keys[f"h:{h}"] = l
        if l.company:
            keys[f"c:{l.company.strip().lower()}|{(l.location or '').strip().lower()}"] = l
    return keys


def _key_candidates(p: Dict[str, Any], location: str) -> List[str]:
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
                            exclude_own: bool = True) -> Dict[str, Any]:
    """Run discovery, skip duplicates + the client's own domain, persist new leads. Returns summary + leads."""
    res = await discover(query, location, mode=mode, limit=limit)
    prospects = res["prospects"]
    own_host = host_of(website.url)
    existing = await _existing_keys(db, website.id)
    campaign = f"find-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    created: List[Lead] = []
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
                {"at": datetime.now(timezone.utc).isoformat(), "kind": "discovered", "note": f"Found via {p.get('source') or res['provider']} for “{query}” in {location or 'anywhere'}"}
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
    audit: Dict[str, Any] = {}
    website_score: Optional[float] = None
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
    lead.qualified_at = datetime.now(timezone.utc)
    if force_pitch or not lead.pitch:
        try:
            lead.pitch = await write_pitch(website_ctx(website), lead_to_dict(lead), tone=tone)
        except Exception as exc:  # pragma: no cover
            log.warning("pitch failed for lead %s: %s", lead.id, exc)
    lead.activity = (lead.activity or []) + [{"at": datetime.now(timezone.utc).isoformat(), "kind": "qualified",
                                               "note": f"Website score {website_score if website_score is not None else '–'} · opportunity {lead.score}/100"}]
    await db.commit()
    await db.refresh(lead)
    return lead


def set_status(lead: Lead, status: str, note: str = "") -> None:
    if status not in STATUSES:
        raise ValueError(f"Unknown status {status}")
    now = datetime.now(timezone.utc)
    lead.status = status
    if status == "contacted":
        lead.last_contacted_at = now
    lead.activity = (lead.activity or []) + [{"at": now.isoformat(), "kind": "status", "note": note or f"Moved to {status}"}]


async def pipeline_summary(db, website_id: int) -> Dict[str, Any]:
    counts = dict((await db.execute(select(Lead.status, func.count()).where(Lead.website_id == website_id).group_by(Lead.status))).all())
    total = sum(counts.values())
    unqualified = (await db.execute(select(func.count()).where(Lead.website_id == website_id, Lead.qualified_at.is_(None)))).scalar() or 0
    due = (await db.execute(select(func.count()).where(Lead.website_id == website_id, Lead.next_follow_up_at.isnot(None), Lead.next_follow_up_at <= datetime.now(timezone.utc), Lead.status.notin_(["won", "lost"])))).scalar() or 0
    avg_score = (await db.execute(select(func.avg(Lead.score)).where(Lead.website_id == website_id))).scalar()
    return {"counts": {s: counts.get(s, 0) for s in STATUSES}, "total": total, "pending_qualification": unqualified,
            "follow_ups_due": due, "avg_score": round(float(avg_score), 1) if avg_score is not None else None,
            "provider": settings.resolved_lead_provider}


async def process_lead_qualification(session_factory: Callable, limit: Optional[int] = None) -> int:
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
