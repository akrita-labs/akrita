"""Tests for the Circle treasury path (PR 4): USYCReal + GatewayReal.

Three tiers (mirrors test_real_adapters.py):
  - Pure: NAV/APY math, chain mapping, burn-intent shape, and write gates.
    No creds, no network — adapters are built with a fake wallets backbone.
  - Creds-gated: the factory wires USYCReal/GatewayReal into the container
    (needs Circle env).
  - Network-gated: live USYC reads on Arc (NAV/APY/balance) and a live Gateway
    unified-balance read, only when AKRITA_LIVE_TESTS=1.
"""
from __future__ import annotations

import os

import pytest

from shared.config import settings


# --------------------------------------------------------------------------
# Fakes — let the pure tier construct adapters without Circle creds.
# --------------------------------------------------------------------------

class _FakeWallets:
    """Stand-in for CircleWalletsReal exposing only what the adapters touch.

    Records contract executions / EIP-712 signs so write paths can be exercised
    offline. Never makes a network call.
    """

    def __init__(self) -> None:
        self.executions: list[dict] = []
        self.signed: list[dict] = []

    def wallet_id(self, role: str, chain: str = "ARC-TESTNET") -> str:
        return f"wid-{role}-{chain}"

    def wallet_address(self, role: str) -> str:
        return "0x94a13d1b20f0100e62f1361563a36966cc90e269"

    async def execute_contract(self, wallet_id, contract_address, abi_signature,
                               abi_parameters, *, blockchain="ARC-TESTNET", wait=True):
        from adapters.base import TxReceipt
        self.executions.append({
            "wallet_id": wallet_id,
            "contract_address": contract_address,
            "abi_signature": abi_signature,
            "abi_parameters": abi_parameters,
            "blockchain": blockchain,
        })
        return TxReceipt(tx_hash="0xfake", block_number=1, gas_paid_usdc=0.0, status="success")

    async def sign_eip712(self, wallet_id, typed_data) -> str:
        self.signed.append({"wallet_id": wallet_id, "typed_data": typed_data})
        return "0x" + "11" * 65


# --------------------------------------------------------------------------
# Pure — USYCReal math + helpers (no network)
# --------------------------------------------------------------------------

def test_usyc_constants_match_bootstrap():
    """Addresses/decimals must match the working bootstrap script."""
    from adapters.real import usyc

    assert usyc.USYC_TELLER_ADDR == "0x9fdF14c5B14173D74C08Af27AebFf39240dC105A"
    assert usyc.USYC_ADDR == "0xe9185F0c5F296Ed1797AaE4238D26CCaBEadb86C"
    assert usyc.USDC_ADDR == "0x3600000000000000000000000000000000000000"
    assert usyc.USYC_DECIMALS == 6 and usyc.USDC_DECIMALS == 6


async def test_usyc_nav_from_convert_to_assets(monkeypatch):
    """get_nav_per_share divides convertToAssets(1 share) by 1e6."""
    from adapters.real.usyc import USYCReal

    usyc = USYCReal(_FakeWallets())

    class _Fn:
        def __init__(self, val): self._val = val
        def call(self):
            async def _c(): return self._val
            return _c()

    class _Funcs:
        def convertToAssets(self, shares):
            assert shares == 10**6
            return _Fn(1_116_277)  # 1.116277 USDC/share, as read live on Arc

    monkeypatch.setattr(usyc._teller, "functions", _Funcs())
    nav = await usyc.get_nav_per_share()
    assert nav == pytest.approx(1.116277, abs=1e-9)


async def test_usyc_apy_annualizes_oracle_growth(monkeypatch):
    """APY compounds the NAV growth between two oracle rounds."""
    from adapters.real.usyc import USYCReal

    usyc = USYCReal(_FakeWallets())

    # Two rounds 30 days apart with ~0.26% growth -> ~3.2% APY.
    base_ts = 1_770_000_000
    latest = (54, 1_116_277_611_710_661_200, base_ts, base_ts + 30 * 86400, 54)
    prior = (24, 1_114_015_490_000_000_000, base_ts - 1, base_ts, 24)

    class _RoundFn:
        def __init__(self, val): self._val = val
        def call(self):
            async def _c(): return self._val
            return _c()

    class _OracleFuncs:
        def latestRoundData(self): return _RoundFn(latest)
        def getRoundData(self, rid):
            assert rid == 54 - 30
            return _RoundFn(prior)

    class _Oracle:
        functions = _OracleFuncs()

    async def _fake_oracle(): return _Oracle()
    monkeypatch.setattr(usyc, "_oracle", _fake_oracle)

    apy = await usyc.get_current_yield_apy()
    assert 0.02 < apy < 0.05  # short-Treasury band; ~3.2%


async def test_usyc_apy_falls_back_when_no_history(monkeypatch):
    """With no usable prior round, APY returns the documented fallback."""
    from adapters.real import usyc as usyc_mod
    from adapters.real.usyc import USYCReal

    usyc = USYCReal(_FakeWallets())

    class _RoundFn:
        def __init__(self, val): self._val = val
        def call(self):
            async def _c(): return self._val
            return _c()

    class _OracleFuncs:
        def latestRoundData(self):
            return _RoundFn((1, 1_116_000_000_000_000_000, 1, 1_770_000_000, 1))
        def getRoundData(self, rid):
            raise RuntimeError("no such round")

    class _Oracle:
        functions = _OracleFuncs()

    async def _fake_oracle(): return _Oracle()
    monkeypatch.setattr(usyc, "_oracle", _fake_oracle)

    apy = await usyc.get_current_yield_apy()
    assert apy == usyc_mod._FALLBACK_APY


async def test_usyc_subscribe_gated_when_not_allowlisted(monkeypatch):
    """subscribe must refuse clearly when the Teller role isn't granted,
    regardless of the ambient .env value."""
    from adapters.real.usyc import USYCReal

    monkeypatch.setattr(settings, "usyc_wallet_allowlisted", False)
    usyc = USYCReal(_FakeWallets())
    with pytest.raises(RuntimeError, match="NotPermissioned|allowlisted|Teller"):
        await usyc.subscribe("wid", 5.0)


async def test_usyc_redeem_gated_when_not_allowlisted(monkeypatch):
    from adapters.real.usyc import USYCReal

    monkeypatch.setattr(settings, "usyc_wallet_allowlisted", False)
    usyc = USYCReal(_FakeWallets())
    with pytest.raises(RuntimeError, match="NotPermissioned|allowlisted|Teller"):
        await usyc.redeem("wid", 5.0)


async def test_usyc_subscribe_builds_approve_then_deposit(monkeypatch):
    """When allowlisted, subscribe issues approve(Teller) then deposit(amount,
    receiver) through the keeper wallet, and reports USYC out via NAV."""
    from adapters.real import usyc as usyc_mod
    from adapters.real.usyc import USYCReal

    monkeypatch.setattr(settings, "usyc_wallet_allowlisted", True)
    wallets = _FakeWallets()
    usyc = USYCReal(wallets)

    async def _nav(): return 1.116277
    monkeypatch.setattr(usyc, "get_nav_per_share", _nav)

    receipt = await usyc.subscribe("wid-treasury", 5.0)

    assert len(wallets.executions) == 2
    approve, deposit = wallets.executions
    assert approve["contract_address"] == usyc_mod.USDC_ADDR
    assert approve["abi_signature"] == "approve(address,uint256)"
    assert approve["abi_parameters"] == [usyc_mod.USYC_TELLER_ADDR, str(5_000_000)]
    assert deposit["contract_address"] == usyc_mod.USYC_TELLER_ADDR
    assert deposit["abi_signature"] == "deposit(uint256,address)"
    assert deposit["abi_parameters"][0] == str(5_000_000)
    assert receipt.usdc_in == 5.0
    assert receipt.usyc_out == pytest.approx(5.0 / 1.116277, rel=1e-9)
    assert receipt.nav == pytest.approx(1.116277)


async def test_usyc_redeem_builds_redeem_call(monkeypatch):
    from adapters.real import usyc as usyc_mod
    from adapters.real.usyc import USYCReal

    monkeypatch.setattr(settings, "usyc_wallet_allowlisted", True)
    wallets = _FakeWallets()
    usyc = USYCReal(wallets)

    async def _nav(): return 1.116277
    monkeypatch.setattr(usyc, "get_nav_per_share", _nav)

    receipt = await usyc.redeem("wid-treasury", 2.0)
    assert len(wallets.executions) == 1
    call = wallets.executions[0]
    assert call["contract_address"] == usyc_mod.USYC_TELLER_ADDR
    assert call["abi_signature"] == "redeem(uint256,address,address)"
    assert call["abi_parameters"][0] == str(2_000_000)
    # receiver == owner == treasury address
    assert call["abi_parameters"][1] == call["abi_parameters"][2]
    assert receipt.usyc_in == 2.0
    assert receipt.usdc_out == pytest.approx(2.0 * 1.116277)


async def test_usyc_subscribe_rejects_nonpositive(monkeypatch):
    from adapters.real.usyc import USYCReal

    monkeypatch.setattr(settings, "usyc_wallet_allowlisted", True)
    usyc = USYCReal(_FakeWallets())

    async def _nav(): return 1.1
    monkeypatch.setattr(usyc, "get_nav_per_share", _nav)
    with pytest.raises(ValueError):
        await usyc.subscribe("wid", 0.0)


# --------------------------------------------------------------------------
# Pure — GatewayReal mapping + burn-intent shape + transfer gate
# --------------------------------------------------------------------------

def test_gateway_constants_and_domains():
    from adapters.real import gateway as gw

    assert gw.GATEWAY_WALLET_ADDR == "0x0077777d7EBA4688BDeF3E311b846F25870A19B9"
    assert gw.GATEWAY_MINTER_ADDR == "0x0022222ABE238Cc2C7Bb1f21003F0a260052475B"
    assert gw._CHAIN_META["arc"]["domain"] == 26
    assert gw._CHAIN_META["polygon"]["domain"] == 7
    assert gw._CHAIN_META["base"]["domain"] == 6


def test_gateway_chain_aliases():
    from adapters.real.gateway import _chain

    assert _chain("arc")["domain"] == 26
    assert _chain("ARC-TESTNET")["domain"] == 26
    assert _chain("polygon")["domain"] == 7
    assert _chain("MATIC-AMOY")["domain"] == 7
    with pytest.raises(ValueError):
        _chain("dogecoin")


def test_gateway_addr_to_bytes32():
    from adapters.real.gateway import _addr_to_bytes32

    out = _addr_to_bytes32("0x3600000000000000000000000000000000000000")
    assert out == "0x" + "0" * 24 + "3600000000000000000000000000000000000000"
    assert len(out) == 66


async def test_gateway_transfer_gated_when_unfunded(monkeypatch):
    """transfer must refuse clearly when the source unified balance is below
    the amount (Gateway burns from deposited balance, not yet seeded)."""
    from adapters.real.gateway import GatewayReal

    gw = GatewayReal(_FakeWallets())

    async def _zero(wallet_id, chain): return 0.0
    monkeypatch.setattr(gw, "get_domain_balance", _zero)

    with pytest.raises(RuntimeError, match="not provisioned|deposit"):
        await gw.transfer("wid", 10.0, "arc", "polygon")


async def test_gateway_transfer_rejects_nonpositive():
    from adapters.real.gateway import GatewayReal

    gw = GatewayReal(_FakeWallets())
    with pytest.raises(ValueError):
        await gw.transfer("wid", 0.0, "arc", "polygon")


async def test_gateway_transfer_signs_correct_burn_intent(monkeypatch):
    """When funded, transfer builds a spec with the right domains/addresses and
    signs it via the keeper wallet (no real network: we stub balance + API)."""
    import httpx

    from adapters.real import gateway as gw_mod
    from adapters.real.gateway import GatewayReal

    wallets = _FakeWallets()
    gw = GatewayReal(wallets)

    async def _funded(wallet_id, chain): return 100.0
    monkeypatch.setattr(gw, "get_domain_balance", _funded)

    captured: dict = {}

    class _Resp:
        status_code = 200
        text = ""
        def json(self):
            return {"attestation": "0xabc", "signature": "0xdef", "transferId": "0xburn"}
        def raise_for_status(self): ...

    class _FakeClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["body"] = json
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    receipt = await gw.transfer("wid-treasury", 5.0, "arc", "polygon")

    # Signed exactly one burn intent.
    assert len(wallets.signed) == 1
    spec = wallets.signed[0]["typed_data"]["message"]["spec"]
    assert spec["sourceDomain"] == 26 and spec["destinationDomain"] == 7
    assert spec["value"] == str(5_000_000)
    assert spec["sourceContract"] == gw_mod._addr_to_bytes32(gw_mod.GATEWAY_WALLET_ADDR)
    assert spec["destinationContract"] == gw_mod._addr_to_bytes32(gw_mod.GATEWAY_MINTER_ADDR)
    # POSTed to /transfer with the signed intent.
    assert captured["url"].endswith("/transfer")
    assert captured["body"][0]["signature"] == "0x" + "11" * 65
    # Minted on the destination chain via gatewayMint.
    mint = wallets.executions[-1]
    assert mint["abi_signature"] == "gatewayMint(bytes,bytes)"
    assert mint["abi_parameters"] == ["0xabc", "0xdef"]
    assert mint["blockchain"] == "MATIC-AMOY"
    assert receipt.amount_usdc == 5.0
    assert receipt.dst_tx == "0xfake"


# --------------------------------------------------------------------------
# Creds-gated — factory wires the treasury adapters
# --------------------------------------------------------------------------

_HAS_CIRCLE = bool(settings.circle_api_key and settings.circle_api_key.count(":") == 2)


@pytest.mark.skipif(not _HAS_CIRCLE, reason="needs CIRCLE_API_KEY")
def test_factory_wires_usyc_and_gateway():
    from adapters import get_adapters, reset_for_tests

    reset_for_tests()
    a = get_adapters()
    assert a.usyc is not None and a.gateway is not None
    reset_for_tests()


# --------------------------------------------------------------------------
# Network-gated — live USYC reads on Arc + live Gateway balance read
# --------------------------------------------------------------------------

_LIVE = os.environ.get("AKRITA_LIVE_TESTS") == "1"


@pytest.mark.skipif(not (_LIVE and _HAS_CIRCLE), reason="set AKRITA_LIVE_TESTS=1 + Circle creds")
async def test_usyc_reads_live():
    """USYC NAV/APY/balance read live from the Arc Teller, oracle, and token."""
    from adapters.real.circle_wallets import CircleWalletsReal
    from adapters.real.usyc import USYCReal

    usyc = USYCReal(CircleWalletsReal())

    nav = await usyc.get_nav_per_share()
    # USYC accrues; NAV is comfortably above par and below an absurd ceiling.
    assert 1.0 < nav < 2.0, f"unexpected NAV {nav}"

    apy = await usyc.get_current_yield_apy()
    assert 0.0 <= apy < 0.20, f"unexpected APY {apy}"

    bal = await usyc.get_balance(usyc._treasury_wallet_id())
    assert bal >= 0.0


@pytest.mark.skipif(not (_LIVE and _HAS_CIRCLE), reason="set AKRITA_LIVE_TESTS=1 + Circle creds")
async def test_gateway_unified_balance_live():
    """Gateway /balances responds live; treasury balance is a non-negative
    float (0 until USDC is deposited into the Gateway Wallet)."""
    from adapters.real.circle_wallets import CircleWalletsReal
    from adapters.real.gateway import GatewayReal

    gw = GatewayReal(CircleWalletsReal())
    bal = await gw.get_unified_balance(gw._wallets.wallet_id("treasury", "ARC-TESTNET"))
    assert isinstance(bal, float) and bal >= 0.0


@pytest.mark.skipif(not (_LIVE and _HAS_CIRCLE), reason="set AKRITA_LIVE_TESTS=1 + Circle creds")
async def test_gateway_transfer_gated_live():
    """Live: with no Gateway deposits, transfer refuses with a provisioning
    error rather than attempting an unfunded burn."""
    from adapters.real.circle_wallets import CircleWalletsReal
    from adapters.real.gateway import GatewayReal

    gw = GatewayReal(CircleWalletsReal())
    with pytest.raises(RuntimeError, match="not provisioned|deposit"):
        await gw.transfer(gw._wallets.wallet_id("treasury", "ARC-TESTNET"), 1.0, "arc", "polygon")
