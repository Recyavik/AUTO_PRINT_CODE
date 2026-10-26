"""Настройки: мониторы (демонстрация / управление), заставка перерыва, напоминания."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import Qt
from shiboken6 import isValid
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSpinBox, QVBoxLayout)

from ..model import DEMO_OFF, Activity, Segment
from ..store import MEDIA_DIR, Settings, existing, portable, resolve
from . import screens
from .editor import finish_on_enter
from .notify import Notifier, parse_pos
from .overlay import BreakOverlay


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройки таймера")
        # модально только для главного окна: карточки напоминаний и заставка остаются нажимаемыми
        # (по умолчанию exec() блокирует щелчки во все окна программы — кнопки пробы не нажимались)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(620, 0)
        self.s = copy.deepcopy(settings)
        self._probe: list = []

        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.demo = QComboBox()
        self.control = QComboBox()
        for sc in screens.screens():
            self.demo.addItem(screens.describe(sc), sc.name())
            self.control.addItem(screens.describe(sc), sc.name())
        self.demo.setCurrentIndex(max(0, self.demo.findData(screens.demo_screen(self.s).name())))
        self.control.setCurrentIndex(max(0, self.control.findData(screens.control_screen(self.s).name())))
        form.addRow("Монитор демонстрации:", self.demo)
        form.addRow("Монитор управления:", self.control)
        hint = QLabel("На мониторе демонстрации — то, что видят зрители: туда выводится заставка перерыва. "
                      "Напоминания появляются только на мониторе управления.", objectName="hint")
        hint.setWordWrap(True)
        form.addRow(hint)

        probe = QHBoxLayout()
        ident = QPushButton("Показать номера мониторов")
        ident.clicked.connect(lambda: self._keep(screens.identify(self._collect())))
        test_note = QPushButton("Проба напоминания")
        test_note.clicked.connect(self._test_note)
        test_break = QPushButton("Проба заставки (10 с)")
        test_break.clicked.connect(self._test_break)
        reset = QPushButton("Сбросить позиции напоминаний и пульта")
        reset.setToolTip("Напоминания — снова в правом верхнем углу монитора управления, пульт видео — внизу по центру")
        reset.clicked.connect(self._reset_pos)
        for b in (ident, test_note, test_break):
            probe.addWidget(b)
        probe.addStretch(1)
        form.addRow(probe)
        form.addRow(reset)

        self.image = self._file_row(form, "Фон перерыва:", self.s.break_image,
                                    "без картинки — встроенный фиолетовый фон", "Картинки (*.png *.jpg *.jpeg *.bmp *.webp)")
        self.eyes = self._file_row(form, "Гимнастика для глаз:", self.s.eyes_media,
                                   "видео или картинка — по «Далее» в напоминании о зарядке",
                                   "Видео и картинки (*.mp4 *.mov *.avi *.mkv *.webm *.wmv *.m4v *.png *.jpg *.jpeg)")

        self.heads = QSpinBox()
        self.heads.setRange(0, 15)
        self.heads.setSuffix(" мин")
        self.heads.setSpecialValueText("не предупреждать")
        self.heads.setValue(self.s.heads_up_min)
        form.addRow("Предупреждать заранее:", self.heads)
        self.sound = QCheckBox("Звук при напоминании")
        self.sound.setChecked(self.s.sound)
        form.addRow(self.sound)
        self.toast = QCheckBox("Дублировать уведомлением Windows (оно появляется на основном мониторе)")
        self.toast.setChecked(self.s.windows_toast)
        form.addRow(self.toast)
        lay.addLayout(form)

        foot = QHBoxLayout()
        foot.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Сохранить", objectName="primary")
        ok.clicked.connect(self.accept)
        foot.addWidget(cancel)
        foot.addWidget(ok)
        lay.addLayout(foot)
        for b in self.findChildren(QPushButton):   # Enter в поле не жмёт кнопки («Выбрать…», пробы)
            b.setAutoDefault(False)
            b.setDefault(False)

    def keyPressEvent(self, e) -> None:
        if not finish_on_enter(self, e):
            super().keyPressEvent(e)

    def _reset_pos(self) -> None:
        self.s.note_pos = self.s.player_pos = ""
        if hasattr(self, "_notifier"):
            self._notifier.anchor = None
            self._notifier.layout()

    def _keep(self, widgets) -> None:
        # окна проб удаляют себя сами (номера мониторов — через 3 с): держим только живые
        self._probe = [w for w in self._probe if isValid(w)] + list(widgets)

    def _file_row(self, form: QFormLayout, label: str, value: str, placeholder: str, filt: str) -> QLineEdit:
        row = QHBoxLayout()
        edit = QLineEdit(value)
        edit.setPlaceholderText(placeholder)
        pick = QPushButton("Выбрать…")
        pick.clicked.connect(lambda: self._pick(edit, label, filt))
        row.addWidget(edit, 1)
        row.addWidget(pick)
        form.addRow(label, row)
        return edit

    def _pick(self, edit: QLineEdit, title: str, filt: str) -> None:
        start = str(Path(resolve(edit.text())).parent) if edit.text() else str(MEDIA_DIR)
        path, _ = QFileDialog.getOpenFileName(self, title.rstrip(":"), start, filt)
        if path:
            edit.setText(portable(path))   # из папки media — относительным путём: папку можно перенести

    def _collect(self) -> Settings:
        s = self.s
        s.demo_screen = self.demo.currentData() or ""
        s.control_screen = self.control.currentData() or ""
        s.break_image = self.image.text().strip()
        s.eyes_media = self.eyes.text().strip()
        s.heads_up_min = self.heads.value()
        s.sound = self.sound.isChecked()
        s.windows_toast = self.toast.isChecked()
        return s

    def _test_note(self) -> None:
        now = datetime.now()
        if not hasattr(self, "_notifier"):   # один на окно настроек: кнопки карточек ссылаются на него
            self._notifier = Notifier(lambda: screens.control_screen(self._collect()), datetime.now)
            self._notifier.anchor = parse_pos(self.s.note_pos)
            # проба тоже перетаскивается — так удобно выбрать место до эфира
            self._notifier.on_moved = lambda a: setattr(self.s, "note_pos", f"{a.x()},{a.y()}" if a else "")
        self._notifier.show(Segment(0, Activity("Зарядка для глаз (проба)", DEMO_OFF, 5), now,
                                    now + timedelta(minutes=5)), False)

    def _test_break(self) -> None:
        s = self._collect()
        now = datetime.now()
        o = BreakOverlay(screens.demo_screen(s), now + timedelta(seconds=10), datetime.now, existing(s.break_image),
                         "Перерыв")
        o.show()
        o.raise_()
        self._keep([o])

    def done(self, r: int) -> None:
        if hasattr(self, "_notifier"):
            self._notifier.clear()
        for w in self._probe:
            if isValid(w):          # уже удалённое окно закрывать нельзя — иначе «Сохранить» не закрывало окно
                w.close()
        self._probe.clear()
        super().done(r)

    def result_settings(self) -> Settings:
        return self._collect()
