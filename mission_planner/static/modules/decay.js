"use strict";
// Drag-decay module panel — served by modules/decay.py.  An altitude-vs-time
// sparkline of the plan's decay profile (drag modes), with the entry-interface
// crossing and impact point when the propagation reached them.
MP.register({
  title: "drag decay",
  open: true,
  html: `
    <style>
      #dc_spark { width:100%; height:64px; margin-top:4px; }
      #dc_entry { color:var(--red); font-weight:600; }
    </style>
    <svg id="dc_spark"></svg>
    <div id="dc_entry"></div>
    <div id="dc_hint" class="hint"></div>`,
  init(ctx) {
    const $ = id => document.getElementById(id);
    const NS = "http://www.w3.org/2000/svg";
    const BLUE = "#2a78d6", RED = "#d03b3b", MUTED = "#898781";
    const el = (tag, attrs, parent) => {
      const e = document.createElementNS(NS, tag);
      for (const k in attrs) e.setAttribute(k, attrs[k]);
      parent.appendChild(e);
      return e;
    };

    function draw(tr) {
      const svg = $("dc_spark");
      svg.innerHTML = "";
      $("dc_entry").textContent = "";
      if (!tr || !tr.decay_profile) {
        svg.style.display = "none";
        $("dc_hint").textContent = "no decay profile: plan in a drag mode";
        return;
      }
      svg.style.display = "";
      $("dc_hint").textContent = "";
      const p = tr.decay_profile;
      const W = 300, H = 64; svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
      // An elliptic orbit (King-Hele decay) also has perigee / apogee curves:
      // the band between them closes as drag circularizes the orbit.
      const band = p.perigee_km && p.apogee_km && p.apogee_km.some((a, i) => a - p.perigee_km[i] > 1);
      const lows = band ? p.perigee_km : p.alt_km, highs = band ? p.apogee_km : p.alt_km;
      const t1 = p.t[p.t.length-1], aMin = Math.min(...lows), aMax = Math.max(...highs);
      // Don't let a small oscillation (J2 / oblate-geodetic wiggle) fill the
      // whole plot height: enforce a minimum y-span relative to altitude.
      const minSpan = Math.max(30, 0.25 * aMax);
      let lo = aMin, hi = aMax;
      if (hi - lo < minSpan) {
        const c = (hi + lo) / 2;
        lo = Math.max(0, c - minSpan / 2);
        hi = lo + minSpan;
      }
      const sx = t => 4 + (t / Math.max(t1,1)) * (W - 44);
      const sy = a => 6 + (hi - a) / (hi - lo) * (H - 18);
      // 100 km entry interface, when in range
      if (lo < 100 && hi > 100) {
        el("line", { x1:4, y1:sy(100), x2:W-44, y2:sy(100), stroke:RED,
                     "stroke-width":.7, "stroke-dasharray":"3 3", opacity:.5 }, svg);
      }
      const line = ys => p.t.map((t,i) => sx(t).toFixed(1)+","+sy(ys[i]).toFixed(1)).join(" ");
      if (band) {
        el("polygon", { points: line(p.apogee_km) + " " + line(p.perigee_km).split(" ").reverse().join(" "),
                        fill:BLUE, opacity:.15, stroke:"none" }, svg);
        for (const ys of [p.perigee_km, p.apogee_km])
          el("polyline", { points: line(ys), fill:"none", stroke:BLUE, "stroke-width":.7, opacity:.6 }, svg);
      }
      el("polyline", { points: line(p.alt_km), fill:"none", stroke:BLUE, "stroke-width":1.5 }, svg);
      el("text", { x:W-38, y:sy(hi)+8, "font-size":10, fill:MUTED }, svg)
        .textContent = Math.round(hi);
      el("text", { x:W-38, y:sy(lo)+2, "font-size":10, fill:MUTED }, svg)
        .textContent = Math.round(lo) + " km";
      let msg = tr.entry
        ? "entry " + tr.entry.epoch_utc.replace("T"," ").slice(0,16) + "Z @ "
          + tr.entry.lat_deg.toFixed(1) + ", " + tr.entry.lon_deg.toFixed(1)
        : "";
      if (tr.impact)
        msg += " — impact @ " + tr.impact.lat_deg.toFixed(1) + ", "
          + tr.impact.lon_deg.toFixed(1);
      $("dc_entry").textContent = msg;
    }

    // Plan is null at load time; a module registered later (a plugin switched
    // on) is caught up through onPlan by MP.apply, so this only seeds the hint.
    const show = p => draw(p ? p.track : null);
    show(ctx.getPlan());
    ctx.onPlan(show);
  },
});
