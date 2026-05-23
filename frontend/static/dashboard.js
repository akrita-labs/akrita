// AKRITA dashboard — live hydration from the orchestrator /state + /api endpoints.
// Replaces the static mockup with real keeper data. The yield ticker and
// kill-switch seal are wired by the inline script in dashboard.html; this file
// owns every other panel (inventory, treasury totals, attribution, chronicle,
// Arc block). No mock data: placeholders are cleared on load and panels show
// honest empty-states when there is genuinely nothing yet.
(function () {
    "use strict";
    var API = window.location.origin;
    var $ = function (id) { return document.getElementById(id); };

    function fmtMoney(n) {
        if (n == null || isNaN(n)) return "—";
        var v = Number(n);
        if (Math.abs(v) >= 10000) return "$" + v.toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
        return "$" + v.toFixed(2);
    }
    function fmtNum(n, d) {
        if (n == null || isNaN(n)) return "—";
        return Number(n).toLocaleString(undefined, { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 });
    }
    function fmtPct(n) { if (n == null || isNaN(n)) return "—"; return (Number(n) * 100).toFixed(2) + "%"; }
    function shortHash(h) { return h ? h.slice(0, 8) + "…" + h.slice(-4) : "—"; }
    function setText(id, t) { var e = $(id); if (e) e.textContent = t; }
    function fmtTime(iso) { try { return new Date(iso).toLocaleTimeString(); } catch (e) { return ""; } }

    async function getJSON(path) {
        var r = await fetch(API + path);
        if (!r.ok) throw new Error(path + " -> " + r.status);
        return r.json();
    }

    function clearPlaceholders() {
        ["kpi-usyc", "kpi-usyc-sub", "treasury-rate", "kpi-fees", "kpi-builder", "field-usdc-pct", "field-usyc-pct"]
            .forEach(function (id) { setText(id, "—"); });
        setText("arc-block", "#—");
        var inv = $("inventory-rows");
        if (inv) inv.innerHTML = '<tr><td colspan="6" class="empty-state">loading…</td></tr>';
        var ch = $("chronicle-list");
        if (ch) ch.innerHTML = '<div class="empty-state">loading…</div>';
        var fb = $("fee-bars");
        if (fb) fb.innerHTML = '<div class="empty-state">loading…</div>';
    }

    async function hydrateTreasury() {
        var bal = await getJSON("/state/balances");
        var agros = (bal["agros-keeper"] && bal["agros-keeper"].arc) || {};
        var usyc = agros.USYC || 0;
        var nav = bal.usyc_nav || 1;
        var apy = bal.usyc_apy || 0;
        var usycUsd = usyc * nav;
        var usdc = agros.USDC || 0;
        setText("kpi-usyc", fmtNum(usyc, 4) + " USYC");
        setText("kpi-usyc-sub", fmtMoney(usycUsd) + " · NAV " + nav.toFixed(4));
        var alloc = usdc + usycUsd;
        var usdcPct = alloc > 0 ? Math.round((usdc / alloc) * 100) : 0;
        setText("field-usdc-pct", "USDC " + usdcPct + "%");
        setText("field-usyc-pct", "USYC " + (100 - usdcPct) + "%");
        var perSec = (usycUsd * apy) / 31557600;
        var perDay = (usycUsd * apy) / 365;
        setText("treasury-rate", "+$" + perSec.toFixed(6) + " / sec · $" + perDay.toFixed(4) + " / day");
    }

    async function hydrateAttribution() {
        var fills = await getJSON("/state/fills?limit=50");
        setText("kpi-fees", "$" + (fills.cumulative_builder_fees_usdc || 0).toFixed(4));
        var bars = $("fee-bars");
        if (bars) {
            var rows = fills.fills || [];
            if (rows.length === 0) {
                bars.innerHTML = '<div class="empty-state">no attributed fills yet · Polymarket order submission is gated on signer collateral</div>';
            } else {
                var byDay = {};
                rows.forEach(function (f) {
                    var d = new Date(f.ts_ms);
                    var k = (d.getUTCMonth() + 1) + "/" + d.getUTCDate();
                    byDay[k] = (byDay[k] || 0) + (f.builder_fee_usdc || 0);
                });
                var keys = Object.keys(byDay);
                var max = Math.max.apply(null, keys.map(function (k) { return byDay[k]; })) || 1;
                bars.innerHTML = keys.map(function (k) {
                    var h = Math.max(6, Math.round((byDay[k] / max) * 70));
                    return '<div style="--h: ' + h + 'px"><i></i><span>' + k + '</span><b>' + byDay[k].toFixed(2) + '</b></div>';
                }).join("");
            }
        }
        try {
            var lb = await getJSON("/api/leaderboard");
            var s = lb.summary || {};
            setText("kpi-builder", (s.registered_builders || 0) + " builders · registry " + shortHash(s.builder_registry));
            window.__akritaExplorer = s.explorer || "";
        } catch (e) { /* attribution still shows real fees without the summary */ }
    }

    async function hydrateInventory() {
        var inv = await getJSON("/state/inventory");
        var rows = inv.inventory || [];
        var tb = $("inventory-rows");
        if (!tb) return;
        if (rows.length === 0) {
            tb.innerHTML = '<tr><td colspan="6" class="empty-state">no open inventory · NOMOS quotes are staged; positions appear once orders fill</td></tr>';
            return;
        }
        tb.innerHTML = rows.map(function (r, i) {
            var net = r.net_exposure || 0;
            var cls = net > 0 ? "delta-hot" : net < 0 ? "delta-cold" : "";
            var mkt = r.market_id ? r.market_id.slice(0, 8) + "…" + r.market_id.slice(-4) : "—";
            return "<tr><td>" + (i + 1) + "</td><td>" + mkt + "</td><td>" + fmtNum(r.long_size, 2) +
                "</td><td>" + fmtNum(r.short_size, 2) + '</td><td class="' + cls + '">' +
                (net >= 0 ? "+" : "") + fmtNum(net, 2) + "</td><td></td></tr>";
        }).join("");
    }

    async function hydrateChronicle() {
        var tr = await getJSON("/state/traces?limit=14");
        var traces = tr.traces || [];
        if (traces.length) {
            var maxBlock = traces.reduce(function (m, t) { return Math.max(m, t.arc_block || 0); }, 0);
            if (maxBlock) setText("arc-block", "#" + maxBlock.toLocaleString());
        }
        var cl = $("chronicle-list");
        if (!cl) return;
        if (traces.length === 0) {
            cl.innerHTML = '<div class="empty-state">no traces committed yet</div>';
            return;
        }
        var glyph = { nomos: "▥", spatha: "†", agros: "✤" };
        var exp = (window.__akritaExplorer || "https://testnet.arcscan.app").replace(/\/$/, "");
        cl.innerHTML = traces.map(function (t) {
            var role = (t.agent_role || "").toUpperCase();
            var hashTxt = shortHash(t.trace_hash);
            var hashHtml = (exp && t.arc_tx)
                ? '<a href="' + exp + "/tx/" + t.arc_tx + '" target="_blank" rel="noopener">' + hashTxt + "</a>"
                : hashTxt;
            var block = t.arc_block ? t.arc_block.toLocaleString() : "—";
            return "<div><span>" + (glyph[t.agent_role] || "▥") + "</span><time>" + fmtTime(t.committed_at) +
                "</time><p>" + role + " committed trace #" + t.decision_id + " — " + hashHtml +
                " · block " + block + "</p><b>ANCHORED</b></div>";
        }).join("");
    }

    function hydrate() {
        // Each section is independent and self-contained: one failing endpoint
        // never blanks the others.
        hydrateTreasury().catch(function () {});
        hydrateAttribution().catch(function () {});
        hydrateInventory().catch(function () {});
        hydrateChronicle().catch(function () {});
    }

    document.addEventListener("DOMContentLoaded", function () {
        clearPlaceholders();
        hydrate();
        setInterval(hydrate, 8000);
    });
})();
