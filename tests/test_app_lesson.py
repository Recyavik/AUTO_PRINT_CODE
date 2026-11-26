"""Экран урока в окне: эфирная полоса (состояние, время, начать / завершить), план сбоку / сверху / скрыт,
линия урока, этапы, «Дальше».

    .venv\\Scripts\\python.exe tests\\test_app_lesson.py
"""
from __future__ import annotations

import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

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

    def test_shift_back_stays_visible(self):
        """Время этапов сдвинули («Следующий этап — сейчас») — «Вернуть время» видно, пока сдвиг есть, а не 10 с."""
        import json
        from autoprint.efir.store import efir_dir
        self.app.lesson.command({"cmd": "start", "force": True})
        self.assertTrue(self.wait_js("!document.querySelector('#endBtn').hidden", 6))
        plan = self.app.efir.store.live.plan
        self.assertIsNotNone(plan)
        self.assertTrue(self.js("document.querySelector('#shiftBack').hidden"))
        self.app.lesson.command({"cmd": "start_at", "index": 1})      # закончили раньше — дальше по плану
        self.app.lesson.publish()
        self.assertTrue(self.wait_js("!document.querySelector('#shiftBack').hidden", 6))
        self.assertIn("Вернуть время", self.js("document.querySelector('#shiftBack').textContent"))
        self.assertIn(f"{plan.hour}:{plan.minute:02d}", self.js("document.querySelector('#shiftBack').dataset.tip"))   # «0:58» — часы как в окне
        raw = json.loads((efir_dir() / "schedules.json").read_text(encoding="utf-8"))
        self.assertEqual(raw["live"]["plan"], plan.isoformat(timespec="seconds"))     # переживёт перезапуск
        self.click("#shiftBack")
        self.assertTrue(self.wait_py(lambda: self.app.efir.store.live.anchor == plan))
        self.assertTrue(self.wait_js("document.querySelector('#shiftBack').hidden", 6))
        self.stop_live()

    def test_zoom_never_jumps_back(self):
        """Ctrl+= несколько раз подряд — масштаб только растёт: ответ программы на прошлый шаг не откатывает его
        (было: 110 → 120 → 130 → 110 → 120 → 130 — «как будто два интерфейса»)."""
        self.js("window.__z = []; new MutationObserver(() => __z.push(parseFloat(document.documentElement.style.zoom)))"
                ".observe(document.documentElement, {attributes: true, attributeFilter: ['style']})")
        try:
            for _ in range(3):
                self.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: '=', ctrlKey: true, bubbles: true}))")
            self.assertTrue(self.wait_py(lambda: self.app.settings.page_zoom == 130))
            pump(1200)
            z = [x for x in self.js("__z") if x]
            self.assertEqual(z[-1], 1.3, z)
            self.assertTrue(all(b >= a for a, b in zip(z, z[1:])), z)
        finally:
            self.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: '0', ctrlKey: true, bubbles: true}))")
            self.assertTrue(self.wait_py(lambda: self.app.settings.page_zoom == 100))

    def lcol_width(self):
        return self.js("getComputedStyle(document.querySelector('.lcol')).maxWidth")

    def drag_grip(self, side: str, dx: float) -> None:
        """Тянуть ручку колонки текста (side: l / r) на dx пикселей окна — события мыши, как от человека."""
        self.js(f"""(() => {{
          const g = document.querySelector('.lgrip.{side}'); const r = g.getBoundingClientRect();
          const x = r.left + r.width / 2, y = r.top + 40;
          const ev = (t, cx) => new PointerEvent(t, {{bubbles: true, clientX: cx, clientY: y, pointerId: 1, button: 0, buttons: 1}});
          g.dispatchEvent(ev('pointerdown', x));
          document.dispatchEvent(ev('pointermove', x + {dx} / 2));
          document.dispatchEvent(ev('pointermove', x + {dx}));
          document.dispatchEvent(ev('pointerup', x + {dx}));
        }})()""")

    def test_text_column_drag_resize(self):
        """Колонку текста тянут за край мышью — шире или уже (по центру, обе стороны), ширина запоминается;
        двойной щелчок по ручке — снова обычная."""
        self.app.settings.page_width = "normal"
        self.app.publish_now()
        self.assertTrue(self.wait_js("getComputedStyle(document.querySelector('.lcol')).maxWidth === '880px'"))
        self.assertTrue(self.js("!!document.querySelector('.lgrip.l') && !!document.querySelector('.lgrip.r')"))
        self.assertIn("Тяните", self.js("document.querySelector('.lgrip.r').dataset.tip"))
        self.app.settings.page_plan = "hidden"                    # места вширь — больше
        self.app.publish_now()
        self.assertTrue(self.wait_js("document.body.classList.contains('plan-hidden')"))
        seen = lambda: self.js("document.querySelector('.lcol').offsetWidth")          # noqa: E731 — видимая ширина
        w0 = seen()
        self.drag_grip("l", -60)                                  # левый край наружу на 60 — колонка шире на 120
        self.assertTrue(self.wait_py(lambda: self.app.settings.page_width.isdigit()), self.app.settings.page_width)
        self.assertAlmostEqual(int(self.app.settings.page_width), w0 + 120, delta=4)
        self.assertTrue(self.wait_js("Math.abs(parseFloat(getComputedStyle(document.querySelector('.lcol')).maxWidth) - "
                                     f"{self.app.settings.page_width}) < 1"))
        w1 = seen()
        self.drag_grip("r", -100)                                 # правый край внутрь на 100 — уже на 200
        self.assertTrue(self.wait_py(lambda: abs(int(self.app.settings.page_width) - (w1 - 200)) <= 4),
                        (w1, self.app.settings.page_width))
        self.assertAlmostEqual(seen(), w1 - 200, delta=4)
        self.drag_grip("r", -1000)                                # слишком узко — не уже 480
        self.assertTrue(self.wait_py(lambda: self.app.settings.page_width == "480"), self.app.settings.page_width)
        self.js("document.querySelector('.lgrip.r').dispatchEvent(new MouseEvent('dblclick', {bubbles: true}))")
        self.assertTrue(self.wait_py(lambda: self.app.settings.page_width == "normal"))
        self.assertTrue(self.wait_js("getComputedStyle(document.querySelector('.lcol')).maxWidth === '880px'"))
        for bad in ("100", "99999", "abc"):                       # чужое — мимо
            self.app.lesson.command({"cmd": "prefs", "key": "page_width", "value": bad})
        self.assertEqual(self.app.settings.page_width, "normal")
        self.app.settings.page_plan = "side"
        self.app.publish_now()

    def test_text_width_choice(self):
        """Ширина текста урока: узко / обычно / широко / во всё окно — из «Аа» в шапке, запоминается."""
        self.app.settings.page_width = "normal"
        self.app.publish_now()
        self.assertTrue(self.wait_js("getComputedStyle(document.querySelector('.lcol')).maxWidth === '880px'"))
        self.click("#zoomBtn")
        self.assertTrue(self.wait_js("!!document.querySelector('.pop #lessonWidth')"))
        self.js("document.querySelector('#lessonWidth button[data-value=wide]').click()")
        self.assertTrue(self.wait_py(lambda: self.app.settings.page_width == "wide"))
        self.assertTrue(self.wait_js("getComputedStyle(document.querySelector('.lcol')).maxWidth === '1160px'"))
        self.js("document.querySelector('#lessonWidth button[data-value=full]').click()")
        self.assertTrue(self.wait_py(lambda: self.app.settings.page_width == "full"))
        self.assertTrue(self.wait_js("getComputedStyle(document.querySelector('.lcol')).maxWidth === 'none'"))
        self.js("document.querySelector('#lessonWidth button[data-value=narrow]').click()")
        self.assertTrue(self.wait_js("getComputedStyle(document.querySelector('.lcol')).maxWidth === '720px'"))
        self.assertTrue(self.wait_py(lambda: self.app.settings.page_width == "narrow"))
        self.js("window.appUI.closePop()")
        self.app.lesson.command({"cmd": "prefs", "key": "page_width", "value": "huge"})    # чужое значение — мимо
        self.assertEqual(self.app.settings.page_width, "narrow")
        self.app.settings.page_width = "normal"
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
        stage("Ещё зарядка", 3, id="a5", stage_kind="exercise"),          # видео не указано — выбрать на уроке
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
        self.app.settings.exercise_pick = "next"     # по умолчанию с 1.2.1: щелчок — видео по очереди
        self.app.settings.exercise_last = ""
        self.app.lesson._last_slide = ""             # «Слайд» после другого теста — снова с первого
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
            self.assertTrue(self.js(f"document.querySelector('{sel}').dataset.tip").startswith(name), sel)
            self.assertEqual(self.js(f"document.querySelector('{sel}').innerText.trim()"), "")      # без подписи
        self.assertEqual(self.js("document.querySelector('#scrBg').getAttribute('aria-pressed')"), "true")

    def test_black_one_click_and_back(self):
        """«Чёрный экран» — значок рядом с «Фоном»: щелчок — у учеников чёрный, миниатюра так и говорит; ещё щелчок — фон."""
        sel = "#scrBlack"
        self.assertEqual(self.js(f"document.querySelector('{sel}').getAttribute('aria-label')"), "Чёрный экран")
        self.assertEqual(self.js(f"document.querySelector('{sel}').innerText.trim()"), "")
        self.assertEqual(self.js(f"document.querySelector('{sel}').previousElementSibling.id"), "scrBg")
        self.click(sel)
        self.assertTrue(self.wait_py(lambda: self.app.efir.mode == "black"))
        self.app.lesson.publish()
        self.assertTrue(self.wait_js(f"document.querySelector('{sel}').getAttribute('aria-pressed') === 'true'"))
        self.assertEqual(self.js("document.querySelector('#scrBg').getAttribute('aria-pressed')"), "false")
        self.assertTrue(self.js("document.querySelector('#screenThumb').dataset.tip.startsWith('У учеников чёрный экран')"))
        self.assertIn("снова фон", self.js(f"document.querySelector('{sel}').dataset.tip"))
        self.click(sel)
        self.assertTrue(self.wait_py(lambda: self.app.efir.mode == "idle"))

    def test_exercise_one_click_in_turn(self):
        """«Зарядка» — одним щелчком: сразу видео по очереди, без меню; подсказка говорит, какое включится."""
        self.app.lesson.publish()
        self.assertTrue(self.wait_js("document.querySelector('#scrEx').dataset.tip.includes('«Глаза»')"))
        self.assertIn("правой кнопкой", self.js("document.querySelector('#scrEx').dataset.tip"))
        self.click("#scrEx")
        self.assertTrue(self.wait_py(lambda: self.app.efir.mode == "exercise" and self.app.efir.ex_index == 0))
        self.assertFalse(self.js("!!document.querySelector('.pop')"))                 # без меню
        self.assertEqual(self.app.settings.exercise_last, "Глаза")
        self.app.lesson.publish()
        self.assertTrue(self.wait_js("document.querySelector('#scrEx').getAttribute('aria-pressed') === 'true'"))
        self.click("#scrEx")                          # идёт — щелчок открывает меню: пауза, сначала, другое видео
        items = self.menu_items()
        for x in ("Пауза", "Сначала", "Убрать — снова фон", "Глаза", "Спина"):
            self.assertIn(x, items)

    def test_exercise_ask_but_stage_has_video(self):
        """«Спросить», но идёт этап-зарядка со своим видео — щелчок включает его, и подсказка так и говорит."""
        self.app.settings.exercise_pick = "ask"
        self.go_live(11, tid="SC")                    # этап «Зарядка» (10–15 мин) — своё видео «Спина»
        self.app.lesson.publish()
        self.assertTrue(self.wait_js("document.querySelector('#scrEx').dataset.tip.includes('«Спина»')", 6),
                        self.js("document.querySelector('#scrEx').dataset.tip"))

    def test_exercise_ask_setting_opens_menu(self):
        self.app.settings.exercise_pick = "ask"
        self.app.lesson.publish()
        self.assertTrue(self.wait_js("document.querySelector('#scrEx').dataset.tip === 'Зарядка — выбрать видео'"))
        self.click("#scrEx")
        self.assertEqual(self.menu_items()[:2], ["Глаза", "Спина"])
        self.assertEqual(self.app.efir.mode, "idle")

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
        self.assertTrue(self.wait_js("/\\d+:\\d\\d/.test(document.querySelector('#scrInfo .brkleft').textContent)"))
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
        self.js("document.querySelector('#scrEx').dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, cancelable: true}))")
        self.assertEqual(self.menu_items()[:2], ["Глаза", "Спина"])           # правой кнопкой — выбрать видео
        self.js("[...document.querySelectorAll('.pop .mi')].find(b => b.textContent.includes('Глаза')).click()")
        self.assertTrue(self.wait_py(lambda: self.app.efir.mode == "exercise"))
        self.app.efir.video_muted = True
        self.app.lesson.publish()
        self.assertTrue(self.wait_js("document.querySelector('#scrEx').classList.contains('warn')"))
        self.assertIn("без звука", self.js("document.querySelector('#scrEx').dataset.tip"))
        self.app.efir.video_muted = False

    ICONS = ("#scrBg", "#scrBlack", "#scrEx", "#scrBreak", "#scrSlide")

    def icon_x(self):
        sels = ",".join(repr(s) for s in self.ICONS)
        return self.js(f"[{sels}].map(s => Math.round(document.querySelector(s).getBoundingClientRect().left * 10) / 10)")

    def assertIconsStay(self, before):
        pump(400)                                    # выезд стрелок и цифры — 0,2 с
        after = self.icon_x()
        for a, b in zip(before, after):
            self.assertAlmostEqual(a, b, delta=0.5, msg=f"значки сдвинулись: {before} → {after}")

    def test_icons_stay_when_slide_nav_rolls_out(self):
        """Включили слайд — стрелки и номер выезжают в заранее оставленное место; значки на месте."""
        before = self.icon_x()
        self.click("#scrSlide")
        self.assertTrue(self.wait_js("!document.querySelector('#slideNav').hidden"))
        self.assertIconsStay(before)
        nav = self.js("(() => { const r = document.querySelector('#slideNav').getBoundingClientRect(),"
                      " s = document.querySelector('#scrInfo').getBoundingClientRect();"
                      " return [r.left >= s.left - 0.5, r.right <= s.right + 0.5, r.width > 40]; })()")
        self.assertEqual(nav, [True, True, True])
        self.click("#slideNav .next")
        self.assertTrue(self.wait_js("document.querySelector('#slideNav .n').textContent === '2'"))
        self.assertIconsStay(before)

    def test_icons_stay_with_break_countdown(self):
        """Перерыв идёт — отсчёт рядом со значками, в том же месте; значки не раздвигаются."""
        before = self.icon_x()
        self.app.lesson.command({"cmd": "break", "minutes": 10})
        self.app.lesson.publish()
        self.assertTrue(self.wait_js("/\\d+:\\d\\d/.test(document.querySelector('#scrInfo .brkleft').textContent)"))
        self.assertIconsStay(before)
        self.click("#scrInfo .brkleft")              # отсчёт — та же кнопка, что и «Перерыв»: меню перерыва
        self.assertIn("+5 мин", self.menu_items())

    def test_icons_stay_when_lesson_starts_and_edit_toggles(self):
        before = self.icon_x()
        self.go_live(1)
        self.assertTrue(self.wait_js("!document.querySelector('#endBtn').hidden", 6))
        self.assertIconsStay(before)
        self.click("#editToggle")                    # правка во время урока: «✓ Сохранено» появилось
        self.assertTrue(self.wait_js("!document.querySelector('#saveChip').hidden"))
        self.assertIconsStay(before)
        self.click("#editToggle")

    def test_lesson_pictures_are_light_copies(self):
        """В тексте урока — копия под ширину колонки (прокрутка без рывков); в просмотре и ученикам — оригинал."""
        src = self.js("document.querySelector('[data-id=im1] figure img').getAttribute('src')")
        full = self.js("document.querySelector('[data-id=im1] figure img').dataset.full")
        self.assertRegex(src, r"^/media/[0-9a-f]{16}/[^?]+\?w=(640|960|1280|1600|1920)$")
        self.assertEqual(src.split("?")[0], full)
        self.assertEqual(self.js("document.querySelector('[data-id=im1] figure img').decoding"), "async")
        self.go_live(1)
        self.assertTrue(self.wait_js("document.body.classList.contains('mode-lesson')", 6))
        self.click("[data-id=im1] figure img")
        self.assertTrue(self.wait_js("!document.querySelector('#viewer').hidden"))
        self.assertEqual(self.js("new URL(document.querySelector('#viewer img').src).pathname"), full)
        # шапка окна (кнопки, перетаскивание) — над просмотром; Esc и «×» закрывают
        self.assertTrue(self.js("document.querySelector('#viewer').getBoundingClientRect().top >= "
                                "document.querySelector('#titlebar').getBoundingClientRect().bottom - 0.5"))
        self.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
        self.assertTrue(self.wait_js("document.querySelector('#viewer').hidden"))
        self.click("[data-id=im1] figure img")
        self.assertTrue(self.wait_js("!document.querySelector('#viewer').hidden"))
        self.click("#viewer .vclose")
        self.assertTrue(self.wait_js("document.querySelector('#viewer').hidden"))
        self.click("#scrSlide")
        self.assertTrue(self.wait_js("document.querySelector('#screenThumb .scr').style.backgroundImage.includes('?w=320')"))

    def test_look_from_lesson_saves_and_returns(self):
        """Оформление открыли из урока — «Сохранить и вернуться к уроку» и «К уроку»; сохранили — снова урок."""
        self.app.lesson.command({"cmd": "look_edit"})
        self.assertTrue(self.wait_js(f"location.hash === '#/efir/looks/{self.look.id}?from=SC'", 6))
        self.assertTrue(self.wait_js("!!document.querySelector('#lkBack')", 6))
        self.assertIn("Экран учеников", self.js("document.querySelector('#crumbs').textContent"))      # урок — в крошках
        self.assertEqual(self.js("document.querySelector('#lksave').textContent"), "Сохранить и вернуться к уроку")
        old = self.look.title
        try:
            self.js("const t = document.querySelector('#lktitle'); t.value = '1Т новый'; t.dispatchEvent(new Event('input'))")
            self.click("#lksave")
            self.assertTrue(self.wait_js("location.hash === '#/lesson/SC'", 6))
            self.assertTrue(self.wait_py(lambda: self.app.efir.store.look(self.look.id).title == "1Т новый"))
            # без правок «К уроку» — сразу назад
            self.app.lesson.command({"cmd": "look_edit"})
            self.assertTrue(self.wait_js("!!document.querySelector('#lkBack')", 6))
            self.click("#lkBack")
            self.assertTrue(self.wait_js("location.hash === '#/lesson/SC'", 6))
        finally:
            lk = self.app.efir.store.look(self.look.id)
            lk.title = old
            self.app.efir.save_look(lk)

    def fake_print(self, **kw):
        p = self.app.printer
        real = p.snapshot

        def fake():
            d = real()
            d.update(kw)
            return d
        p.snapshot = fake
        self.app.lesson.publish()
        return lambda: (setattr(p, "snapshot", real), self.app.lesson.publish())

    def test_typing_marks_current_line_and_caret(self):
        """Набор: набранное, текущая строка и следующая — разным цветом; курсор бежит там, где набор."""
        undo = self.fake_print(state="running", block="ac1", progress=0.6, next_lines=[2],
                               cur={"line": 2, "col": 3, "from": 1})
        try:
            sel = "[data-id=ac1] .hls"
            self.assertTrue(self.wait_js(f"!!document.querySelector('{sel} .hl.cur')"))
            self.assertEqual(self.js(f"document.querySelector('{sel} .hl.cur').style.top"), "33px")      # строка 2
            self.assertEqual(self.js(f"document.querySelectorAll('{sel} .hl.done').length"), 1)          # строка 1
            self.assertEqual(self.js(f"document.querySelectorAll('{sel} .hl.next').length"), 0)          # 2 — текущая
            caret = self.js(f"(() => {{ const c = document.querySelector('{sel} .caret'); const g = document.querySelector("
                            f"'[data-id=ac1] .gut'); return c ? [c.style.top, c.getBoundingClientRect().left > "
                            f"g.getBoundingClientRect().right] : null; }})()")
            self.assertEqual(caret, ["33px", True])
        finally:
            undo()
        undo = self.fake_print(state="line_wait", block="ac1", progress=0.5, next_lines=[2],
                               cur={"line": 1, "col": 8, "from": 1})
        try:
            sel = "[data-id=ac1] .hls"
            self.assertTrue(self.wait_js(f"document.querySelectorAll('{sel} .hl.next').length === 1"))   # следующая
            self.assertTrue(self.js(f"document.querySelector('{sel} .caret').classList.contains('wait')"))
        finally:
            undo()

    def test_pause_says_why(self):
        """Пауза, которую поставил не человек кнопкой, — с причиной: «вы щёлкнули мышью…»."""
        undo = self.fake_print(state="paused", block="ac1", progress=0.3, pause_why="вы щёлкнули мышью — курсор мог сместиться")
        try:
            self.assertTrue(self.wait_js("!document.querySelector('#typingBar').hidden"))
            self.assertTrue(self.wait_js("document.querySelector('#typingBar').textContent.includes('вы щёлкнули мышью')"))
            self.assertIn("Продолжить", self.js("document.querySelector('#typingBar').textContent"))
            self.assertIn("щёлкнули мышью", self.js("document.querySelector('[data-id=ac1] .armslot').textContent"))
        finally:
            undo()

    def test_to_screen_button_right_and_grows(self):
        """«На экран» — справа от картинки, заметная и крупнее на большом окне (до предела); картинка — по центру."""
        geo = ("(() => { const b = document.querySelector('[data-id=im1] .toscreen').getBoundingClientRect();"
               " const r = document.querySelector('[data-id=im1] .row').getBoundingClientRect();"
               " const i = document.querySelector('[data-id=im1] figure img').getBoundingClientRect();"
               " return [r.right - b.right, b.height, Math.abs((i.left + i.right) / 2 - (r.left + r.right) / 2)]; })()")
        self.edge.call("Emulation.setDeviceMetricsOverride", {"width": 1100, "height": 800, "deviceScaleFactor": 1, "mobile": False})
        try:
            pump(400)
            small = self.js(geo)
            self.edge.call("Emulation.setDeviceMetricsOverride", {"width": 2400, "height": 1300, "deviceScaleFactor": 1, "mobile": False})
            pump(400)
            big = self.js(geo)
        finally:
            self.edge.call("Emulation.clearDeviceMetricsOverride")
            pump(200)
        self.assertLess(small[0], 24, small)                  # у правого края строки картинки
        self.assertGreaterEqual(small[1], 32, small)          # не мелкая
        self.assertGreater(big[1], small[1] + 4, (small, big))  # на большом окне — крупнее
        self.assertLessEqual(big[1], 46, big)                 # но до предела
        self.assertLess(small[2], 2, small)                   # картинка по центру

    def stage_ex_btn(self, sid):
        return f"#main [data-act=exercise][data-stage={sid}]"

    def test_exercise_stage_with_video_starts_it(self):
        self.assertTrue(self.wait_js(f"!!document.querySelector('{self.stage_ex_btn('a3')}')"))
        self.assertIn("· Спина", self.js(f"document.querySelector('{self.stage_ex_btn('a3')}').textContent"))
        back = Path(self.look.exercises[1].path)
        back.write_bytes(b"x")
        try:
            self.click(self.stage_ex_btn("a3"))
            self.assertTrue(self.wait_py(lambda: self.app.efir.mode == "exercise" and self.app.efir.ex_index == 1))
            self.assertFalse(self.js("!!document.querySelector('.pop')"))            # без вопроса
        finally:
            back.unlink()

    def test_exercise_stage_without_video_asks(self):
        """Этап «зарядка» без видео (так его пишет нейросеть) — на уроке то же меню видео, что у «Зарядки» наверху."""
        self.app.settings.exercise_pick = "ask"
        self.app.lesson.publish()
        sel = self.stage_ex_btn("a5")
        self.assertTrue(self.wait_js(f"document.querySelector('{sel}')?.textContent === 'Выбрать зарядку ученикам…'"))
        self.click(sel)
        self.assertEqual(self.menu_items()[:2], ["Глаза", "Спина"])
        self.assertEqual(self.app.efir.mode, "idle")
        self.js("[...document.querySelectorAll('.pop .mi')].find(b => b.textContent.includes('Глаза')).click()")
        self.assertTrue(self.wait_py(lambda: self.app.efir.mode == "exercise" and self.app.efir.ex_index == 0))

    def test_exercise_stage_random_not_twice_in_a_row(self):
        self.app.settings.exercise_pick = "random"
        self.app.lesson.publish()
        sel = self.stage_ex_btn("a5")
        self.assertTrue(self.wait_js(f"document.querySelector('{sel}')?.textContent === 'Включить случайную зарядку'"))
        back = Path(self.look.exercises[1].path)
        back.write_bytes(b"x")
        try:
            seen = []
            for _ in range(4):
                self.app.efir.show_background()
                self.click(sel)
                self.assertTrue(self.wait_py(lambda: self.app.efir.mode == "exercise"))
                self.assertFalse(self.js("!!document.querySelector('.pop')"))
                seen.append(self.app.efir.ex_index)
            self.assertTrue(all(a != b for a, b in zip(seen, seen[1:])), seen)     # не то же видео подряд
        finally:
            back.unlink()
            self.app.settings.exercise_pick = "next"
            self.app.lesson.publish()

    def test_exercise_stage_without_video_in_turn(self):
        """Этап «зарядка» без своего видео, настройка «По очереди» — кнопка этапа называет видео и включает его."""
        self.app.lesson.publish()
        sel = self.stage_ex_btn("a5")
        self.assertTrue(self.wait_js(f"document.querySelector('{sel}')?.textContent === 'Включить зарядку ученикам · Глаза'"))
        self.click(sel)
        self.assertTrue(self.wait_py(lambda: self.app.efir.mode == "exercise" and self.app.efir.ex_index == 0))
        self.assertFalse(self.js("!!document.querySelector('.pop')"))

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


class ScreenImageTest(AppPage):
    """Экран учеников: картинка-заставка (фон, перерыв) видна целиком в окне любой формы, поля — размытой копией."""
    port = 18998
    route = "#/lesson/L1"

    def test_break_image_fits_whole(self):
        import base64
        from pathlib import Path
        from autoprint import storage
        from autoprint.efir.model import Look
        from cdp import Edge
        png = Path(storage.DATA_DIR) / "brk-test.png"
        png.write_bytes(base64.b64decode(PNG_1x1_B64))
        look = Look(title="С заставкой", break_background="image:" + str(png), background="image:" + str(png))
        self.app.efir.save_look(look)
        self.app.printer.set_focus("L1")
        self.store.get("L1").look = look.id
        screen = Edge.start(f"http://127.0.0.1:{self.app.efir.server.port}/", pump=lambda: pump(5), width=1000, height=900)
        try:
            self.app.lesson.command({"cmd": "break", "stage": "", "minutes": 5})
            self.assertTrue(screen.wait("!!document.querySelector('#brk.on .bgwrap .bg-image')", 10))
            for host in ("#brk .bgwrap", "#bgs"):
                fit = screen.eval(f"getComputedStyle(document.querySelector('{host} .bg-image .fit')).backgroundSize")
                fill = screen.eval(f"getComputedStyle(document.querySelector('{host} .bg-image .fill')).backgroundSize")
                self.assertEqual((fit, fill), ("contain", "cover"), host)
        finally:
            screen.close()
            self.app.efir.show_background()


def slide_lessons() -> list[Template]:
    """Слайды 16:9: обычный (белый, синяя полоса заголовка во всю ширину, чёрный квадрат) и «фото» (пёстрый край)."""
    import random
    import tempfile
    from PySide6.QtGui import QColor, QImage
    from autoprint.storage import BLOCK_IMAGE, Block
    d = Path(tempfile.mkdtemp())
    plain = QImage(320, 180, QImage.Format_RGB32)
    plain.fill(QColor("#ffffff"))
    for y in range(36):
        for x in range(320):
            plain.setPixelColor(x, y, QColor("#1e50c8"))          # полоса заголовка: верхние 20 %
    for y in range(70, 110):
        for x in range(140, 180):
            plain.setPixelColor(x, y, QColor("#000000"))
    photo = QImage(320, 180, QImage.Format_RGB32)
    rnd = random.Random(7)
    for y in range(0, 180, 4):                                   # пятна 4×4 — край «фото», не одного цвета
        for x in range(0, 320, 4):
            c = QColor(rnd.randrange(40, 255), rnd.randrange(40, 255), rnd.randrange(40, 255))
            for j in range(4):
                for i in range(4):
                    photo.setPixelColor(x + i, y + j, c)
    lines = QImage(320, 180, QImage.Format_RGB32)             # белый, у правого края — тонкие линии узора
    lines.fill(QColor("#ffffff"))
    for y in range(0, 180, 10):
        for x in range(200, 320):
            lines.setPixelColor(x, y, QColor("#8a8a8a"))
    paths = [d / "plain.png", d / "photo.png", d / "lines.png"]
    plain.save(str(paths[0]))
    photo.save(str(paths[1]))
    lines.save(str(paths[2]))
    return [Template("Слайды", [stage("Начало", 5, id="f1"), Block(BLOCK_IMAGE, str(paths[0]), slide=1, id="sp1"),
                                Block(BLOCK_IMAGE, str(paths[1]), slide=2, id="sp2"),
                                Block(BLOCK_IMAGE, str(paths[2]), slide=3, id="sp3")], id="SF")]


class ScreenSlideFillTest(AppPage):
    """Слайд ученикам: целиком, а поля вокруг (вкладка шире слайда 16:9) — не чёрные: продолжение края слайда
    (цвет и полосы заголовка); край пёстрый — тот же слайд, размытый."""
    port = 18999
    templates = staticmethod(slide_lessons)
    route = "#/lesson/SF"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from cdp import Edge
        from autoprint.efir.model import Look
        cls.look = Look(title="С надписью", caption="█████")          # надпись оформления — до урока на фоне
        cls.app.efir.save_look(cls.look)
        cls.store.get("SF").look = cls.look.id
        cls.app.printer.set_focus("SF")
        cls.app.lesson.publish()
        cls.screen = Edge.start(f"http://127.0.0.1:{cls.app.efir.server.port}/?nofade", pump=lambda: pump(5),
                                width=1400, height=600)
        cls.screen.call("Emulation.setDeviceMetricsOverride", {"width": 1400, "height": 600, "deviceScaleFactor": 1,
                                                               "mobile": False})

    @classmethod
    def tearDownClass(cls):
        cls.screen.close()
        cls.app.efir.show_background()
        super().tearDownClass()

    def show(self, bid):
        self.app.efir.clients = max(1, self.app.efir.clients)
        self.app.lesson.command({"cmd": "slide", "block": bid})
        self.assertTrue(self.screen.wait("document.querySelector('#slide').classList.contains('on') && "
                                         f"document.querySelector('#slide img').getAttribute('src') === "
                                         f"{self.app.efir.state()['slide']['src']!r} && "
                                         "document.querySelector('#slide img').complete", 10))
        pump(300)

    def shot(self):
        import base64
        from PySide6.QtGui import QImage
        data = base64.b64decode(self.screen.call("Page.captureScreenshot", {"format": "png"})["data"])
        img = QImage.fromData(data)
        self.assertEqual((img.width(), img.height()), (1400, 600))
        return lambda x, y: img.pixelColor(x, y).getRgb()[:3]

    def test_plain_slide_margins_continue_its_edge(self):
        self.show("sp1")
        px = self.shot()
        # слайд 16:9 во вкладке 1400×600 — 1067×600 по центру, поля по 166 px слева и справа
        self.assertEqual(px(700, 300), (0, 0, 0))                         # квадрат в середине слайда — на месте
        for x in (10, 1390):
            self.assertEqual(px(x, 400), (255, 255, 255), x)            # поле — белое, как край слайда, не чёрное
            r, g, b = px(x, 40)                                          # полоса заголовка продолжается в поле
            self.assertTrue(abs(r - 0x1e) < 6 and abs(g - 0x50) < 6 and abs(b - 0xc8) < 6, (x, r, g, b))
        self.assertEqual(self.screen.eval("getComputedStyle(document.querySelector('#slide .sblur')).display"), "none")

    def test_photo_slide_margins_blurred_copy(self):
        self.show("sp2")
        self.assertEqual(self.screen.eval("getComputedStyle(document.querySelector('#slide .sblur')).display"), "block")
        px = self.shot()
        for x in (10, 1390):
            self.assertGreater(sum(px(x, 300)), 60, x)                   # не чёрная полоса — размытый слайд

    def test_slide_covers_look_caption(self):
        """Надпись оформления (до урока она на фоне) — под слайдом, а не поверх него."""
        self.show("sp1")
        self.assertTrue(self.screen.wait("document.querySelector('#caption').textContent === '█████' && "
                                         "getComputedStyle(document.querySelector('#caption')).display === 'flex'"))
        px = self.shot()
        self.assertEqual(px(700, 300), (0, 0, 0))                         # чёрный квадрат слайда, не белая надпись

    def test_black_hides_slide_and_caption(self):
        """Чёрный экран: у учеников ни слайда, ни фона, ни надписи — вся вкладка чёрная; «Фон» — снова надпись."""
        self.show("sp1")
        self.app.lesson.command({"cmd": "black"})
        self.assertTrue(self.screen.wait("document.querySelector('#black').classList.contains('on')", 10))
        pump(300)
        px = self.shot()
        for x, y in ((10, 40), (10, 400), (300, 40), (700, 300), (1000, 400), (1390, 400), (700, 580)):
            self.assertEqual(px(x, y), (0, 0, 0), (x, y))
        self.app.lesson.command({"cmd": "background"})
        self.assertTrue(self.screen.wait("!document.querySelector('#black').classList.contains('on') && "
                                         "getComputedStyle(document.querySelector('#caption')).display === 'flex'", 10))

    def test_black_stops_animated_background(self):
        """Под чёрным экраном анимация фона не крутится (вкладку захватывают — лишняя работа); «Фон» — снова она."""
        self.look.background = "anim:cube"
        self.app.efir.save_look(self.look)
        try:
            self.app.lesson.command({"cmd": "background"})
            self.app.lesson.publish()
            self.assertTrue(self.screen.wait("document.querySelectorAll('#bgs canvas').length > 0", 10))
            self.app.lesson.command({"cmd": "black"})
            self.assertTrue(self.screen.wait("document.querySelectorAll('#bgs canvas').length === 0", 10))
            self.app.lesson.command({"cmd": "background"})
            self.assertTrue(self.screen.wait("document.querySelectorAll('#bgs canvas').length > 0", 10))
        finally:
            self.look.background = "color:#000000"
            self.app.efir.save_look(self.look)
            self.app.lesson.publish()

    def test_thin_pattern_edge_filled_with_its_color(self):
        """Край в основном белый, по нему тонкие линии узора — поле белое (не размытое и не чёрное)."""
        self.show("sp3")
        self.assertEqual(self.screen.eval("getComputedStyle(document.querySelector('#slide .sblur')).display"), "none")
        px = self.shot()
        for y in (5, 300, 555):
            self.assertEqual(px(1390, y), (255, 255, 255), y)
            self.assertEqual(px(10, y), (255, 255, 255), y)


PNG_1x1_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


if __name__ == "__main__":
    unittest.main(verbosity=2)
