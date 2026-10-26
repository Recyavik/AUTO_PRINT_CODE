"""Напоминания на мониторе управления: карточки поверх всех окон в правом верхнем углу.

Карточка не забирает фокус (печать и демонстрация продолжаются) и висит, пока её не уберут:
ведущий может закончить мысль и только потом перейти к зарядке. Кнопки:
  «⏰ Через 1 мин» — спрятать и напомнить снова через минуту;
  «Закрыть»       — убрать напоминание;
  «Далее ▶»       — начать активность: её файл (видео гимнастики, картинка) — на экран демонстрации.
Несколько карточек — столбиком. Карточку можно перетащить мышью (за любое место, кроме кнопок):
столбик переедет туда, позиция запоминается относительно монитора управления.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QScreen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..model import DEMO_TEXT, Segment, fmt_left
from . import style

MARGIN = 16
WIDTH = 330
GAP = 8
SNOOZE_MS = 60_000      # «Через 1 мин»


def parse_pos(text: str) -> QPoint | None:
    """Позиция столбика из настроек: «x,y» → QPoint; пусто или мусор — None (правый верхний угол)."""
    try:
        x, y = (int(v) for v in text.split(","))
        return QPoint(x, y)
    except ValueError:
        return None


class Card(QWidget):
    """Одно напоминание. heads_up=True — «через N мин», иначе — «сейчас»."""
    acked = Signal(object)          # «Закрыть» — сама карточка
    snoozed = Signal(object)        # «Через 1 мин»
    next = Signal(object)           # «Далее ▶»
    hide_break = Signal()           # «Убрать заставку» (только у перерыва)
    dropped = Signal(object)        # карточку перетащили и отпустили

    def __init__(self, seg: Segment, heads_up: bool, clock: Callable[[], datetime]) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.seg, self.heads_up, self.clock = seg, heads_up, clock
        a = seg.activity
        color = style.KIND_COLOR.get(a.kind, style.BRAND_BRIGHT)

        frame = QFrame(self)
        frame.setObjectName("notecard")
        frame.setStyleSheet(f"""
            QFrame#notecard {{ background: {style.SURFACE2}; border: 1px solid {style.LINE};
              border-left: 5px solid {color}; border-radius: 12px; }}
            QLabel {{ background: transparent; color: {style.INK}; }}
            QLabel#label {{ color: {color}; font-weight: 700; letter-spacing: 1px; font-size: 7.5pt; }}
            QLabel#name {{ font-size: 12.5pt; font-weight: 700; }}
            QLabel#sub {{ color: {style.MUTED}; font-size: 8.5pt; }}
            QLabel#left {{ color: {color}; font-size: 13pt; font-weight: 800; }}
            QPushButton {{ background: rgba(255,255,255,0.06); border: 1px solid {style.LINE}; border-radius: 7px;
              padding: 3px 9px; color: {style.INK}; font-weight: 600; font-size: 9pt; }}
            QPushButton:hover {{ border-color: {style.BRAND}; }}
            QPushButton#ok {{ background: {style.BRAND}; border-color: {style.BRAND}; color: white; }}
            QPushButton#ok:hover {{ background: {style.BRAND_BRIGHT}; }}
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 8, 10, 9)
        lay.setSpacing(2)
        frame.setCursor(Qt.CursorShape.OpenHandCursor)   # подсказка: карточку можно перетащить
        self._drag_from = None

        self.label = QLabel(objectName="label")
        self.name = QLabel(a.name, objectName="name")
        self.name.setWordWrap(True)
        demo = DEMO_TEXT.get(a.demo, "")
        self.sub = QLabel(f"{seg.start:%H:%M}–{seg.end:%H:%M} · {a.min} мин" + (f" · {demo}" if demo else ""),
                          objectName="sub")
        self.left = QLabel(objectName="left")
        lay.addWidget(self.label)
        lay.addWidget(self.name)
        lay.addWidget(self.sub)

        top = QHBoxLayout()
        top.addWidget(self.left)
        top.addStretch(1)
        if a.breaks and not heads_up:
            b = QPushButton("Убрать заставку")
            b.setCursor(Qt.CursorShape.ArrowCursor)
            b.setToolTip("Убрать заставку перерыва с экрана демонстрации")
            b.clicked.connect(self.hide_break)
            top.addWidget(b)
        lay.addLayout(top)

        row = QHBoxLayout()
        snooze = QPushButton("⏰ 1 мин")
        snooze.setToolTip("Спрятать и напомнить снова через минуту")
        snooze.clicked.connect(lambda: self.snoozed.emit(self))
        close = QPushButton("Закрыть")
        close.setToolTip("Убрать напоминание")
        close.clicked.connect(lambda: self.acked.emit(self))
        nxt = QPushButton("Далее ▶", objectName="ok")
        nxt.setToolTip("Начать: файл активности (видео гимнастики, картинка) — на экран демонстрации"
                       if not a.breaks else "Начать перерыв: заставка — на экран демонстрации")
        nxt.clicked.connect(lambda: self.next.emit(self))
        for w in (snooze, close, nxt):
            w.setCursor(Qt.CursorShape.ArrowCursor)
        for w in (snooze, close):
            row.addWidget(w)
        row.addStretch(1)
        row.addWidget(nxt)
        lay.addLayout(row)

        self.setFixedWidth(WIDTH)
        self.refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(250)

    # ---- перетаскивание: кнопки забирают свои щелчки сами, остальная карточка — «ручка»
    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_from = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e) -> None:
        if self._drag_from is not None:
            self.move(e.globalPosition().toPoint() - self._drag_from)

    def mouseReleaseEvent(self, e) -> None:
        if self._drag_from is not None:
            self._drag_from = None
            self.dropped.emit(self)

    def refresh(self) -> None:
        now = self.clock()
        if self.heads_up and now < self.seg.start:
            self.label.setText("СКОРО")
            self.left.setText(f"через {fmt_left(self.seg.start - now)}")
        elif now < self.seg.end:
            self.label.setText("СЕЙЧАС · ПОРА ПЕРЕХОДИТЬ" if not self.heads_up else "НАЧАЛОСЬ")
            self.left.setText(f"осталось {fmt_left(self.seg.end - now)}")
        else:
            self.label.setText("ВРЕМЯ ВЫШЛО")
            self.left.setText("00:00")


class Notifier:
    """Столбик карточек в правом верхнем углу монитора управления."""

    def __init__(self, screen_of: Callable[[], QScreen], clock: Callable[[], datetime]) -> None:
        self.screen_of, self.clock = screen_of, clock
        # где стоит столбик: смещение левого верхнего угла от угла монитора управления; None — справа вверху
        self.anchor: QPoint | None = None
        self.on_moved: Callable[[QPoint | None], None] = lambda anchor: None
        self.cards: list[Card] = []
        self.on_hide_break: Callable[[], None] = lambda: None
        self.on_next: Callable[[Segment], None] = lambda seg: None
        self._snoozed: list[QTimer] = []

    def show(self, seg: Segment, heads_up: bool) -> Card:
        # о блоке достаточно одной карточки: «сейчас» заменяет «скоро»
        for c in [c for c in self.cards if c.seg.index == seg.index]:
            self.close(c)
        card = Card(seg, heads_up, self.clock)
        card.acked.connect(self.close)
        card.snoozed.connect(self.snooze)
        card.next.connect(self._next)
        card.hide_break.connect(lambda: self.on_hide_break())
        card.dropped.connect(self._dropped)
        self.cards.append(card)
        card.adjustSize()
        card.show()
        self.layout()
        return card

    def close(self, card: Card) -> None:
        if card in self.cards:
            self.cards.remove(card)
        card.close()
        card.deleteLater()
        self.layout()

    def snooze(self, card: Card) -> None:
        """Спрятать и через минуту показать снова (как «сейчас» — пора переходить)."""
        seg = card.seg
        self.close(card)
        t = QTimer()
        t.setSingleShot(True)
        t.timeout.connect(lambda: (self._snoozed.remove(t), self.show(seg, False)))
        t.start(SNOOZE_MS)
        self._snoozed.append(t)

    def _dropped(self, card: Card) -> None:
        """Карточку отпустили: столбик переезжает так, чтобы она осталась там, где её бросили."""
        area = self.screen_of().availableGeometry()
        above = sum(c.height() + GAP for c in self.cards[:self.cards.index(card)]) if card in self.cards else 0
        self.anchor = QPoint(card.x() - area.left(), card.y() - above - area.top())
        self.layout()
        self.on_moved(self.anchor)

    def _next(self, card: Card) -> None:
        seg = card.seg
        self.close(card)
        self.on_next(seg)

    def clear(self) -> None:
        for t in self._snoozed:
            t.stop()
        self._snoozed.clear()
        for c in list(self.cards):
            self.close(c)

    def layout(self) -> None:
        area = self.screen_of().availableGeometry()
        for c in self.cards:
            c.adjustSize()
        if self.anchor is None:
            x, y = area.right() - WIDTH - MARGIN, area.top() + MARGIN
        else:
            # не дать уехать за край: монитор могли сменить или поменять разрешение
            total = sum(c.height() + GAP for c in self.cards) or 1
            x = min(max(area.left(), area.left() + self.anchor.x()), area.right() - WIDTH)
            y = min(max(area.top(), area.top() + self.anchor.y()), max(area.top(), area.bottom() - total))
        for c in self.cards:
            if c.screen() != self.screen_of():
                c.setScreen(self.screen_of())
            c.move(QPoint(x, y))
            y += c.height() + GAP
