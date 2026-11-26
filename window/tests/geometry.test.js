"use strict";
// Места окна: node --test window/tests
const test = require("node:test");
const assert = require("node:assert/strict");
const G = require("../geometry.js");

const WORK = { x: 0, y: 0, width: 1920, height: 1040 };
const LEFT = { x: -1280, y: 0, width: 1280, height: 984 };     // второй монитор слева

test("большое окно впервые — 1280×860 по центру", () => {
  assert.deepEqual(G.defaultBig(WORK), { x: 320, y: 90, width: 1280, height: 860 });
});

test("на маленьком экране — с полями, но не меньше 720×480", () => {
  assert.deepEqual(G.defaultBig({ x: 0, y: 0, width: 1024, height: 700 }), { x: 20, y: 20, width: 984, height: 660 });
  const tiny = G.defaultBig({ x: 0, y: 0, width: 700, height: 460 });
  assert.equal(tiny.width, 700);
  assert.equal(tiny.height, 460);
});

test("маленький режим впервые — 360×600 у правого края посередине", () => {
  assert.deepEqual(G.defaultCompact(WORK), { x: 1920 - 360 - 16, y: 220, width: 360, height: 600 });
  assert.deepEqual(G.defaultCompact(LEFT), { x: -16 - 360, y: 192, width: 360, height: 600 });
});

test("вид маленького режима: размер × масштаб, правый верхний угол на месте", () => {
  const cur = { x: 300, y: 50, width: 360, height: 500 };
  assert.deepEqual(G.compactResize(cur, 640, 440, 1, WORK), { x: 20, y: 50, width: 640, height: 440 });
  assert.deepEqual(G.compactResize(cur, 300, 110, 1.5, WORK), { x: 210, y: 50, width: 450, height: 165 });
});

test("вид маленького режима: не меньше 150×70 и не шире экрана", () => {
  const cur = { x: 1500, y: 900, width: 360, height: 100 };
  const r = G.compactResize(cur, 4000, 120, 1, WORK);
  assert.deepEqual([r.x, r.width], [0, 1920]);
  assert.ok(r.y + r.height <= WORK.height);
  assert.deepEqual(G.compactResize(cur, 10, 10, 1, WORK).width, 150);
});

test("запомненное место — там же, если экран на месте", () => {
  assert.deepEqual(G.placeSaved({ x: 100, y: 80, w: 1000, h: 700 }, [WORK, LEFT]), { x: 100, y: 80, width: 1000, height: 700 });
  assert.deepEqual(G.placeSaved({ x: -1200, y: 10, w: 800, h: 600 }, [WORK, LEFT]), { x: -1200, y: 10, width: 800, height: 600 });
});

test("экрана больше нет или запись испорчена — место по умолчанию", () => {
  assert.equal(G.placeSaved({ x: -1200, y: 10, w: 800, h: 600 }, [WORK]), null);
  assert.equal(G.placeSaved({ x: 1910, y: 10, w: 800, h: 600 }, [WORK]), null);       // за правым краем
  assert.equal(G.placeSaved({ x: "1", y: 0, w: 800, h: 600 }, [WORK]), null);
  assert.equal(G.placeSaved(null, [WORK]), null);
  assert.equal(G.placeSaved({ x: 0, y: 0, w: 10, h: 10 }, [WORK]), null);
});

test("больше экрана — по размеру экрана и внутрь", () => {
  const r = G.placeSaved({ x: 1500, y: 100, w: 2600, h: 1300 }, [WORK], G.BIG_MIN);
  assert.deepEqual(r, { x: 0, y: 0, width: 1920, height: 1040 });
  const part = G.placeSaved({ x: 1500, y: 500, w: 800, h: 700 }, [WORK], G.BIG_MIN);
  assert.deepEqual(part, { x: 1120, y: 340, width: 800, height: 700 });
});

test("запись для настроек", () => {
  assert.deepEqual(G.toSaved({ x: 1, y: 2, width: 3, height: 4 }, { max: true }), { x: 1, y: 2, w: 3, h: 4, max: true });
  assert.equal(G.toSaved(null), null);
});
