"use strict";
// Three views of the same drawing: "map" (equirectangular strip around lonC),
// "globe" (orthographic, centred on latC/lonC) and "orbit" (the globe shrunk
// to fit, with the orbit drawn in space around it).  Everything that places
// a point goes through project(), and polyline/polygon/marker clip to the
// visible hemisphere on the globe, so every layer -- core, built-ins,
// plugins, agent scenes -- draws in both views unchanged.

// ------------------------------------------------------------ longitude wrap
const normLon = lon => ((lon + 540) % 360 + 360) % 360 - 180;   // [-180, 180)
const wrapL = lon => normLon(lon - lonC);                        // relative to the map centre
const X = lon => (wrapL(lon) + 180) * S;   // map view only
const Y = lat => (90 - lat) * S;

// ------------------------------------------------------------ globe basis
function globeBasis() {
  const la = latC * DEG, lo = lonC * DEG;
  B = { n: [Math.cos(la) * Math.cos(lo), Math.cos(la) * Math.sin(lo), Math.sin(la)],
        e: [-Math.sin(lo), Math.cos(lo), 0],
        u: [-Math.sin(la) * Math.cos(lo), -Math.sin(la) * Math.sin(lo), Math.cos(la)] };
}
globeBasis();
const vec = (lat, lon) => {
  const la = lat * DEG, lo = lon * DEG;
  return [Math.cos(la) * Math.cos(lo), Math.cos(la) * Math.sin(lo), Math.sin(la)];
};
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const onScreen = v => [GLOBE.cx + GR * dot(v, B.e), GLOBE.cy - GR * dot(v, B.u)];
// {x, y, vis}: screen position and whether the point faces the viewer.
function project(lat, lon) {
  if (projMode === "map") return { x: X(lon), y: Y(lat), vis: true };
  const v = vec(lat, lon), [x, y] = onScreen(v);
  return { x, y, vis: dot(v, B.n) >= 0 };
}
// Screen point -> {lat, lon}, or null off the globe / map.
function unproject(x, y) {
  if (projMode === "map") {
    const lat = 90 - y / S;
    if (lat < -90 || lat > 90 || x < 0 || x > 360 * S) return null;
    return { lat, lon: normLon(x / S - 180 + lonC) };
  }
  const a = (x - GLOBE.cx) / GR, b = (GLOBE.cy - y) / GR;
  const w2 = 1 - a * a - b * b;
  if (w2 < 0) return null;
  const w = Math.sqrt(w2), v = [0, 1, 2].map(i => a * B.e[i] + b * B.u[i] + w * B.n[i]);
  return { lat: Math.asin(v[2]) / DEG, lon: Math.atan2(v[1], v[0]) / DEG };
}

// ------------------------------------------------------------ orbit view
// Track samples are earth-fixed; turning each one east by the earth's
// rotation between its time and the scrub time puts it in the frame of the
// earth as drawn (oriented at tCur), which is the inertial orbit -- a closed
// ellipse, not a ground-track spiral.  That's "ECI" in the View menu: the
// shape is ECI's, the axes are the earth's at tCur (no precession or
// nutation).  "ECEF" skips the turn: the ground track lifted to altitude.
// Vectors are in earth radii.
function orbitVec(lat, lon, alt_km, t_s) {
  const k = 1 + alt_km / RE_KM;
  const turn = orbitView.frame === "eci" ? OMEGA_E_DEG * (t_s - tCur) : 0;
  return vec(lat, lon + turn).map(q => q * k);
}
// Hidden only when behind the earth AND inside its disc.
const occluded = v => dot(v, B.n) < 0 && dot(v, B.e) ** 2 + dot(v, B.u) ** 2 < 1;
function spacePoint(v) { const [x, y] = onScreen(v); return { x, y, vis: !occluded(v) }; }
// Earth radius on screen for the orbit view: the highest point of any track fits.
function orbitRadius() {
  let hi = 0;
  for (const tr of planTracks()) for (const a of tr.alt_km) if (a > hi) hi = a;
  return GLOBE.R / ((1 + Math.max(hi, 600) / RE_KM) * 1.04);
}

// ------------------------------------------------------------ limb helpers
// Where the chord a->b crosses the limb plane, pushed back onto the sphere.
// a, b: {v, c} with c = dot(v, B.n).
function limbPoint(a, b) {
  const t = a.c / (a.c - b.c);
  const p = [0, 1, 2].map(i => a.v[i] + t * (b.v[i] - a.v[i]));
  const m = Math.hypot(...p);
  return p.map(q => q / m);
}
const limbEdge = (a, b) => limbPoint({ v: a, c: dot(a, B.n) }, { v: b, c: dot(b, B.n) });
const behindLimb = v => dot(v, B.n) < 0;
// Points along the limb from p to q; the short way unless `inside` says the
// short arc's midpoint is outside the region being closed.
function limbArc(p, q, inside) {
  const ang = v => Math.atan2(dot(v, B.u), dot(v, B.e));
  const t0 = ang(p);
  let d = ang(q) - t0;
  d = Math.atan2(Math.sin(d), Math.cos(d));
  const at = t => [0, 1, 2].map(i => B.e[i] * Math.cos(t) + B.u[i] * Math.sin(t));
  if (inside && !inside(at(t0 + d / 2))) d -= Math.sign(d || 1) * 2 * Math.PI;
  const n = Math.ceil(Math.abs(d) / (3 * DEG)), out = [];
  for (let k = 1; k < n; k++) out.push(at(t0 + d * k / n));
  return out;
}

// ------------------------------------------------------------ svg helpers
function el(tag, attrs, parent) {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  (parent || $("map")).appendChild(e);
  return e;
}
// 3-vectors as screen polylines, broken wherever hidden(v) says so.  With
// `edge(a, b)` given, a run ends / starts at edge(a, b): the point where the
// chord a->b crosses the boundary (the limb, for lines on the surface).
function clippedPolyline(vs, hidden, attrs, parent, edge) {
  let run = [], prev = null;
  const flush = () => {
    if (run.length > 1)
      el("polyline", { ...attrs, fill:"none",
        points: run.map(v => onScreen(v).map(q => q.toFixed(1)).join(",")).join(" ") }, parent);
    run = [];
  };
  for (const v of vs) {
    const h = hidden(v);
    if (!h) {
      if (prev && prev.h && edge) run.push(edge(prev.v, v));
      run.push(v);
    } else {
      if (prev && !prev.h && edge) run.push(edge(prev.v, v));
      flush();
    }
    prev = { v, h };
  }
  flush();
}
// A line in space (orbit view): hidden only behind the earth's disc.
const spaceLine = (vs, attrs, parent) => clippedPolyline(vs, occluded, attrs, parent);
// A line on the surface, on the globe: clipped at the limb.
const polylineGlobe = (pts, attrs, parent) =>
  clippedPolyline(pts.map(([la, lo]) => vec(la, lo)), behindLimb, attrs, parent, limbEdge);
// polyline that splits at the map seam (center-dependent antimeridian), or on
// the globe at the limb
function polyline(pts, attrs, parent) {
  if (projMode !== "map") return polylineGlobe(pts, attrs, parent);
  let run = [];
  const flush = () => {
    if (run.length > 1)
      el("polyline", { ...attrs, fill:"none",
        points: run.map(p => X(p[1]).toFixed(1) + "," + Y(p[0]).toFixed(1)).join(" ") }, parent);
    run = [];
  };
  for (let i = 0; i < pts.length; i++) {
    if (i && Math.abs(wrapL(pts[i][1]) - wrapL(pts[i-1][1])) > 180) flush();
    run.push(pts[i]);
  }
  flush();
}
// filled polygon that survives the seam: unwrap the ring to a contiguous
// strip, then draw shifted copies; the svg viewport clips the offscreen ones.
// On the globe: clipped to the visible hemisphere, closed along the limb.
// `inside(v)` picks the limb arc for regions a hemisphere or larger (night).
function polygon(latArr, lonArr, attrs, parent, inside) {
  if (projMode !== "map")
    return polygonGlobe(latArr.map((la, i) => vec(la, lonArr[i])), attrs, parent, inside);
  let cum = wrapL(lonArr[0]);
  const xs = [cum];
  for (let i = 1; i < lonArr.length; i++) {
    cum += normLon(lonArr[i] - lonArr[i-1]);
    xs.push(cum);
  }
  // A ring around a pole (a large footprint at high latitude) winds a full
  // 360 deg of longitude: close it along that pole's edge of the map instead
  // of straight across it.
  const lats = latArr.slice();
  const wound = Math.abs(cum + normLon(lonArr[0] - lonArr[lonArr.length - 1]) - xs[0]) > 180;
  if (wound) {
    const pole = lats.reduce((a, b) => a + b, 0) >= 0 ? 90 : -90;
    const xEnd = xs[xs.length - 1] + normLon(lonArr[0] - lonArr[lonArr.length - 1]);
    xs.push(xEnd, xEnd, xs[0]);
    lats.push(latArr[0], pole, pole);
  }
  for (const off of [-360, 0, 360]) {
    const pts = xs.map((x, i) =>
      `${((x + off + 180) * S).toFixed(1)},${Y(lats[i]).toFixed(1)}`);
    if (!wound) { el("polygon", { ...attrs, points: pts.join(" ") }, parent); continue; }
    // Fill the closed shape, but stroke only the real ring, not the edges
    // added along the pole.
    el("polygon", { ...attrs, stroke: "none", points: pts.join(" ") }, parent);
    el("polyline", { ...attrs, fill: "none", points: pts.slice(0, latArr.length + 1).join(" ") }, parent);
  }
}
function polygonGlobe(vs, attrs, parent, inside) {
  const cs = vs.map(v => dot(v, B.n)), n = vs.length;
  const draw = ring => el("polygon", { ...attrs,
    points: ring.map(v => onScreen(v).map(q => q.toFixed(1)).join(",")).join(" ") }, parent);
  if (cs.every(c => c < 0)) return;
  if (cs.every(c => c >= 0)) return draw(vs);
  const start = cs.findIndex(c => c >= 0), out = [];
  let exit = null;
  for (let k = 0; k < n; k++) {
    const i = (start + k) % n, j = (i + 1) % n;
    const a = { v: vs[i], c: cs[i] }, b = { v: vs[j], c: cs[j] };
    if (a.c >= 0) out.push(a.v);
    if (a.c >= 0 && b.c < 0) { exit = limbPoint(a, b); out.push(exit); }
    else if (a.c < 0 && b.c >= 0) {
      const entry = limbPoint(a, b);
      if (exit) out.push(...limbArc(exit, entry, inside));
      out.push(entry);
    }
  }
  draw(out);
}
