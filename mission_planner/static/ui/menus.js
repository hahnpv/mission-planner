"use strict";
// The core's File and View menus; modules add theirs through ctx.addMenuItem
// (plugins.js), the Plugins menu lives there too.
const menubar = new Menubar($("menubar"));

function download(name, text, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  // Revoke once the browser has had a chance to start the download.
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
const planStamp = () => plan.track.epoch_utc.slice(0, 16).replace(/[-:]/g, "");
menubar.add("File", { type:"action", label:"Export track (CSV)", enabled: () => !!plan,
  run() {
    const tr = plan.track, t0 = Date.parse(tr.epoch_utc);
    const rows = tr.t.map((t, i) => [new Date(t0 + t * 1000).toISOString(), t,
                                     tr.lat[i], tr.lon[i], tr.alt_km[i]].join(","));
    download(`track_${planStamp()}.csv`,
             "utc,t_s,lat_deg,lon_deg,alt_km\n" + rows.join("\n") + "\n", "text/csv");
  } });
menubar.add("File", { type:"action", label:"Export plan (JSON)", enabled: () => !!plan,
  run: () => download(`plan_${planStamp()}.json`, JSON.stringify(plan, null, 1),
                      "application/json") });

menubar.add("View", { type:"head", label:"projection" });
for (const [mode, label, title] of [["map", "Map", "flat map; drag sideways to scroll"],
                                    ["globe", "Globe", "the map projected on a globe"],
                                    ["orbit", "Orbit", "the orbit in space around the earth"]])
  menubar.add("View", { type:"radio", label, title, get: () => projMode === mode,
                        set: () => setProj(mode) });
menubar.add("View", { type:"head", label:"orbit view", visible: () => projMode === "orbit" });
const setOrbitView = (key, v) => { orbitView[key] = v; redraw(); };
menubar.add("View", { type:"radio", label:"ECI frame (inertial)", visible: () => projMode === "orbit",
  title:"the orbit in space: a closed path, drawn with the earth's axes at playback time "
        + "(no precession/nutation)",
  get: () => orbitView.frame === "eci", set: () => setOrbitView("frame", "eci") });
menubar.add("View", { type:"radio", label:"ECEF frame (earth-fixed)", visible: () => projMode === "orbit",
  title:"the path as it moves over the turning earth: the ground trace lifted to altitude",
  get: () => orbitView.frame === "ecef", set: () => setOrbitView("frame", "ecef") });
menubar.add("View", { type:"check", label:"Ground trace", visible: () => projMode === "orbit",
  get: () => orbitView.ground, set: v => setOrbitView("ground", v) });
menubar.add("View", { type:"head", label:"layers" });
const setDisplay = (key, on) => { display[key] = on; redraw(); };
const setOverlay = (key, on) => { on ? overlayOff.delete(key) : overlayOff.add(key); redraw(); };
menubar.add("View", { type:"check", label:"Horizon footprint at playback time",
                      title:"green ring = the satellite's visible horizon; anything inside "
                            + "(e.g. a downlink site) can see the vehicle",
                      get: () => display.horizon, set: v => setDisplay("horizon", v) });
menubar.add("View", { type:"check", label:"Night shading",
                      get: () => display.night, set: v => setDisplay("night", v) });
// Modules' display toggles (ctx.addDisplayToggle) land here, under the core layers.
const viewModuleRows = [];
menubar.add("View", { type:"group", items: () => viewModuleRows.filter(i => i.visible()) });
menubar.add("View", { type:"group", items: () => overlayList.length
  ? [{ type:"head", label:"map overlays" }].concat(overlayList.map(ov => {
      const key = ov.pack + "/" + ov.id;
      return { type:"check", label: ov.name, title: ov.pack, swatch: ov.style.color || C.red,
               get: () => !overlayOff.has(key), set: v => setOverlay(key, v) };
    }))
  : [] });
