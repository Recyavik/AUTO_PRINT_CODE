// «Эфир» — вебинар по расписанию (без урока). Две вкладки:
//  «Расписания» (#/efir, #/efir/<id>, #/efir/<id>/edit, #/efir/new): список слева, справа — повестка, «Запустить»,
//   оформление; правка на месте (вид блока угадывается по названию, пока не выбран руками; уйти с несохранённым —
//   вопрос); «Новый эфир»: пусто, по описанию (нейросеть), вставить текст, файл JSON, из «Таймера вебинара»;
//  «Оформления» (#/efir/looks, #/efir/looks/<id>): фон, надпись, зарядки (нет файла — «Заменить…»), экран перерыва,
//   шрифт, цвет; любая правка — «есть изменения»; файлы снаружи — «Скопировать в программу»;
//  идущий вебинар (#/efir/live): табло, повестка, экран учеников, «Завершить эфир».
"use strict";
import { S, send, call, go, now } from "./core.js";
import { h, btn, iconBtn, seg, toggle, field, numberField, select, popover, menu, ask, toast, clear, closePop, tip } from "./ui.js";
import { icon } from "./icons.js";
import { setCrumbs } from "./shell.js";
import { menuAt } from "./lessonmenu.js";
import { jobsBox } from "./jobsbox.js";
import { mmss, clockAt, durText, plural, hm } from "../lesson/state.js";

const KINDS = [["", "Обычный"], ["break", "Перерыв"], ["exercise", "Зарядка"]];
const DEMOS = [["on", "экран вкл"], ["off", "экран выкл"], ["none", "не важно"]];
const BREAK_RE = /перерыв|break/i, EX_RE = /заряд|глаз|гимнаст|физкульт|разминк/i;
const guessKind = (name) => (BREAK_RE.test(name || "") ? "break" : EX_RE.test(name || "") ? "exercise" : "");
const fail = (e) => toast(String((e && e.message) || e), { warn: true });
const ef = () => S.efir || {};
const webinars = () => ef().webinars || [];
const looks = () => ef().looks || [];
const mb = (n) => (n >= 1048576 ? (n / 1048576).toFixed(1) + " МБ" : Math.max(1, Math.round(n / 1024)) + " КБ");
const safeName = (s) => (s || "").replace(/[\\/:*?"<>|]/g, "").trim() || "эфир";

let E = null;            // открытый экран: {hash, dirty, part, update}

function crumbs(extra) { setCrumbs([{ label: "Эфир", href: "#/efir" }, ...(extra ? [{ label: extra }] : [])]); }

// ---------------------------------------------------------------- «Запустить»
function slots() {
  const d = new Date(now());
  d.setSeconds(0, 0);
  const out = [];
  d.setMinutes(d.getMinutes() < 30 ? 30 : 60);
  for (let i = 0; i < 2; i++) { out.push(String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0")); d.setMinutes(d.getMinutes() + 30); }
  return out;
}

async function launch(w, start) {
  closePop();
  try {
    let r = await call({ cmd: "efir_launch", id: w.id, start });
    if (!r.ok && r.other) {
      if (!(await ask("Сейчас идёт «" + r.other + "». Завершить его и начать «" + w.title + "»?", { title: "Идёт эфир", ok: "Завершить и начать", danger: true }))) return;
      r = await call({ cmd: "efir_launch", id: w.id, start, force: true });
    }
    if (r.ok) go("#/efir/live");
  } catch (e) { fail(e); }
}

function launchPanel(anchor, w) {
  const at = h("input", { class: "inp mono", type: "time", id: "launchAt", "aria-label": "Начать в это время" });
  at.value = w.start || slots()[0];
  const goBtn = btn("Начать", { kind: "primary", onClick: () => at.value && launch(w, at.value) });
  goBtn.id = "launchGo";
  at.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); goBtn.click(); } });
  const b = (cls, text, start, hint) => { const x = btn(text, { cls, onClick: () => launch(w, start) }); if (hint) x.title = hint; return x; };
  const row = h("div", { class: "lrow" }, b("lnow", "Сейчас", ""), ...slots().map((t) => b("lslot mono", t, t)));
  const past = w.start && !slots().includes(w.start) ? b("lpast", "Как в прошлый раз · " + w.start, w.start) : null;
  popover(anchor, h("div", { class: "launchpanel" }, h("div", { class: "phead" }, "Запустить «" + w.title + "»"), row, past,
    h("div", { class: "zrow" }, at, goBtn), h("p", { class: "meta" }, "До начала таймер считает «до начала». Время из прошлого (в пределах 6 часов) — эфир уже идёт.")),
  { focus: false });
}

// ---------------------------------------------------------------- список расписаний
function chain(w) {
  const bar = h("div", { class: "wchain", "aria-hidden": "true" });
  for (const a of w.schedule) bar.append(h("i", { class: a.kind === "break" ? "br" : a.kind === "exercise" ? "ex" : "", style: { flexGrow: String(Math.max(1, a.min)) } }));
  return bar;
}

function metaText(w) {
  const n = w.schedule.length;
  const brk = w.schedule.filter((a) => a.kind === "break").reduce((x, a) => x + a.min, 0);
  return durText(w.total) + " · " + n + " " + plural(n, "блок", "блока", "блоков") + (brk ? " · перерыв " + brk + " мин" : "") + (w.look ? " · " + w.look : "");
}

function webinarMenu(w) {
  return [
    { label: "Сделать копию", icon: "copy", on: async () => { try { const r = await call({ cmd: "efir_copy_webinar", id: w.id }); if (r.id) go("#/efir/" + r.id); } catch (e) { fail(e); } } },
    { label: "Экспорт в JSON…", icon: "download", on: () => exportJson(w) },
    { label: "Скопировать для нейросети", icon: "sparkles", hint: "задание с этим расписанием как примером", on: () => call({ cmd: "efir_ai_prompt", id: w.id }).catch(fail) },
    { label: "Выше", icon: "chevron-up", on: () => send({ cmd: "efir_move", id: w.id, d: -1 }) },
    { label: "Ниже", icon: "chevron-down", on: () => send({ cmd: "efir_move", id: w.id, d: 1 }) },
    { sep: true },
    { label: "Удалить…", icon: "trash", danger: true, on: async () => {
      const live = ef().live_id === w.id ? " Эфир идёт — он завершится." : "";
      if (!(await ask("Удалить расписание «" + w.title + "»?" + live, { title: "Удалить расписание", ok: "Удалить", danger: true }))) return;
      try { await call({ cmd: "efir_delete_webinar", id: w.id }); go("#/efir"); } catch (e) { fail(e); }
    } },
  ];
}

async function exportJson(w) {
  try {
    const path = await call({ cmd: "pick_save", name: safeName(w ? w.title : "Расписания эфира") + ".json", filter: "JSON (*.json)", title: "Экспорт в JSON" });
    if (path) await call({ cmd: "efir_export", id: w ? w.id : "", path });
  } catch (e) { fail(e); }
}

function listBox(selId) {
  const box = h("div", { id: "wlist", class: "wlist2", role: "list" });
  const draw = () => {
    clear(box);
    const ws = webinars();
    if (!ws.length) box.append(h("p", { class: "dim empty" }, "Расписаний пока нет — «Новый эфир»."));
    for (const w of ws) {
      const it = h("button", { class: "witem" + (w.id === selId() ? " on" : ""), type: "button", role: "listitem", "data-id": w.id },
        h("div", { class: "wih" }, h("b", null, w.title), w.live ? h("span", { class: "livemark" }, "● идёт") : null),
        h("span", { class: "meta" }, metaText(w)), chain(w));
      it.addEventListener("click", () => go("#/efir/" + w.id));
      it.addEventListener("contextmenu", (e) => menuAt(e, webinarMenu(w)));
      box.append(it);
    }
  };
  draw();
  return { el: box, draw };
}

// ---------------------------------------------------------------- расписание: просмотр
function lookThumbs(lk) {
  if (!lk) return h("p", { class: "dim" }, "Оформление не выбрано");
  const sw = (bg, label) => {
    const el = h("div", { class: "lt-sw" });
    if (bg.kind === "image" && bg.url) el.style.backgroundImage = `url("${bg.url}")`;
    else if (bg.kind === "color") el.style.background = bg.value.slice(6);
    else if (bg.kind === "anim") el.classList.add("anim");
    return h("div", { class: "lt" }, el, h("span", null, label));
  };
  const n = lk.exercises.length;
  return h("div", { class: "lthumbs" }, sw(lk.background, "Фон"), sw(lk.break_background.value ? lk.break_background : lk.background, "Заставка перерыва"),
    h("div", { class: "lt" }, h("div", { class: "lt-sw ex" }, icon("activity")), h("span", null, "Зарядки · " + n + " " + plural(n, "видео", "видео", "видео"))));
}

function detail(box, w) {
  crumbs(w.title);
  const lk = looks().find((l) => l.id === w.look_id);
  const live = ef().live_id === w.id;
  const launchBtn = live ? btn("Открыть эфир", { kind: "primary", icon: "radio", onClick: () => go("#/efir/live") })
    : btn("Запустить", { kind: "primary", icon: "play", onClick: () => launchPanel(launchBtn, w) });
  launchBtn.id = "launchBtn";
  const edit = btn("Изменить", { icon: "pencil", onClick: () => go("#/efir/" + w.id + "/edit") });
  edit.id = "editBtn";
  const more = iconBtn("chevron-down", "Меню расписания", () => menu(more, webinarMenu(w), { align: "right" }), { kind: "ghost" });
  more.id = "wmenuBtn";
  const agenda = h("div", { id: "wagenda", class: "wagenda" });
  let t = 0;
  for (const a of w.schedule) {
    agenda.append(h("div", { class: "arow" + (a.kind ? " k-" + a.kind : "") },
      h("span", { class: "t mono" }, hm(t)), icon(a.kind === "break" ? "cup" : a.kind === "exercise" ? "activity" : "stage", "sm"),
      h("span", { class: "n" }, a.name), h("span", { class: "m mono" }, a.min + " мин"),
      h("span", { class: "demo " + a.demo, title: a.demo === "on" ? "Демонстрация экрана включена" : a.demo === "off" ? "Демонстрация выключена" : "Демонстрация — не важно" })));
    t += a.min;
  }
  const lookSel = select([["", "— без оформления —"], ...looks().map((l) => [l.id, l.title])], w.look_id, async (v) => {
    try { await call({ cmd: "efir_put_webinar", webinar: { ...w, look_id: v } }); } catch (e) { fail(e); }
  }, { label: "Оформление" });
  lookSel.id = "wlookSel";
  const lkEdit = h("button", { class: "linkbtn", type: "button" }, "Изменить оформление");
  lkEdit.addEventListener("click", () => w.look_id && go("#/efir/looks/" + w.look_id));
  box.append(h("div", { id: "wdetail", class: "wdetail" },
    h("div", { class: "wdh" }, h("div", { class: "wdt" }, h("h2", { class: "wtitle" }, w.title), h("span", { class: "meta wmeta" }, metaText(w) + " · начало " + w.start)),
      launchBtn, edit, more),
    h("h3", { class: "efh3" }, "Повестка"), agenda,
    h("div", { class: "wlooks" }, h("div", { class: "wlh" }, h("h3", { class: "efh3" }, "Оформление"), lookSel, lkEdit), lookThumbs(lk))));
}

// ---------------------------------------------------------------- расписание: правка
function editor(box, w) {
  crumbs(w.title);
  const d = { id: w.id, title: w.title, start: w.start, break_min: w.break_min, look_id: w.look_id,
    rows: w.schedule.map((a) => ({ ...a, manual: true })) };
  const dirty = () => { E.dirty = true; saveBtn.disabled = false; };
  const title = h("input", { class: "inp", id: "wtitle", value: d.title, "aria-label": "Название" });
  title.addEventListener("input", () => { d.title = title.value; dirty(); });
  const look = select([["", "— без оформления —"], ...looks().map((l) => [l.id, l.title])], d.look_id, (v) => { d.look_id = v; dirty(); }, { label: "Оформление" });
  look.id = "wlook";
  const rows = h("div", { id: "wrows", class: "wrows" });
  function draw() {
    clear(rows);
    let t = 0;
    d.rows.forEach((a, i) => {
      const n = h("input", { class: "inp rn", value: a.name, "aria-label": "Название блока" });
      const m = numberField(a.min, { min: 1, max: 600, step: 1, unit: "мин", label: "Минуты" });
      m.input.classList.add("rm");
      const k = select(KINDS, a.kind || "", (v) => { a.kind = v; a.manual = true; dirty(); draw(); }, { label: "Вид" });
      k.classList.add("rk");
      const dm = select(DEMOS, a.demo || "on", (v) => { a.demo = v; dirty(); }, { label: "Демонстрация экрана" });
      dm.classList.add("rd");
      n.addEventListener("input", () => {
        a.name = n.value;
        if (!a.manual) { a.kind = guessKind(a.name); k.value = a.kind; }       // вид — по названию, пока не выбран руками
        dirty();
      });
      m.input.addEventListener("input", () => { a.min = Math.max(1, parseInt(m.input.value, 10) || 1); dirty(); });
      const mv = (dir) => { const j = i + dir; if (j < 0 || j >= d.rows.length) return; [d.rows[i], d.rows[j]] = [d.rows[j], d.rows[i]]; dirty(); draw(); };
      const up = iconBtn("chevron-up", "Выше", () => mv(-1), { size: "sm", kind: "ghost", cls: "up" });
      const down = iconBtn("chevron-down", "Ниже", () => mv(1), { size: "sm", kind: "ghost", cls: "down" });
      const add = iconBtn("plus", "Добавить ниже", () => { d.rows.splice(i + 1, 0, { name: "", min: 5, kind: "", demo: "on", manual: false }); dirty(); draw(); }, { size: "sm", kind: "ghost", cls: "add" });
      const del = iconBtn("trash", "Удалить блок", () => { d.rows.splice(i, 1); dirty(); draw(); }, { size: "sm", kind: "ghost", cls: "del" });
      up.disabled = i === 0;
      down.disabled = i === d.rows.length - 1;
      del.disabled = d.rows.length === 1;                     // минимум один блок
      rows.append(h("div", { class: "wrow" + (a.kind ? " k-" + a.kind : "") }, h("span", { class: "t mono" }, hm(t)), n, m, k, dm, h("span", { class: "racts" }, up, down, add, del)));
      t += a.min;
    });
  }
  draw();
  const addBlock = btn("Добавить блок", { icon: "plus", kind: "ghost", onClick: () => { d.rows.push({ name: "", min: 5, kind: "", demo: "on", manual: false }); dirty(); draw(); rows.lastChild.querySelector(".rn").focus(); } });
  addBlock.id = "addBlock";
  const brk = numberField(d.break_min, { min: 1, max: 180, unit: "мин", label: "Перерыв по умолчанию", onChange: (v) => { d.break_min = v; dirty(); } });
  brk.input.id = "breakDefault";
  const exp = btn("Экспорт JSON…", { icon: "download", kind: "ghost", size: "sm", onClick: () => exportJson(w) });
  exp.id = "wexport";
  const aiBtn = btn("Для нейросети", { icon: "sparkles", kind: "ghost", size: "sm", onClick: () => call({ cmd: "efir_ai_prompt", id: w.id }).catch(fail) });
  aiBtn.id = "wai";
  const cancel = btn("Отмена", { kind: "ghost", onClick: () => { E.dirty = false; go("#/efir/" + w.id); } });
  cancel.id = "wcancel";
  const saveBtn = btn("Сохранить", { kind: "primary", onClick: async () => {
    const empty = d.rows.filter((a) => !a.name.trim());
    if (empty.length) { toast("У каждого блока нужно название", { warn: true }); return; }
    try {
      await call({ cmd: "efir_put_webinar", webinar: { id: d.id, title: d.title, start: d.start, break_min: d.break_min, look_id: d.look_id,
        schedule: d.rows.map((a) => ({ name: a.name.trim(), min: a.min, kind: a.kind || "", demo: a.demo || "on" })) } });
      E.dirty = false;
      go("#/efir/" + d.id);
    } catch (e) { fail(e); }
  } });
  saveBtn.id = "wsave";
  box.append(h("div", { id: "wedit", class: "wdetail wedit" }, h("h2", null, "Правка расписания"),
    h("div", { class: "ef2" }, field("Название", title), field("Оформление", look)),
    rows, h("div", { class: "wtools" }, addBlock, h("span", { class: "spacer" }), field("Перерыв по умолчанию", brk), exp, aiBtn),
    h("div", { class: "effoot" }, cancel, h("span", { class: "spacer" }), saveBtn)));
}

// ---------------------------------------------------------------- «Новый эфир»
function newPanel(box) {
  crumbs("Новый эфир");
  const opts = [
    { how: "empty", icon: "plus", title: "Пусто", sub: "образец расписания — поправите под себя" },
    { how: "ai", icon: "sparkles", title: "По описанию — нейросеть", sub: "опишите словами, что и сколько минут" },
    { how: "paste", icon: "clipboard", title: "Вставить текст", sub: "JSON или ответ нейросети" },
    { how: "json", icon: "file", title: "Из файла JSON", sub: "экспорт этой программы или «Повестки эфира»" },
  ];
  if (ef().legacy_found) opts.push({ how: "legacy", icon: "folder", title: "Из «Таймера вебинара»", sub: "перенести шаблоны старой программы" });
  const area = h("div", { class: "newarea" });
  const create = async (d) => {
    try {
      const r = await call({ cmd: "efir_new", ...d });
      if (r.ids && r.ids.length) go("#/efir/" + r.ids[0] + (d.how === "empty" ? "/edit" : ""));
      else if (d.how === "legacy") toast("В «Таймере вебинара» новых шаблонов нет");
    } catch (e) { fail(e); }
  };
  const showArea = (how) => {
    clear(area);
    if (how === "ai") {
      const ta = h("textarea", { id: "newDesc", class: "ta", rows: "5", placeholder: "Например: пара 90 минут — приветствие 5, теория 30, зарядка для глаз 5, перерыв 10, практика 35, выводы 5. Начало в 11:00." });
      const goBtn = btn("Составить", { kind: "primary", icon: "sparkles", onClick: async () => {
        try {
          const r = await call({ cmd: "efir_ai", text: ta.value });
          if (r.copied) toast("Нейросеть не подключена — задание с описанием скопировано: вставьте его в свой чат, ответ — «Вставить текст»", { ms: 9000 });
        } catch (e) { fail(e); }
      } });
      goBtn.id = "newAiGo";
      area.append(field("Описание эфира", ta), h("div", { class: "wrow2" }, goBtn), jobsBox("").el);
      ta.focus();
    } else if (how === "paste") {
      const ta = h("textarea", { id: "newPaste", class: "ta mono", rows: "8", placeholder: "JSON расписания или ответ нейросети целиком" });
      const goBtn = btn("Добавить", { kind: "primary", onClick: () => ta.value.trim() ? create({ how: "paste", text: ta.value }) : ta.focus() });
      goBtn.id = "newPasteGo";
      const copy = btn("Скопировать задание с примером", { icon: "copy", kind: "ghost", onClick: () => call({ cmd: "efir_ai_prompt" }).catch(fail) });
      area.append(field("Текст", ta), h("div", { class: "wrow2" }, copy, h("span", { class: "spacer" }), goBtn));
      ta.focus();
    }
  };
  const cards = h("div", { id: "wnew", class: "newopts" });
  for (const o of opts) {
    const c = h("button", { class: "newopt", type: "button", "data-how": o.how }, icon(o.icon), h("b", null, o.title), h("span", { class: "meta" }, o.sub));
    c.addEventListener("click", async () => {
      cards.querySelectorAll(".newopt").forEach((x) => x.setAttribute("aria-pressed", String(x === c)));
      if (o.how === "empty" || o.how === "legacy") create({ how: o.how });
      else if (o.how === "json") {
        try { const ps = await call({ cmd: "pick_files", purpose: "json" }); if (ps && ps.length) create({ how: "json", path: ps[0] }); } catch (e) { fail(e); }
      } else showArea(o.how);
    });
    cards.append(c);
  }
  box.append(h("div", { class: "wdetail" }, h("h2", null, "Новый эфир"), cards, area));
}

// ---------------------------------------------------------------- оформления
function bgOptions(cur, onPick, o = {}) {
  const box = h("div", { class: "bgopts", id: o.id || null, role: "radiogroup" });
  const opt = (value, label, swatch) => {
    const b = h("button", { class: "bgopt", type: "button", "data-value": value, "aria-pressed": String(cur() === value) }, swatch, h("span", null, label));
    b.addEventListener("click", () => onPick(value));
    return b;
  };
  const draw = () => {
    clear(box);
    if (o.inherit) box.append(opt("", "Как основной", h("i", { class: "sw inh" })));
    box.append(opt("color:#000000", "Чёрный", h("i", { class: "sw", style: { background: "#000" } })));
    for (const [k, t] of ef().animations || []) box.append(opt("anim:" + k, t, h("i", { class: "sw anim a-" + k })));
    const v = cur();
    const colorVal = v.startsWith("color:") && v !== "color:#000000" ? v.slice(6) : "#1E3A5F";
    const ci = h("input", { type: "color", value: colorVal, class: "colorin", "aria-label": "Свой цвет" });
    ci.addEventListener("input", () => onPick("color:" + ci.value.toUpperCase()));
    const own = h("label", { class: "bgopt" + (v.startsWith("color:") && v !== "color:#000000" ? " on" : ""), "aria-pressed": String(v.startsWith("color:") && v !== "color:#000000") }, ci, h("span", null, "Свой цвет…"));
    box.append(own);
    const imgOn = v.startsWith("image:");
    const img = h("button", { class: "bgopt", type: "button", "data-value": "image", "aria-pressed": String(imgOn) }, icon("image"), h("span", null, "Картинка…"));
    img.addEventListener("click", async () => {
      try {
        const ps = await call({ cmd: "pick_files", purpose: "background" });
        if (ps && ps.length) { const r = await call({ cmd: "efir_take_file", path: ps[0] }); onPick("image:" + r.path, r); }
      } catch (e) { fail(e); }
    });
    box.append(img);
  };
  draw();
  box.redraw = draw;
  return box;
}

// оформление открыли из урока (#/efir/looks/<id>?from=<урок>) — «Сохранить и вернуться к уроку», «К уроку»
function fromLesson() {
  const id = E && E.from;
  return id ? (S.lessons || []).find((x) => x.id === id) || null : null;
}
function lookHash(id) { return "#/efir/looks/" + id + (E && E.from ? "?from=" + encodeURIComponent(E.from) : ""); }

function lookEditor(box, lk, reshow) {
  const isNew = !lk;
  const back = fromLesson();
  const L0 = lk || { id: "", title: "Новое оформление", background: { value: "color:#000000" }, caption: "", exercises: [], break_countdown: true,
    break_background: { value: "" }, break_title: "ПЕРЕРЫВ", break_show_title: true, break_done: "ПРОДОЛЖАЕМ", font: "Montserrat", text_color: "#FFFFFF", users: [], outside: 0 };
  if (back) setCrumbs([{ label: "Уроки", href: "#/lessons" }, { label: back.title, href: "#/lesson/" + back.id }, { label: "Оформление «" + L0.title + "»" }]);
  else crumbs(L0.title);
  const d = { id: L0.id, title: L0.title, background: L0.background.value, caption: L0.caption,
    exercises: L0.exercises.map((e) => ({ ...e })), break_countdown: L0.break_countdown, break_background: L0.break_background.value,
    break_title: L0.break_title, break_show_title: L0.break_show_title, break_done: L0.break_done, font: L0.font, text_color: L0.text_color };
  const dirtyMark = h("span", { id: "lkdirty", class: "chip warn", hidden: !isNew }, "есть изменения");
  const setDirty = (on = true) => { E.dirty = on; dirtyMark.hidden = !on; };
  const title = h("input", { class: "inp", id: "lktitle", value: d.title, "aria-label": "Название" });
  title.addEventListener("input", () => { d.title = title.value; setDirty(); });
  const bg = bgOptions(() => d.background, (v) => { d.background = v; setDirty(); bg.redraw(); }, { id: "lkbg" });
  const gallery = btn("Галерея фонов…", { icon: "eye", kind: "ghost", size: "sm", onClick: () => send({ cmd: "efir_gallery", current: d.background }) });
  const caption = h("input", { class: "inp", id: "lkcaption", value: d.caption, placeholder: "например, Вебинар 1Т · скоро начнём" });
  caption.addEventListener("input", () => { d.caption = caption.value; setDirty(); });
  // зарядки
  const exBox = h("div", { id: "lkex", class: "exlist" });
  function drawEx() {
    clear(exBox);
    if (!d.exercises.length) exBox.append(h("p", { class: "dim" }, "Видео зарядок нет — кнопки «Зарядка» у учеников не будет."));
    d.exercises.forEach((e, i) => {
      const t = h("input", { class: "inp ext", value: e.title, "aria-label": "Название кнопки" });
      t.addEventListener("input", () => { e.title = t.value; setDirty(); });
      const miss = e.status === "missing";
      const file = miss ? h("span", { class: "exmissing" }, icon("alert", "sm"), "Файл удалён или перемещён")
        : h("span", { class: "exfile meta" }, e.name + (e.size ? " · " + mb(e.size) : "") + (e.status === "outside" ? " · снаружи программы" : ""));
      const rep = btn(miss ? "Заменить…" : "Другой файл…", { size: "sm", kind: miss ? "" : "ghost", cls: "exreplace", onClick: async () => {
        try {
          const ps = await call({ cmd: "pick_files", purpose: "video", multi: false });
          if (ps && ps.length) { const r = await call({ cmd: "efir_take_file", path: ps[0] }); Object.assign(e, { path: r.path, name: r.name, size: r.size, status: r.status }); setDirty(); drawEx(); }
        } catch (err) { fail(err); }
      } });
      const del = iconBtn("close", "Убрать видео", () => { d.exercises.splice(i, 1); setDirty(); drawEx(); }, { size: "sm", kind: "ghost", cls: "exdel" });
      exBox.append(h("div", { class: "exrow" + (miss ? " bad" : "") }, icon("activity", "sm"), t, file, rep, del));
    });
  }
  drawEx();
  const addVideo = btn("Добавить видео…", { icon: "plus", kind: "ghost", onClick: async () => {
    try {
      const ps = await call({ cmd: "pick_files", purpose: "video" });
      for (const p of ps || []) {
        const r = await call({ cmd: "efir_take_file", path: p });
        d.exercises.push({ title: r.name.replace(/\.[^.]+$/, ""), path: r.path, name: r.name, size: r.size, status: r.status });
      }
      if (ps && ps.length) { setDirty(); drawEx(); }
    } catch (e) { fail(e); }
  } });
  addVideo.id = "lkaddvideo";
  // экран перерыва
  const brkBg = bgOptions(() => d.break_background, (v) => { d.break_background = v; setDirty(); brkBg.redraw(); }, { id: "lkbrkbg", inherit: true });
  const showT = toggle("Показывать надпись", d.break_show_title, (v) => { d.break_show_title = v; brkTitle.disabled = !v; setDirty(); });
  showT.input.id = "lkbrkshow";
  const brkTitle = h("input", { class: "inp", id: "lkbrktitle", value: d.break_title, disabled: !d.break_show_title || null });
  brkTitle.addEventListener("input", () => { d.break_title = brkTitle.value; setDirty(); });
  const count = toggle("Обратный отсчёт", d.break_countdown, (v) => { d.break_countdown = v; setDirty(); });
  count.input.id = "lkcount";
  const done = h("input", { class: "inp", id: "lkdone", value: d.break_done });
  done.addEventListener("input", () => { d.break_done = done.value; setDirty(); });
  const fonts = (ef().fonts || []).map(([k, t]) => [k, t]);
  const fileFont = d.font.startsWith("file:") ? [[d.font, "Свой: " + d.font.slice(5).replace(/\\/g, "/").split("/").pop()]] : [];
  const font = select([...fonts, ...fileFont, ["__file", "Свой файл шрифта…"]], d.font, async (v) => {
    if (v === "__file") {
      try {
        const ps = await call({ cmd: "pick_files", purpose: "font" });
        if (ps && ps.length) { const r = await call({ cmd: "efir_take_file", path: ps[0] }); d.font = "file:" + r.path; setDirty(); const op = h("option", { value: d.font }, "Свой: " + r.name); font.insertBefore(op, font.lastChild); font.value = d.font; return; }
      } catch (e) { fail(e); }
      font.value = d.font;
      return;
    }
    d.font = v;
    setDirty();
  }, { label: "Шрифт" });
  font.id = "lkfont";
  const color = h("input", { type: "color", id: "lkcolor", class: "colorin big", value: d.text_color });
  color.addEventListener("input", () => { d.text_color = color.value.toUpperCase(); setDirty(); });
  const preview = btn("Предпросмотр перерыва", { icon: "eye", kind: "ghost", size: "sm", onClick: () => send({ cmd: "efir_preview_break", look: d }) });
  preview.id = "lkpreview";
  // файлы снаружи программы
  const outside = h("div", { id: "lkoutside", class: "outside", hidden: !(L0.outside > 0) || isNew },
    icon("folder", "sm"), h("span", null, "Файлы снаружи программы: " + mb(L0.outside || 0) + " — флешку вынут, папку переименуют, и экран их не найдёт."));
  const copyBtn = btn("Скопировать в программу", { size: "sm", onClick: async () => {
    if (E.dirty) { toast("Сначала сохраните оформление", { warn: true }); return; }
    try { await call({ cmd: "efir_copy_files", id: d.id }); } catch (e) { fail(e); }
  } });
  copyBtn.id = "lkcopy";
  outside.append(copyBtn);
  const users = h("p", { class: "lkusers meta" }, L0.users && L0.users.length ? "Используется: " + L0.users.join(", ") : "Пока нигде не используется");
  const del = btn("Удалить…", { kind: "ghost", icon: "trash", onClick: async () => {
    if (!(await ask("Удалить оформление «" + d.title + "»?", { title: "Удалить оформление", ok: "Удалить", danger: true }))) return;
    try { await call({ cmd: "efir_delete_look", id: d.id }); E.dirty = false; go("#/efir/looks"); } catch (e) { fail(e); }
  } });
  del.id = "lkdelete";
  del.disabled = isNew || !!(L0.users && L0.users.length);
  if (del.disabled && !isNew) del.title = "Оформление используется — сначала смените его там";
  const cancel = btn("Отмена", { kind: "ghost", onClick: () => { E.dirty = false; if (isNew) go("#/efir/looks"); else reshow(); } });
  cancel.id = "lkcancel";
  const save = btn(back ? "Сохранить и вернуться к уроку" : "Сохранить", { kind: "primary", onClick: async () => {
    try {
      const r = await call({ cmd: "efir_put_look", look: { ...d, exercises: d.exercises.map((e) => ({ title: e.title || "Зарядка", path: e.path })) } });
      setDirty(false);
      if (back) { toast("Оформление сохранено"); go("#/lesson/" + back.id); }
      else if (isNew) go(lookHash(r.id));
    } catch (e) { fail(e); }
  } });
  save.id = "lksave";
  // назад к уроку: есть несохранённые правки — «Уйти без сохранения?» (canLeave экрана)
  const toLesson = back ? btn("К уроку", { icon: "chevron-left", kind: "ghost", size: "sm", tip: "Вернуться к уроку «" + back.title + "»",
    onClick: () => go("#/lesson/" + back.id) }) : null;
  if (toLesson) toLesson.id = "lkBack";
  box.append(h("div", { id: "lookedit", class: "wdetail lookedit" },
    h("div", { class: "wdh" }, toLesson, h("h2", null, isNew ? "Новое оформление" : "Оформление"), dirtyMark),
    field("Название", title), users, outside,
    h("h3", { class: "efh3" }, "Фон (он же занавес)"), bg, h("div", { class: "wrow2" }, gallery), field("Надпись на фоне", caption),
    h("h3", { class: "efh3" }, "Зарядки"), exBox, h("div", { class: "wrow2" }, addVideo),
    h("h3", { class: "efh3" }, "Экран перерыва"), brkBg, showT, brkTitle, count, field("Когда время вышло", done),
    h("div", { class: "ef2" }, field("Шрифт", font), field("Цвет надписей", color)), h("div", { class: "wrow2" }, preview),
    jobsBox("").el,
    h("div", { class: "effoot" }, del, h("span", { class: "spacer" }), cancel, save)));
  // фон из галереи браузера — сюда
  let pickedSeq = (ef().picked || {}).seq || 0;
  return { update: () => { const p = ef().picked || {}; if (p.seq && p.seq !== pickedSeq) { pickedSeq = p.seq; if (p.value) { d.background = p.value; setDirty(); bg.redraw(); } } } };
}

function lookList(selId) {
  const box = h("div", { id: "looklist", class: "wlist2", role: "list" });
  for (const lk of looks()) {
    const sw = h("i", { class: "lsw" });
    const b = lk.background;
    if (b.kind === "image" && b.url) sw.style.backgroundImage = `url("${b.url}")`;
    else if (b.kind === "color") sw.style.background = b.value.slice(6);
    else if (b.kind === "anim") sw.classList.add("anim");
    const miss = lk.exercises.some((e) => e.status === "missing") || b.status === "missing";
    const it = h("button", { class: "witem lkitem" + (lk.id === selId ? " on" : ""), type: "button", "data-id": lk.id },
      h("div", { class: "wih" }, sw, h("b", null, lk.title), miss ? h("span", { class: "badmark", title: "Нет файла" }, icon("alert", "sm")) : null),
      h("span", { class: "meta" }, lk.exercises.length + " " + plural(lk.exercises.length, "зарядка", "зарядки", "зарядок") + " · перерыв «" + (lk.break_show_title ? lk.break_title : "без надписи") + "»"
        + (lk.users.length ? " · " + lk.users.length + " " + plural(lk.users.length, "использование", "использования", "использований") : "")));
    it.addEventListener("click", () => go(lookHash(lk.id)));
    box.append(it);
  }
  if (!looks().length) box.append(h("p", { class: "dim empty" }, "Оформлений пока нет — «Новое оформление»."));
  return box;
}

// ---------------------------------------------------------------- идущий вебинар
function liveView(box) {
  crumbs("Идёт эфир");
  const label = h("div", { class: "lb-label" }), time = h("div", { class: "lb-time mono" }), name = h("div", { class: "lb-name" });
  const bar = h("div", { class: "lb-bar" }, h("i")), next = h("div", { class: "lb-next" }), demo = h("div", { class: "lb-demo" }), clock = h("div", { class: "lb-clock mono" });
  const agenda = h("div", { id: "liveAgenda", class: "lagenda" });
  const status = btn("Время эфира", { icon: "clock", onClick: () => statusMenu(status) });
  status.id = "liveStatus";
  const end = btn("Завершить эфир", { kind: "stop", icon: "stop", onClick: async () => {
    if (await ask("Завершить эфир? Экран учеников вернётся к фону.", { title: "Завершить эфир", ok: "Завершить", danger: true })) { send({ cmd: "efir_stop" }); go("#/efir"); }
  } });
  end.id = "liveEnd";
  const scr = h("div", { class: "lscr", role: "group", "aria-label": "Экран учеников" });
  const mk = (op, ic, label_, fn) => { const b = h("button", { class: "cs", type: "button", "data-op": op }, icon(ic), h("span", null, label_)); b.addEventListener("click", () => fn(b)); scr.append(b); return b; };
  const sBg = mk("background", "image", "Фон", () => send({ cmd: "efir_screen", op: "background" }));
  const sBlack = mk("black", "blackout", "Чёрный", () => send({ cmd: "efir_screen", op: ef().mode === "black" ? "background" : "black" }));
  tip(sBlack, "Чёрный экран ученикам · ещё щелчок — снова фон");
  const sEx = mk("exercise", "activity", "Зарядка", (b) => {
    const list = ef().exercises || [];
    if (!list.length) { toast("В оформлении эфира нет видео зарядок"); return; }
    menu(b, list.map((t, i) => ({ label: t || "Зарядка", on: () => send({ cmd: "efir_screen", op: "exercise", index: i }) })));
  });
  const sBrk = mk("break", "cup", "Перерыв", (b) => {
    if (ef().mode === "break") {
      menu(b, [{ label: "+5 мин", on: () => send({ cmd: "efir_screen", op: "break_adjust", seconds: 300 }) },
        { label: "+1 мин", on: () => send({ cmd: "efir_screen", op: "break_adjust", seconds: 60 }) },
        { label: "−1 мин", on: () => send({ cmd: "efir_screen", op: "break_adjust", seconds: -60 }) },
        { label: ef().break_paused ? "Продолжить отсчёт" : "Пауза отсчёта", on: () => send({ cmd: "efir_screen", op: "break_pause" }) },
        { label: "Убрать — снова фон", on: () => send({ cmd: "efir_screen", op: "background" }) }]);
      return;
    }
    menu(b, [{ head: "Перерыв ученикам" }, ...[5, 10, 15, 20].map((m) => ({ label: m + " мин", on: () => send({ cmd: "efir_screen", op: "break", minutes: m }) }))]);
  });
  const tab = h("div", { class: "ltab meta" });
  const openTab = btn("Открыть вкладку", { size: "sm", kind: "ghost", icon: "open", onClick: () => send({ cmd: "efir_open_tab" }) });
  function statusMenu(anchor) {
    const lv = S.live || {};
    const segs = lv.segments || [];
    const tm = h("input", { class: "inp mono", type: "time", "aria-label": "Начало эфира" });
    tm.value = lv.start_ms ? new Date(lv.start_ms).toTimeString().slice(0, 5) : "";
    const setStart = btn("Изменить начало", { size: "sm", onClick: () => { closePop(); send({ cmd: "efir_set_start", start: tm.value }); } });
    menu(anchor, [
      { node: h("div", { class: "zrow" }, tm, setStart) },
      { label: "Начать этот блок сейчас", hint: "текущий — с этой минуты", on: () => send({ cmd: "efir_start_block" }) },
      { label: "Начать с блока…", on: () => menu(anchor, segs.map((s, i) => ({ label: s.name, hint: clockAt(s.start_ms), on: () => send({ cmd: "efir_start_block", index: i }) }))) },
      { label: "Начать эфир сейчас / заново", hint: "с первого блока", on: () => send({ cmd: "efir_start_block", index: 0 }) },
    ], { align: "left" });
  }
  box.append(h("div", { id: "efirLive", class: "efirlive" },
    h("div", { class: "lstrip" }, status, scr, h("span", { class: "spacer" }), tab, openTab, end),
    h("div", { class: "lmain" }, h("div", { class: "lboard" }, label, time, name, bar, next, demo, clock), agenda)));
  function tick() {
    const lv = S.live;
    const segs = (lv && lv.segments) || [];
    const t = now();
    if (!segs.length) { label.textContent = "Нет эфира"; time.textContent = ""; name.textContent = ""; next.textContent = ""; demo.textContent = ""; clock.textContent = ""; agenda.replaceChildren(); return; }
    let idx = segs.findIndex((s) => s.start_ms <= t && t < s.end_ms);
    const cur = idx >= 0 ? segs[idx] : null;
    if (t < segs[0].start_ms) { label.textContent = "До начала"; time.textContent = mmss((segs[0].start_ms - t) / 1000); name.textContent = lv.title; next.textContent = "Первым: " + segs[0].name; }
    else if (!cur) { label.textContent = "Эфир завершён"; time.textContent = ""; name.textContent = lv.title; next.textContent = ""; idx = segs.length; }
    else {
      const left = (cur.end_ms - t) / 1000;
      label.textContent = "Сейчас · блок " + (idx + 1) + " из " + segs.length;
      time.textContent = mmss(left);
      time.classList.toggle("red", left <= 60);
      name.textContent = cur.name;
      bar.firstChild.style.width = Math.min(100, (t - cur.start_ms) / (cur.end_ms - cur.start_ms) * 100).toFixed(1) + "%";
      const nx = segs[idx + 1];
      next.textContent = nx ? "Дальше: " + clockAt(nx.start_ms) + " · " + nx.name + " · " + Math.round((nx.end_ms - nx.start_ms) / 60000) + " мин" : "Последний блок";
    }
    bar.hidden = !cur;
    demo.textContent = cur ? (cur.demo === "on" ? "Демонстрация ВКЛ" : cur.demo === "off" ? "Демонстрация ВЫКЛ" : "") : "";
    demo.className = "lb-demo " + (cur ? cur.demo : "");
    clock.textContent = "Сейчас " + clockAt(t) + " · эфир " + clockAt(segs[0].start_ms) + "–" + clockAt(segs[segs.length - 1].end_ms);
    const key = JSON.stringify(segs.map((s) => [s.name, s.start_ms])) + idx;
    if (agenda.dataset.k !== key) {
      agenda.dataset.k = key;
      clear(agenda);
      segs.forEach((s, i) => agenda.append(h("div", { class: "la-row" + (i === idx ? " cur" : i < idx ? " past" : "") + (s.kind ? " k-" + s.kind : "") },
        h("span", { class: "t mono" }, clockAt(s.start_ms)), h("span", { class: "n" }, s.name), h("span", { class: "m mono" }, Math.round((s.end_ms - s.start_ms) / 60000) + " мин"))));
    }
    const mode = ef().mode || "idle";
    for (const [b, m] of [[sBg, "idle"], [sBlack, "black"], [sEx, "exercise"], [sBrk, "break"]]) b.setAttribute("aria-pressed", String(mode === m));
    tab.textContent = ef().tab || "";
    openTab.hidden = !!ef().tab_open;
  }
  tick();
  const timer = setInterval(tick, 1000);
  return { update: tick, destroy: () => clearInterval(timer) };
}

// ---------------------------------------------------------------- экран
export function efirView(root, r) {
  const tabs = seg([{ value: "schedules", label: "Расписания" }, { value: "looks", label: "Оформления" }], "schedules",
    (v) => go(v === "looks" ? "#/efir/looks" : "#/efir"), { label: "Раздел" });
  tabs.id = "efirTabs";
  const newBtn = btn("Новый эфир", { kind: "primary", icon: "plus", onClick: () => go(tabs.querySelector("[aria-pressed=true]").dataset.value === "looks" ? "#/efir/looks/new" : "#/efir/new") });
  newBtn.id = "efirNew";
  const left = h("div", { class: "efleft" });
  const right = h("div", { class: "efright" });
  const liveBox = h("div", { class: "eflive" });
  const page = h("div", { class: "page efir" }, h("div", { class: "wrap efwrap" },
    h("div", { class: "pagehead" }, h("h1", null, "Эфир"), tabs, h("span", { class: "spacer" }), newBtn),
    h("div", { class: "efbody" }, left, right)), liveBox);
  root.append(page);
  send({ cmd: "efir_opened" }).catch(() => {});
  let sub = null, list = null, sig = "", lastR = r;
  E = { hash: location.hash, dirty: false };
  function show(r2) {
    lastR = r2;
    E.hash = location.hash;
    E.from = (r2.parts[1] === "looks" && r2.query && r2.query.from) || "";
    if (sub && sub.destroy) sub.destroy();
    sub = null;
    clear(left); clear(right); clear(liveBox);
    page.classList.remove("wediting");
    const p = r2.parts;
    const isLooks = p[1] === "looks";
    const isLive = p[1] === "live";
    page.classList.toggle("islive", isLive);
    tabs.set(isLooks ? "looks" : "schedules");
    newBtn.querySelector(".bl").textContent = isLooks ? "Новое оформление" : "Новый эфир";
    if (isLive) { sub = liveView(liveBox); return; }
    if (isLooks) {
      const id = p[2] || "";
      left.append(lookList(id));
      const reshow = () => show(lastR);
      if (id === "new") sub = lookEditor(right, null, reshow);
      else {
        const lk = looks().find((l) => l.id === id) || (id ? null : looks()[0]);
        if (lk) sub = lookEditor(right, lk, reshow);
        else right.append(h("p", { class: "dim empty" }, id ? "Оформление не найдено." : "Выберите оформление слева."));
        if (!id) crumbs("Оформления");
      }
      if (id === "new") E.dirty = true;
      return;
    }
    const id = p[1] || "";
    const selId = () => (id === "new" ? "" : id || (webinars()[0] || {}).id);
    list = listBox(selId);
    left.append(list.el);
    if (id === "new") { newPanel(right); return; }
    const w = webinars().find((x) => x.id === selId());
    if (!w) { right.append(h("p", { class: "dim empty" }, webinars().length ? "Расписание не найдено." : "Расписаний пока нет. «Новый эфир» — пустое, по описанию нейросетью, из текста или файла.")); crumbs(); return; }
    if (p[2] === "edit") { page.classList.add("wediting"); editor(right, w); }
    else detail(right, w);
  }
  show(r);
  return {
    route: (r2) => show(r2),
    canLeave: () => {
      if (!E || !E.dirty) return true;
      const target = location.hash;
      history.replaceState(null, "", E.hash);               // адрес — обратно, пока не ответили
      ask("Изменения не сохранены. Уйти без сохранения?", { title: "Изменения не сохранены", ok: "Уйти без сохранения", cancel: "Остаться", danger: true })
        .then((ok) => { if (ok) { E.dirty = false; location.hash = target; } });
      return false;
    },
    update: () => {
      if (sub && sub.update) sub.update();
      // список и выбранное перерисовываются, когда поменялись данные (не во время правки)
      const key = JSON.stringify([webinars(), looks().map((l) => [l.id, l.title, l.users, l.outside, l.exercises, l.background]), ef().live_id]);
      if (key !== sig) { const first = !sig; sig = key; if (!first && !(E && E.dirty) && !(lastR.parts[1] === "live")) show(lastR); }
    },
    destroy: () => { if (sub && sub.destroy) sub.destroy(); E = null; },
  };
}
