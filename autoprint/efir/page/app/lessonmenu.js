// Меню урока — одно на «Уроки» (правый щелчок) и шапку урока («▾» у названия). Плоское, без подменю.
"use strict";
import { S, send, call } from "./core.js";
import { h, menu, ask, zoom } from "./ui.js";

export const extraItems = [];        // другие задачи добавляют пункты: fn(lesson) → [{…}] (экспорт, печать, план…)

export function lessonById(id) { return (S.lessons || []).find((x) => x.id === id) || null; }

export async function askDelete(x) {
  const isPlan = x.kind === "plan";
  const topics = isPlan ? (S.lessons || []).filter((l) => l.plan_id === x.id).length : 0;
  const live = S.live && S.live.lesson_id === x.id ? "Идёт урок — он завершится. " : "";
  const q = live + (isPlan ? `Удалить план «${x.title}»?` + (topics ? ` Уроки по нему (${topics}) останутся с этими этапами, но без связи.` : "")
    : `Удалить урок «${x.title}»?`);
  const ok = await ask(q + " Копия прошлой базы — data/templates.json.bak", { title: isPlan ? "Удалить план" : "Удалить урок",
    ok: "Удалить", danger: true });
  if (ok) send({ cmd: "delete", id: x.id });
  return ok;
}

/** Пункты меню урока или плана, одним списком. rename(id) — переименовать на месте (список) или в шапке (урок).
 *  o.open — меню в «Уроках»: первым пунктом «Открыть». */
export function lessonMenuItems(id, rename, o = {}) {
  const x = lessonById(id);
  if (!x) return [];
  const isPlan = x.kind === "plan";
  const items = [];
  if (isPlan && o.open) items.push({ label: "Новый урок по плану", icon: "plus", on: () => send({ cmd: "new_topic", plan: x.id }) });
  if (o.open) items.push({ label: isPlan ? "Открыть план" : "Открыть", icon: "open", on: () => send({ cmd: "open", lesson: x.id }) });
  items.push({ label: "Переименовать", icon: "pencil", on: () => rename && rename(x.id) },
    { label: "Дублировать", icon: "copy", on: () => send({ cmd: "duplicate", id: x.id }) });
  for (const fn of extraItems) items.push(...(fn(x) || []));
  items.push({ sep: true }, { label: "Удалить…", icon: "trash", danger: true, on: () => askDelete(x) });
  return items;
}

/** Меню у точки (правый щелчок): невидимый якорь в месте щелчка. */
export function menuAt(ev, items) {
  ev.preventDefault();
  const z = zoom();
  const a = h("span", { style: { position: "fixed", left: ev.clientX / z + "px", top: ev.clientY / z + "px", width: "1px", height: "1px" } });
  document.body.append(a);
  const m = menu(a, items);
  setTimeout(() => a.remove(), 0);
  return m;
}

export { call };
