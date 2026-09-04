"""Social domain service: channels, posts (draft → scheduled → published), calendar generation.

Used by the API layer (`app.api.social`) and the scheduler (due scheduled posts). Raises
`app.core.errors` exceptions instead of HTTP errors so it stays framework-agnostic.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.time import aware
from app.models import Audit, Creative, Integration, Keyword, SearchQueryStat, SocialPost, Website
from app.services.creatives.studio import public_media_url, render_template_creative
from app.services.social.planner import generate_calendar, schedule_times
from app.services.social.publishers import PLATFORMS, PublishError, publish

log = logging.getLogger(__name__)

EDITABLE_STATUSES = ("draft", "scheduled", "failed")
SECRET_HINTS = ("token", "secret", "password", "key")


def website_ctx(website: Website) -> dict[str, Any]:
    return {"url": website.url, "name": website.name, "industry": website.industry, "target_location": website.target_location,
            "description": website.description}


# --------------------------------------------------------------------------- #
# channels
# --------------------------------------------------------------------------- #
def mask_config(config: dict[str, Any] | None) -> dict[str, Any]:
    return {k: ("••••••" if v and any(h in k for h in SECRET_HINTS) else v) for k, v in (config or {}).items()}


def channel_to_dict(row: Integration) -> dict[str, Any]:
    meta = PLATFORMS.get(row.provider, {})
    return {"platform": row.provider, "label": meta.get("label", row.provider), "status": row.status, "config": mask_config(row.config),
            "connected_at": aware(row.connected_at), "last_error": row.last_error or "", "summary": row.summary or {},
            "last_used_at": aware(row.last_synced_at)}


async def list_channels(db: AsyncSession, website_id: int) -> list[Integration]:
    stmt = select(Integration).where(Integration.website_id == website_id, Integration.provider.in_(list(PLATFORMS)))
    return list((await db.execute(stmt)).scalars().all())


async def get_channel(db: AsyncSession, website_id: int, platform: str) -> Integration | None:
    stmt = select(Integration).where(Integration.website_id == website_id, Integration.provider == platform)
    return (await db.execute(stmt)).scalar_one_or_none()


async def upsert_channel(db: AsyncSession, website_id: int, platform: str, config: dict[str, Any]) -> Integration:
    """Create/update channel credentials. Masked values ("••••") coming back from the UI are ignored."""
    meta = PLATFORMS.get(platform)
    if meta is None:
        raise ValidationError(f"Unknown platform. Supported: {', '.join(PLATFORMS)}")
    if meta["status"] != "live":
        raise ValidationError(f"{meta['label']} publishing is not available yet")
    row = await get_channel(db, website_id, platform)
    if row is None:
        row = Integration(website_id=website_id, provider=platform)
        db.add(row)
    incoming = {k: str(v).strip() for k, v in config.items() if not (isinstance(v, str) and v.startswith("••••"))}
    row.config = {**(row.config or {}), **incoming}
    missing = [f for f in meta["fields"] if not row.config.get(f)]
    if missing:
        raise ValidationError(f"Missing: {', '.join(missing)}")
    row.status = "connected"
    row.connected_at = row.connected_at or datetime.now(UTC)
    row.last_error = ""
    await db.flush()
    return row


# --------------------------------------------------------------------------- #
# posts
# --------------------------------------------------------------------------- #
async def get_post(db: AsyncSession, website_id: int, post_id: int) -> SocialPost:
    post = await db.get(SocialPost, post_id)
    if post is None or post.website_id != website_id:
        raise NotFoundError("Post not found")
    return post


async def get_owned_creative(db: AsyncSession, website_id: int, creative_id: int | None) -> Creative | None:
    if creative_id is None:
        return None
    creative = await db.get(Creative, creative_id)
    if creative is None or creative.website_id != website_id:
        raise ValidationError("Creative not found")
    return creative


async def list_posts(db: AsyncSession, website_id: int, statuses: list[str] | None = None, limit: int = 200) -> list[dict[str, Any]]:
    stmt = select(SocialPost).where(SocialPost.website_id == website_id)
    if statuses:
        stmt = stmt.where(SocialPost.status.in_(statuses))
    stmt = stmt.order_by(SocialPost.scheduled_for.is_(None), SocialPost.scheduled_for, SocialPost.id.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    creative_ids = [r.creative_id for r in rows if r.creative_id]
    creatives: dict[int, Creative] = {}
    if creative_ids:
        creatives = {c.id: c for c in (await db.execute(select(Creative).where(Creative.id.in_(creative_ids)))).scalars().all()}
    return [post_to_dict(r, creatives.get(r.creative_id) if r.creative_id else None) for r in rows]


async def summary(db: AsyncSession, website_id: int) -> dict[str, Any]:
    counts: dict[str, int] = {
        status: n for status, n in (await db.execute(select(SocialPost.status, func.count()).where(SocialPost.website_id == website_id).group_by(SocialPost.status))).all()
    }
    channels = await connected_platforms(db, website_id)
    next_post = (await db.execute(select(SocialPost).where(SocialPost.website_id == website_id, SocialPost.status == "scheduled")
                                  .order_by(SocialPost.scheduled_for))).scalars().first()
    return {"counts": counts, "connected": sorted(channels), "next_scheduled_for": aware(next_post.scheduled_for) if next_post else None,
            "total": sum(counts.values())}


def _validate_target_status(status: str, scheduled_for: datetime | None) -> None:
    if status not in ("draft", "scheduled"):
        raise ValidationError("status must be draft or scheduled")
    if status == "scheduled" and scheduled_for is None:
        raise ValidationError("scheduled_for is required to schedule")


async def create_post(db: AsyncSession, website_id: int, data: dict[str, Any]) -> tuple[SocialPost, Creative | None]:
    """`data` is the validated PostIn payload as a dict."""
    if data["platform"] not in PLATFORMS:
        raise ValidationError("Unknown platform")
    content = (data.get("content") or "").strip()
    if not content:
        raise ValidationError("content is required")
    creative = await get_owned_creative(db, website_id, data.get("creative_id"))
    status = data.get("status") or ("scheduled" if data.get("scheduled_for") else "draft")
    _validate_target_status(status, data.get("scheduled_for"))
    post = SocialPost(
        website_id=website_id, platform=data["platform"], content=content, topic=(data.get("topic") or "").strip()[:255],
        hashtags=[h.strip() for h in (data.get("hashtags") or []) if h.strip()][:30], link_url=(data.get("link_url") or "").strip(),
        creative_id=data.get("creative_id"), media_urls=data.get("media_urls") or [], status=status, scheduled_for=data.get("scheduled_for"),
    )
    db.add(post)
    await db.flush()
    return post, creative


async def update_post(db: AsyncSession, website_id: int, post_id: int, changes: dict[str, Any]) -> SocialPost:
    """`changes` = PostUpdate.model_dump(exclude_unset=True). Enforces the status state machine."""
    post = await get_post(db, website_id, post_id)
    if post.status not in EDITABLE_STATUSES:
        raise ConflictError("Published posts cannot be edited")
    if "creative_id" in changes:
        await get_owned_creative(db, website_id, changes["creative_id"])
    if "platform" in changes and changes["platform"] not in PLATFORMS:
        raise ValidationError("Unknown platform")
    new_status = changes.pop("status", None)
    for key, value in changes.items():
        setattr(post, key, value.strip() if isinstance(value, str) else value)
    if new_status:
        if new_status == "scheduled" and post.scheduled_for is None:
            raise ValidationError("Set scheduled_for before scheduling")
        _validate_target_status(new_status, post.scheduled_for)
        post.status = new_status
        post.error = ""
    elif post.status == "failed":  # editing a failed post re-arms it
        post.status = "scheduled" if post.scheduled_for and aware(post.scheduled_for) > datetime.now(UTC) else "draft"
        post.error = ""
    await db.flush()
    return post


async def bulk_update(db: AsyncSession, website_id: int, ids: list[int], action: str) -> int:
    """action: schedule (keeps each post's scheduled_for) | draft | delete. Returns affected count."""
    if action not in ("schedule", "draft", "delete"):
        raise ValidationError("action must be schedule, draft or delete")
    rows = (await db.execute(select(SocialPost).where(SocialPost.website_id == website_id, SocialPost.id.in_(ids)))).scalars().all()
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
    await db.flush()
    return n


# --------------------------------------------------------------------------- #
# calendar
# --------------------------------------------------------------------------- #
async def build_calendar(db: AsyncSession, website: Website, *, platforms: list[str], weeks: int, posts_per_week: int, tone: str,
                         goals: str, timezone: str, generate_creatives: bool, auto_schedule: bool) -> dict[str, Any]:
    """Generate a multi-week content plan (AI or rule-based) and persist it as posts in one campaign."""
    platforms = [p for p in platforms if p in PLATFORMS] or ["instagram"]
    audit = (await db.execute(select(Audit).where(Audit.website_id == website.id, Audit.status == "completed").order_by(Audit.id.desc()))).scalars().first()
    insights = (audit.ai_insights or {}) if audit else {}
    keywords = (await db.execute(select(Keyword).where(Keyword.website_id == website.id))).scalars().all()
    themes = list(dict.fromkeys([k.term for k in keywords] + list(insights.get("keyword_themes") or [])))
    queries = [q.key for q in (await db.execute(select(SearchQueryStat).where(SearchQueryStat.website_id == website.id, SearchQueryStat.kind == "query")
                                                 .order_by(SearchQueryStat.impressions.desc()).limit(12))).scalars().all()]
    plan = await generate_calendar(website_ctx(website), platforms, weeks, posts_per_week, tone, themes, queries,
                                   list(insights.get("content_ideas") or []), goals)
    connected = await connected_platforms(db, website.id) if auto_schedule else {}
    now = datetime.now(UTC)
    times = schedule_times(plan["posts"], now, timezone)
    campaign = f"plan-{now:%Y%m%d-%H%M}"
    created: list[SocialPost] = []
    creatives: dict[int, Creative] = {}
    for item, when in zip(plan["posts"], times, strict=True):
        creative = None
        brief = item.get("creative") or {}
        if generate_creatives and brief.get("headline"):
            try:
                creative = render_template_creative(website, {
                    "headline": brief.get("headline", ""), "subline": brief.get("subline", ""), "cta": brief.get("cta", ""),
                    "template": brief.get("template", "bold"), "size": "landscape" if item["platform"] in ("linkedin", "x", "facebook") else "square",
                })
                db.add(creative)
                await db.flush()
            except Exception:  # pragma: no cover – a broken creative must not sink the whole plan
                log.exception("creative render failed for calendar item %r", brief.get("headline"))
                creative = None
        content = str(item.get("content", "")).strip()
        scheduled = auto_schedule and item["platform"] in connected
        post = SocialPost(website_id=website.id, platform=item["platform"], topic=str(item.get("topic", ""))[:255], content=content,
                          hashtags=list(item.get("hashtags") or [])[:10], link_url=website.url if "http" not in content else "",
                          creative_id=creative.id if creative else None, status="scheduled" if scheduled else "draft", scheduled_for=when,
                          generated_by_ai=plan["provider"] != "rule-based", campaign=campaign)
        db.add(post)
        created.append(post)
        if creative:
            creatives[id(post)] = creative
    await db.flush()
    for post in created:
        await db.refresh(post)
    return {"provider": plan["provider"], "strategy": plan.get("strategy", ""), "campaign": campaign, "created": len(created),
            "posts": [post_to_dict(p, creatives.get(id(p))) for p in created]}


# --------------------------------------------------------------------------- #
# publishing
# --------------------------------------------------------------------------- #


def post_to_dict(p: SocialPost, creative: Creative | None = None) -> dict[str, Any]:
    c = creative or p.creative
    return {
        "id": p.id, "website_id": p.website_id, "platform": p.platform, "topic": p.topic, "content": p.content, "hashtags": p.hashtags or [],
        "link_url": p.link_url, "media_urls": p.media_urls or [], "creative_id": p.creative_id,
        "creative_url": f"/media/{c.path}" if c else (p.media_urls[0] if p.media_urls else ""),
        "status": p.status, "scheduled_for": aware(p.scheduled_for), "published_at": aware(p.published_at), "external_id": p.external_id,
        "external_url": p.external_url, "error": p.error, "generated_by_ai": p.generated_by_ai, "campaign": p.campaign,
        "created_at": aware(p.created_at), "updated_at": aware(p.updated_at),
    }


async def connected_platforms(db, website_id: int) -> dict[str, Integration]:
    rows = (await db.execute(select(Integration).where(Integration.website_id == website_id, Integration.provider.in_(list(PLATFORMS))))).scalars().all()
    return {r.provider: r for r in rows if r.status in ("connected", "error", "pending")}


def image_url_for(post: SocialPost, creative: Creative | None) -> str | None:
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
        post.published_at = datetime.now(UTC)
        post.external_id = result.get("external_id", "")
        post.external_url = result.get("external_url", "")
        integration.status = "connected"
        integration.last_error = ""
        integration.last_synced_at = datetime.now(UTC)
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
    now = datetime.now(UTC)
    async with session_factory() as db:
        rows = (await db.execute(select(SocialPost).where(SocialPost.status == "scheduled").order_by(SocialPost.scheduled_for))).scalars().all()
        due_ids: list[int] = [r.id for r in rows if r.scheduled_for is not None and aware(r.scheduled_for) <= now][:limit]
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
