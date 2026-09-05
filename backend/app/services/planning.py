"""Planning domain: task ordering + turning an AI/rule-based action plan into board tasks."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.models import Audit, AuditIssue, Task, Website
from app.services.ai.insights import generate_plan
from app.services.rank_tracker import load_keywords

Priority = Literal["low", "medium", "high", "critical"]
PRIORITY_ORDER: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}
OPEN_STATUSES = ("todo", "in_progress")
SCORE_FIELDS = {
    "seo": "seo_score", "technical": "technical_score", "content": "content_score", "aeo": "aeo_score",
    "ai": "ai_readiness_score", "performance": "performance_score", "social": "social_score",
}


@dataclass
class PlannedTask:
    title: str
    description: str
    category: str
    priority: Priority
    due_date: datetime


@dataclass
class PlannedWeek:
    week: int
    theme: str
    tasks: list[PlannedTask] = field(default_factory=list)


@dataclass
class PlanResult:
    provider: str
    strategy_summary: str
    weeks: list[PlannedWeek]
    created: int


def sort_tasks(tasks: list[Task]) -> list[Task]:
    """Open first, then by priority, then oldest first."""
    return sorted(tasks, key=lambda t: (t.status == "done", PRIORITY_ORDER.get(t.priority, 4), t.created_at))


async def latest_audit_context(db: AsyncSession, website_id: int) -> tuple[list[dict[str, Any]], dict[str, float]]:
    """Issues + category scores of the most recent completed audit (empty when none)."""
    latest = (await db.execute(
        select(Audit).where(Audit.website_id == website_id, Audit.status == "completed").order_by(Audit.finished_at.desc()).limit(1)
    )).scalars().first()
    if latest is None:
        return [], {}
    rows = (await db.execute(select(AuditIssue).where(AuditIssue.audit_id == latest.id))).scalars().all()
    issues = [{"code": i.code, "category": i.category, "severity": i.severity, "title": i.title, "description": i.description,
               "recommendation": i.recommendation, "page_url": i.page_url, "impact": i.impact} for i in rows]
    scores = {key: float(value) for key, attr in SCORE_FIELDS.items() if (value := getattr(latest, attr)) is not None}
    return issues, scores


def website_ctx(website: Website) -> dict[str, Any]:
    return {"url": website.url, "name": website.name, "industry": website.industry, "target_location": website.target_location,
            "description": website.description}


async def build_action_plan(db: AsyncSession, website: Website, *, horizon_weeks: int, focus: str) -> PlanResult:
    """Generate a week-by-week plan and persist new tasks (exact-title duplicates that are still open are skipped)."""
    issues, scores = await latest_audit_context(db, website.id)
    keywords = [k.term for k in await load_keywords(db, website.id)]
    plan = await generate_plan(website_ctx(website), issues, scores, keywords, horizon_weeks, focus)

    open_titles = {t.title.lower() for t in (await db.execute(
        select(Task).where(Task.website_id == website.id, Task.status.in_(OPEN_STATUSES))
    )).scalars().all()}
    created = 0
    weeks: list[PlannedWeek] = []
    now = utcnow()
    for raw_week in plan.get("weeks", []):
        week_no = int(raw_week.get("week", len(weeks) + 1))
        due = now + timedelta(days=7 * week_no)
        week = PlannedWeek(week=week_no, theme=str(raw_week.get("theme", f"Week {week_no}")))
        for raw in raw_week.get("tasks", []):
            title = str(raw.get("title", "")).strip()[:255]
            if not title:
                continue
            task = PlannedTask(
                title=title, description=str(raw.get("description", "")), category=str(raw.get("category", "seo"))[:32],
                priority=cast(Priority, raw.get("priority")) if raw.get("priority") in PRIORITY_ORDER else "medium", due_date=due,
            )
            week.tasks.append(task)
            if title.lower() in open_titles:
                continue
            db.add(Task(website_id=website.id, source="ai", title=task.title, description=task.description, category=task.category,
                        priority=task.priority, due_date=task.due_date))
            open_titles.add(title.lower())
            created += 1
        weeks.append(week)
    await db.flush()
    return PlanResult(provider=plan.get("provider", "rule-based"), strategy_summary=plan.get("strategy_summary", ""), weeks=weeks, created=created)
