from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User, Workspace
from app.schemas.all import LoginRequest, MeResponse, RegisterRequest, TokenResponse, UserOut, WorkspaceOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(payload: RegisterRequest, db: DB):
    existing = (await db.execute(select(User).where(User.email == payload.email.lower()))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = User(email=payload.email.lower(), full_name=payload.full_name.strip(), hashed_password=hash_password(payload.password))
    db.add(user)
    await db.flush()
    ws_name = payload.workspace_name.strip() or (f"{payload.full_name.split(' ')[0]}'s workspace" if payload.full_name.strip() else "My workspace")
    db.add(Workspace(name=ws_name, owner_id=user.id))
    await db.commit()
    return TokenResponse(access_token=create_access_token(user.id))


async def _authenticate(db, email: str, password: str) -> User:
    user = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
    if user is None or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
    return user


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: DB):
    user = await _authenticate(db, payload.email, payload.password)
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/token", response_model=TokenResponse, include_in_schema=False)
async def token(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DB):
    """OAuth2 password flow (used by the Swagger UI 'Authorize' button)."""
    user = await _authenticate(db, form.username, form.password)
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUser, db: DB):
    workspaces = (await db.execute(select(Workspace).where(Workspace.owner_id == user.id).order_by(Workspace.id))).scalars().all()
    return MeResponse(user=UserOut.model_validate(user), workspaces=[WorkspaceOut.model_validate(w) for w in workspaces])
