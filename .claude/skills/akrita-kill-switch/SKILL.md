---
name: akrita-kill-switch
description: >
  Engage the AKRITA unified kill switch for an operator — atomically cancel NOMOS
  orders, close SPATHA hedges, redeem AGROS USYC, and commit a kill-switch trace to
  Arc. Use ONLY on explicit requests like "engage the kill switch", "AKRITA halt",
  "panic stop trading for user X". Halts live trading and takes market-order slippage
  on hedges. Requires the token KILL-CONFIRMED. Never auto-run under any circumstance.
user-invocable: true
disable-model-invocation: true
allowed-tools: Bash(curl:*), Read
---

# AKRITA unified kill switch

> **Confirmation gate.** Do NOT POST to `/api/kill-switch` until the user's message
> contains the literal token `KILL-CONFIRMED`. If absent, stop and ask them to
> re-invoke with it AND the target `user_id`. Never infer the user_id; never engage
> "all users" implicitly. This cancels live orders and closes perp positions.

Implemented by `orchestrator/app/kill_switch.py` (sequenced, best-effort: NOMOS
cancel → SPATHA close → AGROS redeem → Arc trace commit; one venue failing yields
`status: partial`, not a crash). Route is `POST /api/kill-switch` (NOT `/admin/kill`).

## Find the target user_id (safe)
```bash
curl -sS http://127.0.0.1:8000/api/users | python3 -m json.tool          # handles → ids
curl -sS "http://127.0.0.1:8000/api/leaderboard" | python3 -c "import sys,json;[print(r['handle'],r['user_id']) for r in json.load(sys.stdin)['leaderboard']]"
```
(The system user is `00000000-0000-0000-0000-000000000001`.)

## Engage (GATED — needs KILL-CONFIRMED)
```bash
curl -sS -X POST http://127.0.0.1:8000/api/kill-switch \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"<uuid>","trigger_source":"manual","trigger_detail":{"reason":"<why>"}}'
```
The response is the event. Then confirm:
```bash
curl -sS http://127.0.0.1:8000/api/kill-switch/<event_id> | python3 -m json.tool
```
Report `status` (completed|partial), `nomos_result`, `spatha_result`, `agros_result`,
and the `arc_tx` (the on-chain kill-switch trace). For any non-empty `errors`, surface
them — live unwind effects are gated by the same Polymarket/Hyperliquid/USYC funding
gates as everywhere, so `partial` is expected until those venues are funded; the
audit event + Arc commit are authoritative regardless.

## Release (manual — there is no release endpoint)
Engaging sets `kill_switch=true` on the user's agent instances. To resume, re-enable
each instance explicitly (an operator decision, not part of this skill):
```bash
curl -sS http://127.0.0.1:8000/api/instances?archetype=nomos\&enabled=false   # locate the instance id(s)
curl -sS -X PUT http://127.0.0.1:8000/api/instances/<instance_id> -H 'Content-Type: application/json' -d '{"enabled":true}'
```

## Notes
- The real gates are the permission prompt on the POST (not allow-listed) + the
  KILL-CONFIRMED token. Maximum blast radius — when in doubt, do not engage.
