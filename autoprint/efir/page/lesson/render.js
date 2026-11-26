// Лента урока: этапы, блоки, план слева. Узлы блоков живут, пока блок не изменился (версия v): пришло новое
// состояние — перерисовываются только изменённые блоки, правка в поле и прокрутка не сбиваются.
"use strict";
import { A, $, el, icon, hm, roleName, durText } from "./state.js";
import { mdHtml, askParts, inline } from "./md.js";

const LINE_H = 21;             // высота строки кода (14px × 1.5) — подсветка строк и полоса шагов
const nodes = new Map();       // id блока → узел .blk
const groupsDom = new Map();   // id этапа ("intro" — до первого этапа) → <section>/<article>
const insNodes = new Map();    // «после чего» → линия «+»

export function stagesOf(items) {
  const out = [];
  let at = 0;
  for (const it of items) {
    if (it.type !== "stage") continue;
    const m = Math.max(0, parseInt(it.minutes, 10) || 0);
    out.push({ i: out.length, id: it.id, item: it, start: at, end: at + m, minutes: m });
    at += m;
  }
  return out;
}

function groupsOf(items) {
  const out = [{ stage: null, blocks: [] }];
  for (const it of items) {
    if (it.type === "stage") out.push({ stage: it, blocks: [] });
    else out[out.length - 1].blocks.push(it);
  }
  return out;
}

export function totalMinutes(items) { return stagesOf(items).reduce((a, s) => a + s.minutes, 0); }

// картинка в тексте урока — копией под ширину колонки (сервер: /media/…?w=): слайды 1920–3840 px браузер
// распаковывал целиком прямо при прокрутке. Ширина — с запасом на Hi-DPI и масштаб окна, из готового ряда размеров
const LIGHT_SIZES = [320, 640, 960, 1280, 1600, 1920];
export function lightUrl(url, cssWidth) {
  if (!url || !/^\/media\/[0-9a-f]{16}\/[^?]+\.(png|jpe?g|webp|bmp)$/i.test(url)) return url;
  const zoom = parseFloat(getComputedStyle(document.documentElement).zoom) || 1;
  // ширина картинки в уроке: не шире колонки и не выше 520 px (16:9 — около 925 px)
  const css = cssWidth || Math.min(960, window.innerWidth || 960);
  const need = css * zoom * (window.devicePixelRatio || 1);
  const w = LIGHT_SIZES.find((s) => s >= need) || LIGHT_SIZES[LIGHT_SIZES.length - 1];
  return url + "?w=" + w;
}

// ---------------------------------------------------------------- блоки
function label(it, kind) {
  const lbl = el("div", "lbl");
  lbl.appendChild(icon(kind));
  const name = el("span", "rname", kind === "code" ? "Код" : kind === "image" ? (it.slide ? "Слайд " + it.slide : "Картинка")
    : roleName(kind));
  if (it.type === "markdown") name.title = "Роль заметки — щёлкните, чтобы сменить";
  lbl.appendChild(name);
  const how = it.type === "markdown" && ((A.S && A.S.roles) || []).find((r) => r.key === kind);
  if (how && how.how) lbl.appendChild(el("span", "how", "· " + how.how));
  if (it.title) lbl.appendChild(el("span", "sub", "· " + it.title));
  else lbl.appendChild(el("span", "addtitle", "+ заголовок"));
  return lbl;
}

function noteContent(it) {
  const c = el("div", "c");
  const empty = !(it.text || "").trim();
  if (empty) {
    c.classList.add("empty");
    c.textContent = "Пусто — щёлкните и пишите";
    return c;
  }
  // правку ещё не подтвердила программа — тот же разбор Markdown здесь, без мигания
  const local = it.local || it.dirty;
  if (it.role === "ask") {
    const [qText, ans] = local ? askParts(it.text) : [null, it.answers || []];
    const q = el("div", "q");
    q.innerHTML = local ? mdHtml(qText) : (it.html || "");
    c.appendChild(q);
    for (const a of ans) {
      const d = el("div", "ans");
      d.innerHTML = "→ " + (local ? inline(a) : a);
      c.appendChild(d);
    }
  } else if (it.role === "term") {
    const [head, ...rest] = (it.text || "").replace(/\s+$/, "").split("\n");
    c.appendChild(el("div", "term", local ? head.trim() : (it.term || head.trim())));
    const d = el("div", "def");
    d.innerHTML = local ? mdHtml(rest.join("\n").trim()) : (it.html || "");
    c.appendChild(d);
  } else {
    c.innerHTML = local ? mdHtml(it.text) : (it.html || "");
  }
  return c;
}

function stepColor(n) { return `hsl(${(n * 47) % 360} 62% 58%)`; }

function codeGutter(it) {
  const g = el("div", "gut");
  const lines = (it.text || "").split("\n").length;
  const steps = it.steps || [];
  const marked = new Set(steps).size > 1;
  let html = "";
  let last = 1;
  for (let i = 0; i < lines; i++) {
    const s = i < steps.length ? steps[i] : (steps.length ? steps[steps.length - 1] : 1);
    last = s;
    html += marked ? `<span class="ln" style="--sc:${stepColor(s)}" title="Шаг ${s}"><b>${s}</b>${i + 1}</span>`
                   : `<span class="ln">${i + 1}</span>`;
  }
  g.innerHTML = html;
  g.classList.toggle("steps", marked);
  return g;
}

function buildBlock(it) {
  A.renders++;
  const n = el("div", "blk");
  n.dataset.id = it.id;
  n.dataset.v = String(it.v) + (it.dirty ? "*" : "");
  n.dataset.type = it.type;
  const tools = el("div", "tools");
  const grip = el("button", "grip");
  grip.title = "Перетащите, чтобы перенести (или Alt+↑ / Alt+↓)";
  grip.draggable = true;
  grip.appendChild(icon("grip"));
  const more = el("button", "bmore");
  more.title = "Действия с блоком";
  more.appendChild(icon("more"));
  tools.appendChild(grip);
  tools.appendChild(more);
  n.appendChild(tools);
  if (it.type === "markdown") {
    const role = it.role || "text";
    const row = el("div", "row r-" + role);
    row.appendChild(label(it, role));
    row.appendChild(noteContent(it));
    n.appendChild(row);
    if (!(it.text || "").trim()) n.classList.add("is-empty");
  } else if (it.type === "code") {
    const row = el("div", "row r-code");
    const lbl = label(it, "code");
    const act = el("span", "armslot");
    lbl.appendChild(act);
    row.appendChild(lbl);
    row.appendChild(el("div", "say"));
    const box = el("div", "codebox");
    box.appendChild(codeGutter(it));
    const pre = el("pre");
    if (it.local || (it.dirty && !it.html)) pre.textContent = it.text || "";
    else pre.innerHTML = it.html || "";
    if (!(it.text || "").trim()) { pre.classList.add("empty"); pre.textContent = "Пустой код — щёлкните и пишите"; }
    box.appendChild(pre);
    const lang = el("span", "lang");
    if (it.icon) {
      const li = el("span", "li");
      const img = el("img");
      img.src = "/static/lang/" + it.icon;
      img.alt = "";
      li.appendChild(img);
      lang.appendChild(li);
    }
    lang.appendChild(document.createTextNode(it.label || it.lang || ""));
    box.appendChild(lang);
    box.appendChild(el("div", "hls"));
    const pb = el("div", "pbar");
    pb.appendChild(el("i"));
    box.appendChild(pb);
    row.appendChild(box);
    const sn = el("div", "selnote");
    row.appendChild(sn);
    n.appendChild(row);
    if (!(it.text || "").trim()) n.classList.add("is-empty");
  } else if (it.type === "image") {
    const row = el("div", "row r-image");
    const lbl = label(it, "image");
    if (it.url && !it.missing) {
      const ts = el("button", "toscreen", "На экран");
      ts.dataset.act = "slide";
      ts.title = "Показать ученикам на их экране (листать — ◀ ▶ или PageUp / PageDown, B — фон)";
      lbl.appendChild(ts);
    }
    row.appendChild(lbl);
    const c = el("div", "c");
    if (it.place) {                       // место: картинку подставят из презентации или вставят
      n.classList.add("place");
      const box = el("div", "missing placebox");
      const pico = el("span", "pico");                 // значок: здесь картинка (урок сохранили без картинок и т. п.)
      pico.appendChild(icon("image"));
      box.appendChild(pico);
      box.appendChild(el("div", "ptxt", it.place === "slide" ? "Слайд " + it.slide + " — картинки нет"
        : "Нужна картинка: " + (it.title || "без подписи")));
      const acts = el("div", "pacts");
      const ins = el("button", "pins", "Выбрать файл…");
      ins.dataset.act = "place-insert";
      ins.title = "Картинка с диска — или выделите это место и нажмите Ctrl+V";
      acts.appendChild(ins);
      if (it.place === "slide") {
        const fs = el("button", "fillslides", "Подставить слайды из презентации…");
        fs.dataset.act = "fill-slides";
        acts.appendChild(fs);
      } else {
        const fi = el("button", "find", "Найти в интернете");
        fi.dataset.act = "find-image";
        fi.title = "Поиск картинок по подписи — в обычном браузере";
        acts.appendChild(fi);
      }
      box.appendChild(acts);
      c.appendChild(box);
    } else if (it.missing || !it.url) {
      c.appendChild(el("div", "missing", it.text ? "Нет файла картинки" + (it.name ? ": " + it.name : "")
        : "Картинки нет — вставьте её сюда (Ctrl+V) или перетащите файл"));
    } else {
      const f = el("figure");
      const img = el("img");
      img.src = lightUrl(it.url);
      img.dataset.full = it.url;                  // просмотр картинки — оригинал
      img.alt = it.title || "Картинка";
      img.loading = "lazy";
      img.decoding = "async";
      f.appendChild(img);
      c.appendChild(f);
    }
    row.appendChild(c);
    n.appendChild(row);
  }
  return n;
}

// печать на блоке кода: «следующим», ход печати, подсветка строк, «Скажи: …», выделенное — без перерисовки блока
function decorateCode(n, it) {
  const P = (A.S && A.S.print) || {};
  const hk = P.hotkey || (A.S && A.S.hotkey) || "Ctrl+F9";
  const on = P.block === it.id;
  const st = on ? P.state : "";
  const busy = on && ["running", "countdown", "paused", "line_wait"].includes(st);
  n.classList.toggle("armed", on);
  n.classList.toggle("busy", busy);
  const slot = n.querySelector(".armslot");
  if (decor.code) decor.code(slot, it, P, on, busy);       // окно программы: «Набрать», «▾» и состояние набора
  else oldArmSlot(slot, it, P, hk, on, busy, st);
  const bar = n.querySelector(".pbar i");
  bar.style.width = busy ? ((P.progress || 0) * 100).toFixed(1) + "%" : "0";
  decorateLines(n, it, P, on);
}

// шапка блока кода для окна программы (screenctl.js ставит свою); null — «Следующим», как в суфлёре 0.12
export const decor = { code: null };

function oldArmSlot(slot, it, P, hk, on, busy, st) {
  let text = "", cls = "armed-chip";
  if (busy) {
    const pct = Math.round((P.progress || 0) * 100);
    text = st === "paused" ? `Пауза · ${pct}% · ${hk} — продолжить`
      : st === "line_wait" ? `Ждёт Enter — следующая строка${P.line ? ` (${P.line.i} из ${P.line.n})` : ""}`
      : st === "countdown" ? `Старт через ${P.countdown || ""}…`
      : `Печатается · ${pct}%${P.step ? ` · шаг ${P.step.i} из ${P.step.n}` : ""} · ${hk} — пауза`;
  } else if (on) {
    text = `▶ Следующим · ${hk}` + (P.step && !P.step.done ? ` · шаг ${P.step.i} из ${P.step.n}` : "")
      + (P.step && P.step.done ? " · все шаги напечатаны" : "");
  }
  const key = text + "|" + on;
  if (slot.dataset.key !== key) {
    slot.dataset.key = key;
    slot.innerHTML = "";
    if (text) slot.appendChild(el("span", cls, text));
    else if ((it.text || "").trim()) {
      const b = el("button", "armbtn", "Следующим");
      b.title = `Печатать этот код следующим: поставьте курсор в Jupyter и нажмите ${hk}`;
      slot.appendChild(b);
    }
  }
}

// столбец на экране: табуляция — до следующей позиции, кратной 8 (как у <pre>)
function visualCol(line, col) {
  let x = 0;
  for (const ch of line.slice(0, col)) x = ch === "\t" ? (Math.floor(x / 8) + 1) * 8 : x + 1;
  return x;
}

function decorateLines(n, it, P, on) {
  // подсветка строк. Не печатается — следующий шаг или строка. Печатается (P.cur) — набранное, текущая строка
  // и следующая разным цветом, и курсор там, где набор сейчас
  const hls = n.querySelector(".hls");
  const busy = on && ["running", "countdown", "paused", "line_wait"].includes(P.state);
  const cur = busy && P.cur ? P.cur : null;
  const nexts = on && !(P.step && P.step.done) ? (P.next_lines || []) : [];
  const rows = [];
  if (cur) {
    for (let ln = Math.max(1, cur.from); ln < cur.line; ln++) rows.push([ln, "done"]);
    rows.push([cur.line, "cur"]);
    for (const ln of nexts) if (ln > cur.line) rows.push([ln, "next"]);
  } else for (const ln of nexts) rows.push([ln, ""]);
  const hk2 = rows.map((r) => r.join(":")).join(",");
  if (hls.dataset.k !== hk2) {
    hls.dataset.k = hk2;
    hls.innerHTML = "";
    for (const [ln, cls] of rows) {
      const d = el("div", "hl" + (cls ? " " + cls : ""));
      d.style.top = (12 + (ln - 1) * LINE_H) + "px";
      hls.appendChild(d);
    }
  }
  let caret = hls.querySelector(".caret");
  if (cur) {
    if (!caret) { caret = el("i", "caret"); hls.appendChild(caret); }
    else if (caret !== hls.lastChild) hls.appendChild(caret);
    const gut = n.querySelector(".gut");
    const text = ((it.text || "").split("\n")[cur.line - 1]) || "";
    caret.style.top = (12 + (cur.line - 1) * LINE_H) + "px";
    caret.style.left = `calc(${gut ? gut.offsetWidth : 0}px + 14px + ${visualCol(text, cur.col)}ch)`;
    caret.classList.toggle("wait", P.state === "line_wait" || P.state === "paused");
  } else if (caret) caret.remove();
  const say = n.querySelector(".say");
  const sayText = on ? (P.say || []).join("\n") : "";
  if (say.dataset.k !== sayText) {
    say.dataset.k = sayText;
    say.innerHTML = "";
    if (sayText) {
      say.appendChild(el("b", "", "Скажи: "));
      say.appendChild(document.createTextNode(sayText));
    }
  }
  say.hidden = !sayText;
  const sn = n.querySelector(".selnote");
  const sel = it.sel || [];
  const selKey = sel.join("-") + "|" + (it.text || "").length;
  if (sn.dataset.k !== selKey) {
    sn.dataset.k = selKey;
    sn.innerHTML = "";
    if (sel.length === 2 && sel[1] > sel[0]) {
      const t = it.text || "";
      const a = t.slice(0, sel[0]).split("\n").length, b = t.slice(0, sel[1]).split("\n").length;
      sn.appendChild(document.createTextNode(`Печатается выделенное: ${a === b ? "строка " + a : "строки " + a + "–" + b} · `));
      const r = el("button", "linkbtn", "печатать весь блок");
      r.dataset.act = "clear-sel";
      sn.appendChild(r);
    }
  }
  sn.hidden = !sn.childNodes.length;
}

function blockNode(it) {
  let n = nodes.get(it.id);
  const v = String(it.v) + (it.dirty ? "*" : "");
  if (n && n.dataset.v !== v && A.editing !== it.id && !A.holding.has(it.id) && !n.contains(document.activeElement)) {
    const fresh = buildBlock(it);
    if (n.classList.contains("sel")) fresh.classList.add("sel");
    n.replaceWith(fresh);
    n = fresh;
  } else if (!n) {
    n = buildBlock(it);
  }
  nodes.set(it.id, n);
  if (it.type === "code") decorateCode(n, it);
  return n;
}

function insNode(after) {
  let n = insNodes.get(after);
  if (!n) {
    n = el("div", "ins");
    n.dataset.after = after;
    const b = el("button", "insbtn");
    b.title = "Добавить блок сюда";
    b.appendChild(icon("plus"));
    n.appendChild(b);
    insNodes.set(after, n);
  }
  return n;
}

// ---------------------------------------------------------------- этапы
function stageHead(art, it, info, pn) {
  let sh = art.querySelector(":scope > .sh");
  const L = A.S && A.S.lesson;
  const fixed = !!(L && L.fixed && L.plan);       // урок по плану: этапы и минуты — из плана
  const key = String(it.v) + (it.dirty ? "*" : "") + "|" + (pn || "") + "|" + it.title + "|" + it.minutes + "|" + it.kind + "|" + it.part + "|" + it.note + "|" + (fixed ? L.plan.title : "");
  if (sh && sh.dataset.k === key) return sh;
  if (sh && sh.contains(document.activeElement)) return sh;
  const fresh = el("div", "sh");
  fresh.dataset.k = key;
  fresh.appendChild(el("span", "clock", ""));
  const sht = el("div", "sht");
  const meta = [];
  if (it.part) meta.push((pn ? pn + ". " : "") + it.part);
  if (it.note) meta.push(it.note);
  meta.push(durText(it.minutes || 0));
  sht.appendChild(el("div", "meta", meta.join(" · ")));
  const h = el("h2", "stitle", it.title || "Этап");
  if (fixed) h.title = "Название — из плана «" + L.plan.title + "»";
  sht.appendChild(h);
  fresh.appendChild(sht);
  const ed = el("div", "sedit");
  const mins = el(fixed ? "span" : "button", fixed ? "mins fixed" : "mins", String(it.minutes || 0));
  mins.title = fixed ? "Минуты — из плана «" + L.plan.title + "»" : "Минуты этапа — щёлкните и наберите";
  if (fixed) { const lk = icon("lock", "Из плана «" + L.plan.title + "»"); lk.classList.add("lockic"); ed.appendChild(lk); }
  ed.appendChild(mins);
  ed.appendChild(el("span", "minsu", "мин"));
  const kind = el("button", "kindbtn");
  kind.title = it.kind === "break" ? "Вид этапа: перерыв" : it.kind === "exercise" ? "Вид этапа: зарядка" : "Вид этапа: обычный";
  kind.appendChild(icon(it.kind === "break" ? "break" : it.kind === "exercise" ? "exercise" : "stage"));
  kind.classList.toggle("on", !!it.kind);
  kind.disabled = fixed;
  ed.appendChild(kind);
  const more = el("button", "smore");
  more.title = fixed ? "Изменить в плане, отвязать от плана" : "Раздел, пометка, удалить этап";
  more.appendChild(icon("more"));
  ed.appendChild(more);
  fresh.appendChild(ed);
  const left = el("div", "left");
  left.appendChild(el("div", "lbl2", ""));
  left.appendChild(el("div", "big", ""));
  fresh.appendChild(left);
  if (sh) sh.replaceWith(fresh); else art.prepend(fresh);
  return fresh;
}

// название видео для сравнения: без кавычек «», регистра и «ё» (как lesson_md.video_key)
export function videoKey(s) {
  return (s || "").trim().replace(/^[«»"'„“”]+|[«»"'„“”]+$/g, "").split(/\s+/).filter(Boolean).join(" ").toLowerCase().replace(/ё/g, "е");
}

// видео зарядок оформления урока: список названий (до 0.12 — да/нет)
export function exerciseList() {
  const x = A.S && A.S.exercises;
  return Array.isArray(x) ? x : (x ? [""] : []);
}

/** Видео этапа-зарядки: своё (по названию) или единственное; "" — выбирают на уроке (меню или случайное). */
export function stageVideo(it) {
  const ex = exerciseList();
  return ex.find((t) => t && it.exercise && videoKey(t) === videoKey(it.exercise)) || (ex.length === 1 ? ex[0] : "");
}

function efirRow(it) {
  const ex = exerciseList();
  const video = stageVideo(it);
  const pick = (A.S && A.S.prefs && A.S.prefs.exercise_pick) || "next";
  const next = (A.S && A.S.exercise_next) || "";        // «по очереди»: какое видео включит кнопка
  const k = "efir:" + it.id + ":" + it.kind + ":" + ex.join("|") + ":" + (it.exercise || "") + ":" + it.minutes + ":" + ((A.S && A.S.efir && A.S.efir.tab) || "") + ":" + (A.S && A.S.efir && A.S.efir.tab_open ? 1 : 0) + ":" + ((A.S && A.S.exercises_missing) || []).join("|") + ":" + pick + ":" + next;
  let n = nodes.get("efir:" + it.id);
  if (n && n.dataset.k === k) return n;
  const fresh = el("div", "blk efir");
  fresh.dataset.k = k;
  const row = el("div", "row " + (it.kind === "break" ? "r-task" : "r-explain"));
  const lbl = el("div", "lbl");
  lbl.appendChild(icon(it.kind));
  lbl.appendChild(el("span", "", (it.kind === "break" ? "Перерыв" : "Зарядка") + " · экран эфира"));
  row.appendChild(lbl);
  const c = el("div", "c");
  if (it.kind === "break") {
    const b = el("button", "efirbtn", "Показать перерыв ученикам · " + (it.minutes || 10) + " мин");
    b.dataset.act = "break";
    b.dataset.stage = it.id;
    c.appendChild(b);
  } else if (ex.length) {
    const b = el("button", "efirbtn", video ? "Включить зарядку ученикам · " + video
      : pick === "random" ? "Включить случайную зарядку" : pick === "ask" ? "Выбрать зарядку ученикам…"
      : "Включить зарядку ученикам" + (next ? " · " + next : ""));
    b.dataset.act = "exercise";
    b.dataset.stage = it.id;
    c.appendChild(b);
    if (video && ((A.S && A.S.exercises_missing) || []).includes(video)) {   // файла видео нет — сказать заранее
      c.appendChild(el("span", "efirnote warnnote", "⚠ Файл видео «" + video + "» не найден (удалён или перемещён)."));
      const pick = el("button", "efirbtn addvideo", "Выбрать видео…");
      pick.dataset.act = "add-video";
      c.appendChild(pick);
    }
  } else {
    c.appendChild(el("span", "efirnote", "В оформлении экрана учеников нет видео зарядки."));
    const av = el("button", "efirbtn addvideo", "Добавить видео зарядки…");
    av.dataset.act = "add-video";
    av.title = "Открыть оформление экрана учеников — там «Зарядки»: видео и их названия";
    c.appendChild(av);
  }
  if (A.S && A.S.efir && A.S.efir.tab) c.appendChild(el("span", "efirnote", A.S.efir.tab));
  if (A.S && A.S.efir && !A.S.efir.tab_open) {      // вкладки экрана учеников нет — открыть отсюда же
    const ot = el("button", "efirbtn opentab", "Открыть вкладку");
    ot.dataset.act = "open-tab";
    ot.title = "Открыть вкладку экрана учеников в браузере — её показывают ученикам (демонстрация вкладки)";
    c.appendChild(ot);
  }
  row.appendChild(c);
  fresh.appendChild(row);
  if (n) n.replaceWith(fresh);
  nodes.set("efir:" + it.id, fresh);
  return fresh;
}

function partNumbers(stages) {
  const nums = {}, out = {};
  let k = 0;
  for (const s of stages) {
    const p = s.item.part;
    if (p && !(p in nums)) nums[p] = ++k;
    out[s.id] = p ? nums[p] : 0;
  }
  return out;
}

function syncChildren(box, want) {
  let i = 0;
  for (const node of want) {
    const cur = box.children[i];
    if (cur !== node) box.insertBefore(node, cur || null);
    i++;
  }
  while (box.children.length > want.length) box.lastElementChild.remove();
}

function groupBox(key, isStage) {
  let g = groupsDom.get(key);
  if (!g) {
    g = el(isStage ? "article" : "section", isStage ? "stage" : "intro");
    g.id = isStage ? "st-" + key : "grp-intro";
    if (!isStage) g.appendChild(el("div", "introh", "Перед уроком"));
    g.appendChild(el("div", "bar"));
    g.lastChild.appendChild(el("i"));
    g.appendChild(el("div", "body"));
    groupsDom.set(key, g);
  }
  return g;
}

// какой слайд сейчас у учеников — отметка на ленте (без перерисовки блоков)
export function markOnScreen() {
  const ef = (A.S && A.S.efir) || {};
  const bid = ef.mode === "slide" ? ef.slide_bid : "";
  for (const n of document.querySelectorAll(".blk.onscreen")) if (n.dataset.id !== bid) n.classList.remove("onscreen");
  if (bid) nodeOf(bid)?.classList.add("onscreen");
}

export function renderMain() {
  const main = $("main");
  const L = A.S && A.S.lesson;
  if (!L) {
    main.innerHTML = "";
    main.appendChild(el("div", "hello", "Откройте урок в AutoPrintCode — здесь появится его экран."));
    nodes.clear(); groupsDom.clear(); insNodes.clear();
    return;
  }
  main.querySelector(":scope > .hello")?.remove();
  const items = A.items;
  const stages = stagesOf(items);
  const sInfo = new Map(stages.map((s) => [s.id, s]));
  const pn = partNumbers(stages);
  const groups = groupsOf(items);
  const wantGroups = [];
  const liveIds = new Set();
  const usedIns = new Set();
  for (const g of groups) {
    const key = g.stage ? g.stage.id : "intro";
    if (!g.stage && !g.blocks.length && stages.length && A.mode !== "prep") continue;
    if (!g.stage && !g.blocks.length && !stages.length) {
      // пустой урок без этапов — «+» в начало
    }
    const box = groupBox(key, !!g.stage);
    box.classList.toggle("has-stages", !!stages.length);
    if (g.stage) {
      const info = sInfo.get(g.stage.id);
      box.classList.toggle("kind-break", g.stage.kind === "break");
      box.classList.toggle("kind-exercise", g.stage.kind === "exercise");
      stageHead(box, g.stage, info, pn[g.stage.id]);
    }
    const body = box.querySelector(":scope > .body");
    const want = [];
    const top = g.stage ? g.stage.id : "";
    want.push(insNode(top)); usedIns.add(top);
    if (g.stage && (g.stage.kind === "break" || g.stage.kind === "exercise")) want.push(efirRow(g.stage));
    for (const it of g.blocks) {
      liveIds.add(it.id);
      want.push(blockNode(it));
      want.push(insNode(it.id)); usedIns.add(it.id);
    }
    if (g.stage && !g.blocks.length) {
      let e = body.querySelector(":scope > .empty-stage");
      if (!e) e = el("div", "empty-stage", "На этом этапе подсказок нет.");
      want.push(e);
    }
    syncChildren(body, want);
    wantGroups.push(box);
    liveIds.add(key);
  }
  syncChildren(main, wantGroups);
  for (const id of [...nodes.keys()]) {
    if (id.startsWith("efir:") ? !liveIds.has(id.slice(5)) : !liveIds.has(id)) nodes.delete(id);
  }
  for (const k of [...groupsDom.keys()]) if (!liveIds.has(k)) groupsDom.delete(k);
  for (const k of [...insNodes.keys()]) if (!usedIns.has(k)) insNodes.delete(k);
  if (!items.length) {
    const hello = el("div", "hello", A.mode === "prep" ? "Урок пустой — нажмите «+» выше, чтобы добавить этап или заметку."
      : "Урок пустой — перейдите в «Подготовку», чтобы его наполнить.");
    main.appendChild(hello);
  }
}

// ---------------------------------------------------------------- шапка печати: название, план урока таблицей
// На экране её нет (план — сбоку); на бумаге и в PDF урок начинается с названия, под ним — план: полоса этапов по
// времени и таблица «время · этап · минуты» (перерыв и зарядка — пометкой). Дальше — текст урока, как на экране.
function renderPrintHead(L, stages) {
  const ph = $("printHead");
  if (!ph) return;
  ph.innerHTML = "";
  if (!L) return;
  ph.appendChild(el("h1", "", L.title || "Урок"));
  const total = stages.reduce((a, s) => a + s.minutes, 0);
  const bits = [];
  if (L.plan && L.plan.title) bits.push("План «" + L.plan.title + "»");
  if (stages.length) bits.push(durText(total), stages.length + " " + (stages.length % 10 === 1 && stages.length % 100 !== 11 ? "этап"
    : [2, 3, 4].includes(stages.length % 10) && ![12, 13, 14].includes(stages.length % 100) ? "этапа" : "этапов"));
  if (bits.length) ph.appendChild(el("div", "phmeta", bits.join(" · ")));
  if (!stages.length) return;
  const bar = el("div", "phbar");
  for (const s of stages) {
    const seg = el("i", s.item.kind ? "k-" + s.item.kind : "");
    seg.style.flexGrow = String(Math.max(1, s.minutes));
    bar.appendChild(seg);
  }
  ph.appendChild(bar);
  const table = el("table", "phplan");
  const tb = el("tbody");
  const pn = partNumbers(stages);
  let lastPart = null;
  for (const s of stages) {
    if (s.item.part && s.item.part !== lastPart) {
      const pr = el("tr", "phpart");
      const td = el("th", "", pn[s.id] + ". " + s.item.part);
      td.colSpan = 3;
      pr.appendChild(td);
      tb.appendChild(pr);
    }
    lastPart = s.item.part || lastPart;
    const tr = el("tr", s.item.kind ? "k-" + s.item.kind : "");
    tr.appendChild(el("td", "t", hm(s.start)));
    const name = el("td", "n", s.item.title || "Этап");
    const word = s.item.kind === "break" ? "перерыв" : "зарядка";
    if (s.item.kind && !(s.item.title || "").toLowerCase().includes(word)) name.appendChild(el("span", "kind", word));
    tr.appendChild(name);
    tr.appendChild(el("td", "m", s.minutes + " мин"));
    tb.appendChild(tr);
  }
  table.appendChild(tb);
  ph.appendChild(table);
}

// ---------------------------------------------------------------- план слева
export function renderPlan() {
  const plan = $("plan");
  const L = A.S && A.S.lesson;
  const stages = L ? stagesOf(A.items) : [];
  renderPrintHead(L, stages);
  plan.hidden = !stages.length;
  if (!stages.length) { plan.innerHTML = ""; return; }
  // не перерисовывать, только пока набирают минуты в поле плана (кнопка в фокусе — не повод ждать: «Закрепить сбоку»)
  const fa = document.activeElement;
  if (plan.contains(fa) && fa.matches("input, textarea")) { plan.dataset.stale = "1"; return; }
  plan.dataset.stale = "";
  plan.innerHTML = "";
  const fixed = !!(L.fixed && L.plan);
  const head = el("div", "ptitle");
  head.appendChild(el("h2", "", "План урока"));
  head.appendChild(el("span", "ptotal", durText(stages.reduce((a, s) => a + s.minutes, 0))));
  plan.appendChild(head);                 // где план (сбоку, сверху, скрыт) — переключатель в полосе урока
  const pn = partNumbers(stages);
  let lastPart = null;
  for (const s of stages) {
    if (s.item.part && s.item.part !== lastPart) plan.appendChild(el("div", "ppart", pn[s.id] + ". " + s.item.part));
    lastPart = s.item.part || lastPart;
    const row = el("div", "prow");
    row.id = "pr-" + s.id;
    row.dataset.id = s.id;
    const line = el("div", "line");
    line.appendChild(el("span", "t", hm(s.start)));
    const name = el("button", "n", s.item.title || "Этап");
    name.title = A.mode === "prep" ? "Перейти к этапу (перетащите строку, чтобы перенести этап)" : "Перейти к этапу";
    line.appendChild(name);
    if (s.item.kind) line.appendChild(icon(s.item.kind === "break" ? "break" : "exercise"));
    if (!fixed) {
      const m = el("input", "pmin");
      m.value = String(s.minutes);
      m.inputMode = "numeric";
      m.maxLength = 3;
      m.title = "Минуты этапа: наберите и нажмите Enter";
      m.setAttribute("aria-label", "Минуты этапа «" + (s.item.title || "Этап") + "»");
      line.appendChild(m);
    }
    line.appendChild(el("span", fixed ? "m fixed" : "m", String(s.minutes)));
    row.appendChild(line);
    const bar = el("div", "pbar2");
    bar.appendChild(el("i"));
    row.appendChild(bar);
    row.draggable = A.mode === "prep" && !fixed;
    plan.appendChild(row);
  }
  const P = A.S && A.S.print;
  if (P && P.block) {
    const owner = stageOfBlock(P.block);
    if (owner) $("pr-" + owner)?.classList.add("has-armed");
  }
  if (fixed) {
    const h = el("p", "phint", "Этапы и минуты — из плана «" + L.plan.title + "». ");
    const b = el("button", "linkbtn openplan", "Изменить план");
    b.title = "Открыть план «" + L.plan.title + "»: этапы и минуты меняются у всех уроков по нему";
    b.onclick = () => window.dispatchEvent(new Event("suflor:open-plan"));
    h.appendChild(b);
    plan.appendChild(h);
    return;
  }
  plan.appendChild(el("p", "phint", A.mode === "prep" ? "Минуты правятся прямо здесь." :
    (A.S.live ? "Щёлкните по этапу — перейти к нему. Сдвинуть время — щелчок по времени урока наверху." : "Щёлкните по этапу — перейти к нему.")));
}

export function stageOfBlock(bid) {
  let cur = null;
  for (const it of A.items) {
    if (it.type === "stage") cur = it.id;
    if (it.id === bid) return cur;
  }
  return null;
}

export function legend() {
  const g = $("legendGrid");
  g.innerHTML = "";
  const roles = (A.S && A.S.roles) || [];
  for (const r of roles.filter((x) => !x.more)) {
    const d = el("div", "r-" + r.key);
    d.appendChild(icon(r.key));
    const s = el("span");
    s.appendChild(el("b", "", r.name));
    s.appendChild(document.createTextNode(" — " + r.hint));
    d.appendChild(s);
    g.appendChild(d);
  }
  for (const [k, n, h] of [["code", "Код", "печатается по " + ((A.S && A.S.hotkey) || "Ctrl+F9")], ["image", "Картинка", "щёлкните — во весь экран"]]) {
    const d = el("div", "r-" + k);
    d.appendChild(icon(k));
    const s = el("span");
    s.appendChild(el("b", "", n));
    s.appendChild(document.createTextNode(" — " + h));
    d.appendChild(s);
    g.appendChild(d);
  }
}

export function nodeOf(id) { return nodes.get(id) || null; }
export { LINE_H, stepColor };
