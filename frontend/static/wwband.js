// AKRITA — SPATHA no-transaction band (Whalley–Wilmott style corridor).
// Renders a delta-neutral target line at zero with a "no-transaction band"
// whose half-width scales inversely with the risk-aversion `a`: low aversion
// => wide band (SPATHA tolerates drift before it cuts); high aversion =>
// narrow band (it hedges aggressively). When |currentDelta| breaches the
// band, the corridor flips to an "active" crimson state and SPATHA "draws".
//
//   renderWWBand(canvasEl, a, currentDelta)
//     canvasEl     — container element; an <svg> is injected.
//     a            — risk aversion in [0.1, 10].
//     currentDelta — current portfolio delta (normalised; 0 = neutral). If
//                    omitted, a gentle ambient value is used for the preview.
//
// Returns true when the band is breached (active), false otherwise.

(function (global) {
    "use strict";

    var GOLD = "#9d6f1d";
    var INK = "#3a2d1a";
    var RULE = "rgba(124, 82, 25, 0.5)";
    var CRIMSON = "#8a2d1c";
    var GREEN = "#2c6040";
    var BAND_CALM = "rgba(44, 96, 64, 0.16)";
    var BAND_HOT = "rgba(138, 45, 28, 0.22)";

    function clamp(x, lo, hi) {
        x = Number(x);
        if (!isFinite(x)) return lo;
        return x < lo ? lo : x > hi ? hi : x;
    }

    // Half-width of the no-transaction band as a fraction of the plot half-
    // height. Inverse in `a`: ~0.9 at a=0.1, ~0.08 at a=10. The cube-root
    // shaping mirrors the WW band's (cost / a)^(1/3) dependence.
    function bandHalfWidth(a) {
        a = clamp(a, 0.1, 10);
        var hw = 0.42 / Math.cbrt(a);   // a=1 -> 0.42, a=8 -> 0.21, a=0.125 -> 0.84
        return clamp(hw, 0.05, 0.92);
    }

    function renderWWBand(el, a, currentDelta) {
        if (!el) return false;
        a = clamp(a, 0.1, 10);
        if (currentDelta === undefined || currentDelta === null) currentDelta = 0.0;
        var d = clamp(currentDelta, -1, 1);

        var hw = bandHalfWidth(a);
        var active = Math.abs(d) > hw;

        var W = 320, H = 180;
        var padL = 30, padR = 14, padT = 16, padB = 22;
        var plotW = W - padL - padR;
        var plotH = H - padT - padB;
        var midY = padT + plotH / 2;

        // Map delta in [-1,1] to y (inverted: +delta above midline).
        var dy = function (val) { return midY - clamp(val, -1, 1) * (plotH / 2); };

        var topY = dy(hw);
        var botY = dy(-hw);
        var deltaY = dy(d);

        var bandFill = active ? BAND_HOT : BAND_CALM;
        var bandEdge = active ? CRIMSON : GREEN;
        var markerColor = active ? CRIMSON : GREEN;

        // A drifting delta path across the plot, ending at the current delta.
        var pts = [];
        var N = 48;
        for (var i = 0; i <= N; i++) {
            var t = i / N;
            // gentle wander converging to current delta
            var wander = Math.sin(t * 6.3 + a) * hw * 0.5 * (1 - t);
            var val = wander * (1 - t) + d * t;
            pts.push((padL + t * plotW).toFixed(1) + "," + dy(val).toFixed(1));
        }

        var caption = active
            ? '<text x="' + (W / 2) + '" y="' + (H - 5) +
              '" fill="' + CRIMSON + '" font-size="10" text-anchor="middle" ' +
              'font-style="italic">⚔ SPATHA draws its sword</text>'
            : '<text x="' + (W / 2) + '" y="' + (H - 5) +
              '" fill="' + GREEN + '" font-size="9" text-anchor="middle" ' +
              'font-style="italic">within the band · holding</text>';

        var svg =
            '<svg viewBox="0 0 ' + W + " " + H + '" width="100%" role="img" ' +
            'aria-label="SPATHA no-transaction band, ' +
            (active ? "breached" : "holding") + '" ' +
            'style="display:block;font-family:var(--font-mono),monospace;">' +
            // band corridor
            '<rect x="' + padL + '" y="' + topY.toFixed(1) +
            '" width="' + plotW + '" height="' + (botY - topY).toFixed(1) +
            '" fill="' + bandFill + '" stroke="' + bandEdge +
            '" stroke-width="1" stroke-dasharray="4 3" />' +
            // delta-neutral target line
            '<line x1="' + padL + '" y1="' + midY.toFixed(1) +
            '" x2="' + (W - padR) + '" y2="' + midY.toFixed(1) +
            '" stroke="' + GOLD + '" stroke-width="1" />' +
            '<text x="' + (W - padR) + '" y="' + (midY - 4).toFixed(1) +
            '" fill="' + GOLD + '" font-size="7" text-anchor="end">Δ = 0</text>' +
            // axis
            '<line x1="' + padL + '" y1="' + padT + '" x2="' + padL + '" y2="' + (H - padB) +
            '" stroke="' + RULE + '" stroke-width="0.5" />' +
            // delta path
            '<polyline points="' + pts.join(" ") +
            '" fill="none" stroke="' + INK + '" stroke-width="1.4" opacity="0.7" />' +
            // current-delta marker
            '<circle cx="' + (W - padR - 2).toFixed(1) + '" cy="' + deltaY.toFixed(1) +
            '" r="4.5" fill="' + markerColor + '" stroke="' + INK + '" stroke-width="1" />' +
            caption +
            "</svg>";

        el.innerHTML = svg;
        return active;
    }

    global.renderWWBand = renderWWBand;
})(typeof window !== "undefined" ? window : this);
