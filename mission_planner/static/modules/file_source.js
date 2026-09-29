"use strict";
// The "File" trajectory source — served by modules/files.py.  One picker over
// every stored file, each labelled with the kind of file an active plugin
// recognised (filekinds.py).  Choosing one asks its reader to inspect it, and
// this panel draws what comes back, so a format needs no UI code of its own:
//
//   {summary, warning?, epoch_utc?, epoch_note?,
//    options?: [{key, label, choices: [..], default?}]}
//
// An option with a single choice is sent but not shown.
MP.register({
  title: "file",
  html: "",   // no side panel; the source brings its own
  init(ctx) {
    let info = null;   // /api/files/<id>/inspect for the chosen file
    const $f = id => document.getElementById("fsrc_" + id);
    const picker = ctx.filePicker({
      placeholder: "choose a file…",
      async onChange(f) {
        info = null;
        $f("opts").hidden = true;
        ctx.updateSource();
        if (!f) return;
        if (!f.kind) { ctx.status(`${f.name}: ${f.kind_note || "unrecognised"}`, true); return; }
        const res = await ctx.api(`/api/files/${f.id}/inspect`);
        if (picker.value !== f.id) return;   // chose another meanwhile
        if (res.error) { ctx.status(`${f.name}: ${res.error}`, true); return; }
        info = res;
        render(res);
        ctx.updateSource();
        ctx.status(`${res.kind_label} ready — show it.`);
      },
    });
    function render(res) {
      $f("kind").textContent = res.kind_label;
      $f("about").textContent = res.summary || "";
      $f("warn").textContent = res.warning || "";
      $f("warn").hidden = !res.warning;
      const box = $f("options");
      box.replaceChildren();
      for (const o of res.options || []) {
        const row = document.createElement("div");
        row.hidden = (o.choices || []).length < 2;
        const lbl = document.createElement("div");
        lbl.className = "lbl";
        lbl.textContent = o.label || o.key;
        const sel = document.createElement("select");
        sel.dataset.key = o.key;
        sel.replaceChildren(...(o.choices || []).map(c => new Option(c)));
        if (o.default != null) sel.value = o.default;
        row.append(lbl, sel);
        box.appendChild(row);
      }
      $f("epoch").value = "";
      const ep = res.epoch_utc ? res.epoch_utc.slice(0, 16).replace("T", " ") + " UTC" : "";
      $f("epochhint").textContent = "blank: " + [res.epoch_note || "the reader's default", ep]
        .filter(Boolean).join(", ");
      $f("opts").hidden = false;
    }
    ctx.addSource({
      id: "file", label: "File", planLabel: "show file",
      html: `<div class="lbl">file</div>
        <div id="fsrc_pick"></div>
        <div id="fsrc_opts" hidden>
          <div class="hint" style="margin-top:4px"><b id="fsrc_kind"></b>
            <span id="fsrc_about"></span></div>
          <div id="fsrc_warn" class="hint" style="color:var(--red)" hidden></div>
          <div id="fsrc_options"></div>
          <div class="lbl">t=0 (utc)</div>
          <input id="fsrc_epoch" type="datetime-local" step="1">
          <div id="fsrc_epochhint" class="hint"></div>
        </div>`,
      init(panel) { panel.querySelector("#fsrc_pick").appendChild(picker.el); },
      ready: () => !!info,
      args(q) {
        q.set("upload", picker.value);
        for (const sel of $f("options").querySelectorAll("select"))
          q.set(sel.dataset.key, sel.value);
        const ep = $f("epoch").value;
        if (ep) q.set("epoch", (ep.length === 16 ? ep + ":00" : ep) + "+00:00");
      },
    });
  },
});
