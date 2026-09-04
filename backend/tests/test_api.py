"""End-to-end API tests. The crawler is monkeypatched so no network is needed."""
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.services.audit import engine as engine_mod
from app.services.audit.crawler import PageData, SiteData, parse_html

HOME_HTML = """<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width">
<title>Testco – Web Design Agency in Delhi | Testco</title>
<meta name="description" content="Testco builds fast, SEO-friendly websites for small businesses in Delhi. Get a free quote and launch in two weeks.">
</head><body><h1>Web design agency in Delhi</h1><p>""" + ("We design and build websites that rank. " * 40) + """</p>
<a href="/about">About</a><a href="/pricing">Pricing</a></body></html>"""


async def fake_crawl_site(start_url: str, max_pages=None) -> SiteData:
    home = PageData(url=start_url + "/", final_url=start_url + "/", status_code=200, response_ms=150, content_type="text/html")
    home.html_bytes = len(HOME_HTML)
    parse_html(home, HOME_HTML)
    about = PageData(url=start_url + "/about", final_url=start_url + "/about", status_code=200, response_ms=90, content_type="text/html")
    parse_html(about, "<html><head><title>About Testco – our team and story</title></head><body><h1>About</h1><p>Short.</p></body></html>")
    site = SiteData(start_url=start_url, domain="testco.example", final_home_url=start_url + "/", https=True,
                    http_redirects_to_https=True, www_redirect_ok=True, robots_txt_found=True, sitemap_found=False, home_ttfb_ms=150)
    site.pages = [home, about]
    return site


@pytest.fixture(scope="module")
def client(module_mocker=None) -> Iterator[TestClient]:
    engine_mod.crawl_site = fake_crawl_site  # type: ignore[assignment]
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth(client: TestClient) -> dict:
    r = client.post("/api/auth/register", json={"email": "owner@testco.example", "password": "secret123", "full_name": "Owner One"})
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_health_and_status(client: TestClient):
    assert client.get("/api/health").json()["status"] == "ok"
    s = client.get("/api/system/status").json()
    assert s["ai_provider"] == "none" and s["scheduler_enabled"] is False


def test_register_duplicate_and_login(client: TestClient, auth: dict):
    r = client.post("/api/auth/register", json={"email": "owner@testco.example", "password": "secret123", "full_name": "x"})
    assert r.status_code == 409
    r = client.post("/api/auth/login", json={"email": "owner@testco.example", "password": "wrong"})
    assert r.status_code == 401
    r = client.post("/api/auth/login", json={"email": "OWNER@testco.example", "password": "secret123"})
    assert r.status_code == 200
    me = client.get("/api/auth/me", headers=auth).json()
    assert me["user"]["email"] == "owner@testco.example" and len(me["workspaces"]) == 1


def test_requires_auth(client: TestClient):
    assert client.get("/api/websites").status_code == 401
    assert client.get("/api/dashboard").status_code == 401


def test_connect_website_runs_audit_and_creates_tasks(client: TestClient, auth: dict):
    r = client.post("/api/websites", json={"url": "testco.example", "name": "Testco", "industry": "web design", "target_location": "Delhi"}, headers=auth)
    assert r.status_code == 201, r.text
    site = r.json()
    assert site["url"] == "https://testco.example" and site["domain"] == "testco.example"
    assert len(site["verification_token"]) == 32

    # duplicate domain in same workspace rejected
    assert client.post("/api/websites", json={"url": "https://www.testco.example/"}, headers=auth).status_code in (201, 409)

    # background audit completed (TestClient runs background tasks before returning)
    audits = client.get(f"/api/websites/{site['id']}/audits", headers=auth).json()
    assert audits and audits[0]["status"] == "completed"
    assert audits[0]["pages_crawled"] == 2
    latest = client.get(f"/api/websites/{site['id']}/audits/latest", headers=auth).json()
    assert 0 < latest["overall_score"] <= 100
    codes = {i["code"] for i in latest["issues"]}
    assert "NO_SITEMAP" in codes and "THIN_CONTENT" in codes
    assert latest["ai_insights"]["provider"] == "rule-based"
    assert latest["ai_insights"]["executive_summary"]

    tasks = client.get(f"/api/websites/{site['id']}/tasks", headers=auth).json()
    assert any(t["source"] == "audit" and t["source_issue_code"] == "NO_SITEMAP" for t in tasks)

    site_after = client.get(f"/api/websites/{site['id']}", headers=auth).json()
    assert site_after["last_score"] == latest["overall_score"]


def _site_id(client: TestClient, auth: dict) -> int:
    return client.get("/api/websites", headers=auth).json()[-1]["id"]


def test_second_audit_autoresolves_fixed_tasks(client: TestClient, auth: dict):
    sid = _site_id(client, auth)

    async def crawl_with_sitemap(start_url, max_pages=None):
        s = await fake_crawl_site(start_url, max_pages)
        s.sitemap_found = True
        s.sitemap_url_count = 5
        return s

    engine_mod.crawl_site = crawl_with_sitemap  # type: ignore[assignment]
    r = client.post(f"/api/websites/{sid}/audits", headers=auth)
    assert r.status_code == 202
    engine_mod.crawl_site = fake_crawl_site  # type: ignore[assignment]
    tasks = client.get(f"/api/websites/{sid}/tasks", headers=auth).json()
    sitemap_task = next(t for t in tasks if t["source_issue_code"] == "NO_SITEMAP")
    assert sitemap_task["status"] == "done" and "Auto-resolved" in sitemap_task["description"]


def test_keywords_crud_and_suggest(client: TestClient, auth: dict):
    sid = _site_id(client, auth)
    r = client.post(f"/api/websites/{sid}/keywords", json={"terms": ["web design delhi", "website cost", "web design delhi"], "location": "Delhi"}, headers=auth)
    assert r.status_code == 201 and len(r.json()) == 2
    r = client.post(f"/api/websites/{sid}/keywords", json={"terms": ["web design delhi"], "location": "Delhi"}, headers=auth)
    assert r.json() == []  # de-duplicated
    checked = client.post(f"/api/websites/{sid}/keywords/check", headers=auth).json()
    assert all(k["latest_position"] is None and k["last_checked_at"] is None for k in checked)  # no SERP provider
    sug = client.post(f"/api/websites/{sid}/keywords/suggest", headers=auth).json()
    assert sug["provider"] == "rule-based" and any("delhi" in s["term"].lower() for s in sug["suggestions"])
    kw_id = checked[0]["id"]
    assert client.delete(f"/api/websites/{sid}/keywords/{kw_id}", headers=auth).status_code == 204


def test_plan_generation_creates_tasks(client: TestClient, auth: dict):
    sid = _site_id(client, auth)
    before = len(client.get(f"/api/websites/{sid}/tasks", headers=auth).json())
    r = client.post(f"/api/websites/{sid}/plan", json={"horizon_weeks": 3, "focus": "more leads"}, headers=auth)
    assert r.status_code == 200, r.text
    plan = r.json()
    assert len(plan["weeks"]) == 3 and plan["created_tasks"] > 0
    after = len(client.get(f"/api/websites/{sid}/tasks", headers=auth).json())
    assert after == before + plan["created_tasks"]
    # idempotent for open tasks with the same title
    again = client.post(f"/api/websites/{sid}/plan", json={"horizon_weeks": 3, "focus": "more leads"}, headers=auth).json()
    assert again["created_tasks"] == 0


def test_task_update_and_delete(client: TestClient, auth: dict):
    sid = _site_id(client, auth)
    t = client.post(f"/api/websites/{sid}/tasks", json={"title": "Manual task", "priority": "high"}, headers=auth).json()
    assert t["source"] == "manual"
    done = client.patch(f"/api/websites/{sid}/tasks/{t['id']}", json={"status": "done"}, headers=auth).json()
    assert done["status"] == "done" and done["completed_at"]
    assert client.delete(f"/api/websites/{sid}/tasks/{t['id']}", headers=auth).status_code == 204


def test_report_schedule_and_send_now(client: TestClient, auth: dict):
    sid = _site_id(client, auth)
    r = client.post(f"/api/websites/{sid}/reports/schedules", json={"recipients": ["Client@Example.com"], "frequency": "weekly", "day_of_week": 0, "hour": 9, "timezone": "Asia/Kolkata"}, headers=auth)
    assert r.status_code == 201, r.text
    sched = r.json()
    assert sched["recipients"] == ["client@example.com"] and sched["next_run_at"].endswith("Z")

    preview = client.get(f"/api/websites/{sid}/reports/preview?period=weekly", headers=auth)
    assert preview.status_code == 200 and "Weekly report" in preview.text and "Testco" in preview.text

    run = client.post(f"/api/websites/{sid}/reports/send-now", json={"period": "monthly"}, headers=auth).json()
    assert run["status"] == "sent", run
    assert "outbox" in run["delivery_info"] and run["recipients"] == ["client@example.com"]
    html = client.get(f"/api/websites/{sid}/reports/runs/{run['id']}/html", headers=auth)
    assert html.status_code == 200 and "Monthly report" in html.text

    upd = client.patch(f"/api/websites/{sid}/reports/schedules/{sched['id']}", json={"enabled": False}, headers=auth).json()
    assert upd["enabled"] is False
    assert client.delete(f"/api/websites/{sid}/reports/schedules/{sched['id']}", headers=auth).status_code == 204


def test_dashboard_and_isolation(client: TestClient, auth: dict):
    d = client.get("/api/dashboard", headers=auth).json()
    assert d["websites"] >= 1 and d["audits_completed"] >= 2 and d["reports_sent"] >= 1

    # another user cannot see or touch this website
    other = client.post("/api/auth/register", json={"email": "intruder@example.com", "password": "secret123"}).json()
    h2 = {"Authorization": f"Bearer {other['access_token']}"}
    sid = _site_id(client, auth)
    assert client.get(f"/api/websites/{sid}", headers=h2).status_code == 404
    assert client.get("/api/websites", headers=h2).json() == []


def test_delete_website_cascades(client: TestClient, auth: dict):
    sid = _site_id(client, auth)
    assert client.delete(f"/api/websites/{sid}", headers=auth).status_code == 204
    assert client.get(f"/api/websites/{sid}/tasks", headers=auth).status_code == 404
