"""AI-powered (with rule-based fallback) insights: audit summaries, keyword ideas, action plans."""
from __future__ import annotations

import logging
import re
from collections import Counter
from itertools import pairwise
from typing import Any
from urllib.parse import urlparse

from app.services.ai.provider import ai_client

log = logging.getLogger(__name__)

STOPWORDS = set(
    ["a", "an", "the", "and", "or", "of", "to", "in", "for", "on", "with", "at", "by", "from", "is", "are", "was", "were", "be", "been", "being", "this", "that", "these", "those", "it", "its", "as", "your", "you", "we", "our", "us", "they", "them", "their", "he", "she", "his", "her", "i", "my", "me", "not", "no", "yes", "but", "if", "then", "than", "so", "such", "can", "will", "just", "about", "into", "over", "under", "more", "most", "very", "also", "all", "any", "each", "few", "other", "some", "own", "same", "too", "s", "t", "don", "should", "now", "here", "there", "home", "page", "welcome", "contact", "us", "menu", "click", "read", "learn", "get", "new", "best", "top", "free", "online", "copyright", "rights", "reserved", "privacy", "policy", "terms", "cookies", "login", "sign", "up", "log", "in"]
)


# --------------------------------------------------------------------------- #
# Audit insights
# --------------------------------------------------------------------------- #
def _issue_digest(issues: list[dict[str, Any]], limit: int = 25) -> str:
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    top = sorted(issues, key=lambda i: order.get(i["severity"], 5))[:limit]
    lines = [f"- [{i['severity']}] ({i['category']}) {i['title']}" + (f" @ {i['page_url']}" if i.get("page_url") else "") for i in top]
    return "\n".join(lines)


async def generate_audit_insights(website: dict[str, Any], facts: dict[str, Any], scores: dict[str, float],
                                  issues: list[dict[str, Any]], homepage_text: str) -> dict[str, Any]:
    fallback = _rule_based_insights(website, facts, scores, issues)
    if not ai_client.available:
        return fallback
    system = (
        "You are a senior SEO + AEO (answer engine optimisation) strategist. You write concise, specific, "
        "actionable advice for small/medium business owners. Avoid generic fluff."
    )
    user = f"""Website: {website.get('url')}
Business name: {website.get('name') or '(unknown)'} | Industry: {website.get('industry') or '(unknown)'} | Target location: {website.get('target_location') or '(unknown)'}
Description: {website.get('description') or '(none)'}

Scores (0-100): {scores}
Site facts: pages crawled={facts.get('pages_crawled')}, https={facts.get('https')}, sitemap={facts.get('sitemap_found')}, robots={facts.get('robots_txt_found')}, schema types={facts.get('schema_types')}, faq pages={facts.get('faq_pages')}, blocked AI bots={facts.get('robots_blocks_ai_bots')}, llms.txt={facts.get('llms_txt_found')}

Top issues:
{_issue_digest(issues)}

Homepage text excerpt:
\"\"\"{homepage_text[:1200]}\"\"\"

Return JSON with keys:
- "executive_summary": 3-4 sentence plain-English summary of where the site stands for Google ranking + AI search visibility.
- "quick_wins": array of 5 objects {{"title","why","how"}} that can be done this week.
- "strategic_priorities": array of 3-4 objects {{"title","why","how"}} for the next 90 days.
- "aeo_recommendations": array of 3-5 strings specific to featured snippets / AI Overviews / ChatGPT visibility.
- "content_ideas": array of 6 objects {{"title","type","target_query"}} (type = blog|landing|faq|comparison|guide).
- "keyword_themes": array of 5-8 short keyword phrases the site should own (include location if local business).
"""
    try:
        data = await ai_client.complete_json(system, user, max_tokens=2200)
        if data.get("executive_summary"):
            data["provider"] = ai_client.provider
            return data
    except Exception as exc:  # network / quota / etc.
        log.warning("AI insights failed, using fallback: %s", exc)
    return fallback


def _rule_based_insights(website: dict[str, Any], facts: dict[str, Any], scores: dict[str, float],
                         issues: list[dict[str, Any]]) -> dict[str, Any]:
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    sorted_issues = sorted(issues, key=lambda i: (order.get(i["severity"], 5), -i.get("impact", 0)))
    unique: dict[str, dict[str, Any]] = {}
    for i in sorted_issues:
        unique.setdefault(i["code"], i)
    top = list(unique.values())

    weakest = sorted(scores.items(), key=lambda kv: kv[1])[:2]
    names = {"seo": "on-page SEO", "technical": "technical health", "content": "content depth", "aeo": "answer-engine optimisation",
             "ai": "AI search readiness", "performance": "performance", "social": "social presence"}
    from app.services.audit.analyzers import compute_overall

    overall = compute_overall(scores) if scores else 0
    weak_txt = " and ".join(f"{names.get(k, k)} ({v})" for k, v in weakest)
    crit = sum(1 for i in issues if i["severity"] == "critical")
    high = sum(1 for i in issues if i["severity"] == "high")
    summary = (
        f"{website.get('name') or website.get('domain') or 'The site'} currently scores about {overall}/100 across our checks. "
        f"The weakest areas are {weak_txt}. "
        f"We found {crit} critical and {high} high-priority issues across {facts.get('pages_crawled', 0)} crawled pages. "
        "Fixing the quick wins below typically lifts visibility within 2-6 weeks; the strategic items build durable rankings and AI citations."
    )
    quick = [{"title": i["title"], "why": i.get("description") or "Directly affects crawling, ranking or click-through.",
              "how": i.get("recommendation", "")} for i in top[:5]]
    strategic = [
        {"title": "Build topic clusters around core services", "why": "Google rewards sites that cover a topic comprehensively.",
         "how": "Create one pillar page per service plus 4-6 supporting articles answering related questions; interlink them."},
        {"title": "Win featured snippets & AI Overviews with FAQ content", "why": "Answer engines cite concise, well-structured answers.",
         "how": "Add question-style H2s with 40-60 word direct answers and FAQPage schema on every key page."},
        {"title": "Strengthen entity & trust signals", "why": "AI search recommends businesses it can verify.",
         "how": "Complete Organization schema with sameAs links, add author bios, reviews, and a Google Business Profile."},
        {"title": "Earn authoritative backlinks & mentions", "why": "Off-page authority remains the strongest ranking factor.",
         "how": "Get listed in relevant directories, publish 1 data-driven piece per month, and pitch it to industry sites."},
    ]
    aeo = [
        "Add a 'Frequently asked questions' section (5-8 real customer questions) with FAQPage JSON-LD to the homepage and service pages.",
        "Start each key section with a direct one-paragraph answer, then elaborate – this is what gets extracted into snippets.",
        "Use tables for pricing/comparisons and numbered lists for processes; both are heavily favoured in AI answers.",
        "Ensure AI crawlers (OAI-SearchBot, PerplexityBot, ClaudeBot, Google-Extended) are allowed in robots.txt and publish /llms.txt.",
        "Keep pages fresh: show 'Last updated' dates and refresh top pages quarterly.",
    ]
    ind = website.get("industry") or "your services"
    loc = website.get("target_location") or ""
    loc_sfx = f" in {loc}" if loc else ""
    content_ideas = [
        {"title": f"How much does {ind} cost{loc_sfx}? (2025 pricing guide)", "type": "guide", "target_query": f"{ind} cost{loc_sfx}"},
        {"title": f"Best {ind} providers{loc_sfx}: how to choose", "type": "comparison", "target_query": f"best {ind}{loc_sfx}"},
        {"title": f"{ind.title()} FAQ: answers to the 10 most common questions", "type": "faq", "target_query": f"{ind} questions"},
        {"title": f"Step-by-step: what to expect when you hire {ind}", "type": "blog", "target_query": f"how {ind} works"},
        {"title": f"{ind.title()}{loc_sfx} – service page with reviews & pricing", "type": "landing", "target_query": f"{ind}{loc_sfx}"},
        {"title": f"{ind.title()} mistakes to avoid (and how we prevent them)", "type": "blog", "target_query": f"{ind} mistakes"},
    ]
    themes = [t for t in [f"{ind}{loc_sfx}", f"best {ind}{loc_sfx}", f"{ind} near me", f"{ind} cost", f"affordable {ind}{loc_sfx}", f"{ind} services"] if t.strip()]
    return {
        "provider": "rule-based",
        "executive_summary": summary,
        "quick_wins": quick,
        "strategic_priorities": strategic,
        "aeo_recommendations": aeo,
        "content_ideas": content_ideas,
        "keyword_themes": themes,
    }


# --------------------------------------------------------------------------- #
# Keyword suggestions
# --------------------------------------------------------------------------- #
def _extract_terms(text: str, top_n: int = 15) -> list[str]:
    words = [w for w in re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", text.lower()) if w not in STOPWORDS]
    uni = Counter(words)
    bigrams = Counter(f"{a} {b}" for a, b in pairwise(words) if a not in STOPWORDS and b not in STOPWORDS)
    terms = [t for t, _ in bigrams.most_common(top_n)] + [t for t, _ in uni.most_common(top_n)]
    out: list[str] = []
    for t in terms:
        if t not in out:
            out.append(t)
    return out[:top_n]


async def suggest_keywords(website: dict[str, Any], page_texts: list[str], titles: list[str], existing: list[str]) -> dict[str, Any]:
    corpus = " ".join(titles) + " " + " ".join(page_texts)
    site_terms = _extract_terms(corpus, top_n=20)
    if ai_client.available:
        system = "You are an SEO keyword strategist. Suggest realistic, high-intent keywords a small business site can rank for."
        user = f"""Website: {website.get('url')} | Name: {website.get('name')} | Industry: {website.get('industry')} | Location: {website.get('target_location')}
Description: {website.get('description')}
Page titles: {titles[:15]}
Frequent site terms: {site_terms}
Already tracked: {existing[:30]}

Return JSON: {{"suggestions": [{{"term": "...", "intent": "informational|commercial|transactional|navigational", "reason": "short reason"}}]}}
Give 15 suggestions, mixing local (if applicable), commercial and question-style informational queries. Exclude already-tracked terms."""
        try:
            data = await ai_client.complete_json(system, user, max_tokens=1500)
            if data.get("suggestions"):
                return {"provider": ai_client.provider, "suggestions": data["suggestions"][:20]}
        except Exception as exc:
            log.warning("AI keyword suggestion failed: %s", exc)
    # Fallback: combine industry/location with site terms
    ind = (website.get("industry") or "").strip()
    loc = (website.get("target_location") or "").strip()
    cands: list[dict[str, str]] = []
    if ind:
        base = [ind, f"best {ind}", f"{ind} near me", f"{ind} cost", f"{ind} price", f"affordable {ind}", f"{ind} services", f"how to choose {ind}"]
        for b in base:
            cands.append({"term": f"{b} in {loc}" if loc and "near me" not in b else b,
                          "intent": "informational" if b.startswith(("how", "what")) or "cost" in b or "price" in b else "commercial",
                          "reason": "Industry + location modifier" if loc else "Industry modifier"})
    for t in site_terms[:10]:
        if len(t.split()) >= 2:
            cands.append({"term": t, "intent": "informational", "reason": "Frequent phrase on your site"})
    existing_l = {e.lower() for e in existing}
    out, seen = [], set()
    for c in cands:
        k = c["term"].lower()
        if k in existing_l or k in seen:
            continue
        seen.add(k)
        out.append(c)
    return {"provider": "rule-based", "suggestions": out[:15]}


# --------------------------------------------------------------------------- #
# Action plan
# --------------------------------------------------------------------------- #
async def generate_plan(website: dict[str, Any], issues: list[dict[str, Any]], scores: dict[str, float],
                        keywords: list[str], horizon_weeks: int, focus: str) -> dict[str, Any]:
    fallback = _rule_based_plan(website, issues, scores, keywords, horizon_weeks, focus)
    if not ai_client.available:
        return fallback
    system = "You are a growth marketer building week-by-week SEO/AEO/social execution plans for a small business."
    user = f"""Website: {website.get('url')} | Name: {website.get('name')} | Industry: {website.get('industry')} | Location: {website.get('target_location')}
Goal/focus: {focus or 'improve Google rankings and AI search visibility'}
Horizon: {horizon_weeks} weeks
Scores: {scores}
Tracked keywords: {keywords[:20]}
Open issues:
{_issue_digest(issues, 30)}

Return JSON: {{"strategy_summary": "2-3 sentences", "weeks": [{{"week": 1, "theme": "...", "tasks": [{{"title": "...", "description": "concrete how-to", "category": "seo|technical|content|aeo|ai|performance|social|outreach", "priority": "low|medium|high|critical"}}]}}]}}
3-5 tasks per week. Week 1 must fix critical/high issues. Later weeks: content, AEO/FAQ, social distribution, link building, measurement."""
    try:
        data = await ai_client.complete_json(system, user, max_tokens=3000)
        if data.get("weeks"):
            data["provider"] = ai_client.provider
            return data
    except Exception as exc:
        log.warning("AI plan failed: %s", exc)
    return fallback


def _rule_based_plan(website: dict[str, Any], issues: list[dict[str, Any]], scores: dict[str, float],
                     keywords: list[str], horizon_weeks: int, focus: str) -> dict[str, Any]:
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    unique: dict[str, dict[str, Any]] = {}
    for i in sorted(issues, key=lambda i: order.get(i["severity"], 5)):
        unique.setdefault(i["code"], i)
    fix_tasks = [
        {"title": f"Fix: {i['title']}", "description": (i.get("recommendation") or i.get("description") or ""),
         "category": i["category"], "priority": "critical" if i["severity"] == "critical" else ("high" if i["severity"] == "high" else "medium")}
        for i in list(unique.values()) if i["severity"] in ("critical", "high", "medium")
    ]
    ind = website.get("industry") or "your service"
    loc = website.get("target_location") or ""
    loc_sfx = f" in {loc}" if loc else ""
    kw = keywords[:3] if keywords else [f"{ind}{loc_sfx}"]
    library = [
        ("Foundation & critical fixes", fix_tasks[:5] or [{"title": "Set up Google Search Console & Analytics", "description": "Verify the domain, submit the sitemap, enable GA4.", "category": "technical", "priority": "high"}]),
        ("On-page optimisation", [*fix_tasks[5:9],
            {"title": f"Optimise homepage for '{kw[0]}'", "description": "Rewrite title, H1, first paragraph and meta description around the primary keyword; add internal links to service pages.", "category": "seo", "priority": "high"},
            {"title": "Set up Google Business Profile" if loc else "Complete Organization schema", "description": "Claim/complete the profile with categories, photos, hours, services and a weekly post cadence." if loc else "Add JSON-LD with logo, sameAs, contact and address.", "category": "aeo", "priority": "high"},
        ]),
        ("Answer-engine content", [
            {"title": "Publish FAQ section with FAQPage schema", "description": "8 real customer questions with 40-60 word direct answers on the homepage and top service page.", "category": "aeo", "priority": "high"},
            {"title": f"Write pillar guide: '{ind.title()}{loc_sfx} – complete guide'", "description": "1500+ words, question-style H2s, pricing table, process steps, CTA.", "category": "content", "priority": "medium"},
            {"title": "Publish /llms.txt and allow AI crawlers", "description": "Curated Markdown summary of the business + key URLs; ensure robots.txt allows OAI-SearchBot, PerplexityBot, ClaudeBot.", "category": "ai", "priority": "medium"},
        ]),
        ("Distribution & social", [
            {"title": "Create 8 social posts from the pillar guide", "description": "Carousel + short video + 3 quote graphics; schedule across Instagram, LinkedIn and Facebook.", "category": "social", "priority": "medium"},
            {"title": "Add OG/Twitter meta tags site-wide", "description": "Rich previews for every share.", "category": "social", "priority": "medium"},
            {"title": "Collect 5 new Google reviews", "description": "Send a review link to recent happy customers via WhatsApp/email.", "category": "outreach", "priority": "medium"},
        ]),
        ("Authority building", [
            {"title": "Submit to 10 relevant directories/citations", "description": "Consistent NAP; prioritise industry and local directories.", "category": "outreach", "priority": "medium"},
            {"title": "Pitch one guest article / expert quote", "description": "Target 3 industry blogs or local news sites with a data-backed angle.", "category": "outreach", "priority": "low"},
            {"title": f"Publish supporting article for '{kw[1] if len(kw) > 1 else kw[0]}'", "description": "800-1200 words, interlink with the pillar page.", "category": "content", "priority": "medium"},
        ]),
        ("Measure & iterate", [
            {"title": "Review rank tracker & Search Console", "description": "Identify pages ranking 5-20 and refresh them (add FAQs, internal links, updated data).", "category": "seo", "priority": "medium"},
            {"title": "Speed pass on top 5 pages", "description": "Compress images to WebP, lazy-load, remove unused scripts; target LCP < 2.5s.", "category": "performance", "priority": "medium"},
            {"title": "Plan next month's content calendar", "description": "4 posts targeting 'People also ask' questions from Search Console queries.", "category": "content", "priority": "low"},
        ]),
    ]
    weeks = []
    for w in range(1, horizon_weeks + 1):
        theme, tasks = library[(w - 1) % len(library)]
        if w > len(library):
            theme = f"{theme} (cycle {((w - 1) // len(library)) + 1})"
        weeks.append({"week": w, "theme": theme, "tasks": tasks[:5]})
    summary = (
        f"Over the next {horizon_weeks} weeks we first remove technical blockers, then optimise the pages that matter for "
        f"'{kw[0]}', build answer-engine friendly FAQ/guide content, distribute it socially and earn citations. "
        f"{'Focus: ' + focus if focus else ''}"
    ).strip()
    return {"provider": "rule-based", "strategy_summary": summary, "weeks": weeks}


# --------------------------------------------------------------------------- #
# Social post drafts (used by phase-2 UI, exposed via API now)
# --------------------------------------------------------------------------- #
async def draft_social_posts(website: dict[str, Any], topic: str, platforms: list[str], tone: str = "friendly") -> dict[str, Any]:
    if ai_client.available:
        system = "You are a social media copywriter for small businesses. Write platform-native posts with hooks, value and a CTA."
        user = f"""Business: {website.get('name')} ({website.get('url')}) | Industry: {website.get('industry')} | Location: {website.get('target_location')}
Topic: {topic}
Tone: {tone}
Platforms: {platforms}
Return JSON: {{"posts": [{{"platform": "...", "content": "...", "hashtags": ["..."], "image_idea": "..."}}]}}"""
        try:
            data = await ai_client.complete_json(system, user, max_tokens=1500)
            if data.get("posts"):
                return {"provider": ai_client.provider, "posts": data["posts"]}
        except Exception as exc:
            log.warning("AI social drafting failed: %s", exc)
    name = website.get("name") or urlparse(website.get("url", "")).netloc
    posts = []
    for p in platforms:
        posts.append({
            "platform": p,
            "content": f"{topic}\n\nAt {name}, we help {website.get('industry') or 'our customers'} get real results. Here's what you should know: (1) why it matters, (2) common mistakes, (3) how we do it differently.\n\nWant to know more? Visit {website.get('url')}",
            "hashtags": [f"#{re.sub(r'[^a-zA-Z0-9]', '', (website.get('industry') or 'business'))}", "#SmallBusiness", f"#{re.sub(r'[^a-zA-Z0-9]', '', website.get('target_location') or 'Local')}"],
            "image_idea": f"Clean branded graphic with the headline '{topic}' and your logo.",
        })
    return {"provider": "rule-based", "posts": posts}
