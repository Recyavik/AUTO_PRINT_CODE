// Окно программы: тема и масштаб, переходы между экранами, уведомления. Экраны регистрируются в views.
"use strict";
import { S, on, send, route, start, emit } from "./core.js";
import { toast } from "./ui.js";

export const views = {};            // имя → (root, route) => { update?(S), destroy?(), route?(r) }
let current = null, currentName = "";

const ZOOM_MIN = 80, ZOOM_MAX = 200;

function setVh() {
  const z = parseFloat(document.documentElement.style.zoom) || 1;
  document.documentElement.style.setProperty("--vh", (innerHeight / z / 100).toFixed(3) + "px");
}
addEventListener("resize", setVh);

function applyLook() {
  const html = document.documentElement;
  html.classList.toggle("light", S.dark === false);
  const z = String(Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, S.zoom || 100)) / 100);
  if (html.style.zoom !== z) {
    html.style.zoom = z;
    setVh();
    emit("zoom", parseFloat(z));
  }
}

// ---------------------------------------------------------------- масштаб: Ctrl+колесо, Ctrl+= / − / 0
export function zoomBy(d) {
  const cur = S.zoom || 100;
  const v = d === 0 ? 100 : Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, cur + d));
  if (v === cur && d !== 0) return;
  S.zoom = v;
  applyLook();
  send({ cmd: "prefs", key: "page_zoom", value: v }).catch(() => {});
}
document.addEventListener("keydown", (e) => {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
  if (e.key === "=" || e.key === "+") { e.preventDefault(); zoomBy(10); }
  else if (e.key === "-" || e.key === "_") { e.preventDefault(); zoomBy(-10); }
  else if (e.key === "0") { e.preventDefault(); zoomBy(0); }
}, true);
let wheelAcc = 0;
addEventListener("wheel", (e) => {
  if (!e.ctrlKey) return;
  e.preventDefault();
  wheelAcc += e.deltaY;
  if (Math.abs(wheelAcc) >= 80) { zoomBy(wheelAcc < 0 ? 10 : -10); wheelAcc = 0; }
}, { passive: false });

// ---------------------------------------------------------------- экраны
// имя экрана для страницы (data-view) — по адресу: #/new → wizard
const VIEW_NAMES = { new: "wizard" };

function render() {
  const r = route();
  const key = views[r.view] ? r.view : (views.lessons ? "lessons" : Object.keys(views)[0]);
  const name = VIEW_NAMES[key] || key;
  const root = document.getElementById("view") || document.getElementById("app");
  if (current && currentName === key && current.route) {   // тот же экран — только новое место в нём
    current.route(r);
    document.body.dataset.view = name;
    emit("view", name);
    return;
  }
  if (current && current.destroy) current.destroy();
  root.innerHTML = "";
  currentName = key;
  document.body.dataset.view = "";
  current = key ? views[key](root, r) || {} : {};
  document.body.dataset.view = name;
  if (S.version && current.update) current.update(S);      // данные уже пришли — экран сразу с ними
  emit("view", name);
}

on("route", render);
on("app", () => {
  applyLook();
  if (!currentName) render();                               // первое состояние: render сам передаст его экрану
  else if (current && current.update) current.update(S);
});
on("notice", (n) => {
  const act = n.action;
  toast(n.text, { warn: n.warn, action: act && act.label, onAction: () => send({ cmd: "notice_action", seq: n.seq }) });
});

export function boot() {
  setVh();
  start();
}
