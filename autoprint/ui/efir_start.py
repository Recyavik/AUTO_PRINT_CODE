"""Начало эфира задаётся при запуске, а не в шаблоне: «Сейчас», ближайшие :00/:30, прошлое время или своё.

Ведущий заходит за несколько минут до урока, выбирает начало — таймер считает «до начала», потом идёт по
расписанию. Шаблон хранит только прошлое время старта, чтобы подставить его в следующий раз.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QPoint, QTime, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QTimeEdit, QVBoxLayout, QWidget, QWidgetAction

from ..efir.model import parse_hhmm
from .theme import theme
from .widgets import accent_button, button


def quick_times(now: datetime, n: int = 2) -> list[str]:
    """Ближайшие отметки :00 и :30 после текущей минуты (17:12 → 17:30, 18:00)."""
    t = now.replace(second=0, microsecond=0)
    t += timedelta(minutes=30 - t.minute % 30)
    out = []
    for _ in range(n):
        out.append(f"{t:%H:%M}")
        t += timedelta(minutes=30)
    return out


class StartPicker(QWidget):
    """Выбор начала: chosen("") — сейчас, chosen("ЧЧ:ММ") — в это время."""
    chosen = Signal(str)

    def __init__(self, last: str = "", now: datetime | None = None, title: str = "Начало эфира") -> None:
        super().__init__()
        now = now or datetime.now()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(8)
        head = QLabel(title)
        head.setStyleSheet(f"font-weight: 600; color: {theme.css('text')};")
        lay.addWidget(head)
        self.now_btn = accent_button(" Сейчас", "play")
        self.now_btn.setFixedHeight(32)
        self.now_btn.setToolTip("Эфир начинается с этой минуты")
        self.now_btn.clicked.connect(lambda: self.chosen.emit(""))
        lay.addWidget(self.now_btn)
        times = quick_times(now)
        hm = parse_hhmm(last)
        last = f"{hm[0]:02d}:{hm[1]:02d}" if hm else ""
        if last and last not in times:
            times.append(last)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.quick_buttons: list[QPushButton] = []
        for t in times:
            b = button(t)
            b.setFixedHeight(30)
            b.setToolTip("Прошлое время старта этого шаблона" if t == last else "Начало в это время")
            b.clicked.connect(lambda _=False, t=t: self.chosen.emit(t))
            row.addWidget(b)
            self.quick_buttons.append(b)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        first = parse_hhmm(last or times[0]) or (now.hour, now.minute)
        self.time_edit.setTime(QTime(first[0], first[1]))
        self.time_edit.setFixedWidth(86)
        self.at_btn = button(" Начать в это время", "clock")
        self.at_btn.setFixedHeight(30)
        self.at_btn.clicked.connect(lambda: self.chosen.emit(self.time_edit.time().toString("HH:mm")))
        row2.addWidget(self.time_edit)
        row2.addWidget(self.at_btn, 1)
        lay.addLayout(row2)
        hint = QLabel("До начала таймер считает «до начала», потом идёт по расписанию.")
        hint.setObjectName("dim")
        hint.setWordWrap(True)
        lay.addWidget(hint)


def ask_start(parent: QWidget, pos: QPoint, last: str = "", title: str = "Начало эфира") -> str | None:
    """Всплывающее окно у pos. "" — сейчас, "ЧЧ:ММ" — в это время, None — передумали."""
    m = QMenu(parent)
    picker = StartPicker(last, title=title)
    picker.setMinimumWidth(280)
    result: list[str] = []

    def pick(value: str) -> None:
        result.append(value)
        m.close()
    picker.chosen.connect(pick)
    act = QWidgetAction(m)
    act.setDefaultWidget(picker)
    m.addAction(act)
    QTimer.singleShot(0, picker.now_btn.setFocus)
    m.exec(pos)
    m.deleteLater()
    return result[0] if result else None
