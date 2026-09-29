"use strict";
// The map: redraw() rebuilds the svg from scratch each time (track, markers,
// module layers, agent scene), plus pan / zoom / click handling.

// Sample index range [i0, i1] of the track inside the shown window; always
// i0 <= i1 < t.length, and at least two samples when the track has them.
function trackWindowIdx() {
  if (!plan) return [0, 0];
  const t = plan.track.t, n = t.length;
  if (n < 2) return [0, 0];
  const tEnd = t[n - 1];
  const lo = win[0] * tEnd, hi = win[1] * tEnd;
  let i0 = t.findIndex(v => v >= lo); if (i0 < 0) i0 = 0;
  let i1 = n - 1;
  for (let i = n - 1; i >= 0; i--) if (t[i] <= hi) { i1 = i; break; }
  return [i0, Math.min(n - 1, Math.max(i0 + 1, i1))];
}
function idxAtTime(ts, tr) {
  const t = (tr || plan.track).t;
  let lo = 0, hi = t.length - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; (t[m] <= ts ? lo = m : hi = m); }
  return (ts - t[lo] < t[hi] - ts) ? lo : hi;
}
// Earth-relative flight path angle [deg] at sample k of a track: the angle
// between the velocity and the local horizontal, atan2(dh/dt, r*dtheta/dt).
// Backward difference off the earth-fixed track, so this is the relative
// (not inertial) gamma -- the one entry corridors are quoted in.  Negative
// is descending.
function fpaDeg(tr, k) {
  const i = Math.max(1, Math.min(k, tr.t.length - 1));
  const dt = tr.t[i] - tr.t[i - 1];
  if (!(dt > 0)) return 0;
  const la1 = tr.lat[i - 1] * DEG, la2 = tr.lat[i] * DEG;
  let dlon = (tr.lon[i] - tr.lon[i - 1]) * DEG;
  dlon = Math.atan2(Math.sin(dlon), Math.cos(dlon));          // wrap-safe
  const hav = Math.sin((la2 - la1) / 2) ** 2
    + Math.cos(la1) * Math.cos(la2) * Math.sin(dlon / 2) ** 2;
  const dth = 2 * Math.asin(Math.min(1, Math.sqrt(Math.max(hav, 0))));
  const r = (RE_KM + 0.5 * (tr.alt_km[i] + tr.alt_km[i - 1])) * 1e3;
  const vh = dth * r / dt, vr = (tr.alt_km[i] - tr.alt_km[i - 1]) * 1e3 / dt;
  return Math.atan2(vr, vh) / DEG;
}

// Wrap map graphics in a group that toggles an info callout when clicked.
// `info` = {key, title, alt_km?, gamma_deg?, rows?} -- key must be stable
// across redraws, since redraw() rebuilds every node from scratch.
function pinGroup(info, lat, lon, at) {
  const p = at || project(lat, lon);
  // Far side of the globe: an unattached group, so callers can still draw into it.
  if (!p.vis) return document.createElementNS(NS, "g");
  const g = el("g", { style:"cursor:pointer" });
  // The glyphs are 4-7 px across; give the pointer something to hit.
  el("circle", { cx:p.x, cy:p.y, r:11, fill:"transparent" }, g);
  // Swallow the press so the map does not read this as a pan or a map click.
  g.addEventListener("mousedown", ev => ev.stopPropagation());
  g.addEventListener("click", ev => {
    ev.stopPropagation();
    pinOpen = pinOpen === info.key ? null : info.key;
    redraw();
  });
  if (pinOpen === info.key) pinHit = { info, lat, lon, x:p.x, y:p.y };
  return g;
}

function marker(lat, lon, color, symbol, name, info, at) {
  const { x, y, vis } = at || project(lat, lon);
  if (!vis) return;
  const parent = info ? pinGroup(info, lat, lon, at) : null;
  if (symbol === "target") {
    el("circle", { cx:x, cy:y, r:7, fill:"none", stroke:color, "stroke-width":1.6 }, parent);
    el("circle", { cx:x, cy:y, r:1.8, fill:color }, parent);
  } else if (symbol === "site") {
    el("rect", { x:x-3.5, y:y-3.5, width:7, height:7, fill:"none", stroke:color, "stroke-width":1.6 }, parent);
  } else {
    el("circle", { cx:x, cy:y, r:3.4, fill:color, stroke:"#fcfcfb", "stroke-width":1.2 }, parent);
  }
  if (name) el("text", { x:x+9, y:y+4, fill:"#0b0b0b", "font-size":11 }, parent).textContent = name;
}

// The open marker's readout.  Scaled by the zoom so it stays a constant size
// on screen, and flipped when it would spill outside the viewport.
function drawPin(p) {
  const k = view.w / 1080;
  const rows = [["lat", p.lat.toFixed(3) + "°"],
                ["lon", p.lon.toFixed(3) + "°"]];
  if (p.info.alt_km != null) rows.push(["alt", p.info.alt_km.toFixed(1) + " km"]);
  if (p.info.gamma_deg != null)
    rows.push(["γ", p.info.gamma_deg.toFixed(2) + "°"]);
  for (const r of p.info.rows || []) rows.push(r);
  const title = p.info.title || "";
  const lh = 13 * k, pad = 7 * k;
  const chars = Math.max(title.length,
    ...rows.map(r => String(r[0]).length + String(r[1]).length + 3));
  const w = Math.max(104 * k, (chars * 6.2 + 18) * k);
  const h = 2 * pad + (rows.length + (title ? 1 : 0)) * lh;
  let bx = p.x + 12 * k, by = p.y + 8 * k;
  if (bx + w > view.x + view.w) bx = p.x - 12 * k - w;
  if (by + h > view.y + view.h) by = p.y - 8 * k - h;
  const g = el("g", { style:"cursor:pointer" });
  g.addEventListener("mousedown", ev => ev.stopPropagation());
  g.addEventListener("click", ev => { ev.stopPropagation(); pinOpen = null; redraw(); });
  el("rect", { x:bx, y:by, width:w, height:h, rx:3 * k, fill:"rgba(252,252,251,.96)",
               stroke:C.grid, "stroke-width":k }, g);
  let ty = by + pad + 9 * k;
  if (title) {
    el("text", { x:bx + pad, y:ty, "font-size":11 * k, "font-weight":600,
                 fill:"#0b0b0b" }, g).textContent = title;
    ty += lh;
  }
  for (const [lab, val] of rows) {
    el("text", { x:bx + pad, y:ty, "font-size":11 * k, fill:C.muted }, g)
      .textContent = lab;
    el("text", { x:bx + w - pad, y:ty, "font-size":11 * k, "text-anchor":"end",
                 fill:"#0b0b0b", style:"font-variant-numeric:tabular-nums" }, g)
      .textContent = val;
    ty += lh;
  }
}

function drawHorizon() {
  const tr = plan.track, k = idxAtTime(tCur);
  const lat0 = tr.lat[k] * DEG, lon0 = tr.lon[k] * DEG;
  const lam = Math.acos(RE_KM / (RE_KM + Math.max(tr.alt_km[k], 1)));
  const lats = [], lons = [];
  for (let b = 0; b <= 360; b += 3) {
    const th = b * DEG;
    const la = Math.asin(Math.sin(lat0) * Math.cos(lam)
      + Math.cos(lat0) * Math.sin(lam) * Math.cos(th));
    const lo = lon0 + Math.atan2(Math.sin(th) * Math.sin(lam) * Math.cos(lat0),
      Math.cos(lam) - Math.sin(lat0) * Math.sin(la));
    lats.push(la / DEG);
    lons.push(normLon(lo / DEG));
  }
  polygon(lats, lons, { fill: C.green, "fill-opacity": .10, stroke: C.green,
    "stroke-width": 1.4, "stroke-opacity": .8, "pointer-events": "none" });
}

// What a module's onDraw / onDrawOver callback gets.  Everything here draws
// correctly in every view (map, globe, orbit):
//   plan, tCur          the current plan and playback time (s past epoch)
//   project(lat, lon)   -> {x, y, vis}; draw nothing when !vis
//   polyline(pts, attrs), polygon(latArr, lonArr, attrs)   seam/limb aware
//   marker(lat, lon, color, symbol, name, info?)           clickable pin when info given
//   C                   the palette; idxAtTime(t_s, track?), fpa(track, k)
//   globe               true off the flat map; view: "map" | "globe" | "orbit"
const layerCtx = () => ({ plan, tCur, project, polyline, polygon, marker, C,
                          idxAtTime, fpa: fpaDeg,
                          globe: projMode !== "map", view: projMode });

function redraw() {
  const svg = $("map");
  svg.innerHTML = "";
  pinHit = null;
  svg.setAttribute("viewBox", `${view.x} ${view.y} ${view.w} ${view.h}`);
  GR = projMode === "orbit" ? orbitRadius() : GLOBE.R;
  globeBasis();

  // globe disc, with a faint darkening toward the limb for depth
  if (projMode !== "map") {
    const defs = el("defs", {});
    const g = el("radialGradient", { id:"limbshade", cx:"50%", cy:"50%", r:"50%" }, defs);
    el("stop", { offset:"70%", "stop-color":"#1c2733", "stop-opacity":0 }, g);
    el("stop", { offset:"100%", "stop-color":"#1c2733", "stop-opacity":.09 }, g);
    el("circle", { cx:GLOBE.cx, cy:GLOBE.cy, r:GR, fill:"#f6f5f2" });
  }

  // graticule
  if (projMode === "map") {
    for (let lon = -180; lon <= 180; lon += 30)
      el("line", { x1:X(lon), y1:Y(90), x2:X(lon), y2:Y(-90), stroke:C.grid, "stroke-width":.5 });
    for (let lat = -60; lat <= 60; lat += 30)
      el("line", { x1:0, y1:Y(lat), x2:360 * S, y2:Y(lat),
                   stroke:C.grid, "stroke-width": lat ? .5 : 1 });
  } else {
    for (let lon = -180; lon < 180; lon += 30) {
      const pts = [];
      for (let lat = -90; lat <= 90; lat += 3) pts.push([lat, lon]);
      polyline(pts, { stroke:C.grid, "stroke-width":.5 });
    }
    for (let lat = -60; lat <= 60; lat += 30) {
      const pts = [];
      for (let lon = -180; lon <= 180; lon += 3) pts.push([lat, lon]);
      polyline(pts, { stroke:C.grid, "stroke-width": lat ? .5 : 1 });
    }
  }

  // coastline
  if (coast) for (const f of coast.features)
    polyline(f.geometry.coordinates.map(c => [c[1], c[0]]),
             { stroke:"#b9b7ae", "stroke-width":.7 });

  // static overlays (shaded regions, e.g. range/warning areas)
  for (const ov of overlayList) {
    const color = ov.style.color || C.red, op = ov.style.opacity || .16;
    if (overlayOff.has(ov.pack + "/" + ov.id)) continue;
    const rings = [];
    for (const f of ov.geojson.features) {
      const g = f.geometry;
      if (g.type === "Polygon") rings.push(g.coordinates[0]);
      else if (g.type === "MultiPolygon")
        for (const poly of g.coordinates) rings.push(poly[0]);
    }
    for (const ring of rings)
      polygon(ring.map(c => c[1]), ring.map(c => c[0]), {
        fill: color, "fill-opacity": op, stroke: color,
        "stroke-width": .8, "stroke-opacity": .6, "pointer-events": "none",
      });
  }

  // horizon footprint at the playback position: the ground that can see the
  // vehicle at 0 deg elevation, geocentric radius acos(RE/(RE+h))
  if (plan && display.horizon) drawHorizon();

  // module map layers, under the ground track
  for (const fn of MP.live(MP._layers)) {
    try { fn(layerCtx()); }
    catch (e) { console.error("module layer:", e); }
  }

  // day/night terminator at scrub time
  if (plan && display.night) {
    const sun = solarSubpoint(Date.parse(plan.track.epoch_utc) + tCur * 1000);
    if (projMode !== "map") drawNightGlobe(sun);
    else el("path", { d: terminatorPath(sun),
                      fill:"#1c2733", opacity:.10, "pointer-events":"none" });
  }

  // ground track (clipped to display window)
  if (plan) {
    const [i0, i1] = trackWindowIdx();
    const tr = plan.track, pts = [], orbit3d = projMode === "orbit";
    for (let i = i0; i <= i1; i++) pts.push([tr.lat[i], tr.lon[i]]);
    // In the orbit view the ground track stays on the surface, faint (and
    // optional), and the orbit itself is drawn in space.
    if (!orbit3d || orbitView.ground)
      polyline(pts, { stroke:C.blue, "stroke-width": orbit3d ? .8 : 1.1,
                      opacity: orbit3d ? .25 : .45 });
    // Emphasize the orbit around the playback position: half a rev ahead
    // and behind the satellite dot, clipped to the display window.  A
    // finished trajectory has no period: all of it.
    const halfP = plan.summary.period_s ? plan.summary.period_s / 2 : Infinity;
    if (orbit3d) {
      const all = [], rev = [];
      for (let i = i0; i <= i1; i++) {
        const v = orbitVec(tr.lat[i], tr.lon[i], tr.alt_km[i], tr.t[i]);
        all.push(v);
        if (Math.abs(tr.t[i] - tCur) <= halfP) rev.push(v);
      }
      spaceLine(all, { stroke:C.blue, "stroke-width":1.1, opacity:.45 });
      spaceLine(rev, { stroke:C.blue, "stroke-width":2.2 });
    } else {
      const rev = [];
      for (let i = i0; i <= i1; i++)
        if (Math.abs(tr.t[i] - tCur) <= halfP) rev.push([tr.lat[i], tr.lon[i]]);
      polyline(rev, { stroke:C.blue, "stroke-width":2.2 });
    }

    // launch site + satellite at scrub time
    if (plan.summary.site_lat != null)
      marker(plan.summary.site_lat, plan.summary.site_lon, C.muted, "site", "",
             { key:"site", title: plan.summary.site });
    // Apsis markers on screen, so the satellite's label can dodge theirs.
    const apsisAt = (tr.apsides || []).map(ap => [ap,
      orbit3d ? spacePoint(orbitVec(ap.lat_deg, ap.lon_deg, ap.alt_km, ap.t_s))
              : project(ap.lat_deg, ap.lon_deg)]);
    const k = idxAtTime(tCur);
    if (k >= i0 && k <= i1) {
      let ps = project(tr.lat[k], tr.lon[k]);
      if (orbit3d) {   // the satellite at altitude, tied to its subpoint
        const v = orbitVec(tr.lat[k], tr.lon[k], tr.alt_km[k], tr.t[k]);
        spaceLine([vec(tr.lat[k], tr.lon[k]), v],
                  { stroke:C.blue, "stroke-width":.8, opacity:.6, "stroke-dasharray":"2 2" });
        ps = spacePoint(v);
      }
      marker(tr.lat[k], tr.lon[k], C.blue, "dot", "",
             { key:"sat", title:"satellite", alt_km: tr.alt_km[k],
               gamma_deg: fpaDeg(tr, k),
               rows: [["utc", fmtUTC(Date.parse(tr.epoch_utc)
                                     + tr.t[k] * 1000).slice(5)]] }, ps);
      if (ps.vis) {
        // Near an apsis marker its label sits to the right, so go left.
        const left = apsisAt.some(([, a]) => a.vis && Math.hypot(a.x - ps.x, a.y - ps.y) < 30);
        el("text", { x: left ? ps.x-8 : ps.x+8, y:ps.y-6, fill:C.blue, "font-size":11,
                     "text-anchor": left ? "end" : "start" })
          .textContent = tr.alt_km[k].toFixed(0) + " km";
      }
    }
    // perigee/apogee markers on the first pass (elliptic only)
    for (const [ap, at] of apsisAt) {
      const { x, y, vis } = at;
      if (!vis) continue;
      // gamma is exactly 0 at an apsis -- the radial rate vanishes there.
      const g = pinGroup({ key:"apsis:" + ap.kind, alt_km: ap.alt_km, gamma_deg: 0,
                           title: ap.kind === "P" ? "perigee" : "apogee",
                           rows: [["t+", (ap.t_s / 60).toFixed(1) + " min"]] },
                         ap.lat_deg, ap.lon_deg, at);
      el("circle", { cx:x, cy:y, r:4,
                     fill: ap.kind === "P" ? C.blue : "#fcfcfb",
                     stroke: C.blue, "stroke-width":1.6 }, g);
      el("text", { x:x+7, y:y+4, fill:C.blue, "font-size":11, "font-weight":600 }, g)
        .textContent = ap.kind + " " + ap.alt_km.toFixed(0) + " km";
    }

    // entry interface crossing (drag modes) and ground impact (modes that fly to the ground)
    if (tr.entry) marker(tr.entry.lat_deg, tr.entry.lon_deg,
                         tr.impact ? C.orange : C.red, "target", "entry",
                         { key:"entry", title:"entry interface", alt_km:100,
                           gamma_deg: fpaDeg(tr, idxAtTime(tr.entry.t_s, tr)),
                           rows: [["utc", tr.entry.epoch_utc.replace("T", " ").slice(5, 19) + "Z"]] });
    if (tr.impact) marker(tr.impact.lat_deg, tr.impact.lon_deg, C.red,
                          "target", "impact",
                          { key:"impact", title:"impact", alt_km: tr.impact.last_alt_km,
                            gamma_deg: fpaDeg(tr, idxAtTime(tr.impact.t_s, tr)),
                            rows: [["utc", tr.impact.epoch_utc.replace("T", " ").slice(5, 19) + "Z"]] });
  }

  // module map layers drawn ON TOP of the track (markers, callouts)
  for (const fn of MP.live(MP._over)) {
    try { fn(layerCtx()); }
    catch (e) { console.error("module layer:", e); }
  }

  // agent scene layers
  if (scene) drawScene();

  // limb shading over the land lines, under the pins
  if (projMode !== "map")
    el("circle", { cx:GLOBE.cx, cy:GLOBE.cy, r:GR, fill:"url(#limbshade)",
                   stroke:C.grid, "stroke-width":1, "pointer-events":"none" });

  // the open marker's callout, last so nothing can draw over it
  if (pinHit) drawPin(pinHit);
}

const SCENE_COLORS = [C.blue, C.orange, C.green, C.red];
function drawScene() {
  let ci = 0, mi = 0; const items = [];
  for (const layer of scene.layers) {
    const color = layer.color || (ci < 4 ? SCENE_COLORS[ci++] : C.muted);
    if (layer.kind === "track") {
      const pts = layer.lat.map((la, i) => [la, layer.lon[i]]);
      polyline(pts, { stroke: color, "stroke-width": layer.width || 1.6,
                      "stroke-dasharray": layer.dash || "" });
      items.push([color, layer.name]);
    } else if (layer.kind === "marker") {
      marker(layer.lat, layer.lon, color, layer.symbol || "dot", layer.name,
             { key:"scene:" + (mi++), title: layer.name || "marker" });
      items.push([color, layer.name]);
    } else if (layer.kind === "polygon") {
      // scene.py: polygon {color?, fill?} -- fill defaults to the outline colour
      polygon(layer.lat, layer.lon, { fill: layer.fill || color, opacity:.15,
                                      stroke: color, "stroke-width":1 });
      items.push([color, layer.name]);
    } else if (layer.kind === "label") {
      const p = project(layer.lat, layer.lon);
      if (p.vis)
        el("text", { x:p.x, y:p.y, fill: layer.color || "#0b0b0b",
                     "font-size":11 }).textContent = layer.text;
    }
  }
  // The legend is built from agent-supplied strings: escape every one.
  const lg = $("legend");
  const rows = items.filter(i => i[1]).map(([c, n]) =>
    `<div><span class="sw" style="background:${escHtml(c)}"></span>${escHtml(n)}</div>`);
  const tables = scene.layers.filter(l => l.kind === "windows");
  let html = (scene.title ? `<b>${escHtml(scene.title)}</b>` : "") + rows.join("");
  for (const tb of tables) {
    html += `<div class="lbl">${escHtml(tb.name)}</div><table style="border-collapse:collapse">`
      + `<tr>${tb.columns.map(c => `<th style="text-align:left;padding:0 6px 0 0">${escHtml(c)}</th>`).join("")}</tr>`
      + tb.rows.map(r => `<tr>${r.map(v => `<td style="padding:0 6px 0 0">${escHtml(v)}</td>`).join("")}</tr>`).join("")
      + "</table>";
  }
  lg.innerHTML = html;
  lg.style.display = html ? "block" : "none";
}

// ------------------------------------------------------------ pan / zoom / click
// Map: one 360-degree strip drawn around lonC.  Horizontal drag rotates lonC,
// so the map scrolls endlessly with the seam on the far side of the globe;
// vertical drag pans (clamped) when zoomed in; the wheel zooms about the
// cursor.  Globe and orbit views: drag rotates (lonC / latC); the wheel zooms about its
// centre.  Double-click resets the zoom in every view.
(function () {
  const svg = $("map");
  const W = 360 * S, H = 180 * S;
  let down = null, moved = false;
  // getScreenCTM accounts for the preserveAspectRatio letterboxing that a
  // plain boundingClientRect division does not (clicks landed offset).
  const toMap = (ev) => {
    const p = new DOMPoint(ev.clientX, ev.clientY)
      .matrixTransform(svg.getScreenCTM().inverse());
    return { x: p.x, y: p.y };
  };
  const clampY = y => Math.max(0, Math.min(H - view.h, y));
  svg.addEventListener("mousedown", ev => {
    // A drag is a pan/rotate, never a text selection (labels, or the side panel
    // if the pointer strays onto it).
    ev.preventDefault();
    down = { ev, lonC, latC, y: view.y, scale: svg.getScreenCTM().a };
    moved = false; svg.classList.add("dragging");
  });
  window.addEventListener("mousemove", ev => {
    if (!down) return;
    const dx = (ev.clientX - down.ev.clientX) / down.scale;
    const dy = (ev.clientY - down.ev.clientY) / down.scale;
    if (Math.abs(ev.clientX - down.ev.clientX) + Math.abs(ev.clientY - down.ev.clientY) > 4) moved = true;
    if (!moved) return;
    if (projMode !== "map") {
      // the point under the cursor follows it (about one radian per screen
      // radius -- GR, which is smaller than GLOBE.R in the orbit view)
      lonC = normLon(down.lonC - dx / GR / DEG);
      latC = Math.max(-89, Math.min(89, down.latC + dy / GR / DEG));
    } else {
      lonC = normLon(down.lonC - dx / S);   // drag right -> the world moves right
      view.y = clampY(down.y - dy);
    }
    redraw();
  });
  window.addEventListener("mouseup", ev => {
    svg.classList.remove("dragging");
    if (down && !moved) {
      const p = toMap(ev), ll = unproject(p.x, p.y);
      if (ll)
        for (const fn of MP.live(MP._clicks)) {
          try { fn(ll.lat, ll.lon); }
          catch (e) { console.error("module click:", e); }
        }
    }
    down = null;
  });
  svg.addEventListener("wheel", ev => {
    ev.preventDefault();
    const f = ev.deltaY > 0 ? 1.2 : 1/1.2;
    const w = Math.min(W, Math.max(40, view.w * f)), h = w / 2;
    if (projMode !== "map") {
      view = { x: GLOBE.cx - w / 2, y: GLOBE.cy - h / 2, w, h };
      return redraw();
    }
    const p = toMap(ev);
    const fx = (p.x - view.x) / view.w, fy = (p.y - view.y) / view.h;
    const cursorLon = p.x / S - 180 + lonC;
    // Keep the view box centred and put the cursor's longitude back under
    // the cursor by rotating lonC; latitude by moving the box vertically.
    view.w = w; view.h = h; view.x = (W - w) / 2;
    lonC = normLon(cursorLon - (view.x + fx * w) / S + 180);
    view.y = clampY(p.y - fy * h);
    redraw();
  }, { passive:false });
  svg.addEventListener("dblclick", () => { view = { x:0, y:0, w:W, h:H }; redraw(); });
})();
// Projection switch (View menu); the view resets, the longitude carries over.
function setProj(mode) {
  projMode = mode;
  view = { x:0, y:0, w:360 * S, h:180 * S };
  redraw();
}
