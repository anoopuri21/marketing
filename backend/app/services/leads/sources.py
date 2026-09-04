"""Prospect discovery providers.

* serpapi – Google Maps local results (businesses) and Google organic results (companies ranking for a
  service query) via SerpAPI. Requires SERPAPI_KEY.
* demo    – deterministic, clearly-labelled sample prospects so the whole pipeline can be tried without keys.

Every provider returns a list of `Prospect` dicts with the same shape::

    {company, website_url, phone, address, rating, reviews, category, place_id, source, snippet}
"""
from __future__ import annotations

import hashlib
import logging
import random
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.http import ssl_context

log = logging.getLogger(__name__)

Prospect = dict[str, Any]

# Domains that are never a "business we could pitch to".
EXCLUDED_HOSTS = (
    "google.", "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com", "youtube.com",
    "yelp.", "justdial.com", "sulekha.com", "indiamart.com", "tripadvisor.", "zomato.com", "swiggy.com",
    "wikipedia.org", "amazon.", "flipkart.com", "quora.com", "reddit.com", "pinterest.", "glassdoor.",
    "indeed.", "naukri.com", "practo.com", "urbancompany.com", "magicbricks.com", "99acres.com", "housing.com",
    "apple.com", "play.google.com", "medium.com", "yellowpages.", "bbb.org", "trustpilot.", "clutch.co",
    "goodfirms.", "thumbtack.com", "angi.com", "houzz.", "mapquest.", "foursquare.",
)


def host_of(url: str) -> str:
    try:
        return (urlparse(url if "://" in url else f"https://{url}").hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def is_directory(url: str) -> bool:
    h = host_of(url)
    return not h or any(h == x.rstrip(".") or h.endswith(x if x.endswith(".") else "." + x) or x in h for x in EXCLUDED_HOSTS)


def _clean_phone(p: str) -> str:
    return re.sub(r"[^\d+()\-\s]", "", p or "").strip()[:40]


# --------------------------------------------------------------------------- #
# SerpAPI
# --------------------------------------------------------------------------- #
async def _serpapi(params: dict[str, Any]) -> dict[str, Any]:
    params = {**params, "api_key": settings.serpapi_key}
    async with httpx.AsyncClient(timeout=40, verify=ssl_context()) as client:
        resp = await client.get("https://serpapi.com/search.json", params=params)
        resp.raise_for_status()
        return resp.json()


async def serpapi_maps(query: str, location: str, limit: int = 20, language: str = "en") -> list[Prospect]:
    """Local businesses from Google Maps for "<query> in <location>"."""
    out: list[Prospect] = []
    start = 0
    while len(out) < limit and start < 60:
        data = await _serpapi({"engine": "google_maps", "type": "search", "q": f"{query} in {location}".strip(), "hl": language, "start": start})
        results = data.get("local_results") or []
        if not results:
            break
        for r in results:
            out.append({
                "company": (r.get("title") or "").strip()[:255],
                "website_url": (r.get("website") or "").strip()[:2048],
                "phone": _clean_phone(r.get("phone") or ""),
                "address": (r.get("address") or "").strip()[:512],
                "rating": r.get("rating"),
                "reviews": r.get("reviews"),
                "category": (r.get("type") or (r.get("types") or [""])[0] or "").strip()[:255],
                "place_id": (r.get("place_id") or r.get("data_id") or "")[:255],
                "source": "serpapi_maps",
                "snippet": (r.get("description") or "").strip()[:500],
            })
            if len(out) >= limit:
                break
        start += 20
    return out


async def serpapi_organic(query: str, location: str, limit: int = 20, language: str = "en") -> list[Prospect]:
    """Companies ranking organically for a service query – useful for B2B prospecting (agencies, SaaS…)."""
    params: dict[str, Any] = {"engine": "google", "q": f"{query} {location}".strip(), "num": min(max(limit * 2, 10), 100), "hl": language}
    if location:
        params["location"] = location
    data = await _serpapi(params)
    out: list[Prospect] = []
    seen: set = set()
    for r in data.get("organic_results") or []:
        link = r.get("link") or ""
        h = host_of(link)
        if not h or h in seen or is_directory(link):
            continue
        seen.add(h)
        out.append({
            "company": (r.get("source") or r.get("title") or h).split(" - ")[0].split(" | ")[0].strip()[:255],
            "website_url": f"https://{h}",
            "phone": "",
            "address": "",
            "rating": None,
            "reviews": None,
            "category": query[:255],
            "place_id": "",
            "source": "serpapi_organic",
            "snippet": (r.get("snippet") or "").strip()[:500],
        })
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- #
# Demo provider (no key)
# --------------------------------------------------------------------------- #
_DEMO_NAMES = ["Sunrise", "Prime", "Elite", "City", "Green Leaf", "Blue Sky", "Royal", "Metro", "Apex", "Harmony",
               "Golden", "Urban", "Classic", "Pioneer", "Summit", "Silverline", "Bright", "Nova", "Crest", "Anchor"]
_DEMO_SUFFIX = ["Studio", "Solutions", "Services", "Center", "Clinic", "Group", "Works", "Hub", "Co.", "Experts"]
_DEMO_TLDS = ["example.com", "example.net", "example.org"]


def demo_prospects(query: str, location: str, limit: int = 12) -> list[Prospect]:
    """Deterministic sample prospects (RFC 2606 example domains) – clearly labelled `source=demo`."""
    seed = hashlib.sha1(f"{query}|{location}".lower().encode()).hexdigest()
    rng = random.Random(seed)
    names = rng.sample(_DEMO_NAMES, k=min(limit, len(_DEMO_NAMES)))
    cat = query.strip().title() or "Business"
    out: list[Prospect] = []
    for i, n in enumerate(names):
        suffix = rng.choice(_DEMO_SUFFIX)
        company = f"{n} {cat} {suffix}" if len(cat.split()) <= 2 else f"{n} {suffix}"
        slug = re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-")
        has_site = rng.random() > 0.25
        out.append({
            "company": company,
            "website_url": f"https://{slug}.{rng.choice(_DEMO_TLDS)}" if has_site else "",
            "phone": f"+91 98{rng.randint(10000000, 99999999)}" if rng.random() > 0.2 else "",
            "address": f"{rng.randint(1, 240)} {rng.choice(['MG Road', 'Main Street', 'Park Avenue', 'Station Road', 'Market Lane'])}, {location or 'your city'}",
            "rating": round(rng.uniform(3.2, 4.9), 1) if rng.random() > 0.15 else None,
            "reviews": rng.choice([0, 3, 8, 15, 27, 44, 61, 98, 150, 320]) if rng.random() > 0.1 else None,
            "category": cat,
            "place_id": f"demo-{seed[:8]}-{i}",
            "source": "demo",
            "snippet": "Sample prospect generated for demo mode. Add SERPAPI_KEY to discover real businesses.",
        })
    return out


# --------------------------------------------------------------------------- #
# Facade
# --------------------------------------------------------------------------- #
async def discover(query: str, location: str, mode: str = "maps", limit: int = 20, language: str = "en") -> dict[str, Any]:
    """Return {"provider": str, "prospects": [...], "note": str}."""
    provider = settings.resolved_lead_provider
    if provider == "none":
        return {"provider": "none", "prospects": [], "note": "Lead discovery is disabled (LEAD_PROVIDER=none)."}
    if provider == "demo":
        return {"provider": "demo", "prospects": demo_prospects(query, location, min(limit, 20)),
                "note": "Demo prospects (example.com domains). Set SERPAPI_KEY in backend/.env to discover real businesses from Google Maps and Google Search."}
    if mode == "organic":
        prospects = await serpapi_organic(query, location, limit, language)
    elif mode == "both":
        maps = await serpapi_maps(query, location, limit, language)
        organic = await serpapi_organic(query, location, max(5, limit // 2), language)
        hosts = {host_of(p["website_url"]) for p in maps if p.get("website_url")}
        prospects = maps + [p for p in organic if host_of(p["website_url"]) not in hosts]
    else:
        prospects = await serpapi_maps(query, location, limit, language)
    return {"provider": "serpapi", "prospects": prospects, "note": ""}
