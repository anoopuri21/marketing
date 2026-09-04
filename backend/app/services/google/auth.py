"""Google service-account authentication (OAuth 2.0 JWT bearer flow) without google SDKs.

The client uploads the service-account JSON (from Google Cloud Console). We mint a signed
JWT with the requested scopes and exchange it for a short-lived access token. Tokens are
cached in-process per (client_email, scopes).
"""
from __future__ import annotations

import json
import time
from collections.abc import Iterable

import httpx
from jose import jwt

from app.core.http import ssl_context

TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = {
    "gsc": "https://www.googleapis.com/auth/webmasters.readonly",
    "ga4": "https://www.googleapis.com/auth/analytics.readonly",
}

_cache: dict[tuple[str, str], tuple[str, float]] = {}


class GoogleAuthError(RuntimeError):
    """Anything that should be shown to the user as the integration's error state."""


def network_error(host: str, exc: Exception) -> GoogleAuthError:
    return GoogleAuthError(
        f"Could not reach {host} ({type(exc).__name__}: {exc or 'connection failed'}). "
        "Check the server's outbound internet access / proxy settings and try again."
    )


def parse_service_account(raw: str | dict) -> dict:
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GoogleAuthError("service_account_json is not valid JSON") from exc
    for key in ("client_email", "private_key", "token_uri"):
        if not data.get(key):
            raise GoogleAuthError(f"service account JSON is missing '{key}'")
    if data.get("type") != "service_account":
        raise GoogleAuthError("JSON is not a service account key (type != service_account)")
    return data


async def get_access_token(service_account: dict, scopes: Iterable[str]) -> str:
    scope_str = " ".join(sorted(scopes))
    key = (service_account["client_email"], scope_str)
    cached = _cache.get(key)
    now = time.time()
    if cached and cached[1] - 60 > now:
        return cached[0]

    claims = {
        "iss": service_account["client_email"],
        "scope": scope_str,
        "aud": service_account.get("token_uri", TOKEN_URI),
        "iat": int(now),
        "exp": int(now) + 3600,
    }
    headers = {"kid": service_account["private_key_id"]} if service_account.get("private_key_id") else None
    try:
        assertion = jwt.encode(claims, service_account["private_key"], algorithm="RS256", headers=headers)
    except Exception as exc:  # malformed private key
        raise GoogleAuthError(f"could not sign JWT with the service account key: {exc}") from exc

    try:
        async with httpx.AsyncClient(timeout=30, verify=ssl_context()) as client:
            resp = await client.post(
                service_account.get("token_uri", TOKEN_URI),
                data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
            )
    except httpx.HTTPError as exc:
        raise network_error("oauth2.googleapis.com", exc) from exc
    if resp.status_code != 200:
        try:
            detail = resp.json().get("error_description") or resp.json().get("error")
        except Exception:
            detail = resp.text[:200]
        raise GoogleAuthError(f"Google token exchange failed ({resp.status_code}): {detail}")
    data = resp.json()
    token = data["access_token"]
    _cache[key] = (token, now + int(data.get("expires_in", 3600)))
    return token


def clear_token_cache() -> None:
    _cache.clear()
