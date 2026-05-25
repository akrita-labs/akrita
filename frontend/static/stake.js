// AKRITA Rugpull Oracle — permissionless bond staking from any wallet.
// Lets an external participant (not the AKRITA keeper) back or fade a rug-risk
// claim with real USDC on Arc: connect wallet → ensure Arc testnet → approve the
// bond token → ClaimRegistry.stake(claimId, backsClaim, amount). Winners withdraw
// stake + a pro-rata share of the losing pool; the losing side is slashed.
//
// Needs window.ethereum (MetaMask / any EIP-1193 wallet) + ethers v6 (loaded via
// CDN in oracle.html). Public on-chain constants only — no secrets here.
(function () {
    "use strict";

    // Arc testnet + deployed ClaimRegistry (immutable) + bond token (USDC on Arc).
    var ARC = {
        chainIdNum: 5042002,
        chainIdHex: "0x4cefb2",
        rpc: "https://rpc.testnet.arc.network",
        explorer: "https://testnet.arcscan.app",
        name: "Arc Testnet",
        currency: { name: "USDC", symbol: "USDC", decimals: 18 },
    };
    var CLAIM_REGISTRY = "0x16aD24beEBa619f7b8C2fcFDa1F1ec1f6210F405";
    var BOND_TOKEN = "0x3600000000000000000000000000000000000000"; // USDC on Arc
    var USDC_DECIMALS = 6;

    var ERC20_ABI = ["function approve(address spender, uint256 amount) returns (bool)"];
    var REGISTRY_ABI = ["function stake(uint256 claimId, bool backsClaim, uint256 amount)"];

    function hasWallet() { return typeof window.ethereum !== "undefined"; }
    function hasEthers() { return typeof window.ethers !== "undefined"; }

    async function ensureArc(eth) {
        try {
            await eth.request({ method: "wallet_switchEthereumChain", params: [{ chainId: ARC.chainIdHex }] });
        } catch (e) {
            if (e && e.code === 4902) {
                await eth.request({
                    method: "wallet_addEthereumChain",
                    params: [{
                        chainId: ARC.chainIdHex,
                        chainName: ARC.name,
                        rpcUrls: [ARC.rpc],
                        nativeCurrency: ARC.currency,
                        blockExplorerUrls: [ARC.explorer],
                    }],
                });
            } else {
                throw e;
            }
        }
    }

    function setStatus(row, text, kind) {
        var el = row.querySelector(".oc-stake-status");
        if (el) { el.textContent = text; el.className = "oc-stake-status" + (kind ? " is-" + kind : ""); }
    }

    async function doStake(row, side) {
        if (!hasWallet()) return setStatus(row, "No wallet found — install MetaMask.", "err");
        if (!hasEthers()) return setStatus(row, "Staking library still loading…", "err");
        var claimId = row.getAttribute("data-claim-id");
        var amtEl = row.querySelector(".oc-stake-amt");
        var amt = parseFloat(amtEl && amtEl.value);
        if (!(amt > 0)) return setStatus(row, "Enter a USDC amount.", "err");
        var backs = side === "back";
        var units = window.ethers.parseUnits(String(amt), USDC_DECIMALS);

        try {
            setStatus(row, "Connecting wallet…", "pend");
            await window.ethereum.request({ method: "eth_requestAccounts" });
            await ensureArc(window.ethereum);
            var provider = new window.ethers.BrowserProvider(window.ethereum);
            var signer = await provider.getSigner();

            setStatus(row, "Approving " + amt + " USDC…", "pend");
            var token = new window.ethers.Contract(BOND_TOKEN, ERC20_ABI, signer);
            var aTx = await token.approve(CLAIM_REGISTRY, units);
            await aTx.wait();

            setStatus(row, "Staking " + (backs ? "FOR (rugs)" : "AGAINST (safe)") + "…", "pend");
            var registry = new window.ethers.Contract(CLAIM_REGISTRY, REGISTRY_ABI, signer);
            var sTx = await registry.stake(claimId, backs, units);
            await sTx.wait();

            var link = ARC.explorer + "/tx/" + sTx.hash;
            setStatus(row, "", "ok");
            var st = row.querySelector(".oc-stake-status");
            if (st) st.innerHTML = '✓ staked · <a href="' + link + '" target="_blank" rel="noopener">view tx ↗</a>';
            if (window.AKRITA && window.AKRITA.reloadOracle) setTimeout(window.AKRITA.reloadOracle, 4000);
        } catch (e) {
            var msg = (e && (e.shortMessage || e.message)) || "stake failed";
            setStatus(row, msg.slice(0, 90), "err");
        }
    }

    document.addEventListener("click", function (ev) {
        var btn = ev.target.closest && ev.target.closest(".oc-stake button[data-side]");
        if (!btn) return;
        var row = btn.closest(".oc-stake");
        if (row) doStake(row, btn.getAttribute("data-side"));
    });
})();
