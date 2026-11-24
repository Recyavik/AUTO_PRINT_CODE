// «Подготовка»: правка урока на месте. Щелчок по тексту — правишь тем же шрифтом; «+» между блоками;
// перенос за ручку или Alt+↑/↓; удаление с «Вернуть»; картинки — Ctrl+V или перетаскиванием файла.
"use strict";
import { A, $, el, icon, menu, closeMenu, toast, newId, isTyping, cmd } from "./state.js";
import * as Q from "./queue.js";
import { nodeOf, stageOfBlock } from "./render.js";
import { beginCode, endCode } from "./code.js";
import { mdHtml, askParts, escapeHtml } from "./md.js";
import { toMarkdown, cleanPaste } from "./richtext.js";

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
  homework: "--accent", goal: "--say",
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

// ---------------------------------------------------------------- правка заметки «как в Word»
// В поле — оформленный текст, как его потом читают; Markdown — только внутри (toMarkdown). У «Спроси» — поле
// вопроса и строки ответов, у «Термина» — термин и определение. Панель кнопок плавает в строке подписи:
// текст при начале правки не сдвигается.
const TOOLS = [["bold", "Ж", "Жирный (Ctrl+B)"], ["italic", "К", "Курсив (Ctrl+I)"], ["ul", "• Список", "Маркированный список"],
  ["ol", "1. Список", "Нумерованный список"], ["code", "Код", "Код в строке, например print()"], ["link", "Ссылка", "Ссылка (Ctrl+K)"],
  ["clear", "Очистить", "Убрать оформление выделенного"]];

let noteState = null;      // {id, box, bar, node, rich, focusEl, modal}

function richField(html, placeholder, label) {
  const r = el("div", "rich");
  r.contentEditable = "true";
  r.spellcheck = true;
  r.innerHTML = html;
  r.dataset.placeholder = placeholder;
  r.setAttribute("role", "textbox");
  r.setAttribute("aria-multiline", "true");
  r.setAttribute("aria-label", label);
  return r;
}

function answerRow(value, onChange) {
  const row = el("div", "ansrow");
  row.appendChild(el("span", "arr", "→"));
  const inp = el("input", "ansin");
  inp.value = value;
  inp.placeholder = "Что может ответить ученик";
  inp.setAttribute("aria-label", "Ответ ученика");
  row.appendChild(inp);
  const del = el("button", "ansdel", "×");
  del.type = "button";
  del.title = "Убрать ответ";
  del.addEventListener("mousedown", (e) => e.preventDefault());
  del.onclick = () => { row.remove(); onChange(); };
  row.appendChild(del);
  inp.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.ctrlKey) {
      e.preventDefault();
      const nr = answerRow("", onChange);
      row.after(nr);
      nr.querySelector("input").focus();
    } else if (e.key === "Backspace" && !inp.value) {
      const prev = row.previousElementSibling && row.previousElementSibling.querySelector("input");
      e.preventDefault();
      row.remove();
      onChange();
      if (prev) prev.focus();
    }
  });
  return row;
}

function toggleCode(rich) {
  const sel = getSelection();
  if (!sel.rangeCount) return;
  const r = sel.getRangeAt(0);
  const node = r.commonAncestorContainer;
  const anc = (node.nodeType === 1 ? node : node.parentElement).closest("code");
  if (anc && rich.contains(anc)) { anc.replaceWith(document.createTextNode(anc.textContent)); return; }
  if (r.collapsed) return;
  const blockOf = (n) => (n.nodeType === 1 ? n : n.parentElement).closest("p, li, div.rich, h2, h3, h4");
  if (blockOf(r.startContainer) !== blockOf(r.endContainer)) { toast("«Код» — внутри одной строки"); return; }
  const code = document.createElement("code");
  code.textContent = r.toString();
  r.deleteContents();
  r.insertNode(code);
  const nr = document.createRange();
  nr.setStartAfter(code);
  nr.collapse(true);
  sel.removeAllRanges();
  sel.addRange(nr);
}

function insertFragment(rich, html) {
  const sel = getSelection();
  const t = document.createElement("template");
  t.innerHTML = html;
  const frag = t.content;
  const last = frag.lastChild;
  if (!rich.textContent.trim()) {
    rich.innerHTML = "";
    rich.appendChild(frag);
  } else {
    let r;
    if (sel.rangeCount && rich.contains(sel.getRangeAt(0).commonAncestorContainer)) { r = sel.getRangeAt(0); r.deleteContents(); }
    else { r = document.createRange(); r.selectNodeContents(rich); r.collapse(false); }
    r.insertNode(frag);
  }
  if (last) {
    const nr = document.createRange();
    nr.selectNodeContents(last);
    nr.collapse(false);
    sel.removeAllRanges();
    sel.addRange(nr);
  }
}

function addLink(rich) {
  const sel = getSelection();
  const saved = sel.rangeCount ? sel.getRangeAt(0).cloneRange() : null;
  if (noteState) noteState.modal = true;
  const url = (prompt("Адрес ссылки", "https://") || "").trim();
  if (noteState) noteState.modal = false;
  rich.focus();
  if (saved) { sel.removeAllRanges(); sel.addRange(saved); }
  if (!/^https?:\/\/\S+$/i.test(url)) return;
  if (sel.isCollapsed) insertFragment(rich, `<a href="${escapeHtml(url)}">${escapeHtml(url)}</a>`);
  else document.execCommand("createLink", false, url);
}

function runTool(cmd_, rich) {
  rich.focus();
  if (cmd_ === "bold" || cmd_ === "italic") document.execCommand(cmd_);
  else if (cmd_ === "ul") document.execCommand("insertUnorderedList");
  else if (cmd_ === "ol") document.execCommand("insertOrderedList");
  else if (cmd_ === "code") toggleCode(rich);
  else if (cmd_ === "link") addLink(rich);
  else if (cmd_ === "clear") { document.execCommand("removeFormat"); document.execCommand("unlink"); }
  rich.dispatchEvent(new Event("input", { bubbles: true }));
}

function toolbar(rich) {
  const bar = el("div", "rtb");
  bar.setAttribute("role", "toolbar");
  bar.setAttribute("aria-label", "Оформление текста");
  for (const [k, n, h] of TOOLS) {
    const b = el("button", "rt-" + k, n);
    b.type = "button";
    b.dataset.cmd = k;
    b.title = h;
    b.addEventListener("mousedown", (e) => e.preventDefault());    // выделение в тексте остаётся
    b.onclick = () => runTool(k, rich);
    bar.appendChild(b);
  }
  return bar;
}

export function beginNote(n, it, caretAtEnd = true) {
  if (noteState && noteState.id === it.id) { noteState.focusEl.focus(); return; }
  finishEditing();
  const c = n.querySelector(".row > .c");
  if (!c) return;
  document.execCommand("defaultParagraphSeparator", false, "p");
  document.execCommand("styleWithCSS", false, false);
  const box = el("div", "c edit ned");
  const role = it.role || "text";
  const text = it.text || "";
  let rich, termIn = null, ansBox = null;
  const changed = () => Q.draft(it.id, { text: serialize() });
  if (role === "ask") {
    const [q, ans] = askParts(text);
    rich = richField(mdHtml(q), "Вопрос классу", "Вопрос");
    box.appendChild(rich);
    ansBox = el("div", "ansed");
    for (const a of ans) ansBox.appendChild(answerRow(a, changed));
    const add = el("button", "addans", "+ ответ ученика");
    add.type = "button";
    add.addEventListener("mousedown", (e) => e.preventDefault());
    add.onclick = () => { const r = answerRow("", changed); ansBox.insertBefore(r, add); r.querySelector("input").focus(); };
    ansBox.appendChild(add);
    box.appendChild(ansBox);
  } else if (role === "term") {
    const [head, ...rest] = text.trim().split("\n");
    termIn = el("input", "termin");
    termIn.value = text.trim() ? head.trim() : "";
    termIn.placeholder = "Термин";
    termIn.setAttribute("aria-label", "Термин");
    box.appendChild(termIn);
    rich = richField(mdHtml(rest.join("\n").trim()), "Определение — дословно", "Определение");
    box.appendChild(rich);
  } else {
    rich = richField(mdHtml(text), "Пишите…", "Текст заметки");
    box.appendChild(rich);
  }
  function serialize() {
    let md = toMarkdown(rich);
    if (termIn) md = (termIn.value.trim() + (md ? "\n" + md : "")).replace(/\s+$/, "");
    if (ansBox) {
      const a = [...ansBox.querySelectorAll(".ansin")].map((i) => i.value.trim()).filter(Boolean);
      if (a.length) md = (md ? md + "\n" : "") + a.map((x) => "→ " + x).join("\n");
    }
    return md;
  }
  const bar = toolbar(rich);
  n.appendChild(bar);
  c.replaceWith(box);
  n.classList.add("editing");
  A.editing = it.id;
  const focusEl = termIn && !termIn.value ? termIn : rich;
  noteState = { id: it.id, box, bar, node: n, rich, focusEl, modal: false };
  box.addEventListener("input", changed);
  rich.addEventListener("paste", (e) => {
    const dt = e.clipboardData;
    if (!dt) return;
    const img = [...(dt.items || [])].find((x) => x.kind === "file" && /^image\//.test(x.type));
    const html = dt.getData("text/html"), plain = dt.getData("text/plain");
    e.preventDefault();
    if (img && !plain) { uploadImage(img.getAsFile(), it.id); return; }        // снимок экрана — картинкой после заметки
    if (html) insertFragment(rich, cleanPaste(html));
    else if (plain) document.execCommand("insertText", false, plain);
    changed();
  });
  box.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.preventDefault(); document.activeElement.blur(); return; }
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      const nrole = (item(it.id) || it).role || "say";
      const nid = insertBlock(it.id, "markdown", { role: nrole });
      document.activeElement.blur();
      startEditingSoon(nid);
      return;
    }
    if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) { e.preventDefault(); moveBlock(it.id, e.key === "ArrowDown" ? 1 : -1); return; }
    if ((e.ctrlKey || e.metaKey) && e.target === rich) {
      const k = e.key.toLowerCase();
      if (k === "k" || k === "л") { e.preventDefault(); runTool("link", rich); }
      else if (k === "u" || k === "г") e.preventDefault();                     // подчёркивания в заметке нет
    }
  });
  box.addEventListener("focusout", () => setTimeout(() => {
    const st = noteState;
    if (!st || st.box !== box || st.modal) return;
    const a = document.activeElement;
    if (a && (box.contains(a) || bar.contains(a))) return;
    finishNote();
  }, 0));
  focusEl.focus({ preventScroll: true });
  if (caretAtEnd && focusEl === rich) {
    const r = document.createRange();
    r.selectNodeContents(rich);
    r.collapse(false);
    const sel = getSelection();
    sel.removeAllRanges();
    sel.addRange(r);
  }
}

function finishNote() {
  if (!noteState) return;
  const { id, node, bar } = noteState;
  noteState = null;
  Q.flush(id);
  bar.remove();
  if (A.editing === id) A.editing = null;
  node.classList.remove("editing");
  node.dataset.v = "stale";            // перерисовать: заметка показывается снова (сразу, без ответа программы)
  refresh();
}

function blurNote() {
  const a = document.activeElement;
  if (noteState && a && noteState.box.contains(a)) a.blur();
}

export function finishEditing() {
  if (noteState) { blurNote(); finishNote(); }
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

export function finishNoteOnly() { if (noteState) { blurNote(); finishNote(); } }
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
// роли по группам («Урок», «Речь», «Ученикам», «Действия», «Для себя», «Материалы»)
function roleGroups() {
  const roles = (A.S && A.S.roles) || [];
  const byKey = new Map(roles.map((r) => [r.key, r]));
  const groups = ((A.S && A.S.role_groups) || []).map((g) => ({ title: g.title, roles: g.roles.map((k) => byKey.get(k)).filter(Boolean) }));
  return { groups, more: roles.filter((r) => r.more) };
}

function roleItem(r, extra) {
  return Object.assign({ label: r.name, hint: r.hint, dot: `var(${ROLE_COLORS[r.key] || "--faint"})` }, extra);
}

export function roleMenu(anchor, it) {
  const { groups, more } = roleGroups();
  const items = [];
  for (const g of groups) {
    items.push({ head: g.title });
    for (const r of g.roles) items.push(roleItem(r, { checked: r.key === it.role, on: () => setFields(it.id, { role: r.key }) }));
  }
  if (more.length) {
    items.push({ head: "Ещё" });
    for (const r of more) items.push(roleItem(r, { checked: r.key === it.role, on: () => setFields(it.id, { role: r.key }) }));
  }
  menu(anchor, items, { cls: "roles tall" });
}

function langMenu(anchor, it) {
  menu(anchor, [{ head: "Язык кода" }, ...LANGS.map(([k, n]) => ({ label: n, checked: (it.lang || "") === k,
    on: () => setFields(it.id, { lang: k }) }))], { cls: "tall" });
}

function copyForChat(it) {
  const d = document.createElement("div");
  d.innerHTML = mdHtml(it.text || "");
  for (const li of d.querySelectorAll("li")) li.prepend("• ");
  for (const b of d.querySelectorAll("p, li, h2, h3, h4")) b.append("\n");
  const text = ("Домашнее задание:\n" + d.textContent).replace(/\n{3,}/g, "\n\n").trim();
  (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject())
    .then(() => toast("Скопировано — вставьте в чат группы"), () => toast("Не удалось скопировать — выделите текст вручную"));
}

export function blockMenu(anchor, it) {
  const list = [];
  if (it.type === "markdown") {
    list.push({ label: "Роль…", on: () => roleMenu(anchor, it) });
    if (it.role === "homework") list.push({ label: "Скопировать для чата", hint: "текст домашнего задания", on: () => copyForChat(it) });
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
  const { groups } = roleGroups();
  const note = (r) => roleItem(r, { on: () => startEditingSoon(insertBlock(after, "markdown", { role: r.key })) });
  const items = [];
  for (const g of groups) {
    items.push({ head: g.title });
    if (g.title === "Урок") {
      items.push({ label: "Этап", hint: "строка плана с минутами", on: () => {
        const id = insertBlock(after, "stage");
        requestAnimationFrame(() => requestAnimationFrame(() => {
          const art = $("st-" + id);
          const h = art && art.querySelector(".stitle");
          if (h) editStageTitle(h, item(id));
        }));
      } });
    }
    for (const r of g.roles) items.push(note(r));
    if (g.title === "Материалы") {
      items.push({ label: "Картинка или слайд…", hint: "файл; или Ctrl+V / перетащите в ленту", on: () => pickImage(after, false) });
      items.push({ label: "Код", hint: "печатается по " + ((A.S && A.S.hotkey) || "Ctrl+F9"),
        on: () => startEditingSoon(insertBlock(after, "code")) });
    }
  }
  menu(anchor, items, { cls: "roles insert tall" });
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
