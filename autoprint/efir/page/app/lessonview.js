// Урок в окне программы: эфирная полоса (состояние урока, время, экран учеников, начать / завершить), план —
// сбоку, лентой сверху или скрыт, текст урока (модули суфлёра: render / edit / queue / code), «Дальше».
// Подготовка и урок — один экран: правка включается переключателем «Правка» (по умолчанию — пока урок не идёт).
"use strict";
import { S, L as LC, on, send } from "./core.js";
import { h, btn, iconBtn, seg, popover, menu, ask, toast, clear, closePop } from "./ui.js";
import { icon } from "./icons.js";
import { setCrumbs } from "./shell.js";
import { lessonMenuItems } from "./lessonmenu.js";
import { slidesFill } from "./sheets.js";
import { A, cmd, now, mmss, hm, hhmm, clockAt, nextHalfHour, durText, plural } from "../lesson/state.js";
import * as Q from "../lesson/queue.js";
import { renderMain, renderPlan, stagesOf, nodeOf, stageOfBlock, markOnScreen } from "../lesson/render.js";
import * as E from "../lesson/edit.js";
import { released } from "../lesson/code.js";

export const hooks = { strip: [], tick: [], apply: [], mount: [] };   // экран учеников, набор, правка — свои части

let V = null;                       // смонтированный экран (элементы) или null

// ---------------------------------------------------------------- время урока
function phaseOf(s, elapsed) {
  if (elapsed === null) return "";
  if (s.end <= s.start) return elapsed >= s.start ? "past" : "future";
  if (elapsed >= s.end) return "past";
  if (elapsed >= s.start) return "current";
  return "future";
}

export function computeCurrent() {
  const stages = stagesOf(A.items);
  if (!stages.length || !A.S || !A.S.live) return { elapsed: null, cur: -1, next: -1, stages };
  const elapsed = (now() - A.S.live.anchor) / 60000;
  let cur = -1, next = -1;
  for (const s of stages) {
    const ph = phaseOf(s, elapsed);
    if (ph === "current") cur = s.i;
    else if (ph === "future" && next < 0 && s.end > s.start) next = s.i;
  }
  return { elapsed, cur, next, stages };
}

function lessonBase() {
  const L = A.S && A.S.lesson;
  if (A.S && A.S.live) return A.S.live.anchor;
  const m = L && /^(\d{1,2}):(\d{2})$/.exec(L.start || "");
  if (!m) return null;
  const d = new Date(now());
  d.setHours(+m[1], +m[2], 0, 0);
  return d.getTime();
}

function stageClock(s, base) {
  if (base !== null) {
    return { from: clockAt(base + s.start * 60000), text: clockAt(base + s.start * 60000) + "–" + clockAt(base + s.end * 60000),
      title: "С " + hm(s.start) + " до " + hm(s.end) + " от начала урока" };
  }
  return { from: hm(s.start), text: hm(s.start) + "–" + hm(s.end),
    title: "От начала урока: " + (s.start ? "с " + s.start + "-й" : "с начала") + " по " + s.end + "-ю минуту" };
}

// ---------------------------------------------------------------- состояние урока → лента
function rebuildItems() {
  const L = A.S && A.S.lesson;
  if (!L) { A.items = []; A.byId = new Map(); A.title = ""; return; }
  const lesson = { title: L.title };
  let items = L.items.slice();
  for (const [id, fr] of [...A.fresh]) {
    const i = items.findIndex((x) => x.id === id);
    if (i >= 0) {
      if (items[i].v === fr.v) A.fresh.delete(id);
      else items[i] = fr;
    }
  }
  items = Q.applyOps(items, Q.overlay(A.S.edits || 0), lesson);
  items = items.map((it) => (it.local && A.fresh.has(it.id) ? A.fresh.get(it.id) : it));
  A.items = items;
  A.byId = new Map(items.map((x) => [x.id, x]));
  A.title = lesson.title;
}

export function setMode(m) {
  if (A.mode === m && document.body.classList.contains("mode-" + m)) return;
  if (m === "lesson") E.finishEditing();
  A.mode = m;
  document.body.classList.toggle("mode-prep", m === "prep");
  document.body.classList.toggle("mode-lesson", m === "lesson");
  document.body.classList.toggle("editing", m === "prep");
  A.curIdx = -2;
  A.userOpen = {};
  if (V) refresh();
  for (const f of hooks.strip) f();
}

function prefs() { return (A.S && A.S.prefs) || (S.prefs || {}); }
function planPos() {
  const p = (S.prefs && S.prefs.page_plan) || "side";
  return p === "strip" ? "top" : (["side", "top", "hidden"].includes(p) ? p : "side");
}

export function refresh() {
  if (!V) return;
  rebuildItems();
  renderMain();
  markOnScreen();
  renderPlan();
  renderRibbon();
  applyCollapse();
  tick();
  const L = A.S && A.S.lesson;
  const t = (L && L.title) || "Урок";
  document.title = t + " — AutoPrintCode";
  setCrumbs([{ label: "Уроки", href: "#/lessons" }, { label: t }], V.menuBtn);
}

// ---------------------------------------------------------------- план лентой сверху
function renderRibbon() {
  const stages = stagesOf(A.items);
  const key = JSON.stringify(stages.map((s) => [s.id, s.minutes, s.item.title, s.item.kind]));
  const rb = V.ribbon, ln = V.line;
  if (rb.dataset.k !== key) {
    rb.dataset.k = key;
    clear(rb);
    clear(ln);
    for (const s of stages) {
      const kind = s.item.kind === "break" ? " brk" : s.item.kind === "exercise" ? " ex" : "";
      const b = h("button", { class: "tseg" + kind, type: "button", "data-id": s.id, style: { flexGrow: String(Math.max(1, s.minutes)) },
        title: (s.item.title || "Этап") + " · " + durText(s.minutes) },
      h("span", { class: "tt mono" }), h("span", { class: "tsn" }, s.item.title || "Этап"), h("span", { class: "fill" }));
      b.addEventListener("click", () => goStage(s.id));
      rb.append(b);
      ln.append(h("i", { style: { flexGrow: String(Math.max(1, s.minutes)) } }));
    }
  }
  rb.hidden = ln.hidden = !stages.length;
}

// ---------------------------------------------------------------- свернуть этапы
function applyCollapse() {
  const { elapsed, stages } = computeCurrent();
  const pastCollapse = prefs().page_past === "collapse";
  for (const s of stages) {
    const st = document.getElementById("st-" + s.id);
    if (!st) continue;
    let open = true;
    if (A.mode === "lesson") {
      if (s.id in A.userOpen) open = A.userOpen[s.id];
      else if (pastCollapse && elapsed !== null && phaseOf(s, elapsed) === "past") open = false;
    }
    st.classList.toggle("collapsed", !open);
  }
}

export function goStage(id) {
  const st = document.getElementById("st-" + id);
  if (!st) return;
  A.userOpen[id] = true;
  applyCollapse();
  st.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ---------------------------------------------------------------- эфирная полоса
function shiftWithUndo(c) {
  const prev = A.S && A.S.live && A.S.live.anchor;
  cmd(c);
  if (prev) toast("Время этапов сдвинуто на сейчас", { action: "Вернуть", onAction: () => cmd({ cmd: "restore_anchor", ms: prev }), ms: 10000 });
}

async function mayReplace() {
  const other = A.S && A.S.other_live;
  if (!other) return true;
  return ask("Сейчас идёт эфир «" + other + "». Завершить его и начать урок?", { title: "Идёт эфир", ok: "Завершить и начать" });
}

async function startNow() {
  if (!(await mayReplace())) return;
  cmd({ cmd: "start", force: !!(A.S && A.S.other_live) });
}

function startAtPanel(anchor) {
  const L = A.S && A.S.lesson;
  const tm = h("input", { class: "inp mono", type: "time", "aria-label": "Время начала" });
  tm.value = (L && L.start) || nextHalfHour();
  const go = btn("Начать", { kind: "primary", onClick: async () => {
    if (!tm.value) return;
    closePop();
    if (!(await mayReplace())) return;
    cmd({ cmd: "start", at: tm.value, force: !!(A.S && A.S.other_live) });
  } });
  tm.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go.click(); } });
  popover(anchor, h("div", { class: "startpanel" }, h("div", { class: "phead" }, "Начать урок в"),
    h("div", { class: "zrow" }, tm, go), h("p", { class: "meta" }, "До начала таймер считает «до начала». Время из прошлого (в пределах 6 часов) — урок уже идёт.")));
  tm.focus();
}

async function endLesson() {
  const { elapsed } = computeCurrent();
  const waiting = elapsed !== null && elapsed < 0;
  const ok = await ask(waiting ? "Отменить назначенное начало урока?" : "Завершить урок? Экран учеников вернётся к фону.",
    { title: waiting ? "Отменить начало" : "Завершить урок", ok: waiting ? "Отменить начало" : "Завершить", danger: true });
  if (ok) cmd({ cmd: "stop" });
}

function statusPanel(anchor) {
  if (!(A.S && A.S.live)) return;
  const tm = h("input", { class: "inp mono", type: "time", "aria-label": "Начало урока" });
  tm.value = hhmm(A.S.live.anchor);
  const was = tm.value;
  let sent = false;
  const commit = () => { if (!sent && tm.value && tm.value !== was) { sent = true; cmd({ cmd: "set_start", start: tm.value }); } };
  tm.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); commit(); closePop(); } else if (e.key === "Escape") { tm.value = was; }
  });
  tm.addEventListener("blur", commit);
  const { next, elapsed } = computeCurrent();
  const waiting = elapsed !== null && elapsed < 0;
  const items = [
    { node: h("div", { class: "zrow" }, h("span", { class: "dim" }, "Начало"), tm) },
    waiting ? { label: "Начать урок сейчас", hint: "не ждать назначенного времени", on: () => shiftWithUndo({ cmd: "shift_now" }) }
      : { label: "Начать этот этап сейчас", hint: "текущий этап — с этой минуты", on: () => shiftWithUndo({ cmd: "shift_now" }) },
    !waiting && next >= 0 ? { label: "Следующий этап — сейчас", hint: "закончили раньше — дальше по плану",
      on: () => shiftWithUndo({ cmd: "start_at", index: next }) } : null,
    { sep: true },
    { label: waiting ? "Отменить начало…" : "Завершить урок…", danger: true, on: endLesson },
  ].filter(Boolean);
  const box = h("div", { class: "menu", role: "menu" });
  for (const it of items) {
    if (it.sep) { box.append(h("div", { class: "psep" })); continue; }
    if (it.node) { box.append(it.node); continue; }
    const b = h("button", { class: "mi" + (it.danger ? " danger" : ""), type: "button", role: "menuitem" },
      h("span", { class: "ml" }, it.label), it.hint ? h("span", { class: "mh" }, it.hint) : null);
    b.addEventListener("click", () => { closePop(); it.on(); });
    box.append(b);
  }
  popover(anchor, h("div", { class: "statuspanel" }, h("div", { class: "phead" }, "Идёт урок"), box), { focus: false });
}

function buildStrip() {
  const tally = h("span", { class: "tally", "aria-hidden": "true" });
  const big = h("span", { class: "big mono" });
  const l1 = h("span", { class: "l1" });
  const l2 = h("span", { class: "l2" });
  const status = h("button", { id: "lessonStatus", class: "status", type: "button" }, tally, big, h("span", { class: "stext" }, l1, l2));
  status.addEventListener("click", () => statusPanel(status));
  const startAt = h("button", { id: "startAt", class: "startat", type: "button", "aria-label": "Начать урок в назначенное время" });
  startAt.addEventListener("click", () => startAtPanel(startAt));
  const meta = h("span", { class: "meta smeta" });
  const nowBtn = btn("Начать сейчас", { kind: "primary", onClick: () => shiftWithUndo({ cmd: "shift_now" }) });
  nowBtn.id = "nowBtn";
  const minutesBtn = btn("Поставьте этапам минуты", { kind: "", onClick: () => {
    setMode("prep");
    requestAnimationFrame(() => {               // план сбоку — поле минут в плане; иначе — минуты в заголовке этапа
      const f = document.body.classList.contains("plan-side") ? document.querySelector("#plan input.pmin") : null;
      if (f) { f.focus(); f.select(); return; }
      const m = document.querySelector("#main .sh .mins:not(.fixed)");
      const it = m && A.byId.get(m.closest(".stage").id.slice(3));
      if (it) E.editStageMinutes(m, it);
    });
  } });
  minutesBtn.id = "minutesBtn";
  const clockNow = h("span", { class: "clock", id: "clockNow" }, h("span", null, "сейчас"), h("b", { class: "mono" }));
  const clockEnd = h("span", { class: "clock", id: "clockEnd" }, h("span", null, "конец"), h("b", { class: "mono" }));
  const screen = h("div", { id: "screen", class: "screenctl" });
  const planPosSeg = seg([{ value: "side", icon: "side", label: "План сбоку" }, { value: "top", icon: "top", label: "План сверху" },
    { value: "hidden", icon: "hidden", label: "Скрыть план" }], planPos(), (v) => {
    S.prefs = Object.assign({}, S.prefs, { page_plan: v });
    applyPlanPos();
    send({ cmd: "prefs", key: "page_plan", value: v });
  }, { icons: true, size: "sm", label: "Где план урока" });
  planPosSeg.id = "planPos";
  const tools = h("div", { class: "stools", id: "stripTools" }, planPosSeg);
  const startBtn = btn("Начать урок", { kind: "primary", icon: "play", onClick: startNow });
  startBtn.id = "startBtn";
  const endBtn = btn("Завершить", { kind: "stop", icon: "stop", onClick: endLesson });
  endBtn.id = "endBtn";
  const strip = h("section", { id: "onair", "aria-label": "Урок и экран учеников" },
    h("div", { class: "sleft" }, status, startAt, meta, nowBtn, minutesBtn),
    h("div", { class: "clocks" }, clockNow, clockEnd), screen, tools, h("div", { class: "sact" }, startBtn, endBtn));
  return { strip, status, tally, big, l1, l2, startAt, meta, nowBtn, minutesBtn, clockNow, clockEnd, screen, tools, planPosSeg, startBtn, endBtn };
}

function applyPlanPos() {
  const p = planPos();
  for (const v of ["side", "top", "hidden"]) document.body.classList.toggle("plan-" + v, p === v);
  if (V) V.st.planPosSeg.set(p);
}

// раз в секунду: время, текущий этап, полосы хода
function tick() {
  if (!V) return;
  const L = A.S && A.S.lesson;
  const st = V.st;
  const { elapsed, cur, stages } = computeCurrent();
  const total = stages.reduce((a, s) => a + s.minutes, 0);
  const live = !!(A.S && A.S.live);
  const waiting = elapsed !== null && elapsed < 0;
  const over = elapsed !== null && elapsed >= total && total > 0;
  const base = lessonBase();
  if (cur !== A.curIdx) {
    A.curIdx = cur;
    if (prefs().page_past === "collapse") for (const s of stages) if (phaseOf(s, elapsed) === "past") delete A.userOpen[s.id];
    applyCollapse();
  }
  // --- состояние
  const set = (el, text) => { if (el.textContent !== text) el.textContent = text; };
  const noMinutes = stages.length && !stages.some((s) => s.minutes > 0);
  let cls = "idle";
  st.startAt.hidden = true;
  st.meta.textContent = "";
  if (!L) {
    set(st.big, ""); set(st.l1, ""); set(st.l2, "Урок не выбран");
  } else if (!stages.length) {
    set(st.big, ""); set(st.l1, A.items.length ? "Урок без этапов" : "Урок пустой"); set(st.l2, "");
  } else if (!live) {
    set(st.big, "");
    const start = /^\d{1,2}:\d{2}$/.test(L.start || "") ? L.start : "";
    set(st.l1, L.kind === "plan" ? "План урока" : "Урок не начат");
    set(st.l2, noMinutes || !start ? "" : "Начало в");          // время не назначено — сама кнопка «Начать в… ▾»
    st.startAt.hidden = !!noMinutes;
    set(st.startAt, (start || "Начать в…") + " ▾");
    st.startAt.classList.toggle("mono", !!start);
    if (start && base !== null) {
      const left = (base - now()) / 60000;
      st.meta.textContent = (left > 0 ? "через " + durText(left) + " · " : "") + "конец в " + clockAt(base + total * 60000);
    } else st.meta.textContent = durText(total) + " · " + stages.length + " " + plural(stages.length, "этап", "этапа", "этапов");
  } else if (waiting) {
    cls = "waiting";
    set(st.big, mmss(-elapsed * 60)); set(st.l1, "До начала"); set(st.l2, (stages[0].item.title || "Этап"));
  } else if (over) {
    cls = "over";
    set(st.big, "+" + mmss((elapsed - total) * 60)); set(st.l1, "Урок окончен"); set(st.l2, "");
  } else if (cur >= 0) {
    const c = stages[cur];
    const left = (c.end - elapsed) * 60;
    cls = left <= 60 ? "live ending" : "live";
    set(st.big, mmss(left));
    set(st.l1, "осталось · этап " + (cur + 1) + " из " + stages.length);
    set(st.l2, c.item.title || "Этап");
  }
  st.status.className = "status " + cls;
  st.status.disabled = !live;
  st.nowBtn.hidden = !waiting;
  st.minutesBtn.hidden = !noMinutes || live;
  st.startBtn.hidden = live || !L || !stages.length || !!noMinutes;
  if (L && L.kind === "plan") st.startBtn.querySelector(".bl").textContent = "Начать по плану";
  else st.startBtn.querySelector(".bl").textContent = "Начать урок";
  st.endBtn.hidden = !live;
  set(st.endBtn.querySelector(".bl"), waiting ? "Отменить начало" : "Завершить");
  st.endBtn.classList.toggle("primary", over);
  st.endBtn.classList.toggle("stop", !over);
  // --- часы
  set(st.clockNow.querySelector("b"), clockAt(now()));
  st.clockEnd.hidden = base === null || !stages.length;
  if (base !== null) {
    let t = clockAt(base + total * 60000);
    const sh = live ? (A.S.live.shift || 0) : 0;
    if (sh) t += (sh > 0 ? " +" : " −") + Math.abs(sh) + " мин";
    set(st.clockEnd.querySelector("b"), t);
  }
  // --- этапы: прошло / идёт / кончается, часы, полоски
  stages.forEach((s, k) => {
    const ph = phaseOf(s, elapsed);
    const ending = ph === "current" && (s.end - elapsed) * 60 <= 60;
    const frac = ph === "current" ? Math.min(1, Math.max(0, (elapsed - s.start) / Math.max(0.001, s.end - s.start))) : ph === "past" ? 1 : 0;
    const art = document.getElementById("st-" + s.id), pr = document.getElementById("pr-" + s.id);
    const rs = V.ribbon.querySelector(`.tseg[data-id="${s.id}"]`), li = V.line.children[k];
    for (const x of [art, pr, rs]) {
      if (!x) continue;
      x.classList.toggle("past", ph === "past");
      x.classList.toggle("current", ph === "current");
      x.classList.toggle("ending", ending);
    }
    if (rs) {
      rs.classList.toggle("done", ph === "past");
      rs.classList.toggle("cur", ph === "current");
      const c = stageClock(s, base);
      set(rs.querySelector(".tt"), c.from + (ph === "current" ? " · идёт" : ""));
      rs.querySelector(".fill").style.width = (frac * 100).toFixed(1) + "%";
    }
    if (li) {
      li.className = ph === "past" ? "done" : ph === "current" ? "cur" : "";
      li.style.setProperty("--f", (frac * 100).toFixed(1) + "%");
    }
    if (art) {
      const clock = art.querySelector(".clock");
      const c = stageClock(s, base);
      if (clock) { if (clock.textContent !== c.text) clock.textContent = c.text; clock.title = c.title; }
      const lbl = art.querySelector(".left .lbl2"), bigS = art.querySelector(".left .big");
      if (lbl) {
        const show = ph === "current" && prefs().page_stage_timer !== false;
        set(lbl, ph === "current" ? (ending ? "Осталось меньше минуты" : "Сейчас · осталось") : ph === "past" ? "Пройдено" : "");
        set(bigS, show ? mmss((s.end - elapsed) * 60) : "");
      }
      const bi = art.querySelector(":scope > .bar i");
      if (bi) bi.style.width = (frac * 100).toFixed(1) + "%";
      nextCard(art, s, ph, stages[k + 1], base);
    }
    if (pr) {
      const t = pr.querySelector(".t");
      if (t) { const c = stageClock(s, base); t.textContent = c.from; t.title = c.title; }
      const pi = pr.querySelector(".pbar2 i");
      if (pi) pi.style.width = (frac * 100).toFixed(1) + "%";
      let sub = pr.querySelector(".psub");
      const want = ph === "current" ? "идёт · осталось " + mmss((s.end - elapsed) * 60) : "";
      if (want && !sub) { sub = h("div", { class: "psub" }); pr.append(sub); }
      if (sub) { sub.hidden = !want; set(sub, want); }
    }
  });
  updateNowbar(cur, stages);
  for (const f of hooks.tick) f({ elapsed, cur, stages, live });
}

// «Дальше» в конце текущего этапа
function nextCard(art, s, ph, nx, base) {
  let card = art.querySelector(":scope > .nextcard");
  const want = ph === "current" && nx && A.mode === "lesson";
  if (!want) { if (card) card.remove(); return; }
  const key = nx.id + "|" + nx.minutes + "|" + (nx.item.title || "") + "|" + (base || 0);
  if (card && card.dataset.k === key) return;
  if (card) card.remove();
  const kind = nx.item.kind === "break" ? "Перерыв: включите его ученикам кнопкой «Перерыв» наверху." :
    nx.item.kind === "exercise" ? "Зарядка: включите её ученикам кнопкой «Зарядка» наверху." : "";
  card = h("div", { class: "nextcard", "data-k": key },
    h("div", { class: "nl" }, h("span", { class: "meta" }, "Дальше" + (base !== null ? " · " + clockAt(base + nx.start * 60000) : "")),
      h("b", null, (nx.item.title || "Этап") + " · " + durText(nx.minutes)), kind ? h("span", { class: "meta" }, kind) : null),
    btn("Начать сейчас", { icon: "skip", onClick: () => shiftWithUndo({ cmd: "start_at", index: nx.i }) }));
  art.append(card);
}

function updateNowbar(cur, stages) {
  const bar = V.nowbar;
  const s = cur >= 0 && A.mode === "lesson" ? stages[cur] : null;
  const st = s && document.getElementById("st-" + s.id);
  let dir = "";
  if (st) {
    const r = st.getBoundingClientRect(), box = V.content.getBoundingClientRect();
    if (r.top > box.bottom - 40) dir = "↓";
    else if (r.bottom < box.top + 40) dir = "↑";
  }
  bar.hidden = !dir;
  if (dir) {
    const text = dir + " Идёт: " + (s.item.title || "Этап");
    if (bar.textContent !== text) bar.textContent = text;
    bar.dataset.id = s.id;
  }
}

// ---------------------------------------------------------------- состояние от программы (канал lesson)
let lastLessonId = null;
function apply(state) {
  if (!state || !V) return;
  const t0 = performance.now();
  A.offset = (state.server_now || Date.now()) - Date.now();
  const prev = A.S;
  A.S = state;
  const id = state.lesson ? state.lesson.id : null;
  if (id !== lastLessonId) {
    lastLessonId = id;
    E.finishEditing();
    A.undo = [];
    A.fresh.clear();
    A.curIdx = -2;
    A.userOpen = {};
    A.selected = null;
    if (id) Q.useLesson(id);
    if (V.content) V.content.scrollTop = 0;
    setMode(state.live ? "lesson" : (state.lesson && state.lesson.kind === "plan" ? "prep" : (A.modeWanted || "prep")));
    // открыт другой урок, чем в адресе (переключили в программе) — адрес следует за уроком
    if (id && location.hash !== "#/lesson/" + id) history.replaceState(null, "", "#/lesson/" + id);
  }
  if (state.live && !(prev && prev.live)) setMode("lesson");
  else if (!state.live && prev && prev.live && prev.lesson && state.lesson && prev.lesson.id === state.lesson.id) setMode("prep");   // урок завершили — снова правка
  const sb = state.efir && state.efir.mode === "slide" ? state.efir.slide_bid : "";
  if (sb && sb !== A.slideBid && A.mode === "lesson") {
    const owner = stageOfBlock(sb);
    if (owner && A.userOpen[owner] === false) { A.userOpen[owner] = true; applyCollapse(); }
    requestAnimationFrame(() => nodeOf(sb)?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }
  A.slideBid = sb;
  for (const f of hooks.apply) f(state, prev);
  refresh();
  for (const f of hooks.strip) f();
  window.__applyMs = performance.now() - t0;      // проверка скорости: урок на 90 блоков — быстрее 300 мс
  window.__lessonReady = true;
}

// ---------------------------------------------------------------- щелчки по ленте (чтение; правка — lessonedit.js)
function openViewer(url, caption) {
  V.viewer.querySelector("img").src = url;
  V.viewer.querySelector(".cap").textContent = caption || "";
  V.viewer.hidden = false;
}

export const mainClick = [];        // обработчики правки: fn(e) → true, если взяли щелчок
function onMainClick(e) {
  const t = e.target;
  if (t.closest("a")) return;
  const img = t.closest("figure img");
  if (img && A.mode === "lesson") { const it = A.byId.get(img.closest(".blk").dataset.id); openViewer(img.src, it && it.title); return; }
  const actBtn = t.closest("[data-act]");
  if (actBtn) {
    const a = actBtn.dataset.act;
    if (a === "break") { const it = A.byId.get(actBtn.dataset.stage); cmd({ cmd: "break", stage: actBtn.dataset.stage, minutes: it ? it.minutes : 10 }); }
    else if (a === "exercise") cmd({ cmd: "exercise", stage: actBtn.dataset.stage || "", index: 0 });
    else if (a === "slide") cmd({ cmd: "slide", block: actBtn.closest(".blk").dataset.id });
    else if (a === "clear-sel") E.setFields(actBtn.closest(".blk").dataset.id, { sel: [] });
    else if (a === "place-insert") E.pickImage(actBtn.closest(".blk").dataset.id, true);
    else if (a === "open-tab") cmd({ cmd: "open_tab" });
    else if (a === "add-video") cmd({ cmd: "look_edit" });
    else if (a === "find-image") cmd({ cmd: "find_image", block: actBtn.closest(".blk").dataset.id });
    else if (a === "fill-slides") { const L = A.S && A.S.lesson; if (L) slidesFill(L.id); }
    return;
  }
  const arm = t.closest(".armbtn");
  if (arm) { cmd({ cmd: "arm", block: arm.closest(".blk").dataset.id }); return; }
  for (const f of mainClick) if (f(e)) return;
  const sh = t.closest(".sh");
  if (A.mode !== "prep" && sh) {
    const st = sh.closest(".stage");
    const sid = st.id.slice(3);
    A.userOpen[sid] = st.classList.contains("collapsed");
    applyCollapse();
  }
}

const NEXT_KEYS = new Set(["ArrowRight", "PageDown"]), PREV_KEYS = new Set(["ArrowLeft", "PageUp"]);
function onKey(e) {
  if (!V || A.mode !== "lesson" || e.ctrlKey || e.altKey || e.metaKey) return;
  const tg = e.target;
  if (tg && (tg.tagName === "INPUT" || tg.tagName === "TEXTAREA" || tg.isContentEditable)) return;
  if (document.querySelector(".sheet, .pop")) return;
  if (!A.items.some((x) => x.type === "image" && x.url)) return;
  const slides = A.items.some((x) => x.type === "image" && x.slide);
  if (!slides && (e.key === "PageDown" || e.key === "PageUp")) return;
  if (NEXT_KEYS.has(e.key) || PREV_KEYS.has(e.key)) { e.preventDefault(); cmd({ cmd: "slide_step", d: NEXT_KEYS.has(e.key) ? 1 : -1 }); }
  else if (["b", "B", "и", "И", ".", "ю"].includes(e.key)) { e.preventDefault(); cmd({ cmd: "background" }); }
}
document.addEventListener("keydown", onKey);
Q.Q.onResult = (res) => {
  for (const [id, it] of Object.entries(res.items || {})) { if (it) A.fresh.set(id, it); released(id); }
  refresh();
};
Q.Q.onError = (text) => toast(text, { warn: true });

// ---------------------------------------------------------------- экран
function renameLesson() {
  const L = A.S && A.S.lesson;
  if (!L) return;
  const inp = h("input", { class: "inp", value: L.title, "aria-label": "Название урока" });
  const save = btn("Сохранить", { kind: "primary", onClick: () => {
    const v = inp.value.trim();
    closePop();
    if (v && v !== L.title) E.act({ op: "set_lesson", title: v }, { op: "set_lesson", title: L.title });
  } });
  inp.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); save.click(); } });
  popover(V.menuBtn, h("div", { class: "startpanel" }, h("div", { class: "phead" }, "Название урока"), h("div", { class: "zrow" }, inp, save)), { align: "right" });
  inp.select();
}

export function lessonView(root, r) {
  const st = buildStrip();
  const ribbon = h("nav", { id: "planRibbon", "aria-label": "Этапы урока" });
  const line = h("div", { id: "lessonLine", "aria-hidden": "true" });
  const plan = h("nav", { id: "plan", "aria-label": "План урока" });
  const banner = h("section", { id: "planbanner", hidden: true });
  const main = h("div", { id: "main" });
  const content = h("div", { id: "content", class: "lcontent" }, h("div", { class: "lcol" }, banner, main));
  const nowbar = h("button", { id: "nowbar", type: "button", hidden: true });
  const viewer = h("div", { id: "viewer", hidden: true }, h("img", { alt: "" }), h("div", { class: "cap" }));
  const toastEl = h("div", { id: "toast", hidden: true });       // старый тост модулей урока (state.toast) — не нужен окну
  const menuBtn = iconBtn("chevron-down", "Меню урока", () => {
    const L = A.S && A.S.lesson;
    if (L) menu(menuBtn, lessonMenuItems(L.id, renameLesson), { align: "left" });
  }, { kind: "ghost", size: "sm" });
  menuBtn.id = "lessonMenuBtn";
  // «↓ Идёт: …» — над текстом урока (в .lbody): полоса набора под ним его не закрывает
  const view = h("div", { class: "lview" }, st.strip, line, ribbon, h("div", { class: "lbody" }, plan, content, nowbar), viewer, toastEl);
  root.append(view);
  V = { st, ribbon, line, plan, banner, main, content, nowbar, viewer, menuBtn };
  main.addEventListener("click", onMainClick);
  main.addEventListener("mouseover", (e) => { const b = e.target.closest(".blk[data-id]"); if (b) A.hovered = b.dataset.id; });
  plan.addEventListener("click", (e) => {
    const n = e.target.closest(".n");
    if (!n) return;
    goStage(n.closest(".prow").dataset.id);
  });
  viewer.addEventListener("click", () => { viewer.hidden = true; });
  nowbar.addEventListener("click", () => { if (nowbar.dataset.id) goStage(nowbar.dataset.id); nowbar.hidden = true; });
  content.addEventListener("scroll", () => { const c = computeCurrent(); updateNowbar(c.cur, c.stages); }, { passive: true });
  applyPlanPos();
  for (const f of hooks.mount) f(V);
  const timer = setInterval(tick, 1000);
  const offLesson = on("lesson", apply);
  lastLessonId = null;
  // урок в адресе — в фокус программы (идёт другой урок — программа спросит). Просим один раз на урок:
  // программа в ответ откроет этот же адрес, и просьба не должна повторяться по кругу
  let asked = "";
  const focusWanted = (id) => {
    const cur = LC.state && LC.state.lesson ? LC.state.lesson.id : null;
    // урок уже в фокусе программы (его открыла она — канал урока ещё в пути): второй раз не просить
    if (!id || id === cur || id === S.focus_id || id === asked || !(S.lessons || []).some((x) => x.id === id)) return;
    asked = id;
    send({ cmd: "open", lesson: id }).catch(() => {});
  };
  focusWanted(r.id);
  if (LC.state) apply(LC.state);
  return {
    update: () => { applyPlanPos(); tick(); },
    route: (r2) => focusWanted(r2.id),
    destroy: () => {
      clearInterval(timer);
      offLesson();
      E.finishEditing();
      Q.flushDrafts();
      V = null;
      for (const c of ["mode-prep", "mode-lesson", "editing", "plan-side", "plan-top", "plan-hidden", "is-live"]) document.body.classList.remove(c);
    },
  };
}

export function lessonV() { return V; }
export { shiftWithUndo, endLesson, startNow, mayReplace, applyCollapse };
