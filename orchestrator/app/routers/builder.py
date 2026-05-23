"""Per-user Polymarket builder-code onboarding + live attribution.

Flow (POST /api/builder):
  1. Validate the bytes32 builder code.
  2. Encrypt the user's Polymarket CLOB creds (Fernet) and upsert the profile.
  3. Auto-register (agentId -> builderCode, controllerWallet) on the Arc
     BuilderRegistry, signed by the operator owner EOA. Idempotent: if the
     code is already on-chain we adopt that agentId instead of re-registering.

GET /api/builder/{user_id} returns that user's live attribution: on-chain
registration (verifiable via getBuilderCode), internal fill volume/fees, and
the trace anchor count + latest trace hash.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from adapters import get_adapters
from orchestrator.app.crypto import encrypt
from shared.config import BYTES32_RE, settings

router = APIRouter()

_ZERO_CODE = "0x" + "0" * 64


class RegisterBuilderBody(BaseModel):
    user_id: str
    builder_code: str = Field(description="Polymarket V2 bytes32 builder code")
    poly_api_key: str | None = None
    poly_api_secret: str | None = None
    poly_api_passphrase: str | None = None
    poly_collateral_ready: bool = False
    auto_register: bool = True


async def _builder_view(user_id: str) -> dict:
    from orchestrator.app.state import state

    profile = await state.get_builder_profile(user_id)
    if not profile:
        return {"user_id": user_id, "registered": False, "builder_code": None}

    agent_id = profile.get("onchain_agent_id")
    onchain_code = None
    if agent_id is not None:
        try:
            onchain_code = await get_adapters().arc.builder_code_for(int(agent_id))
        except Exception:
            onchain_code = None

    vol = (await state.volume_by_user()).get(user_id, {})
    trace_counts = await state.trace_count_by_user()
    latest_trace = (await state.latest_trace_by_user()).get(user_id)

    return {
        "user_id": user_id,
        "builder_code": profile.get("builder_code"),
        "onchain_agent_id": agent_id,
        "registration_status": profile.get("registration_status"),
        "registration_tx": profile.get("registration_tx"),
        "onchain_builder_code": onchain_code,
        "onchain_matches": (onchain_code or "").lower() == (profile.get("builder_code") or "").lower(),
        "poly_collateral_ready": bool(profile.get("poly_collateral_ready")),
        "attributed_volume_usdc": float(vol.get("volume", 0.0)),
        "builder_fees_usdc": float(vol.get("fees", 0.0)),
        "fills": int(vol.get("fills", 0)),
        "trace_count": int(trace_counts.get(user_id, 0)),
        "latest_trace": latest_trace,
    }


@router.post("")
async def register_builder(body: RegisterBuilderBody) -> dict:
    from orchestrator.app.state import state

    code = body.builder_code.strip().lower()
    if not BYTES32_RE.match(code):
        raise HTTPException(422, "builder_code must be 0x + 64 hex chars")
    if code == _ZERO_CODE:
        raise HTTPException(422, "builder_code must be non-zero")

    user = await state.get_user(body.user_id)
    if not user:
        raise HTTPException(404, "user not found")

    # Encrypt CLOB creds at rest (None passes through untouched).
    profile = await state.upsert_builder_profile(
        user_id=body.user_id,
        builder_code=code,
        poly_api_key_enc=encrypt(body.poly_api_key),
        poly_api_secret_enc=encrypt(body.poly_api_secret),
        poly_api_passphrase_enc=encrypt(body.poly_api_passphrase),
        poly_collateral_ready=body.poly_collateral_ready,
    )

    if body.auto_register and profile.get("registration_status") != "registered":
        await _auto_register(state, user, code, profile)

    return await _builder_view(body.user_id)


async def _auto_register(state, user: dict, code: str, profile: dict) -> None:
    """Register the code on the BuilderRegistry. Idempotent + collision-safe."""
    arc = get_adapters().arc
    controller = (
        user.get("msca_address")
        or settings.pricing_wallet_addr
        or settings.treasury_wallet_addr
        or user["id"][:42]
    )

    # If the code is already on-chain, adopt that agentId — never re-register.
    try:
        existing = await arc.agent_id_for_code(code)
    except Exception as e:
        raise HTTPException(502, f"BuilderRegistry read failed: {e}")
    if existing and int(existing) != 0:
        await state.set_builder_onchain(user["id"], int(existing), "registered", profile.get("registration_tx"))
        return

    # Allocate a free agentId (skip any already taken on-chain).
    agent_id = profile.get("onchain_agent_id") or await state.next_agent_id()
    try:
        while await arc.is_agent_registered(int(agent_id)):
            agent_id = int(agent_id) + 1
    except Exception as e:
        raise HTTPException(502, f"BuilderRegistry read failed: {e}")

    # Reserve the id in the DB before the on-chain write so concurrent
    # onboarding can't grab the same one via next_agent_id().
    await state.set_builder_onchain(user["id"], int(agent_id), "registering", None)
    try:
        receipt = await arc.register_builder(int(agent_id), code, controller)
    except Exception as e:
        await state.set_builder_status(user["id"], "failed")
        raise HTTPException(502, f"on-chain registration failed: {e}")

    status = "registered" if receipt.status == "success" else "failed"
    await state.set_builder_onchain(user["id"], int(agent_id), status, receipt.tx_hash)


@router.get("/{user_id}")
async def get_builder(user_id: str) -> dict:
    return await _builder_view(user_id)
