// Окно при запуске: расчёт положения на выбранном мониторе (без перемещения настоящих окон).
import assert from "node:assert/strict";
import { test } from "node:test";
import { normalRectOn } from "../server/screens.ts";

// раскладка: основной 4K (панель задач снизу), слева — 2560×1440 (монитор демонстрации)
const PRIMARY = { monitor: { left: 0, top: 0, right: 3840, bottom: 2160 }, work: { left: 0, top: 0, right: 3840, bottom: 2052 } };
const LEFT = { monitor: { left: -2560, top: 0, right: 0, bottom: 1440 }, work: { left: -2560, top: 0, right: 0, bottom: 1440 } };

test("окно с монитора демонстрации — по центру основного, размер сохраняется", () => {
  const onDemo = { left: -2300, top: 100, right: -700, bottom: 1100 };   // 1600×1000 на левом мониторе
  const r = normalRectOn(onDemo, PRIMARY, PRIMARY);
  assert.deepEqual([r.right - r.left, r.bottom - r.top], [1600, 1000]);
  assert.ok(r.left >= 0 && r.right <= 3840 && r.top >= 0 && r.bottom <= 2052, JSON.stringify(r));
  assert.equal((r.left + r.right) / 2, 1920);
});

test("окно больше монитора — ужимается до рабочей области", () => {
  const big = { left: 0, top: 0, right: 3600, bottom: 2000 };
  const r = normalRectOn(big, LEFT, PRIMARY);
  assert.deepEqual(r, { left: -2560, top: 0, right: 0, bottom: 1440 });
});

test("панель задач основного монитора слева — поправка на координаты рабочей области", () => {
  const primaryTaskbarLeft = { monitor: PRIMARY.monitor, work: { left: 100, top: 0, right: 3840, bottom: 2160 } };
  const r = normalRectOn({ left: 0, top: 0, right: 1000, bottom: 800 }, primaryTaskbarLeft, primaryTaskbarLeft);
  // центр рабочей области x = 1970 → левый край 1470 в экранных координатах → 1370 в координатах рабочей области
  assert.equal(r.left, 1370);
});
