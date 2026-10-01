"use strict";
// ------------------------------------------------------------ capability modules
// Built-ins and plugins (see mission_planner/plugins.py) ship a JS asset that
// calls MP.register to add a side-panel section.  Every hook a module
// registers is stored as {mod, fn} and the core only calls MP.live() ones, so
// an inactive plugin (switched off, or waiting on a requirement) hides its
// panel and its map layers, clicks, plan callbacks and display rows go inert;
// the server gates its routes, modes and data the same way.  A loaded script
// can't be un-run, but inert is indistinguishable from unloaded.
const MP = {
  _onPlan: [],
  _layers: [],     // module map layers, drawn each redraw under the track
  _over: [],       // ... and these on top of it
  _clicks: [],     // module handlers for a click on the map
  _footprint: [],  // module filters: which vehicles' horizon footprints to draw
  _preset: [],     // module hooks: the orbit preset in play changed
  _shape: [],      // ... and the orbit shape (perigee / apogee / epoch)
  mods: {},        // name -> /api/modules record, plus the module's UI once registered
  // active: switched on with its requirements met.  on: active AND it works
  // with the kind of trajectory currently planned (spec key works_with);
  // hooks, panels and menu items follow `on`.
  active: name => MP.mods[name]?.active !== false,
  on: name => MP.active(name)
    && (!plan || (MP.mods[name]?.works_with ?? ["orbit"]).includes(plan.summary.kind ?? "orbit")),
  live: hooks => hooks.filter(h => MP.on(h.mod)).map(h => h.fn),
  // Call every live hook of a list with `args`; one module's error is logged
  // (`what` names the hook) and never stops the others or the caller.
  fire(hooks, what, ...args) {
    for (const fn of MP.live(hooks)) {
      try { fn(...args); }
      catch (e) { console.error(what + ":", e); }
    }
  },
  register(mod) {
    // loadModules tags each module's <script> with its name.
    const name = document.currentScript?.dataset.module ?? mod.title;
    const rec = (MP.mods[name] ??= { name, title: mod.title, status: "loaded",
                                      enabled: true, active: true });
    // Collapsible box, closed by default unless the module says open.  No
    // html, no box (a source-only plugin): it stays detached and counts as
    // open, so isOpen() follows the plugin's switch alone.
    const box = document.createElement("details");
    box.className = "modbox";
    if (mod.open || !mod.html) box.open = true;
    box.hidden = !MP.on(name);
    box.innerHTML = `<summary class="lbl">${escHtml(mod.title)}</summary>` + (mod.html || "");
    if (mod.html) $("modulebox").appendChild(box);
    rec.box = box;
    const hook = (list, drawsOnMap) => fn => {
      list.push({ mod: name, fn });
      if (drawsOnMap) rec.map = true;
    };
    try {
      mod.init({
        api,
        status,
        redraw,
        getPlan: () => plan,
        // The query args that produced the current plan (the payload's
        // `args`; a plan pushed by an agent carries them too), so a module can
        // ask the backend about the very plan on screen -- not the form,
        // which may have moved on.  Before any plan: the form's.
        planArgs: () => new URLSearchParams(plan?.args ?? args()),
        // The module's own collapsible section.  A module that puts graphics
        // on the map should draw nothing while its panel is closed, and can
        // wake up (fetch, redraw) when the user opens it.  An inactive
        // plugin's panel counts as closed.
        isOpen: () => MP.on(name) && box.open,
        onToggle: cb => box.addEventListener("toggle", () => {
          try { cb(box.open); }
          catch (e) { console.error(`plugin ${name} onToggle:`, e); }
        }),
        onPlan: hook(MP._onPlan, false),
        // Map layers get the layer context documented at layerCtx (map.js).
        onDraw: hook(MP._layers, true),
        onDrawOver: hook(MP._over, true),
        // fn(lat, lon) for a click on the map; a module that paints only while
        // its panel is open should gate on isOpen() here too.
        onClick: hook(MP._clicks, true),
        // fn(track, k) -> true | false | null: should this vehicle (sample k,
        // the playback time) show its horizon footprint?  null = no opinion.
        // While any live filter has an opinion, the footprints drawn are every
        // track's that passes them all, instead of the View menu's single
        // footprint of the track in focus.
        footprintFilter: hook(MP._footprint, true),
        // A check item in the View menu's layers section.  Returns a detached
        // checkbox <input> holding the state, so the module can read or set it.
        addDisplayToggle: (label, checked, cb) => {
          const input = document.createElement("input");
          input.type = "checkbox";
          input.checked = !!checked;
          input.onchange = () => cb(input.checked);
          viewModuleRows.push({ type:"check", label, visible: () => MP.on(name),
                                get: () => input.checked,
                                set: v => { input.checked = v; input.onchange(); } });
          return input;
        },
        // An item in a menu-bar menu (created if new); see static/ui/menubar.js
        // for the item types.  Hidden while the module is inactive.
        addMenuItem: (menu, item) => menubar.add(menu, Object.assign({}, item, {
          visible: () => MP.on(name) && (!item.visible || item.visible()) })),
        seek: ts => seekTo(ts),
        // Form hooks for a preset family with rules of its own (example:
        // modules/sso.py).  onPreset(cb): cb(record, name) with the preset's
        // catalog record whenever the preset in play changes, cb(null, null)
        // when none is.  onShapeChange(cb): cb(shape) when perigee, apogee or
        // epoch change.  getShape() -> {hp, ha, inc, node_lon, epoch, preset};
        // setShape({hp?, ha?, inc?, node_lon?}) writes through the form's
        // setters (hp/ha re-run onShapeChange hooks; inc/node_lon don't).
        onPreset: hook(MP._preset, false),
        onShapeChange: hook(MP._shape, false),
        getShape: () => getShape(),
        setShape: v => setShape(v),
        // Rows of the module's own under the orbit-preset dropdown; returns
        // the element.  Hidden while the module is off; within that, showing
        // them (say, only for its presets) is up to the module.
        presetControls: html => {
          const box = document.createElement("div");
          box.innerHTML = html;
          box.dataset.module = name;
          box.hidden = !MP.on(name);
          $("presetctl").appendChild(box);
          rec.presetEl = box;
          return box;
        },
        // A trajectory source: a button in the sidebar's source row and a
        // panel of its own options.  spec: {id, label, html, init?(panel),
        // ready?(), args?(q), planLabel?}; kind and slow come from the plugin's
        // Python `sources` entry of the same id, which must exist.  Call
        // updateSource() when ready() may have changed (e.g. a file chosen).
        addSource: spec => {
          const py = (rec.sources || []).find(x => x.id === spec.id);
          if (!py) throw new Error(`source '${spec.id}' has no server side (spec key 'sources')`);
          const panel = document.createElement("div");
          panel.id = "src_" + spec.id;
          panel.hidden = true;
          panel.innerHTML = spec.html || "";
          $("srcpanels").appendChild(panel);
          SOURCES.push({ ready: () => true, args: () => {}, ...spec,
                         kind: py.kind, slow: py.slow, mod: name });
          spec.init?.(panel);
          renderSources();
        },
        updateSource: () => showSource(),
        // Open a stored file (an upload id) in the File source; {plan: true}
        // plans it once its reader has described it.  plan() plans the form as is.
        openFile: (id, opts) => openFile(id, opts),
        plan: () => doPlan(),
        // A file input over the server's upload store: see static/ui/files.js.
        // Put picker.el in your panel and send picker.value as upload=<id>.
        filePicker: opts => filePicker(opts),
      });
    } catch (e) {
      console.error(`plugin ${name} init:`, e);
      rec.jsError = String(e);
    }
    renderPlugins();
  },
  // Merge a fresh /api/modules inventory and bring the UI in line with it.
  async apply(list) {
    const was = Object.fromEntries(Object.values(MP.mods).map(m => [m.name, m.active]));
    let catalogChanged = false;
    for (const m of list) {
      const rec = Object.assign(MP.mods[m.name] ??= {}, m);
      if (rec.catalog && was[m.name] !== undefined && was[m.name] !== rec.active)
        catalogChanged = true;
    }
    if (catalogChanged) {
      try { await refreshCatalogs(); }
      catch (e) { status("catalog refresh failed: " + e.message, true); }
    }
    buildModeSelect();
    renderSources();
    syncModules();
    // Catch newly active modules up on the plan they missed -- only those
    // that are on for it (MP.on honours works_with).
    if (plan)
      for (const m of list)
        if (MP.on(m.name) && was[m.name] === false)
          MP.fire(MP._onPlan.filter(h => h.mod === m.name), "module onPlan", plan);
    redraw();
  },
  async toggle(name, enabled) {
    let list;
    try {
      list = await apiPost("/api/modules/" + encodeURIComponent(name), { enabled });
      if (list.error) throw new Error(list.error);
    } catch (e) {
      status("plugin toggle failed: " + e.message, true);
      renderPlugins();
      return;
    }
    await MP.apply(list);
    const m = MP.mods[name];
    status(`plugin ${m.title} ${m.enabled ? "on" : "off"}`
      + (m.enabled && !m.active && m.waiting_on ? ` — waiting on ${m.waiting_on}` : "") + ".");
  },
};

// Show each module's panel only while it's on (active and suited to the
// current plan), and bring the menus in line.
function syncModules() {
  for (const m of Object.values(MP.mods)) {
    if (m.box) m.box.hidden = !MP.on(m.name);
    if (m.presetEl) m.presetEl.hidden = !MP.on(m.name);
  }
  renderPlugins();
}
// The Plugins menu (built-ins aren't listed: they're always on).  The rows are
// rebuilt every time it opens; this only refreshes an open menu and the red
// dot that flags a plugin that failed to load.
function renderPlugins() {
  const bad = Object.values(MP.mods).some(m => !m.builtin && (m.status === "failed" || m.jsError));
  menubar.flag("Plugins", bad && C.red);
  menubar.refresh();
}
function pluginItems() {
  const all = Object.values(MP.mods).filter(m => !m.builtin);
  if (!all.length) return [{ type:"action", label:"No plugins installed", enabled: () => false }];
  const ok = all.filter(m => m.status === "loaded");
  return [{ type:"head", label: `${ok.filter(m => m.active).length}/${ok.length} active` }]
    .concat(all.map(m => {
      const loaded = m.status === "loaded";
      let detail = "", err = false;
      if (m.status === "failed") { detail = "failed: " + m.error; err = true; }
      else if (m.status === "unavailable") detail = "unavailable: " + m.error;
      else if (m.jsError) { detail = "js error: " + m.jsError; err = true; }
      else if (m.enabled && !m.active && m.waiting_on) detail = "waiting on " + m.waiting_on;
      return {
        type:"check", label: m.title, title: m.description || m.name,
        get: () => m.enabled && loaded, set: v => MP.toggle(m.name, v),
        enabled: () => loaded, detail, detailErr: err,
        badges: [m.js_url && "panel", m.routes && "routes", m.map && "map",
                 ...(m.modes || []).map(x => "mode " + x.mode), m.catalog && "data",
                 ...(m.file_readers || []).map(x => "reads " + x.label),
                 m.mcp_tools?.length && `mcp ×${m.mcp_tools.length}`,
                 ...(m.requires || []).map(r => "needs " + r)].filter(Boolean),
      };
    }))
    .concat([{ type:"sep" }, { type:"note", label: "Panels, map layers, routes, modes and "
      + "data switch live; MCP tools are fixed when the MCP server starts "
      + "(MP_DISABLE_MODULES)." }]);
}
menubar.add("Plugins", { type:"group", items: pluginItems });

async function loadModules() {
  try {
    const list = await api("/api/modules");
    if (list.error) throw new Error(list.error);
    for (const m of list) {
      MP.mods[m.name] = m;
      if (m.status !== "loaded" || !m.js_url) continue;
      const s = document.createElement("script");
      s.src = m.js_url;
      s.dataset.module = m.name;
      document.body.appendChild(s);
    }
    // A broken plugin shouldn't be something you have to go looking for.
    const nFailed = list.filter(m => !m.builtin && m.status === "failed").length;
    if (nFailed) status(`${nFailed} plugin(s) failed to load — see the Plugins menu.`, true);
    buildModeSelect();
    renderPlugins();
  } catch (e) {
    status("modules failed to load: " + e.message, true);
  }
}

// ------------------------------------------------------------ scene push (SSE)
// Each scene version is taken up once: a reconnect (the server restarted, the
// laptop slept) re-announces the current version, which must neither undo a
// plan made in the form since nor bring back a scene that plan dismissed.
// A scene with a `plan` (scene.py; the show_plan tool) becomes the plan on
// display.
let sceneVersion = -1;
function listenScenes() {
  const es = new EventSource("/api/events");
  es.onmessage = async () => {
    try {
      const res = await api("/api/scene");
      if (res.error) throw new Error(res.error);
      if (!res.scene || res.version === sceneVersion) return;
      sceneVersion = res.version;
      scene = res.scene;
      if (scene.plan) {
        planSeq++;   // a plan request still in flight must not replace it
        applyPlan(scene.plan);
        status(`showing ${scene.title || "a pushed plan"} (from an agent)`);
      }
      redraw();
    } catch (e) {
      status("scene update failed: " + e.message, true);
    }
  };
  es.onerror = () => { es.close(); setTimeout(listenScenes, 3000); };
}
