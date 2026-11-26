// Экран учеников в эфирной полосе урока и набор кода.
//  • Миниатюра — что сейчас у учеников и есть ли их вкладка; её панель: открыть вкладку, адрес, оформление.
//  • Значки «Фон», «Зарядка», «Перерыв», «Слайд» — без подписей, с подсказками; нажатый — то, что у учеников.
//  • Идёт этап-перерыв или этап-зарядка — значок подсвечивается; экран учеников сам не меняется (включает учитель).
//  • Блок кода: «Набрать» (с отсчётом) и «▾» — как набирать; полоса набора внизу урока, пока идёт набор.
"use strict";
import { h, btn, iconBtn, seg, popover, menu, toggle, clear, closePop, tip } from "./ui.js";
import { icon } from "./icons.js";
import { go } from "./core.js";
import { hooks, computeCurrent } from "./lessonview.js";
import { A, cmd, now, mmss } from "../lesson/state.js";
import { decor, exerciseList, lightUrl, stageVideo } from "../lesson/render.js";

const BUSY = ["running", "countdown", "paused", "line_wait"];
let W = null;                         // элементы экрана учеников и полосы набора
let lastStage = null, pulseKind = "";  // этап, на котором подсветили значок, и какой значок

function ef() { return (A.S && A.S.efir) || {}; }
function pr() { return (A.S && A.S.print) || {}; }
function hotkey() { return pr().hotkey || (A.S && A.S.hotkey) || "Ctrl+F9"; }
function slides() { return A.items.filter((x) => x.type === "image" && x.url); }
const set = (el, text) => { if (el.textContent !== text) el.textContent = text; };
const stop = (fn) => (e) => { e.stopPropagation(); fn(e); };

// ---------------------------------------------------------------- перерыв
function planBreak() {
  const { cur, stages } = computeCurrent();
  const c = cur >= 0 ? stages[cur] : null;
  if (c && c.item.kind === "break") return { s: c, now: true };
  const s = stages.find((x) => x.item.kind === "break");
  return s ? { s, now: false } : null;
}

function breakLeft() {
  const e = ef();
  if (e.mode !== "break") return null;
  if (e.break_paused) return (e.break_left || 0) / 1000;
  return e.break_ends ? Math.max(0, (e.break_ends - now()) / 1000) : null;
}

function breakMenu(anchor) {
  const e = ef();
  if (e.mode === "break") {
    menu(anchor, [
      { head: e.break_paused ? "Перерыв · отсчёт на паузе" : "Перерыв идёт" },
      { label: "+5 мин", on: () => cmd({ cmd: "break_adjust", seconds: 300 }) },
      { label: "+1 мин", on: () => cmd({ cmd: "break_adjust", seconds: 60 }) },
      { label: "−1 мин", on: () => cmd({ cmd: "break_adjust", seconds: -60 }) },
      { label: e.break_paused ? "Продолжить отсчёт" : "Пауза отсчёта", on: () => cmd({ cmd: "break_pause" }) },
      { label: "Заново", hint: "отсчёт сначала", on: () => cmd({ cmd: "break_restart" }) },
      { sep: true },
      { label: "Убрать — снова фон", on: () => cmd({ cmd: "background" }) },
    ], { cls: "scrmenu" });
    return;
  }
  const pb = planBreak();
  const items = [{ head: "Перерыв ученикам" }];
  if (pb && pb.s.minutes > 0) {
    items.push({ label: "По плану · " + pb.s.minutes + " мин", hint: pb.now ? "до конца этапа" : (pb.s.item.title || "этап плана"),
      on: () => cmd({ cmd: "break", stage: pb.s.id, minutes: pb.s.minutes }) });
  }
  for (const m of [5, 10, 15, 20]) items.push({ label: m + " мин", on: () => cmd({ cmd: "break", minutes: m }) });
  menu(anchor, items, { cls: "scrmenu" });
}

// ---------------------------------------------------------------- зарядка
function exMenu(anchor) {
  const e = ef();
  const list = exerciseList();
  const missing = (A.S && A.S.exercises_missing) || [];
  const items = [];
  if (e.mode === "exercise") {
    items.push({ head: e.ex_waiting ? "Зарядка ждёт щелчка по вкладке учеников" : e.ex_muted ? "Зарядка идёт без звука" : "Зарядка идёт" },
      { label: e.ex_paused ? "Продолжить" : "Пауза", on: () => cmd({ cmd: "exercise_pause" }) },
      { label: "Сначала", hint: "видео с начала", on: () => cmd({ cmd: "exercise_restart" }) },
      { label: "Убрать — снова фон", on: () => cmd({ cmd: "background" }) },
      { sep: true });
  }
  items.push({ head: "Видео зарядки" });
  list.forEach((title, i) => {
    const gone = missing.includes(title);
    items.push({ label: title || "Зарядка", checked: e.mode === "exercise" && e.ex_index === i, disabled: gone,
      hint: gone ? "файла видео нет" : "", on: () => cmd({ cmd: "exercise", index: i }) });
  });
  if (!list.length) items.push({ label: "Добавить видео зарядки…", hint: "в оформлении экрана учеников", on: () => cmd({ cmd: "look_edit" }) });
  else items.push({ sep: true }, { label: "Видео зарядок…", hint: "добавить, переименовать", on: () => cmd({ cmd: "look_edit" }) });
  menu(anchor, items, { cls: "scrmenu" });
}

// какое видео включает щелчок без выбора: next — по очереди, random — случайное, ask — меню (настройка «Урок → Зарядка»)
function exPick() { return (A.S && A.S.prefs && A.S.prefs.exercise_pick) || "next"; }

// этап-зарядка, который идёт сейчас (его видео — первым), или null
function exStage() {
  const { cur, stages } = computeCurrent();
  const c = cur >= 0 ? stages[cur] : null;
  return c && c.item.kind === "exercise" ? c : null;
}

// «Зарядка» наверху одним щелчком: идёт — меню (пауза, сначала, другое видео); нет — сразу видео: своё у этапа-
// зарядки, который идёт, иначе по очереди или случайное. «Спросить» в настройках или видео нет — меню. Правая
// кнопка — меню всегда (выбрать другое видео).
function exClick(anchor) {
  const list = exerciseList(), st = exStage();
  if (ef().mode === "exercise" || !list.length || exPick() === "ask" && list.length > 1 && !(st && stageVideo(st.item))) {
    exMenu(anchor);
    return;
  }
  cmd({ cmd: "exercise", stage: st ? st.id : "", pick: exPick() });
}

// подсказка «Зарядки»: что включит щелчок
function exTip() {
  const list = exerciseList();
  if (!list.length) return "Зарядка — добавить видео";
  const st = exStage(), own = st ? stageVideo(st.item) : "";      // идёт этап-зарядка со своим видео — оно
  if (!own && exPick() === "ask" && list.length > 1) return "Зарядка — выбрать видео";
  const name = own || (list.length === 1 ? list[0] : exPick() === "random" ? "" : (A.S && A.S.exercise_next) || "");
  const what = name ? "«" + name + "»" : exPick() === "random" ? "случайную" : "видео";
  return "Зарядка: включить " + what + (list.length > 1 ? " · правой кнопкой — другое видео" : "");
}

// кнопка этапа-зарядки в тексте урока: своё видео — сразу; нет — по настройке (по очереди, случайное, меню видео)
function stageExercise(b) {
  const it = A.byId.get(b.dataset.stage);
  if (!it) return false;
  if (stageVideo(it) || exerciseList().length < 2 || exPick() !== "ask") cmd({ cmd: "exercise", stage: it.id, pick: exPick() });
  else exMenu(b);
  pulseKind = "";
  updateStrip();
  return true;
}

// ---------------------------------------------------------------- миниатюра и вкладка
function thumbMenu(anchor) {
  const e = ef();
  const L = (A.S && A.S.lesson) || {};
  const items = [
    { head: e.tab || (e.tab_open ? "Вкладка экрана учеников на связи" : "Вкладка экрана учеников не открыта") },
    { label: "Открыть вкладку", icon: "open", hint: e.tab_open ? "ещё одну, в браузере" : "в браузере — её показывают ученикам",
      on: () => cmd({ cmd: "open_tab" }) },
    { label: "Скопировать адрес вкладки", icon: "copy", hint: "для браузера, из которого показываете", on: () => cmd({ cmd: "copy_url" }) },
  ];
  const looks = L.presets || [];
  if (looks.length) {
    items.push({ head: "Оформление экрана" });
    for (const p of looks) items.push({ label: p.title, checked: p.id === L.preset, on: () => cmd({ cmd: "preset", id: p.id }) });
  }
  items.push({ label: "Изменить оформление…", icon: "pencil", hint: "фон, перерыв, зарядки", on: () => cmd({ cmd: "look_edit" }) });
  menu(anchor, items, { cls: "scrmenu", align: "right" });
}

function thumbText(e) {
  const tab = e.tab_open ? "" : " · вкладка не открыта";
  if (e.mode === "break") return "У учеников перерыв" + tab;
  if (e.mode === "exercise") return "У учеников зарядка" + (e.ex_muted ? " без звука" : "") + tab;
  if (e.mode === "slide") return "У учеников слайд " + (e.slide_n || "") + tab;
  return "У учеников фон" + tab;
}

// ---------------------------------------------------------------- полоса: построить и обновить
function mount(V) {
  const box = V.st.screen;
  clear(box);
  const scr = h("span", { class: "scr" });
  const dot = h("span", { class: "tdot" });
  const thumb = h("button", { class: "thumb", type: "button", id: "screenThumb" }, scr, dot);
  tip(thumb, "Экран учеников");
  thumb.addEventListener("click", () => thumbMenu(thumb));
  const open = btn("Открыть", { size: "sm", icon: "open", tip: "Вкладка экрана учеников не открыта — открыть её в браузере",
    onClick: () => cmd({ cmd: "open_tab" }) });
  open.id = "screenOpen";
  open.hidden = true;
  const bg = iconBtn("image", "Фон", () => cmd({ cmd: "background" }), { size: "sm", cls: "scrbtn" });
  bg.id = "scrBg";
  const ex = iconBtn("activity", "Зарядка", () => { pulseKind = ""; exClick(ex); updateStrip(); }, { size: "sm", cls: "scrbtn" });
  ex.id = "scrEx";
  ex.addEventListener("contextmenu", (e) => { e.preventDefault(); pulseKind = ""; exMenu(ex); updateStrip(); });
  const openBreak = () => { pulseKind = ""; breakMenu(brk); updateStrip(); };
  const brk = iconBtn("cup", "Перерыв", openBreak, { size: "sm", cls: "scrbtn" });
  brk.id = "scrBreak";
  const sl = iconBtn("slide", "Слайд", () => cmd(ef().mode === "slide" ? { cmd: "background" } : { cmd: "slide_step", d: 1 }),
    { size: "sm", cls: "scrbtn" });
  sl.id = "scrSlide";
  const prev = h("button", { class: "prev", type: "button", "aria-label": "Предыдущий слайд" }, "‹");
  const next = h("button", { class: "next", type: "button", "aria-label": "Следующий слайд" }, "›");
  prev.addEventListener("click", () => cmd({ cmd: "slide_step", d: -1 }));
  next.addEventListener("click", () => cmd({ cmd: "slide_step", d: 1 }));
  tip(prev, "Предыдущий слайд · ←");
  tip(next, "Следующий слайд · →");
  const nav = h("span", { id: "slideNav", class: "slidenav", hidden: true }, prev, h("span", { class: "n mono" }), next);
  // отсчёт перерыва — в том же месте, что и стрелки слайдов (режимы не бывают вместе); щелчок — меню перерыва
  const left = h("button", { class: "brkleft mono", type: "button", hidden: true, "aria-label": "Перерыв: сколько осталось" });
  left.addEventListener("click", openBreak);
  tip(left, "Перерыв: сколько осталось · щёлкните — +5 мин, пауза, убрать");
  // место под стрелки и отсчёт оставлено заранее: они выезжают, а значки и кнопки рядом не сдвигаются
  const info = h("span", { id: "scrInfo", class: "scrinfo" }, nav, left);
  const icons = h("div", { class: "scricons", role: "group", "aria-label": "Что показать ученикам" }, bg, ex, brk, sl, info);
  box.append(thumb, open, icons);
  const bar = buildTypingBar();
  V.content.closest(".lbody").after(bar);
  W = { thumb, scr, dot, open, bg, ex, brk, sl, nav, left, bar };
  lastStage = null;
  pulseKind = "";
  updateStrip();
}

function updateStrip() {
  if (!W || !W.thumb.isConnected) return;
  const e = ef();
  const mode = e.mode || "idle";
  for (const [b, m] of [[W.bg, "idle"], [W.ex, "exercise"], [W.brk, "break"], [W.sl, "slide"]]) b.setAttribute("aria-pressed", String(mode === m));
  // миниатюра
  W.thumb.dataset.mode = mode;
  W.thumb.classList.toggle("closed", !e.tab_open);
  W.thumb.dataset.tip = thumbText(e);
  W.thumb.setAttribute("aria-label", thumbText(e));
  const sb = mode === "slide" ? A.byId.get(e.slide_bid) : null;
  const bgd = (mode === "idle" && e.screen_bg) || {};
  const want = mode === "slide" ? "s:" + (sb && sb.url) : mode + "|" + JSON.stringify(bgd);
  if (W.scr.dataset.k !== want) {
    W.scr.dataset.k = want;
    clear(W.scr);
    // фон учеников: картинка, цвет или анимация (её — градиентом); слайд — сам слайд
    const raw = mode === "slide" ? (sb && sb.url) || "" : bgd.kind === "image" ? bgd.url || "" : "";
    const img = raw ? lightUrl(raw, 160) : "";      // миниатюра 58×36 — копия, а не слайд 1920 px
    W.scr.style.backgroundImage = img ? `url("${img}")` : bgd.kind === "anim" ? "linear-gradient(135deg, #22335c, #4a2459)" : "";
    W.scr.style.backgroundColor = bgd.kind === "color" ? bgd.value : "";
    if (mode === "break") W.scr.append(icon("cup", "sm"));
    else if (mode === "exercise") W.scr.append(icon("activity", "sm"));
    else if (mode === "slide" && !(sb && sb.url)) W.scr.append(icon("slide", "sm"));
  }
  W.open.hidden = !!e.tab_open;
  // зарядка: без звука / ждёт щелчка
  const exWarn = mode === "exercise" && (e.ex_muted || e.ex_waiting);
  W.ex.classList.toggle("warn", exWarn);
  W.ex.dataset.tip = e.ex_waiting ? "Зарядка ждёт щелчка — щёлкните один раз по вкладке учеников"
    : exWarn ? "Зарядка идёт без звука — щёлкните один раз по вкладке учеников"
    : mode === "exercise" ? "Зарядка идёт · щелчок — пауза, сначала, другое видео" : exTip();
  // слайд
  const has = slides().length > 0;
  W.sl.disabled = !has && mode !== "slide";
  W.sl.dataset.tip = has ? (mode === "slide" ? "Слайд у учеников · щёлкните — снова фон" : "Слайд") : "Слайд — в уроке нет картинок";
  W.nav.hidden = mode !== "slide";
  set(W.nav.querySelector(".n"), String(e.slide_n || ""));
  W.brk.dataset.tip = mode === "break" ? (e.break_paused ? "Перерыв · отсчёт на паузе" : "Перерыв идёт") : "Перерыв";
  tickStrip();
  updateTyping();
}

// раз в секунду: отсчёт перерыва на значке, подсветка значка на этапе-перерыве / этапе-зарядке
function tickStrip(info) {
  if (!W) return;
  const { cur, stages } = info || computeCurrent();
  const c = cur >= 0 ? stages[cur] : null;
  const id = c ? c.id : "";
  if (id !== lastStage) {
    lastStage = id;
    pulseKind = c && (c.item.kind === "break" || c.item.kind === "exercise") ? c.item.kind : "";
    if ((ef().mode || "idle") !== "exercise") W.ex.dataset.tip = exTip();    // новый этап — подсказка про его видео
  }
  const mode = ef().mode || "idle";
  W.brk.classList.toggle("pulse", pulseKind === "break" && mode !== "break");
  W.ex.classList.toggle("pulse", pulseKind === "exercise" && mode !== "exercise");
  const left = breakLeft();
  W.left.hidden = left === null;
  if (left !== null) set(W.left, mmss(left));
  W.left.classList.toggle("paused", !!ef().break_paused);
}

// ---------------------------------------------------------------- набор кода
function codeName(id) {
  const it = A.byId.get(id);
  if (it && it.title) return it.title;
  const codes = A.items.filter((x) => x.type === "code");
  const k = codes.findIndex((x) => x.id === id);
  return k >= 0 ? "код " + (k + 1) : "код";
}

// почему пауза — коротко (полное — в полосе набора)
function whyShort(P) { return (P.pause_why || "").split(" — ")[0]; }

function stateText(P) {
  const pct = Math.round((P.progress || 0) * 100);
  if (P.state === "countdown") return "Начну через " + (P.countdown || "") + "…";
  if (P.state === "paused") return "Пауза · " + (whyShort(P) || pct + "%");
  if (P.state === "line_wait") return "Жду Enter" + (P.line ? " · строка " + P.line.i + " из " + P.line.n : "");
  return "Набираю · " + pct + "%";
}

function typePanel(anchor, bid) {
  const P = pr();
  const val = h("b", { class: "mono" }, String(P.cpm || 320));
  const r = h("input", { type: "range", min: "60", max: "1200", step: "10", "aria-label": "Скорость набора, знаков в минуту" });
  r.value = String(P.cpm || 320);
  r.addEventListener("input", () => { val.textContent = r.value; });
  r.addEventListener("change", () => cmd({ cmd: "print_settings", key: "cpm", value: +r.value }));
  const opt = (k, label, hint) => toggle(label, !!P[k], (v) => cmd({ cmd: "print_settings", key: k, value: v }), hint);
  const box = h("div", { class: "typepanel" },
    h("div", { class: "phead" }, "Как набирать"),
    seg([{ value: "block", label: "Целиком" }, { value: "lines", label: "По строкам" }, { value: "steps", label: "По шагам" }],
      P.mode || "block", (v) => cmd({ cmd: "print_settings", key: "mode", value: v }), { size: "sm", label: "Как набирать" }),
    h("p", { class: "meta" }, "По строкам — строка, потом ваш Enter. По шагам — шаги отмечают в коде (Alt+1…9 в правке)."),
    h("label", { class: "trange" }, h("span", null, "Скорость"), r, val, h("span", { class: "meta" }, "зн/мин")),
    opt("human", "Как человек", "живой ритм, паузы, опечатки"),
    opt("sound", "Звук клавиш", ""),
    opt("strip", "Комментарии читать вслух", "в код они не набираются — «Скажи: …» над кодом"),
    h("div", { class: "psep" }),
    h("div", { class: "trow2" },
      btn("Сделать следующим", { size: "sm", kind: "ghost", tip: "Набрать потом клавишами " + hotkey() + " — курсор в Jupyter или VS Code",
        onClick: () => { closePop(); cmd({ cmd: "arm", block: bid }); } }),
      btn("Все настройки набора…", { size: "sm", kind: "ghost", onClick: () => { closePop(); go("#/settings/typing"); } })));
  popover(anchor, box, { align: "right", focus: false, cls: "typepop" });
}

// шапка блока кода в окне: «Набрать», «▾», а пока этот блок набирается — его состояние
decor.code = (slot, it, P, on, busy) => {
  const filled = !!(it.text || "").trim();
  const key = [filled, on, busy, busy ? stateText(P) : "", hotkey()].join("|");
  if (slot.dataset.key === key) return;
  slot.dataset.key = key;
  clear(slot);
  if (!filled) return;
  if (busy) { slot.append(h("span", { class: "armed-chip" }, stateText(P))); return; }
  const n = Math.max(1, +((A.S && A.S.button_countdown) || 3));
  const tb = btn("Набрать", { size: "sm", icon: "keyboard", cls: "typeBtn",
    tip: "Набрать этот код: через " + n + " с — в окне, где курсор (Jupyter, VS Code)" });
  tb.addEventListener("click", stop(() => cmd({ cmd: "type", block: it.id })));
  const to = iconBtn("chevron-down", "Как набирать", null, { size: "sm", kind: "ghost", cls: "typeOpts" });
  to.addEventListener("click", stop(() => typePanel(to, it.id)));
  slot.append(tb, to);
  if (on) slot.append(h("span", { class: "armed-chip", title: "Следующим наберётся этот код — " + hotkey() }, "следующий · " + hotkey()));
};

function buildTypingBar() {
  const say = h("div", { class: "tsay", hidden: true });
  const name = h("b", { class: "tname" });
  const info = h("span", { class: "tinfo" });
  const target = h("span", { class: "ttarget meta" });
  const fill = h("i");
  const act = btn("Пауза", { size: "sm", icon: "pause", cls: "tact", onClick: () => cmd({ cmd: "typing", op: act.dataset.op || "pause" }) });
  const stopB = btn("Стоп", { size: "sm", kind: "stop", icon: "stop", cls: "tstop", onClick: () => cmd({ cmd: "typing", op: "stop" }) });
  const why = h("div", { class: "twhy", hidden: true });
  const bar = h("section", { id: "typingBar", hidden: true, "aria-label": "Набор кода", "aria-live": "polite" },
    say,
    h("div", { class: "trow" }, h("span", { class: "tkey" }, icon("keyboard")),
      h("div", { class: "ttext" }, h("div", { class: "tl1" }, name, info), target),
      h("div", { class: "tprog" }, fill), act, stopB),
    why);
  Object.assign(bar, { say, name, info, target, fill, act, why });
  return bar;
}

function updateTyping() {
  if (!W) return;
  const P = pr();
  const bar = W.bar;
  const busy = BUSY.includes(P.state);
  bar.hidden = !busy;
  document.body.classList.toggle("typing", busy);
  if (!busy) return;
  const verb = P.state === "countdown" ? "Начну через " + (P.countdown || "") + " с:" : P.state === "paused" ? "Пауза:"
    : P.state === "line_wait" ? "Жду Enter:" : "Набираю";
  set(bar.name, verb + " " + codeName(P.block));
  const bits = [];
  if (P.line) bits.push("строка " + P.line.i + " из " + P.line.n);
  if (P.step && !P.step.done) bits.push("шаг " + P.step.i + " из " + P.step.n);
  set(bar.info, bits.length ? " · " + bits.join(" · ") : "");
  set(bar.target, P.target ? "→ " + P.target : "");
  bar.fill.style.width = ((P.progress || 0) * 100).toFixed(1) + "%";
  const [op, text, ic] = P.state === "paused" ? ["resume", "Продолжить", "play"] : P.state === "line_wait" ? ["next", "Дальше", "skip"]
    : ["pause", "Пауза", "pause"];
  if (bar.act.dataset.op !== op) {
    bar.act.dataset.op = op;
    bar.act.querySelector(".bl").textContent = text;
    bar.act.querySelector(".i")?.replaceWith(icon(ic));
  }
  // пауза не кнопкой — почему и что делать (иначе «Пауза» непонятна: «я же не нажимал»)
  const whyText = P.state === "paused" && P.pause_why
    ? "Пауза: " + P.pause_why + ". Поставьте курсор, где печатать, и нажмите «Продолжить» или " + hotkey() + "." : "";
  bar.why.hidden = !whyText;
  set(bar.why, whyText);
  const sayText = (P.say || []).join("\n");
  bar.say.hidden = !sayText;
  if (bar.say.dataset.k !== sayText) {
    bar.say.dataset.k = sayText;
    clear(bar.say);
    if (sayText) bar.say.append(h("b", null, "Скажи: "), sayText);
  }
}

hooks.mount.push(mount);
hooks.strip.push(updateStrip);
hooks.tick.push(tickStrip);
hooks.exercise.push(stageExercise);
