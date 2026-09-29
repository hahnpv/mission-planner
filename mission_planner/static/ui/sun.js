"use strict";
// Sun position and the day/night terminator, in both views.
function solarSubpoint(dateMs) {
  const d = dateMs / 86400000 - 10957.5;          // days since J2000.0
  const L = (280.460 + 0.9856474 * d) % 360;
  const g = (357.528 + 0.9856003 * d) * DEG;
  const lam = (L + 1.915 * Math.sin(g) + 0.020 * Math.sin(2*g)) * DEG;
  const eps = 23.439 * DEG;
  const decl = Math.asin(Math.sin(eps) * Math.sin(lam));
  const ra = Math.atan2(Math.cos(eps) * Math.sin(lam), Math.cos(lam));
  const gmst = ((280.46061837 + 360.98564736629 * d) % 360) * DEG;
  return { lat: decl / DEG, lon: normLon((ra - gmst) / DEG) };
}
// Night hemisphere on the globe: the terminator great circle, clipped to the
// visible side and closed along the limb through the dark side.
function drawNightGlobe(sun) {
  const s = vec(sun.lat, sun.lon);
  const ref = Math.abs(s[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0];
  let a = cross(s, ref);
  const m = Math.hypot(...a); a = a.map(q => q / m);
  const b = cross(s, a);
  const ring = [];
  for (let t = 0; t < 360; t += 2)
    ring.push([0, 1, 2].map(i => a[i] * Math.cos(t * DEG) + b[i] * Math.sin(t * DEG)));
  const dark = v => dot(v, s) < 0;
  if (dark(B.n) && ring.every(v => dot(v, B.n) < 1e-9)) {   // facing midnight: all dark
    el("circle", { cx: GLOBE.cx, cy: GLOBE.cy, r: GR, fill:"#1c2733", opacity:.10,
                   "pointer-events":"none" });
    return;
  }
  polygonGlobe(ring, { fill:"#1c2733", opacity:.10, "pointer-events":"none" }, null, dark);
}
function terminatorPath(sun) {
  // Night-side polygon in SCREEN longitude (s = lon - lonC): immune to the
  // wrap seam, closed over the dark pole.
  const pts = [];
  const tanDecl = Math.tan(Math.max(Math.abs(sun.lat), 0.01) * DEG) * Math.sign(sun.lat || 1);
  for (let s = -180; s <= 180; s += 2) {
    const H = (s + lonC - sun.lon) * DEG;
    pts.push([Math.atan(-Math.cos(H) / tanDecl) / DEG, (s + 180) * S]);
  }
  const poleY = sun.lat >= 0 ? Y(-90) : Y(90);
  let dPath = "M" + pts.map(p => p[1].toFixed(1) + " " + Y(p[0]).toFixed(1)).join(" L");
  dPath += ` L ${360 * S} ${poleY} L 0 ${poleY} Z`;
  return dPath;
}
