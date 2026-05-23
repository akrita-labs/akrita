"""AKRITA v1 onboarding / consent / geo router (mounted at /api/onboarding).

This is the signup funnel that turns a bare user into one with declared
jurisdiction, the consents AGROS needs, and an enabled agent instance —
enforcing the regulatory gates as it goes:

  - USYC is a Securities-Act-1933-restricted instrument: AGROS **Tier A**
    (USYC-only treasury) is BLOCKED for US persons AT SIGNUP. We decide
    is_us_person at jurisdiction declaration and refuse to create an enabled
    Tier A instance for them.
  - AGROS **Tier C** (sUSDe / Pendle) requires an EIP-712 `susde_cooldown`
    consent on file before the instance can be created.

JURISDICTION PERSISTENCE (v1 approach — read this):
`state.py` exposes no setter for the User columns (jurisdiction_declared,
jurisdiction_ip_country, is_us_person) and those models are frozen, so we
persist the declaration through the existing consent write path:
`record_consent(consent_type="jurisdiction", version="1", ...)` with the
decision carried in `typed_data` = {jurisdiction, ip_country, is_us_person}.
The gate logic later reads it back via `get_consent(user_id, "jurisdiction")`.
A dedicated `users.jurisdiction` setter is a deliberate follow-up.

IP-GEO (v1 approach): we read `request.client.host` but do NOT call a paid
IP-geolocation provider. With no provider wired we treat the declared value
as `ip_country`. TODO: a real IP-geo lookup is a follow-up (no paid dep added
here).
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from shared.config import settings

router = APIRouter()

_ISO2_RE = re.compile(r"^[A-Za-z]{2}$")

JURISDICTION_CONSENT_TYPE = "jurisdiction"
JURISDICTION_VERSION = "1"
SUSDE_CONSENT_TYPE = "susde_cooldown"
SUSDE_DEFAULT_VERSION = "1"
# EIP-712 type string the SusdeAcceptance contract verifies against.
SUSDE_CONSENT_TYPESTRING = "SusdeConsent(address user,uint64 version,bytes32 docHash,uint256 nonce)"


def _susde_domain() -> dict:
    """EIP-712 domain for the SusdeAcceptance registry.

    `verifyingContract` is the deployed address from config (None until the
    contract is broadcast and SUSDE_ACCEPTANCE_ADDR is set); `chainId` is
    supplied client-side from the wallet/RPC.
    """
    return {
        "name": "AKRITA SusdeAcceptance",
        "version": "1",
        "verifyingContract": settings.susde_acceptance_addr or None,
    }


# ---------------------------------------------------------------------------
# Pure gate decision (unit-tested directly; the /instance route calls this)
# ---------------------------------------------------------------------------

def instance_gate_check(
    archetype: str,
    tier: str | None,
    is_us_person: bool,
    has_susde_consent: bool,
    has_jurisdiction: bool,
) -> tuple[bool, int, str]:
    """Decide whether an agent instance may be created/enabled.

    Returns (allowed, http_code, message). On allow, http_code is 200 and
    message is "ok". Only AGROS is gated; NOMOS and SPATHA are always allowed.

    AGROS gates (in order):
      1. Jurisdiction must be on file (needed to know is_us_person)  -> 409
      2. Tier A is USYC-only and USYC is restricted to NON-US persons
         (Securities Act of 1933) -> US person blocked                -> 403
      3. Tier C (sUSDe/Pendle) requires a signed susde_cooldown consent -> 409
    """
    if archetype != "agros":
        return True, 200, "ok"

    if not has_jurisdiction:
        return (
            False,
            409,
            "jurisdiction must be declared before enabling AGROS — "
            "POST /api/onboarding/jurisdiction first",
        )

    if tier == "A" and is_us_person:
        return (
            False,
            403,
            "AGROS Tier A invests idle USDC in USYC, a security restricted to "
            "non-US persons under the Securities Act of 1933; US persons cannot "
            "enable Tier A. Choose Tier B or declare a non-US jurisdiction.",
        )

    if tier == "C" and not has_susde_consent:
        return (
            False,
            409,
            "AGROS Tier C uses sUSDe (7-day cooldown on redemption); sign the "
            "EIP-712 susde_cooldown consent first via "
            "POST /api/onboarding/consent/susde.",
        )

    return True, 200, "ok"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _derive_ip_country(request: Request, declared: str) -> str:
    """Best-effort IP -> ISO-2 country.

    v1: no paid IP-geo provider is wired, so we fall back to the declared
    value as the ip_country (and record the observed client host for audit).
    TODO: plug a real IP-geolocation lookup here as a follow-up — do NOT add a
    paid dependency to satisfy this.
    """
    client = request.client
    host = client.host if client else None  # noqa: F841 — reserved for a real lookup
    # No geolocation provider available -> trust the declared value.
    return declared.upper()


async def _read_jurisdiction(state, user_id: str) -> dict | None:
    """Read the latest jurisdiction declaration (stored as a consent)."""
    consent = await state.get_consent(user_id, JURISDICTION_CONSENT_TYPE)
    if not consent:
        return None
    td = consent.get("typed_data") or {}
    # typed_data carries the decision; tolerate either flat or nested shapes.
    payload = td.get("message", td)
    return {
        "jurisdiction_declared": payload.get("jurisdiction"),
        "ip_country": payload.get("ip_country"),
        "is_us_person": bool(payload.get("is_us_person")),
    }


def _public_user(u: dict) -> dict:
    return {
        "id": u["id"],
        "handle": u.get("handle"),
        "display_name": u.get("display_name"),
        "msca_address": u.get("msca_address"),
        "is_system": bool(u.get("is_system")),
    }


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class JurisdictionBody(BaseModel):
    user_id: str
    jurisdiction_declared: str = Field(description="ISO-3166-1 alpha-2 country code")


class SusdeConsentBody(BaseModel):
    # signer_address/typed_data/signature are optional: the UI may record an
    # acknowledgment before wallet (MSCA) signing is wired. The on-chain
    # SusdeAcceptance.accept(...) submission (human-held) remains the
    # authoritative cryptographic gate.
    user_id: str
    signer_address: str = ""
    typed_data: dict = {}
    signature: str = ""
    version: str = SUSDE_DEFAULT_VERSION


class InstanceBody(BaseModel):
    user_id: str
    archetype: str
    template_key: str | None = None
    params: dict | None = None
    enabled: bool = False
    name: str = "default"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/jurisdiction")
async def declare_jurisdiction(body: JurisdictionBody, request: Request) -> dict:
    from orchestrator.app.state import state

    declared = body.jurisdiction_declared.strip()
    if not _ISO2_RE.match(declared):
        raise HTTPException(422, "jurisdiction_declared must be an ISO-3166-1 alpha-2 code")
    declared = declared.upper()

    user = await state.get_user(body.user_id)
    if not user:
        raise HTTPException(404, "user not found")

    ip_country = _derive_ip_country(request, declared)
    is_us_person = (declared == "US") or (ip_country == "US")

    # Persist via the consent write path (no users.jurisdiction setter in v1).
    decision = {
        "jurisdiction": declared,
        "ip_country": ip_country,
        "is_us_person": is_us_person,
    }
    await state.record_consent(
        user_id=body.user_id,
        consent_type=JURISDICTION_CONSENT_TYPE,
        version=JURISDICTION_VERSION,
        signer_address=(user.get("msca_address") or "0x" + "0" * 40),
        typed_data=decision,
        signature="",  # a declaration, not a signed EIP-712 payload
    )

    return {
        "user_id": body.user_id,
        "jurisdiction_declared": declared,
        "ip_country": ip_country,
        "is_us_person": is_us_person,
    }


@router.post("/consent/susde")
async def record_susde_consent(body: SusdeConsentBody) -> dict:
    from orchestrator.app.state import state

    user = await state.get_user(body.user_id)
    if not user:
        raise HTTPException(404, "user not found")

    version = body.version or SUSDE_DEFAULT_VERSION
    await state.record_consent(
        user_id=body.user_id,
        consent_type=SUSDE_CONSENT_TYPE,
        version=version,
        signer_address=body.signer_address,
        typed_data=body.typed_data,
        signature=body.signature,
    )
    # NOTE: the on-chain SusdeAcceptance.accept(...) submission is a separate,
    # human-held step. Here we only persist the signed off-chain consent.
    has = await state.has_consent(body.user_id, SUSDE_CONSENT_TYPE, version)
    return {
        "recorded": True,
        "has_consent": bool(has),
        "verifying_contract": settings.susde_acceptance_addr or None,
    }


@router.get("/consent/susde/{user_id}")
async def get_susde_consent(user_id: str) -> dict:
    from orchestrator.app.state import state

    has = await state.has_consent(user_id, SUSDE_CONSENT_TYPE, SUSDE_DEFAULT_VERSION)
    return {
        "has_consent": bool(has),
        "consent_version": SUSDE_DEFAULT_VERSION,
        "verifying_contract": settings.susde_acceptance_addr or None,
        "domain": _susde_domain(),
        "primary_type": "SusdeConsent",
        "type": SUSDE_CONSENT_TYPESTRING,
    }


@router.post("/instance")
async def create_instance(body: InstanceBody) -> dict:
    from shared.params import ARCHETYPE_PARAMS, TEMPLATES, validate_params

    from orchestrator.app.state import state

    archetype = body.archetype.strip().lower()
    if archetype not in ARCHETYPE_PARAMS:
        raise HTTPException(404, f"unknown archetype '{archetype}'")

    user = await state.get_user(body.user_id)
    if not user:
        raise HTTPException(404, "user not found")

    # Resolve params: template_key takes precedence, else explicit params.
    resolved_params: dict = {}
    if body.template_key:
        tpl = TEMPLATES.get(body.template_key)
        if tpl is None:
            tpl = await state.get_template(body.template_key)
        if tpl is None:
            raise HTTPException(404, f"unknown template '{body.template_key}'")
        if archetype == "agros":
            # Templates carry the AGROS tier (agros_tier / agros_params.tier),
            # not a full AgrosParams body — seed the tier and use defaults.
            tier = tpl.get("agros_tier") or (tpl.get("agros_params") or {}).get("tier") or "B"
            resolved_params = {"tier": tier}
        else:
            # NOMOS/SPATHA params live under the archetype key in the template.
            resolved_params = tpl.get(archetype) or tpl.get(f"{archetype}_params") or {}
    elif body.params is not None:
        resolved_params = body.params

    # Validate against the depurated parameter surface (extra=forbid). The
    # unknown-archetype case is handled above; here any failure is a bad
    # params body (removed/unknown knobs, out-of-range) -> 422.
    try:
        validated = validate_params(archetype, resolved_params)
    except Exception as e:
        raise HTTPException(422, f"invalid params: {e}")
    params_out = validated.model_dump()

    # Resolve the AGROS tier from validated params for the gate.
    tier = params_out.get("tier") if archetype == "agros" else None

    # Read jurisdiction (persisted as a consent) + susde consent for the gate.
    juris = await _read_jurisdiction(state, body.user_id)
    is_us_person = bool(juris["is_us_person"]) if juris else False
    has_jurisdiction = juris is not None
    has_susde = await state.has_consent(body.user_id, SUSDE_CONSENT_TYPE, SUSDE_DEFAULT_VERSION)

    allowed, code, msg = instance_gate_check(
        archetype=archetype,
        tier=tier,
        is_us_person=is_us_person,
        has_susde_consent=bool(has_susde),
        has_jurisdiction=has_jurisdiction,
    )
    if not allowed:
        raise HTTPException(code, msg)

    # Create or update the named instance for this (user, archetype, name).
    existing = [
        i
        for i in await state.list_user_instances(body.user_id)
        if i.get("archetype") == archetype and i.get("name") == body.name
    ]
    if existing:
        inst = existing[0]
        await state.set_instance_flags(
            inst["id"], enabled=body.enabled, params=params_out
        )
        inst = await state.get_agent_instance(inst["id"])
    else:
        inst = await state.create_agent_instance(
            user_id=body.user_id,
            archetype=archetype,
            name=body.name,
            enabled=body.enabled,
            params=params_out,
        )

    return inst


@router.get("/profile/{user_id}")
async def get_profile(user_id: str) -> dict:
    from orchestrator.app.reputation import compute_reputation_summary
    from orchestrator.app.state import state

    user = await state.get_user(user_id)
    if not user:
        raise HTTPException(404, "user not found")

    summary = await compute_reputation_summary(user_id, state=state)
    juris = await _read_jurisdiction(state, user_id)
    return {
        **_public_user(user),
        "reputation": summary,
        "jurisdiction": juris,
    }
