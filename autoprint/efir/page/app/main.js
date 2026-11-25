// Окно программы: тема и масштаб, переходы между экранами, уведомления. Экраны регистрируются в views.
"use strict";
import { S, on, send, route, start, emit } from "./core.js";
import { toast } from "./ui.js";

export const views = {};            // имя → (root, route) => { update?(S), destroy?(), route?(r) }
let current = null, currentName = "";

const ZOOM_MIN = 80, ZOOM_MAX = 200;
// «Масштаб под размер окна»: ширина окна / AUTO_BASE (шагом 10 %, 90…150 %); в маленьком режиме — обычный
const AUTO_BASE = 1500, AUTO_MIN = 90, AUTO_MAX = 150;
let pendingZoom = null, pendingUntil = 0;       // свой шаг масштаба, пока программа его не подтвердила

function setVh() {
  const z = parseFloat(document.documentElement.style.zoom) || 1;
  document.documentElement.style.setProperty("--vh", (innerHeight / z / 100).toFixed(3) + "px");
}
addEventListener("resize", setVh);

export function autoZoomOn() {
  return !!(S.prefs && S.prefs.page_zoom_auto) && !(S.window && S.window.compact);
}
function autoZoom() {
  return Math.max(AUTO_MIN, Math.min(AUTO_MAX, Math.round(innerWidth / AUTO_BASE * 10) * 10));
}
/** Масштаб сейчас: под окно (авто) или свой; свой шаг держится, пока программа не ответила тем же (без отката). */
export function zoomNow() {
  if (autoZoomOn()) return autoZoom();
  return Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, pendingZoom !== null ? pendingZoom : (S.zoom || 100)));
}
// состояние от программы: её масштаб совпал со своим шагом (или ждали слишком долго) — шаг подтверждён
function confirmZoom() {
  if (pendingZoom !== null && (S.zoom === pendingZoom || Date.now() > pendingUntil)) pendingZoom = null;
}

function applyLook() {
  const html = document.documentElement;
  html.classList.toggle("light", S.dark === false);
  const z = String(zoomNow() / 100);
  if (html.style.zoom !== z) {
    emit("beforezoom");                          // экран урока запоминает место в тексте
    html.style.zoom = z;
    setVh();
    emit("zoom", parseFloat(z));
  }
}
// окно растягивают: авто-масштаб — когда отпустили (не на каждый кадр: перестройка урока не бесплатна)
let autoTimer = 0;
addEventListener("resize", () => {
  if (!autoZoomOn()) return;
  clearTimeout(autoTimer);
  autoTimer = setTimeout(applyLook, 200);
});

// ---------------------------------------------------------------- масштаб: Ctrl+колесо, Ctrl+= / − / 0
// шаги подряд (колесо, Ctrl+=) — одна перестройка за кадр и одна запись в программу, когда перестали
let zoomFrame = 0, zoomSend = 0, zoomExpire = 0;
export function zoomBy(d) {
  const cur = zoomNow();
  if (autoZoomOn()) {                            // руками — значит, снова вручную
    S.prefs = Object.assign({}, S.prefs, { page_zoom_auto: false });
    send({ cmd: "prefs", key: "page_zoom_auto", value: false }).catch(() => {});
  }
  const v = d === 0 ? 100 : Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, cur + d));
  if (v === cur && d !== 0) return;
  pendingZoom = v;
  pendingUntil = Date.now() + 3000;
  if (!zoomFrame) zoomFrame = requestAnimationFrame(() => { zoomFrame = 0; applyLook(); });
  clearTimeout(zoomSend);
  zoomSend = setTimeout(() => {
    pendingUntil = Date.now() + 3000;              // ждать ответа программы — от отправки
    send({ cmd: "prefs", key: "page_zoom", value: pendingZoom !== null ? pendingZoom : v }).catch(() => {});
    // программа так и не ответила тем же (масштаб поменяли и там) — её значение
    clearTimeout(zoomExpire);
    zoomExpire = setTimeout(() => { confirmZoom(); applyLook(); }, 3100);
  }, 250);
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
  // экран с несохранённой правкой сам спрашивает и вернёт адрес («Эфир»: правка расписания и оформления)
  if (current && current.canLeave && current.canLeave(r) === false) return;
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
  confirmZoom();
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
