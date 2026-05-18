"""WebSocket endpoint — pushes live decision + fill events to the dashboard."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from orchestrator.app.state import state

router = APIRouter()
log = logging.getLogger("akrita.live")


@router.websocket("")
async def live_ws(websocket: WebSocket):
    await websocket.accept()
    q = state.subscribe_ws()
    log.info("WebSocket client connected")
    try:
        while True:
            event = await q.get()
            await websocket.send_text(json.dumps(event))
    except WebSocketDisconnect:
        log.info("WebSocket client disconnected")
    except Exception as e:
        log.exception("WebSocket error: %s", e)
    finally:
        state.unsubscribe_ws(q)
