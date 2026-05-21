"""
USYCReal — Circle / Hashnote USYC tokenized money-market fund on Arc.

Split signing model (mirrors ArcReal):
  - READS  (NAV, APY, USYC balance) go directly to the Arc JSON-RPC via
    web3.py against the USYC Teller, its price oracle, and the USYC token.
    No signing, no Circle round-trip.
  - WRITES (subscribe = deposit USDC -> USYC, redeem = burn USYC -> USDC)
    are signed by the Circle MPC treasury-keeper wallet through
    CircleWalletsReal.execute_contract. The Teller is a Hashnote ERC-4626
    vault:
      deposit(uint256 assets, address receiver) -> shares   (subscribe)
      redeem(uint256 shares, address receiver, address owner) -> assets (redeem)

  Write gating (external Circle dependency):
    The treasury wallet is allowlisted on the USYC *token* but the live
    blocker is the Teller's RolesAuthority: until Circle grants the keeper
    the investor role, `deposit()`/`redeem()` revert `NotPermissioned()`.
    `scripts/bootstrap/usyc_check_permission.py` verifies the on-chain
    grant. We refuse early with an actionable error when
    `settings.usyc_wallet_allowlisted` is False; once True we attempt the
    call (it may still revert NotPermissioned until Circle finishes the
    grant — that is expected and surfaces as a Circle tx failure).

NAV: ERC-4626 `convertToAssets(1e6)` on the Teller is the canonical
price-per-share (USYC and USDC are both 6-decimals on Arc). The Teller's
Chainlink-style USYC/USD oracle (`Teller.oracle()`, 18-decimals) is the
same value and is used to derive a live APY from the round-over-round NAV
growth.
"""
from __future__ import annotations

from web3 import AsyncHTTPProvider, AsyncWeb3

from adapters.base import RedeemReceipt, SubscribeReceipt
from adapters.real.circle_wallets import CircleWalletsReal
from shared.config import settings


# Arc testnet constants — verified against docs.arc.io/arc/references/contract-addresses
# and scripts/bootstrap/usyc_subscribe.py.
USDC_ADDR = "0x3600000000000000000000000000000000000000"
USYC_ADDR = "0xe9185F0c5F296Ed1797AaE4238D26CCaBEadb86C"
USYC_TELLER_ADDR = "0x9fdF14c5B14173D74C08Af27AebFf39240dC105A"
USDC_DECIMALS = 6
USYC_DECIMALS = 6
_ONE_SHARE = 10**USYC_DECIMALS  # 1.0 USYC in base units

# Fallback USYC/USD price-oracle (Teller.oracle()); read live at call time but
# pinned here for documentation / resilience if the Teller view ever changes.
USYC_ORACLE_ADDR = "0x52b56c7642e71dc54714d879127d97cd0b3d4581"

# Conservative fallback APY (short-dated Treasuries) if the oracle has no usable
# history to annualize. The live oracle currently yields ~3.2%.
_FALLBACK_APY = 0.032
# How many oracle rounds to look back when annualizing NAV growth. The USYC/USD
# feed updates roughly daily; ~30 rounds gives a smooth multi-week estimate.
_APY_LOOKBACK_ROUNDS = 30


# Minimal ABI fragments — only what USYCReal reads on Teller / oracle / token.
_TELLER_ABI = [
    {
        "type": "function",
        "name": "convertToAssets",
        "stateMutability": "view",
        "inputs": [{"name": "shares", "type": "uint256"}],
        "outputs": [{"name": "assets", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "convertToShares",
        "stateMutability": "view",
        "inputs": [{"name": "assets", "type": "uint256"}],
        "outputs": [{"name": "shares", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "totalAssets",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "oracle",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "address"}],
    },
]

# Chainlink AggregatorV3 surface exposed by the USYC/USD oracle.
_ORACLE_ABI = [
    {
        "type": "function",
        "name": "decimals",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint8"}],
    },
    {
        "type": "function",
        "name": "latestRoundData",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [
            {"name": "roundId", "type": "uint80"},
            {"name": "answer", "type": "int256"},
            {"name": "startedAt", "type": "uint256"},
            {"name": "updatedAt", "type": "uint256"},
            {"name": "answeredInRound", "type": "uint80"},
        ],
    },
    {
        "type": "function",
        "name": "getRoundData",
        "stateMutability": "view",
        "inputs": [{"name": "roundId", "type": "uint80"}],
        "outputs": [
            {"name": "roundId", "type": "uint80"},
            {"name": "answer", "type": "int256"},
            {"name": "startedAt", "type": "uint256"},
            {"name": "updatedAt", "type": "uint256"},
            {"name": "answeredInRound", "type": "uint80"},
        ],
    },
]

_ERC20_ABI = [
    {
        "type": "function",
        "name": "balanceOf",
        "stateMutability": "view",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "decimals",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint8"}],
    },
]


class USYCReal:
    def __init__(self, wallets: CircleWalletsReal) -> None:
        self._wallets = wallets
        self._w3 = AsyncWeb3(AsyncHTTPProvider(settings.arc_rpc_url))
        self._teller = self._w3.eth.contract(
            address=AsyncWeb3.to_checksum_address(USYC_TELLER_ADDR), abi=_TELLER_ABI
        )
        self._usyc = self._w3.eth.contract(
            address=AsyncWeb3.to_checksum_address(USYC_ADDR), abi=_ERC20_ABI
        )
        self._usdc = self._w3.eth.contract(
            address=AsyncWeb3.to_checksum_address(USDC_ADDR), abi=_ERC20_ABI
        )

    # ----- helpers ---------------------------------------------------------

    def _treasury_wallet_id(self) -> str:
        """Circle wallet id of the keeper that signs Teller writes.

        USYC writes always come from the treasury (AGROS) keeper on Arc.
        We accept the configured id directly, but fall back to resolving the
        treasury wallet so callers may pass either the wallet id or omit it.
        """
        return self._wallets.wallet_id("treasury", "ARC-TESTNET")

    async def _oracle(self):
        """Resolve the USYC/USD oracle from the Teller at call time (with a
        pinned fallback if the Teller view is unavailable)."""
        try:
            addr = await self._teller.functions.oracle().call()
        except Exception:
            addr = USYC_ORACLE_ADDR
        return self._w3.eth.contract(
            address=AsyncWeb3.to_checksum_address(addr), abi=_ORACLE_ABI
        )

    # ----- reads -----------------------------------------------------------

    async def get_nav_per_share(self) -> float:
        """USYC net asset value in USDC per 1.0 USYC share.

        ERC-4626 `convertToAssets(1 share)` is the canonical price-per-share;
        USYC and USDC are both 6-decimals on Arc so the ratio is direct.
        """
        assets = int(await self._teller.functions.convertToAssets(_ONE_SHARE).call())
        return assets / 10**USDC_DECIMALS

    async def get_current_yield_apy(self) -> float:
        """Annualized USYC yield, derived live from the USYC/USD price oracle.

        USYC has no on-chain APY scalar; its yield is the rate at which NAV
        accrues. We read the latest oracle round and a prior round, then
        compound the price growth to a 365-day APY. Falls back to a
        documented short-Treasury constant if no usable history exists.
        """
        oracle = await self._oracle()
        try:
            latest = await oracle.functions.latestRoundData().call()
            latest_round = int(latest[0])
            latest_answer = int(latest[1])
            latest_ts = int(latest[3])
        except Exception:
            return _FALLBACK_APY
        if latest_answer <= 0 or latest_ts <= 0 or latest_round <= 1:
            return _FALLBACK_APY

        # Walk back to find a populated historical round to annualize against.
        for back in (_APY_LOOKBACK_ROUNDS, 10, 5, 2, 1):
            prior_round = latest_round - back
            if prior_round <= 0:
                continue
            try:
                prior = await oracle.functions.getRoundData(prior_round).call()
            except Exception:
                continue
            prior_answer = int(prior[1])
            prior_ts = int(prior[3])
            if prior_answer <= 0 or prior_ts <= 0 or prior_ts >= latest_ts:
                continue
            dt_days = (latest_ts - prior_ts) / 86400.0
            if dt_days <= 0:
                continue
            growth = latest_answer / prior_answer
            try:
                return growth ** (365.0 / dt_days) - 1.0
            except (OverflowError, ValueError):
                return _FALLBACK_APY
        return _FALLBACK_APY

    async def get_balance(self, wallet_id: str) -> float:
        """USYC balance (human units) of the holder behind `wallet_id`.

        `wallet_id` is the Circle wallet id; we resolve its on-chain address
        and read `balanceOf` on the USYC token directly from Arc. The treasury
        keeper is the only USYC holder today, so we map through its configured
        address; an unknown id falls back to the treasury address used by the
        subscribe/redeem path.
        """
        holder = self._holder_address(wallet_id)
        raw = int(await self._usyc.functions.balanceOf(
            AsyncWeb3.to_checksum_address(holder)
        ).call())
        return raw / 10**USYC_DECIMALS

    def _holder_address(self, wallet_id: str) -> str:
        """Map a Circle wallet id to its on-chain address.

        The keeper wallet ids and addresses are configured in pairs; for the
        treasury (the USYC holder) we already know the address. If the id is
        the configured treasury id we use the treasury address, otherwise we
        fall back to the treasury address (the only USYC-bearing wallet).
        """
        if wallet_id and wallet_id == settings.treasury_wallet_id_arc:
            return settings.treasury_wallet_addr
        # Default to the treasury address: USYC only ever sits in the treasury.
        return settings.treasury_wallet_addr or self._wallets.wallet_address("treasury")

    # ----- writes (via Circle treasury-keeper, gated on Teller role) -------

    def _require_writes_ready(self) -> None:
        if not settings.usyc_wallet_allowlisted:
            raise RuntimeError(
                "USYC writes blocked: treasury wallet is not yet allowlisted / "
                "granted the USYC Teller RolesAuthority investor role, so "
                "deposit()/redeem() revert NotPermissioned(). This is an "
                "external Circle Support dependency. Verify the grant with "
                "scripts/bootstrap/usyc_check_permission.py, then set "
                "USYC_WALLET_ALLOWLISTED=true. See scripts/bootstrap/usyc_subscribe.py."
            )

    async def subscribe(self, wallet_id: str, amount_usdc: float) -> SubscribeReceipt:
        """Subscribe USDC into USYC via the Teller (ERC-4626 deposit).

        Two signed steps through the Circle treasury-keeper wallet:
          1. USDC.approve(Teller, amount)
          2. Teller.deposit(amount, treasury_addr)  -> USYC shares minted

        Returns a SubscribeReceipt with the USYC minted implied by the NAV at
        execution time. NOTE: until Circle grants the Teller role, step 2
        reverts NotPermissioned() and surfaces as a Circle tx failure.
        """
        self._require_writes_ready()
        wid = wallet_id or self._treasury_wallet_id()
        receiver = self._holder_address(wid)
        amount_units = int(round(amount_usdc * 10**USDC_DECIMALS))
        if amount_units <= 0:
            raise ValueError(f"subscribe amount must be positive, got {amount_usdc}")

        nav = await self.get_nav_per_share()

        # 1) Approve the Teller to pull USDC.
        await self._wallets.execute_contract(
            wallet_id=wid,
            contract_address=USDC_ADDR,
            abi_signature="approve(address,uint256)",
            abi_parameters=[USYC_TELLER_ADDR, str(amount_units)],
            blockchain="ARC-TESTNET",
        )
        # 2) Deposit USDC -> USYC shares.
        receipt = await self._wallets.execute_contract(
            wallet_id=wid,
            contract_address=USYC_TELLER_ADDR,
            abi_signature="deposit(uint256,address)",
            abi_parameters=[str(amount_units), receiver],
            blockchain="ARC-TESTNET",
        )
        usyc_out = amount_usdc / nav if nav > 0 else 0.0
        return SubscribeReceipt(
            usdc_in=amount_usdc,
            usyc_out=usyc_out,
            nav=nav,
            tx_hash=receipt.tx_hash,
        )

    async def redeem(self, wallet_id: str, amount_usyc: float) -> RedeemReceipt:
        """Redeem USYC back to USDC via the Teller (ERC-4626 redeem).

        Signed by the Circle treasury-keeper wallet:
          Teller.redeem(shares, receiver, owner)  -> USDC returned

        The keeper is both receiver and owner. Returns a RedeemReceipt with
        the USDC out implied by the NAV at execution time (fee=0; the Teller
        applies any spread inside the conversion). Gated identically to
        subscribe — reverts NotPermissioned() until Circle completes the grant.
        """
        self._require_writes_ready()
        wid = wallet_id or self._treasury_wallet_id()
        owner = self._holder_address(wid)
        shares_units = int(round(amount_usyc * 10**USYC_DECIMALS))
        if shares_units <= 0:
            raise ValueError(f"redeem amount must be positive, got {amount_usyc}")

        nav = await self.get_nav_per_share()

        receipt = await self._wallets.execute_contract(
            wallet_id=wid,
            contract_address=USYC_TELLER_ADDR,
            abi_signature="redeem(uint256,address,address)",
            abi_parameters=[str(shares_units), owner, owner],
            blockchain="ARC-TESTNET",
        )
        usdc_out = amount_usyc * nav
        return RedeemReceipt(
            usyc_in=amount_usyc,
            usdc_out=usdc_out,
            fee=0.0,
            tx_hash=receipt.tx_hash,
        )
