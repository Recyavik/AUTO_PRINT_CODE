// Фоновые работы программы (нейросеть составляет урок, качаются картинки): ход виден в «Новом уроке» и в «Уроках»,
// куда бы учитель ни ушёл. Строки обновляются на месте — кнопки не пересоздаются каждую секунду.
"use strict";
import { S, on, send } from "./core.js";
import { h, btn, clear } from "./ui.js";

const clock = (s) => Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");

function phaseText(j) {
  const n = (j.chars || 0).toLocaleString("ru-RU");
  if (j.kind === "photos") return "скачиваю картинки" + (j.preview ? ": " + j.preview : "…");
  if (j.kind === "copy") return "копирую" + (j.preview ? ": " + j.preview : "…");
  return { connect: "жду ответа", think: j.chars ? "думает — объём рассуждений " + n : "думает",
    write: "пишет — " + n + " знаков" }[j.phase] || "работает";
}

function line(j) {
  if (j.error) return j.error;
  if (j.done) return "Готово";
  return (j.who ? j.who + ": " : "") + phaseText(j) + " · " + clock(j.seconds || 0);
}

function actions(j) {
  const out = [];
  const mk = (label, act, cmd, kind = "ghost") => {
    const b = btn(label, { size: "sm", kind, onClick: () => send({ cmd, id: j.id }).catch(() => {}) });
    b.dataset.act = act;
    return b;
  };
  if (!j.done) {
    if (j.kind === "photos") out.push(mk("Пропустить", "skip", "job_skip", ""));
    out.push(mk("Отмена", "cancel", "job_cancel"));
  } else if (j.error) out.push(mk("Закрыть", "dismiss", "job_dismiss"));
  return out;
}

/** Блок работ: {el, destroy}. Пусто — блок скрыт. */
export function jobsBox(cls = "") {
  const box = h("section", { class: "jobs " + cls, "aria-live": "polite", "aria-label": "Фоновые работы" });
  const rows = new Map();
  const draw = () => {
    const list = S.jobs || [];
    box.hidden = !list.length;
    const ids = new Set(list.map((j) => j.id));
    for (const [id, el] of rows) if (!ids.has(id)) { el.remove(); rows.delete(id); }
    for (const j of list) {
      let el = rows.get(j.id);
      if (!el) {
        el = h("div", { class: "job", "data-id": j.id }, h("span", { class: "jspin", "aria-hidden": "true" }),
          h("div", { class: "jtext" }, h("b", { class: "jt" }), h("span", { class: "jp" }), h("span", { class: "jtail mono" })),
          h("div", { class: "jact" }));
        rows.set(j.id, el);
        box.append(el);
      }
      el.className = "job" + (j.error ? " err" : j.done ? " ok" : "");
      const set = (sel, t) => { const x = el.querySelector(sel); if (x.textContent !== t) x.textContent = t; };
      set(".jt", j.title || "Работа");
      set(".jp", line(j));
      set(".jtail", !j.done && j.phase === "write" && j.preview ? j.preview : "");
      const akey = [j.done, !!j.error, j.kind].join("|");
      const act = el.querySelector(".jact");
      if (act.dataset.k !== akey) { act.dataset.k = akey; clear(act); act.append(...actions(j)); }
    }
  };
  const off = on("app", draw);
  draw();
  return { el: box, destroy: off };
}
