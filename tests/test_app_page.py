"""Страница окна программы: связь с программой (канал app, команды, вызовы с ответом), вид, оболочка.

    .venv\\Scripts\\python.exe tests\\test_app_page.py
"""
from __future__ import annotations

import json
import unittest
import urllib.error
import urllib.request

from apphelp import AppPage, pump  # noqa: F401

import autoprint


class BridgeTest(AppPage):
    port = 18992

    def post(self, path: str, data: dict, headers: dict | None = None) -> int:
        req = urllib.request.Request(f"http://127.0.0.1:{self.app.efir.server.port}{path}",
                                     data=json.dumps(data).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_ready_and_state(self):
        self.assertTrue(self.js("window.__ready"))
        self.assertEqual(self.js("window.S.version"), autoprint.__version__)

    def test_cmd_requires_header(self):
        self.assertEqual(self.post("/app/cmd", {"cmd": "ping"}), 403)
        self.assertEqual(self.post("/app/cmd", {"cmd": "ping"}, {"X-Suflor": "1", "Origin": "http://evil.example"}), 403)
        self.assertEqual(self.post("/app/call", {"cmd": "ping"}), 403)

    def test_call_roundtrip(self):
        self.assertEqual(self.js("window.appCore.call({cmd: 'ping'})"), "pong")
        err = self.js("window.appCore.call({cmd: 'nope'}).then(() => '', (e) => e.message)")
        self.assertIn("Неизвестная команда", err)

    def test_state_follows_changes(self):
        n = self.js("window.S.lessons.length")
        self.app.new_template()
        self.assertTrue(self.wait_js(f"window.S.lessons.length === {n + 1}"))

    def test_navigate_from_python(self):
        self.app.show_view("#/settings")
        self.assertTrue(self.wait_js("location.hash === '#/settings'"))

    def test_cmd_reaches_window(self):
        self.js("window.appCore.send({cmd: 'window', op: 'regions', drag: [[0, 0, 100, 40]], holes: [], zoom: 1})")
        self.assertTrue(self.wait_py(lambda: self.app.window.regions.drag == [(0.0, 0.0, 100.0, 40.0)]))


CONTRAST_JS = """(() => {
  const lum = (hex) => { const c = hex.trim().replace('#','');
    const v = [0,2,4].map(i => parseInt(c.substr(i,2),16)/255).map(x => x <= 0.03928 ? x/12.92 : Math.pow((x+0.055)/1.055, 2.4));
    return 0.2126*v[0] + 0.7152*v[1] + 0.0722*v[2]; };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x,y)+0.05)/(Math.min(x,y)+0.05); };
  const st = getComputedStyle(document.documentElement);
  const t = (n) => st.getPropertyValue('--' + n);
  return [['text','ground'],['text','panel'],['dim','panel'],['dim','ground'],['faint','ground'],['faint','panel'],
          ['on-accent','accent'],['text','raised']].map(([a,b]) => [a + '/' + b, ratio(t(a), t(b))]);
})()"""


class ViewKitTest(AppPage):
    """Вид: шрифты, темы, контраст, масштаб, компоненты (витрина #/dev/ui)."""
    port = 18993
    route = "#/dev/ui"
    width, height = 900, 700

    def test_fonts_served(self):
        port = self.app.efir.server.port
        for name in ("Onest-cyrillic.woff2", "JetBrainsMono-latin.woff2"):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/static/fonts/{name}", timeout=5) as r:
                self.assertEqual(r.headers.get("Content-Type"), "font/woff2")
                self.assertEqual(r.read(4), b"wOF2")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/static/fonts/OFL-Onest.txt", timeout=5) as r:
            self.assertIn("Open Font License", r.read().decode("utf-8"))
        self.assertTrue(self.wait_js("[...document.fonts].some(f => /Onest/.test(f.family) && f.status === 'loaded')", 5))
        self.assertIn("Onest", self.js("getComputedStyle(document.body).fontFamily"))

    def test_theme_class_follows_state(self):
        from autoprint.ui.theme import theme
        try:
            theme.set_mode("light")
            self.app.publish_now()
            self.assertTrue(self.wait_js("document.documentElement.classList.contains('light')"))
            theme.set_mode("dark")
            self.app.publish_now()
            self.assertTrue(self.wait_js("!document.documentElement.classList.contains('light')"))
        finally:
            theme.set_mode(self.app.settings.theme)

    def test_contrast_pairs(self):
        for light in (False, True):
            self.js(f"document.documentElement.classList.toggle('light', {str(light).lower()})")
            for pair, r in self.js(CONTRAST_JS):
                self.assertGreaterEqual(r, 4.5, f"{'светлая' if light else 'тёмная'}: {pair} = {r:.2f}")
        self.js(f"document.documentElement.classList.toggle('light', {str(not self.js('window.S.dark')).lower()})")

    def test_ctrl_wheel_zoom(self):
        self.app.settings.page_zoom = 100
        self.app.publish_now()
        self.assertTrue(self.wait_js("window.S.zoom === 100"))
        self.js("window.dispatchEvent(new WheelEvent('wheel', {deltaY: -100, ctrlKey: true, cancelable: true}))")
        self.assertTrue(self.wait_py(lambda: self.app.settings.page_zoom == 110))
        self.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: '0', ctrlKey: true, bubbles: true}))")
        self.assertTrue(self.wait_py(lambda: self.app.settings.page_zoom == 100))

    def test_zoom200_no_hscroll(self):
        try:
            self.app.settings.page_zoom = 200
            self.app.publish_now()
            self.assertTrue(self.wait_js("document.documentElement.style.zoom === '2'"))
            self.assertTrue(self.wait_js("document.body.dataset.view === 'dev'"))
            self.assertTrue(self.js("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"),
                            self.js("document.documentElement.scrollWidth + ' > ' + document.documentElement.clientWidth"))
        finally:
            self.app.settings.page_zoom = 100
            self.app.publish_now()

    def test_sheet_esc_returns_null(self):
        self.js("window.__ans = 'wait'; window.appUI.ask('Удалить?').then((r) => { window.__ans = r; }); true")
        self.assertTrue(self.wait_js("!!document.querySelector('.sheet')"))
        self.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
        self.assertTrue(self.wait_js("window.__ans === false"))
        self.assertFalse(self.js("!!document.querySelector('.sheet')"))

    def test_icon_buttons_have_labels(self):
        """У кнопок-значков есть подпись для экранного диктора и подсказка."""
        self.assertTrue(self.wait_js("document.querySelectorAll('.btn.icon').length > 0"))
        bad = self.js("[...document.querySelectorAll('.btn.icon')].filter(b => !b.getAttribute('aria-label')).length")
        self.assertEqual(bad, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
