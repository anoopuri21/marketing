"""Content planner: turns a website's context (audit insights, keywords, GSC queries) into a
week-by-week social calendar with platform-native copy, hashtags and a creative brief per post.

Works with an LLM when configured and falls back to a rule-based generator otherwise.
"""
from __future__ import annotations

import logging
import random
import re
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.services.ai.provider import ai_client

log = logging.getLogger(__name__)

# Best-practice posting windows (local time) per platform – used when scheduling a plan.
BEST_TIMES: dict[str, list[time]] = {
    "instagram": [time(11, 0), time(19, 0)],
    "facebook": [time(13, 0), time(20, 0)],
    "linkedin": [time(9, 0), time(12, 30)],
    "x": [time(10, 0), time(18, 0)],
    "webhook": [time(10, 0)],
    "google_business": [time(10, 0)],
}
POST_TYPES = ["tip", "faq", "behind_the_scenes", "offer", "testimonial", "stat", "myth", "checklist", "story", "announcement"]
TEMPLATE_FOR_TYPE = {"tip": "gradient", "faq": "split", "behind_the_scenes": "minimal", "offer": "bold", "testimonial": "quote", "stat": "stat",
                     "myth": "bold", "checklist": "split", "story": "minimal", "announcement": "bold"}


def _hashtag(s: str) -> str:
    return "#" + re.sub(r"[^A-Za-z0-9]", "", s.title())[:30]


def short_topic(topic: str, max_words: int = 7) -> str:
    """Trim long audit titles ("How much does X cost in Y? (2025 pricing guide)") down to a headline-sized phrase."""
    t = re.sub(r"\s*\(.*?\)\s*", " ", topic)  # drop parentheticals
    t = re.split(r"[:|–—-]\s", t)[0].strip()      # keep the part before a colon/dash
    t = re.sub(r"^(how much does|how to|what is|what are|why|best|top \d+)\s+", "", t, flags=re.I) if len(t.split()) > max_words else t
    words = t.split()
    if len(words) > max_words:
        t = " ".join(words[:max_words])
    return t.strip(" ?!.,").strip()


async def generate_calendar(website: dict[str, Any], platforms: list[str], weeks: int, posts_per_week: int, tone: str,
                            themes: list[str], queries: list[str], content_ideas: list[dict[str, Any]], goals: str = "") -> dict[str, Any]:
    """Return {"provider", "strategy", "posts": [{week, day_offset, platform, type, topic, content, hashtags, creative: {...}}]}."""
    total = weeks * posts_per_week
    if ai_client.available:
        system = ("You are a senior social media strategist for small and local businesses. You write platform-native posts "
                  "(hooks first, short lines, one clear CTA), never generic filler, and you know what earns saves, shares and DMs.")
        user = f"""Business: {website.get('name')} ({website.get('url')}) | Industry: {website.get('industry') or 'unknown'} | Location: {website.get('target_location') or 'n/a'}
Description: {website.get('description') or 'n/a'}
Goals: {goals or 'more enquiries and Google visibility'}
Tone: {tone}
Platforms: {platforms}
Keyword themes to reinforce: {themes[:8]}
Real Google queries people use to find them: {queries[:12]}
Content ideas from the SEO audit: {[c.get('title') for c in content_ideas[:6]]}

Create a {weeks}-week calendar with {posts_per_week} posts per week ({total} posts total), rotating post types among {POST_TYPES}
and spreading posts across the platforms. Every post must be specific to this business – mention real services, local context and answer real questions.
Return JSON: {{"strategy": "2-3 sentences", "posts": [{{"week": 1, "day_offset": 0-6, "platform": "...", "type": "...", "topic": "short topic",
"content": "full post text without hashtags", "hashtags": ["..."], "creative": {{"headline": "max 9 words for the image", "subline": "max 20 words or a 3-5 item list", "cta": "max 4 words", "template": "bold|gradient|split|quote|stat|minimal"}}}}]}}"""
        try:
            data = await ai_client.complete_json(system, user, max_tokens=6000)
            posts = data.get("posts") or []
            if posts:
                for p in posts:
                    p.setdefault("creative", {})
                    p["platform"] = p.get("platform") if p.get("platform") in platforms else platforms[0]
                    p["type"] = p.get("type") if p.get("type") in POST_TYPES else "tip"
                    p["week"] = int(p.get("week") or 1)
                    p["day_offset"] = int(p.get("day_offset") or 0) % 7
                    p["hashtags"] = [h if str(h).startswith("#") else f"#{h}" for h in (p.get("hashtags") or [])][:8]
                return {"provider": ai_client.provider, "strategy": data.get("strategy", ""), "posts": posts[:total]}
        except Exception as exc:
            log.warning("AI calendar failed, using rule-based: %s", exc)
    return _rule_based_calendar(website, platforms, weeks, posts_per_week, tone, themes, queries, content_ideas)


def _rule_based_calendar(website: dict[str, Any], platforms: list[str], weeks: int, posts_per_week: int, tone: str,
                         themes: list[str], queries: list[str], content_ideas: list[dict[str, Any]]) -> dict[str, Any]:
    name = website.get("name") or website.get("url", "").replace("https://", "").replace("http://", "")
    industry = website.get("industry") or "our field"
    location = website.get("target_location") or ""
    loc = f" in {location}" if location else ""
    url = website.get("url", "")
    # Interleave sources so a short calendar still mixes real queries, keyword themes and audit content ideas
    sources = [[str(q) for q in queries[:10]], [str(t) for t in themes], [c.get("title", "") for c in content_ideas if c.get("title")]]
    topics: list[str] = []
    for i in range(max((len(src) for src in sources), default=0)):
        for src in sources:
            if i < len(src):
                topics.append(src[i])
    topics = [t for t in dict.fromkeys(t.strip() for t in topics) if t] or [f"{industry}{loc}", f"how to choose the right {industry} partner", f"common {industry} mistakes"]
    rng = random.Random(f"{name}{weeks}{posts_per_week}")
    base_tags = [_hashtag(industry)] + ([_hashtag(location)] if location else []) + ["#SmallBusiness", _hashtag(name)]
    posts: list[dict[str, Any]] = []
    day_slots = [0, 2, 4, 1, 3, 5, 6]
    i = 0
    for week in range(1, weeks + 1):
        for slot in range(posts_per_week):
            ptype = POST_TYPES[i % len(POST_TYPES)]
            topic = topics[i % len(topics)]
            platform = platforms[i % len(platforms)]
            content, headline, subline, cta = _copy_for(ptype, short_topic(topic), name, industry, location, url, tone, rng)
            posts.append({
                "week": week, "day_offset": day_slots[slot % len(day_slots)], "platform": platform, "type": ptype, "topic": topic,
                "content": content, "hashtags": base_tags[:3] + [_hashtag(short_topic(topic, 4))][:1],
                "creative": {"headline": headline, "subline": subline, "cta": cta, "template": TEMPLATE_FOR_TYPE.get(ptype, "bold")},
            })
            i += 1
    strategy = (f"Rotate education (tips, FAQs, checklists), proof (testimonials, results) and offers so followers learn something every week and "
                f"know exactly how to hire {name}{loc}. Each post reinforces a keyword theme the website should rank for, and links back to a page that answers the question.")
    return {"provider": "rule-based", "strategy": strategy, "posts": posts}


def _copy_for(ptype: str, topic: str, name: str, industry: str, location: str, url: str, tone: str, rng: random.Random):
    loc = f" in {location}" if location else ""
    t = topic.rstrip("?")
    tl = t[0].lower() + t[1:] if t else t
    if ptype == "tip":
        return (f"Quick tip on {tl}:\n\nMost people get this wrong because nobody explains it plainly. Here's the short version -\n1) Know what you actually need\n2) Compare at least two options\n3) Ask what's NOT included\n\nSave this for later, and DM us if you want a straight answer for your situation.",
                f"Quick tip: {t}", "Know what you need · Compare options · Ask what's not included", "Save this")
    if ptype == "faq":
        return (f"\"{t}?\" - we get asked this every week.\n\nShort answer: it depends on your situation, but there are three things that matter most. We wrote a plain-English guide that walks through each one.\n\nRead it here: {url}",
                f"{t}?", "The plain-English answer, in 3 points", "Read the guide")
    if ptype == "behind_the_scenes":
        return (f"Behind the scenes at {name} today.\n\nA lot of what we do around {tl} never makes it to the website - the checks, the back-and-forth, the small details that keep things smooth for you.\n\nQuestions about how we work? Ask below.",
                f"Behind the scenes at {name}", f"How we handle {tl} - the parts you don't see", "")
    if ptype == "offer":
        return (f"This month at {name}{loc}: book a free consultation about {tl}.\n\nNo pitch, just clear answers and a plan you can use - whether you work with us or not.\n\nSpots are limited, message us to grab one.",
                f"Free consultation: {t}", "Clear answers, no pressure. Limited spots this month.", "Book now")
    if ptype == "testimonial":
        return (f"\"They made {tl} feel simple. Clear pricing, quick replies, and they did what they said.\" - a happy client{loc}\n\nThis is the standard we hold ourselves to at {name}. Thank you for trusting us!",
                f"They made {tl} feel simple. Clear pricing, quick replies.", f"Client review, {location or name}", "")
    if ptype == "stat":
        pct = rng.choice([68, 72, 81, 87, 93])
        return (f"{pct}% of people research {tl} online before they ever make a call.\n\nIf your questions aren't answered clearly somewhere, they simply move on. That's why we publish honest guides on exactly this.\n\nWhat's the one thing you wish someone had told you about {tl}?",
                f"{pct}% research {tl} online first", "Be the clear answer they find.", "Learn more")
    if ptype == "myth":
        return (f"Myth: {t} is only for big budgets.\n\nReality: the biggest wins usually come from getting a few basics right - and most of them cost time, not money.\n\nWe break down where to start in our guide: {url}",
                f"Myth: {t} is only for big budgets", "Reality: the basics matter more than the budget", "See why")
    if ptype == "checklist":
        return (f"Your 5-point checklist for {tl}:\n\n1. Define the outcome you want\n2. Set a realistic budget range\n3. Check reviews and past work\n4. Get everything in writing\n5. Agree on how you'll measure success\n\nScreenshot this - it'll save you a headache later.",
                f"5-point checklist: {t}", "1. Define the outcome 2. Set a budget 3. Check reviews 4. Get it in writing 5. Measure success", "Save this")
    if ptype == "story":
        return (f"A client came to us last month completely stuck on {tl}. Three conversations later they had a clear plan and one less thing to worry about.\n\nThat's the part of this job we love{' here' + loc if loc else ''}. If you're in the same spot, you know where to find us.",
                f"From stuck to sorted: {t}", f"A recent client story from {name}", "")
    return (f"News from {name}: we've just published a new resource on {tl}.\n\nIt answers the questions we hear most often, in plain language. Have a look and tell us what we missed: {url}",
            f"New: {t}", f"Fresh from {name}", "Take a look")


def schedule_times(posts: list[dict[str, Any]], start: datetime, tz_name: str) -> list[datetime]:
    """Assign a concrete UTC datetime to each planned post using best-practice local posting windows."""
    try:
        tz = ZoneInfo(tz_name or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    start_local = start.astimezone(tz)
    # start on the next day so the client can review first
    day0 = (start_local + timedelta(days=1)).date()
    out: list[datetime] = []
    per_day_count: dict[Any, int] = {}
    for p in posts:
        d = day0 + timedelta(days=(int(p.get("week", 1)) - 1) * 7 + int(p.get("day_offset", 0)))
        windows = BEST_TIMES.get(p.get("platform", ""), [time(10, 0)])
        n = per_day_count.get((d, p.get("platform")), 0)
        per_day_count[(d, p.get("platform"))] = n + 1
        slot = windows[n % len(windows)]
        local_dt = datetime.combine(d, slot, tzinfo=tz) + timedelta(minutes=15 * (n // len(windows)))
        out.append(local_dt.astimezone(UTC))
    return out
