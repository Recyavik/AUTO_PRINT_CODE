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


# ================================================================ Task 3: план строкой — сдвиг конца урока

class ShiftTest(Base):
    port = 18971

    def test_shift_after_restart_stage(self):
        from datetime import datetime, timedelta
        at = (datetime.now() - timedelta(minutes=15)).strftime("%H:%M")
        cmd = self.win.lesson.command
        cmd({"cmd": "start", "at": at})
        self.assertEqual(self.win.efir.live_lesson_id(), "L")
        self.assertEqual(self.state()["live"]["shift"], 0)
        cmd({"cmd": "shift_now"})                       # этап-перерыв (10–20 мин) начат заново сейчас
        shift = self.state()["live"]["shift"]
        self.assertTrue(5 <= shift <= 6, shift)
        cmd({"cmd": "set_start", "start": at})          # новое время начала — новый план, сдвига нет
        self.assertEqual(self.state()["live"]["shift"], 0)


# ================================================================ Task 4: экран учеников с экрана урока

class EfirPageTest(Base):
    port = 18972

    def test_start_no_timer(self):
        ef = self.win.efir
        opened = []
        ef.open_tab = lambda: opened.append(1)
        self.win.lesson.command({"cmd": "start"})
        self.assertEqual(ef.live_lesson_id(), "L")
        self.assertIsNone(ef.timer_window)                   # «Начать урок» не открывает окно таймера
        self.assertEqual(opened, [])
        ef.stop_live()
        self.win.settings.start_timer = self.win.settings.start_screen = True
        self.win.lesson.command({"cmd": "start"})
        self.assertIsNotNone(ef.timer_window)
        self.assertEqual(opened, [1])

    def test_start_at_no_timer(self):
        self.win.lesson.command({"cmd": "start_at", "index": 2})
        self.assertEqual(self.win.efir.live_lesson_id(), "L")
        self.assertIsNone(self.win.efir.timer_window)

    def test_break_default_and_minutes(self):
        ef = self.win.efir
        self.win.lesson.command({"cmd": "break"})           # без этапа — перерыв урока (этап «Перерыв» 10 мин)
        self.assertEqual(ef.mode, "break")
        self.assertAlmostEqual(ef.brk_total, 600, delta=1)
        st = self.state()["efir"]
        self.assertEqual(st["mode"], "break")
        self.assertGreater(st["break_ends"], time.time() * 1000)
        self.assertIn("tab_open", st)
        self.win.lesson.command({"cmd": "break", "minutes": 15})
        self.assertAlmostEqual(ef.brk_total, 900, delta=1)
        self.win.lesson.command({"cmd": "background"})
        self.assertEqual(ef.mode, "idle")

    def test_look_new_and_edit(self):
        ef = self.win.efir
        edited = []
        ef.edit_look = lambda lid=None: edited.append(lid)
        n0 = len(ef.store.looks)
        self.win.lesson.command({"cmd": "look_new"})
        self.assertEqual(len(ef.store.looks), n0 + 1)
        new = ef.store.looks[-1]
        self.assertEqual(self.L.look, new.id)                # урок сразу на новом оформлении
        self.assertEqual(edited, [new.id])
        self.win.lesson.command({"cmd": "look_edit"})
        self.assertEqual(edited, [new.id, new.id])


class TimerBreakTest(Base):
    port = 18973

    def test_popup_buttons(self):
        from PySide6.QtWidgets import QAbstractSpinBox, QPushButton
        ef = self.win.efir
        self.win.settings.start_timer = True
        self.win.lesson.command({"cmd": "start"})
        tw = ef.timer_window
        m = tw._break_menu()
        self.assertEqual(m.findChildren(QAbstractSpinBox), [])        # поле минут больше не забирает фокус
        texts = [b.text().strip() for b in m.findChildren(QPushButton)]
        self.assertEqual(texts[0], "10 мин")                            # по плану — первым
        self.assertIn("5 мин", texts)
        self.assertIn("20 мин", texts)
        started = []
        ef.start_break = lambda minutes, ends_at=None: started.append(minutes)
        [b for b in m.findChildren(QPushButton) if b.text().strip() == "15 мин"][0].click()
        self.assertEqual(started, [15])


if __name__ == "__main__":
    unittest.main(verbosity=2)
