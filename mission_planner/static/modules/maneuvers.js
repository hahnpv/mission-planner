"use strict";
// Maneuver planner module panel — served only when modules/maneuvers.py is
// present; registers itself with the core UI via MP.register.
MP.register({
  title: "maneuver planner",
  html: `
    <div class="row">
      <input id="mv_alt1" type="number" step="10" title="from altitude km" placeholder="from alt km">
      <input id="mv_inc1" type="number" step="0.5" title="from inclination deg" placeholder="from inc°">
    </div>
    <div class="row" style="margin-top:4px">
      <input id="mv_alt2" type="number" step="10" title="target altitude km" placeholder="to alt km" value="800">
      <input id="mv_inc2" type="number" step="0.5" title="target inclination deg" placeholder="to inc°">
    </div>
    <div class="row" style="margin-top:4px">
      <input id="mv_lead" type="number" step="5" title="co-orbital phase lead deg (optional)" placeholder="phase lead° (opt)">
      <button id="mv_go" class="small">compute</button>
    </div>
    <div id="mv_out"></div>`,
  init(ctx) {
    const $ = id => document.getElementById(id);
    const fill = p => {
      if (!p) return;
      $("mv_alt1").value = p.summary.alt_km;
      $("mv_inc1").value = p.summary.inc_deg;
      if (!$("mv_inc2").value) $("mv_inc2").value = p.summary.inc_deg;
    };
    // Null at load time; kept because a module registered later (a plugin
    // switched on) is caught up on the current plan through onPlan by
    // MP.apply, and this seeds the form the same way for that case.
    fill(ctx.getPlan());
    ctx.onPlan(fill);

    const fmtT = s => s >= 5400 ? (s / 3600).toFixed(1) + " h" : Math.round(s / 60) + " min";
    $("mv_go").onclick = async () => {
      const q = new URLSearchParams({
        alt1: $("mv_alt1").value || 400, inc1: $("mv_inc1").value || 0,
        alt2: $("mv_alt2").value || 400, inc2: $("mv_inc2").value || 0,
        lead: $("mv_lead").value || "",
      });
      let r;
      try { r = await ctx.api("/api/maneuvers/budget?" + q); }
      catch (e) { ctx.status("maneuvers: " + e.message, true); return; }
      if (r.error) { ctx.status("maneuvers: " + r.error, true); return; }
      const h = r.hohmann, c = r.combined, rows = [
        ["hohmann &Delta;v1 / &Delta;v2", `${h.dv1_ms} / ${h.dv2_ms} m/s`],
        ["hohmann total &middot; time", `${h.dv_total_ms} m/s &middot; ${fmtT(h.transfer_time_s)}`],
      ];
      if (r.plane_change_only.dv_ms > 0.05) rows.push(
        ["plane change alone", `${r.plane_change_only.dv_ms} m/s`],
        ["combined (far burn)", `${c.dv_total_ms} m/s`]);
      if (r.phasing) {
        const p = r.phasing;
        rows.push(["phasing " + (p.feasible ? "" : "(INFEASIBLE) ")
          + `via ${p.phasing_alt_km} km`,
          `${p.dv_total_ms} m/s &middot; ${fmtT(p.time_s)}`]);
      }
      const d = r.deorbit_from_target;
      rows.push(["deorbit to 100 km", `${d.dv_ms} m/s &middot; ${fmtT(d.coast_time_s)} coast`]);
      $("mv_out").innerHTML = "<table style='width:100%;border-collapse:collapse'>"
        + rows.map(x => `<tr><td style='padding:1.5px 0'>${x[0]}</td>`
          + `<td style='text-align:right;font-variant-numeric:tabular-nums'>${x[1]}</td></tr>`).join("")
        + "</table>";
    };
  },
});
