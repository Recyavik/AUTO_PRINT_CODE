"""Программа без виджетов: уроки и планы, сохранение, импорт и экспорт, печать по хоткеям, эфир, обновления, сессия.

Окно — одно (ui/app_window.py, встроенный браузер со страницей /app). Всё, что раньше делало главное окно Qt
(список уроков, меню, тосты, вопросы), теперь показывает страница: App только сообщает об изменениях сигналом
changed(тема) и просит открыть нужный экран сигналом navigate(hash). Имена методов — как у прежнего MainWindow:
на них опираются контроллеры урока и эфира.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QFileDialog

from . import APP_NAME, __version__, system, updater
from .guard import InputGuard
from .hotkeys import HotkeyManager, parse_hotkey
from .importers import export_ipynb
from .storage import KIND_PLAN, Settings, Template, TemplateStore
from .typer import COUNTDOWN, FINISHED, IDLE, LINE_WAIT, PAUSED, RUNNING
from .ui import logo
from .ui.efir_control import EfirController
from .ui.lesson_control import LessonController
from .ui.print_control import BUSY, MODE_BLOCK, MODE_LINES, MODE_STEPS, PrintController
from .ui.theme import theme
from .ui.updates import MODE_AUTO, MODE_DOWNLOAD, UpdateManager

log = logging.getLogger("autoprint")

STATE_TEXT = {IDLE: "Готов", COUNTDOWN: "Отсчёт…", RUNNING: "Печатает", PAUSED: "Пауза", FINISHED: "Готово",
              LINE_WAIT: "Ждёт Enter"}

# действия глобальных хоткеев: поле настроек, подпись, тихий ли он
HOTKEYS = [
    ("hotkey_toggle", "Старт / пауза / продолжить"),
    ("hotkey_restart", "Начать сначала"),
    ("hotkey_stop", "Остановить"),
    ("hotkey_next_block", "Следующий блок кода"),
    ("hotkey_prev_block", "Предыдущий блок кода"),
    ("hotkey_next_tab", "Следующий урок"),
    ("hotkey_step_back", "Шаг назад без печати (режим «По шагам»)"),
]


def lesson_meta(t, plan_title: str = "", topics: int = 0) -> str:
    """«1 ч 30 мин · 12 этапов · 5 кодов» — что в уроке, одной строкой. План: «План · 1 ч 30 мин · 9 этапов ·
    уроков: 3»; урок по плану — в конце «план «X»»."""
    from .efir.model import fmt_minutes
    from .storage import BLOCK_STAGE, is_printable
    from .ui.print_control import _plural
    stages = [b for b in t.blocks if b.type == BLOCK_STAGE]
    codes = sum(1 for b in t.blocks if is_printable(b))
    parts = ["План"] if t.kind == KIND_PLAN else []
    if stages:
        total = sum(max(0, int(b.minutes or 0)) for b in stages)
        parts.append(fmt_minutes(total))
        parts.append(f"{len(stages)} {_plural(len(stages), 'этап', 'этапа', 'этапов')}")
    if t.kind == KIND_PLAN:
        parts.append(f"уроков: {topics}")
        return " · ".join(parts)
    parts.append(f"{codes} {_plural(codes, 'код', 'кода', 'кодов')}" if codes else "без кода")
    if plan_title:
        parts.append(f"план «{plan_title}»")
    return " · ".join(parts)


def apply_migrations(s: Settings, store: TemplateStore | None = None) -> bool:
    """Разовые переделки настроек и базы при обновлении (autoprint/migrations.py). True — что-то поменялось."""
    from . import migrations
    return migrations.apply(s, store)


class App(QObject):
    changed = Signal(str)      # что поменялось: library | settings | print | update | efir | window | jobs | notice
    navigate = Signal(str)     # открыть экран страницы: "#/lessons", "#/lesson/<id>", "#/settings/ai"…

    def __init__(self, settings: Settings, store: TemplateStore, web: bool = True) -> None:
        super().__init__()
        self.settings = settings
        self.store = store
        self._migrated = apply_migrations(settings, store)
        self.notice = {"seq": 0, "text": "", "warn": False, "action": None}
        self.view = ""                      # последний запрошенный экран (hash)
        self.nav = {"seq": 0, "hash": ""}   # просьба странице открыть экран (seq растёт)
        self.drop_info = {"seq": 0, "files": []}   # файлы, перетащенные в окно
        self.update_info: dict | None = None
        self.jobs = None                    # фоновые работы (jobs.py) — Task 11

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

        self._save_timer = QTimer(self, singleShot=True, interval=700, timeout=self._save_store)
        self._settings_timer = QTimer(self, singleShot=True, interval=400, timeout=self._save_settings)

        self.updates = UpdateManager(settings, self)
        self.updates.checked.connect(self._on_update_checked)
        self.updates.check_failed.connect(self._on_update_check_failed)
        self.updates.ready.connect(self._on_update_ready)
        self.updates.download_failed.connect(lambda t: log.warning("Обновление не скачано: %s", t))
        self.relaunch_requested = False     # app.py перезапустит программу после выхода
        self._auto_checked_once = False
        self._quitting = False
        self._tray_hint_shown = False

        self.efir = EfirController(self)    # экран учеников, эфир по урокам и шаблонам вебинаров
        self.efir.message.connect(lambda t, warn: self._notify(t, warn=warn))
        self.printer.live_id = self.efir.live_lesson_id
        self.lesson = LessonController(self)

        from .ui.app_window import AppWindow
        from .ui.tray import Tray
        self.tray = Tray(self)
        self.window = AppWindow(self, web=web)
        self.window.close_handler = self.on_window_close
        from .app_cmd import AppCommands
        self.commands = AppCommands(self)   # команды страницы окна (/app/cmd, /app/call)
        self._pub_timer = QTimer(self, singleShot=True, interval=150, timeout=self.publish_now)
        self.changed.connect(self._schedule_publish)
        self.navigate.connect(self._on_navigate)
        self.efir.ensure_server()
        # идёт урок или эфир — этапы сменяются по часам: окну — свежее «этап i из n» раз в 5 с
        self._live_timer = QTimer(self, interval=5000,
                                  timeout=lambda: self._schedule_publish() if self.efir.live_webinar() else None)
        self._live_timer.start()
        theme.changed.connect(self._on_theme)
        self._apply_settings()
        self._apply_hotkeys()
        self._restore_session()
        self.efir.live_changed.connect(lambda: self.changed.emit("library"))
        self.efir.webinars_changed.connect(lambda: self.changed.emit("efir"))
        QTimer.singleShot(1200, self.efir.restore)   # эфир шёл до перезапуска — вернуть его

        QTimer.singleShot(8000, self._auto_check_updates)
        self._update_timer = QTimer(self, interval=3600 * 1000, timeout=self._auto_check_updates)
        self._update_timer.start()
        QTimer.singleShot(1500, self._show_update_result)
        if settings.pin_tray_icon:      # значок у часов: запись в реестре появится после показа значка
            system.pin_tray_icon(True)
        if settings.autostart:          # путь программы мог измениться — обновить запись автозапуска
            system.set_autostart(True)

    # ================================================================ состояние окна (канал app)
    def _schedule_publish(self, _topic: str = "") -> None:
        """Изменений бывает много подряд (ход печати, правки) — странице уходит не чаще раза в 150 мс."""
        if not self._pub_timer.isActive():
            self._pub_timer.start()

    def publish_now(self) -> None:
        from .app_state import app_state
        self._pub_timer.stop()
        if self.efir.server.running:
            self.efir.server.publish(app_state(self), channel="app")

    def _on_navigate(self, hash_: str) -> None:
        self.nav = {"seq": self.nav["seq"] + 1, "hash": hash_}
        self.publish_now()

    def drop(self, paths: list[str]) -> None:
        """Файлы перетащили в окно — страница решает, что с ними делать (импорт, материал, картинка, видео)."""
        files = []
        for p in paths:
            f = Path(p)
            if f.is_file():
                files.append({"path": str(f), "name": f.name, "size": f.stat().st_size, "ext": f.suffix.lower()})
        if files:
            self.drop_info = {"seq": self.drop_info["seq"] + 1, "files": files}
            self.publish_now()

    # ================================================================ экраны и окно
    def show_view(self, hash_: str) -> None:
        """Открыть экран в окне программы (страница слушает navigate) и показать окно."""
        self.view = hash_
        self.navigate.emit(hash_)
        self.show_window()

    def show_window(self) -> None:
        w = self.window
        if w.isMinimized() or not w.isVisible():
            w.showMaximized() if w.isMaximized() else w.showNormal()
        w.raise_()
        w.activateWindow()

    _show_window = show_window

    def set_compact(self, on: bool) -> None:
        self.window.set_compact(on)
        self.show_window()
        self._settings_timer.start()
        self.changed.emit("window")

    def open_settings(self, page: str = "") -> None:
        self.show_view("#/settings" + (f"/{page}" if page else ""))

    def import_files(self, tab: str = "file") -> None:
        """Импорт и урок через нейросеть — это «Новый урок» (шаги в окне)."""
        self.show_view("#/new")

    def _on_theme(self) -> None:
        self.window.restyle_frame()
        self._on_state(self.engine.state)
        self.changed.emit("settings")

    # ================================================================ настройки
    def _apply_settings(self) -> None:
        s = self.settings
        theme.set_mode(s.theme)
        self.window.apply_pin()
        self.printer.apply_settings()
        self._on_state(self.engine.state)

    def _apply_hotkeys(self) -> None:
        s = self.settings
        self.hotkeys.set_bindings({k: getattr(s, k) for k, _t in HOTKEYS})
        self.guard.set_hotkeys({hk for k, _t in HOTKEYS if (hk := parse_hotkey(getattr(s, k)))})

    def save_settings(self) -> None:
        self._settings_timer.stop()
        self.settings.save()

    _save_settings = save_settings

    def _settings_touched(self) -> None:
        """Изменение с экрана урока: сохранить чуть позже, окну — показать новое значение."""
        self._settings_timer.start()
        self.changed.emit("settings")

    def on_setting_changed(self, key: str) -> None:
        """Изменение из «Настроек» (ключ поля или группа hotkeys / ai)."""
        s = self.settings
        self._settings_timer.start()
        self.changed.emit("settings")
        if key == "sound_volume":
            self.printer.on_settings_changed(key)
            return
        if key == "hotkeys":
            self._apply_hotkeys()
            self._set_title_status()
            self.lesson.schedule_publish()     # «Следующим · Ctrl+F9» на экране урока
            return
        if key == "update_skip_version" or key.startswith("update_") or key == "ai":
            return
        if key == "pin_tray_icon":
            system.pin_tray_icon(s.pin_tray_icon, wait_s=2.0)
            return
        if key == "autostart":
            if not system.set_autostart(s.autostart):
                s.autostart = system.autostart_enabled()   # переключатель — как на самом деле
                self._notify("Не удалось изменить автозапуск (нет доступа к реестру).", warn=True)
            return
        if key in ("close_to_tray", "samples_seen"):
            return
        self.printer.on_settings_changed(key)
        self._apply_settings()

    _on_setting_changed = on_setting_changed

    def hotkey_capture(self, on: bool) -> None:
        """Пока в «Настройках» записывают сочетание — глобальные хоткеи сняты (иначе запись их не увидит)."""
        if on:
            self.hotkeys.set_bindings({})
        else:
            self._apply_hotkeys()

    def test_sound(self, style: str, volume: int) -> None:
        player = self.printer.player
        player.set_style(style)
        player.set_volume(volume)
        if getattr(player, "loading", False):
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

    # ================================================================ уроки
    def _fill_library(self, select_id: str = "") -> None:
        """Список уроков поменялся — страница перерисует «Уроки»."""
        self.changed.emit("library")

    def refresh_library_item(self, t: Template | None = None) -> None:
        self.changed.emit("library")

    def _selected(self) -> Template | None:
        return self.printer.focus()

    def _new_from_menu(self, key: str) -> None:
        if key.startswith("plan:"):
            self.new_topic(key[5:])
        elif key.startswith("newplan:"):
            self.new_plan(key[8:])
        else:
            self.new_template(key)

    def open_lesson(self, tid: str, ask: bool = True) -> bool:
        """Открыть урок в окне. Идёт другой урок — при ask не открывать, а спросить на странице (действие в
        уведомлении повторит открытие с force); ask=False — уже спросили, идущий урок завершается."""
        t = self.store.get(tid)
        if t is None:
            return False
        live = self.efir.live_lesson_id()
        if live and live != tid:
            if ask:
                cur = self.store.get(live)
                name = cur.title if cur else "урок"
                self._notify(f"Идёт урок «{name}». Завершить его и открыть «{t.title}»?",
                             action={"label": "Завершить и открыть", "cmd": {"cmd": "open", "lesson": tid, "force": True}})
                return False
            self.efir.stop_live()
        self.printer.set_focus(tid)
        self.settings.page_lesson = tid
        self._settings_timer.start()
        self.lesson.schedule_publish()
        self.show_view(f"#/lesson/{tid}")
        return True

    def rename(self, t: Template, title: str) -> bool:
        title = (title or "").strip()
        if not title or title == t.title:
            return False
        t.title = title
        self.touch(t)
        self.lesson.schedule_publish()
        return True

    def new_template(self, structure: str = "empty") -> Template:
        """Новый урок: пустой (этап «Начало» и заметка «Говоришь») или по шаблону структуры — сразу в окне."""
        t = self.store.add_from_structure(structure if isinstance(structure, str) else "empty")
        self.touch(t)
        self._fill_library(t.id)
        self.open_lesson(t.id, ask=False)
        return t

    def new_from_presentation(self, path: str = "") -> Template | None:
        """Урок из презентации: PDF или PowerPoint → урок по слайдам (заметки докладчика — плашками)."""
        if self.efir.live_webinar() is not None:
            self._notify("Идёт эфир — урок из презентации подготовьте после него: импорт занимает до минуты, "
                         "и программа на это время занята.", warn=True)
            return None
        if not path:
            return None
        notes: list[str] = []
        try:
            if path.lower().endswith(".pptx"):
                t, notes = self.pptx_lesson(path)
            else:
                from .slides import from_pdf
                t = from_pdf(path)
        except Exception as e:   # noqa: BLE001 — сказать, что не так с файлом
            log.warning("Урок из презентации %s не создан: %s", path, e)
            self._notify(f"Не получилось открыть презентацию: {e}", warn=True)
            return None
        self.store.insert(t)
        self.touch(t)
        self._fill_library(t.id)
        slides_n = sum(1 for b in t.blocks if b.type == "image")
        self._notify(f"Урок «{t.title}»: слайдов — {slides_n}. " + " ".join(notes), tray=bool(notes))
        self.open_lesson(t.id)
        return t

    def pptx_lesson(self, path: str, pdf: str | None = None) -> tuple[Template, list[str]]:
        """PowerPoint → урок по слайдам. Картинок нет (PowerPoint не сохранил PDF) — попросить PDF этой презентации."""
        from . import slides
        t, warns, need = slides.from_pptx(path, pdf=pdf)
        if need:
            pick, _ = QFileDialog.getOpenFileName(self.window, f"PDF презентации «{Path(path).stem}» — для картинок "
                                                  "слайдов", str(Path(path).parent), "PDF (*.pdf)")
            if pick:
                t, warns, _need = slides.from_pptx(path, pdf=pick, export=False)
        return t, warns

    def recognize_lesson(self, t: Template) -> bool:
        """Тетрадка-сценарий (⏱ 00:00–00:03 · …, 🗣 Говоришь) → новый урок с этапами рядом с исходным."""
        from .scenario_import import looks_like_scenario, recognize
        if not looks_like_scenario(t.blocks):
            self._notify("Не нашёл в уроке заголовков с ⏱ 00:00–00:05 — распознавать нечего.", tray=True)
            return False
        r = recognize(t)
        self.store.templates.insert(self.store.templates.index(t) + 1, r)
        self.touch(r)
        self._fill_library(r.id)
        stages = sum(1 for b in r.blocks if b.type == "stage")
        if self.efir.live_lesson_id():
            self._notify(f"Готово: «{r.title}» — этапов {stages}, в списке уроков. Идёт урок — откройте копию "
                         "после него.", tray=True)
            self.lesson.schedule_publish()
            return True
        self._notify(f"Готово: «{r.title}» — этапов {stages}. Исходный урок не изменён.", tray=True)
        self.open_lesson(r.id, ask=False)
        return True

    def duplicate(self, t: Template) -> Template:
        c = self.store.duplicate(t)
        self.touch(c)
        self._fill_library(c.id)
        return c

    _duplicate = duplicate

    # ================================================================ планы уроков
    def exercise_titles(self, t: Template | None = None) -> list[str]:
        look = self.efir.lesson_look(t)
        return [e.title for e in look.exercises] if look is not None else []

    def plan_changed(self, plan: Template) -> list[Template]:
        """План правили — уроки по нему приводятся к нему (идущий урок — тоже: таймер подстроит publish)."""
        from . import plans
        changed = [t for t in self.store.topics_of(plan.id) if plans.sync_topic(t, plan)]
        for t in changed:
            self.touch(t)
        self.refresh_library_item(plan)
        self.lesson.schedule_publish()
        return changed

    def _added(self, t: Template, open_it: bool = True) -> Template:
        self.touch(t)
        self._fill_library(t.id)
        if open_it:
            self.open_lesson(t.id, ask=False)
        return t

    def new_topic(self, plan_id: str, title: str = "Новый урок") -> Template | None:
        from . import plans
        p = self.store.get(plan_id)
        if p is None or p.kind != KIND_PLAN:
            return None
        return self._added(self.store.insert(plans.new_topic(p, title)))

    def new_plan(self, structure: str = "empty") -> Template:
        return self._added(self.store.add_plan_from_structure(structure if isinstance(structure, str) else "empty"))

    def make_plan(self, t: Template) -> Template | None:
        from . import plans
        from .storage import BLOCK_STAGE
        if t.kind == KIND_PLAN or t.plan_id or not any(b.type == BLOCK_STAGE for b in t.blocks):
            return None
        p = self.store.insert(plans.plan_from_lesson(t))
        self.touch(t)
        self._added(p, open_it=False)
        self._notify(f"План «{p.title}»: этапы и минуты урока «{t.title}». Урок теперь по этому плану.")
        self.lesson.schedule_publish()
        return p

    def link_plan(self, t: Template, plan_id: str) -> list[str]:
        from . import plans
        p = self.store.get(plan_id)
        if p is None or p.kind != KIND_PLAN or t.kind == KIND_PLAN:
            return []
        notes = plans.link_topic(t, p)
        self.touch(t)
        self.lesson.schedule_publish()
        self._notify(f"Урок «{t.title}» теперь по плану «{p.title}». " + " ".join(notes), tray=bool(notes))
        return notes

    def unlink_plan(self, t: Template) -> None:
        from . import plans
        if not t.plan_id:
            return
        plans.unlink(t)
        self.touch(t)
        self.lesson.schedule_publish()

    def delete_lesson(self, t: Template, ask: bool = False) -> bool:
        """Удалить урок или план (вопрос задаёт страница). Уроки удалённого плана остаются с теми же этапами."""
        topics = self.store.topics_of(t.id) if t.kind == KIND_PLAN else []
        if self.efir.live_lesson_id() == t.id:
            self.efir.stop_live()
        from . import plans
        for x in topics:
            plans.unlink(x)
            x.updated = time.time()
        self.store.remove(t)
        if self.printer.focus_id == t.id:
            self.printer.set_focus(self.store.templates[0].id if self.store.templates else "")
        self.printer.on_store_changed()
        self._save_timer.start()
        self._fill_library(self.printer.focus_id)
        self.lesson.schedule_publish()
        return True

    # ---------------------------------------------------------------- добавить импортированное
    def add_imported(self, templates: list[Template], looks=(), notes=(), style: str = "") -> Template | None:
        """Импорт (файл, пакет, ответ нейросети): оформления — к себе (если ещё нет), уроки и планы — в список,
        открывается урок (план — только если уроков нет). style — разбор кода нейросетью: включить его печать."""
        from .lesson_ai import STYLE_COMMENTS, STYLE_PARTS, STYLE_STEPS
        for look in looks:
            if self.efir.store.look(look.id) is None:
                self.efir.save_look(look)
        last = None
        for t in templates:
            self.store.insert(t)
            if t.kind != KIND_PLAN or last is None:
                last = t
        if last is None:
            return None
        self.touch(last)
        self._fill_library(last.id)
        msg = (f"Добавлен урок «{last.title}»: блоков — {len(last.blocks)}, из них кода — "
               f"{len(last.code_blocks())}." if len(templates) == 1 else f"Добавлено уроков: {len(templates)}.")
        if notes:
            msg += " " + " ".join(notes)
        mode = {STYLE_STEPS: MODE_STEPS, STYLE_COMMENTS: MODE_LINES, STYLE_PARTS: MODE_BLOCK}.get(style)
        if mode:
            # разбор нейросетью: включить подходящую печать; комментарии — читать вслух, а не печатать
            self.printer.set_option("mode", mode)
            self.printer.set_option("strip", True)
            names = {MODE_STEPS: "«По шагам»", MODE_LINES: "«По строкам»", MODE_BLOCK: "«Целиком»"}
            msg += f" Печать: {names[mode]}, комментарии — читать вслух."
        self._notify(msg)
        self.open_lesson(last.id)          # идёт урок — спросит, а не завершит его молча
        return last

    def import_paths(self, paths: list[str]) -> dict:
        """Файлы урока (перетащили в окно, «Уже есть файл урока?», Ctrl+O): пакеты .autoprint/.zip — с планами и
        оформлениями; .pptx с одноимённым .pdf рядом — картинки слайдов из PDF; во время эфира презентации не
        импортируются (PowerPoint занимает программу до минуты). → {added: [id], errors: [str], open: id}."""
        from . import package
        from .importers import FILE_EXTS, PACKAGE_EXTS, load_file
        from .scenario_import import looks_like_scenario
        paths = [str(p) for p in paths]
        done: list[Template] = []
        errors: list[str] = []
        notes: list[str] = []
        looks = []
        skipped = [p for p in paths if Path(p).suffix.lower() not in FILE_EXTS]
        if skipped:
            errors.append(", ".join(Path(p).name for p in skipped) + ": подходят файлы .autoprint, .zip, .ipynb, .md, "
                          ".py, .json, .pdf и .pptx")
        paths = [p for p in paths if p not in skipped]
        for p in [x for x in paths if x.lower().endswith(PACKAGE_EXTS)]:
            try:
                pkg = package.read_package(p)
            except (OSError, ValueError, KeyError) as e:
                errors.append(f"{Path(p).name}: {e}")
                continue
            done += pkg.plans + pkg.lessons
            looks += pkg.looks
            notes += pkg.notes
            parts = [f"уроков: {len(pkg.lessons)}"] + ([f"планов: {len(pkg.plans)}"] if pkg.plans else []) + \
                    ([f"оформлений экрана учеников: {len(pkg.looks)}"] if pkg.looks else [])
            notes.append(f"Из {Path(p).name}: " + ", ".join(parts) + ".")
        paths = [x for x in paths if not x.lower().endswith(PACKAGE_EXTS)]
        pdfs = {Path(p).stem.lower(): p for p in paths if p.lower().endswith(".pdf")}
        pptx = {Path(p).stem.lower() for p in paths if p.lower().endswith(".pptx")}
        live = self.efir.live_webinar() is not None
        for p in paths:
            if p.lower().endswith(".pdf") and Path(p).stem.lower() in pptx:
                continue                         # PDF той же презентации — картинки к слайдам PPTX
            if p.lower().endswith((".pdf", ".pptx")) and live:
                errors.append(f"{Path(p).name}: идёт эфир — презентацию импортируйте после него")
                continue
            try:
                if p.lower().endswith(".pptx"):
                    t, warns = self.pptx_lesson(p, pdfs.get(Path(p).stem.lower()))
                    notes += warns
                else:
                    t = load_file(p)
            except Exception as e:   # noqa: BLE001 — показать причину по каждому файлу
                errors.append(f"{Path(p).name}: {e}")
                continue
            if not t.blocks:
                errors.append(f"{Path(p).name}: нет блоков для импорта")
                continue
            done.append(t)
        last = self.add_imported(done, looks, notes) if done else None
        if errors:
            self._notify("Не импортировано — " + "; ".join(errors)[:400], warn=True)
        scen = next((t for t in done if t.kind != KIND_PLAN and looks_like_scenario(t.blocks)), None)
        if scen is not None:                     # тетрадка-сценарий с ⏱ — предложить разложить по этапам
            self._notify(f"В уроке «{scen.title}» есть заголовки с ⏱ — можно разложить его по этапам.",
                         action={"label": "Разложить по этапам", "cmd": {"cmd": "recognize", "id": scen.id}})
        return {"added": [t.id for t in done], "errors": errors, "open": last.id if last is not None else ""}

    def _take_import(self, d) -> None:
        """Результат прежнего окна «Импорт урока» (до «Нового урока» в окне)."""
        self.add_imported(list(d.result), getattr(d, "result_looks", []), getattr(d, "result_notes", []),
                          getattr(d, "result_style", ""))

    # ---------------------------------------------------------------- урок одним файлом (.autoprint)
    def _package_parts(self, templates: list[Template], include_plans: bool, include_looks: bool):
        lessons = [t for t in templates if t.kind != KIND_PLAN]
        plans_ = [t for t in templates if t.kind == KIND_PLAN]
        if include_plans:
            for t in lessons:
                p = self.store.get(t.plan_id) if t.plan_id else None
                if p is not None and p not in plans_:
                    plans_.append(p)
        looks = []
        if include_looks:                      # оформление уроков; у плана — только своё (без «по умолчанию»)
            owners = lessons + [p for p in plans_ if p.look] + ([] if lessons else plans_)
            for t in owners:
                lk = self.efir.lesson_look(t)
                if lk is not None and lk not in looks:
                    looks.append(lk)
        return lessons, plans_, looks

    def package_media_size(self, templates: list[Template], include_looks: bool = True) -> int:
        from . import package
        lessons, plans_, looks = self._package_parts(templates, True, include_looks)
        files = {p.resolve() for t in lessons + plans_ for p in package.lesson_files(t)}
        files |= {p.resolve() for lk in looks for p in package.look_files(lk)}
        return sum(p.stat().st_size for p in files if p.is_file())

    def export_package(self, templates: list[Template], path, include_plans: bool = True,
                       include_looks: bool = True) -> dict:
        import copy as _copy
        from . import package
        lessons, plans_, looks = self._package_parts(templates, include_plans, include_looks)
        if include_looks:                      # урок без своего оформления — с тем, что у него на экране сейчас
            lessons = [_copy.copy(t) for t in lessons]
            for t in lessons:
                lk = self.efir.lesson_look(t)
                if lk is not None and not t.look:
                    t.look = lk.id
        return package.export_package(path, lessons=lessons, plans=plans_, looks=looks)

    def export_package_dialog(self, templates: list[Template]) -> None:
        """До листа «Экспорт» (Task 10): прежнее окошко с галочками поверх окна программы."""
        from .ui.export_package import ExportPackageDialog
        if not templates:
            return
        d = ExportPackageDialog(self.window, templates, self)
        if d.exec() != d.DialogCode.Accepted:
            return
        name = templates[0].title if len(templates) == 1 else "Уроки AutoPrint"
        safe = "".join(c for c in name if c not in '\\/:*?"<>|').strip() or "урок"
        path, _ = QFileDialog.getSaveFileName(self.window, "Урок одним файлом", safe + ".autoprint",
                                              "Урок AutoPrint (*.autoprint)")
        if not path:
            return
        self._package_to(templates, path, d.include_plans(), d.include_looks())

    def _package_to(self, templates, path, include_plans: bool, include_looks: bool) -> dict | None:
        try:
            s = self.export_package(templates, path, include_plans, include_looks)
        except OSError as e:
            self._notify(f"Не сохранилось: {e}", warn=True)
            return None
        mb = s["bytes"] / 1024 / 1024
        self._notify(f"Сохранено одним файлом: уроков — {s['lessons']}, планов — {s['plans']}, оформлений — "
                     f"{s['looks']}, файлов внутри — {s['files']} ({mb:.1f} МБ). {path}")
        return s

    def export_template(self, t: Template, fmt: str, path: str | None = None) -> None:
        """fmt: package | md | ipynb | students | json. path None — спросить файл системным окном."""
        if fmt == "package" and path is None:
            self.export_package_dialog([t])
            return
        safe = "".join(c for c in t.title if c not in '\\/:*?"<>|').strip() or "template"
        if path is None:
            flt = {"md": "Markdown (*.md)", "ipynb": "Jupyter (*.ipynb)", "students": "Jupyter (*.ipynb)"}.get(
                fmt, "JSON (*.json)")
            name = f"{safe} — для учеников.ipynb" if fmt == "students" else f"{safe}.{fmt}"
            path, _ = QFileDialog.getSaveFileName(self.window, "Экспорт", name, flt)
            if not path:
                return
        try:
            if fmt == "package":
                self._package_to([t], path, True, True)
                return
            if fmt == "md":
                from .lesson_md import export_md
                export_md(t, Path(path))
            elif fmt in ("ipynb", "students"):
                export_ipynb(t, path, students=fmt == "students")
            else:
                TemplateStore.export_template(t, path)
            self._notify(f"Сохранено: {path}")
        except OSError as e:
            self._notify(f"Не сохранилось: {e}", warn=True)

    def restart_app(self) -> None:
        """Перезапуск программы — тем же путём, что после обновления."""
        if self._busy_typing():
            self._notify("Сейчас идёт набор кода — остановите его и перезапустите программу.", warn=True)
            return
        self._save_settings()
        self._restart()

    _restart_app = restart_app

    def open_report(self) -> None:
        """До листа «Сообщить об ошибке» (Task 15) — прежнее окно поверх окна программы."""
        from .ui.report_dialog import show_report_dialog
        show_report_dialog(self.window, self.settings)

    def _open_log(self) -> None:
        import os
        from .logs import LOG_FILE
        if LOG_FILE.exists():
            os.startfile(LOG_FILE)
        else:
            self._notify("Журнал пока пуст.")

    def _open_data_dir(self) -> None:
        import os
        from .storage import DATA_DIR
        os.startfile(DATA_DIR)

    # ================================================================ сохранение
    def touch(self, t: Template | None = None) -> None:
        """Урок изменился: отметить время, сообщить окну, сохранить чуть позже."""
        t = t or self.printer.focus()
        if t is not None:
            t.updated = time.time()
        self.changed.emit("library")
        self.printer.on_store_changed()
        self._save_timer.start()

    def save_store(self) -> None:
        try:
            self.store.save()
        except OSError as e:
            self._notify(f"Не удалось сохранить уроки: {e}", warn=True)

    _save_store = save_store

    def _ensure_samples(self) -> str:
        from .samples_lesson import LESSON_SAMPLE_ID, LESSON_TITLE, PLAN_SAMPLE_ID, PLAN_TITLE, lesson_sample, plan_sample
        seen = self.settings.samples_seen
        if PLAN_SAMPLE_ID not in seen:
            seen.append(PLAN_SAMPLE_ID)
            if not any(x.title == PLAN_TITLE and x.kind == KIND_PLAN for x in self.store.templates):
                self.store.templates.append(plan_sample())
            self._save_store()
            self._save_settings()
        if LESSON_SAMPLE_ID in seen:
            return ""
        seen.append(LESSON_SAMPLE_ID)
        added = ""
        if not self.store.created_fresh and not any(x.title == LESSON_TITLE for x in self.store.templates):
            t = lesson_sample()
            self.store.templates.insert(0, t)
            added = t.id
        self._save_store()
        self._save_settings()
        return added

    def _restore_session(self) -> None:
        s = self.settings
        added = self._ensure_samples()
        if self._migrated:
            self._save_settings()
        if s.window_geometry:
            self.window.restoreGeometry(QByteArray.fromBase64(s.window_geometry.encode()))
        tid = next((x for x in (added, s.page_lesson, s.current_tab) if x and self.store.get(x)),
                   self.store.templates[0].id if self.store.templates else "")
        self.printer.set_focus(tid)

    def _save_session(self) -> None:
        s = self.settings
        if not self.window.compact:
            s.window_geometry = bytes(self.window.saveGeometry().toBase64()).decode()
        s.current_tab = s.page_lesson = self.printer.focus_id
        s.save()

    # ================================================================ печать
    def _on_hotkey(self, action: str) -> None:
        if self.printer.on_hotkey(action):
            return
        if action == "hotkey_next_tab":
            self.cmd_next_tab(+1)

    on_hotkey = _on_hotkey

    def cmd_next_tab(self, d: int = 1) -> None:
        """Хоткей «следующий урок»: в окне — следующий урок списка (во время урока — нельзя)."""
        if self.efir.live_lesson_id():
            self._notify("Идёт урок — другой урок не открыть хоткеем.", tray=True)
            return
        ids = [t.id for t in self.store.templates]
        if not ids:
            return
        self.printer.engine.pause()
        cur = self.printer.focus_id
        i = ids.index(cur) if cur in ids else -1
        tid = ids[(i + d) % len(ids)]
        self.printer.set_focus(tid)
        self.lesson.schedule_publish()
        self.navigate.emit(f"#/lesson/{tid}")
        t = self.store.get(tid)
        if not self.window.isActiveWindow():
            self._notify(f"Урок: {t.title}", tray=True)

    def _busy_typing(self) -> bool:
        return self.engine.state in BUSY

    def _on_state(self, _st: str = "") -> None:
        st = self.engine.state
        if hasattr(self, "tray"):
            self.tray.set_state(logo.STATE_KIND.get(st, logo.IDLE), f"{APP_NAME}: {STATE_TEXT.get(st, st)}")
        self._set_title_status()
        self.changed.emit("print")

    def _on_print_changed(self) -> None:
        self._set_title_status()
        self.changed.emit("print")

    def _set_title_status(self) -> None:
        if not hasattr(self, "window"):
            return
        st = self.engine.state
        text = STATE_TEXT.get(st, st)
        p = self.printer
        if p.job and st in BUSY:
            t, b = p.find_block(p.job["bid"])
            if b and t:
                text += f" · {b.display_title(t.code_number(b))}"
        elif st == COUNTDOWN and p.countdown_n:
            text = f"Старт через {p.countdown_n}… Поставьте курсор в нужное окно"
        self.window.setWindowTitle(f"{APP_NAME} — {text}" if st != IDLE else APP_NAME)

    def _notify(self, text: str, tray: bool = False, warn: bool = False, quiet: bool = False,
                action: dict | None = None) -> None:
        """Сообщение: тостом в окне (и на экране урока), в трее — если окно не на виду."""
        self.notice = {"seq": self.notice["seq"] + 1, "text": str(text)[:600], "warn": bool(warn), "action": action}
        # несколько сообщений подряд (быстрее, чем уходит состояние) — окно покажет каждое, а не только последнее
        self.notices = (getattr(self, "notices", []) + [dict(self.notice)])[-6:]
        self.changed.emit("notice")
        lesson = getattr(self, "lesson", None)
        if lesson is not None:
            lesson.notice(text, warn)
        win = getattr(self, "window", None)
        hidden = win is None or not win.isVisible() or win.isMinimized() or not win.isActiveWindow()
        if not quiet and (tray or hidden) and hasattr(self, "tray"):
            self.tray.message(text, warn)

    notify = _notify

    # ================================================================ обновления
    def _auto_check_updates(self) -> None:
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
        self.changed.emit("update")
        if rel is None:
            self._show_update_button(None)
            if manual:
                self._notify(f"У вас последняя версия — {__version__}.")
            return
        if not manual and self.updates.is_skipped(rel):
            return
        self._show_update_button(rel)
        if manual:
            self.open_update_dialog()
        elif self.settings.update_mode in (MODE_DOWNLOAD, MODE_AUTO) and self.updates.can_install:
            self.updates.download(rel)
        elif not self._busy_typing():
            self._notify(f"Доступна новая версия {rel.version} — «Обновить» в окне программы.", tray=True)

    def _on_update_check_failed(self, text: str, manual: bool) -> None:
        if manual:
            self._notify(text, warn=True)

    def _on_update_ready(self, rel) -> None:
        self._show_update_button(rel)
        if self.settings.update_mode == MODE_AUTO:
            text = f"Версия {rel.version} скачана и установится при выходе из программы."
        else:
            text = f"Версия {rel.version} готова к установке — «Обновить» в окне программы."
        if self._busy_typing():
            log.info(text)
        else:
            self._notify(text, tray=True)

    def _show_update_button(self, rel) -> None:
        if rel is None:
            self.update_info = None
            self.tray.show_update(None)
        else:
            ready = bool(self.updates.staged and self.updates.staged[0].version == rel.version)
            text = f"Обновить до {rel.version}" if ready else f"Доступна версия {rel.version}"
            self.update_info = {"version": rel.version, "ready": ready, "text": text}
            self.tray.show_update(text)
        self.changed.emit("update")

    def open_update_dialog(self) -> None:
        """До листа «Обновление» (Task 15) — прежнее окно поверх окна программы."""
        from .ui.updates import UpdateDialog
        rel = self.updates.latest
        if rel is None:
            self.check_updates(manual=True)
            return
        dlg = UpdateDialog(self.updates, rel, self.window)
        dlg.restart_requested.connect(self.install_update_and_restart)
        dlg.exec()

    def install_update_and_restart(self) -> None:
        if self._busy_typing():
            self._notify("Сейчас идёт набор кода — остановите его и обновите программу.", warn=True)
            return
        try:
            ver = self.updates.apply_staged()
        except updater.UpdateError as e:
            self._notify(str(e), warn=True)
            return
        log.info("Перезапуск после обновления до %s", ver)
        self._restart()

    def _restart(self) -> None:
        self.engine.stop()
        self.relaunch_requested = True
        QTimer.singleShot(0, self.quit_app)

    restart = _restart

    def _show_update_result(self) -> None:
        d = updater.pop_last_update()
        if d:
            self._notify(f"{APP_NAME} обновлён: {d.get('from')} → {d.get('to')}.", tray=True)

    # ================================================================ закрытие
    def on_window_close(self, e) -> None:
        """«Закрыть» окна: в трей (по настройке и всегда, пока идёт эфир), иначе — выход из программы."""
        live = self.efir.live_webinar() is not None
        if (self.settings.close_to_tray or live) and not self._quitting and self.tray.visible():
            e.ignore()
            self._save_session()
            self.window.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.message("Программа работает в трее. Хоткеи действуют. Выход — из меню значка.")
            return
        self.shutdown()
        e.accept()
        QTimer.singleShot(0, QApplication.quit)

    def shutdown(self) -> None:
        if getattr(self, "_shut", False):
            return
        self._shut = True
        if (self.updates.staged and not self.updates.applied and not self.relaunch_requested
                and self.settings.update_mode == MODE_AUTO):
            try:
                self.updates.apply_staged()
            except updater.UpdateError as err:
                log.warning("Обновление при выходе не установлено: %s", err)
        if self.jobs is not None:
            self.jobs.cancel_all()
        self._save_session()
        self.lesson.shutdown()
        self.efir.shutdown()
        self.engine.stop()
        self._save_timer.stop()
        self._save_store()
        self.hotkeys.shutdown()
        self.guard.shutdown()
        self.tray.hide()

    def quit_app(self) -> None:
        self._quitting = True
        self.window.close()
        QApplication.quit()

    # для прежних тестов и кода: окно-«главное» закрывается так же
    def close(self) -> None:
        self.quit_app()


__all__ = ["App", "HOTKEYS", "STATE_TEXT", "apply_migrations", "MODE_BLOCK", "MODE_LINES", "MODE_STEPS"]
