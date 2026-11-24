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


# ================================================================ Task 7: роли и палитра

class RolesV11Test(unittest.TestCase):
    def test_roles(self):
        R = storage.ROLES
        self.assertEqual([R[k][1] for k in ("trap", "output", "hint", "homework", "goal")],
                         ["Типичные ошибки", "Результат кода", "Если застрял", "Домашнее задание", "Цель урока"])
        self.assertNotIn("hint", storage.ROLE_MORE)
        groups = dict(storage.ROLE_GROUPS)
        self.assertEqual(list(groups), ["Урок", "Речь", "Ученикам", "Действия", "Для себя", "Материалы"])
        self.assertEqual(groups["Речь"], ["say", "tell", "term", "ask"])
        self.assertEqual(groups["Ученикам"], ["task", "hint", "extra", "homework"])
        self.assertEqual(sorted(k for g in groups.values() for k in g), sorted(storage.ROLE_ORDER))

    def test_state_roles_how(self):
        from autoprint import scenario
        roles = {r["key"]: r for r in scenario.roles_state()}
        self.assertEqual(roles["say"]["how"], "дословно")
        self.assertEqual(roles["tell"]["how"], "своими словами")
        self.assertEqual(roles["ask"]["how"], "ответы учеников")
        self.assertEqual([g["title"] for g in scenario.role_groups_state()][0], "Урок")

    def test_md_names_old_and_new(self):
        from autoprint.lesson_md import _role
        for name, key in (("Ловушки", "trap"), ("Типичные ошибки", "trap"), ("Вывод", "output"),
                          ("Результат кода", "output"), ("Подсказка", "hint"), ("Если застрял", "hint"),
                          ("Домашнее задание", "homework"), ("Цель урока", "goal")):
            self.assertEqual(_role(name), key, name)

    def test_students_notebook_homework(self):
        import json
        from autoprint.importers import export_ipynb
        t = Template("У", [note("Скажи", id="a"), code("x = 1", id="b"),
                           note("Решить задачи 1–3", role="homework", id="c")])
        path = TMP / "students.ipynb"
        export_ipynb(t, str(path), students=True)
        cells = json.loads(path.read_text(encoding="utf-8"))["cells"]
        self.assertEqual([c["cell_type"] for c in cells], ["code", "markdown"])
        self.assertIn("Домашнее задание", "".join(cells[1]["source"]))
        self.assertIn("Решить задачи 1–3", "".join(cells[1]["source"]))

    def test_ai_knows_new_roles(self):
        from autoprint import lesson_ai as L
        prompt = L.build_prompt("материал", L.Options(style=L.STYLE_SCENARIO))
        for word in ('"homework"', "Домашнее задание", '"goal"', "Цель урока", "Если застрял", "Типичные ошибки"):
            self.assertIn(word, prompt)
        self.assertEqual(L._TYPE_ROLE.get("домашнее задание"), "homework")
        self.assertEqual(L._TYPE_ROLE.get("цель"), "goal")


# ================================================================ Task 8: слайды и экран учеников

def slide_png(n: int) -> str:
    """Картинка-слайд в data/media → ссылка блока."""
    from PySide6.QtGui import QColor, QImage
    folder = storage.DATA_DIR / storage.MEDIA_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"test-slide-{n}.png"
    im = QImage(32, 18, QImage.Format.Format_RGB32)
    im.fill(QColor(20 * n, 40, 80))
    im.save(str(p), "PNG")
    return storage.media_ref(p)


def slides_lesson(tid: str = "S") -> Template:
    return Template("Презентация", [stage("Презентация", 30, id="ps"),
                                     Block(BLOCK_IMAGE, slide_png(1), title="Титул", slide=1, id="sl1"),
                                     note("Скажи про тему", id="sn1"),
                                     Block(BLOCK_IMAGE, slide_png(2), title="План", slide=2, id="sl2"),
                                     Block(BLOCK_IMAGE, slide_png(3), title="Итоги", slide=3, id="sl3")], id=tid)


class SlideTest(Base):
    port = 18974

    def setUp(self):
        self.L = slides_lesson("L")
        self.win = make_window([self.L], port=self.port)
        self.win.lesson.open_page = lambda: None
        self.win.printer.set_focus("L")

    def test_show_slide_and_background(self):
        ef = self.win.efir
        self.win.lesson.command({"cmd": "slide", "block": "sl2"})
        self.assertEqual(ef.mode, "slide")
        st = ef.state()
        self.assertTrue(st["slide"]["src"].endswith("test-slide-2.png"), st["slide"])
        self.assertTrue(st["slide"]["next"].endswith("test-slide-3.png"), st["slide"])
        e = self.state()["efir"]
        self.assertEqual((e["mode"], e["slide_n"], e["slide_bid"]), ("slide", 2, "sl2"))
        self.win.lesson.command({"cmd": "background"})
        self.assertEqual(ef.mode, "idle")
        self.assertIsNone(ef.store.slide)

    def test_slide_step(self):
        ef = self.win.efir
        step = lambda d: self.win.lesson.command({"cmd": "slide_step", "d": d})
        step(1)
        self.assertEqual(ef.slide["bid"], "sl1")                       # ничего не показано — первый слайд
        step(1)
        step(1)
        self.assertEqual(ef.slide["bid"], "sl3")
        step(1)
        self.assertEqual(ef.slide["bid"], "sl3")                       # последний — остаётся
        step(-1)
        self.assertEqual(ef.slide["bid"], "sl2")
        self.win.lesson.command({"cmd": "slide", "block": "sn1"})      # заметку на экран не выводят
        self.assertEqual(ef.slide["bid"], "sl2")

    def test_slide_survives_restart(self):
        from autoprint.efir import store as store_mod
        from autoprint.ui.efir_control import EfirController
        ef = self.win.efir
        self.win.lesson.command({"cmd": "start"})
        self.win.lesson.command({"cmd": "slide", "block": "sl3"})
        folder = ef.store.path.parent
        old = store_mod.efir_dir
        store_mod.efir_dir = lambda: folder
        try:
            ctl2 = EfirController(None)
        finally:
            store_mod.efir_dir = old
        ctl2.settings = ef.settings
        ctl2.show_timer = lambda: None
        ctl2.server.want_port = 18975
        ctl2.ensure_server()
        try:
            ctl2.restore()
            self.assertEqual(ctl2.mode, "slide")
            self.assertTrue(ctl2.state()["slide"]["src"].endswith("test-slide-3.png"))
        finally:
            ctl2.server.stop()

    def test_md_slide_roundtrip(self):
        from autoprint import lesson_md
        text = lesson_md.to_md(self.L, "")
        self.assertIn("![Слайд 2 · План]", text)
        back = lesson_md.parse(text, storage.DATA_DIR, "П")
        self.assertEqual([(b.slide, b.title) for b in back.blocks if b.type == BLOCK_IMAGE],
                         [(1, "Титул"), (2, "План"), (3, "Итоги")])

    def test_item_state_slide(self):
        from autoprint import scenario
        it = scenario.item_state(self.L.find_block("sl2"), lambda p: "/m/" + Path(p).name)
        self.assertEqual(it["slide"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
