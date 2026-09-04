"""Google Search Console + GA4 integration tests.

Google's OAuth token endpoint and the two data APIs are served by an httpx MockTransport,
so the full flow (JWT signing → token → queries → local tables → report email) runs offline.
"""
import json
from collections.abc import Iterator
from datetime import UTC

import httpx
import pytest
from fastapi.testclient import TestClient

from app.services.audit import engine as engine_mod
from app.services.google import analytics as ga4_mod
from app.services.google import auth as auth_mod
from app.services.google import search_console as gsc_mod
from tests.test_api import fake_crawl_site

ORIGINAL_ASYNC_CLIENT = httpx.AsyncClient  # captured at import time, before any module patches it


def _service_account() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    return json.dumps({
        "type": "service_account", "project_id": "demo", "private_key_id": "abc123", "private_key": pem,
        "client_email": "rankpilot@demo.iam.gserviceaccount.com", "token_uri": "https://oauth2.googleapis.com/token",
    })


SA_JSON = _service_account()
CALLS: list = []
STATE = {"has_property": True, "ga4_error": False}


def _gsc_rows(dimension: str, prev: bool) -> list:
    if dimension == "query":
        rows = [
            ("web design delhi", 40, 900, 3.2), ("testco", 25, 120, 1.1), ("website redesign cost", 6, 400, 8.7),
            ("seo agency delhi", 2, 350, 14.2), ("free website audit", 1, 15, 9.0),
        ]
        if prev:
            rows = [(q, int(c * 0.8), int(i * 0.9), p + 1.0) for q, c, i, p in rows]
        return [{"keys": [q], "clicks": c, "impressions": i, "ctr": c / i, "position": p} for q, c, i, p in rows]
    if dimension == "page":
        return [{"keys": ["https://testco.example/"], "clicks": 60, "impressions": 1500, "ctr": 0.04, "position": 4.1},
                {"keys": ["https://testco.example/pricing"], "clicks": 14, "impressions": 285, "ctr": 0.049, "position": 6.3}]
    if dimension == "date":
        base = 2 if prev else 3
        return [{"keys": [f"2026-08-{d:02d}"], "clicks": base, "impressions": base * 25, "ctr": 0.04, "position": 5.0} for d in range(1, 29)]
    return []


def _ga4_response(body: dict) -> dict:
    dims = [d["name"] for d in body["dimensions"]]
    mets = [m["name"] for m in body["metrics"]]
    samples = {
        "date": [["20260801"], ["20260802"], ["20260803"]],
        "sessionDefaultChannelGroup": [["Organic Search"], ["Direct"], ["Referral"]],
        "pagePath": [["/"], ["/pricing"]],
        "country": [["India"], ["United States"]],
        "deviceCategory": [["mobile"], ["desktop"]],
    }
    rows = []
    for idx, dim_values in enumerate(samples[dims[0]]):
        values = []
        for m in mets:
            if m == "averageSessionDuration":
                values.append({"value": "95.5"})
            elif m == "conversions":
                values.append({"value": str(3 - idx)})
            else:
                values.append({"value": str(100 - idx * 30)})
        rows.append({"dimensionValues": [{"value": v} for v in dim_values], "metricValues": values})
    return {"dimensionHeaders": [{"name": d} for d in dims], "metricHeaders": [{"name": m} for m in mets], "rows": rows}


def _handler(request: httpx.Request) -> httpx.Response:
    CALLS.append((request.method, str(request.url)))
    url = str(request.url)
    if url == "https://oauth2.googleapis.com/token":
        form = dict(pair.split("=", 1) for pair in request.content.decode().split("&"))
        assert form["grant_type"].startswith("urn"), form
        assert form["assertion"].count(".") == 2  # header.payload.signature
        return httpx.Response(200, json={"access_token": "ya29.test", "expires_in": 3600, "token_type": "Bearer"})
    assert request.headers.get("Authorization") == "Bearer ya29.test"
    if url.endswith("/webmasters/v3/sites"):
        entries = [{"siteUrl": "sc-domain:testco.example", "permissionLevel": "siteOwner"}] if STATE["has_property"] else \
                  [{"siteUrl": "https://other.example/", "permissionLevel": "siteOwner"}]
        return httpx.Response(200, json={"siteEntry": entries})
    if "/searchAnalytics/query" in url:
        body = json.loads(request.content)
        prev = body["endDate"] < _period_start_marker()
        return httpx.Response(200, json={"rows": _gsc_rows(body["dimensions"][0], prev)})
    if url.endswith(":runReport"):
        if STATE["ga4_error"]:
            return httpx.Response(403, json={"error": {"message": "User does not have sufficient permissions for this property."}})
        return httpx.Response(200, json=_ga4_response(json.loads(request.content)))
    return httpx.Response(404, json={"error": "unexpected url " + url})


def _period_start_marker() -> str:
    """The current period starts 29 days before today-2; anything ending before that is the 'previous' period."""
    from datetime import date, timedelta

    return (date.today() - timedelta(days=2 + 27)).isoformat()


@pytest.fixture(scope="module")
def client(module_mocker=None) -> Iterator[TestClient]:
    engine_mod.crawl_site = fake_crawl_site  # type: ignore[assignment]
    transport = httpx.MockTransport(_handler)

    class PatchedAsyncClient(ORIGINAL_ASYNC_CLIENT):
        def __init__(self, *args, **kwargs):
            kwargs.pop("verify", None)
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    for mod in (auth_mod, gsc_mod, ga4_mod):
        mod.httpx.AsyncClient = PatchedAsyncClient  # type: ignore[attr-defined]
    try:
        from app.main import app

        with TestClient(app) as c:
            yield c
    finally:
        for mod in (auth_mod, gsc_mod, ga4_mod):
            mod.httpx.AsyncClient = ORIGINAL_ASYNC_CLIENT  # type: ignore[attr-defined]
        auth_mod.clear_token_cache()


@pytest.fixture(scope="module")
def auth(client: TestClient) -> dict:
    r = client.post("/api/auth/register", json={"email": "gsc@testco.example", "password": "secret123", "full_name": "GSC Owner"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def site_id(client: TestClient, auth: dict) -> int:
    r = client.post("/api/websites", json={"url": "https://testco.example", "name": "Testco"}, headers=auth)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    client.post(f"/api/websites/{sid}/keywords", json={"terms": ["web design delhi", "not ranking yet"]}, headers=auth)
    return sid


def test_catalog_marks_google_integrations_live(client: TestClient):
    cat = client.get("/api/integrations/catalog").json()
    assert cat["google_search_console"]["status"] == "live" and cat["ga4"]["status"] == "live"
    assert "service_account_json" in cat["ga4"]["fields"]


def test_service_account_validation(client: TestClient, auth: dict, site_id: int):
    r = client.put(f"/api/websites/{site_id}/integrations", json={"provider": "google_search_console", "config": {"service_account_json": "{not json"}}, headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "error" and "valid JSON" in body["last_error"]
    r = client.put(f"/api/websites/{site_id}/integrations", json={"provider": "nope", "config": {}}, headers=auth)
    assert r.status_code == 400


def test_search_console_connect_syncs_and_feeds_keywords(client: TestClient, auth: dict, site_id: int):
    CALLS.clear()
    r = client.put(f"/api/websites/{site_id}/integrations", json={"provider": "google_search_console", "config": {"service_account_json": SA_JSON}}, headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "connected", body["last_error"]
    assert body["last_error"] == "" and body["last_synced_at"]
    assert body["config"]["site_url"] == "sc-domain:testco.example"
    assert body["config"]["service_account_json"].startswith("••••")  # secret never leaves the server
    assert "rankpilot@demo.iam.gserviceaccount.com" in body["config"]["service_account_json"]
    summary = body["summary"]
    assert summary["totals"]["clicks"] == 3 * 28 and summary["totals"]["prev_clicks"] == 2 * 28
    assert summary["queries"] == 5 and summary["matched_keywords"] == 1
    assert sum(1 for m, u in CALLS if u.endswith("/token")) == 1  # token cached across the 6 API calls

    perf = client.get(f"/api/websites/{site_id}/search-performance", headers=auth).json()
    assert perf["connected"] is True
    assert perf["queries"][0]["key"] == "web design delhi" and perf["queries"][0]["prev_clicks"] == 32
    assert [p["key"] for p in perf["pages"]] == ["https://testco.example/", "https://testco.example/pricing"]
    opp_keys = [o["key"] for o in perf["opportunities"]]
    assert opp_keys == ["website redesign cost", "seo agency delhi"]  # pos 5-20 with >=20 impressions, sorted by impressions

    kws = client.get(f"/api/websites/{site_id}/keywords", headers=auth).json()
    tracked = {k["term"]: k for k in kws}
    assert tracked["web design delhi"]["latest_position"] == 3
    assert tracked["not ranking yet"]["latest_position"] is None
    detail = client.get(f"/api/websites/{site_id}/keywords/{tracked['web design delhi']['id']}", headers=auth).json()
    assert detail["ranks"] and detail["ranks"][0]["provider"] == "search_console"


def test_search_console_without_property_access_reports_actionable_error(client: TestClient, auth: dict, site_id: int):
    STATE["has_property"] = False
    try:
        r = client.post(f"/api/websites/{site_id}/integrations/google_search_console/sync", headers=auth)
    finally:
        STATE["has_property"] = True
    body = r.json()
    assert body["status"] == "error"
    assert "rankpilot@demo.iam.gserviceaccount.com" in body["last_error"] and "https://other.example/" in body["last_error"]
    # previous data remains available while the connection is in error state
    perf = client.get(f"/api/websites/{site_id}/search-performance", headers=auth).json()
    assert perf["connected"] is True and perf["error"] and len(perf["queries"]) == 5
    # a successful re-sync clears the error
    body = client.post(f"/api/websites/{site_id}/integrations/google_search_console/sync", headers=auth).json()
    assert body["status"] == "connected" and body["last_error"] == ""


def test_ga4_connect_and_error_paths(client: TestClient, auth: dict, site_id: int):
    r = client.put(f"/api/websites/{site_id}/integrations", json={"provider": "ga4", "config": {"property_id": "123456", "service_account_json": SA_JSON}}, headers=auth)
    body = r.json()
    assert body["status"] == "connected", body["last_error"]
    totals = body["summary"]["totals"]
    assert totals["sessions"] == 100 + 70 + 40 and totals["conversions"] == 6
    assert totals["organic_sessions"] == 100 and totals["organic_share"] == 47.6
    assert body["summary"]["daily"][0]["date"] == "2026-08-01"
    assert body["summary"]["property"] == "properties/123456"

    a = client.get(f"/api/websites/{site_id}/analytics", headers=auth).json()
    assert a["connected"] is True and a["summary"]["channels"][0]["channel"] == "Organic Search"

    STATE["ga4_error"] = True
    try:
        body = client.post(f"/api/websites/{site_id}/integrations/ga4/sync", headers=auth).json()
    finally:
        STATE["ga4_error"] = False
    assert body["status"] == "error" and "sufficient permissions" in body["last_error"]
    client.post(f"/api/websites/{site_id}/integrations/ga4/sync", headers=auth)


def test_report_includes_google_data(client: TestClient, auth: dict, site_id: int):
    html = client.get(f"/api/websites/{site_id}/reports/preview?period=weekly", headers=auth).text
    assert "Google performance" in html
    assert "web design delhi" in html and "Quick-win opportunities" in html and "website redesign cost" in html
    assert "Organic share" in html and "47.6%" in html


def test_scheduler_sync_respects_interval(client: TestClient, auth: dict, site_id: int):
    import asyncio

    from app.services import scheduler

    # Both integrations were synced moments ago → nothing due
    assert asyncio.run(scheduler.process_integration_syncs()) == 0
    # Force them due by rewinding last_synced_at
    from datetime import datetime, timedelta

    from sqlalchemy import update

    from app.core.database import session_scope
    from app.models import Integration

    async def rewind():
        async with session_scope() as db:
            await db.execute(update(Integration).values(last_synced_at=datetime.now(UTC) - timedelta(days=2)))

    asyncio.run(rewind())
    assert asyncio.run(scheduler.process_integration_syncs()) == 2
    assert asyncio.run(scheduler.process_integration_syncs()) == 0


def test_delete_integration(client: TestClient, auth: dict, site_id: int):
    assert client.delete(f"/api/websites/{site_id}/integrations/ga4", headers=auth).status_code == 204
    assert client.get(f"/api/websites/{site_id}/analytics", headers=auth).json() == {"connected": False}
    providers = [i["provider"] for i in client.get(f"/api/websites/{site_id}/integrations", headers=auth).json()]
    assert providers == ["google_search_console"]


def test_additive_migration_adds_new_columns(tmp_path):
    """Databases created before this release get the new Integration columns on startup."""
    import sqlite3

    from sqlalchemy import create_engine, inspect

    from app.core.database import _add_missing_columns

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE integrations (id INTEGER PRIMARY KEY, website_id INTEGER, provider VARCHAR(50), status VARCHAR(30), config JSON, connected_at DATETIME)")
    con.commit()
    con.close()
    eng = create_engine(f"sqlite:///{path}")
    with eng.begin() as conn:
        _add_missing_columns(conn)
    cols = {c["name"] for c in inspect(eng).get_columns("integrations")}
    assert {"last_synced_at", "last_error", "summary"} <= cols
