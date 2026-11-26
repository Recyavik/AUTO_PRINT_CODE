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

from autoprint.storage import Settings  # noqa: E402


class BlackScreenTest(unittest.TestCase):
    port = 18942

    def setUp(self):
        from autoprint.efir.model import Look
        self.look = Look(title="Синий", background="color:#123456", caption="Скоро начнём", exercises=videos("Глаза 1"))
        self.look_b = Look(title="Зелёный", background="color:#00aa00", exercises=videos("Шея 1", "Шея 2"))
        self.win = window([lesson("A"), lesson("B")], self.port)
        self.win.efir.save_look(self.look)
        self.win.efir.save_look(self.look_b)
        self.win.store.get("A").look = self.look.id
        self.win.store.get("B").look = self.look_b.id
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

    def test_other_lesson_look_ready_under_black(self):
        """Чёрный экран между уроками: открыли другой урок — «Фон» сразу его (без мелькания прошлого), и зарядка до
        начала урока — из его видео."""
        self.win.lesson.command({"cmd": "black"})
        self.focus("B")
        self.win.lesson.command({"cmd": "background"})
        self.assertEqual(self.screen()["bg"], {"kind": "color", "value": "#00aa00"})       # сразу, а не через 0,3 с
        self.win.lesson.command({"cmd": "exercise", "index": 1})
        self.assertEqual(self.screen()["exercise"]["title"], "Шея 2")

    def test_black_survives_restart_during_lesson(self):
        """Урок идёт, у учеников чёрный, программу перезапустили — снова чёрный (как слайд и перерыв), а не фон."""
        ef = self.win.efir
        self.win.lesson.command({"cmd": "start", "force": True})
        self.win.lesson.command({"cmd": "black"})
        ef.store.load()                                   # с диска — как после перезапуска
        ef.mode, ef.webinar = "idle", None
        ef.restore()
        self.assertEqual(ef.mode, "black")
        self.assertEqual(self.screen()["mode"], "black")
        self.win.lesson.command({"cmd": "background"})
        ef.store.load()
        ef.mode = "idle"
        ef.restore()
        self.assertEqual(ef.mode, "idle")                 # фон включили — после перезапуска фон

    def test_black_before_start_survives_restart(self):
        """Чёрный включили до «Начать урок», урок начали, программу перезапустили — у учеников всё ещё чёрный."""
        ef = self.win.efir
        self.win.lesson.command({"cmd": "black"})
        self.win.lesson.command({"cmd": "start", "force": True})
        self.assertEqual(ef.mode, "black")
        ef.store.load()
        ef.mode, ef.webinar = "idle", None
        ef.restore()
        self.assertEqual(ef.mode, "black")

    def test_black_not_kept_after_slide_or_break(self):
        """Чёрный, потом слайд или перерыв — после перезапуска не чёрный."""
        ef = self.win.efir
        self.win.lesson.command({"cmd": "start", "force": True})
        self.win.lesson.command({"cmd": "black"})
        self.win.lesson.command({"cmd": "break", "minutes": 5})
        ef.store.load()
        self.assertFalse(getattr(ef.store, "black", False))
        self.assertIsNotNone(ef.store.brk)

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


# ================================================================ 1.2.4: зарядка — по щелчку по вкладке учеников

class ExerciseStartByClickTest(unittest.TestCase):
    """Зарядка всегда встаёт на первый кадр и ждёт щелчка по вкладке учеников (настройка «Как начинается видео»:
    по щелчку — по умолчанию, или сразу); щелчок по идущей — пауза, ещё щелчок — дальше."""
    port = 18943

    def setUp(self):
        from autoprint.efir.model import Look
        self.look = Look(title="Синий", exercises=videos("Глаза 1"))
        self.win = window([lesson("A")], self.port)
        self.win.efir.save_look(self.look)
        self.win.store.get("A").look = self.look.id
        self.win.printer.set_focus("A")
        self.win.settings.exercise_start = "click"
        self.said = []
        self.win.efir.message.connect(lambda text, warn: self.said.append(text))

    def tearDown(self):
        close(self.win)

    def start(self):
        self.win.lesson.command({"cmd": "exercise", "index": 0})
        self.assertEqual(self.win.efir.mode, "exercise")
        return self.win.efir.ex_seq

    def lesson_efir(self) -> dict:
        self.win.lesson._last = None
        self.win.lesson.publish()
        return self.win.efir.server._states["lesson"]["efir"]

    def test_setting_default_click(self):
        from autoprint.settings_spec import FIELDS
        self.assertEqual(Settings().exercise_start, "click")
        self.assertEqual(FIELDS["exercise_start"], ("choice", ("click", "auto")))
        self.start()
        self.assertTrue(self.win.efir.state()["exercise"]["gate"])
        self.win.settings.exercise_start = "auto"
        self.start()
        self.assertFalse(self.win.efir.state()["exercise"]["gate"])

    def test_ready_is_not_a_warning(self):
        """Вкладка сообщила «стою, жду щелчка» — это не беда (без красного и всплывающих предупреждений), но
        учитель видит, что зарядка ждёт; пошла — больше не ждёт."""
        seq = self.start()
        self.win.efir._on_report({"type": "ready", "seq": seq})
        st = self.lesson_efir()
        self.assertEqual((st["ex_ready"], st["ex_muted"]), (True, False))
        self.assertEqual(self.said, [])
        self.assertIn("ждёт щелчка", self.win.efir.tab_status()[0])
        self.win.efir._on_report({"type": "video", "seq": seq, "pos": 1, "dur": 60, "paused": False, "muted": False})
        self.assertFalse(self.lesson_efir()["ex_ready"])

    def test_click_on_playing_exercise_pauses_and_resumes(self):
        seq = self.start()
        self.win.efir._on_report({"type": "toggle", "seq": seq})
        self.assertTrue(self.win.efir.ex_paused)
        self.assertTrue(self.win.efir.state()["exercise"]["paused"])
        self.win.efir._on_report({"type": "toggle", "seq": seq})
        self.assertFalse(self.win.efir.ex_paused)
        self.win.efir._on_report({"type": "toggle", "seq": seq - 1})        # от прошлой зарядки — не трогаем
        self.assertFalse(self.win.efir.ex_paused)

    def test_lesson_page_knows_setting(self):
        self.assertEqual(self.lesson_efir() and self.win.efir.server._states["lesson"]["prefs"]["exercise_start"], "click")
        self.win.lesson.command({"cmd": "prefs", "key": "exercise_start", "value": "auto"})
        self.assertEqual(self.win.settings.exercise_start, "auto")
        self.win.lesson.command({"cmd": "prefs", "key": "exercise_start", "value": "чепуха"})
        self.assertEqual(self.win.settings.exercise_start, "auto")


if __name__ == "__main__":
    unittest.main(verbosity=2)
