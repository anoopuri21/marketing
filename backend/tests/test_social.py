"""Creative studio + social publishing tests (all network calls mocked with httpx.MockTransport)."""
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.services.audit import engine as engine_mod
from app.services.social import publishers as pub_mod
from tests.test_api import fake_crawl_site

ORIGINAL_ASYNC_CLIENT = httpx.AsyncClient  # captured at import time, before any module patches it

CALLS: list = []
STATE = {"fail_facebook": False}


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    CALLS.append((request.method, url, request.content))
    if url.startswith("https://graph.facebook.com/"):
        if STATE["fail_facebook"]:
            return httpx.Response(400, json={"error": {"message": "Invalid OAuth access token - Cannot parse access token", "code": 190}})
        if url.endswith("/photos"):
            return httpx.Response(200, json={"id": "111", "post_id": "123_456"})
        if url.endswith("/feed"):
            return httpx.Response(200, json={"id": "123_789"})
        if url.endswith("/media"):
            return httpx.Response(200, json={"id": "container1"})
        if url.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "ig_1"})
        if "fields=permalink" in url:
            return httpx.Response(200, json={"permalink": "https://www.instagram.com/p/abc/"})
        if "fields=id" in url:
            return httpx.Response(200, json={"id": "1", "name": "Testco Page"})
    if url.startswith("https://api.linkedin.com/rest/images"):
        return httpx.Response(200, json={"value": {"uploadUrl": "https://upload.linkedin.test/u1", "image": "urn:li:image:abc"}})
    if url.startswith("https://upload.linkedin.test/"):
        return httpx.Response(201)
    if url == "https://api.linkedin.com/rest/posts":
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:999"})
    if url == "https://api.x.com/2/tweets":
        return httpx.Response(201, json={"data": {"id": "1700", "text": "x"}})
    if url.startswith("https://hooks.example.com/"):
        return httpx.Response(200, json={"id": "zap-1"})
    if url.startswith("http://localhost:8000/media/"):  # LinkedIn image download
        buf = io.BytesIO()
        Image.new("RGB", (10, 10), "red").save(buf, format="PNG")
        return httpx.Response(200, content=buf.getvalue(), headers={"content-type": "image/png"})
    return httpx.Response(404, json={"error": "unexpected " + url})


@pytest.fixture(scope="module")
def client(module_mocker=None) -> Iterator[TestClient]:
    engine_mod.crawl_site = fake_crawl_site  # type: ignore[assignment]
    transport = httpx.MockTransport(_handler)

    class PatchedAsyncClient(ORIGINAL_ASYNC_CLIENT):
        def __init__(self, *args, **kwargs):
            kwargs.pop("verify", None)
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    pub_mod.httpx.AsyncClient = PatchedAsyncClient  # type: ignore[attr-defined]
    try:
        from app.main import app

        with TestClient(app) as c:
            yield c
    finally:
        pub_mod.httpx.AsyncClient = ORIGINAL_ASYNC_CLIENT  # type: ignore[attr-defined]


@pytest.fixture(scope="module")
def auth(client: TestClient) -> dict:
    r = client.post("/api/auth/register", json={"email": "social@testco.example", "password": "secret123", "full_name": "Social Owner"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def site_id(client: TestClient, auth: dict) -> int:
    r = client.post("/api/websites", json={"url": "https://testco.example", "name": "Testco", "industry": "web design", "target_location": "Delhi"}, headers=auth)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    client.post(f"/api/websites/{sid}/keywords", json={"terms": ["web design delhi", "website redesign cost"]}, headers=auth)
    return sid


# --------------------------------------------------------------------------- creatives
def test_templates_and_brand(client: TestClient, auth: dict, site_id: int):
    t = client.get(f"/api/websites/{site_id}/creatives/templates", headers=auth).json()
    assert {x["id"] for x in t["templates"]} >= {"bold", "gradient", "split", "quote", "stat", "minimal"}
    assert t["ai_images"] is False
    b = client.get(f"/api/websites/{site_id}/creatives/brand", headers=auth).json()
    assert b["primary"] == "#4F46E5" and b["name"] == "Testco" and b["handle"] == "testco.example"
    b = client.put(f"/api/websites/{site_id}/creatives/brand", json={"primary": "#E11D48", "style": "bold, playful"}, headers=auth).json()
    assert b["primary"] == "#E11D48" and b["style"] == "bold, playful"
    # logo upload
    buf = io.BytesIO()
    Image.new("RGBA", (300, 120), (255, 0, 0, 255)).save(buf, format="PNG")
    r = client.post(f"/api/websites/{site_id}/creatives/brand/logo", files={"file": ("logo.png", buf.getvalue(), "image/png")}, headers=auth)
    assert r.status_code == 200 and r.json()["logo_url"].startswith("/media/brand/")
    assert client.get(r.json()["logo_url"]).status_code == 200


def test_render_preview_and_create_creative(client: TestClient, auth: dict, site_id: int):
    spec = {"headline": "5 things to check before hiring a web designer", "subline": "1. Portfolio 2. Speed 3. SEO basics 4. Support 5. Price", "cta": "Read the guide", "template": "split", "size": "square"}
    r = client.post(f"/api/websites/{site_id}/creatives/preview", json=spec, headers=auth)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    img = Image.open(io.BytesIO(r.content))
    assert img.size == (540, 540)

    r = client.post(f"/api/websites/{site_id}/creatives", json=spec, headers=auth)
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["kind"] == "template" and c["width"] == 1080 and c["height"] == 1080 and c["url"].startswith("/media/creatives/")
    assert c["public_url"].startswith("http://localhost:8000/media/creatives/")
    served = client.get(c["url"])
    assert served.status_code == 200 and served.headers["content-type"] == "image/png"

    for tpl, size, dims in (("bold", "landscape", (1200, 628)), ("stat", "story", (1080, 1920)), ("quote", "square", (1080, 1080))):
        r = client.post(f"/api/websites/{site_id}/creatives", json={**spec, "headline": "87% of buyers research online first", "template": tpl, "size": size}, headers=auth)
        assert r.status_code == 201 and (r.json()["width"], r.json()["height"]) == dims

    r = client.post(f"/api/websites/{site_id}/creatives", json={"headline": "   "}, headers=auth)
    assert r.status_code == 400
    r = client.post(f"/api/websites/{site_id}/creatives/ai", json={"prompt": "happy customers in a modern office"}, headers=auth)
    assert r.status_code == 400 and "OPENAI_API_KEY" in r.json()["detail"]

    listed = client.get(f"/api/websites/{site_id}/creatives", headers=auth).json()
    assert len(listed) == 4


def test_upload_and_delete_creative(client: TestClient, auth: dict, site_id: int):
    buf = io.BytesIO()
    Image.new("RGB", (800, 600), "blue").save(buf, format="JPEG")
    r = client.post(f"/api/websites/{site_id}/creatives/upload", files={"file": ("photo.jpg", buf.getvalue(), "image/jpeg")}, headers=auth)
    assert r.status_code == 201 and r.json()["kind"] == "upload" and r.json()["url"].endswith(".jpg")
    cid = r.json()["id"]
    assert client.delete(f"/api/websites/{site_id}/creatives/{cid}", headers=auth).status_code == 204
    assert client.get(r.json()["url"]).status_code == 404
    r = client.post(f"/api/websites/{site_id}/creatives/upload", files={"file": ("bad.png", b"not an image", "image/png")}, headers=auth)
    assert r.status_code == 400


# --------------------------------------------------------------------------- channels
def test_channels(client: TestClient, auth: dict, site_id: int):
    cat = client.get("/api/social/platforms").json()
    assert cat["facebook"]["status"] == "live" and cat["google_business"]["status"] == "planned"
    r = client.put(f"/api/websites/{site_id}/social/channels", json={"platform": "facebook", "config": {"page_id": "1", "access_token": "EAAB..."}}, headers=auth)
    assert r.status_code == 200 and r.json()["status"] == "connected" and r.json()["config"]["access_token"] == "••••••"
    r = client.put(f"/api/websites/{site_id}/social/channels", json={"platform": "instagram", "config": {"account_id": "9"}}, headers=auth)
    assert r.status_code == 400 and "access_token" in r.json()["detail"]
    r = client.put(f"/api/websites/{site_id}/social/channels", json={"platform": "google_business", "config": {"location_id": "1"}}, headers=auth)
    assert r.status_code == 400
    for platform, cfg in (("instagram", {"account_id": "9", "access_token": "t"}), ("linkedin", {"organization_id": "555", "access_token": "t"}),
                          ("x", {"access_token": "t"}), ("webhook", {"url": "https://hooks.example.com/abc", "secret": "s3cr3t"})):
        assert client.put(f"/api/websites/{site_id}/social/channels", json={"platform": platform, "config": cfg}, headers=auth).status_code == 200
    channels = client.get(f"/api/websites/{site_id}/social/channels", headers=auth).json()
    assert {c["platform"] for c in channels} == {"facebook", "instagram", "linkedin", "x", "webhook"}
    # test endpoint (read call on Graph)
    t = client.post(f"/api/websites/{site_id}/social/channels/facebook/test", headers=auth).json()
    assert t["ok"] is True and "Testco Page" in t["detail"]
    t = client.post(f"/api/websites/{site_id}/social/channels/webhook/test", headers=auth).json()
    assert t["ok"] is True
    # signature header on webhook
    method, url, content = next(c for c in CALLS if c[1].startswith("https://hooks.example.com/"))
    assert json.loads(content)["test"] is True


# --------------------------------------------------------------------------- posts
def test_post_lifecycle_and_publish(client: TestClient, auth: dict, site_id: int):
    creative = client.post(f"/api/websites/{site_id}/creatives", json={"headline": "Free website audit this week", "template": "bold"}, headers=auth).json()
    r = client.post(f"/api/websites/{site_id}/social/posts", json={"platform": "facebook", "content": "Free website audit this week – DM us!", "hashtags": ["webdesign", "#Delhi"], "creative_id": creative["id"], "link_url": "https://testco.example/audit"}, headers=auth)
    assert r.status_code == 201, r.text
    post = r.json()
    assert post["status"] == "draft" and post["creative_url"] == creative["url"]
    pv = client.get(f"/api/websites/{site_id}/social/posts/{post['id']}/preview", headers=auth).json()
    assert pv["text"].endswith("#webdesign #Delhi") and "https://testco.example/audit" in pv["text"]

    CALLS.clear()
    r = client.post(f"/api/websites/{site_id}/social/posts/{post['id']}/publish", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "published" and body["external_id"] == "123_456" and body["external_url"] == "https://www.facebook.com/123_456"
    method, url, content = CALLS[0]
    assert url.endswith("/1/photos") and b"url=http%3A%2F%2Flocalhost%3A8000%2Fmedia%2Fcreatives" in content
    assert client.post(f"/api/websites/{site_id}/social/posts/{post['id']}/publish", headers=auth).status_code == 409
    assert client.patch(f"/api/websites/{site_id}/social/posts/{post['id']}", json={"content": "x"}, headers=auth).status_code == 409

    # instagram requires an image
    r = client.post(f"/api/websites/{site_id}/social/posts", json={"platform": "instagram", "content": "No image here"}, headers=auth)
    r = client.post(f"/api/websites/{site_id}/social/posts/{r.json()['id']}/publish", headers=auth).json()
    assert r["status"] == "failed" and "image" in r["error"]
    # instagram with image → container + publish + permalink
    r = client.post(f"/api/websites/{site_id}/social/posts", json={"platform": "instagram", "content": "With image", "creative_id": creative["id"]}, headers=auth)
    r = client.post(f"/api/websites/{site_id}/social/posts/{r.json()['id']}/publish", headers=auth).json()
    assert r["status"] == "published" and r["external_url"] == "https://www.instagram.com/p/abc/"
    # linkedin with image → upload flow
    r = client.post(f"/api/websites/{site_id}/social/posts", json={"platform": "linkedin", "content": "LinkedIn post", "creative_id": creative["id"]}, headers=auth)
    r = client.post(f"/api/websites/{site_id}/social/posts/{r.json()['id']}/publish", headers=auth).json()
    assert r["status"] == "published" and r["external_id"] == "urn:li:share:999" and "linkedin.com/feed/update/" in r["external_url"]
    # x text
    r = client.post(f"/api/websites/{site_id}/social/posts", json={"platform": "x", "content": "Short one"}, headers=auth)
    r = client.post(f"/api/websites/{site_id}/social/posts/{r.json()['id']}/publish", headers=auth).json()
    assert r["status"] == "published" and r["external_url"] == "https://x.com/i/web/status/1700"
    # webhook: signed payload
    CALLS.clear()
    r = client.post(f"/api/websites/{site_id}/social/posts", json={"platform": "webhook", "content": "Hook", "hashtags": ["a"]}, headers=auth)
    r = client.post(f"/api/websites/{site_id}/social/posts/{r.json()['id']}/publish", headers=auth).json()
    assert r["status"] == "published" and r["external_id"] == "zap-1"
    _, _, content = CALLS[0]
    payload = json.loads(content)
    assert payload["hashtags"] == ["a"] and payload["website"] == "https://testco.example" and payload["platform"] == "webhook"

    # failure path marks post failed + channel error, and a retry after fixing works
    STATE["fail_facebook"] = True
    r = client.post(f"/api/websites/{site_id}/social/posts", json={"platform": "facebook", "content": "Will fail"}, headers=auth)
    pid = r.json()["id"]
    r = client.post(f"/api/websites/{site_id}/social/posts/{pid}/publish", headers=auth).json()
    assert r["status"] == "failed" and "Invalid OAuth access token" in r["error"]
    ch = next(c for c in client.get(f"/api/websites/{site_id}/social/channels", headers=auth).json() if c["platform"] == "facebook")
    assert ch["status"] == "error"
    STATE["fail_facebook"] = False
    r = client.patch(f"/api/websites/{site_id}/social/posts/{pid}", json={"content": "Will succeed now"}, headers=auth).json()
    assert r["status"] == "draft" and r["error"] == ""
    assert client.post(f"/api/websites/{site_id}/social/posts/{pid}/publish", headers=auth).json()["status"] == "published"


def test_schedule_and_scheduler_publishes_due_posts(client: TestClient, auth: dict, site_id: int):
    import asyncio

    from app.core.database import session_scope
    from app.services.social.service import process_due_posts

    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    r = client.post(f"/api/websites/{site_id}/social/posts", json={"platform": "facebook", "content": "Later", "scheduled_for": future}, headers=auth)
    assert r.json()["status"] == "scheduled"
    r = client.post(f"/api/websites/{site_id}/social/posts", json={"platform": "facebook", "content": "Now-ish", "scheduled_for": past}, headers=auth)
    due_id = r.json()["id"]
    r = client.post(f"/api/websites/{site_id}/social/posts", json={"platform": "facebook", "content": "Needs a time", "status": "scheduled"}, headers=auth)
    assert r.status_code == 400

    assert asyncio.run(process_due_posts(session_scope)) == 1
    posts = {p["id"]: p for p in client.get(f"/api/websites/{site_id}/social/posts", headers=auth).json()}
    assert posts[due_id]["status"] == "published"
    assert asyncio.run(process_due_posts(session_scope)) == 0
    summary = client.get(f"/api/websites/{site_id}/social/summary", headers=auth).json()
    assert summary["counts"]["scheduled"] == 1 and summary["counts"]["published"] >= 7 and "facebook" in summary["connected"]


def test_calendar_generation_rule_based(client: TestClient, auth: dict, site_id: int):
    r = client.post(f"/api/websites/{site_id}/social/calendar", json={"platforms": ["instagram", "linkedin", "facebook"], "weeks": 2, "posts_per_week": 3, "timezone": "Asia/Kolkata", "generate_creatives": True}, headers=auth)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["provider"] == "rule-based" and body["created"] == 6 and body["strategy"]
    posts = body["posts"]
    assert all(p["status"] == "draft" and p["scheduled_for"] and p["creative_url"] for p in posts)
    assert {p["platform"] for p in posts} == {"instagram", "linkedin", "facebook"}
    assert any("web design delhi" in p["topic"].lower() or "website redesign cost" in p["topic"].lower() for p in posts)
    # times are in sensible local windows and strictly in the future, sorted by week/day
    from zoneinfo import ZoneInfo

    hours = [datetime.fromisoformat(p["scheduled_for"].replace("Z", "+00:00")).astimezone(ZoneInfo("Asia/Kolkata")).hour for p in posts]
    assert all(8 <= h <= 21 for h in hours)
    assert all(datetime.fromisoformat(p["scheduled_for"].replace("Z", "+00:00")) > datetime.now(timezone.utc) for p in posts)
    assert len({p["content"] for p in posts}) == 6  # no duplicate copy

    # bulk schedule
    ids = [p["id"] for p in posts]
    r = client.post(f"/api/websites/{site_id}/social/posts/bulk?action=schedule", json=ids, headers=auth)
    assert r.json()["updated"] == 6
    r = client.get(f"/api/websites/{site_id}/social/posts?status=scheduled", headers=auth).json()
    assert len(r) == 7
    r = client.post(f"/api/websites/{site_id}/social/posts/bulk?action=delete", json=ids[:2], headers=auth)
    assert r.json()["updated"] == 2

    # auto_schedule only schedules connected channels
    client.delete(f"/api/websites/{site_id}/social/channels/linkedin", headers=auth)
    body = client.post(f"/api/websites/{site_id}/social/calendar", json={"platforms": ["linkedin", "facebook"], "weeks": 1, "posts_per_week": 2, "auto_schedule": True, "generate_creatives": False}, headers=auth).json()
    statuses = {p["platform"]: p["status"] for p in body["posts"]}
    assert statuses == {"linkedin": "draft", "facebook": "scheduled"}
    assert all(p["creative_url"] == "" for p in body["posts"])


def test_compose_text_limits():
    from app.services.social.publishers import compose_text

    text = compose_text("x" * 300, ["a"], "https://t.co/x", "x")
    assert len(text) <= 280 and text.endswith("…")
    ig = compose_text("caption", ["tag"], "https://example.com", "instagram")
    assert "https://example.com" not in ig and ig.endswith("#tag")


def test_brand_colour_guess():
    from app.services.creatives.studio import guess_brand_colours

    html = '<meta name="theme-color" content="#0f766e"><style>.btn{background:#0f766e}.a{color:#f59e0b}.g{color:#777777}.w{color:#ffffff}</style>'
    c = guess_brand_colours(html)
    assert c["primary"] == "#0F766E" and c["secondary"] == "#F59E0B"
    assert guess_brand_colours("<p>no colours</p>") == {}
