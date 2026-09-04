"""Lead qualification: mini SEO audit of the prospect's website → gaps → opportunity score → pitch angle.

Re-uses the real crawler + analyzers with a tiny page budget so it stays fast (a few seconds per lead).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.services.audit.analyzers import analyze
from app.services.audit.crawler import crawl_site

log = logging.getLogger(__name__)

# Gap catalogue: (code -> label, what we can sell against it, weight for the opportunity score)
GAP_CATALOGUE: Dict[str, Dict[str, Any]] = {
    "NO_WEBSITE": {"label": "No website found", "pitch": "a professional website that shows up on Google", "weight": 30},
    "HOME_UNREACHABLE": {"label": "Website is down or unreachable", "pitch": "getting the site back online and stable", "weight": 30},
    "NO_HTTPS": {"label": "No HTTPS (browsers warn visitors)", "pitch": "securing the site with HTTPS", "weight": 12},
    "TLS_INVALID": {"label": "Broken SSL certificate", "pitch": "fixing the SSL certificate", "weight": 12},
    "NOT_MOBILE_FRIENDLY": {"label": "Not mobile friendly", "pitch": "a mobile-friendly experience", "weight": 12},
    "NO_SCHEMA": {"label": "No structured data (schema.org)", "pitch": "rich results & AI-search visibility with structured data", "weight": 10},
    "NO_LOCAL_SCHEMA": {"label": "No LocalBusiness schema", "pitch": "local search visibility", "weight": 8},
    "MISSING_TITLE": {"label": "Pages without titles", "pitch": "basic on-page SEO", "weight": 8},
    "MISSING_META_DESCRIPTION": {"label": "Missing meta descriptions", "pitch": "click-worthy Google snippets", "weight": 5},
    "NO_SITEMAP": {"label": "No XML sitemap", "pitch": "making sure Google indexes every page", "weight": 5},
    "NO_ROBOTS": {"label": "No robots.txt", "pitch": "crawl hygiene", "weight": 2},
    "SLOW_TTFB": {"label": "Slow server response", "pitch": "page speed", "weight": 7},
    "LARGE_HTML": {"label": "Very heavy pages", "pitch": "page speed", "weight": 4},
    "NO_FAQ": {"label": "No FAQ content", "pitch": "answer-engine (AI Overviews / ChatGPT) visibility", "weight": 6},
    "NO_CONTACT": {"label": "No phone/email on homepage", "pitch": "lead capture & conversion", "weight": 6},
    "NO_SOCIAL_LINKS": {"label": "No social profiles linked", "pitch": "social presence & content marketing", "weight": 5},
    "NO_OG_TAGS": {"label": "No social sharing tags", "pitch": "social presence & content marketing", "weight": 3},
    "THIN_CONTENT": {"label": "Thin content", "pitch": "content that ranks and converts", "weight": 6},
    "MISSING_H1": {"label": "Pages without an H1", "pitch": "basic on-page SEO", "weight": 3},
    "IMAGES_MISSING_ALT": {"label": "Images without alt text", "pitch": "accessibility & image SEO", "weight": 2},
    "AI_BOTS_BLOCKED": {"label": "AI crawlers blocked", "pitch": "AI-search visibility", "weight": 4},
    "NO_LLMS_TXT": {"label": "No llms.txt", "pitch": "AI-search visibility", "weight": 2},
}

# Issue codes emitted by analyzers → gap codes (only the ones we can turn into a pitch)
ISSUE_TO_GAP = {
    "HOME_UNREACHABLE": "HOME_UNREACHABLE", "HOME_ERROR_STATUS": "HOME_UNREACHABLE",
    "NO_HTTPS": "NO_HTTPS", "INVALID_TLS_CERT": "TLS_INVALID", "NO_VIEWPORT": "NOT_MOBILE_FRIENDLY",
    "NO_STRUCTURED_DATA": "NO_SCHEMA", "NO_ORG_SCHEMA": "NO_LOCAL_SCHEMA",
    "MISSING_TITLE": "MISSING_TITLE", "MISSING_META_DESC": "MISSING_META_DESCRIPTION",
    "NO_SITEMAP": "NO_SITEMAP", "NO_ROBOTS_TXT": "NO_ROBOTS", "SLOW_TTFB": "SLOW_TTFB", "SLOW_PAGE": "SLOW_TTFB", "HEAVY_HTML": "LARGE_HTML",
    "NO_FAQ_SCHEMA": "NO_FAQ", "NO_QUESTION_HEADINGS": "NO_FAQ", "NO_CONTACT_SIGNALS": "NO_CONTACT",
    "NO_SOCIAL_PROFILE_LINKS": "NO_SOCIAL_LINKS", "FEW_SOCIAL_PROFILES": "NO_SOCIAL_LINKS", "MISSING_OG_TAGS": "NO_OG_TAGS",
    "THIN_CONTENT": "THIN_CONTENT", "MISSING_H1": "MISSING_H1", "SITEWIDE_ALT_MISSING": "IMAGES_MISSING_ALT",
    "AI_BOTS_BLOCKED": "AI_BOTS_BLOCKED", "NO_LLMS_TXT": "NO_LLMS_TXT",
}


def _gap(code: str, detail: str = "") -> Dict[str, Any]:
    meta = GAP_CATALOGUE[code]
    return {"code": code, "label": meta["label"], "pitch": meta["pitch"], "weight": meta["weight"], "detail": detail[:200]}


def gaps_from_analysis(facts: Dict[str, Any], issues: List[Dict[str, Any]], scores: Dict[str, float]) -> List[Dict[str, Any]]:
    """Map audit output onto the gap catalogue. Uses facts for the important binary signals so we don't depend on exact issue codes."""
    gaps: Dict[str, Dict[str, Any]] = {}
    if facts.get("tls_invalid"):
        gaps["TLS_INVALID"] = _gap("TLS_INVALID", facts.get("tls_error", ""))
    elif facts.get("https") is False:
        gaps["NO_HTTPS"] = _gap("NO_HTTPS")
    if not facts.get("sitemap_found"):
        gaps["NO_SITEMAP"] = _gap("NO_SITEMAP")
    if not facts.get("robots_txt_found"):
        gaps["NO_ROBOTS"] = _gap("NO_ROBOTS")
    if not facts.get("schema_types"):
        gaps["NO_SCHEMA"] = _gap("NO_SCHEMA")
    elif not any(t in ("LocalBusiness", "Organization", "Store", "Restaurant", "Dentist", "MedicalBusiness", "ProfessionalService") or t.endswith("Business") for t in facts.get("schema_types") or []):
        gaps["NO_LOCAL_SCHEMA"] = _gap("NO_LOCAL_SCHEMA")
    if not facts.get("faq_pages") and not facts.get("question_headings"):
        gaps["NO_FAQ"] = _gap("NO_FAQ")
    if facts.get("robots_blocks_ai_bots"):
        gaps["AI_BOTS_BLOCKED"] = _gap("AI_BOTS_BLOCKED", ", ".join(facts.get("robots_blocks_ai_bots") or [])[:100])
    if facts.get("llms_txt_found") is False:
        gaps["NO_LLMS_TXT"] = _gap("NO_LLMS_TXT")
    ttfb = facts.get("home_ttfb_ms")
    if isinstance(ttfb, (int, float)) and ttfb > 1200:
        gaps["SLOW_TTFB"] = _gap("SLOW_TTFB", f"{int(ttfb)} ms")
    avg_words = facts.get("avg_word_count")
    if isinstance(avg_words, int) and 0 < avg_words < 250:
        gaps["THIN_CONTENT"] = _gap("THIN_CONTENT", f"~{avg_words} words per page")
    for issue in issues:
        code = ISSUE_TO_GAP.get(str(issue.get("code", "")))
        if code and code not in gaps:
            gaps[code] = _gap(code, str(issue.get("title") or issue.get("detail") or ""))
    ordered = sorted(gaps.values(), key=lambda g: -g["weight"])
    return ordered[:12]


def opportunity_score(gaps: List[Dict[str, Any]], website_score: Optional[float], listing: Dict[str, Any]) -> int:
    """0-100: how much a prospect needs help *and* is reachable. Higher = better lead."""
    score = 0.0
    if website_score is None:  # no site at all
        score += 45
    else:
        score += max(0.0, (100 - website_score)) * 0.5  # weak site → up to 50
    score += min(30.0, sum(g["weight"] for g in gaps) * 0.5)
    # Listing signals: contactable & established businesses are better prospects than ghosts
    if listing.get("phone"):
        score += 8
    reviews = listing.get("reviews")
    if isinstance(reviews, (int, float)):
        if reviews >= 20:
            score += 6  # real, active business
        elif reviews == 0:
            score -= 4
    rating = listing.get("rating")
    if isinstance(rating, (int, float)) and rating < 3.5:
        score += 4  # reputation help needed
    return int(max(0, min(100, round(score))))


def demo_audit(url: str) -> Dict[str, Any]:
    """Deterministic pseudo-audit for demo prospects (example.com domains are never crawled)."""
    import hashlib
    import random

    rng = random.Random(hashlib.sha1(url.encode()).hexdigest())
    score = round(rng.uniform(28, 72), 1)
    pool = ["NO_SCHEMA", "NO_SITEMAP", "MISSING_META_DESCRIPTION", "NO_FAQ", "SLOW_TTFB", "NO_CONTACT", "NO_SOCIAL_LINKS",
            "THIN_CONTENT", "NOT_MOBILE_FRIENDLY", "NO_HTTPS", "NO_LLMS_TXT", "IMAGES_MISSING_ALT", "MISSING_H1", "NO_OG_TAGS"]
    codes = rng.sample(pool, k=rng.randint(3, 6))
    gaps = sorted([_gap(c) for c in codes], key=lambda g: -g["weight"])
    return {
        "website_score": score,
        "scores": {"seo": round(score + rng.uniform(-10, 10), 1), "technical": round(score + rng.uniform(-10, 15), 1), "content": round(score + rng.uniform(-15, 10), 1),
                   "aeo": round(max(5, score - rng.uniform(5, 25)), 1), "ai": round(max(5, score - rng.uniform(0, 20)), 1), "performance": round(score + rng.uniform(-10, 10), 1), "social": round(score + rng.uniform(-20, 20), 1)},
        "gaps": gaps, "pages_crawled": rng.randint(3, 8),
        "facts": {"https": "NO_HTTPS" not in codes, "sitemap_found": "NO_SITEMAP" not in codes, "schema_types": [] if "NO_SCHEMA" in codes else ["WebSite"],
                  "home_ttfb_ms": rng.randint(1300, 3200) if "SLOW_TTFB" in codes else rng.randint(200, 900), "avg_word_count": rng.randint(120, 240) if "THIN_CONTENT" in codes else rng.randint(300, 900),
                  "title": "Home", "has_phone": "NO_CONTACT" not in codes, "has_email": False, "issue_counts": {}},
        "unreachable": False, "demo": True,
    }


def is_demo_url(url: str) -> bool:
    from app.services.leads.sources import host_of

    h = host_of(url)
    return h.endswith(("example.com", "example.net", "example.org")) or h in ("example.com", "example.net", "example.org")


async def qualify_website(url: str, max_pages: Optional[int] = None) -> Dict[str, Any]:
    """Crawl a few pages of the prospect's site and return {website_score, scores, gaps, facts, pages_crawled}."""
    if is_demo_url(url):
        return demo_audit(url)
    site = await asyncio.wait_for(crawl_site(url, max_pages=max_pages or settings.lead_qualify_max_pages), timeout=90)
    result = analyze(site)
    issue_dicts = [i.__dict__ for i in result.issues]
    facts = result.facts
    unreachable = any(i.code == "HOME_UNREACHABLE" for i in result.issues) or not site.pages
    gaps = [_gap("HOME_UNREACHABLE", (site.errors or [""])[0])] if unreachable else gaps_from_analysis(facts, issue_dicts, result.scores)
    home = site.pages[0] if site.pages else None
    return {
        "website_score": None if unreachable else round(result.overall, 1),
        "scores": {k: round(v, 1) for k, v in result.scores.items()},
        "gaps": gaps,
        "pages_crawled": len(site.pages),
        "facts": {
            "https": facts.get("https"), "sitemap_found": facts.get("sitemap_found"), "schema_types": (facts.get("schema_types") or [])[:8],
            "home_ttfb_ms": facts.get("home_ttfb_ms"), "avg_word_count": facts.get("avg_word_count"),
            "title": (home.title if home else "")[:200], "has_phone": bool(home and home.has_phone), "has_email": bool(home and home.has_email),
            "issue_counts": facts.get("issue_counts") or {},
        },
        "unreachable": unreachable,
    }
