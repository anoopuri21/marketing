from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import DB, OwnedWebsite
from app.models import Audit, AuditIssue, Task
from app.schemas.all import PlanRequest, PlanResponse, PlanWeek, TaskCreate, TaskOut, TaskUpdate
from app.services.ai.insights import generate_plan
from app.services.rank_tracker import load_keywords

router = APIRouter(prefix="/api/websites/{website_id}", tags=["tasks & planning"])

PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(website: OwnedWebsite, db: DB, status: str | None = None):
    stmt = select(Task).where(Task.website_id == website.id)
    if status:
        stmt = stmt.where(Task.status == status)
    tasks = list((await db.execute(stmt)).scalars().all())
    tasks.sort(key=lambda t: (t.status == "done", PRIORITY_ORDER.get(t.priority, 4), t.created_at))
    return tasks


@router.post("/tasks", response_model=TaskOut, status_code=201)
async def create_task(payload: TaskCreate, website: OwnedWebsite, db: DB):
    task = Task(website_id=website.id, source="manual", **payload.model_dump())
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(task_id: int, payload: TaskUpdate, website: OwnedWebsite, db: DB):
    task = await db.get(Task, task_id)
    if task is None or task.website_id != website.id:
        raise HTTPException(status_code=404, detail="Task not found")
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(task, k, v)
    if "status" in data:
        task.completed_at = datetime.now(UTC) if data["status"] == "done" else None
    await db.commit()
    await db.refresh(task)
    return task


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: int, website: OwnedWebsite, db: DB):
    task = await db.get(Task, task_id)
    if task is None or task.website_id != website.id:
        raise HTTPException(status_code=404, detail="Task not found")
    await db.delete(task)
    await db.commit()


@router.post("/plan", response_model=PlanResponse)
async def generate_action_plan(payload: PlanRequest, website: OwnedWebsite, db: DB):
    latest = (await db.execute(
        select(Audit).where(Audit.website_id == website.id, Audit.status == "completed").order_by(Audit.finished_at.desc()).limit(1)
    )).scalars().first()
    issues, scores = [], {}
    if latest:
        rows = (await db.execute(select(AuditIssue).where(AuditIssue.audit_id == latest.id))).scalars().all()
        issues = [{"code": i.code, "category": i.category, "severity": i.severity, "title": i.title,
                   "description": i.description, "recommendation": i.recommendation, "page_url": i.page_url, "impact": i.impact} for i in rows]
        raw_scores = {"seo": latest.seo_score, "technical": latest.technical_score, "content": latest.content_score,
                      "aeo": latest.aeo_score, "ai": latest.ai_readiness_score, "performance": latest.performance_score, "social": latest.social_score}
        scores = {k: v for k, v in raw_scores.items() if v is not None}
    keywords = [k.term for k in await load_keywords(db, website.id)]
    ctx = {"url": website.url, "name": website.name, "industry": website.industry,
           "target_location": website.target_location, "description": website.description}
    plan = await generate_plan(ctx, issues, scores, keywords, payload.horizon_weeks, payload.focus)

    # Persist as tasks with due dates per week (skip exact-title duplicates that are still open).
    open_titles = {t.title.lower() for t in (await db.execute(
        select(Task).where(Task.website_id == website.id, Task.status.in_(["todo", "in_progress"]))
    )).scalars().all()}
    created = 0
    weeks_out: list[PlanWeek] = []
    now = datetime.now(UTC)
    for w in plan.get("weeks", []):
        week_no = int(w.get("week", len(weeks_out) + 1))
        due = now + timedelta(days=7 * week_no)
        tasks_in = []
        for t in w.get("tasks", []):
            try:
                tc = TaskCreate(title=str(t.get("title", ""))[:255], description=str(t.get("description", "")),
                                category=str(t.get("category", "seo"))[:32],
                                priority=t.get("priority") if t.get("priority") in PRIORITY_ORDER else "medium", due_date=due)
            except Exception:
                continue
            tasks_in.append(tc)
            if tc.title.lower() in open_titles:
                continue
            db.add(Task(website_id=website.id, source="ai", **tc.model_dump()))
            open_titles.add(tc.title.lower())
            created += 1
        weeks_out.append(PlanWeek(week=week_no, theme=str(w.get("theme", f"Week {week_no}")), tasks=tasks_in))
    await db.commit()
    return PlanResponse(provider=plan.get("provider", "rule-based"), strategy_summary=plan.get("strategy_summary", ""),
                        weeks=weeks_out, created_tasks=created)
