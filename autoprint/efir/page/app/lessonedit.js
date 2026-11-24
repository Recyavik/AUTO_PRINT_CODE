// Правка урока в окне: переключатель «Правка» в полосе урока, правка на месте (модули суфлёра edit.js, code.js),
// «+» между блоками, перенос за ручку и Alt+↑/↓, удаление с «Вернуть», Ctrl+Z, картинки (Ctrl+V, файл на окне,
// «Выбрать файл…»), минуты в плане сбоку, план как документ (уроки по нему, «Новый урок по плану»).
// Правка включена, пока урок не идёт; в идущем уроке её включают переключателем (поправить опечатку).
"use strict";
import { on } from "./core.js";
import { h, btn, iconBtn, ask, clear } from "./ui.js";
import { hooks, mainClick, setMode, lessonV, refresh } from "./lessonview.js";
import { registerDrop } from "./shell.js";
import { importFiles } from "./library.js";
import { A, cmd, toast, isTyping } from "../lesson/state.js";
import * as Q from "../lesson/queue.js";
import * as E from "../lesson/edit.js";
import { nodeOf, stagesOf, renderPlan } from "../lesson/render.js";
import { beginCode } from "../lesson/code.js";

const IMAGE_RE = /\.(png|jpe?g|gif|webp)$/i;
const editing = () => !!lessonV() && A.mode === "prep";

// ---------------------------------------------------------------- «Правка» и «Сохранено»
function toggleEditing() {
  const on_ = A.mode !== "prep";
  A.modeWanted = on_ ? "prep" : "lesson";
  setMode(on_ ? "prep" : "lesson");
}

function saveChip() {
  const c = document.getElementById("saveChip");
  if (!c) return;
  const n = Q.busy();
  c.classList.toggle("warn", Q.Q.offline && n > 0);
  c.textContent = n === 0 ? "✓ Сохранено" : Q.Q.offline ? `Нет связи — правки ждут (${n})` : "Сохраняю…";
  c.title = n === 0 ? "Все правки сохранены в программе" : Q.Q.offline ? "Правки сохранятся, когда программа снова будет на связи" : "";
  c.hidden = A.mode !== "prep" && n === 0;
}
Q.Q.onChange = saveChip;
on("online", (ch) => { if (ch === "lesson") Q.retryNow(); });       // связь вернулась — неотправленные правки сразу
window.__suflor = { push: Q.push, busy: Q.busy };                   // для проверок: правка в очередь, сколько ждёт

// ---------------------------------------------------------------- урок по плану → план; план → его уроки
async function mayLeaveLive(what) {
  const L = A.S && A.S.lesson;
  if (!(A.S && A.S.live)) return true;
  return ask("Идёт урок «" + (L ? L.title : "") + "». Завершить его и " + what + "?",
    { title: "Идёт урок", ok: "Завершить урок", danger: true });
}

async function openLesson(id, title) {
  if (!(await mayLeaveLive("открыть «" + title + "»"))) return;
  cmd({ cmd: "open", lesson: id, force: !!(A.S && A.S.live) });
}

function openPlan() {
  const L = A.S && A.S.lesson;
  if (L && L.plan) openLesson(L.plan.id, L.plan.title);
}
window.addEventListener("suflor:open-plan", openPlan);

async function newTopic() {
  const L = A.S && A.S.lesson;
  if (!L || L.kind !== "plan" || !(await mayLeaveLive("создать новый урок по плану"))) return;
  cmd({ cmd: "new_lesson", plan: L.id, force: !!(A.S && A.S.live) });
}

function renderBanner() {
  const V = lessonV();
  if (!V) return;
  const L = A.S && A.S.lesson;
  const b = V.banner;
  const show = !!(L && L.kind === "plan");
  b.hidden = !show;
  if (!show) { if (b.dataset.k) { b.dataset.k = ""; clear(b); } return; }
  const topics = L.topics || [];
  const key = JSON.stringify([L.id, topics]);
  if (b.dataset.k === key) return;
  b.dataset.k = key;
  clear(b);
  const line = h("div", { class: "pbl" }, h("b", null, "План урока"),
    ": этапы и минуты для всех уроков по нему (" + topics.length + ")" + (topics.length ? ": " : ". Уроков пока нет."));
  topics.forEach((x, i) => {
    const a = h("button", { class: "linkbtn", type: "button" }, x.title);
    a.addEventListener("click", () => openLesson(x.id, x.title));
    line.append(a);
    if (i < topics.length - 1) line.append(", ");
  });
  const nb = btn("Новый урок по плану", { size: "sm", icon: "plus", onClick: newTopic });
  nb.id = "newTopicBtn";
  b.append(h("div", { class: "pbtext" }, line, h("small", null, "Заметки плана — заготовки: попадут в новые уроки по этому плану.")), nb);
}

// ---------------------------------------------------------------- щелчки в ленте (правка)
mainClick.push((e) => {
  if (A.mode !== "prep") return false;
  const t = e.target;
  const ins = t.closest(".insbtn");
  if (ins) { E.insertMenu(ins, ins.closest(".ins").dataset.after); return true; }
  const sh = t.closest(".sh");
  if (sh) {
    const it = A.byId.get(sh.closest(".stage").id.slice(3));
    if (!it) return true;
    const L = A.S.lesson;
    const fixed = !!(L && L.fixed && L.plan);          // урок по плану: этапы, минуты и вид — из плана
    if (t.closest(".stitle")) {
      if (!fixed) E.editStageTitle(t.closest(".stitle"), it);
      else toast("Название и вид этапа — из плана «" + L.plan.title + "»", "Изменить план", openPlan);
    } else if (t.closest(".mins.fixed")) toast("Минуты этапа — из плана «" + L.plan.title + "»", "Изменить план", openPlan);
    else if (t.closest(".mins")) E.editStageMinutes(t.closest(".mins"), it);
    else if (t.closest(".kindbtn")) E.kindMenu(t.closest(".kindbtn"), it);
    else if (t.closest(".smore")) E.stageMenu(t.closest(".smore"), it);
    return true;
  }
  const blk = t.closest(".blk[data-id]");
  if (!blk) return false;
  if (t.closest(".ned, .rtb, .armslot")) return true;  // внутри правки или «Набрать» — не начинать правку заново
  const it = A.byId.get(blk.dataset.id);
  if (!it) return true;
  E.selectBlock(it.id);
  if (t.closest(".bmore")) E.blockMenu(t.closest(".bmore"), it);
  else if (t.closest(".grip")) { /* ручка — перенос */ }
  else if (t.closest(".rname") && it.type === "markdown") E.roleMenu(t.closest(".rname"), it);
  else if (t.closest(".sub, .addtitle")) E.editTitle(blk, it);
  else if (it.type === "markdown" && t.closest(".row > .c")) E.beginNote(blk, it);
  else if (it.type === "code" && t.closest(".codebox")) beginCode(blk, it, E.finishNoteOnly);
  return true;
});

// ---------------------------------------------------------------- минуты и перенос этапов в плане сбоку
function commitPlanMinutes(inp) {
  const row = inp.closest(".prow");
  const it = row && A.byId.get(row.dataset.id);
  const n = E.parseMinutes(inp.value);
  if (!it || n === null) { if (it) inp.value = String(it.minutes || 0); return; }
  if (n !== (it.minutes || 0)) E.setFields(it.id, { minutes: n });
}

function wirePlan(plan) {
  plan.addEventListener("keydown", (e) => {
    const inp = e.target.closest(".pmin");
    if (!inp) return;
    if (e.key === "Enter") { e.preventDefault(); commitPlanMinutes(inp); inp.blur(); } else if (e.key === "Escape") {
      const it = A.byId.get(inp.closest(".prow").dataset.id);
      inp.value = String(it ? it.minutes : 0);
      inp.blur();
    }
  });
  plan.addEventListener("focusout", (e) => {
    const inp = e.target.closest(".pmin");
    if (inp && inp.isConnected) commitPlanMinutes(inp);
    setTimeout(() => {
      const fa = document.activeElement;
      if (plan.dataset.stale && !(plan.contains(fa) && fa.matches("input, textarea"))) renderPlan();
    }, 0);
  });
  plan.addEventListener("input", (e) => {
    const inp = e.target.closest(".pmin");
    if (inp) inp.value = inp.value.replace(/[^\d]/g, "").slice(0, 3);
  });
  let dragStage = null;
  const clearMarks = () => plan.querySelectorAll(".prow.dragging, .prow.drop-above, .prow.drop-below")
    .forEach((x) => x.classList.remove("dragging", "drop-above", "drop-below"));
  plan.addEventListener("dragstart", (e) => {
    const row = e.target.closest(".prow");
    if (!row || A.mode !== "prep") return;
    dragStage = row.dataset.id;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", "");
    row.classList.add("dragging");
  });
  plan.addEventListener("dragover", (e) => {
    const row = dragStage && e.target.closest(".prow");
    if (!row) return;
    e.preventDefault();
    plan.querySelectorAll(".prow.drop-above, .prow.drop-below").forEach((x) => x.classList.remove("drop-above", "drop-below"));
    const r = row.getBoundingClientRect();
    row.classList.add(e.clientY < r.top + r.height / 2 ? "drop-above" : "drop-below");
  });
  plan.addEventListener("drop", (e) => {
    if (!dragStage) return;
    e.preventDefault();
    const row = e.target.closest(".prow");
    const ids = stagesOf(A.items).map((s) => s.id);
    if (row && row.dataset.id !== dragStage) {
      const r = row.getBoundingClientRect();
      const k = ids.indexOf(row.dataset.id);
      let after = e.clientY >= r.top + r.height / 2 ? row.dataset.id : (k > 0 ? ids[k - 1] : "");
      if (after === dragStage) after = ids[ids.indexOf(dragStage) - 1] || "";
      E.moveStage(dragStage, after);
    }
    dragStage = null;
    clearMarks();
  });
  plan.addEventListener("dragend", () => { dragStage = null; clearMarks(); });
}

// ---------------------------------------------------------------- перенос блоков, файлы в ленту
function wireMain(main) {
  let dragBlock = null;
  const clearDrop = () => document.querySelectorAll(".drop-before, .drop-after").forEach((x) => x.classList.remove("drop-before", "drop-after"));
  main.addEventListener("dragstart", (e) => {
    const g = e.target.closest(".grip");
    if (!g || A.mode !== "prep") return;
    dragBlock = g.closest(".blk").dataset.id;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", "");
    g.closest(".blk").classList.add("dragging");
  });
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
    const place = after === null ? E.pastePlace() : after;
    (async () => { for (const f of files) await E.uploadImage(f, place); })();
  });
  main.addEventListener("dragend", () => { dragBlock = null; clearDrop(); document.querySelector(".blk.dragging")?.classList.remove("dragging"); });
}

// файлы, брошенные на окно программы (их ловит окно, а не страница): картинки — в урок, остальное — импорт
registerDrop("lesson", async (files) => {
  const paths = files.map((f) => f.path);
  if (editing() && paths.length && paths.every((p) => IMAGE_RE.test(p))) {
    const place = E.pastePlace();
    for (const p of paths) await E.placeImageFile(p, place);
    return;
  }
  importFiles(paths);
});

// ---------------------------------------------------------------- клавиши и вставка
document.addEventListener("paste", (e) => {
  if (!editing() || isTyping(e.target)) return;
  const f = [...(e.clipboardData && e.clipboardData.items || [])].find((x) => x.kind === "file" && /^image\//.test(x.type));
  if (!f) return;
  e.preventDefault();
  const sel = A.selected && A.byId.get(A.selected);
  if (sel && sel.type === "image" && sel.place) { E.uploadImage(f.getAsFile(), sel.id, sel.id); return; }   // место — заменить
  E.uploadImage(f.getAsFile(), E.pastePlace());
});

document.addEventListener("keydown", (e) => {
  if (!editing() || isTyping(e.target) || document.querySelector(".scrim, .pop, body > .menu")) return;
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === "z") { e.preventDefault(); E.undo(); return; }
  if (!A.selected) return;
  if (e.key === "Delete") { e.preventDefault(); E.deleteBlock(A.selected); } else if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
    e.preventDefault();
    E.moveBlock(A.selected, e.key === "ArrowDown" ? 1 : -1);
  } else if (e.key === "Escape") E.selectBlock(null);
  else if (e.key === "Enter") {
    const it = A.byId.get(A.selected), n = nodeOf(A.selected);
    if (it && n) { e.preventDefault(); if (it.type === "markdown") E.beginNote(n, it); else if (it.type === "code") beginCode(n, it, E.finishNoteOnly); }
  }
});
window.addEventListener("suflor:refresh", () => refresh());           // правка в очереди — лента сразу

// ---------------------------------------------------------------- подключение к экрану урока
function mount(V) {
  const tg = iconBtn("pencil", "Правка", toggleEditing, { size: "sm", cls: "edittoggle" });
  tg.id = "editToggle";
  const chip = h("span", { id: "saveChip", class: "savechip", hidden: true });
  V.st.tools.prepend(tg, chip);
  wirePlan(V.plan);
  wireMain(V.main);
  update();
}

function update() {
  const V = lessonV();
  if (!V) return;
  const tg = document.getElementById("editToggle");
  if (tg) {
    tg.setAttribute("aria-pressed", String(A.mode === "prep"));
    tg.dataset.tip = A.mode === "prep" ? "Правка включена — щёлкните, чтобы только читать" : "Правка урока на месте";
  }
  saveChip();
  renderBanner();
}

hooks.mount.push(mount);
hooks.strip.push(update);
