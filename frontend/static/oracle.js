// AKRITA Rugpull Oracle — live claim feed.
// Reads GET /api/claims and renders issued rug-risk claims + bond pools.
// Honest states: "not live yet" until ClaimRegistry is deployed (available:false);
// empty when deployed-but-no-claims; populated once NOMOS issues claims.
(function () {
    "use strict";
    var API = window.location.origin;
    var REFRESH_MS = 15000;

    function $(id) { return document.getElementById(id); }
    function esc(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
        });
    }
    function shortHex(h) {
        h = String(h || "");
        return h.length > 14 ? h.slice(0, 8) + "…" + h.slice(-4) : (h || "—");
    }
    function usdc(raw) {
        var v = Number(raw || 0) / 1e6; // bond token has 6 decimals
        return "$" + v.toLocaleString(undefined, { maximumFractionDigits: 2 });
    }
    function statusPill(status) {
        var s = String(status || "open").toLowerCase();
        var cls = s === "rugged" ? "ak-pill-live" : s === "safe" ? "ak-pill-demo" : "ak-pill-gated";
        var label = s === "rugged" ? "RUGGED" : s === "safe" ? "HELD" : "OPEN";
        return '<span class="ak-pill ' + cls + '">' + label + "</span>";
    }

    function setStatus(text, cls) {
        var el = $("oracle-status");
        if (!el) return;
        el.textContent = text;
        el.className = "ak-pill " + (cls || "ak-pill-gated");
    }

    function renderClaim(c) {
        var bond = c.bond || { for_stake: 0, against_stake: 0 };
        var commit = (c.source_commit || "").replace(/^0x/, "").slice(0, 10);
        var pct = (Number(c.drop_threshold_bps || 0) / 100).toFixed(0);
        var days = Math.max(1, Math.round(Number(c.window_s || 0) / 86400));
        var traceLink = c.trace_hash
            ? '<a href="/app/trace?hash=' + esc(c.trace_hash) + '">trace ' + esc(shortHex(c.trace_hash)) + "</a>"
            : "—";
        return (
            '<article class="oracle-claim">' +
            '<div class="oc-head">' +
            '<span class="oc-token">' + esc(c.token || c.token_id || "—") + "</span>" +
            statusPill(c.status) +
            "</div>" +
            '<div class="oc-meta">' +
            '<span title="GitHub provenance">NFI commit ' + esc(commit || "—") + "</span>" +
            "<span>predict &gt;" + esc(pct) + "% drop / " + esc(days) + "d</span>" +
            "<span>" + traceLink + "</span>" +
            "</div>" +
            '<div class="oc-bonds">' +
            '<span class="oc-for">FOR ' + usdc(bond.for_stake) + "</span>" +
            '<span class="oc-against">AGAINST ' + usdc(bond.against_stake) + "</span>" +
            "</div>" +
            "</article>"
        );
    }

    function renderNotLive(detail) {
        return (
            '<div class="ak-live-panel"><p>The on-chain oracle isn\'t live yet — ' +
            "<code>ClaimRegistry</code> hasn't been deployed (set <code>CLAIM_REGISTRY_ADDR</code> " +
            "after <code>DeployClaimRegistry.s.sol</code>). The signal pipeline (NFI blacklist → " +
            "reasoning trace) is built and tested; claims appear here once NOMOS starts issuing." +
            (detail ? '<br /><small>' + esc(detail) + "</small>" : "") +
            "</p></div>"
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
                feed.innerHTML = renderNotLive(data.detail);
                return;
            }
            var claims = data.claims || [];
            setStatus(data.total + " claim" + (data.total === 1 ? "" : "s"), "ak-pill-live");
            feed.innerHTML = claims.length
                ? claims.map(renderClaim).join("")
                : '<p class="empty-state">Oracle is live — no rug-risk claims issued yet.</p>';
        } catch (e) {
            setStatus("unavailable", "ak-pill-gated");
            feed.innerHTML = '<p class="empty-state">Could not reach the claims API: ' + esc(e.message || e) + "</p>";
        }
    }

    function boot() {
        load();
        setInterval(load, REFRESH_MS);
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
    else boot();
})();
