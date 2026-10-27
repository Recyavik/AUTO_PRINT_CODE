"""Настройки: мониторы (демонстрация / управление), заставка перерыва, напоминания."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QSlider, QSpinBox, QVBoxLayout)
from shiboken6 import isValid

from .. import __version__, chime, updater
from ..model import DEMO_OFF, Activity, Segment
from ..store import MEDIA_DIR, Settings, existing, portable, resolve
from . import screens, style
from .editor import finish_on_enter
from .lessons import LessonLengthEdit
from .notify import Notifier, parse_pos
from .overlay import BreakOverlay


class SettingsDialog(QDialog):
    install_started = Signal()          # запущен установщик обновления — таймеру пора закрыться

    def __init__(self, settings: Settings, parent=None, release=None, is_live=lambda: False) -> None:
        """release — уже найденное обновление (из автопроверки); is_live() — идёт ли эфир."""
        super().__init__(parent)
        self.release, self.is_live = release, is_live
        self._thread = None
        self.setWindowTitle("Настройки таймера")
        # кнопка «Развернуть»: на весь экран и обратно к прежнему размеру (и двойной щелчок по заголовку)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
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
        reset.setToolTip("Напоминания — снова в правом верхнем углу монитора управления, пульты видео и перерыва — внизу по центру")
        reset.clicked.connect(self._reset_pos)
        for b in (ident, test_note, test_break):
            probe.addWidget(b)
        probe.addStretch(1)
        form.addRow(probe)
        form.addRow(reset)

        self.image = self._file_row(form, "Фон перерыва:", self.s.break_image,
                                    "без картинки — встроенный фиолетовый фон", "Картинки (*.png *.jpg *.jpeg *.bmp *.webp)")
        # цвет надписей заставки: образец-кнопка открывает выбор цвета, «Белый» — как было по умолчанию
        self.text_color = self.s.break_text_color
        self.color_btn = QPushButton()
        self.color_btn.setFixedWidth(120)
        self.color_btn.setToolTip("Цвет «ПЕРЕРЫВ», отсчёта и «ПРОДОЛЖАЕМ» на заставке. Проверить — «Проба заставки».")
        self.color_btn.clicked.connect(self._pick_color)
        white = QPushButton("Белый")
        white.clicked.connect(lambda: self._set_color("#FFFFFF"))
        crow = QHBoxLayout()
        crow.addWidget(self.color_btn)
        crow.addWidget(white)
        crow.addStretch(1)
        form.addRow("Цвет надписей заставки:", crow)
        self._set_color(self.text_color)
        self.eyes = self._file_row(form, "Гимнастика для глаз:", self.s.eyes_media,
                                   "видео или картинка — кнопкой «▶ Показать видео» в напоминании о зарядке",
                                   "Видео и картинки (*.mp4 *.mov *.avi *.mkv *.webm *.wmv *.m4v *.png *.jpg *.jpeg)")

        self.lesson = LessonLengthEdit()
        self.lesson.setValue(self.s.lesson_min)
        self.lesson.setToolTip("Предел каждой части занятия: до перерыва и после него (академический час — 45 мин).<br>"
                               "В редакторе шаблона минуты блока нельзя увеличить сверх него. Для всех шаблонов, у которых не задана своя.")
        form.addRow("Продолжительность урока:", self.lesson)

        self.theme = QComboBox()
        for key, title in style.THEME_NAMES.items():
            self.theme.addItem(title, key)
        self.theme.setCurrentIndex(max(0, self.theme.findData(self.s.theme)))
        self.theme.setToolTip("Оформление окна таймера, карточек и пультов. Экран демонстрации от темы не зависит.")
        form.addRow("Тема:", self.theme)

        self.heads = QSpinBox()
        self.heads.setRange(0, 15)
        self.heads.setSuffix(" мин")
        self.heads.setSpecialValueText("не предупреждать")
        self.heads.setValue(self.s.heads_up_min)
        form.addRow("Предупреждать заранее:", self.heads)
        self.sound = QCheckBox("Звук напоминаний")
        self.sound.setChecked(self.s.sound)
        self.sound.setToolTip("Мягкий колокольчик, когда появляется напоминание. Снимите галочку — напоминания без звука.")
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(5, 100)
        self.volume.setSingleStep(5)
        self.volume.setValue(max(5, self.s.sound_volume))
        self.volume.setToolTip("Громкость колокольчика")
        self.volume.sliderReleased.connect(lambda: chime.play(self.volume.value()))
        try_btn = QPushButton("▶ Проба")
        try_btn.clicked.connect(lambda: chime.play(self.volume.value()))
        self.sound.toggled.connect(self.volume.setEnabled)
        self.sound.toggled.connect(try_btn.setEnabled)
        self.volume.setEnabled(self.s.sound)
        try_btn.setEnabled(self.s.sound)
        snd = QHBoxLayout()
        snd.addWidget(self.sound)
        snd.addWidget(self.volume, 1)
        snd.addWidget(try_btn)
        form.addRow(snd)
        self.toast = QCheckBox("Дублировать уведомлением Windows (оно появляется на основном мониторе)")
        self.toast.setChecked(self.s.windows_toast)
        form.addRow(self.toast)
        lay.addLayout(form)
        self._build_updates(lay)

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
        s.break_text_color = self.text_color
        s.eyes_media = self.eyes.text().strip()
        s.heads_up_min = self.heads.value()
        s.lesson_min = self.lesson.value()
        s.sound = self.sound.isChecked()
        s.sound_volume = self.volume.value()
        s.windows_toast = self.toast.isChecked()
        s.auto_update_check = self.auto_update.isChecked()
        s.theme = self.theme.currentData()
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

    def _set_color(self, name: str) -> None:
        self.text_color = QColor(name).name().upper() if QColor.isValidColorName(name) else "#FFFFFF"
        c = QColor(self.text_color)
        ink = "#000000" if c.lightness() > 140 else "#FFFFFF"   # подпись на образце читается на любом цвете
        self.color_btn.setText(self.text_color)
        self.color_btn.setStyleSheet(f"background: {self.text_color}; color: {ink}; border: 1px solid #888; font-weight: 600;")

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(QColor(self.text_color), self, "Цвет надписей заставки")
        if c.isValid():
            self._set_color(c.name())

    def _test_break(self) -> None:
        s = self._collect()
        now = datetime.now()
        o = BreakOverlay(screens.demo_screen(s), now + timedelta(seconds=10), datetime.now, existing(s.break_image),
                         "Перерыв", s.break_text_color)
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

    # ---------------------------------------------------------------- обновления
    def _build_updates(self, lay: QVBoxLayout) -> None:
        box = QGroupBox("Обновления")
        bl = QVBoxLayout(box)
        row = QHBoxLayout()
        row.addWidget(QLabel(f"Установлена версия {__version__}"))
        row.addStretch(1)
        self.check_btn = QPushButton("Проверить обновления")
        self.check_btn.clicked.connect(self.check_updates)
        self.install_btn = QPushButton(objectName="primary")
        self.install_btn.clicked.connect(self.install_update)
        self.install_btn.hide()
        row.addWidget(self.check_btn)
        row.addWidget(self.install_btn)
        bl.addLayout(row)
        self.update_status = QLabel(objectName="hint")
        self.update_status.setWordWrap(True)
        bl.addWidget(self.update_status)
        self.auto_update = QCheckBox("Проверять обновления автоматически — сообщу, когда выйдет новая версия")
        self.auto_update.setChecked(self.s.auto_update_check)
        bl.addWidget(self.auto_update)
        lay.addWidget(box)
        if not updater.can_update():
            self.check_btn.setEnabled(False)
            self.update_status.setText("Обновления ставятся в установленной версии таймера. "
                                       "Запуск из исходников обновляется через git pull.")
        elif self.release is not None:
            self._show_release(self.release)

    def check_updates(self) -> None:
        self.check_btn.setEnabled(False)
        self.update_status.setText("Проверяю…")
        self._thread = updater.CheckThread(self)
        self._thread.found.connect(self._show_release)
        self._thread.failed.connect(lambda e: self._update_failed("Не удалось проверить обновления", e))
        self._thread.start()

    def _show_release(self, rel) -> None:
        self.check_btn.setEnabled(True)
        self.release = rel
        if rel is None:
            self.update_status.setText("Установлена последняя версия.")
            self.install_btn.hide()
            return
        notes = rel.notes.strip()
        self.update_status.setText(f"Доступна версия {rel.version}." + (f"\n{notes}" if notes else ""))
        self.install_btn.setText(f"⬇ Установить {rel.version}")
        self.install_btn.show()

    def _update_failed(self, what: str, err: str) -> None:
        self.check_btn.setEnabled(True)
        self.install_btn.setEnabled(True)
        self.update_status.setText(f"{what}: {err}. Проверьте интернет и попробуйте ещё раз.")

    def install_update(self) -> None:
        """Скачать и поставить. Во время эфира — нет: установка закрывает таймер."""
        if self.is_live():
            self.update_status.setText("Идёт эфир — обновление можно поставить после него "
                                       "(или остановите эфир). Установка закрывает таймер на полминуты.")
            return
        self.install_btn.setEnabled(False)
        self.update_status.setText("Скачиваю обновление…")
        self._thread = updater.DownloadThread(self.release, self)
        self._thread.progress.connect(lambda p: self.update_status.setText(f"Скачиваю обновление… {p}%"))
        self._thread.failed.connect(lambda e: self._update_failed("Не удалось скачать обновление", e))
        self._thread.done.connect(self._run_installer)
        self._thread.start()

    def _run_installer(self, path) -> None:
        self.update_status.setText("Устанавливаю — таймер закроется и откроется уже обновлённым.")
        updater.install(path)
        self.install_started.emit()

    def result_settings(self) -> Settings:
        return self._collect()
