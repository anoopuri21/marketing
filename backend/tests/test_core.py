"""Core layer: settings guard, time helpers, domain-error → HTTP mapping, request ids."""
from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core import time as time_mod
from app.core.config import INSECURE_SECRET_KEY, Settings
from app.core.errors import ConflictError, DomainError, NotFoundError, UpstreamError, ValidationError
from app.main import app


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# settings
# --------------------------------------------------------------------------- #
def test_production_refuses_insecure_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", INSECURE_SECRET_KEY)
    monkeypatch.setenv("CORS_ORIGINS", "*")
    with pytest.raises(ValueError) as exc:
        Settings(_env_file=None)
    msg = str(exc.value)
    assert "SECRET_KEY" in msg and "CORS_ORIGINS" in msg


def test_production_accepts_hardened_config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com, https://www.example.com")
    s = Settings(_env_file=None)
    assert s.is_production
    assert s.cors_origin_list == ["https://app.example.com", "https://www.example.com"]


def test_development_allows_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    assert not Settings(_env_file=None).is_production


# --------------------------------------------------------------------------- #
# time helpers
# --------------------------------------------------------------------------- #
def test_aware_and_helpers():
    naive = datetime(2026, 1, 1, 12, 0, 0)
    assert time_mod.aware(naive).tzinfo is UTC
    assert time_mod.aware(None) is None
    already = datetime.now(UTC)
    assert time_mod.aware(already) is already
    assert time_mod.utcnow().tzinfo is UTC
    assert time_mod.is_past(datetime.now(UTC) - timedelta(seconds=1))
    assert not time_mod.is_past(datetime.now(UTC) + timedelta(days=1))
    assert not time_mod.is_past(None)
    assert time_mod.age(None) is None
    assert time_mod.age(naive) > timedelta(days=1)


# --------------------------------------------------------------------------- #
# errors
# --------------------------------------------------------------------------- #
def test_domain_error_status_codes():
    assert NotFoundError("x").status_code == 404
    assert ValidationError("x").status_code == 400
    assert ConflictError("x").status_code == 409
    assert UpstreamError("x").status_code == 502
    assert DomainError("x", status_code=418).status_code == 418
    assert DomainError("boom").message == "boom"


def test_domain_errors_become_json_responses(client: TestClient):
    r = client.post("/api/auth/register", json={"email": "core@example.com", "password": "secret123", "full_name": "Core"})
    token = r.json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}
    r = client.post("/api/websites", json={"url": "https://core.example.com", "name": "Core"}, headers=auth)
    sid = r.json()["id"]

    # NotFoundError raised inside the social service → 404 JSON with request id
    r = client.get(f"/api/websites/{sid}/social/posts/999999/preview", headers=auth)
    assert r.status_code == 404
    assert r.json()["detail"] == "Post not found"
    assert r.json()["request_id"] == r.headers["X-Request-ID"]

    # ValidationError → 400
    r = client.post(f"/api/websites/{sid}/social/posts", json={"platform": "myspace", "content": "hi"}, headers=auth)
    assert r.status_code == 400
    assert "Unknown platform" in r.json()["detail"]

    # ConflictError → 409 (bulk action validation) & ValidationError from leads status machine
    r = client.post(f"/api/websites/{sid}/social/posts/bulk?action=explode", json=[1, 2], headers=auth)
    assert r.status_code == 400
    r = client.post(f"/api/websites/{sid}/leads", json={"company": "Acme"}, params={"qualify": "false"}, headers=auth)
    lead_id = r.json()["id"]
    r = client.post(f"/api/websites/{sid}/leads/{lead_id}/status", json={"status": "teleported"}, headers=auth)
    assert r.status_code == 400 and "Unknown status" in r.json()["detail"]
    # keep the shared test DB clean for the scheduler tests (no pending leads left behind)
    assert client.delete(f"/api/websites/{sid}/leads/{lead_id}", headers=auth).status_code == 204
    assert client.delete(f"/api/websites/{sid}", headers=auth).status_code in (200, 204)


def test_request_id_is_propagated(client: TestClient):
    r = client.get("/api/health", headers={"X-Request-ID": "trace-abc-123"})
    assert r.status_code == 200
    assert r.headers["X-Request-ID"] == "trace-abc-123"
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"
    r = client.get("/api/health")
    assert len(r.headers["X-Request-ID"]) >= 8


# --------------------------------------------------------------------------- #
# credentials at rest
# --------------------------------------------------------------------------- #
def test_crypto_roundtrip_and_legacy():
    from app.core import crypto

    token = crypto.encrypt_json({"access_token": "EAAB-secret", "page_id": "1"})
    assert token.startswith(crypto.PREFIX) and "EAAB-secret" not in token
    assert crypto.decrypt_json(token) == {"access_token": "EAAB-secret", "page_id": "1"}
    assert crypto.decrypt_json({"legacy": True}) == {"legacy": True}  # old JSON column values
    assert crypto.decrypt_text("plain") == "plain"
    with pytest.raises(ValueError):
        crypto.decrypt_text(crypto.PREFIX + "not-a-token")


def test_integration_config_is_encrypted_in_db(client: TestClient):
    import sqlite3

    from app.core.config import settings

    r = client.post("/api/auth/register", json={"email": "vault@example.com", "password": "secret123", "full_name": "Vault"})
    auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
    sid = client.post("/api/websites", json={"url": "https://vault.example.com", "name": "Vault"}, headers=auth).json()["id"]
    r = client.put(f"/api/websites/{sid}/social/channels", json={"platform": "facebook", "config": {"page_id": "42", "access_token": "EAAB-super-secret"}}, headers=auth)
    assert r.status_code == 200
    assert r.json()["config"]["access_token"].startswith("••••")  # masked in API responses

    db_path = settings.database_url.split("///", 1)[1]
    raw = sqlite3.connect(db_path).execute("SELECT config FROM integrations WHERE website_id = ?", (sid,)).fetchone()[0]
    assert raw.startswith("enc:v1:") and "EAAB-super-secret" not in raw

    # the ORM still sees plaintext and partial updates keep the secret
    r = client.put(f"/api/websites/{sid}/social/channels", json={"platform": "facebook", "config": {"page_id": "43", "access_token": "••••••"}}, headers=auth)
    assert r.json()["config"]["page_id"] == "43"
    assert client.delete(f"/api/websites/{sid}", headers=auth).status_code in (200, 204)


# --------------------------------------------------------------------------- #
# rate limiting
# --------------------------------------------------------------------------- #
def test_rate_limiter_blocks_and_recovers(monkeypatch: pytest.MonkeyPatch):
    from app.core import ratelimit

    ratelimit.reset()
    key = "login:203.0.113.9"
    assert all(ratelimit.check(key, limit=3, window_seconds=60) is None for _ in range(3))
    wait = ratelimit.check(key, limit=3, window_seconds=60)
    assert wait is not None and 0 < wait <= 60
    ratelimit.reset(key)
    assert ratelimit.check(key, limit=3, window_seconds=60) is None


def test_login_returns_429_when_enabled(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from app.core import ratelimit
    from app.core.config import settings

    ratelimit.reset()
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    try:
        codes = [client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrong"}).status_code for _ in range(11)]
    finally:
        monkeypatch.setattr(settings, "rate_limit_enabled", False)
        ratelimit.reset()
    assert codes[:10] == [401] * 10 and codes[10] == 429
