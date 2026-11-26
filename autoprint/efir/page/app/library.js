// «Уроки»: продолжить (или идущий урок), планы, все уроки по группам планов, поиск, импорт перетаскиванием.
"use strict";
import { S, on, send, call, now, go } from "./core.js";
import { h, btn, iconBtn, clear, toast, menu } from "./ui.js";
import { icon } from "./icons.js";
import { setCrumbs, registerDrop } from "./shell.js";
import { lessonMenuItems, menuAt, lessonById } from "./lessonmenu.js";
import { exportSheet } from "./sheets.js";
import { jobsBox } from "./jobsbox.js";

export function plural(n, one, few, many) {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  return b === 1 ? one : b >= 2 && b <= 4 ? few : many;
}
export function durText(min) {
  min = Math.max(0, Math.round(min));
  const hh = Math.floor(min / 60), m = min % 60;
  return hh && m ? `${hh} ч ${m} мин` : hh ? `${hh} ч` : `${m} мин`;
}
export function mmss(sec) {
  sec = Math.max(0, Math.ceil(sec));
  const hh = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return hh ? `${hh}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}
const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
export function whenText(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000), today = new Date(now());
  const day = (x) => Math.floor(new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime() / 86400000);
  const diff = day(today) - day(d);
  if (diff <= 0) return "сегодня";
  if (diff === 1) return "вчера";
  if (diff < 7) return `${diff} ${plural(diff, "день", "дня", "дней")} назад`;
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

// ---------------------------------------------------------------- импорт
export async function importFiles(paths) {
  if (!paths || !paths.length) return null;
  try { return await call({ cmd: "import_paths", paths }); } catch (e) { toast("Не импортировано: " + e.message, { warn: true }); return null; }
}
export async function pickAndImport() {
  try {
    const paths = await call({ cmd: "pick_files", purpose: "import" });
    return importFiles(paths);
  } catch (e) { toast(e.message, { warn: true }); return null; }
}
on("shortcut", (k) => { if (k === "open") pickAndImport(); });
registerDrop("lessons", (files) => importFiles(files.map((f) => f.path)));

/** Ответ своего чата: «Новый урок» → «Тема и текст» с «Ответ нейросети» — задание для чата и поле ответа. plan — по
 *  какому плану (по умолчанию — последний выбранный). */
export function answerImport(plan) {
  const wz = S.wizard || {};
  const p = plan || ((S.plans || []).some((x) => x.id === wz.plan) ? wz.plan : "none");
  go("#/new/text?plan=" + encodeURIComponent(p) + "&src=paste");
}

/** «Импорт»: файл урока или ответ нейросети — на виду, а не только перетаскиванием и Ctrl+O. */
export function importMenu(anchor) {
  menu(anchor, [
    { label: "Файл урока…", icon: "file", hint: ".autoprint, презентация .pptx или .pdf, .md, .ipynb — или перетащите в окно",
      on: () => pickAndImport() },
    { label: "Ответ нейросети…", icon: "sparkles", hint: "скопировать задание для своего чата (ChatGPT, GigaChat…) и вставить ответ",
      on: () => answerImport() },
  ], { align: "right", cls: "stack2" });
}

// ---------------------------------------------------------------- экран
export function lessonsView(root) {
  setCrumbs([{ label: "Уроки" }]);
  const search = h("input", { id: "libSearch", type: "search", placeholder: "Найти урок", "aria-label": "Найти урок",
    autocomplete: "off" });
  const exportAll = iconBtn("download", "Уроки одним файлом (.autoprint) — все или отмеченные", () => exportSheet(null, true), { kind: "ghost" });
  exportAll.id = "exportAll";
  const importBtn = btn("Импорт", { icon: "upload", onClick: () => importMenu(importBtn) });
  importBtn.id = "importBtn";
  const newBtn = h("a", { class: "btn primary", id: "newLessonBtn", href: "#/new" }, icon("plus"), h("span", null, "Новый урок"));
  const cont = h("section", { id: "continueCard", class: "today", hidden: true });
  const jobs = jobsBox("libjobs");                // нейросеть составляет урок — ход виден и здесь
  const plansGrid = h("div", { id: "plansGrid", class: "plans" });
  const list = h("div", { id: "lessonList", class: "list", role: "list" });
  const plansSect = h("section", { class: "sect" }, h("h2", null, "Планы", h("span", { class: "meta" }, "этапы и время, по которым строятся уроки")), plansGrid);
  const page = h("div", { class: "page" }, h("div", { class: "wrap" },
    h("div", { class: "pagehead" }, h("h1", null, "Уроки"),
      h("div", { class: "phact" }, h("label", { class: "search" }, icon("search", "sm"), search), exportAll, importBtn, newBtn)),
    jobs.el, cont, plansSect, h("section", { class: "sect" }, h("h2", null, "Все уроки"), list)));
  root.append(page);

  let sig = "", renaming = "", lastOpen = { id: "", at: 0 };

  const open = (id) => {                         // щелчок и двойной щелчок подряд — одно открытие
    const t = Date.now();
    if (lastOpen.id === id && t - lastOpen.at < 700) return;
    lastOpen = { id, at: t };
    send({ cmd: "open", lesson: id });
  };

  function rename(id) {
    const row = list.querySelector(`.lrow[data-id="${CSS.escape(id)}"]`) || plansGrid.querySelector(`.pcard[data-id="${CSS.escape(id)}"]`);
    const x = lessonById(id);
    if (!row || !x) return;
    renaming = id;
    const tt = row.querySelector(".tt");
    const inp = h("input", { class: "inp", value: x.title, "aria-label": "Название" });
    tt.replaceWith(inp);
    inp.focus();
    inp.select();
    let done = false;
    const finish = async (save) => {
      if (done) return;
      done = true;
      renaming = "";
      const v = inp.value.trim();
      if (save && v && v !== x.title) await call({ cmd: "rename", id, title: v }).catch(() => {});
      sig = "";
      render();
      const again = list.querySelector(`.lrow[data-id="${CSS.escape(id)}"]`);
      if (again) again.focus();
    };
    inp.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Enter") { e.preventDefault(); finish(true); } else if (e.key === "Escape") { e.preventDefault(); finish(false); }
    });
    inp.addEventListener("blur", () => finish(true));
    inp.addEventListener("click", (e) => e.stopPropagation());
  }

  function lessonRow(x) {
    const live = S.live && S.live.lesson_id === x.id;
    const row = h("div", { class: "lrow", role: "listitem button", tabindex: "0", "data-id": x.id, dataset: { title: x.title.toLowerCase() } },
      h("div", { class: "lt" }, h("span", { class: "tt" }, x.title), h("span", { class: "lm" }, x.meta)),
      live ? h("span", { class: "livemark" }, h("span", { class: "dot" }), "идёт") : null,
      h("span", { class: "when meta" }, whenText(x.updated)));
    row.addEventListener("click", () => open(x.id));
    row.addEventListener("dblclick", (e) => e.preventDefault());
    row.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); open(x.id); }
      else if (e.key === "F2") { e.preventDefault(); rename(x.id); }
      else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const rows = [...list.querySelectorAll(".lrow:not([hidden])")];
        const i = rows.indexOf(row) + (e.key === "ArrowDown" ? 1 : -1);
        if (rows[i]) rows[i].focus();
      }
    });
    row.addEventListener("contextmenu", (e) => menuAt(e, lessonMenuItems(x.id, rename, { open: true })));
    return row;
  }

  function planCard(p) {
    const bar = h("div", { class: "minibar", "aria-hidden": "true" },
      p.stages.map((s) => h("i", { class: s.kind === "break" ? "br" : s.kind === "exercise" ? "ex" : "", style: { flexGrow: String(Math.max(1, s.minutes)) } })));
    const nt = iconBtn("plus", "Новый урок по плану", (e) => { e.stopPropagation(); send({ cmd: "new_topic", plan: p.id }); }, { kind: "ghost", size: "sm", cls: "newtopic" });
    const card = h("div", { class: "pcard", role: "button", tabindex: "0", "data-id": p.id },
      h("div", { class: "pc-top" }, h("b", { class: "tt" }, p.title), nt), bar,
      h("span", { class: "meta" }, `${durText(p.total)} · ${p.stages.length} ${plural(p.stages.length, "этап", "этапа", "этапов")} · ` +
        `${p.topics} ${plural(p.topics, "урок", "урока", "уроков")}`));
    card.addEventListener("click", () => open(p.id));
    card.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target === card) { e.preventDefault(); open(p.id); } else if (e.key === "F2") { e.preventDefault(); rename(p.id); } });
    card.addEventListener("contextmenu", (e) => menuAt(e, lessonMenuItems(p.id, rename, { open: true })));
    return card;
  }

  function renderContinue() {
    const live = S.live && S.live.lesson_id ? lessonById(S.live.lesson_id) : null;
    const x = live || (S.continue_id ? lessonById(S.continue_id) : null);
    cont.hidden = !x;
    if (!x) return;
    clear(cont);
    const left = h("span", { class: "meta liveleft" });
    const head = live ? h("span", { class: "meta lv" }, h("span", { class: "dot live" }), `Идёт урок · этап ${S.live.index + 1} из ${S.live.count} · `, left)
      : h("span", { class: "meta" }, "Продолжить");
    cont.append(h("div", { class: "tl" }, head, h("b", null, x.title), h("span", { class: "meta" }, x.meta)),
      btn(live ? "Вернуться к уроку" : "Открыть", { kind: "primary", size: "lg", onClick: () => open(x.id) }));
    tick();
  }

  function tick() {
    const el = cont.querySelector(".liveleft");
    if (el && S.live && S.live.ends_ms) el.textContent = "осталось " + mmss((S.live.ends_ms - now()) / 1000);
  }
  const timer = setInterval(tick, 1000);

  function applySearch() {
    const q = search.value.trim().toLowerCase();
    let grp = null, shown = 0;
    const flush = () => { if (grp) grp.hidden = shown === 0; };
    for (const el of list.children) {
      if (el.classList.contains("grp")) { flush(); grp = el; shown = 0; continue; }
      const hide = !!q && !el.dataset.title.includes(q);
      el.hidden = hide;
      if (!hide) shown++;
    }
    flush();
    for (const c of plansGrid.querySelectorAll(".pcard[data-id]")) {
      const x = lessonById(c.dataset.id);
      c.hidden = !!q && !!x && !x.title.toLowerCase().includes(q);
    }
  }
  search.addEventListener("input", applySearch);

  function render() {
    if (renaming) return;
    const key = JSON.stringify([S.lessons, S.plans, S.live && [S.live.lesson_id, S.live.index, S.live.count], S.continue_id]);
    if (key === sig) { tick(); return; }
    sig = key;
    const focusId = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.id : "";
    const lessons = (S.lessons || []).filter((x) => x.kind !== "plan");
    const plans = S.plans || [];
    renderContinue();
    clear(plansGrid);
    plans.forEach((p) => plansGrid.append(planCard(p)));
    plansGrid.append(h("a", { id: "newPlanCard", class: "pcard add", href: "#/new/plan" }, icon("plus"), "Новый план"));
    clear(list);
    const planIds = new Set(plans.map((p) => p.id));
    if (plans.length) {
      for (const p of plans) {
        const own = lessons.filter((x) => x.plan_id === p.id);
        if (!own.length) continue;
        list.append(h("div", { class: "grp", dataset: { title: p.title } }, icon("link", "sm"), p.title));
        own.forEach((x) => list.append(lessonRow(x)));
      }
      const free = lessons.filter((x) => !planIds.has(x.plan_id));
      if (free.length) {
        list.append(h("div", { class: "grp", dataset: { title: "Без плана" } }, "Без плана"));
        free.forEach((x) => list.append(lessonRow(x)));
      }
    } else {
      lessons.forEach((x) => list.append(lessonRow(x)));
    }
    if (!lessons.length) list.append(h("div", { class: "empty" }, "Уроков пока нет — «Новый урок» или перетащите файл урока в окно."));
    applySearch();
    if (focusId) {
      const f = list.querySelector(`[data-id="${CSS.escape(focusId)}"]`) || plansGrid.querySelector(`[data-id="${CSS.escape(focusId)}"]`);
      if (f) f.focus();
    }
  }

  return { update: render, destroy: () => { clearInterval(timer); jobs.destroy(); } };
}
