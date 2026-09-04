"""Creative studio API: brand kit, template/AI creatives, previews, uploads."""
from __future__ import annotations

import contextlib
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, OwnedWebsite
from app.core.config import settings
from app.models import Creative
from app.services.creatives.studio import (
    brand_for,
    creative_to_dict,
    generate_ai_creative,
    guess_brand_colours,
    image_provider_available,
    media_root,
    preview_png,
    render_template_creative,
    store_logo,
    store_upload,
    template_catalog,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/websites/{website_id}/creatives", tags=["creatives"])

MAX_UPLOAD = 8 * 1024 * 1024


class CreativeSpecIn(BaseModel):
    headline: str = ""
    subline: str = ""
    cta: str = ""
    template: str = "bold"
    size: str = "square"
    primary: str | None = None
    secondary: str | None = None
    accent_words: list[str] = Field(default_factory=list)
    brand_name: str | None = None
    handle: str | None = None


class AICreativeIn(BaseModel):
    prompt: str
    size: str = "square"


class BrandIn(BaseModel):
    primary: str | None = None
    secondary: str | None = None
    text: str | None = None
    style: str | None = None


@router.get("/templates")
async def templates():
    return {"templates": template_catalog(), "sizes": ["square", "landscape", "story"], "ai_images": image_provider_available(),
            "image_provider": settings.resolved_image_provider}


@router.get("/brand")
async def get_brand(website: OwnedWebsite):
    b = brand_for(website)
    return {**b, "logo_url": f"/media/{b['logo_path']}" if b.get("logo_path") else ""}


@router.put("/brand")
async def update_brand(payload: BrandIn, website: OwnedWebsite, db: DB):
    website.brand = {**(website.brand or {}), **{k: v.strip() for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}}
    await db.commit()
    await db.refresh(website)
    b = brand_for(website)
    return {**b, "logo_url": f"/media/{b['logo_path']}" if b.get("logo_path") else ""}


@router.post("/brand/detect")
async def detect_brand(website: OwnedWebsite, db: DB):
    """Guess brand colours from the live homepage (theme-color meta / inline CSS)."""
    import httpx

    from app.core.http import ssl_context

    try:
        async with httpx.AsyncClient(timeout=15, verify=ssl_context(), follow_redirects=True, headers={"User-Agent": settings.user_agent}) as client:
            resp = await client.get(website.url)
            html = resp.text[:400_000]
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch the homepage to detect colours ({type(exc).__name__})") from exc
    colours = guess_brand_colours(html)
    if not colours:
        return {"detected": False, "brand": brand_for(website)}
    website.brand = {**(website.brand or {}), **colours}
    await db.commit()
    return {"detected": True, "brand": brand_for(website), "colours": colours}


@router.post("/brand/logo")
async def upload_logo(website: OwnedWebsite, db: DB, file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="Logo must be under 8 MB")
    try:
        rel = store_logo(website, data, file.filename or "logo.png")
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read the image – upload a PNG, JPG or WebP") from None
    website.brand = {**(website.brand or {}), "logo_path": rel}
    await db.commit()
    return {"logo_url": f"/media/{rel}"}


@router.delete("/brand/logo", status_code=204)
async def delete_logo(website: OwnedWebsite, db: DB):
    b = dict(website.brand or {})
    rel = b.pop("logo_path", "")
    website.brand = b
    await db.commit()
    if rel:
        with contextlib.suppress(OSError):
            (media_root() / rel).unlink(missing_ok=True)


@router.get("")
async def list_creatives(website: OwnedWebsite, db: DB, limit: int = 60):
    rows = (await db.execute(select(Creative).where(Creative.website_id == website.id).order_by(Creative.id.desc()).limit(limit))).scalars().all()
    return [creative_to_dict(c) for c in rows]


@router.post("/preview")
async def preview(payload: CreativeSpecIn, website: OwnedWebsite):
    png = preview_png(website, payload.model_dump())
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("", status_code=201)
async def create_creative(payload: CreativeSpecIn, website: OwnedWebsite, db: DB):
    try:
        creative = render_template_creative(website, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.add(creative)
    await db.commit()
    await db.refresh(creative)
    return creative_to_dict(creative)


@router.post("/ai", status_code=201)
async def create_ai_creative(payload: AICreativeIn, website: OwnedWebsite, db: DB):
    if not payload.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")
    try:
        creative = await generate_ai_creative(website, payload.prompt, payload.size)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.add(creative)
    await db.commit()
    await db.refresh(creative)
    return creative_to_dict(creative)


@router.post("/upload", status_code=201)
async def upload_creative(website: OwnedWebsite, db: DB, file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="Image must be under 8 MB")
    try:
        creative = store_upload(website, data, file.filename or "upload.png")
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read the image – upload a PNG, JPG or WebP") from None
    db.add(creative)
    await db.commit()
    await db.refresh(creative)
    return creative_to_dict(creative)


@router.delete("/{creative_id}", status_code=204)
async def delete_creative(creative_id: int, website: OwnedWebsite, db: DB):
    creative = await db.get(Creative, creative_id)
    if creative is None or creative.website_id != website.id:
        raise HTTPException(status_code=404, detail="Creative not found")
    path = media_root() / creative.path
    await db.delete(creative)
    await db.commit()
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)
