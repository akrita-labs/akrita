// AKRITA — Polymarket scoring curve.
// Renders S = ((v - s) / v)^2 where v = max spread, s = current quote spread
// offset (expressed as a fraction of the max spread). A moving marker tracks
// the operator's current NOMOS offset. Pure inline-SVG; no dependencies.
//
//   renderScoreCurve(canvasEl, offset)
//     canvasEl — any container element (a <div>); we inject an <svg> into it.
//     offset   — number in [0, 1]: the quote-spread offset as a fraction of
//                the maximum allowed spread. Smaller = tighter quotes, higher
//                score; larger = wider/safer, lower score.
//
// The score function rewards quoting near the max spread boundary (s -> v):
// S peaks when the offset is small (tight to mid) and decays toward the edge.
// We treat `offset` directly as s/v in [0,1] so S = (1 - offset)^2.

(function (global) {
    "use strict";

    var GOLD = "#9d6f1d";
    var GOLD_BRIGHT = "#c79a3e";
    var INK = "#3a2d1a";
    var RULE = "rgba(124, 82, 25, 0.5)";
    var CRIMSON = "#8a2d1c";
    var GREEN = "#2c6040";

    function clamp01(x) {
        x = Number(x);
        if (!isFinite(x)) return 0;
        if (x < 0) return 0;
        if (x > 1) return 1;
        return x;
    }

    // Polymarket-style scoring: score falls off as the offset widens.
    function score(offset) {
        var s = 1 - clamp01(offset);
        return s * s; // ((v - s)/v)^2 with offset = s/v
    }

    function renderScoreCurve(el, offset) {
        if (!el) return;
        offset = clamp01(offset);

        var W = 320, H = 180;
        var padL = 34, padR = 14, padT = 14, padB = 28;
        var plotW = W - padL - padR;
        var plotH = H - padT - padB;

        var x = function (t) { return padL + t * plotW; };          // t in [0,1]
        var y = function (v) { return padT + (1 - clamp01(v)) * plotH; }; // v in [0,1]

        // Build the curve polyline.
        var pts = [];
        var N = 60;
        for (var i = 0; i <= N; i++) {
            var t = i / N;
            pts.push(x(t).toFixed(1) + "," + y(score(t)).toFixed(1));
        }

        var mx = x(offset);
        var my = y(score(offset));
        var sVal = score(offset);

        // Gridlines at 0.25 / 0.5 / 0.75.
        var grid = "";
        [0.25, 0.5, 0.75].forEach(function (g) {
            grid +=
                '<line x1="' + padL + '" y1="' + y(g).toFixed(1) +
                '" x2="' + (W - padR) + '" y2="' + y(g).toFixed(1) +
                '" stroke="' + RULE + '" stroke-width="0.5" stroke-dasharray="2 3" />';
        });

        var svg =
            '<svg viewBox="0 0 ' + W + " " + H + '" width="100%" role="img" ' +
            'aria-label="Polymarket scoring curve, score ' + sVal.toFixed(2) +
            ' at offset ' + offset.toFixed(2) + '" ' +
            'style="display:block;font-family:var(--font-mono),monospace;">' +
            // axes
            '<line x1="' + padL + '" y1="' + padT + '" x2="' + padL + '" y2="' + (H - padB) +
            '" stroke="' + GOLD + '" stroke-width="1" />' +
            '<line x1="' + padL + '" y1="' + (H - padB) + '" x2="' + (W - padR) + '" y2="' + (H - padB) +
            '" stroke="' + GOLD + '" stroke-width="1" />' +
            grid +
            // curve
            '<polyline points="' + pts.join(" ") +
            '" fill="none" stroke="' + CRIMSON + '" stroke-width="1.8" />' +
            // marker drop-line
            '<line x1="' + mx.toFixed(1) + '" y1="' + my.toFixed(1) +
            '" x2="' + mx.toFixed(1) + '" y2="' + (H - padB) +
            '" stroke="' + GOLD + '" stroke-width="0.8" stroke-dasharray="2 2" />' +
            // marker
            '<circle cx="' + mx.toFixed(1) + '" cy="' + my.toFixed(1) +
            '" r="4.5" fill="' + GOLD_BRIGHT + '" stroke="' + INK + '" stroke-width="1" />' +
            // labels
            '<text x="' + padL + '" y="10" fill="' + GOLD + '" font-size="8">S</text>' +
            '<text x="' + (W - padR) + '" y="' + (H - 8) +
            '" fill="' + GOLD + '" font-size="8" text-anchor="end">offset →</text>' +
            '<text x="' + (mx + 6).toFixed(1) + '" y="' + Math.max(my - 6, 14).toFixed(1) +
            '" fill="' + GREEN + '" font-size="9">S=' + sVal.toFixed(2) + '</text>' +
            "</svg>";

        el.innerHTML = svg;
    }

    global.renderScoreCurve = renderScoreCurve;
})(typeof window !== "undefined" ? window : this);
