# secrets/

This directory holds material that must not live in `.env`: JSON keystores,
delegate certs, signed permission grants, and provider-specific credential
files. The whole directory is `.gitignore`d.

## Layout

| File                        | Source                                   | Used by              |
| --------------------------- | ---------------------------------------- | -------------------- |
| `hl_api_wallet.json`        | Hyperliquid testnet API wallet keystore  | `HyperliquidReal`    |
| `circle_pricing.json`       | Circle Developer wallet export (pricing) | `CircleWalletsReal`  |
| `circle_hedge.json`         | Circle Developer wallet export (hedge)   | `CircleWalletsReal`  |
| `circle_treasury.json`      | Circle Developer wallet export (treasury)| `CircleWalletsReal`  |
| `circle_trace.json`         | Circle Developer wallet export (trace)   | `CircleWalletsReal`  |
| `gateway_delegate.json`     | EOA delegate for Gateway burn signatures | `GatewayReal`        |
| `arc_deployer.json`         | Deployer keystore for Foundry scripts    | `make contracts-deploy` |

Every file path here is referenced by an env var in `.env.example` so the
runtime can locate it without hardcoded paths. If you add a new credential
file, add the matching env var too.

## Conventions

- Never commit anything from this directory. The repo `.gitignore` excludes
  the whole tree; this README is the only tracked file.
- Use absolute paths in env vars when running outside Docker; the compose
  stack mounts `./secrets:/app/secrets:ro`.
- Rotate any key that has been pasted into chat, logs, or screenshots.
