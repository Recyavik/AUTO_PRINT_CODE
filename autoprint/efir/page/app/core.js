// Связь окна программы с программой: состояние (SSE: канал app — окно, канал lesson — открытый урок),
// команды (POST /app/cmd), вызовы с ответом (POST /app/call), переходы между экранами (#/…).
"use strict";

export const S = {};                 // состояние канала app (последнее)
export const L = { state: null };    // состояние канала lesson (последнее)

const listeners = new Map();         // событие → [fn]
export function on(event, fn) {
  if (!listeners.has(event)) listeners.set(event, []);
  listeners.get(event).push(fn);
  return () => { const a = listeners.get(event); const i = a.indexOf(fn); if (i >= 0) a.splice(i, 1); };
}
export function emit(event, data) {
  for (const fn of [...(listeners.get(event) || [])]) {
    try { fn(data); } catch (e) { console.error(e); }
  }
}

// ---------------------------------------------------------------- каналы
function connect(channel, onState) {
  const es = new EventSource("/events?ch=" + channel);
  es.onmessage = (e) => {
    let s;
    try { s = JSON.parse(e.data); } catch (err) { return; }
    onState(s);
  };
  es.onopen = () => emit("online", channel);
  es.onerror = () => emit("offline", channel);     // EventSource переподключится сам
  return es;
}

let navSeq = -1, noticeSeq = -1, dropSeq = -1, sheetSeq = -1;
export function now() { return Date.now() + (S._offset || 0); }   // часы программы

function onApp(s) {
  for (const k of Object.keys(S)) if (!(k in s)) delete S[k];
  Object.assign(S, s);
  if (s.server_now) S._offset = s.server_now - Date.now();
  window.S = S;
  if (S.nav && S.nav.seq !== navSeq) {
    const first = navSeq === -1;
    navSeq = S.nav.seq;
    // программа просит открыть экран; при первом подключении — только если страница открыта без экрана
    if (S.nav.hash && (!first || !location.hash || location.hash === "#")) go(S.nav.hash);
  }
  if (S.notice && S.notice.seq !== noticeSeq) {
    const first = noticeSeq === -1;
    const fresh = (S.notices || [S.notice]).filter((n) => n.seq > noticeSeq && n.text);
    noticeSeq = S.notice.seq;
    if (!first) fresh.forEach((n) => emit("notice", n));     // каждое новое, а не только последнее
  }
  if (S.drop && S.drop.seq !== dropSeq) {
    const first = dropSeq === -1;
    dropSeq = S.drop.seq;
    if (!first && S.drop.files && S.drop.files.length) emit("drop", S.drop.files);
  }
  if (S.sheet && S.sheet.seq !== sheetSeq) {
    const first = sheetSeq === -1;
    sheetSeq = S.sheet.seq;
    // программа просит открыть лист; при первом подключении — только свежую просьбу (окно только загрузилось)
    if (S.sheet.name && (!first || now() - S.sheet.t < 8000)) setTimeout(() => emit("sheet", { ...S.sheet }), 0);
  }
  emit("app", S);
  if (!window.__ready) { window.__ready = true; emit("ready", S); }
}

function onLesson(s) {
  L.state = s;
  emit("lesson", s);
}

// ---------------------------------------------------------------- команды
const HEADERS = { "Content-Type": "application/json", "X-Suflor": "1" };

export async function send(cmd) {
  try {
    const r = await fetch("/app/cmd", { method: "POST", headers: HEADERS, body: JSON.stringify(cmd) });
    if (!r.ok) throw new Error("HTTP " + r.status);
  } catch (e) {
    emit("offline", "cmd");
    throw e;
  }
}

export async function call(cmd) {
  const r = await fetch("/app/call", { method: "POST", headers: HEADERS, body: JSON.stringify(cmd) });
  let d = null;
  try { d = await r.json(); } catch (e) { /* не JSON */ }
  if (!d || !d.ok) throw new Error((d && d.error) || ("Программа не ответила (HTTP " + r.status + ")"));
  return d.result;
}

// ---------------------------------------------------------------- переходы
export function go(hash) {
  if (location.hash !== hash) location.hash = hash;      // тот же адрес — экран уже открыт, повторять нечего
}

export function route() {
  const h = decodeURIComponent((location.hash || "").replace(/^#\/?/, ""));
  const [path, query] = h.split("?");
  const parts = path.split("/").filter(Boolean);
  const q = {};
  for (const kv of (query || "").split("&").filter(Boolean)) {
    const [k, v] = kv.split("=");
    q[k] = v === undefined ? "" : v;
  }
  return { view: parts[0] || "lessons", id: parts[1] || "", rest: parts.slice(2), query: q, parts };
}
// программа запоминает экран для следующего запуска (адрес — в момент отправки: «Уйти без сохранения?» мог вернуть прежний)
let viewTimer = 0;
function reportView() {
  clearTimeout(viewTimer);
  viewTimer = setTimeout(() => { if (location.hash) send({ cmd: "view", hash: location.hash }).catch(() => {}); }, 400);
}
// последнее место вне настроек — «Назад» в настройках ведёт туда (урок, эфир, уроки)
let outside = "";
export function lastPlace() { return outside; }
function rememberPlace() { if (location.hash && route().view !== "settings") outside = location.hash; }
window.addEventListener("hashchange", () => { rememberPlace(); emit("route", route()); reportView(); });
rememberPlace();
on("ready", reportView);

export function start() {
  connect("app", onApp);
  connect("lesson", onLesson);
}

window.appCore = { S, L, on, send, call, go, route };
