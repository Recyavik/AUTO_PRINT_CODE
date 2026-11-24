// Временные экраны, пока настоящие не готовы (уроки — Task 6, новый урок — 11, эфир — 13, настройки — 14).
// В установленную программу не попадают: сборка ставится только целиком готовой.
"use strict";
import { h } from "./ui.js";
import { setCrumbs } from "./shell.js";

function stub(title) {
  return (root) => {
    setCrumbs([{ label: title }]);
    root.append(h("div", { class: "page" }, h("div", { class: "wrap" }, h("h1", null, title))));
    return {};
  };
}

export const placeholders = {
  lessons: stub("Уроки"),
  new: stub("Новый урок"),
  efir: stub("Эфир"),
  settings: stub("Настройки"),
};
