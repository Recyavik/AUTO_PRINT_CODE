// Общее состояние экрана урока и мелкие помощники (DOM, время, команды программе).
"use strict";

export const A = {
  S: null,              // последнее состояние от программы (урок — с наложенными неотправленными правками)
  offset: 0,            // часы программы − часы страницы, мс
  mode: "prep",         // prep — «Подготовка», lesson — «Урок»
  lessonId: null,
  items: [],            // блоки урока по порядку (после наложения правок)
  byId: new Map(),      // id → блок
  editing: null,        // id блока, который сейчас правят (его узел не перерисовывается)
  holding: new Set(),   // правку закончили, ждём HTML от программы — узел пока не трогать (код)
  fresh: new Map(),     // id → блок из ответа на правку (новее, чем последнее состояние)
  selected: null,       // выделенный блок (Delete, Ctrl+V — после него)
  hovered: null,        // блок под мышью (куда вставить картинку)
  undo: [],             // обратные действия для Ctrl+Z (структура урока)
  curIdx: -2,
  userOpen: {},
  slideBid: "",         // какой слайд у учеников — сменился: лента показывает его («я здесь»)
  renders: 0,           // сколько узлов блоков создано заново (тест: ввод не перерисовывает ленту)
};
window.__renders = () => A.renders;

export const $ = (id) => document.getElementById(id);

export function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}

export function now() { return Date.now() + A.offset; }

export function mmss(sec) {
  sec = Math.max(0, Math.ceil(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? h + ":" + String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0") : m + ":" + String(s).padStart(2, "0");
}
export function hm(min) { min = Math.round(min); return Math.floor(min / 60) + ":" + String(min % 60).padStart(2, "0"); }
export function hhmm(ms) { const d = new Date(ms); return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0"); }
export function clockAt(ms) { const d = new Date(ms); return d.getHours() + ":" + String(d.getMinutes()).padStart(2, "0"); }
export function nextHalfHour() {
  const d = new Date(now()); d.setSeconds(0, 0); d.setMinutes(d.getMinutes() + 30 - d.getMinutes() % 30); return hhmm(d.getTime());
}
export function durText(min) {
  min = Math.max(0, Math.round(min));
  const h = Math.floor(min / 60), m = min % 60;
  return h && m ? `${h} ч ${m} мин` : h ? `${h} ч` : `${m} мин`;
}
export function plural(n, one, few, many) {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  return b === 1 ? one : b >= 2 && b <= 4 ? few : many;
}

export function newId() {
  const a = new Uint8Array(6);
  crypto.getRandomValues(a);
  return Array.from(a, (x) => x.toString(16).padStart(2, "0")).join("");
}

// команды, которые открывают окно программы: оно может оказаться под экраном урока — сказать, где его искать
const OPENS_WINDOW = new Set(["export", "look_edit", "look_new", "fill_slides", "settings"]);   // export — и .autoprint

export async function cmd(data) {
  if (OPENS_WINDOW.has(data && data.cmd)) toast("Открываю окно AutoPrintCode — если его не видно, оно на панели задач");
  try {
    await fetch("/lesson/cmd", { method: "POST", headers: { "Content-Type": "application/json", "X-Suflor": "1" },
      body: JSON.stringify(data) });
  } catch (e) {                                // действие не дошло — сказать, а не молчать
    toast("Нет связи с AutoPrintCode — действие не выполнено. Повторите через пару секунд.");
  }
}

export function isTyping(t) {
  t = t || document.activeElement;
  return !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable || !!t.closest?.(".cm-editor"));
}

// всплывающее сообщение внизу (с кнопкой действия)
let toastTimer = 0;
export function toast(text, action, onAction, ms = 6000) {
  const t = $("toast");
  t.innerHTML = "";
  t.appendChild(el("span", "", text));
  if (action) {
    const b = el("button", "ghost", action);
    b.onclick = () => { t.hidden = true; onAction(); };
    t.appendChild(b);
  }
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, ms);
}

// всплывающее меню у элемента: items — [{label, on, checked, danger, sep, sub:[…], disabled}]
let openMenu = null;
export function closeMenu() { if (openMenu) { openMenu.remove(); openMenu = null; } }
export function menu(anchor, items, opts = {}) {
  closeMenu();
  const m = el("div", "menu" + (opts.cls ? " " + opts.cls : ""));
  m.setAttribute("role", "menu");
  const build = (box, list) => {
    for (const it of list) {
      if (it.sep) { box.appendChild(el("div", "msep")); continue; }
      if (it.head) { box.appendChild(el("div", "mhead", it.head)); continue; }
      if (it.node) { box.appendChild(it.node); continue; }
      const b = el("button", "mi" + (it.danger ? " danger" : "") + (it.checked ? " on" : ""));
      b.setAttribute("role", "menuitem");
      if (it.dot) { const d = el("span", "mdot"); d.style.setProperty("--rc", it.dot); b.appendChild(d); }
      b.appendChild(el("span", "ml", it.label));
      if (it.hint) b.appendChild(el("span", "mh", it.hint));
      if (it.disabled) b.disabled = true;
      b.onclick = (e) => { e.stopPropagation(); if (it.keep) { it.on(b); return; } closeMenu(); it.on && it.on(); };
      box.appendChild(b);
    }
  };
  build(m, items);
  document.body.appendChild(m);
  // «Размер текста» — zoom на <html>: координаты на экране делим на него, иначе меню уезжает и обрезается
  const z = parseFloat(document.documentElement.style.zoom) || 1;
  const vw = innerWidth / z, vh = innerHeight / z;
  m.style.maxHeight = Math.max(120, vh - 16) + "px";
  m.style.maxWidth = Math.min(420, vw - 16) + "px";
  const rr = anchor.getBoundingClientRect();
  const r = { left: rr.left / z, right: rr.right / z, top: rr.top / z, bottom: rr.bottom / z };
  const w = m.offsetWidth, h = m.offsetHeight;
  let x = opts.right ? r.right - w : r.left, y = r.bottom + 4;
  if (x + w > vw - 8) x = vw - w - 8;
  if (y + h > vh - 8) {                       // не влезает под кнопку — над ней, иначе у нижнего края окна
    y = r.top - h - 4 >= 8 ? r.top - h - 4 : Math.max(8, vh - h - 8);
  }
  m.style.left = Math.max(8, x) + "px";
  m.style.top = y + "px";
  openMenu = m;
  const first = m.querySelector("input, button");
  if (opts.focus !== false && first) first.focus({ preventScroll: true });
  return m;
}
document.addEventListener("mousedown", (e) => { if (openMenu && !openMenu.contains(e.target)) closeMenu(); }, true);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && openMenu) { closeMenu(); e.stopPropagation(); } }, true);

// ICONS (stroke 2, 24×24): роли, код, картинка, этапы, действия
export const ICONS = {
  say: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  term: '<path d="M4 19.5V5a2 2 0 0 1 2-2h13v16H6.5a2.5 2.5 0 0 0 0 5H19"/><path d="M9 8h6M9 11h4"/>',
  tell: '<path d="M4 5h16v11H10l-6 4z"/><path d="M8 9h8M8 12h5"/>',
  ask: '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.4 2.4c-.6.3-1 .8-1 1.5v.4"/><path d="M12 17.2v.1"/>',
  do: '<path d="M5 3l13 7-5.5 1.8L10.5 18z"/>',
  show: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  output: '<path d="M4 6l5 5-5 5"/><path d="M12 18h8"/>',
  important: '<path d="M12 3.5l9 16H3z"/><path d="M12 10v4.5M12 17.2v.1"/>',
  trap: '<path d="M9 7.13v-1a3 3 0 1 1 6 0v1"/><path d="M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6"/><path d="M12 20v-9M6 13H2M22 13h-4"/>',
  extra: '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
  task: '<path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><path d="M14 2v6h6M16 13H8M16 17H8"/>',
  text: '<path d="M17 6H3M21 12H3M15 18H3"/>',
  explain: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>',
  hint: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/><path d="m5.6 5.6 3.6 3.6M14.8 14.8l3.6 3.6M18.4 5.6l-3.6 3.6M9.2 14.8l-3.6 3.6"/>',
  homework: '<path d="M3 11 12 4l9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-5h4v5"/>',
  goal: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/>',
  code: '<path d="M8 8l-4 4 4 4M16 8l4 4-4 4M13.5 5l-3 14"/>',
  image: '<rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
  stage: '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2 2M10 2h4"/>',
  break: '<path d="M10 2v2M14 2v2M6 2v2"/><path d="M16 8a1 1 0 0 1 1 1v8a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V9a1 1 0 0 1 1-1h14a4 4 0 1 1 0 8h-1"/>',
  exercise: '<path d="m16 13 5.2 3.5a.5.5 0 0 0 .8-.4V7.9a.5.5 0 0 0-.8-.4L16 10.5"/><rect x="2" y="6" width="14" height="12" rx="2"/>',
  more: '<circle cx="5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="19" cy="12" r="1.3"/>',
  grip: '<circle cx="9" cy="6" r="1.2"/><circle cx="15" cy="6" r="1.2"/><circle cx="9" cy="12" r="1.2"/><circle cx="15" cy="12" r="1.2"/><circle cx="9" cy="18" r="1.2"/><circle cx="15" cy="18" r="1.2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  play: '<path d="M7 4v16l13-8z"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
};

export function icon(name, label) {
  const s = el("span", "ic");
  const t = label ? "<title>" + label.replace(/[<&>]/g, "") + "</title>" : "";
  s.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="' + (label ? "false" : "true") + '">' + t + (ICONS[name] || ICONS.text) + "</svg>";
  return s;
}

export function roleName(key) {
  const r = (A.S && A.S.roles || []).find((x) => x.key === key);
  return r ? r.name : ({ code: "Код", image: "Картинка" }[key] || "Заметка");
}
