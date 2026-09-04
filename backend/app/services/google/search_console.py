"""Google Search Console (Search Analytics API) client + sync into local tables."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy import delete, select

from app.core.http import ssl_context
from app.models import Integration, Keyword, KeywordRank, SearchQueryStat, Website
from app.services.google.auth import SCOPES, GoogleAuthError, get_access_token, network_error, parse_service_account

log = logging.getLogger(__name__)

API = "https://searchconsole.googleapis.com/webmasters/v3"


def candidate_property_urls(website_url: str) -> List[str]:
    """Search Console properties can be URL-prefix or Domain properties; try the usual forms."""
    parsed = urlparse(website_url)
    host = parsed.netloc.lower()
    bare = host.removeprefix("www.")
    return list(dict.fromkeys([
        f"sc-domain:{bare}",
        f"{parsed.scheme}://{host}/",
        f"https://{bare}/",
        f"https://www.{bare}/",
        f"http://{bare}/",
        f"http://www.{bare}/",
    ]))


class SearchConsoleClient:
    def __init__(self, service_account_json: str | dict):
        self.sa = parse_service_account(service_account_json)

    async def _headers(self) -> Dict[str, str]:
        token = await get_access_token(self.sa, [SCOPES["gsc"]])
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def list_sites(self) -> List[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=30, verify=ssl_context()) as client:
                resp = await client.get(f"{API}/sites", headers=await self._headers())
        except httpx.HTTPError as exc:
            raise network_error("searchconsole.googleapis.com", exc) from exc
        if resp.status_code != 200:
            raise GoogleAuthError(f"Search Console sites.list failed ({resp.status_code}): {resp.text[:200]}")
        return resp.json().get("siteEntry", []) or []

    async def resolve_property(self, website_url: str, preferred: str = "") -> Optional[str]:
        sites = {s["siteUrl"]: s.get("permissionLevel", "") for s in await self.list_sites()}
        if preferred and preferred in sites:
            return preferred
        for cand in candidate_property_urls(website_url):
            if cand in sites and sites[cand] != "siteUnverifiedUser":
                return cand
        return None

    async def query(self, site_url: str, start: date, end: date, dimensions: List[str], row_limit: int = 1000,
                    filters: Optional[List[Dict[str, str]]] = None) -> List[Dict[str, Any]]:
        body: Dict[str, Any] = {
            "startDate": start.isoformat(), "endDate": end.isoformat(), "dimensions": dimensions,
            "rowLimit": row_limit, "dataState": "final",
        }
        if filters:
            body["dimensionFilterGroups"] = [{"filters": filters}]
        from urllib.parse import quote

        url = f"{API}/sites/{quote(site_url, safe='')}/searchAnalytics/query"
        try:
            async with httpx.AsyncClient(timeout=60, verify=ssl_context()) as client:
                resp = await client.post(url, headers=await self._headers(), json=body)
        except httpx.HTTPError as exc:
            raise network_error("searchconsole.googleapis.com", exc) from exc
        if resp.status_code != 200:
            raise GoogleAuthError(f"Search Console query failed ({resp.status_code}): {resp.text[:300]}")
        return resp.json().get("rows", []) or []


# --------------------------------------------------------------------------- #
# Sync
# --------------------------------------------------------------------------- #
async def sync_search_console(db, website: Website, integration: Integration, days: int = 28) -> Dict[str, Any]:
    """Pull query + page stats for the last N days (GSC data lags ~2 days)."""
    cfg = integration.config or {}
    client = SearchConsoleClient(cfg.get("service_account_json", ""))
    prop = await client.resolve_property(website.url, cfg.get("site_url", ""))
    if not prop:
        sites = await client.list_sites()
        available = ", ".join(s["siteUrl"] for s in sites) or "none"
        raise GoogleAuthError(
            f"The service account has no access to a Search Console property for {website.domain}. "
            f"Add {client.sa['client_email']} as a user in Search Console. Properties visible: {available}"
        )
    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=days - 1)
    prev_start, prev_end = start - timedelta(days=days), start - timedelta(days=1)

    queries = await client.query(prop, start, end, ["query"], row_limit=500)
    pages = await client.query(prop, start, end, ["page"], row_limit=200)
    prev_queries = await client.query(prop, prev_start, prev_end, ["query"], row_limit=500)
    totals_rows = await client.query(prop, start, end, ["date"], row_limit=100)
    prev_totals_rows = await client.query(prop, prev_start, prev_end, ["date"], row_limit=100)

    # Replace this period's snapshot
    await db.execute(delete(SearchQueryStat).where(SearchQueryStat.website_id == website.id))
    prev_by_query = {r["keys"][0]: r for r in prev_queries}
    for r in queries:
        q = r["keys"][0]
        prev = prev_by_query.get(q)
        db.add(SearchQueryStat(
            website_id=website.id, kind="query", key=q, clicks=int(r.get("clicks", 0)), impressions=int(r.get("impressions", 0)),
            ctr=float(r.get("ctr", 0.0)), position=float(r.get("position", 0.0)),
            prev_clicks=int(prev.get("clicks", 0)) if prev else None, prev_position=float(prev.get("position", 0.0)) if prev else None,
            period_start=start, period_end=end,
        ))
    for r in pages:
        db.add(SearchQueryStat(
            website_id=website.id, kind="page", key=r["keys"][0], clicks=int(r.get("clicks", 0)), impressions=int(r.get("impressions", 0)),
            ctr=float(r.get("ctr", 0.0)), position=float(r.get("position", 0.0)), period_start=start, period_end=end,
        ))
    daily = [{"date": r["keys"][0], "clicks": r.get("clicks", 0), "impressions": r.get("impressions", 0), "position": round(r.get("position", 0), 1)} for r in totals_rows]
    totals = {
        "clicks": sum(r.get("clicks", 0) for r in totals_rows), "impressions": sum(r.get("impressions", 0) for r in totals_rows),
        "prev_clicks": sum(r.get("clicks", 0) for r in prev_totals_rows), "prev_impressions": sum(r.get("impressions", 0) for r in prev_totals_rows),
    }
    imp = totals["impressions"]
    totals["avg_position"] = round(sum(r.get("position", 0) * r.get("impressions", 0) for r in totals_rows) / imp, 1) if imp else None
    totals["ctr"] = round(totals["clicks"] / imp * 100, 2) if imp else 0.0

    # Feed tracked keywords with real Google positions (provider = search_console)
    keywords = (await db.execute(select(Keyword).where(Keyword.website_id == website.id))).scalars().all()
    by_term = {r["keys"][0].lower(): r for r in queries}
    matched = 0
    for kw in keywords:
        r = by_term.get(kw.term.lower())
        if not r:
            continue
        matched += 1
        db.add(KeywordRank(
            keyword_id=kw.id, checked_at=datetime.now(timezone.utc), position=int(round(r.get("position", 0))) or None,
            url="", engine="google", provider="search_console",
            features={"clicks": r.get("clicks", 0), "impressions": r.get("impressions", 0), "ctr": round(r.get("ctr", 0) * 100, 2), "period_days": days},
        ))

    integration.status = "connected"
    integration.connected_at = integration.connected_at or datetime.now(timezone.utc)
    integration.last_synced_at = datetime.now(timezone.utc)
    integration.last_error = ""
    integration.summary = {
        "property": prop, "period": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "totals": totals, "daily": daily, "queries": len(queries), "pages": len(pages), "matched_keywords": matched,
    }
    integration.config = {**cfg, "site_url": prop}
    await db.flush()
    return integration.summary
