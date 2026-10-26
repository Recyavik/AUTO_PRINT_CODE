"""Напоминания на мониторе управления: карточки поверх всех окон в правом верхнем углу.

Карточка не забирает фокус (печать и демонстрация продолжаются) и висит, пока её не уберут:
ведущий может закончить мысль и только потом перейти к зарядке. Сверху — что происходит
(«СКОРО НАЧНЁТСЯ · через 00:59», «ИДЁТ СЕЙЧАС · осталось 02:10», «ВРЕМЯ ВЫШЛО»). Кнопки:
  «▶ Показать видео» / «▶ Показать картинку» / «☕ Начать перерыв» — только если активности есть что
      показать на экране демонстрации (видео гимнастики, картинка, заставка перерыва);
  «⏰ Напомнить через минуту» — спрятать и показать снова через минуту;
  «✓ Понятно»                 — убрать напоминание.
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
WIDTH = 360
GAP = 8
SNOOZE_MS = 60_000      # «Через 1 мин»

def phase_style(phase: str) -> tuple[str, str, str | None]:
    """Фаза карточки → (фон, рамка, цвет полоски и надписи; None — цвет активности) — в цветах текущей темы.
    «Скоро» — холодный сине-фиолетовый и янтарь: предстоит, можно закончить мысль;
    «сейчас» — фиолетовый: идёт; «время вышло» — с красным оттенком."""
    bg, border = {"soon": style.CARD_SOON, "now": style.CARD_NOW, "over": style.CARD_OVER}[phase]
    return bg, border, {"soon": style.AMBER, "over": style.RED}.get(phase)

def parse_pos(text: str) -> QPoint | None:
    """Позиция столбика из настроек: «x,y» → QPoint; пусто или мусор — None (правый верхний угол)."""
    try:
        x, y = (int(v) for v in text.split(","))
        return QPoint(x, y)
    except ValueError:
        return None


class Card(QWidget):
    """Одно напоминание. heads_up=True — «через N мин», иначе — «сейчас».
    action — надпись кнопки действия («▶ Показать видео», «☕ Начать перерыв»); пусто — кнопки нет."""
    acked = Signal(object)          # «✓ Понятно» — сама карточка
    snoozed = Signal(object)        # «⏰ Напомнить через минуту»
    next = Signal(object)           # кнопка действия: показать файл активности или начать перерыв
    dropped = Signal(object)        # карточку перетащили и отпустили

    def __init__(self, seg: Segment, heads_up: bool, clock: Callable[[], datetime], action: str = "") -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.seg, self.heads_up, self.clock = seg, heads_up, clock
        a = seg.activity
        self.phase = ""

        frame = QFrame(self)
        frame.setObjectName("notecard")
        self.frame = frame
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
        lay.addLayout(top)

        lay.addSpacing(4)
        if action:                  # главное — что сделать сейчас: отдельной строкой во всю ширину
            act = QPushButton(action, objectName="ok")
            act.setToolTip("Заставка перерыва — на экран демонстрации" if a.breaks
                           else "На экран демонстрации — зрителям")
            act.setCursor(Qt.CursorShape.ArrowCursor)
            act.clicked.connect(lambda: self.next.emit(self))
            lay.addWidget(act)
        row = QHBoxLayout()
        snooze = QPushButton("⏰ Напомнить через минуту")
        snooze.setToolTip("Спрятать карточку и показать её снова через минуту")
        snooze.clicked.connect(lambda: self.snoozed.emit(self))
        close = QPushButton("✓ Понятно")
        close.setToolTip("Убрать напоминание")
        close.clicked.connect(lambda: self.acked.emit(self))
        for w in (snooze, close):
            w.setCursor(Qt.CursorShape.ArrowCursor)
        row.addWidget(snooze)
        row.addStretch(1)
        row.addWidget(close)
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

    def _apply_phase(self, phase: str) -> None:
        """Оттенок карточки по фазе: предстоит / идёт / время вышло."""
        if phase == self.phase:
            return
        self.phase = phase
        bg, border, accent = phase_style(phase)
        color = accent or style.KIND_COLOR.get(self.seg.activity.kind, style.BRAND_BRIGHT)
        self.frame.setStyleSheet(f"""
            QFrame#notecard {{ background: {bg}; border: 1px solid {border};
              border-left: 5px solid {color}; border-radius: 12px; }}
            QLabel {{ background: transparent; color: {style.INK}; }}
            QLabel#label {{ color: {color}; font-weight: 700; letter-spacing: 1px; font-size: 7.5pt; }}
            QLabel#name {{ font-size: 12.5pt; font-weight: 700; }}
            QLabel#sub {{ color: {style.MUTED}; font-size: 8.5pt; }}
            QLabel#left {{ color: {color}; font-size: 13pt; font-weight: 800; }}
            QPushButton {{ background: {style.TINT2}; border: 1px solid {border}; border-radius: 7px;
              padding: 3px 9px; color: {style.INK}; font-weight: 600; font-size: 9pt; }}
            QPushButton:hover {{ border-color: {style.BRAND_BRIGHT}; }}
            QPushButton#ok {{ background: {style.BRAND}; border-color: {style.BRAND}; color: {style.ON_BRAND};
              padding: 5px 9px; font-size: 10pt; }}
            QPushButton#ok:hover {{ background: {style.BRAND_BRIGHT}; }}
        """)

    def restyle(self) -> None:
        """Тему сменили — перекрасить."""
        self.phase = ""
        self.refresh()

    def refresh(self) -> None:
        now = self.clock()
        if now < self.seg.start:
            self._apply_phase("soon")
            self.label.setText("СКОРО НАЧНЁТСЯ")
            self.left.setText(f"через {fmt_left(self.seg.start - now)}")
        elif now < self.seg.end:
            self._apply_phase("now")
            self.label.setText("ИДЁТ СЕЙЧАС")
            self.left.setText(f"осталось {fmt_left(self.seg.end - now)}")
        else:
            self._apply_phase("over")
            self.label.setText("ВРЕМЯ ВЫШЛО")
            self.left.setText("закончилась")


class Notifier:
    """Столбик карточек в правом верхнем углу монитора управления."""

    def __init__(self, screen_of: Callable[[], QScreen], clock: Callable[[], datetime]) -> None:
        self.screen_of, self.clock = screen_of, clock
        # где стоит столбик: смещение левого верхнего угла от угла монитора управления; None — справа вверху
        self.anchor: QPoint | None = None
        self.on_moved: Callable[[QPoint | None], None] = lambda anchor: None
        self.cards: list[Card] = []
        # показывать ли карточку (окно таймера: идёт перерыв — у ведущего пульт, карточка «сейчас» не нужна)
        self.accepts: Callable[[Segment, bool], bool] = lambda seg, heads_up: True
        self.on_next: Callable[[Segment], None] = lambda seg: None
        # надпись кнопки действия для активности («▶ Показать видео»…); пусто — показать нечего, кнопки нет
        self.action_of: Callable[[Segment], str] = lambda seg: ""
        self._snoozed: list[QTimer] = []

    def show(self, seg: Segment, heads_up: bool) -> Card | None:
        # о блоке достаточно одной карточки: «сейчас» заменяет «скоро»
        for c in [c for c in self.cards if c.seg.index == seg.index]:
            self.close(c)
        if not self.accepts(seg, heads_up):
            return None
        card = Card(seg, heads_up, self.clock, self.action_of(seg))
        card.acked.connect(self.close)
        card.snoozed.connect(self.snooze)
        card.next.connect(self._next)
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
