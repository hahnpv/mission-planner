"use strict";
// Ground station module panel — served by modules/groundstation.py.  One
// station, placed explicitly ("place on map", then a click; Esc cancels) or
// typed in.  The panel lists the vehicles that see it now (0 deg elevation,
// the horizon footprint's own geometry), and the View menu toggle limits the
// horizon footprints to exactly those vehicles.  Kept in this browser.
MP.register({
  title: "ground station",
  html: `
    <div class="row">
      <button id="gs_place" class="small" type="button">place on map</button>
      <button id="gs_clear" class="small ghost" type="button">remove</button>
    </div>
    <div class="row" style="margin-top:4px">
      <input id="gs_lat" type="number" step="0.01" placeholder="lat °">
      <input id="gs_lon" type="number" step="0.01" placeholder="lon °">
    </div>
    <input id="gs_name" placeholder="name" style="margin-top:4px">
    <div id="gs_view" class="hint" style="margin-top:4px"></div>`,
  init(ctx) {
    const $g = id => document.getElementById("gs_" + id);
    const KEY = "mp.groundstation", RE = 6378.137, D = Math.PI / 180;
    let gs = null, placing = false, onlyVisible = false;
    try { gs = JSON.parse(localStorage.getItem(KEY)) || null; } catch { gs = null; }

    function save() {
      try { gs ? localStorage.setItem(KEY, JSON.stringify(gs)) : localStorage.removeItem(KEY); }
      catch {}
    }
    function sync() {
      $g("lat").value = gs ? gs.lat.toFixed(3) : "";
      $g("lon").value = gs ? gs.lon.toFixed(3) : "";
      $g("name").value = gs ? gs.name : "";
      $g("clear").disabled = !gs;
      $g("place").textContent = placing ? "click the map…" : gs ? "move on map" : "place on map";
      $g("place").classList.toggle("primary", placing);
      if (!gs) $g("view").textContent = "no station placed";
    }
    function setStation(lat, lon, name) {
      gs = { lat: Math.max(-90, Math.min(90, lat)), lon: ((lon + 540) % 360) - 180,
             name: name ?? gs?.name ?? "ground station" };
      save(); sync(); ctx.redraw();
    }

    // Central angle station -> subpoint, and the elevation it means at altitude h.
    function look(tr, k) {
      const la1 = gs.lat * D, la2 = tr.lat[k] * D, dlo = (tr.lon[k] - gs.lon) * D;
      const c = Math.sin(la1) * Math.sin(la2) + Math.cos(la1) * Math.cos(la2) * Math.cos(dlo);
      const psi = Math.acos(Math.max(-1, Math.min(1, c)));
      const r = RE + Math.max(tr.alt_km[k], 0);
      const visible = psi <= Math.acos(RE / r);
      const el = Math.atan2(Math.cos(psi) - RE / r, Math.sin(psi)) / D;
      return { visible, el };
    }

    $g("place").onclick = () => {
      placing = !placing;
      sync();
      if (placing) ctx.status("click the map to place the ground station (Esc cancels).");
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

    ctx.addDisplayToggle("footprints: only vehicles that see the ground station", false, v => {
      onlyVisible = v;
      if (v && !gs) ctx.status("place a ground station first (ground station panel).", true);
      ctx.redraw();
    });
    ctx.footprintFilter((tr, k) => (onlyVisible && gs ? look(tr, k).visible : null));

    // The station itself, and who sees it now (the panel line).
    ctx.onDrawOver(d => {
      if (!gs) return;
      const seen = [];
      if (d.plan) {
        const tracks = d.plan.tracks || [d.plan.track];
        for (const tr of tracks) {
          const n = tr.t.length;
          if (n < 2 || d.tCur < tr.t[0] || d.tCur > tr.t[n - 1]) continue;
          const k = d.idxAtTime(d.tCur, tr), l = look(tr, k);
          if (l.visible) seen.push([tr.label || tr.id || "vehicle", l.el]);
        }
      }
      seen.sort((a, b) => b[1] - a[1]);
      $g("view").textContent = !d.plan ? "plan something to see who is in view"
        : seen.length ? `in view now (${seen.length}): ` + seen.map(([n, e]) => `${n} ${e.toFixed(0)}°`).join(", ")
        : "nothing in view now";
      d.marker(gs.lat, gs.lon, d.C.green, "site", gs.name,
        { key: "gs", title: gs.name,
          rows: [["in view", String(seen.length)]].concat(
            seen.slice(0, 6).map(([n, e]) => [n, `el ${e.toFixed(1)}°`])) });
    });
    sync();
  },
});
