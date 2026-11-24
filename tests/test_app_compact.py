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
                               stage("Итоги", 5, id="c4")], id="C")]


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
        self.assertTrue(self.wait_js("document.querySelectorAll('#compact .cscr button').length === 4", 6))
        labels = self.js("[...document.querySelectorAll('#compact .cscr button')].map(b => b.textContent.trim())")
        self.assertEqual(labels, ["Фон", "Зарядка", "Перерыв", "Слайд"])
        before = self.app.efir.store.live.anchor
        self.click("#compact .cnext")                   # «Следующий этап» — перерыв начинается сейчас
        self.assertTrue(self.wait_py(lambda: self.app.efir.store.live.anchor != before))

    def test_compact_drag_regions(self):
        self.size(360, 600)
        self.assertTrue(self.wait_js("!!document.querySelector('#compact[data-drag]')"))
        r = self.js("(() => { const b = document.querySelector('#compact').getBoundingClientRect(); return [b.left, b.top, b.width, b.height]; })()")

        def covered():
            for x, y, w, h in self.app.window.regions.drag:
                if x <= r[0] + 1 and y <= r[1] + 1 and x + w >= r[0] + r[2] - 1 and y + h >= r[1] + r[3] - 1:
                    return True
            return False
        self.assertTrue(self.wait_py(covered, 6), self.app.window.regions.drag)

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
        ef.show_timer = lambda: None
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
