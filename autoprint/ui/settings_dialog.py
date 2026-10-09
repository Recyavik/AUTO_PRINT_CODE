"""Окно настроек."""
from __future__ import annotations

import time
from dataclasses import asdict

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QKeySequenceEdit, QLabel, QMessageBox, QPushButton, QSlider,
                               QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from .. import __version__
from ..hotkeys import parse_hotkey
from ..sounds import STYLES
from ..storage import PROFILE_IDE, PROFILES, Settings
from ..updater import MODE_FROZEN, install_mode
from .updates import INTERVALS, MODE_DOWNLOAD, MODE_NOTIFY, UPDATE_MODES

HOTKEYS = [
    ("hotkey_toggle", "Старт / пауза / продолжить"),
    ("hotkey_restart", "Начать сначала"),
    ("hotkey_stop", "Остановить"),
    ("hotkey_next_block", "Следующий блок кода"),
    ("hotkey_prev_block", "Предыдущий блок кода"),
    ("hotkey_next_tab", "Следующая вкладка-образец"),
]


class _HotkeyEdit(QWidget):
    def __init__(self, value: str) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QKeySequenceEdit(QKeySequence(value))
        self.edit.setMaximumSequenceLength(1)
        clear = QPushButton("✕")
        clear.setFixedWidth(28)
        clear.setToolTip("Без хоткея")
        clear.clicked.connect(self.edit.clear)
        lay.addWidget(self.edit, 1)
        lay.addWidget(clear)

    def value(self) -> str:
        return self.edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)


def _spin(lo: int, hi: int, val: int, suffix: str = "", step: int = 1) -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setValue(val)
    if suffix:
        s.setSuffix(suffix)
    return s


class SettingsDialog(QDialog):
    test_sound = Signal(str, int)   # (стиль, громкость)
    check_updates = Signal()

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(520)
        s = settings
        tabs = QTabWidget()

        # ---- хоткеи
        w = QWidget()
        f = QFormLayout(w)
        self.hk: dict[str, _HotkeyEdit] = {}
        for key, label in HOTKEYS:
            self.hk[key] = _HotkeyEdit(getattr(s, key))
            f.addRow(label + ":", self.hk[key])
        note = QLabel("Хоткеи глобальные — работают в любом окне и не доходят до него. "
                      "Удобны F-клавиши с Ctrl/Shift: они редко заняты в редакторах.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        f.addRow(note)
        tabs.addTab(w, "Хоткеи")

        # ---- печать
        w = QWidget()
        f = QFormLayout(w)
        self.cpm = _spin(30, 3000, s.cpm, " симв/мин", 10)
        self.jitter = _spin(0, 90, s.jitter, " %")
        self.nl_pause = _spin(0, 3000, s.newline_pause_ms, " мс", 10)
        self.punct = _spin(0, 1000, s.punct_pause_ms, " мс", 10)
        self.tab_w = _spin(1, 8, s.tab_width, " пробелов")
        self.key_gap = _spin(5, 200, s.key_gap_ms, " мс", 5)
        self.key_gap.setToolTip("Меньше — быстрее служебные нажатия и отступы, но медленные редакторы "
                                "(Блокнот Windows 11, браузерные IDE) начинают терять символы. "
                                "Если символы пропадают — увеличьте.")
        self.fast_indent = QCheckBox("Отступы печатать быстро")
        self.fast_indent.setChecked(s.fast_indent)
        self.indent_tab = QCheckBox("Отступы набирать клавишей Tab (как программист)")
        self.indent_tab.setChecked(s.indent_with_tab)
        self.indent_tab.setToolTip("Одно нажатие Tab на каждые «Таб в образце» пробелов отступа. "
                                   "Редактор сам превращает Tab в отступ (VS Code, PyCharm, Jupyter — "
                                   "4 пробела). Не включайте для простых полей ввода в браузере: "
                                   "там Tab переводит фокус. Если в редакторе отступ 2 пробела — "
                                   "уровни разойдутся с образцом.")
        self.whole_lines = QCheckBox("Выделение в образце расширять до целых строк")
        self.whole_lines.setChecked(s.selection_whole_lines)
        self.strip_comments = QCheckBox("Не печатать комментарии (# …, // …, /* … */)")
        self.strip_comments.setChecked(s.strip_comments)
        self.strip_comments.setToolTip("Строки-комментарии пропускаются целиком, комментарии в конце строки "
                                       "отрезаются. Сам образец не меняется.")
        self.profile = QComboBox()
        for k, v in PROFILES.items():
            self.profile.addItem(v, k)
        self.profile.setCurrentIndex(self.profile.findData(s.profile))
        self.esc = QCheckBox("Esc перед Enter (закрыть подсказки). Не для Jupyter!")
        self.esc.setChecked(s.esc_before_enter)
        f.addRow("Скорость:", self.cpm)
        f.addRow("Разброс темпа:", self.jitter)
        f.addRow("Пауза после Enter:", self.nl_pause)
        f.addRow("Пауза после , ; : ) ]:", self.punct)
        f.addRow("Таб в образце =", self.tab_w)
        f.addRow("Мин. интервал нажатий:", self.key_gap)
        f.addRow(self.fast_indent)
        f.addRow(self.indent_tab)
        f.addRow(self.whole_lines)
        f.addRow(self.strip_comments)
        f.addRow("Профиль окна:", self.profile)
        f.addRow(self.esc)
        hint = QLabel("<b>IDE</b>: убирает автоотступы и автоскобки редактора, чтобы код "
                      "получился точно как в образце. <b>Блокнот</b>: печать «как есть».")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        f.addRow(hint)
        tabs.addTab(w, "Печать")

        # ---- имитация ручного ввода
        w = QWidget()
        f = QFormLayout(w)
        self.human = QCheckBox("Имитация ручного ввода")
        self.human.setChecked(s.human_typing)
        self.typos = _spin(0, 30, s.typo_per_100_words, " на 100 слов")
        self.typos.setToolTip("0 — без опечаток. Опечатки только в словах из букв; "
                              "скобки, кавычки, отступы и Enter никогда не задеваются.")
        self.think = QDoubleSpinBox()
        self.think.setRange(0, 10)
        self.think.setSingleStep(0.5)
        self.think.setDecimals(1)
        self.think.setSuffix(" с")
        self.think.setValue(s.think_pause_s)
        self.think.setToolTip("0 — без пауз. Перед новым куском кода (после пустой строки, "
                              "перед def/class/for/if) пауза дольше.")
        f.addRow(self.human)
        f.addRow("Опечатки:", self.typos)
        f.addRow("Обдумывание строки:", self.think)
        hint = QLabel(
            "Как набирает человек:<br>"
            "• <b>неровный ритм</b> — знакомые слова (print, return, self) быстрой очередью, первая буква "
            "слова, заглавные и символы с Shift — медленнее, темп плавно «гуляет»;<br>"
            "• <b>обдумывание</b> — пауза перед новой строкой, дольше перед новым куском кода, "
            "иногда заминка между словами;<br>"
            "• <b>опечатки</b> — соседняя клавиша, перестановка букв, двойное нажатие; ошибка "
            "замечается через 0–2 буквы и исправляется Backspace.<br>"
            "«Разброс темпа» на вкладке «Печать» задаёт неровность ритма. Из-за пауз набор "
            "идёт медленнее заданной скорости.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        f.addRow(hint)
        for wdg in (self.typos, self.think):
            wdg.setEnabled(s.human_typing)
            self.human.toggled.connect(wdg.setEnabled)
        tabs.addTab(w, "Как человек")

        # ---- звук
        w = QWidget()
        f = QFormLayout(w)
        self.snd = QCheckBox("Звук клавиш")
        self.snd.setChecked(s.sound_enabled)
        self.style = QComboBox()
        for k, v in STYLES.items():
            self.style.addItem(v, k)
        self.style.setCurrentIndex(max(0, self.style.findData(s.sound_style)))
        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(s.sound_volume)
        test = QPushButton("▶ Проба")
        test.clicked.connect(lambda: self.test_sound.emit(self.style.currentData(), self.vol.value()))
        vrow = QHBoxLayout()
        vrow.addWidget(self.vol, 1)
        vrow.addWidget(test)
        f.addRow(self.snd)
        f.addRow("Звук:", self.style)
        f.addRow("Громкость:", vrow)
        tabs.addTab(w, "Звук")

        # ---- поведение
        w = QWidget()
        f = QFormLayout(w)
        self.hk_delay = _spin(0, 3000, s.hotkey_start_delay_ms, " мс", 50)
        self.countdown = _spin(0, 10, s.button_countdown_s, " с")
        self.minimize = QCheckBox("Сворачивать окно при старте кнопкой (фокус вернётся в прошлое окно)")
        self.minimize.setChecked(s.minimize_on_button_start)
        self.autopause = QCheckBox("Пауза, если сменилось активное окно")
        self.autopause.setChecked(s.autopause_on_focus_change)
        self.guard = QCheckBox("Пауза, если во время печати нажата клавиша или кнопка мыши\n"
                               "(случайная клавиша не попадёт в код)")
        self.guard.setChecked(s.guard_enabled)
        self.advance = QCheckBox("По окончании переходить к следующему блоку кода")
        self.advance.setChecked(s.auto_advance)
        self.on_top = QCheckBox("Окно поверх остальных")
        self.on_top.setChecked(s.always_on_top)
        f.addRow("Задержка старта по хоткею:", self.hk_delay)
        f.addRow("Отсчёт при старте кнопкой:", self.countdown)
        for cb in (self.minimize, self.autopause, self.guard, self.advance, self.on_top):
            f.addRow(cb)
        tabs.addTab(w, "Поведение")

        # ---- обновления
        w = QWidget()
        f = QFormLayout(w)
        self.upd_auto = QCheckBox("Проверять обновления автоматически")
        self.upd_auto.setChecked(s.update_auto_check)
        self.upd_interval = QComboBox()
        for k, v in INTERVALS.items():
            self.upd_interval.addItem(v, k)
        if self.upd_interval.findData(s.update_interval_h) < 0:   # своё значение из settings.json — не терять
            self.upd_interval.addItem(f"Каждые {s.update_interval_h} ч", s.update_interval_h)
        self.upd_interval.setCurrentIndex(self.upd_interval.findData(s.update_interval_h))
        self.upd_mode = QComboBox()
        # собранный .exe сам себя не заменит — ему доступно только «сообщить»
        modes = {MODE_NOTIFY: UPDATE_MODES[MODE_NOTIFY]} if install_mode() == MODE_FROZEN else UPDATE_MODES
        for k, v in modes.items():
            self.upd_mode.addItem(v, k)
        self.upd_mode.setCurrentIndex(max(0, self.upd_mode.findData(s.update_mode)))
        self.upd_mode.setToolTip("Обновление никогда не ставится во время печати и не прерывает занятие: "
                                 "в худшем случае новая версия запустится в следующий раз.")
        self.upd_beta = QCheckBox("Предлагать бета-версии (pre-release)")
        self.upd_beta.setChecked(s.update_prerelease)
        for wdg in (self.upd_interval, self.upd_mode):
            wdg.setEnabled(s.update_auto_check)
            self.upd_auto.toggled.connect(wdg.setEnabled)

        last = (time.strftime("%d.%m.%Y %H:%M", time.localtime(s.update_last_check))
                if s.update_last_check else "ещё не было")
        info = QLabel(f"Установлена версия <b>{__version__}</b> · последняя проверка: {last}")
        info.setTextFormat(Qt.TextFormat.RichText)

        btn_check = QPushButton("Проверить сейчас")
        btn_check.clicked.connect(self.check_updates)
        brow = QHBoxLayout()
        brow.addWidget(btn_check)
        brow.addStretch(1)

        f.addRow(self.upd_auto)
        f.addRow("Как часто:", self.upd_interval)
        f.addRow("Найдя новую версию:", self.upd_mode)
        f.addRow(self.upd_beta)
        f.addRow(info)
        f.addRow(brow)

        self._unskip = False
        if s.update_skip_version:
            unskip = QPushButton(f"Снова предлагать версию {s.update_skip_version}")
            unskip.clicked.connect(lambda: (setattr(self, "_unskip", True), unskip.setEnabled(False)))
            f.addRow(unskip)

        note = QLabel("Ваши образцы и настройки при обновлении не меняются. Во время печати программа "
                      "не обновляется и не отвлекает уведомлениями.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        f.addRow(note)
        tabs.addTab(w, "Обновления")

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(bb)
        self.result_settings: Settings | None = None
        self._base = s

    def _accept(self) -> None:
        values = {k: e.value() for k, e in self.hk.items()}
        used = {}
        for k, v in values.items():
            if not v:
                continue
            if parse_hotkey(v) is None:
                QMessageBox.warning(self, "Хоткей", f"Сочетание «{v}» не поддерживается.")
                return
            if v in used:
                QMessageBox.warning(self, "Хоткей", f"«{v}» назначен дважды.")
                return
            used[v] = k
        if not values["hotkey_toggle"]:
            QMessageBox.warning(self, "Хоткей", "Нужен хоткей «Старт / пауза».")
            return
        s = Settings(**asdict(self._base))
        for k, v in values.items():
            setattr(s, k, v)
        s.cpm = self.cpm.value()
        s.jitter = self.jitter.value()
        s.newline_pause_ms = self.nl_pause.value()
        s.punct_pause_ms = self.punct.value()
        s.tab_width = self.tab_w.value()
        s.key_gap_ms = self.key_gap.value()
        s.fast_indent = self.fast_indent.isChecked()
        s.indent_with_tab = self.indent_tab.isChecked()
        s.selection_whole_lines = self.whole_lines.isChecked()
        s.strip_comments = self.strip_comments.isChecked()
        s.human_typing = self.human.isChecked()
        s.typo_per_100_words = self.typos.value()
        s.think_pause_s = float(self.think.value())
        s.profile = self.profile.currentData() or PROFILE_IDE
        s.esc_before_enter = self.esc.isChecked()
        s.sound_enabled = self.snd.isChecked()
        s.sound_style = self.style.currentData()
        s.sound_volume = self.vol.value()
        s.hotkey_start_delay_ms = self.hk_delay.value()
        s.button_countdown_s = self.countdown.value()
        s.minimize_on_button_start = self.minimize.isChecked()
        s.autopause_on_focus_change = self.autopause.isChecked()
        s.guard_enabled = self.guard.isChecked()
        s.auto_advance = self.advance.isChecked()
        s.always_on_top = self.on_top.isChecked()
        s.update_auto_check = self.upd_auto.isChecked()
        s.update_interval_h = self.upd_interval.currentData()
        s.update_mode = self.upd_mode.currentData() or MODE_DOWNLOAD
        s.update_prerelease = self.upd_beta.isChecked()
        if self._unskip:
            s.update_skip_version = ""
        self.result_settings = s
        self.accept()
