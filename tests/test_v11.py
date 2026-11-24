"""0.11 — урок по событиям: «Мои настройки», экран учеников с экрана урока, роли, слайды и презентации,
промпт для своего чата, шаблоны структуры. Всё без окон на экране.

    python tests/test_v11.py
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import quiet  # noqa: E402,F401  — до PySide6: offscreen, своя папка данных

from test_v10 import TMP, code, make_window, note, pump, stage  # noqa: E402  (там же QApplication и тема)

from autoprint import storage  # noqa: E402
from autoprint.storage import BLOCK_CODE, BLOCK_IMAGE, BLOCK_MARKDOWN, BLOCK_STAGE, Block, Template  # noqa: E402,F401


def lesson_with_stages(tid: str = "L") -> Template:
    return Template("Урок", [stage("Начало", 10, id="s1"), note("Добрый день", id="n1"),
                             stage("Перерыв", 10, id="s2", stage_kind="break"),
                             stage("Практика", 20, id="s3"), code("print(1)", id="c1")], id=tid)


class Base(unittest.TestCase):
    port = 18970

    def setUp(self):
        self.L = lesson_with_stages()
        self.win = make_window([self.L], port=self.port)
        self.win.lesson.open_page = lambda: None
        self.win.printer.set_focus("L")

    def tearDown(self):
        ef = self.win.efir
        if ef.live_webinar() is not None:
            ef.stop_live()
        if ef.timer_window is not None:
            ef.timer_window.close_silently()
        self.win._quitting = True
        self.win.close()
        pump()

    def state(self) -> dict:
        self.win.lesson._last = None
        self.win.lesson.publish()
        return self.win.efir.server._states["lesson"]


# ================================================================ Task 1: «Мои настройки»

class PrefsTest(Base):
    def test_defaults(self):
        s = storage.Settings()
        self.assertEqual((s.page_zoom, s.page_plan, s.page_past, s.page_stage_timer, s.start_timer, s.start_screen),
                         (100, "strip", "dim", True, False, False))

    def test_prefs_command(self):
        cmd = self.win.lesson.command
        cmd({"cmd": "prefs", "key": "page_zoom", "value": 130})
        cmd({"cmd": "prefs", "key": "page_plan", "value": "side"})
        cmd({"cmd": "prefs", "key": "page_past", "value": "collapse"})
        cmd({"cmd": "prefs", "key": "page_stage_timer", "value": False})
        cmd({"cmd": "prefs", "key": "start_timer", "value": True})
        s = self.win.settings
        self.assertEqual((s.page_zoom, s.page_plan, s.page_past, s.page_stage_timer, s.start_timer),
                         (130, "side", "collapse", False, True))
        cmd({"cmd": "prefs", "key": "page_zoom", "value": 900})          # вне 80…200 — к краю
        self.assertEqual(s.page_zoom, 200)
        cmd({"cmd": "prefs", "key": "page_plan", "value": "zzz"})        # неизвестное — не меняется
        self.assertEqual(s.page_plan, "side")
        cmd({"cmd": "prefs", "key": "hotkey_toggle", "value": "x"})      # не настройка страницы
        self.assertEqual(s.hotkey_toggle, "Ctrl+F9")
        p = self.state()["prefs"]
        self.assertEqual(p["page_zoom"], 200)
        self.assertEqual(p["page_plan"], "side")
        self.assertEqual(p["start_timer"], True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
