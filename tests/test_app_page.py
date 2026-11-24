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


if __name__ == "__main__":
    unittest.main(verbosity=2)
