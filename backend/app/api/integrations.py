"""Integrations: credential vault + live sync for Google Search Console and GA4."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DB, OwnedWebsite
from app.models import Integration, SearchQueryStat
from app.schemas.all import IntegrationOut, IntegrationUpsert
from app.services.google.analytics import sync_ga4
from app.services.google.auth import GoogleAuthError
from app.services.google.search_console import sync_search_console

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["integrations"])

SUPPORTED_INTEGRATIONS: Dict[str, Dict[str, Any]] = {
    "google_search_console": {
        "label": "Google Search Console", "status": "live", "fields": ["service_account_json"], "optional_fields": ["site_url"],
        "help": "Create a service account in Google Cloud (enable the Search Console API), download its JSON key, "
                "and add the service-account email as a user (Full or Restricted) on the property in Search Console.",
    },
    "ga4": {
        "label": "Google Analytics 4", "status": "live", "fields": ["property_id", "service_account_json"], "optional_fields": [],
        "help": "Enable the Google Analytics Data API, then add the service-account email as a Viewer on the GA4 property. "
                "Property ID is the numeric ID from Admin → Property settings.",
    },
    "google_business_profile": {"label": "Google Business Profile", "status": "planned", "fields": ["location_id"], "optional_fields": [], "help": ""},
    "facebook": {"label": "Facebook Page", "status": "planned", "fields": ["page_id", "access_token"], "optional_fields": [], "help": ""},
    "instagram": {"label": "Instagram Business", "status": "planned", "fields": ["account_id", "access_token"], "optional_fields": [], "help": ""},
    "linkedin": {"label": "LinkedIn Page", "status": "planned", "fields": ["organization_id", "access_token"], "optional_fields": [], "help": ""},
    "x": {"label": "X (Twitter)", "status": "planned", "fields": ["api_key", "api_secret", "access_token", "access_secret"], "optional_fields": [], "help": ""},
}

SECRET_HINTS = ("token", "secret", "json", "password", "key")


def _mask(config: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in (config or {}).items():
        if v and any(h in k for h in SECRET_HINTS):
            if k == "service_account_json":
                try:
                    import json

                    email = json.loads(v).get("client_email", "") if isinstance(v, str) else v.get("client_email", "")
                    out[k] = f"•••••• ({email})" if email else "••••••"
                    continue
                except Exception:
                    pass
            out[k] = "••••••"
        else:
            out[k] = v
    return out


def _to_out(row: Integration) -> IntegrationOut:
    return IntegrationOut(
        id=row.id, provider=row.provider, status=row.status, connected_at=row.connected_at, config=_mask(row.config),
        last_synced_at=row.last_synced_at, last_error=row.last_error or "", summary=row.summary or {},
    )


async def _get(db, website_id: int, provider: str) -> Optional[Integration]:
    return (await db.execute(
        select(Integration).where(Integration.website_id == website_id, Integration.provider == provider)
    )).scalar_one_or_none()


@router.get("/integrations/catalog")
async def integrations_catalog():
    return SUPPORTED_INTEGRATIONS


@router.get("/websites/{website_id}/integrations", response_model=List[IntegrationOut])
async def list_integrations(website: OwnedWebsite, db: DB):
    rows = (await db.execute(select(Integration).where(Integration.website_id == website.id))).scalars().all()
    return [_to_out(r) for r in rows]


@router.put("/websites/{website_id}/integrations", response_model=IntegrationOut)
async def upsert_integration(payload: IntegrationUpsert, website: OwnedWebsite, db: DB):
    meta = SUPPORTED_INTEGRATIONS.get(payload.provider)
    if meta is None:
        raise HTTPException(status_code=400, detail=f"Unsupported provider. Supported: {', '.join(SUPPORTED_INTEGRATIONS)}")
    row = await _get(db, website.id, payload.provider)
    if row is None:
        row = Integration(website_id=website.id, provider=payload.provider)
        db.add(row)
    # ignore masked placeholders coming back from the UI
    incoming = {k: v for k, v in payload.config.items() if not (isinstance(v, str) and v.startswith("••••"))}
    row.config = {**(row.config or {}), **incoming}
    complete = all(row.config.get(f) for f in meta["fields"])
    row.status = "pending" if complete and meta["status"] == "live" else ("connected" if complete else "disconnected")
    row.last_error = ""
    await db.flush()

    if complete and meta["status"] == "live":
        try:
            await _sync(db, website, row)
        except GoogleAuthError as exc:
            row.status = "error"
            row.last_error = str(exc)
        except Exception as exc:  # pragma: no cover - network etc.
            log.exception("integration sync failed")
            row.status = "error"
            row.last_error = f"{type(exc).__name__}: {exc}"[:500]
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


async def _sync(db, website, row: Integration) -> Dict[str, Any]:
    if row.provider == "google_search_console":
        return await sync_search_console(db, website, row)
    if row.provider == "ga4":
        return await sync_ga4(db, website, row)
    raise HTTPException(status_code=400, detail="This integration does not support sync yet")


@router.post("/websites/{website_id}/integrations/{provider}/sync", response_model=IntegrationOut)
async def sync_integration(provider: str, website: OwnedWebsite, db: DB):
    row = await _get(db, website.id, provider)
    if row is None:
        raise HTTPException(status_code=404, detail="Integration not connected")
    try:
        await _sync(db, website, row)
    except GoogleAuthError as exc:
        row.status = "error"
        row.last_error = str(exc)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        log.exception("integration sync failed")
        row.status = "error"
        row.last_error = f"{type(exc).__name__}: {exc}"[:500]
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.delete("/websites/{website_id}/integrations/{provider}", status_code=204)
async def delete_integration(provider: str, website: OwnedWebsite, db: DB):
    row = await _get(db, website.id, provider)
    if row:
        await db.delete(row)
        await db.commit()
    return None


# --------------------------------------------------------------------------- #
# Search performance data (from the Search Console sync)
# --------------------------------------------------------------------------- #
class SearchStatOut(BaseModel):
    key: str
    clicks: int
    impressions: int
    ctr: float
    position: float
    prev_clicks: Optional[int] = None
    prev_position: Optional[float] = None


class SearchPerformanceOut(BaseModel):
    connected: bool
    synced_at: Optional[datetime] = None
    summary: Dict[str, Any] = {}
    queries: List[SearchStatOut] = []
    pages: List[SearchStatOut] = []
    opportunities: List[SearchStatOut] = []  # positions 5-20 with impressions: quick-win candidates
    error: str = ""


@router.get("/websites/{website_id}/search-performance", response_model=SearchPerformanceOut)
async def search_performance(website: OwnedWebsite, db: DB, limit: int = 100):
    row = await _get(db, website.id, "google_search_console")
    if row is None:
        return SearchPerformanceOut(connected=False)
    stats = (await db.execute(select(SearchQueryStat).where(SearchQueryStat.website_id == website.id))).scalars().all()
    queries = sorted([s for s in stats if s.kind == "query"], key=lambda s: (-s.clicks, -s.impressions))
    pages = sorted([s for s in stats if s.kind == "page"], key=lambda s: (-s.clicks, -s.impressions))
    opps = sorted([s for s in queries if 4.5 <= s.position <= 20 and s.impressions >= 20], key=lambda s: -s.impressions)
    conv = lambda s: SearchStatOut(key=s.key, clicks=s.clicks, impressions=s.impressions, ctr=round(s.ctr * 100, 2), position=round(s.position, 1),
                                   prev_clicks=s.prev_clicks, prev_position=round(s.prev_position, 1) if s.prev_position is not None else None)
    return SearchPerformanceOut(
        connected=row.status in ("connected", "error"), synced_at=row.last_synced_at, summary=row.summary or {},
        queries=[conv(s) for s in queries[:limit]], pages=[conv(s) for s in pages[:50]], opportunities=[conv(s) for s in opps[:25]],
        error=row.last_error or "",
    )


@router.get("/websites/{website_id}/analytics")
async def analytics(website: OwnedWebsite, db: DB):
    row = await _get(db, website.id, "ga4")
    if row is None:
        return {"connected": False}
    return {"connected": row.status in ("connected", "error"), "synced_at": row.last_synced_at, "summary": row.summary or {}, "error": row.last_error or ""}
