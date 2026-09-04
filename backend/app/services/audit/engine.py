"""Audit orchestration: crawl -> analyse -> AI insights -> persist -> sync tasks."""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.database import session_scope
from app.models import Audit, AuditIssue, AuditPage, Task, Website
from app.services.ai.insights import generate_audit_insights
from app.services.audit.analyzers import analyze
from app.services.audit.crawler import crawl_site

log = logging.getLogger(__name__)

# Only these severities become tasks automatically.
TASK_SEVERITIES = {"critical", "high", "medium"}
SEVERITY_TO_PRIORITY = {"critical": "critical", "high": "high", "medium": "medium", "low": "low", "info": "low"}


async def run_audit(audit_id: int) -> None:
    """Execute an audit end-to-end. Safe to call from a background task or scheduler."""
    async with session_scope() as db:
        audit = await db.get(Audit, audit_id)
        if audit is None:
            log.warning("audit %s vanished", audit_id)
            return
        website = await db.get(Website, audit.website_id)
        if website is None:
            return
        audit.status = "running"
        audit.started_at = datetime.now(UTC)
        await db.commit()
        site_url = website.url
        website_ctx = {
            "url": website.url, "domain": website.domain, "name": website.name,
            "industry": website.industry, "target_location": website.target_location, "description": website.description,
        }

    try:
        site = await crawl_site(site_url)
        result = analyze(site)
        issue_dicts = [i.__dict__ for i in result.issues]
        homepage_text = site.pages[0].text_sample if site.pages else ""
        try:
            insights = await asyncio.wait_for(
                generate_audit_insights(website_ctx, result.facts, result.scores, issue_dicts, homepage_text), timeout=120
            )
        except Exception as exc:  # pragma: no cover
            log.warning("insights failed: %s", exc)
            insights = {}
    except Exception as exc:
        log.exception("audit %s failed", audit_id)
        async with session_scope() as db:
            audit = await db.get(Audit, audit_id)
            if audit:
                audit.status = "failed"
                audit.error = f"{type(exc).__name__}: {exc}"[:1000]
                audit.finished_at = datetime.now(UTC)
        return

    async with session_scope() as db:
        audit = await db.get(Audit, audit_id)
        if audit is None:  # deleted while crawling
            log.warning("audit %s vanished before completion", audit_id)
            return
        website = await db.get(Website, audit.website_id)
        if website is None:
            log.warning("website for audit %s vanished before completion", audit_id)
            return
        audit.status = "completed"
        audit.finished_at = datetime.now(UTC)
        audit.pages_crawled = len(site.pages)
        audit.overall_score = result.overall
        audit.seo_score = result.scores.get("seo")
        audit.technical_score = result.scores.get("technical")
        audit.content_score = result.scores.get("content")
        audit.aeo_score = result.scores.get("aeo")
        audit.ai_readiness_score = result.scores.get("ai")
        audit.performance_score = result.scores.get("performance")
        audit.social_score = result.scores.get("social")
        audit.summary = result.facts
        audit.ai_insights = insights

        for p in site.pages:
            db.add(AuditPage(
                audit_id=audit.id, url=p.url, status_code=p.status_code, response_ms=p.response_ms,
                title=p.title, meta_description=p.meta_description, h1=" | ".join(p.h1), word_count=p.word_count,
                canonical=p.canonical, data=p.to_dict(),
            ))
        for i in result.issues:
            db.add(AuditIssue(
                audit_id=audit.id, code=i.code, category=i.category, severity=i.severity, title=i.title,
                description=i.description, recommendation=i.recommendation, page_url=i.page_url, impact=i.impact,
            ))

        website.last_score = result.overall
        website.last_audit_at = audit.finished_at
        await db.flush()
        await _sync_tasks(db, website.id, result.issues)
    log.info("audit %s completed: score=%s pages=%s issues=%s", audit_id, result.overall, len(site.pages), len(result.issues))


async def _sync_tasks(db, website_id: int, issues) -> None:
    """Create tasks for new important issues; auto-complete tasks whose issue disappeared."""
    existing = (await db.execute(
        select(Task).where(Task.website_id == website_id, Task.source == "audit")
    )).scalars().all()
    by_key = {(t.source_issue_code, t.page_url): t for t in existing}
    current_keys = set()
    for issue in issues:
        if issue.severity not in TASK_SEVERITIES:
            continue
        key = (issue.code, issue.page_url)
        current_keys.add(key)
        if key in by_key:
            t = by_key[key]
            if t.status == "done":  # issue came back
                t.status = "todo"
                t.completed_at = None
            continue
        # cap page-specific duplicates of the same code to keep the board readable
        same_code = sum(1 for k in current_keys if k[0] == issue.code)
        if same_code > 5:
            continue
        db.add(Task(
            website_id=website_id, title=issue.title, description=(issue.recommendation or issue.description),
            category=issue.category, priority=SEVERITY_TO_PRIORITY.get(issue.severity, "medium"), status="todo",
            source="audit", source_issue_code=issue.code, page_url=issue.page_url,
        ))
    for key, t in by_key.items():
        if key not in current_keys and t.status in ("todo", "in_progress"):
            t.status = "done"
            t.completed_at = datetime.now(UTC)
            t.description = (t.description + "\n\n[Auto-resolved: issue no longer detected in latest audit]").strip()


async def create_and_run_audit(website_id: int, trigger: str = "manual") -> int | None:
    async with session_scope() as db:
        audit = Audit(website_id=website_id, status="queued", trigger=trigger)
        db.add(audit)
        await db.flush()
        audit_id = audit.id
    await run_audit(audit_id)
    return audit_id
