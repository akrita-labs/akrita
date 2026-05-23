"""Kill-switch HTTP surface.

Mounted at prefix ``/api/kill-switch``.

POST /            — trigger a user-scoped emergency stop (cancel orders, close
                   hedges, redeem USYC, anchor a trace on Arc).
GET  /            — list recent kill-switch events (optionally per-user).
GET  /{event_id}  — fetch a single kill-switch event.

Adapters + state are resolved exactly as the decisions router does: the
process-singleton adapter container via ``get_adapters()`` and the StateStore
facade singleton.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from adapters import get_adapters
from orchestrator.app import kill_switch as kill_switch_mod
from orchestrator.app.state import state

router = APIRouter()


class TriggerKillSwitchBody(BaseModel):
    user_id: str
    trigger_source: str = "manual"
    trigger_detail: dict = Field(default_factory=dict)


@router.post("")
async def trigger(body: TriggerKillSwitchBody) -> dict:
    adapters = get_adapters()
    event = await kill_switch_mod.trigger_kill_switch(
        body.user_id,
        body.trigger_source,
        body.trigger_detail,
        adapters=adapters,
        state=state,
    )
    return event


@router.get("")
async def list_events(
    limit: int = Query(20, ge=1, le=200),
    user_id: str | None = Query(None),
) -> dict:
    events = await state.list_kill_switch_events(limit=limit, user_id=user_id)
    return {"events": events}


@router.get("/{event_id}")
async def get_event(event_id: int) -> dict:
    event = await state.get_kill_switch_event(event_id)
    if not event:
        raise HTTPException(404, "kill-switch event not found")
    return event
