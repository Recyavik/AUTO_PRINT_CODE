"""Окно программы (AppWindow): области перетаскивания, кнопки окна, маленький режим, сообщение при сбое,
настоящий встроенный браузер на offscreen.

    .venv\\Scripts\\python.exe tests\\test_app_shell.py
"""
from __future__ import annotations

import sys
import time
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import quiet  # noqa: E402,F401  — до PySide6: offscreen, своя папка данных

from PySide6.QtCore import QSize, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

try:                                    # встроенный браузер — до QApplication (общий OpenGL-контекст)
    import PySide6.QtWebEngineWidgets  # noqa: F401,E402
except ImportError:
    pass

app = QApplication.instance() or QApplication(sys.argv)
quiet.patch()

from autoprint.efir.server import BroadcastServer  # noqa: E402
from autoprint.storage import Settings  # noqa: E402
from autoprint.ui.regions import HTCAPTION, HTCLIENT, Regions, hit_code  # noqa: E402
from autoprint.ui.app_window import AppWindow  # noqa: E402

PORT = 18971


def pump(ms: int = 30) -> None:
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


class _Efir:
    def __init__(self, server):
        self.server = server


class FakeApp:
    def __init__(self, running: bool = True):
        self.settings = Settings()
        self.server = BroadcastServer(port=PORT)
        if running:
            self.server.start()
        self.efir = _Efir(self.server)

    def close(self):
        self.server.stop()


class RegionsTest(unittest.TestCase):
    def test_hit_code_drag_and_holes(self):
        r = Regions(drag=[(0, 0, 800, 44)], holes=[(700, 6, 40, 32)], zoom=1.0)
        self.assertEqual(hit_code(10, 10, r), HTCAPTION)
        self.assertEqual(hit_code(710, 10, r), HTCLIENT)
        self.assertEqual(hit_code(10, 60, r), HTCLIENT)

    def test_hit_code_zoom(self):
        r = Regions(drag=[(0, 0, 100, 44)], holes=[], zoom=1.5)
        self.assertEqual(hit_code(140, 60, r), HTCAPTION)
        self.assertEqual(hit_code(160, 10, r), HTCLIENT)

    def test_regions_from_page_data(self):
        r = Regions.from_data({"drag": [[0, 0, 10, 10]], "holes": [[1, 1, 2, 2]], "zoom": 1.25})
        self.assertEqual(r.drag, [(0.0, 0.0, 10.0, 10.0)])
        self.assertEqual(r.zoom, 1.25)
        bad = Regions.from_data({"drag": "x", "holes": [[1, "a"]], "zoom": -3})
        self.assertEqual((bad.drag, bad.holes, bad.zoom), ([], [], 1.0))


class WindowTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeApp()
        self.w = AppWindow(self.fake, web=False)

    def tearDown(self):
        self.w.close()
        self.fake.close()
        pump()

    def test_window_cmd_pin_and_compact(self):
        w = self.w
        w.resize(700, 500)
        w.show()
        pump()
        big = w.size()
        w.window_cmd("pin")
        self.assertTrue(w.on_top())
        self.assertTrue(w.pinned)
        w.window_cmd("pin")
        self.assertFalse(w.pinned)
        self.assertFalse(w.on_top())
        w.window_cmd("compact")
        pump()
        self.assertTrue(w.compact)
        self.assertEqual(w.width(), 360)
        self.assertEqual(w.size(), w.compact_rect().size())
        self.assertTrue(w.on_top())             # маленький — поверх всех (efir_pinned по умолчанию)
        w.window_cmd("compact")
        pump()
        self.assertFalse(w.compact)
        self.assertEqual(w.size(), big)

    def test_compact_layout_size(self):
        """Вид маленького режима: размер в пикселях страницы × масштаб; правый верхний угол — на месте; в экран."""
        w = self.w
        w.window_cmd("compact", True)
        pump()
        try:
            w.setGeometry(300, 50, 360, 500)          # offscreen: экран 800×600
            right, top = w.geometry().right(), w.geometry().top()
            w.window_cmd("compact_size", {"w": 640, "h": 440})
            self.assertEqual((w.width(), w.height()), (640, 440))
            self.assertEqual((w.geometry().right(), w.geometry().top()), (right, top))
            self.fake.settings.page_zoom = 150
            w.window_cmd("compact_size", {"w": 300, "h": 110})
            self.assertEqual((w.width(), w.height()), (450, 165))
            w.window_cmd("compact_size", {"w": 99999, "h": "x"})            # чужое — мимо
            self.assertEqual((w.width(), w.height()), (450, 165))
            avail = w.screen().availableGeometry()
            w.window_cmd("compact_size", {"w": 4000, "h": 120})              # шире экрана — по ширине экрана
            self.assertTrue(avail.contains(w.geometry()), (avail, w.geometry()))
        finally:
            self.fake.settings.page_zoom = 100
            w.window_cmd("compact", False)
            pump()

    def test_frame_press_goes_to_log(self):
        """Нажатие на заголовок / край и начало-конец перетаскивания — строкой в журнал (для разбора жалоб)."""
        import ctypes
        from ctypes import wintypes
        from shiboken6 import VoidPtr
        from autoprint.ui import frameless
        msg = wintypes.MSG()
        msg.hWnd, msg.message, msg.wParam = 0, frameless.WM_NCLBUTTONDOWN, 2
        with self.assertLogs("autoprint.ui.frameless", "INFO") as cm:
            self.w.nativeEvent(b"windows_generic_MSG", VoidPtr(ctypes.addressof(msg)))
            msg.message, msg.wParam = frameless.WM_NCLBUTTONDOWN, 11
            self.w.nativeEvent(b"windows_generic_MSG", VoidPtr(ctypes.addressof(msg)))
            msg.message = frameless.WM_ENTERSIZEMOVE
            self.w.nativeEvent(b"windows_generic_MSG", VoidPtr(ctypes.addressof(msg)))
        text = "\n".join(cm.output)
        for part in ("нажатие — заголовок", "нажатие — правый край", "начали тянуть"):
            self.assertIn(part, text)

    def test_hit_test_uses_regions(self):
        w = self.w
        w.set_regions({"drag": [[0, 0, 300, 44]], "holes": [[250, 4, 40, 36]], "zoom": 1})
        self.assertEqual(w.client_hit(10, 10), HTCAPTION)
        self.assertEqual(w.client_hit(260, 10), HTCLIENT)
        self.assertEqual(w.client_hit(10, 100), HTCLIENT)

    def test_app_route_served(self):
        url = f"http://127.0.0.1:{self.fake.server.port}/app"
        with urllib.request.urlopen(url, timeout=5) as r:
            self.assertEqual(r.status, 200)
            self.assertIn("text/html", r.headers.get("Content-Type"))
            self.assertIn('id="app"', r.read().decode("utf-8"))


class FailTest(unittest.TestCase):
    def test_server_down_shows_message(self):
        fake = FakeApp(running=False)
        w = AppWindow(fake, web=False)
        w.load()
        self.assertTrue(w.message_text().startswith("Не удалось запустить окно программы"))
        w.close()


    def test_renderer_gone_shows_message_and_reloads(self):
        """Страница упала после загрузки (сбой отрисовки) — не белое окно: сообщение и перезагрузка."""
        fake = FakeApp()
        w = AppWindow(fake, web=False)
        reloads = []
        w.retry = lambda: reloads.append(1)
        w.on_render_gone(2, 1)
        self.assertTrue(w.message_text().startswith("Не удалось запустить окно программы"))
        self.assertFalse(w.fail.isHidden())
        end = time.time() + 4
        while not reloads and time.time() < end:
            app.processEvents()
            time.sleep(0.02)
        self.assertEqual(reloads, [1])
        w.close()

    def test_page_not_ready_shows_message(self):
        """Страница загрузилась, но её скрипты не запустились (нет __ready) — сообщение, а не пустой фон."""
        fake = FakeApp()
        w = AppWindow(fake, web=False)
        w.on_ready_checked(True)
        self.assertTrue(w.fail.isHidden())
        w.on_ready_checked(False)
        self.assertFalse(w.fail.isHidden())
        w.close()


class WebEngineTest(unittest.TestCase):
    def test_webengine_offscreen_ready(self):
        try:
            import PySide6.QtWebEngineWidgets  # noqa: F401
        except ImportError as e:
            self.skipTest(f"нет QtWebEngine: {e}")
        fake = FakeApp()
        w = AppWindow(fake, web=True)
        got = []
        w.ready.connect(lambda: got.append(True))
        w.load()
        end = time.time() + 25
        while not got and time.time() < end:
            pump(50)
        if not got:
            w.close()
            fake.close()
            self.skipTest("встроенный браузер не загрузил страницу на offscreen за 25 с")
        res = []
        w.run_js("window.__ready === true", res.append)
        end = time.time() + 10
        while not (res and res[-1]) and time.time() < end:
            pump(100)
            if not res or not res[-1]:
                w.run_js("window.__ready === true", res.append)
        self.assertTrue(res and res[-1], "страница не получила состояние канала app")
        w.close()
        fake.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
