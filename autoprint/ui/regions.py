"""Где окно программы тянется мышью, а где — нажимаются кнопки страницы.

Заголовок окна рисует страница (встроенный браузер). Она сообщает прямоугольники «ручек» (пустое место шапки,
табло маленького режима) и «дырок» в них (кнопки, поля) — в CSS-пикселях страницы, с её масштабом. Окно в
WM_NCHITTEST спрашивает hit_code: внутри ручки и вне дырок — заголовок (тянуть, двойной щелчок, прилипание к
краям), иначе — содержимое страницы.
"""
from __future__ import annotations

from dataclasses import dataclass, field

HTCLIENT, HTCAPTION = 1, 2
MAX_RECTS = 200          # больше страница не шлёт; лишнее отбрасывается

Rect = tuple[float, float, float, float]


def _rects(raw) -> list[Rect]:
    out: list[Rect] = []
    if not isinstance(raw, (list, tuple)):
        return out
    for r in raw[:MAX_RECTS]:
        if not isinstance(r, (list, tuple)) or len(r) != 4:
            continue
        try:
            x, y, w, h = (float(v) for v in r)
        except (TypeError, ValueError):
            continue
        if w > 0 and h > 0:
            out.append((x, y, w, h))
    return out


@dataclass
class Regions:
    drag: list[Rect] = field(default_factory=list)
    holes: list[Rect] = field(default_factory=list)
    zoom: float = 1.0

    @classmethod
    def from_data(cls, d) -> "Regions":
        d = d if isinstance(d, dict) else {}
        try:
            z = float(d.get("zoom") or 1)
        except (TypeError, ValueError):
            z = 1.0
        return cls(_rects(d.get("drag")), _rects(d.get("holes")), z if 0.25 <= z <= 5 else 1.0)


def _inside(x: float, y: float, r: Rect, k: float) -> bool:
    rx, ry, rw, rh = r
    return rx * k <= x < (rx + rw) * k and ry * k <= y < (ry + rh) * k


def hit_code(x: float, y: float, r: Regions) -> int:
    """x, y — логические пиксели окна (как у Qt). Ручка без дырки — HTCAPTION, иначе HTCLIENT."""
    k = r.zoom
    if any(_inside(x, y, h, k) for h in r.holes):
        return HTCLIENT
    if any(_inside(x, y, d, k) for d in r.drag):
        return HTCAPTION
    return HTCLIENT
