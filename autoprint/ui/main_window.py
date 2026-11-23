"""Главное окно: свой заголовок, библиотека образцов слева, пульт печати, лента блоков, трей."""
from __future__ import annotations

import logging

import shiboken6
import time
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QInputDialog, QListWidgetItem, QMenu,
                               QPushButton,
                               QMessageBox, QStackedWidget, QSystemTrayIcon, QToolButton, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__, system, taskbar, updater, winapi
from .. import steps as S
from ..comments import comment_spans, comment_text, strip_comments
from ..guard import InputGuard
from ..hotkeys import HotkeyManager, parse_hotkey
from ..importers import export_ipynb
from ..sounds import KeySoundPlayer
from ..storage import (BLOCK_CODE, BLOCK_IMAGE, BLOCK_STAGE, PROFILE_SHORT, PROFILES, Block, Settings, Template,
                       TemplateStore, steps_sample_template)
from ..textprint import PRINT_COMMENT, PRINT_MARKDOWN, PRINT_MODES, PRINT_PLAIN, printable, selection_text
from ..typer import COUNTDOWN, FINISHED, IDLE, LINE_WAIT, PAUSED, RUNNING, TypingEngine, build_units
from .. import highlighter
from . import icons, logo
from .blocks import BlockWidget, typing_slice
from .control_strip import STATE_TEXT, ControlStrip
from .efir_control import EfirController
from .frameless import FramelessWindow
from .lesson_control import LessonController
from .library import ROLE_COUNT, ROLE_ID, LibraryPanel
from .prompter import Prompter
from .prompter_control import PrompterController
from .settings_window import HOTKEYS, SettingsWindow
from .template_view import TemplateView, ZoomWheelFilter, _plural
from .theme import STATE_TOKENS, theme
from .updates import MODE_AUTO, MODE_DOWNLOAD, UpdateDialog, UpdateManager
from .widgets import IconButton, Toast, install_wheel_guard

log = logging.getLogger("autoprint")

# настройки, после которых уже подготовленный текст нужно собрать заново
REBUILD_KEYS = {"profile", "strip_comments", "human_typing", "typos_per_100", "think_pause_s", "tab_width",
                "fast_indent", "indent_with_tab", "selection_whole_lines", "print_mode", "step_nav"}
BUSY = (RUNNING, COUNTDOWN, PAUSED, LINE_WAIT)
MODE_BLOCK, MODE_LINES, MODE_STEPS = "block", "lines", "steps"

# exe окна → как его назвать на пульте
APP_NAMES = {"code": "VS Code", "notepad": "Блокнот", "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox",
             "pycharm64": "PyCharm", "idea64": "IntelliJ IDEA", "windowsterminal": "Терминал",
             "sublime_text": "Sublime Text", "notepad++": "Notepad++", "yandex": "Яндекс Браузер",
             "browser": "Яндекс Браузер", "opera": "Opera", "cursor": "Cursor", "pythonw": "Python",
             "python": "Python", "jupyter-lab": "JupyterLab"}


def app_name(exe: str) -> str:
    base = exe.rsplit("\\", 1)[-1]
    if base.lower().endswith(".exe"):
        base = base[:-4]
    return APP_NAMES.get(base.lower(), base or "окно")


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


class MainWindow(FramelessWindow):
    def __init__(self, settings: Settings, store: TemplateStore) -> None:
        super().__init__(APP_NAME)
        self.settings = settings
        self.store = store
        self._migrated = apply_migrations(settings, store)
        self._zoom_filter = ZoomWheelFilter(self)
        QApplication.instance().installEventFilter(self._zoom_filter)
        install_wheel_guard(QApplication.instance())   # колесо не меняет счётчики и списки без щелчка по ним
        self.tray_icons = {k: logo.make_icon(k) for k in (logo.IDLE, logo.RUNNING, logo.PAUSED)}
        self.setWindowIcon(logo.make_icon(logo.APP))
        self.resize(1320, 840)
        self.setMinimumSize(980, 600)

        self.engine = TypingEngine(settings)
        self.player = KeySoundPlayer(settings.sound_style, settings.sound_volume, settings.sound_enabled)
        self.engine.sound.connect(self.player.play)
        self.engine.state_changed.connect(self._on_state)
        self.engine.progress.connect(self._on_progress)
        self.engine.message.connect(lambda t: self._notify(t, warn=True))
        self.engine.countdown.connect(self._on_countdown)
        self.engine.finished.connect(self._on_finished)
        self.engine.target.connect(self._on_target)
        self.engine.interrupted.connect(lambda _kind: self._notify("Пауза: вы кликнули мышью.", quiet=True))
        self.job: dict | None = None   # {kind, tid, bid, base, text, omap, src_len[, step]}
        self._target = ""
        self.step_next: dict[str, int | None] = {}   # id блока → какой шаг печатать следующим (None — все)

        self.guard = InputGuard()
        self.engine.click_count = self.guard.click_count   # клики мышью во время печати (Raw Input)
        self.guard.tripped.connect(self._on_guard)
        self.guard.enter_pressed.connect(lambda: self.engine.continue_line(by_enter=True))

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
        self._label_timer = QTimer(self)
        self._label_timer.setSingleShot(True)
        self._label_timer.setInterval(150)
        self._label_timer.timeout.connect(self._update_armed_label)
        self._analysis: tuple | None = None   # (ключ, строки) — разбор активного блока по шагам

        self.updates = UpdateManager(settings, self)
        self.updates.checked.connect(self._on_update_checked)
        self.updates.check_failed.connect(self._on_update_check_failed)
        self.updates.ready.connect(self._on_update_ready)
        self.updates.download_failed.connect(lambda t: log.warning("Обновление не скачано: %s", t))
        self.relaunch_requested = False   # app.py перезапустит программу после выхода
        self._auto_checked_once = False
        self.settings_win: SettingsWindow | None = None
        self.views: dict[str, TemplateView] = {}
        self._view_scroll: dict[str, int] = {}    # где была прокрутка у выгруженного из памяти занятия

        self.efir = EfirController(self)    # «Эфир»: шаблоны вебинаров, таймер, вкладка эфира
        self.efir.message.connect(lambda t, warn: self._notify(t, warn=warn))
        self.lesson = LessonController(self)   # суфлёр урока: страница в браузере, время — от «Эфира»
        self._build_ui()
        self._build_tray()
        theme.changed.connect(self._on_theme)
        theme.about_to_change.connect(self._drop_views_for_theme)
        self._on_theme()
        self._apply_settings()
        self._apply_hotkeys()
        self._restore_session()
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
        self.btn_efir.setToolTip("Эфир: таймер вебинара по шаблону и экран для учеников — фон, зарядка, перерыв")
        self.btn_efir.clicked.connect(self._efir_clicked)
        self.btn_efir.setFixedHeight(32)
        self.btn_efir.setMaximumWidth(320)
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
        root = QHBoxLayout(self.body)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.library = LibraryPanel()
        lib = self.library.list
        lib.itemClicked.connect(lambda it: self.open_template(it.data(ROLE_ID)))
        lib.currentItemChanged.connect(lambda it, _prev: self.open_template(it.data(ROLE_ID)) if it else None)
        lib.itemChanged.connect(self._on_library_renamed)
        lib.customContextMenuRequested.connect(self._library_menu)
        self.library.search.textChanged.connect(self._filter_library)
        self.library.new_requested.connect(self.new_template)
        self.library.import_requested.connect(lambda: self.import_files())
        self.library.update_clicked.connect(self.open_update_dialog)
        root.addWidget(self.library)

        main = QWidget()
        ml = QVBoxLayout(main)
        ml.setContentsMargins(22, 16, 10, 0)
        ml.setSpacing(14)
        self.strip = ControlStrip()
        self.strip.toggle_clicked.connect(lambda: self.cmd_toggle(from_button=True, pressed=True))
        self.strip.btn_toggle.pressed.connect(self._remember_press)
        self.strip.restart_clicked.connect(lambda: self.cmd_restart(from_button=True))
        self.strip.stop_clicked.connect(self.cmd_stop)
        self.strip.cpm_changed.connect(self._on_cpm)
        self.strip.human_toggled.connect(self._on_human_toggle)
        self.strip.strip_toggled.connect(self._on_strip_toggle)
        self.strip.sound_toggled.connect(self._on_sound_toggle)
        self.strip.volume_changed.connect(self._on_volume)
        self.strip.volume_released.connect(self._on_volume_released)
        self.strip.profile_changed.connect(self._on_profile)
        self.strip.mode_changed.connect(self._on_mode)
        strip_wrap = QVBoxLayout()
        strip_wrap.setContentsMargins(0, 0, 12, 0)
        strip_wrap.setSpacing(10)
        strip_wrap.addWidget(self.strip)
        self.prompter = Prompter()
        self.prompter.detach_clicked.connect(lambda: self.prompter_ctl.show())
        strip_wrap.addWidget(self.prompter)
        self.prompter_ctl = PrompterController(self)    # суфлёр в отдельном окне
        self.strip.prompter_clicked.connect(lambda: self.prompter_ctl.toggle())
        ml.addLayout(strip_wrap)
        self.stack = QStackedWidget()
        ml.addWidget(self.stack, 1)
        root.addWidget(main, 1)
        self.toast = Toast(main)

        sc = [("Ctrl+N", self.new_template), ("Ctrl+O", lambda: self.import_files()), ("Ctrl+Q", self.quit_app),
              ("Ctrl+,", lambda: self.open_settings()), ("F1", lambda: self.open_settings("about")),
              ("Alt+Down", lambda: self.cmd_block(+1)), ("Alt+Up", lambda: self.cmd_block(-1)),
              ("Ctrl+=", lambda: self._zoom_block(+1)), ("Ctrl++", lambda: self._zoom_block(+1)),
              ("Ctrl+-", lambda: self._zoom_block(-1)), ("Ctrl+0", lambda: self._zoom_block(0)),
              ("Ctrl+Shift+0", self._reset_zoom),
              ("Ctrl+Tab", lambda: self.cmd_next_tab(+1)), ("Ctrl+Shift+Tab", lambda: self.cmd_next_tab(-1))]
        for i in range(1, 10):
            sc.append((f"Ctrl+{i}", lambda i=i: self._goto_template(i - 1)))
        for seq, slot in sc:
            QShortcut(QKeySequence(seq), self, slot)

    def _fill_logo_menu(self) -> None:
        # сочетания здесь — только подпись («\t…»): сами клавиши — QShortcut окна; setShortcut у пунктов
        # меню сделал бы их двусмысленными, и Qt не запускал бы ни то ни другое
        m = self.logo_menu
        m.clear()
        m.addAction(icons.icon("settings"), "Настройки…\tCtrl+,", lambda: self.open_settings())
        m.addAction(icons.icon("info"), "О программе", lambda: self.open_settings("about"))
        m.addAction(icons.icon("help"), "Как пользоваться\tF1", lambda: self.open_settings("about"))
        m.addAction(icons.icon("refresh"), "Проверить обновления…", lambda: self.check_updates(manual=True))
        m.addSeparator()
        m.addAction(icons.icon("plus"), "Новое занятие\tCtrl+N", self.new_template)
        m.addAction(icons.icon("import"), "Импорт…\tCtrl+O", lambda: self.import_files())
        m.addAction(icons.icon("sparkles"), "Разобрать код нейросетью…", lambda: self.import_files("ai"))
        m.addAction(icons.icon("export"), "Урок в Markdown (.md, с картинками рядом)…", lambda: self.export_current("md"))
        m.addAction(icons.icon("export"), "Экспорт занятия в .ipynb…", lambda: self.export_current("ipynb"))
        m.addAction(icons.icon("export"), "Тетрадка для учеников (.ipynb, без подсказок)…",
                    lambda: self.export_current("students"))
        m.addAction(icons.icon("export"), "Экспорт занятия в .json…", lambda: self.export_current("json"))
        m.addSeparator()
        m.addAction(icons.icon("file-code"), "Добавить пример урока (суфлёр, этапы, картинки)", self._add_lesson_sample)
        m.addAction(icons.icon("file-code"), "Добавить пример занятия (все возможности)", self._add_tour_sample)
        m.addAction(icons.icon("file-code"), "Добавить пример пошагового урока", self._add_steps_sample)
        m.addAction(icons.icon("presentation"), "Суфлёр урока (окно браузера)", self.lesson.open_page)
        m.addAction(icons.icon("radio"), "Эфир — шаблоны вебинаров…", self.efir.show_window)
        m.addAction(icons.icon("external"), ("Закрыть окно суфлёра" if self.prompter_ctl.visible()
                                             else "Суфлёр в отдельном окне"), lambda: self.prompter_ctl.toggle())
        m.addAction(icons.icon("lines"), "Все блоки — обычный размер\tCtrl+Shift+0", self._reset_zoom)
        m.addAction(icons.icon("bug"), "Сообщить об ошибке…", self.open_report)
        m.addAction(icons.icon("file-text"), "Журнал работы", self._open_log)
        m.addAction(icons.icon("folder"), "Папка с данными", self._open_data_dir)
        m.addSeparator()
        m.addAction(icons.icon("logout"), "Выход\tCtrl+Q", self.quit_app)

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(self.tray_icons[logo.IDLE], self)
        menu = QMenu()
        menu.addAction("Показать окно", self._show_window)
        menu.addSeparator()
        menu.addAction("Старт / пауза", lambda: self.cmd_toggle(from_button=False, countdown=3, pressed=True))
        menu.aboutToShow.connect(self._remember_press)
        menu.addAction("Стоп", self.cmd_stop)
        menu.addAction("Суфлёр в отдельном окне", lambda: self.prompter_ctl.toggle())
        menu.addAction("Эфир…", self._efir_clicked)
        menu.addAction("Суфлёр урока", self.lesson.open_page)
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

    def _drop_views_for_theme(self) -> None:
        """Перед сменой темы: открытые занятия убрать совсем, после — собрать заново. Qt пересчитывает оформление
        каждого виджета по одному (~1 мс), и большое занятие «висело» секундами; собрать заново — в разы быстрее.
        Вкладку, из которой сейчас идёт печать, не трогаем."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)   # занятие собирается заново — секунду-две
        self._theme_cursor = True
        cur = self.current_view()
        self._theme_restore = cur.template.id if cur is not None else ""
        for tid in list(self.views):
            if self._view_busy(tid):
                continue
            v = self.views.pop(tid)
            self._view_scroll[tid] = v.scroll.verticalScrollBar().value()
            self.stack.removeWidget(v)
            shiboken6.delete(v)             # сразу, а не deleteLater: иначе Qt успеет перекрасить и его

    def _restore_views_after_theme(self) -> None:
        tid = getattr(self, "_theme_restore", "")
        self._theme_restore = ""
        if tid and self.store.get(tid):
            self.open_template(tid)

    def _on_theme(self) -> None:
        self._restore_views_after_theme()
        highlighter.set_palette("dark" if theme.dark else "light")
        self.logo_btn.setIcon(title_logo_icon())
        self.restyle_frame()
        self._update_efir_pill()
        self._on_state(self.engine.state)
        self.library.list.viewport().update()
        if getattr(self, "_theme_cursor", False):
            self._theme_cursor = False
            QApplication.restoreOverrideCursor()

    # ================================================================ настройки
    def _apply_settings(self) -> None:
        s = self.settings
        theme.set_mode(s.theme)
        self.strip.set_settings(s)
        self.player.enabled = s.sound_enabled
        self.player.set_style(s.sound_style)
        self.player.set_volume(s.sound_volume)
        self.guard.enabled = s.guard_enabled
        on_top = bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        if on_top != s.always_on_top:
            visible = self.isVisible()
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, s.always_on_top)  # пересоздаёт окно
            # свойства панели задач — до показа, иначе кнопка успеет появиться как «Python»
            self._apply_taskbar()
            if visible:
                self.show()
        self.engine.rebuild()
        self._apply_mode()
        self._on_state(self.engine.state)
        self._update_armed_label()

    def _apply_mode(self) -> None:
        """Режим печати → вид блоков (колонка шагов, подсветка следующего шага) и суфлёр."""
        steps_on = self.settings.print_mode == MODE_STEPS
        for v in self.views.values():
            v.apply_step_mode(steps_on)
        self._refresh_prompter()

    def _on_mode(self, mode: str) -> None:
        if mode == self.settings.print_mode:
            return
        if self.engine.state in BUSY:
            self.cmd_stop()
        self.settings.print_mode = mode
        self.strip.set_settings(self.settings)   # переключатель на пульте — если режим сменили не с пульта
        self._invalidate_job_if_idle()
        self.engine.rebuild()
        self._settings_touched()
        self._apply_mode()
        self._update_armed_label()
        self._notify({MODE_BLOCK: "Печать блока целиком.",
                      MODE_LINES: f"По строкам: {self.settings.hotkey_toggle} — первая строка, дальше Enter "
                                  "в редакторе — следующая. Пустые строки идут сами.",
                      MODE_STEPS: f"По шагам: {self.settings.hotkey_toggle} печатает следующий шаг. Шаги "
                                  "размечаются слева от номеров строк (правый щелчок, Alt+1…9)."}[mode]
                     if mode in (MODE_BLOCK, MODE_LINES, MODE_STEPS) else "")

    def _apply_hotkeys(self) -> None:
        s = self.settings
        self.hotkeys.set_bindings({k: getattr(s, k) for k, _t, _i in HOTKEYS})
        self.guard.set_hotkeys({hk for k, _t, _i in HOTKEYS if (hk := parse_hotkey(getattr(s, k)))})
        self.strip.set_settings(s)

    def _save_settings(self) -> None:
        self._settings_timer.stop()
        self.settings.save()

    def _settings_touched(self) -> None:
        """Изменение с пульта: сохранить чуть позже и показать новое значение в окне настроек."""
        self._settings_timer.start()
        if self.settings_win:
            self.settings_win.reload()

    def _on_setting_changed(self, key: str) -> None:
        """Изменение из окна настроек."""
        s = self.settings
        self._settings_timer.start()
        if key == "sound_volume":   # ползунок шлёт много шагов — только громкость
            self.player.set_volume(s.sound_volume)
            self.strip.set_settings(s)
            return
        if key == "hotkeys":
            self._apply_hotkeys()
            self._set_title_status()   # подсказка «Ctrl+F9 — старт» в заголовке
            return
        if key == "print_mode" and self.engine.state in BUSY:
            self.cmd_stop()   # как и переключатель на пульте: задание прежнего режима не продолжаем
        if key in REBUILD_KEYS:
            self._invalidate_job_if_idle()
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
        self._apply_settings()

    def _on_profile(self, profile: str) -> None:
        self.settings.profile = profile
        self.engine.rebuild()
        self._invalidate_job_if_idle()
        self._settings_touched()

    def _on_cpm(self, v: int) -> None:
        self.settings.cpm = v   # движок читает скорость на лету
        self._settings_touched()

    def _on_sound_toggle(self, on: bool) -> None:
        self.settings.sound_enabled = on
        self.player.enabled = on
        self._settings_touched()

    def _on_volume(self, v: int) -> None:
        self.settings.sound_volume = v
        self.player.set_volume(v)
        if not self.strip.vol.isSliderDown():   # колёсико / клавиши — сразу, перетаскивание — по отпусканию
            self._on_volume_released()

    def _on_volume_released(self) -> None:
        self._settings_touched()
        if self.engine.state != RUNNING:   # услышать новую громкость
            for i, kind in enumerate(("key", "key", "space")):
                QTimer.singleShot(i * 120, lambda k=kind: self.player.play(k))

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

    def _on_strip_toggle(self, on: bool) -> None:
        self.settings.strip_comments = on
        self._settings_touched()
        self._invalidate_job_if_idle()
        self._update_armed_label()
        self._notify("Комментарии не печатаются." if on else "Комментарии печатаются как в коде.")

    def _on_human_toggle(self, on: bool) -> None:
        self.settings.human_typing = on
        self._settings_touched()
        self.engine.rebuild()
        self._invalidate_job_if_idle()
        self._notify("Как человек: живой ритм, паузы и опечатки." if on else "Ровная печать без опечаток.")

    def _test_sound(self, style: str, volume: int) -> None:
        self.player.set_style(style)
        self.player.set_volume(volume)
        if getattr(self.player, "loading", False):
            # новый звук собирается в фоне — сыграть, как только будет готов
            def once(_style: str) -> None:
                self.player.ready.disconnect(once)
                self._play_demo()
            self.player.ready.connect(once)
            return
        self._play_demo()

    def _play_demo(self) -> None:
        was = self.player.enabled
        self.player.enabled = True
        for i, kind in enumerate(["key", "key", "key", "space", "key", "key", "enter"]):
            QTimer.singleShot(i * 140, lambda k=kind: self.player.play(k))
        QTimer.singleShot(1100, lambda: setattr(self.player, "enabled", was))

    # ================================================================ библиотека
    def _fill_library(self, select_id: str = "") -> None:
        lib = self.library.list
        lib.blockSignals(True)
        lib.clear()
        for t in self.store.templates:
            it = QListWidgetItem(t.title)
            it.setToolTip(f"{t.title}\nБлоков: {len(t.blocks)}, из них кода: {len(t.code_blocks())}")
            it.setData(ROLE_ID, t.id)
            it.setData(ROLE_COUNT, len(t.blocks))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
            lib.addItem(it)
            if t.id == select_id:
                lib.setCurrentItem(it)
        lib.blockSignals(False)
        self._filter_library(self.library.search.text())

    def _select_in_library(self, tid: str) -> None:
        lib = self.library.list
        lib.blockSignals(True)
        for i in range(lib.count()):
            if lib.item(i).data(ROLE_ID) == tid:
                lib.setCurrentRow(i)
        lib.blockSignals(False)

    def _refresh_library_item(self, t: Template) -> None:
        lib = self.library.list
        lib.blockSignals(True)
        for i in range(lib.count()):
            it = lib.item(i)
            if it.data(ROLE_ID) == t.id:
                it.setText(t.title)
                it.setData(ROLE_COUNT, len(t.blocks))
                it.setToolTip(f"{t.title}\nБлоков: {len(t.blocks)}, из них кода: {len(t.code_blocks())}")
        lib.blockSignals(False)

    def _filter_library(self, text: str) -> None:
        q = text.strip().lower()
        lib = self.library.list
        for i in range(lib.count()):
            it = lib.item(i)
            t = self.store.get(it.data(ROLE_ID))
            hay = t.title.lower() if t else ""
            it.setHidden(bool(q) and q not in hay)

    def _library_menu(self, pos) -> None:
        lib = self.library.list
        it = lib.itemAt(pos)
        if not it:
            return
        t = self.store.get(it.data(ROLE_ID))
        m = QMenu(self)
        m.addAction(icons.icon("file-code"), "Открыть", lambda: self.open_template(t.id))
        m.addAction(icons.icon("pencil"), "Переименовать", lambda: lib.editItem(it))
        m.addAction(icons.icon("copy"), "Дублировать", lambda: self._duplicate(t))
        m.addSeparator()
        m.addAction(icons.icon("export"), "Урок в Markdown (.md)…", lambda: self.export_template(t, "md"))
        m.addAction(icons.icon("export"), "Экспорт в .ipynb…", lambda: self.export_template(t, "ipynb"))
        m.addAction(icons.icon("export"), "Тетрадка для учеников…", lambda: self.export_template(t, "students"))
        m.addAction(icons.icon("export"), "Экспорт в .json…", lambda: self.export_template(t, "json"))
        m.addSeparator()
        m.addAction(icons.icon("trash"), "Удалить…", lambda: self._delete_template(t))
        m.exec(lib.viewport().mapToGlobal(pos))

    def _on_library_renamed(self, it: QListWidgetItem) -> None:
        t = self.store.get(it.data(ROLE_ID))
        title = it.text().strip()
        if t and not title:   # стёрли название целиком — вернуть прежнее, а не оставить пустую строку
            self._refresh_library_item(t)
            return
        if t and title and title != t.title:
            t.title = title
            v = self.views.get(t.id)
            if v:
                v.refresh_header()
            self._touch()

    def current_view(self) -> TemplateView | None:
        v = self.stack.currentWidget()
        return v if isinstance(v, TemplateView) else None

    def open_template(self, tid: str, activate: bool = True) -> TemplateView | None:
        v = self.views.get(tid)
        if v is None:
            t = self.store.get(tid)
            if not t:
                return None
            v = TemplateView(t)
            v.step_pointer = self._step_pointer
            v.zoom_changed.connect(lambda z: self._notify(f"Масштаб блока: {z} %"))
            v.changed.connect(self._touch)
            v.changed.connect(self.lesson.schedule_publish)
            v.armed_changed.connect(lambda _bid: self._update_armed_label())
            v.armed_changed.connect(lambda _bid: self.lesson.schedule_publish())
            v.suflor_requested.connect(self.lesson.open_page)
            v.steps_changed.connect(self._on_steps_changed)
            v.step_pointer_requested.connect(self._set_step_pointer)
            v.apply_step_mode(self.settings.print_mode == MODE_STEPS)
            if activate:
                self._evict_views(keep=tid)
            self.views[tid] = v
            self.stack.addWidget(v)
            pos = self._view_scroll.pop(tid, None)
            if pos:
                self._restore_scroll(v, pos)
        if activate:
            # первый виджет в пустом стеке становится текущим сам — поэтому выделение и пульт обновляем всегда
            if self.stack.currentWidget() is not v:
                self.stack.setCurrentWidget(v)
            self._select_in_library(tid)
            self._update_armed_label()
            self.lesson.schedule_publish()      # страница суфлёра показывает открытое занятие
        return v

    def _view_busy(self, tid: str) -> bool:
        return bool(self.job and self.job.get("tid") == tid and self.engine.state in BUSY)

    def _evict_views(self, keep: str) -> None:
        """В памяти — открываемое занятие и предыдущее (и то, из которого идёт печать). Остальные — выгрузить:
        каждый блок — десятки виджетов, а их число и делает медленными открытие, прокрутку и смену темы."""
        cur = self.current_view()
        keep_ids = {keep} | ({cur.template.id} if cur is not None else set())
        for tid in list(self.views):
            if tid in keep_ids or self._view_busy(tid):
                continue
            v = self.views.get(tid)
            if v is not None:
                self._view_scroll[tid] = v.scroll.verticalScrollBar().value()
            self._close_view(tid)

    @staticmethod
    def _restore_scroll(v: TemplateView, pos: int) -> None:
        """Высоты блоков досчитываются после первого показа — ставим прокрутку дважды."""
        bar = v.scroll.verticalScrollBar()
        for ms in (0, 60):
            QTimer.singleShot(ms, v, lambda: bar.setValue(pos))

    def _close_view(self, tid: str) -> None:
        v = self.views.pop(tid, None)
        if v is None:
            return
        if self.job and self.job["tid"] == tid and self.engine.state in BUSY:   # и «ждёт Enter»
            self.cmd_stop()
        self.stack.removeWidget(v)
        # сразу, а не deleteLater: «отложенное» занятие ещё живо до возврата в цикл событий, и смена темы
        # успела бы перекрасить все его виджеты (на этом и «висло»)
        shiboken6.delete(v)

    # ---- масштаб блока (у каждого блока свой)
    def _target_block(self) -> BlockWidget | None:
        """Блок под мышью, иначе блок с курсором ввода, иначе активный блок (кода или текста)."""
        v = self.current_view()
        if not v:
            return None
        for w in (QApplication.widgetAt(QCursor.pos()), QApplication.focusWidget()):
            while w is not None and not isinstance(w, BlockWidget):
                w = w.parentWidget()
            if w is not None and w in v.widgets:
                return w
        return v.block_widget(v.template.active_block)

    def _zoom_block(self, steps: int) -> None:
        w = self._target_block()
        if w:
            w.zoom_by(steps) if steps else w.apply_zoom(100)

    def _reset_zoom(self) -> None:
        v = self.current_view()
        if v:
            v.reset_zoom()

    def _goto_template(self, i: int) -> None:
        visible = [self.library.list.item(k) for k in range(self.library.list.count())
                   if not self.library.list.item(k).isHidden()]
        if 0 <= i < len(visible):
            self.open_template(visible[i].data(ROLE_ID))

    def new_template(self) -> None:
        title, ok = QInputDialog.getText(self, "Новое занятие", "Название (например, «Занятие 3. Циклы»):")
        if not ok:
            return
        t = self.store.add(title.strip() or "Новое занятие")
        self._touch()
        self._fill_library(t.id)
        self.open_template(t.id)

    def _duplicate(self, t: Template) -> None:
        c = self.store.duplicate(t)
        self._touch()
        self._fill_library(c.id)
        self.open_template(c.id)

    def _delete_template(self, t: Template) -> None:
        if QMessageBox.question(self, "Удалить занятие",
                                f"Удалить занятие «{t.title}»?\n"
                                "(Резервная копия прошлой версии базы — data/templates.json.bak)") \
                != QMessageBox.StandardButton.Yes:
            return
        cur = self.current_view()
        was_current = cur is not None and cur.template.id == t.id
        self._close_view(t.id)
        self.store.remove(t)
        self._touch()
        self._fill_library("" if was_current or cur is None else cur.template.id)
        if was_current and self.store.templates:
            self.open_template(self.store.templates[0].id)
        self._update_armed_label()

    def import_files(self, tab: str = "file") -> None:
        """Окно «Импорт занятия»: из файла, вставкой или с помощью нейросети. Не модальное: из него можно
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
        from ..lesson_ai import STYLE_COMMENTS, STYLE_PARTS, STYLE_SCENARIO, STYLE_STEPS
        last = None
        for t in d.result:
            self.store.insert(t)
            last = t
        if last is None:
            return
        self._touch()
        self._fill_library(last.id)
        self.open_template(last.id)
        msg = (f"Добавлено занятие «{last.title}»: блоков — {len(last.blocks)}, из них кода — "
               f"{len(last.code_blocks())}." if len(d.result) == 1 else f"Добавлено занятий: {len(d.result)}.")
        mode = {STYLE_STEPS: MODE_STEPS, STYLE_COMMENTS: MODE_LINES, STYLE_PARTS: MODE_BLOCK}.get(d.result_style)
        if mode:
            # разбор нейросетью: включить подходящую печать; комментарии — на суфлёр, а не в редактор
            self._on_mode(mode)
            self.strip.sw_strip.setChecked(True)
            names = {MODE_STEPS: "«По шагам»", MODE_LINES: "«По строкам»", MODE_BLOCK: "«Целиком»"}
            msg += f" Включены {names[mode]} и «Без комментариев»" + \
                   (": комментарии — на суфлёре." if mode != MODE_BLOCK else ": блок за блоком — Ctrl+F12.")
        if d.result_style == STYLE_SCENARIO:
            msg += " Урок по этапам — откройте «Суфлёр урока» в шапке занятия."
        self.toast.show_message(msg, ms=9000)

    def export_current(self, fmt: str) -> None:
        v = self.current_view()
        if v:
            self.export_template(v.template, fmt)

    def export_template(self, t: Template, fmt: str) -> None:
        """fmt: md (урок в Markdown, картинки — папкой рядом) | ipynb | students (тетрадка для учеников —
        без подсказок преподавателю) | json."""
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
    def _touch(self) -> None:
        v = self.current_view()
        if v:
            v.template.updated = time.time()
            self._refresh_library_item(v.template)
        if self.job and self.engine.state in BUSY and self._find_block(self.job["bid"])[1] is None:
            self.cmd_stop()   # блок, который сейчас печатается, удалили — не допечатывать то, чего уже нет
        # пульт и суфлёр — чуть позже, а не на каждое нажатие клавиши: в большом блоке это заметно
        self._label_timer.start()
        self._save_timer.start()

    def _save_store(self) -> None:
        try:
            self.store.save()
        except OSError as e:
            self._notify(f"Не удалось сохранить занятия: {e}", warn=True)

    def _ensure_samples(self) -> str:
        """Встроенные примеры — по одному разу (и новым пользователям, и после обновления): пошаговый урок
        и «Пример занятия: все возможности». Возвращает id экскурсии, если её добавили только что
        (у обновившихся — её и открыть), иначе пустую строку."""
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
            # 0.9: пример урока для суфлёра — этапы, подсказки, код, картинки. Обновившимся — сразу открыть
            t = lesson_sample()
            # в новой базе первой остаётся экскурсия по программе, у обновившихся пример урока — наверх
            self.store.templates.insert(1 if self.store.created_fresh else 0, t)
            if not self.store.created_fresh and not tour_id:
                tour_id = t.id
            seen.append(LESSON_SAMPLE_ID)
            changed = True
        if changed:
            self._save_store()
            self._save_settings()
        return tour_id

    def _add_lesson_sample(self) -> None:
        from ..samples_lesson import lesson_sample
        t = lesson_sample()
        self.store.templates.insert(0, t)
        self._touch()
        self._fill_library(t.id)
        self.open_template(t.id)

    def _add_tour_sample(self) -> None:
        from ..samples import tour_template
        t = tour_template()
        self.store.templates.insert(0, t)
        self._touch()
        self._fill_library(t.id)
        self.open_template(t.id)

    def _add_steps_sample(self) -> None:
        t = self.store.insert(steps_sample_template())
        self._touch()
        self._fill_library(t.id)
        self.open_template(t.id)

    def _restore_session(self) -> None:
        s = self.settings
        tour_id = self._ensure_samples()
        if self._migrated:
            self._save_settings()
        if s.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(s.window_geometry.encode()))
        tid = tour_id or (s.current_tab if self.store.get(s.current_tab) else
                          (self.store.templates[0].id if self.store.templates else ""))
        self._fill_library(tid)
        if tid:
            self.open_template(tid)
        self._update_armed_label()
        if s.prompter_window:
            QTimer.singleShot(300, self.prompter_ctl.show)   # в прошлый раз суфлёр был открыт отдельным окном

    def _save_session(self) -> None:
        s = self.settings
        s.window_geometry = bytes(self.saveGeometry().toBase64()).decode()
        v = self.current_view()
        s.current_tab = v.template.id if v else ""
        s.open_tabs = [s.current_tab] if s.current_tab else []
        s.save()

    # ================================================================ печать
    def _armed(self):
        """Активный блок открытого образца → (view, block) или None."""
        v = self.current_view()
        if not v or not v.template.active_block:
            return None
        block = v.template.find_block(v.template.active_block)
        return (v, block) if block else None

    def _mode_for(self, block: Block) -> str:
        """Режим печати блока: текст (условие, пояснение) печатается целиком — шагов и строк у него нет."""
        return self.settings.print_mode if block.type == BLOCK_CODE else MODE_BLOCK

    def _typing_text(self, t: Template, block: Block) -> tuple[str, int, list | None, int, str]:
        """Что печатать из блока «целиком» или «по строкам» → (текст, смещение в блоке, карта позиций
        без комментариев, длина куска в блоке, описание для пульта)."""
        whole = self.settings.selection_whole_lines
        if block.type != BLOCK_CODE:
            mode = block.print_as if block.print_as in PRINT_MODES else PRINT_MARKDOWN
            lang = t.lang_near(block)
            part = {PRINT_MARKDOWN: "текст как Markdown", PRINT_PLAIN: "простой текст",
                    PRINT_COMMENT: f"текст комментарием ({lang})"}[mode]
            if not block.sel:
                text = printable(block.text, mode, lang)
                return text, 0, None, len(text), part
            raw, base = typing_slice(block.text, block.sel, whole)
            text = selection_text(block.text, raw, base, mode, lang)
            return text, base, None, len(raw), part + ", выделенные строки"
        text, base = typing_slice(block.text, block.sel, whole)
        src_len, omap = len(text), None
        part = "выделенные строки" if block.sel else "весь блок"
        if self.settings.strip_comments:
            text, omap = strip_comments(text, block.lang)
            part += ", без комментариев"
        return text, base, omap, src_len, part

    def _find_block(self, bid: str) -> tuple[Template | None, Block | None]:
        for t in self.store.templates:
            b = t.find_block(bid)
            if b:
                return t, b
        return None, None

    def _code_number(self, t: Template, block: Block) -> int:
        ids = [b.id for b in t.code_blocks()]
        return ids.index(block.id) + 1 if block.id in ids else 0

    # ---- печать по шагам: какой шаг следующий
    @staticmethod
    def _block_steps(block: Block) -> list[int]:
        return S.step_numbers(block.steps, block.text.count("\n") + 1)

    def _step_pointer(self, bid: str) -> int | None:
        """Какой шаг блока печатать следующим; None — все шаги напечатаны."""
        _t, b = self._find_block(bid)
        if not b:
            return None
        nums = self._block_steps(b)
        if bid not in self.step_next:
            return nums[0]
        k = self.step_next[bid]
        if k is None:
            return None
        return next((n for n in nums if n >= k), None)   # разметку поменяли — ближайший следующий

    def _step_index(self, block: Block, k: int | None) -> tuple[int, int]:
        nums = self._block_steps(block)
        return (nums.index(k) + 1 if k in nums else len(nums)), len(nums)

    def _set_step_pointer(self, bid: str, k: int | None) -> None:
        if self.job and self.job["bid"] == bid and self.engine.state in BUSY:
            self.cmd_stop()
        self.step_next[bid] = k
        self._invalidate_job_if_idle()
        self._refresh_step_views()
        self._update_armed_label()

    def _refresh_step_views(self) -> None:
        on = self.settings.print_mode == MODE_STEPS
        for v in self.views.values():
            v.apply_step_mode(on)

    def _on_steps_changed(self, _bid: str) -> None:
        self._invalidate_job_if_idle()
        if self.settings.print_mode == MODE_STEPS:
            self._refresh_step_views()
        self._label_timer.start()

    def _lines_of(self, block: Block) -> list:
        """Разбор блока по шагам (с учётом «Без комментариев»). Запоминается: пульт и суфлёр спрашивают
        его на каждое изменение, а в большом блоке разбор не бесплатный."""
        strip = self.settings.strip_comments
        key = (block.id, block.text, tuple(block.steps), block.lang, strip)
        if self._analysis is None or self._analysis[0] != key:
            self._analysis = (key, S.analyze(block.text, block.steps, block.lang, strip))
        return self._analysis[1]

    def _advance_step(self, bid: str, k: int) -> int | None:
        """Шаг k напечатан → указатель на следующий. Возвращает его (None — шаги кончились)."""
        _t, b = self._find_block(bid)
        nums = self._block_steps(b) if b else []
        nxt = next((n for n in nums if n > k), None)
        self.step_next[bid] = nxt
        self._refresh_step_views()
        return nxt

    def cmd_step_back(self) -> None:
        """Шаг назад без печати: следующим снова будет предыдущий шаг (чтобы переснять его)."""
        a = self._armed()
        if self.settings.print_mode != MODE_STEPS or (a and a[1].type != BLOCK_CODE):
            self._notify("«Шаг назад» работает в режиме «По шагам» у блока кода.")
            return
        if not a:
            return
        _v, block = a
        if self.engine.state in BUSY:
            self.cmd_stop()
        nums = self._block_steps(block)
        k = self._step_pointer(block.id)
        prev = nums[-1] if k is None else next((n for n in reversed(nums) if n < k), nums[0])
        self._set_step_pointer(block.id, prev)
        i, n = self._step_index(block, prev)
        where = ""
        if self.settings.step_nav != "home":
            # стрелки отсчитываются от курсора: после стирания он мог остаться где угодно — подскажем где
            lines = self._lines_of(block)
            cur = S.cursor_before(lines, prev)
            if cur is None:
                where = " и поставьте курсор туда, где начинался урок"
            else:
                doc = [sl.typed for sl in lines if sl.typed is not None and sl.step < prev]
                txt = doc[cur].strip()
                txt = f" «{txt[:40]}{'…' if len(txt) > 40 else ''}»" if txt else " (пустой)"
                where = f", затем поставьте курсор в конец строки {cur + 1} урока{txt}"
        self._notify(f"Следующим будет шаг {i} из {n}. Если он уже напечатан — сотрите его в редакторе{where}.",
                     tray=not self.isActiveWindow())

    # ---- пульт и суфлёр
    def _update_armed_label(self) -> None:
        if self.engine.state in BUSY and self.job:
            self._refresh_prompter()
            return   # во время печати на пульте — ход печати
        a = self._armed()
        if not a:
            self.strip.set_info("Нет активного блока — щёлкните по блоку кода или текста")
            self.strip.set_progress(0, 0, 0)
            self._set_title_status()
            self._refresh_prompter()
            return
        v, block = a
        title = f"<b style='color:{theme.c('text').name()}'>{block.display_title(self._code_number(v.template, block))}</b>"
        mode = self._mode_for(block)
        window = f" · окно: {PROFILE_SHORT[block.profile]}" if block.profile in PROFILE_SHORT else ""
        if mode == MODE_STEPS:
            k = self._step_pointer(block.id)
            nums = self._block_steps(block)
            if k is None:
                self.strip.set_info(f"По шагам: {title} · все шаги напечатаны · "
                                    f"{self.settings.hotkey_restart or 'кнопка ⟲'} — сначала")
                self.strip.set_progress(len(nums), len(nums), 1.0, "шаг.")
            else:
                i, n = self._step_index(block, k)
                lines = self._lines_of(block)
                count = sum(1 for sl in lines if sl.step == k and sl.typed is not None)
                self.strip.set_info(f"Дальше: шаг {i} из {n} · {title} · строк: {count}{window}")
                self.strip.set_progress(i - 1, n, (i - 1) / max(1, n), "шаг.")
        else:
            text, _base, _omap, _n, part = self._typing_text(v.template, block)
            if mode == MODE_LINES:
                part = "по строкам, " + part
            lines = text.count("\n") + 1 if text else 0
            self.strip.set_info(f"Печатать: {title} · {part} · {len(text)} симв.{window}")
            self.strip.set_progress(0, lines, 0)
        self._set_title_status()
        self._refresh_prompter()

    def _refresh_prompter(self) -> None:
        """Суфлёр: что дальше и что сказать. Только для «По строкам» и «По шагам».
        Открыто окно суфлёра — показывает оно, а суфлёр под пультом прячется."""
        s = self.settings
        if self.prompter_ctl.visible():
            self.prompter.hide()
            self.prompter_ctl.refresh()
            return
        a = self._armed()
        mode = self._mode_for(a[1]) if a else MODE_BLOCK
        if not s.show_prompter or mode == MODE_BLOCK or not a:
            self.prompter.hide()
            return
        v, block = a
        name = block.display_title(self._code_number(v.template, block))
        busy = self.engine.state in BUSY and self.job and self.job["bid"] == block.id
        if mode == MODE_STEPS:
            k = self.job["step"] if busy and self.job.get("kind") == MODE_STEPS else self._step_pointer(block.id)
            if k is None:
                self.prompter.show_content(f"{name} · все шаги напечатаны", f"{s.hotkey_restart} — сначала",
                                           [], [])
                return
            lines = self._lines_of(block)
            i, n = self._step_index(block, k)
            say = S.narration(block.text, lines, k, block.lang)
            code, hidden = S.preview(lines, k)
            head = "Печатается" if busy else "Дальше"
            self.prompter.show_content(f"{head}: шаг {i} из {n} · {name}",
                                       "" if busy else f"{s.hotkey_toggle} — напечатать шаг", say, code, hidden)
            return
        info = self._lines_prompt(block)
        if info is None:
            self.prompter.hide()
            return
        title, say, row = info
        if not row:
            self.prompter.show_content(f"{name} · строки кончились", "", [], [])
            return
        hint = "" if busy else f"{s.hotkey_toggle} — начать"
        if busy and self.engine.state == LINE_WAIT:
            hint = f"Enter или {s.hotkey_toggle} — напечатать"
        self.prompter.show_content(f"Дальше: {title} · {name}", hint, say, [row])

    def _lines_prompt(self, block: Block) -> tuple[str, list[str], str] | None:
        """По строкам: следующая непустая строка и комментарии перед ней → («строка N из M», что сказать,
        строка; "" — строки кончились). None — печатать нечего."""
        s = self.settings
        busy = self.engine.state in BUSY and self.job and self.job["bid"] == block.id
        job = self.job if busy and self.job.get("kind") == MODE_LINES else self._job_for_armed()
        if not job or job.get("kind") != MODE_LINES:
            return None
        text = job["text"]
        rows = text.split("\n")
        pos = getattr(self, "_last_pos", 0) if busy else 0
        cur = text.count("\n", 0, pos) if busy and pos else -1
        nxt = next((r for r in range(cur + 1, len(rows)) if rows[r].strip()), None)
        if nxt is None:
            return f"{len(rows)} из {len(rows)}", [], ""
        starts = [0]
        for r in rows[:-1]:
            starts.append(starts[-1] + len(r) + 1)

        def src(i: int) -> int:   # позиция в тексте задания → в тексте блока
            omap = job["omap"]
            if omap is not None:
                i = omap[i] if i < len(omap) else job["src_len"]
            return job["base"] + i

        def row_start(r: int) -> int:
            """Начало строки r задания в тексте блока. Через «\\n» перед ней: он стоит сразу перед
            этой строкой исходника — после вырезанных строк-комментариев, а не перед ними."""
            if r == 0:
                return src(0) if rows[0] else job["base"]
            return src(starts[r] - 1) + 1

        def line_end(i: int) -> int:
            e = block.text.find("\n", i)
            return len(block.text) if e < 0 else e

        # что сказать: строки-комментарии после напечатанной строки (её хвостовой комментарий уже звучал)
        # и до конца следующей — вместе с её хвостовым комментарием, как и по шагам
        a_src = line_end(row_start(cur)) if cur >= 0 else job["base"]
        b_end = line_end(row_start(nxt))
        say = [comment_text(block.text[x:y]) for x, y in comment_spans(block.text, block.lang)
               if a_src <= x < b_end] if s.strip_comments else []
        return f"строка {nxt + 1} из {len(rows)}", [t for t in say if t], rows[nxt]

    # ---- задание на печать
    def _job_for_armed(self) -> dict | None:
        a = self._armed()
        if not a:
            return None
        v, block = a
        if block.type in (BLOCK_STAGE, BLOCK_IMAGE):
            return None          # этап урока и картинка — для суфлёра, их не печатают
        mode = self._mode_for(block)
        profile = block.profile if block.profile in PROFILES else ""   # окно, выбранное у блока
        if mode == MODE_STEPS:
            k = self._step_pointer(block.id)
            if k is None or not block.text.strip():   # пустой блок — «нечего печатать», а не «шаг без кода»
                return None
            text, st, lang = block.text, list(block.steps), block.lang

            def build(s: Settings, text=text, st=st, lang=lang, k=k):
                return S.build_step_units(S.analyze(text, st, lang, s.strip_comments), k, s, s.step_nav)
            job = {"kind": MODE_STEPS, "tid": v.template.id, "bid": block.id, "step": k, "base": 0, "text": text,
                   "omap": None, "src_len": len(text), "builder": build, "profile": profile,
                   "key": (tuple(st), k, self.settings.strip_comments, self.settings.step_nav)}
            if not build(self.settings):
                job["empty"] = True   # в шаге только комментарии — печатать нечего, это «слова»
            return job
        text, base, omap, src_len, _part = self._typing_text(v.template, block)
        if not text.strip():
            return None
        builder = None
        if mode == MODE_LINES:
            def builder(s: Settings, text=text):
                return build_units(text, s, line_wait=True)
        return {"kind": mode, "tid": v.template.id, "bid": block.id, "base": base, "text": text, "omap": omap,
                "src_len": src_len, "builder": builder, "key": None, "profile": profile}

    # ---- картинка: в буфер обмена и Ctrl+V туда, где курсор
    def _paste_image_block(self, block: Block, from_button: bool = False) -> bool:
        """Картинку не набрать с клавиатуры — её вставляют: копия в буфер обмена и Ctrl+V в окно с курсором.
        В markdown-ячейке Jupyter (и в VS Code) из неё получается вложение ячейки."""
        from ..storage import media_path
        local = media_path(block.text)
        img = QImage(str(local)) if local is not None else QImage()
        if img.isNull():
            self._notify("Нет файла картинки — вставьте её в блок заново («Файл…» или «Из буфера»).", warn=True,
                         tray=not self.isActiveWindow())
            return False
        QGuiApplication.clipboard().setImage(img)
        if from_button:
            if self.settings.minimize_on_button_start:
                self.showMinimized()
            delay = max(1, int(self.settings.button_countdown_s)) * 1000
        else:
            delay = max(50, int(self.settings.hotkey_start_delay_ms))
        self._paste_until = time.time() + 4.0
        QTimer.singleShot(delay, self._paste_when_ready)
        return True

    def _paste_when_ready(self) -> None:
        if winapi.modifiers_down() and time.time() < self._paste_until:
            QTimer.singleShot(30, self._paste_when_ready)     # ждём, пока отпустят Ctrl/Alt хоткея
            return
        if winapi.is_own_window(winapi.foreground_window()):
            self._notify("Картинка в буфере обмена. Поставьте курсор в ячейку Jupyter (markdown, режим правки) "
                         "и нажмите Ctrl+V — или хоткей ещё раз, уже из того окна.", warn=True)
            return
        winapi.tap(0x56, winapi.VK_CONTROL)                    # Ctrl+V
        self._notify("Картинка вставлена (Ctrl+V). В Jupyter — в markdown-ячейку в режиме правки.", quiet=True)

    def _same_job(self, job: dict | None) -> bool:
        return bool(job and self.job and all(job.get(k) == self.job.get(k)
                                             for k in ("kind", "tid", "bid", "base", "text", "key", "profile")))

    def _load_job(self, job: dict) -> None:
        self._clear_progress()
        self.job = job
        self.engine.load(job["text"], job.get("profile", ""), job_key=job["bid"], builder=job.get("builder"))

    def _invalidate_job_if_idle(self) -> None:
        if self.engine.state in (IDLE, FINISHED):
            self.job = None

    def _start_params(self, from_button: bool, countdown: int | None = None) -> tuple[float, int]:
        s = self.settings
        if from_button:
            if s.minimize_on_button_start:
                self.showMinimized()
            return 0.0, s.button_countdown_s if countdown is None else countdown
        return s.hotkey_start_delay_ms / 1000, countdown or 0

    def _skip_empty_step(self, job: dict) -> None:
        """Шаг без кода (одни комментарии-слова): отмечаем сказанным и переходим к следующему."""
        _t, b = self._find_block(job["bid"])
        i, n = self._step_index(b, job["step"]) if b else (0, 0)
        nxt = self._advance_step(job["bid"], job["step"])
        self._update_armed_label()
        tail = f" Дальше — шаг {i + 1}." if nxt is not None else " Шаги кончились."
        self._notify(f"Шаг {i} из {n} — только слова, кода в нём нет.{tail}", tray=not self.isActiveWindow())

    def _remember_press(self) -> None:
        """Состояние в момент нажатия кнопки «Пауза» (или открытия меню трея): пока кнопку отпускают,
        окно программы становится активным, и печать сама встаёт на паузу (сменилось окно)."""
        st = self.engine.state
        if st == PAUSED and time.monotonic() - self.engine.auto_paused_at < 1.0:
            # печать встала на паузу сама от этого же щелчка: значок в трее — окно Проводника, щелчок по
            # нему — «клик мышью»; окно программы при нажатии стало активным — «сменилось окно».
            # До щелчка печать шла
            st = RUNNING
        self._press_state = st

    def cmd_toggle(self, from_button: bool = False, countdown: int | None = None,
                   pressed: bool = False) -> None:
        st = self.engine.state
        press_state, self._press_state = getattr(self, "_press_state", None), None
        if pressed and press_state in (RUNNING, COUNTDOWN) and st not in (RUNNING, COUNTDOWN):
            # нажимали «Пауза» во время печати — оставить паузу, а не продолжить (раньше кнопка ставила
            # паузу и тут же снова запускала печать с отсчётом и сворачиванием окна). Если, пока кнопку
            # отпускали, блок допечатался или строка дошла до ожидания Enter, — тоже ничего не запускать
            if st == PAUSED:
                self._notify("Пауза.", quiet=True)
            return
        if st == LINE_WAIT:
            # по строкам: хоткей или кнопка = «следующая строка» — как продолжение после паузы
            # (задержка хоткея, с кнопки — отсчёт и сворачивание окна, чтобы фокус вернулся в редактор)
            self.engine.continue_line(False, *self._start_params(from_button, countdown))
            return
        if self.engine.active:   # печать идёт или готовится — пауза
            self.engine.pause()
            return
        a = self._armed()
        if a and a[1].type == BLOCK_IMAGE and st != PAUSED:
            self._paste_image_block(a[1], from_button)   # картинка «печатается» вставкой: в Jupyter — вложением
            return
        if a and self._mode_for(a[1]) == MODE_STEPS and self._step_pointer(a[1].id) is None \
                and st != PAUSED:
            self._notify(f"Все шаги блока напечатаны. {self.settings.hotkey_restart or 'Кнопка ⟲'} — сначала, "
                         f"{self.settings.hotkey_next_block or 'выбор блока'} — следующий блок.",
                         tray=not self.isActiveWindow())
            return
        job = self._job_for_armed()
        if job is None:
            self._notify("Нечего печатать: выберите (щёлкните) непустой блок кода или текста.", warn=True)
            return
        if st == PAUSED and self._same_job(job):
            self.engine.resume(*self._start_params(from_button, countdown))
            return
        if job.get("empty"):
            if st == PAUSED:
                self.cmd_stop()   # на паузе стоит другое задание — его уже не продолжить
            self._skip_empty_step(job)
            return
        if not self._same_job(job) or st == FINISHED or st == PAUSED:
            if st == PAUSED:
                self._notify("Текст для печати изменился (занятие, выделение или настройки) — "
                             "печать начнётся с начала.")
            self._load_job(job)
        self.engine.start(*self._start_params(from_button, countdown))

    def cmd_restart(self, from_button: bool = False) -> None:
        a = self._armed()
        if a and self._mode_for(a[1]) == MODE_STEPS:
            self.step_next[a[1].id] = self._block_steps(a[1])[0]   # по шагам «сначала» — с первого шага
            self._refresh_step_views()
        job = self._job_for_armed()
        if job is None:
            self._notify("Нечего печатать: выберите (щёлкните) непустой блок кода или текста.", warn=True)
            return
        if job.get("empty"):
            self.cmd_stop()
            self._skip_empty_step(job)
            return
        self._load_job(job)
        self.engine.restart(*self._start_params(from_button))

    def cmd_stop(self) -> None:
        self.engine.stop()
        self._clear_progress()
        self.job = None
        self._update_armed_label()

    def cmd_block(self, d: int) -> None:
        v = self.current_view()
        if not v:
            return
        t = v.template
        nav = t.nav_blocks()
        if not nav:
            return
        ids = [b.id for b in nav]
        i = ids.index(t.active_block) if t.active_block in ids else -1
        j = max(0, min(len(ids) - 1, i + d))
        b = nav[j]
        if j != i:   # на краю ленты переходить некуда — печать на паузе не сбрасываем
            if self.engine.state in BUSY:
                self.cmd_stop()
            v.go_to_block(b.id)
        n = t.code_number(b)
        where = f" ({n} из {len(t.code_blocks())})" if n else ""
        self._notify(f"Активный блок: {b.display_title(n)}{where}", tray=not self.isActiveWindow())

    def cmd_next_tab(self, d: int = 1) -> None:
        lib = self.library.list
        rows = [k for k in range(lib.count()) if not lib.item(k).isHidden()]
        if not rows:
            return
        self.engine.pause()   # идёт или готовится — пауза (иначе ничего)
        cur = lib.currentRow()
        i = rows.index(cur) if cur in rows else -1
        it = lib.item(rows[(i + d) % len(rows)])
        self.open_template(it.data(ROLE_ID))
        v = self.current_view()
        if v and not self.isActiveWindow():
            self._notify(f"Занятие: {v.template.title}", tray=True)

    def _on_hotkey(self, action: str) -> None:
        if self.prompter_ctl.on_hotkey(action):
            return   # суфлёр «печатаю сам»: хоткеи листают шаги, программа не печатает
        if action == "hotkey_toggle":
            self.cmd_toggle()
        elif action == "hotkey_restart":
            self.cmd_restart()
        elif action == "hotkey_stop":
            self.cmd_stop()
        elif action == "hotkey_next_block":
            self.cmd_block(+1)
        elif action == "hotkey_prev_block":
            self.cmd_block(-1)
        elif action == "hotkey_next_tab":
            self.cmd_next_tab(+1)
        elif action == "hotkey_step_back":
            self.cmd_step_back()

    # ---- сигналы движка
    def _on_guard(self, kind: str) -> None:
        if self.engine.state != RUNNING:
            # защита осталась включённой, хотя печать уже стоит (запоздалый сигнал) — снять, иначе
            # хук глотал бы все клавиши пользователя
            self.guard.disarm()
            return
        self.engine.pause("нажата клавиша" if kind == "key" else "клик мышью")
        # без всплывающего уведомления Windows: оно со звуком, а пауза и так видна (значок в трее)
        self._notify("Пауза: вы нажали клавишу." if kind == "key" else "Пауза: вы кликнули мышью.",
                     tray=False, quiet=True)

    def _on_target(self, exe: str) -> None:
        self._target = app_name(exe)

    def _on_state(self, _signalled: str = "") -> None:
        # сигналы из потока печати приходят с опозданием: после «Стоп» может прийти запоздалое
        # «Печатает». Поэтому — только текущее состояние движка, иначе защита включится у стоящей печати
        st = self.engine.state
        if st == RUNNING and self.settings.guard_enabled:
            self.guard.arm()
        else:
            self.guard.disarm()
        self.guard.watch_enter(st == LINE_WAIT)   # по строкам: ждём Enter пользователя
        self.strip.set_state(st)
        kind = logo.STATE_KIND.get(st, logo.IDLE)
        self.tray.setIcon(self.tray_icons[kind])
        self.tray.setToolTip(f"{APP_NAME}: {STATE_TEXT.get(st, st)}")
        if st == FINISHED and self.job:
            self._clear_progress()   # подсветка в блоке больше не нужна, а на пульте — итог
            lines = self.job["text"].count("\n") + 1
            self.strip.set_progress(lines, lines, 1.0)
            self.strip.set_info(f"Напечатано → {self._target}" if self._target else "Напечатано")
        elif st in (IDLE, FINISHED):
            if st == IDLE:
                self._clear_progress()
            self._update_armed_label()
        else:
            self._show_job_progress()
            self._refresh_prompter()
        self._set_title_status()
        self.prompter_ctl.refresh()

    def _set_title_status(self, extra: str = "") -> None:
        st = self.engine.state
        text = STATE_TEXT.get(st, st)
        if self.job and st in BUSY:
            t, b = self._find_block(self.job["bid"])
            if b and t:
                text += f" · {b.display_title(self._code_number(t, b))}"
                if self.job.get("kind") == MODE_STEPS:
                    i, n = self._step_index(b, self.job["step"])
                    text += f" · шаг {i} из {n}"
                elif self._line_info:
                    text += f" · строка {self._line_info[0]} из {self._line_info[1]}"
        elif st == IDLE and self.settings.hotkey_toggle:
            text += f" · {self.settings.hotkey_toggle} — старт"
        if extra:
            text = extra
        self.titlebar.set_status(text, STATE_TOKENS.get(st, "ok"))
        self.setWindowTitle(f"{APP_NAME} — {text}")

    _line_info: tuple[int, int] | None = None

    def _on_progress(self, pos: int, total: int) -> None:
        self._last_pos = pos
        # загрузка задания тоже шлёт progress(0) — блок гасим только когда печать действительно идёт:
        # если старт сорвётся (курсор в своём окне и т. п.), состояние так и останется «Готов»
        if self.engine.state in BUSY:
            self._show_job_progress()

    def _show_job_progress(self) -> None:
        job = self.job
        if not job:
            return
        text = job["text"]
        pos = max(0, min(getattr(self, "_last_pos", 0), len(text)))
        v = self.views.get(job["tid"])
        w = v.code_widget(job["bid"]) if v else None
        where = f"→ {self._target}" if self._target else ""
        if job.get("kind") == MODE_STEPS:
            _t, b = self._find_block(job["bid"])
            i, n = self._step_index(b, job["step"]) if b else (1, 1)
            self._line_info = None
            self.strip.set_progress(i, n, (i - 0.5) / max(1, n), "шаг.")
            self.strip.set_info(f"{where} · шаг {i} из {n}" if where else f"шаг {i} из {n}")
            if w:
                w.set_step_progress(job["step"], pos)
        else:
            total_lines = text.count("\n") + 1
            line = text.count("\n", 0, pos) + 1
            self._line_info = (line, total_lines)
            self.strip.set_progress(line if pos else 0, total_lines, pos / max(1, len(text)))
            if self.engine.state == LINE_WAIT:
                where = f"{where} · Enter — следующая строка" if where else "Enter — следующая строка"
            self.strip.set_info(where)
            # подсветка в блоке: напечатанное — ярко, остальное — приглушённо
            if w:
                omap = job["omap"]
                src = (omap[pos] if pos < len(omap) else job["src_len"]) if omap is not None else pos
                w.set_progress(job["base"], job["base"] + src, job["base"] + job["src_len"])
        self._set_title_status()

    def _clear_progress(self) -> None:
        self._last_pos = 0
        self._line_info = None
        for v in self.views.values():
            v.clear_progress()

    def _on_countdown(self, n: int) -> None:
        if n and self.engine.state == COUNTDOWN:   # после паузы отсчёт на пульте не возвращаем
            self.strip.set_state(COUNTDOWN, n)
            self._set_title_status(f"Старт через {n}… Поставьте курсор в нужное окно")
            self.tray.setToolTip(f"{APP_NAME}: старт через {n}")

    def _on_finished(self) -> None:
        job = self.job
        if job and job.get("kind") == MODE_STEPS:
            _t, b = self._find_block(job["bid"])
            i, n = self._step_index(b, job["step"]) if b else (0, 0)
            nxt = self._advance_step(job["bid"], job["step"])
            self.job = None
            self._update_armed_label()
            if nxt is not None:
                self._notify(f"Шаг {i} из {n} напечатан. Дальше — шаг {i + 1}.", quiet=True)
                return
            self._notify("Шаг напечатан — он был единственным." if n == 1 else
                         f"Все {n} {_plural(n, 'шаг', 'шага', 'шагов')} напечатаны.", quiet=True)
        else:
            self._notify("Набор завершён.", quiet=True)
        if job and self.prompter_ctl.after_block_done():
            return   # открыт суфлёр — он сам ведёт к следующему блоку занятия
        if self.settings.auto_advance and job:
            v = self.views.get(job["tid"])
            if v and v is self.current_view():
                ids = [b.id for b in v.template.nav_blocks()]
                if job["bid"] in ids and ids.index(job["bid"]) + 1 < len(ids):
                    QTimer.singleShot(400, lambda: self.cmd_block(+1))

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
        tip = "Эфир: таймер вебинара по шаблону и экран для учеников — фон, зарядка, перерыв"
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
    def _busy_typing(self) -> bool:
        return self.engine.state in BUSY

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
            self._notify(f"Доступна новая версия {rel.version} — кнопка слева внизу.", tray=True)

    def _on_update_check_failed(self, text: str, manual: bool) -> None:
        if manual:
            QMessageBox.warning(QApplication.activeModalWidget() or self.settings_win or self, "Обновления", text)

    def _on_update_ready(self, rel) -> None:
        self._show_update_button(rel)
        if self.settings.update_mode == MODE_AUTO:
            text = f"Версия {rel.version} скачана и установится при выходе из программы."
        else:
            text = f"Версия {rel.version} готова к установке — кнопка слева внизу."
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
        self.prompter_ctl.shutdown()
        self.lesson.shutdown()          # окно суфлёра закрывается вместе с программой
        self.efir.shutdown()
        self.engine.stop()
        self._save_timer.stop()
        self._save_store()
        self._save_session()
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
