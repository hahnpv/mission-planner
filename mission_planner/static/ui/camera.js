"use strict";
// Standard camera views: one click points the globe / orbit view along a
// direction that means something -- down on a pole, square to the orbit
// plane, edge-on to it, over the vehicle, from the sun.  The camera is the
// view direction (latC / lonC, earth-fixed at the playback time; north stays
// up) plus the zoom; a view sets the direction and resets the zoom.
//
// "follow" re-aims the chosen view on every redraw, so it holds as playback
// runs (the orbit plane turns under the earth's axes, the vehicle moves on);
// a drag on the map lets go of it.  From the flat map a view switches to the
// orbit view, except "over vehicle", which just centres the map on it.
// The bar is pinned to the bottom of the side panel (#camerabar).

// Where the focused vehicle is, in the earth's axes at the playback time
// (the orbit view's ECI frame), in earth radii: sample k turned east by the
// earth's rotation between its time and tCur.
function inertialAt(tr, k) {
  const turn = OMEGA_E_DEG * (tr.t[k] - tCur);
  return vec(tr.lat[k], tr.lon[k] + turn).map(q => q * (1 + tr.alt_km[k] / RE_KM));
}
const unit = v => { const m = Math.hypot(...v); return m > 1e-12 ? v.map(q => q / m) : null; };
// The focused track's orbit normal (r x v) at the playback time, or null.
function orbitNormal() {
  const tr = plan?.track;
  if (!tr || tr.t.length < 2) return null;
  const k = Math.min(idxAtTime(tCur, tr), tr.t.length - 2);
  return unit(cross(inertialAt(tr, k), inertialAt(tr, k + 1)));
}
const sunNow = () => solarSubpoint(plan
  ? Date.parse(plan.track.epoch_utc) + tCur * 1000 : Date.now());

// Each view: a direction to look along (from outside, toward the earth's
// centre), or null when it doesn't apply yet (no plan).
const CAMERA_VIEWS = [
  { id: "north", label: "N pole", title: "look down on the north pole", dir: () => [0, 0, 1] },
  { id: "south", label: "S pole", title: "look up at the south pole", dir: () => [0, 0, -1] },
  { id: "face", label: "face-on", title: "square to the orbit plane: the orbit's true shape",
    dir: orbitNormal },
  { id: "edge", label: "edge-on", title: "in the orbit plane, along the line of nodes: "
      + "the plane as a line tilted by the inclination",
    dir: () => {
      const h = orbitNormal();
      if (!h) return null;
      // Node line = z x h; an equatorial orbit has none, so look along the vehicle instead.
      return unit(cross([0, 0, 1], h)) || unit(inertialAt(plan.track, idxAtTime(tCur)));
    } },
  { id: "vehicle", label: "vehicle", title: "straight down on the vehicle",
    dir: () => plan ? unit(inertialAt(plan.track, idxAtTime(tCur))) : null },
  { id: "sun", label: "sun", title: "from the sun: the day side",
    dir: () => { const s = sunNow(); return vec(s.lat, s.lon); } },
];
const camera = { follow: false, current: null };

// Aim along a view's direction; `keepZoom` when re-aiming during follow.
function aimCamera(v, keepZoom) {
  const d = v.dir();
  if (!d) return false;
  if (projMode === "map") {
    if (v.id !== "vehicle") setProj("orbit");
    else {                       // the flat map can only centre the longitude
      lonC = normLon(Math.atan2(d[1], d[0]) / DEG);
      return true;
    }
  }
  latC = Math.max(-89, Math.min(89, Math.asin(Math.max(-1, Math.min(1, d[2]))) / DEG));
  lonC = normLon(Math.atan2(d[1], d[0]) / DEG);
  if (!keepZoom) view = { x: 0, y: 0, w: 360 * S, h: 180 * S };
  return true;
}
function setCameraView(id) {
  const v = CAMERA_VIEWS.find(x => x.id === id);
  if (!v) return;
  if (!aimCamera(v, false)) { status(`the ${v.label} view needs a plan first.`, true); return; }
  camera.current = id;
  renderCamera();
  redraw();
}
// Called at the top of every redraw (map.js): follow keeps the view aimed.
function cameraBeforeDraw() {
  if (!camera.follow || !camera.current) return;
  // Back on the flat map (View menu), only "vehicle" still means anything.
  if (projMode === "map" && camera.current !== "vehicle") return cameraReleased();
  const v = CAMERA_VIEWS.find(x => x.id === camera.current);
  if (v) aimCamera(v, true);
}
// A drag lets go of the view (map.js calls this when one starts).
function cameraReleased() {
  if (!camera.current) return;
  camera.current = null;
  renderCamera();
}

function renderCamera() {
  const box = $("camerabar");
  box.querySelectorAll("button[data-cam]").forEach(b =>
    b.classList.toggle("on", b.dataset.cam === camera.current));
  $("camfollow").checked = camera.follow;
}
(function buildCamera() {
  const box = $("camerabar");
  box.innerHTML = `<div class="lbl">camera</div>
    <div class="camgrid">${CAMERA_VIEWS.map(v =>
      `<button class="small ghost" data-cam="${v.id}" title="${escHtml(v.title)}">${escHtml(v.label)}</button>`).join("")}</div>
    <label class="camfollow" title="keep the view aimed as playback runs">
      <input id="camfollow" type="checkbox"> follow</label>`;
  box.querySelectorAll("button[data-cam]").forEach(b => b.onclick = () => setCameraView(b.dataset.cam));
  $("camfollow").onchange = () => {
    camera.follow = $("camfollow").checked;
    if (camera.follow && camera.current) redraw();
  };
})();
