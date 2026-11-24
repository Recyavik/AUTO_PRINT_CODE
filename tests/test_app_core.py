"""Программа без виджетов (App): уроки, планы, окно и трей — без старого главного окна Qt.

    .venv\\Scripts\\python.exe tests\\test_app_core.py
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import quiet  # noqa: E402,F401

from PySide6.QtGui import QCloseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
quiet.patch()

from autoprint import storage  # noqa: E402
from autoprint.storage import BLOCK_MARKDOWN, BLOCK_STAGE, Block, Settings, Template, TemplateStore  # noqa: E402

PORT = 18981
SEEN = ["steps_v1", "tour_v1", "lesson_v1", "lesson_v2", "lesson_v3", "plan_v1"]


def pump(ms: int = 30) -> None:
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def stage(title, minutes=5, **kw):
    return Block(BLOCK_STAGE, "", title=title, minutes=minutes, **kw)


def lesson(title="Урок", tid="L1") -> Template:
    return Template(title, [stage("Начало", 5, id=tid + "s1"), Block(BLOCK_MARKDOWN, "Привет", role="say",
                                                                       id=tid + "n1")], id=tid)


def make_app(templates: list[Template]):
    from autoprint.app_core import App
    storage.TEMPLATES_FILE.unlink(missing_ok=True)
    storage.TEMPLATES_FILE.with_suffix(".json.bak").unlink(missing_ok=True)
    store = TemplateStore()
    store.templates = list(templates)
    store.save()
    s = Settings()
    s.efir_port = PORT
    s.update_auto_check = False
    s.sound_enabled = False
    s.samples_seen = list(SEEN)
    s.migrations = ["tray_v1", "window_v10"]
    return App(s, store, web=False)


class AppCoreTest(unittest.TestCase):
    def setUp(self):
        self.a = make_app([lesson("A", "LA"), lesson("B", "LB")])
        self.events: list[str] = []
        self.a.changed.connect(self.events.append)
        self.nav: list[str] = []
        self.a.navigate.connect(self.nav.append)

    def tearDown(self):
        self.a.efir.stop_live()
        self.a._quitting = True
        self.a.shutdown()
        self.a.window.hide()
        pump()

    def test_new_template_touches_and_emits_library(self):
        n = len(self.a.store.templates)
        t = self.a.new_template()
        self.assertEqual(len(self.a.store.templates), n + 1)
        self.assertIn("library", self.events)
        self.assertEqual(self.nav[-1], f"#/lesson/{t.id}")

    def test_open_lesson_asks_when_other_live(self):
        self.a.printer.set_focus("LA")
        self.assertTrue(self.a.efir.launch_lesson(self.a.store.get("LA"), start="", show=False))
        self.assertFalse(self.a.open_lesson("LB"))
        n = self.a.notice
        self.assertIn("Идёт урок «A»", n["text"])
        self.assertEqual(n["action"]["cmd"], {"cmd": "open", "lesson": "LB", "force": True})
        self.assertEqual(self.a.efir.live_lesson_id(), "LA")          # идущий урок не тронут
        self.assertTrue(self.a.open_lesson("LB", ask=False))
        self.assertEqual(self.a.efir.live_lesson_id(), "")

    def test_delete_plan_unlinks_topics(self):
        from autoprint import plans
        p = self.a.store.insert(plans.plan_from_lesson(self.a.store.get("LA")))
        t = self.a.new_topic(p.id)
        self.assertEqual(t.plan_id, p.id)
        self.a.delete_lesson(p)
        self.assertIsNone(self.a.store.get(p.id))
        self.assertEqual(t.plan_id, "")

    def test_close_hides_to_tray_when_live(self):
        self.a.tray.visible = lambda: True
        self.a.settings.close_to_tray = False
        self.a.efir.launch_lesson(self.a.store.get("LA"), start="", show=False)
        self.a.window.show()
        e = QCloseEvent()
        self.a.on_window_close(e)
        self.assertFalse(e.isAccepted())
        self.assertFalse(self.a.window.isVisible())

    def test_tray_menu_items(self):
        self.assertEqual(self.a.tray.items(), ["Показать окно", "Маленький режим", "Старт / пауза", "Стоп",
                                               "Обновление…", "Настройки…", "Выход"])
        self.assertFalse(self.a.tray.update_action.isVisible())

    def test_app_state_keys(self):
        from autoprint.app_state import app_state
        s = app_state(self.a)
        for k in ("version", "dark", "zoom", "prefs", "lessons", "plans", "continue_id", "live", "print", "update",
                  "ai", "jobs", "notice", "window", "drop", "nav", "efir", "settings"):
            self.assertIn(k, s)
        self.assertEqual([x["id"] for x in s["lessons"]], ["LA", "LB"])
        self.assertEqual(s["lessons"][0]["meta"], "5 мин · 1 этап · без кода")
        self.assertEqual(set(s["ai"]["cli"]), {"claude", "codex"})
        import json
        json.dumps(s)                                   # уходит в страницу как есть

    def test_minimize_on_type(self):
        calls = []
        w = self.a.window
        w.isVisible = lambda: True
        w.isMinimized = lambda: False
        w.showMinimized = lambda: calls.append("min")
        w.showNormal = lambda: calls.append("normal")
        eng = self.a.engine

        def to(st):
            eng.state = st
            self.a._on_state()
        self.assertFalse(self.a.settings.minimize_on_type)          # по умолчанию окно остаётся
        to("countdown")
        to("idle")
        self.assertEqual(calls, [])
        self.a.settings.minimize_on_type = True
        to("countdown")
        to("running")
        to("paused")                                                # пауза — окно ещё свёрнуто
        self.assertEqual(calls, ["min"])
        to("finished")
        self.assertEqual(calls, ["min", "normal"])
        to("idle")
        self.assertEqual(calls, ["min", "normal"])

    def test_show_view_emits_navigate(self):
        self.a.show_view("#/lesson/LA")
        self.assertEqual(self.nav[-1], "#/lesson/LA")
        self.a.open_settings("ai")
        self.assertEqual(self.nav[-1], "#/settings/ai")


# ================================================================ бывший ui_regress: окно без лишних окон, тема, отсчёт

class RegressTest(unittest.TestCase):
    """Перенесено из tests/ui_regress.py (Task 16): то, что проверялось на старых окнах, — на одном окне."""

    def setUp(self):
        from PySide6.QtCore import QEvent, QObject
        from PySide6.QtWidgets import QMenu, QWidget
        plan = Template("План", [stage("Этап", 10, id="P1s")], id="P1", kind="plan")
        foreign = Template("Чужой", [Block(BLOCK_MARKDOWN, "чужая роль", role="warning", id="Fw"), stage("Начало", 5, id="Fs")], id="F")
        self.stray: list[str] = []
        spy_list = self.stray

        class StraySpy(QObject):
            """Виджет, показанный самостоятельным окном (до вставки в родителя), мелькает на панели задач."""
            def eventFilter(self, obj, ev) -> bool:
                if ev.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow() \
                        and type(obj).__name__ not in ("AppWindow", "QTipLabel", "QComboBoxPrivateContainer") \
                        and not isinstance(obj, QMenu):
                    spy_list.append(f"{type(obj).__name__} «{obj.objectName()}»")
                return False
        self.spy = StraySpy()
        app.installEventFilter(self.spy)
        self.errors: list[str] = []
        self._hook = sys.excepthook
        sys.excepthook = lambda t, v, tb: self.errors.append(f"{t.__name__}: {v}")
        self.a = make_app([plan, foreign])
        from PySide6.QtCore import Qt
        self.a.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.a.window.show()
        pump()

    def tearDown(self):
        sys.excepthook = self._hook
        app.removeEventFilter(self.spy)
        self.a._quitting = True
        self.a.shutdown()
        self.a.window.hide()
        pump()

    def test_focus_is_lesson_not_plan(self):
        """0.12: при запуске в фокусе — урок, а не план (план стоит первым)."""
        f = self.a.printer.focus()
        self.assertIsNotNone(f)
        self.assertEqual(f.kind, "")

    def test_theme_switch_without_errors(self):
        from autoprint.ui.theme import theme
        for mode in ("light", "dark", "light", "dark"):
            self.a.settings.theme = mode
            theme.set_mode(mode)
            pump(60)
        self.assertEqual(self.errors, [])

    def test_no_stray_windows(self):
        """Окно программы и лист «Сообщить об ошибке» — без лишних окон на панели задач."""
        self.a.open_report()
        self.a.open_update_dialog()
        pump(100)
        self.assertEqual(self.stray, [])
        self.assertEqual(self.errors, [])

    def test_pause_during_countdown_stays_paused(self):
        """Пауза во время отсчёта: печать не начинается и не становится «Печатает» — остаётся «Пауза»."""
        from autoprint.typer import IDLE, PAUSED, RUNNING, TypingEngine
        e = TypingEngine(Settings())
        states = []
        e.state_changed.connect(states.append)
        e.load("abc")
        e.start(0.0, countdown=3)
        pump(400)
        e.pause()
        pump(1100)
        st = e.state
        e.stop()
        pump(200)
        self.assertEqual(st, PAUSED)
        self.assertNotIn(RUNNING, states)
        self.assertEqual(e.state, IDLE)

    def test_windows_newlines_in_sample(self):
        from autoprint.storage import _block_from
        blk = _block_from({"type": "code", "text": "a = 1\r\nb = 2", "steps": ["1", 2]})
        self.assertEqual((blk.text, blk.steps), ("a = 1\nb = 2", [1, 2]))


# ================================================================ Task 17: 1.0 — миграция настроек и сессия окна

class MigrationV1Test(unittest.TestCase):
    def old(self) -> Settings:
        s = Settings()
        s.migrations = ["tray_v1", "window_v10"]
        s.page_plan, s.ui_scale, s.page_zoom, s.start_timer, s.window_geometry = "strip", 150, 100, True, "AAAA"
        return s

    def test_migration_v1_values(self):
        from autoprint import migrations
        s = self.old()
        self.assertTrue(migrations.apply(s))
        self.assertEqual((s.page_plan, s.page_zoom, s.ui_scale, s.start_compact, s.window_geometry),
                         ("top", 150, 100, True, ""))
        self.assertIn("v1", s.migrations)
        s2 = self.old()
        s2.page_zoom, s2.ui_scale = 120, 175                 # масштаб страницы уже свой — не трогать
        migrations.apply(s2)
        self.assertEqual((s2.page_zoom, s2.ui_scale), (120, 100))
        s3 = self.old()
        s3.ui_scale = 250                                     # к пределам 80…200
        migrations.apply(s3)
        self.assertEqual(s3.page_zoom, 200)

    def test_migration_v1_once(self):
        from autoprint import migrations
        s = self.old()
        migrations.apply(s)
        s.page_plan, s.window_geometry, s.start_compact = "strip", "BBBB", False
        self.assertFalse(migrations.apply(s))
        self.assertEqual((s.page_plan, s.window_geometry, s.start_compact), ("strip", "BBBB", False))

    def test_new_defaults(self):
        s = Settings()
        self.assertEqual((s.page_plan, s.start_compact, s.last_view, s.compact), ("side", False, "", False))


class SessionTest(unittest.TestCase):
    """Перезапуск программы: тот же экран, маленький режим, урок в эфире; --tray — без окна."""

    def setUp(self):
        self.apps = []

    def tearDown(self):
        for a in self.apps:
            a.efir.stop_live()
            a._quitting = True
            a.shutdown()
            a.window.hide()
        pump()

    def start(self, templates=None, settings=None):
        from autoprint.app_core import App
        if templates is not None:
            a = make_app(templates)
            if settings is not None:
                a.settings.__dict__.update(settings)
        else:
            store = TemplateStore()
            a = App(self.apps[-1].settings if self.apps else Settings(), store, web=False)
        self.apps.append(a)
        return a

    def restart(self, a):
        """Выход и новый запуск с теми же настройками и данными."""
        from autoprint.app_core import App
        s = a.settings
        a._quitting = True
        a.shutdown()
        a.window.hide()
        self.apps.remove(a)
        pump()
        b = App(s, TemplateStore(), web=False)
        self.apps.append(b)
        return b

    def test_restore_last_view(self):
        a = self.start([lesson("A", "LA"), lesson("B", "LB")])
        a.commands.cmd_view({"hash": "#/settings/sound"})
        self.assertEqual(a.settings.last_view, "#/settings/sound")
        a.commands.cmd_view({"hash": "#/new/plan"})          # шаги «Нового урока» не восстанавливаются
        self.assertEqual(a.settings.last_view, "#/settings/sound")
        b = self.restart(a)
        self.assertEqual(b.nav["hash"], "#/settings/sound")
        b.commands.cmd_view({"hash": "#/lesson/LB"})
        c = self.restart(b)
        self.assertEqual(c.nav["hash"], "#/lesson/LB")
        c.delete_lesson(c.store.get("LB"))                   # урока больше нет — «Уроки»
        c.settings.last_view = "#/lesson/LB"
        d = self.restart(c)
        self.assertEqual(d.nav["hash"], "#/lessons")

    def test_restore_live_lesson_view(self):
        a = self.start([lesson("A", "LA"), lesson("B", "LB")])
        a.commands.cmd_view({"hash": "#/efir"})
        a.printer.set_focus("LB")
        a.lesson.command({"cmd": "start"})
        self.assertEqual(a.efir.live_lesson_id(), "LB")
        a.set_compact(True)
        b = self.restart(a)
        self.assertEqual(b.nav["hash"], "#/lesson/LB")      # урок в эфире — важнее последнего экрана
        self.assertTrue(b.window.compact)
        b.efir.restore()
        self.assertEqual(b.efir.live_lesson_id(), "LB")
        b.set_compact(False)

    def test_tray_flag_starts_hidden(self):
        a = self.start([lesson("A", "LA")])
        a.window.hide()
        a.start(tray=True)
        pump()
        self.assertFalse(a.window.isVisible())
        a.start(tray=False)
        pump()
        self.assertTrue(a.window.isVisible())


if __name__ == "__main__":
    unittest.main(verbosity=2)
