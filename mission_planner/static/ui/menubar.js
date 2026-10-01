"use strict";
// Drop-down menu bar.  Generic: knows nothing about orbits or plugins.
//
//   const bar = new Menubar(hostEl);
//   bar.add("View", { type:"radio", label:"globe", get:() => mode === "globe",
//                     set:() => setMode("globe") });
//
// Item types:
//   action  {label, run(), enabled?()}             closes the menu
//   check   {label, get(), set(bool), enabled?()}  stays open, so several can be flipped
//   radio   {label, get(), set(), enabled?()}      closes the menu
//   head    {label}                                a small section caption
//   note    {label}                                small muted text, wraps
//   sep     {}                                     a divider
//   group   {items()}                              expands to the items it returns
//                                                  at open time (lists that change)
// Any item may carry visible?() -- false hides it (an inert plugin's items) --
// title, a hover tooltip; badges, a list of small tags; and detail?() (or a
// string), a second line under the label, red when detailErr?() is true.
// Dropdowns are rebuilt every time they open, so get()/enabled() are always
// read fresh and the bar never holds state of its own.  A menu with no
// visible items (bar a head or sep) is hidden from the bar.
class Menubar {
  constructor(host) {
    this.host = host;
    this.menus = [];          // [{name, items, btn}]
    this.openMenu = null;     // the menu whose dropdown is showing
    this.drop = document.createElement("div");
    this.drop.className = "mb-drop";
    this.drop.hidden = true;
    document.body.appendChild(this.drop);
    // Click anywhere else, or Escape, closes the menu.
    document.addEventListener("mousedown", ev => {
      if (this.openMenu && !this.drop.contains(ev.target) && !this.host.contains(ev.target))
        this.close();
    });
    document.addEventListener("keydown", ev => {
      if (ev.key === "Escape" && this.openMenu) this.close();
    });
    window.addEventListener("resize", () => this.close());
  }

  // The named menu, created at the end of the bar if it doesn't exist yet.
  menu(name) {
    let m = this.menus.find(x => x.name === name);
    if (m) return m;
    const btn = document.createElement("button");
    btn.className = "mb-btn";
    btn.textContent = name;
    m = { name, items: [], btn };
    btn.addEventListener("mousedown", ev => {
      ev.preventDefault();
      this.openMenu === m ? this.close() : this.open(m);
    });
    // Once one menu is open, hovering the bar switches between them.
    btn.addEventListener("mouseenter", () => {
      if (this.openMenu && this.openMenu !== m) this.open(m);
    });
    this.host.appendChild(btn);
    this.menus.push(m);
    this.refresh();
    return m;
  }

  add(name, item) {
    this.menu(name).items.push(item);
    this.refresh();
    return item;
  }

  // Hide empty menus; re-render an open dropdown (visibility may have changed).
  refresh() {
    for (const m of this.menus)
      m.btn.hidden = !this.live(m).some(i => !["head", "sep", "note"].includes(i.type));
    if (this.openMenu) this.open(this.openMenu);
  }

  live(m) {
    return m.items.filter(i => !i.visible || i.visible())
      .flatMap(i => i.type === "group" ? i.items() : [i]);
  }

  open(m) {
    if (m.btn.hidden) { this.close(); return; }
    this.openMenu = m;
    this.menus.forEach(x => x.btn.classList.toggle("on", x === m));
    this.drop.innerHTML = "";
    // Drop separators and heads that would lead, trail or double up.
    const items = [];
    for (const it of this.live(m)) {
      const prev = items[items.length - 1];
      if (it.type === "sep" && (!prev || prev.type === "sep")) continue;
      if (prev && prev.type === "head" && (it.type === "head" || it.type === "sep")) items.pop();
      items.push(it);
    }
    while (items.length && ["sep", "head"].includes(items[items.length - 1].type)) items.pop();

    for (const it of items) {
      if (it.type === "sep") { this.drop.appendChild(Object.assign(document.createElement("div"), { className:"mb-sep" })); continue; }
      if (it.type === "head" || it.type === "note") {
        this.drop.appendChild(Object.assign(document.createElement("div"),
          { className: "mb-" + it.type, textContent: it.label }));
        continue;
      }
      const row = document.createElement("button");
      row.className = "mb-item";
      const on = (it.type === "check" || it.type === "radio") && it.get();
      const mark = it.type === "check" ? (on ? "✓" : "") : it.type === "radio" ? (on ? "●" : "") : "";
      row.innerHTML = `<span class="mb-mark"></span><span class="mb-label"></span>`;
      row.children[0].textContent = mark;
      row.children[1].textContent = it.label;
      if (it.swatch) {   // a colour from data: set it as a property, never as markup
        const sw = document.createElement("span");
        sw.className = "mb-sw"; sw.style.background = it.swatch;
        row.children[1].prepend(sw);
      }
      const val = f => typeof f === "function" ? f() : f;
      const detail = val(it.detail), badges = val(it.badges) || [];
      if (badges.length || detail) {
        const sub = document.createElement("span");
        sub.className = "mb-sub";
        for (const b of badges)
          sub.appendChild(Object.assign(document.createElement("span"), { className:"mb-badge", textContent:b }));
        if (detail)
          sub.appendChild(Object.assign(document.createElement("span"),
            { className: "mb-detail" + (val(it.detailErr) ? " err" : ""), textContent: detail }));
        row.children[1].appendChild(sub);
      }
      if (it.title) row.title = it.title;
      row.disabled = it.enabled ? !it.enabled() : false;
      row.addEventListener("click", () => {
        if (it.type === "check") { it.set(!it.get()); this.open(m); }
        else { this.close(); (it.run || it.set)(); }
      });
      this.drop.appendChild(row);
    }
    const r = m.btn.getBoundingClientRect();
    this.drop.style.left = r.left + "px";
    this.drop.style.top = r.bottom + "px";
    this.drop.hidden = false;
  }

  // A small dot on a menu's button, e.g. to say something inside needs a look;
  // null clears it.
  flag(name, color) {
    const btn = this.menu(name).btn;
    btn.querySelector(".mb-flag")?.remove();
    if (color) {
      const dot = document.createElement("span");
      dot.className = "mb-flag"; dot.style.background = color;
      btn.appendChild(dot);
    }
  }

  close() {
    this.openMenu = null;
    this.menus.forEach(x => x.btn.classList.remove("on"));
    this.drop.hidden = true;
  }
}
