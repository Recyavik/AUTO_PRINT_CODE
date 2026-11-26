"use strict";
// Места окна на экране (DIP Electron): большое окно, маленький режим. Чистые функции — тесты в tests/geometry.test.js.
// Прямоугольник Electron — {x, y, width, height}; в настройках программы — {x, y, w, h} (+ max у большого).

const BIG = { width: 1280, height: 860 };
const BIG_MIN = { width: 720, height: 480 };
const COMPACT = { width: 360, height: 600 };
const COMPACT_MIN = { width: 150, height: 70 };
const SEEN = { width: 120, height: 40 };      // столько окна должно быть на каком-нибудь экране, иначе — место заново

const num = (v) => typeof v === "number" && Number.isFinite(v);

/** Первый запуск: 1280×860, но не больше рабочей области экрана (с полями 20 px), по центру. */
function defaultBig(work) {
  const w = Math.max(Math.min(BIG.width, work.width - 40), Math.min(BIG_MIN.width, work.width));
  const h = Math.max(Math.min(BIG.height, work.height - 40), Math.min(BIG_MIN.height, work.height));
  return { x: work.x + Math.floor((work.width - w) / 2), y: work.y + Math.floor((work.height - h) / 2), width: w, height: h };
}

/** Маленький режим впервые: 360×600 у правого края экрана (отступ 16 px), по высоте — посередине. */
function defaultCompact(work) {
  const w = Math.min(COMPACT.width, work.width), h = Math.min(COMPACT.height, work.height);
  return { x: Math.max(work.x, work.x + work.width - w - 16), y: work.y + Math.max(0, Math.floor((work.height - h) / 2)),
    width: w, height: h };
}

/** «Вид» маленького режима: w×h пикселей страницы × масштаб k. Правый верхний угол — на месте, окно — в пределах экрана. */
function compactResize(cur, w, h, k, work) {
  const W = Math.max(COMPACT_MIN.width, Math.min(Math.round(w * k), work.width));
  const H = Math.max(COMPACT_MIN.height, Math.min(Math.round(h * k), work.height));
  const right = cur.x + cur.width;
  return { x: Math.max(work.x, Math.min(right - W, work.x + work.width - W)),
    y: Math.max(work.y, Math.min(cur.y, work.y + work.height - H)), width: W, height: H };
}

function overlap(a, b) {
  const w = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x);
  const h = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y);
  return w > 0 && h > 0 ? { width: w, height: h } : null;
}

/** Запомненное место {x, y, w, h} → прямоугольник на том экране, где окно было; экрана больше нет (окно почти
 * не видно) или запись испорчена — null (место по умолчанию). Больше экрана — по размеру экрана и внутрь него. */
function placeSaved(saved, works, min) {
  if (!saved || typeof saved !== "object" || ![saved.x, saved.y, saved.w, saved.h].every(num)) return null;
  if (saved.w < 50 || saved.h < 30) return null;
  const b = { x: Math.round(saved.x), y: Math.round(saved.y), width: Math.round(saved.w), height: Math.round(saved.h) };
  let best = null, area = 0;
  for (const wa of works || []) {
    const o = overlap(b, wa);
    if (o && o.width * o.height > area) { best = wa; area = o.width * o.height; }
  }
  if (!best) return null;
  const o = overlap(b, best);
  if (o.width < Math.min(SEEN.width, b.width) || o.height < Math.min(SEEN.height, b.height)) return null;
  const m = min || { width: 1, height: 1 };
  const width = Math.max(Math.min(b.width, best.width), Math.min(m.width, best.width));
  const height = Math.max(Math.min(b.height, best.height), Math.min(m.height, best.height));
  const x = Math.max(best.x, Math.min(b.x, best.x + best.width - width));
  const y = Math.max(best.y, Math.min(b.y, best.y + best.height - height));
  return { x, y, width, height };
}

/** Прямоугольник Electron → запись для настроек программы. */
function toSaved(b, extra) {
  return b ? Object.assign({ x: b.x, y: b.y, w: b.width, h: b.height }, extra || {}) : null;
}

module.exports = { BIG, BIG_MIN, COMPACT, COMPACT_MIN, defaultBig, defaultCompact, compactResize, placeSaved, toSaved };
