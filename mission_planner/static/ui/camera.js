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
//
// "screenshot" copies the main pane (the map / globe / orbit SVG, plugin
// layers included) to the clipboard as a PNG, or downloads it where the
// clipboard can't take images (an older browser, a non-localhost http page).

// Where a vehicle is at sample k, in the earth's axes at the playback time
// (the orbit view's ECI frame, whatever frame that view is set to), in
// earth radii.
const inertialAt = (tr, k) => orbitVec(tr.lat[k], tr.lon[k], tr.alt_km[k], tr.t[k], "eci");
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

// The main pane as a PNG blob at twice its on-screen size.  The SVG's own
// attributes carry its colours; the page supplies only the background and
// the font, which a detached image would lose, so they are written in.
function mapPng() {
  const svg = $("map"), css = getComputedStyle(svg);
  const w = svg.clientWidth, h = svg.clientHeight, scale = 2;
  const clone = svg.cloneNode(true);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", w);
  clone.setAttribute("height", h);
  clone.setAttribute("style", `font-family:${css.fontFamily}; font-size:${css.fontSize}`);
  const bg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  const vb = svg.viewBox.baseVal;
  // Cover the whole pane, letterbox included (preserveAspectRatio "meet").
  const k = Math.max(vb.width / w, vb.height / h);
  Object.entries({ x: vb.x + (vb.width - w * k) / 2, y: vb.y + (vb.height - h * k) / 2,
                   width: w * k, height: h * k, fill: css.backgroundColor })
    .forEach(([a, v]) => bg.setAttribute(a, v));
  clone.insertBefore(bg, clone.firstChild);
  const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)],
                                           { type: "image/svg+xml" }));
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const c = document.createElement("canvas");
      c.width = w * scale; c.height = h * scale;
      const g = c.getContext("2d");
      g.scale(scale, scale);
      g.drawImage(img, 0, 0, w, h);
      URL.revokeObjectURL(url);
      c.toBlob(b => b ? resolve(b) : reject(new Error("the canvas gave no image")), "image/png");
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("the map would not render")); };
    img.src = url;
  });
}
async function takeScreenshot() {
  const png = mapPng();
  try {
    // Hand the clipboard a promise, inside the click: Safari needs that.
    await navigator.clipboard.write([new ClipboardItem({ "image/png": png })]);
    status("screenshot copied to the clipboard.");
    return "clipboard";
  } catch (err) {
    let blob;
    try { blob = await png; } catch (e) { status(`screenshot failed: ${e.message}`, true); return "failed"; }
    download(`mission-planner-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.png`,
             blob, "image/png");
    status("the clipboard can't take images here: screenshot downloaded instead.");
    return "download";
  }
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
    <div class="camfollow">
      <label title="keep the view aimed as playback runs"><input id="camfollow" type="checkbox"> follow</label>
      <button id="camshot" class="small ghost" title="copy the main pane to the clipboard as a PNG">take screenshot</button>
    </div>`;
  $("camshot").onclick = takeScreenshot;
  box.querySelectorAll("button[data-cam]").forEach(b => b.onclick = () => setCameraView(b.dataset.cam));
  $("camfollow").onchange = () => {
    camera.follow = $("camfollow").checked;
    if (camera.follow && camera.current) redraw();
  };
})();
