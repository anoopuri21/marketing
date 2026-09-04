from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, HTTPException
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, OwnedWebsite
from app.core.security import generate_token
from app.models import Audit, Website, Workspace
from app.schemas.all import (
    VerificationInstructions,
    VerifyRequest,
    VerifyResponse,
    WebsiteCreate,
    WebsiteOut,
    WebsiteUpdate,
)
from app.services import verification
from app.services.audit.engine import run_audit

router = APIRouter(prefix="/api/websites", tags=["websites"])


@router.get("", response_model=list[WebsiteOut])
async def list_websites(user: CurrentUser, db: DB):
    stmt = (
        select(Website).join(Workspace, Website.workspace_id == Workspace.id)
        .where(Workspace.owner_id == user.id).order_by(Website.created_at.desc())
    )
    return (await db.execute(stmt)).scalars().all()


@router.post("", response_model=WebsiteOut, status_code=201)
async def create_website(payload: WebsiteCreate, user: CurrentUser, db: DB, background: BackgroundTasks):
    if payload.workspace_id is not None:
        ws = await db.get(Workspace, payload.workspace_id)
        if ws is None or ws.owner_id != user.id:
            raise HTTPException(status_code=404, detail="Workspace not found")
    else:
        ws = (await db.execute(select(Workspace).where(Workspace.owner_id == user.id).order_by(Workspace.id))).scalars().first()
        if ws is None:
            ws = Workspace(name="My workspace", owner_id=user.id)
            db.add(ws)
            await db.flush()
    domain = urlparse(payload.url).netloc.lower()
    dup = (await db.execute(select(Website).where(Website.workspace_id == ws.id, Website.domain == domain))).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=409, detail="This website is already connected to the workspace")
    website = Website(
        workspace_id=ws.id, url=payload.url, domain=domain, name=payload.name.strip() or domain.removeprefix("www."),
        industry=payload.industry.strip(), target_location=payload.target_location.strip(),
        description=payload.description.strip(), verification_token=generate_token(),
    )
    db.add(website)
    await db.flush()
    # Kick off the first audit immediately so the dashboard is useful right away.
    audit = Audit(website_id=website.id, status="queued", trigger="manual")
    db.add(audit)
    await db.commit()
    background.add_task(run_audit, audit.id)
    await db.refresh(website)
    return website


@router.get("/{website_id}", response_model=WebsiteOut)
async def get_website(website: OwnedWebsite):
    return website


@router.patch("/{website_id}", response_model=WebsiteOut)
async def update_website(payload: WebsiteUpdate, website: OwnedWebsite, db: DB):
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(website, field, value.strip() if isinstance(value, str) else value)
    await db.commit()
    await db.refresh(website)
    return website


@router.delete("/{website_id}", status_code=204)
async def delete_website(website: OwnedWebsite, db: DB):
    await db.delete(website)
    await db.commit()


@router.get("/{website_id}/verification", response_model=VerificationInstructions)
async def verification_instructions(website: OwnedWebsite):
    return verification.instructions(website.url, website.verification_token)


@router.post("/{website_id}/verify", response_model=VerifyResponse)
async def verify_website(payload: VerifyRequest, website: OwnedWebsite, db: DB):
    ok, method, detail = await verification.verify(website.url, website.verification_token, payload.method)
    if ok:
        website.verified = True
        website.verified_at = datetime.now(UTC)
        website.verification_method = method
        await db.commit()
    return VerifyResponse(verified=ok, method=method, detail=detail)
