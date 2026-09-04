"""Google Analytics 4 (Data API v1beta) client + sync."""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from app.core.http import ssl_context
from app.models import Integration, Website
from app.services.google.auth import SCOPES, GoogleAuthError, get_access_token, network_error, parse_service_account

log = logging.getLogger(__name__)

API = "https://analyticsdata.googleapis.com/v1beta"


class GA4Client:
    def __init__(self, service_account_json: str | dict, property_id: str):
        self.sa = parse_service_account(service_account_json)
        pid = str(property_id).strip()
        self.property = pid if pid.startswith("properties/") else f"properties/{pid}"

    async def _headers(self) -> dict[str, str]:
        token = await get_access_token(self.sa, [SCOPES["ga4"]])
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def run_report(self, start: date, end: date, dimensions: list[str], metrics: list[str], limit: int = 100,
                         order_by_metric: str | None = None) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "dateRanges": [{"startDate": start.isoformat(), "endDate": end.isoformat()}],
            "dimensions": [{"name": d} for d in dimensions],
            "metrics": [{"name": m} for m in metrics],
            "limit": limit,
        }
        if order_by_metric:
            body["orderBys"] = [{"metric": {"metricName": order_by_metric}, "desc": True}]
        try:
            async with httpx.AsyncClient(timeout=60, verify=ssl_context()) as client:
                resp = await client.post(f"{API}/{self.property}:runReport", headers=await self._headers(), json=body)
        except httpx.HTTPError as exc:
            raise network_error("analyticsdata.googleapis.com", exc) from exc
        if resp.status_code != 200:
            try:
                msg = resp.json().get("error", {}).get("message", resp.text[:200])
            except Exception:
                msg = resp.text[:200]
            raise GoogleAuthError(f"GA4 runReport failed ({resp.status_code}): {msg}")
        data = resp.json()
        dim_names = [d["name"] for d in data.get("dimensionHeaders", [])]
        met_names = [m["name"] for m in data.get("metricHeaders", [])]
        rows = []
        for row in data.get("rows", []) or []:
            item: dict[str, Any] = {}
            for name, v in zip(dim_names, row.get("dimensionValues", []), strict=False):
                item[name] = v.get("value")
            for name, v in zip(met_names, row.get("metricValues", []), strict=False):
                raw = v.get("value", "0")
                item[name] = float(raw) if "." in raw else int(raw)
            rows.append(item)
        return rows


def _sum(rows: list[dict[str, Any]], metric: str) -> float:
    return sum(float(r.get(metric, 0) or 0) for r in rows)


async def sync_ga4(db, website: Website, integration: Integration, days: int = 28) -> dict[str, Any]:
    cfg = integration.config or {}
    client = GA4Client(cfg.get("service_account_json", ""), cfg.get("property_id", ""))
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    prev_start, prev_end = start - timedelta(days=days), start - timedelta(days=1)

    metrics = ["sessions", "totalUsers", "engagedSessions", "conversions", "averageSessionDuration"]
    daily = await client.run_report(start, end, ["date"], metrics, limit=100)
    prev_daily = await client.run_report(prev_start, prev_end, ["date"], ["sessions", "totalUsers", "conversions"], limit=100)
    channels = await client.run_report(start, end, ["sessionDefaultChannelGroup"], ["sessions", "conversions"], limit=20, order_by_metric="sessions")
    pages = await client.run_report(start, end, ["pagePath"], ["screenPageViews", "sessions"], limit=25, order_by_metric="screenPageViews")
    countries = await client.run_report(start, end, ["country"], ["sessions"], limit=10, order_by_metric="sessions")
    devices = await client.run_report(start, end, ["deviceCategory"], ["sessions"], limit=5, order_by_metric="sessions")

    daily.sort(key=lambda r: r.get("date", ""))
    sessions = _sum(daily, "sessions")
    totals = {
        "sessions": int(sessions), "users": int(_sum(daily, "totalUsers")), "engaged_sessions": int(_sum(daily, "engagedSessions")),
        "conversions": int(_sum(daily, "conversions")),
        "avg_session_duration": round(_sum(daily, "averageSessionDuration") / max(len(daily), 1), 1),
        "prev_sessions": int(_sum(prev_daily, "sessions")), "prev_users": int(_sum(prev_daily, "totalUsers")), "prev_conversions": int(_sum(prev_daily, "conversions")),
    }
    totals["engagement_rate"] = round(totals["engaged_sessions"] / sessions * 100, 1) if sessions else 0.0
    organic = next((c for c in channels if str(c.get("sessionDefaultChannelGroup", "")).lower().startswith("organic search")), None)
    totals["organic_sessions"] = int(organic["sessions"]) if organic else 0
    totals["organic_share"] = round(totals["organic_sessions"] / sessions * 100, 1) if sessions else 0.0

    integration.status = "connected"
    integration.connected_at = integration.connected_at or datetime.now(UTC)
    integration.last_synced_at = datetime.now(UTC)
    integration.last_error = ""
    integration.summary = {
        "property": client.property, "period": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "totals": totals,
        "daily": [{"date": f"{r['date'][:4]}-{r['date'][4:6]}-{r['date'][6:]}", "sessions": r.get("sessions", 0), "users": r.get("totalUsers", 0), "conversions": r.get("conversions", 0)} for r in daily],
        "channels": [{"channel": r.get("sessionDefaultChannelGroup"), "sessions": r.get("sessions", 0), "conversions": r.get("conversions", 0)} for r in channels],
        "top_pages": [{"path": r.get("pagePath"), "views": r.get("screenPageViews", 0), "sessions": r.get("sessions", 0)} for r in pages],
        "countries": [{"country": r.get("country"), "sessions": r.get("sessions", 0)} for r in countries],
        "devices": [{"device": r.get("deviceCategory"), "sessions": r.get("sessions", 0)} for r in devices],
    }
    await db.flush()
    return integration.summary
