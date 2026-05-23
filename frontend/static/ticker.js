// AKRITA — USYC yield ticker.
// Given a starting USDC balance and a 7-day APY, increment a displayed
// balance at a per-second yield rate using requestAnimationFrame, so idle
// treasury visibly "farms while it is not fighting".
//
//   startYieldTicker(el, balanceUsd, apyPct)
//     el         — element whose textContent we update with the live balance.
//     balanceUsd — starting balance in USD (the principal that earns yield).
//     apyPct     — annual percentage yield. Accepts either a fraction
//                  (e.g. 0.043 for 4.3%) or whole-percent (e.g. 4.3); both
//                  are normalised.
//
// Returns a controller: { stop(), update(balanceUsd, apyPct), rate }.
// Re-calling startYieldTicker on the same element cancels the prior loop.

(function (global) {
    "use strict";

    var SECONDS_PER_YEAR = 365 * 24 * 60 * 60;
    var registry = (global.__akritaTickers = global.__akritaTickers || new WeakMap());

    function normalizeApy(apyPct) {
        var a = Number(apyPct);
        if (!isFinite(a) || a <= 0) return 0;
        // Heuristic: values > 1 are treated as whole-percent (e.g. 4.3 -> 0.043).
        return a > 1 ? a / 100 : a;
    }

    function fmtUsd(v) {
        if (!isFinite(v)) v = 0;
        return "$" + v.toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    function startYieldTicker(el, balanceUsd, apyPct) {
        if (!el) return { stop: function () {}, update: function () {}, rate: 0 };

        // Cancel any existing ticker on this element.
        var prior = registry.get(el);
        if (prior && prior.raf) cancelAnimationFrame(prior.raf);

        var ctrl = {
            balance: Number(balanceUsd) || 0,
            apy: normalizeApy(apyPct),
            raf: null,
            running: true,
            last: null,
        };
        // Per-second accrual rate (continuous approximation).
        ctrl.rate = (ctrl.balance * ctrl.apy) / SECONDS_PER_YEAR;

        function tick(now) {
            if (!ctrl.running) return;
            if (ctrl.last === null) ctrl.last = now;
            var dt = (now - ctrl.last) / 1000; // seconds
            ctrl.last = now;
            ctrl.balance += ctrl.rate * dt;
            el.textContent = fmtUsd(ctrl.balance);
            ctrl.raf = requestAnimationFrame(tick);
        }

        // Paint immediately so the element isn't blank before the first frame.
        el.textContent = fmtUsd(ctrl.balance);

        // Guard: requestAnimationFrame may be absent in non-browser contexts.
        if (typeof requestAnimationFrame === "function") {
            ctrl.raf = requestAnimationFrame(tick);
        }

        var controller = {
            get rate() { return ctrl.rate; },
            stop: function () {
                ctrl.running = false;
                if (ctrl.raf) cancelAnimationFrame(ctrl.raf);
            },
            update: function (newBalance, newApy) {
                if (newBalance !== undefined && newBalance !== null && isFinite(Number(newBalance))) {
                    ctrl.balance = Number(newBalance);
                }
                if (newApy !== undefined && newApy !== null) {
                    ctrl.apy = normalizeApy(newApy);
                }
                ctrl.rate = (ctrl.balance * ctrl.apy) / SECONDS_PER_YEAR;
            },
        };

        registry.set(el, ctrl);
        return controller;
    }

    global.startYieldTicker = startYieldTicker;
})(typeof window !== "undefined" ? window : this);
