"""1.2.1 — зарядка одним щелчком (видео по очереди), фон учеников с запуска (а не чёрный экран). Без окон на экране.
Слайды без чёрных полос — в test_app_lesson.py (ScreenSlideFillTest: нужна настоящая вкладка экрана учеников).

    python tests/test_v121.py
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import quiet  # noqa: E402,F401  — до PySide6: offscreen, своя папка данных

from test_v10 import TMP, make_window, note, pump, stage  # noqa: E402,F401

from autoprint.storage import Settings, Template  # noqa: E402


def window(templates, port):
    win = make_window(templates, port=port)
    win.lesson.open_page = lambda: None
    win.efir.clients = 1                 # вкладка учеников «на связи» — сами её не открываем
    return win


def close(win) -> None:
    win.efir.show_background()
    win._quitting = True
    win.close()
    pump()


def wait(pred, timeout: float = 5) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        pump(20)
        if pred():
            return True
    return False


def videos(*names, missing=()):
    from autoprint.efir.model import Exercise
    out = []
    for n in names:
        p = TMP / f"v121-{n}.mp4"
        if n in missing:
            p.unlink(missing_ok=True)
        else:
            p.write_bytes(b"\x00" * 16)
        out.append(Exercise(n, str(p)))
    return out


def lesson(tid="U", look="") -> Template:
    t = Template("Урок " + tid, [stage("Начало", 5, id=tid + "a"), stage("Зарядка", 3, id=tid + "z", stage_kind="exercise"),
                                 stage("Своя", 3, id=tid + "own", stage_kind="exercise", exercise="Глаза 3")], id=tid)
    t.look = look
    return t


# ================================================================ зарядка одним щелчком

class ExerciseInTurnTest(unittest.TestCase):
    port = 18940

    def setUp(self):
        from autoprint.efir.model import Look
        self.win = window([lesson()], self.port)
        self.look = Look(title="Глаза", exercises=videos("Глаза 1", "Глаза 2", "Глаза 3"))
        self.win.efir.save_look(self.look)
        self.win.store.get("U").look = self.look.id
        self.win.printer.set_focus("U")
        self.win.settings.exercise_pick = "next"
        self.win.settings.exercise_last = ""

    def tearDown(self):
        close(self.win)

    def click(self, **kw):
        """«Зарядка» наверху: страница шлёт exercise с выбором из настройки (без номера видео)."""
        self.win.efir.show_background()
        self.win.lesson.command({"cmd": "exercise", "pick": self.win.settings.exercise_pick, **kw})
        self.assertEqual(self.win.efir.mode, "exercise")
        return self.win.efir.ex_index

    def test_one_click_plays_videos_in_turn(self):
        """Щелчок — сразу видео, без меню: 1, 2, 3 и снова 1; прошлое — в настройках (переживёт перезапуск)."""
        self.assertEqual([self.click() for _ in range(4)], [0, 1, 2, 0])
        self.assertEqual(self.win.settings.exercise_last, "Глаза 1")

    def test_turn_skips_video_without_file(self):
        Path(self.look.exercises[1].path).unlink()
        try:
            self.assertEqual([self.click() for _ in range(3)], [0, 2, 0])
        finally:
            Path(self.look.exercises[1].path).write_bytes(b"\x00" * 16)

    def test_turn_continues_after_choice_from_menu(self):
        """Выбрали видео в меню (правой кнопкой) — дальше по очереди после него."""
        self.click(index=1)
        self.assertEqual(self.win.settings.exercise_last, "Глаза 2")
        self.assertEqual(self.click(), 2)

    def test_turn_continues_after_restart(self):
        self.win.settings.exercise_last = "глаза 2"           # записано прошлым запуском (регистр, «ё» — неважно)
        self.assertEqual(self.click(), 2)

    def test_stage_own_video_wins(self):
        self.assertEqual(self.click(stage="Uown"), 2)          # этап «Своя» — со своим видео «Глаза 3»
        self.assertEqual(self.click(stage="Uz"), 0)            # этап без видео — по очереди после него

    def test_page_knows_which_video_is_next(self):
        """Подсказка «Зарядки» и кнопка этапа говорят, какое видео включится."""
        self.win.settings.exercise_last = "Глаза 1"
        self.win.lesson._last = None
        self.win.lesson.publish()
        st = self.win.efir.server._states["lesson"]
        self.assertEqual(st["exercise_next"], "Глаза 2")
        self.assertEqual(st["prefs"]["exercise_pick"], "next")

    def test_random_and_ask_still_work(self):
        self.win.settings.exercise_pick = "random"
        seen = [self.click() for _ in range(4)]
        self.assertTrue(all(a != b for a, b in zip(seen, seen[1:])), seen)
        self.win.lesson._set_pref("exercise_pick", "ask")
        self.assertEqual(self.win.settings.exercise_pick, "ask")
        self.win.lesson._set_pref("exercise_pick", "next")
        self.assertEqual(self.win.settings.exercise_pick, "next")

    def test_double_click_does_not_skip_a_video(self):
        """Двойной щелчок по «Зарядке» (страница ещё не знает, что зарядка пошла) — второй не перескакивает видео.
        Выбор видео в меню сразу после — меняет его (номер указан)."""
        self.win.efir.show_background()
        seq = self.win.efir.ex_seq
        for _ in range(2):
            self.win.lesson.command({"cmd": "exercise", "pick": "next"})
        self.assertEqual((self.win.efir.ex_index, self.win.efir.ex_seq - seq), (0, 1))
        self.assertEqual(self.win.settings.exercise_last, "Глаза 1")
        self.win.lesson.command({"cmd": "exercise", "index": 2})
        self.assertEqual(self.win.efir.ex_index, 2)

    def test_same_titles_still_go_in_turn(self):
        """Видео с одинаковыми названиями (старые оформления: все «Зарядка») — по очереди всё равно все."""
        from autoprint.efir.model import Look
        same = videos("Зарядка", "Другая")
        look = Look(title="Одинаковые", exercises=[same[0], same[0], same[1]])
        self.win.efir.save_look(look)
        self.win.store.get("U").look = look.id
        self.win.efir.webinar = None
        self.win.lesson._idle_key = ""
        self.assertEqual([self.click() for _ in range(4)], [0, 1, 2, 0])

    def test_compact_click_uses_current_exercise_stage(self):
        """Маленький режим не знает этапов — без этапа программа сама берёт своё видео идущего этапа-зарядки."""
        from datetime import datetime, timedelta
        self.win.lesson.command({"cmd": "start", "force": True})
        live = self.win.efir.store.live
        self.win.efir.store.set_live(live.webinar_id, datetime.now() - timedelta(minutes=9))   # идёт этап «Своя»
        self.win.efir.live_changed.emit()
        self.assertEqual(self.click(), 2)                       # «Глаза 3» — своё видео этапа, а не по очереди
        self.win.efir.stop_live()

    def test_board_exercise_moves_the_turn_too(self):
        """Зарядка с табло вебинара (номер видео) — тоже «прошлая»."""
        self.win.lesson._ensure_screen(self.win.store.get("U"))
        self.win.commands.cmd_efir_screen({"op": "exercise", "index": 2})
        self.assertEqual(self.win.settings.exercise_last, "Глаза 3")


class ExerciseSettingTest(unittest.TestCase):
    def test_default_is_in_turn(self):
        self.assertEqual(Settings().exercise_pick, "next")
        from autoprint.settings_spec import FIELDS
        self.assertIn("next", FIELDS["exercise_pick"][1])

    def test_ask_becomes_in_turn_once(self):
        """До 1.2.1 «Спросить» стояло само (по умолчанию) — теперь щелчок сразу включает видео. Если потом
        выбрать «Спросить» руками — так и останется."""
        from autoprint import migrations
        s = Settings()
        s.exercise_pick = "ask"
        s.migrations = ["tray_v1", "window_v10", "v1"]
        self.assertTrue(migrations.apply(s))
        self.assertEqual(s.exercise_pick, "next")
        s.exercise_pick = "ask"
        migrations.apply(s)
        self.assertEqual(s.exercise_pick, "ask")

    def test_random_kept(self):
        from autoprint import migrations
        s = Settings()
        s.exercise_pick = "random"
        s.migrations = ["tray_v1", "window_v10", "v1"]
        migrations.apply(s)
        self.assertEqual(s.exercise_pick, "random")


# ================================================================ фон учеников с запуска

class IdleScreenTest(unittest.TestCase):
    port = 18941

    def setUp(self):
        from autoprint.efir.model import Look
        self.la = Look(title="Синий", background="color:#123456", caption="Скоро начнём", exercises=videos("Глаза 1"))
        self.lb = Look(title="Куб", background="anim:cube")
        self.win = window([lesson("A"), lesson("B")], self.port)
        for lk in (self.la, self.lb):
            self.win.efir.save_look(lk)
        self.win.store.get("A").look = self.la.id
        self.win.store.get("B").look = self.lb.id

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

    def test_background_of_open_lesson_before_start(self):
        """Урок не начат, эфира нет — у учеников фон и надпись оформления открытого урока, а не чёрный экран."""
        self.focus("A")
        self.assertEqual(self.screen()["mode"], "idle")
        self.assertEqual(self.screen()["bg"], {"kind": "color", "value": "#123456"})
        self.assertEqual(self.screen()["caption"], "Скоро начнём")
        self.focus("B")                                      # открыли другой урок — у учеников его фон
        self.assertEqual(self.screen()["bg"], {"kind": "anim", "value": "cube"})

    def test_at_program_start(self):
        """Запуск программы: эфира не было — экран учеников сам приходит к фону урока (без щелчка по «Фону»)."""
        self.win.printer.set_focus("A")
        self.win.efir.webinar = None
        self.win.efir.restore()
        self.assertTrue(wait(lambda: self.screen().get("bg") == {"kind": "color", "value": "#123456"}), self.screen())

    def test_look_edit_reaches_screen(self):
        self.focus("A")
        self.la.background = "color:#abcdef"
        self.win.efir.save_look(self.la)
        self.assertTrue(wait(lambda: self.screen().get("bg") == {"kind": "color", "value": "#abcdef"}), self.screen())

    def test_break_before_lesson_not_replaced(self):
        """Перерыв, включённый до урока, остаётся, даже если открыть другой урок."""
        self.focus("A")
        self.win.lesson.command({"cmd": "break", "minutes": 5})
        self.focus("B")
        self.assertEqual(self.screen()["mode"], "break")
        self.assertEqual(self.screen()["bg"], {"kind": "color", "value": "#123456"})

    def test_live_lesson_keeps_its_look(self):
        """Урок идёт — открыли другой урок посмотреть: у учеников всё ещё оформление идущего урока."""
        self.focus("A")
        self.win.lesson.command({"cmd": "start", "force": True})
        self.assertEqual(self.win.efir.live_lesson_id(), "A")
        self.win.store.get("B")
        self.win.printer.set_focus("B")
        self.win.lesson._last = None
        self.win.lesson.publish()
        self.assertEqual(self.screen()["bg"], {"kind": "color", "value": "#123456"})

    def test_after_scheduled_webinar_back_to_lesson_look(self):
        """Шёл вебинар по расписанию со своим оформлением, его завершили — у учеников снова оформление урока,
        и «Зарядка» играет видео урока (а не молчит: у вебинара видео нет)."""
        from autoprint.efir.model import Look
        lm = Look(title="Вебинар", background="color:#00ff00")
        self.win.efir.save_look(lm)
        self.focus("A")
        w = self.win.efir.put_webinar({"title": "Вебинар", "start": "10:00", "schedule": [{"name": "Блок", "min": 30}],
                                       "look_id": lm.id})
        self.assertTrue(self.win.efir.launch(w.id, start="", force=True))
        self.assertEqual(self.screen()["bg"], {"kind": "color", "value": "#00ff00"})
        self.win.efir.stop_live()
        self.focus("A")
        self.assertEqual(self.screen()["bg"], {"kind": "color", "value": "#123456"})
        self.win.lesson.command({"cmd": "exercise", "pick": "next"})
        self.assertEqual(self.win.efir.mode, "exercise")

    def test_stale_lesson_after_restart_back_to_background(self):
        """Вчерашний урок не завершили, программу перезапустили: урок снимается — и у учеников фон урока, а не
        чёрный экран до первого щелчка."""
        from datetime import datetime, timedelta
        self.focus("A")
        self.win.lesson.command({"cmd": "start", "force": True})
        live = self.win.efir.store.live
        self.win.efir.store.set_live(live.webinar_id, datetime.now() - timedelta(days=1))
        pump(600)                                              # всё отложенное уже ушло
        self.win.efir.server.publish({"mode": "wait"})        # вкладка учеников после перезапуска
        self.win.efir.webinar = None
        ended = []
        self.win.efir.live_changed.connect(lambda: ended.append(1))
        self.win.efir.restore()
        self.assertIsNone(self.win.efir.store.live)
        self.assertTrue(ended)                                 # экран урока и экран учеников узнают, что урока нет
        self.assertTrue(wait(lambda: self.screen().get("bg") == {"kind": "color", "value": "#123456"}, 1.0),
                        self.screen())                         # сразу, а не когда что-то ещё случайно обновит урок

    def test_no_lesson_default_look(self):
        """Ни одного урока не открыто — фон оформления по умолчанию (а не чёрный)."""
        self.win.printer.set_focus("")
        self.win.settings.lesson_look = self.lb.id
        self.win.lesson._last = None
        self.win.lesson.publish()
        if self.win.lesson.current() is None:
            self.assertEqual(self.screen()["bg"], {"kind": "anim", "value": "cube"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
