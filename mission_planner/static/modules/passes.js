"use strict";
// Target-pass module panel — served only when modules/passes.py is present.
// Click the map to drop a target, get the overflight windows for the planned
// orbit.  Nothing this module owns — the target ring, the closest-approach
// dot, or even the map click itself — happens while the panel is closed.
MP.register({
  title: "target passes",
  html: `
    <style>
      #pa_table table { width:100%; border-collapse:collapse; font-size:12px; }
      #pa_table th { text-align:left; font-size:10px; letter-spacing:.08em;
        text-transform:uppercase; color:var(--muted); font-weight:500; padding:2px 4px; }
      #pa_table td { padding:2.5px 4px; border-top:1px solid var(--grid);
        font-variant-numeric:tabular-nums; }
      #pa_table tr.sel td { background:#e8f0fb; }
      #pa_table tbody tr { cursor:pointer; }
    </style>
    <div class="row">
      <input id="pa_tgt" placeholder="lat, lon">
      <input id="pa_within" type="number" value="500" title="within km">
    </div>
    <div class="hint">click the map to set the target · km = miss distance searched</div>
    <div id="pa_table"></div>`,
  init(ctx) {
    const $ = id => document.getElementById(id);
    let target = null, list = [], sel = -1;

    async function search() {
      if (!ctx.getPlan() || !target) return;
      const q = ctx.planArgs();
      q.set("tgt_lat", target.lat);
      q.set("tgt_lon", target.lon);
      q.set("within_km", $("pa_within").value || 500);
      ctx.status("searching passes…");
      let res;
      try { res = await ctx.api("/api/passes?" + q); }
      catch (e) { ctx.status("server unreachable: " + e.message, true); return; }
      if (res.error) { ctx.status(res.error, true); return; }
      list = res.passes; sel = -1;
      ctx.status(res.n + " pass(es) within " + q.get("within_km") + " km.");
      render();
      ctx.redraw();
    }

    // Track labels may come from a file: escape them before they go into HTML.
    const escHtml = s => String(s).replace(/[&<>"]/g,
      ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);
    function render() {
      // A multi-track plan: the passes of every vehicle, so say whose each is.
      const multi = (ctx.getPlan()?.tracks || []).length > 1;
      const rows = list.map((p, i) =>
        `<tr data-i="${i}">${multi ? `<td>${escHtml(p.label || p.track)}</td>` : ""}`
        + `<td>${p.ca_utc.replace("T", " ").slice(5, 16)}</td>`
        + `<td>${p.min_dist_km}</td>`
        + `<td>${p.direction[0] === "a" ? "asc" : "desc"}</td>`
        + `<td>${p.alt_km}</td></tr>`).join("");
      $("pa_table").innerHTML = rows
        ? `<table><thead><tr>${multi ? "<th>track</th>" : ""}<th>closest utc</th><th>km</th><th>leg</th>`
          + `<th>alt</th></tr></thead><tbody>${rows}</tbody></table>`
        : "<div class='hint'>no passes in horizon.</div>";
      $("pa_table").querySelectorAll("tbody tr").forEach(r => r.onclick = () => {
        sel = +r.dataset.i;
        $("pa_table").querySelectorAll("tr").forEach(x => x.classList.remove("sel"));
        r.classList.add("sel");
        ctx.seek(list[sel].ca_t_s);        // core moves playback and redraws
      });
    }

    function setTarget(lat, lon) {
      target = { lat: +lat.toFixed(2), lon: +lon.toFixed(2) };
      $("pa_tgt").value = target.lat + ", " + target.lon;
      ctx.redraw();
      search();
    }
    $("pa_tgt").onchange = () => {
      const m = $("pa_tgt").value.split(",").map(Number);
      if (m.length === 2 && m.every(isFinite)) setTarget(m[0], m[1]);
    };
    $("pa_within").onchange = search;

    ctx.onClick((lat, lon) => { if (ctx.isOpen()) setTarget(lat, lon); });
    ctx.onPlan(() => {
      list = []; sel = -1; $("pa_table").innerHTML = "";
      if (ctx.isOpen()) search();
    });
    ctx.onToggle(open => {
      if (open && target && !list.length) search(); else ctx.redraw();
    });

    // Over the ground track, not under it: the CA dot marks a point ON the
    // track and would be hidden by it.
    ctx.onDrawOver(d => {
      if (!ctx.isOpen()) return;
      // A target is a point on the ground: no altitude, no flight path angle.
      if (target) d.marker(target.lat, target.lon, d.C.orange, "target", "target",
                           { key:"pa:target", title:"target" });
      if (sel >= 0 && list[sel] && d.plan) {
        const p = list[sel], tr = d.plan.track, k = d.idxAtTime(p.ca_t_s);
        d.marker(tr.lat[k], tr.lon[k], d.C.green, "dot", "CA",
                 { key:"pa:ca", title:"closest approach", alt_km: tr.alt_km[k],
                   gamma_deg: d.fpa(tr, k),
                   rows: [["utc", p.ca_utc.replace("T", " ").slice(5, 19) + "Z"],
                          ["miss", p.min_dist_km + " km"],
                          ["leg", p.direction]] });
      }
    });
  },
});
