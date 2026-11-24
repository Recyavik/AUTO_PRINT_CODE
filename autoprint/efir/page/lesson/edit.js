// «Подготовка»: правка урока на месте. Щелчок по тексту — правишь тем же шрифтом; «+» между блоками;
// перенос за ручку или Alt+↑/↓; удаление с «Вернуть»; картинки — Ctrl+V или перетаскиванием файла.
"use strict";
import { A, $, el, icon, menu, closeMenu, toast, newId, isTyping, cmd } from "./state.js";
import * as Q from "./queue.js";
import { nodeOf, stageOfBlock } from "./render.js";
import { beginCode, endCode } from "./code.js";

const refresh = () => window.dispatchEvent(new Event("suflor:refresh"));
export const item = (id) => A.byId.get(id);

const LANGS = [["python", "Python"], ["javascript", "JavaScript"], ["typescript", "TypeScript"], ["html", "HTML"],
  ["css", "CSS"], ["java", "Java"], ["kotlin", "Kotlin"], ["csharp", "C#"], ["cpp", "C++"], ["c", "C"],
  ["go", "Go"], ["php", "PHP"], ["sql", "SQL"], ["json", "JSON"], ["bash", "Bash"], ["powershell", "PowerShell"],
  ["text", "Текст"]];
const PROFILES = [["", "Как в настройках"], ["ide", "IDE: VS Code, Jupyter"], ["plain", "Блокнот, простое поле"],
  ["terminal", "Терминал"]];
const ROLE_COLORS = { say: "--say", term: "--term", tell: "--tell", ask: "--ask", do: "--do", show: "--show",
  output: "--output", important: "--imp", trap: "--trap", extra: "--extra", task: "--accent", text: "--faint",
  explain: "--say", hint: "--show" };

// ---------------------------------------------------------------- действия (с отменой)
export function act(op, inverse, record = true) {
  Q.push(op);
  if (record && inverse) { A.undo.push(inverse); if (A.undo.length > 60) A.undo.shift(); }
  refresh();
}

export function undo() {
  const inv = A.undo.pop();
  if (!inv) { toast("Отменять нечего"); return; }
  const ops = [].concat(inv);
  // отмена вставки — удаление; в новый блок могли уже написать текст — удалять с «Вернуть», как обычное удаление
  if (ops.length === 1 && ops[0].op === "delete" && item(ops[0].block)) { deleteBlock(ops[0].block); return; }
  for (const op of ops) Q.push(op);
  refresh();
}

export function snapshot(it) {
  return { id: it.id, type: it.type, text: it.text || "", title: it.title || "", role: it.role || "text",
    lang: it.lang || "python", steps: it.steps || [], sel: it.sel || [], profile: it.profile || "",
    minutes: it.minutes || 0, stage_kind: it.kind || "", part: it.part || "" };
}

function prevId(id) {
  const i = A.items.findIndex((x) => x.id === id);
  return i > 0 ? A.items[i - 1].id : "";
}

export function setFields(id, fields) {
  const it = item(id);
  if (!it) return;
  const old = {};
  for (const k of Object.keys(fields)) old[k] = k === "stage_kind" ? (it.kind || "") : (it[k] ?? "");
  act({ op: "set", block: id, fields }, { op: "set", block: id, fields: old });
}

export function deleteBlock(id) {
  const it = item(id);
  if (!it) return;
  if (A.editing === id) finishEditing();
  const inv = { op: "restore", block: snapshot(it), after: prevId(id) };
  act({ op: "delete", block: id }, inv);
  if (A.selected === id) A.selected = null;
  toast(it.type === "stage" ? "Этап удалён (его блоки остались)" : "Блок удалён", "Вернуть", () => {
    const k = A.undo.lastIndexOf(inv);
    if (k >= 0) A.undo.splice(k, 1);
    act(inv, null, false);
  }, 10000);
}

export function insertBlock(after, type, extra = {}) {
  const id = newId();
  const b = Object.assign({ id, type }, extra);
  if (type === "markdown" && !b.role) b.role = "say";
  if (type === "stage") { b.title = b.title || "Новый этап"; if (b.minutes === undefined) b.minutes = 5; }
  if (type === "code") b.lang = b.lang || lessonLang();
  act({ op: "insert", after, block: b }, { op: "delete", block: id });
  return id;
}

function lessonLang() {
  const c = A.items.find((x) => x.type === "code" && x.lang);
  return c ? c.lang : "python";
}

export function moveBlock(id, dir) {
  const i = A.items.findIndex((x) => x.id === id);
  if (i < 0) return;
  let after;
  if (dir > 0) {
    if (i + 1 >= A.items.length) return;
    after = A.items[i + 1].id;                    // ниже следующего (следующий этап — в его начало)
  } else {
    if (i === 0) return;
    after = i >= 2 ? A.items[i - 2].id : "";
  }
  const inv = { op: "move", block: id, after: prevId(id) };
  act({ op: "move", block: id, after }, inv);
}

export function moveStage(id, afterStage) {
  const stages = A.items.filter((x) => x.type === "stage");
  const k = stages.findIndex((x) => x.id === id);
  const back = k > 0 ? stages[k - 1].id : "";
  act({ op: "move_stage", stage: id, after_stage: afterStage || "" }, { op: "move_stage", stage: id, after_stage: back });
}
window.__moveStage = moveStage;       // для проверки переноса этапа без мыши

// ---------------------------------------------------------------- правка заметки
function autosize(ta) {
  ta.style.height = "auto";
  ta.style.height = ta.scrollHeight + "px";
}

let noteState = null;      // {id, ta, node}

export function beginNote(n, it, caretAtEnd = true) {
  if (noteState && noteState.id === it.id) { noteState.ta.focus(); return; }
  finishEditing();
  const c = n.querySelector(".row > .c");
  if (!c) return;
  const ta = el("textarea", "c edit");
  ta.value = it.text || "";
  ta.rows = 1;
  ta.spellcheck = true;
  ta.placeholder = it.role === "ask" ? "Вопрос. Ниже строки «→ ответ» — что могут ответить ученики"
    : it.role === "term" ? "Термин в первой строке, ниже — определение" : "Пишите…";
  ta.setAttribute("aria-label", "Текст заметки");
  c.replaceWith(ta);
  n.classList.add("editing");
  A.editing = it.id;
  noteState = { id: it.id, ta, node: n };
  autosize(ta);
  ta.focus({ preventScroll: true });
  if (caretAtEnd) ta.setSelectionRange(ta.value.length, ta.value.length);
  ta.addEventListener("input", () => { autosize(ta); Q.draft(it.id, { text: ta.value }); });
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.preventDefault(); ta.blur(); return; }
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      const role = (item(it.id) || it).role || "say";
      const nid = insertBlock(it.id, "markdown", { role });
      ta.blur();
      startEditingSoon(nid);
      return;
    }
    if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
      e.preventDefault();
      moveBlock(it.id, e.key === "ArrowDown" ? 1 : -1);
    }
  });
  ta.addEventListener("blur", () => setTimeout(() => {
    if (noteState && noteState.ta === ta && document.activeElement !== ta) finishNote();
  }, 0));
}

function finishNote() {
  if (!noteState) return;
  const { id, node } = noteState;
  noteState = null;
  Q.flush(id);
  if (A.editing === id) A.editing = null;
  node.classList.remove("editing");
  node.dataset.v = "stale";            // перерисовать: заметка показывается снова (сразу, без ответа программы)
  refresh();
}

export function finishEditing() {
  if (noteState) noteState.ta.blur(), finishNote();
  endCode();
}

export function startEditingSoon(id) {
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const n = nodeOf(id), it = item(id);
    if (!n || !it) return;
    if (it.type === "markdown") beginNote(n, it);
    else if (it.type === "code") beginCode(n, it, finishNoteOnly);
    n.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }));
}

export function finishNoteOnly() { if (noteState) { noteState.ta.blur(); finishNote(); } }
export function editingNote() { return noteState; }

// ---------------------------------------------------------------- маленькое поле на месте (заголовок, минуты)
export function inlineInput(target, value, onCommit, opts = {}) {
  const inp = el("input", "inl " + (opts.cls || ""));
  inp.value = value;
  if (opts.numeric) { inp.inputMode = "numeric"; inp.maxLength = 3; }
  if (opts.placeholder) inp.placeholder = opts.placeholder;
  inp.setAttribute("aria-label", opts.label || "Поле");
  const keep = target.style.display;
  target.style.display = "none";
  target.after(inp);
  inp.focus();
  inp.select();
  let done = false;
  const finish = (commit) => {
    if (done) return;
    done = true;
    inp.remove();
    target.style.display = keep;
    if (commit && inp.value !== value) onCommit(inp.value);
  };
  inp.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); finish(true); }
    else if (e.key === "Escape") { e.preventDefault(); finish(false); }
  });
  inp.addEventListener("blur", () => finish(true));
  return inp;
}

export function editTitle(n, it) {
  const lbl = n.querySelector(".lbl");
  const target = lbl.querySelector(".sub") || lbl.querySelector(".addtitle");
  inlineInput(target, it.title || "", (v) => setFields(it.id, { title: v.trim() }),
    { cls: "inl-title", placeholder: "Заголовок плашки", label: "Заголовок" });
}

// ---------------------------------------------------------------- меню
export function roleMenu(anchor, it) {
  const roles = (A.S && A.S.roles) || [];
  const items = [{ head: "Роль заметки" }];
  for (const r of roles) {
    if (r.more && !items.some((x) => x.head === "Ещё")) items.push({ head: "Ещё" });
    items.push({ label: r.name, hint: r.hint, checked: r.key === it.role, dot: `var(${ROLE_COLORS[r.key] || "--faint"})`,
      on: () => setFields(it.id, { role: r.key }) });
  }
  menu(anchor, items, { cls: "roles" });
}

function langMenu(anchor, it) {
  menu(anchor, [{ head: "Язык кода" }, ...LANGS.map(([k, n]) => ({ label: n, checked: (it.lang || "") === k,
    on: () => setFields(it.id, { lang: k }) }))], { cls: "tall" });
}

export function blockMenu(anchor, it) {
  const list = [];
  if (it.type === "markdown") {
    list.push({ label: "Роль…", on: () => roleMenu(anchor, it) });
    list.push({ label: it.title ? "Изменить заголовок" : "Добавить заголовок", on: () => editTitle(nodeOf(it.id), it) });
  } else if (it.type === "code") {
    list.push({ label: "Следующим к печати", on: () => cmd({ cmd: "arm", block: it.id }) });
    list.push({ label: "Язык: " + (LANGS.find((x) => x[0] === it.lang)?.[1] || it.lang || "—") + "…", on: () => langMenu(anchor, it) });
    list.push({ head: "Куда печатать" });
    for (const [k, n] of PROFILES) list.push({ label: n, checked: (it.profile || "") === k, on: () => setFields(it.id, { profile: k }) });
    list.push({ sep: true });
    list.push({ label: it.title ? "Изменить заголовок" : "Добавить заголовок", on: () => editTitle(nodeOf(it.id), it) });
  } else if (it.type === "image") {
    list.push({ label: "Заменить картинку…", on: () => pickImage(it.id, true) });
    list.push({ label: it.title ? "Изменить подпись" : "Добавить подпись", on: () => editTitle(nodeOf(it.id), it) });
  }
  list.push({ label: "Дублировать", on: () => {
    const s = snapshot(it); s.id = newId();
    act({ op: "insert", after: it.id, block: s }, { op: "delete", block: s.id });
  } });
  list.push({ sep: true });
  list.push({ label: "Удалить", danger: true, on: () => deleteBlock(it.id) });
  menu(anchor, list, { right: true });
}

export function insertMenu(anchor, after) {
  const roles = ((A.S && A.S.roles) || []).filter((r) => !r.more);
  const items = [{ head: "Заметка" }];
  for (const r of roles) {
    items.push({ label: r.name, hint: r.hint, dot: `var(${ROLE_COLORS[r.key] || "--faint"})`,
      on: () => startEditingSoon(insertBlock(after, "markdown", { role: r.key })) });
  }
  items.push({ sep: true });
  items.push({ label: "Код", hint: "печатается по " + ((A.S && A.S.hotkey) || "Ctrl+F9"),
    on: () => startEditingSoon(insertBlock(after, "code")) });
  items.push({ label: "Картинка…", hint: "файл; или Ctrl+V / перетащите в ленту", on: () => pickImage(after, false) });
  items.push({ label: "Этап", hint: "строка плана с минутами", on: () => {
    const id = insertBlock(after, "stage");
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const art = $("st-" + id);
      const h = art && art.querySelector(".stitle");
      if (h) editStageTitle(h, item(id));
    }));
  } });
  menu(anchor, items, { cls: "roles insert" });
}

// ---------------------------------------------------------------- этапы
export function editStageTitle(h, it) {
  inlineInput(h, it.title || "", (v) => setFields(it.id, { title: v.trim() || "Этап" }), { cls: "inl-stage", label: "Название этапа" });
}

export function parseMinutes(v) {
  const n = parseInt(String(v).replace(/[^\d]/g, ""), 10);
  return Number.isFinite(n) ? Math.max(0, Math.min(600, n)) : null;
}

export function editStageMinutes(btn, it) {
  inlineInput(btn, String(it.minutes || 0), (v) => {
    const n = parseMinutes(v);
    if (n !== null && n !== it.minutes) setFields(it.id, { minutes: n });
  }, { numeric: true, cls: "inl-min", label: "Минуты этапа" });
}

export function kindMenu(anchor, it) {
  const kinds = [["", "Обычный этап"], ["break", "Перерыв — экран перерыва ученикам"], ["exercise", "Зарядка — видео ученикам"]];
  menu(anchor, kinds.map(([k, n]) => ({ label: n, checked: (it.kind || "") === k, on: () => setFields(it.id, { stage_kind: k }) })));
}

function askText(anchor, title, value, onCommit) {
  const box = el("div", "askbox");
  box.appendChild(el("div", "mhead", title));
  const inp = el("input", "inl");
  inp.value = value;
  inp.setAttribute("aria-label", title);
  box.appendChild(inp);
  menu(anchor, [{ node: box }], { right: true });
  inp.focus();
  inp.select();
  inp.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); closeMenu(); onCommit(inp.value.trim()); }
  });
}

export function stageMenu(anchor, it) {
  menu(anchor, [
    { label: it.part ? "Раздел: " + it.part : "Раздел…", hint: "группа этапов в плане", on: () => askText(anchor, "Раздел (часть урока)", it.part || "", (v) => setFields(it.id, { part: v })) },
    { label: it.note ? "Пометка: " + it.note : "Пометка…", hint: "строка под названием", on: () => askText(anchor, "Пометка этапа", it.note || "", (v) => setFields(it.id, { text: v })) },
    { sep: true },
    { label: "Удалить этап", hint: "блоки останутся", danger: true, on: () => deleteBlock(it.id) },
  ], { right: true });
}

// ---------------------------------------------------------------- картинки
export async function uploadImage(blob, after, replaceId) {
  const lid = A.S && A.S.lesson && A.S.lesson.id;
  if (!lid) return;
  const id = newId();
  const q = new URLSearchParams({ lesson: lid, after: after || "", id });
  let res = null;
  try {
    const r = await fetch("/lesson/upload?" + q, { method: "POST", headers: { "Content-Type": blob.type || "application/octet-stream", "X-Suflor": "1" }, body: blob });
    res = await r.json().catch(() => null);
    if (!r.ok || !res || !res.ok) { toast((res && res.error) || "Картинка не добавлена"); return; }
  } catch (e) {
    toast("Нет связи с AutoPrintCode — картинка не добавлена");
    return;
  }
  Q.Q.recent.push({ edits: res.edits || 0, ops: [{ op: "insert", after: after || "", block: { id, type: "image", text: "" } }] });
  if (res.item) A.fresh.set(id, res.item);
  A.undo.push({ op: "delete", block: id });
  if (replaceId) act({ op: "delete", block: replaceId }, null, false);
  refresh();
}

export function pickImage(target, replace) {
  const inp = el("input");
  inp.type = "file";
  inp.accept = "image/png,image/jpeg,image/gif,image/webp";
  inp.onchange = () => { const f = inp.files && inp.files[0]; if (f) uploadImage(f, replace ? target : target, replace ? target : null); };
  inp.click();
}

// куда вставить картинку из буфера: после выделенного блока, под мышью, иначе в конец видимого этапа
export function pastePlace() {
  if (A.selected && item(A.selected)) return A.selected;
  if (A.hovered && item(A.hovered)) return A.hovered;
  const stages = [...document.querySelectorAll("#main > .stage")];
  const vis = stages.find((s) => s.getBoundingClientRect().bottom > 120) || stages[stages.length - 1];
  if (!vis) return A.items.length ? A.items[A.items.length - 1].id : "";
  const sid = vis.id.slice(3);
  let last = sid;
  let inside = false;
  for (const it of A.items) {
    if (it.id === sid) { inside = true; continue; }
    if (inside && it.type === "stage") break;
    if (inside) last = it.id;
  }
  return last;
}

// «после чего» для точки (x, y) в ленте — перенос блока и бросок файла
export function dropAfter(y, target) {
  const blk = target.closest && target.closest(".blk[data-id], .ins");
  if (!blk) return null;
  if (blk.classList.contains("ins")) return blk.dataset.after;
  const r = blk.getBoundingClientRect();
  const id = blk.dataset.id;
  return y > r.top + r.height / 2 ? id : prevId(id);
}

export function selectBlock(id) {
  if (A.selected === id) return;
  if (A.selected) nodeOf(A.selected)?.classList.remove("sel");
  A.selected = id;
  if (id) nodeOf(id)?.classList.add("sel");
}

export { stageOfBlock, isTyping };
