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
    claims,
    decisions,
    health_instances,
    instances,
    kill_switch,
    leaderboard,
    live,
    onboarding,
    state as state_router,
    traces,
    users,
)
from orchestrator.app.state import state

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
    log.info("  SusdeAcceptance: %s", settings.susde_acceptance_addr or "<unset>")
    log.info(
        "  BuilderCode: %s",
        (settings.poly_builder_code[:10] + "...") if settings.poly_builder_code else "<unset>",
    )
    init_engine()
    init_redis()
    log.info("  Postgres + Redis engines initialised")

    import asyncio

    bg_tasks: list[asyncio.Task] = []
    if settings.freeze_oracle_enabled:
        bg_tasks.append(asyncio.create_task(_freeze_oracle_loop()))
        log.info("  Freeze-oracle loop ENABLED (every %ss)", settings.freeze_oracle_interval_s)
    if settings.goplus_oracle_enabled and settings.goplus_watchlist_addrs:
        bg_tasks.append(asyncio.create_task(_goplus_oracle_loop()))
        log.info(
            "  GoPlus-screen loop ENABLED (every %ss, %d watched)",
            settings.goplus_oracle_interval_s,
            len(settings.goplus_watchlist_addrs),
        )
    if settings.spatha_oracle_enabled:
        bg_tasks.append(asyncio.create_task(_spatha_oracle_loop()))
        log.info("  SPATHA-conviction loop ENABLED (every %ss)", settings.spatha_oracle_interval_s)
    if settings.discovery_oracle_enabled:
        bg_tasks.append(asyncio.create_task(_discovery_oracle_loop()))
        log.info("  Discovery loop ENABLED (every %ss)", settings.discovery_oracle_interval_s)
    if settings.resolver_oracle_enabled:
        bg_tasks.append(asyncio.create_task(_resolver_oracle_loop()))
        log.info("  AGROS-resolver loop ENABLED (every %ss)", settings.resolver_oracle_interval_s)

    try:
        yield
    finally:
        for t in bg_tasks:
            t.cancel()
        await shutdown_engine()
        await shutdown_redis()
        log.info("AKRITA orchestrator shutting down")


async def _freeze_oracle_loop():
    """Opt-in autonomous loop: periodically attest new on-chain stablecoin
    freezes. Idempotent (deterministic decision ids), best-effort (never raises),
    runs only when FREEZE_ORACLE_ENABLED=1."""
    import asyncio

    from adapters import get_adapters
    from agents.nomos.claim_issuer import scan_freezes

    while True:
        try:
            await asyncio.sleep(settings.freeze_oracle_interval_s)
            results = await scan_freezes(get_adapters(), limit=settings.freeze_oracle_limit)
            issued = sum(1 for r in results if not r.get("error"))
            log.info("freeze-oracle: scanned %d, newly attested %d", len(results), issued)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # never let the loop die
            log.warning("freeze-oracle loop error: %s", e)


async def _goplus_oracle_loop():
    """Opt-in autonomous loop: NOMOS periodically re-screens the GoPlus watchlist
    and issues a rug-risk claim on anything the reasoner judges a genuine rug.
    Forward-looking (rug *capability*, not a lagging freeze). Idempotent per token
    per screen, best-effort (never raises), runs only when GOPLUS_ORACLE_ENABLED=1
    and a watchlist is set."""
    import asyncio

    from adapters import get_adapters
    from agents.nomos.claim_issuer import screen_watchlist

    while True:
        try:
            await asyncio.sleep(settings.goplus_oracle_interval_s)
            results = await screen_watchlist(get_adapters(), settings.goplus_watchlist_addrs)
            issued = sum(1 for r in results if r.get("flagged"))
            skipped = sum(1 for r in results if r.get("skipped"))
            log.info(
                "goplus-screen: screened %d, issued %d, agent-skipped %d",
                len(results), issued, skipped,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:  # never let the loop die
            log.warning("goplus-screen loop error: %s", e)


async def _spatha_oracle_loop():
    """Opt-in autonomous loop: SPATHA forms (and where funded, places) bond
    conviction on open predictive claims, anchoring each decision on Arc as agent
    2. Idempotent per claim, best-effort, runs only when SPATHA_ORACLE_ENABLED=1."""
    import asyncio

    from adapters import get_adapters
    from agents.spatha.conviction_issuer import scan_open_claims

    while True:
        try:
            await asyncio.sleep(settings.spatha_oracle_interval_s)
            results = await scan_open_claims(
                get_adapters(), max_stake_usdc=settings.spatha_max_stake_usdc
            )
            decided = sum(1 for r in results if r.get("trace_hash"))
            staked = sum(1 for r in results if r.get("execution") == "staked")
            log.info("spatha-conviction: decided %d, staked %d", decided, staked)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # never let the loop die
            log.warning("spatha-conviction loop error: %s", e)


async def _discovery_oracle_loop():
    """Opt-in goal-seeking loop: NOMOS discovers freshly-promoted tokens from the
    open market, the reasoner triages which to screen, and genuine rugs are claimed.
    Best-effort, idempotent per token, runs only when DISCOVERY_ORACLE_ENABLED=1."""
    import asyncio

    from adapters import get_adapters
    from agents.nomos.claim_issuer import discover_and_screen

    while True:
        try:
            await asyncio.sleep(settings.discovery_oracle_interval_s)
            out = await discover_and_screen(
                get_adapters(),
                max_candidates=settings.discovery_max_candidates,
                max_select=settings.discovery_max_select,
            )
            issued = sum(1 for r in out.get("results", []) if r.get("flagged") and not r.get("already_attested"))
            log.info(
                "discovery: %d found, %d screened, %d newly claimed",
                out.get("discovered", 0), out.get("screened", 0), issued,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:  # never let the loop die
            log.warning("discovery loop error: %s", e)


async def _resolver_oracle_loop():
    """Opt-in loop: AGROS checks open predictive claims' real markets and settles
    the bond on clear outcomes (rugged/held), anchoring each settlement on Arc as
    agent 3. Conservative + best-effort; runs only when RESOLVER_ORACLE_ENABLED=1."""
    import asyncio

    from adapters import get_adapters
    from agents.agros.resolver_issuer import resolve_open_claims

    while True:
        try:
            await asyncio.sleep(settings.resolver_oracle_interval_s)
            results = await resolve_open_claims(get_adapters())
            resolved = sum(1 for r in results if r.get("action") == "resolved")
            log.info("agros-resolver: checked %d, settled %d", len(results), resolved)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # never let the loop die
            log.warning("agros-resolver loop error: %s", e)


app = FastAPI(
    title="AKRITA Orchestrator",
    description=(
        "Autonomous on-chain Rugpull Oracle. NOMOS reads real rug signals "
        "(stablecoin freezes, GoPlus token-security), reasons with an LLM under a "
        "deterministic risk gate, and anchors each signed claim as a verifiable "
        "trace on Arc; SPATHA and AGROS manage bond exposure and treasury."
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
# Multi-tenant runtime: per-instance work-list, onboarding/consent/geo gates,
# unified kill switch, and per-instance liveness.
app.include_router(instances.router, prefix="/api/instances", tags=["instances"])
app.include_router(onboarding.router, prefix="/api/onboarding", tags=["onboarding"])
app.include_router(kill_switch.router, prefix="/api/kill-switch", tags=["kill-switch"])
app.include_router(health_instances.router, prefix="/api/health", tags=["health"])
# Rugpull Oracle (Pivot 1): read-only claim + bond views.
app.include_router(claims.router, prefix="/api/claims", tags=["claims"])


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/templates", tags=["templates"])
async def list_templates() -> dict:
    """Onboarding templates: Conservative King / Balanced Counsel / Aggressive Sovereign."""
    return {"templates": await state.list_templates()}


# Serve the bundled demo dashboard at /  — only if frontend is built.
# Mounting at "/" intercepts every unmatched route, so we register all the
# JSON routes above first, then mount static last as the catch-all.
frontend_dir = pathlib.Path(__file__).resolve().parents[2] / "frontend"
if (frontend_dir / "index.html").exists():

    def _frontend_page(file_name: str) -> FileResponse:
        return FileResponse(frontend_dir / file_name)

    @app.get("/app/dashboard", include_in_schema=False)
    async def dashboard_page() -> FileResponse:
        return _frontend_page("dashboard.html")

    @app.get("/app/oracle", include_in_schema=False)
    async def oracle_page() -> FileResponse:
        return _frontend_page("oracle.html")

    @app.get("/login", include_in_schema=False)
    async def login_page() -> FileResponse:
        return _frontend_page("login.html")

    @app.get("/app/builder", include_in_schema=False)
    async def builder_page() -> FileResponse:
        return _frontend_page("builder.html")

    @app.get("/app/leaderboard", include_in_schema=False)
    async def leaderboard_page() -> FileResponse:
        return _frontend_page("leaderboard.html")

    @app.get("/about", include_in_schema=False)
    async def about_page() -> FileResponse:
        return _frontend_page("about.html")

    @app.get("/agents", include_in_schema=False)
    async def agents_page() -> FileResponse:
        return _frontend_page("agents.html")

    @app.get("/proof", include_in_schema=False)
    async def proof_page() -> FileResponse:
        return _frontend_page("proof.html")

    @app.get("/app/trace", include_in_schema=False)
    @app.get("/app/trace/{trace_ref:path}", include_in_schema=False)
    async def trace_page(trace_ref: str = "") -> FileResponse:
        return _frontend_page("trace.html")

    @app.get("/app/personalize", include_in_schema=False)
    async def personalize_page() -> FileResponse:
        return _frontend_page("personalize.html")

    @app.get("/app/akritai/{erc8004_id}", include_in_schema=False)
    async def akritai_page(erc8004_id: str = "") -> FileResponse:
        return _frontend_page("akritai.html")

    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
