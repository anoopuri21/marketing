from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DB, OwnedWebsite
from app.core.errors import NotFoundError
from app.core.time import utcnow
from app.models import Task
from app.schemas.all import PlanRequest, PlanResponse, PlanWeek, TaskCreate, TaskOut, TaskUpdate
from app.services.planning import build_action_plan, sort_tasks

router = APIRouter(prefix="/api/websites/{website_id}", tags=["tasks & planning"])


async def _owned_task(db: DB, website_id: int, task_id: int) -> Task:
    task = await db.get(Task, task_id)
    if task is None or task.website_id != website_id:
        raise NotFoundError("Task not found")
    return task


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(website: OwnedWebsite, db: DB, status: str | None = None):
    stmt = select(Task).where(Task.website_id == website.id)
    if status:
        stmt = stmt.where(Task.status == status)
    return sort_tasks(list((await db.execute(stmt)).scalars().all()))


@router.post("/tasks", response_model=TaskOut, status_code=201)
async def create_task(payload: TaskCreate, website: OwnedWebsite, db: DB):
    task = Task(website_id=website.id, source="manual", **payload.model_dump())
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(task_id: int, payload: TaskUpdate, website: OwnedWebsite, db: DB):
    task = await _owned_task(db, website.id, task_id)
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(task, k, v)
    if "status" in data:
        task.completed_at = utcnow() if data["status"] == "done" else None
    await db.commit()
    await db.refresh(task)
    return task


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: int, website: OwnedWebsite, db: DB):
    task = await _owned_task(db, website.id, task_id)
    await db.delete(task)
    await db.commit()


@router.post("/plan", response_model=PlanResponse)
async def generate_action_plan(payload: PlanRequest, website: OwnedWebsite, db: DB):
    result = await build_action_plan(db, website, horizon_weeks=payload.horizon_weeks, focus=payload.focus)
    await db.commit()
    weeks = [
        PlanWeek(week=w.week, theme=w.theme, tasks=[
            TaskCreate(title=t.title, description=t.description, category=t.category, priority=t.priority, due_date=t.due_date) for t in w.tasks
        ])
        for w in result.weeks
    ]
    return PlanResponse(provider=result.provider, strategy_summary=result.strategy_summary, weeks=weeks, created_tasks=result.created)
