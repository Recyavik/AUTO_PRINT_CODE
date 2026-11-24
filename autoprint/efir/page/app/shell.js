// Оболочка окна: своя шапка (знак, «хлебные крошки», «Аа», поверх всех, маленький режим, свернуть / развернуть /
// закрыть), меню разделов, области перетаскивания окна для программы, клавиши окна, файлы, перетащенные в окно.
"use strict";
import { S, on, send, go, emit } from "./core.js";
import { h, iconBtn, clear, popover, seg, btn, $ } from "./ui.js";
import { icon } from "./icons.js";
import { zoomBy } from "./main.js";

let crumbsEl, extraEl, railEl, viewEl;

export function mountShell(root) {
  crumbsEl = h("nav", { class: "crumbs", id: "crumbs", "aria-label": "Где вы" });
  extraEl = h("div", { class: "tb-extra", id: "tbExtra" });
  const zoomBtn = iconBtn("zoom", "Размер и план", () => zoomPanel(zoomBtn), { kind: "ghost", cls: "tbb" });
  zoomBtn.id = "zoomBtn";
  const pin = iconBtn("pin", "Поверх всех окон", () => send({ cmd: "window", op: "pin" }), { kind: "ghost", cls: "tbb" });
  pin.id = "pinBtn";
  const compact = iconBtn("pip", "Маленький режим", () => send({ cmd: "window", op: "compact" }), { kind: "ghost", cls: "tbb" });
  compact.id = "compactBtn";
  const min = iconBtn("min", "Свернуть", () => send({ cmd: "window", op: "min" }), { kind: "ghost", cls: "wb" });
  min.id = "minBtn";
  const max = iconBtn("max", "Развернуть", () => send({ cmd: "window", op: "toggle_max" }), { kind: "ghost", cls: "wb" });
  max.id = "maxBtn";
  const close = iconBtn("close", "Закрыть", () => send({ cmd: "window", op: "close" }), { kind: "ghost", cls: "wb close" });
  close.id = "closeBtn";
  const logo = h("a", { class: "tb-logo", href: "#/lessons", "aria-label": "Уроки" }, h("img", { src: "/favicon.svg", alt: "" }));
  const bar = h("header", { id: "titlebar", "data-drag": "" }, logo, crumbsEl, h("div", { class: "tb-fill", "data-drag": "" }),
    extraEl, h("div", { class: "tb-tools" }, zoomBtn, pin, compact), h("span", { class: "tb-sep" }), h("div", { class: "tb-win" }, min, max, close));
  bar.addEventListener("dblclick", (e) => { if (!e.target.closest("button, a, input")) send({ cmd: "window", op: "toggle_max" }); });

  const nav = (href, ic, label, extra) => h("a", { class: "nav", href }, icon(ic), h("span", { class: "nl" }, label), extra);
  railEl = h("nav", { id: "rail", "aria-label": "Разделы" },
    nav("#/lessons", "book", "Уроки", h("span", { class: "cnt mono" })),
    nav("#/efir", "radio", "Эфир", h("span", { class: "livemark", hidden: true }, h("span", { class: "dot" }), "идёт")),
    h("span", { class: "spacer" }),
    btn("", { kind: "primary", block: true, cls: "upd", onClick: () => send({ cmd: "update_open" }) }),
    nav("#/settings", "sliders", "Настройки"));
  railEl.querySelector(".upd").id = "updateBtn";
  viewEl = h("main", { id: "view" });
  root.append(h("div", { id: "shell" }, bar, h("div", { id: "frame" }, railEl, viewEl)));

  on("app", update);
  on("view", (name) => { markRail(name); queueRegions(); });
  on("zoom", queueRegions);
  addEventListener("resize", queueRegions);
  setInterval(() => sendRegions(false), 2000);
  update();
  return viewEl;
}

export function viewRoot() { return viewEl; }

/** «Хлебные крошки» в шапке: [{label, href}] — последняя без ссылки. extra — свои кнопки экрана (меню урока). */
export function setCrumbs(items, extra = null) {
  clear(crumbsEl);
  items.forEach((it, i) => {
    if (i) crumbsEl.append(h("span", { class: "sep", "aria-hidden": "true" }, "/"));
    crumbsEl.append(it.href && i < items.length - 1 ? h("a", { href: it.href }, it.label) : h("b", { class: "cur" }, it.label));
  });
  clear(extraEl);
  if (extra) extraEl.append(extra);
  queueRegions();
}

function markRail(name) {
  for (const a of railEl.querySelectorAll("a.nav")) {
    const on_ = a.getAttribute("href") === "#/" + name || (name === "wizard" && a.getAttribute("href") === "#/lessons");
    a.classList.toggle("on", on_);
    if (on_) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
}

function update() {
  if (!railEl || !S.lessons) return;
  const n = S.lessons.filter((x) => x.kind !== "plan").length;
  railEl.querySelector('a[href="#/lessons"] .cnt').textContent = String(n);
  railEl.querySelector(".livemark").hidden = !(S.live && !S.live.lesson_id);
  const u = railEl.querySelector("#updateBtn");
  u.hidden = !S.update;
  if (S.update) u.querySelector(".bl") ? (u.querySelector(".bl").textContent = S.update.text) : u.append(h("span", { class: "bl" }, S.update.text));
  const w = S.window || {};
  $("#pinBtn").setAttribute("aria-pressed", String(!!w.pinned));
  const max = $("#maxBtn");
  const want = w.maximized ? "restore" : "max";
  if (max.dataset.ic !== want) {
    max.dataset.ic = want;
    max.replaceChildren(icon(want));
    max.setAttribute("aria-label", w.maximized ? "Восстановить" : "Развернуть");
    max.dataset.tip = w.maximized ? "Восстановить" : "Развернуть";
  }
  document.body.classList.toggle("compact", !!w.compact);
}

// ---------------------------------------------------------------- «Аа»: масштаб и где план урока
function zoomPanel(anchor) {
  const val = h("b", { class: "zval mono" }, (S.zoom || 100) + " %");
  const upd = () => { val.textContent = (S.zoom || 100) + " %"; };
  const box = h("div", { class: "zoompanel" },
    h("div", { class: "phead" }, "Размер"),
    h("div", { class: "zrow" },
      iconBtn("minus", "Мельче (Ctrl −)", () => { zoomBy(-10); upd(); }, { size: "sm" }), val,
      iconBtn("plus", "Крупнее (Ctrl +)", () => { zoomBy(10); upd(); }, { size: "sm" }),
      btn("Обычный", { kind: "ghost", size: "sm", onClick: () => { zoomBy(0); upd(); } })),
    h("div", { class: "phead" }, "План урока"),
    seg([{ value: "side", icon: "side", label: "Сбоку" }, { value: "top", icon: "top", label: "Сверху" },
      { value: "hidden", icon: "hidden", label: "Скрыть" }], (S.prefs || {}).page_plan || "side",
    (v) => send({ cmd: "prefs", key: "page_plan", value: v }), { cls: "planpos" }),
    h("p", { class: "meta" }, "Ещё: Ctrl + колесо мыши, Ctrl+= и Ctrl+− (Ctrl+0 — обычный)."));
  popover(anchor, box, { align: "right", focus: false });
}

// ---------------------------------------------------------------- области окна (где тянуть)
let regionsQueued = false, lastRegions = "";
function queueRegions() {
  if (regionsQueued) return;
  regionsQueued = true;
  requestAnimationFrame(() => requestAnimationFrame(() => { regionsQueued = false; sendRegions(true); }));
}

const INTERACTIVE = "button, a, input, select, textarea, [contenteditable], [data-nodrag], .seg, label";

function rectOf(el) {
  const r = el.getBoundingClientRect();
  return [Math.round(r.left * 10) / 10, Math.round(r.top * 10) / 10, Math.round(r.width * 10) / 10, Math.round(r.height * 10) / 10];
}

/** Ручки — [data-drag] (шапка, табло маленького режима); дырки — кнопки и поля внутри них. Масштаб — во сколько
 * раз пиксель прямоугольника больше пикселя окна (в разных Chromium getBoundingClientRect с CSS zoom считает по-разному). */
export function sendRegions(force) {
  const drag = [], holes = [];
  for (const d of document.querySelectorAll("[data-drag]")) {
    if (!d.offsetParent && d.id !== "titlebar") continue;
    if (d.parentElement && d.parentElement.closest("[data-drag]")) continue;   // вложенная ручка — внутри внешней
    drag.push(rectOf(d));
    for (const x of d.querySelectorAll(INTERACTIVE)) {
      if (x.offsetParent === null) continue;
      const outer = x.parentElement && x.parentElement.closest(INTERACTIVE);
      if (outer && d.contains(outer)) continue;                   // внутри другой кнопки или поля — уже дырка
      holes.push(rectOf(x));
    }
  }
  const html = document.documentElement.getBoundingClientRect();
  const k = html.width > 0 ? innerWidth / html.width : 1;
  const zoom = Math.abs(k - 1) < 0.02 ? 1 : Math.round(k * 1000) / 1000;
  const data = { drag, holes, zoom };
  const key = JSON.stringify(data);
  if (!force && key === lastRegions) return;
  lastRegions = key;
  send({ cmd: "window", op: "regions", ...data }).catch(() => {});
}

// ---------------------------------------------------------------- клавиши окна
document.addEventListener("keydown", (e) => {
  if (e.defaultPrevented) return;
  const ctrl = e.ctrlKey || e.metaKey;
  const k = (e.key || "").toLowerCase();
  if (ctrl && !e.altKey && !e.shiftKey && (k === "n" || e.code === "KeyN" || k === "т")) { e.preventDefault(); go("#/new"); }
  else if (ctrl && !e.altKey && !e.shiftKey && (k === "o" || e.code === "KeyO" || k === "щ")) { e.preventDefault(); emit("shortcut", "open"); }
  else if (ctrl && !e.altKey && (k === "," || e.code === "Comma" || k === "б")) { e.preventDefault(); go("#/settings"); }
  else if (ctrl && !e.altKey && (k === "q" || e.code === "KeyQ" || k === "й")) { e.preventDefault(); send({ cmd: "quit" }); }
  else if (e.key === "F1") { e.preventDefault(); go("#/settings/about"); }
});

// ---------------------------------------------------------------- файлы, перетащенные в окно
const dropHandlers = {};
/** Обработчик файлов для экрана: fn(files) → true, если взял. Иначе — экран «Уроки» (импорт). */
export function registerDrop(view, fn) { dropHandlers[view] = fn; }
on("drop", (files) => {
  const view = document.body.dataset.view || "lessons";
  window.__lastDrop = { view, files };
  const fn = dropHandlers[view] || dropHandlers.lessons;
  if (fn) fn(files);
});
