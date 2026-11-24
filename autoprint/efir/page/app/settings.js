// «Настройки» (#/settings/<раздел>): слева разделы, справа строки. Всё применяется сразу, без «ОК»; числа — в пределах
// (их же проверяет программа). Хоткей записывается здесь: нужен Ctrl / Alt / Win (кроме F1–F24, Pause, ScrollLock),
// занятое — тост, «Старт / пауза» обязателен; пока ждём сочетание — глобальные хоткеи сняты.
"use strict";
import { S, L as LC, send, call, go } from "./core.js";
import { h, btn, iconBtn, seg, toggle, numberField, select, toast, clear, tip } from "./ui.js";
import { icon } from "./icons.js";
import { setCrumbs } from "./shell.js";

const SECTIONS = [
  ["view", "eye", "Вид"], ["lesson", "book", "Урок"], ["typing", "keyboard", "Набор кода"], ["sound", "volume", "Звук клавиш"],
  ["hotkeys", "pointer", "Горячие клавиши"], ["behavior", "sliders", "Поведение"], ["ai", "sparkles", "Нейросеть"],
  ["updates", "refresh", "Обновления"], ["about", "info", "О программе"],
];
const LIMITS = {
  page_zoom: [80, 200, 10, "%"], cpm: [30, 3000, 10, "зн/мин"], jitter: [0, 90, 1, "%"], newline_pause_ms: [0, 3000, 10, "мс"],
  punct_pause_ms: [0, 1000, 10, "мс"], tab_width: [1, 8, 1, "пробела"], key_gap_ms: [5, 200, 5, "мс"], typos_per_100: [0, 10, 0.5, "на 100"],
  think_pause_s: [0, 10, 0.5, "с"], hotkey_start_delay_ms: [0, 3000, 50, "мс"], button_countdown_s: [0, 10, 1, "с"],
};
const fail = (e) => toast(String((e && e.message) || e), { warn: true });
const st = () => S.settings || {};
const mb = (n) => (n >= 1048576 ? (n / 1048576).toFixed(1) + " МБ" : Math.max(1, Math.round(n / 1024)) + " КБ");

let V = null;        // открытый раздел: {sec, inputs: {key: el}, refresh}

async function setv(key, value) {
  try {
    const r = await call({ cmd: "set", key, value });
    syncField(key, r.value);
    return r.value;
  } catch (e) { fail(e); syncField(key, st()[key]); return null; }
}

function syncField(key, value) {
  const el = V && V.inputs[key];
  if (!el) return;
  if (el.type === "checkbox") el.checked = !!value;
  else if (el.set) el.set(value);
  else if (document.activeElement !== el) el.value = String(value);
}

// ---------------------------------------------------------------- строки
function row(label, hint, ...controls) {
  return h("div", { class: "srow" }, h("div", { class: "srt" }, h("b", null, label), hint ? h("small", null, hint) : null),
    h("div", { class: "src" }, ...controls.filter(Boolean)));
}

function card(title, ...rows) { return h("section", { class: "scard" }, title ? h("h3", null, title) : null, ...rows.filter(Boolean)); }

function sw(key, label, hint, onChange) {
  const t = toggle(label, !!st()[key], async (v) => { const r = await setv(key, v); if (onChange) onChange(r); }, hint);
  t.input.id = "f-" + key;
  V.inputs[key] = t.input;
  return h("div", { class: "srow swrow" }, t);
}

function num(key, label, hint) {
  const [lo, hi, step, unit] = LIMITS[key];
  const f = numberField(st()[key], { min: lo, max: hi, step, unit, label, onChange: (v) => setv(key, v) });
  f.input.id = "f-" + key;
  V.inputs[key] = f.input;
  return row(label, hint, f);
}

function segRow(key, label, hint, options) {
  const s = seg(options.map(([v, t]) => ({ value: v, label: t })), st()[key], (v) => setv(key, v), { label });
  s.id = "f-" + key;
  V.inputs[key] = s;
  return row(label, hint, s);
}

function selRow(key, label, hint, options) {
  const s = select(options, st()[key], (v) => setv(key, isNaN(+v) || v === "" ? v : +v), { label });
  s.id = "f-" + key;
  V.inputs[key] = s;
  return row(label, hint, s);
}

function note(text) { return h("p", { class: "snote" }, text); }

// ---------------------------------------------------------------- разделы
function secView() {
  return [card("Тема",
    segRow("theme", "Тема оформления", "«Как в Windows» — светлая или тёмная, как в системе", [["system", "Как в Windows"], ["dark", "Тёмная"], ["light", "Светлая"]])),
  card("Размер и урок",
    num("page_zoom", "Масштаб", "Всё окно крупнее или мельче; ещё — Ctrl+колесо мыши и Ctrl+= / Ctrl+−"),
    segRow("page_plan", "План в уроке", "", [["side", "Сбоку"], ["top", "Сверху"], ["hidden", "Скрыть"]]),
    segRow("page_past", "Пройденные этапы", "", [["dim", "Приглушать"], ["collapse", "Сворачивать"]]),
    sw("page_stage_timer", "Таймер на текущем этапе", "Сколько осталось — крупно в заголовке этапа"),
    note("Размер кода в блоке: Ctrl или Shift + колесо мыши над блоком — крупнее и мельче, Ctrl+0 — обычный."))];
}

function secLesson() {
  const outside = st().looks_outside || 0;
  const copy = outside ? btn("Скопировать файлы всех оформлений в программу (" + mb(outside) + ")", { icon: "folder", onClick: async () => {
    try { await call({ cmd: "copy_all_media" }); toast("Копирую файлы оформлений — ход виден в «Уроках»"); } catch (e) { fail(e); }
  } }) : null;
  if (copy) copy.id = "copyAllMedia";
  return [card("Начало урока",
    sw("start_screen", "При начале урока — открыть экран учеников", "Вкладка в браузере, если она ещё не открыта"),
    sw("start_compact", "При начале урока — маленький режим", "Окно уменьшается и встаёт поверх остальных — вместо прежнего мини-таймера")),
  card("Картинки и видео",
    sw("copy_media", "Копировать картинки и видео в программу", "Фон, заставка перерыва, видео зарядок и свой шрифт — копией в папку программы: флешку вынут, а эфир работает"),
    copy ? row("Файлы снаружи программы", "Оформления до 1.0 ссылаются на файлы на диске", copy) : null)];
}

function secTyping() {
  const humanDeps = (on) => { for (const k of ["typos_per_100", "think_pause_s"]) if (V.inputs[k]) V.inputs[k].disabled = !on; };
  const out = [card("Как набирать",
    segRow("print_mode", "Как набирать блок кода", "Целиком — за раз · По строкам — строка, потом ваш Enter · По шагам — частями, с возвратом наверх",
      [["block", "Целиком"], ["lines", "По строкам"], ["steps", "По шагам"]]),
    selRow("step_nav", "Шаги: к месту вставки", "Стрелками — от курсора; от начала документа — переживает щелчки, код с первой строки файла",
      [["arrows", "Стрелками от курсора"], ["home", "От начала документа"]])),
  card("Темп",
    num("cpm", "Скорость", "Знаков в минуту; есть и в «▾» у блока кода"),
    num("jitter", "Разброс темпа", "0 — ровно, как метроном"),
    num("newline_pause_ms", "Пауза после Enter", ""),
    num("punct_pause_ms", "Пауза после знаков", "После , ; : ) ] } >")),
  card("Отступы и выделение",
    sw("fast_indent", "Отступы печатать быстро", "Пробелы в начале строки — быстрой очередью"),
    sw("indent_with_tab", "Отступы клавишей Tab", "Не для простых полей в браузере: там Tab переводит фокус"),
    num("tab_width", "Таб в коде", "Сколько пробелов — один уровень отступа"),
    sw("selection_whole_lines", "Выделение до целых строк", "Выделили часть строки — наберётся вся строка"),
    sw("strip_comments", "Не печатать комментарии", "Их читают вслух — «Скажи: …» над кодом; сам урок не меняется")),
  card("Окно, куда набирается",
    selRow("profile", "Профиль окна", "IDE убирает автоскобки и автоотступы редактора; Блокнот — как есть", st().profiles || []),
    sw("esc_before_enter", "Esc перед Enter", "Закрывает подсказки автодополнения. Не для Jupyter"),
    num("key_gap_ms", "Мин. интервал нажатий", "Пропадают или переставляются символы — увеличьте"),
    sw("minimize_on_type", "Сворачивать окно при наборе", "Один монитор: окно уходит из-под курсора на время набора и возвращается после")),
  card("Как человек",
    sw("human_typing", "Печатать как человек", "Живой ритм, паузы, опечатки — итог всегда совпадает с кодом", humanDeps),
    num("typos_per_100", "Опечатки", "В среднем на 100 символов; 0 — без опечаток"),
    num("think_pause_s", "Обдумывание строки", "Пауза перед новой строкой"))];
  humanDeps(!!st().human_typing);
  return out;
}

function secSound() {
  const styles = st().sound_styles || [];
  const del = btn("Удалить свой звук", { icon: "trash", kind: "ghost", onClick: async () => {
    try { await call({ cmd: "sound_delete" }); } catch (e) { fail(e); }
  } });
  del.id = "soundDelete";
  const sel = select(styles.map(([k, t]) => [k, t]), st().sound_style, async (v) => {
    await setv("sound_style", v);
    del.hidden = !(styles.find((x) => x[0] === v) || [])[2];
  }, { label: "Какая клавиатура" });
  sel.id = "f-sound_style";
  V.inputs.sound_style = sel;
  del.hidden = !(styles.find((x) => x[0] === st().sound_style) || [])[2];
  const listen = btn("Послушать", { icon: "play", onClick: () => send({ cmd: "test_sound" }) });
  listen.id = "testSound";
  const rec = btn("Записать звук клавиатуры…", { icon: "mic", kind: "primary", onClick: () => send({ cmd: "record_sound" }) });
  rec.id = "recordSound";
  const vol = h("input", { type: "range", min: "0", max: "100", step: "1", id: "f-sound_volume", "aria-label": "Громкость" });
  vol.value = String(st().sound_volume ?? 60);
  const val = h("b", { class: "mono vval" }, vol.value + " %");
  vol.addEventListener("input", () => { val.textContent = vol.value + " %"; });
  vol.addEventListener("change", async () => { await setv("sound_volume", +vol.value); send({ cmd: "test_sound" }); });
  V.inputs.sound_volume = vol;
  return [card("Клавиатура",
    sw("sound_enabled", "Звук клавиш", "Если звук пишется отдельно, его можно выключить"),
    row("Какая клавиатура", "Записи настоящих клавиатур и ваши собственные", sel, listen),
    row("Своя клавиатура", "Запишите микрофоном любую: несколько нажатий клавиш, пробела и Enter", del, rec),
    row("Громкость", "Отдельно от громкости Windows; отпустили — проба", vol, val))];
}

// ---------------------------------------------------------------- хоткеи
const KEY_NAMES = { ArrowUp: "Up", ArrowDown: "Down", ArrowLeft: "Left", ArrowRight: "Right", Space: "Space", Enter: "Return",
  NumpadEnter: "Return", Tab: "Tab", Home: "Home", End: "End", PageUp: "PgUp", PageDown: "PgDown", Insert: "Ins", Delete: "Del",
  Pause: "Pause", ScrollLock: "ScrollLock", Backquote: "`", Minus: "-", Equal: "=", BracketLeft: "[", BracketRight: "]",
  Semicolon: ";", Quote: "'", Comma: ",", Period: ".", Slash: "/", Backslash: "\\" };
function keyName(e) {
  const c = e.code || "";
  if (/^Key[A-Z]$/.test(c)) return c.slice(3);
  if (/^Digit\d$/.test(c)) return c.slice(5);
  if (/^F\d{1,2}$/.test(c)) return c;
  if (KEY_NAMES[c]) return KEY_NAMES[c];
  if (/^F\d{1,2}$/.test(e.key)) return e.key;
  if (e.key && e.key.length === 1) return e.key.toUpperCase();
  return KEY_NAMES[e.key] || "";
}

function secHotkeys() {
  let capturing = null;
  const stop = (f, text) => {
    f.classList.remove("capturing");
    f.textContent = text;
    if (capturing === f) { capturing = null; send({ cmd: "hotkey_capture", on: false }); }
  };
  const save = async (f, key, value) => {
    try {
      const r = await call({ cmd: "set_hotkey", key, value });
      if (!r.ok) { toast(r.error, { warn: true }); f.classList.add("clash"); f.textContent = value || f.dataset.value || "—"; return; }
      f.dataset.value = value;
      f.classList.remove("clash");
      f.textContent = value || "—";
    } catch (e) { fail(e); }
  };
  const rows = (st().hotkeys || []).map((hk) => {
    const f = h("button", { class: "hk mono", type: "button", "data-key": hk.key, "data-value": hk.value }, hk.value || "—");
    f.addEventListener("click", () => {
      if (capturing && capturing !== f) stop(capturing, capturing.dataset.value || "—");
      if (f.classList.contains("capturing")) { stop(f, f.dataset.value || "—"); return; }
      f.classList.remove("clash");
      f.classList.add("capturing");
      f.textContent = "Нажмите сочетание…";
      capturing = f;
      send({ cmd: "hotkey_capture", on: true });
      f.focus();
    });
    f.addEventListener("keydown", (e) => {
      if (!f.classList.contains("capturing")) return;
      e.preventDefault();
      e.stopPropagation();
      const mods = e.ctrlKey || e.altKey || e.shiftKey || e.metaKey;
      if (e.key === "Escape" && !mods) { stop(f, f.dataset.value || "—"); return; }
      if ((e.key === "Backspace" || e.key === "Delete") && !mods) { stop(f, f.dataset.value || "—"); save(f, hk.key, ""); return; }
      if (["Control", "Shift", "Alt", "Meta", "AltGraph"].includes(e.key)) {
        f.textContent = [e.ctrlKey && "Ctrl", e.altKey && "Alt", e.shiftKey && "Shift", e.metaKey && "Win"].filter(Boolean).concat("…").join("+");
        return;
      }
      const k = keyName(e);
      const text = [e.ctrlKey && "Ctrl", e.altKey && "Alt", e.shiftKey && "Shift", e.metaKey && "Meta"].filter(Boolean).concat(k).join("+");
      if (!k) { stop(f, text + " — не подходит"); f.classList.add("clash"); return; }
      // хоткей глобальный: просто буква, пробел или Enter перестали бы печататься во всех программах
      const strong = e.ctrlKey || e.altKey || e.metaKey;
      const solo = /^F\d{1,2}$/.test(k) || k === "Pause" || k === "ScrollLock";
      if (!strong && !solo) { stop(f, text + " — нужен Ctrl, Alt или Win"); f.classList.add("clash"); return; }
      stop(f, text);
      save(f, hk.key, text);
    });
    f.addEventListener("blur", () => { if (f.classList.contains("capturing")) stop(f, f.dataset.value || "—"); });
    const clearBtn = hk.key === "hotkey_toggle" ? h("span", { class: "hkpad" }) : iconBtn("close", "Без хоткея", () => save(f, hk.key, ""), { size: "sm", kind: "ghost" });
    return row(hk.title, "", f, clearBtn);
  });
  V.onLeave = () => { if (capturing) stop(capturing, capturing.dataset.value || "—"); };
  return [card("Набор кода", ...rows),
    note("Удобны F-клавиши с Ctrl или Shift: они редко заняты в редакторах. Пока поле ждёт сочетание, глобальные хоткеи отключены. Esc — отмена, Backspace — без хоткея.")];
}

function secBehavior() {
  return [card("Старт",
    num("hotkey_start_delay_ms", "Задержка старта по хоткею", "Чтобы успеть отпустить клавиши"),
    num("button_countdown_s", "Отсчёт при старте кнопкой или из трея", "Время поставить курсор в нужное окно")),
  card("Защита во время набора",
    sw("autopause_on_focus_change", "Пауза, если сменилось активное окно", "Текст не уйдёт не туда"),
    sw("guard_enabled", "Пауза при нажатии клавиши или щелчке", "Случайная клавиша не попадёт в код; что нажато — не записывается")),
  card("Трей и запуск",
    sw("close_to_tray", "Сворачивать в трей при закрытии", "Крестик прячет окно, хоткеи работают. Выход — из меню значка в трее"),
    sw("pin_tray_icon", "Значок всегда виден у часов", "Не прячется в «скрытые значки»"),
    sw("autostart", "Запускать вместе с Windows", "Сразу в трей, без окна"))];
}

// ---------------------------------------------------------------- нейросеть
function providerBox(which, allowNone) {
  const W = which === "backup" ? "Backup" : "Main";
  const cur = (st().ai || {})[which] || {};
  const provs = st().providers || [];
  const p = provs.find((x) => x.id === cur.id) || null;
  const opts = (allowNone ? [["", "Не подключена — «Скопировать задание» для своего чата"]] : [])
    .concat(provs.map((x) => [x.id, x.name + (x.kind === "cli" ? (x.installed ? " · установлен" : " · не найден") : "")]));
  const prov = select(opts, cur.id, async (v) => {
    try { await call({ cmd: "ai_set", which, provider: v }); } catch (e) { fail(e); }
  }, { label: "Нейросеть" });
  prov.id = "aiProv" + W;
  const hint = h("small", { class: "meta phint" }, p ? p.hint : "Без подключения нейросеть — свой чат: «Скопировать задание», ответ — обратно.");
  const url = h("input", { class: "inp", id: "aiUrl" + W, value: cur.url || "", placeholder: (p && p.url) || "https://…/v1" });
  url.addEventListener("change", () => call({ cmd: "ai_set", which, url: url.value }).catch(fail));
  const key = h("input", { class: "inp", type: "password", id: "aiKey" + W, autocomplete: "off",
    placeholder: cur.key_set ? "ключ задан — введите новый, чтобы заменить" : "ключ доступа" + (p && !p.needs_key ? " (если сервер просит)" : "") });
  key.addEventListener("change", async () => {
    const v = key.value;
    key.value = "";                                   // ключ уходит в программу и шифруется; на странице не остаётся
    try { await call({ cmd: "ai_set", which, key: v }); toast("Ключ сохранён (зашифрован)"); } catch (e) { fail(e); }
  });
  let modelEl;
  if (p && p.kind === "cli") {
    const list = p.models.map(([id, t]) => [id, t]);
    if (cur.model && !list.some(([id]) => id === cur.model)) list.push([cur.model, cur.model]);
    modelEl = select(list, cur.model, (v) => call({ cmd: "ai_set", which, model: v }).catch(fail), { label: "Модель" });
  } else {
    modelEl = h("input", { class: "inp", value: cur.model || "", list: "aiModels" + W, "aria-label": "Модель" });
    modelEl.addEventListener("change", () => call({ cmd: "ai_set", which, model: modelEl.value }).catch(fail));
  }
  modelEl.id = "aiModel" + W;
  const dl = h("datalist", { id: "aiModels" + W }, ...(p && p.kind !== "cli" ? p.models.map(([id]) => h("option", { value: id })) : []));
  const info = h("small", { class: "meta", id: "aiInfo" + W }, cur.problem || "");
  const refresh = btn("Обновить", { icon: "refresh", kind: "ghost", size: "sm", onClick: async () => {
    refresh.disabled = true;
    try {
      const models = await call({ cmd: "ai_models", which });
      clear(dl);
      for (const m of models) dl.append(h("option", { value: m }));
      info.textContent = "Моделей на сервере: " + models.length + ".";
    } catch (e) { info.textContent = e.message; } finally { refresh.disabled = false; }
  } });
  refresh.id = "aiModels" + W + "Btn";
  refresh.hidden = !p || p.kind === "cli";
  const pill = h("span", { class: "chip", id: "aiPill" + W, hidden: true });
  const check = btn("Проверить", { icon: "play", size: "sm", onClick: async () => {
    check.disabled = true;
    pill.hidden = false;
    pill.className = "chip";
    pill.textContent = "проверяю…";
    try {
      const r = await call({ cmd: "ai_check", which });
      pill.textContent = r.ok ? r.ms + " мс" : "не вышло";
      pill.className = "chip " + (r.ok ? "ok" : "warn");
      info.textContent = r.text;
    } catch (e) { pill.textContent = "не вышло"; pill.className = "chip warn"; info.textContent = e.message; } finally { check.disabled = false; }
  } });
  check.id = "aiCheck" + W;
  const f = (label, control, show) => { const x = h("div", { class: "field" }, h("label", null, label), control); x.hidden = !show; return x; };
  const openai = !!(p && p.kind === "openai");
  return h("div", { class: "aibox", id: "ai" + W + "Box" },
    h("div", { class: "field" }, h("label", { for: prov.id }, which === "backup" ? "Запасная" : "Нейросеть"), prov, hint),
    f("Адрес сервера", url, openai), f("Ключ доступа", key, openai),
    f("Модель", h("div", { class: "src" }, modelEl, refresh, dl), !!p),
    f("Проверка связи", h("div", { class: "src" }, check, pill), !!p), info);
}

function secAi() {
  const backupOn = !!st().ai_backup_enabled;
  const backup = h("div", { id: "aiBackup", hidden: !backupOn }, providerBox("backup", false));
  const mins = numberField(Math.round((st().ai_timeout_s || 0) / 60), { min: 0, max: 60, step: 1, unit: "мин", label: "Сколько ждать ответ",
    onChange: (v) => setv("ai_timeout_s", v * 60) });
  mins.input.id = "f-ai_timeout_min";
  return [card("Откуда брать модель", providerBox("main", true)),
    card("Запасная", sw("ai_backup_enabled", "Пробовать запасную", "Основная не ответила (сервер лёг, кончился лимит) — тот же запрос уйдёт запасной",
      (on) => { backup.hidden = !on; }), backup),
    card("Ожидание", row("Сколько ждать ответ", "0 — «авто»: по длине материала, до 20 минут", mins)),
    note("Материал уходит на сервер выбранной нейросети. LM Studio и Ollama работают на этом компьютере — с ними ничего никуда не уходит. Claude и ChatGPT по подписке — через установленные Claude Code и Codex, ключ не нужен.")];
}

// ---------------------------------------------------------------- обновления, о программе
function secUpdates() {
  const s = st();
  const deps = (on) => { for (const k of ["update_interval_h", "update_mode"]) if (V.inputs[k]) V.inputs[k].disabled = !on; };
  const modes = [["notify", "Только сообщить"], ["download", "Скачать и предложить перезапуск"], ["auto", "Скачать и установить при выходе"]];
  const last = s.update_last_check ? new Date(s.update_last_check * 1000).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" }) : "ещё не было";
  const checkNow = btn("Проверить сейчас", { kind: "primary", icon: "refresh", onClick: () => send({ cmd: "update_check" }) });
  checkNow.id = "updCheck";
  const unskip = btn("Снова предлагать", { kind: "ghost", onClick: () => setv("update_skip_version", "") });
  unskip.id = "unskip";
  const out = [card("Проверка",
    sw("update_auto_check", "Проверять автоматически", "Во время набора программа не обновляется и не отвлекает", deps),
    selRow("update_interval_h", "Как часто", "", [[0, "При каждом запуске"], [24, "Раз в день"], [168, "Раз в неделю"]]),
    selRow("update_mode", "Найдя новую версию", "", s.can_self_update ? modes : modes.slice(0, 1)),
    sw("update_prerelease", "Бета-версии", "Предлагать предварительные выпуски")),
  card("Версия", row("Установлена версия " + (s.version || ""), "Последняя проверка: " + last, checkNow),
    s.update_skip_version ? row("Пропущенная версия", "Версия " + s.update_skip_version + " не предлагается", unskip) : null)];
  deps(!!s.update_auto_check);
  return out;
}

function secAbout() {
  const s = { ...st() };
  for (const hk of st().hotkeys || []) s[hk.key] = hk.value;
  const b = (id, text, ic, cmd, kind) => { const x = btn(text, { icon: ic, kind, onClick: () => send({ cmd }) }); x.id = id; return x; };
  const roles = (LC.state && LC.state.roles) || [];
  const legend = roles.length ? card("Обозначения ролей", h("div", { class: "rolegrid" },
    ...roles.map((r) => h("div", { class: "rolei r-" + r.key }, h("b", null, r.name), r.how ? h("small", null, r.how) : null)))) : null;
  return [h("div", { class: "abouthead" }, h("div", { class: "alogo" }, icon("keyboard")),
    h("div", null, h("h2", null, "AutoPrintCode"), h("span", { class: "meta" }, "Версия " + (s.version || "") + " · суфлёр урока и набор кода в любое окно"))),
  h("div", { class: "abtns" }, b("checkUpd", "Проверить обновления", "refresh", "update_check", "primary"), b("openLog", "Журнал работы", "file", "open_log"),
    b("openData", "Папка с данными", "folder", "open_data"), b("reportBug", "Сообщить об ошибке", "bug", "report")),
  card("Как пользоваться", h("ol", { class: "howto" },
    h("li", null, "Откройте урок в «Уроках» — или «Новый урок»: план, тема, текст."),
    h("li", null, "Набирается только код: у блока — «Набрать» или следующий по очереди клавишами."),
    h("li", null, "Поставьте курсор в окне, куда набирать: Jupyter, VS Code, Блокнот."),
    h("li", null, "Нажмите ", h("b", { class: "mono" }, s.hotkey_toggle || "Ctrl+F9"), " — набор; ещё раз — пауза, ещё раз — продолжение."),
    h("li", null, h("b", { class: "mono" }, s.hotkey_restart || "—"), " — этот код ещё раз · ", h("b", { class: "mono" }, s.hotkey_stop || "—"),
      " — стоп · ", h("b", { class: "mono" }, s.hotkey_next_block || "—"), " / ", h("b", { class: "mono" }, s.hotkey_prev_block || "—"), " — следующий / предыдущий код."))),
  legend,
  h("a", { class: "rel", href: s.releases_url || "https://github.com/", target: "_blank", rel: "noopener" }, "Выпуски на GitHub")];
}

const BUILD = { view: secView, lesson: secLesson, typing: secTyping, sound: secSound, hotkeys: secHotkeys, behavior: secBehavior,
  ai: secAi, updates: secUpdates, about: secAbout };

// ---------------------------------------------------------------- экран
export function settingsView(root, r) {
  const nav = h("nav", { id: "setnav", "aria-label": "Разделы настроек" });
  for (const [k, ic, title] of SECTIONS) {
    const b = h("button", { type: "button", "data-sec": k }, icon(ic), h("span", null, title));
    b.addEventListener("click", () => go("#/settings/" + k));
    nav.append(b);
  }
  const body = h("div", { id: "setbody" });
  root.append(h("div", { class: "page settings" }, h("div", { class: "setwrap" }, nav, body)));
  let sec = "", sig = "";
  function show(r2) {
    if (V && V.onLeave) V.onLeave();
    sec = BUILD[r2.parts[1]] ? r2.parts[1] : "view";
    const title = SECTIONS.find((x) => x[0] === sec)[2];
    setCrumbs([{ label: "Настройки", href: "#/settings" }, { label: title }]);
    nav.querySelectorAll("button").forEach((b) => b.setAttribute("aria-current", b.dataset.sec === sec ? "page" : "false"));
    V = { sec, inputs: {} };
    clear(body);
    body.append(h("h1", null, title), ...BUILD[sec]().filter(Boolean));
    sig = keyOf();
  }
  // перерисовать раздел, когда поменялось то, что он показывает (и не во время ввода)
  const keyOf = () => JSON.stringify([sec, sec === "ai" ? [st().ai, st().providers, st().ai_backup_enabled] : sec === "sound" ? st().sound_styles
    : sec === "lesson" ? st().looks_outside : sec === "updates" ? [st().update_skip_version, st().update_last_check] : 0]);
  show(r);
  // ушли из поля ввода — показать то, что пришло, пока в нём печатали
  body.addEventListener("focusout", () => setTimeout(() => { if (V) upd(); }, 0));
  function upd() {
    if (!V) return;
    for (const [k, el] of Object.entries(V.inputs)) if (k in st() && document.activeElement !== el) syncField(k, st()[k]);
    // перерисовать, только если не печатают в поле; фокус (список, кнопка) — вернуть на то же место
    const k = keyOf();
    const a = document.activeElement;
    const typing = body.contains(a) && a.matches("input:not([type=checkbox]):not([type=range]), textarea");
    if (k !== sig && !typing) {
      const id = body.contains(a) ? a.id : "";
      show({ parts: ["settings", sec] });
      const back = id && document.getElementById(id);
      if (back) back.focus();
    }
  }
  return { route: show, update: upd, destroy: () => { if (V && V.onLeave) V.onLeave(); V = null; } };
}
