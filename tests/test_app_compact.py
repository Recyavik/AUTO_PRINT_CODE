"""Маленький режим: то же окно поверх всех, табло урока или вебинара, раскладки по размеру окна, «Большой режим».

    .venv\\Scripts\\python.exe tests\\test_app_compact.py
"""
from __future__ import annotations

import unittest

from apphelp import AppPage, code, note, pump, stage  # noqa: F401

from autoprint.storage import Template


def lessons() -> list[Template]:
    return [Template("Циклы", [stage("Начало", 5, id="c1"), note("Привет", id="cn"), code("print(1)", id="cc"),
                               stage("Перерыв", 5, id="c2", stage_kind="break"), stage("Практика", 20, id="c3"),
                               stage("Итоги", 5, id="c4")], id="C"),
            Template("Длинный", [stage(f"Этап номер {i} с длинным названием", 5, id=f"m{i}") for i in range(12)], id="M")]


class CompactTest(AppPage):
    port = 18970
    templates = staticmethod(lessons)
    route = "#/lesson/C"

    def setUp(self):
        if self.app.efir.live_webinar() is not None:
            self.stop_live()
        self.app.printer.set_focus("C")
        self.app.set_compact(True)
        self.app.publish_now()
        self.assertTrue(self.wait_js("document.body.classList.contains('compact') && !!document.querySelector('#compact')"))

    def tearDown(self):
        self.edge.call("Emulation.clearDeviceMetricsOverride")
        self.js("window.dispatchEvent(new Event('resize'))")
        if self.app.efir.live_webinar() is not None:
            self.stop_live()
        if self.app.settings.page_zoom != 100:
            self.app.settings.page_zoom = 100
            self.app.publish_now()
        self.app.set_compact(False)
        self.app.publish_now()
        self.wait_js("!document.body.classList.contains('compact')")
        super().tearDown()

    def size(self, w, h):
        self.edge.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": False})
        self.js("window.dispatchEvent(new Event('resize'))")

    def board(self) -> str:
        return self.js("document.querySelector('#compact').textContent")

    def test_compact_sizes(self):
        for w, h, want in ((300, 500, "tall"), (200, 120, "tiny"), (900, 200, "strip"), (700, 400, "side"), (250, 400, "tiny")):
            self.size(w, h)
            self.assertTrue(self.wait_js(f"document.body.dataset.size === {want!r}"), (w, h, want, self.js("document.body.dataset.size")))

    def test_auto_zoom_follows_window_but_not_in_compact(self):
        """«Масштаб под размер окна»: шире окно — крупнее (90…150 %, после того как окно отпустили); Ctrl+= — снова
        вручную. В маленьком режиме — обычный масштаб (раскладки табло считают пиксели страницы)."""
        self.app.set_compact(False)
        self.app.publish_now()
        self.assertTrue(self.wait_js("!document.body.classList.contains('compact')"))
        zoom = "parseFloat(document.documentElement.style.zoom || '1')"
        try:
            self.app.settings.page_zoom_auto = True
            self.app.publish_now()
            self.size(1500, 860)
            self.assertTrue(self.wait_js(f"{zoom} === 1"), self.js(zoom))
            self.size(2100, 900)
            self.assertTrue(self.wait_js(f"{zoom} === 1.4"), self.js(zoom))
            self.size(900, 700)
            self.assertTrue(self.wait_js(f"{zoom} === 0.9"), self.js(zoom))
            self.size(2100, 900)
            self.assertTrue(self.wait_js(f"{zoom} === 1.4"))
            self.app.set_compact(True)                                   # маленький режим — свой, обычный масштаб
            self.app.publish_now()
            self.assertTrue(self.wait_js(f"document.body.classList.contains('compact') && {zoom} === 1"), self.js(zoom))
            self.app.set_compact(False)
            self.app.publish_now()
            self.assertTrue(self.wait_js(f"{zoom} === 1.4"))
            self.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: '=', ctrlKey: true, bubbles: true}))")
            self.assertTrue(self.wait_py(lambda: not self.app.settings.page_zoom_auto))   # Ctrl+= — снова вручную
            self.assertTrue(self.wait_py(lambda: self.app.settings.page_zoom == 150),     # от 140 % — на шаг крупнее
                            (self.app.settings.page_zoom, self.js("S.zoom"), self.js(zoom), self.edge.errors()[-3:]))
        finally:
            self.app.settings.page_zoom_auto = False
            self.app.settings.page_zoom = 100
            self.app.publish_now()
            self.app.set_compact(True)
            self.app.publish_now()

    def test_layout_menu_resizes_window(self):
        """Вид маленького режима — выбором, а не только растягиванием: табло, со списком, полоса, только время."""
        self.size(360, 600)
        self.assertTrue(self.wait_js("document.body.dataset.size === 'tall'"))
        self.click("#compactLayout")
        self.assertTrue(self.wait_js("!!document.querySelector('.pop')"))
        items = self.js("[...document.querySelectorAll('.pop .mi .ml')].map(e => e.textContent)")
        self.assertEqual(items, ["Табло", "Табло и этапы", "Полоса", "Только время"])
        self.assertTrue(self.js("[...document.querySelectorAll('.pop .mi')][0].getAttribute('aria-checked') === 'true'"))
        self.js("[...document.querySelectorAll('.pop .mi')].find(b => b.textContent.includes('Полоса')).click()")
        # размер окна считает окно (Electron): правый верхний угол на месте, в пределах экрана — window/geometry.js
        want = {"op": "compact_size", "w": 980, "h": 160, "k": 1.0}
        self.assertTrue(self.wait_py(lambda: want in self.app.window.sent), self.app.window.sent[-3:])

    def test_strip_has_screen_icons(self):
        """Полоса урока — со значками экрана учеников (без подписей, с подсказками), как в большом окне."""
        self.size(980, 160)
        self.assertTrue(self.wait_js("document.body.dataset.size === 'strip'"))
        vis = self.js("(() => { const g = document.querySelector('#compact .cscr'); const r = g.getBoundingClientRect();"
                      " return [getComputedStyle(g).display !== 'none', r.bottom <= innerHeight + 1,"
                      " [...g.querySelectorAll('button')].map(b => getComputedStyle(b.querySelector('span')).display),"
                      " [...g.querySelectorAll('button')].map(b => b.dataset.tip)]; })()")
        self.assertTrue(vis[0], vis)
        self.assertTrue(vis[1], vis)
        self.assertEqual(vis[2], ["none"] * 5)
        self.assertEqual(vis[3], ["Фон", "Чёрный экран", "Зарядка", "Перерыв", "Слайд"])

    def test_size_counts_zoom(self):
        """Раскладка — по размеру в пикселях страницы: при 150 % окно 720×420 — это 480×280, «сбоку» не влезает."""
        self.size(720, 420)
        self.assertTrue(self.wait_js("document.body.dataset.size === 'side'"))
        self.app.settings.page_zoom = 150
        self.app.publish_now()
        self.js("window.dispatchEvent(new Event('resize'))")
        self.assertTrue(self.wait_js("document.body.dataset.size === 'tall'"), self.js("document.body.dataset.size"))

    def test_nothing_hidden_when_low(self):
        """Низкое окно при 150 %: табло прокручивается — «Следующий этап» достижим, а не обрезан."""
        self.go_live(1, tid="M")
        self.app.settings.page_zoom = 150
        self.app.publish_now()
        self.size(720, 420)
        self.assertTrue(self.wait_js("!!document.querySelector('#compact .cnext') && document.documentElement.style.zoom === '1.5'"))
        pump(300)
        over, oy = self.js("(() => { const c = document.querySelector('#compact');"
                           " return [c.scrollHeight > c.clientHeight + 1, getComputedStyle(c).overflowY]; })()")
        if over:                                            # не влезло — человек должен мочь прокрутить
            self.assertIn(oy, ("auto", "scroll"))

    def test_strip_cells_fit_whole(self):
        """Широкий и низкий: только целые ячейки повестки, остальные — кнопкой «N ›»."""
        self.go_live(1, tid="M")
        self.size(1100, 150)
        self.assertTrue(self.wait_js("document.body.dataset.size === 'strip' && document.querySelectorAll('#compact .ca-cell').length > 0"))
        pump(300)
        r = self.js("(() => { const a = document.querySelector('#compact .cagenda').getBoundingClientRect();"
                    " return [...document.querySelectorAll('#compact .cagenda > *')].map(c => [c.getBoundingClientRect().right, a.right]); })()")
        self.assertTrue(all(right <= edge + 1 for right, edge in r), r)
        n = self.js("document.querySelectorAll('#compact .ca-cell').length")
        total = len(self.app.efir.segments())
        if n < total:
            self.assertTrue(self.js("[...document.querySelectorAll('#compact .ca-more')].some(b => b.textContent.endsWith('›'))"))

    def test_strip_default_size_keeps_two_stages(self):
        """«Полоса» своего размера (980 × 160): пять значков экрана учеников (два ряда) не отнимают ячейку повестки —
        видно не меньше двух этапов, как до «Чёрного экрана»; значки целиком в окне."""
        self.go_live(1, tid="M")
        self.size(980, 160)
        self.assertTrue(self.wait_js("document.body.dataset.size === 'strip' && document.querySelectorAll('#compact .ca-cell').length > 0"))
        pump(300)
        self.assertGreaterEqual(self.js("document.querySelectorAll('#compact .ca-cell').length"), 2)
        r = self.js("(() => { const b = [...document.querySelectorAll('#compact .cscr button')].map(e => e.getBoundingClientRect());"
                    " return [b.every(x => x.bottom <= innerHeight + 1 && x.right <= innerWidth + 1), new Set(b.map(x => Math.round(x.top))).size]; })()")
        self.assertEqual(r, [True, 2])

    def test_side_layout_typing_bar_visible(self):
        """«Табло и этапы» (660 × 440): пять кнопок экрана учеников и полоса набора кода — всё видно без прокрутки."""
        p = self.app.printer
        snap = p.snapshot
        p.snapshot = lambda: {**snap(), "state": "paused", "block": "cc", "progress": .5}
        self.addCleanup(lambda: setattr(p, "snapshot", snap))
        self.go_live(1, tid="C")
        self.size(660, 440)
        self.app.publish_now()
        self.assertTrue(self.wait_js("document.body.dataset.size === 'side' && !document.querySelector('#compact .ctype').hidden", 6))
        pump(300)
        r = self.js("(() => { const t = document.querySelector('#compact .ctype').getBoundingClientRect();"
                    " const c = document.querySelector('#compact'); return [t.bottom <= innerHeight + 1, c.scrollHeight <= c.clientHeight + 1]; })()")
        self.assertEqual(r, [True, True])

    def test_compact_widths(self):
        self.go_live(2, tid="C")
        for zoom in (100, 200):
            self.app.settings.page_zoom = zoom
            self.app.publish_now()
            self.size(360, 600)
            pump(300)
            self.assertTrue(self.wait_js(f"document.documentElement.style.zoom === '{zoom / 100:g}' || {zoom} === 100"))
            over = self.js("(() => { const c = document.querySelector('#compact'); return [c.scrollWidth, c.clientWidth,"
                           " document.documentElement.scrollWidth, innerWidth]; })()")
            self.assertLessEqual(over[0], over[1] + 1, (zoom, over))                 # внутри табло — без прокрутки вбок

    def test_compact_board_texts(self):
        self.size(360, 600)
        self.assertTrue(self.wait_js("document.querySelector('#compact').textContent.includes('Нет эфира')"))
        self.go_live(2, tid="C")
        self.assertTrue(self.wait_js("document.querySelector('#compact').textContent.includes('осталось')", 6))
        text = self.board()
        self.assertIn("этап 1 из 4", text)
        self.assertIn("Начало", text)
        self.assertIn("Дальше · ", text)
        self.assertIn("Перерыв", text)
        self.assertRegex(self.js("document.querySelector('#compact .cb-time').textContent"), r"^[23]:\d\d$")

    def test_compact_waiting_and_over(self):
        self.size(360, 600)
        self.go_live(-10, tid="C")
        self.assertTrue(self.wait_js("document.querySelector('#compact').textContent.includes('До начала')", 6))
        self.stop_live()
        self.go_live(40, tid="C")
        self.assertTrue(self.wait_js("document.querySelector('#compact').textContent.includes('Эфир завершён')", 6))

    def test_compact_red_last_minute(self):
        self.size(360, 600)
        self.go_live(4.5, tid="C")                     # «Начало» (5 мин) кончается через 30 с
        self.assertTrue(self.wait_js("document.querySelector('#compact .cb-time').classList.contains('red')", 6))

    def test_compact_screen_icons_and_next(self):
        self.size(360, 600)
        self.go_live(2, tid="C")
        self.assertTrue(self.wait_js("document.querySelectorAll('#compact .cscr button').length === 5", 6))
        labels = self.js("[...document.querySelectorAll('#compact .cscr button')].map(b => b.textContent.trim())")
        self.assertEqual(labels, ["Фон", "Чёрный", "Зарядка", "Перерыв", "Слайд"])
        # 2 × 2 и «Слайд» во всю ширину — ни одна кнопка не висит одна в ряду с пустым местом
        rows = self.js("(() => { const b = [...document.querySelectorAll('#compact .cscr button')].map(e => e.getBoundingClientRect());"
                       " return [b[0].top === b[1].top, b[2].top === b[3].top, Math.round(b[4].width) >= Math.round(b[0].width * 2)]; })()")
        self.assertEqual(rows, [True, True, True])
        black = "[...document.querySelectorAll('#compact .cscr button')][1]"
        self.js(black + ".click()")
        self.assertTrue(self.wait_py(lambda: self.app.efir.mode == "black"))
        self.app.publish_now()
        self.assertTrue(self.wait_js(black + ".getAttribute('aria-pressed') === 'true'", 6))
        self.js(black + ".click()")                    # ещё раз — снова фон
        self.assertTrue(self.wait_py(lambda: self.app.efir.mode == "idle"))
        before = self.app.efir.store.live.anchor
        self.click("#compact .cnext")                   # «Следующий этап» — перерыв начинается сейчас
        self.assertTrue(self.wait_py(lambda: self.app.efir.store.live.anchor != before))

    def test_compact_planned_break_full_minutes(self):
        """Маленький режим: этап «Перерыв» (5 мин) идёт уже минуту — «По плану · 5 мин» даёт все 5 минут с этой
        минуты, а не остаток по расписанию."""
        self.app.efir.clients = 1
        self.size(360, 600)
        self.go_live(6, tid="C")                        # этап «Перерыв» 5–10 мин идёт с 5-й минуты
        self.assertTrue(self.wait_js("document.querySelectorAll('#compact .cscr button').length === 5", 6))
        try:
            self.js("[...document.querySelectorAll('#compact .cscr button')][3].click()")
            self.assertTrue(self.wait_js("[...document.querySelectorAll('.pop .mi')].some(b => b.textContent.includes('По плану · 5 мин'))"))
            self.js("[...document.querySelectorAll('.pop .mi')].find(b => b.textContent.includes('По плану')).click()")
            self.assertTrue(self.wait_py(lambda: self.app.efir.mode == "break"))
            self.assertAlmostEqual(self.app.efir.brk_total, 300, delta=2)
        finally:
            self.app.efir.show_background()

    def test_compact_exercise_one_click(self):
        """«Зарядка» в маленьком режиме — как наверху: щелчок сразу включает видео (по очереди), правой кнопкой — меню."""
        import tempfile
        from pathlib import Path
        from autoprint.efir.model import Exercise, Look
        d = Path(tempfile.mkdtemp())
        (d / "e.mp4").write_bytes(b"x")
        look = Look(title="З", exercises=[Exercise("Глаза", str(d / "e.mp4")), Exercise("Шея", str(d / "e.mp4"))])
        self.app.efir.save_look(look)
        self.store.get("C").look = look.id
        self.app.efir.clients = 1
        self.app.settings.exercise_pick = "next"
        self.size(360, 600)
        self.go_live(2, tid="C")
        self.assertTrue(self.wait_js("document.querySelectorAll('#compact .cscr button').length === 5", 6))
        ex = "[...document.querySelectorAll('#compact .cscr button')][2]"
        try:
            self.js(ex + ".click()")
            self.assertTrue(self.wait_py(lambda: self.app.efir.mode == "exercise"))
            self.assertFalse(self.js("!!document.querySelector('.pop')"))
        finally:
            self.app.efir.show_background()
            self.app.publish_now()
        self.assertTrue(self.wait_js(ex + ".getAttribute('aria-pressed') === 'false'", 6))
        self.js(ex + ".dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, cancelable: true}))")
        self.assertTrue(self.wait_js("[...document.querySelectorAll('.pop .mi')].some(b => b.textContent.includes('Шея'))"))
        self.js("window.appUI && window.appUI.closePop && window.appUI.closePop()")

    def test_compact_drag_regions(self):
        self.size(360, 600)
        self.assertTrue(self.wait_js("!!document.querySelector('#compact[data-drag]')"))
        st = ("(s) => { const e = document.querySelector(s); const c = e && getComputedStyle(e);"
              " return c ? (c.getPropertyValue('-webkit-app-region') || c.getPropertyValue('app-region') || '') : null; }")
        self.assertEqual(self.js("(" + st + ")('#compact')"), "drag")             # табло тянет окно
        self.assertEqual(self.js("(" + st + ")('#compact button')"), "no-drag")   # кнопки на нём нажимаются

    def test_expand_returns_big(self):
        self.click("#compactExpand")
        self.assertTrue(self.wait_py(lambda: not self.app.window.compact))
        self.assertTrue(self.wait_js("!document.body.classList.contains('compact')"))

    def test_tray_compact_item(self):
        self.app.set_compact(False)
        tray = self.app.tray
        act = next(a for a in tray.menu.actions() if a.text() == "Маленький режим")
        act.trigger()
        self.assertTrue(self.app.window.compact)
        self.assertEqual(act.text(), "Большой режим")
        act.trigger()
        self.assertFalse(self.app.window.compact)
        self.assertEqual(act.text(), "Маленький режим")


class WebinarBoardTest(AppPage):
    """Вебинар по расписанию (не урок) — то же табло: сейчас, повестка."""
    port = 18969
    templates = staticmethod(lessons)
    route = "#/lessons"

    def test_webinar_board(self):
        from autoprint.efir.model import Activity, Webinar
        ef = self.app.efir
        w = ef.store.add([Webinar(title="Пара 1Т", schedule=[Activity("Лекция", 30), Activity("Перерыв", 10, kind="break")])])[0]
        ef.launch(w.id, "")
        self.app.set_compact(True)
        self.app.publish_now()
        try:
            self.assertTrue(self.wait_js("!!document.querySelector('#compact') && document.querySelector('#compact').textContent.includes('Лекция')", 6))
            self.assertIn("Дальше · ", self.js("document.querySelector('#compact').textContent"))
        finally:
            ef.stop_live()
            self.app.set_compact(False)
            self.app.publish_now()


if __name__ == "__main__":
    unittest.main(verbosity=2)
