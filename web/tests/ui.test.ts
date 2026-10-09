// Сквозной тест страницы: отдельный помощник (свой порт и папка данных) + Chrome/Edge без окна.
//
//   npm run test:ui
//
// Рабочие образцы и запущенный помощник не затрагиваются. Нет Chrome/Edge — тест пропускается.
// Печать в окна здесь не проверяется (это tests/e2e-editors.ts) — только страница и её связь с помощником.
import assert from "node:assert/strict";
import { type ChildProcess, spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, before, test } from "node:test";
import puppeteer, { type Browser, type Page } from "puppeteer-core";

const PORT = 8790 + 100 + Math.floor(Math.random() * 100);
const URL_SELF = `http://127.0.0.1:${PORT}`;
const DATA = fs.mkdtempSync(path.join(os.tmpdir(), "apc-ui-"));
const BROWSERS = [
  String.raw`C:\Program Files\Google\Chrome\Application\chrome.exe`,
  String.raw`C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`,
  String.raw`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`,
  String.raw`C:\Program Files\Microsoft\Edge\Application\msedge.exe`,
];
const browserPath = BROWSERS.find((p) => fs.existsSync(p));
const built = fs.existsSync(path.join(import.meta.dirname, "..", "dist", "index.html"));
const skip = !browserPath ? "нет Chrome/Edge" : !built ? "страница не собрана (npm run build)" : false;

const MD = "## Условие\n\nСтрока один\n\nСтрока два про **словарь**";
const block = (id: string, type: string, text: string) =>
  ({ id, type, text, lang: "python", sel: [], role: "task", title: "", zoom: 100, print_as: "markdown" });
fs.writeFileSync(path.join(DATA, "templates.json"), JSON.stringify({ version: 3, templates: [
  { id: "aaa", title: "Альфа", active_block: "code1", updated: 1,
    blocks: [block("md1", "markdown", MD), block("code1", "code", "x = 1\ny = 2")] },
  { id: "bbb", title: "Бета", active_block: "", updated: 1, blocks: [block("b1", "code", "b")] },
  { id: "ccc", title: "Гамма", active_block: "", updated: 1, blocks: [block("c1", "code", "c")] },
] }));
fs.writeFileSync(path.join(DATA, "settings.json"), JSON.stringify({
  open_tabs: ["aaa", "bbb", "ccc"], current_tab: "aaa", sound_enabled: false,
  // хоткеи помощника глобальные — тестовый экземпляр их не занимает
  hotkey_toggle: "", hotkey_restart: "", hotkey_stop: "", hotkey_next_block: "", hotkey_prev_block: "",
}));

let helper: ChildProcess;
let browser: Browser;
let page: Page;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

const saved = () => JSON.parse(fs.readFileSync(path.join(DATA, "templates.json"), "utf-8"));
const savedSettings = () => JSON.parse(fs.readFileSync(path.join(DATA, "settings.json"), "utf-8"));
const tabNames = () => page.$$eval(".tab span", (els) => els.map((e) => e.textContent).join(","));

async function waitFor<T>(get: () => T | Promise<T>, ok: (v: T) => boolean, ms = 5000): Promise<T> {
  const end = Date.now() + ms;
  for (;;) {
    const v = await get();
    if (ok(v) || Date.now() > end) return v;
    await sleep(100);
  }
}

before(async () => {
  if (skip) return;
  helper = spawn(process.execPath, ["server/main.ts", "--no-open"], {
    cwd: path.join(import.meta.dirname, ".."), stdio: "ignore",
    env: { ...process.env, AUTOPRINT_PORT: String(PORT), AUTOPRINT_DATA: DATA },
  });
  await waitFor(() => fetch(`${URL_SELF}/api/version`).then((r) => r.ok, () => false), (ok) => ok, 15000);
  browser = await puppeteer.launch({ executablePath: browserPath, headless: true });
  page = await browser.newPage();
  // без окна страница «не в фокусе», и редактор кода не сообщает о выделении — включаем фокус
  const cdp = await page.createCDPSession();
  await cdp.send("Emulation.setFocusEmulationEnabled", { enabled: true });
  await page.goto(URL_SELF);
  await page.waitForSelector(".tab");
});

after(async () => {
  await browser?.close();
  helper?.kill();
  fs.rmSync(DATA, { recursive: true, force: true });
});

test("удаление выделенного кода (одна правка) сохраняется", { skip }, async () => {
  const editor = await page.waitForSelector('[data-bid="code1"] .cm-content');
  await editor!.click();
  await page.keyboard.down("Control");
  await page.keyboard.press("KeyA");
  await page.keyboard.up("Control");
  // предусловие ошибки: выделение уже записано в блок
  const sel = await waitFor(() => saved().templates[0].blocks[1].sel.join(), (x) => x === "0,11");
  assert.equal(sel, "0,11", "выделение сохранено");
  await page.keyboard.press("Backspace");      // одна правка: текст и выделение меняются в одном обновлении
  await sleep(1500);                           // редактор догоняет значение со страницы после паузы в наборе
  assert.equal(saved().templates[0].blocks[1].text, "", "текст в templates.json");
  const shown = await page.$eval('[data-bid="code1"] .cm-content', (e) => (e as HTMLElement).innerText.trim());
  assert.equal(shown, "", "текст в редакторе не откатился");
  await page.keyboard.type("z = 3");
  assert.equal(await waitFor(() => saved().templates[0].blocks[1].text, (t) => t === "z = 3"), "z = 3");
});

test("выделение в тексте блока — печатаются выделенные строки", { skip }, async () => {
  const para = await page.waitForSelector('[data-bid="md1"] .md-view p:last-child');
  await para!.click({ count: 3 });              // тройной щелчок — выделить абзац
  const label = await waitFor(() => page.$eval(".status .armed", (e) => e.textContent ?? ""),
    (t) => t.includes("выделенные строки"));
  assert.match(label, /Условие · текст как Markdown, выделенные строки \(1 стр\./);
  const md = await waitFor(() => saved().templates[0], (t) => t.active_block === "md1");
  assert.equal(md.active_block, "md1", "щелчок по тексту делает блок активным");
  const [a, b] = md.blocks[0].sel;
  assert.equal(MD.slice(a, b), "Строка два про **словарь**");
});

test("вкладки перетаскиваются, порядок сохраняется", { skip }, async () => {
  const drag = (from: number, to: number, side: "left" | "right") => page.evaluate(async (f, t, side) => {
    const tabs = [...document.querySelectorAll(".tab")];
    const dt = new DataTransfer();
    const r = tabs[t].getBoundingClientRect();
    const x = side === "left" ? r.left + 3 : r.right - 3;
    const ev = (type: string) => new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: dt, clientX: x, clientY: r.top + 5 });
    tabs[f].dispatchEvent(ev("dragstart"));
    await new Promise((r) => setTimeout(r, 50));
    tabs[t].dispatchEvent(ev("dragover"));
    await new Promise((r) => setTimeout(r, 50));
    tabs[t].dispatchEvent(ev("drop"));
    tabs[f].dispatchEvent(ev("dragend"));
    await new Promise((r) => setTimeout(r, 200));
  }, from, to, side);
  assert.equal(await tabNames(), "Альфа,Бета,Гамма");
  await drag(2, 0, "left");
  assert.equal(await tabNames(), "Гамма,Альфа,Бета");
  await drag(0, 2, "right");
  assert.equal(await tabNames(), "Альфа,Бета,Гамма");
  await drag(0, 1, "right");
  assert.equal(await tabNames(), "Бета,Альфа,Гамма");
  const tabs = await waitFor(() => savedSettings().open_tabs.join(), (t) => t === "bbb,aaa,ccc");
  assert.equal(tabs, "bbb,aaa,ccc");
  await page.reload();
  await page.waitForSelector(".tab");
  assert.equal(await tabNames(), "Бета,Альфа,Гамма", "после перезагрузки");
});

test("кривой адрес не роняет помощника", { skip }, async () => {
  const bad = await fetch(`${URL_SELF}/%`);
  assert.equal(bad.status, 400);
  assert.ok((await fetch(`${URL_SELF}/api/version`)).ok, "помощник жив");
});
