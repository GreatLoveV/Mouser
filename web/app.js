"use strict";
// ---------- session token (handed over in the URL fragment, never sent to the server in a URL) ----------
const TOKEN = (() => {
  const m = location.hash.match(/t=([\w-]+)/);
  try {
    if (m) sessionStorage.setItem("mouser-token", m[1]);
    history.replaceState(null, "", location.pathname);
    return m ? m[1] : sessionStorage.getItem("mouser-token") || "";
  } catch { return m ? m[1] : ""; }
})();

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k === "style") el.style.cssText = v; // CSSOM, allowed by our CSP (style attributes are not)
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null) el.append(k);
  return el;
}
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

async function api(path, body) {
  const opts = { headers: { "X-Mouser-Token": TOKEN } };
  if (body !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `Request failed (${r.status})`);
  return data;
}

let toastTimer;
function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.toggle("err", isErr);
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), isErr ? 6000 : 2200);
}
async function act(path, body, ok) {
  try { await api(path, body); if (ok) toast(ok); return true; }
  catch (e) { toast(e.message, true); return false; }
}

// ---------- the mouse's controls, in physical order ----------
const CONTROLS = {
  left: { name: "Left click", fixed: true },
  right: { name: "Right click" },
  middle: { name: "Wheel click" },
  tilt_left: { name: "Wheel tilt left" },
  tilt_right: { name: "Wheel tilt right" },
  scroll_mode: { name: "Scroll mode button", fixed: true },
  dpi: { name: "DPI button", fixed: true },
  clutch: { name: "Sensitivity clutch", fixed: true },
  forward: { name: "Forward (front side button)" },
  back: { name: "Back (rear side button)" },
};
const PRESS_NAMES = { ...Object.fromEntries(Object.entries(CONTROLS).map(([k, v]) => [k, v.name])),
  forward: "Forward side button", back: "Back side button", wheel_up: "Scroll up", wheel_down: "Scroll down" };
const FLASH_ONLY = new Set(["tilt_left", "tilt_right", "dpi", "scroll_mode"]);
const MOUSE_NAMES = { left: "Left click", right: "Right click", middle: "Middle click", back: "Back", forward: "Forward" };
const MEDIA_NAMES = { play_pause: "Play / pause", next: "Next track", prev: "Previous track", vol_up: "Volume up", vol_down: "Volume down", mute: "Mute" };
const DPI_NAMES = { up: "DPI stage up", down: "DPI stage down", cycle: "Cycle DPI stages" };
// Breathing and reactive aren't here: the Basilisk V3 refuses them (tested on firmware v1.00).
const EFFECT_NAMES = { off: "Off", static: "Static", spectrum: "Spectrum", wave: "Wave" };
const ZONE_NAMES = { all: "All", scroll: "Scroll wheel", logo: "Logo", underglow: "Underglow" };

function describe(a) {
  if (!a || a.type === "default") return "Normal";
  switch (a.type) {
    case "disabled": return "Turned off";
    case "mouse": return MOUSE_NAMES[a.button];
    case "keys": return a.label;
    case "media": return MEDIA_NAMES[a.key];
    case "dpi": return DPI_NAMES[a.mode];
    case "clutch": return `Clutch at ${a.dpi} DPI`;
  }
  return "Custom";
}

// ---------- state ----------
let S = null;               // everything we know about the mouse and the app
let seq = 0;                // last event we've seen
let stages = [];            // the stage list as shown (may hold an edit not sent yet)
let editingProfile = "default";
let selected = null;        // control open in the Buttons tab
let lightZone = "all";
const pending = { stages: 0, light: 0, polling: 0, scroll: 0 }; // ignore echoes right after our own writes
const hold = (k, ms = 1200) => (pending[k] = Date.now() + ms);
const busy = (k) => Date.now() < pending[k];

async function loadState() {
  try {
    S = await api("/api/state");
  } catch (e) {
    setDevice(false, e.message);
    return false;
  }
  seq = S.seq;
  for (const el of $$(".pressed")) el.classList.remove("pressed"); // releases we may have missed
  stages = (S.stages || []).map((s) => [...s]);
  $("#split-xy").checked = stages.some(([x, y]) => x !== y);
  renderAll();
  return true;
}

function renderAll() {
  const ok = S.connected;
  setDevice(ok, ok ? `Basilisk V3 connected, firmware ${S.firmware}` : "Basilisk V3 not found. Plug it in by USB; Mouser reconnects by itself.");
  // Settings can't be read or changed without the mouse: lock the panel instead of showing stale values.
  $(".panel").inert = !ok;
  $(".panel").classList.toggle("offline", !ok);
  $("#pause").checked = S.paused;
  if (ok) {
    renderReadout();
    renderStages();
    renderClutch();
    renderPolling();
    renderScroll();
    renderLighting();
  }
  renderProfiles();
  renderBinds();
  paintMouse();
}

function setDevice(ok, text) {
  const d = $("#device");
  if (!d) return; // after Quit the page is replaced
  d.textContent = text;
  d.className = "device " + (ok ? "ok" : "bad");
}

// ---------- tabs ----------
const tabs = $$('[role="tab"]');
function selectTab(tab) {
  for (const t of tabs) {
    const on = t === tab;
    t.setAttribute("aria-selected", on);
    t.tabIndex = on ? 0 : -1;
    $("#" + t.getAttribute("aria-controls")).hidden = !on;
  }
}
for (const t of tabs) {
  t.addEventListener("click", () => selectTab(t));
  t.addEventListener("keydown", (e) => {
    const i = tabs.indexOf(t);
    const n = e.key === "ArrowRight" ? tabs[(i + 1) % tabs.length] : e.key === "ArrowLeft" ? tabs[(i - 1 + tabs.length) % tabs.length] : null;
    if (n) { e.preventDefault(); n.focus(); selectTab(n); }
  });
}

function seg(container, options, value, onPick) {
  container.replaceChildren(
    ...Object.entries(options).map(([v, label]) =>
      h("button", { type: "button", role: "radio", "aria-checked": String(String(v) === String(value)), onclick: () => onPick(v) }, label))
  );
}

// ---------- readout under the drawing ----------
function renderReadout() {
  const [x, y] = S.dpi;
  $("#dpi-now").textContent = x === y ? x : `${x} × ${y}`;
  const a = S.active_stage;
  $("#pips").replaceChildren(...S.stages.map(([sx], i) => h("button", {
    type: "button", class: "pip" + (i + 1 === a ? " on" : ""), "aria-pressed": String(i + 1 === a),
    "aria-label": `Stage ${i + 1}, ${sx} DPI`, title: `Stage ${i + 1}: ${sx} DPI`,
    onclick: () => switchStage(i + 1),
  }, String(i + 1))));
  const stageDpi = S.stages[a - 1] || [x, y];
  $("#dpi-note").textContent = S.clutch ? "Sensitivity clutch held"
    : !same(stageDpi, S.dpi) ? "Set by your profile, not a stage" : `Stage ${a} of ${S.stages.length}`;
  const sc = S.scroll || {};
  $("#wheel-now").textContent = (sc.free_spin ? "Free-spin" : "Notched") + (sc.smart_reel ? ", smart-reel on" : "");
  const prof = S.profiles.find((p) => p.id === S.active_profile);
  $("#profile-now").textContent = prof ? prof.name : "–";
}

// ---------- sensitivity ----------
const MAX_DPI = 26000;
const logFill = (v) => (Math.log(v) - Math.log(100)) / (Math.log(MAX_DPI) - Math.log(100));
function renderStages() {
  const box = $("#stages");
  // Don't rebuild while you're typing in a stage: just move the "active" mark.
  if (box.contains(document.activeElement) && box.children.length === stages.length) {
    [...box.children].forEach((row, i) => {
      row.classList.toggle("active", i + 1 === S.active_stage);
      row.querySelector('input[type="radio"]').checked = i + 1 === S.active_stage;
    });
    return;
  }
  const split = $("#split-xy").checked;
  box.replaceChildren(...stages.map(([x, y], i) => {
    const n = i + 1;
    const num = (val, axis) => h("input", {
      type: "number", min: 100, max: MAX_DPI, step: 50, value: val, "aria-label": `Stage ${n} ${axis} DPI`.replace("  ", " "),
      onchange: (e) => {
        const v = Math.max(100, Math.min(MAX_DPI, Math.round(+e.target.value / 50) * 50 || 100));
        e.target.value = v;
        if (axis === "Y") stages[i][1] = v; else { stages[i][0] = v; if (!split) stages[i][1] = v; }
        saveStages(S.active_stage, `Stage ${n} set to ${v} DPI`);
      },
    });
    return h("div", { class: "stage-row" + (n === S.active_stage ? " active" : "") },
      h("label", { class: "pick" },
        h("input", { type: "radio", name: "active-stage", checked: n === S.active_stage, onchange: () => switchStage(n) }),
        `Stage ${n}`),
      h("div", { class: "bar-track", "aria-hidden": "true" },
        h("div", { class: "bar-fill", style: `transform: scaleX(${logFill(Math.max(x, y))})` })),
      h("div", { class: "nums" }, num(x, split ? "X" : ""), split ? num(y, "Y") : null),
      h("button", {
        type: "button", class: "icon-btn", "aria-label": `Remove stage ${n}`, title: `Remove stage ${n}`, disabled: stages.length <= 1,
        onclick: () => {
          stages.splice(i, 1);
          saveStages(Math.min(S.active_stage > n ? S.active_stage - 1 : S.active_stage, stages.length), `Removed stage ${n}`);
        },
      }, "✕"));
  }));
  $("#add-stage").disabled = stages.length >= 5;
}
async function saveStages(active, msg) {
  hold("stages");
  S.active_stage = active;
  S.stages = stages.map((s) => [...s]);
  S.dpi = [...stages[active - 1]];
  renderStages(); renderReadout();
  if (!(await act("/api/stages", { stages, active }, msg))) loadState();
  hold("stages", 400);
}
function switchStage(n) {
  if (n === S.active_stage && same(S.dpi, S.stages[n - 1])) return;
  saveStages(n, `Stage ${n}: ${stages[n - 1][0]} DPI`);
}
$("#split-xy").addEventListener("change", () => {
  if (!$("#split-xy").checked && stages.some(([x, y]) => x !== y)) {
    stages = stages.map(([x]) => [x, x]);
    saveStages(S.active_stage, "X and Y now match");
  } else renderStages();
});
$("#add-stage").addEventListener("click", () => {
  const last = stages[stages.length - 1] || [800, 800];
  stages.push([Math.min(MAX_DPI, last[0] * 2), Math.min(MAX_DPI, last[1] * 2)]);
  saveStages(S.active_stage, `Added stage ${stages.length}`);
});

// ---------- sensitivity clutch ----------
// The slider is logarithmic (100 to 26000) so the low values you'd actually use get most of its length.
const toRange = (v) => Math.round(logFill(v) * 1000);
const fromRange = (r) => Math.max(100, Math.min(MAX_DPI, Math.round(Math.exp(Math.log(100) + (r / 1000) * (Math.log(MAX_DPI) - Math.log(100))) / 50) * 50));
function renderClutch() {
  const own = S.clutch_dpi != null;
  const hw = S.clutch_hw_dpi;
  const v = own ? S.clutch_dpi : hw || 400;
  $("#clutch-own").checked = own;
  const box = $("#clutch-value");
  box.setAttribute("aria-disabled", String(!own));
  for (const el of box.querySelectorAll("input")) el.disabled = !own;
  if (!box.contains(document.activeElement)) {
    $("#clutch-dpi").value = v;
    $("#clutch-range").value = toRange(v);
  }
  const builtIn = hw ? `${hw} DPI` : "its built-in DPI";
  $("#clutch-note").textContent = own
    ? `Holding the clutch switches to ${v} DPI while Mouser is running. If Mouser isn't running, the mouse uses ${builtIn}.`
    : hw ? `The clutch uses the mouse's built-in ${hw} DPI.` : "The clutch uses the mouse's built-in DPI. Press it once and Mouser will show the value here.";
}
let clutchTimer;
function saveClutch(dpi, msg) {
  S.clutch_dpi = dpi;
  renderClutch();
  clearTimeout(clutchTimer);
  clutchTimer = setTimeout(() => act("/api/clutch", { dpi }, msg), 250);
}
$("#clutch-own").addEventListener("change", (e) => {
  const v = e.target.checked ? +$("#clutch-dpi").value || S.clutch_hw_dpi || 400 : null;
  saveClutch(v, v ? `Clutch now drops to ${v} DPI` : "Clutch back to the mouse's built-in DPI");
});
$("#clutch-range").addEventListener("input", (e) => {
  const v = fromRange(+e.target.value);
  $("#clutch-dpi").value = v;
  saveClutch(v, `Clutch now drops to ${v} DPI`);
});
$("#clutch-dpi").addEventListener("change", (e) => {
  const v = Math.max(100, Math.min(MAX_DPI, Math.round(+e.target.value / 50) * 50 || 400));
  e.target.value = v;
  $("#clutch-range").value = toRange(v);
  saveClutch(v, `Clutch now drops to ${v} DPI`);
});

function renderPolling() {
  seg($("#polling"), { 125: "125 Hz", 500: "500 Hz", 1000: "1000 Hz" }, S.polling, async (v) => {
    hold("polling");
    S.polling = +v; renderPolling();
    await act("/api/polling", { hz: +v }, `Polling rate set to ${v} Hz`);
  });
}
function renderScroll() {
  for (const el of $$("[data-scroll]")) {
    const v = (S.scroll || {})[el.dataset.scroll];
    el.checked = !!v;
    el.disabled = v === null || v === undefined;
  }
}
for (const el of $$("[data-scroll]")) {
  el.addEventListener("change", async () => {
    hold("scroll");
    S.scroll[el.dataset.scroll] = el.checked;
    renderReadout();
    if (!(await act("/api/scroll", { key: el.dataset.scroll, on: el.checked }))) loadState();
  });
}

// ---------- lighting ----------
function zoneSpec(z) { return S.lighting[z === "all" ? "scroll" : z]; }
function renderLighting() {
  seg($("#zone"), ZONE_NAMES, lightZone, (z) => { lightZone = z; renderLighting(); });
  const spec = zoneSpec(lightZone);
  seg($("#effect"), EFFECT_NAMES, spec.effect, (e) => applyLight({ effect: e }));
  const editing = ["c1", "speed", "bright"].includes(document.activeElement?.id);
  if (!editing) {
    $("#c1").value = spec.colors[0] || "#00b4ff";
    $("#speed").value = spec.speed;
    $("#bright").value = spec.brightness;
  }
  $("#bright-out").textContent = $("#bright").value + "%";
  const e = spec.effect;
  $("#c1-wrap").hidden = e !== "static";
  $("#speed-wrap").hidden = e !== "wave";
  $("#bright-wrap").hidden = e === "off";
}
let lightTimer;
function applyLight(patch) {
  const cur = zoneSpec(lightZone);
  const effect = patch.effect || cur.effect;
  const spec = { effect, colors: [$("#c1").value], speed: +$("#speed").value, brightness: +$("#bright").value };
  const zones = lightZone === "all" ? ["scroll", "logo", "underglow"] : [lightZone];
  for (const z of zones) S.lighting[z] = { ...spec };
  hold("light", 2500);
  renderLighting();
  paintMouse();
  clearTimeout(lightTimer);
  lightTimer = setTimeout(() => act("/api/lighting", { zone: lightZone, ...spec }), 150);
}
for (const id of ["#c1", "#speed", "#bright"]) $(id).addEventListener("input", () => applyLight({}));

function paintMouse() {
  if (!S || !S.lighting) return;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  for (const g of $$(".zone")) {
    const spec = S.lighting[g.dataset.zone];
    const flashing = g.classList.contains("flash");
    g.className.baseVal = "zone" + (flashing ? " flash" : "");
    g.style.setProperty("--zc", spec.colors[0] || "#00b4ff");
    g.style.setProperty("--zc2", spec.colors[1] || spec.colors[0] || "#00b4ff");
    g.style.setProperty("--speed", spec.speed);
    g.style.opacity = 0.35 + 0.65 * (spec.brightness / 100);
    if (spec.effect === "off" || spec.brightness === 0) g.classList.add("off");
    else if (spec.effect === "spectrum" || spec.effect === "wave") { g.style.setProperty("--zc", "#ff3b3b"); if (!reduce) g.classList.add("fx-" + spec.effect); }
  }
  const s = S.lighting.scroll;
  document.documentElement.style.setProperty("--signal", s.effect === "static" ? s.colors[0] : "#00b4ff");
  const prof = profile();
  for (const el of $$("#mouse .hot")) {
    el.classList.toggle("mapped", !!(prof && prof.bindings[el.dataset.btn]));
    el.classList.toggle("selected", el.dataset.btn === selected);
  }
}

// ---------- live link with the mouse ----------
function markPress(name, down) {
  for (const el of $$(`#mouse [data-btn="${name}"], [data-bind="${name}"]`)) {
    if (FLASH_ONLY.has(name)) {
      el.classList.remove("pressed");
      void el.getBoundingClientRect();
      el.classList.add("pressed", "flash-once");
      setTimeout(() => el.classList.remove("pressed", "flash-once"), 240);
    } else {
      el.classList.toggle("pressed", down);
    }
  }
}
function lastPressed(text) { $("#last-btn").textContent = text; }
function flashReactive() {
  for (const g of $$(".zone.fx-reactive")) {
    g.classList.add("flash");
    setTimeout(() => g.classList.remove("flash"), 60);
  }
}
let wheelTimer;
function spinWheel(dir) {
  const r = $("#ridges");
  r.classList.remove("roll-up", "roll-down");
  void r.getBoundingClientRect();
  r.classList.add(dir === "up" ? "roll-up" : "roll-down");
  clearTimeout(wheelTimer);
  wheelTimer = setTimeout(() => r.classList.remove("roll-up", "roll-down"), 200);
}

function onEvent(e) {
  switch (e.kind) {
    case "button":
      markPress(e.name, e.down);
      if (e.down) { lastPressed(PRESS_NAMES[e.name] || e.name); flashReactive(); }
      break;
    case "wheel":
      spinWheel(e.dir);
      lastPressed(PRESS_NAMES["wheel_" + e.dir]);
      break;
    case "hw_button":
      if (e.name === "clutch") {
        markPress("clutch", e.down);
        if (e.down) lastPressed("Sensitivity clutch (held)");
      } else {
        markPress(e.name, true); // the "dpi" / "scroll" events carry the new values and set the text
      }
      flashReactive();
      break;
    case "dpi":
      if (e.cause === "dpi_button") lastPressed(`DPI button, now stage ${e.active_stage} (${e.dpi[0]} DPI)`);
      break;
    case "scroll":
      if (S.scroll && e.scroll.free_spin !== S.scroll.free_spin) lastPressed(`Scroll mode button, now ${e.scroll.free_spin ? "free-spin" : "notched"}`);
      break;
    case "connection":
      loadState();
      break;
  }
}

// Bring what's on screen in line with what the mouse reports, without
// fighting a change you just made.
function sync(st) {
  if (st.connected !== S.connected) return loadState();
  S.paused = st.paused; $("#pause").checked = st.paused;
  S.foreground = st.foreground;
  if (st.active_profile !== S.active_profile) { S.active_profile = st.active_profile; renderProfiles(); }
  if (!st.connected) return;
  S.clutch = st.clutch;
  if (st.clutch_hw_dpi !== S.clutch_hw_dpi) { S.clutch_hw_dpi = st.clutch_hw_dpi; renderClutch(); }
  if (!busy("stages")) {
    S.dpi = st.dpi;
    if (!same(st.stages, S.stages) || st.active_stage !== S.active_stage) {
      S.stages = st.stages; S.active_stage = st.active_stage;
      if (!$("#stages").contains(document.activeElement)) stages = st.stages.map((s) => [...s]);
      renderStages();
    }
  }
  if (!busy("polling") && st.polling !== S.polling) { S.polling = st.polling; renderPolling(); }
  if (!busy("scroll") && !same(st.scroll, S.scroll)) { S.scroll = st.scroll; renderScroll(); }
  if (!busy("light") && !same(st.lighting, S.lighting)) { S.lighting = st.lighting; renderLighting(); paintMouse(); }
  renderReadout();
  $("#device").title = st.foreground ? `Program in front: ${st.foreground}` : "";
}

async function live() {
  for (;;) {
    try {
      const L = await api(`/api/live?since=${seq}`);
      if (L.reset) { await loadState(); continue; }
      for (const e of L.events) onEvent(e);
      seq = L.seq;
      sync(L.state);
      // Minimized: check rarely, so the app also stops watching the mouse closely.
      await new Promise((r) => setTimeout(r, document.hidden ? 4000 : 60));
    } catch (e) {
      setDevice(false, "Mouser isn't answering. Reopen it from the Start menu or the tray icon.");
      await new Promise((r) => setTimeout(r, 2000));
    }
  }
}

// ---------- buttons ----------
function profile() { return S && (S.profiles.find((p) => p.id === editingProfile) || S.profiles[0]); }
for (const el of $$("#mouse .hot")) {
  const c = CONTROLS[el.dataset.btn];
  el.setAttribute("tabindex", "0");
  el.setAttribute("role", "button");
  el.setAttribute("aria-label", c.fixed ? `${c.name}: what it does` : `Change ${c.name}`);
  el.append(Object.assign(document.createElementNS("http://www.w3.org/2000/svg", "title"), { textContent: c.name }));
  const pick = () => { selectTab($("#tab-buttons")); openControl(el.dataset.btn); };
  el.addEventListener("click", pick);
  el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
}

function renderBinds() {
  const sel = $("#edit-profile");
  sel.replaceChildren(...S.profiles.map((p) => h("option", { value: p.id, selected: p.id === editingProfile }, p.name)));
  const prof = profile();
  $("#binds").replaceChildren(...Object.entries(CONTROLS).map(([b, c]) => {
    const a = prof.bindings[b];
    return h("li", {}, h("button", {
      type: "button", "data-bind": b, "aria-current": String(b === selected), onclick: () => openControl(b),
    }, h("span", {}, c.name), h("span", { class: "what" + (a ? " changed" : "") }, c.fixed ? "Built into the mouse" : describe(a))));
  }));
}
$("#edit-profile").addEventListener("change", (e) => { editingProfile = e.target.value; closeEditor(); });

function openControl(b) {
  selected = b;
  const c = CONTROLS[b];
  $("#editor").hidden = true;
  $("#fixed-info").hidden = true;
  if (c.fixed) showInfo(b);
  else openEditor(b);
  renderBinds();
  paintMouse();
  const panel = c.fixed ? $("#fixed-info") : $("#editor");
  panel.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
}

function showInfo(b) {
  const st = S.stages.map(([x]) => x).join(", ");
  const info = {
    left: ["Left click always stays a left click, so no setting can lock you out of your mouse.", null],
    dpi: [`Steps through your DPI stages (${st}) and starts over after the last one. The mouse handles this button itself, so it can't be remapped, but you can change the stages it steps through.`, "Edit DPI stages"],
    scroll_mode: [`Switches the wheel between notched and free-spin. It's ${S.scroll.free_spin ? "free-spin" : "notched"} right now. The mouse handles this button itself.`, "Scroll wheel settings"],
    clutch: [`Lowers your DPI while you hold it, for precise aiming${S.clutch_dpi ? ` (now ${S.clutch_dpi} DPI)` : ""}. The mouse handles the button itself, so it can't be remapped, but you can choose the DPI it drops to.`, "Set clutch DPI"],
  }[b];
  $("#fixed-title").textContent = CONTROLS[b].name;
  $("#fixed-text").textContent = info[0];
  const go = $("#fixed-go");
  go.hidden = !info[1];
  go.textContent = info[1] || "";
  go.onclick = () => {
    selectTab($("#tab-sens"));
    const target = { dpi: "#stages", clutch: "#clutch-h", scroll_mode: "[data-scroll]" }[b];
    $(target).scrollIntoView({ block: "center" });
    if (b === "clutch") $("#clutch-own").focus();
  };
  $("#fixed-info").hidden = false;
}
$("#fixed-close").addEventListener("click", () => { selected = null; $("#fixed-info").hidden = true; renderBinds(); paintMouse(); });

let captured = null;
function openEditor(b) {
  const a = profile().bindings[b] || { type: "default" };
  $("#editor").hidden = false;
  $("#editor-title").textContent = CONTROLS[b].name;
  $('#act-type option[value="clutch"]').disabled = b.startsWith("tilt");
  $("#act-type").value = a.type;
  if (a.type === "mouse") $("#act-mouse").value = a.button;
  if (a.type === "media") $("#act-media").value = a.key;
  if (a.type === "dpi") $("#act-dpi").value = a.mode;
  if (a.type === "clutch") $("#act-clutch").value = a.dpi;
  captured = a.type === "keys" ? { keys: a.keys, label: a.label } : null;
  $("#act-keys").textContent = captured ? captured.label : "Click, then press the keys";
  showFields();
}
function closeEditor() { selected = null; $("#editor").hidden = true; $("#fixed-info").hidden = true; renderBinds(); paintMouse(); }
function showFields() {
  const t = $("#act-type").value;
  for (const el of $$("[data-for]")) el.hidden = el.dataset.for !== t;
}
$("#act-type").addEventListener("change", showFields);
$("#act-cancel").addEventListener("click", closeEditor);

// shortcut capture
const KEY_LABEL = { 16: "Shift", 17: "Ctrl", 18: "Alt", 91: "Win", 92: "Win", 32: "Space", 13: "Enter", 27: "Esc", 9: "Tab", 8: "Backspace", 46: "Delete",
  37: "Left", 38: "Up", 39: "Right", 40: "Down", 33: "Page Up", 34: "Page Down", 35: "End", 36: "Home", 45: "Insert" };
const MODS = [17, 16, 18, 91];
let listening = false, held = [];
function stopListening() { listening = false; $("#act-keys").classList.remove("listening"); }
$("#act-keys").addEventListener("click", () => {
  listening = true; held = [];
  $("#act-keys").classList.add("listening");
  $("#act-keys").textContent = "Press the keys now…";
});
$("#act-keys").addEventListener("blur", () => {
  if (listening && !captured) $("#act-keys").textContent = "Click, then press the keys";
  stopListening();
});
document.addEventListener("keydown", (e) => {
  if (!listening) return;
  e.preventDefault();
  const vk = e.keyCode;
  if (!vk || held.includes(vk) || held.length >= 4) return;
  held.push(vk);
  held.sort((a, b) => (MODS.includes(b) - MODS.includes(a)));
  const label = held.map((k) => KEY_LABEL[k] || (k >= 112 && k <= 135 ? "F" + (k - 111) : String.fromCharCode(k).trim() || `Key ${k}`)).join(" + ");
  captured = { keys: [...held], label };
  $("#act-keys").textContent = label;
  if (!MODS.includes(vk)) stopListening();
});

$("#act-save").addEventListener("click", async () => {
  const t = $("#act-type").value;
  let a = { type: t };
  if (t === "mouse") a.button = $("#act-mouse").value;
  if (t === "media") a.key = $("#act-media").value;
  if (t === "dpi") a.mode = $("#act-dpi").value;
  if (t === "clutch") {
    const v = Math.round(+$("#act-clutch").value / 50) * 50;
    if (!(v >= 100 && v <= 26000)) return toast("Pick a clutch DPI between 100 and 26000.", true);
    a.dpi = v;
  }
  if (t === "keys") {
    if (!captured) return toast("Press a shortcut first: click the box, then press the keys.", true);
    a = { type: "keys", ...captured };
  }
  if (t === "mouse" && a.button === selected) a = { type: "default" };
  const profiles = structuredClone(S.profiles);
  const p = profiles.find((x) => x.id === editingProfile);
  if (a.type === "default") delete p.bindings[selected]; else p.bindings[selected] = a;
  const label = CONTROLS[selected].name;
  if (await act("/api/profiles", { profiles }, `${label}: ${describe(a)}`)) {
    S.profiles = profiles;
    closeEditor();
  }
});

// ---------- profiles ----------
function renderProfiles() {
  $("#profile-list").replaceChildren(...S.profiles.map((p, i) => {
    const apps = i === 0 ? "Used whenever no other profile matches" : p.apps.join(", ");
    const extra = p.dpi ? `, sets ${p.dpi} DPI` : "";
    const live = p.id === S.active_profile;
    return h("li", {},
      h("div", {},
        h("div", { class: live ? "live" : "" }, p.name + (live ? " (in use)" : "")),
        h("div", { class: "meta" }, apps + extra)),
      i === 0 ? h("span") : h("button", {
        type: "button", class: "ghost", "aria-label": `Delete profile ${p.name}`,
        onclick: async () => {
          if (!confirm(`Delete the ${p.name} profile and its button settings?`)) return;
          const profiles = S.profiles.filter((x) => x.id !== p.id);
          if (await act("/api/profiles", { profiles }, `Deleted ${p.name}`)) {
            if (editingProfile === p.id) editingProfile = "default";
            loadState();
          }
        },
      }, "Delete"));
  }));
  const prof = S.profiles.find((p) => p.id === S.active_profile);
  $("#profile-now").textContent = prof ? prof.name : "–";
}
$("#new-profile").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("#np-name").value.trim();
  const apps = $("#np-apps").value.split(",").map((s) => s.trim()).filter(Boolean);
  if (!apps.length) return toast("Add at least one program, like game.exe. Without one this profile would never switch on.", true);
  const dpi = $("#np-dpi").value ? Math.round(+$("#np-dpi").value / 50) * 50 : null;
  let id = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 30) || "profile";
  while (S.profiles.some((p) => p.id === id)) id += "-2";
  const profiles = [...S.profiles, { id, name, apps, bindings: {}, dpi }];
  if (await act("/api/profiles", { profiles }, `Added ${name}`)) {
    e.target.reset();
    editingProfile = id;
    loadState();
  }
});
$("#np-apps").addEventListener("focus", () => {
  const fg = S && S.foreground;
  if (fg && !$("#np-apps").value && !["chrome.exe", "msedge.exe", "explorer.exe"].includes(fg)) $("#np-apps").placeholder = fg;
});

// ---------- top bar ----------
$("#pause").addEventListener("change", (e) =>
  act("/api/pause", { paused: e.target.checked }, e.target.checked ? "Remapping paused. Buttons do their normal jobs." : "Remapping is back on"));
$("#quit").addEventListener("click", async () => {
  if (!confirm("Quit Mouser? Remapped buttons go back to normal until you open it again. DPI, lighting and scroll settings stay on the mouse.")) return;
  await act("/api/quit", {});
  document.body.replaceChildren(h("p", { class: "hint", style: "padding:32px" }, "Mouser has quit. You can close this window."));
});

// Coming back to the window: catch up at once instead of waiting for the slow check.
document.addEventListener("visibilitychange", () => { if (!document.hidden && S) loadState(); });

if (!TOKEN) {
  setDevice(false, "Open Mouser from the Start menu or its tray icon to use this window.");
} else {
  loadState().then(live);
}
