"use strict";
// The side panel: trajectory source, orbit shape, anchor and propagation
// controls, planning requests, presets and the catalog.

// ------------------------------------------------------------ planning
// The request args for the current form: the source's own, then the shared
// orbit shape (any source declaring shape), epoch and span (an orbit source,
// or one declaring propagate) and the propagation mode (an orbit source).
const propagates = src => src.kind === "orbit" || !!src.propagate;
function args() {
  const src = currentSource(), a = new URLSearchParams();
  a.set("source", src.id);
  src.args(a);
  if (src.shape) {
    a.set("hp", $("peri").value); a.set("inc", $("inc").value);
    if ($("apo").value) a.set("ha", $("apo").value);
  }
  if (propagates(src)) {
    a.set("hours", +horizonHours().toFixed(3));
    const ep = epochValue();
    if (ep) a.set("epoch", ep + ":00+00:00");
  }
  if (src.kind === "orbit") {
    const hours = horizonHours();
    a.set("mode", $("mode").value);
    if (modeInfo($("mode").value).needs_beta) a.set("beta", $("beta").value);
    // dt: the mirror of planning.default_dt (TARGET_POINTS 20000, 30 s floor)
    const dt = Math.max(30, Math.round(hours * 3600 / 20000 / 10) * 10);
    a.set("dt", dt);
  }
  return a;
}
// Propagation modes: the core's two plus any an active plugin provides.
const CORE_MODES = { kepler: { mode: "kepler", needs_beta: false },
                     decay: { mode: "decay", needs_beta: true } };
function modeInfo(mode) {
  if (CORE_MODES[mode]) return CORE_MODES[mode];
  for (const m of Object.values(MP.mods))
    if (m.active) for (const x of m.modes || []) if (x.mode === mode) return x;
  return { mode, needs_beta: false };
}
function buildModeSelect() {
  const sel = $("mode"), cur = sel.value;
  sel.querySelectorAll("option[data-plugin]").forEach(o => o.remove());
  for (const m of Object.values(MP.mods)) {
    if (!m.active) continue;
    for (const x of m.modes || []) {
      const o = document.createElement("option");
      o.value = x.mode; o.textContent = x.label; o.dataset.plugin = m.name;
      sel.appendChild(o);
    }
  }
  if (![...sel.options].some(o => o.value === cur)) {
    sel.value = "kepler";
    status(`mode ${cur} is no longer available — back to kepler.`);
  } else sel.value = cur;
  sel.onchange();
}
// Every plan request takes a sequence number; a response (or job poll) whose
// number is no longer current is dropped, so a slow run can't overwrite a
// newer plan.
let planSeq = 0;
let lastAsked = null, lastSource = null;   // the last plan request: args (a string), source id
async function doPlan(keep = false) {
  clearTimeout(autoTimer);
  const src = currentSource();
  if (!src.ready()) return;
  if (propagates(src) && !epochValue()) {
    status("epoch must read YYYY-MM-DD HH:MM (UTC)", true);
    return;
  }
  lastAsked = String(args()); lastSource = src.id;
  if (src.kind === "orbit") {
    const m = modeInfo($("mode").value);
    if (m.slow) return doJobPlan(m.mode);
  } else if (src.slow) return doJobPlan(src.label);
  const my = ++planSeq;
  status("planning…");
  let res;
  try { res = await api("/api/plan?" + args()); }
  catch (e) { if (my === planSeq) status("server unreachable: " + e.message, true); return; }
  if (my !== planSeq) return;
  if (res.error) { status(res.error, true); return; }
  applyPlan(res, keep);
}
// Auto-replan: with the box ticked and a plan on screen, a form change that
// alters the request replans it after a pause, keeping the scrub time, the
// shown window and the focused track.  Only the source on screen replans
// (picking another waits for the plan button), and slow runs (background
// jobs) are left to the plan button.  Changes are caught as they bubble up
// the side panel; a module's own inputs don't alter the request, so they
// cost nothing.
const AUTO_KEY = "mp.autoplan", AUTO_MS = 500;
let autoTimer = null;
try { $("autoplan").checked = localStorage.getItem(AUTO_KEY) !== "0"; } catch { $("autoplan").checked = true; }
$("autoplan").onchange = () => {
  try { localStorage.setItem(AUTO_KEY, $("autoplan").checked ? "1" : "0"); } catch {}
  scheduleReplan();
};
function scheduleReplan() {
  clearTimeout(autoTimer);
  if ($("autoplan").checked && plan) autoTimer = setTimeout(autoReplan, AUTO_MS);
}
function autoReplan() {
  const src = currentSource();
  if (!plan || src.id !== lastSource || !src.ready() || (propagates(src) && !epochValue())) return;
  if (src.kind === "orbit" ? modeInfo($("mode").value).slow : src.slow) return;
  if (String(args()) !== lastAsked) doPlan(true);
}
for (const ev of ["input", "change", "click"])
  $("sidescroll").addEventListener(ev, e => { if (e.target.id !== "plan") scheduleReplan(); });
// Slow plugin modes and sources run as a background job on the server; poll
// until done.  `what` names it in the status line.
async function doJobPlan(what) {
  const my = ++planSeq;
  status(`starting ${what} run…`);
  let job;
  try { job = await apiPost("/api/plan_job?" + args()); }
  catch (e) { if (my === planSeq) status("server unreachable: " + e.message, true); return; }
  if (my !== planSeq) return;
  if (job.error) { status(job.error, true); return; }
  const poll = async () => {
    if (my !== planSeq) return;
    let res;
    try { res = await api("/api/plan_job/" + job.job_id); }
    catch (e) { if (my === planSeq) status("server unreachable: " + e.message, true); return; }
    if (my !== planSeq) return;
    if (res.status === "running") {
      status(`${what} running… ${Math.round(res.elapsed_s)} s`);
      setTimeout(poll, 2000);
    } else if (res.status === "error" || res.error) {   // the run failed, or the job is unknown
      status(res.error, true);
    } else {
      applyPlan(res);
    }
  };
  poll();
}
// keep: hold on to the scrub time, the shown window and the focused track
// (an auto-replan).
function applyPlan(res, keep = false) {
  if (!res.track || !res.track.t || res.track.t.length < 2) {
    status("plan has no track points", true);
    return;
  }
  // Only the plan itself: a job result also carries its bookkeeping
  // (status, elapsed_s), which must not leak into the plan.  `args` are the
  // query args that produced it (ctx.planArgs).
  const focus = keep && plan?.track.id;
  plan = { summary: res.summary, track: res.track, tracks: res.tracks, primary: res.primary,
           args: res.args };
  if (focus) plan.track = plan.tracks?.find(x => x.id === focus) || plan.track;
  // A scene that came with a plan annotates that plan (its target, passes):
  // it goes when another plan replaces it.  A plain scene stays.
  if (scene?.plan && res !== scene.plan) scene = null;
  const w = keep ? [...win] : [0, 1];
  if (!keep) tCur = 0;
  pinOpen = null;
  renderTrackPicker();
  const s = plan.summary;
  const row = r => `<tr><td>${r[0]}</td><td>${r[1]}</td></tr>`;
  // The launch site, when there is one: element-anchored (preset) orbits have none.
  $("summary").innerHTML = s.site_lat == null ? "" :
    `<details class="modbox" style="border-top:none;margin-top:0;padding-top:0" open>
       <summary class="lbl">launch site</summary><table>` + [
      ["site", escHtml(s.site)],
      ["lat", s.site_lat.toFixed(3) + "°"],
      ["lon", s.site_lon.toFixed(3) + "°"],
      ["launch azimuth", s.launch_azimuth_deg + "°"],
    ].map(row).join("") + "</table></details>";
  // Modules that don't work with this kind of trajectory go inert before any
  // onPlan callback runs.
  syncModules();
  // "1 rev" only means something for an orbit.
  document.querySelector("[data-win=rev]").hidden = s.kind === "trajectory";
  if (s.kind === "trajectory") {
    status(`showing ${s.title || s.source} (${new Date().toISOString().slice(11, 19)}Z)`);
    $("elements").innerHTML = "";
    setWindow(...w);
    MP.fire(MP._onPlan, "module onPlan", plan);
    return;
  }
  const shape = s.e > 1e-4
    ? `${s.perigee_km.toFixed(0)}×${s.apogee_km.toFixed(0)} km`
    : `${s.alt_km.toFixed(0)} km`;
  const stamp = new Date().toISOString().slice(11, 19) + "Z";
  status(`planned ${s.title || s.site} · ${shape} / ${s.inc_deg}° · `
    + `${s.revs_per_day} rev/day` + (plan.track.entry ? " · DECAYS — see entry" : "")
    + ` (${stamp})`);
  $("elements").innerHTML = "<div class='lbl'>orbit</div><table>" + [
    ["period", (s.period_s/60).toFixed(1) + " min"],
    ["revs / day", s.revs_per_day],
    ["raan drift", s.raan_drift_deg_per_day + "°/day"],
  ].map(row).join("") + "</table><div class='lbl'>orbital elements @ epoch</div><table>" + [
    ["a", s.a_km.toFixed(1) + " km"], ["e", s.e.toFixed(5)],
    ["i", s.inc_deg + "°"], ["&Omega; (RAAN)", s.raan_deg + "°"],
    ["&omega; (arg perigee)", s.argp_deg + "°"], ["&nu;&#8320;", s.nu0_deg + "°"],
  ].map(row).join("") + "</table>";
  setWindow(...w);
  MP.fire(MP._onPlan, "module onPlan", plan);
}
$("plan").onclick = () => doPlan();

// ------------------------------------------------------------ multi-track plans
// A plan with several tracks (plan.tracks, e.g. a constellation) keeps one in
// focus as plan.track: the panels, markers and modules work on that one; the
// others draw faintly.  The picker and a click on a vehicle move the focus,
// and modules hear about it through their onPlan hooks.
function renderTrackPicker() {
  $("trackpick").hidden = !plan?.tracks;
  if (!plan?.tracks) return;
  $("trackcount").textContent = plan.tracks.length;
  $("tracksel").replaceChildren(...plan.tracks.map(tr => new Option(tr.label || tr.id, tr.id)));
  $("tracksel").value = plan.track.id;
}
function setFocus(id) {
  const tr = plan?.tracks?.find(x => x.id === id);
  if (!tr || tr === plan.track) return;
  plan.track = tr;
  $("tracksel").value = id;
  MP.fire(MP._onPlan, "module onPlan", plan);
  redraw();
}
$("tracksel").onchange = () => setFocus($("tracksel").value);

// Open a stored file (uploads.py) in the File source (modules/files.py);
// with {plan: true} it is planned as soon as its reader has described it.
function openFile(id, opts = {}) {
  setSource("file");
  document.dispatchEvent(new CustomEvent("mp:open-file", { detail: { id, plan: !!opts.plan } }));
}
// A catalog preset can be a file a plugin fetches (catalog.py: `file_from`):
// POST to its route, which stores the file and answers with the upload.
async function openFilePreset(name, p) {
  status(`fetching ${name}…`);
  let res;
  try { res = await apiPost(p.file_from); }
  catch (e) { status(`${name}: server unreachable: ${e.message}`, true); return; }
  if (res.error) { status(`${name}: ${res.error}`, true); return; }
  openFile(res.id, { plan: true });
}

// ------------------------------------------------------------ orbit shape
// Every quantity is a typed number with a slider under it; the number is the
// source of truth.  The altitude sliders are log-scaled 120 .. 50 000 km, so
// LEO keeps fine resolution and GEO is within reach of a drag; the field
// takes anything.  A blank apogee means circular (the "circular" box).
const ALT_LO = Math.log(120), ALT_HI = Math.log(50000);
const altToSlider = km =>
  Math.round((Math.log(Math.min(50000, Math.max(120, km || 120))) - ALT_LO) / (ALT_HI - ALT_LO) * 1000);
function sliderToAlt(v) {
  const km = Math.exp(ALT_LO + v / 1000 * (ALT_HI - ALT_LO));
  const step = km < 2000 ? 5 : km < 10000 ? 10 : 50;
  return Math.round(km / step) * step;
}
let PRESETS = {};   // name -> {hp, ha, inc, argp?, node_lon?, raw} or {file_from} from /api/presets
let leg = "ascending";   // which leg of the orbit crosses the launch site

function periSync() {
  const hp = +$("peri").value, apo = $("apo").value, ha = apo ? Math.max(+apo, hp) : hp;
  $("alt").value = altToSlider(hp);
  $("apos").value = altToSlider(ha);
  $("circ").checked = !apo;
  $("aporow").hidden = !apo;
  $("eccv").textContent = apo ? "e = " + ((ha - hp) / (2 * RE_KM + hp + ha)).toFixed(3) : "";
  // Perigee position only means something for an elliptic orbit off a site.
  $("pofsrow").hidden = !(anchor === "site" && ha > hp);
  $("nodelbl").textContent = +$("inc").value === 0 && !apo && Math.abs(hp - 35786) < 100
    ? "station longitude" : "ascending node longitude";
  syncInc();
  shapeChanged();
}
function setCircular(on) {
  if (on) $("apo").value = "";
  else if (!$("apo").value) $("apo").value = $("peri").value;
  periSync();
}
// Typing in a field only mirrors it (no rewriting under the cursor); a
// finished edit (change) normalises it.
$("peri").oninput = periSync;
$("peri").onchange = () => {
  if ($("apo").value && +$("apo").value < +$("peri").value) $("apo").value = $("peri").value;
  periSync();
};
$("alt").oninput = () => {
  $("peri").value = sliderToAlt(+$("alt").value);
  if ($("apo").value && +$("apo").value < +$("peri").value) $("apo").value = $("peri").value;
  periSync();
};
$("apo").oninput = periSync;
$("apos").oninput = () => { $("apo").value = Math.max(sliderToAlt(+$("apos").value), +$("peri").value); periSync(); };
$("circ").onchange = () => setCircular($("circ").checked);

// Inclination has two resolutions.  The field and the slider keep 0.01 deg,
// so a COMPUTED inclination (SSO sync, a preset, anything set
// programmatically) survives intact; a hand-dragged slider snaps to a round
// 0.1 deg instead, and arrow keys (below) move a whole 0.1.
let incShown = +$("inc").value;
function setInc(v) {                    // the one way inclination is written
  $("inc").value = v;
  $("incs").value = v;
  incShown = +$("inc").value;
  syncInc();
}
const incClamp = v => Math.min(120, Math.max(0, v)).toFixed(1);
// The site's latitude is the least inclination it can launch into: the
// slider's floor and a hint, red while the value is below it.
function syncInc() {
  const inc = +$("inc").value;
  const need = anchor === "site" && source === "orbit" ? Math.abs(+$("sitelat").value || 0) : 0;
  $("incs").min = need ? Math.ceil(need * 2) / 2 : 0;
  $("incmin").textContent = need ? `≥ ${need}° from the site` : "";
  $("incmin").classList.toggle("warn", inc < need);
  $("incnote").textContent = inc === 0 ? "equatorial" : inc === 90 ? "polar"
    : inc > 90 ? "retrograde" : "prograde";
  presetBadge();
  planHint();
}
$("inc").oninput = () => {
  const v = +$("inc").value;
  if (Number.isFinite(v)) { $("incs").value = v; incShown = v; syncInc(); }
};
$("inc").onchange = () => setInc(incClamp(+$("inc").value || 0));
$("incs").oninput = () => setInc(incClamp(Math.round(+$("incs").value * 10) / 10));
// Arrow keys move by the slider's own 0.01, which oninput would round straight
// back onto the current value -- the slider would look stuck.  Handle them
// here as a full 0.1 step instead, to the next 0.1 gridline (so an arrow off
// a computed 98.19 lands on 98.2 / 98.1 rather than 98.29).
$("incs").addEventListener("keydown", ev => {
  const d = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[ev.key];
  if (d === undefined) return;
  ev.preventDefault();
  setInc(incClamp(d > 0 ? Math.floor(incShown * 10 + 1e-6) / 10 + 0.1
                        : Math.ceil(incShown * 10 - 1e-6) / 10 - 0.1));
});
$("pofs").oninput = () => { $("pofsv").textContent = $("pofs").value; };

// ------------------------------------------------------------ orbit presets
// Ready-made shapes as a fill: picking one writes the fields, and the form
// stays complete and plannable.  The preset stays "in play" (for the
// modules' onPreset hooks) until another is picked; a badge says "modified"
// once the fields have moved away from its record.  A preset carrying
// node_lon or argp is anchored by elements, so it switches the anchor to the
// node longitude.
// Each source with the shape block brings its own list (`presets`, records
// shaped like the catalog's): the orbit's is the catalog, a constellation's
// its patterns.  A source without one gets the shape fields alone.  Each
// source remembers the preset it had in play.
const presetList = src => (typeof src.presets === "function" ? src.presets() : src.presets) || null;
function buildPresets(list) {
  SOURCES[0].presets = list;
  renderPresets();
}
function renderPresets() {
  const list = presetList(currentSource());
  $("presetrow").hidden = !list;
  PRESETS = {};
  for (const p of list || [])
    PRESETS[p.name] = p.file_from ? { file_from: p.file_from }
      : { hp: p.perigee_km, ha: p.apogee_km ?? p.perigee_km, inc: p.inc_deg,
          argp: p.argp_deg, node_lon: p.node_lon_deg, raw: p };
  const label = p => p.label || (p.file_from ? `${p.name} · file`
    : `${p.name} · ${p.perigee_km}${(p.apogee_km ?? p.perigee_km) > p.perigee_km
       ? "×" + p.apogee_km : ""} km / ${p.inc_deg}°`);
  $("preset").innerHTML = "<option value=''>custom shape</option>"
    + (list || []).map(p => `<option value="${escHtml(p.name)}">${escHtml(label(p))}</option>`).join("");
  if (activePreset && !PRESETS[activePreset]) { activePreset = null; presetChanged(); }
  $("preset").value = activePreset ?? "";
  presetBadge();
}
function presetBadge() {
  const p = activePreset && PRESETS[activePreset];
  $("presetbadge").hidden = !p || !!p.file_from;
  if (!p || p.file_from) return;
  const s = getShape();
  const mod = p.hp !== s.hp || p.ha !== s.ha || Math.abs(p.inc - s.inc) > 0.051
    || !!currentSource().presetEdited?.(p.raw);
  $("presetbadge").textContent = mod ? "modified" : "preset";
  $("presetbadge").classList.toggle("mod", mod);
}

// Form hooks for modules (ctx.onPreset / onShapeChange / getShape / setShape,
// plugins.js): a preset family with its own rules -- e.g. the sun-synchronous
// one (modules/sso.py), whose inclination follows from the altitude and whose
// node from the local time -- lives in a module, not here.
// activePreset (state.js) is the preset's NAME: a catalog refresh rebuilds the
// PRESETS records, and the name survives that where an object would not.
// Every live onPreset hook learns the preset in play: the catalog record and
// name, or (null, null) when none is (none chosen, or a source without the
// shape block).
function presetChanged() {
  const on = activePreset && currentSource().shape;
  MP.fire(MP._preset, "module preset hook", on ? PRESETS[activePreset].raw : null, on ? activePreset : null);
}
function shapeChanged() {
  // The form's first sync runs before plugins.js (MP) and any module loads.
  if (typeof MP === "undefined") return;
  MP.fire(MP._shape, "module shape hook", getShape());
}
// The orbit shape as the form holds it; epoch is normalised to
// "YYYY-MM-DDTHH:MM" in UTC ("" when unset or unreadable).
function getShape() {
  const hp = +$("peri").value;
  return { hp, ha: Math.max(+$("apo").value || hp, hp), inc: +$("inc").value,
           node_lon: +$("nodelon").value, epoch: epochValue() || "", preset: activePreset };
}
// Write shape fields through the form's own setters.  A new perigee/apogee
// runs the usual sync, which reaches onShapeChange hooks; inc / node_lon alone
// don't, so a hook may call setShape({inc, node_lon}) without looping.
function setShape(v) {
  if (v.inc != null) setInc(v.inc);
  if (v.node_lon != null) { $("nodelon").value = v.node_lon; $("nodelons").value = v.node_lon; planHint(); }
  if (v.hp != null || v.ha != null) {
    const hp = v.hp ?? +$("peri").value;
    $("peri").value = hp;
    if (v.ha != null) $("apo").value = v.ha > hp ? v.ha : "";
    periSync();
  }
}

$("preset").onchange = () => {
  const name = $("preset").value;
  if (name && PRESETS[name]?.file_from) {   // a file preset: to the File source
    $("preset").value = activePreset ?? "";
    return openFilePreset(name, PRESETS[name]);
  }
  activePreset = name || null;
  if (activePreset) {
    const p = PRESETS[name];
    $("peri").value = p.hp;
    $("apo").value = p.ha > p.hp ? p.ha : "";
    setInc(p.inc);
    if (p.node_lon != null) { $("nodelon").value = p.node_lon; $("nodelons").value = p.node_lon; }
    currentSource().onPreset?.(p.raw);
    const elements = p.node_lon != null || p.argp != null;
    if (elements && anchor !== "node" && source === "orbit") setAnchor("node");
    status(`${name} — adjust if needed, then plan.`
      + (elements ? ` anchored by its node longitude.` : ""));
  }
  presetChanged();
  periSync();
};

// ------------------------------------------------------------ epoch & horizon
// The epoch is ISO text in UTC ("YYYY-MM-DD HH:MM"; a T, seconds or a Z are
// accepted), so a value from a log or an ephemeris pastes straight in.  The
// calendar button opens the browser's picker over a hidden datetime-local.
const EPOCH_RE = /^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?\s*Z?$/i;
function epochValue() {
  const m = EPOCH_RE.exec($("epoch").value.trim());
  if (!m) return null;
  const v = m[1] + "T" + m[2];
  return Number.isNaN(Date.parse(v + ":00Z")) ? null : v;
}
function setEpoch(d) {        // d: a Date, or a "YYYY-MM-DDTHH:MM" string
  const v = d instanceof Date ? d.toISOString().slice(0, 16) : d;
  $("epoch").value = v.replace("T", " ");
  $("epoch").classList.remove("err");
  shapeChanged();
}
$("epoch").oninput = () => $("epoch").classList.toggle("err", !epochValue());
$("epoch").onchange = () => { const v = epochValue(); if (v) setEpoch(v); else shapeChanged(); };
$("epochnow").onclick = () => setEpoch(new Date());
$("epochcal").onclick = () => {
  const p = $("epochpick");
  p.value = epochValue() || "";
  try { p.showPicker(); } catch { p.focus(); }
};
$("epochpick").onchange = () => { if ($("epochpick").value) setEpoch($("epochpick").value); };

// How long to propagate: a number with a unit (hours, days or revolutions of
// the current shape), and chips for the usual spans.
function periodS() {
  const s = getShape(), a = RE_KM + (s.hp + s.ha) / 2;
  return 2 * Math.PI * Math.sqrt(a ** 3 / MU_KM);
}
function horizonHours() {
  const n = Math.max(0, +$("hours").value || 0), u = $("hunit").value;
  if (u === "days") return n * 24;
  if (u === "revs") return n * (currentSource().shape ? periodS() : 5400) / 3600;
  return n;
}
function syncHorizonChips() {
  const cur = `${$("hours").value} ${$("hunit").value}`;
  $("horizon").querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.h === cur));
}
$("horizon").querySelectorAll("button").forEach(b => b.onclick = () => {
  const [n, u] = b.dataset.h.split(" ");
  $("hours").value = n; $("hunit").value = u;
  syncHorizonChips();
});
$("hours").oninput = $("hunit").onchange = syncHorizonChips;
$("mode").onchange = () => $("betarow").style.display =
  modeInfo($("mode").value).needs_beta ? "block" : "none";

// ------------------------------------------------------------ anchor
// How the orbit source ties the orbit to the Earth: its plane over a launch
// site at the epoch (server source `site`), or its ascending node over a
// longitude (server source `preset`).
function setAnchor(id) {
  anchor = id;
  $("anchorseg").querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.anchor === id));
  $("anchor_site").hidden = id !== "site";
  $("anchor_node").hidden = id !== "node";
  if (source === "orbit") $("epochlbl").textContent = id === "site" ? "launch epoch (utc)" : "epoch (utc)";
  if (id === "site") siteChanged();
  periSync();
}
$("anchorseg").querySelectorAll("button").forEach(b => b.onclick = () => setAnchor(b.dataset.anchor));
function setLeg(id) {
  leg = id;
  $("legseg").querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.leg === id));
  planHint();
}
$("legseg").querySelectorAll("button").forEach(b => b.onclick = () => setLeg(b.dataset.leg));

// The site: one of the catalog's, or "custom" with typed or picked
// coordinates -- the dropdown then reads "custom (lat, lon)", so nothing
// changes behind your back.
const fmtLat = v => `${Math.abs(v).toFixed(2)}°${v < 0 ? "S" : "N"}`;
const fmtLon = v => `${Math.abs(v).toFixed(2)}°${v < 0 ? "W" : "E"}`;
const siteName = () => $("site").value === "custom"
  ? `${fmtLat(+$("sitelat").value || 0)} ${fmtLon(+$("sitelon").value || 0)}` : $("site").value;
$("site").onchange = () => {
  const s = sitesList.find(x => x.name === $("site").value);
  if (s) { $("sitelat").value = s.lat; $("sitelon").value = s.lon; }
  siteChanged();
};
// After the site or its coordinates moved: a site can only inject into
// inc >= |lat|, so bump the inclination if needed (the hint shows the floor).
function siteChanged() {
  const need = Math.abs(+$("sitelat").value || 0);
  if (anchor === "site" && +$("inc").value < need) {
    setInc(Math.ceil(need * 2) / 2);
    status(`inclination raised to ${$("inc").value}° — the minimum from ${siteName()} (|lat| = ${need}°)`);
  }
  syncInc();
}
function setCustomSite() {
  let o = $("site").querySelector("option[value=custom]");
  if (!o) { o = new Option("", "custom"); $("site").appendChild(o); }
  $("site").value = "custom";
  o.textContent = `custom (${siteName()})`;
  siteChanged();
}
$("sitelat").oninput = $("sitelon").oninput = setCustomSite;
$("sitepick").onclick = () => {
  if (mapPick) { pickOnMap(null); return; }
  pickOnMap((lat, lon) => {
    $("sitelat").value = lat.toFixed(2); $("sitelon").value = lon.toFixed(2);
    setCustomSite();
    status(`launch site set to ${siteName()}.`);
    scheduleReplan();
  }, "sitepick");
};
$("nodelon").oninput = () => { $("nodelons").value = $("nodelon").value; planHint(); };
$("nodelons").oninput = () => { $("nodelon").value = $("nodelons").value; planHint(); };

// One line under the plan button saying what will be planned.
function planHint() {
  const src = currentSource();
  if (src.id !== "orbit") { $("planhint").textContent = ""; return; }
  const s = getShape(), shape = s.ha > s.hp ? `${s.hp}×${s.ha} km` : `${s.hp} km`;
  const name = activePreset
    ? activePreset + ($("presetbadge").classList.contains("mod") ? "*" : "") : "custom";
  const where = anchor === "site" ? `from ${siteName()}, ${leg}` : `node at ${$("nodelon").value || 0}°E`;
  $("planhint").textContent = `${name} · ${shape} / ${s.inc}° · ${where}`;
}

// ------------------------------------------------------------ trajectory source
// Where the trajectory comes from.  Each source has its own panel of options;
// the orbit form (shape, epoch, propagation, plan) follows once the source is
// ready.  A source: {id, label, kind: "orbit"|"trajectory", ready(), args(q)}
// plus shape (shows the shared orbit-shape block), presets (its list for the
// shape block's picker, or a function returning it), onPreset(record) (fill
// the source's own fields from a picked preset), presetEdited(record) (have
// they moved away from it), propagate (a trajectory source that takes the
// shared epoch and span), epochLabel, planLabel,
// slow, and mod (the plugin that added it; its chip shows only while that's
// active).  The core's one source is the orbit, which the server knows as
// `site` or `preset` by its anchor; plugins add theirs through a spec's
// `sources` key and ctx.addSource.
const SOURCES = [
  { id:"orbit", label:"Orbit", kind:"orbit", shape:true,
    ready: () => true,
    args(a) {
      if (anchor === "site") {
        a.set("source", "site");
        if ($("site").value === "custom") {
          a.set("lat", $("sitelat").value || 0); a.set("lon", $("sitelon").value || 0);
        } else a.set("site", $("site").value);
        a.set("leg", leg);
        if ($("apo").value) a.set("pofs", $("pofs").value);
      } else {
        a.set("source", "preset");
        a.set("argp", (activePreset && PRESETS[activePreset]?.argp) || 0);
        a.set("node_lon", $("nodelon").value || 0);
      }
    } },
];
const currentSource = () => SOURCES.find(x => x.id === source) || SOURCES[0];
const sourceShown = x => !x.mod || MP.active(x.mod);
// The old core ids still work: "site" / "preset" are the orbit with that anchor.
const SOURCE_ALIAS = { site: "site", preset: "node" };
function setSource(id) {
  const alias = SOURCE_ALIAS[id];
  if (alias) id = "orbit";
  if (id !== source) {
    currentSource().activePreset = activePreset;
    source = id;
    activePreset = currentSource().activePreset ?? null;
    showSource();
    presetChanged();
    periSync();
    status(currentSource().ready() ? "set parameters, then plan." : "choose a trajectory.");
  }
  if (alias && alias !== anchor) setAnchor(alias);
}
function showSource() {
  const src = currentSource(), ready = src.ready();
  for (const x of SOURCES) $("src_" + x.id).hidden = x.id !== source;
  document.querySelectorAll("#srcseg button").forEach(b => b.classList.toggle("on", b.dataset.src === source));
  $("shapeform").hidden = !src.shape;
  renderPresets();
  $("propform").hidden = !(ready && propagates(src));
  $("moderow").hidden = src.kind !== "orbit";
  $("planrow").hidden = !ready;
  $("plan").textContent = src.planLabel || (src.kind === "orbit" ? "plan orbit" : "show trajectory");
  if (src.epochLabel) $("epochlbl").textContent = src.epochLabel;
  else $("epochlbl").textContent = src.id === "orbit" && anchor === "site" ? "launch epoch (utc)" : "epoch (utc)";
  planHint();
}
// The source chips: the core's plus those of active plugins.  If the current
// source's plugin went away, fall back to the orbit.
function renderSources() {
  $("srcseg").innerHTML = SOURCES.filter(sourceShown).map(x =>
    `<button class="${x.mod ? "plug" : ""}" data-src="${x.id}">${escHtml(x.label)}</button>`).join("");
  document.querySelectorAll("#srcseg button").forEach(b => b.onclick = () => setSource(b.dataset.src));
  if (!sourceShown(currentSource())) setSource("orbit");
  showSource();
}

// ------------------------------------------------------------ catalog
function buildSites() {
  const cur = $("site").value;
  $("site").innerHTML = sitesList.map(s => `<option>${escHtml(s.name)}</option>`).join("");
  if (cur === "custom") setCustomSite();
  else if (sitesList.some(s => s.name === cur)) { $("site").value = cur; planHint(); }
  else $("site").onchange();
}
// Sites, presets and overlays: the core catalog plus every active data pack.
// A server-side error (a broken data pack) is thrown with its message.
async function refreshCatalogs() {
  const [sites, presets, overlays] = await Promise.all(
    [api("/api/sites"), api("/api/presets"), api("/api/overlays")]);
  for (const r of [sites, presets, overlays]) if (r.error) throw new Error(r.error);
  [sitesList, overlayList] = [sites, overlays];
  buildSites();
  buildPresets(presets);
}

// ------------------------------------------------------------ first state
setLeg("ascending");
setAnchor("site");
syncHorizonChips();
$("pofsv").textContent = $("pofs").value;
