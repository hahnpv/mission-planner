"use strict";
// The side panel: trajectory source, orbit shape and propagation controls,
// planning requests, presets and the catalog.

// ------------------------------------------------------------ planning
// The request args for the current form: the source's own, then the shared
// orbit shape (site/preset) and propagation (any orbit source).
function args() {
  const src = currentSource(), a = new URLSearchParams();
  a.set("source", src.id);
  src.args(a);
  if (src.shape) {
    a.set("hp", $("peri").value); a.set("inc", $("inc").value);
    if ($("apo").value) a.set("ha", $("apo").value);
  }
  if (src.kind === "orbit") {
    a.set("hours", $("hours").value);
    const ep = $("epoch").value;
    if (ep) a.set("epoch", ep + ":00+00:00");
    a.set("mode", $("mode").value);
    if (modeInfo($("mode").value).needs_beta) a.set("beta", $("beta").value);
    // dt: keep point count sane over long horizons
    const dt = Math.max(30, Math.round(+$("hours").value * 3600 / 20000 / 10) * 10);
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
async function doPlan() {
  const src = currentSource();
  if (!src.ready()) return;
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
  applyPlan(res);
}
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
function applyPlan(res) {
  if (!res.track || !res.track.t || res.track.t.length < 2) {
    status("plan has no track points", true);
    return;
  }
  // Only the plan itself: a job result also carries its bookkeeping
  // (status, elapsed_s), which must not leak into the plan.
  plan = { summary: res.summary, track: res.track, tracks: res.tracks, primary: res.primary };
  tCur = 0; pinOpen = null;
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
    setWindow(0, 1);
    MP.live(MP._onPlan).forEach(cb => cb(plan));
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
  setWindow(0, 1);
  MP.live(MP._onPlan).forEach(cb => cb(plan));
}
$("plan").onclick = doPlan;

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
  MP.live(MP._onPlan).forEach(cb => cb(plan));
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

// ------------------------------------------------------------ live controls
const live = [["hours","hoursv"],["pofs","pofsv"]];
for (const [a,b] of live) {
  $(a).oninput = () => $(b).textContent = $(a).value;
  $(b).textContent = $(a).value;
}
// Inclination is the one control with two resolutions.  The input keeps its
// native 0.01 deg so a COMPUTED inclination (SSO sync, a preset, anything
// set programmatically) survives assignment intact -- the step attribute
// would silently round it.  A hand-dragged slider snaps to a round 0.1 deg
// instead, and arrow keys (below) move a whole 0.1.
let incShown = +$("inc").value;
function setInc(v) {                    // the one way inclination is written
  $("inc").value = v;
  $("incv").textContent = $("inc").value;
  incShown = +$("inc").value;
}
const incClamp = v => Math.min(120, Math.max(0, v)).toFixed(1);
$("inc").oninput = () => setInc(incClamp(Math.round(+$("inc").value * 10) / 10));
// Arrow keys move by the input's own 0.01, which oninput would round straight
// back onto the current value -- the slider would look stuck.  Handle them
// here as a full 0.1 step instead.
$("inc").addEventListener("keydown", ev => {
  const d = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[ev.key];
  if (d === undefined) return;
  ev.preventDefault();
  // Step to the next 0.1 gridline, so an arrow off a computed value like
  // 98.19 lands on 98.2 / 98.1 rather than 98.29.
  setInc(incClamp(d > 0 ? Math.floor(incShown * 10 + 1e-6) / 10 + 0.1
                        : Math.ceil(incShown * 10 - 1e-6) / 10 - 0.1));
});
setInc($("inc").value);
// Perigee: the number field is the source of truth; the slider is a
// quick-set for the LEO range (values above 1000 km live in the field).
$("alt").oninput = () => { $("peri").value = $("alt").value; periSync(); };
$("peri").oninput = () => { $("alt").value = $("peri").value; periSync(); };
function periSync() {
  $("altv").textContent = $("peri").value;
  // Perigee position only means something for an elliptic orbit off a site.
  $("pofsrow").hidden = !(source === "site" && +$("apo").value > +$("peri").value);
  ssoSync();
}
$("apo").oninput = periSync;
periSync();

// ------------------------------------------------------------ orbit presets
// Element-anchored classics: no launch site; RAAN from node/station longitude.
let PRESETS = {};   // name -> {hp, ha, inc, argp?, node_lon?, sso?, sub?} from /api/presets
function buildPresets(list) {
  PRESETS = {};
  for (const p of list)
    PRESETS[p.name] = p.file_from ? { file_from: p.file_from, pack: p.pack } : { hp: p.perigee_km, ha: p.apogee_km ?? p.perigee_km, inc: p.inc_deg,
                        argp: p.argp_deg, node_lon: p.node_lon_deg, pack: p.pack,
                        sso: !!p.sun_synchronous,
                        sub: p.sun_synchronous ? () => ssoRepeatOptions() : undefined };
  const cur = $("preset").value;
  $("preset").innerHTML = "<option value='' disabled hidden>choose an orbit…</option>"
    + list.map(p => `<option>${escHtml(p.name)}</option>`).join("");
  if (!cur) $("preset").value = "";
  if (cur && PRESETS[cur]) $("preset").value = cur;
  else if (cur) { $("preset").value = ""; $("preset").onchange(); }
}
// The sun-synchronous inclination [deg] for a perigee/apogee altitude pair
// (J2 nodal regression of +0.9856 deg/day), or NaN when none exists.
const SSO_RATE = 2 * Math.PI / (365.2422 * 86400);   // rad/s, one turn per year
function ssoInclination(hp, ha) {
  const a = RE_KM + (hp + ha) / 2;
  const e = (ha - hp) / (2 * RE_KM + hp + ha);           // (ra-rp)/(ra+rp)
  const p = a * (1 - e * e);
  const n = Math.sqrt(MU_KM / (a * a * a));
  const k = 1.5 * J2 * (RE_KM / p) ** 2 * n;
  const ci = -SSO_RATE / k;
  return Math.abs(ci) > 1 ? NaN : Math.acos(ci) / DEG;
}
// Repeat-ground-track sun-synchronous family: exactly j revs per solar day.
// For an SSO the node tracks the mean sun, so the repeat condition is a
// draconitic period of 86400/j s; iterate a with the J2 rates and the
// altitude-dependent SSO inclination.
function ssoRepeatOptions() {
  const out = [];
  for (let j = 16; j >= 12; j--) {
    const T = 86400 / j;
    let a = Math.cbrt(MU_KM * (T / (2 * Math.PI)) ** 2), inc = 98;
    for (let it = 0; it < 25; it++) {
      const h = a - RE_KM;
      inc = ssoInclination(h, h);
      if (isNaN(inc)) { a = NaN; break; }
      const n = Math.sqrt(MU_KM / a ** 3), k = 1.5 * J2 * (RE_KM / a) ** 2 * n;
      const ci = Math.cos(inc * DEG);
      const du = n + 0.5 * k * (5 * ci * ci - 1) + 0.5 * k * (3 * ci * ci - 1);
      a *= Math.cbrt((du * T / (2 * Math.PI)) ** 2);
    }
    const h = a - RE_KM;
    if (h > 150 && h < 2500)
      out.push({ label: `${j} rev/day — ${h.toFixed(0)} km, ${inc.toFixed(2)}°`,
                 hp: +h.toFixed(1), ha: +h.toFixed(1) });
  }
  return out;
}
let subOptions = [];
$("preset2").onchange = () => {
  const o = subOptions[+$("preset2").value];
  if (!o) return;
  $("peri").value = o.hp; $("alt").value = o.hp;
  $("apo").value = o.ha > o.hp ? o.ha : "";
  periSync();
};

$("preset").onchange = () => {
  const name = $("preset").value;
  if (name && PRESETS[name]?.file_from) {   // a file preset: to the File source
    $("preset").value = activePreset ? Object.keys(PRESETS).find(k => PRESETS[k] === activePreset) : "";
    return openFilePreset(name, PRESETS[name]);
  }
  activePreset = name ? PRESETS[name] : null;
  // Optional second-level dropdown (e.g. repeat-track SSO family).
  subOptions = activePreset && activePreset.sub ? activePreset.sub() : [];
  $("preset2row").style.display = subOptions.length ? "block" : "none";
  $("preset2").innerHTML = "<option value=''>custom altitude</option>"
    + subOptions.map((o, i) => `<option value="${i}">${o.label}</option>`).join("");
  $("nodelonrow").style.display = activePreset ? "block" : "none";
  $("ltanrow").style.display = activePreset && activePreset.sso ? "block" : "none";
  showSource();
  if (activePreset) {
    $("peri").value = activePreset.hp; $("alt").value = activePreset.hp;
    $("apo").value = activePreset.ha > activePreset.hp ? activePreset.ha : "";
    setInc(activePreset.inc);
    $("nodelon").value = activePreset.node_lon ?? 0;
    status(`preset ${name} — adjust if needed, then plan.`);
    ssoSync();
  }
  periSync();
};

// Sun-synchronous epoch sync: exact inclination for the current hp/ha, and
// node longitude from the requested LTAN at the chosen epoch (mean sun; the
// equation of time adds up to ~16 min that planning can ignore).
function ssoSync() {
  if (!activePreset || !activePreset.sso) return;
  const hp = +$("peri").value, ha = Math.max(+$("apo").value || hp, hp);
  const inc = ssoInclination(hp, ha);
  if (isNaN(inc)) {
    status("no sun-synchronous inclination exists at this altitude", true);
    return;
  }
  setInc(inc.toFixed(2));                // keeps both decimals
  const shown = $("inc").value;
  const ep = $("epoch").value;
  const utcH = ep ? (+ep.slice(11, 13)) + (+ep.slice(14, 16)) / 60 : 12;
  let lam = ((+$("ltan").value - utcH) * 15 + 540) % 360;
  $("nodelon").value = ((lam + 360) % 360 - 180).toFixed(1);
  status(`SSO synced: inc ${shown}° for ${hp}×${ha} km, `
    + `node ${$("nodelon").value}° for LTAN ${$("ltan").value} h`);
}
$("ltan").oninput = ssoSync;
$("epoch").onchange = ssoSync;
$("mode").onchange = () => $("betarow").style.display =
  modeInfo($("mode").value).needs_beta ? "block" : "none";
$("site").onchange = () => {
  const s = sitesList.find(x => x.name === $("site").value);
  if (s) {
    $("sitelat").value = s.lat; $("sitelon").value = s.lon;
    // A site can only inject into inc >= |lat|: bump the slider if needed.
    const need = Math.abs(s.lat);
    if (+$("inc").value < need) {
      setInc(Math.ceil(need * 2) / 2);
      status(`inclination raised to ${$("inc").value}° — minimum from `
        + `${s.name} (|lat| = ${need}°)`);
    }
  }
};
$("sitelat").oninput = $("sitelon").oninput = () => { $("site").value = "custom"; };

// ------------------------------------------------------------ trajectory source
// Where the trajectory comes from.  Each source has its own panel of options;
// the orbit form (shape, epoch, propagation, plan) follows once the source is
// ready -- a preset source isn't until an orbit is picked.  Each source keeps
// its own shape values, so switching back and forth doesn't cross them over.
// A source: {id, label, kind: "orbit"|"trajectory", ready(), args(q)} plus
// shape (uses the shared orbit-shape block), epochLabel, planLabel, slow, and
// mod (the plugin that added it; its button shows only while that's active).
// The server side is planning.py (core) or a plugin spec's `sources` key.
const SOURCES = [
  { id:"site", label:"Launch site", kind:"orbit", shape:true, epochLabel:"launch epoch (utc)",
    ready: () => true,
    args(a) {
      if ($("site").value === "custom") {
        a.set("lat", $("sitelat").value || 0); a.set("lon", $("sitelon").value || 0);
      } else a.set("site", $("site").value);
      a.set("leg", $("leg").value);
      if ($("apo").value) a.set("pofs", $("pofs").value);
    } },
  { id:"preset", label:"Orbit preset", kind:"orbit", shape:true, epochLabel:"epoch (utc)",
    ready: () => !!activePreset,
    args(a) {
      a.set("argp", activePreset.argp || 0);
      a.set("node_lon", $("nodelon").value || 0);
    } },
];
const currentSource = () => SOURCES.find(x => x.id === source);
const sourceShown = x => !x.mod || MP.active(x.mod);
const SHAPE = ["peri", "apo", "inc", "pofs"];
const shapeMemo = {};
function setSource(id) {
  if (id === source) return;
  shapeMemo[source] = Object.fromEntries(SHAPE.map(k => [k, $(k).value]));
  source = id;
  const memo = shapeMemo[id];
  if (memo) {
    for (const k of SHAPE) $(k).value = memo[k];
    $("alt").value = memo.peri; setInc(memo.inc); $("pofsv").textContent = memo.pofs;
  }
  activePreset = id === "preset" && $("preset").value ? PRESETS[$("preset").value] : null;
  showSource();
  periSync();
  if (id === "site") $("site").onchange();
  status(currentSource().ready() ? "set parameters, then plan." : "choose an orbit.");
}
function showSource() {
  const src = currentSource(), ready = src.ready();
  for (const x of SOURCES) $("src_" + x.id).hidden = x.id !== source;
  document.querySelectorAll("#srcseg button").forEach(b => b.classList.toggle("on", b.dataset.src === source));
  $("shapeform").hidden = !(ready && src.shape);
  $("propform").hidden = !(ready && src.kind === "orbit");
  $("planrow").hidden = !ready;
  $("plan").textContent = src.planLabel || (src.kind === "orbit" ? "plan orbit" : "show trajectory");
  if (src.epochLabel) $("epochlbl").textContent = src.epochLabel;
}
// The source buttons: core ones plus those of active plugins.  If the
// current source's plugin went away, fall back to a launch site.
function renderSources() {
  $("srcseg").innerHTML = SOURCES.filter(sourceShown).map(x =>
    `<button class="small ghost" data-src="${x.id}">${escHtml(x.label)}</button>`).join("");
  document.querySelectorAll("#srcseg button").forEach(b => b.onclick = () => setSource(b.dataset.src));
  if (!sourceShown(currentSource())) setSource("site");
  showSource();
}

// ------------------------------------------------------------ catalog
function buildSites() {
  const cur = $("site").value;
  $("site").innerHTML = sitesList.map(s => `<option>${escHtml(s.name)}</option>`).join("")
    + "<option value='custom'>custom…</option>";
  if (cur === "custom" || sitesList.some(s => s.name === cur)) $("site").value = cur;
  else $("site").onchange();
}
// Sites, presets and overlays: the core catalog plus every active data pack.
async function refreshCatalogs() {
  let presets;
  [sitesList, presets, overlayList] = await Promise.all(
    [api("/api/sites"), api("/api/presets"), api("/api/overlays")]);
  buildSites();
  buildPresets(presets);
}
