"""Social publishing API: channel connections, posts (draft → scheduled → published), AI calendar."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DB, OwnedWebsite
from app.models import Audit, Creative, Integration, Keyword, SearchQueryStat, SocialPost
from app.models.entities import aware
from app.services.ai.insights import draft_social_posts
from app.services.creatives.studio import render_template_creative
from app.services.social.planner import generate_calendar, schedule_times
from app.services.social.publishers import PLATFORMS, compose_text
from app.services.social.service import connected_platforms, post_to_dict, publish_post

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["social"])

SECRET_HINTS = ("token", "secret", "password", "key")


# --------------------------------------------------------------------------- #
# schemas
# --------------------------------------------------------------------------- #
class ChannelUpsert(BaseModel):
    platform: str
    config: Dict[str, Any] = Field(default_factory=dict)


class PostIn(BaseModel):
    platform: str
    content: str = ""
    topic: str = ""
    hashtags: List[str] = Field(default_factory=list)
    link_url: str = ""
    creative_id: Optional[int] = None
    media_urls: List[str] = Field(default_factory=list)
    scheduled_for: Optional[datetime] = None  # if set → status scheduled
    status: Optional[str] = None  # draft|scheduled (explicit override)


class PostUpdate(BaseModel):
    platform: Optional[str] = None
    content: Optional[str] = None
    topic: Optional[str] = None
    hashtags: Optional[List[str]] = None
    link_url: Optional[str] = None
    creative_id: Optional[int] = None
    media_urls: Optional[List[str]] = None
    scheduled_for: Optional[datetime] = None
    status: Optional[str] = None


class CalendarIn(BaseModel):
    platforms: List[str] = Field(default_factory=lambda: ["instagram", "facebook", "linkedin"])
    weeks: int = Field(default=2, ge=1, le=8)
    posts_per_week: int = Field(default=3, ge=1, le=7)
    tone: str = "friendly"
    goals: str = ""
    timezone: str = "UTC"
    generate_creatives: bool = True
    auto_schedule: bool = False  # True → posts are created as scheduled (only for connected channels)


class DraftIn(BaseModel):
    topic: str
    platforms: List[str] = Field(default_factory=lambda: ["instagram", "linkedin", "facebook"])
    tone: str = "friendly"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _mask(config: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k, v in (config or {}).items():
        out[k] = "••••••" if v and any(h in k for h in SECRET_HINTS) else v
    return out


def _channel_out(row: Integration) -> Dict[str, Any]:
    meta = PLATFORMS.get(row.provider, {})
    return {"platform": row.provider, "label": meta.get("label", row.provider), "status": row.status, "config": _mask(row.config), "connected_at": aware(row.connected_at),
            "last_error": row.last_error or "", "summary": row.summary or {}, "last_used_at": aware(row.last_synced_at)}


async def _get_post(db, website_id: int, post_id: int) -> SocialPost:
    post = await db.get(SocialPost, post_id)
    if post is None or post.website_id != website_id:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


async def _check_creative(db, website_id: int, creative_id: Optional[int]) -> Optional[Creative]:
    if creative_id is None:
        return None
    c = await db.get(Creative, creative_id)
    if c is None or c.website_id != website_id:
        raise HTTPException(status_code=400, detail="Creative not found")
    return c


def _website_ctx(website) -> Dict[str, Any]:
    return {"url": website.url, "name": website.name, "industry": website.industry, "target_location": website.target_location, "description": website.description}


# --------------------------------------------------------------------------- #
# channels
# --------------------------------------------------------------------------- #
@router.get("/social/platforms")
async def platforms_catalog():
    return PLATFORMS


@router.get("/websites/{website_id}/social/channels")
async def list_channels(website: OwnedWebsite, db: DB):
    rows = (await db.execute(select(Integration).where(Integration.website_id == website.id, Integration.provider.in_(list(PLATFORMS))))).scalars().all()
    return [_channel_out(r) for r in rows]


@router.put("/websites/{website_id}/social/channels")
async def upsert_channel(payload: ChannelUpsert, website: OwnedWebsite, db: DB):
    meta = PLATFORMS.get(payload.platform)
    if meta is None:
        raise HTTPException(status_code=400, detail=f"Unknown platform. Supported: {', '.join(PLATFORMS)}")
    if meta["status"] != "live":
        raise HTTPException(status_code=400, detail=f"{meta['label']} publishing is not available yet")
    row = (await db.execute(select(Integration).where(Integration.website_id == website.id, Integration.provider == payload.platform))).scalar_one_or_none()
    if row is None:
        row = Integration(website_id=website.id, provider=payload.platform)
        db.add(row)
    incoming = {k: str(v).strip() for k, v in payload.config.items() if not (isinstance(v, str) and v.startswith("••••"))}
    row.config = {**(row.config or {}), **incoming}
    missing = [f for f in meta["fields"] if not row.config.get(f)]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing: {', '.join(missing)}")
    row.status = "connected"
    row.connected_at = row.connected_at or datetime.now(timezone.utc)
    row.last_error = ""
    await db.commit()
    await db.refresh(row)
    return _channel_out(row)


@router.delete("/websites/{website_id}/social/channels/{platform}", status_code=204)
async def delete_channel(platform: str, website: OwnedWebsite, db: DB):
    row = (await db.execute(select(Integration).where(Integration.website_id == website.id, Integration.provider == platform))).scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.commit()
    return None


@router.post("/websites/{website_id}/social/channels/{platform}/test")
async def test_channel(platform: str, website: OwnedWebsite, db: DB):
    """Send a test publish for webhook channels; for API channels validate the token with a read call."""
    import httpx

    from app.core.http import ssl_context
    from app.services.social.publishers import GRAPH, LINKEDIN, X_API, publish_webhook

    row = (await db.execute(select(Integration).where(Integration.website_id == website.id, Integration.provider == platform))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Channel not connected")
    cfg = row.config or {}
    ok, detail = False, ""
    try:
        if platform == "webhook":
            await publish_webhook(cfg, f"RankPilot test message for {website.domain}", None, website.url, {"test": True, "platform": "webhook"})
            ok, detail = True, "Webhook accepted the test payload"
        else:
            async with httpx.AsyncClient(timeout=30, verify=ssl_context()) as client:
                if platform in ("facebook", "instagram"):
                    obj = cfg.get("page_id") if platform == "facebook" else cfg.get("account_id")
                    resp = await client.get(f"{GRAPH}/{obj}", params={"fields": "id,name,username", "access_token": cfg.get("access_token", "")})
                    ok = resp.status_code == 200
                    detail = f"Connected to {resp.json().get('name') or resp.json().get('username') or obj}" if ok else resp.json().get("error", {}).get("message", resp.text[:200])
                elif platform == "linkedin":
                    org = cfg.get("organization_id", "")
                    resp = await client.get(f"{LINKEDIN}/organizations/{org}", headers={"Authorization": f"Bearer {cfg.get('access_token', '')}", "LinkedIn-Version": "202409"})
                    ok = resp.status_code == 200
                    detail = f"Connected to {resp.json().get('localizedName', org)}" if ok else resp.text[:200]
                elif platform == "x":
                    resp = await client.get(f"{X_API}/users/me", headers={"Authorization": f"Bearer {cfg.get('access_token', '')}"})
                    ok = resp.status_code == 200
                    detail = f"Connected as @{resp.json().get('data', {}).get('username', '?')}" if ok else resp.text[:200]
    except Exception as exc:
        detail = f"Could not reach {platform} ({type(exc).__name__}: {exc or 'connection failed'})"
    row.status = "connected" if ok else "error"
    row.last_error = "" if ok else detail[:500]
    await db.commit()
    return {"ok": ok, "detail": detail}


# --------------------------------------------------------------------------- #
# posts
# --------------------------------------------------------------------------- #
@router.get("/websites/{website_id}/social/posts")
async def list_posts(website: OwnedWebsite, db: DB, status: Optional[str] = None, limit: int = 200):
    stmt = select(SocialPost).where(SocialPost.website_id == website.id)
    if status:
        stmt = stmt.where(SocialPost.status.in_(status.split(",")))
    stmt = stmt.order_by(SocialPost.scheduled_for.is_(None), SocialPost.scheduled_for, SocialPost.id.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    creatives = {}
    ids = [r.creative_id for r in rows if r.creative_id]
    if ids:
        creatives = {c.id: c for c in (await db.execute(select(Creative).where(Creative.id.in_(ids)))).scalars().all()}
    return [post_to_dict(r, creatives.get(r.creative_id)) for r in rows]


@router.get("/websites/{website_id}/social/summary")
async def social_summary(website: OwnedWebsite, db: DB):
    counts = dict((await db.execute(select(SocialPost.status, func.count()).where(SocialPost.website_id == website.id).group_by(SocialPost.status))).all())
    channels = await connected_platforms(db, website.id)
    next_post = (await db.execute(select(SocialPost).where(SocialPost.website_id == website.id, SocialPost.status == "scheduled").order_by(SocialPost.scheduled_for))).scalars().first()
    return {"counts": counts, "connected": sorted(channels), "next_scheduled_for": aware(next_post.scheduled_for) if next_post else None,
            "total": sum(counts.values())}


@router.post("/websites/{website_id}/social/posts", status_code=201)
async def create_post(payload: PostIn, website: OwnedWebsite, db: DB):
    if payload.platform not in PLATFORMS:
        raise HTTPException(status_code=400, detail="Unknown platform")
    if not payload.content.strip():
        raise HTTPException(status_code=400, detail="content is required")
    creative = await _check_creative(db, website.id, payload.creative_id)
    status = payload.status or ("scheduled" if payload.scheduled_for else "draft")
    if status not in ("draft", "scheduled"):
        raise HTTPException(status_code=400, detail="status must be draft or scheduled")
    if status == "scheduled" and payload.scheduled_for is None:
        raise HTTPException(status_code=400, detail="scheduled_for is required to schedule")
    post = SocialPost(website_id=website.id, platform=payload.platform, content=payload.content.strip(), topic=payload.topic.strip()[:255],
                      hashtags=[h.strip() for h in payload.hashtags if h.strip()][:30], link_url=payload.link_url.strip(), creative_id=payload.creative_id,
                      media_urls=payload.media_urls, status=status, scheduled_for=payload.scheduled_for)
    db.add(post)
    await db.commit()
    await db.refresh(post)
    return post_to_dict(post, creative)


@router.patch("/websites/{website_id}/social/posts/{post_id}")
async def update_post(post_id: int, payload: PostUpdate, website: OwnedWebsite, db: DB):
    post = await _get_post(db, website.id, post_id)
    if post.status in ("published", "publishing"):
        raise HTTPException(status_code=409, detail="Published posts cannot be edited")
    data = payload.model_dump(exclude_unset=True)
    if "creative_id" in data:
        await _check_creative(db, website.id, data["creative_id"])
    if "platform" in data and data["platform"] not in PLATFORMS:
        raise HTTPException(status_code=400, detail="Unknown platform")
    new_status = data.pop("status", None)
    for k, v in data.items():
        setattr(post, k, v.strip() if isinstance(v, str) else v)
    if new_status:
        if new_status not in ("draft", "scheduled"):
            raise HTTPException(status_code=400, detail="status must be draft or scheduled")
        if new_status == "scheduled" and post.scheduled_for is None:
            raise HTTPException(status_code=400, detail="Set scheduled_for before scheduling")
        post.status = new_status
        post.error = ""
    elif post.status == "failed":
        post.status = "scheduled" if post.scheduled_for and aware(post.scheduled_for) > datetime.now(timezone.utc) else "draft"
        post.error = ""
    await db.commit()
    await db.refresh(post)
    creative = await db.get(Creative, post.creative_id) if post.creative_id else None
    return post_to_dict(post, creative)


@router.delete("/websites/{website_id}/social/posts/{post_id}", status_code=204)
async def delete_post(post_id: int, website: OwnedWebsite, db: DB):
    post = await _get_post(db, website.id, post_id)
    await db.delete(post)
    await db.commit()
    return None


@router.post("/websites/{website_id}/social/posts/{post_id}/publish")
async def publish_now(post_id: int, website: OwnedWebsite, db: DB):
    post = await _get_post(db, website.id, post_id)
    if post.status == "published":
        raise HTTPException(status_code=409, detail="Already published")
    await publish_post(db, website, post)
    await db.commit()
    await db.refresh(post)
    creative = await db.get(Creative, post.creative_id) if post.creative_id else None
    return post_to_dict(post, creative)


@router.get("/websites/{website_id}/social/posts/{post_id}/preview")
async def preview_text(post_id: int, website: OwnedWebsite, db: DB):
    post = await _get_post(db, website.id, post_id)
    return {"text": compose_text(post.content, post.hashtags or [], post.link_url, post.platform), "max_chars": PLATFORMS.get(post.platform, {}).get("max_chars")}


# --------------------------------------------------------------------------- #
# AI: quick drafts + full calendar
# --------------------------------------------------------------------------- #
@router.post("/websites/{website_id}/social/draft")
async def social_draft(payload: DraftIn, website: OwnedWebsite):
    return await draft_social_posts(_website_ctx(website), payload.topic, payload.platforms[:5], payload.tone)


@router.post("/websites/{website_id}/social/calendar", status_code=201)
async def generate_content_calendar(payload: CalendarIn, website: OwnedWebsite, db: DB):
    platforms = [p for p in payload.platforms if p in PLATFORMS] or ["instagram"]
    # Context: audit insights, tracked keywords, real Google queries
    audit = (await db.execute(select(Audit).where(Audit.website_id == website.id, Audit.status == "completed").order_by(Audit.id.desc()))).scalars().first()
    insights = (audit.ai_insights or {}) if audit else {}
    keywords = (await db.execute(select(Keyword).where(Keyword.website_id == website.id))).scalars().all()
    themes = list(dict.fromkeys([k.term for k in keywords] + list(insights.get("keyword_themes") or [])))
    queries = [q.key for q in (await db.execute(select(SearchQueryStat).where(SearchQueryStat.website_id == website.id, SearchQueryStat.kind == "query")
                                                 .order_by(SearchQueryStat.impressions.desc()).limit(12))).scalars().all()]
    plan = await generate_calendar(_website_ctx(website), platforms, payload.weeks, payload.posts_per_week, payload.tone, themes, queries,
                                   list(insights.get("content_ideas") or []), payload.goals)
    connected = await connected_platforms(db, website.id) if payload.auto_schedule else {}
    times = schedule_times(plan["posts"], datetime.now(timezone.utc), payload.timezone)
    campaign = f"plan-{datetime.now(timezone.utc):%Y%m%d-%H%M}"
    created: List[SocialPost] = []
    creatives: Dict[int, Creative] = {}
    for p, when in zip(plan["posts"], times):
        creative = None
        brief = p.get("creative") or {}
        if payload.generate_creatives and brief.get("headline"):
            try:
                creative = render_template_creative(website, {"headline": brief.get("headline", ""), "subline": brief.get("subline", ""), "cta": brief.get("cta", ""),
                                                              "template": brief.get("template", "bold"), "size": "landscape" if p["platform"] in ("linkedin", "x", "facebook") else "square"})
                db.add(creative)
                await db.flush()
            except Exception as exc:  # pragma: no cover
                log.warning("creative render failed: %s", exc)
                creative = None
        scheduled = payload.auto_schedule and p["platform"] in connected
        post = SocialPost(website_id=website.id, platform=p["platform"], topic=str(p.get("topic", ""))[:255], content=str(p.get("content", "")).strip(),
                          hashtags=list(p.get("hashtags") or [])[:10], link_url=website.url if "http" not in str(p.get("content", "")) else "",
                          creative_id=creative.id if creative else None, status="scheduled" if scheduled else "draft", scheduled_for=when,
                          generated_by_ai=plan["provider"] != "rule-based", campaign=campaign)
        db.add(post)
        created.append(post)
        if creative:
            creatives[id(post)] = creative
    await db.commit()
    for p in created:
        await db.refresh(p)
    return {"provider": plan["provider"], "strategy": plan.get("strategy", ""), "campaign": campaign, "created": len(created),
            "posts": [post_to_dict(p, creatives.get(id(p))) for p in created]}


@router.post("/websites/{website_id}/social/posts/bulk")
async def bulk_update(website: OwnedWebsite, db: DB, ids: List[int], action: str):
    """action: schedule (keeps each post's scheduled_for) | draft | delete"""
    rows = (await db.execute(select(SocialPost).where(SocialPost.website_id == website.id, SocialPost.id.in_(ids)))).scalars().all()
    n = 0
    for post in rows:
        if action == "delete":
            await db.delete(post)
            n += 1
        elif action == "schedule" and post.status in ("draft", "failed") and post.scheduled_for:
            post.status = "scheduled"
            post.error = ""
            n += 1
        elif action == "draft" and post.status in ("scheduled", "failed"):
            post.status = "draft"
            n += 1
    await db.commit()
    return {"updated": n}
