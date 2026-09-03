"""Shared FastAPI dependencies."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import User, Website, Workspace

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

DB = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)], db: DB) -> User:
    sub = decode_access_token(token)
    if sub is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user = await db.get(User, int(sub))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_owned_website(website_id: int, user: CurrentUser, db: DB) -> Website:
    stmt = (
        select(Website).join(Workspace, Website.workspace_id == Workspace.id)
        .where(Website.id == website_id, Workspace.owner_id == user.id)
    )
    website = (await db.execute(stmt)).scalar_one_or_none()
    if website is None:
        raise HTTPException(status_code=404, detail="Website not found")
    return website


OwnedWebsite = Annotated[Website, Depends(get_owned_website)]
