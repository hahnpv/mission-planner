"use strict";
// Sun-synchronous presets -- served by modules/sso.py.  No panel of its own:
// rows under the orbit-preset dropdown (repeat-track variant, LTAN), shown
// while a `sun_synchronous` catalog preset is in play.
MP.register({
  title: "sun-synchronous presets",
  init(ctx) {
    const el = ctx.presetControls(`
      <div id="sso_rows" hidden>
        <div id="sso_varrow">
          <div class="lbl">variant</div>
          <select id="sso_variant"></select>
        </div>
        <div class="lbl">LTAN — local time of ascending node (h)</div>
        <input id="sso_ltan" type="number" step="0.5" min="0" max="24" value="10.5">
      </div>`);
    const $s = id => el.querySelector("#sso_" + id);
    // Its own constants, like a plugin would have (km, km^3/s^2).
    const RE_KM = 6378.137, MU_KM = 398600.4418, J2 = 1.08262668e-3, DEG = Math.PI / 180;
    let on = false, variants = [];

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
    function repeatOptions() {
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
                     h: +h.toFixed(1) });
      }
      return out;
    }

    // Exact inclination for the current hp/ha, and node longitude from the
    // LTAN at the chosen epoch (mean sun; the equation of time adds up to
    // ~16 min that planning can ignore).
    function sync(shape) {
      if (!on) return;
      const { hp, ha, epoch } = shape;
      const inc = ssoInclination(hp, ha);
      if (isNaN(inc)) {
        ctx.status("no sun-synchronous inclination exists at this altitude", true);
        return;
      }
      const utcH = epoch ? (+epoch.slice(11, 13)) + (+epoch.slice(14, 16)) / 60 : 12;
      const lam = ((+$s("ltan").value - utcH) * 15 + 540) % 360;
      const node = ((lam + 360) % 360 - 180).toFixed(1);
      ctx.setShape({ inc: inc.toFixed(2), node_lon: node });   // 2 decimals kept
      const s = ctx.getShape();
      ctx.status(`SSO synced: inc ${s.inc}° for ${hp}×${ha} km, `
        + `node ${node}° for LTAN ${$s("ltan").value} h`);
    }

    ctx.onPreset(rec => {
      on = !!rec?.sun_synchronous;
      $s("rows").hidden = !on;
      if (!on) return;
      variants = repeatOptions();
      $s("varrow").hidden = !variants.length;
      $s("variant").innerHTML = "<option value=''>custom altitude</option>"
        + variants.map((o, i) => `<option value="${i}">${o.label}</option>`).join("");
    });
    ctx.onShapeChange(sync);
    $s("ltan").oninput = () => sync(ctx.getShape());
    $s("variant").onchange = () => {
      const o = variants[+$s("variant").value];
      if (o) ctx.setShape({ hp: o.h, ha: o.h });   // re-runs sync via onShapeChange
    };
  },
});
