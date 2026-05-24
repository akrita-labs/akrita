---
name: akrita-stack
description: >
  Inspect or restart the AKRITA stack. Use for "is AKRITA up", "stack status",
  "check the orchestrator", "tail orchestrator logs", "restart the orchestrator",
  "reload Caddy", or the dev-mode "bring up the stack". STATUS/logs are read-only and
  safe. RESTART/reload bounce the live service and require the token RESTART-CONFIRMED.
user-invocable: true
disable-model-invocation: true
allowed-tools: Bash(systemctl status:*), Bash(journalctl:*), Bash(curl:*), Bash(caddy validate:*), Bash(make:*), Read
---

# AKRITA stack — status & lifecycle

**Live deployment** (this host): native systemd `akrita-orchestrator` (uvicorn on
127.0.0.1:8000) behind **Caddy** (https://akritafi.xyz), with host Postgres + Redis.
The repo's `docker-compose.yml` is **dev-only** — do not use it on the live box (it
would fight the host services for ports 5432/6379).

## Status (safe — run freely)
```bash
systemctl status akrita-orchestrator caddy --no-pager
curl -fsS http://127.0.0.1:8000/health && echo
journalctl -u akrita-orchestrator -n 50 --no-pager
```
Public check (from anywhere): `https://akritafi.xyz/health` should return `{"status":"ok"}`.

## Restart / reload (GATED)
> Confirmation gate: do NOT run any `restart`/`reload` until the user's message
> contains the literal token `RESTART-CONFIRMED`. If absent, stop and ask them to
> re-invoke with it. These bounce the live site.

```bash
sudo systemctl restart akrita-orchestrator     # after a code/.env change
sudo systemctl reload caddy                     # after a Caddyfile change
caddy validate --config /etc/caddy/Caddyfile    # validate before reload (safe)
```
After restart, re-run the status checks above to confirm `active` + `/health` ok.

## Dev mode (local docker, NOT the live host)
```bash
make db-up        # Postgres + Redis only
make run          # orchestrator + 3 agents in docker compose
make migrate      # alembic upgrade head (prefer /akrita-alembic-migrate for the gated flow)
```

## Notes
- The three agents (NOMOS/SPATHA/AGROS) are **not** running as systemd units on the
  live host yet — only the orchestrator + Caddy are. Don't invent `systemctl start nomos`.
- `allowed-tools` does not enforce restrictions; the real gate for restart is the
  permission prompt on `sudo systemctl` + the RESTART-CONFIRMED token.
