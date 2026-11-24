"""Экран урока в окне: эфирная полоса (состояние, время, начать / завершить), план сбоку / сверху / скрыт,
линия урока, этапы, «Дальше».

    .venv\\Scripts\\python.exe tests\\test_app_lesson.py
"""
from __future__ import annotations

import time
import unittest
from datetime import datetime, timedelta

from apphelp import AppPage, code, note, pump, stage  # noqa: F401

from autoprint.storage import Template


def lesson() -> list[Template]:
    return [Template("Проверка урока", [
        note("Перед уроком", id="n0"),
        stage("Начало", 5, id="s1"), note("Привет", id="n1"), code("print('hello')", id="c1"),
        stage("Практика", 10, id="s2"), note("Делаем", role="do", id="n2"),
        stage("Перерыв", 5, id="s3", stage_kind="break"),
        stage("Итоги", 5, id="s4"), note("Вопросы?", role="tell", id="n4"),
    ], id="L1"), Template("Без минут", [stage("А", 0, id="z1"), note("x", id="zn")], id="L0")]


class LessonViewTest(AppPage):
    port = 18996
    templates = staticmethod(lesson)
    route = "#/lesson/L1"

    def setUp(self):
        if self.app.efir.live_webinar() is not None:
            self.stop_live()
        self.app.printer.set_focus("L1")
        self.store.get("L1").start = ""
        self.app.lesson.publish()
        self.app.publish_now()
        self.go("#/lesson/L1", "lesson")
        self.assertTrue(self.wait_js("document.querySelectorAll('#main .stage').length === 4"))

    def tearDown(self):
        if self.app.efir.live_webinar() is not None:
            self.stop_live()
        super().tearDown()

    def status(self) -> str:
        return self.js("document.querySelector('#lessonStatus').textContent")

    def test_status_not_started_with_start_at(self):
        self.store.get("L1").start = "18:00"
        self.app.lesson.publish()
        # «Урок не начат» было и до правки — ждать нового состояния, а не старого текста
        self.assertTrue(self.wait_js("document.querySelector('#lessonStatus').textContent.includes('Начало в')"))
        self.assertIn("Урок не начат", self.status())
        self.assertIn("18:00", self.js("document.querySelector('#startAt').textContent"))
        self.assertTrue(self.js("!document.querySelector('#startBtn').hidden"))
        self.assertTrue(self.js("document.querySelector('#endBtn').hidden"))

    def test_waiting_shows_now_button(self):
        at = (datetime.now() + timedelta(minutes=30)).strftime("%H:%M")
        self.app.lesson.command({"cmd": "start", "at": at})
        self.assertTrue(self.wait_js("document.querySelector('#lessonStatus').textContent.includes('До начала')", 6))
        self.assertTrue(self.js("!document.querySelector('#nowBtn').hidden"))
        self.assertEqual(self.js("document.querySelector('#endBtn').textContent"), "Отменить начало")

    def test_live_status_and_left(self):
        self.go_live(2)
        self.assertTrue(self.wait_js("document.querySelector('#lessonStatus').textContent.includes('этап 1 из 4')", 6))
        big = self.js("document.querySelector('#lessonStatus .big').textContent")
        self.assertRegex(big, r"^[23]:\d\d$")
        self.assertIn("Начало", self.status())
        self.assertTrue(self.js("document.querySelector('#plan .prow[data-id=s1]').classList.contains('current')"))
        self.assertFalse(self.js("document.querySelector('#endBtn').hidden"))
        self.assertTrue(self.js("document.querySelector('#startBtn').hidden"))

    def test_over_shows_plus(self):
        self.go_live(25 + 2)
        self.assertTrue(self.wait_js("document.querySelector('#lessonStatus').textContent.includes('Урок окончен')", 6))
        self.assertTrue(self.js("document.querySelector('#lessonStatus .big').textContent.startsWith('+2:')"))
        self.assertTrue(self.js("document.querySelector('#endBtn').classList.contains('primary')"))

    def test_shift_with_undo(self):
        self.go_live(1)
        before = self.app.efir.store.live.anchor
        self.assertTrue(self.wait_js("document.querySelector('#lessonStatus').textContent.includes('этап 1')", 6))
        self.click("#lessonStatus")
        self.assertTrue(self.wait_js("!!document.querySelector('.pop')"))
        self.js("[...document.querySelectorAll('.pop .mi')].find(b => b.textContent.includes('Следующий этап — сейчас')).click()")
        self.assertTrue(self.wait_py(lambda: self.app.efir.store.live.anchor != before))
        self.assertTrue(self.wait_js("[...document.querySelectorAll('.toast')].some(t => t.textContent.includes('Время этапов сдвинуто на сейчас'))"))
        self.js("[...document.querySelectorAll('.toast .btn')].filter(b => b.textContent.includes('Вернуть')).pop().click()")
        self.assertTrue(self.wait_py(lambda: abs((self.app.efir.store.live.anchor - before).total_seconds()) < 2))

    def test_plan_positions_toggle(self):
        self.app.settings.page_plan = "side"
        self.app.publish_now()
        self.assertTrue(self.wait_js("document.body.classList.contains('plan-side')"))
        self.assertEqual(self.js("document.querySelectorAll('#plan .prow').length"), 4)
        self.js("document.querySelector('#planPos button[data-value=top]').click()")
        self.assertTrue(self.wait_py(lambda: self.app.settings.page_plan == "top"))
        self.assertTrue(self.wait_js("document.body.classList.contains('plan-top')"))
        self.assertEqual(self.js("document.querySelectorAll('#planRibbon .tseg').length"), 4)
        self.assertTrue(self.js("getComputedStyle(document.querySelector('#plan')).display === 'none'"))
        self.js("document.querySelector('#planPos button[data-value=hidden]').click()")
        self.assertTrue(self.wait_js("document.body.classList.contains('plan-hidden')"))
        self.assertTrue(self.js("getComputedStyle(document.querySelector('#planRibbon')).display === 'none'"))
        self.app.settings.page_plan = "side"
        self.app.publish_now()

    def test_ribbon_widths_follow_minutes(self):
        self.app.settings.page_plan = "top"
        self.app.publish_now()
        self.assertTrue(self.wait_js("document.querySelectorAll('#planRibbon .tseg').length === 4"))
        self.assertEqual(self.js("[...document.querySelectorAll('#planRibbon .tseg')].map(s => s.style.flexGrow)"),
                         ["5", "10", "5", "5"])
        self.assertTrue(self.js("document.querySelector('#planRibbon .tseg[data-id=s3]').classList.contains('brk')"))
        self.app.settings.page_plan = "side"
        self.app.publish_now()

    def test_lesson_line_segments(self):
        self.go_live(7)
        self.assertTrue(self.wait_js("document.querySelectorAll('#lessonLine i').length === 4", 6))
        self.assertTrue(self.wait_js("document.querySelector('#lessonLine i:nth-child(1)').classList.contains('done')", 6))
        self.assertTrue(self.js("document.querySelector('#lessonLine i:nth-child(2)').classList.contains('cur')"))

    def test_next_card_starts_next_stage(self):
        self.go_live(1)
        self.assertTrue(self.wait_js("!!document.querySelector('#st-s1 .nextcard')", 6))
        self.assertIn("Практика", self.js("document.querySelector('#st-s1 .nextcard').textContent"))
        before = self.app.efir.store.live.anchor
        self.js("document.querySelector('#st-s1 .nextcard .btn').click()")
        self.assertTrue(self.wait_py(lambda: self.app.efir.store.live.anchor != before))

    def test_no_minutes_button(self):
        self.app.printer.set_focus("L0")
        self.app.lesson.publish()
        self.go("#/lesson/L0", "lesson")
        self.assertTrue(self.wait_js("!!document.querySelector('#minutesBtn') && !document.querySelector('#minutesBtn').hidden", 6))
        self.click("#minutesBtn")
        # курсор — в поле минут: в плане сбоку или в заголовке этапа
        self.assertTrue(self.wait_js("document.activeElement && (document.activeElement.classList.contains('pmin')"
                                     " || document.activeElement.classList.contains('inl-min'))"))

    def test_other_live_asks_sheet(self):
        from autoprint.efir.model import Activity, Webinar
        w = Webinar(title="Вебинар 1Т", schedule=[Activity("Блок", 30)])
        self.app.efir.store.put(w)
        self.app.efir.launch(w.id, start="")
        self.app.lesson.publish()
        try:
            self.assertTrue(self.wait_js("!document.querySelector('#startBtn').hidden"))
            self.click("#startBtn")
            self.assertTrue(self.wait_js("!!document.querySelector('.sheet')"))
            self.assertIn("Сейчас идёт эфир «Вебинар 1Т»", self.js("document.querySelector('.sheet').textContent"))
            self.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
            self.assertEqual(self.app.efir.live_webinar().id, w.id)          # отказались — вебинар идёт
        finally:
            self.app.efir.stop_live()
            self.app.lesson.publish()

    def test_crumbs_and_title(self):
        self.assertEqual(self.js("document.querySelector('#crumbs .cur').textContent"), "Проверка урока")
        self.assertTrue(self.js("document.title.startsWith('Проверка урока')"))
        self.assertTrue(self.js("!!document.querySelector('#lessonMenuBtn')"))


PNG_1x1 = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                        "1f15c4890000000d49444154789c63f8cfc0f01f0005000201a2e3a7a20000000049454e44ae426082")


def screen_lessons() -> list[Template]:
    import tempfile
    from pathlib import Path
    from autoprint.storage import BLOCK_IMAGE, Block
    d = Path(tempfile.mkdtemp())
    imgs = []
    for i in (1, 2):
        p = d / f"slide{i}.png"
        p.write_bytes(PNG_1x1)
        imgs.append(Block(BLOCK_IMAGE, str(p), slide=i, id=f"im{i}"))
    return [Template("Экран учеников", [
        stage("Начало", 5, id="a1"), note("Привет", id="an1"), code("print(1)\nprint(2)", id="ac1"), imgs[0],
        stage("Перерыв", 5, id="a2", stage_kind="break"),
        stage("Зарядка", 5, id="a3", stage_kind="exercise", exercise="Спина"), imgs[1],
        stage("Итоги", 5, id="a4"), note("Пока", id="an4"),
    ], id="SC")]


class ScreenCtlTest(AppPage):
    """Экран учеников значками в полосе и набор кода (Task 8)."""
    port = 18997
    templates = staticmethod(screen_lessons)
    route = "#/lesson/SC"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import tempfile
        from pathlib import Path
        from autoprint.efir.model import Exercise, Look
        d = Path(tempfile.mkdtemp())
        (d / "eyes.mp4").write_bytes(b"x")
        cls.look = Look(title="1Т", exercises=[Exercise("Глаза", str(d / "eyes.mp4")), Exercise("Спина", str(d / "back.mp4"))])
        cls.app.efir.save_look(cls.look)
        cls.store.get("SC").look = cls.look.id

    def setUp(self):
        ef = self.app.efir
        if ef.live_webinar() is not None:
            self.stop_live()
        ef.show_background()
        ef.clients = 1
        self.app.printer.set_focus("SC")
        self.app.lesson.publish()
        self.app.publish_now()
        self.go("#/lesson/SC", "lesson")
        self.assertTrue(self.wait_js("!!document.querySelector('#scrBg')"))

    def tearDown(self):
        self.app.efir.show_background()
        if self.app.efir.live_webinar() is not None:
            self.stop_live()
        self.js("window.appUI.closePop()")
        super().tearDown()

    def menu_items(self):
        self.assertTrue(self.wait_js("!!document.querySelector('.pop')"))
        return self.js("[...document.querySelectorAll('.pop .mi .ml')].map(e => e.textContent)")

    def test_icons_have_tooltips_no_labels(self):
        for sel, name in (("#scrBg", "Фон"), ("#scrEx", "Зарядка"), ("#scrBreak", "Перерыв"), ("#scrSlide", "Слайд")):
            self.assertEqual(self.js(f"document.querySelector('{sel}').getAttribute('aria-label')"), name)
            self.assertEqual(self.js(f"document.querySelector('{sel}').dataset.tip"), name)
            self.assertEqual(self.js(f"document.querySelector('{sel}').innerText.trim()"), "")      # без подписи
        self.assertEqual(self.js("document.querySelector('#scrBg').getAttribute('aria-pressed')"), "true")

    def test_break_menu_planned_first(self):
        self.click("#scrBreak")
        items = self.menu_items()
        self.assertEqual(items[0], "По плану · 5 мин")
        self.assertEqual(items[1:5], ["5 мин", "10 мин", "15 мин", "20 мин"])
        self.js("[...document.querySelectorAll('.pop .mi')].find(b => b.textContent.includes('10 мин')).click()")
        self.assertTrue(self.wait_py(lambda: self.app.efir.mode == "break"))
        self.assertAlmostEqual(self.app.efir.brk_total, 600, delta=2)

    def test_break_running_controls(self):
        self.app.lesson.command({"cmd": "break", "minutes": 10})
        self.app.lesson.publish()
        self.assertTrue(self.wait_js("document.querySelector('#scrBreak').getAttribute('aria-pressed') === 'true'"))
        self.assertTrue(self.wait_js("/\\d+:\\d\\d/.test(document.querySelector('#scrBreak .badge').textContent)"))
        self.click("#scrBreak")
        items = self.menu_items()
        for x in ("+5 мин", "+1 мин", "−1 мин", "Пауза отсчёта", "Заново", "Убрать — снова фон"):
            self.assertIn(x, items)
        ends = self.app.efir.brk_ends
        self.js("[...document.querySelectorAll('.pop .mi')].find(b => b.textContent.includes('+5 мин')).click()")
        self.assertTrue(self.wait_py(lambda: self.app.efir.brk_ends - ends > 290))

    def test_no_auto_switch_on_break_stage(self):
        self.go_live(6, tid="SC")                     # идёт этап «Перерыв» (5–10 мин)
        self.assertTrue(self.wait_js("document.querySelector('#lessonStatus').textContent.includes('Перерыв')", 6))
        pump(1500)
        self.assertEqual(self.app.efir.mode, "idle")                 # ничего не включилось само
        self.assertTrue(self.wait_js("document.querySelector('#scrBreak').classList.contains('pulse')"))
        self.click("#scrBreak")                       # учитель заметил — подсветка гаснет, перерыв не включился
        self.assertTrue(self.wait_js("!document.querySelector('#scrBreak').classList.contains('pulse')"))
        self.assertEqual(self.app.efir.mode, "idle")

    def test_exercise_list_and_muted_mark(self):
        self.app.lesson.publish()
        self.click("#scrEx")
        self.assertEqual(self.menu_items()[:2], ["Глаза", "Спина"])
        self.js("[...document.querySelectorAll('.pop .mi')].find(b => b.textContent.includes('Глаза')).click()")
        self.assertTrue(self.wait_py(lambda: self.app.efir.mode == "exercise"))
        self.app.efir.video_muted = True
        self.app.lesson.publish()
        self.assertTrue(self.wait_js("document.querySelector('#scrEx').classList.contains('warn')"))
        self.assertIn("без звука", self.js("document.querySelector('#scrEx').dataset.tip"))
        self.app.efir.video_muted = False

    def test_slide_arrows(self):
        self.click("#scrSlide")
        self.assertTrue(self.wait_py(lambda: self.app.efir.mode == "slide"))
        self.assertTrue(self.wait_js("!document.querySelector('#slideNav').hidden"))
        self.assertTrue(self.wait_js("document.querySelector('#slideNav .n').textContent === '1'"))
        self.click("#slideNav .next")
        self.assertTrue(self.wait_py(lambda: (self.app.efir.slide or {}).get("bid") == "im2"))

    def test_thumb_shows_screen_background(self):
        old = self.look.background
        self.look.background = "color:#123456"
        self.app.efir.save_look(self.look)
        try:
            self.app.lesson.publish()
            self.assertTrue(self.wait_js("getComputedStyle(document.querySelector('#screenThumb .scr')).backgroundColor"
                                         " === 'rgb(18, 52, 86)'"))
        finally:
            self.look.background = old
            self.app.efir.save_look(self.look)

    def test_tab_closed_thumb_open_button(self):
        opened = []
        old = self.app.efir.open_tab
        self.app.efir.open_tab = lambda: opened.append(1)
        try:
            self.app.efir.clients = 0
            self.app.lesson.publish()
            self.assertTrue(self.wait_js("!document.querySelector('#screenOpen').hidden"))
            self.click("#screenOpen")
            self.assertTrue(self.wait_py(lambda: opened == [1]))
        finally:
            self.app.efir.open_tab = old
            self.app.efir.clients = 1

    def test_type_button_arms_and_counts_down(self):
        started = []
        eng = self.app.printer.engine
        old = eng.start
        eng.start = lambda *a, **k: started.append(a)
        try:
            self.assertTrue(self.wait_js("!!document.querySelector('.blk[data-id=ac1] .typeBtn')"))
            self.click(".blk[data-id=ac1] .typeBtn")
            self.assertTrue(self.wait_py(lambda: bool(started)))
            self.assertEqual(self.app.printer.armed()[1].id, "ac1")
            self.assertEqual(started[0][1] if len(started[0]) > 1 else None, max(1, self.app.settings.button_countdown_s))
        finally:
            eng.start = old
            self.app.printer.stop()

    def test_typing_bar_pause_stop(self):
        snap = self.app.printer.snapshot
        self.app.printer.snapshot = lambda: {**snap(), "state": "running", "block": "ac1", "progress": .4,
                                             "line": {"i": 2, "n": 2}, "target": "VS Code"}
        stopped = []
        old_stop = self.app.printer.stop
        self.app.printer.stop = lambda: stopped.append(1)
        try:
            self.app.lesson.publish()
            self.assertTrue(self.wait_js("!document.querySelector('#typingBar').hidden"))
            text = self.js("document.querySelector('#typingBar').textContent")
            self.assertIn("Набираю", text)
            self.assertIn("строка 2 из 2", text)
            self.assertIn("VS Code", text)
            self.click("#typingBar .tstop")
            self.assertTrue(self.wait_py(lambda: stopped == [1]))
        finally:
            self.app.printer.snapshot = snap
            self.app.printer.stop = old_stop
            self.app.lesson.publish()

    def _paused_typing(self):
        p = self.app.printer
        snap, toggle, state = p.snapshot, p.toggle, p.engine.state
        p.snapshot = lambda: {**snap(), "state": "paused", "block": "ac1", "progress": .5}
        calls = []
        p.toggle = lambda **k: calls.append(k)
        p.engine.state = "paused"

        def restore():
            p.snapshot, p.toggle, p.engine.state = snap, toggle, state
            self.app.lesson.publish()
        self.addCleanup(restore)
        self.app.lesson.publish()
        return calls

    def test_typing_bar_resume_counts_down(self):
        calls = self._paused_typing()
        self.assertTrue(self.wait_js("document.querySelector('#typingBar .tact').textContent.includes('Продолжить')"))
        self.click("#typingBar .tact")
        self.assertTrue(self.wait_py(lambda: calls == [{"countdown": max(1, self.app.settings.button_countdown_s)}]))

    def test_pause_after_window_click_keeps_pause(self):
        # щелчок по окну сам ставит набор на паузу; затем «Пауза» — набор не должен продолжиться
        calls = self._paused_typing()
        self.app.lesson.command({"cmd": "typing", "op": "pause"})
        pump(200)
        self.assertEqual(calls, [])
        self.assertEqual(self.app.printer.engine.state, "paused")

    def test_type_opts_change_mode(self):
        self.app.settings.print_mode = "block"
        self.assertTrue(self.wait_js("!!document.querySelector('.blk[data-id=ac1] .typeOpts')"))
        self.click(".blk[data-id=ac1] .typeOpts")
        self.assertTrue(self.wait_js("!!document.querySelector('.pop .typepanel')"))
        self.js("document.querySelector('.pop .typepanel .seg button[data-value=lines]').click()")
        self.assertTrue(self.wait_py(lambda: self.app.settings.print_mode == "lines"))
        self.app.printer.set_option("mode", "block")


if __name__ == "__main__":
    unittest.main(verbosity=2)
