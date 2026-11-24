// Компоненты окна программы: кнопки, сегменты, переключатель, поля, всплывающая панель, меню (плоское, без
// подменю), лист (окно внутри окна), вопрос, тост, подсказка. Всё — обычный DOM, без сборки.
"use strict";
import { icon } from "./icons.js";

// ---------------------------------------------------------------- DOM
export function h(tag, attrs = null, ...children) {
  const e = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") e.className = v;
      else if (k === "text") e.textContent = v;
      else if (k === "html") e.innerHTML = v;
      else if (k === "style" && typeof v === "object") Object.assign(e.style, v);
      else if (k === "dataset") Object.assign(e.dataset, v);
      else if (k === "tip") tip(e, v);
      else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2).toLowerCase(), v);
      else if (v === true) e.setAttribute(k, "");
      else e.setAttribute(k, String(v));
    }
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return e;
}

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
export function clear(el) { while (el.firstChild) el.firstChild.remove(); return el; }
export function zoom() { return parseFloat(document.documentElement.style.zoom) || 1; }

// ---------------------------------------------------------------- кнопки
export function btn(text, o = {}) {
  const cls = ["btn", o.kind, o.size, o.block ? "block" : "", o.cls].filter(Boolean).join(" ");
  const b = h("button", { class: cls, type: "button", title: null, "aria-label": o.label || null,
    "aria-pressed": o.pressed === undefined ? null : String(!!o.pressed), disabled: o.disabled || null });
  if (o.icon) b.append(icon(o.icon, o.iconCls || ""));
  if (text) b.append(h("span", { class: "bl" }, text));
  if (o.tip) tip(b, o.tip);
  if (o.onClick) b.addEventListener("click", o.onClick);
  return b;
}

/** Кнопка-значок: подпись для диктора и подсказка обязательны. */
export function iconBtn(name, label, onClick, o = {}) {
  const b = btn("", { ...o, icon: name, label, cls: ["icon", o.cls].filter(Boolean).join(" "), onClick });
  tip(b, o.tip || label);
  return b;
}

// ---------------------------------------------------------------- сегменты
/** options: [{value, label, icon, tip}] — set(value) меняет нажатую без onChange. */
export function seg(options, value, onChange, o = {}) {
  const box = h("div", { class: ["seg", o.icons ? "icons" : "", o.size, o.cls].filter(Boolean).join(" "), role: "group",
    "aria-label": o.label || null });
  const buttons = options.map((opt) => {
    const b = h("button", { type: "button", "aria-pressed": String(opt.value === value),
      "aria-label": o.icons ? (opt.label || opt.tip) : null, dataset: { value: opt.value } });
    if (opt.icon) b.append(icon(opt.icon));
    if (!o.icons && opt.label) b.append(h("span", null, opt.label));
    if (opt.tip || o.icons) tip(b, opt.tip || opt.label);
    b.addEventListener("click", () => { box.set(opt.value); onChange && onChange(opt.value); });
    box.append(b);
    return b;
  });
  box.set = (v) => buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.value === String(v))));
  return box;
}

// ---------------------------------------------------------------- переключатель и поля
export function toggle(label, checked, onChange, hint = "") {
  const inp = h("input", { type: "checkbox", role: "switch", class: "sw" });
  inp.checked = !!checked;
  inp.addEventListener("change", () => onChange && onChange(inp.checked));
  const st = h("span", { class: "st" }, h("b", null, label), hint ? h("small", null, hint) : null);
  const lab = h("label", { class: "switch" }, inp, st);
  lab.input = inp;
  return lab;
}

let fieldN = 0;
export function field(label, control, o = {}) {
  const id = control.id || "f" + (++fieldN);
  const target = control.matches && control.matches("input, select, textarea") ? control : control.querySelector("input, select, textarea");
  if (target && !target.id) target.id = id;
  return h("div", { class: "field" }, h("label", { for: target ? target.id : null }, label), control,
    o.hint ? h("small", { class: "meta" }, o.hint) : null);
}

/** Число с пределами: значение за пределами поправляется при уходе из поля. Колесо — только у поля в фокусе. */
export function numberField(value, o = {}) {
  const inp = h("input", { class: "inp mono", type: "number", min: o.min, max: o.max, step: o.step || 1,
    "aria-label": o.label || null });
  inp.value = String(value);
  const fix = () => {
    let v = parseFloat(inp.value.replace(",", "."));
    if (isNaN(v)) v = parseFloat(o.min ?? 0);
    if (o.min !== undefined) v = Math.max(o.min, v);
    if (o.max !== undefined) v = Math.min(o.max, v);
    inp.value = String(v);
    o.onChange && o.onChange(v);
  };
  inp.addEventListener("change", fix);
  inp.addEventListener("wheel", (e) => { if (document.activeElement !== inp) e.preventDefault(); }, { passive: false });
  const box = h("span", { class: "num" }, inp, o.unit ? h("span", { class: "unit" }, o.unit) : null);
  box.input = inp;
  return box;
}

/** Выбор из списка: options — [[value, label]]. */
export function select(options, value, onChange, o = {}) {
  const s = h("select", { class: "sel", "aria-label": o.label || null });
  for (const [v, t] of options) {
    const op = h("option", { value: v }, t);
    if (String(v) === String(value)) op.selected = true;
    s.append(op);
  }
  s.addEventListener("change", () => onChange && onChange(s.value));
  return s;
}

// ---------------------------------------------------------------- всплывающая панель
let openPop = null;
export function closePop() { if (openPop) { const p = openPop; openPop = null; p.remove(); p.onclose && p.onclose(); } }

function place(el, anchor, align) {
  const z = zoom();
  const vw = innerWidth / z, vh = innerHeight / z;
  el.style.maxHeight = Math.max(140, vh - 16) + "px";
  const rr = anchor.getBoundingClientRect();
  const r = { left: rr.left / z, right: rr.right / z, top: rr.top / z, bottom: rr.bottom / z };
  const w = el.offsetWidth, hgt = el.offsetHeight;
  let x = align === "right" ? r.right - w : r.left, y = r.bottom + 6;
  if (x + w > vw - 8) x = vw - w - 8;
  if (y + hgt > vh - 8) y = r.top - hgt - 6 >= 8 ? r.top - hgt - 6 : Math.max(8, vh - hgt - 8);
  el.style.left = Math.max(8, x) + "px";
  el.style.top = y + "px";
}

/** Панель у элемента. Закрывается щелчком мимо, Esc, повторным вызовом. */
export function popover(anchor, content, o = {}) {
  closePop();
  const el = h("div", { class: "pop " + (o.cls || ""), role: o.role || "dialog" }, content);
  document.body.append(el);
  place(el, anchor, o.align);
  openPop = el;
  el.onclose = o.onClose;
  el.anchor = anchor;
  if (o.focus !== false) {
    const f = el.querySelector("input, button, select, textarea");
    if (f) f.focus({ preventScroll: true });
  }
  return { el, close: () => { if (openPop === el) closePop(); } };
}
document.addEventListener("mousedown", (e) => {
  if (openPop && !openPop.contains(e.target) && !(openPop.anchor && openPop.anchor.contains(e.target))) closePop();
}, true);

/** Меню — плоский список, без подменю: [{label, hint, danger, disabled, checked, on} | {sep} | {head}]. */
export function menu(anchor, items, o = {}) {
  const box = h("div", { class: "menu", role: "menu" });
  for (const it of items) {
    if (!it) continue;
    if (it.sep) { box.append(h("div", { class: "psep" })); continue; }
    if (it.head) { box.append(h("div", { class: "phead" }, it.head)); continue; }
    const b = h("button", { class: "mi" + (it.danger ? " danger" : ""), type: "button", role: "menuitem",
      "aria-checked": it.checked === undefined ? null : String(!!it.checked), disabled: it.disabled || null },
    it.icon ? icon(it.icon, "sm") : null, h("span", { class: "ml" }, it.label), it.hint ? h("span", { class: "mh" }, it.hint) : null);
    b.addEventListener("click", (e) => { e.stopPropagation(); closePop(); it.on && it.on(); });
    box.append(b);
  }
  return popover(anchor, box, { ...o, role: "menu" });
}

// ---------------------------------------------------------------- лист (окно внутри окна)
const sheets = [];
/** buttons: [{label, kind, value, autofocus}] → Promise<value | null>. Esc и «Отмена» → null. */
export function sheet(title, body, buttons, o = {}) {
  return new Promise((resolve) => {
    const foot = h("div", { class: "sfoot" });
    const scrim = h("div", { class: "scrim" });
    const box = h("div", { class: "sheet" + (o.wide ? " wide" : ""), role: "dialog", "aria-modal": "true",
      "aria-label": title }, h("div", { class: "shead" }, h("h2", null, title)), h("div", { class: "sbody" }, body), foot);
    const done = (v) => {
      const i = sheets.indexOf(api);
      if (i >= 0) sheets.splice(i, 1);
      scrim.remove();
      resolve(v);
    };
    const api = { done, box };
    let first = null, auto = null;
    for (const [i, b] of (buttons || []).entries()) {
      if (b.spacer) { foot.append(h("span", { class: "spacer" })); continue; }
      const el = btn(b.label, { kind: b.kind, onClick: () => { if (!b.check || b.check()) done(b.value === undefined ? b.label : b.value); } });
      foot.append(el);
      if (!first) first = el;
      if (b.autofocus || (!auto && i === buttons.length - 1)) auto = el;
    }
    if (!foot.childElementCount) foot.remove();
    scrim.append(box);
    scrim.addEventListener("mousedown", (e) => { if (e.target === scrim && o.dismiss !== false) done(null); });
    document.body.append(scrim);
    sheets.push(api);
    if (o.onOpen) o.onOpen(api);
    const f = o.focus ? box.querySelector(o.focus) : (body.querySelector && body.querySelector("input, textarea, select")) || auto;
    if (f) f.focus({ preventScroll: true });
  });
}

export function ask(text, o = {}) {
  const body = h("p", { class: "dim" }, text);
  return sheet(o.title || "Подтвердите", body, [
    { spacer: true },
    { label: o.cancel || "Отмена", kind: "ghost", value: false },
    { label: o.ok || "Да", kind: o.danger ? "danger" : "primary", value: true, autofocus: true },
  ]).then((v) => v === true);
}

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (openPop) { closePop(); e.stopPropagation(); return; }
  if (sheets.length) { sheets[sheets.length - 1].done(null); e.stopPropagation(); e.preventDefault(); }
}, true);
export function sheetOpen() { return sheets.length > 0; }

// ---------------------------------------------------------------- тост
export function toast(text, o = {}) {
  let host = document.getElementById("toasts");
  if (!host) { host = h("div", { id: "toasts", role: "status", "aria-live": "polite" }); document.body.append(host); }
  const t = h("div", { class: "toast" + (o.warn ? " warn" : "") },
    o.warn ? icon("alert", "sm") : null, h("span", { class: "tt" }, text));
  if (o.action) t.append(btn(o.action, { kind: "ghost", size: "sm", onClick: () => { t.remove(); o.onAction && o.onAction(); } }));
  host.append(t);
  while (host.childElementCount > 3) host.firstChild.remove();
  setTimeout(() => t.remove(), o.ms || (o.action ? 9000 : 5000));
  return t;
}

// ---------------------------------------------------------------- подсказка
let tipEl = null, tipTimer = 0;
function hideTip() { clearTimeout(tipTimer); if (tipEl) { tipEl.remove(); tipEl = null; } }
function showTip(el) {
  const text = el.dataset.tip;
  if (!text || !el.isConnected) return;
  hideTip();
  tipEl = h("div", { class: "tip", role: "tooltip" }, text);
  document.body.append(tipEl);
  const z = zoom();
  const r = el.getBoundingClientRect();
  const vw = innerWidth / z;
  const w = tipEl.offsetWidth, hh = tipEl.offsetHeight;
  let x = (r.left + r.right) / 2 / z - w / 2, y = r.bottom / z + 8;
  if (y + hh > innerHeight / z - 6) y = r.top / z - hh - 8;
  tipEl.style.left = Math.max(6, Math.min(vw - w - 6, x)) + "px";
  tipEl.style.top = y + "px";
}
/** Подсказка своего вида: при наведении (350 мс) и фокусе с клавиатуры. */
export function tip(el, text) {
  el.dataset.tip = text;
  if (!el.getAttribute("aria-label") && !el.textContent.trim()) el.setAttribute("aria-label", text);
  if (el._tip) return el;
  el._tip = true;
  el.addEventListener("mouseenter", () => { clearTimeout(tipTimer); tipTimer = setTimeout(() => showTip(el), 350); });
  el.addEventListener("mouseleave", hideTip);
  el.addEventListener("focus", () => { if (el.matches(":focus-visible")) showTip(el); });
  el.addEventListener("blur", hideTip);
  el.addEventListener("mousedown", hideTip);
  return el;
}

window.appUI = { h, btn, iconBtn, seg, toggle, field, numberField, select, popover, closePop, menu, sheet, ask, toast, tip };
