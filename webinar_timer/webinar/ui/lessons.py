"""Уроки на табло: панель урока в повестке и полоса всего эфира с разбивкой на уроки и перерывы.

Урок — подряд идущие блоки между перерывами. Продолжительность урока (академический час 45 мин, обычный 60,
своя или без предела) задают в ⚙ Настройки; у шаблона может быть своя — в его редакторе. В повестке каждый урок — своя панель с заголовком «УРОК 1 · 11:00–11:45 ·
45 мин», перерывы стоят между панелями. Полоса сверху показывает весь эфир: уроки, перерывы, прошедшее время
и отметку «сейчас».
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QSpinBox, QVBoxLayout, QWidget

from ..model import Segment, lessons
from . import style


def lesson_minutes(segs: list[Segment]) -> int:
    return sum(s.activity.min for s in segs)


class LessonLengthEdit(QWidget):
    """Продолжительность урока: академический час, обычный, своя (минуты) или без предела.
    follow — значение из общих настроек: тогда первый вариант «Как в настройках» (value() → None)."""
    changed = Signal(object)
    PRESETS = [("Академический час · 45 мин", 45), ("Обычный час · 60 мин", 60)]

    def __init__(self, follow: int | None = None) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.mode = QComboBox()
        if follow is not None:
            self.mode.addItem("Как в настройках · " + (f"{follow} мин" if follow else "без предела"), "follow")
        for label, n in self.PRESETS:
            self.mode.addItem(label, n)
        self.mode.addItem("Своя продолжительность", "custom")
        self.mode.addItem("Без предела", 0)
        self.custom = QSpinBox()
        self.custom.setRange(5, 240)
        self.custom.setSuffix(" мин")
        self.custom.setValue(90)
        lay.addWidget(self.mode, 1)
        lay.addWidget(self.custom)
        self.mode.currentIndexChanged.connect(self._changed)
        self.custom.valueChanged.connect(self._changed)
        self._sync()

    def value(self) -> int | None:
        key = self.mode.currentData()
        if key == "follow":
            return None
        return self.custom.value() if key == "custom" else key

    def setValue(self, v: int | None) -> None:
        self.mode.blockSignals(True)
        self.custom.blockSignals(True)
        if v is None:
            i = self.mode.findData("follow")
        else:
            i = self.mode.findData(v)
            if i < 0 or v == 0 and self.mode.itemData(i) != 0:
                i = self.mode.findData("custom")
                self.custom.setValue(v)
        self.mode.setCurrentIndex(max(0, i))
        self.mode.blockSignals(False)
        self.custom.blockSignals(False)
        self._sync()

    def _sync(self) -> None:
        self.custom.setVisible(self.mode.currentData() == "custom")

    def _changed(self, *_a) -> None:
        self._sync()
        self.changed.emit(self.value())


class LessonPanel(QFrame):
    """Панель урока в повестке: заголовок и строки его блоков (их добавляет окно — add_row)."""

    def __init__(self, number: int, segs: list[Segment], limit: int = 0, name: str = "") -> None:
        super().__init__(objectName="lesson")
        self.segs = segs
        self.first, self.last = segs[0].index, segs[-1].index
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        head = QHBoxLayout()
        head.setContentsMargins(10, 2, 10, 0)
        self.title = QLabel(f"УРОК {number}" + (f" · {name}" if name else ""))
        mins = lesson_minutes(segs)
        over = bool(limit) and mins > limit
        self.info = QLabel(f"{segs[0].start:%H:%M}–{segs[-1].end:%H:%M} · "
                           + (f"{mins} из {limit} мин" if over else f"{mins} мин"))
        self.info.setToolTip("Продолжительность урока — в ⚙ Настройки или своя у шаблона" if limit else "")
        self._over = over
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(self.info)
        lay.addLayout(head)
        self.body = lay
        self.state = None
        self.set_state("")

    def add_row(self, w: QWidget) -> None:
        self.body.addWidget(w)

    def contains(self, index: int) -> bool:
        return self.first <= index <= self.last

    def set_state(self, state: str) -> None:
        """state: now — идёт сейчас, past — прошёл, "" — впереди."""
        if state == self.state:
            return
        self.state = state
        border = style.BRAND if state == "now" else style.LINE
        bg = "rgba(142,77,255,0.07)" if state == "now" else "rgba(255,255,255,0.02)"
        self.setStyleSheet(f"QFrame#lesson {{ background: {bg}; border: 1px solid {border}; border-radius: 14px; }}")
        accent = style.BRAND_BRIGHT if state == "now" else (style.DIM if state == "past" else style.MUTED)
        self.title.setStyleSheet(f"color: {accent}; font-weight: 800; letter-spacing: 2px; font-size: 8.5pt;")
        info = style.RED if self._over else (style.DIM if state == "past" else style.MUTED)
        self.info.setStyleSheet(f"color: {info}; font-size: 9pt; font-weight: 600;")


class TimelineBar(QWidget):
    """Полоса всего эфира: уроки и перерывы в масштабе времени, прошедшее закрашено, белая отметка — сейчас."""

    def __init__(self) -> None:
        super().__init__()
        self.segs: list[Segment] = []
        self.now: datetime | None = None
        self.setFixedHeight(24)
        self.setMinimumWidth(120)

    def set_segments(self, segs: list[Segment], names: list[str] | None = None) -> None:
        self.segs = segs
        self.names = names or []
        self._parts = self._build_parts()
        self._tip()
        self.update()

    def set_now(self, now: datetime) -> None:
        self.now = now
        self.update()

    def _build_parts(self) -> list[tuple[str, datetime, datetime, str]]:
        """[(вид: lesson|break, начало, конец, подпись)] по порядку."""
        def title(n: int) -> str:
            return self.names[n - 1] if n - 1 < len(self.names) and self.names[n - 1] else f"Урок {n}"

        out = [("lesson", g[0].start, g[-1].end, f"{title(n)} · {lesson_minutes(g)} мин")
               for n, g in enumerate(lessons(self.segs), 1)]
        out += [("break", s.start, s.end, f"☕ {s.activity.min}") for s in self.segs if s.activity.breaks]
        return sorted(out, key=lambda part: part[1])

    def _tip(self) -> None:
        self.setToolTip("\n".join(f"{label} · {a:%H:%M}–{b:%H:%M}" for _k, a, b, label in self._parts))

    def paintEvent(self, _e) -> None:
        if not self.segs:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        begin, end = self.segs[0].start, self.segs[-1].end
        span = max(1.0, (end - begin).total_seconds())
        w, h = self.width(), self.height()
        x_of = lambda t: (t - begin).total_seconds() / span * w      # noqa: E731
        now = self.now
        f = QFont(self.font())
        f.setPixelSize(11)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        fm = QFontMetrics(f)
        for kind, a, b, label in self._parts:
            r = QRectF(x_of(a) + 1, 0, max(2.0, x_of(b) - x_of(a) - 2), h)
            clip = QPainterPath()
            clip.addRoundedRect(r, 6, 6)
            base, fill = (("rgba(242,182,75,0.16)", style.AMBER) if kind == "break"
                          else ("rgba(255,255,255,0.06)", style.BRAND))
            p.fillPath(clip, _color(base))
            if now is not None and now > a:
                done = QRectF(r.left(), 0, min(r.width(), x_of(min(now, b)) - r.left()), h)
                p.save()
                p.setClipPath(clip)
                p.fillRect(done, QColor(fill))
                p.restore()
            text = fm.elidedText(label, Qt.TextElideMode.ElideRight, int(r.width()) - 10)
            if text and text != "…":
                if kind == "lesson":
                    p.setPen(QColor(style.INK))
                else:                                # прошедший перерыв закрашен янтарём — текст тёмный
                    p.setPen(QColor("#1A1206" if now is not None and now >= b else style.AMBER))
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
        if now is not None and begin <= now <= end:
            x = x_of(now)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("white"))
            p.drawRoundedRect(QRectF(x - 1.5, -1, 3, h + 2), 1.5, 1.5)


def _color(css: str) -> QColor:
    """«rgba(r,g,b,a)» с долей прозрачности (QColor понимает только #AARRGGBB)."""
    if css.startswith("rgba("):
        r, g, b, a = (v.strip() for v in css[5:-1].split(","))
        return QColor(int(r), int(g), int(b), int(float(a) * 255))
    return QColor(css)
