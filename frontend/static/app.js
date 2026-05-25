// AKRITA Frontier-Keeper dashboard.
// Hydrates initial state via REST, then subscribes to /live WebSocket for
// incremental events.

(() => {
    const API = window.location.origin;
    const WS_URL = API.replace(/^http/, "ws") + "/live";

    const $ = (id) => document.getElementById(id);

    // ----- State containers (in-memory) ----------------------------------
    const state = {
        traces: [],          // ordered newest-first
        fills: [],
        feedsByAgent: { nomos: [], spatha: [], agros: [] },
    };

    // ----- KPI rendering --------------------------------------------------

    function flashKpi(el) {
        el.classList.add("flash");
        setTimeout(() => el.classList.remove("flash"), 600);
    }

    function fmtMoney(n) {
        if (n === null || n === undefined) return "—";
        const v = Number(n);
        if (Math.abs(v) >= 10_000) return "$" + v.toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
        return "$" + v.toFixed(2);
    }

    function fmtPct(n) {
        if (n === null || n === undefined) return "—";
        return (Number(n) * 100).toFixed(2) + "%";
    }

    function shortHash(h) {
        if (!h) return "";
        return h.slice(0, 8) + "…" + h.slice(-4);
    }

    function shortCid(c) {
        if (!c) return "";
        return c.length > 16 ? c.slice(0, 10) + "…" + c.slice(-4) : c;
    }

    // ----- REST hydration -------------------------------------------------

    async function hydrate() {
        try {
            const [balR, fillsR, decisionsR, treasuryR, tracesR] = await Promise.all([
                fetch(API + "/state/balances").then(r => r.json()),
                fetch(API + "/state/fills?limit=50").then(r => r.json()),
                fetch(API + "/state/decisions?limit=50").then(r => r.json()),
                fetch(API + "/state/treasury?limit=20").then(r => r.json()),
                fetch(API + "/state/traces?limit=20").then(r => r.json()),
            ]);

            renderBalances(balR);
            renderFills(fillsR);
            renderDecisions(decisionsR.decisions || []);
            renderTraces(tracesR);
        } catch (err) {
            console.error("hydrate failed", err);
        }
    }

    function renderBalances(bal) {
        const agros = bal["agros-keeper"] || {};
        const usycAmt = (agros.arc && agros.arc.USYC) || 0;
        const nav = bal.usyc_nav || 1;
        const usycUsdValue = usycAmt * nav;
        $("kpi-usyc").textContent = fmtMoney(usycUsdValue);
        $("kpi-usyc-apy").textContent = "apy: " + fmtPct(bal.usyc_apy || 0);

        // Sum USDC across all wallets, all chains
        let usdcTotal = 0;
        for (const wallet of Object.keys(bal)) {
            if (typeof bal[wallet] !== "object" || bal[wallet] === null) continue;
            for (const chain of Object.keys(bal[wallet])) {
                const c = bal[wallet][chain];
                if (c && typeof c.USDC === "number") usdcTotal += c.USDC;
            }
        }
        $("kpi-usdc").textContent = fmtMoney(usdcTotal);
    }

    function renderFills(fillsResponse) {
        const fills = fillsResponse.fills || [];
        const cumFees = fillsResponse.cumulative_builder_fees_usdc || 0;
        $("kpi-fees").textContent = "$" + cumFees.toFixed(4);

        let totalVol = 0;
        for (const f of fills) totalVol += (f.price * f.size);
        $("kpi-volume").textContent = fmtMoney(totalVol);

        const list = $("fills-list");
        if (fills.length === 0) {
            list.innerHTML = '<div class="empty-state">no fills yet</div>';
            return;
        }
        list.innerHTML = fills.map(f => `
            <div class="fill-row">
                <span class="fill-side-${f.side.toLowerCase()}">${f.side}</span>
                <span>${f.market_id.slice(0, 10)}…</span>
                <span>${f.size}</span>
                <span>@ ${f.price.toFixed(4)}</span>
                <span class="fill-fee">fee +${(f.builder_fee_usdc || 0).toFixed(4)}</span>
            </div>
        `).join("");
    }

    function renderDecisions(decisions) {
        const byAgent = { nomos: [], spatha: [], agros: [] };
        for (const d of decisions) {
            const role = d.agent_role;
            if (byAgent[role]) byAgent[role].push(d);
        }
        for (const agent of ["nomos", "spatha", "agros"]) {
            renderAgentFeed(agent, byAgent[agent]);
        }
    }

    // Trace KPI + list come straight from the traces table (on-chain anchor
    // record), so they reflect committed traces regardless of execution status.
    function renderTraces(tracesResponse) {
        const count = tracesResponse.count || 0;
        $("kpi-traces").textContent = count;
        const traces = (tracesResponse.traces || []).map(t => ({
            decision_id: t.decision_id,
            agent_role: t.agent_role,
            trace_hash: t.trace_hash,
            ipfs_cid: t.cid,
        }));
        renderTraceList(traces);
    }

    function decisionSummary(d) {
        if (d.agent_role === "nomos") {
            return `quote · bid ${d.bid?.toFixed(4)} ask ${d.ask?.toFixed(4)} size ${d.size}`;
        }
        if (d.agent_role === "spatha") {
            return `hedge · ${d.side} ${d.size} ${d.instrument}`;
        }
        if (d.agent_role === "agros") {
            return `${d.action} · ${d.amount}`;
        }
        return "decision";
    }

    function renderAgentFeed(agent, decisions) {
        const el = $("feed-" + agent);
        if (!decisions || decisions.length === 0) {
            el.innerHTML = `<div class="empty-state">${agent === "nomos" ? "awaiting first quote…" : agent === "spatha" ? "standing watch…" : "tending the field…"}</div>`;
            return;
        }
        // Most recent first (top of list)
        el.innerHTML = decisions.slice(0, 8).map(d => `
            <div class="decision-row">
                <div class="decision-id">#${d.decision_id} · ${new Date(d.ts_ms).toLocaleTimeString()}</div>
                <div class="decision-summary">${decisionSummary(d)}</div>
                ${d.trace_hash ? `<div class="decision-hash"><a href="/app/trace?hash=${d.trace_hash}">trace ${shortHash(d.trace_hash)}</a></div>` : ""}
            </div>
        `).join("");
    }

    function renderTraceList(traces) {
        const list = $("trace-list");
        if (traces.length === 0) {
            list.innerHTML = '<div class="empty-state">no traces committed yet</div>';
            return;
        }
        list.innerHTML = traces.slice(0, 20).map(t => `
            <div class="trace-row">
                <span class="trace-agent ${t.agent_role}">${t.agent_role.toUpperCase()}</span>
                <span>#${t.decision_id}</span>
                <span class="trace-hash">${shortHash(t.trace_hash)}</span>
                <span class="trace-cid">cid ${shortCid(t.ipfs_cid)}</span>
                <span><a class="trace-verify-link" href="/app/trace?hash=${t.trace_hash}">verify →</a></span>
            </div>
        `).join("");
    }

    // ----- WebSocket live feed -------------------------------------------

    let ws = null;

    function connectWS() {
        $("ws-status").textContent = "connecting…";
        $("ws-status").className = "value status-pending";
        try {
            ws = new WebSocket(WS_URL);
        } catch (e) {
            $("ws-status").textContent = "ws unavailable";
            $("ws-status").className = "value status-disconnected";
            return;
        }
        ws.onopen = () => {
            $("ws-status").textContent = "live";
            $("ws-status").className = "value status-connected";
        };
        ws.onmessage = (msg) => {
            try { handleEvent(JSON.parse(msg.data)); }
            catch (e) { console.warn("bad event", e); }
        };
        ws.onclose = () => {
            $("ws-status").textContent = "disconnected";
            $("ws-status").className = "value status-disconnected";
            setTimeout(connectWS, 2000);
        };
        ws.onerror = () => { /* close handler will reconnect */ };
    }

    function handleEvent(evt) {
        if (evt.type === "decision" || evt.type === "fill") {
            // Refresh from REST (simpler than diffing client-side state)
            hydrate();
            if (evt.type === "decision") {
                flashKpi($("kpi-traces"));
            } else if (evt.type === "fill") {
                flashKpi($("kpi-fees"));
                flashKpi($("kpi-volume"));
            }
        }
    }

    // ----- Boot -----------------------------------------------------------

    document.addEventListener("DOMContentLoaded", () => {
        hydrate();
        connectWS();
        // Periodic background refresh as a safety net
        setInterval(hydrate, 8000);
    });
})();
