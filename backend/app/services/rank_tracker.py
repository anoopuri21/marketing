"""Keyword rank checking.

Providers:
  * serpapi  – real Google SERP data when SERPAPI_KEY is configured.
  * none     – graceful no-op that records an 'unchecked' data point so the UI still works.

Adding another provider (DataForSEO, ValueSERP, Google Search Console) = one more function.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.http import ssl_context
from app.models import Keyword, KeywordRank, Website

log = logging.getLogger(__name__)


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


async def _serpapi_lookup(term: str, domain: str, location: str, language: str) -> Dict:
    params = {
        "engine": "google", "q": term, "api_key": settings.serpapi_key, "num": 100, "hl": language or "en",
    }
    if location:
        params["location"] = location
    async with httpx.AsyncClient(timeout=60, verify=ssl_context()) as client:
        resp = await client.get("https://serpapi.com/search.json", params=params)
        resp.raise_for_status()
        data = resp.json()
    position: Optional[int] = None
    url = ""
    for item in data.get("organic_results", []) or []:
        link = item.get("link", "")
        if link and _host(link) == domain:
            position = item.get("position")
            url = link
            break
    features = {
        "ai_overview": bool(data.get("ai_overview")),
        "featured_snippet": bool(data.get("answer_box")),
        "people_also_ask": len(data.get("related_questions", []) or []),
        "local_pack": bool(data.get("local_results")),
    }
    return {"position": position, "url": url, "features": features, "provider": "serpapi"}


async def check_keyword(db, keyword: Keyword, website: Website) -> KeywordRank:
    provider = settings.resolved_serp_provider
    domain = _host(website.url)
    if provider == "serpapi":
        try:
            res = await _serpapi_lookup(keyword.term, domain, keyword.location, keyword.language)
        except Exception as exc:
            log.warning("serpapi failed for %s: %s", keyword.term, exc)
            res = {"position": None, "url": "", "features": {"error": str(exc)[:200]}, "provider": "serpapi"}
    else:
        res = {"position": None, "url": "", "features": {"note": "No SERP provider configured. Set SERPAPI_KEY to enable live rank checks."}, "provider": "none"}
    rank = KeywordRank(
        keyword_id=keyword.id, checked_at=datetime.now(timezone.utc), position=res["position"], url=res["url"],
        engine="google", provider=res["provider"], features=res["features"],
    )
    db.add(rank)
    return rank


async def check_all_for_website(db, website_id: int) -> int:
    website = await db.get(Website, website_id)
    if website is None:
        return 0
    keywords = (await db.execute(select(Keyword).where(Keyword.website_id == website_id))).scalars().all()
    for kw in keywords:
        await check_keyword(db, kw, website)
    await db.flush()
    return len(keywords)


def enrich_keyword(kw: Keyword) -> dict:
    """Attach latest/previous position to a keyword (ranks must be loaded, ordered desc)."""
    ranks = list(kw.ranks)
    checked = [r for r in ranks if r.provider not in ("", "none")]
    latest = checked[0] if checked else None
    prev = checked[1] if len(checked) > 1 else None
    return {
        "latest_position": latest.position if latest else None,
        "previous_position": prev.position if prev else None,
        "latest_url": latest.url if latest else "",
        "last_checked_at": latest.checked_at if latest else None,
    }


async def load_keywords(db, website_id: int) -> List[Keyword]:
    stmt = (
        select(Keyword).where(Keyword.website_id == website_id)
        .options(selectinload(Keyword.ranks)).order_by(Keyword.created_at.desc())
    )
    return (await db.execute(stmt)).scalars().all()
