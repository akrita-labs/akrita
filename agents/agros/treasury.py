"""
AGROS — pure treasury decision logic.

Import-safe, side-effect-free helpers extracted from the AGROS loop so they can
be unit-tested in isolation and reused per tenant. Nothing here touches the
network, the clock, or global state: every function is a pure transform of its
arguments. The orchestration shell (``main.py``) is responsible for fetching
balances, submitting decisions, and looping.

The single authoritative per-action cap (``MAX_TREASURY_ACTION_USDC``) lives in
``shared.params`` and is re-enforced server-side; we honour it here so the agent
never *proposes* an oversized sweep.
"""
from __future__ import annotations

from shared.params import MAX_TREASURY_ACTION_USDC, AgrosParams


def target_buffer(projected_outflow: float, params: AgrosParams) -> float:
    """USDC we must keep liquid to cover the forecast horizon.

    The larger of the operator's floor (``redemption_buffer_usd``) and the
    projected outflow scaled by the safety fraction. Sweeping is only allowed
    above this line; redemptions are triggered below it.
    """
    return max(params.redemption_buffer_usd, projected_outflow * params.safety_buffer_fraction)


def decide_action(
    current_usdc: float,
    projected_outflow: float,
    params: AgrosParams,
    min_subscribe: float = 50.0,
) -> tuple[str, float]:
    """Decide subscribe / redeem / noop and the (capped) amount.

    surplus = current_usdc - target_buffer(...)
      surplus >=  min_subscribe -> sweep surplus into USYC
      surplus <= -min_subscribe -> redeem the deficit out of USYC
      otherwise                 -> noop (inside the dead-band, no churn)

    Amounts are capped at ``MAX_TREASURY_ACTION_USDC`` so a single tick can never
    move more than the per-action ceiling (the server re-enforces this too).
    """
    surplus = current_usdc - target_buffer(projected_outflow, params)

    if surplus >= min_subscribe:
        return "usyc_subscribe", min(surplus, MAX_TREASURY_ACTION_USDC)
    if surplus <= -min_subscribe:
        return "usyc_redeem", min(-surplus, MAX_TREASURY_ACTION_USDC)
    return "noop", 0.0


def tier_allows_susde(params: AgrosParams) -> bool:
    """Whether this instance may allocate to sUSDe.

    True only for Tier C *and* an explicit cooldown acceptance. The authoritative
    gate is on-chain consent enforced at config-time elsewhere; this mirrors it so
    the agent never targets sUSDe (which carries a redemption cooldown) without the
    operator having accepted that illiquidity.
    """
    return params.tier == "C" and params.susde_cooldown_acceptance is True


def humanize(
    action: str,
    amount: float,
    projected_outflow: float,
    buffer: float,
    apy: float,
    tier: str,
) -> str:
    """Render a rich, human-readable narrative for the trace.

    The spec MANDATES a narrative on every AGROS trace; these strings are the
    audit-trail prose a human reads when reconstructing why capital moved.
    """
    if action == "usyc_subscribe":
        return (
            f"Subscribed ${amount:.2f} to USYC. "
            f"Forecast ${projected_outflow:.0f} outflow next 60 min; "
            f"safety buffer ${buffer:.0f} maintained. "
            f"Capturing {apy:.2f}% APY on idle margin (Tier {tier})."
        )
    if action == "usyc_redeem":
        return (
            f"Redeemed ${amount:.2f} from USYC. "
            f"Forecast ${projected_outflow:.0f} outflow next 60 min outpaced "
            f"liquid USDC; restoring the ${buffer:.0f} safety buffer for imminent "
            f"fills (foregoing {apy:.2f}% APY on the redeemed slice, Tier {tier})."
        )
    # noop
    return (
        f"No treasury action. Liquid USDC sits within the dead-band around the "
        f"${buffer:.0f} safety buffer (forecast ${projected_outflow:.0f} outflow "
        f"next 60 min). Idle margin continues earning {apy:.2f}% APY in USYC "
        f"(Tier {tier})."
    )
