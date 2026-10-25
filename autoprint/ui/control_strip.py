"""Пульт печати над образцом: старт/пауза, скорость, режимы, ход печати, звук, профиль окна."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from ..storage import PROFILES, Settings
from ..typer import COUNTDOWN, FINISHED, IDLE, LINE_WAIT, PAUSED, RUNNING
from . import icons
from .frameless import StatusDot
from .theme import STATE_TOKENS, theme
from .widgets import FlowLayout, IconButton, Segmented, Slider, Switch, combo, flow_sep, spin, vsep

SPEED_PRESETS = [(180, "Медленно"), (320, "Стандарт"), (600, "Быстро")]
MODES = [("block", "Целиком"), ("lines", "По строкам"), ("steps", "По шагам")]
STATE_TEXT = {IDLE: "Готов", COUNTDOWN: "Отсчёт…", RUNNING: "Печатает", PAUSED: "Пауза", FINISHED: "Готово",
              LINE_WAIT: "Ждёт Enter"}


class StartButton(QPushButton):
    """Большая янтарная кнопка: [значок] Старт  Ctrl+F9."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("bigBtn")
        self.setProperty("accent", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(8)
        self.ic = QLabel()
        self.ic.setFixedSize(14, 14)
        self.txt = QLabel()
        self.txt.setObjectName("bigBtnText")
        self.kbd = QLabel()
        self.kbd.setObjectName("kbd")
        for w in (self.ic, self.txt, self.kbd):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            lay.addWidget(w)
        self._icon = "play"
        self.set_mode("Старт", "play")
        theme.changed.connect(self._on_theme)

    def _on_theme(self) -> None:
        self.set_mode(self.txt.text(), self._icon)

    def set_mode(self, text: str, icon_name: str) -> None:
        self._icon = icon_name
        self.txt.setText(text)
        self.ic.setPixmap(icons.pixmap(icon_name, theme.c("on_accent"), 14))
        self.setMinimumWidth(self.layout().sizeHint().width())

    def set_hotkey(self, hk: str) -> None:
        self.kbd.setText(hk)
        self.kbd.setVisible(bool(hk))
        self.setMinimumWidth(self.layout().sizeHint().width())

    def sizeHint(self) -> QSize:
        return QSize(max(150, self.layout().sizeHint().width()), 36)


class ControlStrip(QFrame):
    toggle_clicked = Signal()
    restart_clicked = Signal()
    stop_clicked = Signal()
    cpm_changed = Signal(int)
    human_toggled = Signal(bool)
    strip_toggled = Signal(bool)
    sound_toggled = Signal(bool)
    volume_changed = Signal(int)
    volume_released = Signal()
    profile_changed = Signal(str)
    mode_changed = Signal(str)
    prompter_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(0)

        # ---- строка 1: управление
        top = QWidget()
        flow = FlowLayout(top, hspacing=10, vspacing=10)
        self.btn_toggle = StartButton()
        self.btn_toggle.clicked.connect(self.toggle_clicked)
        self.btn_restart = IconButton("restart", "Сначала", 15, box=36, framed=True)
        self.btn_restart.clicked.connect(self.restart_clicked)
        self.btn_stop = IconButton("stop", "Стоп", 15, box=36, framed=True)
        self.btn_stop.clicked.connect(self.stop_clicked)
        self.btn_prompter = IconButton("lines", "Суфлёр в отдельном окне: что сказать и что набрать, "
                                       "«Дальше» — следующий шаг", 15, box=36, framed=True)
        self.btn_prompter.setCheckable(True)
        self.btn_prompter.clicked.connect(self.prompter_clicked)
        self.speed = Segmented(SPEED_PRESETS)
        self.speed.setToolTip("Скорость печати")
        self.speed.changed.connect(self._on_preset)
        self.cpm = spin(30, 3000, 320, " зн/мин", 10, width=136)
        self.cpm.setToolTip("Точная скорость, знаков в минуту")
        self.cpm.valueChanged.connect(self._on_cpm)
        self.sw_human = Switch("Как человек")
        self.sw_human.setToolTip("Живой ритм, паузы на обдумывание и исправленные опечатки")
        self.sw_human.toggled.connect(self.human_toggled)
        self.sw_strip = Switch("Без комментариев")
        self.sw_strip.setToolTip("Комментарии # …, // …, /* … */ не печатаются. Само занятие не меняется")
        self.sw_strip.toggled.connect(self.strip_toggled)
        self.mode = Segmented(MODES)
        self.mode.setToolTip("Целиком — блок за один раз · По строкам — строка, затем Enter — следующая · "
                             "По шагам — урок частями, в том числе с возвратом наверх")
        self.mode.changed.connect(lambda k: self.mode_changed.emit(str(k)))
        for w in (self.btn_toggle, self.btn_restart, self.btn_stop, self.btn_prompter, flow_sep(), self.mode,
                  flow_sep(), self.speed, self.cpm, flow_sep(), self.sw_human, self.sw_strip):
            flow.addWidget(w)
        outer.addWidget(top)

        # ---- строка 2: ход печати, звук, окно
        line = QFrame()
        line.setObjectName("hsep")
        outer.addSpacing(10)
        outer.addWidget(line)
        outer.addSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.dot = StatusDot()
        self.state_lbl = QLabel()
        self.state_lbl.setObjectName("stateLbl")
        self.info = QLabel()
        self.info.setObjectName("dim")
        self.info.setMinimumWidth(80)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setMinimumWidth(60)
        self.count = QLabel()
        self.count.setObjectName("mono")
        self.btn_sound = IconButton("volume", "Звук клавиш", 16, box=28)
        self.btn_sound.setCheckable(True)
        self.btn_sound.toggled.connect(self._on_sound)
        self.vol = Slider(0, 100)
        self.vol.setFixedWidth(96)
        self.vol.valueChanged.connect(self._on_volume)
        self.vol.sliderReleased.connect(self.volume_released)
        self.profile = combo(PROFILES, "ide")
        self.profile.setToolTip("Куда печатаем: IDE убирает автоскобки и автоотступы (VS Code, Jupyter, Colab, веб-IDE), "
                                "Блокнот — печать как есть, Терминал — только символы и Enter (Git Bash, PowerShell)")
        # в узком окне список может сжаться: иначе минимальная ширина пульта больше доступной, и перенос
        # кнопок верхней строки считается для этой (несуществующей) ширины — третья строка обрезается
        self.profile.setMinimumWidth(130)
        self.profile.currentIndexChanged.connect(lambda _i: self.profile_changed.emit(self.profile.currentData()))
        row.addWidget(self.dot)
        row.addWidget(self.state_lbl)
        row.addWidget(self.info, 2)
        row.addWidget(self.progress, 1)
        row.addWidget(self.count)
        row.addSpacing(4)
        row.addWidget(vsep(20))
        row.addSpacing(2)
        row.addWidget(self.btn_sound)
        row.addWidget(self.vol)
        row.addSpacing(6)
        row.addWidget(self.profile)
        outer.addLayout(row)
        self._full_info = ""
        self.set_state(IDLE)

    # ------------------------------------------------------------ значения из настроек
    def set_settings(self, s: Settings) -> None:
        widgets = (self.cpm, self.sw_human, self.sw_strip, self.btn_sound, self.vol, self.profile, self.speed,
                   self.mode)
        for w in widgets:
            w.blockSignals(True)
        self.mode.set_value(s.print_mode)
        self.cpm.setValue(s.cpm)
        self.speed.set_value(next((v for v, _ in SPEED_PRESETS if v == s.cpm), None))
        self.sw_human.setChecked(s.human_typing)
        self.sw_strip.setChecked(s.strip_comments)
        self.btn_sound.setChecked(s.sound_enabled)
        self._sound_icon(s.sound_enabled)
        self.vol.setValue(s.sound_volume)
        self.vol.setEnabled(s.sound_enabled)
        self.vol.setToolTip(f"Громкость клавиш: {s.sound_volume} %")
        self.profile.setCurrentIndex(max(0, self.profile.findData(s.profile)))
        for w in widgets:
            w.blockSignals(False)
        self.btn_toggle.set_hotkey(s.hotkey_toggle)
        self.btn_toggle.setToolTip(f"Старт / пауза / продолжить ({s.hotkey_toggle or 'без хоткея'})")
        self.btn_restart.setToolTip(f"Сначала ({s.hotkey_restart})" if s.hotkey_restart else "Сначала")
        self.btn_stop.setToolTip(f"Стоп ({s.hotkey_stop})" if s.hotkey_stop else "Стоп")

    # ------------------------------------------------------------ состояние
    def set_state(self, st: str, countdown: int = 0) -> None:
        token = STATE_TOKENS.get(st, "ok")
        self.dot.set_token(token)
        text = f"Старт через {countdown}…" if st == COUNTDOWN and countdown else STATE_TEXT.get(st, st)
        self.state_lbl.setText(f"<b style='color:{theme.c(token).name()}'>{text}</b>")
        if st in (RUNNING, COUNTDOWN):
            self.btn_toggle.set_mode("Пауза", "pause")
        elif st == PAUSED:
            self.btn_toggle.set_mode("Продолжить", "play")
        elif st == LINE_WAIT:
            self.btn_toggle.set_mode("Дальше", "enter")
        else:
            self.btn_toggle.set_mode("Старт", "play")

    def set_prompter_on(self, on: bool) -> None:
        self.btn_prompter.setChecked(on)
        self.btn_prompter.set_icon("lines", "accent" if on else "dim")

    def set_info(self, html: str) -> None:
        self.info.setText(html)
        self.info.setToolTip(self.info.text())

    def set_progress(self, done: int, total: int, frac: float, unit: str = "стр.") -> None:
        self.progress.setMaximum(1000)
        self.progress.setValue(int(max(0.0, min(1.0, frac)) * 1000))
        self.count.setText(f"{done} / {total} {unit}" if total else "")

    # ------------------------------------------------------------ внутреннее
    def _on_preset(self, cpm) -> None:
        self.cpm.setValue(int(cpm))   # → _on_cpm → сигнал

    def _on_cpm(self, v: int) -> None:
        self.speed.set_value(next((c for c, _ in SPEED_PRESETS if c == v), None))
        self.cpm_changed.emit(v)

    def _sound_icon(self, on: bool) -> None:
        self.btn_sound.set_icon("volume" if on else "volume-off", "dim" if on else "faint")

    def _on_sound(self, on: bool) -> None:
        self._sound_icon(on)
        self.vol.setEnabled(on)
        self.sound_toggled.emit(on)

    def _on_volume(self, v: int) -> None:
        self.vol.setToolTip(f"Громкость клавиш: {v} %")
        self.volume_changed.emit(v)

