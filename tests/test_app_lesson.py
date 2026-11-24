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
        self.assertTrue(self.wait_js("document.querySelector('#lessonStatus').textContent.includes('Урок не начат')"))
        self.assertIn("Начало в", self.status())
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
