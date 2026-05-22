"""
AKRITA Orchestrator BFF — main FastAPI app.

Sequences decisions from NOMOS / SPATHA / AGROS through the
trace pipeline + risk gate + execution surface.
"""
from __future__ import annotations

import logging
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from orchestrator.app.config import settings
from orchestrator.app.db.session import init_engine, shutdown_engine
from orchestrator.app.redis_client import init_redis, shutdown_redis
from orchestrator.app.routers import (
    builder,
    decisions,
    leaderboard,
    live,
    state as state_router,
    traces,
    users,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
)
log = logging.getLogger("akrita")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("AKRITA orchestrator starting")
    log.info("  TraceRegistry: %s", settings.trace_registry_addr or "<unset>")
    log.info("  BuilderRegistry: %s", settings.builder_registry_addr or "<unset>")
    log.info(
        "  BuilderCode: %s",
        (settings.poly_builder_code[:10] + "...") if settings.poly_builder_code else "<unset>",
    )
    init_engine()
    init_redis()
    log.info("  Postgres + Redis engines initialised")
    try:
        yield
    finally:
        await shutdown_engine()
        await shutdown_redis()
        log.info("AKRITA orchestrator shutting down")


app = FastAPI(
    title="AKRITA Orchestrator",
    description=(
        "Multi-agent autonomous keeper for Polymarket V2 with USYC active "
        "margin. Three agents (NOMOS pricing, SPATHA hedge, AGROS treasury) "
        "negotiate decisions through this BFF."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(decisions.router, prefix="/decisions", tags=["decisions"])
app.include_router(state_router.router, prefix="/state", tags=["state"])
app.include_router(traces.router, prefix="/traces", tags=["traces"])
app.include_router(live.router, prefix="/live", tags=["live"])
# Multi-tenant: identity, per-user builder onboarding, public leaderboard.
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(builder.router, prefix="/api/builder", tags=["builder"])
app.include_router(leaderboard.router, prefix="/api/leaderboard", tags=["leaderboard"])


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok"}


# Serve the bundled demo dashboard at /  — only if frontend is built.
# Mounting at "/" intercepts every unmatched route, so we register all the
# JSON routes above first, then mount static last as the catch-all.
frontend_dir = pathlib.Path(__file__).resolve().parents[2] / "frontend"
if (frontend_dir / "index.html").exists():

    def _frontend_page(file_name: str) -> FileResponse:
        return FileResponse(frontend_dir / file_name)

    @app.get("/dashboard", include_in_schema=False)
    async def dashboard_page() -> FileResponse:
        return _frontend_page("dashboard.html")

    @app.get("/builder", include_in_schema=False)
    async def builder_page() -> FileResponse:
        return _frontend_page("builder.html")

    @app.get("/leaderboard", include_in_schema=False)
    async def leaderboard_page() -> FileResponse:
        return _frontend_page("leaderboard.html")

    @app.get("/about", include_in_schema=False)
    async def about_page() -> FileResponse:
        return _frontend_page("about.html")

    @app.get("/trace", include_in_schema=False)
    @app.get("/trace/{trace_ref:path}", include_in_schema=False)
    async def trace_page(trace_ref: str = "") -> FileResponse:
        return _frontend_page("trace.html")

    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
