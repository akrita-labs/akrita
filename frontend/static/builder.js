(function () {
    "use strict";

    var API = window.location.origin;
    var $ = function (id) { return document.getElementById(id); };

    function esc(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
        });
    }

    function short(h) {
        h = String(h || "");
        return h.length > 16 ? h.slice(0, 10) + "..." + h.slice(-4) : h || "-";
    }

    function money(v) {
        return "$" + (Number(v) || 0).toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    function num(v) {
        return (Number(v) || 0).toLocaleString();
    }

    async function getJSON(path) {
        var res = await fetch(API + path);
        if (!res.ok) throw new Error(path + " -> HTTP " + res.status);
        return res.json();
    }

    function requestedRef() {
        var q = new URLSearchParams(window.location.search);
        return q.get("user") || q.get("id") || q.get("handle") ||
            (window.localStorage && localStorage.getItem("akrita.user")) || null;
    }

    function chooseRow(rows) {
        var ref = requestedRef();
        if (ref) {
            var refStr = String(ref);
            var hit = rows.filter(function (r) {
                return String(r.user_id) === refStr ||
                    String(r.handle) === refStr ||
                    String(r.onchain_agent_id) === refStr;
            })[0];
            if (hit) return hit;
        }
        return rows.filter(function (r) { return r.handle === "operator"; })[0] ||
            rows.filter(function (r) { return !r.is_system; })[0] ||
            rows[0] ||
            null;
    }

    function dataPill(row) {
        if (!row || row.is_system) return "";
        if (row.handle === "operator" || row.display_name === "AKRITA House") {
            return window.AKRITA ? window.AKRITA.pillHTML("live", {
                label: "LIVE",
                tooltip: "AKRITA House uses the real Polymarket builder code.",
            }) : '<span class="ak-pill ak-pill-live">LIVE</span>';
        }
        return window.AKRITA ? window.AKRITA.pillHTML("demo", {
            label: "DEMO",
            tooltip: "Demo operator account; builder code is deterministic.",
        }) : '<span class="ak-pill ak-pill-demo">DEMO</span>';
    }

    function renderHero(row, detail) {
        var code = detail.builder_code || (row && row.builder_code);
        var status = detail.registration_status || (row && row.registration_status) || "unregistered";
        var match = detail.onchain_matches === true || status === "registered";
        var subtitle = "<em>Builder code</em> " + esc(short(code)) +
            " · " + esc(status) +
            " · attribution <strong>" + (match ? "VERIFIED" : "PENDING") + "</strong> " +
            dataPill(row);
        $("builder-title").textContent = (row && (row.display_name || row.handle))
            ? (row.display_name || row.handle) + " · Builder Profile"
            : "Polymarket V2 · Builder Profile";
        $("builder-subtitle").innerHTML = subtitle;
    }

    function renderMetrics(row, detail) {
        var volume = detail.attributed_volume_usdc != null ? detail.attributed_volume_usdc : row.attributed_volume_usdc;
        var fees = detail.builder_fees_usdc != null ? detail.builder_fees_usdc : row.builder_fees_usdc;
        var fills = detail.fills != null ? detail.fills : row.fills;
        var traces = detail.trace_count != null ? detail.trace_count : row.trace_count;
        $("builder-volume").textContent = money(volume);
        $("builder-fees").textContent = money(fees) + " USDC";
        $("builder-fills").textContent = num(fills);
        $("builder-traces").textContent = num(traces);
    }

    function renderSnapshot(row, detail) {
        var host = $("builder-volume-chart");
        if (!host) return;
        var latest = detail.latest_trace || (row && row.latest_trace);
        var traceLine = latest && latest.trace_hash
            ? '<p>Latest trace #' + esc(latest.decision_id) + ' · ' + esc(short(latest.trace_hash)) + '</p>'
            : '<p>No operator-owned trace anchored yet.</p>';
        host.innerHTML =
            '<div class="ak-live-panel">' +
            '<p>' + dataPill(row) + ' ' +
            'BuilderRegistry status is live. Volume and fees are read from the fills table; $0 means no settled attributed fills yet.</p>' +
            traceLine +
            '</div>';
    }

    function renderFills(row) {
        var body = $("builder-fills-body");
        if (!body) return;
        if (!row || !row.fills) {
            body.innerHTML = '<tr><td colspan="7" class="empty-state">No attributed fills yet. This is a live zero from the fills table; execution may still be gated.</td></tr>';
            return;
        }
        body.innerHTML = '<tr><td colspan="7" class="empty-state">Attributed fills are summarized above; per-fill rows will appear here as the fills endpoint exposes operator-scoped records.</td></tr>';
    }

    async function boot() {
        try {
            var lb = await getJSON("/api/leaderboard");
            var rows = lb.leaderboard || [];
            var row = chooseRow(rows);
            if (!row) throw new Error("No builder rows returned.");
            var detail = {};
            try {
                detail = await getJSON("/api/builder/" + encodeURIComponent(row.user_id));
            } catch (e) {
                detail = {};
            }
            renderHero(row, detail);
            renderMetrics(row, detail);
            renderSnapshot(row, detail);
            renderFills(row);
        } catch (e) {
            var body = $("builder-fills-body");
            if (body) body.innerHTML = '<tr><td colspan="7" class="empty-state">Could not load live builder attribution: ' + esc(e.message || e) + "</td></tr>";
            var host = $("builder-volume-chart");
            if (host) host.innerHTML = '<div class="ak-live-panel"><p>Live builder attribution is temporarily unavailable.</p></div>';
        }
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
    else boot();
})();
