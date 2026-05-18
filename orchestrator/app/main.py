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
from fastapi.staticfiles import StaticFiles

from orchestrator.app.config import settings
from orchestrator.app.routers import decisions, live, state as state_router, traces

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
)
log = logging.getLogger("akrita")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("AKRITA orchestrator starting")
    log.info("  TraceRegistry: %s", settings.trace_registry_addr)
    log.info("  BuilderRegistry: %s", settings.builder_registry_addr)
    log.info("  BuilderCode: %s", settings.builder_code[:10] + "...")
    yield
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


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok"}


# Serve the bundled demo dashboard at /  — only if frontend is built.
# Mounting at "/" intercepts every unmatched route, so we register all the
# JSON routes above first, then mount static last as the catch-all.
frontend_dir = pathlib.Path(__file__).resolve().parents[2] / "frontend"
if (frontend_dir / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
