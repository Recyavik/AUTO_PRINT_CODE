// Витрина компонентов (#/dev/ui): для проверки вида и снимков экрана. В меню не показывается.
"use strict";
import { h, btn, iconBtn, seg, toggle, field, numberField, select, menu, sheet, ask, toast } from "./ui.js";
import { icon } from "./icons.js";

export function devView(root) {
  const wrap = h("div", { class: "wrap" });
  root.append(h("div", { class: "devui" }, wrap));
  const sec = (title, ...items) => wrap.append(h("section", { class: "field" }, h("h2", null, title), h("div", { class: "row" }, ...items)));
  wrap.append(h("h1", null, "Компоненты окна"));
  sec("Кнопки", btn("Начать урок", { kind: "primary", icon: "play" }), btn("Набрать", { icon: "keyboard" }),
    btn("Отмена", { kind: "ghost" }), btn("Завершить", { kind: "stop", icon: "stop" }), btn("Маленькая", { size: "sm" }),
    iconBtn("pin", "Поверх всех окон", () => {}), iconBtn("copy", "Скопировать", () => {}, { kind: "ghost" }));
  sec("Сегменты", seg([{ value: "a", label: "Целиком" }, { value: "b", label: "По строкам" }, { value: "c", label: "По шагам" }], "a"),
    seg([{ value: "bg", icon: "image", label: "Фон" }, { value: "ex", icon: "activity", label: "Зарядка" },
      { value: "br", icon: "cup", label: "Перерыв" }, { value: "sl", icon: "slide", label: "Слайд" }], "bg", null,
    { icons: true, label: "Что видят ученики" }));
  sec("Переключатели", toggle("Как человек", true, null, "живой ритм, паузы, опечатки"), toggle("Звук клавиш", false));
  sec("Поля", field("Тема урока", h("input", { class: "inp", value: "Django: формы и валидация" })),
    field("Скорость", numberField(320, { min: 30, max: 3000, step: 10, unit: "зн/мин" })),
    field("Тема", select([["system", "Как в Windows"], ["dark", "Тёмная"], ["light", "Светлая"]], "system")));
  const mb = btn("Меню", { icon: "chevron-down" });
  mb.addEventListener("click", () => menu(mb, [{ label: "Переименовать", icon: "pencil" }, { label: "Экспорт…", icon: "download" },
    { sep: true }, { label: "Удалить…", danger: true, icon: "trash" }]));
  sec("Всплывающее", mb, btn("Лист", { onClick: () => sheet("Экспорт урока", h("p", null, "Формат и что положить в файл."),
    [{ spacer: true }, { label: "Отмена", kind: "ghost", value: null }, { label: "Сохранить…", kind: "primary" }]) }),
  btn("Вопрос", { onClick: () => ask("Удалить урок «Пример»?", { danger: true, ok: "Удалить" }) }),
  btn("Тост", { onClick: () => toast("Время этапов сдвинуто на сейчас", { action: "Вернуть" }) }));
  sec("Метки", h("span", { class: "chip ok" }, h("span", { class: "dot" }), "на связи"), h("span", { class: "chip warn" }, "До начала 4:12"),
    h("span", { class: "chip live" }, "Идёт"), h("span", { class: "chip" }, icon("lock", "sm"), "из плана"));
  return {};
}
