"""Website ownership verification: meta tag, HTML file, or DNS TXT record."""
from __future__ import annotations

import asyncio
import re
from urllib.parse import urlparse

import httpx

from app.core.http import make_client

META_NAME = "rankpilot-verification"
FILE_PREFIX = "rankpilot-"
DNS_PREFIX = "rankpilot-site-verification="


def instructions(url: str, token: str) -> dict:
    root = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    fname = f"{FILE_PREFIX}{token}.html"
    return {
        "token": token,
        "meta_tag": f'<meta name="{META_NAME}" content="{token}">',
        "dns_record": f"{DNS_PREFIX}{token}",
        "html_file_name": fname,
        "html_file_content": f"{FILE_PREFIX}verification: {token}",
        "html_file_url": f"{root}/{fname}",
    }


async def _check_meta(client: httpx.AsyncClient, url: str, token: str) -> bool:
    try:
        resp = await client.get(url + "/")
    except httpx.HTTPError:
        return False
    if resp.status_code >= 400:
        return False
    pattern = re.compile(
        rf'<meta[^>]+name=["\']{META_NAME}["\'][^>]+content=["\']{re.escape(token)}["\']|'
        rf'<meta[^>]+content=["\']{re.escape(token)}["\'][^>]+name=["\']{META_NAME}["\']',
        re.I,
    )
    return bool(pattern.search(resp.text[:200_000]))


async def _check_file(client: httpx.AsyncClient, url: str, token: str) -> bool:
    ins = instructions(url, token)
    try:
        resp = await client.get(ins["html_file_url"])
    except httpx.HTTPError:
        return False
    return resp.status_code == 200 and token in resp.text[:5000]


async def _check_dns(url: str, token: str) -> bool:
    host = urlparse(url).netloc.removeprefix("www.")
    expected = f"{DNS_PREFIX}{token}"
    # 1) DNS-over-HTTPS (works without extra dependencies)
    try:
        async with make_client(timeout=10) as client:
            for endpoint in ("https://dns.google/resolve", "https://cloudflare-dns.com/dns-query"):
                try:
                    resp = await client.get(endpoint, params={"name": host, "type": "TXT"}, headers={"accept": "application/dns-json"})
                    if resp.status_code != 200:
                        continue
                    for ans in resp.json().get("Answer", []) or []:
                        data = str(ans.get("data", "")).replace('"', "")
                        if expected in data:
                            return True
                    return False
                except httpx.HTTPError:
                    continue
    except Exception:
        pass
    # 2) fallback: system resolver via `dig`/`nslookup` if present
    for cmd in (["dig", "+short", "TXT", host], ["nslookup", "-type=TXT", host]):
        try:
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            if expected in out.decode(errors="ignore"):
                return True
        except Exception:
            continue
    return False


async def verify(url: str, token: str, method: str = "auto") -> tuple[bool, str, str]:
    """Returns (verified, method_used, detail)."""
    async with make_client() as client:
        checks = []
        if method in ("auto", "meta"):
            checks.append(("meta", _check_meta(client, url, token)))
        if method in ("auto", "file"):
            checks.append(("file", _check_file(client, url, token)))
        if method in ("auto", "dns"):
            checks.append(("dns", _check_dns(url, token)))
        results = await asyncio.gather(*(c[1] for c in checks), return_exceptions=True)
    for (name, _), ok in zip(checks, results, strict=True):
        if ok is True:
            return True, name, f"Verified via {name}."
    tried = ", ".join(c[0] for c in checks)
    return False, "", f"Verification token not found (checked: {tried}). Changes can take a few minutes to propagate."
