"""Окно таймера эфира: маленькое, по желанию поверх всех окон.

Шапка — узкая: название шаблона, «⋯» (все команды), «Закрепить» (поверх всех окон; нажата — закреплено),
«Свернуть», «Закрыть» (только с подтверждением: закрыть = завершить эфир). Под шапкой — плашка кнопок
экрана эфира: Фон, Зарядка, Перерыв. Ниже табло: что идёт, сколько осталось, что дальше; повестка — столько
строк, сколько помещается. Размер любой — от крошечного до во весь экран, текст подстраивается сам. Окно
перетаскивается за любое место табло. «Начать с блока…» — в «⋯», с вопросом (двойной щелчок по строке больше
не сдвигает расписание: промахнуться при перетаскивании легко).
"""
from __future__ import annotations

import ctypes
from datetime import datetime

from PySide6.QtCore import QByteArray, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton, QToolButton,
                               QVBoxLayout, QWidget, QWidgetAction)

from ..efir.model import DEMO_OFF, DEMO_ON, KIND_BREAK, KIND_EXERCISE, Agenda, Segment, agenda_at, fmt_left
from . import icons
from .efir_control import MODE_BREAK, MODE_EXERCISE, MODE_IDLE
from .frameless import HTCAPTION, HTCLIENT, FramelessWindow, StatusDot, user32
from .theme import mix, theme
from .widgets import IconButton, IconLabel, ThemedButton, accent_button, button

HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
HEADER_H = 30
STRIP_MIN_W, STRIP_MIN_H = 300, 170          # меньше — плашка кнопок прячется (команды — в «⋯»)


def _font(px: float, weight: QFont.Weight = QFont.Weight.Normal, display: bool = True, tnum: bool = False) -> QFont:
    f = QFont(theme.display_family if display else theme.ui_family)
    f.setPixelSize(max(6, int(px)))
    f.setWeight(weight)
    if tnum:
        try:
            f.setFeature(QFont.Tag("tnum"), 1)     # цифры одной ширины — время не «прыгает»
        except (AttributeError, TypeError):
            pass
    return f


def _elide(p: QPainter, text: str, width: float) -> str:
    return QFontMetricsF(p.font()).elidedText(text, Qt.TextElideMode.ElideRight, max(0.0, width))


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


ROW_MIN = 22.0         # строка повестки не ниже — иначе не прочитать
NOTE_H = 14.0          # строка «ещё N раньше / дальше»
CELL_MIN = 120.0       # клетка полосы не уже


def agenda_slice(n: int, cur: int, fit: int) -> tuple[int, int]:
    """Какие блоки повестки показывать — срез [a, b): все, если влезают; иначе одна строка до текущей и дальше
    будущие («сколько влазит, столько и показывать»)."""
    if n <= 0:
        return 0, 0
    if fit >= n:
        return 0, n
    fit = max(1, fit)
    cur = max(0, min(cur, n - 1))
    a = max(0, min(cur - 1, n - fit))
    return a, a + fit


def list_fit(height: float, n: int, row: float = ROW_MIN, note: float = NOTE_H) -> int:
    """Сколько строк повестки помещается по высоте (если не все — с одной строкой «ещё N»)."""
    if n <= 0:
        return 0
    if n * row <= height:
        return n
    return max(1, int((height - note) // row))


def board_mode(w: float, h: float) -> str:
    """Раскладка табло по размеру: strip — широкое низкое окно (повестка полосой справа), side — повестка
    списком справа, below — список под «сейчас», hero — только «что сейчас» (совсем маленькое окно)."""
    if w >= 640 and 60 <= h < 230 and w >= 2.6 * h:
        return "strip"
    if h < 150 or w < 260:
        return "hero"
    if w >= 560 and h >= 230:
        return "side"
    return "below"


class Board(QWidget):
    """Табло: рисуется целиком само — так текст масштабируется под любой размер окна."""

    def __init__(self, ctl) -> None:
        super().__init__()
        self.ctl = ctl
        self.setMinimumSize(60, 30)
        self._rows: list[tuple[QRectF, int]] = []
        self._list_rect = QRectF()
        self.mode = "hero"
        self.setMouseTracking(True)

    def drag_at(self, pt: QPointF) -> bool:
        return True                      # табло целиком — ручка окна (строки повестки — не кнопки)

    # ------------------------------------------------------------ рисование
    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        r = QRectF(self.rect())
        segs = self.ctl.segments()
        ag = agenda_at(segs, datetime.now())
        w, h = r.width(), r.height()
        self._rows, self._list_rect = [], QRectF()
        self.mode = board_mode(w, h) if segs else "hero"
        pad = _clamp(min(w, h) * 0.05, 4, 18)
        if self.mode == "side":
            lw = _clamp(w * 0.42, 240, 560)
            self._draw_hero(p, QRectF(r.left(), r.top(), w - lw, h), ag)
            self._draw_list(p, QRectF(r.right() - lw, r.top(), lw, h).adjusted(0, pad, -pad, -pad), segs, ag)
        elif self.mode == "below":
            hh = _clamp(h * 0.42, 90, 320)
            self._draw_hero(p, QRectF(r.left(), r.top(), w, hh), ag)
            self._draw_list(p, QRectF(r.left(), r.top() + hh, w, h - hh).adjusted(pad, 0, -pad, -pad), segs, ag)
        elif self.mode == "strip":
            hw = _clamp(w * 0.32, 200, 440)
            self._draw_hero(p, QRectF(r.left(), r.top(), hw, h), ag)
            self._draw_strip(p, QRectF(r.left() + hw, r.top(), w - hw, h).adjusted(0, pad, -pad, -pad), segs, ag)
        else:
            self._draw_hero(p, r, ag)
        # общий ход эфира — тонкая полоса по низу
        if ag.phase != "before" and segs:
            bar_h = 3 if h > 60 else 2
            p.fillRect(QRectF(r.left(), r.bottom() - bar_h, w, bar_h), mix(theme.c("bg"), theme.c("stroke_strong"), 1))
            p.fillRect(QRectF(r.left(), r.bottom() - bar_h, w * _clamp(ag.total_frac, 0, 1), bar_h),
                       theme.c("accent"))
        p.end()

    def _texts(self, ag: Agenda) -> tuple[str, str, str, str, QColor]:
        """(подпись, название, время, «дальше», цвет времени)."""
        text, dim, accent = theme.c("text"), theme.c("dim"), theme.c("accent")
        if ag.phase == "before":
            nxt = ag.next
            return ("ДО НАЧАЛА", nxt.activity.name if nxt else "", fmt_left(ag.left_s),
                    f"Старт в {ag.start:%H:%M}" if ag.start else "", accent)
        if ag.phase == "after" or ag.current is None:
            if not self.ctl.segments():
                return ("ЭФИР", "Нет эфира", "--:--", "", dim)
            return ("ЭФИР ЗАВЕРШЁН", "Повестка закончилась", "00:00",
                    f"Был до {ag.end:%H:%M}" if ag.end else "", dim)
        cur = ag.current
        nxt = (f"Дальше: {ag.next.activity.name} · в {ag.next.start:%H:%M} · {ag.next.activity.min} мин"
               if ag.next else f"Последний блок · конец в {cur.end:%H:%M}")
        color = theme.c("live") if ag.left_s <= 60 else text
        return ("СЕЙЧАС", cur.activity.name, fmt_left(ag.left_s), nxt, color)

    def _kind_color(self, seg: Segment | None) -> QColor:
        if seg is None:
            return theme.c("text")
        if seg.activity.kind == KIND_BREAK:
            return theme.c("accent")
        if seg.activity.kind == KIND_EXERCISE:
            return theme.c("role_explain")
        return theme.c("text")

    def _draw_hero(self, p: QPainter, r: QRectF, ag: Agenda) -> None:
        cap, name, tm, nxt, tcolor = self._texts(ag)
        w, h = r.width(), r.height()
        pad = _clamp(min(w, h) * 0.07, 4, 22)
        c = r.adjusted(pad, pad * 0.7, -pad, -pad * 0.8)
        cw, ch = c.width(), c.height()
        name_color = self._kind_color(ag.current) if ag.phase == "live" else theme.c("text")
        if ch < 58:                                            # одна строка: «Теория · 12:40»
            px = _clamp(ch * 0.62, 9, 40)
            p.setFont(_font(px, QFont.Weight.DemiBold, tnum=True))
            tw = QFontMetricsF(p.font()).horizontalAdvance(tm) + 4
            p.setPen(tcolor)
            p.drawText(QRectF(c.right() - tw, c.top(), tw, ch), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, tm)
            p.setFont(_font(px * 0.62, QFont.Weight.Medium))
            p.setPen(name_color)
            p.drawText(QRectF(c.left(), c.top(), cw - tw - 6, ch), Qt.AlignmentFlag.AlignVCenter,
                       _elide(p, name, cw - tw - 6))
            return
        if ch < 125:                                           # название + крупное время (+ «дальше»)
            show_next = ch >= 100 and bool(nxt)
            name_px = _clamp(ch * 0.17, 9, 18)
            next_px = name_px * 0.85
            avail = ch - name_px * 1.35 - (next_px * 1.5 if show_next else 0)
            time_px = _clamp(min(avail * 0.92, cw * 0.30), 12, 200)
            y = c.top()
            p.setFont(_font(name_px, QFont.Weight.DemiBold))
            p.setPen(name_color)
            p.drawText(QRectF(c.left(), y, cw, name_px * 1.35), Qt.AlignmentFlag.AlignVCenter, _elide(p, name, cw))
            y += name_px * 1.35
            p.setFont(_font(time_px, QFont.Weight.Bold, tnum=True))
            p.setPen(tcolor)
            p.drawText(QRectF(c.left(), y, cw, avail), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, tm)
            if show_next:
                p.setFont(_font(next_px, display=False))
                p.setPen(theme.c("dim"))
                p.drawText(QRectF(c.left(), c.bottom() - next_px * 1.5, cw, next_px * 1.5),
                           Qt.AlignmentFlag.AlignVCenter, _elide(p, nxt, cw))
            return
        # полное табло: подпись, название, время, полоса, «дальше», часы. Высоты — в «единицах»; если места
        # мало, сначала уходят часы, потом подпись — время и «дальше» видны всегда
        K = 3.8                                                # время = K единиц
        base = 2.1 + K * 1.15 + (1.0 if ag.phase == "live" else 0) + (1.5 if nxt else 0)
        show_cap = show_clock = True
        for show_cap, show_clock in ((True, True), (True, False), (False, False)):
            unit = min(ch / (base + 1.45 * show_cap + 1.45 * show_clock), cw / 11.0)
            if unit >= 13:
                break
        unit = _clamp(unit, 6, 70)
        cap_px, name_px, time_px = min(unit * 0.85, 20), unit * 1.45, unit * K
        next_px = min(unit * 0.95, 24)                         # подписи не растут без конца — длинное влезает
        time_px = min(time_px, cw * 0.32)
        y = c.top()
        if show_cap:
            p.setFont(_font(cap_px, QFont.Weight.DemiBold, display=False))
            p.setPen(theme.c("dim"))
            p.drawText(QRectF(c.left(), y, cw, cap_px * 1.5), Qt.AlignmentFlag.AlignVCenter, cap)
            if ag.phase == "live" and ag.current and ag.current.activity.demo in (DEMO_ON, DEMO_OFF):
                on = ag.current.activity.demo == DEMO_ON
                badge = "ДЕМОНСТРАЦИЯ ВКЛ" if on else "ДЕМОНСТРАЦИЯ ВЫКЛ"
                p.setFont(_font(cap_px * 0.92, QFont.Weight.DemiBold, display=False))
                bw = QFontMetricsF(p.font()).horizontalAdvance(badge) + cap_px * 1.6
                if bw < cw * 0.6:
                    br = QRectF(c.right() - bw, y, bw, cap_px * 1.5)
                    col = theme.c("ok") if on else theme.c("faint")
                    bg = QColor(col)
                    bg.setAlphaF(0.14)
                    path = QPainterPath()
                    path.addRoundedRect(br, br.height() / 2, br.height() / 2)
                    p.fillPath(path, bg)
                    p.setPen(col)
                    p.drawText(br, Qt.AlignmentFlag.AlignCenter, badge)
            y += unit * 1.45
        p.setFont(_font(name_px, QFont.Weight.Bold))
        p.setPen(name_color)
        p.drawText(QRectF(c.left(), y, cw, unit * 2.1), Qt.AlignmentFlag.AlignVCenter, _elide(p, name, cw))
        y += unit * 2.1
        p.setFont(_font(time_px, QFont.Weight.Bold, tnum=True))
        p.setPen(tcolor)
        time_h = unit * K * 1.15
        p.drawText(QRectF(c.left(), y, cw, time_h), Qt.AlignmentFlag.AlignVCenter, tm)
        y += time_h
        if ag.phase == "live":
            bh = max(3.0, unit * 0.3)
            bar = QRectF(c.left(), y + unit * 0.2, cw, bh)
            path = QPainterPath()
            path.addRoundedRect(bar, bh / 2, bh / 2)
            p.fillPath(path, mix(theme.c("card"), theme.c("stroke_strong"), 1))
            done = QRectF(bar.left(), bar.top(), bar.width() * _clamp(ag.frac, 0, 1), bh)
            path = QPainterPath()
            path.addRoundedRect(done, bh / 2, bh / 2)
            p.fillPath(path, theme.c("accent"))
            y += unit * 1.0
        if nxt:
            p.setFont(_font(next_px, display=False))
            p.setPen(theme.c("dim"))
            p.drawText(QRectF(c.left(), y, cw, unit * 1.5), Qt.AlignmentFlag.AlignVCenter, _elide(p, nxt, cw))
            y += unit * 1.5
        if show_clock:
            p.setFont(_font(next_px * 0.92, display=False, tnum=True))
            p.setPen(theme.c("faint"))
            row = QRectF(c.left(), max(y, c.bottom() - unit * 1.45), cw, unit * 1.45)
            span = f"Эфир {ag.start:%H:%M}–{ag.end:%H:%M}" if ag.start and ag.end else ""
            p.drawText(row, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, f"{datetime.now():%H:%M:%S}")
            p.drawText(row, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, span)

    @staticmethod
    def _focus_index(segs: list[Segment], ag: Agenda) -> int:
        return ag.index if ag.phase == "live" else (0 if ag.phase == "before" else len(segs) - 1)

    def _more(self, p: QPainter, rect: QRectF, text: str, align) -> None:
        p.setFont(_font(_clamp(rect.height() * 0.62, 10, 14), display=False))
        p.setPen(theme.c("faint"))
        p.drawText(rect, align | Qt.AlignmentFlag.AlignVCenter, text)

    def _draw_list(self, p: QPainter, r: QRectF, segs: list[Segment], ag: Agenda) -> None:
        """Повестка списком: столько строк, сколько влезает (все — если помещаются); не влезло — одна строка до
        текущей, дальше будущие, и одна строка «ещё N раньше · ещё N дальше»."""
        self._list_rect = QRectF(r)
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.fillPath(path, theme.c("card"))
        p.setPen(QPen(theme.c("stroke"), 1))
        p.drawPath(path)
        inner = r.adjusted(6, 6, -6, -6)
        n = len(segs)
        a, b = agenda_slice(n, self._focus_index(segs, ag), list_fit(inner.height(), n))
        note_h = NOTE_H if (a > 0 or b < n) else 0.0
        rh = _clamp((inner.height() - note_h) / max(1, b - a), ROW_MIN, 56)
        px = _clamp(rh * 0.42, 11, 22)
        y = inner.top()
        for s in segs[a:b]:
            row = QRectF(inner.left(), y, inner.width(), rh)
            self._rows.append((row, s.index))
            self._draw_row(p, row, s, ag, px)
            y += rh
        if note_h:
            more = " · ".join(x for x in (f"↑ ещё {a} раньше" if a else "", f"↓ ещё {n - b} дальше" if b < n else "") if x)
            self._more(p, QRectF(inner.left() + 10, y, inner.width() - 20, note_h), more, Qt.AlignmentFlag.AlignLeft)

    def _draw_row(self, p: QPainter, row: QRectF, s: Segment, ag: Agenda, px: float) -> None:
        rh = row.height()
        is_cur = ag.phase == "live" and s.index == ag.index
        is_next = ag.phase == "before" and s.index == 0
        past = (ag.phase == "live" and s.index < ag.index) or ag.phase == "after"
        if is_cur or is_next:
            hl = QPainterPath()
            hl.addRoundedRect(row.adjusted(0, 1, 0, -1), 8, 8)
            if is_cur:
                p.fillPath(hl, theme.c("accent_soft"))
                p.fillRect(QRectF(row.left(), row.top() + rh * 0.18, 4, rh * 0.64), theme.c("accent"))
            else:
                p.setPen(QPen(theme.c("accent"), 1.2))
                p.drawPath(hl)
        kind_col = {KIND_BREAK: theme.c("accent"), KIND_EXERCISE: theme.c("role_explain")}.get(s.activity.kind)
        x = row.left() + 12
        p.setFont(_font(px * 0.9, display=False, tnum=True))
        p.setPen(theme.c("faint") if past else theme.c("dim"))
        fm = QFontMetricsF(p.font())
        tw = fm.horizontalAdvance("00:00") + px * 0.7
        p.drawText(QRectF(x, row.top(), tw, rh), Qt.AlignmentFlag.AlignVCenter, f"{s.start:%H:%M}")
        x += tw
        mins = f"{s.activity.min} мин"
        mw = fm.horizontalAdvance(mins) + 10
        p.drawText(QRectF(row.right() - mw - 8, row.top(), mw, rh),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, mins)
        if s.activity.demo == DEMO_ON:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.c("ok") if not past else theme.c("faint"))
            d = _clamp(px * 0.22, 3, 5)
            p.drawEllipse(QPointF(row.right() - mw - 14, row.center().y()), d, d)
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.setFont(_font(px, QFont.Weight.Bold if is_cur else QFont.Weight.Medium, display=False))
        p.setPen(theme.c("faint") if past else (kind_col or theme.c("text")))
        name_w = row.right() - mw - 26 - x
        p.drawText(QRectF(x, row.top(), name_w, rh), Qt.AlignmentFlag.AlignVCenter, _elide(p, s.activity.name, name_w))

    def _draw_strip(self, p: QPainter, r: QRectF, segs: list[Segment], ag: Agenda) -> None:
        """Широкое низкое окно: блоки полосой слева направо — столько клеток, сколько влезает."""
        self._list_rect = QRectF(r)
        n, gap = len(segs), 6
        cells = max(1, int((r.width() + gap) // (CELL_MIN + gap)))
        a, b = agenda_slice(n, self._focus_index(segs, ag), cells)
        side = 30.0
        left, right = a > 0, b < n
        inner = r.adjusted(side if left else 0, 0, -(side if right else 0), 0)
        if left:
            self._more(p, QRectF(r.left(), r.top(), side, r.height()), f"‹ {a}", Qt.AlignmentFlag.AlignCenter)
        if right:
            self._more(p, QRectF(r.right() - side, r.top(), side, r.height()), f"{n - b} ›",
                       Qt.AlignmentFlag.AlignCenter)
        k = max(1, b - a)
        cw = min(260.0, (inner.width() - gap * (k - 1)) / k)
        x = inner.left()
        h = inner.height()
        px = _clamp(min(h * 0.2, cw * 0.11), 10, 24)
        for s in segs[a:b]:
            cell = QRectF(x, inner.top(), cw, h)
            self._rows.append((cell, s.index))
            is_cur = ag.phase == "live" and s.index == ag.index
            is_next = ag.phase == "before" and s.index == 0
            past = (ag.phase == "live" and s.index < ag.index) or ag.phase == "after"
            path = QPainterPath()
            path.addRoundedRect(cell, 10, 10)
            p.fillPath(path, theme.c("accent_soft") if is_cur else theme.c("card"))
            p.setPen(QPen(theme.c("accent") if (is_cur or is_next) else theme.c("stroke"), 1.4 if is_cur else 1))
            p.drawPath(path)
            if is_cur:
                p.fillRect(QRectF(cell.left() + 10, cell.top(), cell.width() - 20, 3), theme.c("accent"))
            c = cell.adjusted(10, h * 0.1, -10, -h * 0.1)
            kind_col = {KIND_BREAK: theme.c("accent"), KIND_EXERCISE: theme.c("role_explain")}.get(s.activity.kind)
            p.setFont(_font(px * 0.85, display=False, tnum=True))
            p.setPen(theme.c("faint") if past else theme.c("dim"))
            p.drawText(QRectF(c.left(), c.top(), c.width(), c.height() * 0.3), Qt.AlignmentFlag.AlignVCenter,
                       f"{s.start:%H:%M} · {s.activity.min} мин")
            p.setFont(_font(px * 1.15, QFont.Weight.Bold if is_cur else QFont.Weight.DemiBold, display=False))
            p.setPen(theme.c("faint") if past else (kind_col or theme.c("text")))
            name_r = QRectF(c.left(), c.top() + c.height() * 0.32, c.width(), c.height() * 0.68)
            p.drawText(name_r, Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                       self._fit_two_lines(p, s.activity.name, name_r))
            x += cw + gap

    @staticmethod
    def _fit_two_lines(p: QPainter, text: str, r: QRectF) -> str:
        """Название в две строки, а если и так не влезает — с многоточием."""
        fm = QFontMetricsF(p.font())
        if fm.boundingRect(r, int(Qt.TextFlag.TextWordWrap), text).height() <= r.height() + 1:
            return text
        while len(text) > 1:
            text = text[:-1]
            t = text.rstrip() + "…"
            if fm.boundingRect(r, int(Qt.TextFlag.TextWordWrap), t).height() <= r.height() + 1:
                return t
        return text


class TimerWindow(FramelessWindow):
    def __init__(self, ctl) -> None:
        super().__init__("Эфир", minimize=True, maximize=False)
        self.ctl = ctl
        self.settings = ctl.settings
        self._silent = False
        self.setObjectName("efirTimer")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(150, 70)
        tb = self.titlebar
        tb.setFixedHeight(HEADER_H)
        for b in (tb.btn_min, tb.btn_close):
            if b is not None:
                b.setFixedSize(34, HEADER_H)
        tb.btn_close.clicked.disconnect()
        tb.btn_close.clicked.connect(self.close)
        self.ic = IconLabel("radio", "accent", 14)
        tb.left.addWidget(self.ic)
        self.dot = StatusDot()
        self.dot.setToolTip("")
        self.btn_more = IconButton("more", "Все команды эфира", 16, box=28)
        self.btn_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more_menu = QMenu(self.btn_more)
        self.more_menu.aboutToShow.connect(self._fill_more)
        self.btn_more.setMenu(self.more_menu)
        self.btn_more.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        self.btn_pin = IconButton("pin", "Закрепить поверх всех окон", 15, box=28)
        self.btn_pin.setObjectName("pinBtn")
        self.btn_pin.setCheckable(True)
        self.btn_pin.toggled.connect(self._on_pin)
        tb.right.addWidget(self.dot)
        tb.right.addSpacing(4)
        tb.right.addWidget(self.btn_more)
        tb.right.addWidget(self.btn_pin)

        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.strip = QWidget()
        self.strip.setObjectName("efirStrip")
        sl = QHBoxLayout(self.strip)
        sl.setContentsMargins(10, 4, 10, 6)
        sl.setSpacing(6)
        self.btn_bg = ThemedButton("Фон", "monitor", "dim")
        self.btn_bg.setToolTip("Убрать зарядку или перерыв — на вкладке эфира снова фон (занавес)")
        self.btn_bg.clicked.connect(self.ctl.show_background)
        self.btn_ex = ThemedButton("Зарядка", "eye", "dim")
        self.btn_ex.clicked.connect(self._exercise_clicked)
        self.btn_brk = ThemedButton("Перерыв", "coffee", "dim")
        self.btn_brk.clicked.connect(self._break_clicked)
        self.btn_tab = ThemedButton("Открыть вкладку", "external", "accent")
        self.btn_tab.setToolTip("Вкладка эфира не открыта (или её закрыли) — открыть её в браузере. "
                                "Её и захватывайте в демонстрации")
        self.btn_tab.clicked.connect(self.ctl.open_tab)
        self.tab_lbl = QLabel()
        self.tab_lbl.setObjectName("efirTab")
        for b in (self.btn_bg, self.btn_ex, self.btn_brk, self.btn_tab):
            b.setFixedHeight(30)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            sl.addWidget(b)
        sl.addSpacing(6)
        sl.addWidget(self.tab_lbl, 1)
        lay.addWidget(self.strip)
        self.board = Board(ctl)
        lay.addWidget(self.board, 1)

        self._geo_timer = QTimer(self)
        self._geo_timer.setSingleShot(True)
        self._geo_timer.setInterval(600)
        self._geo_timer.timeout.connect(self.save_geometry)
        self._tick = QTimer(self)
        self._tick.setInterval(250)
        self._tick.timeout.connect(self._refresh)
        self._tick.start()
        ctl.screen_changed.connect(self._refresh)
        ctl.tab_changed.connect(self._refresh)
        ctl.live_changed.connect(self._refresh)
        theme.changed.connect(self._restyle)
        self._restyle()
        self.resize(440, 270)
        self._place_default()
        geo = getattr(self.settings, "efir_timer_geometry", "")
        if geo:
            self.restoreGeometry(QByteArray.fromBase64(geo.encode()))
        self.btn_pin.setChecked(bool(getattr(self.settings, "efir_pinned", True)))
        self._on_pin(self.btn_pin.isChecked())
        self._refresh()

    # ------------------------------------------------------------ вид
    def _restyle(self) -> None:
        t = theme
        self.setStyleSheet(f"""
QWidget#efirTimer {{ background: {t.css('bg')}; }}
QWidget#efirStrip {{ background: transparent; }}
QLabel#efirTab {{ color: {t.css('faint')}; font-size: 11px; }}
QToolButton#pinBtn {{ border-radius: 6px; }}
QToolButton#pinBtn:checked {{ background: {t.css('accent_soft')}; }}
""")
        self._on_pin(self.btn_pin.isChecked(), apply=False)
        self.board.update()

    def _place_default(self) -> None:
        scr = QGuiApplication.primaryScreen()
        if not scr:
            return
        a = scr.availableGeometry()
        self.move(a.right() - self.width() - 24, a.top() + max(24, (a.height() - self.height()) // 2))

    def show_and_raise(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._layout_for_size()
        if self.isVisible():
            self._geo_timer.start()

    def moveEvent(self, e) -> None:
        super().moveEvent(e)
        if self.isVisible():
            self._geo_timer.start()

    def _layout_for_size(self) -> None:
        w, h = self.width(), self.height()
        self.strip.setVisible(w >= STRIP_MIN_W and h >= STRIP_MIN_H)
        self.tab_lbl.setVisible(w >= 560)
        self.btn_tab.setText(" Открыть вкладку" if w >= 420 else " Вкладка")
        self.titlebar.title.setVisible(w >= 230)
        self.ic.setVisible(w >= 190)
        self.dot.setVisible(w >= 200)
        bw = 34 if w >= 220 else 26                      # в крошечном окне кнопки шапки уже
        for b in (self.titlebar.btn_min, self.titlebar.btn_close):
            if b is not None:
                b.setFixedWidth(bw)
        for b in (self.btn_more, self.btn_pin):
            b.setFixedWidth(28 if w >= 220 else 24)

    def save_geometry(self) -> None:
        if self.settings is not None:
            self.settings.efir_timer_geometry = bytes(self.saveGeometry().toBase64()).decode()
            self.settings.save()

    # ------------------------------------------------------------ закрепить
    def _on_pin(self, on: bool, apply: bool = True) -> None:
        self.btn_pin.set_icon("pin", "accent" if on else "dim")
        self.btn_pin.setToolTip("Закреплено поверх всех окон — нажмите, чтобы открепить" if on
                                else "Закрепить поверх всех окон")
        if apply:
            self._apply_topmost(on)
            if self.settings is not None and self.settings.efir_pinned != on:
                self.settings.efir_pinned = on
                self.settings.save()

    def _apply_topmost(self, on: bool) -> None:
        hwnd = int(self.winId())
        try:
            user32.SetWindowPos(hwnd, ctypes.c_void_p(HWND_TOPMOST if on else HWND_NOTOPMOST), 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        except (OSError, ctypes.ArgumentError, AttributeError):
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
            self.show()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._layout_for_size()
        QTimer.singleShot(0, lambda: self._apply_topmost(self.btn_pin.isChecked()))

    # ------------------------------------------------------------ перетаскивание за табло
    def _hit_test(self, msg) -> int:
        res = super()._hit_test(msg)
        if res != HTCLIENT:
            return res
        x = ctypes.c_short(msg.lParam & 0xFFFF).value
        y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
        from ctypes import wintypes
        pt = wintypes.POINT(x, y)
        user32.ScreenToClient(msg.hWnd, ctypes.byref(pt))
        dpr = self.devicePixelRatioF() or 1.0
        local = QPoint(int(pt.x / dpr), int(pt.y / dpr))
        child = self.childAt(local)
        if child is self.board and self.board.drag_at(QPointF(self.board.mapFrom(self, local))):
            return HTCAPTION
        if child is self.strip or child is self.tab_lbl:
            return HTCAPTION
        return HTCLIENT

    # ------------------------------------------------------------ состояние
    def _refresh(self) -> None:
        ctl = self.ctl
        w = ctl.live_webinar()
        self.titlebar.title.setText(w.title if w else "Эфир")
        self.setWindowTitle(f"Эфир — {w.title}" if w else "Эфир")
        text, token = ctl.tab_status()
        self.dot.set_token(token)
        self.dot.setToolTip(text + f"\n{ctl.url}")
        self.tab_lbl.setText(text)
        self.btn_tab.setVisible(ctl.clients <= 0)       # закрыли вкладку случайно — открыть прямо отсюда
        has_ex = bool(w and w.exercises)
        self.btn_ex.setVisible(has_ex)
        mode = ctl.mode
        self._set_active(self.btn_bg, mode == MODE_IDLE)
        self._set_active(self.btn_ex, mode == MODE_EXERCISE)
        self._set_active(self.btn_brk, mode == MODE_BREAK)
        if mode == MODE_EXERCISE:
            left = ctl.exercise_left()
            label = "Пауза" if ctl.ex_paused else (fmt_left(left) if left else "идёт")
            self.btn_ex.setText(f" Зарядка · {label}")
        else:
            self.btn_ex.setText(" Зарядка" + (" ▾" if w and len(w.exercises) > 1 else ""))
        if mode == MODE_BREAK:
            left = ctl.break_left()
            label = "пауза" if ctl.brk_left_paused is not None else (fmt_left(left) if left > 0 else "время вышло")
            self.btn_brk.setText(f" Перерыв · {label}")
        else:
            self.btn_brk.setText(" Перерыв")
        self.btn_bg.setText(" Фон")
        self.board.update()

    @staticmethod
    def _set_active(b: QPushButton, on: bool) -> None:
        if bool(b.property("accent")) != on:
            b.setProperty("accent", on)
            b._color = "on_accent" if on else "dim"
            b._refresh()
            b.style().unpolish(b)
            b.style().polish(b)

    # ------------------------------------------------------------ кнопки экрана
    def _exercise_clicked(self) -> None:
        ctl, w = self.ctl, self.ctl.live_webinar()
        if not w or not w.exercises:
            return
        if ctl.mode == MODE_EXERCISE:
            m = QMenu(self)
            self._exercise_running_actions(m)
            m.exec(self.btn_ex.mapToGlobal(QPoint(0, self.btn_ex.height())))
        elif len(w.exercises) == 1:
            ctl.start_exercise(0)
        else:
            m = QMenu(self)
            for i, ex in enumerate(w.exercises):
                m.addAction(icons.icon("play"), ex.title, lambda i=i: ctl.start_exercise(i))
            m.exec(self.btn_ex.mapToGlobal(QPoint(0, self.btn_ex.height())))

    def _exercise_running_actions(self, m: QMenu) -> None:
        ctl = self.ctl
        m.addAction(icons.icon("play" if ctl.ex_paused else "pause"), "Продолжить" if ctl.ex_paused else "Пауза",
                    ctl.exercise_pause)
        m.addAction(icons.icon("restart"), "Сначала", ctl.exercise_restart)
        m.addAction(icons.icon("stop"), "Убрать — снова фон", ctl.show_background)

    def _break_clicked(self) -> None:
        if self.ctl.mode == MODE_BREAK:
            m = QMenu(self)
            self._break_running_actions(m)
            m.exec(self.btn_brk.mapToGlobal(QPoint(0, self.btn_brk.height())))
        else:
            self._break_popup(self.btn_brk.mapToGlobal(QPoint(0, self.btn_brk.height())))

    def _break_running_actions(self, m: QMenu) -> None:
        ctl = self.ctl
        m.addAction(icons.icon("plus"), "+1 минута", lambda: ctl.break_adjust(60))
        m.addAction(icons.icon("minus"), "−1 минута", lambda: ctl.break_adjust(-60))
        paused = ctl.brk_left_paused is not None
        m.addAction(icons.icon("play" if paused else "pause"), "Продолжить отсчёт" if paused else "Пауза отсчёта",
                    ctl.break_pause)
        m.addAction(icons.icon("restart"), "Заново", ctl.break_restart)
        m.addAction(icons.icon("stop"), "Убрать — снова фон", ctl.show_background)

    def _break_popup(self, pos: QPoint) -> None:
        m = self._break_menu()
        if m is not None:
            m.exec(pos)

    def _break_menu(self) -> QMenu | None:
        """«Перерыв»: кнопки минут — плановые первыми, без поля ввода (оно забирало фокус и колесо)."""
        w = self.ctl.live_webinar()
        if not w:
            return None
        m = QMenu(self)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(12, 10, 12, 10)
        bl.setSpacing(8)
        head = QLabel("Перерыв — на сколько минут")
        head.setStyleSheet(f"font-weight: 600; color: {theme.css('text')};")
        bl.addWidget(head)
        row = QHBoxLayout()
        row.setSpacing(6)
        planned = max(1, int(w.break_min or 10))
        for n in [planned] + [x for x in (5, 10, 15, 20) if x != planned]:
            b = accent_button(f" {n} мин", "play") if n == planned else button(f"{n} мин")
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setFixedHeight(32)
            b.setToolTip("По плану урока" if n == planned else f"Перерыв {n} мин")
            b.clicked.connect(lambda _=False, n=n: (self.ctl.start_break(n), m.close()))
            row.addWidget(b)
        bl.addLayout(row)
        tip = QLabel("Во время перерыва здесь же: ±1 минута, пауза, «Снова фон».")
        tip.setStyleSheet(f"color: {theme.css('dim')}; font-size: 12px;")
        bl.addWidget(tip)
        act = QWidgetAction(m)
        act.setDefaultWidget(box)
        m.addAction(act)
        return m

    def _fill_more(self) -> None:
        ctl, m = self.ctl, self.more_menu
        m.clear()
        w = ctl.live_webinar()
        m.addAction(icons.icon("monitor"), "Фон (занавес)" + ("  ✓" if ctl.mode == MODE_IDLE else ""),
                    ctl.show_background)
        if w and w.exercises:
            if ctl.mode == MODE_EXERCISE:
                self._exercise_running_actions(m.addMenu(icons.icon("eye"), "Зарядка идёт"))
            for i, ex in enumerate(w.exercises):
                m.addAction(icons.icon("eye"), f"Зарядка: {ex.title}", lambda i=i: ctl.start_exercise(i))
        if ctl.mode == MODE_BREAK:
            self._break_running_actions(m.addMenu(icons.icon("coffee"), "Перерыв идёт"))
        elif w:
            m.addAction(icons.icon("coffee"), f"Перерыв {w.break_min} мин…",
                        lambda: self._break_popup(self.mapToGlobal(QPoint(10, HEADER_H))))
        m.addSeparator()
        m.addAction(icons.icon("external"), "Открыть вкладку эфира в браузере", ctl.open_tab)
        m.addAction(icons.icon("copy"), f"Скопировать адрес вкладки ({ctl.url})", ctl.copy_url)
        m.addSeparator()
        ag = ctl.agenda()
        if ag.phase == "before":
            m.addAction(icons.icon("play"), "Начать эфир сейчас (с первого блока)", lambda: ctl.start_now(0))
        elif ag.phase == "live":
            m.addAction(icons.icon("clock"), f"Начать этот этап сейчас: «{ag.current.activity.name}»",
                        lambda: ctl.start_now(None))
        else:
            m.addAction(icons.icon("play"), "Начать эфир заново сейчас", lambda: ctl.start_now(0))
        if w:
            m.addAction(icons.icon("restart"), "Изменить начало…", self._change_start)
            sub = m.addMenu(icons.icon("next"), "Начать с блока…")
            for s in ctl.segments():
                sub.addAction(f"{s.activity.name} · {s.activity.min} мин", lambda i=s.index: self._start_from(i))
        m.addSeparator()
        if w:
            m.addAction(icons.icon("pencil"), "Изменить оформление урока…" if w.lesson_id else "Изменить шаблон…",
                        ctl.edit_live)
        m.addAction(icons.icon("layers"), "Шаблоны вебинаров…", ctl.show_window)
        m.addSeparator()
        m.addAction(icons.icon("x"), "Завершить эфир…", self.close)

    def _change_start(self) -> None:
        from .efir_start import ask_start
        w = self.ctl.live_webinar()
        if w is None:
            return
        v = ask_start(self, self.mapToGlobal(QPoint(10, HEADER_H)), last=w.start, title="Начало эфира")
        if v is not None:
            self.ctl.set_start(v)

    def _start_from(self, index: int) -> None:
        segs = self.ctl.segments()
        if not 0 <= index < len(segs):
            return
        r = QMessageBox.question(self, "Начать с блока", f"Эфир пойдёт с блока «{segs[index].activity.name}» — "
                                 "время сдвинется на сейчас. Так?")
        if r == QMessageBox.StandardButton.Yes:
            self.ctl.start_now(index)

    # ------------------------------------------------------------ закрыть
    def close_silently(self) -> None:
        self._silent = True
        self.close()

    def closeEvent(self, e) -> None:
        w0 = self.ctl.live_webinar()
        if not self._silent and w0 is not None and w0.lesson_id:
            # идёт урок: × только прячет мини-таймер (урок, перерыв и экран учеников — как были); снова — с экрана
            # урока: «Урок идёт ▾ → Мини-таймер»
            e.ignore()
            self.save_geometry()
            self.hide()
            return
        if not self._silent:
            w = self.ctl.live_webinar()
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle("Завершить эфир?")
            box.setText(f"Закрыть таймер{f' «{w.title}»' if w else ''}?")
            box.setInformativeText("Эфир завершится: отсчёт остановится, на вкладке эфира останется фон. "
                                   "Шаблон никуда не денется. Чтобы просто убрать окно, сверните его.")
            yes = box.addButton("Завершить эфир", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not yes:
                e.ignore()
                return
        self.save_geometry()
        self._tick.stop()
        super().closeEvent(e)
        if not self._silent:
            self._silent = True
            if self.ctl.timer_window is self:
                self.ctl.timer_window = None
            self.ctl.stop_live()
