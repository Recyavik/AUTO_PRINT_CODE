"""Пульты на мониторе управления: зрители видят только экран демонстрации, а ведущий — пульт поверх своих окон.

Пульт видео (PlayerPanel): сначала, −10 с, пауза/играть, +10 с, полоса перемотки (щелчок — сразу туда),
время, громкость и «Убрать»; под полосой — сколько осталось, когда ролик закончится и выходит ли он за план блока. Пульт перерыва (BreakPanel): крупный отсчёт и полоса, −1 мин, пауза/продолжить,
+1 мин, «Заново» и «Убрать» — отсчёт на заставке у зрителей меняется вместе с ним.
Пульт занавеса (CurtainPanel): только «Убрать занавес» — вверху монитора управления, чтобы не закрывать другие пульты.
Фокус пульт не забирает; его можно перетащить мышью за свободное место — позиция (общая для обоих пультов)
запоминается относительно монитора управления, как у карточек напоминаний.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Callable

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QScreen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QStyle, QVBoxLayout, QWidget

from ..model import fmt_left
from . import style

STEP_MS = 10_000        # перемотка видео кнопками −10 с / +10 с
BREAK_STEP = timedelta(minutes=1)   # перерыв: −1 мин / +1 мин
WIDTH = 600
MARGIN = 24

def theme_colors(kind: str) -> tuple[str, str, str, str, str]:
    """Оформление пульта в цветах текущей темы: (фон, рамка, акцент, кнопка «ok», она же при наведении)."""
    bg, border, ok, ok_hover = style.PANEL_VIDEO if kind == "video" else style.PANEL_BREAK
    return bg, border, style.EYE if kind == "video" else style.AMBER, ok, ok_hover


def fmt_ms(ms: int) -> str:
    s = max(0, ms) // 1000
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def plan_line(pos_ms: int, dur_ms: int, now: datetime, planned_end: datetime | None) -> tuple[str, int]:
    """Строка пульта видео: «осталось 2:50 · закончится в 11:07 · по плану до 11:05, +2 мин» и на сколько
    минут ролик выходит за план (0 — укладывается или плана нет). Длина ещё не известна — пусто."""
    if dur_ms <= 0:
        return "", 0
    left = max(0, dur_ms - pos_ms)
    finish = now + timedelta(milliseconds=left)
    text = f"осталось {fmt_ms(left)} · закончится в {finish:%H:%M}"
    if planned_end is None:
        return text, 0
    late = (finish - planned_end).total_seconds()
    over = max(1, math.floor(late / 60 + 0.5)) if late >= 30 else 0   # до минуты; меньше полуминуты — не опоздание
    text += f" · по плану до {planned_end:%H:%M}"
    if over > 0:
        text += f", +{over} мин"
    return text, max(0, over)


class SeekSlider(QSlider):
    """Полоса перемотки: щелчок по полосе — сразу в это место (а не шаг к нему, как у обычного QSlider)."""

    def __init__(self) -> None:
        super().__init__(Qt.Orientation.Horizontal)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            v = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), int(e.position().x()), self.width())
            self.setValue(v)
            self.sliderMoved.emit(v)
        super().mousePressEvent(e)


class _Remote(QWidget):
    """Общее у пультов: рамка в цветах темы, подпись «НА ЭКРАНЕ ДЕМОНСТРАЦИИ», перетаскивание, место на экране."""
    stop_requested = Signal()       # «Убрать»
    dropped = Signal(object)        # пульт перетащили: смещение от угла монитора управления

    def __init__(self, theme: str, caption: str, title: str, screen: QScreen, anchor: QPoint | None) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.screen_, self.anchor = screen, anchor
        self._drag_from = None

        self._kind = theme
        frame = QFrame(self, objectName="player")
        self.frame = frame
        frame.setCursor(Qt.CursorShape.OpenHandCursor)   # подсказка: пульт можно перетащить
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)
        self.lay = QVBoxLayout(frame)
        self.lay.setContentsMargins(14, 9, 12, 10)
        self.lay.setSpacing(6)

        head = QHBoxLayout()
        self.title = QLabel(title, objectName="name")
        self.title.setMinimumWidth(1)
        head.addWidget(QLabel(caption, objectName="label"))
        head.addWidget(self.title, 1)
        self.lay.addLayout(head)

        self.restyle()
        self.setMinimumWidth(WIDTH)

    def restyle(self) -> None:
        """Оформить в цветах текущей темы (и перекрасить, если тему сменили)."""
        bg, border, accent, ok, ok_hover = theme_colors(self._kind)
        self.frame.setStyleSheet(f"""
            QFrame#player {{ background: {bg}; border: 1px solid {border};
              border-left: 5px solid {accent}; border-radius: 12px; }}
            QLabel {{ background: transparent; color: {style.INK}; }}
            QLabel#label {{ color: {accent}; font-weight: 700; letter-spacing: 1px; font-size: 7.5pt; }}
            QLabel#name {{ font-size: 10pt; font-weight: 700; }}
            QLabel#time {{ color: {style.MUTED}; font-size: 9pt; font-weight: 600; }}
            QLabel#big {{ color: {accent}; font-size: 20pt; font-weight: 800; }}
            QPushButton {{ background: {style.TINT2}; border: 1px solid {border}; border-radius: 7px;
              padding: 4px 10px; color: {style.INK}; font-weight: 600; font-size: 9.5pt; }}
            QPushButton:hover {{ border-color: {accent}; }}
            QPushButton#ok {{ background: {ok}; border-color: {ok}; color: {style.ON_BRAND}; }}
            QPushButton#ok:hover {{ background: {ok_hover}; }}
            QPushButton#stop:hover {{ border-color: {style.RED}; color: {style.RED}; }}
            QSlider {{ background: transparent; }}
            QSlider::groove:horizontal {{ height: 6px; background: {style.TINT2}; border-radius: 3px; }}
            QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 3px; }}
            QSlider::handle:horizontal {{ width: 14px; margin: -5px 0; border-radius: 7px; background: {style.INK}; }}
        """)

    def _button(self, text: str, tip: str, slot: Callable, name: str = "") -> QPushButton:
        b = QPushButton(text, objectName=name)
        b.setToolTip(tip)
        b.setCursor(Qt.CursorShape.ArrowCursor)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setAutoDefault(False)
        b.clicked.connect(slot)
        return b

    def _fix_buttons(self, *buttons: QPushButton) -> None:
        for b in buttons:
            b.setMinimumWidth(max(b.minimumWidth(), b.sizeHint().width()))   # кнопки не сжимаются под текст

    # ---- место на мониторе управления
    def place(self) -> None:
        self.adjustSize()
        area = self.screen_.availableGeometry()
        if self.anchor is None:          # по умолчанию — внизу по центру
            x, y = area.center().x() - self.width() // 2, area.bottom() - self.height() - MARGIN
        else:
            x, y = area.left() + self.anchor.x(), area.top() + self.anchor.y()
        x = min(max(area.left(), x), area.right() - self.width())
        y = min(max(area.top(), y), area.bottom() - self.height())
        self.move(x, y)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_from = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e) -> None:
        if self._drag_from is not None:
            self.move(e.globalPosition().toPoint() - self._drag_from)

    def mouseReleaseEvent(self, e) -> None:
        if self._drag_from is not None:
            self._drag_from = None
            area = self.screen_.availableGeometry()
            self.anchor = QPoint(self.x() - area.left(), self.y() - area.top())
            self.dropped.emit(self.anchor)


class PlayerPanel(_Remote):
    """Пульт к QMediaPlayer: player — что показывает видео на экране демонстрации."""

    def __init__(self, player, audio, title: str, screen: QScreen, anchor: QPoint | None = None,
                 clock: Callable[[], datetime] = datetime.now, planned_end: datetime | None = None) -> None:
        """planned_end — когда блок кончается по расписанию (видео не из повестки — None)."""
        super().__init__("video", "НА ЭКРАНЕ ДЕМОНСТРАЦИИ", title, screen, anchor)
        self.player, self.audio = player, audio
        self.clock, self.planned_end = clock, planned_end

        bar = QHBoxLayout()
        self.slider = SeekSlider()
        self.slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.time = QLabel("0:00 / 0:00", objectName="time")
        bar.addWidget(self.slider, 1)
        bar.addWidget(self.time)
        self.lay.addLayout(bar)
        self.plan = QLabel(objectName="time")
        self.plan.setTextFormat(Qt.TextFormat.RichText)
        self.lay.addWidget(self.plan)

        row = QHBoxLayout()
        self.restart_btn = self._button("↺ Сначала", "Видео с начала", lambda: self.seek_to(0))
        self.back_btn = self._button("−10 с", "Назад на 10 секунд", lambda: self.seek_by(-STEP_MS))
        self.play_btn = self._button("❚❚ Пауза", "Пауза / продолжить", self.toggle_play, "ok")
        self.play_btn.setMinimumWidth(104)
        self.fwd_btn = self._button("+10 с", "Вперёд на 10 секунд", lambda: self.seek_by(STEP_MS))
        self.mute_btn = self._button("🔊", "Звук: выключить / включить", self.toggle_mute)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(70)
        self.volume.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.volume.setCursor(Qt.CursorShape.PointingHandCursor)
        self.volume.setToolTip("Громкость")
        self.stop_btn = self._button("■ Убрать", "Остановить видео и убрать его с экрана демонстрации",
                                     self.stop_requested.emit, "stop")
        for w in (self.restart_btn, self.back_btn, self.play_btn, self.fwd_btn):
            row.addWidget(w)
        row.addSpacing(6)
        row.addWidget(self.mute_btn)
        row.addWidget(self.volume)
        row.addStretch(1)
        row.addWidget(self.stop_btn)
        self.lay.addLayout(row)
        self._fix_buttons(self.restart_btn, self.back_btn, self.play_btn, self.fwd_btn, self.mute_btn, self.stop_btn)

        player.positionChanged.connect(self._on_position)
        player.durationChanged.connect(self._on_duration)
        player.playbackStateChanged.connect(lambda _s: self._sync_play())
        self.slider.sliderMoved.connect(self._on_slider_moved)
        self.slider.sliderReleased.connect(lambda: self.seek_to(self.slider.value()))
        self.volume.valueChanged.connect(self._on_volume)
        self.volume.setValue(round(audio.volume() * 100))
        self._on_duration(player.duration())
        self._on_position(player.position())
        self._sync_play()
        self._plan_timer = QTimer(self)                 # на паузе позиция стоит, а «закончится в» уходит вперёд
        self._plan_timer.timeout.connect(self._show_plan)
        self._plan_timer.start(1000)

    # ---- управление
    def playing(self) -> bool:
        from PySide6.QtMultimedia import QMediaPlayer
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def toggle_play(self) -> None:
        if self.playing():
            self.player.pause()
        else:
            self.player.play()
        self._sync_play()

    def seek_to(self, ms: int) -> None:
        dur = self.player.duration()
        ms = max(0, ms if dur <= 0 else min(ms, max(0, dur - 200)))   # не в самый конец: там видео сразу «кончается»
        self.player.setPosition(ms)
        self._on_position(ms)

    def seek_by(self, delta_ms: int) -> None:
        self.seek_to(self.player.position() + delta_ms)

    def toggle_mute(self) -> None:
        self.audio.setMuted(not self.audio.isMuted())
        self.mute_btn.setText("🔇" if self.audio.isMuted() else "🔊")

    # ---- отображение
    def _sync_play(self) -> None:
        self.play_btn.setText("❚❚ Пауза" if self.playing() else "▶ Играть")

    def _on_duration(self, ms: int) -> None:
        self.slider.setRange(0, max(0, ms))
        self._show_time(self.player.position())

    def _on_position(self, ms: int) -> None:
        if not self.slider.isSliderDown():       # тянут ползунок — не дёргать его из плеера
            self.slider.setValue(ms)
            self._show_time(ms)

    def _on_slider_moved(self, ms: int) -> None:
        self._show_time(ms)
        if not self.slider.isSliderDown():       # щелчок по полосе — сразу туда
            self.seek_to(ms)

    def _show_time(self, ms: int) -> None:
        self.time.setText(f"{fmt_ms(ms)} / {fmt_ms(self.player.duration())}")
        self._show_plan(ms)

    def _show_plan(self, ms: int | None = None) -> None:
        pos = self.player.position() if ms is None else ms
        text, over = plan_line(pos, self.player.duration(), self.clock(), self.planned_end)
        self.plan.setText(f"<span style='color:{style.AMBER}; font-weight:700'>{text}</span>" if over else text)
        self.plan.setToolTip("Ролик закончится позже, чем блок по расписанию: следующий блок начнётся во время видео. "
                             "Можно перемотать или убрать видео раньше." if over else "")

    def _on_volume(self, v: int) -> None:
        self.audio.setVolume(v / 100)


class BreakPanel(_Remote):
    """Пульт к заставке перерыва (BreakOverlay): отсчёт у зрителей меняется вместе с пультом."""

    def __init__(self, overlay, screen: QScreen, anchor: QPoint | None = None) -> None:
        super().__init__("break", "ПЕРЕРЫВ НА ЭКРАНЕ ДЕМОНСТРАЦИИ", "", screen, anchor)
        self.overlay = overlay

        bar = QHBoxLayout()
        self.big = QLabel(objectName="big")
        # перемотка, как у видео: тянуть — цифры на пульте показывают, что будет; отпустить или щёлкнуть — на заставку
        self.progress = SeekSlider()
        self.progress.setRange(0, 1000)
        self.progress.setToolTip("Перемотать отсчёт перерыва: потяните ползунок или щёлкните по полосе")
        self.progress.sliderMoved.connect(self._on_slider_moved)
        self.progress.sliderReleased.connect(lambda: self.seek(self.progress.value()))
        bar.addWidget(self.big)
        bar.addSpacing(8)
        bar.addWidget(self.progress, 1)
        self.lay.addLayout(bar)

        row = QHBoxLayout()
        self.less_btn = self._button("−1 мин", "Перерыв на минуту короче", lambda: self.add(-BREAK_STEP))
        self.pause_btn = self._button("❚❚ Пауза", "Остановить отсчёт / продолжить", self.toggle_pause, "ok")
        self.pause_btn.setMinimumWidth(124)
        self.more_btn = self._button("+1 мин", "Перерыв на минуту длиннее", lambda: self.add(BREAK_STEP))
        self.restart_btn = self._button("↺ Заново", "Начать отсчёт перерыва сначала", self.restart)
        self.stop_btn = self._button("■ Убрать", "Убрать заставку перерыва с экрана демонстрации",
                                     self.stop_requested.emit, "stop")
        for w in (self.less_btn, self.pause_btn, self.more_btn, self.restart_btn):
            row.addWidget(w)
        row.addStretch(1)
        row.addWidget(self.stop_btn)
        self.lay.addLayout(row)
        self._fix_buttons(self.less_btn, self.pause_btn, self.more_btn, self.restart_btn, self.stop_btn)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(250)
        self.refresh()

    def add(self, delta: timedelta) -> None:
        self.overlay.add(delta)
        self.refresh()

    def toggle_pause(self) -> None:
        if self.overlay.paused:
            self.overlay.resume()
        else:
            self.overlay.pause()
        self.refresh()

    def restart(self) -> None:
        self.overlay.restart()
        self.refresh()

    def _passed(self, value: int) -> timedelta:
        """Положение ползунка (0–1000) → сколько прошло от перерыва."""
        return timedelta(seconds=round(self.overlay.total.total_seconds() * value / 1000))

    def seek(self, value: int) -> None:
        self.overlay.seek(self._passed(value))
        self.refresh()

    def _on_slider_moved(self, value: int) -> None:
        if self.progress.isSliderDown():         # тянут: показать, что будет, заставку не трогать до отпускания
            left = self.overlay.total - self._passed(value)
            self.big.setText(fmt_left(left) if left.total_seconds() > 0 else "00:00")
        else:                                    # щелчок по полосе — сразу туда
            self.seek(value)

    def refresh(self) -> None:
        o = self.overlay
        if self.progress.isSliderDown():         # ползунок тянут — не перебивать его отсчётом
            return
        left = o.left()
        self.big.setText(fmt_left(left) if left.total_seconds() > 0 else "00:00")
        total = max(1.0, o.total.total_seconds())
        self.progress.setValue(int(1000 * min(1.0, max(0.0, 1 - left.total_seconds() / total))))
        if o.paused:
            self.title.setText("отсчёт на паузе")
        elif left.total_seconds() > 0:
            self.title.setText(f"до {o.end:%H:%M} · {round(total / 60)} мин")
        else:
            self.title.setText("время вышло — на экране «ПРОДОЛЖАЕМ»")
        text = "▶ Продолжить" if o.paused else "❚❚ Пауза"
        if self.pause_btn.text() != text:
            self.pause_btn.setText(text)

    def closeEvent(self, e) -> None:
        self._timer.stop()
        super().closeEvent(e)


class CurtainPanel(_Remote):
    """Пульт экстренного занавеса: одна кнопка «Убрать»; стоит вверху монитора управления (не на месте других пультов)."""

    def __init__(self, screen: QScreen, hotkey: str, text: str) -> None:
        super().__init__("break", "ЗАНАВЕС НА ЭКРАНЕ ДЕМОНСТРАЦИИ", f"зрители видят «{text}»", screen, None)
        row = QHBoxLayout()
        hint = QLabel(f"Убрать — кнопкой или {hotkey}" if hotkey else "Убрать — кнопкой", objectName="time")
        self.stop_btn = self._button("■ Убрать занавес", "Открыть экран демонстрации зрителям",
                                     self.stop_requested.emit, "ok")
        row.addWidget(hint, 1)
        row.addWidget(self.stop_btn)
        self.lay.addLayout(row)
        self._fix_buttons(self.stop_btn)

    def place(self) -> None:
        self.adjustSize()
        area = self.screen_.availableGeometry()
        self.move(area.center().x() - self.width() // 2, area.top() + MARGIN)
