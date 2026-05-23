// AKRITA — Personalize (the configuration page).
// Drives the Stratiotis/Strategos mode toggle, the three template cards
// (fetched from /api/templates), the NOMOS/SPATHA/AGROS controls, the live
// score-curve + WW-band previews, the Tier-D waitlist stub, and Save (PUT
// /api/instances/{id}). Vanilla JS, demo-safe when endpoints are absent.
//
// Depends on (loaded before this file): scorecurve.js, wwband.js.

(function () {
    "use strict";

    var API = window.location.origin;
    var $ = function (id) { return document.getElementById(id); };
    var MODE_KEY = "akrita.mode";          // "stratiotis" | "strategos"
    var DEFAULT_MODE = "stratiotis";

    // Resolve a user id: ?user= overrides localStorage; absence => demo mode.
    var params = new URLSearchParams(window.location.search);
    var userId = params.get("user") || localStorage.getItem("akrita.user") || null;
    if (userId) localStorage.setItem("akrita.user", userId);
    var readOnly = !userId;

    // In-memory config — the source of truth the controls hydrate from / write to.
    var config = {
        nomos: {
            quote_spread_bps_offset_to_max_spread: 0.5,
            inventory_target_pct: 0.5,
            max_position_per_market_usd: 250,
            daily_loss_limit_usd: 500,
            market_whitelist_tags: ["crypto"],
        },
        spatha: {
            hedge_band_risk_aversion: 1.0,
            hedge_underlying_whitelist: ["BTC", "ETH"],
            leverage_cap: 3,
            kill_switch_funding_apr_pct: 200,
        },
        agros: { tier: "B" },
        pro: { order_levels: 3, volatility_window: 60, hlp_passive: false },
    };

    var instanceIds = { nomos: null, spatha: null, agros: null };

    // ----- helpers --------------------------------------------------------

    function setText(id, txt) { var e = $(id); if (e) e.textContent = txt; }

    function getCheckedValues(name) {
        var out = [];
        document.querySelectorAll('input[name="' + name + '"]:checked').forEach(function (cb) {
            out.push(cb.value);
        });
        return out;
    }

    function setCheckedValues(name, values) {
        var set = {};
        (values || []).forEach(function (v) { set[String(v)] = true; });
        document.querySelectorAll('input[name="' + name + '"]').forEach(function (cb) {
            cb.checked = !!set[cb.value];
        });
    }

    // ----- mode toggle (Stratiotis / Strategos) ---------------------------

    function currentMode() {
        var m = localStorage.getItem(MODE_KEY);
        return m === "strategos" ? "strategos" : DEFAULT_MODE;
    }

    function applyMode(mode) {
        localStorage.setItem(MODE_KEY, mode);
        document.body.setAttribute("data-mode", mode);
        var toggle = $("mode-toggle");
        if (toggle) toggle.setAttribute("aria-checked", mode === "strategos" ? "true" : "false");
        setText("mode-readout", mode === "strategos"
            ? "Strategos — the general's full council"
            : "Stratiotis — the foot-soldier's essentials");
        // Pro placeholders are revealed only in Strategos.
        document.querySelectorAll(".pro-only").forEach(function (e) {
            e.style.display = mode === "strategos" ? "" : "none";
        });
    }

    function wireModeToggle() {
        var toggle = $("mode-toggle");
        if (!toggle) return;
        toggle.addEventListener("click", function () {
            applyMode(currentMode() === "strategos" ? "stratiotis" : "strategos");
        });
        toggle.addEventListener("keydown", function (ev) {
            if (ev.key === " " || ev.key === "Enter") {
                ev.preventDefault();
                applyMode(currentMode() === "strategos" ? "stratiotis" : "strategos");
            }
        });
        applyMode(currentMode());
    }

    // ----- previews (score curve + WW band) -------------------------------

    function refreshScoreCurve() {
        var host = $("score-curve");
        if (host && typeof window.renderScoreCurve === "function") {
            window.renderScoreCurve(host, config.nomos.quote_spread_bps_offset_to_max_spread);
        }
    }

    function refreshWWBand(delta) {
        var host = $("ww-band");
        if (host && typeof window.renderWWBand === "function") {
            if (delta === undefined) delta = window.__akritaDemoDelta || 0.15;
            window.renderWWBand(host, config.spatha.hedge_band_risk_aversion, delta);
        }
    }

    // ----- slider/control wiring ------------------------------------------

    // Bind a range input to a config path, updating a readout + optional hook.
    function bindRange(inputId, readoutId, obj, key, fmt, onChange) {
        var input = $(inputId);
        if (!input) return;
        function sync() {
            var v = parseFloat(input.value);
            obj[key] = v;
            if (readoutId) setText(readoutId, fmt ? fmt(v) : String(v));
            if (onChange) onChange(v);
        }
        input.addEventListener("input", sync);
        // initialise readout from current config
        input.value = obj[key];
        sync();
    }

    function wireControls() {
        // NOMOS
        bindRange("nomos-offset", "nomos-offset-val", config.nomos,
            "quote_spread_bps_offset_to_max_spread",
            function (v) { return v.toFixed(2); },
            refreshScoreCurve);
        bindRange("nomos-inventory", "nomos-inventory-val", config.nomos,
            "inventory_target_pct",
            function (v) { return (v * 100).toFixed(0) + "%"; });
        bindRange("nomos-maxpos", "nomos-maxpos-val", config.nomos,
            "max_position_per_market_usd",
            function (v) { return "$" + v.toFixed(0); });
        bindRange("nomos-dailyloss", "nomos-dailyloss-val", config.nomos,
            "daily_loss_limit_usd",
            function (v) { return "$" + v.toFixed(0); });

        var tagsBox = $("nomos-tags");
        if (tagsBox) {
            tagsBox.addEventListener("change", function () {
                config.nomos.market_whitelist_tags = getCheckedValues("market_whitelist_tags");
            });
        }

        // SPATHA
        bindRange("spatha-aversion", "spatha-aversion-val", config.spatha,
            "hedge_band_risk_aversion",
            function (v) { return v.toFixed(1); },
            function () { refreshWWBand(); });
        bindRange("spatha-leverage", "spatha-leverage-val", config.spatha,
            "leverage_cap",
            function (v) { return v.toFixed(0) + "×"; });
        bindRange("spatha-funding", "spatha-funding-val", config.spatha,
            "kill_switch_funding_apr_pct",
            function (v) { return v.toFixed(0) + "%"; });

        var underBox = $("spatha-underlying");
        if (underBox) {
            underBox.addEventListener("change", function () {
                config.spatha.hedge_underlying_whitelist = getCheckedValues("hedge_underlying_whitelist");
            });
        }

        // AGROS tier
        document.querySelectorAll('input[name="agros_tier"]').forEach(function (radio) {
            radio.addEventListener("change", function () {
                if (radio.checked) {
                    config.agros.tier = radio.value;
                    applyAgrosTier(radio.value);
                }
            });
        });

        // Pro placeholders (Strategos-only).
        bindRange("pro-order-levels", "pro-order-levels-val", config.pro,
            "order_levels", function (v) { return v.toFixed(0); });
        bindRange("pro-vol-window", "pro-vol-window-val", config.pro,
            "volatility_window", function (v) { return v.toFixed(0) + "s"; });
        var hlp = $("pro-hlp-passive");
        if (hlp) {
            hlp.addEventListener("change", function () { config.pro.hlp_passive = hlp.checked; });
        }
    }

    function applyAgrosTier(tier) {
        // Tier C reveals the EIP-712 sUSDe cooldown acceptance.
        var consent = $("agros-consent");
        if (consent) consent.style.display = tier === "C" ? "" : "none";
    }

    // Push the in-memory config into the DOM controls (used after a template
    // is selected, or on initial hydration).
    function syncControlsFromConfig() {
        var map = [
            ["nomos-offset", config.nomos.quote_spread_bps_offset_to_max_spread],
            ["nomos-inventory", config.nomos.inventory_target_pct],
            ["nomos-maxpos", config.nomos.max_position_per_market_usd],
            ["nomos-dailyloss", config.nomos.daily_loss_limit_usd],
            ["spatha-aversion", config.spatha.hedge_band_risk_aversion],
            ["spatha-leverage", config.spatha.leverage_cap],
            ["spatha-funding", config.spatha.kill_switch_funding_apr_pct],
            ["pro-order-levels", config.pro.order_levels],
            ["pro-vol-window", config.pro.volatility_window],
        ];
        map.forEach(function (pair) {
            var el = $(pair[0]);
            if (el && pair[1] !== undefined && pair[1] !== null) {
                el.value = pair[1];
                el.dispatchEvent(new Event("input"));
            }
        });
        setCheckedValues("market_whitelist_tags", config.nomos.market_whitelist_tags);
        setCheckedValues("hedge_underlying_whitelist", config.spatha.hedge_underlying_whitelist);

        var tierRadio = document.querySelector('input[name="agros_tier"][value="' + config.agros.tier + '"]');
        if (tierRadio) { tierRadio.checked = true; }
        applyAgrosTier(config.agros.tier);

        var hlp = $("pro-hlp-passive");
        if (hlp) hlp.checked = !!config.pro.hlp_passive;

        refreshScoreCurve();
        refreshWWBand();
    }

    // ----- templates ------------------------------------------------------

    function applyTemplate(tpl) {
        if (!tpl) return;
        var n = tpl.nomos_params || {};
        var s = tpl.spatha_params || {};
        Object.keys(n).forEach(function (k) { if (k in config.nomos) config.nomos[k] = n[k]; });
        Object.keys(s).forEach(function (k) { if (k in config.spatha) config.spatha[k] = s[k]; });
        if (tpl.agros_tier) config.agros.tier = tpl.agros_tier;
        syncControlsFromConfig();
    }

    function renderTemplateCards(templates) {
        var host = $("template-cards");
        if (!host) return;

        // Friendly display names mapped to the three required cards; if the
        // backend supplies its own display_name we honour it.
        host.innerHTML = "";
        templates.forEach(function (tpl) {
            var card = document.createElement("button");
            card.type = "button";
            card.className = "tpl-card";
            card.setAttribute("data-key", tpl.key);
            card.innerHTML =
                '<span class="tpl-flower" aria-hidden="true">✾</span>' +
                "<h3>" + esc(tpl.display_name || tpl.key) + "</h3>" +
                '<p class="tpl-tier">AGROS Tier ' + esc(tpl.agros_tier || "—") + "</p>" +
                '<p class="tpl-desc">' + esc(templateBlurb(tpl)) + "</p>";
            card.addEventListener("click", function () {
                selectCard(card);
                applyTemplate(tpl);
            });
            host.appendChild(card);
            if (tpl.is_default) card.setAttribute("data-default", "true");
        });
    }

    function templateBlurb(tpl) {
        var key = (tpl.key || "").toLowerCase();
        var name = (tpl.display_name || "").toLowerCase();
        if (key.indexOf("conserv") >= 0 || name.indexOf("conservative") >= 0)
            return "Tight risk, wide bands, modest size. The king who keeps the keep.";
        if (key.indexOf("aggress") >= 0 || name.indexOf("aggressive") >= 0)
            return "Narrow bands, higher leverage, larger positions. The sovereign who marches.";
        return "A measured stance between caution and conquest. The counsel that balances.";
    }

    function selectCard(card) {
        document.querySelectorAll(".tpl-card").forEach(function (c) {
            c.classList.toggle("selected", c === card);
        });
    }

    function esc(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
        });
    }

    async function loadTemplates() {
        var fallback = [
            { key: "conservative_king", display_name: "The Conservative King",
              agros_tier: "A", is_default: false,
              nomos_params: { quote_spread_bps_offset_to_max_spread: 0.75, inventory_target_pct: 0.4, max_position_per_market_usd: 100, daily_loss_limit_usd: 200, market_whitelist_tags: ["crypto"] },
              spatha_params: { hedge_band_risk_aversion: 5.0, hedge_underlying_whitelist: ["BTC"], leverage_cap: 2, kill_switch_funding_apr_pct: 120 } },
            { key: "balanced_counsel", display_name: "The Balanced Counsel",
              agros_tier: "B", is_default: true,
              nomos_params: { quote_spread_bps_offset_to_max_spread: 0.5, inventory_target_pct: 0.5, max_position_per_market_usd: 250, daily_loss_limit_usd: 500, market_whitelist_tags: ["crypto", "sports"] },
              spatha_params: { hedge_band_risk_aversion: 1.0, hedge_underlying_whitelist: ["BTC", "ETH"], leverage_cap: 3, kill_switch_funding_apr_pct: 200 } },
            { key: "aggressive_sovereign", display_name: "The Aggressive Sovereign",
              agros_tier: "C", is_default: false,
              nomos_params: { quote_spread_bps_offset_to_max_spread: 0.25, inventory_target_pct: 0.65, max_position_per_market_usd: 750, daily_loss_limit_usd: 3000, market_whitelist_tags: ["crypto", "sports", "politics"] },
              spatha_params: { hedge_band_risk_aversion: 0.4, hedge_underlying_whitelist: ["BTC", "ETH", "SOL"], leverage_cap: 8, kill_switch_funding_apr_pct: 400 } },
        ];
        var templates = fallback;
        try {
            var res = await fetch(API + "/api/templates");
            if (res.ok) {
                var data = await res.json();
                if (data && Array.isArray(data.templates) && data.templates.length) {
                    templates = data.templates;
                }
            }
        } catch (e) { /* demo-safe: keep fallback */ }

        renderTemplateCards(templates);

        // Pre-fill silently from the default template (do not force a choice).
        var def = templates.filter(function (t) { return t.is_default; })[0] || templates[1] || templates[0];
        if (def) applyTemplate(def);
    }

    // ----- existing instances --------------------------------------------

    async function loadInstances() {
        if (readOnly) return;
        var arches = ["nomos", "spatha", "agros"];
        for (var i = 0; i < arches.length; i++) {
            var arch = arches[i];
            try {
                var res = await fetch(API + "/api/instances?archetype=" + arch + "&enabled=true");
                if (!res.ok) continue;
                var data = await res.json();
                var list = (data && data.instances) || [];
                var mine = list.filter(function (x) { return String(x.user_id) === String(userId); });
                var inst = mine[0] || list[0];
                if (!inst) continue;
                instanceIds[arch] = inst.id;
                var p = inst.params || {};
                if (arch === "agros" && p.tier) config.agros.tier = p.tier;
                else {
                    Object.keys(p).forEach(function (k) {
                        if (config[arch] && k in config[arch]) config[arch][k] = p[k];
                    });
                }
            } catch (e) { /* demo-safe */ }
        }
        syncControlsFromConfig();
    }

    // ----- consent (Tier C EIP-712 sUSDe cooldown) ------------------------

    function wireConsent() {
        var btn = $("agros-consent-btn");
        if (!btn) return;
        btn.addEventListener("click", async function () {
            if (readOnly) {
                flash("agros-consent-status", "Demo mode — connect an operator to sign.");
                return;
            }
            btn.disabled = true;
            try {
                var res = await fetch(API + "/api/onboarding/consent/susde", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ user_id: userId, consent_type: "susde_cooldown", agreed: true }),
                });
                flash("agros-consent-status", res.ok ? "Cooldown acceptance signed ✓" : "Could not record consent.");
            } catch (e) {
                flash("agros-consent-status", "Consent endpoint unavailable (stub).");
            }
            btn.disabled = false;
        });
    }

    function flash(id, msg) {
        var e = $(id);
        if (e) { e.textContent = msg; e.style.display = "block"; }
    }

    // ----- waitlist (Tier D stub) -----------------------------------------

    function wireWaitlist() {
        var btn = $("waitlist-btn");
        var input = $("waitlist-email");
        if (!btn || !input) return;
        btn.addEventListener("click", async function () {
            var email = (input.value || "").trim();
            if (!email || email.indexOf("@") < 0) {
                flash("waitlist-status", "Enter a valid email.");
                return;
            }
            try {
                var res = await fetch(API + "/api/waitlist", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ email: email, tier: "D" }),
                });
                if (res.ok) flash("waitlist-status", "You're on the list — we'll write after the hackathon.");
                else throw new Error("HTTP " + res.status);
            } catch (e) {
                console.log("[waitlist] (stub) captured:", email);
                flash("waitlist-status", "Noted (stub) — " + esc(email));
            }
            input.value = "";
        });
    }

    // ----- save -----------------------------------------------------------

    function paramsFor(arch) {
        if (arch === "nomos") return Object.assign({}, config.nomos);
        if (arch === "spatha") return Object.assign({}, config.spatha);
        if (arch === "agros") return { tier: config.agros.tier };
        return {};
    }

    async function save() {
        var status = $("save-status");
        if (readOnly) {
            if (status) { status.textContent = "Read-only demo — append ?user=<id> to save."; status.style.display = "block"; }
            return;
        }
        if (status) { status.textContent = "Saving…"; status.style.display = "block"; }

        var arches = ["nomos", "spatha", "agros"];
        var oks = 0, fails = 0;
        for (var i = 0; i < arches.length; i++) {
            var arch = arches[i];
            var id = instanceIds[arch];
            var body = { params: paramsFor(arch), enabled: true };
            try {
                var url = id != null
                    ? API + "/api/instances/" + encodeURIComponent(id)
                    : API + "/api/onboarding/instance";
                var payload = id != null ? body : Object.assign({ user_id: userId, archetype: arch }, body);
                var res = await fetch(url, {
                    method: id != null ? "PUT" : "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
                if (res.ok) oks++; else fails++;
            } catch (e) { fails++; }
        }
        if (status) {
            status.textContent = fails === 0
                ? "Saved " + oks + " agent configs ✓"
                : "Saved " + oks + ", " + fails + " failed (endpoint may be pending).";
        }
    }

    function wireSave() {
        var btn = $("save-btn");
        if (btn) btn.addEventListener("click", save);
    }

    // ----- demo delta drift for the WW band preview -----------------------

    function startDeltaDrift() {
        // Gentle ambient delta so the band preview feels alive even at rest.
        var t = 0;
        setInterval(function () {
            t += 0.4;
            window.__akritaDemoDelta = Math.sin(t) * 0.55 + Math.sin(t * 0.37) * 0.25;
            refreshWWBand(window.__akritaDemoDelta);
        }, 1200);
    }

    // ----- boot -----------------------------------------------------------

    document.addEventListener("DOMContentLoaded", function () {
        if (readOnly) {
            var banner = $("demo-banner");
            if (banner) banner.style.display = "block";
        } else {
            setText("operator-id", "operator " + userId);
        }
        wireModeToggle();
        wireControls();
        wireConsent();
        wireWaitlist();
        wireSave();
        loadTemplates().then(loadInstances);
        startDeltaDrift();
    });
})();
