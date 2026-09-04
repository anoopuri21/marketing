"""Lead finder: discovery providers (SerpAPI via MockTransport + demo), qualification, pitch and pipeline API."""
import asyncio
import io
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.services.audit import engine as engine_mod
from app.services.leads import qualifier as qual_mod
from app.services.leads import sources as src_mod
from tests.test_api import fake_crawl_site

ORIGINAL_ASYNC_CLIENT = httpx.AsyncClient  # captured at import time (other modules patch httpx.AsyncClient)


# --------------------------------------------------------------------------- #
# unit: providers
# --------------------------------------------------------------------------- #
def test_demo_prospects_deterministic_and_labelled():
    a = src_mod.demo_prospects("dentist", "Delhi", 6)
    b = src_mod.demo_prospects("dentist", "Delhi", 6)
    assert [p["company"] for p in a] == [p["company"] for p in b]
    assert len(a) == 6 and all(p["source"] == "demo" for p in a)
    assert all((not p["website_url"]) or p["website_url"].endswith((".example.com", ".example.net", ".example.org")) for p in a)


def test_directory_filter():
    assert src_mod.is_directory("https://www.justdial.com/Delhi/dentists")
    assert src_mod.is_directory("https://maps.google.com/x")
    assert src_mod.is_directory("https://en.wikipedia.org/wiki/Dentist")
    assert not src_mod.is_directory("https://smile-dental-clinic.in/")
    assert src_mod.host_of("HTTPS://WWW.Smile.IN/path") == "smile.in"


def _serpapi_handler(request: httpx.Request) -> httpx.Response:
    params = dict(request.url.params)
    assert params.get("api_key") == "test-key"
    if params.get("engine") == "google_maps":
        if params.get("start", "0") != "0":
            return httpx.Response(200, json={"local_results": []})
        return httpx.Response(200, json={"local_results": [
            {"title": "Smile Dental Clinic", "website": "https://smiledental.in", "phone": "+91 98765 43210", "address": "12 MG Road, Delhi", "rating": 4.6, "reviews": 120, "type": "Dentist", "place_id": "pl-1"},
            {"title": "City Dental Care", "phone": "011 2345 6789", "address": "5 Park Ave, Delhi", "rating": 3.9, "reviews": 12, "type": "Dental clinic", "place_id": "pl-2"},
            {"title": "Testco Own", "website": "https://testco.example", "place_id": "pl-own"},
        ]})
    return httpx.Response(200, json={"organic_results": [
        {"title": "Best Dentists in Delhi - Justdial", "link": "https://www.justdial.com/Delhi/Dentists", "snippet": "directory"},
        {"title": "Bright Smiles | Dental Implants Delhi", "link": "https://brightsmiles.co.in/services", "source": "Bright Smiles", "snippet": "implants"},
        {"title": "Bright Smiles blog", "link": "https://brightsmiles.co.in/blog", "snippet": "dup host"},
        {"title": "Smile Dental Clinic", "link": "https://www.smiledental.in/", "snippet": "dup of maps"},
    ]})


@pytest.fixture()
def serpapi(monkeypatch):
    transport = httpx.MockTransport(_serpapi_handler)

    class Patched(ORIGINAL_ASYNC_CLIENT):
        def __init__(self, *args, **kwargs):
            kwargs.pop("verify", None)
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(src_mod.httpx, "AsyncClient", Patched)
    monkeypatch.setattr(src_mod.settings, "serpapi_key", "test-key")
    monkeypatch.setattr(src_mod.settings, "lead_provider", "serpapi")
    yield


def test_serpapi_maps_and_organic(serpapi):
    maps = asyncio.run(src_mod.serpapi_maps("dentist", "Delhi", limit=10))
    assert [p["company"] for p in maps] == ["Smile Dental Clinic", "City Dental Care", "Testco Own"]
    assert maps[0]["phone"] == "+91 98765 43210" and maps[0]["rating"] == 4.6 and maps[0]["source"] == "serpapi_maps"
    organic = asyncio.run(src_mod.serpapi_organic("dentist", "Delhi", limit=10))
    # directory dropped, duplicate host collapsed, company from `source`
    assert [p["website_url"] for p in organic] == ["https://brightsmiles.co.in", "https://smiledental.in"]
    assert organic[0]["company"] == "Bright Smiles"
    both = asyncio.run(src_mod.discover("dentist", "Delhi", mode="both", limit=10))
    assert both["provider"] == "serpapi"
    hosts = [src_mod.host_of(p["website_url"]) for p in both["prospects"] if p["website_url"]]
    assert hosts.count("smiledental.in") == 1 and "brightsmiles.co.in" in hosts


# --------------------------------------------------------------------------- #
# unit: qualification + pitch
# --------------------------------------------------------------------------- #
def test_gaps_and_opportunity_score():
    facts = {"https": False, "sitemap_found": False, "robots_txt_found": True, "schema_types": [], "faq_pages": 0, "question_headings": 0,
             "home_ttfb_ms": 2500, "avg_word_count": 120, "llms_txt_found": False}
    gaps = qual_mod.gaps_from_analysis(facts, [{"code": "NO_CONTACT_SIGNALS", "title": "No contact"}], {})
    codes = [g["code"] for g in gaps]
    assert codes[0] == "NO_HTTPS" and "NO_SCHEMA" in codes and "SLOW_TTFB" in codes and "THIN_CONTENT" in codes and "NO_CONTACT" in codes
    weak = qual_mod.opportunity_score(gaps, 35.0, {"phone": "+91 1", "reviews": 40, "rating": 4.2})
    strong = qual_mod.opportunity_score([], 92.0, {"phone": "", "reviews": 0, "rating": 4.9})
    no_site = qual_mod.opportunity_score([qual_mod._gap("NO_WEBSITE")], None, {"phone": "+91 1", "reviews": 25, "rating": 4.0})
    assert weak > 60 and strong < 15 and no_site >= 70
    assert strong >= 0 and no_site <= 100


def test_qualify_website_uses_crawler(monkeypatch):
    monkeypatch.setattr(qual_mod, "crawl_site", fake_crawl_site)
    res = asyncio.run(qual_mod.qualify_website("https://testco.example"))
    assert res["pages_crawled"] == 2 and res["website_score"] is not None and not res["unreachable"]
    assert any(g["code"] == "NO_SITEMAP" for g in res["gaps"])
    demo = asyncio.run(qual_mod.qualify_website("https://x.example.com"))
    assert demo.get("demo") and 0 < demo["website_score"] < 100


def test_rule_based_pitch_personalises():
    from app.services.leads.pitch import rule_based_pitch

    site = {"name": "Testco", "url": "https://testco.example", "industry": "web design", "target_location": "Delhi", "description": ""}
    lead = {"company": "Smile Dental Clinic", "website_url": "https://smiledental.in", "location": "Delhi", "category": "Dentist", "website_score": 41.0,
            "audit": {"gaps": [qual_mod._gap("NO_SCHEMA"), qual_mod._gap("SLOW_TTFB", "2500 ms"), qual_mod._gap("NO_FAQ")]}}
    p = rule_based_pitch(site, lead)
    assert p["provider"] == "rule-based" and "Smile Dental Clinic" in p["email"]["subject"]
    assert "41/100" in p["email"]["body"] and "structured data" in p["email"]["body"].lower()
    assert "Testco" in p["email"]["body"] and len(p["follow_ups"]) == 2 and p["whatsapp"].startswith("Hi there")
    no_site = rule_based_pitch(site, {"company": "City Dental Care", "website_url": "", "location": "Delhi", "audit": {"gaps": []}})
    assert "no website" in no_site["angle"].lower()


# --------------------------------------------------------------------------- #
# API flow (demo provider, crawler faked)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    engine_mod.crawl_site = fake_crawl_site  # type: ignore[assignment]
    original = qual_mod.crawl_site
    qual_mod.crawl_site = fake_crawl_site  # type: ignore[assignment]
    try:
        from app.main import app

        with TestClient(app) as c:
            yield c
    finally:
        qual_mod.crawl_site = original  # type: ignore[assignment]


@pytest.fixture(scope="module")
def auth(client: TestClient) -> dict:
    r = client.post("/api/auth/register", json={"email": "leads@testco.example", "password": "secret123", "full_name": "Leads Owner"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def site_id(client: TestClient, auth: dict) -> int:
    r = client.post("/api/websites", json={"url": "https://testco.example", "name": "Testco", "industry": "web design", "target_location": "Delhi"}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_discover_dedupe_and_background_qualify(client: TestClient, auth: dict, site_id: int):
    assert client.get("/api/system/status").json()["lead_provider"] == "demo"
    r = client.post(f"/api/websites/{site_id}/leads/discover", json={"query": "dentist", "location": "Delhi", "limit": 6}, headers=auth)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["provider"] == "demo" and d["created"] == 6 and d["campaign"].startswith("find-")
    assert all(l["status"] == "new" and l["source"] == "demo" for l in d["leads"])
    # same search again → all duplicates skipped
    r2 = client.post(f"/api/websites/{site_id}/leads/discover", json={"query": "dentist", "location": "Delhi", "limit": 6}, headers=auth)
    assert r2.json()["created"] == 0 and r2.json()["skipped"] == 6
    # background task ran inside TestClient → leads are qualified with a pitch
    leads = client.get(f"/api/websites/{site_id}/leads?sort=score", headers=auth).json()
    assert len(leads) == 6
    assert all(l["qualified_at"] for l in leads), [l["qualify_error"] for l in leads]
    assert all(l["pitch"].get("email", {}).get("subject") for l in leads)
    assert leads[0]["score"] >= leads[-1]["score"]
    no_site = [l for l in leads if not l["website_url"]]
    if no_site:
        assert no_site[0]["audit"]["gaps"][0]["code"] == "NO_WEBSITE"
    summary = client.get(f"/api/websites/{site_id}/leads/summary", headers=auth).json()
    assert summary["total"] == 6 and summary["counts"]["new"] == 6 and summary["pending_qualification"] == 0
    camps = client.get(f"/api/websites/{site_id}/leads/campaigns", headers=auth).json()
    assert camps and camps[0]["query"] == "dentist"


def test_manual_lead_real_crawl_qualify_and_pipeline(client: TestClient, auth: dict, site_id: int):
    r = client.post(f"/api/websites/{site_id}/leads?qualify=false", json={"company": "Acme Web", "website_url": "acme-web.test", "contact_name": "Riya Sharma", "location": "Delhi"}, headers=auth)
    assert r.status_code == 201, r.text
    lead = r.json()
    assert lead["website_url"] == "https://acme-web.test" and lead["qualified_at"] is None
    q = client.post(f"/api/websites/{site_id}/leads/{lead['id']}/qualify", headers=auth).json()
    assert q["qualified_at"] and q["website_score"] is not None and q["audit"]["pages_crawled"] == 2
    assert "Riya" in q["pitch"]["email"]["body"]
    # pipeline: contacted → follow-up auto scheduled from the pitch cadence
    s = client.post(f"/api/websites/{site_id}/leads/{lead['id']}/status", json={"status": "contacted", "note": "Sent intro email"}, headers=auth).json()
    assert s["status"] == "contacted" and s["last_contacted_at"] and s["next_follow_up_at"]
    assert s["activity"][-1]["note"] == "Sent intro email"
    # patch with note + tags; invalid status rejected
    p = client.patch(f"/api/websites/{site_id}/leads/{lead['id']}", json={"tags": ["hot"], "activity_note": "Owner interested", "email": "riya@acme-web.test"}, headers=auth).json()
    assert p["tags"] == ["hot"] and p["activity"][-1]["note"] == "Owner interested" and p["email"] == "riya@acme-web.test"
    assert client.post(f"/api/websites/{site_id}/leads/{lead['id']}/status", json={"status": "bogus"}, headers=auth).status_code == 400
    won = client.post(f"/api/websites/{site_id}/leads/{lead['id']}/status", json={"status": "won"}, headers=auth).json()
    assert won["next_follow_up_at"] is None
    # regenerate pitch with a different tone
    rp = client.post(f"/api/websites/{site_id}/leads/{lead['id']}/pitch", json={"tone": "professional"}, headers=auth).json()
    assert rp["pitch"]["provider"] == "rule-based" and rp["activity"][-1]["kind"] == "pitch"
    # filters
    assert len(client.get(f"/api/websites/{site_id}/leads?status=won", headers=auth).json()) == 1
    assert len(client.get(f"/api/websites/{site_id}/leads?q=acme", headers=auth).json()) == 1


def test_csv_import_export_bulk_and_isolation(client: TestClient, auth: dict, site_id: int):
    csv_bytes = (b"Company,Website,Phone,City,Notes\nBeta Bakers,beta-bakers.test,+91 90000 00000,Delhi,walk-in\n"
                 b"Dup Bakers,https://beta-bakers.test/x,,Delhi,dup host\n,,,,\nGamma Gym,,,Noida,no site\n")
    r = client.post(f"/api/websites/{site_id}/leads/import?qualify=false", files={"file": ("leads.csv", io.BytesIO(csv_bytes), "text/csv")}, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 2 and r.json()["skipped"] == 2
    ids = [l["id"] for l in r.json()["leads"]]
    b = client.post(f"/api/websites/{site_id}/leads/bulk", json={"ids": ids, "action": "qualify"}, headers=auth).json()
    assert b["updated"] == 2 and b["queued"]
    after = {l["id"]: l for l in client.get(f"/api/websites/{site_id}/leads", headers=auth).json()}
    assert all(after[i]["qualified_at"] for i in ids)
    gym = next(l for l in after.values() if l["company"] == "Gamma Gym")
    assert gym["audit"]["gaps"][0]["code"] == "NO_WEBSITE" and gym["score"] >= 45
    st = client.post(f"/api/websites/{site_id}/leads/bulk", json={"ids": ids, "action": "status", "status": "lost"}, headers=auth).json()
    assert st["updated"] == 2
    exp = client.get(f"/api/websites/{site_id}/leads/export.csv?status=lost", headers=auth)
    assert exp.status_code == 200 and exp.headers["content-type"].startswith("text/csv")
    assert "Beta Bakers" in exp.text and "Gamma Gym" in exp.text and "Acme Web" not in exp.text
    # tenant isolation: another user cannot see these leads
    other = client.post("/api/auth/register", json={"email": "other-leads@testco.example", "password": "secret123", "full_name": "Other"}).json()["access_token"]
    assert client.get(f"/api/websites/{site_id}/leads", headers={"Authorization": f"Bearer {other}"}).status_code == 404
    d = client.post(f"/api/websites/{site_id}/leads/bulk", json={"ids": ids, "action": "delete"}, headers=auth).json()
    assert d["updated"] == 2
    assert client.get(f"/api/websites/{site_id}/leads/{ids[0]}", headers=auth).status_code == 404


def test_scheduler_qualifies_pending_leads(client: TestClient, auth: dict, site_id: int):
    from app.core.database import session_scope
    from app.services.leads.service import process_lead_qualification

    r = client.post(f"/api/websites/{site_id}/leads?qualify=false", json={"company": "Pending Co", "website_url": "https://pending.test"}, headers=auth).json()
    assert r["qualified_at"] is None
    assert client.get(f"/api/websites/{site_id}/leads/summary", headers=auth).json()["pending_qualification"] == 1
    n = asyncio.run(process_lead_qualification(session_scope, limit=5))
    assert n == 1
    lead = client.get(f"/api/websites/{site_id}/leads/{r['id']}", headers=auth).json()
    assert lead["qualified_at"] and lead["pitch"]["email"]["subject"]
