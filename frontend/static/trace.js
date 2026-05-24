(function () {
    "use strict";

    var API = window.location.origin;
    var EXPLORER = "https://testnet.arcscan.app";
    var $ = function (id) { return document.getElementById(id); };

    function esc(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
        });
    }

    function setText(id, value) {
        var el = $(id);
        if (el) el.textContent = value == null || value === "" ? "—" : String(value);
    }

    function shortHash(h) {
        h = String(h || "");
        return h.length > 18 ? h.slice(0, 10) + "..." + h.slice(-6) : h || "—";
    }

    function roleName(role) {
        var key = String(role || "").toUpperCase();
        var plain = { NOMOS: "Market Maker", SPATHA: "Hedger", AGROS: "Treasury" }[key];
        return plain ? key + " / " + plain : key || "—";
    }

    function fmtTime(value) {
        if (value == null || value === "") return "—";
        var d = typeof value === "number" ? new Date(value) : new Date(value);
        if (isNaN(d.getTime())) return String(value);
        return d.toISOString().replace("T", " ").replace("Z", " UTC");
    }

    async function getJSON(path) {
        var res = await fetch(API + path);
        if (!res.ok) throw new Error(path + " -> HTTP " + res.status);
        return res.json();
    }

    function parseRef() {
        var q = new URLSearchParams(window.location.search);
        if (q.get("hash")) return { type: "hash", value: q.get("hash") };
        if (q.get("id")) return { type: "id", value: q.get("id") };

        var parts = window.location.pathname.replace(/\/+$/, "").split("/");
        var last = parts[parts.length - 1];
        if (!last || last === "trace" || last === "trace.html") return null;
        return /^\d+$/.test(last) ? { type: "id", value: last } : { type: "hash", value: last };
    }

    function setStep(name, state, message) {
        var step = document.querySelector('.trace-step[data-step="' + name + '"]');
        if (!step) return;
        step.classList.remove("is-active", "is-done", "is-fail");
        if (state) step.classList.add("is-" + state);
        var span = step.querySelector("span");
        if (span) span.innerHTML = message;
    }

    function setStamp(id, state, label) {
        var stamp = $(id);
        if (!stamp) return;
        stamp.classList.remove("is-done", "is-fail");
        if (state) stamp.classList.add("is-" + state);
        var span = stamp.querySelector("span");
        if (span && label) span.textContent = label;
    }

    function linkTx(tx) {
        if (!tx) return "tx —";
        return '<a class="lb-link" href="' + esc(EXPLORER.replace(/\/$/, "") + "/tx/" + tx) +
            '" target="_blank" rel="noopener">' + esc(shortHash(tx)) + "</a>";
    }

    function linkBlock(block) {
        if (!block) return "block —";
        return '<a class="lb-link" href="' + esc(EXPLORER.replace(/\/$/, "") + "/block/" + block) +
            '" target="_blank" rel="noopener">block ' + esc(block) + "</a>";
    }

    function valueHTML(value) {
        if (value == null || value === "") return "—";
        if (typeof value === "number") return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(6)));
        if (typeof value === "boolean") return value ? "true" : "false";
        if (Array.isArray(value) || typeof value === "object") return "<pre>" + esc(JSON.stringify(value, null, 2)) + "</pre>";
        return esc(value);
    }

    function rowsHTML(obj) {
        var keys = Object.keys(obj || {});
        if (!keys.length) return "<tr><th>status</th><td>No section data returned.</td></tr>";
        return keys.map(function (key) {
            return "<tr><th>" + esc(key) + "</th><td>" + valueHTML(obj[key]) + "</td></tr>";
        }).join("");
    }

    function readRisk(gate) {
        gate = gate || {};
        var checks = gate.checks || [];
        var passed = checks.filter(function (c) { return !!c.passed; }).length;
        var total = checks.length;
        var verdict = gate.approved === false ? "Blocked" : "Approved";
        return verdict + (total ? " - " + passed + "/" + total + " sentinels" : "");
    }

    function headline(body) {
        var role = String(body.agent_role || "").toLowerCase();
        var c = body.conclusion || {};
        var f = body.fundamentals || {};
        if (role === "nomos") {
            return "NOMOS / Market Maker quoted " +
                (c.final_bid != null ? "bid " + c.final_bid : "a bid") + " / " +
                (c.final_ask != null ? "ask " + c.final_ask : "an ask") +
                (f.market_question ? " for " + f.market_question : ".");
        }
        if (role === "spatha") {
            return "SPATHA / Hedger " + (c.action || "reviewed") + " " +
                ((body.technical && body.technical.hedge_side) || "exposure") +
                (body.technical && body.technical.instrument ? " on " + body.technical.instrument : "") + ".";
        }
        if (role === "agros") {
            return "AGROS / Treasury chose " + (c.action || "a treasury action") +
                (c.amount != null ? " for $" + Number(c.amount).toFixed(2) : "") + ".";
        }
        return (c.narrative || body.narrative || "Committed trace #" + body.decision_id);
    }

    function renderMeta(meta) {
        var role = meta.agent_role || "—";
        var traceHash = meta.trace_hash || meta.on_chain_hash;
        setText("trace-title", "Trace · " + shortHash(traceHash));
        setText("trace-provenance", "agent: " + roleName(role) + " · decision_id: " + (meta.decision_id || "—") +
            " · ts: " + fmtTime(meta.committed_at || meta.ts_ms));
        setStamp("stamp-committed", meta.arc_tx || meta.arc_tx_hash || traceHash ? "done" : "", "COMMITTED");
        setStamp("stamp-pinned", meta.cid || meta.ipfs_cid ? "done" : "", "PINNED");
    }

    function renderGauge(technical) {
        var book = (technical && technical.orderbook_state) || {};
        var bid = book.best_bid;
        var ask = book.best_ask;
        var mid = book.microprice != null ? book.microprice : (bid != null && ask != null ? (Number(bid) + Number(ask)) / 2 : null);
        setText("trace-mid-label", mid != null ? "mid " + Number(mid).toFixed(3) : "mid —");
        setText("trace-bid-label", bid != null ? "BID " + Number(bid).toFixed(3) : "BID");
        setText("trace-ask-label", ask != null ? "ASK " + Number(ask).toFixed(3) : "ASK");
        var scale = $("trace-gauge-scale");
        if (!scale || mid == null) return;
        var points = [];
        for (var i = 3; i >= -4; i--) points.push(Math.max(0, Math.min(1, mid + i * 0.01)));
        scale.innerHTML = points.map(function (p) { return "<li>" + p.toFixed(3) + "</li>"; }).join("");
    }

    function renderTechnical(technical) {
        renderGauge(technical);
        var host = $("trace-technical-readout");
        if (!host) return;
        var keys = Object.keys(technical || {});
        if (!keys.length) {
            host.innerHTML = "<dt>status:</dt><dd>No technical section returned.</dd>";
            return;
        }
        host.innerHTML = keys.map(function (key) {
            return "<dt>" + esc(key) + ":</dt><dd>" + valueHTML(technical[key]) + "</dd>";
        }).join("");
    }

    function renderBody(body, meta) {
        var c = body.conclusion || {};
        setText("trace-summary-title", headline(body));
        setText("trace-summary-why", c.narrative || body.narrative || "The trace body did not include a narrative.");
        setText("sum-role", roleName(body.agent_role || meta.agent_role));
        setText("sum-decision", body.decision_id || meta.decision_id);
        setText("sum-ts", fmtTime(body.ts_ms || meta.ts_ms || meta.committed_at));
        setText("sum-model", body.model || "unset");
        setText("sum-compute", body.computation_ms != null ? body.computation_ms + " ms" : "—");

        var risk = readRisk(body.risk_gate);
        var pill = $("trace-live-pill");
        if (pill) {
            pill.textContent = "LIVE";
            pill.setAttribute("data-tip", "On-chain trace plus live risk gate: " + risk);
            pill.setAttribute("title", "On-chain trace plus live risk gate: " + risk);
        }

        var fundamentals = $("trace-fundamentals");
        if (fundamentals) fundamentals.innerHTML = rowsHTML(body.fundamentals || {});
        renderTechnical(body.technical || {});

        var out = Object.assign({}, c, {
            risk_gate: risk,
            trace_hash: meta.trace_hash || meta.on_chain_hash || null,
            ipfs_cid: meta.cid || meta.ipfs_cid || null,
            arc_tx_hash: meta.arc_tx || meta.arc_tx_hash || null,
            arc_block: meta.arc_block || null,
        });
        setText("trace-conclusion-json", JSON.stringify(out, null, 2));
    }

    function showError(message) {
        setText("trace-summary-title", "Trace unavailable");
        setText("trace-summary-why", message);
        setStep("body", "fail", esc(message));
        setStep("hash", "fail", "Verification did not run.");
        setStep("arc", "fail", "Arc comparison did not run.");
        setStep("seal", "fail", "Not verified.");
        setStamp("stamp-verified", "fail", "FAILED");
    }

    async function resolveMeta(ref) {
        if (!ref) {
            var latest = await getJSON("/state/traces?limit=1");
            var row = (latest.traces || [])[0];
            if (!row) throw new Error("No committed traces yet.");
            ref = { type: "id", value: row.decision_id };
        }
        if (ref.type === "hash") return getJSON("/traces/by-hash/" + encodeURIComponent(ref.value));
        return getJSON("/traces/" + encodeURIComponent(ref.value));
    }

    async function boot() {
        var meta;
        try {
            meta = await resolveMeta(parseRef());
            renderMeta(meta);
        } catch (e) {
            showError(e.message || "Trace metadata could not be loaded.");
            return;
        }

        var id = meta.decision_id;
        var body = null;
        try {
            setStep("body", "active", "Fetching /traces/" + esc(id) + "/body...");
            body = await getJSON("/traces/" + encodeURIComponent(id) + "/body");
            setStep("body", "done", "IPFS body loaded for decision #" + esc(id) + ".");
            renderBody(body, meta);
        } catch (e) {
            setStamp("stamp-pinned", "fail", "PIN FAILED");
            showError("IPFS body unavailable: " + (e.message || e));
            return;
        }

        try {
            setStep("hash", "active", "Calling server /verify with canonical JSON hashing.");
            var verify = await getJSON("/traces/" + encodeURIComponent(id) + "/verify");
            setStep("hash", "done", "recomputed_hash " + esc(shortHash(verify.recomputed_hash)));
            var tx = verify.arc_tx_hash || meta.arc_tx || meta.arc_tx_hash;
            var block = verify.arc_block || meta.arc_block;
            if (verify.matches === true) {
                setStep("arc", "done", "Registry match confirmed · " + linkTx(tx) + " · " + linkBlock(block));
                setStep("seal", "done", "Verified seal: on-chain hash matches canonical IPFS body.");
                setStamp("stamp-verified", "done", "VERIFIED");
            } else {
                setStep("arc", "fail", "Registry mismatch · on-chain " + esc(shortHash(verify.on_chain_hash)) +
                    " vs recomputed " + esc(shortHash(verify.recomputed_hash)));
                setStep("seal", "fail", "Red seal: hash mismatch.");
                setStamp("stamp-verified", "fail", "MISMATCH");
            }
        } catch (e) {
            setStep("hash", "fail", "Server verification failed: " + esc(e.message || e));
            setStep("arc", "fail", "Arc registry comparison did not complete.");
            setStep("seal", "fail", "Red seal: verification incomplete.");
            setStamp("stamp-verified", "fail", "FAILED");
        }
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
    else boot();
})();
