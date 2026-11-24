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


if __name__ == "__main__":
    unittest.main(verbosity=2)
