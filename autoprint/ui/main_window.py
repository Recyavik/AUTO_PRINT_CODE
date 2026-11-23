"""Окно программы: список уроков, строка печати, трей. Урок готовят и ведут на экране урока (в браузере,
lesson_control); печать по хоткеям — print_control."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidgetItem, QMenu,
                               QMessageBox, QProgressBar, QSystemTrayIcon, QToolButton, QVBoxLayout)

from .. import APP_NAME, __version__, system, taskbar, updater
from ..guard import InputGuard
from ..hotkeys import HotkeyManager, parse_hotkey
from ..importers import export_ipynb
from ..storage import Settings, Template, TemplateStore, steps_sample_template
from ..typer import COUNTDOWN, FINISHED, IDLE, LINE_WAIT, PAUSED, RUNNING
from . import icons, logo
from .efir_control import EfirController
from .frameless import FramelessWindow
from .lesson_control import LessonController
from .library import ROLE_ID, ROLE_LIVE, ROLE_META, LibraryPanel, lesson_meta
from .print_control import BUSY, MODE_BLOCK, MODE_LINES, MODE_STEPS, PrintController, app_name  # noqa: F401
from .settings_window import HOTKEYS, SettingsWindow
from .theme import STATE_TOKENS, theme
from .updates import MODE_AUTO, MODE_DOWNLOAD, UpdateDialog, UpdateManager
from .widgets import IconButton, Toast, button, install_wheel_guard

log = logging.getLogger("autoprint")

STATE_TEXT = {IDLE: "Готов", COUNTDOWN: "Отсчёт…", RUNNING: "Печатает", PAUSED: "Пауза", FINISHED: "Готово",
              LINE_WAIT: "Ждёт Enter"}

def apply_migrations(s: Settings, store: TemplateStore | None = None) -> bool:
    """Разовые переделки настроек и базы при обновлении (autoprint/migrations.py). True — что-то поменялось."""
    from .. import migrations
    return migrations.apply(s, store)


def efir_token(phase: str, mode: str) -> str:
    """Цвет кнопки «Эфир»: обычный — эфира нет или он кончился, жёлтый — до начала, перерыв или зарядка,
    красный — эфир идёт."""
    if mode in ("break", "exercise"):
        return "accent"
    return {"before": "accent", "live": "live"}.get(phase, "dim")


def title_logo_icon():
    """Знак программы в шапке — фирменный, одинаковый в обеих темах (как на панели задач)."""
    return logo.make_icon(logo.APP)


class PrintBar(QFrame):
    """Строка печати внизу окна: что печатается и сколько, «Пауза» и «Стоп». Видна только во время печати."""

    def __init__(self, printer: PrintController) -> None:
        super().__init__()
        self.printer = printer
        self.setObjectName("printBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 10)
        lay.setSpacing(8)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.text = QLabel()
        self.text.setObjectName("printBarText")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        col.addWidget(self.text)
        col.addWidget(self.bar)
        lay.addLayout(col, 1)
        self.btn_pause = button("Пауза", "pause")
        self.btn_pause.clicked.connect(lambda: printer.toggle())
        self.btn_stop = button("Стоп", "stop")
        self.btn_stop.clicked.connect(printer.stop)
        lay.addWidget(self.btn_pause)
        lay.addWidget(self.btn_stop)
        self.hide()

    def refresh(self) -> None:
        p = self.printer
        st = p.engine.state
        if st not in BUSY or not p.job:
            self.hide()
            return
        t, b = p.find_block(p.job["bid"])
        name = b.display_title(t.code_number(b)) if b and t else "код"
        snap = p.snapshot()
        extra = ""
        if snap.get("step"):
            extra = f" · шаг {snap['step']['i']} из {snap['step']['n']}"
        elif snap.get("line"):
            extra = f" · строка {snap['line']['i']} из {snap['line']['n']}"
        where = f" → {p.target}" if p.target else ""
        self.text.setText(f"{STATE_TEXT.get(st, st)}: {name}{extra} · {round(snap['progress'] * 100)}%{where}")
        self.bar.setValue(int(snap["progress"] * 1000))
        self.btn_pause.setText("Продолжить" if st == PAUSED else ("Дальше" if st == LINE_WAIT else "Пауза"))
        self.show()


class MainWindow(FramelessWindow):
    def __init__(self, settings: Settings, store: TemplateStore) -> None:
        super().__init__(APP_NAME)
        self.settings = settings
        self.store = store
        self._migrated = apply_migrations(settings, store)
        install_wheel_guard(QApplication.instance())   # колесо не меняет счётчики и списки без щелчка по ним
        self.tray_icons = {k: logo.make_icon(k) for k in (logo.IDLE, logo.RUNNING, logo.PAUSED)}
        self.setWindowIcon(logo.make_icon(logo.APP))
        self.resize(520, 720)
        self.setMinimumSize(420, 480)

        self.guard = InputGuard()
        self.printer = PrintController(settings, store, self.guard, self)
        self.engine = self.printer.engine
        self.printer.notify.connect(lambda text, warn, quiet: self._notify(text, warn=warn, quiet=quiet))
        self.printer.state.connect(self._on_state)
        self.printer.changed.connect(self._on_print_changed)
        self.printer.store_changed.connect(lambda: self._save_timer.start())
        self.printer.settings_touched.connect(self._settings_touched)

        self.hotkeys = HotkeyManager()
        self.hotkeys.triggered.connect(self._on_hotkey)
        self.hotkeys.failed.connect(lambda t: self._notify(
            f"Не удалось занять хоткеи: {t} (заняты другой программой?). Смените их в настройках.", warn=True))

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(700)
        self._save_timer.timeout.connect(self._save_store)
        self._settings_timer = QTimer(self)
        self._settings_timer.setSingleShot(True)
        self._settings_timer.setInterval(400)
        self._settings_timer.timeout.connect(self._save_settings)

        self.updates = UpdateManager(settings, self)
        self.updates.checked.connect(self._on_update_checked)
        self.updates.check_failed.connect(self._on_update_check_failed)
        self.updates.ready.connect(self._on_update_ready)
        self.updates.download_failed.connect(lambda t: log.warning("Обновление не скачано: %s", t))
        self.relaunch_requested = False   # app.py перезапустит программу после выхода
        self._auto_checked_once = False
        self.settings_win: SettingsWindow | None = None

        self.efir = EfirController(self)    # «Эфир»: шаблоны вебинаров, таймер, вкладка эфира
        self.efir.message.connect(lambda t, warn: self._notify(t, warn=warn))
        self.printer.live_id = self.efir.live_lesson_id
        self.lesson = LessonController(self)   # экран урока: страница в браузере, время — от «Эфира»
        self._build_ui()
        self._build_tray()
        theme.changed.connect(self._on_theme)
        self._on_theme()
        self._apply_settings()
        self._apply_hotkeys()
        self._restore_session()
        self.efir.live_changed.connect(self._refresh_live_mark)
        QTimer.singleShot(1200, self.efir.restore)   # эфир шёл до перезапуска — вернуть таймер

        # автопроверка: вскоре после запуска, затем раз в час смотрим, не пора ли
        QTimer.singleShot(8000, self._auto_check_updates)
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(3600 * 1000)
        self._update_timer.timeout.connect(self._auto_check_updates)
        self._update_timer.start()
        QTimer.singleShot(1500, self._show_update_result)

    # ================================================================ UI
    def _build_ui(self) -> None:
        tb = self.titlebar
        self.logo_btn = QToolButton()
        self.logo_btn.setObjectName("logoBtn")
        self.logo_btn.setIconSize(QSize(18, 18))
        self.logo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.logo_btn.setToolTip("Меню программы")
        self.logo_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.logo_menu = QMenu(self.logo_btn)
        self.logo_menu.aboutToShow.connect(self._fill_logo_menu)
        self.logo_btn.setMenu(self.logo_menu)
        tb.left.addWidget(self.logo_btn)
        self.btn_settings = IconButton("settings", "Настройки (Ctrl+,)", 17, box=32)
        self.btn_settings.setObjectName("titleTool")
        self.btn_settings.clicked.connect(lambda: self.open_settings())
        self.btn_about = IconButton("info", "О программе", 17, box=32)
        self.btn_about.setObjectName("titleTool")
        self.btn_about.clicked.connect(lambda: self.open_settings("about"))
        self.btn_report = IconButton("bug", "Сообщить об ошибке", 17, box=32)
        self.btn_report.setObjectName("titleTool")
        self.btn_report.clicked.connect(self.open_report)
        # «Эфир» — плашкой сверху: шаблоны вебинаров, таймер и вкладка эфира для учеников
        self.btn_efir = QToolButton()
        self.btn_efir.setObjectName("efirBtn")
        self.btn_efir.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_efir.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_efir.setIconSize(QSize(16, 16))
        self.btn_efir.setToolTip("Эфир: таймер вебинара и экран для учеников — фон, зарядка, перерыв")
        self.btn_efir.clicked.connect(self._efir_clicked)
        self.btn_efir.setFixedHeight(32)
        self.btn_efir.setMaximumWidth(260)
        tb.right.addWidget(self.btn_efir)
        tb.right.addSpacing(8)
        self._efir_timer = QTimer(self)
        self._efir_timer.setInterval(1000)
        self._efir_timer.timeout.connect(self._update_efir_pill)
        self._efir_timer.start()
        self.efir.live_changed.connect(self._update_efir_pill)
        tb.right.addWidget(self.btn_report)
        tb.right.addWidget(self.btn_settings)
        tb.right.addWidget(self.btn_about)

        self.body.setObjectName("appRoot")
        self.body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        root = QVBoxLayout(self.body)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.library = LibraryPanel()
        lib = self.library.list
        lib.itemChanged.connect(self._on_library_renamed)
        lib.customContextMenuRequested.connect(self._library_menu)
        self.library.search.textChanged.connect(self._filter_library)
        self.library.open_requested.connect(self._open_selected)
        self.library.new_requested.connect(self.new_template)
        self.library.import_requested.connect(lambda: self.import_files())
        self.library.ai_requested.connect(lambda: self.import_files("ai"))
        self.library.update_clicked.connect(self.open_update_dialog)
        root.addWidget(self.library, 1)
        self.print_bar = PrintBar(self.printer)
        root.addWidget(self.print_bar)
        self.toast = Toast(self.body)

        sc = [("Ctrl+N", self.new_template), ("Ctrl+O", lambda: self.import_files()), ("Ctrl+Q", self.quit_app),
              ("Ctrl+,", lambda: self.open_settings()), ("F1", lambda: self.open_settings("about"))]
        for seq, slot in sc:
            QShortcut(QKeySequence(seq), self, slot)

    def _fill_logo_menu(self) -> None:
        # сочетания здесь — только подпись («\t…»): сами клавиши — QShortcut окна
        m = self.logo_menu
        m.clear()
        m.addAction(icons.icon("settings"), "Настройки…\tCtrl+,", lambda: self.open_settings())
        m.addAction(icons.icon("info"), "О программе", lambda: self.open_settings("about"))
        m.addAction(icons.icon("help"), "Как пользоваться\tF1", lambda: self.open_settings("about"))
        m.addAction(icons.icon("refresh"), "Проверить обновления…", lambda: self.check_updates(manual=True))
        m.addSeparator()
        m.addAction(icons.icon("plus"), "Новый урок\tCtrl+N", self.new_template)
        m.addAction(icons.icon("import"), "Импорт…\tCtrl+O", lambda: self.import_files())
        m.addAction(icons.icon("sparkles"), "Урок из методички (нейросеть)…", lambda: self.import_files("ai"))
        t = self._selected()
        if t is not None:
            self._export_menu(m.addMenu(icons.icon("export"), "Экспорт урока"), t)
        m.addSeparator()
        m.addAction(icons.icon("presentation"), "Экран урока", self._open_selected)
        m.addAction(icons.icon("radio"), "Эфир — шаблоны вебинаров…", self.efir.show_window)
        m.addAction(icons.icon("bug"), "Сообщить об ошибке…", self.open_report)
        m.addAction(icons.icon("file-text"), "Журнал работы", self._open_log)
        m.addAction(icons.icon("folder"), "Папка с данными", self._open_data_dir)
        m.addSeparator()
        m.addAction(icons.icon("logout"), "Выход\tCtrl+Q", self.quit_app)

    def _export_menu(self, m: QMenu, t: Template) -> None:
        m.addAction("Урок в Markdown (.md, с картинками рядом)…", lambda: self.export_template(t, "md"))
        m.addAction("Урок в .ipynb…", lambda: self.export_template(t, "ipynb"))
        m.addAction("Тетрадка для учеников (.ipynb, только код)…", lambda: self.export_template(t, "students"))
        m.addAction("Урок в .json…", lambda: self.export_template(t, "json"))

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(self.tray_icons[logo.IDLE], self)
        menu = QMenu()
        menu.addAction("Показать окно", self._show_window)
        menu.addSeparator()
        menu.addAction("Старт / пауза", lambda: self.printer.toggle(
            countdown=max(1, int(self.settings.button_countdown_s)), pressed=True))
        menu.aboutToShow.connect(self.printer.remember_press)
        menu.addAction("Стоп", self.printer.stop)
        menu.addAction("Эфир…", self._efir_clicked)
        menu.addAction("Экран урока", self.lesson.open_page)
        menu.addSeparator()
        self.tray_update = menu.addAction("Обновление…", self.open_update_dialog)
        self.tray_update.setVisible(False)
        menu.addAction("Настройки…", lambda: self.open_settings())
        menu.addAction("Выход", self.quit_app)
        self.tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self._show_window()
                                    if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.setToolTip(APP_NAME)
        self.tray.show()
        self._quitting = False
        self._tray_hint_shown = False
        if self.settings.pin_tray_icon:   # значок у часов: запись в реестре появится после показа значка
            system.pin_tray_icon(True)
        if self.settings.autostart:      # путь программы мог измениться — обновить запись автозапуска
            system.set_autostart(True)

    def _on_theme(self) -> None:
        self.logo_btn.setIcon(title_logo_icon())
        self.restyle_frame()
        self._update_efir_pill()
        self._on_state(self.engine.state)
        self.library.list.viewport().update()

    # ================================================================ настройки
    def _apply_settings(self) -> None:
        s = self.settings
        theme.set_mode(s.theme)
        on_top = bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        if on_top != s.always_on_top:
            visible = self.isVisible()
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, s.always_on_top)  # пересоздаёт окно
            # свойства панели задач — до показа, иначе кнопка успеет появиться как «Python»
            self._apply_taskbar()
            if visible:
                self.show()
        self.printer.apply_settings()
        self._on_state(self.engine.state)

    def _apply_hotkeys(self) -> None:
        s = self.settings
        self.hotkeys.set_bindings({k: getattr(s, k) for k, _t, _i in HOTKEYS})
        self.guard.set_hotkeys({hk for k, _t, _i in HOTKEYS if (hk := parse_hotkey(getattr(s, k)))})

    def _save_settings(self) -> None:
        self._settings_timer.stop()
        self.settings.save()

    def _settings_touched(self) -> None:
        """Изменение с экрана урока: сохранить чуть позже и показать новое значение в окне настроек."""
        self._settings_timer.start()
        if self.settings_win:
            self.settings_win.reload()

    def _on_setting_changed(self, key: str) -> None:
        """Изменение из окна настроек."""
        s = self.settings
        self._settings_timer.start()
        if key == "sound_volume":   # ползунок шлёт много шагов — только громкость
            self.printer.on_settings_changed(key)
            return
        if key == "hotkeys":
            self._apply_hotkeys()
            self._set_title_status()
            self.lesson.schedule_publish()     # «Следующим · Ctrl+F9» на экране урока
            return
        if key == "update_skip_version" or key.startswith("update_"):
            return
        if key == "pin_tray_icon":
            system.pin_tray_icon(s.pin_tray_icon, wait_s=2.0)
            return
        if key == "autostart":
            if not system.set_autostart(s.autostart):
                s.autostart = system.autostart_enabled()   # переключатель — как на самом деле
                if self.settings_win:
                    self.settings_win.reload()
                self._notify("Не удалось изменить автозапуск (нет доступа к реестру).", warn=True)
            return
        if key in ("close_to_tray", "samples_seen"):
            return
        self.printer.on_settings_changed(key)
        self._apply_settings()

    def open_settings(self, page: str = "") -> None:
        if self.settings_win is None:
            # владелец — главное окно: иначе при «Окно поверх остальных» настройки окажутся под ним
            w = SettingsWindow(self.settings, self)
            w.setWindowIcon(self.windowIcon())
            w.changed.connect(self._on_setting_changed)
            w.test_sound.connect(self._test_sound)
            w.check_updates.connect(lambda: self.check_updates(manual=True))
            w.open_log.connect(self._open_log)
            w.open_data.connect(self._open_data_dir)
            w.hotkey_capture.connect(self._on_hotkey_capture)
            w.restart_requested.connect(self._restart_app)
            w.report_requested.connect(self.open_report)
            w.closed.connect(self._on_settings_closed)
            self.settings_win = w
            # поверх главного окна, по центру
            g = self.geometry()
            w.move(g.x() + (g.width() - w.width()) // 2, g.y() + max(0, (g.height() - w.height()) // 2))
        w = self.settings_win
        w.reload()
        if page:
            w.show_page(page)
        w.showNormal()
        w.raise_()
        w.activateWindow()

    def _on_settings_closed(self) -> None:
        self._save_settings()
        self._apply_hotkeys()
        if self.settings_win:
            self.settings_win.deleteLater()
            self.settings_win = None

    def _on_hotkey_capture(self, on: bool) -> None:
        if on:
            self.hotkeys.set_bindings({})  # иначе запись не увидит уже занятые сочетания
        else:
            self._apply_hotkeys()

    def _test_sound(self, style: str, volume: int) -> None:
        player = self.printer.player
        player.set_style(style)
        player.set_volume(volume)
        if getattr(player, "loading", False):
            # новый звук собирается в фоне — сыграть, как только будет готов
            def once(_style: str) -> None:
                player.ready.disconnect(once)
                self._play_demo()
            player.ready.connect(once)
            return
        self._play_demo()

    def _play_demo(self) -> None:
        player = self.printer.player
        was = player.enabled
        player.enabled = True
        for i, kind in enumerate(["key", "key", "key", "space", "key", "key", "enter"]):
            QTimer.singleShot(i * 140, lambda k=kind: player.play(k))
        QTimer.singleShot(1100, lambda: setattr(player, "enabled", was))

    # ================================================================ список уроков
    def _fill_library(self, select_id: str = "") -> None:
        lib = self.library.list
        live = self.efir.live_lesson_id()
        lib.blockSignals(True)
        lib.clear()
        for t in self.store.templates:
            it = QListWidgetItem(t.title)
            it.setToolTip(t.title)
            it.setData(ROLE_ID, t.id)
            it.setData(ROLE_META, lesson_meta(t))
            it.setData(ROLE_LIVE, bool(live) and t.id == live)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
            lib.addItem(it)
            if t.id == select_id:
                lib.setCurrentItem(it)
        if lib.currentRow() < 0 and lib.count():
            lib.setCurrentRow(0)
        lib.blockSignals(False)
        self._filter_library(self.library.search.text())

    def _select_in_library(self, tid: str) -> None:
        lib = self.library.list
        lib.blockSignals(True)
        for i in range(lib.count()):
            if lib.item(i).data(ROLE_ID) == tid:
                lib.setCurrentRow(i)
        lib.blockSignals(False)

    def refresh_library_item(self, t: Template) -> None:
        lib = self.library.list
        lib.blockSignals(True)
        for i in range(lib.count()):
            it = lib.item(i)
            if it.data(ROLE_ID) == t.id:
                it.setText(t.title)
                it.setToolTip(t.title)
                it.setData(ROLE_META, lesson_meta(t))
        lib.blockSignals(False)

    def _refresh_live_mark(self) -> None:
        live = self.efir.live_lesson_id()
        lib = self.library.list
        lib.blockSignals(True)
        for i in range(lib.count()):
            it = lib.item(i)
            it.setData(ROLE_LIVE, bool(live) and it.data(ROLE_ID) == live)
        lib.blockSignals(False)

    def _filter_library(self, text: str) -> None:
        q = text.strip().lower()
        lib = self.library.list
        for i in range(lib.count()):
            it = lib.item(i)
            t = self.store.get(it.data(ROLE_ID))
            hay = t.title.lower() if t else ""
            it.setHidden(bool(q) and q not in hay)

    def _selected(self) -> Template | None:
        it = self.library.list.currentItem()
        return self.store.get(it.data(ROLE_ID)) if it is not None else None

    def _open_selected(self) -> None:
        t = self._selected()
        if t is not None:
            self.open_lesson(t.id)
        elif self.printer.focus() is not None:
            self.lesson.open_page()

    def _library_menu(self, pos) -> None:
        lib = self.library.list
        it = lib.itemAt(pos)
        if not it:
            return
        t = self.store.get(it.data(ROLE_ID))
        m = QMenu(self)
        m.addAction(icons.icon("presentation"), "Открыть", lambda: self.open_lesson(t.id))
        m.addAction(icons.icon("pencil"), "Переименовать", lambda: lib.editItem(it))
        m.addAction(icons.icon("copy"), "Дублировать", lambda: self._duplicate(t))
        self._export_menu(m.addMenu(icons.icon("export"), "Экспорт"), t)
        m.addSeparator()
        m.addAction(icons.icon("trash"), "Удалить…", lambda: self._delete_template(t))
        m.exec(lib.viewport().mapToGlobal(pos))

    def _on_library_renamed(self, it: QListWidgetItem) -> None:
        t = self.store.get(it.data(ROLE_ID))
        title = it.text().strip()
        if t and not title:   # стёрли название целиком — вернуть прежнее, а не оставить пустую строку
            self.refresh_library_item(t)
            return
        if t and title and title != t.title:
            t.title = title
            self.touch(t)

    def open_lesson(self, tid: str, ask: bool = True) -> bool:
        """Открыть урок на экране урока. Идёт другой урок — сначала спросить, завершить ли его (ask=False —
        уже спросили на странице)."""
        t = self.store.get(tid)
        if t is None:
            return False
        live = self.efir.live_lesson_id()
        if live and live != tid:
            cur = self.store.get(live)
            name = cur.title if cur else "урок"
            if ask and QMessageBox.question(self, "Идёт урок", f"Идёт урок «{name}». Завершить его и открыть «{t.title}»?") \
                    != QMessageBox.StandardButton.Yes:
                return False
            self.efir.stop_live()
        self.printer.set_focus(tid)
        self.settings.page_lesson = tid
        self._settings_timer.start()
        self._select_in_library(tid)
        self.lesson.open_page()
        return True

    def new_template(self) -> None:
        """Новый урок: этап «Начало» и пустая заметка «Говоришь» — сразу на экран урока, править там."""
        t = self.store.add("Новый урок")
        self.touch(t)
        self._fill_library(t.id)
        self.open_lesson(t.id)

    def _duplicate(self, t: Template) -> None:
        c = self.store.duplicate(t)
        self.touch(c)
        self._fill_library(c.id)

    def delete_lesson(self, t: Template, ask: bool = True) -> bool:
        if ask and QMessageBox.question(
                self, "Удалить урок", f"Удалить урок «{t.title}»?\n"
                "(Резервная копия прошлой версии базы — data/templates.json.bak)") != QMessageBox.StandardButton.Yes:
            return False
        if self.efir.live_lesson_id() == t.id:
            self.efir.stop_live()
        self.store.remove(t)
        if self.printer.focus_id == t.id:
            self.printer.set_focus(self.store.templates[0].id if self.store.templates else "")
        self.printer.on_store_changed()
        self._save_timer.start()
        self._fill_library(self.printer.focus_id)
        self.lesson.schedule_publish()
        return True

    def _delete_template(self, t: Template) -> None:
        self.delete_lesson(t)

    def import_files(self, tab: str = "file") -> None:
        """Окно «Импорт урока»: из файла, вставкой или с помощью нейросети. Не модальное: из него можно
        открыть ⚙ → Нейросеть, подключить её и вернуться."""
        from .import_dialog import ImportDialog
        d = getattr(self, "_import_dlg", None)
        if d is not None and d.isVisible():
            d.tabs.set_value(tab)
            d._show_tab(tab)
            d.raise_()
            d.activateWindow()
            return
        d = ImportDialog(self, self.settings, tab=tab, open_ai_settings=lambda: self.open_settings("ai"))
        d.accepted.connect(lambda: self._take_import(d))
        d.finished.connect(lambda _r: self._save_settings())   # запомнить выбор разбора
        self._import_dlg = d
        d.show()

    def _take_import(self, d) -> None:
        from ..lesson_ai import STYLE_COMMENTS, STYLE_PARTS, STYLE_STEPS
        last = None
        for t in d.result:
            self.store.insert(t)
            last = t
        if last is None:
            return
        self.touch(last)
        self._fill_library(last.id)
        msg = (f"Добавлен урок «{last.title}»: блоков — {len(last.blocks)}, из них кода — "
               f"{len(last.code_blocks())}." if len(d.result) == 1 else f"Добавлено уроков: {len(d.result)}.")
        mode = {STYLE_STEPS: MODE_STEPS, STYLE_COMMENTS: MODE_LINES, STYLE_PARTS: MODE_BLOCK}.get(d.result_style)
        if mode:
            # разбор нейросетью: включить подходящую печать; комментарии — читать вслух, а не печатать
            self.printer.set_option("mode", mode)
            self.printer.set_option("strip", True)
            names = {MODE_STEPS: "«По шагам»", MODE_LINES: "«По строкам»", MODE_BLOCK: "«Целиком»"}
            msg += f" Печать: {names[mode]}, комментарии — читать вслух."
        self.toast.show_message(msg, ms=9000)
        self.open_lesson(last.id)

    def export_template(self, t: Template, fmt: str) -> None:
        """fmt: md (урок в Markdown, картинки — папкой рядом) | ipynb | students (тетрадка для учеников —
        только код) | json."""
        safe = "".join(c for c in t.title if c not in '\\/:*?"<>|').strip() or "template"
        flt = {"md": "Markdown (*.md)", "ipynb": "Jupyter (*.ipynb)", "students": "Jupyter (*.ipynb)"}.get(
            fmt, "JSON (*.json)")
        name = f"{safe} — для учеников.ipynb" if fmt == "students" else f"{safe}.{fmt}"
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт", name, flt)
        if not path:
            return
        try:
            if fmt == "md":
                from ..lesson_md import export_md
                export_md(t, Path(path))
            elif fmt in ("ipynb", "students"):
                export_ipynb(t, path, students=fmt == "students")
            else:
                TemplateStore.export_template(t, path)
            self._notify(f"Сохранено: {path}")
        except OSError as e:
            QMessageBox.warning(self, "Экспорт", str(e))

    def _restart_app(self) -> None:
        """Перезапуск программы (новый размер интерфейса) — тем же путём, что после обновления."""
        if self._busy_typing() and QMessageBox.question(
                self, APP_NAME, "Сейчас идёт печать. Остановить её и перезапустить программу?") \
                != QMessageBox.StandardButton.Yes:
            return
        self._save_settings()
        self._restart()

    def open_report(self) -> None:
        """Отчёт об ошибке: журнал и сведения о системе без личных данных → zip или задача на GitHub."""
        from .report_dialog import show_report_dialog
        show_report_dialog(self.settings_win if self.settings_win and self.settings_win.isActiveWindow()
                           else self, self.settings)

    def _open_log(self) -> None:
        import os
        from ..logs import LOG_FILE
        if LOG_FILE.exists():
            os.startfile(LOG_FILE)
        else:
            self._notify("Журнал пока пуст.")

    def _open_data_dir(self) -> None:
        import os
        from ..storage import DATA_DIR
        os.startfile(DATA_DIR)

    # ================================================================ сохранение
    def touch(self, t: Template | None = None) -> None:
        """Урок изменился: отметить время, обновить строку в списке, сохранить чуть позже."""
        t = t or self.printer.focus()
        if t is not None:
            t.updated = time.time()
            self.refresh_library_item(t)
        self.printer.on_store_changed()
        self._save_timer.start()

    def _save_store(self) -> None:
        try:
            self.store.save()
        except OSError as e:
            self._notify(f"Не удалось сохранить уроки: {e}", warn=True)

    def _ensure_samples(self) -> str:
        """Встроенные примеры — по одному разу (и новым пользователям, и после обновления). Возвращает id
        примера, если его добавили только что, иначе пустую строку."""
        from ..samples import TOUR_SAMPLE_ID, tour_template
        from ..storage import STEPS_SAMPLE_ID
        seen, changed, tour_id = self.settings.samples_seen, False, ""
        if STEPS_SAMPLE_ID not in seen:
            self.store.insert(steps_sample_template())
            seen.append(STEPS_SAMPLE_ID)
            changed = True
        if TOUR_SAMPLE_ID not in seen:
            if not self.store.created_fresh:   # в новой базе экскурсия уже есть — она первая
                t = tour_template()
                self.store.templates.insert(0, t)
                tour_id = t.id
            seen.append(TOUR_SAMPLE_ID)
            changed = True
        from ..samples_lesson import LESSON_SAMPLE_ID, LESSON_TITLE, lesson_sample
        if LESSON_SAMPLE_ID not in seen and any(x.title == LESSON_TITLE for x in self.store.templates):
            seen.append(LESSON_SAMPLE_ID)       # пример уже в базе (настройки не успели сохраниться) — второй не нужен
            changed = True
        if LESSON_SAMPLE_ID not in seen:
            t = lesson_sample()
            self.store.templates.insert(1 if self.store.created_fresh else 0, t)
            if not self.store.created_fresh and not tour_id:
                tour_id = t.id
            seen.append(LESSON_SAMPLE_ID)
            changed = True
        if changed:
            self._save_store()
            self._save_settings()
        return tour_id

    def _restore_session(self) -> None:
        s = self.settings
        added = self._ensure_samples()
        if self._migrated:
            self._save_settings()
        if s.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(s.window_geometry.encode()))
        tid = next((x for x in (added, s.page_lesson, s.current_tab) if x and self.store.get(x)),
                   self.store.templates[0].id if self.store.templates else "")
        self._fill_library(tid)
        self.printer.set_focus(tid)
        if s.page_open and tid:
            QTimer.singleShot(800, self.lesson.open_page)   # в прошлый раз экран урока был открыт

    def _save_session(self) -> None:
        s = self.settings
        s.window_geometry = bytes(self.saveGeometry().toBase64()).decode()
        s.current_tab = s.page_lesson = self.printer.focus_id
        s.page_open = self.lesson.page_alive()
        s.save()

    # ================================================================ печать
    def _on_hotkey(self, action: str) -> None:
        if self.printer.on_hotkey(action):
            return
        if action == "hotkey_next_tab":
            self.cmd_next_tab(+1)

    def cmd_next_tab(self, d: int = 1) -> None:
        """Хоткей «следующий урок»: урок на экране урока — следующий в списке (во время урока — нельзя)."""
        if self.efir.live_lesson_id():
            self._notify("Идёт урок — другой урок не открыть хоткеем.", tray=True)
            return
        ids = [t.id for t in self.store.templates]
        if not ids:
            return
        self.printer.engine.pause()   # идёт или готовится — пауза (иначе ничего)
        cur = self.printer.focus_id
        i = ids.index(cur) if cur in ids else -1
        tid = ids[(i + d) % len(ids)]
        self.printer.set_focus(tid)
        self._select_in_library(tid)
        self.lesson.schedule_publish()
        t = self.store.get(tid)
        if not self.isActiveWindow():
            self._notify(f"Урок: {t.title}", tray=True)

    def _busy_typing(self) -> bool:
        return self.engine.state in BUSY

    def _on_state(self, _st: str = "") -> None:
        st = self.engine.state
        if hasattr(self, "tray"):     # первый вызов — из _on_theme, до трея
            self.tray.setIcon(self.tray_icons[logo.STATE_KIND.get(st, logo.IDLE)])
            self.tray.setToolTip(f"{APP_NAME}: {STATE_TEXT.get(st, st)}")
        self._set_title_status()
        self.print_bar.refresh()

    def _on_print_changed(self) -> None:
        self.print_bar.refresh()
        self._set_title_status()

    def _set_title_status(self) -> None:
        st = self.engine.state
        text = STATE_TEXT.get(st, st)
        p = self.printer
        if p.job and st in BUSY:
            t, b = p.find_block(p.job["bid"])
            if b and t:
                text += f" · {b.display_title(t.code_number(b))}"
        elif st == COUNTDOWN and p.countdown_n:
            text = f"Старт через {p.countdown_n}… Поставьте курсор в нужное окно"
        self.titlebar.set_status(text, STATE_TOKENS.get(st, "ok"))
        self.setWindowTitle(f"{APP_NAME} — {text}")

    def _notify(self, text: str, tray: bool = False, warn: bool = False, quiet: bool = False) -> None:
        self.toast.show_message(text, warn=warn)
        if not quiet and (tray or not self.isActiveWindow()):
            self.tray.showMessage(APP_NAME, text, self.tray_icons[logo.PAUSED if warn else logo.IDLE], 3000)

    # ================================================================ прочее
    def _efir_clicked(self) -> None:
        """Плашка «Эфир»: эфир идёт — показать таймер, иначе — шаблоны вебинаров."""
        if self.efir.live_webinar() is not None:
            self.efir.show_timer()
        else:
            self.efir.show_window()

    def _update_efir_pill(self) -> None:
        """Кнопка «Эфир» в шапке — такая же плоская, как «Настройки»; цвет и короткий текст — по состоянию."""
        b = getattr(self, "btn_efir", None)
        if b is None:
            return
        from ..efir.model import fmt_left
        ctl = self.efir
        w = ctl.live_webinar()
        mode = ctl.mode
        phase = ""
        tip = "Эфир: таймер вебинара и экран для учеников — фон, зарядка, перерыв"
        if mode == "break":
            text = f"Перерыв · {fmt_left(max(0.0, ctl.break_left()))}"
        elif mode == "exercise":
            text = "Зарядка"
        else:
            text = "Эфир"
        if w is not None:
            ag = ctl.agenda()
            phase = ag.phase
            if mode not in ("break", "exercise"):
                if phase == "before":
                    text = f"Эфир · через {fmt_left(ag.left_s)}"
                elif phase == "live" and ag.current:
                    name = ag.current.activity.name
                    name = name if len(name) <= 24 else name[:23].rstrip() + "…"
                    text = f"{name} · {fmt_left(ag.left_s)}"
                else:
                    text = "Эфир завершён"
            tip = f"{w.title}: эфир {ag.start:%H:%M}–{ag.end:%H:%M}. Щёлкните — таймер" if ag.start else tip
        if b.text() != text:
            b.setText(text)
        b.setToolTip(tip)
        token = efir_token(phase, mode)
        key = (token, theme.dark)
        if getattr(b, "_style_key", None) != key:
            b._style_key = key
            b.setIcon(icons.icon("radio", token, 16))
            col = theme.css("dim" if token == "dim" else token)
            b.setStyleSheet(f"QToolButton#efirBtn {{ color: {col}; }}")

    def _show_window(self) -> None:
        if self.isMaximized():
            self.showMaximized()
        else:
            self.showNormal()
        self.raise_()
        self.activateWindow()

    # ================================================================ панель задач
    def set_taskbar_icon(self, icon_path: str) -> None:
        """Своя иконка и имя на панели задач (иначе Windows покажет «Python»)."""
        self._taskbar_icon = icon_path
        self._apply_taskbar()

    def _apply_taskbar(self) -> None:
        path = getattr(self, "_taskbar_icon", "")
        if path:
            taskbar.apply_to_window(int(self.winId()), path, APP_NAME)

    def event(self, e) -> bool:
        # «Окно поверх остальных» и т. п. пересоздают окно Windows — свойства панели задач
        # теряются, их нужно записать новому окну
        if e.type() == QEvent.Type.WinIdChange:
            QTimer.singleShot(0, self._apply_taskbar)
        return super().event(e)

    # ================================================================ обновления
    def _auto_check_updates(self) -> None:
        # «при каждом запуске» — только первая проверка; иначе таймер раз в час смотрит, не пора ли
        if self._auto_checked_once and self.settings.update_interval_h <= 0:
            return
        self._auto_checked_once = True
        if self.updates.check_due():
            self.updates.check(manual=False)

    def check_updates(self, manual: bool = True) -> None:
        if manual:
            self._notify("Проверка обновлений…", quiet=True)
        self.updates.check(manual)

    def _on_update_checked(self, rel, manual: bool) -> None:
        self.settings.update_last_check = time.time()
        self._save_settings()
        if self.settings_win:
            self.settings_win.refresh_update_info()
        if rel is None:
            self._show_update_button(None)
            if manual:
                QMessageBox.information(QApplication.activeModalWidget() or self.settings_win or self, "Обновления",
                                        f"У вас последняя версия — {__version__}.")
            return
        if not manual and self.updates.is_skipped(rel):
            return
        self._show_update_button(rel)
        if manual:
            self.open_update_dialog()
        elif self.settings.update_mode in (MODE_DOWNLOAD, MODE_AUTO) and self.updates.can_install:
            self.updates.download(rel)   # сообщим, когда будет готово
        elif not self._busy_typing():
            self._notify(f"Доступна новая версия {rel.version} — кнопка над списком уроков.", tray=True)

    def _on_update_check_failed(self, text: str, manual: bool) -> None:
        if manual:
            QMessageBox.warning(QApplication.activeModalWidget() or self.settings_win or self, "Обновления", text)

    def _on_update_ready(self, rel) -> None:
        self._show_update_button(rel)
        if self.settings.update_mode == MODE_AUTO:
            text = f"Версия {rel.version} скачана и установится при выходе из программы."
        else:
            text = f"Версия {rel.version} готова к установке — кнопка над списком уроков."
        if self._busy_typing():   # не отвлекаем во время занятия
            log.info(text)
        else:
            self._notify(text, tray=True)

    def _show_update_button(self, rel) -> None:
        if rel is None:
            self.library.show_update(None)
            self.tray_update.setVisible(False)
            return
        ready = bool(self.updates.staged and self.updates.staged[0].version == rel.version)
        text = f"Обновить до {rel.version}" if ready else f"Доступна версия {rel.version}"
        self.library.show_update(text)
        self.tray_update.setText(text)
        self.tray_update.setVisible(True)

    def open_update_dialog(self) -> None:
        rel = self.updates.latest
        if rel is None:
            self.check_updates(manual=True)
            return
        dlg = UpdateDialog(self.updates, rel, QApplication.activeModalWidget() or self.settings_win or self)
        dlg.restart_requested.connect(self.install_update_and_restart)
        dlg.exec()

    def install_update_and_restart(self) -> None:
        if self._busy_typing():
            if QMessageBox.question(self, "Обновление", "Сейчас идёт печать. Остановить её и перезапустить "
                                    "программу с новой версией?") != QMessageBox.StandardButton.Yes:
                return
        try:
            ver = self.updates.apply_staged()
        except updater.UpdateError as e:
            QMessageBox.warning(self, "Обновление", str(e))
            return
        log.info("Перезапуск после обновления до %s", ver)
        self._restart()

    def _restart(self) -> None:
        self.engine.stop()
        self.relaunch_requested = True
        QTimer.singleShot(0, self.quit_app)

    def _show_update_result(self) -> None:
        d = updater.pop_last_update()
        if not d:
            return
        self._notify(f"{APP_NAME} обновлён: {d.get('from')} → {d.get('to')}.", tray=True)

    def closeEvent(self, e) -> None:
        live = self.efir.live_webinar() is not None    # идёт эфир — таймер не должен пропасть вместе с окном
        if (self.settings.close_to_tray or live) and not self._quitting and self.tray.isVisible():
            # «закрыть» = спрятать в трей; выход — из меню логотипа или значка в трее
            e.ignore()
            self._save_session()
            self.hide()
            if self.settings_win:
                self.settings_win.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.showMessage(APP_NAME, "Программа работает в трее. Хоткеи действуют. "
                                      "Выход — из меню значка.", self.tray_icons[logo.IDLE], 3000)
            return
        # «установить при выходе»: скачанное обновление применяется, новая версия — со следующего запуска
        if (self.updates.staged and not self.updates.applied and not self.relaunch_requested
                and self.settings.update_mode == MODE_AUTO):
            try:
                self.updates.apply_staged()
            except updater.UpdateError as err:
                log.warning("Обновление при выходе не установлено: %s", err)
        if self.settings_win:
            self.settings_win.close()
        self._save_session()            # до закрытия экрана урока: запомнить, был ли он открыт
        self.lesson.shutdown()          # окно экрана урока закрывается вместе с программой
        self.efir.shutdown()
        self.engine.stop()
        self._save_timer.stop()
        self._save_store()
        self.hotkeys.shutdown()
        self.guard.shutdown()
        self.tray.hide()
        super().closeEvent(e)
        # приложение не выходит само при закрытии последнего окна (живёт в трее) — выходим явно
        QTimer.singleShot(0, QApplication.quit)

    def quit_app(self) -> None:
        self._quitting = True
        self.close()
        QApplication.quit()
