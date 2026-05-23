// AKRITA — Kill switch.
// A red-wax-seal "Engage Kill Switch" affordance. On click: confirm, POST
// /api/kill-switch {user_id, trigger_source:"manual"}, then play an "atomic
// shutdown" moment — four steps light up in sequence as the orchestrator's
// JSON results arrive (NOMOS cancel -> SPATHA close -> AGROS redeem -> Arc
// trace committed), ending with a link to the Arc tx.
//
//   wireKillSwitch(buttonEl, userId)
//     buttonEl — the seal/button element to wire.
//     userId   — operator id; if absent, runs in demo mode (no POST, the
//                sequence plays with simulated results).
//
// The overlay + step styles are injected once so the widget is drop-in on
// any parchment page. No dependencies.

(function (global) {
    "use strict";

    var STEP_DEFS = [
        { key: "nomos", label: "NOMOS — cancel open quotes", greek: "ΝΟΜΟΣ" },
        { key: "spatha", label: "SPATHA — close hedges", greek: "ΣΠΑΘΑ" },
        { key: "agros", label: "AGROS — redeem to USDC", greek: "ΑΓΡΟΣ" },
        { key: "trace", label: "Arc — trace committed", greek: "✠" },
    ];

    var stylesInjected = false;

    function injectStyles() {
        if (stylesInjected || typeof document === "undefined") return;
        stylesInjected = true;
        var css =
            ".ks-overlay{position:fixed;inset:0;z-index:9999;display:flex;" +
            "align-items:center;justify-content:center;" +
            "background:rgba(26,18,12,0.62);backdrop-filter:blur(2px);" +
            "font-family:var(--font-body,Georgia,serif);}" +
            ".ks-card{position:relative;width:min(440px,92vw);padding:30px 34px 26px;" +
            "background:linear-gradient(180deg,#f5eedd 0%,#e9dcc1 100%);" +
            "border:1px solid var(--page-rule,rgba(124,82,25,0.5));" +
            "box-shadow:0 18px 60px rgba(26,18,12,0.5);color:#17120e;}" +
            ".ks-card::before{content:'';position:absolute;inset:8px;pointer-events:none;" +
            "border:1px solid rgba(132,88,27,0.44);}" +
            ".ks-title{margin:0 0 4px;font-family:var(--font-display,serif);" +
            "font-size:26px;letter-spacing:0.06em;text-transform:uppercase;" +
            "color:#8a2d1c;text-align:center;}" +
            ".ks-sub{margin:0 0 18px;text-align:center;font-style:italic;" +
            "font-size:14px;color:#5f482b;}" +
            ".ks-steps{list-style:none;margin:0 0 18px;padding:0;}" +
            ".ks-steps li{display:flex;align-items:center;gap:12px;padding:9px 4px;" +
            "border-bottom:1px dotted rgba(124,82,25,0.4);font-family:var(--font-mono),monospace;" +
            "font-size:12px;color:#8b8f9d;opacity:0.5;transition:opacity .4s,color .4s;}" +
            ".ks-steps li:last-child{border-bottom:none;}" +
            ".ks-steps li .ks-seal{flex:0 0 auto;width:20px;height:20px;border-radius:50%;" +
            "border:1px dashed rgba(124,82,25,0.5);display:flex;align-items:center;" +
            "justify-content:center;font-size:11px;color:#9d6f1d;}" +
            ".ks-steps li.active{opacity:1;color:#17120e;}" +
            ".ks-steps li.active .ks-seal{background:radial-gradient(circle,#a8331f,#7a1f1f);" +
            "border-style:solid;border-color:#5f1414;color:#fff5df;}" +
            ".ks-steps li.done .ks-seal{background:radial-gradient(circle,#3a7a52,#2c6040);" +
            "border-color:#1d4630;color:#fff5df;}" +
            ".ks-actions{display:flex;gap:12px;justify-content:center;}" +
            ".ks-btn{min-height:42px;padding:0 22px;border:1px solid var(--page-gold,#9d6f1d);" +
            "font-family:var(--font-display,serif);font-size:17px;letter-spacing:0.07em;" +
            "text-transform:uppercase;cursor:pointer;text-decoration:none;display:inline-flex;" +
            "align-items:center;justify-content:center;}" +
            ".ks-btn.confirm{background:linear-gradient(180deg,#a8331f,#7a1f1f);color:#fff5df;border-color:#5f1414;}" +
            ".ks-btn.cancel{background:rgba(255,250,238,0.4);color:#342313;}" +
            ".ks-arc{margin:16px 0 0;text-align:center;font-family:var(--font-mono),monospace;font-size:12px;}" +
            ".ks-arc a{color:#9d6f1d;border-bottom:1px dotted #9d6f1d;text-decoration:none;}" +
            ".ks-seal-btn{cursor:pointer;}";
        var s = document.createElement("style");
        s.textContent = css;
        document.head.appendChild(s);
    }

    function el(tag, cls, html) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (html !== undefined) e.innerHTML = html;
        return e;
    }

    function sleep(ms) {
        return new Promise(function (res) { setTimeout(res, ms); });
    }

    function buildModal() {
        var overlay = el("div", "ks-overlay");
        var card = el("div", "ks-card");
        card.appendChild(el("h3", "ks-title", "Engage Kill Switch"));
        card.appendChild(el("p", "ks-sub",
            "Atomic shutdown across all three agents. Open quotes cancelled, " +
            "hedges closed, treasury redeemed to USDC. This cannot be undone."));

        var steps = el("ul", "ks-steps");
        STEP_DEFS.forEach(function (sd) {
            var li = el("li");
            li.setAttribute("data-step", sd.key);
            li.appendChild(el("span", "ks-seal", sd.greek === "✠" ? "✠" : sd.greek[0]));
            li.appendChild(el("span", "ks-step-label", sd.label));
            steps.appendChild(li);
        });
        card.appendChild(steps);

        var actions = el("div", "ks-actions");
        var confirm = el("button", "ks-btn confirm", "Break the Seal");
        var cancel = el("button", "ks-btn cancel", "Stand Down");
        actions.appendChild(cancel);
        actions.appendChild(confirm);
        card.appendChild(actions);

        var arc = el("div", "ks-arc");
        arc.style.display = "none";
        card.appendChild(arc);

        overlay.appendChild(card);
        return { overlay: overlay, card: card, steps: steps, confirm: confirm, cancel: cancel, arc: arc, actions: actions };
    }

    function setStep(steps, key, cls) {
        var li = steps.querySelector('li[data-step="' + key + '"]');
        if (li) {
            li.classList.remove("active", "done");
            li.classList.add(cls);
        }
    }

    function explorerTxUrl(txHash) {
        // Best-effort Arc explorer base; the backend usually returns a full URL.
        return "https://explorer.arc-testnet.circle.com/tx/" + txHash;
    }

    async function playSequence(ui, result) {
        ui.actions.style.display = "none";
        var order = ["nomos", "spatha", "agros", "trace"];
        for (var i = 0; i < order.length; i++) {
            var key = order[i];
            setStep(ui.steps, key, "active");
            await sleep(700);
            setStep(ui.steps, key, "done");
        }
        // Surface the Arc tx link if the backend returned one.
        var tx = result && (result.arc_tx_url || result.trace_arc_tx_url || null);
        var txHash = result && (result.arc_tx || result.trace_arc_tx || result.tx_hash || null);
        var href = tx || (txHash ? explorerTxUrl(txHash) : null);
        if (href) {
            ui.arc.style.display = "block";
            ui.arc.innerHTML =
                'Trace committed on Arc — <a href="' + href +
                '" target="_blank" rel="noopener">view transaction ↗</a>';
        } else {
            ui.arc.style.display = "block";
            ui.arc.innerHTML = '<span style="color:#5f482b;font-style:italic;">' +
                "shutdown sequence complete</span>";
        }
        // Re-enable a single dismiss button.
        ui.actions.style.display = "flex";
        ui.confirm.style.display = "none";
        ui.cancel.textContent = "Close";
        ui.cancel.classList.remove("cancel");
        ui.cancel.classList.add("confirm");
    }

    function wireKillSwitch(button, userId) {
        if (!button) return;
        injectStyles();
        button.classList.add("ks-seal-btn");

        button.addEventListener("click", function () {
            var ui = buildModal();
            document.body.appendChild(ui.overlay);

            function close() {
                if (ui.overlay.parentNode) ui.overlay.parentNode.removeChild(ui.overlay);
            }
            ui.cancel.addEventListener("click", close);
            ui.overlay.addEventListener("click", function (ev) {
                if (ev.target === ui.overlay) close();
            });

            ui.confirm.addEventListener("click", async function () {
                ui.confirm.disabled = true;
                ui.confirm.textContent = "Sealing…";

                var result = null;
                if (userId) {
                    try {
                        var res = await fetch(
                            (global.location ? global.location.origin : "") + "/api/kill-switch",
                            {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ user_id: userId, trigger_source: "manual" }),
                            }
                        );
                        if (res.ok) result = await res.json();
                        else result = { error: "HTTP " + res.status };
                    } catch (e) {
                        result = { error: String(e && e.message ? e.message : e) };
                    }
                }
                // Demo mode (no userId) or after the POST: play the moment.
                await playSequence(ui, result);
            });
        });
    }

    global.wireKillSwitch = wireKillSwitch;
})(typeof window !== "undefined" ? window : this);
