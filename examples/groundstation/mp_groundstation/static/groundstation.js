"use strict";
// Ground station panel -- the UI half of the groundstation plugin.  One
// station, placed explicitly ("place on map", then a click; Esc cancels) or
// typed in, with an elevation mask.  The panel says who is above the mask
// now and lists the contact windows (from the plugin's REST route); the map
// shows the station and the ring inside which the vehicle in focus is above
// the mask; a View-menu toggle limits the horizon footprints to the vehicles
// above it.  The station is kept in this browser.
MP.register({
  title: "ground station",
  html: `
    <style>
      #gs_table table { width:100%; border-collapse:collapse; font-size:12px; margin-top:4px; }
      #gs_table th { text-align:left; font-size:10px; letter-spacing:.08em; text-transform:uppercase;
        color:var(--muted); font-weight:500; padding:2px 4px; }
      #gs_table td { padding:2.5px 4px; border-top:1px solid var(--grid); font-variant-numeric:tabular-nums; }
      #gs_table tbody tr { cursor:pointer; }
      #gs_table tbody tr:hover td { background:#e8f0fb; }
    </style>
    <div class="row">
      <button id="gs_place" class="small" type="button">place on map</button>
      <button id="gs_clear" class="small ghost" type="button">remove</button>
    </div>
    <div class="row" style="margin-top:4px">
      <input id="gs_lat" type="number" step="0.01" placeholder="lat °">
      <input id="gs_lon" type="number" step="0.01" placeholder="lon °">
    </div>
    <div class="row" style="margin-top:4px">
      <input id="gs_name" placeholder="name">
      <input id="gs_mask" type="number" step="1" min="0" max="89" value="10"
             title="elevation mask: the lowest elevation that counts as contact">
    </div>
    <div class="hint">name · elevation mask (°)</div>
    <div id="gs_view" class="hint" style="margin-top:4px"></div>
    <div id="gs_cov" class="hint" style="margin-top:4px"></div>
    <div id="gs_table"></div>`,
  init(ctx) {
    const $g = id => document.getElementById("gs_" + id);
    const KEY = "mp.groundstation", RE = 6378.137, D = Math.PI / 180;
    let gs = null, placing = false, onlyVisible = false, reqSeq = 0;
    try { gs = JSON.parse(localStorage.getItem(KEY)) || null; } catch { gs = null; }
    const mask = () => (gs && Number.isFinite(gs.mask) ? gs.mask : 10);

    function save() {
      try { gs ? localStorage.setItem(KEY, JSON.stringify(gs)) : localStorage.removeItem(KEY); }
      catch {}
    }
    function sync() {
      $g("lat").value = gs ? gs.lat.toFixed(3) : "";
      $g("lon").value = gs ? gs.lon.toFixed(3) : "";
      $g("name").value = gs ? gs.name : "";
      $g("mask").value = mask();
      $g("clear").disabled = !gs;
      $g("place").textContent = placing ? "click the map…" : gs ? "move on map" : "place on map";
      $g("place").classList.toggle("primary", placing);
      if (!gs) { $g("view").textContent = "no station placed"; $g("cov").textContent = ""; $g("table").replaceChildren(); }
    }
    function setStation(lat, lon, name) {
      gs = { lat: Math.max(-90, Math.min(90, lat)), lon: ((lon + 540) % 360) - 180,
             name: name ?? gs?.name ?? "ground station", mask: mask() };
      save(); sync(); ctx.redraw(); refresh();
    }

    // Elevation of the vehicle at sample k as seen from the station [deg]
    // (the same geometry as the plugin's contacts.py).
    function elevation(tr, k) {
      const la1 = gs.lat * D, la2 = tr.lat[k] * D, dlo = (tr.lon[k] - gs.lon) * D;
      const c = Math.sin(la1) * Math.sin(la2) + Math.cos(la1) * Math.cos(la2) * Math.cos(dlo);
      const psi = Math.acos(Math.max(-1, Math.min(1, c)));
      const r = RE + Math.max(tr.alt_km[k], 0);
      return Math.atan2(Math.cos(psi) - RE / r, Math.sin(psi)) / D;
    }
    // The ring of ground range [deg] inside which a vehicle at alt_km is above the mask.
    function ringDeg(alt_km) {
      const r = RE + Math.max(alt_km, 0), el = mask() * D;
      return (Math.acos(Math.min(1, RE / r * Math.cos(el))) - el) / D;
    }
    // Points of a small circle of angular radius rho [deg] around the station.
    function circle(rho) {
      const la = gs.lat * D, lo = gs.lon * D, d = rho * D, lats = [], lons = [];
      for (let b = 0; b <= 360; b += 4) {
        const br = b * D;
        const la2 = Math.asin(Math.sin(la) * Math.cos(d) + Math.cos(la) * Math.sin(d) * Math.cos(br));
        const lo2 = lo + Math.atan2(Math.sin(br) * Math.sin(d) * Math.cos(la),
                                    Math.cos(d) - Math.sin(la) * Math.sin(la2));
        lats.push(la2 / D); lons.push(((lo2 / D + 540) % 360) - 180);
      }
      return [lats, lons];
    }

    // ---- contact windows, from the plugin's route --------------------------
    // Window labels may come from a file: escape them before they go into HTML.
    const escHtml = s => String(s).replace(/[&<>"]/g,
      ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);
    // "HH:MM", with "+1d" (etc.) for a window on a later UTC day than the plan's start.
    const day = iso => Date.parse(iso.slice(0, 10)) / 86400000;
    const when = (iso, epoch) => {
      const n = Math.round(day(iso) - day(epoch));
      return iso.slice(11, 16) + (n ? ` +${n}d` : "");
    };
    const mins = s => (s / 60).toFixed(s < 600 ? 1 : 0);
    async function refresh() {
      if (!gs || !ctx.getPlan() || !ctx.isOpen()) return;
      const my = ++reqSeq;
      const q = ctx.planArgs();
      q.set("gs_lat", gs.lat); q.set("gs_lon", gs.lon); q.set("min_el", mask());
      $g("cov").textContent = "finding contacts…";
      let r;
      try { r = await ctx.api("/api/groundstation/contacts?" + q); }
      catch (e) { r = { error: "server unreachable: " + e.message }; }
      if (my !== reqSeq) return;   // the station, mask or plan changed meanwhile
      if (r.error) { $g("cov").textContent = ""; ctx.status("ground station: " + r.error, true); return; }
      const c = r.coverage, epoch = ctx.getPlan().track.epoch_utc;
      const multi = (ctx.getPlan().tracks || []).length > 1;
      $g("cov").textContent = !r.n ? `no contacts above ${mask()}°`
        : `${r.n} contact${r.n > 1 ? "s" : ""} · ${mins(c.total_s)} min in all `
          + `(${(c.fraction * 100).toFixed(1)}%) · longest gap ${(c.longest_gap_s / 3600).toFixed(1)} h`;
      const rows = r.contacts.slice(0, 50).map(w =>
        `<tr data-t="${w.max_el_t_s}">${multi ? `<td>${escHtml(w.label || w.track)}</td>` : ""}`
        + `<td>${when(w.aos_utc, epoch)}${w.partial ? "*" : ""}</td><td>${mins(w.duration_s)}</td>`
        + `<td>${w.max_el_deg.toFixed(0)}°</td><td>${w.aos_az_deg.toFixed(0)}→${w.los_az_deg.toFixed(0)}°</td></tr>`);
      $g("table").innerHTML = !r.n ? "" : `<table><thead><tr>${multi ? "<th>track</th>" : ""}`
        + `<th>aos utc</th><th>min</th><th>max el</th><th>az</th></tr></thead><tbody>${rows.join("")}</tbody></table>`
        + (r.contacts.some(w => w.partial)
          ? `<div class="hint">* cut off by the start or end of the plan</div>` : "");
      $g("table").querySelectorAll("tbody tr").forEach(tr => tr.onclick = () => ctx.seek(+tr.dataset.t));
    }
    ctx.onPlan(() => refresh());
    ctx.onToggle(open => { if (open) refresh(); });

    // ---- placing and editing the station -----------------------------------
    $g("place").onclick = () => {
      placing = !placing;
      sync();
      ctx.status(placing ? "click the map to place the ground station (Esc cancels)." : "placing cancelled.");
    };
    document.addEventListener("keydown", ev => {
      if (ev.key === "Escape" && placing) { placing = false; sync(); ctx.status("placing cancelled."); }
    });
    ctx.onClick((lat, lon) => {
      if (!placing) return;
      placing = false;
      setStation(lat, lon);
      ctx.status(`ground station at ${gs.lat.toFixed(3)}°, ${gs.lon.toFixed(3)}°.`);
    });
    $g("clear").onclick = () => { gs = null; placing = false; save(); sync(); ctx.redraw(); };
    const typed = () => {
      const lat = parseFloat($g("lat").value), lon = parseFloat($g("lon").value);
      if (Number.isFinite(lat) && Number.isFinite(lon)) setStation(lat, lon, $g("name").value || undefined);
    };
    $g("lat").onchange = $g("lon").onchange = typed;
    $g("name").onchange = () => { if (gs) { gs.name = $g("name").value || "ground station"; save(); ctx.redraw(); } };
    $g("mask").onchange = () => {
      const m = parseFloat($g("mask").value);
      if (!Number.isFinite(m) || m < 0 || m >= 90) { ctx.status("the elevation mask is 0–89°.", true); sync(); return; }
      if (gs) { gs.mask = m; save(); ctx.redraw(); refresh(); }
    };

    // ---- the map, and the View menu ----------------------------------------
    ctx.addDisplayToggle("footprints: only vehicles above the ground station's mask", false, v => {
      onlyVisible = v;
      if (v && !gs) ctx.status("place a ground station first (ground station panel).", true);
      ctx.redraw();
    });
    ctx.footprintFilter((tr, k) => (onlyVisible && gs ? elevation(tr, k) >= mask() : null));

    // Under the track: the ring inside which the vehicle in focus is above the mask.
    ctx.onDraw(d => {
      if (!gs || !d.plan || !ctx.isOpen()) return;
      const tr = d.plan.track, k = d.idxAtTime(d.tCur, tr);
      const [lats, lons] = circle(ringDeg(tr.alt_km[k]));
      d.polygon(lats, lons, { fill: d.C.green, "fill-opacity": 0.06, stroke: d.C.green,
                              "stroke-width": 1, "stroke-dasharray": "4 3" });
    });
    // Over the track: the station, and who is above the mask now (the panel line).
    ctx.onDrawOver(d => {
      if (!gs) return;
      const seen = [];
      if (d.plan) {
        for (const tr of d.plan.tracks || [d.plan.track]) {
          const n = tr.t.length;
          if (n < 2 || d.tCur < tr.t[0] || d.tCur > tr.t[n - 1]) continue;
          const e = elevation(tr, d.idxAtTime(d.tCur, tr));
          if (e >= mask()) seen.push([tr.label || tr.id || "vehicle", e]);
        }
      }
      seen.sort((a, b) => b[1] - a[1]);
      $g("view").textContent = !d.plan ? "plan something to see who is in contact"
        : seen.length ? `in contact now (${seen.length}): ` + seen.map(([n, e]) => `${n} ${e.toFixed(0)}°`).join(", ")
        : `nothing above ${mask()}° now`;
      d.marker(gs.lat, gs.lon, d.C.green, "site", gs.name,
        { key: "gs", title: gs.name,
          rows: [["mask", `${mask()}°`], ["in contact", String(seen.length)]].concat(
            seen.slice(0, 6).map(([n, e]) => [n, `el ${e.toFixed(1)}°`])) });
    });
    sync();
  },
});
