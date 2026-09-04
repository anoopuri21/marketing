"""Social publishing API: channel connections, posts (draft → scheduled → published), AI calendar.

Thin HTTP layer – validation/state rules live in `app.services.social.service`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import DB, OwnedWebsite
from app.models import Creative
from app.services.ai.insights import draft_social_posts
from app.services.social import service as social
from app.services.social.publishers import PLATFORMS, compose_text, verify_channel

router = APIRouter(prefix="/api", tags=["social"])


# --------------------------------------------------------------------------- #
# schemas
# --------------------------------------------------------------------------- #
class ChannelUpsert(BaseModel):
    platform: str
    config: dict[str, Any] = Field(default_factory=dict)


class PostIn(BaseModel):
    platform: str
    content: str = ""
    topic: str = ""
    hashtags: list[str] = Field(default_factory=list)
    link_url: str = ""
    creative_id: int | None = None
    media_urls: list[str] = Field(default_factory=list)
    scheduled_for: datetime | None = None  # if set → status scheduled
    status: str | None = None  # draft|scheduled (explicit override)


class PostUpdate(BaseModel):
    platform: str | None = None
    content: str | None = None
    topic: str | None = None
    hashtags: list[str] | None = None
    link_url: str | None = None
    creative_id: int | None = None
    media_urls: list[str] | None = None
    scheduled_for: datetime | None = None
    status: str | None = None


class CalendarIn(BaseModel):
    platforms: list[str] = Field(default_factory=lambda: ["instagram", "facebook", "linkedin"])
    weeks: int = Field(default=2, ge=1, le=8)
    posts_per_week: int = Field(default=3, ge=1, le=7)
    tone: str = "friendly"
    goals: str = ""
    timezone: str = "UTC"
    generate_creatives: bool = True
    auto_schedule: bool = False  # True → posts are created as scheduled (only for connected channels)


class DraftIn(BaseModel):
    topic: str
    platforms: list[str] = Field(default_factory=lambda: ["instagram", "linkedin", "facebook"])
    tone: str = "friendly"


async def _post_with_creative(db: DB, post) -> dict[str, Any]:
    creative = await db.get(Creative, post.creative_id) if post.creative_id else None
    return social.post_to_dict(post, creative)


# --------------------------------------------------------------------------- #
# channels
# --------------------------------------------------------------------------- #
@router.get("/social/platforms")
async def platforms_catalog():
    return PLATFORMS


@router.get("/websites/{website_id}/social/channels")
async def list_channels(website: OwnedWebsite, db: DB):
    return [social.channel_to_dict(r) for r in await social.list_channels(db, website.id)]


@router.put("/websites/{website_id}/social/channels")
async def upsert_channel(payload: ChannelUpsert, website: OwnedWebsite, db: DB):
    row = await social.upsert_channel(db, website.id, payload.platform, payload.config)
    await db.commit()
    await db.refresh(row)
    return social.channel_to_dict(row)


@router.delete("/websites/{website_id}/social/channels/{platform}", status_code=204)
async def delete_channel(platform: str, website: OwnedWebsite, db: DB):
    row = await social.get_channel(db, website.id, platform)
    if row:
        await db.delete(row)
        await db.commit()


@router.post("/websites/{website_id}/social/channels/{platform}/test")
async def test_channel(platform: str, website: OwnedWebsite, db: DB):
    """Send a test publish for webhook channels; for API channels validate the token with a read call."""
    row = await social.get_channel(db, website.id, platform)
    if row is None:
        raise HTTPException(status_code=404, detail="Channel not connected")
    ok, detail = await verify_channel(platform, row.config or {}, site_url=website.url, site_domain=website.domain)
    row.status = "connected" if ok else "error"
    row.last_error = "" if ok else detail[:500]
    await db.commit()
    return {"ok": ok, "detail": detail}


# --------------------------------------------------------------------------- #
# posts
# --------------------------------------------------------------------------- #
@router.get("/websites/{website_id}/social/posts")
async def list_posts(website: OwnedWebsite, db: DB, status: str | None = None, limit: int = 200):
    statuses = [s for s in status.split(",") if s] if status else None
    return await social.list_posts(db, website.id, statuses, limit)


@router.get("/websites/{website_id}/social/summary")
async def social_summary(website: OwnedWebsite, db: DB):
    return await social.summary(db, website.id)


@router.post("/websites/{website_id}/social/posts", status_code=201)
async def create_post(payload: PostIn, website: OwnedWebsite, db: DB):
    post, creative = await social.create_post(db, website.id, payload.model_dump())
    await db.commit()
    await db.refresh(post)
    return social.post_to_dict(post, creative)


@router.patch("/websites/{website_id}/social/posts/{post_id}")
async def update_post(post_id: int, payload: PostUpdate, website: OwnedWebsite, db: DB):
    post = await social.update_post(db, website.id, post_id, payload.model_dump(exclude_unset=True))
    await db.commit()
    await db.refresh(post)
    return await _post_with_creative(db, post)


@router.delete("/websites/{website_id}/social/posts/{post_id}", status_code=204)
async def delete_post(post_id: int, website: OwnedWebsite, db: DB):
    post = await social.get_post(db, website.id, post_id)
    await db.delete(post)
    await db.commit()


@router.post("/websites/{website_id}/social/posts/{post_id}/publish")
async def publish_now(post_id: int, website: OwnedWebsite, db: DB):
    post = await social.get_post(db, website.id, post_id)
    if post.status == "published":
        raise HTTPException(status_code=409, detail="Already published")
    await social.publish_post(db, website, post)
    await db.commit()
    await db.refresh(post)
    return await _post_with_creative(db, post)


@router.get("/websites/{website_id}/social/posts/{post_id}/preview")
async def preview_text(post_id: int, website: OwnedWebsite, db: DB):
    post = await social.get_post(db, website.id, post_id)
    return {"text": compose_text(post.content, post.hashtags or [], post.link_url, post.platform), "max_chars": PLATFORMS.get(post.platform, {}).get("max_chars")}


# --------------------------------------------------------------------------- #
# AI: quick drafts + full calendar
# --------------------------------------------------------------------------- #
@router.post("/websites/{website_id}/social/draft")
async def social_draft(payload: DraftIn, website: OwnedWebsite):
    return await draft_social_posts(social.website_ctx(website), payload.topic, payload.platforms[:5], payload.tone)


@router.post("/websites/{website_id}/social/calendar", status_code=201)
async def generate_content_calendar(payload: CalendarIn, website: OwnedWebsite, db: DB):
    result = await social.build_calendar(
        db, website, platforms=payload.platforms, weeks=payload.weeks, posts_per_week=payload.posts_per_week, tone=payload.tone,
        goals=payload.goals, timezone=payload.timezone, generate_creatives=payload.generate_creatives, auto_schedule=payload.auto_schedule,
    )
    await db.commit()
    return result


@router.post("/websites/{website_id}/social/posts/bulk")
async def bulk_update(website: OwnedWebsite, db: DB, ids: list[int], action: str):
    """action: schedule (keeps each post's scheduled_for) | draft | delete"""
    n = await social.bulk_update(db, website.id, ids, action)
    await db.commit()
    return {"updated": n}
