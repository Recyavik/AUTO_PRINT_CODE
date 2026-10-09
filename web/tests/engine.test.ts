// Движок печати в «сухом» режиме (без нажатий): состояния, пауза/продолжение, стоп, темп.
import assert from "node:assert/strict";
import { test } from "node:test";
import { DEFAULT_SETTINGS, type EngineState, type Settings } from "../shared/model.ts";
import { Engine } from "../server/engine.ts";
import type { EngineEvent } from "../server/engine-worker.ts";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const S: Settings = { ...DEFAULT_SETTINGS, profile: "plain", cpm: 600, jitter: 0, newline_pause_ms: 0, punct_pause_ms: 0 };

function make(settings = S) {
  const e = new Engine(settings, "⌨ AutoPrintCode", { dryRun: true });
  const events: EngineEvent[] = [];
  e.on("event", (ev) => events.push(ev));
  const waitState = (st: EngineState, ms = 5000) => new Promise<void>((resolve, reject) => {
    if (e.state === st) return resolve();
    const t = setTimeout(() => reject(new Error(`нет состояния ${st}, сейчас ${e.state}`)), ms);
    e.on("event", (ev) => { if (ev.e === "state" && ev.state === st) { clearTimeout(t); resolve(); } });
  });
  return { e, events, waitState };
}

test("темп соответствует заданной скорости", async () => {
  const { e, events, waitState } = make();
  e.load("a".repeat(30));        // 600 симв/мин → 100 мс на символ → ~3 с
  const t0 = performance.now();
  e.start(0, 0);
  await waitState("finished");
  const ms = performance.now() - t0;
  await e.close();
  assert.ok(ms > 2700 && ms < 3800, `30 символов за ${ms.toFixed(0)} мс`);
  assert.equal(events.filter((x) => x.e === "sound").length, 30);
});

test("пауза, продолжение и стоп", async () => {
  const { e, events, waitState } = make();
  e.load("b".repeat(40));
  e.start(0, 0);
  await waitState("running");
  await sleep(500);
  e.pause();
  await waitState("paused");
  const typed = events.filter((x) => x.e === "sound").length;
  await sleep(500);
  assert.equal(events.filter((x) => x.e === "sound").length, typed, "во время паузы набор стоит");
  assert.ok(typed > 2 && typed < 10, `до паузы ${typed}`);
  e.resume(0, 0);
  await waitState("running");
  await sleep(300);
  e.stop();
  await waitState("idle");
  const atStop = events.filter((x) => x.e === "sound").length;
  await sleep(300);
  assert.equal(events.filter((x) => x.e === "sound").length, atStop, "после стопа набор не идёт");
  await e.close();
});

test("отсчёт перед стартом и «сначала»", async () => {
  const { e, events, waitState } = make({ ...S, cpm: 3000 });
  e.load("abc\ndef");
  e.start(0, 2);
  await waitState("countdown");
  await waitState("finished", 4000);
  assert.deepEqual(events.filter((x) => x.e === "countdown").map((x) => (x as { n: number }).n), [2, 1, 0]);
  e.restart(0, 0);
  await waitState("running");
  await waitState("finished");
  const sounds = events.filter((x) => x.e === "sound").length;
  assert.equal(sounds, 14, "два полных прогона по 7 единиц");
  await e.close();
});

test("пауза во время отсчёта и задержки хоткея: печать не начинается", async () => {
  for (const [delay, countdown] of [[0, 2], [1, 0]]) {
    const { e, events, waitState } = make({ ...S, cpm: 3000 });
    e.load("пауза");
    e.start(delay, countdown);
    await sleep(300);
    assert.ok(e.active, `готовится: delay=${delay} countdown=${countdown}`);
    e.pause();
    await waitState("paused");
    await sleep((delay + countdown) * 1000 + 500);
    assert.equal(e.state, "paused", "пауза не теряется, движок не «залипает» в печати");
    assert.equal(events.filter((x) => x.e === "sound").length, 0, "ни одного нажатия");
    e.resume(0, 0);
    await waitState("finished");
    assert.equal(events.filter((x) => x.e === "sound").length, 5);
    await e.close();
  }
});
