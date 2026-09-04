"""RankPilot API – FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import audits, auth, creatives, integrations, keywords, misc, reports, social, tasks, websites
from app.core.config import settings
from app.core.database import init_db
from app.services.scheduler import recover_stale_audits, start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("rankpilot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await recover_stale_audits()
    start_scheduler()
    log.info("%s v%s ready | ai=%s serp=%s email=%s", settings.app_name, __version__,
             settings.resolved_ai_provider, settings.resolved_serp_provider, settings.resolved_email_backend)
    yield
    stop_scheduler()


app = FastAPI(
    title=f"{settings.app_name} API",
    version=__version__,
    description="All-in-one website growth platform: SEO/AEO/AI-search audits, rank tracking, planning, and automated reports.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth.router, websites.router, audits.router, keywords.router, tasks.router, reports.router, integrations.router, social.router, creatives.router, misc.router):
    app.include_router(r)


@app.get("/api/health", tags=["system"])
async def health():
    return {"status": "ok", "version": __version__}


# Generated creatives / uploaded logos. Public by design: social networks fetch post images from here.
_media = Path(settings.media_dir)
_media.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=_media), name="media")


# Serve the built frontend (frontend/dist) when present – single-process production deploy.
_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        candidate = _dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_dist / "index.html")
