// Листы окна программы (не урока): «Доступно обновление», «Сообщить об ошибке», «Записать звук клавиатуры»,
// «Внутренняя ошибка». Программа просит открыть лист через S.sheet (core.js → событие sheet): из трея, по найденному
// обновлению, при сбое; из «Настроек» — так же, командой.
"use strict";
import { S, on, send, call } from "./core.js";
import { h, btn, toggle, sheet, ask, toast, clear } from "./ui.js";
import { icon } from "./icons.js";
import { mdHtml } from "../lesson/md.js";

const fail = (e) => toast(String((e && e.message) || e), { warn: true });
const mb = (n) => (n >= 1048576 ? (n / 1048576).toFixed(1) + " МБ" : Math.max(1, Math.round(n / 1024)) + " КБ");
const open = {};                 // какой лист уже открыт: update | report | record | crash
const painters = new Set();      // открытые листы, которым нужно новое состояние программы
on("app", () => painters.forEach((p) => p()));

function once(name, make) {
  const cur = open[name];
  if (cur && cur.isConnected) return;               // этот лист уже на экране
  const p = make();
  open[name] = [...document.querySelectorAll(".scrim .sheet")].pop() || null;   // sheet() добавляет лист сразу
  return p.finally(() => { if (open[name] && !open[name].isConnected) open[name] = null; });
}

function foot(...items) { return h("div", { class: "sfoot inbody" }, ...items); }

// ---------------------------------------------------------------- обновление
export function updateSheet() {
  return once("update", () => {
    const head = h("div", { class: "updhead" });
    const notes = h("div", { class: "updnotes md" });
    const status = h("p", { class: "updstatus" });
    const bar = h("div", { class: "updbar", hidden: true }, h("span"));
    const main = btn("", { kind: "primary", onClick: () => {
      const r = S.release;
      const closes = r && (!r.installable || r.staged);
      send({ cmd: "update_install" }).catch(fail);
      if (closes) api.done("install");
    } });
    main.id = "updMain";
    const skip = btn("Пропустить эту версию", { kind: "ghost", onClick: async () => {
      try { await call({ cmd: "update_skip" }); api.done("skip"); } catch (e) { fail(e); }
    } });
    const later = btn("Позже", { onClick: () => api.done(null) });
    let api = null, notesFor = "";
    const paint = () => {
      const r = S.release;
      if (!r) { if (api) api.done(null); return; }
      clear(head).append(h("b", null, r.name || "AutoPrintCode " + r.version),
        h("span", { class: "dim" }, `Установлена версия ${r.current}, доступна ${r.version}` + (r.published ? ` от ${r.published}` : "")
          + (r.prerelease ? " (бета)" : "") + "."));
      if (notesFor !== r.version + r.notes) {
        notesFor = r.version + r.notes;
        notes.innerHTML = mdHtml(r.notes.trim() || "_Автор не добавил описание к этой версии._");
      }
      let label, text, warn = false;
      const p = r.progress;
      if (!r.installable) {
        label = "Скачать…";
        text = r.reason || "Скачайте новую версию со страницы выпуска.";
      } else if (r.staged) {
        label = "Перезапустить и обновить";
        text = r.frozen ? "Обновление скачано, контрольная сумма совпала. Программа закроется на несколько секунд и откроется "
          + "уже новой версией. Ваши уроки и настройки не изменятся." : "Обновление скачано и проверено. Ваши уроки и настройки не изменятся.";
      } else if (r.downloading) {
        label = "Отменить загрузку";
        text = p ? p.stage + (p.got ? ": " + mb(p.got) + (p.total ? " из " + mb(p.total) : "") : "…") : "Загрузка…";
      } else {
        label = "Обновить и перезапустить";
        text = "Ваши уроки и настройки не изменятся.";
      }
      if (r.error) { text = r.error + (r.frozen ? " Новую версию можно скачать и вручную — со страницы выпуска." : ""); warn = true; }
      main.querySelector(".bl") ? (main.querySelector(".bl").textContent = label) : main.append(h("span", { class: "bl" }, label));
      status.textContent = text;
      status.classList.toggle("warn", warn);
      bar.hidden = !r.downloading;
      const fill = bar.firstChild;
      fill.style.width = p && p.total ? Math.round((p.got / p.total) * 100) + "%" : "";
      bar.classList.toggle("busy", !!(r.downloading && !(p && p.total)));
      skip.hidden = !!r.staged;
    };
    const body = h("div", { class: "updsheet" }, head, h("div", { class: "flabel" }, "Что нового"), notes, status, bar,
      foot(skip, h("span", { class: "spacer" }), later, main));
    paint();
    painters.add(paint);
    return sheet("Доступно обновление", body, [], { wide: true, onOpen: (a) => { api = a; }, focus: "#updMain" })
      .finally(() => painters.delete(paint));
  });
}

// ---------------------------------------------------------------- сообщить об ошибке
const PLACEHOLDER = "Например: открыл урок, в VS Code нажал Ctrl+F9 — ожидал, что код напечатается с отступами, а строки "
  + "съехали вправо. Повторяется каждый раз.";

export function reportSheet() {
  return once("report", () => {
    const desc = h("textarea", { class: "ta", id: "repDesc", rows: "4", placeholder: PLACEHOLDER });
    const withSet = toggle("Приложить настройки (без уроков и личных данных)", true, () => refresh(),
      "Скорость, режимы, горячие клавиши, экраны и названия звуковых устройств");
    withSet.input.id = "repSettings";
    const crash = h("div", { class: "repcrash", hidden: true });
    const logs = h("small", { class: "meta" }, "В отчёт — последние строки журнала, в файл .zip — журнал целиком");
    const preview = h("pre", { class: "reppreview", id: "repPreview" }, "Собираю отчёт…");
    let info = null, saved = null, timer = 0;
    const args = () => ({ description: desc.value, include_settings: withSet.input.checked });
    async function refresh(fresh = false) {
      try {
        info = await call({ cmd: "report", fresh, ...args() });
        const top = preview.scrollTop;
        preview.textContent = info.markdown;
        preview.scrollTop = top;
        logs.textContent = `В отчёт — последние ${info.log_lines} строк журнала, в файл .zip — журнал целиком`;
        crash.hidden = !info.crash;
        if (info.crash) clear(crash).append(icon("bug"), h("div", null, h("b", null, "В журнале есть ошибка — она попадёт в отчёт"),
          h("small", null, `${info.crash.time} · ${info.crash.text}`)));
      } catch (e) { fail(e); }
    }
    desc.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(refresh, 250); });
    async function save() {
      if (!info) await refresh();
      try {
        const path = await call({ cmd: "pick_save", title: "Сохранить отчёт", name: info.zip_name, dir: info.desktop,
          filter: "Архив ZIP (*.zip)" });
        if (!path) return null;
        saved = await call({ cmd: "report_save", path, ...args() });
        toast(`Отчёт сохранён: ${saved.name}. Приложите его к сообщению на GitHub.`);
        return saved;
      } catch (e) { fail(e); return null; }
    }
    async function github() {
      if (!saved) await save();          // файл нужен, чтобы приложить его к сообщению; отмена — откроем и без него
      try {
        const r = await call({ cmd: "report_github", ...args() });
        if (!r.ok) toast("Не удалось открыть браузер — ссылка скопирована, вставьте её в адресную строку.", { warn: true });
        else if (r.saved) toast(`В браузере открылось новое сообщение — перетащите в него файл «${saved.name}» (он в папке ${saved.folder}).`);
        else toast("В браузере открылось новое сообщение. Сохраните отчёт и приложите файл к сообщению — в нём журнал работы.");
      } catch (e) { fail(e); }
    }
    let api = null;
    const logBtn = btn("Папка с журналом", { icon: "folder", size: "sm", onClick: () => send({ cmd: "open_log_folder" }) });
    const body = h("div", { class: "repsheet" },
      h("p", { class: "dim" }, "Опишите, что произошло. К сообщению приложатся версия программы, сведения о системе и журнал "
        + "работы — без текста уроков и того, что печатается."),
      h("div", { class: "field" }, h("label", { for: "repDesc" }, "Что случилось?"), desc,
        h("small", { class: "meta" }, "Что вы делали, чего ожидали и что произошло вместо этого")),
      withSet, crash,
      h("div", { class: "reprow" }, h("div", null, h("b", null, "Журнал работы"), logs), logBtn),
      h("div", { class: "rephead" }, h("span", { class: "flabel" }, "Что будет в отчёте"),
        h("small", { class: "meta" }, "Папка пользователя → %USERPROFILE%, имя → <user>")),
      preview,
      h("p", { class: "note" }, "«Сохранить отчёт…» — получится файл .zip: отчёт и журнал целиком. «Открыть на GitHub» — в браузере "
        + "откроется новое сообщение с кратким описанием: перетащите в него файл отчёта. Нет аккаунта на GitHub — пришлите файл "
        + "автору любым удобным способом."),
      foot(btn("Закрыть", { kind: "ghost", onClick: () => api.done(null) }), h("span", { class: "spacer" }),
        btn("Скопировать", { icon: "copy", onClick: async () => {
          try { await call({ cmd: "report_copy", ...args() }); toast("Отчёт скопирован — вставьте его в письмо или сообщение (Ctrl+V)."); }
          catch (e) { fail(e); }
        } }),
        btn("Сохранить отчёт…", { icon: "download", onClick: save }),
        btn("Открыть на GitHub", { kind: "primary", icon: "open", onClick: github })));
    refresh(true);
    return sheet("Сообщить об ошибке", body, [], { wide: true, onOpen: (a) => { api = a; }, focus: "#repDesc" });
  });
}

// ---------------------------------------------------------------- внутренняя ошибка
export function crashSheet(text) {
  return once("crash", () => sheet("Внутренняя ошибка", h("div", { class: "crashsheet" },
    h("p", null, "Внутренняя ошибка: " + (text || "")),
    h("p", { class: "dim" }, "Подробности — в журнале. Сообщите об ошибке — отчёт без личных данных поможет её исправить.")), [
    { spacer: true }, { label: "Закрыть", kind: "ghost", value: null },
    { label: "Сообщить об ошибке…", kind: "primary", value: "report", autofocus: true },
  ]).then((v) => { if (v === "report") setTimeout(reportSheet, 0); }));
}

// ---------------------------------------------------------------- запись звука клавиатуры
const STEPS = [
  ["mic", "Микрофон", "Запишем, как звучит ваша клавиатура, — и AutoPrintCode будет печатать её звуком. Понадобятся микрофон и пара минут."],
  ["key", "Обычные клавиши", "Нажмите «Начать запись» и спокойно нажимайте разные клавиши с буквами — около 15 раз, с паузой примерно "
    + "в полсекунды. Потом нажмите «Стоп»."],
  ["space", "Пробел", "Так же: около 8 нажатий пробела с паузами. Можно пропустить — тогда пробел будет звучать как обычная клавиша, "
    + "только ниже и громче."],
  ["enter", "Enter", "Около 8 нажатий Enter с паузами. Можно пропустить — тогда Enter будет звучать как обычная клавиша, только ниже и громче."],
  ["save", "Готово", "Назовите набор и послушайте, как он звучит. После сохранения он появится в списке «Какая клавиатура»."],
];
const KIND_TITLE = { key: "Обычные клавиши", space: "Пробел", enter: "Enter" };
const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function wavePath(w) {
  if (!w || !w.length) return "";
  const n = w.length, sx = 600 / Math.max(n, 1);
  let d = "";
  for (let i = 0; i < n; i++) {
    const v = Math.max(0.02, w[i]) * 26;
    const x = (i * sx + sx / 2).toFixed(1);
    d += `M${x} ${(30 - v).toFixed(1)}V${(30 + v).toFixed(1)}`;
  }
  return d;
}

export function recordSheet() {
  return once("record", () => {
    let step = 0, api = null, device = null;
    const lastClock = {};
    const R = () => S.record || null;
    const head = h("div", { class: "rechead" });
    const title = h("h3");
    const lede = h("p", { class: "dim" });
    const content = h("div", { class: "reccontent" });
    const warn = h("p", { class: "recwarn", hidden: true });
    const cancel = btn("Отмена", { kind: "ghost", onClick: () => api.tryClose() });
    const back = btn("Назад", { onClick: () => goStep(step - 1) });
    const next = btn("Далее", { kind: "primary", onClick: () => (STEPS[step][0] === "save" ? save() : goStep(step + 1)) });
    next.id = "recNext";
    const W = {};                 // элементы текущего шага

    const rec = (op, extra = {}) => call({ cmd: "record", op, ...extra });

    function build() {
      const [key, t, l] = STEPS[step];
      clear(head).append(h("div", { class: "dots" }, ...STEPS.map((_, i) => h("span", { class: i === step ? "on" : i < step ? "done" : "" }))),
        h("span", { class: "flabel" }, `Шаг ${step + 1} из ${STEPS.length}`));
      title.textContent = t;
      lede.textContent = l;
      clear(content);
      for (const k of Object.keys(W)) delete W[k];
      if (key === "mic") {
        W.sel = h("select", { class: "sel", id: "recDevice", "aria-label": "Микрофон" });
        W.sel.addEventListener("change", () => { device = W.sel.value; rec("monitor", { device }).catch(fail); });
        W.meter = h("div", { class: "recmeter" }, h("span"));
        content.append(
          h("div", { class: "field" }, h("label", { for: "recDevice" }, "Микрофон"), W.sel,
            h("small", { class: "meta" }, "Подойдёт тот, которым вы записываете видео")),
          h("div", { class: "field" }, h("span", { class: "flabel" }, "Уровень"), W.meter,
            h("small", { class: "meta" }, "Нажмите любую клавишу — полоска должна подпрыгнуть")),
          h("p", { class: "note" }, "Поставьте микрофон рядом с клавиатурой, в комнате — тишина. Дальше — три коротких записи: обычные "
            + "клавиши, пробел и Enter. Микрофон Bluetooth-наушников лучше не выбирать: пока он включён, Windows переводит наушники "
            + "в режим гарнитуры — звук становится тише и хуже. После закрытия записи всё возвращается."));
      } else if (key === "save") {
        W.name = h("input", { class: "inp", id: "recName", maxlength: "40", value: "Моя клавиатура" });
        W.name.addEventListener("input", paint);
        W.name.addEventListener("keydown", (e) => { if (e.key === "Enter" && !next.disabled) save(); });
        W.sum = h("div", { class: "recsum" });
        content.append(h("div", { class: "field" }, h("label", { for: "recName" }, "Название"), W.name,
          h("small", { class: "meta" }, "Так набор будет называться в «Настройках»")), W.sum,
          h("div", { class: "reprow" }, h("div", null, h("b", null, "Как это прозвучит"), h("small", { class: "meta" }, "Несколько нажатий подряд — как при печати")),
            btn("Послушать", { icon: "play", onClick: () => rec("preview", { kind: "all" }).catch(fail) })));
        setTimeout(() => { W.name.focus(); W.name.select(); }, 0);
      } else {
        W.kind = key;
        W.start = btn("Начать запись", { kind: "primary", icon: "mic", onClick: () => startRec(key) });
        W.stop = btn("Стоп", { icon: "stop", onClick: () => rec("stop").catch(fail) });
        W.listen = btn("Послушать", { icon: "play", onClick: () => rec("preview", { kind: key }).catch(fail) });
        W.clock = h("span", { class: "mono recclock" }, "0:00");
        W.path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        W.marks = document.createElementNS("http://www.w3.org/2000/svg", "g");
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", "0 0 600 60");
        svg.setAttribute("preserveAspectRatio", "none");
        svg.classList.add("recwave");
        svg.append(W.marks, W.path);
        W.status = h("p", { class: "recstatus" });
        content.append(h("div", { class: "recbox" }, h("div", { class: "recctl" }, W.start, W.stop, W.listen, h("span", { class: "spacer" }), W.clock),
          svg, W.status));
        if (key !== "key") {
          W.skip = btn("Пропустить — возьмём обычные клавиши", { kind: "ghost", onClick: async () => {
            try { await rec("skip", { kind: key }); goStep(step + 1); } catch (e) { fail(e); }
          } });
          content.append(W.skip);
        }
      }
      paint();
    }

    function paint() {
      const r = R();
      if (!r) return;
      const key = STEPS[step][0];
      const busy = !!r.recording;
      warn.hidden = !r.error;
      warn.textContent = r.error || "";
      back.hidden = step === 0;
      back.disabled = busy;
      cancel.disabled = busy;
      if (key === "mic" && W.sel) {
        const sig = JSON.stringify(r.devices);
        if (W.sel.dataset.sig !== sig) {
          W.sel.dataset.sig = sig;
          clear(W.sel);
          for (const [id, name, def] of r.devices) W.sel.append(h("option", { value: id }, name + (def ? " — по умолчанию" : "")));
          if (!r.devices.length) W.sel.append(h("option", { value: "" }, "Микрофон не найден"));
          const want = device || r.device || (r.devices.find((d) => d[2]) || r.devices[0] || [""])[0];
          W.sel.value = want;
          W.sel.disabled = !r.devices.length;
        }
        W.meter.firstChild.style.width = Math.round((r.level || 0) * 100) + "%";
        if (!r.devices.length && !r.error) { warn.hidden = false; warn.textContent = "Микрофон не найден: подключите его — он появится в списке сам"; }
      }
      if (W.kind) {
        const k = r.kinds[W.kind];
        const mine = r.recording === W.kind;
        W.start.hidden = mine;
        W.stop.hidden = !mine;
        W.start.disabled = busy;
        W.start.querySelector(".bl").textContent = k.has ? "Записать заново" : "Начать запись";
        W.listen.disabled = busy || !k.has;
        if (mine) lastClock[W.kind] = r.elapsed;
        W.clock.textContent = clock(lastClock[W.kind] || 0);
        W.path.setAttribute("d", wavePath(k.wave));
        clear(W.marks);
        if (!mine) for (const [a, b] of k.marks) {
          const rc = document.createElementNS("http://www.w3.org/2000/svg", "rect");
          rc.setAttribute("x", (a * 600).toFixed(1)); rc.setAttribute("width", Math.max(1, (b - a) * 600).toFixed(1));
          rc.setAttribute("y", "0"); rc.setAttribute("height", "60");
          W.marks.append(rc);
        }
        W.status.textContent = k.status;
        W.status.className = "recstatus" + (k.tone ? " t-" + k.tone : "");
        if (W.skip) W.skip.disabled = busy;
      }
      if (key === "save" && W.sum) {
        clear(W.sum);
        for (const kind of ["key", "space", "enter"]) {
          const k = r.kinds[kind];
          const word = k.hits % 10 === 1 && k.hits % 100 !== 11 ? "удар" : (k.hits % 10 >= 2 && k.hits % 10 <= 4 && !(k.hits % 100 >= 12 && k.hits % 100 <= 14)) ? "удара" : "ударов";
          const text = k.hits ? `Записано: ${k.hits} ${word}` : kind === "key" ? "Нет записей — вернитесь на шаг 2"
            : "Не записано — возьмём обычные клавиши, ниже по тону и громче";
          W.sum.append(h("div", { class: "recsumrow" }, h("b", null, KIND_TITLE[kind]), h("small", { class: "meta" }, text)));
        }
      }
      let ok = !busy;
      if (key === "mic") ok = ok && r.devices.length > 0;
      else if (key === "key") ok = ok && r.kinds.key.hits >= r.min_key;
      else if (key === "save") ok = ok && !!(W.name && W.name.value.trim()) && r.kinds.key.has;
      next.disabled = !ok;
      next.querySelector(".bl").textContent = key === "save" ? "Сохранить" : "Далее";
    }

    async function goStep(i) {
      const r = R();
      if (r && r.recording) return;
      i = Math.max(0, Math.min(STEPS.length - 1, i));
      const was = STEPS[step][0];
      step = i;
      build();
      try {
        if (STEPS[i][0] === "mic") await rec("monitor", { device: device || (R() && R().device) || null });
        else if (was === "mic") await rec("quiet");
      } catch (e) { fail(e); }
    }

    async function startRec(kind) {
      if (document.activeElement) document.activeElement.blur();   // пробел и Enter не нажмут кнопку с фокусом
      lastClock[kind] = 0;
      try { await rec("start", { kind, device }); } catch (e) { fail(e); }
    }

    async function save() {
      try {
        await rec("save", { name: W.name ? W.name.value : "" });
        api.done("saved");
      } catch (e) { fail(e); }
    }

    // пока идёт запись, клавиши — только для микрофона: ни кнопок, ни закрытия листа
    const guard = (e) => {
      const r = R();
      if (!r || !r.recording) return;
      e.preventDefault();
      e.stopImmediatePropagation();
    };
    for (const t of ["keydown", "keyup", "keypress"]) window.addEventListener(t, guard, true);
    painters.add(paint);

    const body = h("div", { class: "recsheet" }, head, title, lede, content, warn, foot(cancel, h("span", { class: "spacer" }), back, next));
    build();
    rec("monitor", { device: null }).catch(fail);
    return sheet("Записать звук клавиатуры", body, [], {
      wide: true, dismiss: false, onOpen: (a) => { api = a; }, focus: "#recNext",
      beforeClose: async () => {
        const r = R();
        const was = !!(r && r.recording);
        if (was) await rec("stop").catch(() => {});
        const dirty = was || (r && !r.saved && ["key", "space", "enter"].some((k) => r.kinds[k].has));
        if (!dirty) return true;
        return ask("Закрыть без сохранения? Записи пропадут.", { title: "Записать звук клавиатуры", ok: "Закрыть", cancel: "Отмена", danger: true });
      },
    }).finally(() => {
      painters.delete(paint);
      for (const t of ["keydown", "keyup", "keypress"]) window.removeEventListener(t, guard, true);
      rec("close").catch(() => {});
    });
  });
}

on("sheet", (r) => {
  if (r.name === "update") updateSheet();
  else if (r.name === "report") reportSheet();
  else if (r.name === "record") recordSheet();
  else if (r.name === "crash") crashSheet(r.text);
});
window.__winsheets = { updateSheet, reportSheet, recordSheet, crashSheet };
