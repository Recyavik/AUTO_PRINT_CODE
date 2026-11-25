// «Новый урок» по шагам (#/new):
//  1 — «На чём построить урок?»: карточки планов, «Без плана», «Свой план» (#/new/plan), «Уже есть файл урока?»;
//  2 — «Тема и текст» (#/new/text?plan=…): тема, класс (без плана — минуты и перерыв) и откуда взять текст этапов:
//      «Составит нейросеть» (по теме или по файлу; Claude Code и Codex читают сам файл), «Вставить текст» (ответ
//      своего чата, Markdown, тетрадка, код), «Заполню сам».
// Нейросеть и картинки работают в фоне — ход виден здесь и в «Уроках»; готовый урок открывается сам.
"use strict";
import { S, call, go } from "./core.js";
import { h, btn, iconBtn, seg, toggle, field, numberField, select, toast, clear } from "./ui.js";
import { icon } from "./icons.js";
import { setCrumbs, registerDrop } from "./shell.js";
import { pickAndImport, importFiles } from "./library.js";
import { jobsBox } from "./jobsbox.js";
import { durText, plural, hm } from "../lesson/state.js";

// выбранное в мастере — живёт, пока открыта программа (между шагами и после ухода на другой экран)
const W = { plan: null, topic: "", cls: null, minutes: null, brk: null, src: "ai", files: [], material: "", what: "lesson",
  code: null, answer: "", paste: "", lang: "", slides: "", draft: null };
let cur = null;                     // открытый шаг: {onDrop, update}
const fail = (e) => toast(String((e && e.message) || e), { warn: true });
const CODE_STYLES = [{ value: "comments", label: "С комментариями" }, { value: "steps", label: "По шагам" }, { value: "parts", label: "По частям" }];
const LANGS = [["", "Язык кода: определить сам"], ["python", "Python"], ["javascript", "JavaScript"], ["typescript", "TypeScript"],
  ["html", "HTML"], ["css", "CSS"], ["java", "Java"], ["kotlin", "Kotlin"], ["csharp", "C#"], ["cpp", "C++"], ["c", "C"],
  ["go", "Go"], ["php", "PHP"], ["sql", "SQL"], ["json", "JSON"], ["bash", "Bash"]];
const START_LABELS = { empty: "Пусто", online90: "Онлайн-занятие 90 мин", pair90: "Пара 2×45", school45: "Школьный урок 45 мин" };
const START_ORDER = ["empty", "online90", "pair90", "school45"];
const KIND_NAMES = [["", "Обычный"], ["break", "Перерыв"], ["exercise", "Зарядка"]];

function crumbs() { setCrumbs([{ label: "Уроки", href: "#/lessons" }, { label: "Новый урок" }]); }

function stepper(n) {
  const li = (k, t) => h("li", { class: k === n ? "on" : k < n ? "done" : "" }, h("span", { class: "n" }, String(k)), h("span", { class: "t" }, t));
  return h("ol", { class: "wsteps", "aria-label": "Шаги" }, li(1, "План"), li(2, "Тема и текст"));
}

function foot(...items) { return h("div", { class: "wfoot" }, ...items); }

function stagesOf(p) { return p.stages || []; }

// ---------------------------------------------------------------- шаг 1: план
function planCard(p) {
  const total = stagesOf(p).reduce((a, s) => a + (s.minutes || 0), 0);
  const bar = h("div", { class: "wbar", "aria-hidden": "true" });
  let at = 0;
  const list = h("ol", { class: "wlist" });
  stagesOf(p).forEach((s, i) => {
    bar.append(h("i", { class: s.kind === "break" ? "br" : s.kind === "exercise" ? "ex" : "", style: { flexGrow: String(Math.max(1, s.minutes || 0)) } }));
    if (i < 7) list.append(h("li", null, h("span", { class: "mono t" }, hm(at)), h("span", { class: "sn" }, s.title || "Этап"), h("span", { class: "mono m" }, String(s.minutes || 0))));
    at += s.minutes || 0;
  });
  if (stagesOf(p).length > 7) list.append(h("li", { class: "more" }, "…ещё " + (stagesOf(p).length - 7)));
  return h("button", { class: "wplan", type: "button", "data-id": p.id, "aria-pressed": String(W.plan === p.id) },
    h("div", { class: "wph" }, h("b", null, p.title), h("span", { class: "meta" }, durText(total) + " · " + stagesOf(p).length + " " + plural(stagesOf(p).length, "этап", "этапа", "этапов"))),
    bar, list);
}

function step1(box) {
  crumbs();
  const plans = () => S.plans || [];
  const wz = S.wizard || {};
  // только что сохранённый план может прийти в состояние чуть позже — выбор не сбрасываем, карточка отметится сама
  if (W.plan === null) W.plan = plans().some((p) => p.id === wz.plan) ? wz.plan : (plans()[0] ? plans()[0].id : "none");
  const cards = h("div", { id: "planCards", class: "wplans" });
  const next = () => go("#/new/text?plan=" + encodeURIComponent(W.plan || "none"));
  let sig = "";
  const draw = () => {
    const key = JSON.stringify([plans(), W.plan]);
    if (key === sig) return;
    sig = key;
    clear(cards);
    for (const p of plans()) cards.append(planCard(p));
    cards.append(h("button", { class: "wplan none", type: "button", "data-id": "none", "aria-pressed": String(W.plan === "none") },
      h("div", { class: "wph" }, h("b", null, "Без плана"), h("span", { class: "meta" }, "пустой урок")),
      h("p", { class: "dim" }, "Этапы и минуты добавите сами — или нейросеть разложит урок по длительности.")));
    const own = h("button", { class: "wown", type: "button", id: "ownPlan" }, icon("plus"),
      h("b", null, "Свой план"), h("span", { class: "meta" }, "этапы и минуты — один раз, потом всегда в списке"));
    own.addEventListener("click", () => go("#/new/plan"));
    cards.append(own);
  };
  cards.addEventListener("click", (e) => {
    const c = e.target.closest(".wplan");
    if (!c) return;
    W.plan = c.dataset.id;
    cards.querySelectorAll(".wplan").forEach((x) => x.setAttribute("aria-pressed", String(x === c)));
    sig = JSON.stringify([plans(), W.plan]);
  });
  cards.addEventListener("dblclick", (e) => { if (e.target.closest(".wplan")) next(); });
  draw();
  const pick = btn("Выбрать файл…", { icon: "upload", onClick: () => pickAndImport() });
  pick.id = "pickLessonFile";
  const nextBtn = btn("Далее", { kind: "primary", onClick: next });
  nextBtn.id = "wizNext";
  box.append(h("div", { class: "wrap wwrap" }, stepper(1), h("h1", null, "На чём построить урок?"),
    h("p", { class: "dim lead" }, "План — этапы и минуты урока. Выберите свой обычный формат: урок будет по нему."), cards,
    h("div", { class: "wfile" }, icon("file"), h("span", null, "Уже есть файл урока?"), pick,
      h("span", { class: "meta" }, "или перетащите его в окно: .autoprint, презентация .pptx или .pdf, .md, .ipynb")),
    foot(btn("Отмена", { kind: "ghost", onClick: () => go("#/lessons") }), h("span", { class: "spacer" }), nextBtn)));
  return { update: draw, onDrop: (paths) => importFiles(paths) };
}

// ---------------------------------------------------------------- свой план
function planEditor(box) {
  crumbs();
  const structs = S.structures || [];
  if (!W.draft) W.draft = { title: "Мой план", start: "empty", stages: [{ title: "Начало", minutes: 5, kind: "", exercise: "" }] };
  const d = W.draft;
  const title = h("input", { class: "inp", id: "planTitle", value: d.title, "aria-label": "Название плана" });
  title.addEventListener("input", () => { d.title = title.value; });
  const start = seg(START_ORDER.filter((k) => k === "empty" || structs.some((s) => s.key === k)).map((k) => ({ value: k, label: START_LABELS[k] })),
    d.start, (v) => {
      d.start = v;
      const st = structs.find((s) => s.key === v);
      d.stages = st && st.stages.length ? st.stages.map((s) => ({ title: s.title, minutes: s.minutes, kind: s.kind || "", exercise: "" }))
        : [{ title: "Начало", minutes: 5, kind: "", exercise: "" }];
      drawStages();
    }, { label: "Начать с" });
  start.id = "planStart";
  const list = h("div", { id: "planStages", class: "pstages" });
  const total = h("div", { id: "planTotal", class: "ptotal" });
  const sum = () => { total.textContent = "Всего " + durText(d.stages.reduce((a, s) => a + (parseInt(s.minutes, 10) || 0), 0)); };
  const ex = S.exercises || [];
  function row(s, i) {
    const t = h("input", { class: "inp ptitle", value: s.title, "aria-label": "Название этапа" });
    t.addEventListener("input", () => { s.title = t.value; });
    const m = numberField(s.minutes, { min: 0, max: 600, step: 5, unit: "мин", label: "Минуты этапа" });
    m.input.classList.add("pmins");
    m.input.addEventListener("input", () => { s.minutes = Math.max(0, Math.min(600, parseInt(m.input.value, 10) || 0)); sum(); });
    const k = select(KIND_NAMES, s.kind, (v) => { s.kind = v; drawStages(); }, { label: "Вид этапа" });
    k.classList.add("pkind");
    const exSel = s.kind === "exercise" && ex.length
      ? select([["", "Видео: первое по списку"], ...ex.map((x) => [x, x])], s.exercise || "", (v) => { s.exercise = v; }, { label: "Видео зарядки" })
      : null;
    if (exSel) exSel.classList.add("pex");
    const move = (dir) => { const j = i + dir; if (j < 0 || j >= d.stages.length) return; [d.stages[i], d.stages[j]] = [d.stages[j], d.stages[i]]; drawStages(); };
    const up = iconBtn("chevron-up", "Выше", () => move(-1), { size: "sm", kind: "ghost", cls: "up" });
    const down = iconBtn("chevron-down", "Ниже", () => move(1), { size: "sm", kind: "ghost", cls: "down" });
    const del = iconBtn("trash", "Удалить этап", () => { d.stages.splice(i, 1); drawStages(); }, { size: "sm", kind: "ghost", cls: "del" });
    up.disabled = i === 0;
    down.disabled = i === d.stages.length - 1;
    del.disabled = d.stages.length === 1;
    return h("div", { class: "pstage" + (s.kind ? " k-" + s.kind : "") }, h("span", { class: "pn mono" }, String(i + 1)), t, m, k, exSel, h("span", { class: "pacts" }, up, down, del));
  }
  function drawStages() {
    clear(list);
    d.stages.forEach((s, i) => list.append(row(s, i)));
    sum();
  }
  drawStages();
  const add = btn("Добавить этап", { icon: "plus", kind: "ghost", onClick: () => { d.stages.push({ title: "Этап", minutes: 5, kind: "", exercise: "" }); drawStages(); } });
  add.id = "addStage";
  const save = btn("Сохранить план", { kind: "primary", onClick: async () => {
    save.disabled = true;
    try {
      const r = await call({ cmd: "plan_create", title: d.title, stages: d.stages });
      W.plan = r.id;
      W.draft = null;
      go("#/new");
    } catch (e) { fail(e); } finally { save.disabled = false; }
  } });
  save.id = "savePlan";
  const back = btn("Назад", { kind: "ghost", onClick: () => go("#/new") });
  back.id = "planBack";
  box.append(h("div", { class: "wrap wwrap" }, stepper(1), h("h1", null, "Новый план"),
    h("p", { class: "dim lead" }, "Этапы и минуты вашего обычного урока. План сохранится и будет в списке всегда."),
    field("Название", title), field("Начать с", start), list, h("div", { class: "prow2" }, add, total),
    foot(back, h("span", { class: "spacer" }), save)));
  title.focus({ preventScroll: true });
  title.select();
  return {};
}

// ---------------------------------------------------------------- шаг 2: тема и текст
function aiState() { return S.ai || {}; }

function whoLine(onUse) {
  const ai = aiState();
  if (ai.configured) {
    const ch = h("button", { class: "linkbtn", type: "button" }, "Сменить…");
    ch.addEventListener("click", () => go("#/settings/ai"));
    return h("div", { id: "aiWho", class: "who" }, icon("sparkles", "sm"), "Сделает: ", h("b", null, ai.name || "нейросеть"),
      ai.model ? " · " + ai.model : "", " · ", ch);
  }
  const cli = ai.cli || {};
  const box = h("div", { class: "who off" }, h("span", null, "Нейросеть не подключена."));
  if (cli.claude) { const b = btn("Использовать Claude Code (по подписке)", { size: "sm", onClick: () => onUse("claude") }); b.id = "useClaude"; box.append(b); }
  if (cli.codex) { const b = btn("Использовать Codex (по подписке)", { size: "sm", onClick: () => onUse("codex") }); b.id = "useCodex"; box.append(b); }
  if (!cli.claude && !cli.codex) { const b = btn("Подключить нейросеть…", { size: "sm", onClick: () => go("#/settings/ai") }); b.id = "connectAi"; box.append(b); }
  box.append(h("span", { class: "meta" }, "Или «Скопировать задание» — для своего чата."));
  return box;
}

function step2(box, planId) {
  crumbs();
  const plan = (S.plans || []).find((p) => p.id === planId) || null;
  W.plan = plan ? plan.id : "none";
  const wz = S.wizard || {};
  if (W.cls === null) W.cls = wz.cls || "";
  if (W.minutes === null) W.minutes = wz.minutes || 90;
  if (W.brk === null) W.brk = wz.brk || 0;
  if (!W.code) W.code = { style: ["comments", "steps", "parts"].includes(wz.style) ? wz.style : "steps", task: wz.task !== false,
    explain: wz.explain !== false, keep: wz.keep !== false, detail: wz.detail === "full" ? "full" : "short" };
  const topic = h("input", { class: "inp", id: "topic", value: W.topic, placeholder: "например, Циклы for в Python", "aria-label": "Тема урока" });
  topic.addEventListener("input", () => { W.topic = topic.value; });
  const cls = h("input", { class: "inp", id: "cls", value: W.cls, placeholder: "например, 5 класс или 11–12 лет" });
  cls.addEventListener("input", () => { W.cls = cls.value; });
  const fields = [field("Тема урока", topic), field("Класс или возраст", cls, { hint: "необязательно" })];
  let planLine = null;
  if (!plan) {
    const mins = numberField(W.minutes, { min: 10, max: 600, step: 5, unit: "мин", label: "Длительность", onChange: (v) => { W.minutes = v; } });
    mins.input.id = "minutes";
    mins.input.addEventListener("input", () => { W.minutes = parseInt(mins.input.value, 10) || W.minutes; });
    const brk = numberField(W.brk, { min: 0, max: 60, step: 5, unit: "мин", label: "Перерыв", onChange: (v) => { W.brk = v; } });
    brk.input.id = "breakMin";
    brk.input.addEventListener("input", () => { W.brk = parseInt(brk.input.value, 10) || 0; });
    fields.push(field("Длительность", mins), field("Перерыв", brk, { hint: "0 — без перерыва" }));
  } else {
    const total = stagesOf(plan).reduce((a, s) => a + (s.minutes || 0), 0);
    const ch = h("button", { class: "linkbtn", type: "button" }, "Сменить");
    ch.addEventListener("click", () => go("#/new"));
    planLine = h("div", { id: "planLine", class: "planline" }, icon("layers", "sm"),
      h("span", null, "План «" + plan.title + "» · " + durText(total) + " · " + stagesOf(plan).length + " " + plural(stagesOf(plan).length, "этап", "этапа", "этапов")), ch);
  }
  // ---- откуда взять текст
  const SRC = [
    { key: "ai", icon: "sparkles", title: "Составит нейросеть", sub: "по теме или по вашему файлу" },
    { key: "paste", icon: "clipboard", title: "Вставить текст", sub: "ответ своего чата, Markdown, код" },
    { key: "manual", icon: "pencil", title: "Заполню сам", sub: "этапы из плана, внутри пусто" },
  ];
  const cards = h("div", { class: "wsrcs", role: "radiogroup", "aria-label": "Откуда взять текст этапов" });
  const panel = h("div", { id: "srcPanel" });
  for (const s of SRC) {
    const c = h("button", { class: "wsrc", type: "button", "data-src": s.key, "aria-pressed": String(W.src === s.key) },
      icon(s.icon), h("b", null, s.title), h("span", { class: "meta" }, s.sub));
    c.addEventListener("click", () => { W.src = s.key; cards.querySelectorAll(".wsrc").forEach((x) => x.setAttribute("aria-pressed", String(x === c))); drawPanel(); });
    cards.append(c);
  }
  let pasteTimer = 0, aiSig = "";
  const ctx = () => ({ plan: W.plan, topic: W.topic.trim(), cls: W.cls, minutes: W.minutes, brk: W.brk });
  const copyTask = async (what) => {
    try { await call({ cmd: "copy_prompt", ...ctx(), what, material: W.material, code: W.code }); } catch (e) { fail(e); }
  };
  async function useCli(which) {
    try { await call({ cmd: "use_cli", which }); } catch (e) { fail(e); }
  }
  function aiPanel() {
    const files = h("div", { id: "matFiles", class: "mfiles" });
    const drawFiles = () => {
      clear(files);
      W.files.forEach((p, i) => files.append(h("span", { class: "mfile" }, icon("file", "sm"), h("span", null, p.split(/[\\/]/).pop()),
        iconBtn("close", "Убрать файл", () => { W.files.splice(i, 1); drawFiles(); }, { size: "sm", kind: "ghost" }))));
    };
    drawFiles();
    const pick = btn("Выбрать файл…", { icon: "upload", size: "sm", onClick: async () => {
      let ps = [];
      try { ps = await call({ cmd: "pick_files", purpose: "material" }); } catch (e) { fail(e); return; }
      for (const p of ps || []) if (!W.files.includes(p)) W.files.push(p);
      drawFiles();
    } });
    pick.id = "pickMaterial";
    const mat = h("textarea", { id: "material", class: "ta mono", rows: "4", placeholder: "…или вставьте сюда текст методички или код" });
    mat.value = W.material;
    mat.addEventListener("input", () => { W.material = mat.value; });
    const codeBox = h("div", { class: "codeopts", hidden: W.what !== "code" });
    const cs = seg(CODE_STYLES, W.code.style, (v) => { W.code.style = v; }, { label: "Как разобрать код" });
    cs.id = "codeStyle";
    codeBox.append(cs,
      toggle("Краткое условие задачи", W.code.task, (v) => { W.code.task = v; }),
      toggle("Пояснения для учеников", W.code.explain, (v) => { W.code.explain = v; }),
      toggle("Не менять код — только комментарии и разметка", W.code.keep, (v) => { W.code.keep = v; }),
      seg([{ value: "short", label: "Коротко" }, { value: "full", label: "Подробно" }], W.code.detail, (v) => { W.code.detail = v; }, { label: "Комментарии" }));
    const what = seg([{ value: "lesson", label: "Методичка или презентация — урок по этапам" }, { value: "code", label: "Код — разобрать для набора" }],
      W.what, (v) => { W.what = v; codeBox.hidden = v !== "code"; }, { cls: "vseg", label: "Что это" });
    what.id = "what";
    const ans = h("textarea", { id: "aiAnswer", class: "ta mono", rows: "3", placeholder: "Ответ своего чата — вставьте сюда: урок соберётся из него" });
    ans.value = W.answer;
    ans.addEventListener("input", () => { W.answer = ans.value; });
    const copy = btn("Скопировать задание", { icon: "copy", size: "sm", onClick: () => copyTask(W.what) });
    copy.id = "copyTaskAi";
    return h("div", { class: "srcpanel" },
      h("div", { class: "mdrop" }, icon("upload"), h("div", { class: "mtext" }, h("b", null, "Материал — необязательно"),
        h("span", { class: "meta" }, "Перетащите методичку, презентацию или код (pdf, docx, pptx, txt, md, ipynb, py). Без материала — урок по теме.")), pick),
      files, mat, field("Что это", what), codeBox, whoLine(useCli),
      h("details", { class: "ownchat" }, h("summary", null, "Спросить свой чат вместо этого"),
        h("div", { class: "wrow" }, copy, h("span", { class: "meta" }, "вставьте задание в свой чат, ответ — сюда:")), ans));
  }
  function pastePanel() {
    const ta = h("textarea", { id: "pasteText", class: "ta mono", rows: "9", placeholder: "Ответ нейросети (блок ~~~markdown или JSON), Markdown с кодом, тетрадка Jupyter или просто код" });
    ta.value = W.paste;
    const sum = h("div", { id: "pasteSummary", class: "psum", "aria-live": "polite" });
    const slidesBtn = btn("Подставить слайды из презентации…", { size: "sm", icon: "slide", onClick: async () => {
      try { const ps = await call({ cmd: "pick_files", purpose: "presentation" }); if (ps && ps.length) { W.slides = ps[0]; preview(); } } catch (e) { fail(e); }
    } });
    slidesBtn.id = "pasteSlides";
    slidesBtn.hidden = true;
    const preview = async () => {
      if (!W.paste.trim()) { sum.textContent = ""; slidesBtn.hidden = true; return; }
      try {
        const r = await call({ cmd: "paste_preview", text: W.paste, lang: W.lang, plan: W.plan, slides: W.slides });
        clear(sum);
        sum.classList.toggle("bad", !r.ok);
        sum.append(h("span", null, r.summary));
        for (const n of r.notes || []) sum.append(h("small", null, n));
        slidesBtn.hidden = !r.slides_empty;
      } catch (e) { sum.textContent = e.message; }
    };
    ta.addEventListener("input", () => { W.paste = ta.value; clearTimeout(pasteTimer); pasteTimer = setTimeout(preview, 300); });
    const clip = btn("Вставить из буфера", { icon: "clipboard", size: "sm", onClick: async () => {
      try { ta.value = W.paste = await call({ cmd: "clipboard_text" }); preview(); } catch (e) { fail(e); }
    } });
    clip.id = "pasteClip";
    const lang = select(LANGS, W.lang, (v) => { W.lang = v; preview(); }, { label: "Язык кода" });
    lang.id = "pasteLang";
    const copy = btn("Скопировать задание", { icon: "copy", size: "sm", onClick: () => copyTask("lesson") });
    copy.id = "copyTaskPaste";
    if (W.paste) setTimeout(preview, 0);
    return h("div", { class: "srcpanel" },
      h("ol", { class: "psteps" },
        h("li", null, h("span", null, "Скопируйте задание — план, тема, класс и видео зарядок уже внутри"), copy),
        h("li", null, "Отправьте его в любую нейросеть вместе с методичкой"),
        h("li", null, "Вставьте ответ сюда")),
      ta, h("div", { class: "wrow" }, clip, lang, slidesBtn), sum);
  }
  function manualPanel() {
    return h("div", { class: "srcpanel" }, h("p", { class: "dim" }, plan
      ? "Этапы — из плана «" + plan.title + "», внутри пусто: впишете сами. Заготовки плана попадут в урок."
      : "Один этап «Начало», внутри пусто: этапы и текст добавите сами."));
  }
  function drawPanel() {
    clear(panel);
    aiSig = JSON.stringify(aiState());
    panel.append(W.src === "paste" ? pastePanel() : W.src === "manual" ? manualPanel() : aiPanel());
  }
  drawPanel();
  const jobs = jobsBox("wjobs");
  jobs.el.id = "jobs";
  const create = btn("Создать урок", { kind: "primary", icon: "check", onClick: async () => {
    let d;
    if (W.src === "manual") d = { ...ctx(), source: "manual" };
    else if (W.src === "paste") {
      if (!W.paste.trim()) { toast("Вставьте ответ нейросети или текст урока"); document.getElementById("pasteText")?.focus(); return; }
      d = { ...ctx(), source: "paste", text: W.paste, lang: W.lang, slides: W.slides };
    } else if (W.answer.trim()) d = { ...ctx(), source: "paste", text: W.answer, what: W.what, code: W.code };
    else {
      if (!aiState().configured) { toast("Подключите нейросеть — или «Спросить свой чат» и вставьте ответ", { warn: true }); return; }
      d = { ...ctx(), source: "ai", files: W.files, material: W.material, what: W.what, code: W.code };
    }
    create.disabled = true;
    try {
      const r = await call({ cmd: "wizard_create", ...d });
      Object.assign(W, { topic: "", files: [], material: "", answer: "", paste: "", slides: "" });
      if (r && r.job) { topic.value = ""; drawPanel(); jobs.el.scrollIntoView({ behavior: "smooth", block: "nearest" }); }
    } catch (e) { fail(e); } finally { create.disabled = false; }
  } });
  create.id = "createLesson";
  const back = btn("Назад", { kind: "ghost", onClick: () => go("#/new") });
  back.id = "wizBack";
  box.append(h("div", { class: "wrap wwrap" }, stepper(2), h("h1", null, "Тема и текст"), planLine,
    h("div", { class: "wfields" + (plan ? "" : " four") }, ...fields),
    h("h2", { class: "wh2" }, "Откуда взять текст этапов?"), cards, panel, jobs.el,
    foot(back, h("span", { class: "spacer" }), create)));
  topic.focus({ preventScroll: true });               // поле темы — в фокусе сразу
  return {
    update: () => { if (W.src === "ai" && JSON.stringify(aiState()) !== aiSig) drawPanel(); },
    onDrop: (paths) => {
      if (W.src !== "ai") { W.src = "ai"; cards.querySelectorAll(".wsrc").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.src === "ai"))); }
      for (const p of paths) if (!W.files.includes(p)) W.files.push(p);
      drawPanel();
    },
    destroy: () => { clearTimeout(pasteTimer); jobs.destroy(); },
  };
}

// ---------------------------------------------------------------- экран
registerDrop("wizard", (files) => { if (cur && cur.onDrop) cur.onDrop(files.map((f) => f.path)); });

export function wizardView(root, r) {
  W.plan = null;                    // пришли в «Новый урок» заново — план по умолчанию: последний выбранный
  const box = h("div", { class: "page wizard" });
  root.append(box);
  const show = (r2) => {
    if (cur && cur.destroy) cur.destroy();
    clear(box);
    const step = r2.parts[1] || "";
    cur = step === "plan" ? planEditor(box) : step === "text" ? step2(box, r2.query.plan || "") : step1(box);
  };
  show(r);
  return {
    route: show,
    update: () => { if (cur && cur.update) cur.update(); },
    destroy: () => { if (cur && cur.destroy) cur.destroy(); cur = null; },
  };
}
