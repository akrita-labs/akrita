// AKRITA Rugpull Oracle — live claim feed.
// Reads GET /api/claims (on-chain claims) and enriches each with its IPFS trace
// body to show the human-readable attestation (e.g. "USDT froze 0x… — illicit")
// plus a verifiable Etherscan link to the actual freeze tx. No mock data; honest
// "not live yet" until ClaimRegistry is deployed.
(function () {
    "use strict";
    var API = window.location.origin;
    var REFRESH_MS = 20000;
    var IPFS_GATEWAYS = ["https://ipfs.io/ipfs/", "https://cloudflare-ipfs.com/ipfs/"];

    function $(id) { return document.getElementById(id); }
    function esc(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
        });
    }
    function shortHex(h) {
        h = String(h || "");
        return h.length > 14 ? h.slice(0, 10) + "…" + h.slice(-6) : (h || "—");
    }
    function setStatus(text, cls) {
        var el = $("oracle-status");
        if (el) { el.textContent = text; el.className = "ak-pill " + (cls || "ak-pill-gated"); }
    }

    async function fetchTrace(cid) {
        if (!cid) return null;
        for (var i = 0; i < IPFS_GATEWAYS.length; i++) {
            try {
                var ctrl = new AbortController();
                var t = setTimeout(function () { ctrl.abort(); }, 6000);
                var r = await fetch(IPFS_GATEWAYS[i] + cid, { signal: ctrl.signal });
                clearTimeout(t);
                if (r.ok) return await r.json();
            } catch (e) { /* try next gateway */ }
        }
        return null;
    }

    function statusPill(status) {
        var s = String(status || "open").toLowerCase();
        var cls = s === "rugged" ? "ak-pill-live" : s === "safe" ? "ak-pill-demo" : "ak-pill-gated";
        var label = s === "rugged" ? "RUGGED" : s === "safe" ? "HELD" : "OPEN";
        return '<span class="ak-pill ' + cls + '">' + label + "</span>";
    }

    function fmtConf(v) { return v == null ? null : Math.round(Number(v) * 100) + "%"; }

    function sevTag(sev) {
        sev = String(sev || "").toLowerCase();
        if (!sev) return "";
        return '<span class="oc-sev oc-sev-' + esc(sev) + '">' + esc(sev) + "</span>";
    }

    // The agent's actual reasoning — model byline + confidence + the rationale that
    // was hashed into the on-chain trace. This is the "the AI decided" evidence.
    function reasoningBlock(body, agentLabel) {
        var r = body.reasoning || {};
        var c = body.conclusion || {};
        var rationale = c.rationale || r.rationale;
        if (!rationale && !r.model) return "";
        var conf = fmtConf(c.confidence != null ? c.confidence : r.confidence);
        var decided = String(r.decided_by || "").indexOf("reasoner") === 0;
        var bits = ["<b>" + esc(agentLabel) + "</b>"];
        if (r.model) bits.push(esc(r.model));
        if (conf) bits.push("conf " + conf);
        if (r.latency_ms) bits.push((r.latency_ms / 1000).toFixed(1) + "s");
        return '<div class="oc-reasoning">' +
            (rationale ? '<div class="oc-rationale">“' + esc(rationale) + '”</div>' : "") +
            '<div class="oc-byline">' + (decided ? "🧠 " : "⚙ ") + bits.join(" · ") + "</div>" +
            "</div>";
    }

    // SPATHA's independent second opinion (its own on-chain trace, agent 2).
    function spathaBlock(c) {
        var s = c._spatha;
        if (!s) return "";
        var con = s.conclusion || {}, r = s.reasoning || {}, t = s.technical || {};
        var pos = String(t.position || con.position || "").toLowerCase();
        if (!pos) return "";
        var conf = fmtConf(r.conviction);
        var label = pos === "back" ? "backs the rug call" : pos === "fade" ? "fades it" : "abstained";
        var exec = String(t.execution || "");
        var amt = con.amount_usdc != null ? con.amount_usdc : t.amount_usdc;
        var execTag = exec === "staked"
            ? '<span class="oc-exec staked">staked $' + esc(amt) + "</span>"
            : exec.indexOf("gated") === 0
                ? '<span class="oc-exec gated">stake gated on funding</span>'
                : "";
        var sLink = c.spatha && c.spatha.trace_hash
            ? ' <a href="/app/trace?hash=' + esc(c.spatha.trace_hash) +
              "&cid=" + esc(c.spatha.ipfs_cid) + '">SPATHA trace ↗</a>'
            : "";
        return '<div class="oc-spatha"><span class="oc-spatha-tag">SPATHA</span> ' +
            esc(label) + (conf ? " (" + conf + ")" : "") + " " + execTag +
            (r.rationale ? '<div class="oc-rationale">“' + esc(r.rationale) + '”</div>' : "") +
            sLink +
            "</div>";
    }

    // Permissionless participation: any wallet can back/fade an open predictive
    // claim. Handlers live in stake.js (wallet connect + Arc + approve + stake).
    function stakeControls(c) {
        if (c.status !== "open") return "";
        return '<div class="oc-stake" data-claim-id="' + esc(c.claim_id) + '">' +
            '<span class="oc-stake-label">Take a side:</span>' +
            '<input class="oc-stake-amt" type="number" min="0.1" step="0.1" value="1.0" aria-label="USDC amount" />' +
            '<button class="oc-stake-btn oc-stake-back" data-side="back" type="button">Back · rugs</button>' +
            '<button class="oc-stake-btn oc-stake-fade" data-side="fade" type="button">Fade · safe</button>' +
            '<span class="oc-stake-status" role="status"></span>' +
            "</div>";
    }

    function renderClaim(c) {
        var body = c._trace || {};
        var dtype = body.decision_type;
        var traceLink = c.trace_hash
            ? '<a href="/app/trace?hash=' + esc(c.trace_hash) +
              (c.ipfs_cid ? "&cid=" + esc(c.ipfs_cid) : "") + '">trace ' + esc(shortHex(c.trace_hash)) + "</a>"
            : "";

        if (dtype === "freeze_attestation") {
            var f = body.fundamentals || {}, tech = body.technical || {}, con = body.conclusion || {};
            var issuer = tech.issuer || "stablecoin";
            var addr = f.frozen_address || "—";
            var src = (f.source || {}).freeze_tx || c.source_commit;
            var etherscan = src ? '<a href="https://etherscan.io/tx/' + esc(src) + '" target="_blank" rel="noopener">verify freeze on Ethereum ↗</a>' : "";
            return (
                '<article class="oracle-claim">' +
                '<div class="oc-head"><span class="oc-token">🔒 ' + esc(issuer) + " freeze</span>" +
                sevTag(con.severity) +
                '<span class="ak-pill ak-pill-live">ATTESTED</span></div>' +
                '<div class="oc-statement">' + esc(addr) + " flagged illicit" +
                (con.likely_cause ? " · " + esc(con.likely_cause) : " (sanctions / hack / fraud)") + "</div>" +
                reasoningBlock(body, "NOMOS") +
                '<div class="oc-meta"><span>' + etherscan + "</span><span>" + traceLink + "</span></div>" +
                spathaBlock(c) +
                "</article>"
            );
        }

        if (dtype === "rug_claim") {
            var fr = body.fundamentals || {}, tr = body.technical || {}, cc = body.conclusion || {};
            var token = fr.token || shortHex(c.token_id);
            var reasons = (tr.reasons || []).join(", ");
            var b = c.bond || { for_stake: 0, against_stake: 0 };
            return (
                '<article class="oracle-claim">' +
                '<div class="oc-head"><span class="oc-token">' + esc(token) + "</span>" +
                sevTag(cc.severity) + statusPill(c.status) + "</div>" +
                '<div class="oc-statement">GoPlus: ' + esc(reasons || "rug risk") + "</div>" +
                reasoningBlock(body, "NOMOS") +
                '<div class="oc-meta"><span>' + traceLink + "</span></div>" +
                '<div class="oc-bonds"><span class="oc-for">FOR $' + (Number(b.for_stake) / 1e6).toFixed(2) +
                '</span><span class="oc-against">AGAINST $' + (Number(b.against_stake) / 1e6).toFixed(2) + "</span></div>" +
                spathaBlock(c) +
                stakeControls(c) +
                "</article>"
            );
        }

        // Fallback (trace body unavailable): show the on-chain claim fields.
        return (
            '<article class="oracle-claim">' +
            '<div class="oc-head"><span class="oc-token">claim #' + esc(c.claim_id) + "</span>" + statusPill(c.status) + "</div>" +
            '<div class="oc-meta"><span>token ' + esc(shortHex(c.token_id)) + "</span><span>" + traceLink + "</span></div>" +
            "</article>"
        );
    }

    async function load() {
        var feed = $("oracle-feed");
        if (!feed) return;
        try {
            var r = await fetch(API + "/api/claims?limit=50");
            if (!r.ok) throw new Error("HTTP " + r.status);
            var data = await r.json();
            if (!data.available) {
                setStatus("not live", "ak-pill-gated");
                feed.innerHTML = '<div class="ak-live-panel"><p>Oracle not live yet — ClaimRegistry not deployed.</p></div>';
                return;
            }
            var claims = data.claims || [];
            setStatus(data.total + " claim" + (data.total === 1 ? "" : "s"), "ak-pill-live");
            // Enrich each claim with its IPFS trace body — NOMOS's reasoning, and
            // SPATHA's separate on-chain decision when present (parallel, best-effort).
            await Promise.all(claims.map(async function (c) {
                c._trace = await fetchTrace(c.ipfs_cid);
                if (c.spatha && c.spatha.ipfs_cid) c._spatha = await fetchTrace(c.spatha.ipfs_cid);
            }));
            feed.innerHTML = claims.length
                ? claims.map(renderClaim).join("")
                : '<p class="empty-state">Oracle is live — no claims issued yet.</p>';
        } catch (e) {
            setStatus("unavailable", "ak-pill-gated");
            feed.innerHTML = '<p class="empty-state">Could not reach the claims API: ' + esc(e.message || e) + "</p>";
        }
    }

    function boot() {
        if (window.AKRITA) window.AKRITA.reloadOracle = load;  // let stake.js refresh after a tx
        load();
        setInterval(load, REFRESH_MS);
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
    else boot();
})();
