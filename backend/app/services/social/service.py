"""Publishing pipeline used by the API (publish now) and the scheduler (due scheduled posts)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from app.models import Creative, Integration, SocialPost, Website
from app.models.entities import aware
from app.services.creatives.studio import public_media_url
from app.services.social.publishers import PLATFORMS, PublishError, publish

log = logging.getLogger(__name__)


def post_to_dict(p: SocialPost, creative: Optional[Creative] = None) -> Dict[str, Any]:
    c = creative or p.creative
    return {
        "id": p.id, "website_id": p.website_id, "platform": p.platform, "topic": p.topic, "content": p.content, "hashtags": p.hashtags or [],
        "link_url": p.link_url, "media_urls": p.media_urls or [], "creative_id": p.creative_id,
        "creative_url": f"/media/{c.path}" if c else (p.media_urls[0] if p.media_urls else ""),
        "status": p.status, "scheduled_for": aware(p.scheduled_for), "published_at": aware(p.published_at), "external_id": p.external_id,
        "external_url": p.external_url, "error": p.error, "generated_by_ai": p.generated_by_ai, "campaign": p.campaign,
        "created_at": aware(p.created_at), "updated_at": aware(p.updated_at),
    }


async def connected_platforms(db, website_id: int) -> Dict[str, Integration]:
    rows = (await db.execute(select(Integration).where(Integration.website_id == website_id, Integration.provider.in_(list(PLATFORMS))))).scalars().all()
    return {r.provider: r for r in rows if r.status in ("connected", "error", "pending")}


def image_url_for(post: SocialPost, creative: Optional[Creative]) -> Optional[str]:
    if creative:
        return public_media_url(creative.path)
    if post.media_urls:
        return str(post.media_urls[0])
    return None


async def publish_post(db, website: Website, post: SocialPost) -> SocialPost:
    """Publish immediately; records result/error on the row (caller commits)."""
    integration = (await db.execute(select(Integration).where(Integration.website_id == website.id, Integration.provider == post.platform))).scalar_one_or_none()
    creative = await db.get(Creative, post.creative_id) if post.creative_id else None
    post.status = "publishing"
    post.error = ""
    try:
        if integration is None or not integration.config:
            raise PublishError(f"{PLATFORMS.get(post.platform, {}).get('label', post.platform)} is not connected – add credentials in the Publish tab.")
        result = await publish(post.platform, integration.config, post.content, post.hashtags or [], image_url_for(post, creative), post.link_url,
                               extra={"website": website.url, "post_id": post.id, "topic": post.topic, "platform": post.platform})
        post.status = "published"
        post.published_at = datetime.now(timezone.utc)
        post.external_id = result.get("external_id", "")
        post.external_url = result.get("external_url", "")
        integration.status = "connected"
        integration.last_error = ""
        integration.last_synced_at = datetime.now(timezone.utc)
        summary = dict(integration.summary or {})
        summary["published"] = int(summary.get("published", 0)) + 1
        summary["last_post_at"] = post.published_at.isoformat()
        integration.summary = summary
    except PublishError as exc:
        post.status = "failed"
        post.error = str(exc)[:1000]
        if integration is not None:
            integration.status = "error"
            integration.last_error = str(exc)[:500]
    except Exception as exc:  # pragma: no cover - unexpected
        log.exception("publish failed")
        post.status = "failed"
        post.error = f"{type(exc).__name__}: {exc}"[:1000]
    await db.flush()
    return post


async def process_due_posts(session_factory, limit: int = 10) -> int:
    """Scheduler hook: publish posts whose `scheduled_for` has passed."""
    now = datetime.now(timezone.utc)
    async with session_factory() as db:
        rows = (await db.execute(select(SocialPost).where(SocialPost.status == "scheduled").order_by(SocialPost.scheduled_for))).scalars().all()
        due_ids: List[int] = [r.id for r in rows if r.scheduled_for is not None and aware(r.scheduled_for) <= now][:limit]
    published = 0
    for post_id in due_ids:
        async with session_factory() as db:
            post = await db.get(SocialPost, post_id)
            website = await db.get(Website, post.website_id) if post else None
            if post is None or website is None or post.status != "scheduled":
                continue
            await publish_post(db, website, post)
            published += 1 if post.status == "published" else 0
    return published
