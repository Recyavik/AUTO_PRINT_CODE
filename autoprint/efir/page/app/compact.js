// Маленький режим: то же окно — маленькое и поверх всех; вместо экранов — табло урока или вебинара.
// Раскладки по размеру окна (body[data-size]):
//   tiny  — только «сейчас»: название и время;
//   tall  — табло, «Дальше · …», экран учеников (2 × 2 и «Слайд» во всю ширину) с подписями, «Следующий этап», набор кода;
//   strip — «сейчас» слева, повестка ячейками направо («‹ N» / «N ›»), значки экрана учеников без подписей;
//   side  — «сейчас» слева, список этапов справа.
// Вид можно и выбрать (значок «Вид» вверху справа): окно станет нужного размера — LAYOUTS.
// Время краснеет в последнюю минуту. Нет урока и эфира — «Нет эфира». Тянуть окно — за любое пустое место табло.
"use strict";
import { S, L as LC, on, send, now } from "./core.js";
import { h, btn, iconBtn, menu, clear, zoom, tip } from "./ui.js";
import { icon } from "./icons.js";
import { cmd, mmss, clockAt, durText } from "../lesson/state.js";

const BUSY = ["running", "countdown", "paused", "line_wait"];
let B = null;               // элементы табло
let offset = 0;             // «‹ N» / «N ›»: с какой ячейки повестки показывать (широкий и низкий)

// размеры в пикселях страницы (программа умножит на масштаб окна) — каждый попадает в свою раскладку sizeOf
export const LAYOUTS = [
  { size: "tall", label: "Табло", hint: "узкое и высокое: время, дальше, экран учеников", w: 360, h: 600 },
  { size: "side", label: "Табло и этапы", hint: "время слева, все этапы списком справа", w: 660, h: 440 },
  { size: "strip", label: "Полоса", hint: "низкая во всю ширину: этапы ячейками, значки экрана", w: 980, h: 160 },
  { size: "tiny", label: "Только время", hint: "самое маленькое: название и сколько осталось", w: 300, h: 110 },
];

function layoutMenu(anchor) {
  const cur = document.body.dataset.size;
  menu(anchor, LAYOUTS.map((l) => ({ label: l.label, hint: l.hint, checked: l.size === cur,
    on: () => send({ cmd: "window", op: "compact_size", arg: { w: l.w, h: l.h } }).catch(() => {}) })), { align: "right", cls: "stackmenu" });
}

export function sizeOf(w, hgt) {
  if (hgt < 150 || w < 260) return "tiny";
  if (w >= 640 && w >= 2.6 * hgt && hgt >= 60 && hgt < 230) return "strip";
  if (w >= 560 && hgt >= 230) return "side";
  return "tall";
}

function board() {
  const lv = S.live;
  const segs = (lv && lv.segments) || [];
  if (!segs.length) return { kind: "none", segs: [] };
  const t = now();
  if (t < segs[0].start_ms) return { kind: "before", segs, idx: -1, next: segs[0], left: (segs[0].start_ms - t) / 1000 };
  if (t >= segs[segs.length - 1].end_ms) return { kind: "after", segs, idx: segs.length };
  const i = Math.max(0, segs.findIndex((s) => s.start_ms <= t && t < s.end_ms));
  const c = segs[i];
  return { kind: "live", segs, idx: i, cur: c, next: segs[i + 1] || null, left: (c.end_ms - t) / 1000,
    frac: (t - c.start_ms) / Math.max(1, c.end_ms - c.start_ms) };
}

const mins = (s) => Math.round((s.end_ms - s.start_ms) / 60000);
const set = (el, text) => { if (el.textContent !== text) el.textContent = text; };

// ---------------------------------------------------------------- экран учеников (урок): пять значков с подписями
function efir() { return (LC.state && LC.state.efir) || {}; }

function breakMenu(anchor) {
  const e = efir();
  if (e.mode === "break") {
    menu(anchor, [
      { label: "+5 мин", on: () => cmd({ cmd: "break_adjust", seconds: 300 }) },
      { label: "+1 мин", on: () => cmd({ cmd: "break_adjust", seconds: 60 }) },
      { label: "−1 мин", on: () => cmd({ cmd: "break_adjust", seconds: -60 }) },
      { label: e.break_paused ? "Продолжить отсчёт" : "Пауза отсчёта", on: () => cmd({ cmd: "break_pause" }) },
      { label: "Убрать — снова фон", on: () => cmd({ cmd: "background" }) },
    ]);
    return;
  }
  const b = board();
  const items = [{ head: "Перерыв ученикам" }];
  if (b.kind === "live" && b.cur.kind === "break") items.push({ label: "По плану · " + mins(b.cur) + " мин", hint: "до конца этапа", on: () => cmd({ cmd: "break", minutes: Math.max(1, Math.round(b.left / 60)) }) });
  for (const m of [5, 10, 15, 20]) items.push({ label: m + " мин", on: () => cmd({ cmd: "break", minutes: m }) });
  menu(anchor, items);
}

function exMenu(anchor) {
  const e = efir();
  const list = (LC.state && LC.state.exercises) || [];
  const items = [];
  if (e.mode === "exercise") {
    items.push({ label: e.ex_paused ? "Продолжить" : "Пауза", on: () => cmd({ cmd: "exercise_pause" }) },
      { label: "Сначала", on: () => cmd({ cmd: "exercise_restart" }) },
      { label: "Убрать — снова фон", on: () => cmd({ cmd: "background" }) }, { sep: true });
  }
  if (!list.length) items.push({ label: "Видео зарядок нет", disabled: true });
  list.forEach((title, i) => items.push({ label: title || "Зарядка", checked: e.mode === "exercise" && e.ex_index === i, on: () => cmd({ cmd: "exercise", index: i }) }));
  menu(anchor, items);
}

// «Зарядка» одним щелчком — как в большом режиме: идёт — меню; нет — сразу видео (своё у идущего этапа-зарядки его
// выберет программа, иначе по очереди или случайное); «Спросить» или видео нет — меню. Правая кнопка — меню всегда.
function exClick(anchor) {
  const list = (LC.state && LC.state.exercises) || [];
  const pick = (LC.state && LC.state.prefs && LC.state.prefs.exercise_pick) || "next";
  if (efir().mode === "exercise" || !list.length || pick === "ask" && list.length > 1) { exMenu(anchor); return; }
  cmd({ cmd: "exercise", pick });
}

function screenGrid() {
  const mk = (ic, label, fn, full = label) => {
    const b = h("button", { class: "cs", type: "button", "aria-pressed": "false", "aria-label": full }, icon(ic), h("span", null, label));
    tip(b, full);                                   // в полосе подписи скрыты — подсказка остаётся
    b.addEventListener("click", () => fn(b));
    return b;
  };
  const bg = mk("image", "Фон", () => cmd({ cmd: "background" }));
  const blk = mk("blackout", "Чёрный", () => cmd({ cmd: efir().mode === "black" ? "background" : "black" }), "Чёрный экран");
  const ex = mk("activity", "Зарядка", (b) => exClick(b));
  ex.addEventListener("contextmenu", (e) => { e.preventDefault(); exMenu(ex); });
  const brk = mk("cup", "Перерыв", (b) => breakMenu(b));
  const sl = mk("slide", "Слайд", () => cmd(efir().mode === "slide" ? { cmd: "background" } : { cmd: "slide_step", d: 1 }));
  const el = h("div", { class: "cscr", role: "group", "aria-label": "Экран учеников" }, bg, blk, ex, brk, sl);
  return { el, bg, blk, ex, brk, sl };
}

// ---------------------------------------------------------------- табло
function build() {
  const expand = iconBtn("expand", "Большой режим", () => send({ cmd: "window", op: "compact", arg: false }).catch(() => {}), { size: "sm", kind: "ghost" });
  expand.id = "compactExpand";
  const layout = iconBtn("layers", "Вид маленького режима", () => layoutMenu(layout), { size: "sm", kind: "ghost" });
  layout.id = "compactLayout";
  const label = h("div", { class: "cb-label" });
  const time = h("div", { class: "cb-time mono" });
  const sub = h("span", { class: "cb-sub" });
  const name = h("div", { class: "cb-name" });
  const bar = h("div", { class: "cb-bar" }, h("i"));
  const clock = h("div", { class: "cb-clock mono" });
  const next = h("div", { class: "cb-next" });
  const nowBox = h("div", { class: "cnow" }, label, h("div", { class: "cb-tline" }, time, sub), name, bar, clock, next);
  const agenda = h("div", { class: "cagenda" });
  const scr = screenGrid();
  const nextBtn = btn("Следующий этап", { icon: "skip", size: "sm", cls: "cnext", onClick: () => send({ cmd: "live_next" }).catch(() => {}) });
  const tname = h("span", { class: "ctn" });
  const tact = btn("Пауза", { size: "sm", icon: "pause", onClick: () => cmd({ cmd: "typing", op: tact.dataset.op || "pause" }) });
  const typing = h("div", { class: "ctype", hidden: true }, icon("keyboard", "sm"), tname, tact,
    iconBtn("stop", "Стоп", () => cmd({ cmd: "typing", op: "stop" }), { size: "sm", kind: "ghost" }));
  const root = h("div", { id: "compact", "data-drag": "", "aria-label": "Маленький режим" },
    h("div", { class: "ctop" }, layout, expand), nowBox, agenda, scr.el, nextBtn, typing);
  document.body.append(root);
  B = { root, label, time, sub, name, bar, clock, next, agenda, scr, nextBtn, typing, tname, tact };
}

function renderAgenda(b, size) {
  const box = B.agenda;
  const segs = b.segs;
  const key = size + "|" + JSON.stringify(segs.map((s) => [s.name, s.start_ms, s.end_ms])) + "|" + b.idx + "|" + offset + "|" + innerWidth
    + "|" + zoom();
  if (box.dataset.k === key) return;
  box.dataset.k = key;
  clear(box);
  if (size === "side") {
    segs.forEach((s, i) => box.append(h("div", { class: "ca-row" + (i === b.idx ? " cur" : i < b.idx ? " past" : "") + (s.kind ? " k-" + s.kind : "") },
      h("span", { class: "mono t" }, clockAt(s.start_ms)), h("span", { class: "n" }, s.name || "Этап"), h("span", { class: "mono m" }, String(mins(s))))));
    return;
  }
  if (size !== "strip") return;
  // только целые ячейки — по настоящей ширине полосы (масштаб уже учтён), с местом под «‹ N» и «N ›»
  const CELL = 148, MORE = 64;
  const avail = box.clientWidth || (innerWidth / zoom() - 300);
  let fit = Math.max(1, Math.floor((avail + 8) / CELL));
  if (fit < segs.length) fit = Math.max(1, Math.floor((avail + 8 - 2 * MORE) / CELL));
  const first = Math.max(0, Math.min(segs.length - fit, (b.idx >= 0 ? b.idx : 0) + offset));
  const before = first, after = Math.max(0, segs.length - first - fit);
  if (before) { const p = h("button", { class: "ca-more", type: "button" }, "‹ " + before); p.addEventListener("click", () => { offset -= 1; tick(); }); box.append(p); }
  segs.slice(first, first + fit).forEach((s, k) => {
    const i = first + k;
    box.append(h("div", { class: "ca-cell" + (i === b.idx ? " cur" : i < b.idx ? " past" : "") + (s.kind ? " k-" + s.kind : "") },
      h("span", { class: "mono t" }, clockAt(s.start_ms)), h("b", null, s.name || "Этап"), h("span", { class: "m" }, durText(mins(s)))));
  });
  if (after) { const n = h("button", { class: "ca-more", type: "button" }, after + " ›"); n.addEventListener("click", () => { offset += 1; tick(); }); box.append(n); }
}

function tick() {
  if (!B || !document.body.classList.contains("compact")) return;
  const size = sizeOf(innerWidth / zoom(), innerHeight / zoom());     // в пикселях страницы: 150 % — места меньше
  if (document.body.dataset.size !== size) document.body.dataset.size = size;
  const b = board();
  const lv = S.live || {};
  B.time.classList.toggle("red", b.kind === "live" && b.left <= 60);
  if (b.kind === "none") {
    set(B.label, "Нет эфира"); set(B.time, clockAt(now())); set(B.sub, "сейчас"); set(B.name, ""); set(B.clock, ""); set(B.next, "");
  } else if (b.kind === "before") {
    set(B.label, "До начала"); set(B.time, mmss(b.left)); set(B.sub, ""); set(B.name, lv.title || "");
    set(B.clock, "начало " + clockAt(b.next.start_ms) + " · сейчас " + clockAt(now()));
    set(B.next, "Первым · " + (b.next.name || "Этап") + " · " + durText(mins(b.next)));
  } else if (b.kind === "after") {
    set(B.label, "Эфир завершён"); set(B.time, ""); set(B.sub, ""); set(B.name, lv.title || ""); set(B.clock, "сейчас " + clockAt(now())); set(B.next, "");
  } else {
    set(B.label, "Сейчас · этап " + (b.idx + 1) + " из " + b.segs.length);
    set(B.time, mmss(b.left)); set(B.sub, "осталось"); set(B.name, b.cur.name || "Этап");
    set(B.clock, clockAt(b.cur.start_ms) + "–" + clockAt(b.cur.end_ms) + " · сейчас " + clockAt(now()));
    set(B.next, b.next ? "Дальше · " + clockAt(b.next.start_ms) + " · " + (b.next.name || "Этап") + " · " + durText(mins(b.next)) : "Это последний этап");
  }
  B.bar.hidden = b.kind !== "live";
  B.bar.firstChild.style.width = b.kind === "live" ? (Math.min(1, Math.max(0, b.frac)) * 100).toFixed(1) + "%" : "0";
  B.root.dataset.kind = b.kind;
  renderAgenda(b, size);
  // экран учеников — только у урока на экране урока (вебинар ведут из «Эфира»)
  const mode = efir().mode || "idle";
  for (const [el, m] of [[B.scr.bg, "idle"], [B.scr.blk, "black"], [B.scr.ex, "exercise"], [B.scr.brk, "break"], [B.scr.sl, "slide"]]) el.setAttribute("aria-pressed", String(mode === m));
  B.scr.el.hidden = !(LC.state && LC.state.lesson);
  B.nextBtn.hidden = !(b.kind === "live" && b.next) && b.kind !== "before";
  set(B.nextBtn.querySelector(".bl"), b.kind === "before" ? "Начать сейчас" : "Следующий этап");
  const P = S.print || {};
  const busy = BUSY.includes(P.state);
  B.typing.hidden = !busy;
  if (busy) {
    const bits = [P.state === "paused" ? "Пауза" + (P.pause_why ? " — " + P.pause_why.split(" — ")[0] : "") : P.state === "line_wait" ? "Жду Enter" : P.state === "countdown" ? "Начну через " + (P.countdown || "") : "Набираю"];
    if (P.line) bits.push("строка " + P.line.i + " из " + P.line.n);
    if (P.step && !P.step.done) bits.push("шаг " + P.step.i + " из " + P.step.n);
    set(B.tname, bits.join(" · "));
    const [op, text] = P.state === "paused" ? ["resume", "Продолжить"] : P.state === "line_wait" ? ["next", "Дальше"] : ["pause", "Пауза"];
    B.tact.dataset.op = op;
    set(B.tact.querySelector(".bl"), text);
  }
}

let timer = 0;
function apply() {
  const on_ = !!(S.window && S.window.compact);
  document.body.classList.toggle("compact", on_);
  if (on_ && !B) build();
  if (!B) return;
  if (on_) {
    if (!timer) { timer = setInterval(tick, 1000); offset = 0; }
    tick();
  } else {
    if (timer) { clearInterval(timer); timer = 0; }
    delete document.body.dataset.size;
  }
}

on("app", apply);
on("lesson", () => { if (timer) tick(); });
window.addEventListener("resize", () => { if (timer) tick(); });
