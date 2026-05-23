"""User identity endpoints.

A user is a person operating their own configured agent instances. Identity
is the smart-account (Circle Modular Wallet) address; before wallet
onboarding lands a user is just a handle + optional display name. Auth
(passkey/session) layers on top later — these endpoints are currently open
so the seed bootstrap + public onboarding flow can create the 12 users.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from orchestrator.app.state import state

router = APIRouter()

_HANDLE_RE = re.compile(r"^[a-zA-Z0-9_.-]{2,64}$")
_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


class CreateUserBody(BaseModel):
    handle: str = Field(min_length=2, max_length=64)
    display_name: str | None = Field(default=None, max_length=120)
    msca_address: str | None = None


def _public_user(u: dict) -> dict:
    created = u.get("created_at")
    return {
        "id": u["id"],
        "handle": u["handle"],
        "display_name": u.get("display_name"),
        "msca_address": u.get("msca_address"),
        "is_system": bool(u.get("is_system")),
        "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
    }


@router.post("")
async def create_user(body: CreateUserBody) -> dict:
    if not _HANDLE_RE.match(body.handle):
        raise HTTPException(422, "handle must be 2-64 chars of [a-zA-Z0-9_.-]")
    if body.msca_address and not _ADDR_RE.match(body.msca_address):
        raise HTTPException(422, "msca_address must be a 0x 20-byte address")
    if await state.get_user_by_handle(body.handle):
        raise HTTPException(409, f"handle '{body.handle}' already taken")
    user = await state.create_user(body.handle, body.display_name, body.msca_address)
    return _public_user(user)


@router.get("")
async def list_users() -> dict:
    return {"users": [_public_user(u) for u in await state.list_users()]}


@router.get("/{user_id}")
async def get_user(user_id: str) -> dict:
    u = await state.get_user(user_id)
    if not u:
        raise HTTPException(404, "user not found")
    return _public_user(u)
