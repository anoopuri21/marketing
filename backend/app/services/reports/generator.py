"""Builds and delivers the periodic (weekly/monthly) performance report for a website."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models import Audit, AuditIssue, Integration, ReportRun, SearchQueryStat, Task, Website
from app.models.entities import aware
from app.services.rank_tracker import enrich_keyword, load_keywords
from app.services.reports.mailer import send_email

log = logging.getLogger(__name__)

TEMPLATES = Path(__file__).resolve().parent.parent.parent / "templates"
_env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))


def score_color(v) -> str:
    if v is None:
        return "#9ca3af"
    if v >= 80:
        return "#059669"
    if v >= 60:
        return "#d97706"
    return "#dc2626"


def pct_change(cur, prev) -> Optional[float]:
    try:
        cur, prev = float(cur or 0), float(prev or 0)
    except (TypeError, ValueError):
        return None
    if prev <= 0:
        return None
    return round((cur - prev) / prev * 100, 1)


def severity_color(sev: str) -> str:
    return {"critical": "#b91c1c", "high": "#ea580c", "medium": "#d97706", "low": "#2563eb", "info": "#6b7280"}.get(sev, "#6b7280")


async def build_report_html(db, website: Website, period: str = "weekly") -> tuple[str, str, dict]:
    """Returns (subject, html, context)."""
    now = datetime.now(timezone.utc)
    days = 7 if period == "weekly" else 30
    since = now - timedelta(days=days)

    audits = (await db.execute(
        select(Audit).where(Audit.website_id == website.id, Audit.status == "completed")
        .order_by(Audit.finished_at.desc()).limit(2)
    )).scalars().all()
    latest: Optional[Audit] = audits[0] if audits else None
    previous: Optional[Audit] = audits[1] if len(audits) > 1 else None

    issues: List[AuditIssue] = []
    if latest:
        issues = (await db.execute(select(AuditIssue).where(AuditIssue.audit_id == latest.id))).scalars().all()
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    seen = set()
    top_issues = []
    for i in sorted(issues, key=lambda i: (order.get(i.severity, 5), -i.impact)):
        if i.code in seen:
            continue
        seen.add(i.code)
        top_issues.append(i)
        if len(top_issues) >= 7:
            break

    keywords = await load_keywords(db, website.id)
    kw_rows = []
    for k in keywords[:15]:
        e = enrich_keyword(k)
        change = None
        if e["latest_position"] and e["previous_position"]:
            change = e["previous_position"] - e["latest_position"]
        kw_rows.append({"term": k.term, "location": k.location, "latest_position": e["latest_position"],
                        "last_checked_at": e["last_checked_at"], "change": change})

    tasks = (await db.execute(select(Task).where(Task.website_id == website.id))).scalars().all()
    tasks_done = [t for t in tasks if t.status == "done" and t.completed_at and aware(t.completed_at) >= since]
    tasks_open = sorted([t for t in tasks if t.status in ("todo", "in_progress")],
                        key=lambda t: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(t.priority, 4))

    insights = (latest.ai_insights if latest else {}) or {}
    overall = latest.overall_score if latest else None
    delta = None
    if latest and previous and latest.overall_score is not None and previous.overall_score is not None:
        delta = round(latest.overall_score - previous.overall_score, 1)

    categories = [
        ("On-page SEO", latest.seo_score if latest else None),
        ("Technical", latest.technical_score if latest else None),
        ("Content", latest.content_score if latest else None),
        ("Answer engines (AEO)", latest.aeo_score if latest else None),
        ("AI search readiness", latest.ai_readiness_score if latest else None),
        ("Performance", latest.performance_score if latest else None),
        ("Social", latest.social_score if latest else None),
    ]
    sev_counts = {}
    for i in issues:
        sev_counts[i.severity] = sev_counts.get(i.severity, 0) + 1
    stats = [
        ("Pages crawled", latest.pages_crawled if latest else 0),
        ("Critical", sev_counts.get("critical", 0)),
        ("High", sev_counts.get("high", 0)),
        ("Keywords tracked", len(keywords)),
        ("Tasks done", len(tasks_done)),
    ]
    # Live data from Google integrations (if connected)
    integrations = {i.provider: i for i in (await db.execute(select(Integration).where(Integration.website_id == website.id))).scalars().all()}
    gsc = integrations.get("google_search_console")
    ga4 = integrations.get("ga4")
    gsc_summary = (gsc.summary or {}) if gsc and gsc.status == "connected" else {}
    ga4_summary = (ga4.summary or {}) if ga4 and ga4.status == "connected" else {}
    top_queries: list = []
    opportunities: list = []
    if gsc_summary:
        query_stats = (await db.execute(select(SearchQueryStat).where(SearchQueryStat.website_id == website.id, SearchQueryStat.kind == "query"))).scalars().all()
        top_queries = sorted(query_stats, key=lambda q: (-q.clicks, -q.impressions))[:8]
        opportunities = sorted([q for q in query_stats if 4.5 <= q.position <= 20 and q.impressions >= 20], key=lambda q: -q.impressions)[:5]

    period_label = "Weekly" if period == "weekly" else "Monthly"
    subject = f"[{settings.app_name}] {period_label} report for {website.name or website.domain} – score {overall if overall is not None else 'n/a'}/100"
    rank_note = ""
    if keywords and settings.resolved_serp_provider == "none":
        rank_note = "Live Google positions require a SERP provider (set SERPAPI_KEY). Keywords are tracked and will populate automatically once configured."

    template = _env.get_template("report_email.html")
    html = template.render(
        app_name=settings.app_name, subject=subject, period_label=period_label, frequency=period,
        website=website, generated_at=now.strftime("%d %b %Y, %H:%M UTC"), overall=overall, delta=delta,
        categories=categories, executive_summary=insights.get("executive_summary", ""), stats=stats,
        top_issues=top_issues, keywords=kw_rows, rank_note=rank_note, tasks_done=tasks_done, tasks_open=tasks_open,
        quick_wins=(insights.get("quick_wins") or [])[:5], dashboard_url=f"{settings.frontend_url}/websites/{website.id}",
        gsc=gsc_summary, ga4=ga4_summary, top_queries=top_queries, opportunities=opportunities, pct=pct_change,
        pages_crawled=latest.pages_crawled if latest else settings.crawl_max_pages,
        score_color=score_color, severity_color=severity_color,
    )
    ctx = {"overall": overall, "delta": delta, "issues": len(issues), "keywords": len(keywords), "latest_audit_id": latest.id if latest else None}
    return subject, html, ctx


async def generate_and_send(db, website: Website, recipients: List[str], period: str = "weekly",
                            schedule_id: Optional[int] = None) -> ReportRun:
    run = ReportRun(schedule_id=schedule_id, website_id=website.id, recipients=list(recipients),
                    period_label=f"{period} · {datetime.now(timezone.utc).strftime('%Y-%m-%d')}", status="pending")
    db.add(run)
    await db.flush()
    try:
        subject, html, _ = await build_report_html(db, website, period)
        run.subject = subject
        run.html = html
        info = await send_email(recipients, subject, html)
        run.status = "sent"
        run.delivery_info = info
    except Exception as exc:
        log.exception("report delivery failed for website %s", website.id)
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"[:1000]
    await db.flush()
    return run
