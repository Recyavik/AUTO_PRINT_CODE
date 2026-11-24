// Листы урока (пункты его меню): «Экспорт…», «Печать или PDF…», «План урока…», «Обновить по ответу нейросети…»;
// «Подставить слайды из презентации…» и «Разложить по этапам» — сразу действием. Меню одно — у названия урока
// и правым щелчком в «Уроках»; пункты добавляются сюда, в lessonmenu.extraItems.
"use strict";
import { S, L as LC, send, call, go } from "./core.js";
import { h, btn, seg, toggle, sheet, ask, toast, clear } from "./ui.js";
import { extraItems, lessonById } from "./lessonmenu.js";
import { durText, plural } from "../lesson/state.js";

const mb = (n) => (n >= 1048576 ? (n / 1048576).toFixed(1) + " МБ" : Math.max(1, Math.round(n / 1024)) + " КБ");
const safeName = (s) => (s || "").replace(/[\\/:*?"<>|]/g, "").trim() || "урок";
const fail = (e) => toast(String((e && e.message) || e), { warn: true });

// ---------------------------------------------------------------- экспорт
const FORMATS = [
  { value: "package", label: "Урок одним файлом (.autoprint)", ext: "autoprint", filter: "Урок AutoPrint (*.autoprint)" },
  { value: "md", label: "Markdown (.md)", ext: "md", filter: "Markdown (*.md)" },
  { value: "ipynb", label: ".ipynb", ext: "ipynb", filter: "Jupyter (*.ipynb)" },
  { value: "students", label: "Тетрадка для учеников (только код)", ext: "ipynb", filter: "Jupyter (*.ipynb)" },
  { value: "json", label: ".json", ext: "json", filter: "JSON (*.json)" },
];

/** Лист «Экспорт»: урок id или все уроки (all). */
export function exportSheet(id, all = false) {
  const x = all ? null : lessonById(id);
  if (!all && !x) return;
  const q = all ? { all: true } : { id };
  const opts = { fmt: "package", plans: true, looks: true };
  const pkg = h("div", { class: "pkgopts" }, h("p", { class: "meta" }, "Считаю, сколько весят картинки…"));
  call({ cmd: "export_sizes", ...q }).then((s) => {
    clear(pkg);
    const pics = toggle("Картинки и слайды урока — " + mb(s.pics), true, null, "внутри всегда");
    pics.input.disabled = true;
    opts.plans = !!s.linked;
    const plan = toggle("План урока — этапы и минуты, по которым идёт урок", opts.plans, (v) => { opts.plans = v; });
    plan.input.disabled = !s.linked;
    const looks = toggle("Оформление экрана учеников: фон, заставка перерыва, видео зарядок — " + mb(s.looks), true,
      (v) => { opts.looks = v; });
    pkg.append(pics, plan, looks, h("p", { class: "meta" },
      "Внутри — обычный архив, и в нём понятная копия урока (.md с картинками): её можно открыть и без AutoPrint."));
  }).catch((e) => { clear(pkg); pkg.append(h("p", { class: "meta" }, "Размер не посчитать: " + e.message)); });
  const body = h("div", { class: "exportsheet" });
  if (all) {
    body.append(h("p", { class: "dim" }, "Один файл .autoprint — все уроки и планы с картинками. Отдайте его коллеге или "
      + "перенесите на другой компьютер: «Импорт» откроет всё так же."));
  } else {
    body.append(h("div", { class: "flabel" }, "Формат"),
      seg(FORMATS.map((f) => ({ value: f.value, label: f.label })), opts.fmt, (v) => { opts.fmt = v; pkg.hidden = v !== "package"; },
        { cls: "vseg", label: "Формат" }));
  }
  body.append(pkg);
  let api = null;
  const save = async () => {
    const f = FORMATS.find((y) => y.value === opts.fmt);
    const base = all ? "Уроки AutoPrint" : safeName(x.title);
    const name = opts.fmt === "students" ? base + " — для учеников.ipynb" : base + "." + f.ext;
    let path = "";
    try { path = await call({ cmd: "pick_save", name, filter: f.filter, title: all ? "Все уроки одним файлом" : "Экспорт урока" }); } catch (e) { fail(e); return; }
    if (!path) return;                                       // передумали — лист остаётся
    try {
      await call({ cmd: "export", ...q, fmt: opts.fmt, path, plans: opts.plans, looks: opts.looks });
      if (api) api.done(true);
    } catch (e) { toast("Не сохранилось: " + e.message, { warn: true }); }
  };
  sheet(all ? "Все уроки одним файлом" : "Экспорт урока «" + x.title + "»", body, [
    { spacer: true }, { label: "Отмена", kind: "ghost", value: null },
    { label: "Сохранить…", kind: "primary", check: () => { save(); return false; } },
  ], { wide: true, onOpen: (a) => { api = a; } });
}

// ---------------------------------------------------------------- печать и PDF
const PRINT_DEF = { size: "normal", answers: true, code: true, slides: "big" };
function printPrefs() {
  try { return Object.assign({}, PRINT_DEF, JSON.parse(localStorage.getItem("suflor.print") || "{}")); } catch (e) { return { ...PRINT_DEF }; }
}

function waitFor(pred, ms) {
  return new Promise((resolve) => {
    const end = Date.now() + ms;
    const step = () => { if (pred()) resolve(true); else if (Date.now() > end) resolve(false); else setTimeout(step, 60); };
    step();
  });
}

/** Печатается урок на экране урока: из «Уроков» — сначала открыть его. */
function showLesson(id) {
  if (location.hash !== "#/lesson/" + id) go("#/lesson/" + id);
  return waitFor(() => document.body.dataset.view === "lesson" && LC.state && LC.state.lesson && LC.state.lesson.id === id
    && !!document.querySelector("#main .stage, #main .blk"), 8000);
}

export async function printSheet(id) {
  const x = lessonById(id);
  if (!x) return;
  if (!(await showLesson(id))) { toast("Урок не открылся — печать не начата", { warn: true }); return; }
  const pr = printPrefs();
  const body = h("div", { class: "printsheet" },
    h("div", { class: "flabel" }, "Размер текста"),
    seg([{ value: "small", label: "Мелко" }, { value: "normal", label: "Обычно" }, { value: "large", label: "Крупно" }], pr.size, (v) => { pr.size = v; }),
    h("div", { class: "flabel" }, "Слайды и картинки"),
    seg([{ value: "big", label: "Крупно" }, { value: "thumbs", label: "Миниатюрами" }, { value: "none", label: "Без" }], pr.slides, (v) => { pr.slides = v; }),
    toggle("Ответы к вопросам", pr.answers, (v) => { pr.answers = v; }),
    toggle("Код", pr.code, (v) => { pr.code = v; }),
    h("p", { class: "meta" }, "Печатается текст урока — без кнопок и полос программы. Цветные плашки — если принтер цветной."));
  let api = null;
  const run = async (kind) => {
    try { localStorage.setItem("suflor.print", JSON.stringify(pr)); } catch (e) { /* нет хранилища */ }
    let path = "";
    if (kind === "pdf") {
      try { path = await call({ cmd: "pick_save", name: safeName(x.title) + ".pdf", filter: "PDF (*.pdf)", title: "Сохранить PDF" }); } catch (e) { fail(e); return; }
      if (!path) return;
    }
    if (api) api.done(kind);
    // классы печати — только на время печати: страница печатается с ними, потом всё как было
    const cls = ["print-size-" + pr.size, "print-slides-" + pr.slides];
    if (!pr.answers) cls.push("print-no-answers");
    if (!pr.code) cls.push("print-no-code");
    document.body.classList.add(...cls);
    try { await call(kind === "pdf" ? { cmd: "print_pdf", path } : { cmd: "print" }); } catch (e) { fail(e); } finally { document.body.classList.remove(...cls); }
  };
  sheet("Печать или PDF", body, [
    { spacer: true }, { label: "Отмена", kind: "ghost", value: null },
    { label: "Печать…", check: () => { run("print"); return false; } },
    { label: "Сохранить PDF…", kind: "primary", check: () => { run("pdf"); return false; } },
  ], { onOpen: (a) => { api = a; } });
}

// ---------------------------------------------------------------- план урока
async function leaveLive(what) {
  if (!S.live) return true;
  return ask("Идёт урок «" + (S.live.title || "") + "». Завершить его и " + what + "?", { title: "Идёт урок", ok: "Завершить урок", danger: true });
}

export function planSheet(id) {
  const x = lessonById(id);
  if (!x) return;
  const plan = x.plan_id ? (S.plans || []).find((p) => p.id === x.plan_id) : null;
  const list = h("div", { class: "menu sheetlist" });
  let api = null;
  const item = (label, hint, on, danger = false) => {
    const b = h("button", { class: "mi" + (danger ? " danger" : ""), type: "button" }, h("span", { class: "ml" }, label),
      hint ? h("span", { class: "mh" }, hint) : null);
    b.addEventListener("click", () => { if (api) api.done(true); on(); });
    list.append(b);
  };
  if (plan) {
    item("Открыть план «" + plan.title + "»", "этапы и минуты — у всех уроков по нему", async () => {
      if (await leaveLive("открыть план «" + plan.title + "»")) send({ cmd: "open", lesson: plan.id, force: !!S.live });
    });
    item("Отвязать от плана", "этапы останутся, их можно будет править здесь", async () => {
      if (await ask("Отвязать урок «" + x.title + "» от плана «" + plan.title + "»? Этапы останутся, но правка плана их больше не изменит.",
        { title: "Отвязать от плана", ok: "Отвязать" })) call({ cmd: "plan_link", id, op: "unlink" }).catch(fail);
    });
  } else {
    const plans = S.plans || [];
    list.append(h("div", { class: "phead" }, "Привязать к плану"));
    if (!plans.length) list.append(h("p", { class: "meta" }, "Планов пока нет — сделайте план из этапов этого урока."));
    for (const p of plans) {
      item(p.title, durText(p.total) + " · " + p.stages.length + " " + plural(p.stages.length, "этап", "этапа", "этапов"), async () => {
        try {
          const r = await call({ cmd: "plan_link", id, op: "link", plan: p.id });
          if (r && r.notes && r.notes.length) toast(r.notes.join(" "));
        } catch (e) { fail(e); }
      });
    }
    if (x.stages) {
      list.append(h("div", { class: "psep" }));
      item("Сделать из этапов план", "этапы и минуты этого урока — для следующих уроков", () => call({ cmd: "plan_link", id, op: "make" }).catch(fail));
    }
  }
  const lead = plan ? "Урок идёт по плану «" + plan.title + "»: этапы и минуты — из плана."
    : "Урок без плана. План — этапы и минуты, общие для многих уроков (онлайн-пара, школьный урок).";
  sheet("План урока «" + x.title + "»", h("div", { class: "plansheet" }, h("p", { class: "dim" }, lead), list),
    [{ spacer: true }, { label: "Закрыть", kind: "ghost", value: null }], { onOpen: (a) => { api = a; } });
}

// ---------------------------------------------------------------- ответ нейросети
export function answerSheet(id) {
  const x = lessonById(id);
  if (!x) return;
  const ta = h("textarea", { class: "ta ansta", rows: "11", "aria-label": "Ответ нейросети",
    placeholder: "Вставьте ответ чата целиком (Ctrl+V) — блок ~~~markdown" });
  const copy = btn("Скопировать задание", { icon: "copy", onClick: () => call({ cmd: "prompt", id }).catch(fail) });
  const body = h("div", { class: "answersheet" },
    h("p", { class: "dim" }, "1. Скопируйте задание и вставьте его в свой чат (ChatGPT, GigaChat, Алиса, DeepSeek) вместе с презентацией или методичкой."),
    h("div", null, copy),
    h("p", { class: "dim" }, "2. Ответ чата вставьте сюда. Получится копия урока" + (x.kind === "plan" ? " по этому плану" : "")
      + " рядом с исходным; исходный не меняется."),
    ta);
  sheet("Обновить по ответу нейросети", body, [
    { spacer: true }, { label: "Отмена", kind: "ghost", value: null },
    { label: "Добавить урок", kind: "primary", check: () => {
      const v = ta.value.trim();
      if (!v) { ta.focus(); toast("Вставьте ответ нейросети в поле"); return false; }
      call({ cmd: "answer", id, text: v }).catch(fail);
      return true;
    } },
  ], { wide: true });
}

// ---------------------------------------------------------------- слайды из презентации
export async function slidesFill(id) {
  let paths = [];
  try { paths = await call({ cmd: "pick_files", purpose: "presentation" }); } catch (e) { fail(e); return; }
  if (!paths || !paths.length) return;
  toast("Подставляю слайды из презентации…");
  try { await call({ cmd: "slides_fill", id, path: paths[0] }); } catch (e) { fail(e); }
}

// ---------------------------------------------------------------- пункты меню урока
extraItems.push((x) => {
  const items = [
    { label: "Экспорт…", icon: "download", on: () => exportSheet(x.id) },
    { label: "Печать или PDF…", icon: "printer", on: () => printSheet(x.id) },
  ];
  if (x.kind !== "plan") items.push({ label: "План урока…", icon: "layers", on: () => planSheet(x.id) });
  items.push({ label: "Обновить по ответу нейросети…", icon: "sparkles", on: () => answerSheet(x.id) });
  if (x.slides_empty) items.push({ label: "Подставить слайды из презентации…", icon: "slide", on: () => slidesFill(x.id) });
  if (x.scenario) items.push({ label: "Разложить по этапам (⏱ этапы, 🗣 реплики)", icon: "wand", on: () => send({ cmd: "recognize", id: x.id }) });
  return items;
});
