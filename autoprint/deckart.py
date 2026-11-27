"""Кнопки пульта картинками (1.3): SVG в стиле окна программы — тёмная плитка, значок линией, подпись; нажатое —
янтарным, выключенный звук и микрофон — красным. Текст раскладывает программа (переносит по словам, уменьшает,
обрезает многоточием), поэтому ничего не вылезает за край кнопки, какого бы размера ни была сетка.

tile(...) → SVG-строка; data_url(svg) → «data:image/svg+xml;base64,…» для Macro Deck (imageUrl из переменной).
Размер: ячейка — 100 × 100 единиц, кнопка на w ячеек — w·100 + (w−1)·GAP.
"""
from __future__ import annotations

import base64
from xml.sax.saxutils import escape

GAP = 8
FONT = "'Segoe UI', Roboto, 'Noto Sans', Arial, sans-serif"

# цвета окна программы (тёмная тема, app.css)
GROUND, PANEL, RAISED, RAISED2 = "#161A22", "#1C212B", "#242A36", "#2D3442"
TEXT, DIM, FAINT, OFF = "#E9EDF3", "#A6AFBE", "#858FA0", "#4A5160"
ACCENT, ON_ACCENT, LIVE, ON_LIVE, OK = "#F2B54D", "#1E1606", "#FF6B5E", "#2A0B08", "#6AD3A0"

# Стили страницы: tiles — плитки как в программе (нажатое залито янтарным); outline — контуром (нажатое — янтарная
# рамка и значок); icons — крупные значки без плашек (нажатое — янтарный круг под значком).
STYLES = {
    "tiles": {"ground": GROUND, "btn": RAISED, "btn_line": RAISED2, "fg": TEXT, "info": PANEL, "info_line": RAISED2,
              "on": ACCENT, "on_fg": ON_ACCENT, "alert": LIVE, "alert_fg": ON_LIVE, "off_fg": OFF, "off": PANEL,
              "shape": "fill", "radius": 14, "label": 15, "icon": 34},
    "outline": {"ground": "#101318", "btn": "#101318", "btn_line": "#3A4252", "fg": "#D6DCE6", "info": "#101318",
                "info_line": "#2A303C", "on": ACCENT, "on_fg": ACCENT, "alert": LIVE, "alert_fg": LIVE, "off_fg": "#3E4554",
                "off": "#101318", "shape": "line", "radius": 18, "label": 14, "icon": 36},
    "icons": {"ground": GROUND, "btn": GROUND, "btn_line": "", "fg": TEXT, "info": GROUND, "info_line": "",
              "on": ACCENT, "on_fg": ON_ACCENT, "alert": LIVE, "alert_fg": ON_LIVE, "off_fg": OFF, "off": GROUND,
              "shape": "dot", "radius": 50, "label": 12.5, "icon": 40},
}
DEFAULT_STYLE = "tiles"


def _st(style: str) -> dict:
    return STYLES.get(style) or STYLES[DEFAULT_STYLE]


# значки окна программы (icons.js), 24 × 24, линия 1.8
ICONS = {
    "image": '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><circle cx="9" cy="10" r="1.7"/>'
             '<path d="M21 16l-5-5-9.5 8.5"/>',
    "blackout": '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><rect x="6.5" y="8" width="11" height="8" '
                'rx="1" fill="currentColor" stroke="none"/>',
    "activity": '<path d="M3 12h4l3-7 4 14 3-7h4"/>',
    "cup": '<path d="M4.5 9h12v5a5 5 0 0 1-5 5h-2a5 5 0 0 1-5-5z"/><path d="M16.5 10.5h1.3a2.3 2.3 0 0 1 0 4.6h-1.3"/>'
           '<path d="M8.5 3.5v2.5M12.5 3.5v2.5"/>',
    "slide": '<rect x="3" y="4.5" width="18" height="13" rx="2.5"/><path d="M10.5 8.5v5l4-2.5z"/><path d="M9 21h6"/>',
    "prev": '<path d="M14.5 6l-6 6 6 6"/>',
    "next": '<path d="M9.5 6l6 6-6 6"/>',
    "open": '<path d="M14 4.5h5.5V10M19.5 4.5l-8 8"/><path d="M18 14v4.5A1.5 1.5 0 0 1 16.5 20h-11A1.5 1.5 0 0 1 4 '
            '18.5v-11A1.5 1.5 0 0 1 5.5 6H10"/>',
    "volume": '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>',
    "volume-off": '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M16 9.5l5 5M21 9.5l-5 5"/>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    "mic-off": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3M4 4l16 16"/>',
}


# ---------------------------------------------------------------- текст
def _char_w(c: str) -> float:
    """Ширина знака в долях кегля (жирный гротеск, на глаз; с запасом)."""
    if c == " ":
        return 0.28
    if c in ".,:;·'!|ilI1":
        return 0.32
    if c in "—–":
        return 0.9
    if c.isdigit():
        return 0.58
    if c in "ЖШЩЮМWMШмшщжю":
        return 0.9
    if c.isupper():
        return 0.7
    return 0.58


def text_w(s: str, size: float) -> float:
    return sum(_char_w(c) for c in s) * size


def _wrap(words: list[str], size: float, width: float, lines: int) -> list[str] | None:
    out: list[str] = []
    cur = ""
    for w in words:
        cand = (cur + " " + w).strip()
        if text_w(cand, size) <= width:
            cur = cand
            continue
        if cur:
            out.append(cur)
        cur = w
        if text_w(w, size) > width or len(out) >= lines:
            return None
    if cur:
        out.append(cur)
    return out if len(out) <= lines else None


def fit(text: str, width: float, size: float, lines: int = 2, min_size: float | None = None) -> tuple[list[str], float]:
    """Текст в ширину width: по словам не больше lines строк; не влезло — мельче (до min_size); и так нет —
    последняя строка с многоточием. → (строки, кегль)."""
    text = " ".join((text or "").split())
    if not text:
        return [], size
    words = text.split(" ")
    s = size
    lo = min_size if min_size is not None else size * 0.62
    while s >= lo - 0.01:
        got = _wrap(words, s, width, lines)
        if got is not None:
            return got, s
        s -= max(0.5, size * 0.04)
    s = lo
    out: list[str] = []
    cur = ""
    for w in words:
        cand = (cur + " " + w).strip()
        if text_w(cand, s) <= width:
            cur = cand
            continue
        if len(out) == lines - 1:
            break
        if cur:
            out.append(cur)
        cur = w
    cur = cur or words[0]
    while cur and text_w(cur + "…", s) > width:
        cur = cur[:-1]
    out.append(cur.rstrip() + "…")
    return out[:lines], s


def _text(lines: list[str], x: float, y_mid: float, size: float, color: str, weight: int = 600,
          anchor: str = "middle", lh: float = 1.18) -> str:
    if not lines:
        return ""
    step = size * lh
    y0 = y_mid - step * (len(lines) - 1) / 2 + size * 0.35
    spans = "".join(f'<tspan x="{x:.1f}" y="{y0 + i * step:.1f}">{escape(t)}</tspan>' for i, t in enumerate(lines))
    return (f'<text font-family="{FONT}" font-size="{size:.1f}" font-weight="{weight}" fill="{color}" '
            f'text-anchor="{anchor}">{spans}</text>')


# ---------------------------------------------------------------- плитки
def _svg(w: float, h: float, body: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" width="{w:.0f}" '
            f'height="{h:.0f}">{body}</svg>')


def _plate(w: float, h: float, fill: str, line: str = "", rx: float = 14, lw: float = 1.2) -> str:
    stroke = f' stroke="{line}" stroke-width="{lw}"' if line else ""
    o = lw / 2 + 0.5
    return (f'<rect x="{o:.1f}" y="{o:.1f}" width="{w - 2 * o:.1f}" height="{h - 2 * o:.1f}" rx="{rx}" '
            f'fill="{fill}"{stroke}/>')


def _icon(name: str, cx: float, cy: float, size: float, color: str) -> str:
    k = size / 24
    return (f'<g transform="translate({cx - size / 2:.1f} {cy - size / 2:.1f}) scale({k:.3f})" fill="none" '
            f'stroke="{color}" color="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
            f'{ICONS[name]}</g>')


def width_of(cells: int) -> float:
    return cells * 100 + (cells - 1) * GAP


def _look(mode: str, S: dict) -> tuple[str, str, str, float]:
    """(заливка, цвет значка и подписи, рамка, толщина рамки) кнопки в этом стиле."""
    shape = S["shape"]
    if shape == "line":
        line = {"on": S["on"], "alert": S["alert"], "off": "#232833"}.get(mode, S["btn_line"])
        fg = {"on": S["on_fg"], "alert": S["alert_fg"], "off": S["off_fg"]}.get(mode, S["fg"])
        fill = {"on": "#2A2416", "alert": "#2C1716"}.get(mode, S["btn"])
        return fill, fg, line, 2.2 if mode in ("on", "alert") else 1.4
    if shape == "dot":
        fg = {"on": S["on_fg"], "alert": S["alert_fg"], "off": S["off_fg"]}.get(mode, S["fg"])
        return S["btn"], fg, "", 0
    fill = {"on": S["on"], "alert": S["alert"], "off": S["off"]}.get(mode, S["btn"])
    fg = {"on": S["on_fg"], "alert": S["alert_fg"], "off": S["off_fg"]}.get(mode, S["fg"])
    line = "" if mode in ("on", "alert") else (S["btn"] if mode == "off" else S["btn_line"])
    return fill, fg, line, 1.2


def button(icon: str, label: str, mode: str = "", sub: str = "", cells: int = 1, style: str = DEFAULT_STYLE) -> str:
    """Кнопка: значок и подпись под ним (не поверх). mode: "" — обычная, "on" — нажата (у учеников это), "off" —
    недоступна, "alert" — красная (выключен звук / микрофон). sub — вторая строка мельче (номер слайда)."""
    S = _st(style)
    w, h = width_of(cells), 100.0
    fill, fg, line, lw = _look(mode, S)
    parts = [_plate(w, h, fill, line, S["radius"] if S["shape"] != "dot" else 14, lw)]
    isz = S["icon"]
    if S["shape"] == "dot" and mode in ("on", "alert"):
        parts.append(f'<circle cx="{w / 2:.1f}" cy="{38 if label else 50}" r="{isz * 0.78:.1f}" '
                     f'fill="{S["on"] if mode == "on" else S["alert"]}"/>')
    label_fg = fg if S["shape"] != "dot" or mode not in ("on", "alert") else (S["on"] if mode == "on" else S["alert"])
    if label:
        parts.append(_icon(icon, w / 2, 38 if not sub else 33, isz, fg))
        lines, size = fit(label, w - 14, S["label"], lines=1, min_size=10)
        parts.append(_text(lines, w / 2, 78 if not sub else 70, size, label_fg))
        if sub:
            sl, ss = fit(sub, w - 14, 12, lines=1, min_size=9)
            parts.append(_text(sl, w / 2, 88, ss, label_fg, weight=500))
    else:
        parts.append(_icon(icon, w / 2, h / 2, isz + 8, fg))
    return _svg(w, h, "".join(parts))


def time_color(warn: bool, style: str = DEFAULT_STYLE) -> str:
    """Цвет крупного времени этапа: последняя минута — красным; «Контур» — янтарным."""
    return LIVE if warn else (ACCENT if _st(style)["shape"] == "line" else TEXT)


def timer_color(style: str = DEFAULT_STYLE) -> str:
    """Цвет отсчёта на кнопке «Перерыв» (она нажата)."""
    S = _st(style)
    return S["on"] if S["shape"] == "dot" else _look("on", S)[1]


def timer(label: str, cells: int = 1, style: str = DEFAULT_STYLE, draw_text: bool = True) -> str:
    """Кнопка «Перерыв», пока он идёт: значок и отсчёт крупно вместо подписи («08:12»). draw_text=False — низ
    пустой: отсчёт пишет Macro Deck подписью."""
    S = _st(style)
    w, h = width_of(cells), 100.0
    fill, fg, line, lw = _look("on", S)
    parts = [_plate(w, h, fill, line, S["radius"] if S["shape"] != "dot" else 14, lw)]
    if S["shape"] == "dot":
        parts.append(f'<circle cx="{w / 2:.1f}" cy="30" r="20" fill="{S["on"]}"/>')
        tcolor = S["on"]
    else:
        tcolor = fg
    parts.append(_icon("cup", w / 2, 30, 24, fg))
    if draw_text:
        lines, size = fit(label, w - 12, 30, lines=1, min_size=16)
        parts.append(_text(lines, w / 2, 70, size, tcolor, weight=700))
    return _svg(w, h, "".join(parts))


def stage(name: str, cells: int = 2, align: str = "left", style: str = DEFAULT_STYLE) -> str:
    """Прошедший или следующий этап: название бледнее, до трёх строк; без слов «предыдущий / следующий»."""
    S = _st(style)
    w, h = width_of(cells), 100.0
    parts = [_plate(w, h, S["info"], S["info_line"], S["radius"] if S["shape"] != "dot" else 14)]
    if name:
        lines, size = fit(name, w - 28, 15, lines=3, min_size=11)
        x, anchor = (16, "start") if align == "left" else (w - 16, "end")
        parts.append(_text(lines, x, h / 2, size, FAINT, weight=500, anchor=anchor))
    return _svg(w, h, "".join(parts))


def now(name: str, left: str, frac: float = 0.0, warn: bool = False, sub: str = "", cells: int = 3,
        style: str = DEFAULT_STYLE, draw_left: bool = True) -> str:
    """Идущий этап: название сверху (одна строка, мельче — если длинное), крупно сколько осталось, тонкая полоса
    хода этапа. Урок не идёт — название урока до трёх строк. draw_left=False — середина пустая: время пишет
    Macro Deck подписью (картинку он не меняет каждую секунду, подпись — меняет)."""
    S = _st(style)
    w, h = width_of(cells), 100.0
    parts = [_plate(w, h, S["info"], S["info_line"] or (S["btn_line"] if S["shape"] == "line" else ""),
                    S["radius"] if S["shape"] != "dot" else 14)]
    if left:
        nl, ns = fit(name, w - 32, 14, lines=1, min_size=10.5)
        parts.append(_text(nl, w / 2, 20, ns, DIM, weight=500))
        if draw_left:
            tl, ts = fit(left, w - 32, 48, lines=1, min_size=26)
            parts.append(_text(tl, w / 2, 56, ts, time_color(warn, style), weight=700))
        if sub:
            sl, ss = fit(sub, w - 32, 11, lines=1, min_size=9)
            parts.append(_text(sl, w / 2, 80, ss, FAINT, weight=500))
        bw = w - 44
        f = max(0.0, min(1.0, frac))
        parts.append(f'<rect x="22" y="89" width="{bw:.1f}" height="4" rx="2" fill="{RAISED2}"/>')
        if f > 0:
            parts.append(f'<rect x="22" y="89" width="{bw * f:.1f}" height="4" rx="2" fill="{LIVE if warn else ACCENT}"/>')
    else:
        lines, size = fit(name, w - 32, 18, lines=3, min_size=12)
        parts.append(_text(lines, w / 2, h / 2, size, TEXT, weight=600))
    return _svg(w, h, "".join(parts))


def data_url(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
