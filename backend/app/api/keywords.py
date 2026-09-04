from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, OwnedWebsite
from app.models import Audit, AuditPage, Keyword
from app.schemas.all import KeywordCreate, KeywordDetailOut, KeywordOut, KeywordSuggestResponse
from app.services.ai.insights import suggest_keywords
from app.services.rank_tracker import check_all_for_website, check_keyword, enrich_keyword, load_keywords

router = APIRouter(prefix="/api/websites/{website_id}/keywords", tags=["keywords"])


def _to_out(kw: Keyword) -> KeywordOut:
    base = KeywordOut.model_validate(kw)
    for k, v in enrich_keyword(kw).items():
        setattr(base, k, v)
    return base


@router.get("", response_model=list[KeywordOut])
async def list_keywords(website: OwnedWebsite, db: DB):
    return [_to_out(k) for k in await load_keywords(db, website.id)]


@router.post("", response_model=list[KeywordOut], status_code=201)
async def add_keywords(payload: KeywordCreate, website: OwnedWebsite, db: DB):
    existing = {(k.term.lower(), k.location.lower()) for k in await load_keywords(db, website.id)}
    created = []
    for raw in payload.terms:
        term = " ".join(raw.split()).strip()
        if not term or (term.lower(), payload.location.lower()) in existing:
            continue
        kw = Keyword(website_id=website.id, term=term, location=payload.location.strip(), language=payload.language, source="manual")
        db.add(kw)
        created.append(kw)
        existing.add((term.lower(), payload.location.lower()))
    await db.commit()
    if not created:
        return []
    ids = [k.id for k in created]
    stmt = select(Keyword).where(Keyword.id.in_(ids)).options(selectinload(Keyword.ranks))
    return [_to_out(k) for k in (await db.execute(stmt)).scalars().all()]


@router.delete("/{keyword_id}", status_code=204)
async def delete_keyword(keyword_id: int, website: OwnedWebsite, db: DB):
    kw = await db.get(Keyword, keyword_id)
    if kw is None or kw.website_id != website.id:
        raise HTTPException(status_code=404, detail="Keyword not found")
    await db.delete(kw)
    await db.commit()


@router.get("/{keyword_id}", response_model=KeywordDetailOut)
async def keyword_detail(keyword_id: int, website: OwnedWebsite, db: DB):
    stmt = select(Keyword).where(Keyword.id == keyword_id, Keyword.website_id == website.id).options(selectinload(Keyword.ranks))
    kw = (await db.execute(stmt)).scalars().first()
    if kw is None:
        raise HTTPException(status_code=404, detail="Keyword not found")
    base = KeywordDetailOut.model_validate(kw)
    for k, v in enrich_keyword(kw).items():
        setattr(base, k, v)
    return base


@router.post("/check", response_model=list[KeywordOut])
async def check_ranks(website: OwnedWebsite, db: DB):
    await check_all_for_website(db, website.id)
    await db.commit()
    return [_to_out(k) for k in await load_keywords(db, website.id)]


@router.post("/{keyword_id}/check", response_model=KeywordOut)
async def check_one(keyword_id: int, website: OwnedWebsite, db: DB):
    kw = await db.get(Keyword, keyword_id)
    if kw is None or kw.website_id != website.id:
        raise HTTPException(status_code=404, detail="Keyword not found")
    await check_keyword(db, kw, website)
    await db.commit()
    stmt = select(Keyword).where(Keyword.id == keyword_id).options(selectinload(Keyword.ranks))
    refreshed = (await db.execute(stmt)).scalars().one()
    return _to_out(refreshed)


@router.post("/suggest", response_model=KeywordSuggestResponse)
async def suggest(website: OwnedWebsite, db: DB):
    latest = (await db.execute(
        select(Audit).where(Audit.website_id == website.id, Audit.status == "completed").order_by(Audit.finished_at.desc()).limit(1)
    )).scalars().first()
    texts, titles = [], []
    if latest:
        pages = (await db.execute(select(AuditPage).where(AuditPage.audit_id == latest.id).limit(15))).scalars().all()
        for p in pages:
            titles.append(p.title)
            texts.append((p.data or {}).get("text_sample", ""))
    existing = [k.term for k in await load_keywords(db, website.id)]
    ctx = {"url": website.url, "name": website.name, "industry": website.industry,
           "target_location": website.target_location, "description": website.description}
    return await suggest_keywords(ctx, texts, titles, existing)
