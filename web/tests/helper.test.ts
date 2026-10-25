// Второй запуск помощника (start.bat, автозапуск): заменяет устаревшего, не трогает такого же или новее.
// Помощники запускаются на своём порту со своей папкой данных — рабочий помощник не затрагивается.
//
//   node --test tests/helper.test.ts      (входит в npm run test:ui)
import assert from "node:assert/strict";
import { type ChildProcess, spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, test } from "node:test";

const WEB = path.join(import.meta.dirname, "..");
const PORT = 8790 + 300 + Math.floor(Math.random() * 100);
const URL_SELF = `http://127.0.0.1:${PORT}`;
const DATA = fs.mkdtempSync(path.join(os.tmpdir(), "apc-helper-"));
const VERSION = JSON.parse(fs.readFileSync(path.join(WEB, "package.json"), "utf-8")).version as string;
fs.writeFileSync(path.join(DATA, "settings.json"), JSON.stringify({   // глобальные хоткеи не занимаем
  hotkey_toggle: "", hotkey_restart: "", hotkey_stop: "", hotkey_next_block: "", hotkey_prev_block: "",
}));

const procs: ChildProcess[] = [];
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function start(version?: string): ChildProcess {
  const p = spawn(process.execPath, ["server/main.ts", "--no-open"], {
    cwd: WEB, stdio: "ignore",
    env: { ...process.env, AUTOPRINT_PORT: String(PORT), AUTOPRINT_DATA: DATA, AUTOPRINT_VERSION: version ?? "" },
  });
  procs.push(p);
  return p;
}

const running = () => fetch(`${URL_SELF}/api/version`).then((r) => r.text(), () => null);
const exited = (p: ChildProcess) => p.exitCode !== null || p.signalCode !== null;

async function waitFor(ok: () => boolean | Promise<boolean>, ms = 20000): Promise<boolean> {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    if (await ok()) return true;
    await sleep(200);
  }
  return false;
}

after(() => {
  for (const p of procs) if (!exited(p)) p.kill();
  fs.rmSync(DATA, { recursive: true, force: true });
});

test("устаревший помощник заменяется новым (по ключу из папки данных)", async () => {
  const old = start("0.0.1");
  assert.ok(await waitFor(async () => (await running()) === "AutoPrintCode 0.0.1"), "старый помощник запущен");
  const fresh = start();
  assert.ok(await waitFor(async () => (await running()) === `AutoPrintCode ${VERSION}`), "на порту — новая версия");
  assert.ok(await waitFor(() => exited(old)), "старый завершился");
  assert.ok(!exited(fresh), "новый работает");
});

test("помощник без ключа (версии до 0.5.3) завершается по процессу", async () => {
  fs.rmSync(path.join(DATA, ".helper-token"));      // так выглядит помощник, у которого нет /api/shutdown
  for (const p of procs) if (!exited(p)) p.kill();
  await waitFor(async () => (await running()) === null);
  const old = start("0.0.2");
  assert.ok(await waitFor(async () => (await running()) === "AutoPrintCode 0.0.2"));
  fs.rmSync(path.join(DATA, ".helper-token"));
  start();
  assert.ok(await waitFor(async () => (await running()) === `AutoPrintCode ${VERSION}`), "на порту — новая версия");
  assert.ok(await waitFor(() => exited(old)), "старый завершён");
});

test("такой же версии — второй запуск только открывает страницу и выходит", async () => {
  const before = procs.filter((p) => !exited(p));
  const second = start();
  assert.ok(await waitFor(() => exited(second)), "второй экземпляр вышел");
  assert.equal(await running(), `AutoPrintCode ${VERSION}`);
  assert.ok(before.every((p) => !exited(p)), "работающий помощник не тронут");
});

test("более новый работающий помощник не заменяется старым", async () => {
  for (const p of procs) if (!exited(p)) p.kill();
  await waitFor(async () => (await running()) === null);
  start("99.0.0");
  assert.ok(await waitFor(async () => (await running()) === "AutoPrintCode 99.0.0"));
  const older = start();
  assert.ok(await waitFor(() => exited(older)), "запуск старой версии вышел");
  assert.equal(await running(), "AutoPrintCode 99.0.0");
});
