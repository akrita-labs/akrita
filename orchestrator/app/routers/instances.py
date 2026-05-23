"""Agent-instance work-list + tuning endpoints.

Mounted at prefix ``/api/instances``.

GET /            — the agent work-list. An archetype runner (NOMOS/SPATHA/AGROS)
                   polls this to discover the enabled, non-killed instances it
                   is responsible for driving this tick.
PUT /{instance_id} — operator/builder updates an instance's params (validated
                   against the depurated per-archetype schema) and/or its
                   enabled flag.

The instance dicts come straight from ``state`` (the StateStore facade); this
router never touches the DB or repositories directly.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from orchestrator.app.state import state
from shared.params import ARCHETYPE_PARAMS, validate_params

router = APIRouter()

_ARCHETYPES = set(ARCHETYPE_PARAMS)  # {"nomos","spatha","agros"}


def _public_instance(inst: dict) -> dict:
    """Project a raw agent_instance row down to the work-list shape."""
    return {
        "id": inst["id"],
        "user_id": inst["user_id"],
        "archetype": inst["archetype"],
        "name": inst.get("name", "default"),
        "enabled": bool(inst.get("enabled", False)),
        "kill_switch": bool(inst.get("kill_switch", False)),
        "params": inst.get("params") or {},
    }


@router.get("")
async def list_instances(
    archetype: str = Query(..., description="one of nomos/spatha/agros"),
    enabled: bool = Query(True),
) -> dict:
    """Return the instances an archetype runner should act on.

    ``state.list_enabled_instances(archetype)`` already returns only rows with
    ``enabled=True AND kill_switch=False`` (the active work-list). When the
    caller asks for ``enabled=False`` we surface the inverse intent by
    returning an empty list — the StateStore facade exposes no cross-user
    "list disabled instances" read (only ``list_user_instances(user_id)``),
    so a disabled work-list is not resolvable here without a user scope.
    """
    if archetype not in _ARCHETYPES:
        raise HTTPException(400, f"unknown archetype {archetype!r}")

    rows = await state.list_enabled_instances(archetype)
    # list_enabled_instances is already filtered to enabled & not kill_switched.
    if enabled:
        instances = [_public_instance(r) for r in rows]
    else:
        instances = []
    return {"instances": instances}


class UpdateInstanceBody(BaseModel):
    params: dict
    enabled: bool | None = None


@router.put("/{instance_id}")
async def update_instance(instance_id: str, body: UpdateInstanceBody) -> dict:
    """Validate + persist new params (and optionally toggle enabled) for an
    instance. Params are validated against the archetype's depurated schema
    (``extra='forbid'`` rejects removed knobs) before anything is written."""
    inst = await state.get_agent_instance(instance_id)
    if not inst:
        raise HTTPException(404, "instance not found")

    archetype = inst["archetype"]
    if archetype not in _ARCHETYPES:
        raise HTTPException(400, f"unknown archetype {archetype!r}")

    try:
        validated = validate_params(archetype, body.params)
    except Exception as e:
        raise HTTPException(400, f"invalid params: {e}")

    flags: dict = {"params": validated.model_dump(mode="json")}
    if body.enabled is not None:
        flags["enabled"] = body.enabled

    await state.set_instance_flags(instance_id, **flags)

    updated = await state.get_agent_instance(instance_id)
    if not updated:  # pragma: no cover — defensive, row was just present
        raise HTTPException(404, "instance not found")
    return _public_instance(updated)
