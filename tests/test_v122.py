"""1.2.2 — чёрный экран ученикам по щелчку (ни фона, ни надписи, ни слайда). Без окон на экране.
Значок в полосе урока, кнопки в табло вебинара и в маленьком режиме — в test_app_lesson.py, test_app_efir.py,
test_app_compact.py; что видят ученики (снимок вкладки) — в test_app_lesson.py (ScreenSlideFillTest).

    python tests/test_v122.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import quiet  # noqa: E402,F401  — до PySide6: offscreen, своя папка данных

from test_v121 import close, lesson, videos, window  # noqa: E402


class BlackScreenTest(unittest.TestCase):
    port = 18942

    def setUp(self):
        from autoprint.efir.model import Look
        self.look = Look(title="Синий", background="color:#123456", caption="Скоро начнём", exercises=videos("Глаза 1"))
        self.win = window([lesson("A"), lesson("B")], self.port)
        self.win.efir.save_look(self.look)
        self.win.store.get("A").look = self.look.id
        self.focus("A")

    def tearDown(self):
        if self.win.efir.live_webinar() is not None:
            self.win.efir.stop_live()
        close(self.win)

    def screen(self) -> dict:
        return self.win.efir.server._states["screen"]

    def focus(self, tid):
        self.win.printer.set_focus(tid)
        self.win.lesson._last = None
        self.win.lesson.publish()

    def test_black_and_back_to_background(self):
        """«Чёрный экран» — у учеников просто чёрный; «Фон» — снова фон и надпись оформления урока."""
        self.win.lesson.command({"cmd": "black"})
        self.assertEqual(self.win.efir.mode, "black")
        self.assertEqual(self.screen()["mode"], "black")
        self.win.lesson.command({"cmd": "background"})
        self.assertEqual(self.screen()["mode"], "idle")
        self.assertEqual(self.screen()["bg"], {"kind": "color", "value": "#123456"})
        self.assertEqual(self.screen()["caption"], "Скоро начнём")

    def test_black_replaces_break_slide_and_exercise(self):
        """Шёл перерыв (или зарядка) — чёрный экран его убирает: перерыв не вернётся после перезапуска программы."""
        self.win.lesson.command({"cmd": "start", "force": True})
        self.win.lesson.command({"cmd": "break", "minutes": 5})
        self.assertIsNotNone(self.win.efir.store.brk)
        self.win.lesson.command({"cmd": "black"})
        self.assertEqual(self.screen()["mode"], "black")
        self.assertNotIn("brk", self.screen())
        self.assertIsNone(self.win.efir.store.brk)
        self.win.lesson.command({"cmd": "exercise", "pick": "next"})
        self.assertEqual(self.win.efir.mode, "exercise")
        self.win.lesson.command({"cmd": "black"})
        self.assertEqual(self.screen()["mode"], "black")
        self.assertNotIn("exercise", self.screen())

    def test_black_from_webinar_board(self):
        """Табло вебинара по расписанию (урок не нужен) — тоже чёрный экран и обратно фон."""
        self.win.commands.cmd_efir_screen({"op": "black"})
        self.assertEqual(self.screen()["mode"], "black")
        self.win.commands.cmd_efir_screen({"op": "background"})
        self.assertEqual(self.screen()["mode"], "idle")

    def test_black_kept_when_other_lesson_opened(self):
        """Чёрный экран включили до урока, открыли другой урок — у учеников всё ещё чёрный (как перерыв)."""
        self.win.lesson.command({"cmd": "black"})
        self.focus("B")
        self.assertEqual(self.screen()["mode"], "black")

    def test_black_without_any_look(self):
        """Оформлений нет вовсе — всё равно чёрный экран (а не «фон»)."""
        self.win.efir.webinar = None
        self.win.efir.show_black()
        self.assertEqual(self.win.efir.state()["mode"], "black")

    def test_lesson_page_knows_black(self):
        """Страница урока знает, что у учеников чёрный экран (значок нажат, миниатюра чёрная)."""
        self.win.lesson.command({"cmd": "black"})
        self.win.lesson._last = None
        self.win.lesson.publish()
        self.assertEqual(self.win.efir.server._states["lesson"]["efir"]["mode"], "black")


if __name__ == "__main__":
    unittest.main(verbosity=2)
