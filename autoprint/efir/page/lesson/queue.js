// Очередь правок урока: страница меняет урок сразу у себя, а программе отправляет действия по одному.
// Нет связи — правки ждут (и в localStorage, переживают перезагрузку страницы и программы); повтор после
// обрыва безопасен: id новых блоков придумывает страница, программа второй раз их не вставит.
"use strict";

const MAX_AGE = 24 * 3600 * 1000;        // забытые правки старше суток не отправляем

export const Q = {
  lesson: null,
  pending: [],          // [{seq, ops, t}] — ещё не подтверждённые программой (по порядку)
  recent: [],           // подтверждённые, но ещё не пришедшие в состоянии от программы: [{edits, ops}]
  drafts: new Map(),    // блок → поля, которые печатают прямо сейчас (уйдут через паузу)
  timers: new Map(),
  seq: 0,
  sending: false,
  offline: false,
  delay: 1000,
  onChange: () => {},   // состояние очереди изменилось (значок «Сохранено»)
  onResult: () => {},   // программа ответила на правку: (ответ, действия)
  onError: () => {},    // правку не приняли: (текст)
};

const key = (lid) => "suflor.pending." + lid;

function persist() {
  if (!Q.lesson) return;
  try {
    const drafts = [...Q.drafts].map(([block, fields]) => ({ op: "set", block, fields }));
    const all = Q.pending.concat(drafts.length ? [{ seq: -1, ops: drafts, t: Date.now() }] : []);
    if (all.length) localStorage.setItem(key(Q.lesson), JSON.stringify(all));
    else localStorage.removeItem(key(Q.lesson));
  } catch (e) { /* хранилище недоступно — правки всё равно уйдут, пока страница открыта */ }
}

export function useLesson(lid) {
  if (Q.lesson === lid) return;
  flushDrafts();
  Q.lesson = lid;
  Q.pending = [];
  Q.recent = [];
  Q.drafts.clear();
  try {
    const saved = JSON.parse(localStorage.getItem(key(lid)) || "[]");
    for (const e of saved) {
      if (e && Array.isArray(e.ops) && Date.now() - (e.t || 0) < MAX_AGE) Q.pending.push({ seq: ++Q.seq, ops: e.ops, t: e.t });
    }
  } catch (e) { /* ничего */ }
  persist();
  Q.onChange();
  send();
}

// действие — сразу в очередь (вставка, удаление, перенос…)
export function push(op) {
  flushDrafts();
  Q.pending.push({ seq: ++Q.seq, ops: [op], t: Date.now() });
  persist();
  Q.onChange();
  send();
}

// поля блока, которые сейчас правят: уходят через delay мс тишины (или сразу — flush)
export function draft(block, fields, delay = 400) {
  const cur = Q.drafts.get(block) || {};
  Q.drafts.set(block, Object.assign(cur, fields));
  clearTimeout(Q.timers.get(block));
  Q.timers.set(block, setTimeout(() => flush(block), delay));
  persist();
  Q.onChange();
}

export function flush(block) {
  const fields = Q.drafts.get(block);
  clearTimeout(Q.timers.get(block));
  Q.timers.delete(block);
  if (!fields) return;
  Q.drafts.delete(block);
  const last = Q.pending[Q.pending.length - 1];
  const op = { op: "set", block, fields };
  if (last && !last.sent && last.ops.length === 1 && last.ops[0].op === "set" && last.ops[0].block === block) {
    Object.assign(last.ops[0].fields, fields);         // ещё не ушло — дописать в то же действие
  } else {
    Q.pending.push({ seq: ++Q.seq, ops: [op], t: Date.now() });
  }
  persist();
  Q.onChange();
  send();
}

export function flushDrafts() { for (const b of [...Q.drafts.keys()]) flush(b); }

export function busy() { return Q.pending.length + Q.drafts.size; }

// все действия, которых ещё нет в состоянии от программы: подтверждённые недавно, ждущие, черновики
export function overlay(serverEdits) {
  Q.recent = Q.recent.filter((r) => r.edits > serverEdits);
  const ops = [];
  for (const r of Q.recent) ops.push(...r.ops);
  for (const e of Q.pending) ops.push(...e.ops);
  for (const [block, fields] of Q.drafts) ops.push({ op: "set", block, fields });
  return ops;
}

async function send() {
  if (Q.sending || !Q.pending.length || !Q.lesson) return;
  Q.sending = true;
  const e = Q.pending[0];
  e.sent = true;
  let res = null, status = 0;
  try {
    const r = await fetch("/lesson/edit", { method: "POST", headers: { "Content-Type": "application/json", "X-Suflor": "1" },
      body: JSON.stringify({ lesson: Q.lesson, ops: e.ops }) });
    status = r.status;
    res = await r.json().catch(() => null);
  } catch (err) { status = 0; }
  Q.sending = false;
  if (status === 200 && res && res.ok) {
    Q.pending.shift();
    Q.offline = false;
    Q.delay = 1000;
    Q.recent.push({ edits: res.edits || 0, ops: e.ops });
    persist();
    Q.onResult(res, e.ops);
    Q.onChange();
    send();
    return;
  }
  if (status === 400 || status === 403 || status === 413) {   // программа правку не приняла — дальше её не слать
    Q.pending.shift();
    persist();
    Q.onError((res && res.error) || "Правка не принята");
    Q.onChange();
    send();
    return;
  }
  e.sent = false;                         // нет связи или программа занята — повторить позже
  Q.offline = true;
  Q.onChange();
  setTimeout(send, Q.delay);
  Q.delay = Math.min(30000, Q.delay * 2);
}

export function retryNow() { Q.delay = 1000; send(); }

// ---------------------------------------------------------------- те же действия у себя (как lesson_edit.py)
function stageEnd(items, i) {
  let j = i + 1;
  while (j < items.length && items[j].type !== "stage") j++;
  return j;
}

function fromBlock(b) {
  const it = { id: b.id, type: b.type, v: 0, text: b.text || "", title: b.title || "", local: true };
  if (b.type === "markdown") { it.role = b.role || "say"; it.html = ""; }
  if (b.type === "code") { it.lang = b.lang || "python"; it.steps = b.steps || []; it.sel = b.sel || []; it.profile = b.profile || ""; it.html = ""; }
  if (b.type === "stage") { it.minutes = b.minutes === undefined ? 5 : b.minutes; it.kind = b.stage_kind || ""; it.part = b.part || ""; it.note = (b.text || "").trim(); }
  if (b.type === "image") { it.url = ""; it.missing = !b.text; }
  return it;
}

const FIELD_MAP = { stage_kind: "kind" };

export function applyOps(items, ops, lesson) {
  items = items.slice();
  const idx = (id) => items.findIndex((x) => x.id === id);
  for (const op of ops) {
    if (op.op === "set") {
      const i = idx(op.block);
      if (i < 0) continue;
      const it = Object.assign({}, items[i]);
      for (const [k, v] of Object.entries(op.fields)) {
        it[FIELD_MAP[k] || k] = v;
        if (k === "text" && it.type === "stage") it.note = String(v).trim();
      }
      it.dirty = true;
      items[i] = it;
    } else if (op.op === "insert" || op.op === "restore") {
      if (idx(op.block.id) >= 0) continue;
      const at = op.after ? idx(op.after) + 1 : 0;
      if (op.after && at === 0) continue;
      items.splice(at, 0, fromBlock(op.block));
    } else if (op.op === "delete") {
      const i = idx(op.block);
      if (i >= 0) items.splice(i, 1);
    } else if (op.op === "move") {
      const i = idx(op.block);
      if (i < 0 || op.block === op.after) continue;
      const [b] = items.splice(i, 1);
      const at = op.after ? idx(op.after) + 1 : 0;
      items.splice(op.after && at === 0 ? i : at, 0, b);
    } else if (op.op === "move_stage") {
      const i = idx(op.stage);
      if (i < 0 || items[i].type !== "stage" || op.stage === op.after_stage) continue;
      const group = items.splice(i, stageEnd(items, i) - i);
      let at;
      if (op.after_stage) {
        const k = idx(op.after_stage);
        if (k < 0) { items.splice(i, 0, ...group); continue; }
        at = stageEnd(items, k);
      } else {
        at = items.findIndex((x) => x.type === "stage");
        if (at < 0) at = items.length;
      }
      items.splice(at, 0, ...group);
    } else if (op.op === "set_lesson" && lesson) {
      lesson.title = op.title;
    }
  }
  return items;
}
