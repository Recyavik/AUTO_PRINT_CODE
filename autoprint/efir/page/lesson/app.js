// Экран урока: связь с программой (SSE), шапка, режимы «Подготовка» / «Урок», время этапов, обработчики.
"use strict";
import { A, $, el, icon, menu, closeMenu, toast, cmd, now, mmss, hm, hhmm, clockAt, nextHalfHour, durText, plural,
  isTyping } from "./state.js";
import * as Q from "./queue.js";
import { renderMain, renderPlan, legend, stagesOf, nodeOf, stageOfBlock, markOnScreen, exerciseList } from "./render.js";
import * as E from "./edit.js";
import { beginCode, released, endCode } from "./code.js";

const BUSY = ["running", "countdown", "paused", "line_wait"];

// ---------------------------------------------------------------- урок: состояние программы + свои правки
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

let headerStale = false;
export function refresh() {
  rebuildItems();
  renderMain();
  markOnScreen();
  renderPlan();
  applyCollapse();
  tick();
  const t = A.title || "Экран урока";
  if ($("title").dataset.v !== t && !$("title").contains(document.activeElement)) {
    $("title").dataset.v = t;
    $("titleText").textContent = t;
  }
  // в списке окон для демонстрации экрана видно: это — не ученикам (их окно — «Экран учеников — показывать…»)
  document.title = (A.S && A.S.lesson ? t + " · Суфлёр (только для вас)" : "Суфлёр (только для вас)") + " — AutoPrintCode";
  saveChip();
}
window.addEventListener("suflor:refresh", refresh);

// ---------------------------------------------------------------- «Мои настройки»: размер, план, этапы
const ZOOM_MIN = 80, ZOOM_MAX = 200;
export function prefs() { return (A.S && A.S.prefs) || {}; }

function applyPrefs() {
  const p = prefs();
  const z = String(Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, p.page_zoom || 100)) / 100);
  if (document.documentElement.style.zoom !== z) document.documentElement.style.zoom = z;
  setVh();
  const b = document.body.classList;
  for (const v of ["strip", "side", "hidden"]) b.toggle("plan-" + v, (p.page_plan || "strip") === v);
  b.toggle("past-collapse", p.page_past === "collapse");
  b.toggle("no-stage-timer", p.page_stage_timer === false);
}

// 1vh в пикселях страницы с учётом zoom: высоты «по экрану» (план, меню, слайд) не вылезают за окно
function setVh() {
  const z = parseFloat(document.documentElement.style.zoom) || 1;
  document.documentElement.style.setProperty("--vh", (innerHeight / z / 100).toFixed(3) + "px");
}
window.addEventListener("resize", setVh);
setVh();

export function setPref(key, value) {
  if (!A.S) return;
  A.S.prefs = Object.assign({}, A.S.prefs, { [key]: value });
  applyPrefs();
  cmd({ cmd: "prefs", key, value });
  refresh();
}

function zoomBy(d) {
  const z = prefs().page_zoom || 100;
  setPref("page_zoom", d === 0 ? 100 : Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, z + d)));
}

// Ctrl+= / Ctrl+− / Ctrl+0 и Ctrl+колесо — размер текста (а не масштаб браузера: он не запоминается)
document.addEventListener("keydown", (e) => {
  if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey && e.key !== "+") return;
  if (e.key === "=" || e.key === "+") { e.preventDefault(); zoomBy(10); }
  else if (e.key === "-" || e.key === "_") { e.preventDefault(); zoomBy(-10); }
  else if (e.key === "0") { e.preventDefault(); zoomBy(0); }
}, true);
let wheelAcc = 0;
window.addEventListener("wheel", (e) => {
  if (!e.ctrlKey) return;
  e.preventDefault();
  wheelAcc += e.deltaY;
  if (Math.abs(wheelAcc) >= 80) { zoomBy(wheelAcc < 0 ? 10 : -10); wheelAcc = 0; }
}, { passive: false });

function prefsMenu(anchor) {
  const p = prefs();
  const box = el("div", "pmenu prefs");
  box.appendChild(el("div", "mhead", "Мои настройки"));
  const zr = el("div", "zrow");
  zr.appendChild(el("span", "", "Размер текста"));
  const minus = el("button", "", "−"), val = el("b", "zval"), plus = el("button", "", "+"), reset = el("button", "ghost", "Обычный");
  minus.setAttribute("aria-label", "Мельче");
  plus.setAttribute("aria-label", "Крупнее");
  const upd = () => { val.textContent = (prefs().page_zoom || 100) + " %"; };
  upd();
  minus.onclick = () => { zoomBy(-10); upd(); };
  plus.onclick = () => { zoomBy(10); upd(); };
  reset.onclick = () => { zoomBy(0); upd(); };
  for (const x of [minus, val, plus, reset]) zr.appendChild(x);
  box.appendChild(zr);
  box.appendChild(el("div", "phelp", "Ещё: Ctrl + колесо мыши, Ctrl+= и Ctrl+− (Ctrl+0 — обычный)."));
  const seg = (title, key, opts, cls, def) => {
    box.appendChild(el("div", "mlabel", title));
    const s = el("div", "seg " + cls);
    for (const [v, n] of opts) {
      const b = el("button", "", n);
      b.setAttribute("aria-pressed", (p[key] || def) === v ? "true" : "false");
      b.onclick = () => { setPref(key, v); s.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b ? "true" : "false")); };
      s.appendChild(b);
    }
    box.appendChild(s);
  };
  seg("План в «Уроке»", "page_plan", [["strip", "Строкой"], ["side", "Сбоку"], ["hidden", "Скрыть"]], "plan", "strip");
  seg("Пройденные этапы", "page_past", [["dim", "Приглушать"], ["collapse", "Сворачивать"]], "past", "dim");
  for (const [k, n, h] of [["page_stage_timer", "Таймер на текущем этапе", "«осталось» на карточке этапа"],
    ["start_timer", "При начале урока — мини-таймер", "маленькое окно «Эфира» поверх всех окон"],
    ["start_screen", "При начале урока — экран учеников", "вкладка, которую показывают ученикам"]]) {
    const lab = el("label", "ptog");
    const c = el("input");
    c.type = "checkbox";
    c.checked = k === "page_stage_timer" ? p[k] !== false : !!p[k];
    c.onchange = () => setPref(k, c.checked);
    lab.appendChild(c);
    const t = el("span");
    t.appendChild(el("b", "", n));
    t.appendChild(el("small", "", h));
    lab.appendChild(t);
    box.appendChild(lab);
  }
  menu(anchor, [{ node: box }], { right: true, cls: "wide", focus: false });
}

// ---------------------------------------------------------------- режим
function setMode(m, user = false) {
  if (A.S && A.S.live && m === "prep" && !user) m = "lesson";
  if (A.mode === m && document.body.classList.contains("mode-" + m)) return;
  if (m === "lesson") E.finishEditing();
  A.mode = m;
  document.body.classList.toggle("mode-prep", m === "prep");
  document.body.classList.toggle("mode-lesson", m === "lesson");
  try { localStorage.setItem("suflor.mode", m); } catch (e) { /* нет хранилища */ }
  A.curIdx = -2;
  A.userOpen = {};
  renderTools();
  refresh();
}

// ---------------------------------------------------------------- шапка
function chip(text, cls = "") { return el("span", "chip " + cls, text); }

function lessonsMenu(anchor) {
  const L = A.S && A.S.lesson;
  const box = el("div", "lsearch");
  const inp = el("input", "inl");
  inp.placeholder = "Найти урок…";
  inp.setAttribute("aria-label", "Поиск урока");
  box.appendChild(inp);
  const list = el("div", "llist");
  box.appendChild(list);
  const live = A.S && A.S.live;
  const fill = () => {
    list.innerHTML = "";
    const q = inp.value.trim().toLowerCase();
    const all = (A.S.lessons || []).filter((x) => !q || x.title.toLowerCase().includes(q));
    const plansL = all.filter((x) => x.kind === "plan"), lessonsL = all.filter((x) => x.kind !== "plan");
    const add = (x) => {
      const b = el("button", "mi" + (L && x.id === L.id ? " on" : ""));
      b.appendChild(el("span", "ml", x.title));
      const meta = x.kind === "plan"
        ? [x.stages ? durText(x.total) : "", x.stages ? x.stages + " " + plural(x.stages, "этап", "этапа", "этапов") : ""].filter(Boolean).join(" · ")
        : [x.stages ? durText(x.total) : "", x.stages ? x.stages + " " + plural(x.stages, "этап", "этапа", "этапов") : "",
          x.codes ? x.codes + " " + plural(x.codes, "код", "кода", "кодов") : "без кода", x.plan ? "план «" + x.plan + "»" : ""].filter(Boolean).join(" · ");
      b.appendChild(el("span", "mh", meta));
      b.onclick = () => {
        closeMenu();
        if (L && x.id === L.id) return;
        if (live && !confirm("Идёт урок «" + L.title + "». Завершить его и открыть «" + x.title + "»?")) return;
        cmd({ cmd: "open", lesson: x.id, force: !!live });
      };
      list.appendChild(b);
    };
    if (plansL.length) {                      // есть планы — две группы
      list.appendChild(el("div", "mhead", "Планы"));
      plansL.forEach(add);
      if (lessonsL.length) list.appendChild(el("div", "mhead", "Уроки"));
    }
    lessonsL.forEach(add);
  };
  fill();
  inp.addEventListener("input", fill);
  // «Новый урок»: по плану, пустой или по шаблону структуры (этапы с минутами), новый план
  const news = [{ head: "Новый урок" }];
  for (const p of A.S.plans || []) {
    const nb = el("button", "mi newl");
    nb.appendChild(icon("plus"));
    nb.appendChild(el("span", "ml", "По плану «" + p.title + "»"));
    if (p.minutes) nb.appendChild(el("span", "mh", durText(p.minutes)));
    nb.onclick = () => {
      closeMenu();
      if (live && !confirm("Идёт урок «" + L.title + "». Завершить его и начать новый?")) return;
      cmd({ cmd: "new_lesson", force: !!live, plan: p.id });
      setMode("prep", true);
    };
    news.push({ node: nb });
  }
  const structs = (A.S.structures && A.S.structures.length) ? A.S.structures : [{ key: "empty", title: "Пустой урок", minutes: 0 }];
  for (const s of structs) {
    const nb = el("button", "mi newl");
    nb.appendChild(icon("plus"));
    nb.appendChild(el("span", "ml", s.title));
    if (s.minutes) nb.appendChild(el("span", "mh", durText(s.minutes)));
    nb.onclick = () => {
      closeMenu();
      if (live && !confirm("Идёт урок «" + L.title + "». Завершить его и начать новый?")) return;
      cmd({ cmd: "new_lesson", force: !!live, structure: s.key });
      setMode("prep", true);
    };
    news.push({ node: nb });
  }
  const np = el("button", "mi newp");
  np.appendChild(icon("plus"));
  np.appendChild(el("span", "ml", "Новый план урока"));
  np.appendChild(el("span", "mh", "этапы и минуты для многих уроков"));
  np.onclick = () => {
    closeMenu();
    if (live && !confirm("Идёт урок «" + L.title + "». Завершить его и начать новый план?")) return;
    cmd({ cmd: "new_plan", force: !!live, structure: "empty" });
    setMode("prep", true);
  };
  news.push({ sep: true }, { node: np });
  menu(anchor, [{ node: box }, { sep: true }, ...news], { cls: "lessons" });
  inp.focus();
}

function printMenu(anchor) {
  const P = (A.S && A.S.print) || {};
  const box = el("div", "pmenu");
  box.appendChild(el("div", "mhead", "Как печатать код"));
  const seg = el("div", "seg");
  for (const [k, n] of [["block", "Целиком"], ["lines", "По строкам"], ["steps", "По шагам"]]) {
    const b = el("button", "", n);
    b.setAttribute("aria-pressed", P.mode === k ? "true" : "false");
    b.onclick = () => { cmd({ cmd: "print_settings", key: "mode", value: k }); seg.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b ? "true" : "false")); };
    seg.appendChild(b);
  }
  box.appendChild(seg);
  const hint = el("div", "phelp", "По строкам — строка, потом ваш Enter. По шагам — шаги отмечают в коде (Alt+1…9 в «Подготовке»).");
  box.appendChild(hint);
  const sp = el("label", "prange");
  const val = el("b", "", String(P.cpm || 320));
  sp.appendChild(el("span", "", "Скорость"));
  const r = el("input");
  r.type = "range"; r.min = "60"; r.max = "1200"; r.step = "10"; r.value = String(P.cpm || 320);
  r.setAttribute("aria-label", "Скорость печати, знаков в минуту");
  r.oninput = () => { val.textContent = r.value; };
  r.onchange = () => cmd({ cmd: "print_settings", key: "cpm", value: +r.value });
  sp.appendChild(r);
  sp.appendChild(val);
  sp.appendChild(el("span", "u", "зн/мин"));
  box.appendChild(sp);
  for (const [k, n, h] of [["human", "Как человек", "живой ритм, паузы, опечатки"], ["sound", "Звук клавиш", ""],
    ["strip", "Комментарии читать вслух", "в код они не печатаются — «Скажи: …» над кодом"]]) {
    const lab = el("label", "ptog");
    const c = el("input");
    c.type = "checkbox";
    c.checked = !!P[k];
    c.onchange = () => cmd({ cmd: "print_settings", key: k, value: c.checked });
    lab.appendChild(c);
    const t = el("span");
    t.appendChild(el("b", "", n));
    if (h) t.appendChild(el("small", "", h));
    lab.appendChild(t);
    box.appendChild(lab);
  }
  const all = el("button", "linkbtn", "Все настройки печати…");
  all.onclick = () => { closeMenu(); cmd({ cmd: "settings", page: "print" }); };
  box.appendChild(all);
  menu(anchor, [{ node: box }], { right: true, cls: "wide", focus: false });
}

function moreMenu(anchor) {
  const L = A.S.lesson;
  const presets = (L && L.presets) || [];
  const items = [];
  if (A.mode === "lesson" && stagesOf(A.items).length) {
    items.push({ head: "Этапы" });
    items.push({ label: "Свернуть пройденные", on: () => collapseStages("past") });
    items.push({ label: "Свернуть все этапы", on: () => collapseStages("all") });
    items.push({ label: "Развернуть все этапы", on: () => collapseStages("none") });
    items.push({ sep: true });
  }
  items.push(
    { label: $("legend").hidden ? "Показать обозначения" : "Скрыть обозначения", on: () => { $("legend").hidden = !$("legend").hidden; } },
    { label: "Распечатать или PDF…", hint: "размер, ответы, код, слайды", on: printBox },
    { head: "Экспорт урока" },
    { label: "Урок в Markdown (.md)…", on: () => cmd({ cmd: "export", fmt: "md" }) },
    { label: "Урок в .ipynb…", on: () => cmd({ cmd: "export", fmt: "ipynb" }) },
    { label: "Тетрадка учеников (только код)…", on: () => cmd({ cmd: "export", fmt: "students" }) },
    { label: "Урок в .json…", on: () => cmd({ cmd: "export", fmt: "json" }) },
  );
  items.push({ head: "Оформление экрана учеников" });
  for (const p of presets) items.push({ label: p.title, checked: p.id === L.preset, on: () => cmd({ cmd: "preset", id: p.id }) });
  if (presets.length) items.push({ label: "Изменить оформление…", hint: "фон, зарядки, перерыв", on: () => cmd({ cmd: "look_edit" }) });
  items.push({ label: "Новое оформление…", on: () => cmd({ cmd: "look_new" }) });
  items.push({ sep: true });
  items.push({ label: "Разложить по этапам (⏱ этапы, 🗣 реплики)…", hint: "копия урока", on: () => cmd({ cmd: "recognize" }) });
  const hasSlides = A.items.some((x) => x.type === "image" && x.slide);
  items.push({ head: "Нейросеть в своём чате" });
  items.push({ label: L.kind === "plan" ? "Промпт для нового урока по этому плану…" : hasSlides ? "Промпт для слайдов…" : "Промпт для своего чата…",
    hint: "ChatGPT, GigaChat, Алиса, DeepSeek",
    on: () => cmd({ cmd: "chat_prompt" }) });
  items.push({ label: "Вставить ответ нейросети…", hint: "копия урока", on: answerBox });
  if (A.items.some((x) => x.type === "image" && x.place === "slide")) {
    items.push({ label: "Подставить слайды из презентации…", hint: "PDF или PowerPoint — картинки к «Слайд N»", on: () => cmd({ cmd: "fill_slides" }) });
  }
  // план урока: открыть / отвязать; обычный урок — сделать из этапов план или привязать к плану
  const isPlan = L.kind === "plan";
  if (!isPlan) {
    const plansL = (A.S.plans || []);
    const hasStages = stagesOf(A.items).length > 0;
    if (L.fixed && L.plan) {
      items.push({ head: "План урока" });
      items.push({ label: "Открыть план «" + L.plan.title + "»", on: openPlan });
      items.push({ label: "Отвязать от плана…", on: () => {
        if (confirm("Отвязать урок «" + L.title + "» от плана «" + L.plan.title + "»? Этапы останутся, но правка плана их больше не изменит.")) cmd({ cmd: "unlink_plan" });
      } });
    } else if (hasStages || plansL.length) {
      items.push({ head: "План урока" });
      if (hasStages) items.push({ label: "Сделать из этапов план", hint: "этапы и минуты — для многих уроков", on: () => cmd({ cmd: "make_plan" }) });
      for (const p of plansL) items.push({ label: "Привязать к плану «" + p.title + "»", on: () => cmd({ cmd: "link_plan", plan: p.id }) });
    }
  }
  items.push({ label: isPlan ? "Удалить план…" : "Удалить урок…", danger: true, on: () => {
    const n = (L.topics || []).length;
    const q = (A.S.live ? "Идёт урок — он завершится. " : "") +
      (isPlan ? "Удалить план «" + L.title + "»?" + (n ? " Уроки по нему (" + n + ") останутся с этими этапами, но без связи." : "")
        : "Удалить урок «" + L.title + "»?");
    if (confirm(q + " Копия прошлой базы — data/templates.json.bak")) cmd({ cmd: "delete_lesson" });
  } });
  menu(anchor, items, { right: true });
}

// идёт другой эфир (вебинар по расписанию) — спросить здесь, а не окном программы, которое может быть за браузером
function mayReplace() {
  const other = A.S && A.S.other_live;
  return !other || confirm("Сейчас идёт эфир «" + other + "». Завершить его и начать урок?");
}

// идёт урок: «Урок идёт · 11:02 ▾» — начало, «Начать этот этап сейчас», «Завершить»
function liveMenu(anchor) {
  const box = el("div", "pmenu");
  box.appendChild(el("div", "mhead", "Идёт урок"));
  const row = el("label", "zrow");
  row.appendChild(el("span", "", "Начало"));
  const tm = el("input");
  tm.type = "time";
  tm.className = "tmin";
  tm.value = hhmm(A.S.live.anchor);
  tm.title = "Начало идущего урока: наберите время и нажмите Enter — время этапов сдвинется (Esc — отмена)";
  const was = tm.value;
  let sent = false;
  // по Enter или уходу из поля — не на каждую цифру (набрали «1» поверх 17:30 — это не 01:30)
  const commit = () => { if (!sent && tm.value && tm.value !== was) { sent = true; cmd({ cmd: "set_start", start: tm.value }); } };
  tm.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); commit(); closeMenu(); } else if (e.key === "Escape") { tm.value = was; closeMenu(); }
  });
  tm.addEventListener("blur", commit);
  row.appendChild(tm);
  box.appendChild(row);
  const { next, elapsed } = computeCurrent();
  const waiting = elapsed !== null && elapsed < 0;
  menu(anchor, [{ node: box },
    waiting ? { label: "Начать урок сейчас", hint: "не ждать назначенного времени", on: () => shiftWithUndo({ cmd: "shift_now" }) }
      : { label: "Начать этот этап сейчас", hint: "текущий этап — с этой минуты, следующие сдвигаются", on: () => shiftWithUndo({ cmd: "shift_now" }) },
    ...(!waiting && next >= 0 ? [{ label: "Следующий этап — сейчас", hint: "закончили раньше — дальше по плану",
      on: () => shiftWithUndo({ cmd: "start_at", index: next }) }] : []),
    { label: "Мини-таймер «Эфира»", hint: "окно поверх всех", on: () => cmd({ cmd: "timer" }) },
    { sep: true },
    { label: waiting ? "Отменить начало…" : "Завершить урок…", danger: true, on: endLesson },
  ], { focus: false });
}

// сдвиг времени урока — с «Вернуть» (прежнее начало урока)
function shiftWithUndo(c) {
  const prev = A.S && A.S.live && A.S.live.anchor;
  cmd(c);
  if (prev) toast("Время этапов сдвинуто на сейчас", "Вернуть", () => cmd({ cmd: "restore_anchor", ms: prev }), 10000);
}

function endLesson() {
  const { elapsed } = computeCurrent();
  const waiting = elapsed !== null && elapsed < 0;
  if (confirm(waiting ? "Отменить назначенное начало урока? Таймер «Эфира» закроется." : "Завершить урок? Таймер «Эфира» закроется.")) cmd({ cmd: "stop" });
}

function startAtMenu(anchor) {
  const L = A.S.lesson;
  const box = el("div", "pmenu");
  box.appendChild(el("div", "mhead", "Начать урок в"));
  const row = el("div", "zrow");
  const tm = el("input");
  tm.type = "time";
  tm.className = "tmin";
  tm.value = (L && L.start) || nextHalfHour();
  const go = el("button", "primary", "Начать");
  go.onclick = () => { if (tm.value && mayReplace()) { closeMenu(); cmd({ cmd: "start", at: tm.value, force: !!A.S.other_live }); } };
  tm.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go.click(); } });
  row.appendChild(tm);
  row.appendChild(go);
  box.appendChild(row);
  box.appendChild(el("div", "phelp", "До начала таймер считает «до начала». Время из прошлого (в пределах 6 часов) — урок уже идёт."));
  menu(anchor, [{ node: box }], { focus: false });
  tm.focus();
}

// ---------------------------------------------------------------- экран учеников
function renderScreenCtl() {
  stripEl();
  const box = $("strip").querySelector(".screen");
  box.innerHTML = "";
  const ef = (A.S && A.S.efir) || {};
  const sc = el("button", "chip scrchip");
  sc.title = "Экран учеников: что у них сейчас и что показать";
  sc.onclick = () => screenMenu(sc);
  box.appendChild(sc);
  if (ef.mode && ef.mode !== "idle") {
    const back = el("button", "", "Вернуть фон");
    back.title = "Ученикам — снова фон (B)";
    back.onclick = () => cmd({ cmd: "background" });
    box.appendChild(back);
  } else if (stagesOf(A.items).some((s) => s.item.kind === "break")) {   // в уроке есть перерыв — кнопка под рукой
    const br = el("button", "", "Перерыв");
    br.title = "Перерыв ученикам — по плану урока (другие минуты — в «У учеников ▾»)";
    br.onclick = () => cmd({ cmd: "break", stage: currentBreakStage() });
    box.appendChild(br);
  }
  screenChip();
}

function currentBreakStage() {
  const { cur, stages } = computeCurrent();
  const s = cur >= 0 ? stages[cur] : null;
  return s && s.item.kind === "break" ? s.id : "";
}

function screenText() {
  const ef = (A.S && A.S.efir) || {};
  if (ef.mode === "break") {
    const left = ef.break_ends ? Math.max(0, (ef.break_ends - now()) / 1000) : 0;
    if (ef.break_ends && !left && !ef.break_paused) return ["Перерыв окончен ▾", "warn"];
    return ["У учеников: перерыв" + (left ? " · " + mmss(left) : "") + (ef.break_paused ? " · пауза" : "") + " ▾", "warn"];
  }
  if (ef.mode === "exercise") {
    if (ef.ex_waiting) return ["У учеников: зарядка ждёт щелчка по их вкладке ▾", "bad"];
    if (ef.ex_muted) return ["У учеников: зарядка без звука — щёлкните по их вкладке ▾", "bad"];
    return ["У учеников: зарядка ▾", "warn"];
  }
  if (ef.mode === "slide") return ["У учеников: слайд " + (ef.slide_n || "") + " ▾", "ok"];
  if (!ef.tab_open) return ["Экран учеников ▾", "dim"];
  return ["У учеников: фон ▾", ""];
}

function screenChip() {
  const c = document.querySelector("#strip .scrchip");
  if (!c) return;
  const [text, cls] = screenText();
  if (c.textContent !== text) c.textContent = text;
  c.title = cls === "dim" ? "Вкладка экрана учеников не открыта — щёлкните: открыть, фон, перерыв, зарядка"
    : "Экран учеников: что у них сейчас и что показать";
  c.className = "chip scrchip" + (cls ? " " + cls : "");
}

function screenMenu(anchor) {
  const ef = (A.S && A.S.efir) || {};
  const stages = stagesOf(A.items);
  const brk = stages.find((s) => s.item.kind === "break");
  const planned = brk && brk.minutes > 0 ? brk.minutes : 10;
  const items = [{ head: "Экран учеников" }];
  if (ef.mode === "break") {                // идёт перерыв — им можно управлять отсюда, не только из мини-таймера
    items.push({ label: "+5 мин", hint: "к перерыву", on: () => cmd({ cmd: "break_adjust", seconds: 300 }) });
    items.push({ label: "+1 мин", on: () => cmd({ cmd: "break_adjust", seconds: 60 }) });
    items.push({ label: ef.break_paused ? "Продолжить отсчёт" : "Пауза отсчёта", on: () => cmd({ cmd: "break_pause" }) });
    items.push({ label: "Заново", hint: "отсчёт сначала", on: () => cmd({ cmd: "break_restart" }) });
    items.push({ label: "Убрать — снова фон", on: () => cmd({ cmd: "background" }) });
    items.push({ sep: true });
  }
  if (!ef.tab_open) items.push({ label: "Открыть экран учеников", hint: "вкладка для демонстрации", on: () => cmd({ cmd: "open_tab" }) });
  items.push({ label: "Скопировать адрес вкладки", hint: "вставьте в браузер, из которого показываете", on: () => cmd({ cmd: "copy_url" }) });
  items.push({ label: "Фон", checked: !ef.mode || ef.mode === "idle", on: () => cmd({ cmd: "background" }) });
  items.push({ label: `Перерыв по плану · ${planned} мин`, checked: ef.mode === "break", on: () => cmd({ cmd: "break", stage: currentBreakStage(), minutes: planned }) });
  for (const m of [5, 10, 15, 20].filter((x) => x !== planned)) items.push({ label: `Перерыв ${m} мин`, on: () => cmd({ cmd: "break", minutes: m }) });
  const exl = exerciseList();
  if (exl.length > 1) {                        // несколько видео — выбрать, какое
    items.push({ head: "Зарядка" });
    exl.forEach((title, i) => items.push({ label: title || "Зарядка", checked: ef.mode === "exercise" && ef.ex_index === i,
      on: () => cmd({ cmd: "exercise", index: i }) }));
  } else if (exl.length) {
    items.push({ label: "Зарядка", checked: ef.mode === "exercise", on: () => cmd({ cmd: "exercise", index: 0 }) });
  }
  items.push({ sep: true });
  items.push({ label: "Мини-таймер «Эфира»", hint: "окно поверх всех", on: () => cmd({ cmd: "timer" }) });
  menu(anchor, items);
}

// печать: размер текста, ответы к вопросам, код, слайды — классы на <body> только на время печати
const PRINT_DEF = { size: "normal", answers: true, code: true, slides: "big" };
function printPrefs() {
  try { return Object.assign({}, PRINT_DEF, JSON.parse(localStorage.getItem("suflor.print") || "{}")); } catch (e) { return { ...PRINT_DEF }; }
}
function printBox() {
  const pr = printPrefs();
  const ov = el("div", "modal");
  const box = el("div", "mbox printbox");
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-label", "Печать урока");
  box.appendChild(el("h3", "", "Печать урока или PDF"));
  const seg = (title, key, opts) => {
    box.appendChild(el("div", "mlabel", title));
    const s = el("div", "seg");
    for (const [v, n] of opts) {
      const b = el("button", "", n);
      b.setAttribute("aria-pressed", pr[key] === v ? "true" : "false");
      b.onclick = () => { pr[key] = v; s.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b ? "true" : "false")); };
      s.appendChild(b);
    }
    box.appendChild(s);
  };
  seg("Размер текста", "size", [["small", "Мелко"], ["normal", "Обычно"], ["large", "Крупно"]]);
  seg("Слайды и картинки", "slides", [["big", "Крупно"], ["thumbs", "Миниатюрами"], ["none", "Без"]]);
  for (const [k, n] of [["answers", "Ответы к вопросам"], ["code", "Код"]]) {
    const lab = el("label", "ptog");
    const c = el("input");
    c.type = "checkbox";
    c.name = k;
    c.checked = !!pr[k];
    c.onchange = () => { pr[k] = c.checked; };
    lab.appendChild(c);
    lab.appendChild(el("b", "", n));
    box.appendChild(lab);
  }
  box.appendChild(el("p", "phelp", "Для PDF в окне печати выберите принтер «Сохранить как PDF». Цвет плашек печатается, "
    + "если принтер цветной."));
  const row = el("div", "mrow");
  const no = el("button", "", "Отмена");
  const ok = el("button", "primary", "Печать");
  no.onclick = () => ov.remove();
  ok.onclick = () => {
    for (const k of ["answers", "code"]) pr[k] = box.querySelector(`input[name=${k}]`).checked;
    try { localStorage.setItem("suflor.print", JSON.stringify(pr)); } catch (e) { /* нет хранилища */ }
    ov.remove();
    const cls = ["print-size-" + pr.size, "print-slides-" + pr.slides];
    if (!pr.answers) cls.push("print-no-answers");
    if (!pr.code) cls.push("print-no-code");
    document.body.classList.add(...cls);
    try { window.print(); } finally { document.body.classList.remove(...cls); }
  };
  ov.addEventListener("keydown", (e) => { if (e.key === "Escape") ov.remove(); });
  row.appendChild(no);
  row.appendChild(ok);
  box.appendChild(row);
  ov.appendChild(box);
  document.body.appendChild(ov);
  ok.focus();
}

// ответ своего чата — вставить сюда, получится копия урока (слайды — по номерам)
function answerBox() {
  const ov = el("div", "modal");
  const box = el("div", "mbox");
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-label", "Ответ нейросети");
  box.appendChild(el("h3", "", "Ответ нейросети"));
  box.appendChild(el("p", "phelp", "Вставьте ответ чата целиком (Ctrl+V) — блок ~~~markdown. Получится копия урока: этапы "
    + "и заметки по ответу, слайды — по номерам. Исходный урок не меняется."));
  const ta = el("textarea", "ansta");
  ta.rows = 12;
  ta.setAttribute("aria-label", "Ответ нейросети");
  box.appendChild(ta);
  const row = el("div", "mrow");
  const ok = el("button", "primary", "Добавить урок");
  const no = el("button", "", "Отмена");
  ok.onclick = () => { if (!ta.value.trim()) { ta.focus(); return; } cmd({ cmd: "apply_answer", text: ta.value }); ov.remove(); toast("Готовлю урок по ответу…"); };
  no.onclick = () => ov.remove();
  ov.addEventListener("keydown", (e) => { if (e.key === "Escape") ov.remove(); });
  row.appendChild(no);
  row.appendChild(ok);
  box.appendChild(row);
  ov.appendChild(box);
  document.body.appendChild(ov);
  ta.focus();
}

function toolsBusy() { const a = document.activeElement; return !!a && a !== document.body && $("tools").contains(a); }
$("tools").addEventListener("focusout", () => setTimeout(() => { if (headerStale && !toolsBusy()) { headerStale = false; renderTools(); } }, 0));

// под названием — «по плану «X» ↗»; у плана в «Подготовке» — полоса: чей это план и что такое заготовки
function renderPlanInfo() {
  const L = A.S && A.S.lesson;
  const link = $("planlink"), banner = $("planbanner");
  const linked = !!(L && L.fixed && L.plan);
  link.hidden = !linked;
  if (linked) link.textContent = "по плану «" + L.plan.title + "» ↗";
  const show = !!(L && L.kind === "plan" && A.mode === "prep");
  banner.hidden = !show;
  if (!show) return;
  banner.innerHTML = "";
  const topics = L.topics || [];
  const line = el("div");
  line.appendChild(el("b", "", "План урока"));
  line.appendChild(document.createTextNode(": этапы и минуты для всех уроков по нему (" + topics.length + ")" + (topics.length ? ": " : ". Уроков пока нет — «Новый урок» у названия ▾.")));
  topics.forEach((x, i) => {
    const b = el("button", "linkbtn", x.title);
    b.onclick = () => {                     // идёт урок (план «Начать») — как в списке уроков: спросить
      if (A.S.live && !confirm("Идёт урок «" + L.title + "». Завершить его и открыть «" + x.title + "»?")) return;
      cmd({ cmd: "open", lesson: x.id, force: !!A.S.live });
    };
    line.appendChild(b);
    if (i < topics.length - 1) line.appendChild(document.createTextNode(", "));
  });
  banner.appendChild(line);
  banner.appendChild(el("small", "", "Заметки плана — заготовки: попадут в новые уроки по этому плану."));
}

export function renderTools() {
  renderPlanInfo();
  if (toolsBusy()) { headerStale = true; return; }
  const t = $("tools");
  t.innerHTML = "";
  const L = A.S && A.S.lesson;
  $("lessonsBtn").hidden = !A.S;
  if (!L) return;
  const P = A.S.print || {};
  const stages = stagesOf(A.items);
  const status = el("button", "chip");
  status.id = "status";
  status.onclick = () => { if (A.S && A.S.live) liveMenu(status); };     // и в «Подготовке» — урок же идёт
  t.appendChild(status);
  if (A.S.live) {                          // главные действия идущего урока — на виду, а не в меню
    const now_ = el("button", "primary nowbtn", "Начать сейчас");
    now_.id = "nowbtn";
    now_.title = "Урок назначен на позже — начать его прямо сейчас";
    now_.hidden = true;                    // видна, пока ждём назначенного начала (tick)
    now_.onclick = () => shiftWithUndo({ cmd: "shift_now" });
    t.appendChild(now_);
    const end = el("button", "endbtn", "Завершить урок");
    end.id = "endbtn";
    end.title = "Завершить урок: таймер «Эфира» закроется, экран учеников вернётся к фону";
    end.onclick = endLesson;
    t.appendChild(end);
  }
  if (BUSY.includes(P.state)) {
    const it = A.byId.get(P.block);
    const name = it ? (it.title || "Код") : "Код";
    t.appendChild(chip(`Печать · ${name} · ${Math.round((P.progress || 0) * 100)}%`, "warn printing"));
  }
  const seg = el("div", "seg modes");
  seg.setAttribute("role", "group");
  seg.setAttribute("aria-label", "Режим экрана");
  for (const [m, n, h] of [["prep", "Подготовка", "Правка урока на месте"], ["lesson", "Урок", "Ведение урока: время этапов, что печатается"]]) {
    const b = el("button", "", n);
    b.title = h;
    b.setAttribute("aria-pressed", A.mode === m ? "true" : "false");
    b.onclick = () => setMode(m, true);
    seg.appendChild(b);
  }
  t.appendChild(seg);
  // экран учеников — во второй строке, рядом с планом; идёт урок — и в «Подготовке» (правка опечатки на уроке)
  document.body.classList.toggle("is-live", !!A.S.live);
  if (A.mode === "lesson" || A.S.live) renderScreenCtl();
  if (A.mode === "lesson" && stages.length && !A.S.live && !stages.some((s) => s.minutes > 0)) {
    const pm = el("button", "warn", "Поставить минуты");     // подсказка — сразу кнопкой: в «Подготовку», к минутам
    pm.title = "Поставьте этапам минуты — тогда урок можно начать";
    pm.onclick = () => {
      setMode("prep", true);
      requestAnimationFrame(() => { const f = document.querySelector("#plan input.pmin"); if (f) { f.focus(); f.select(); } });
    };
    t.appendChild(pm);
  }
  if (A.mode === "lesson" && stages.length && !A.S.live && stages.some((s) => s.minutes > 0)) {
    const go = el("button", "primary", "Начать урок");
    go.title = "Урок начинается с этой минуты: этапы пойдут по часам";
    go.onclick = () => { if (mayReplace()) cmd({ cmd: "start", force: !!A.S.other_live }); };
    t.appendChild(go);
    const at = el("button", "", /^\d{1,2}:\d{2}$/.test(L.start || "") ? "Начать в " + L.start + " ▾" : "Начать в… ▾");
    at.title = "Начать урок в назначенное время: до начала таймер считает «до начала»";
    at.setAttribute("aria-label", "Начать урок в назначенное время");
    at.onclick = () => startAtMenu(at);
    t.appendChild(at);
  }
  const zb = el("button", "iconbtn only prefsbtn", "Аа");
  zb.title = "Мои настройки: размер текста, план, этапы";
  zb.setAttribute("aria-label", "Мои настройки");
  zb.onclick = () => prefsMenu(zb);
  t.appendChild(zb);
  const hasCode = A.items.some((x) => x.type === "code");
  const pb = el("button", "iconbtn");
  pb.hidden = !hasCode;                       // урок без кода — печатать нечего, кнопка не мешает
  pb.title = "Печать: режим, скорость, «как человек»";
  pb.appendChild(icon("gear"));
  pb.appendChild(el("span", "", "Печать"));
  pb.onclick = () => printMenu(pb);
  t.appendChild(pb);
  const mb = el("button", "iconbtn only");
  mb.title = "Ещё: обозначения, печать на бумагу, экспорт, оформление эфира";
  mb.setAttribute("aria-label", "Ещё");
  mb.appendChild(icon("more"));
  mb.onclick = () => moreMenu(mb);
  t.appendChild(mb);
  const sv = chip("", "save");
  sv.id = "saveChip";
  t.appendChild(sv);
  saveChip();
  $("kicker").textContent = (A.mode === "prep" ? "Подготовка урока" : "Урок") +
    (stages.length ? " · " + durText(stages.reduce((a, s) => a + s.minutes, 0)) + " · " + stages.length + " " + plural(stages.length, "этап", "этапа", "этапов") : "");
}

function saveChip() {
  const c = $("saveChip");
  if (!c) return;
  const n = Q.busy();
  c.classList.toggle("warn", Q.Q.offline && n > 0);
  c.textContent = n === 0 ? "✓ Сохранено" : Q.Q.offline ? `Нет связи — правки ждут (${n})` : "Сохраняю…";
  c.title = n === 0 ? "Все правки сохранены в программе" : Q.Q.offline ? "Правки сохранятся, когда программа снова будет на связи" : "";
}

// ---------------------------------------------------------------- время урока
function phaseOf(s, elapsed) {
  if (elapsed === null) return "";
  if (s.end <= s.start) return elapsed >= s.start ? "past" : "future";
  if (elapsed >= s.end) return "past";
  if (elapsed >= s.start) return "current";
  return "future";
}

function computeCurrent() {
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

// «Урок» ничего не сворачивает сам: все этапы раскрыты; свернуть — щелчком по этапу, «⋯ → Свернуть все этапы»
// или настройкой «Пройденные этапы: сворачивать»
function applyCollapse() {
  const { elapsed, stages } = computeCurrent();
  const pastCollapse = prefs().page_past === "collapse";
  for (const s of stages) {
    const st = $("st-" + s.id);
    if (!st) continue;
    let open = true;
    if (A.mode === "lesson") {
      if (s.id in A.userOpen) open = A.userOpen[s.id];
      else if (pastCollapse && elapsed !== null && phaseOf(s, elapsed) === "past") open = false;
    }
    st.classList.toggle("collapsed", !open);
  }
}

export function collapseStages(which) {
  const { elapsed, stages } = computeCurrent();
  for (const s of stages) {
    if (which === "all") A.userOpen[s.id] = false;
    else if (which === "none") A.userOpen[s.id] = true;
    else if (which === "past" && elapsed !== null && phaseOf(s, elapsed) === "past") A.userOpen[s.id] = false;
  }
  applyCollapse();
}

// план строкой: ‹ прошлый · ● текущий 3:12 из 8 · следующий (8) › · конец 19:30 · План ▾
function goStage(id) {
  const st = $("st-" + id);                // план, открытый «План ▾», остаётся сбоку — он текст не закрывает
  if (!st) return;
  A.userOpen[id] = true;
  applyCollapse();
  st.scrollIntoView({ behavior: "smooth", block: "start" });
}

function stripEl() {
  const s = $("strip");
  if (!s.firstChild) {
    for (const [cls, tag] of [["prev", "button"], ["cur", "button"], ["next", "button"], ["end", "span"], ["more", "button"], ["screen", "span"]]) {
      s.appendChild(el(tag, cls));
    }
    const more = s.querySelector(".more");
    more.textContent = "План ▾";
    more.title = "Весь план урока";
    s.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      if (b.classList.contains("more")) {
        const on = document.body.classList.toggle("plan-open");
        b.setAttribute("aria-pressed", on ? "true" : "false");
        return;
      }
      if (b.dataset.id) goStage(b.dataset.id);
    });
  }
  return s;
}

function renderStrip(elapsed, cur, stages) {
  const s = $("strip");
  s.hidden = false;                       // вторая строка «Урока»: план (по настройке) и экран учеников
  stripEl();
  const [pb, cb, nb, end] = ["prev", "cur", "next", "end"].map((c) => s.querySelector("." + c));
  s.classList.toggle("noplan", !stages.length);
  if (!stages.length) return;
  const set = (e, text, id) => {
    if (e.textContent !== text) e.textContent = text;
    e.hidden = !text;
    e.dataset.id = id || "";
  };
  const name = (x) => x.item.title || "Этап";
  const total = stages.reduce((a, x) => a + x.minutes, 0);
  const first = stages[0], last = stages[stages.length - 1];
  if (cur >= 0) {
    const c = stages[cur], pv = stages[cur - 1], nx = stages[cur + 1];
    const timer = prefs().page_stage_timer !== false ? " · осталось " + mmss((c.end - elapsed) * 60) : "";
    set(pb, pv ? "‹ " + name(pv) : "", pv && pv.id);
    set(cb, "● " + name(c) + timer, c.id);
    set(nb, nx ? name(nx) + " (" + nx.minutes + ") ›" : "", nx && nx.id);
  } else if (elapsed !== null && elapsed >= total) {
    set(pb, "‹ " + name(last), last.id);
    set(cb, "Урок окончен", "");
    set(nb, "", "");
  } else {
    set(pb, "", "");
    set(cb, elapsed !== null && elapsed < 0 ? "До начала " + mmss(-elapsed * 60) : "Не начат · " + durText(total), first.id);
    set(nb, name(first) + " (" + first.minutes + ") ›", first.id);
  }
  let endText = "";
  if (A.S && A.S.live) {
    endText = "Конец урока " + clockAt(A.S.live.anchor + total * 60000);
    const sh = A.S.live.shift || 0;
    if (sh) endText += (sh > 0 ? " · +" : " · −") + Math.abs(sh) + " мин";
  }
  set(end, endText, "");
}

// текущий этап вне экрана — плашка «↓ Идёт: …» (лента сама не прокручивается: учитель может дочитывать)
function updateNowbar(cur, stages) {
  const bar = $("nowbar");
  if (!bar) return;
  const s = cur >= 0 && A.mode === "lesson" ? stages[cur] : null;
  const st = s && $("st-" + s.id);
  let dir = "";
  if (st) {
    const z = parseFloat(document.documentElement.style.zoom) || 1;
    const r = st.getBoundingClientRect(), top = document.querySelector("header").getBoundingClientRect().bottom;
    if (r.top > innerHeight - 40 * z) dir = "↓";
    else if (r.bottom < top + 40 * z) dir = "↑";
  }
  bar.hidden = !dir;
  if (dir) {
    const text = dir + " Идёт: " + (s.item.title || "Этап");
    if (bar.textContent !== text) bar.textContent = text;
    bar.dataset.id = s.id;
  }
}
$("nowbar").addEventListener("click", () => {
  const st = $("st-" + $("nowbar").dataset.id);
  if (st) { A.userOpen[st.id.slice(3)] = true; applyCollapse(); st.scrollIntoView({ behavior: "smooth", block: "start" }); }
  $("nowbar").hidden = true;
});
window.addEventListener("scroll", () => { const c = computeCurrent(); updateNowbar(c.cur, c.stages); }, { passive: true });

// время этапа: урок идёт — часы от его начала; задано «Начать в 18:00» — часы от него; иначе — от начала урока
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

function tick() {
  const L = A.S && A.S.lesson;
  if (!L) return;
  const base = lessonBase();
  const status = $("status");
  const { elapsed, cur, next, stages } = computeCurrent();
  if (cur !== A.curIdx) {
    A.curIdx = cur;
    if (prefs().page_past === "collapse") {     // этап закончился — пройденные сворачиваются, даже если их раскрывали
      for (const s of stages) if (phaseOf(s, elapsed) === "past") delete A.userOpen[s.id];
    }
    applyCollapse();            // без «сворачивать пройденные» раскрытое учителем не трогаем
  }
  updateNowbar(cur, stages);
  renderStrip(elapsed, cur, stages);
  screenChip();
  for (const s of stages) {
    const st = $("st-" + s.id), pr = $("pr-" + s.id);
    if (!st) continue;
    const ph = phaseOf(s, elapsed);
    const ending = ph === "current" && (s.end - elapsed) * 60 <= 60;
    for (const x of [st, pr]) {
      if (!x) continue;
      x.classList.toggle("past", ph === "past");
      x.classList.toggle("current", ph === "current");
      x.classList.toggle("ending", ending);
    }
    const clock = st.querySelector(".clock");
    const c = stageClock(s, base);
    if (clock) {
      if (clock.textContent !== c.text) clock.textContent = c.text;
      clock.title = c.title;
    }
    const t = pr && pr.querySelector(".t");
    if (t) { t.textContent = c.from; t.title = c.title; }
    const lbl = st.querySelector(".left .lbl2"), big = st.querySelector(".left .big");
    if (!lbl) continue;
    if (ph === "current") {
      const left = (s.end - elapsed) * 60;
      const timer = prefs().page_stage_timer !== false && !document.body.classList.contains("plan-strip");
      lbl.textContent = !timer ? "Сейчас" : ending ? "Осталось меньше минуты" : "Сейчас · осталось";
      big.textContent = timer ? mmss(left) : "";
      const frac = Math.min(1, Math.max(0, (elapsed - s.start) / (s.end - s.start)));
      const bi = st.querySelector(":scope > .bar i");
      if (bi) bi.style.width = (frac * 100).toFixed(1) + "%";
      const pi = pr && pr.querySelector(".pbar2 i");
      if (pi) pi.style.width = (frac * 100).toFixed(1) + "%";
    } else if (ph === "past") {
      lbl.textContent = "Пройдено";
      big.textContent = "";
    } else {
      lbl.textContent = "";
      big.textContent = "";
    }
  }
  const total = stages.reduce((a, s) => a + s.minutes, 0);
  const endBtn = $("endbtn");               // время урока вышло — «Завершить урок» выделена
  const waiting = elapsed !== null && elapsed < 0;
  if (endBtn) {
    endBtn.classList.toggle("primary", elapsed !== null && elapsed >= total && total > 0);
    const want = waiting ? "Отменить начало" : "Завершить урок";
    if (endBtn.textContent !== want) endBtn.textContent = want;
  }
  const nowBtn = $("nowbtn");               // ждём «Начать в 18:00» — «Начать сейчас» на виду
  if (nowBtn) nowBtn.hidden = !waiting;
  const pt = document.querySelector("#plan .ptotal");
  if (pt) pt.textContent = durText(total);
  if (!status) return;
  if (!stages.length) {
    status.className = "chip";
    status.textContent = A.items.length ? "Урок без этапов" : "Урок пустой";
  } else if (elapsed === null) {
    status.className = "chip";
    status.textContent = A.mode === "prep" ? durText(total) : "Урок не начат";
  } else if (elapsed < 0) {
    status.className = "chip warn";
    status.textContent = "До начала · " + mmss(-elapsed * 60);
  } else if (elapsed >= total) {
    status.className = "chip";
    status.textContent = "Урок окончен · +" + mmss((elapsed - total) * 60);
  } else {
    status.className = "chip ok";
    status.innerHTML = '<span class="dot"></span>';
    status.appendChild(document.createTextNode("Урок идёт · " + mmss(elapsed * 60) + (A.mode === "lesson" ? " ▾" : "")));
  }
}
setInterval(tick, 1000);

// ---------------------------------------------------------------- щелчки по ленте
function openViewer(url, caption) {
  const v = $("viewer");
  v.querySelector("img").src = url;
  v.querySelector(".cap").textContent = caption || "";
  v.hidden = false;
}
$("viewer").onclick = () => { $("viewer").hidden = true; };
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("viewer").hidden = true; });

$("main").addEventListener("click", (e) => {
  const t = e.target;
  if (t.closest("a")) return;                       // ссылки в заметках открываются, правка не начинается
  const img = t.closest("figure img");
  if (img) { const it = A.byId.get(img.closest(".blk").dataset.id); openViewer(img.src, it && it.title); return; }
  const actBtn = t.closest("[data-act]");
  if (actBtn) {
    const a = actBtn.dataset.act;
    if (a === "break") {
      const it = A.byId.get(actBtn.dataset.stage);
      cmd({ cmd: "break", stage: actBtn.dataset.stage, minutes: it ? it.minutes : 10 });
    } else if (a === "exercise") cmd({ cmd: "exercise", stage: actBtn.dataset.stage || "", index: 0 });
    else if (a === "slide") cmd({ cmd: "slide", block: actBtn.closest(".blk").dataset.id });
    else if (a === "clear-sel") { const b = actBtn.closest(".blk"); E.setFields(b.dataset.id, { sel: [] }); }
    else if (a === "place-insert") E.pickImage(actBtn.closest(".blk").dataset.id, true);       // место → картинка
    else if (a === "open-tab") cmd({ cmd: "open_tab" });
    else if (a === "add-video") cmd({ cmd: "look_edit" });
    else if (a === "find-image") cmd({ cmd: "find_image", block: actBtn.closest(".blk").dataset.id });
    else if (a === "fill-slides") cmd({ cmd: "fill_slides" });
    return;
  }
  const arm = t.closest(".armbtn");
  if (arm) { cmd({ cmd: "arm", block: arm.closest(".blk").dataset.id }); return; }
  const blk = t.closest(".blk[data-id]");
  const sh = t.closest(".sh");
  if (A.mode !== "prep") {
    if (sh) {
      const st = sh.closest(".stage");
      const id = st.id.slice(3);
      A.userOpen[id] = st.classList.contains("collapsed");
      applyCollapse();
    }
    return;
  }
  // ---- «Подготовка»
  const ins = t.closest(".insbtn");
  if (ins) { E.insertMenu(ins, ins.closest(".ins").dataset.after); return; }
  if (sh) {
    const st = sh.closest(".stage");
    const it = A.byId.get(st.id.slice(3));
    if (!it) return;
    const fixedPlan = A.S.lesson && A.S.lesson.fixed;          // урок по плану: название этапа — из плана
    if (t.closest(".stitle")) {
      if (!fixedPlan) E.editStageTitle(t.closest(".stitle"), it);
      else toast("Название и вид этапа — из плана «" + A.S.lesson.plan.title + "»", "Изменить в плане",
        () => window.dispatchEvent(new Event("suflor:open-plan")));
    }
    else if (t.closest(".mins") && !t.closest(".mins.fixed")) E.editStageMinutes(t.closest(".mins"), it);
    else if (t.closest(".kindbtn")) E.kindMenu(t.closest(".kindbtn"), it);
    else if (t.closest(".smore")) E.stageMenu(t.closest(".smore"), it);
    return;
  }
  if (!blk) return;
  if (t.closest(".ned, .rtb")) return;              // щелчок внутри правки (поле, ответы, кнопки) — правка уже идёт
  const it = A.byId.get(blk.dataset.id);
  if (!it) return;
  E.selectBlock(it.id);
  if (t.closest(".bmore")) { E.blockMenu(t.closest(".bmore"), it); return; }
  if (t.closest(".grip")) return;
  if (t.closest(".rname") && it.type === "markdown") { E.roleMenu(t.closest(".rname"), it); return; }
  if (t.closest(".sub, .addtitle")) { E.editTitle(blk, it); return; }
  if (it.type === "markdown" && t.closest(".row > .c")) { E.beginNote(blk, it); return; }
  if (it.type === "code" && t.closest(".codebox")) { beginCode(blk, it, E.finishNoteOnly); return; }
});

$("main").addEventListener("mouseover", (e) => {
  const b = e.target.closest(".blk[data-id]");
  if (b) A.hovered = b.dataset.id;
});

// ---------------------------------------------------------------- план слева
$("plan").addEventListener("click", (e) => {
  const n = e.target.closest(".n");
  if (!n) return;
  const row = n.closest(".prow");
  const stages = stagesOf(A.items);
  const s = stages.find((x) => x.id === row.dataset.id);
  if (!s) return;
  goStage(s.id);              // щелчок по этапу — только перейти к нему; сдвинуть время — «Урок идёт ▾» (с «Вернуть»)
});

function commitPlanMinutes(inp) {
  const row = inp.closest(".prow");
  const it = row && A.byId.get(row.dataset.id);
  const n = E.parseMinutes(inp.value);
  if (!it || n === null) { if (it) inp.value = String(it.minutes || 0); return; }
  if (n !== (it.minutes || 0)) E.setFields(it.id, { minutes: n });
}
$("plan").addEventListener("keydown", (e) => {
  const inp = e.target.closest(".pmin");
  if (!inp) return;
  if (e.key === "Enter") { e.preventDefault(); commitPlanMinutes(inp); inp.blur(); }
  else if (e.key === "Escape") { const it = A.byId.get(inp.closest(".prow").dataset.id); inp.value = String(it ? it.minutes : 0); inp.blur(); }
});
$("plan").addEventListener("focusout", (e) => {
  const inp = e.target.closest(".pmin");
  if (inp && inp.isConnected) commitPlanMinutes(inp);
  setTimeout(() => { const fa = document.activeElement;
    if ($("plan").dataset.stale && !($("plan").contains(fa) && fa.matches("input, textarea"))) renderPlan(); }, 0);
});
$("plan").addEventListener("input", (e) => {
  const inp = e.target.closest(".pmin");
  if (inp) inp.value = inp.value.replace(/[^\d]/g, "").slice(0, 3);
});

let dragStage = null;
$("plan").addEventListener("dragstart", (e) => {
  const row = e.target.closest(".prow");
  if (!row || A.mode !== "prep") return;
  dragStage = row.dataset.id;
  e.dataTransfer.effectAllowed = "move";
  e.dataTransfer.setData("text/plain", "");
  row.classList.add("dragging");
});
$("plan").addEventListener("dragover", (e) => {
  if (!dragStage) return;
  const row = e.target.closest(".prow");
  if (!row) return;
  e.preventDefault();
  document.querySelectorAll(".prow.drop-above, .prow.drop-below").forEach((x) => x.classList.remove("drop-above", "drop-below"));
  const r = row.getBoundingClientRect();
  row.classList.add(e.clientY < r.top + r.height / 2 ? "drop-above" : "drop-below");
});
$("plan").addEventListener("drop", (e) => {
  if (!dragStage) return;
  e.preventDefault();
  const row = e.target.closest(".prow");
  const stages = stagesOf(A.items).map((s) => s.id);
  if (row && row.dataset.id !== dragStage) {
    const r = row.getBoundingClientRect();
    const below = e.clientY >= r.top + r.height / 2;
    const k = stages.indexOf(row.dataset.id);
    let after = below ? row.dataset.id : (k > 0 ? stages[k - 1] : "");
    if (after === dragStage) after = stages[stages.indexOf(dragStage) - 1] || "";
    E.moveStage(dragStage, after);
  }
  dragStage = null;
});
$("plan").addEventListener("dragend", () => {
  dragStage = null;
  document.querySelectorAll(".prow.dragging, .prow.drop-above, .prow.drop-below").forEach((x) => x.classList.remove("dragging", "drop-above", "drop-below"));
});

// ---------------------------------------------------------------- перенос блоков и файлы
let dragBlock = null;
const main = $("main");
main.addEventListener("dragstart", (e) => {
  const g = e.target.closest(".grip");
  if (!g || A.mode !== "prep") return;
  dragBlock = g.closest(".blk").dataset.id;
  e.dataTransfer.effectAllowed = "move";
  e.dataTransfer.setData("text/plain", "");
  g.closest(".blk").classList.add("dragging");
});
function clearDrop() { document.querySelectorAll(".drop-before, .drop-after").forEach((x) => x.classList.remove("drop-before", "drop-after")); }
main.addEventListener("dragover", (e) => {
  if (A.mode !== "prep") return;
  const files = [...(e.dataTransfer.types || [])].includes("Files");
  if (!dragBlock && !files) return;
  e.preventDefault();
  clearDrop();
  const b = e.target.closest(".blk[data-id]");
  if (b) { const r = b.getBoundingClientRect(); b.classList.add(e.clientY > r.top + r.height / 2 ? "drop-after" : "drop-before"); }
});
main.addEventListener("dragleave", (e) => { if (!main.contains(e.relatedTarget)) clearDrop(); });
main.addEventListener("drop", (e) => {
  if (A.mode !== "prep") return;
  clearDrop();
  const after = E.dropAfter(e.clientY, e.target);
  if (dragBlock) {
    e.preventDefault();
    const id = dragBlock;
    dragBlock = null;
    document.querySelector(".blk.dragging")?.classList.remove("dragging");
    if (after === null || after === id) return;
    const i = A.items.findIndex((x) => x.id === id);
    const prev = i > 0 ? A.items[i - 1].id : "";
    if (after === prev) return;
    E.act({ op: "move", block: id, after }, { op: "move", block: id, after: prev });
    return;
  }
  const files = [...(e.dataTransfer.files || [])].filter((f) => /^image\/(png|jpeg|gif|webp)$/.test(f.type));
  if (!files.length) return;
  e.preventDefault();
  let place = after === null ? E.pastePlace() : after;
  (async () => { for (const f of files) await E.uploadImage(f, place); })();
});
main.addEventListener("dragend", () => { dragBlock = null; clearDrop(); document.querySelector(".blk.dragging")?.classList.remove("dragging"); });

document.addEventListener("paste", (e) => {
  if (A.mode !== "prep" || isTyping(e.target)) return;
  const f = [...(e.clipboardData && e.clipboardData.items || [])].find((x) => x.kind === "file" && /^image\//.test(x.type));
  if (!f) return;
  e.preventDefault();
  const sel = A.selected && A.byId.get(A.selected);
  if (sel && sel.type === "image" && sel.place) { E.uploadImage(f.getAsFile(), sel.id, sel.id); return; }   // выбрано место — заменить
  E.uploadImage(f.getAsFile(), E.pastePlace());
});

// кликер презентации в «Уроке»: ◀ ▶ / PageUp / PageDown — слайды ученикам, B или «.» — фон
const NEXT_KEYS = new Set(["ArrowRight", "PageDown"]), PREV_KEYS = new Set(["ArrowLeft", "PageUp"]);
document.addEventListener("keydown", (e) => {
  if (A.mode !== "lesson" || isTyping(e.target) || e.ctrlKey || e.altKey || e.metaKey) return;
  if (document.querySelector(".modal")) return;                            // открыто окно — клавиши ему
  if (!A.items.some((x) => x.type === "image" && x.url)) return;           // без картинок — обычная прокрутка
  const slides = A.items.some((x) => x.type === "image" && x.slide);
  if (!slides && (e.key === "PageDown" || e.key === "PageUp")) return;     // только картинки — PageUp/Down листают ленту
  if (NEXT_KEYS.has(e.key) || PREV_KEYS.has(e.key)) {
    e.preventDefault();
    cmd({ cmd: "slide_step", d: NEXT_KEYS.has(e.key) ? 1 : -1 });
  } else if (["b", "B", "и", "И", ".", "ю"].includes(e.key)) {
    e.preventDefault();
    cmd({ cmd: "background" });
  }
});

document.addEventListener("keydown", (e) => {
  if (A.mode !== "prep" || isTyping(e.target)) return;
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === "z") { e.preventDefault(); E.undo(); return; }
  if (!A.selected) return;
  if (e.key === "Delete") { e.preventDefault(); E.deleteBlock(A.selected); }
  else if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) { e.preventDefault(); E.moveBlock(A.selected, e.key === "ArrowDown" ? 1 : -1); }
  else if (e.key === "Escape") E.selectBlock(null);
  else if (e.key === "Enter") {
    const it = A.byId.get(A.selected), n = nodeOf(A.selected);
    if (it && n) { e.preventDefault(); if (it.type === "markdown") E.beginNote(n, it); else if (it.type === "code") beginCode(n, it, E.finishNoteOnly); }
  }
});

// название урока: щелчок в «Подготовке» — переименовать; ▾ — другие уроки
$("titleText").addEventListener("click", () => {
  if (A.mode !== "prep" || !A.S || !A.S.lesson) return;
  E.inlineInput($("titleText"), A.title, (v) => { if (v.trim()) E.act({ op: "set_lesson", title: v.trim() }, { op: "set_lesson", title: A.title }); },
    { cls: "inl-h1", label: "Название урока" });
});
$("lessonsBtn").addEventListener("click", () => lessonsMenu($("lessonsBtn")));

// ---------------------------------------------------------------- связь с программой
Q.Q.onChange = saveChip;
Q.Q.onError = (text) => toast(text);
window.__suflor = { push: Q.push, busy: Q.busy };     // для проверок: правка в очередь, сколько ждёт

// урок по плану → открыть план (идёт урок — как переход к другому уроку: спросить, завершить ли)
function openPlan() {
  const L = A.S && A.S.lesson;
  if (!L || !L.plan) return;
  if (A.S.live && !confirm("Идёт урок «" + L.title + "». Завершить его и открыть «" + L.plan.title + "»?")) return;
  cmd({ cmd: "open", lesson: L.plan.id, force: !!A.S.live });
  setMode("prep", true);
}
window.addEventListener("suflor:open-plan", openPlan);
window.addEventListener("suflor:pin-plan", (e) => {       // «Закрепить сбоку» / «В строку» в шапке плана
  document.body.classList.remove("plan-open");
  setPref("page_plan", e.detail);
});
$("planlink").addEventListener("click", openPlan);
Q.Q.onResult = (res) => {
  for (const [id, it] of Object.entries(res.items || {})) {
    if (it) A.fresh.set(id, it);
    released(id);
  }
  refresh();
};

let lastTools = "";
function apply(state) {
  const t0 = performance.now();
  document.body.classList.toggle("light", state.dark === false);
  A.offset = (state.server_now || Date.now()) - Date.now();
  const prev = A.S;
  const prevId = prev && prev.lesson ? prev.lesson.id : null;
  A.S = state;
  const n = state.notice;                   // сообщение программы — тостом здесь (окно программы обычно скрыто)
  if (n && typeof n.seq === "number") {
    if (A.noticeSeq !== undefined && n.seq > A.noticeSeq && n.text) toast(n.text, null, null, n.warn ? 10000 : 6000);
    A.noticeSeq = n.seq;
  }
  const id = state.lesson ? state.lesson.id : null;
  if (id !== prevId) {
    E.finishEditing();
    A.undo = [];
    A.fresh.clear();
    A.curIdx = -2;
    A.userOpen = {};
    A.selected = null;
    if (id) Q.useLesson(id);
    window.scrollTo(0, 0);
  }
  if (state.live && !(prev && prev.live) && A.mode !== "lesson") setMode("lesson");
  // слайд у учеников сменился (учитель листает) — «я здесь»: лента показывает этот слайд
  const sb = state.efir && state.efir.mode === "slide" ? state.efir.slide_bid : "";
  if (sb && sb !== A.slideBid && A.mode === "lesson") {
    const owner = stageOfBlock(sb);                       // слайд в свёрнутом этапе — этап раскрыть
    if (owner && A.userOpen[owner] === false) { A.userOpen[owner] = true; applyCollapse(); }
    requestAnimationFrame(() => nodeOf(sb)?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }
  A.slideBid = sb;
  applyPrefs();
  rebuildItems();
  const key = JSON.stringify([A.title, state.live, state.efir, state.print && [state.print.state, state.print.block, Math.round((state.print.progress || 0) * 50)],
    state.lessons && state.lessons.length, A.mode, state.lesson && state.lesson.presets, state.lesson && state.lesson.preset, A.items.length]);
  if (key !== lastTools) { lastTools = key; renderTools(); }
  legend();
  refresh();
  window.__applyMs = performance.now() - t0;      // тест скорости: урок на 90 блоков — быстрее 300 мс
  window.__ready = true;
}

function connect() {
  const es = new EventSource("/events?ch=lesson");
  es.onmessage = (e) => {
    $("offline").hidden = true;
    try { apply(JSON.parse(e.data)); } catch (err) { console.error(err); }
  };
  es.onopen = () => { $("offline").hidden = true; Q.retryNow(); };
  es.onerror = () => { $("offline").hidden = false; };
}

let saved = "prep";
try { saved = localStorage.getItem("suflor.mode") || "prep"; } catch (e) { /* нет хранилища */ }
A.mode = saved === "lesson" ? "lesson" : "prep";
document.body.classList.add("mode-" + A.mode);
window.addEventListener("beforeunload", () => Q.flushDrafts());
// высота шапки (в «Уроке» кнопки переносятся на вторую строку) — для плана и прокрутки к этапу
new ResizeObserver(() => document.documentElement.style.setProperty("--hh", document.querySelector("header").offsetHeight + "px"))
  .observe(document.querySelector("header"));
connect();
