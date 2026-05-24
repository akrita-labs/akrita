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

    function renderClaim(c) {
        var body = c._trace || {};
        var dtype = body.decision_type;
        var traceLink = c.trace_hash
            ? '<a href="/app/trace?hash=' + esc(c.trace_hash) + '">trace ' + esc(shortHex(c.trace_hash)) + "</a>"
            : "";

        if (dtype === "freeze_attestation") {
            var f = body.fundamentals || {}, tech = body.technical || {};
            var issuer = tech.issuer || "stablecoin";
            var addr = f.frozen_address || "—";
            var src = (f.source || {}).freeze_tx || c.source_commit;
            var etherscan = src ? '<a href="https://etherscan.io/tx/' + esc(src) + '" target="_blank" rel="noopener">verify freeze on Ethereum ↗</a>' : "";
            return (
                '<article class="oracle-claim">' +
                '<div class="oc-head"><span class="oc-token">🔒 ' + esc(issuer) + " freeze</span>" +
                '<span class="ak-pill ak-pill-live">ATTESTED</span></div>' +
                '<div class="oc-statement">' + esc(addr) + " flagged illicit (sanctions / hack / fraud)</div>" +
                '<div class="oc-meta">' +
                "<span>" + etherscan + "</span>" +
                "<span>" + traceLink + "</span>" +
                "</div></article>"
            );
        }

        if (dtype === "rug_claim") {
            var fr = body.fundamentals || {}, tr = body.technical || {};
            var token = fr.token || shortHex(c.token_id);
            var reasons = (tr.reasons || []).join(", ");
            var b = c.bond || { for_stake: 0, against_stake: 0 };
            return (
                '<article class="oracle-claim">' +
                '<div class="oc-head"><span class="oc-token">' + esc(token) + "</span>" + statusPill(c.status) + "</div>" +
                '<div class="oc-statement">GoPlus: ' + esc(reasons || "rug risk") + "</div>" +
                '<div class="oc-meta"><span>' + traceLink + "</span></div>" +
                '<div class="oc-bonds"><span class="oc-for">FOR $' + (Number(b.for_stake) / 1e6).toFixed(2) +
                '</span><span class="oc-against">AGAINST $' + (Number(b.against_stake) / 1e6).toFixed(2) + "</span></div>" +
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
            // Enrich each claim with its IPFS trace body (parallel, best-effort).
            await Promise.all(claims.map(async function (c) { c._trace = await fetchTrace(c.ipfs_cid); }));
            feed.innerHTML = claims.length
                ? claims.map(renderClaim).join("")
                : '<p class="empty-state">Oracle is live — no claims issued yet.</p>';
        } catch (e) {
            setStatus("unavailable", "ak-pill-gated");
            feed.innerHTML = '<p class="empty-state">Could not reach the claims API: ' + esc(e.message || e) + "</p>";
        }
    }

    function boot() { load(); setInterval(load, REFRESH_MS); }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
    else boot();
})();
