"""
Bootstrap: create the four AKRITA keeper wallets on Circle Developer-Controlled Wallets.

Flow per https://developers.circle.com/wallets/dev-controlled/create-your-first-wallet
and https://developers.circle.com/wallets/dev-controlled/register-entity-secret:

  1. Load/generate the 32-byte entity secret (one per Circle project, irrecoverable).
  2. Register it via the Circle Python SDK (saves recovery file under secrets/).
  3. Create a wallet set ("akrita-keepers").
  4. Create four EOA wallets, each on ARC-TESTNET + MATIC-AMOY:
       pricing-keeper, hedge-keeper, treasury-keeper, trace-keeper.
  5. Write the four walletIds and the wallet-set ID back into .env.

Idempotent: skips the whole flow if all four wallet IDs already exist in .env;
reuses the entity secret file if present; skips registration if the recovery
file already exists.
"""
from __future__ import annotations

import os
import re
import secrets as py_secrets
import sys
import uuid
from pathlib import Path

from circle.web3 import developer_controlled_wallets as dcw
from circle.web3 import utils

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"
SECRETS_DIR = REPO_ROOT / "secrets"
ENTITY_SECRET_FILE = SECRETS_DIR / "circle_entity_secret.txt"
RECOVERY_DIR = SECRETS_DIR / "circle_recovery"
WALLET_RECORD_FILE = SECRETS_DIR / "circle_wallets.json"

WALLET_SET_NAME = "akrita-keepers"
BLOCKCHAINS = ["ARC-TESTNET", "MATIC-AMOY"]
ACCOUNT_TYPE = "EOA"
WALLET_NAMES = [
    ("PRICING", "pricing-keeper"),
    ("HEDGE", "hedge-keeper"),
    ("TREASURY", "treasury-keeper"),
    ("TRACE", "trace-keeper"),
]
# Map Circle blockchain enum value -> short suffix used in env-var names.
CHAIN_SUFFIX = {"ARC-TESTNET": "ARC", "MATIC-AMOY": "MATIC"}


def read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def update_env(path: Path, updates: dict[str, str]) -> None:
    text = path.read_text()
    for k, v in updates.items():
        pattern = re.compile(rf"^{re.escape(k)}=.*$", re.MULTILINE)
        if pattern.search(text):
            text = pattern.sub(f"{k}={v}", text)
        else:
            text += f"\n{k}={v}\n"
    path.write_text(text)


def load_or_create_entity_secret() -> str:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    if ENTITY_SECRET_FILE.exists():
        hex_str = ENTITY_SECRET_FILE.read_text().strip()
        if len(hex_str) != 64:
            raise SystemExit(
                f"{ENTITY_SECRET_FILE} has wrong length ({len(hex_str)}, want 64)"
            )
        print(f"[entity-secret] reusing {ENTITY_SECRET_FILE}")
        return hex_str
    hex_str = py_secrets.token_bytes(32).hex()
    ENTITY_SECRET_FILE.write_text(hex_str + "\n")
    ENTITY_SECRET_FILE.chmod(0o600)
    print(f"[entity-secret] generated -> {ENTITY_SECRET_FILE}")
    return hex_str


def register_entity_secret(api_key: str, entity_secret_hex: str) -> None:
    RECOVERY_DIR.mkdir(parents=True, exist_ok=True)
    existing = list(RECOVERY_DIR.glob("recovery_file_*"))
    if existing:
        print(f"[register] recovery file already in {RECOVERY_DIR} ({existing[0].name}) — skipping")
        return
    result = utils.register_entity_secret_ciphertext(
        api_key=api_key,
        entity_secret=entity_secret_hex,
        recoveryFileDownloadPath=str(RECOVERY_DIR),
    )
    saved = list(RECOVERY_DIR.glob("recovery_file_*"))
    saved_path = saved[0] if saved else RECOVERY_DIR
    print(f"[register] entity secret registered; recovery file -> {saved_path}")
    if result:
        print(f"[register] SDK returned: {type(result).__name__}")


def build_api_client(api_key: str, entity_secret_hex: str) -> dcw.ApiClient:
    return utils.init_developer_controlled_wallets_client(
        api_key=api_key,
        entity_secret=entity_secret_hex,
    )


def _inner(item):
    return getattr(item, "actual_instance", item)


def get_or_create_wallet_set(api_client: dcw.ApiClient) -> str:
    api = dcw.WalletSetsApi(api_client)
    existing = api.get_wallet_sets()
    sets = [
        _inner(item)
        for item in (existing.data.wallet_sets or [])
        if getattr(_inner(item), "custody_type", "") == "DEVELOPER"
    ]
    if sets:
        chosen = sorted(sets, key=lambda s: s.create_date)[0]
        print(f"[wallet-set] reusing existing developer wallet set {chosen.id}")
        return chosen.id
    req = dcw.CreateWalletSetRequest(
        idempotencyKey=str(uuid.uuid4()),
        entitySecretCiphertext="",
        name=WALLET_SET_NAME,
    )
    resp = api.create_wallet_set(req)
    wallet_set_id = _inner(resp.data.wallet_set).id
    print(f"[wallet-set] created {WALLET_SET_NAME} -> {wallet_set_id}")
    return wallet_set_id


def list_wallets(api_client: dcw.ApiClient, wallet_set_id: str) -> list:
    api = dcw.WalletsApi(api_client)
    resp = api.get_wallets(wallet_set_id=wallet_set_id, page_size=50)
    return [_inner(w) for w in (resp.data.wallets or [])]


def create_wallets(api_client: dcw.ApiClient, wallet_set_id: str) -> list:
    api = dcw.WalletsApi(api_client)
    req = dcw.CreateWalletRequest(
        idempotencyKey=str(uuid.uuid4()),
        entitySecretCiphertext="",
        walletSetId=wallet_set_id,
        blockchains=BLOCKCHAINS,
        accountType=ACCOUNT_TYPE,
        count=len(WALLET_NAMES),
        metadata=[{"name": name} for _, name in WALLET_NAMES],
    )
    resp = api.create_wallet(req)
    return [_inner(w) for w in resp.data.wallets]


def chain_value(w) -> str:
    bc = getattr(w, "blockchain", None)
    return getattr(bc, "value", bc) if bc is not None else ""


def main() -> int:
    if not ENV_FILE.exists():
        raise SystemExit(f"{ENV_FILE} not found")
    env = read_env(ENV_FILE)

    api_key = env.get("CIRCLE_API_KEY", "")
    if not api_key or api_key.count(":") != 2:
        raise SystemExit("CIRCLE_API_KEY missing or malformed in .env (need TEST_API_KEY:<id>:<secret>)")

    entity_secret_hex = load_or_create_entity_secret()
    register_entity_secret(api_key, entity_secret_hex)

    api_client = build_api_client(api_key, entity_secret_hex)

    wallet_set_id = get_or_create_wallet_set(api_client)

    existing = list_wallets(api_client, wallet_set_id)
    expected = len(WALLET_NAMES) * len(BLOCKCHAINS)
    if len(existing) >= expected:
        print(f"[wallets] reusing {len(existing)} existing wallets in set")
        wallets = existing
    else:
        wallets = create_wallets(api_client, wallet_set_id)

    by_name_chain: dict[tuple[str, str], object] = {}
    by_name_addr: dict[str, str] = {}
    for w in wallets:
        wname = getattr(w, "name", None)
        cv = chain_value(w)
        if wname and cv:
            by_name_chain[(wname, cv)] = w
            by_name_addr.setdefault(wname, getattr(w, "address", "") or "")

    env_updates: dict[str, str] = {"CIRCLE_WALLET_SET_ID": wallet_set_id}
    record_lines = [f"walletSetId: {wallet_set_id}"]
    missing: list[str] = []

    for prefix, wallet_name in WALLET_NAMES:
        addr = by_name_addr.get(wallet_name, "")
        env_updates[f"{prefix}_WALLET_ADDR"] = addr
        for chain, suffix in CHAIN_SUFFIX.items():
            w = by_name_chain.get((wallet_name, chain))
            env_key = f"{prefix}_WALLET_ID_{suffix}"
            if w is None:
                missing.append(f"{wallet_name}/{chain}")
                env_updates[env_key] = ""
                continue
            env_updates[env_key] = w.id
            line = f"  {wallet_name:18s} {env_key:25s} id={w.id}  addr={addr}  chain={chain}"
            print(line)
            record_lines.append(line.strip())

    if missing:
        print(f"[warn] missing wallets for: {', '.join(missing)}")

    update_env(ENV_FILE, env_updates)
    WALLET_RECORD_FILE.write_text("\n".join(record_lines) + "\n")
    print(f"\n.env updated. Summary -> {WALLET_RECORD_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
