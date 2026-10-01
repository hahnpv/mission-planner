"use strict";
// Shared constants and mutable UI state.  The UI is plain <script> files
// loaded in order (see index.html); top-level declarations here are visible
// to every later file.  Nothing in this file touches the DOM beyond $().
const $ = id => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
const C = { blue:"#2a78d6", orange:"#eb6834", green:"#1baf7a", red:"#d03b3b",
            muted:"#898781", grid:"#e1e0d9" };
const S = 3;                       // px per degree, base projection
const DEG = Math.PI / 180;
const RE_KM = 6378.137, MU_KM = 398600.4418, J2 = 1.08262668e-3;   // km, km^3/s^2
const OMEGA_E_DEG = 7.2921159e-5 / DEG;                            // earth rotation, deg/s
const GLOBE = { cx: 540, cy: 270, R: 255 };   // globe centre/radius in the 1080x540 view box

// ------------------------------------------------------------ state
let projMode = "map";              // "map" | "globe" | "orbit"
let lonC = 0;                      // map/globe centre longitude; horizontal drag rotates it
let latC = 20;                     // globe centre latitude; vertical drag tilts it
let GR = GLOBE.R;                  // earth radius on screen: GLOBE.R, or smaller in orbit view
let B = null;                      // globe basis: n (centre), e (east), u (up)
let coast = null, sitesList = [], overlayList = [];   // catalog: core + active data packs
// Map overlays: "pack/id" of those the user switched off, and the View menu's
// master switch that hides them all while keeping that selection.  Both kept
// in this browser (the accessors throw in some private modes).
const OVERLAY_KEY = "mp.overlays";
const overlayOff = new Set();
let overlaysHidden = false;
try {
  const saved = JSON.parse(localStorage.getItem(OVERLAY_KEY)) || {};
  for (const k of saved.off || []) overlayOff.add(k);
  overlaysHidden = !!saved.hidden;
} catch {}
function saveOverlays() {
  try { localStorage.setItem(OVERLAY_KEY, JSON.stringify({ off: [...overlayOff], hidden: overlaysHidden })); }
  catch {}
}
const display = { horizon: false, night: true };    // core layers, switched from the View menu
const orbitView = { frame: "eci", ground: true };   // orbit view: frame of the lifted path, ground trace
let activePreset = null;           // name of the orbit preset in play (a key of PRESETS, form.js)
let source = "site";               // trajectory source id (see SOURCES in form.js)
let plan = null;                   // {summary, track, tracks?, primary?, args?} from /api/plan;
                                   // track is the one in focus (setFocus in form.js)
let scene = null;                  // agent-pushed Scene
let win = [0, 1];                  // shown span, fraction of track duration
let tCur = 0;                      // scrub time, seconds past epoch
let playing = false, lastFrame = 0;
let view = { x:0, y:0, w:1080, h:540 };
let pinOpen = null;                // key of the marker whose info callout is showing
let pinHit = null;                 // that marker's position, captured during redraw

// ------------------------------------------------------------ helpers
// Every /api/ error comes back as JSON {"error": ...} (including 500s), so a
// caller checks res.error; anything else that isn't ok is a transport error.
async function api(p) {
  const r = await fetch(p);
  let j = null;
  try { j = await r.json(); } catch {}
  if (!r.ok && !(j && j.error)) throw new Error(`HTTP ${r.status}`);
  return j;
}
async function apiPost(p, body) {
  const opts = { method: "POST" };
  if (body !== undefined) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(p, opts);
  let j = null;
  try { j = await r.json(); } catch {}
  if (!r.ok && !(j && j.error)) throw new Error(`HTTP ${r.status}`);
  return j;
}
// Every track of the plan: one for most plans, several for a constellation or
// a multi-vehicle file.  They share one clock (seconds past the plan epoch).
const planTracks = () => plan ? (plan.tracks || [plan.track]) : [];
// The plan's last instant [s past epoch]: the timeline spans 0 .. planEnd().
function planEnd() {
  let end = 0;
  for (const tr of planTracks()) end = Math.max(end, tr.t[tr.t.length - 1]);
  return end;
}
// The status bar (one line along the bottom): every status message, the
// core's and plugins' (ctx.status).  A long one is cut; its tooltip has it all.
function status(msg, isErr) {
  $("status").textContent = msg;
  $("status").className = isErr ? "err" : "";
  $("statusbar").title = msg;
}
const escHtml = s => String(s).replace(/[&<>"]/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
