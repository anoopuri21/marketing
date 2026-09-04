"""RankPilot API – FastAPI application entry point.

Layering (see docs/ARCHITECTURE.md):

    api/        thin HTTP layer: auth deps, request/response schemas, calls services
    services/   business logic (audits, reports, social, leads, …) – no FastAPI imports
    models/     SQLAlchemy ORM entities            core/  config, db, security, time, errors, logging

`create_app()` builds the application so tests and alternative entry points can construct it
without import-time side effects beyond settings/logging.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import audits, auth, creatives, integrations, keywords, leads, misc, reports, social, tasks, websites
from app.core.config import settings
from app.core.database import init_db
from app.core.errors import DomainError
from app.core.logging import configure_logging, request_id_middleware, request_id_var
from app.services.scheduler import recover_stale_audits, start_scheduler, stop_scheduler

configure_logging(settings.log_level)
log = logging.getLogger("rankpilot")

ROUTERS = (
    auth.router, websites.router, audits.router, keywords.router, tasks.router, reports.router,
    integrations.router, social.router, creatives.router, leads.router, misc.router,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    await recover_stale_audits()
    start_scheduler()
    log.info("%s v%s ready | env=%s ai=%s serp=%s email=%s leads=%s", settings.app_name, __version__, settings.environment,
             settings.resolved_ai_provider, settings.resolved_serp_provider, settings.resolved_email_backend, settings.resolved_lead_provider)
    yield
    stop_scheduler()


async def _domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "request_id": request_id_var.get()})


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    detail = "Internal server error" if settings.is_production else f"{type(exc).__name__}: {exc}"
    return JSONResponse(status_code=500, content={"detail": detail, "request_id": request_id_var.get()})


def _mount_static(app: FastAPI) -> None:
    # Generated creatives / uploaded logos. Public by design: social networks fetch post images from here.
    media = Path(settings.media_dir)
    media.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=media), name="media")

    # Serve the built frontend (frontend/dist) when present – single-process production deploy.
    dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str) -> FileResponse:
            candidate = dist / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.app_name} API",
        version=__version__,
        description="All-in-one website growth platform: SEO/AEO/AI-search audits, rank tracking, planning, social publishing, "
                    "lead finder and automated reports.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.middleware("http")(request_id_middleware)
    app.add_exception_handler(DomainError, _domain_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_error_handler)

    for router in ROUTERS:
        app.include_router(router)

    @app.get("/api/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    _mount_static(app)
    return app


app = create_app()
