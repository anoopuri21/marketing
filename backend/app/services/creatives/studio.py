"""Creative studio service: brand kit, template rendering, optional AI image generation, storage."""
from __future__ import annotations

import base64
import logging
import re
import secrets
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from app.core.config import settings
from app.core.http import ssl_context
from app.core.time import aware
from app.models import Creative, Website
from app.services.creatives.renderer import SIZES, TEMPLATES, CreativeSpec, hex_to_rgb, render

log = logging.getLogger(__name__)

DEFAULT_BRAND: dict[str, Any] = {"primary": "#4F46E5", "secondary": "#0EA5E9", "text": "#FFFFFF", "logo_path": "", "style": "clean, modern, friendly"}


def media_root() -> Path:
    root = Path(settings.media_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def public_media_url(rel_path: str) -> str:
    """Absolute URL for a stored media file (used by social publishers – platforms fetch the image)."""
    return f"{settings.public_base_url.rstrip('/')}/media/{rel_path.lstrip('/')}"


def brand_for(website: Website) -> dict[str, Any]:
    brand = {**DEFAULT_BRAND, **(website.brand or {})}
    brand["name"] = website.name or website.domain
    brand["handle"] = website.domain.removeprefix("www.")
    return brand


def spec_from_payload(website: Website, payload: dict[str, Any]) -> CreativeSpec:
    brand = brand_for(website)
    return CreativeSpec(
        headline=str(payload.get("headline") or "").strip()[:220],
        subline=str(payload.get("subline") or "").strip()[:600],
        brand_name=str(payload.get("brand_name") or brand["name"]),
        handle=str(payload.get("handle") if payload.get("handle") is not None else brand["handle"]),
        cta=str(payload.get("cta") or "").strip()[:40],
        template=str(payload.get("template")) if payload.get("template") in TEMPLATES else "bold",
        size=str(payload.get("size")) if payload.get("size") in SIZES else "square",
        primary=str(payload.get("primary") or brand["primary"]),
        secondary=str(payload.get("secondary") or brand["secondary"]),
        text=str(payload.get("text") or brand["text"]),
        logo_path=str(media_root() / brand["logo_path"]) if brand.get("logo_path") else None,
        accent_words=[w for w in (payload.get("accent_words") or []) if isinstance(w, str)][:5],
    )


def _new_rel_path(website_id: int, ext: str = "png") -> str:
    rel = Path("creatives") / str(website_id) / f"{secrets.token_hex(8)}.{ext}"
    (media_root() / rel).parent.mkdir(parents=True, exist_ok=True)
    return rel.as_posix()


def render_template_creative(website: Website, payload: dict[str, Any]) -> Creative:
    spec = spec_from_payload(website, payload)
    if not spec.headline:
        raise ValueError("headline is required")
    img = render(spec)
    rel = _new_rel_path(website.id)
    img.save(media_root() / rel, format="PNG", optimize=True)
    return Creative(
        website_id=website.id, kind="template", template=spec.template, size=spec.size, width=img.width, height=img.height, path=rel,
        spec={"headline": spec.headline, "subline": spec.subline, "cta": spec.cta, "primary": spec.primary, "secondary": spec.secondary,
              "accent_words": spec.accent_words, "brand_name": spec.brand_name, "handle": spec.handle},
    )


def preview_png(website: Website, payload: dict[str, Any]) -> bytes:
    """Fast preview (downscaled) without persisting."""
    import io

    spec = spec_from_payload(website, payload)
    if not spec.headline:
        spec.headline = "Your headline here"
    img = render(spec)
    img.thumbnail((540, 960))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def store_upload(website: Website, data: bytes, filename: str, kind: str = "upload") -> Creative:
    import io

    img = Image.open(io.BytesIO(data))
    img.load()
    fmt = "png" if (img.mode in ("RGBA", "P") or filename.lower().endswith(".png")) else "jpg"
    rel = _new_rel_path(website.id, fmt)
    if fmt == "jpg":
        img.convert("RGB").save(media_root() / rel, format="JPEG", quality=88)
    else:
        img.save(media_root() / rel, format="PNG", optimize=True)
    return Creative(website_id=website.id, kind=kind, template="", size="custom", width=img.width, height=img.height, path=rel,
                    spec={"filename": filename})


def store_logo(website: Website, data: bytes, filename: str) -> str:
    import io

    img = Image.open(io.BytesIO(data)).convert("RGBA")
    img.thumbnail((600, 300))
    rel = Path("brand") / str(website.id) / "logo.png"
    (media_root() / rel).parent.mkdir(parents=True, exist_ok=True)
    img.save(media_root() / rel, format="PNG")
    return rel.as_posix()


# --------------------------------------------------------------------------- #
# AI image generation (optional)
# --------------------------------------------------------------------------- #
def image_provider_available() -> bool:
    return settings.resolved_image_provider == "openai"


async def generate_ai_creative(website: Website, prompt: str, size: str = "square") -> Creative:
    if not image_provider_available():
        raise RuntimeError("No image provider configured (set OPENAI_API_KEY to enable AI images). Template creatives work without a key.")
    brand = brand_for(website)
    sizes = {"square": "1024x1024", "landscape": "1536x1024", "story": "1024x1536"}
    full_prompt = (
        f"{prompt.strip()}. Social media marketing image for {brand['name']} ({website.industry or 'business'}"
        f"{', ' + website.target_location if website.target_location else ''}). Style: {brand.get('style', 'clean, modern')}; "
        f"brand colours around {brand['primary']} and {brand['secondary']}. No text, no letters, no watermarks, photographic or clean illustration."
    )
    body = {"model": settings.openai_image_model, "prompt": full_prompt, "n": 1, "size": sizes.get(size, "1024x1024")}
    async with httpx.AsyncClient(timeout=180, verify=ssl_context()) as client:
        resp = await client.post(f"{settings.openai_base_url.rstrip('/')}/images/generations",
                                 headers={"Authorization": f"Bearer {settings.openai_api_key}"}, json=body)
    if resp.status_code != 200:
        try:
            msg = resp.json().get("error", {}).get("message", resp.text[:200])
        except Exception:
            msg = resp.text[:200]
        raise RuntimeError(f"Image generation failed ({resp.status_code}): {msg}")
    item = resp.json()["data"][0]
    if item.get("b64_json"):
        data = base64.b64decode(item["b64_json"])
    else:
        async with httpx.AsyncClient(timeout=60, verify=ssl_context()) as client:
            data = (await client.get(item["url"])).content
    creative = store_upload(website, data, "ai.png", kind="ai")
    creative.size = size
    creative.spec = {"prompt": prompt, "model": settings.openai_image_model}
    return creative


# --------------------------------------------------------------------------- #
# Brand colour extraction from the website (best-effort, no network beyond the crawl we already do)
# --------------------------------------------------------------------------- #
HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")


def guess_brand_colours(html: str) -> dict[str, str]:
    """Pick the most frequent saturated colours from inline CSS / theme-color meta."""
    import colorsys
    from collections import Counter

    m = re.search(r'name=["\']theme-color["\'][^>]*content=["\'](#[0-9a-fA-F]{3,6})', html or "", re.I)
    counts: Counter = Counter()
    for hx in HEX_RE.findall(html or ""):
        rgb = hex_to_rgb(hx)
        _h, l, s = colorsys.rgb_to_hls(*[c / 255 for c in rgb])
        if s < 0.35 or l < 0.15 or l > 0.85:  # skip greys / near black / near white
            continue
        counts["#{:02X}{:02X}{:02X}".format(*rgb)] += 1
    ranked = [c for c, _ in counts.most_common(6)]
    out: dict[str, str] = {}
    if m:
        out["primary"] = m.group(1).upper()
    elif ranked:
        out["primary"] = ranked[0]
    for c in ranked:
        if c != out.get("primary"):
            out["secondary"] = c
            break
    return out


def creative_to_dict(c: Creative) -> dict[str, Any]:
    return {
        "id": c.id, "kind": c.kind, "template": c.template, "size": c.size, "width": c.width, "height": c.height,
        "url": f"/media/{c.path}", "public_url": public_media_url(c.path), "spec": c.spec or {}, "created_at": aware(c.created_at),
    }


def template_catalog() -> list[dict[str, Any]]:
    return [{"id": k, **v} for k, v in TEMPLATES.items()]
