"use strict";
// ------------------------------------------------------------ file picker
// A reusable file input over the server's upload store (uploads.py): a list
// of the files already stored there (filtered by extension), a browse button
// that uploads a new one, drop-a-file-on-it, and a remove button that deletes
// the chosen file from the server (after a confirm).  Anything that reads a file
// -- a trajectory source's panel, a module panel -- builds one with
// filePicker(opts) (plugins: ctx.filePicker) and passes `picker.value`, the
// upload id, as a request arg (upload=<id>).
//
//   opts: {accept: ".h5,.hdf5", placeholder: "choose a file…",
//          onChange(info | null)}   info = {id, name, size, uploaded_utc,
//                                           kind, kind_label, kind_note}
// Each file is labelled with its kind: the plugin file reader that claims it
// (filekinds.py), or "unrecognised".
//   returns {el, value, info, select(id) (async), refresh()}
function fmtBytes(n) {
  if (n < 1024) return n + " B";
  const u = ["kB", "MB", "GB"];
  let i = -1;
  do { n /= 1024; i++; } while (n >= 1024 && i < u.length - 1);
  return n.toFixed(n < 10 ? 1 : 0) + " " + u[i];
}
function filePicker(opts = {}) {
  const accept = opts.accept || "";
  const exts = accept.split(",").map(s => s.trim()).filter(s => s.startsWith("."));
  const el = document.createElement("div");
  el.className = "filepick";
  el.innerHTML = `<div class="row"><select></select>
    <button class="small ghost" type="button" title="upload a file from this computer">browse…</button>
    <button class="small ghost" type="button" title="delete the chosen file from the server" disabled>✕</button></div>
    <input type="file" hidden>`;
  const sel = el.querySelector("select"), input = el.querySelector("input");
  const [btn, del] = el.querySelectorAll("button");
  if (accept) input.accept = accept;
  let list = [];
  const picker = {
    el,
    get value() { return sel.value; },
    get info() { return list.find(x => x.id === sel.value) || null; },
    async select(id) {
      if (!list.some(x => x.id === id)) await load(id); else render(id);
      changed();
    },
    refresh: () => load(sel.value),
  };
  function render(keep) {
    sel.innerHTML = `<option value="">${escHtml(opts.placeholder || "choose a file…")}</option>`
      + list.map(x => `<option value="${x.id}">${escHtml(x.name)}`
        + ("kind" in x ? ` · ${escHtml(x.kind_label || "unrecognised")}` : "")
        + ` · ${fmtBytes(x.size)}`
        + (x.uploaded_utc ? ` · ${x.uploaded_utc.slice(0, 10)}` : "") + "</option>").join("");
    sel.value = list.some(x => x.id === keep) ? keep : "";
    del.disabled = !sel.value;
  }
  const changed = () => { del.disabled = !sel.value; opts.onChange?.(picker.info); };
  async function load(keep) {
    try {
      const res = await api("/api/uploads" + (exts.length ? "?ext=" + encodeURIComponent(exts.join(",")) : ""));
      if (res.error) throw new Error(res.error);
      list = res;
    } catch (e) {
      status("stored files failed to load: " + e.message, true);
    }
    render(keep);
  }
  async function send(file) {
    if (exts.length && !exts.some(x => file.name.toLowerCase().endsWith(x.toLowerCase()))) {
      status(`${file.name}: expected ${exts.join(" / ")}`, true);
      return;
    }
    status(`uploading ${file.name} (${fmtBytes(file.size)})…`);
    const fd = new FormData();
    fd.append("file", file);
    let res = null;
    try {
      const r = await fetch("/api/uploads", { method: "POST", body: fd });
      try { res = await r.json(); } catch {}
      if (!r.ok && !(res && res.error)) throw new Error(`HTTP ${r.status}`);
      if (res.error) throw new Error(res.error);
    } catch (e) {
      status(`upload of ${file.name} failed: ${e.message}`, true);
      return;
    }
    status(`uploaded ${res.name}.`);
    await load(res.id);
    changed();
  }
  sel.onchange = changed;
  // Pick up files stored from elsewhere (MCP, another tab) before the list is
  // opened -- re-rendering an open <select> would close it.
  el.addEventListener("mouseenter", () => load(sel.value));
  btn.onclick = () => input.click();
  del.onclick = async () => {
    const x = picker.info;
    if (!x || !confirm(`Delete ${x.name} from the server?\n\nPlans that use it will need it `
                        + "uploaded again.")) return;
    let res;
    try {
      res = await fetch("/api/uploads/" + x.id, { method: "DELETE" }).then(r => r.json());
    } catch (e) { res = { error: e.message }; }
    // Gone already (another tab) counts as done.
    if (res.error && !/no upload/.test(res.error)) {
      status(`delete of ${x.name} failed: ${res.error}`, true);
      return;
    }
    status(`deleted ${x.name}.`);
    await load("");
    changed();
  };
  input.onchange = () => { if (input.files[0]) send(input.files[0]); input.value = ""; };
  el.addEventListener("dragover", ev => { ev.preventDefault(); el.classList.add("drop"); });
  el.addEventListener("dragleave", () => el.classList.remove("drop"));
  el.addEventListener("drop", ev => {
    ev.preventDefault();
    el.classList.remove("drop");
    const f = ev.dataTransfer.files[0];
    if (f) send(f);
  });
  load();
  return picker;
}
