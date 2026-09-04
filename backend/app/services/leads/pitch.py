"""Personalised outreach copy for a lead: email, WhatsApp/DM message and two follow-ups.

Uses the configured LLM when available, otherwise a rule-based writer that still personalises on the
prospect's real gaps (from the mini audit) and the sender's own strengths.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.ai.provider import ai_client

log = logging.getLogger(__name__)


def _sender(website: dict[str, Any]) -> dict[str, str]:
    return {
        "name": website.get("name") or website.get("domain") or "our team",
        "url": website.get("url") or "",
        "industry": website.get("industry") or "digital marketing",
        "location": website.get("target_location") or "",
        "description": (website.get("description") or "")[:300],
    }


def _angle(lead: dict[str, Any]) -> dict[str, Any]:
    gaps: list[dict[str, Any]] = (lead.get("audit") or {}).get("gaps") or []
    company = lead.get("company") or "your business"
    if not lead.get("website_url"):
        return {"headline": f"{company} has no website Google can find",
                "hook": f"I looked for {company} online and couldn't find a website – customers searching for you right now are landing on competitors.",
                "offer": "a simple, fast website that ranks for local searches", "gap_lines": ["No website found"]}
    if gaps and gaps[0]["code"] == "HOME_UNREACHABLE":
        return {"headline": f"{company}'s website isn't loading",
                "hook": f"I tried opening {lead.get('website_url')} today and it didn't load – that quietly costs enquiries every day.",
                "offer": "getting the site back up, fast and secure", "gap_lines": ["Website unreachable"]}
    top = gaps[:3]
    lines = [g["label"] + (f" ({g['detail']})" if g.get("detail") and len(g["detail"]) < 40 else "") for g in top]
    offers = []
    for g in top:
        if g["pitch"] not in offers:
            offers.append(g["pitch"])
    score = lead.get("website_score")
    score_txt = f" It scores {score:.0f}/100 on our SEO & AI-search check." if isinstance(score, (int, float)) else ""
    return {
        "headline": f"{min(len(gaps), 3)} quick wins for {company}'s website" if gaps else f"Ideas for growing {company} online",
        "hook": f"I ran a quick health check on {lead.get('website_url')}.{score_txt} A few things are quietly holding it back on Google and in AI search:" if lines else f"I had a look at {lead.get('website_url')} and noticed a few things that could bring in more customers.",
        "offer": " and ".join(offers[:2]) if offers else "more visibility on Google and AI search",
        "gap_lines": lines,
    }


def rule_based_pitch(website: dict[str, Any], lead: dict[str, Any]) -> dict[str, Any]:
    s = _sender(website)
    a = _angle(lead)
    company = lead.get("company") or "there"
    first = (lead.get("contact_name") or "").split(" ")[0] or "there"
    loc = f" in {lead.get('location')}" if lead.get("location") else ""
    bullets = "\n".join(f"• {l}" for l in a["gap_lines"][:3]) if a["gap_lines"] else "• A clearer Google presence\n• Content that answers what customers search for\n• Better conversion from visitors to enquiries"
    email_subject = a["headline"]
    email_body = f"""Hi {first},

{a['hook']}
{bullets}

We're {s['name']}{' (' + s['url'] + ')' if s['url'] else ''} – we help {lead.get('category') or 'businesses'}{loc} get found on Google and AI search and turn visitors into customers. Fixing these usually takes 2–4 weeks and starts showing results within 4–8 weeks.

Happy to send over the full report (free, no strings). Would a 15-minute call this week work?

Best,
{s['name']}
{s['url']}"""
    whatsapp = f"Hi {first}, this is {s['name']}. I ran a quick health check on {company}'s online presence{loc} and found a few things costing you enquiries ({', '.join(a['gap_lines'][:2]) if a['gap_lines'] else 'visibility on Google'}). Can I send you the free report?"
    follow_ups = [
        {"day": 3, "channel": "email", "subject": f"Re: {email_subject}",
         "body": f"Hi {first},\n\nJust floating this to the top of your inbox. The free report for {company} is ready – it shows exactly what to fix and in what order. Shall I send it?\n\n{s['name']}"},
        {"day": 8, "channel": "whatsapp", "subject": "",
         "body": f"Hi {first}, last nudge from {s['name']} 🙂 If growing {company} online isn't a priority right now, no problem at all – just let me know and I'll close the file. If it is, I'm happy to walk you through the report in 15 minutes."},
    ]
    return {"provider": "rule-based", "angle": a["headline"], "hook": a["hook"], "offer": a["offer"],
            "email": {"subject": email_subject, "body": email_body}, "whatsapp": whatsapp, "follow_ups": follow_ups}


async def write_pitch(website: dict[str, Any], lead: dict[str, Any], tone: str = "friendly") -> dict[str, Any]:
    if ai_client.available:
        s = _sender(website)
        a = _angle(lead)
        system = ("You write short, specific, non-spammy B2B outreach for a digital marketing / SEO agency. Personalise on the "
                  "prospect's actual website gaps. No hype, no exclamation marks in subject lines, plain language, under 150 words per message.")
        user = f"""Sender: {s['name']} ({s['url']}) – {s['industry']}{' in ' + s['location'] if s['location'] else ''}. {s['description']}
Prospect: {lead.get('company')} | category: {lead.get('category')} | location: {lead.get('location')} | website: {lead.get('website_url') or 'NONE'} | rating: {lead.get('rating')} ({lead.get('reviews')} reviews)
Website health score: {lead.get('website_score')}
Gaps found: {a['gap_lines']}
Suggested angle: {a['headline']} – offer: {a['offer']}
Tone: {tone}
Return JSON: {{"angle": "one line", "hook": "one sentence", "offer": "what we'd fix",
 "email": {{"subject": "...", "body": "..."}}, "whatsapp": "short WhatsApp/DM message",
 "follow_ups": [{{"day": 3, "channel": "email", "subject": "...", "body": "..."}}, {{"day": 8, "channel": "whatsapp", "subject": "", "body": "..."}}]}}"""
        try:
            data = await ai_client.complete_json(system, user, max_tokens=1200)
            if data.get("email", {}).get("body"):
                data["provider"] = ai_client.provider
                data.setdefault("follow_ups", [])
                return data
        except Exception as exc:
            log.warning("AI pitch failed: %s", exc)
    return rule_based_pitch(website, lead)
