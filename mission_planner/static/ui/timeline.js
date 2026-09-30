"use strict";
// Playback: the scrub slider, the shown-window slider and buttons, play/pause.
function fmtUTC(ms) {
  return new Date(ms).toISOString().replace("T", " ").slice(0, 19) + "Z";
}
function updateClock() {
  if (!plan) return;
  $("clock").textContent = fmtUTC(Date.parse(plan.track.epoch_utc) + tCur * 1000);
}
function setScrubFromSlider() {
  if (!plan) return;
  const tEnd = planEnd();
  const lo = win[0] * tEnd, hi = win[1] * tEnd;
  tCur = lo + ($("scrub").value / 1000) * (hi - lo);
  updateClock(); redraw();
}
function setWindow(w0, w1) {
  win = [Math.max(0, Math.min(w0, w1 - 0.001)), Math.min(1, w1)];
  $("win0").value = Math.round(win[0] * 1000);
  $("win1").value = Math.round(win[1] * 1000);
  $("winfill").style.left = (win[0] * 100) + "%";
  $("winfill").style.width = ((win[1] - win[0]) * 100) + "%";
  if (plan) {
    const tEnd = planEnd();
    const span = (win[1] - win[0]) * tEnd;
    $("winlabel").textContent = span >= 86400 ? (span/86400).toFixed(1) + " d"
                              : (span/3600).toFixed(1) + " h";
    tCur = Math.max(win[0] * tEnd, Math.min(tCur, win[1] * tEnd));
  }
  updateClock(); redraw();
}
$("win0").oninput = () => setWindow($("win0").value/1000, $("win1").value/1000);
$("win1").oninput = () => setWindow($("win0").value/1000, $("win1").value/1000);
document.querySelectorAll("[data-win]").forEach(b => b.onclick = () => {
  if (!plan) return;
  const tEnd = planEnd();
  if (b.dataset.win === "all") return setWindow(0, 1);
  const span = b.dataset.win === "rev" ? plan.summary.period_s : +b.dataset.win;
  const start = win[0];
  setWindow(start, Math.min(1, start + span / tEnd));
});
$("scrub").oninput = setScrubFromSlider;
$("play").onclick = () => {
  playing = !playing;
  $("play").innerHTML = playing ? "&#10074;&#10074;" : "&#9654;";
  if (playing) { lastFrame = performance.now(); requestAnimationFrame(tick); }
};
function tick(now) {
  if (!playing || !plan) return;
  const dt = (now - lastFrame) / 1000; lastFrame = now;
  const tEnd = planEnd();
  const lo = win[0] * tEnd, hi = win[1] * tEnd;
  tCur += dt * (+$("speed").value);
  if (tCur > hi) tCur = lo;
  $("scrub").value = Math.round(1000 * (tCur - lo) / Math.max(hi - lo, 1e-9));
  updateClock(); redraw();
  requestAnimationFrame(tick);
}
// Move playback to a given seconds-past-epoch, widening the display window
// if the instant falls outside it.  Exposed to modules as ctx.seek.
function seekTo(ts) {
  if (!plan) return;
  const tEnd = planEnd();
  tCur = Math.max(0, Math.min(ts, tEnd));
  if (tCur < win[0] * tEnd || tCur > win[1] * tEnd) setWindow(0, 1);
  const lo = win[0] * tEnd, hi = win[1] * tEnd;
  $("scrub").value = Math.round(1000 * (tCur - lo) / Math.max(hi - lo, 1e-9));
  updateClock(); redraw();
}
