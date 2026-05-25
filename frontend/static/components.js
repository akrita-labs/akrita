(function () {
    "use strict";

    var STORAGE_USER = "akrita.user";
    var SANDBOX_USER = "sandbox-operator";

    var GLOSSARY = {
        NOMOS: {
            plain: "Claim Issuer",
            def: "The signing agent that reads on-chain rug signals — stablecoin freezes, token-security failures — and issues a verifiable rug-risk claim.",
        },
        SPATHA: {
            plain: "Risk Sentinel",
            def: "The risk agent that stakes the bond market for or against a claim, containing exposure at the boundary.",
        },
        AGROS: {
            plain: "Treasury",
            def: "The treasury agent that keeps idle bond collateral productive between resolutions.",
        },
        AKRITAI: {
            plain: "Frontier Keepers",
            def: "The three-agent AKRITA system: rug-risk claims, bond settlement, and treasury.",
        },
        USYC: {
            plain: "Tokenized Treasury Yield",
            def: "The yield-bearing asset used by AGROS for idle treasury capital.",
        },
        ClaimRegistry: {
            plain: "On-chain Claim Registry",
            def: "The Arc contract that records signed rug-risk claims and their two-sided USDC bond pools.",
        },
        pUSD: {
            plain: "Operating Margin",
            def: "The margin asset needed before the gated keeper execution path can leave the sandbox gate.",
        },
        STRATIOTIS: {
            plain: "Essentials Mode",
            def: "The simpler configuration mode for default keeper operation.",
        },
        STRATEGOS: {
            plain: "Pro Mode",
            def: "The advanced configuration mode for expanded keeper controls.",
        },
        "Arc testnet": {
            plain: "Live Settlement Network",
            def: "The public test network where trace anchors and risk verdicts are committed.",
        },
        "BuilderRegistry": {
            plain: "On-chain Builder Registry",
            def: "The Arc contract that associates operators with builder codes.",
        },
        "TraceRegistry": {
            plain: "On-chain Trace Registry",
            def: "The Arc contract that stores decision trace hashes and IPFS CIDs.",
        },
    };

    // Dashboard / Keeper app navigation. The public homepage header is authored
    // statically in index.html and is intentionally NOT driven by this array.
    var NAV = [
        { label: "Oracle", href: "/app/oracle", group: "Trust Layer" },
        { label: "Keeper Overview", href: "/app/dashboard", group: "Operation" },
        { label: "Traces", href: "/app/trace", group: "Trust Layer" },
        { label: "Operators", href: "/app/leaderboard", group: "Ecosystem" },
        { label: "Builder Profile", href: "/app/builder", group: "Ecosystem" },
        { label: "Strategy", href: "/app/personalize", group: "Operation" },
    ];

    var PAGE_CONTEXT = {
        "/app/oracle": "Rugpull Oracle",
        "/app/dashboard": "Operation Console",
        "/app/leaderboard": "Ecosystem Board",
        "/app/personalize": "Configuration Sandbox",
        "/app/builder": "Builder Attribution",
        "/app/trace": "Trust Layer",
        "/about": "System Map",
        "/app/akritai": "Operator Profile",
    };

    function esc(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
        });
    }

    function featureEnabled(name) {
        var raw = document.body ? document.body.getAttribute("data-ak") || "" : "";
        var parts = raw.split(/[\s,]+/).filter(Boolean);
        return parts.indexOf(name) >= 0;
    }

    function glossTitle(term) {
        var g = GLOSSARY[term];
        if (!g) return term;
        return term + " / " + g.plain + " - " + g.def;
    }

    function glossNode(term, text) {
        var abbr = document.createElement("abbr");
        abbr.className = "ak-gloss ak-tooltip";
        abbr.setAttribute("data-term", term);
        abbr.setAttribute("data-tip", glossTitle(term));
        abbr.setAttribute("title", glossTitle(term));
        abbr.setAttribute("tabindex", "0");
        abbr.textContent = text || term;
        return abbr;
    }

    function glossHTML(term, text) {
        return '<abbr class="ak-gloss ak-tooltip" data-term="' + esc(term) +
            '" data-tip="' + esc(glossTitle(term)) + '" title="' + esc(glossTitle(term)) +
            '" tabindex="0">' + esc(text || term) + "</abbr>";
    }

    function dualLabel(key) {
        var g = GLOSSARY[key];
        if (!g) return esc(key);
        return glossHTML(key) + " / " + esc(g.plain);
    }

    function pill(state, opts) {
        opts = opts || {};
        var normalized = String(state || "").toLowerCase();
        var label = opts.label || normalized.toUpperCase();
        var span = document.createElement("span");
        span.className = "ak-pill ak-pill-" + normalized + (opts.className ? " " + opts.className : "");
        span.textContent = label;
        if (opts.tooltip) {
            span.classList.add("ak-tooltip");
            span.setAttribute("data-tip", opts.tooltip);
            span.setAttribute("title", opts.tooltip);
            span.setAttribute("tabindex", "0");
        }
        if (opts.ariaLabel) span.setAttribute("aria-label", opts.ariaLabel);
        return span;
    }

    function pillHTML(state, opts) {
        return pill(state, opts).outerHTML;
    }

    function termBoundary(text, index, term) {
        var before = index > 0 ? text.charAt(index - 1) : "";
        var after = index + term.length < text.length ? text.charAt(index + term.length) : "";
        var word = /[A-Za-z0-9_]/;
        return !word.test(before) && !word.test(after);
    }

    function findNextTerm(text, used, terms) {
        var best = null;
        terms.forEach(function (term) {
            if (used[term]) return;
            var start = 0;
            var idx = text.indexOf(term, start);
            while (idx >= 0) {
                if (termBoundary(text, idx, term)) {
                    if (!best || idx < best.index || (idx === best.index && term.length > best.term.length)) {
                        best = { term: term, index: idx };
                    }
                    return;
                }
                start = idx + term.length;
                idx = text.indexOf(term, start);
            }
        });
        return best;
    }

    function shouldSkipTextNode(node) {
        if (!node || !node.nodeValue || !node.nodeValue.trim()) return true;
        var parent = node.parentElement;
        if (!parent) return true;
        return !!parent.closest("abbr.ak-gloss, script, style, pre, code, kbd, samp, textarea, input, select, button");
    }

    function glossifyHost(host, used, terms) {
        var walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT, {
            acceptNode: function (node) {
                return shouldSkipTextNode(node) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
            },
        });
        var nodes = [];
        var node;
        while ((node = walker.nextNode())) nodes.push(node);

        nodes.forEach(function (textNode) {
            var text = textNode.nodeValue;
            var match = findNextTerm(text, used, terms);
            if (!match) return;

            var frag = document.createDocumentFragment();
            var cursor = 0;
            while (match) {
                if (match.index > cursor) frag.appendChild(document.createTextNode(text.slice(cursor, match.index)));
                frag.appendChild(glossNode(match.term, match.term));
                used[match.term] = true;
                cursor = match.index + match.term.length;
                match = findNextTerm(text.slice(cursor), used, terms);
                if (match) match.index += cursor;
            }
            if (cursor < text.length) frag.appendChild(document.createTextNode(text.slice(cursor)));
            textNode.parentNode.replaceChild(frag, textNode);
        });
    }

    function glossifyAll(root) {
        var scope = root || document;
        var hosts = [];
        if (scope.nodeType === 1 && scope.matches && scope.matches("[data-glossify]")) {
            hosts = [scope];
        } else if (scope.querySelectorAll) {
            hosts = Array.prototype.slice.call(scope.querySelectorAll("[data-glossify]"));
        }
        if (!hosts.length && scope !== document) hosts = [scope];
        var terms = Object.keys(GLOSSARY).sort(function (a, b) { return b.length - a.length; });
        var used = {};
        hosts.forEach(function (host) { glossifyHost(host, used, terms); });
    }

    function normalizedPath() {
        var path = window.location.pathname.replace(/\/+$/, "") || "/";
        path = path.replace(/\.html$/, "");
        if (path.indexOf("/app/trace/") === 0) return "/app/trace";
        if (path.indexOf("/app/akritai/") === 0) return "/app/akritai";
        return path;
    }

    function isActive(item) {
        if (item.external) return false;
        var here = normalizedPath();
        var itemPath = item.href.replace(/\/+$/, "") || "/";
        if (itemPath === "/app/trace" && here === "/app/trace") return true;
        if (itemPath === "/app/personalize" && here === "/app/personalize") return true;
        return here === itemPath;
    }

    function renderNav(nav) {
        nav.innerHTML = "";
        NAV.forEach(function (item) {
            // No decorative dot separators — spacing alone divides nav items.
            var a = document.createElement("a");
            a.href = item.href;
            a.textContent = item.label;
            a.setAttribute("data-group", item.group);
            if (item.external) {
                a.target = "_blank";
                a.rel = "noopener";
            }
            if (isActive(item)) a.classList.add("is-active");
            nav.appendChild(a);
        });
    }

    function getUser() {
        try { return window.localStorage && localStorage.getItem(STORAGE_USER); }
        catch (e) { return null; }
    }

    function setUser(userId) {
        try {
            if (window.localStorage) localStorage.setItem(STORAGE_USER, userId);
        } catch (e) {}
    }

    // Wallet connection is requested only when a state-changing action needs an
    // operator identity (save strategy, register builder, fund keeper, edit risk
    // parameters, copy config). There is intentionally no persistent "connect"
    // button in the page chrome. Returns the resolved user id.
    function connectWallet(opts) {
        opts = opts || {};
        var userId = getUser();
        if (!userId) {
            userId = opts.userId || SANDBOX_USER;
            setUser(userId);
        }
        window.dispatchEvent(new CustomEvent("akrita:user", { detail: { user_id: userId } }));
        return userId;
    }

    function mountNav() {
        Array.prototype.forEach.call(document.querySelectorAll(".home-nav, .dashboard-nav"), renderNav);

        // Status badge only — no wallet button. Wallet is requested on action.
        var dashSlot = document.querySelector(".dashboard-live");
        if (dashSlot) {
            dashSlot.innerHTML = "";
            dashSlot.appendChild(pill("live", {
                label: "Live: Arc Testnet",
                tooltip: "Decisions, traces and risk verdicts are live on Arc testnet. Execution may be gated.",
            }));
            dashSlot.classList.add("ak-nav-actions");
            return;
        }

        var enter = document.querySelector(".home-enter");
        if (enter && enter.parentNode) {
            var actions = document.createElement("div");
            actions.className = "ak-nav-actions";
            actions.appendChild(pill("live", {
                label: "Live: Arc Testnet",
                tooltip: "Decisions, traces and risk verdicts are live on Arc testnet. Execution may be gated.",
            }));
            enter.parentNode.replaceChild(actions, enter);
        }
    }

    function mountContextStrip() {
        if (document.body.classList.contains("home-page")) return;
        if (document.querySelector(".ak-context-strip")) return;

        var path = normalizedPath();
        var title = PAGE_CONTEXT[path] || "AKRITA Console";
        var strip = document.createElement("section");
        strip.className = "ak-context-strip";
        strip.setAttribute("aria-label", "Data status");
        strip.innerHTML =
            '<div class="ak-context-title">' + esc(title) + "</div>" +
            '<div class="ak-context-pills">' +
            pillHTML("live", {
                label: "LIVE trace & risk",
                tooltip: "Decisions, trace anchors, risk verdicts, treasury balances and leaderboard volume are read from live endpoints.",
            }) +
            pillHTML("gated", {
                label: "GATED execution",
                tooltip: "Polymarket fills, Hyperliquid hedges and some treasury actions can be blocked by funding, margin, signer, or allowlist gates.",
            }) +
            pillHTML("demo", {
                label: "DEMO accounts",
                tooltip: "Seeded non-system operators are demo accounts unless the row is AKRITA House.",
            }) +
            "</div>";

        var anchor = document.querySelector(".dashboard-nav") || document.querySelector(".home-header");
        if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(strip, anchor.nextSibling);
    }

    function mountGlossaryDrawer() {
        if (document.getElementById("ak-glossary-drawer")) return;

        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "ak-glossary-toggle";
        btn.setAttribute("aria-expanded", "false");
        btn.setAttribute("aria-controls", "ak-glossary-drawer");
        btn.textContent = "Glossary of the Empire";

        var drawer = document.createElement("aside");
        drawer.id = "ak-glossary-drawer";
        drawer.className = "ak-glossary-drawer";
        drawer.setAttribute("aria-hidden", "true");
        drawer.innerHTML =
            '<div class="ak-glossary-head">' +
            '<h2>Glossary of the Empire</h2>' +
            '<button type="button" aria-label="Close glossary">x</button>' +
            "</div>" +
            '<dl>' + Object.keys(GLOSSARY).map(function (term) {
                var g = GLOSSARY[term];
                return "<dt>" + esc(term) + " / " + esc(g.plain) + "</dt><dd>" + esc(g.def) + "</dd>";
            }).join("") + "</dl>";

        function setOpen(open) {
            drawer.classList.toggle("is-open", open);
            drawer.setAttribute("aria-hidden", open ? "false" : "true");
            btn.setAttribute("aria-expanded", open ? "true" : "false");
        }

        btn.addEventListener("click", function () { setOpen(!drawer.classList.contains("is-open")); });
        drawer.querySelector("button").addEventListener("click", function () { setOpen(false); btn.focus(); });
        document.addEventListener("keydown", function (ev) {
            if (ev.key === "Escape") setOpen(false);
        });

        document.body.appendChild(btn);
        document.body.appendChild(drawer);
    }

    function boot() {
        if (!document.body) return;
        if (featureEnabled("nav")) mountNav();
        if (featureEnabled("pills")) mountContextStrip();
        if (featureEnabled("glossary")) {
            // Inline term tooltips only — the floating "Glossary of the Empire"
            // drawer button was removed to reduce chrome clutter.
            glossifyAll(document.querySelector("main") || document.body);
        }
    }

    window.AKRITA = {
        GLOSSARY: GLOSSARY,
        NAV: NAV,
        pill: pill,
        pillHTML: pillHTML,
        dualLabel: dualLabel,
        glossifyAll: glossifyAll,
        mountNav: mountNav,
        mountContextStrip: mountContextStrip,
        mountGlossaryDrawer: mountGlossaryDrawer,
        sandboxUser: SANDBOX_USER,
        connectWallet: connectWallet,
        requireWallet: connectWallet,
        getUser: getUser,
    };

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
    else boot();
})();
