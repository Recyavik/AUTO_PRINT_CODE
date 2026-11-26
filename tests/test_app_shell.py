"""Окно программы (ShellWindow → Electron, папка window/): команды и зеркало состояния без процесса; настоящее окно
Electron — невидимо (--autoprint-hidden=1): загрузка, где тянуть окно, маленький режим, PDF, ссылки наружу, сбой.

    .venv\\Scripts\\python.exe tests\\test_app_shell.py

Окно Electron нужно собрать один раз: npm install в папке window (без него эти проверки пропускаются).
"""
from __future__ import annotations

import base64
import ctypes
import json
import struct
import sys
import tempfile
import time
import unittest
import urllib.request
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import quiet  # noqa: E402,F401  — до PySide6: offscreen, своя папка данных, окно Electron не показывается

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
quiet.patch()

from autoprint.efir.server import BroadcastServer  # noqa: E402
from autoprint.storage import Settings  # noqa: E402
from autoprint.ui import shell_window as SW  # noqa: E402
from autoprint.ui.shell_window import CloseEvent, ShellWindow, parse_place, qt_filters  # noqa: E402

PORT = 18971
user32 = ctypes.windll.user32
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = (wintypes.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)
user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
user32.IsWindowVisible.argtypes = (wintypes.HWND,)
HTCLIENT, HTCAPTION, HTLEFT = 1, 2, 10


def pump(ms: int = 30) -> None:
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.004)


def wait(cond, s: float = 20) -> bool:
    end = time.time() + s
    while time.time() < end:
        if cond():
            return True
        pump(20)
    return bool(cond())


class _Efir:
    def __init__(self, server):
        self.server = server


class FakeApp:
    def __init__(self, running: bool = True, port: int = PORT):
        self.settings = Settings()
        self.server = BroadcastServer(port=port)
        if running:
            self.server.start()
        self.efir = _Efir(self.server)
        self.drops: list[list[str]] = []
        self.notes: list[str] = []

    def drop(self, paths):
        self.drops.append(paths)

    def notify(self, text, **_kw):
        self.notes.append(text)

    def close(self):
        self.server.stop()


def qt_blob(left, top, w, h, maximized=False) -> str:
    """Запись места окна, как её сохранял Qt 6 (saveGeometry) до 1.2."""
    r = (left, top, left + w - 1, top + h - 1)
    raw = struct.pack(">IHH4i4iiBBi4i", 0x1D9D0CB, 3, 0, *r, *r, 0, int(maximized), 0, 1920, *r)
    return base64.b64encode(raw).decode()


class PlacesTest(unittest.TestCase):
    def test_json_places(self):
        self.assertEqual(parse_place('{"x":10,"y":20,"w":900,"h":700,"max":true}', True),
                         {"x": 10, "y": 20, "w": 900, "h": 700, "max": True})
        self.assertEqual(parse_place('{"x":10,"y":20,"w":360,"h":600}', False), {"x": 10, "y": 20, "w": 360, "h": 600})
        for bad in ("", "{}", '{"x":1,"y":2,"w":0,"h":5}', "мусор", '[1,2]'):
            self.assertIsNone(parse_place(bad, True), bad)

    def test_qt_places_from_before_12(self):
        """Окно откроется там же, где было окно Qt (запись saveGeometry), и развёрнутым, если было."""
        self.assertEqual(parse_place(qt_blob(403, 235, 1476, 844), True),
                         {"x": 403, "y": 235, "w": 1476, "h": 844, "max": False})
        self.assertTrue(parse_place(qt_blob(0, 0, 1280, 860, maximized=True), True)["max"])
        from PySide6.QtWidgets import QWidget
        w = QWidget()                          # запись настоящего Qt этой версии
        w.setGeometry(120, 90, 900, 640)
        real = bytes(w.saveGeometry().toBase64()).decode()
        self.assertEqual(parse_place(real, True), {"x": 120, "y": 90, "w": 900, "h": 640, "max": False})

    def test_qt_file_filters(self):
        self.assertEqual(qt_filters("PDF (*.pdf);;Все файлы (*.*)"),
                         [{"name": "PDF", "extensions": ["pdf"]}, {"name": "Все файлы", "extensions": ["*"]}])
        self.assertEqual(qt_filters("Картинки (*.png *.jpg *.jpeg)"),
                         [{"name": "Картинки", "extensions": ["png", "jpg", "jpeg"]}])
        self.assertEqual(qt_filters(""), [])


class ProtocolTest(unittest.TestCase):
    """Без процесса окна: что уходит окну и как меняется зеркало его состояния."""

    def setUp(self):
        self.fake = FakeApp(running=False)
        self.w = ShellWindow(self.fake, launch=False)

    def ops(self):
        return [m["op"] for m in self.w.sent]

    def test_pin_and_compact(self):
        w = self.w
        w.window_cmd("pin")
        self.assertTrue(w.pinned and w.on_top())
        self.assertEqual(w.sent[-1], {"op": "top", "on": True})
        w.window_cmd("pin")
        self.assertFalse(w.pinned or w.on_top())
        w.window_cmd("compact")
        self.assertTrue(w.compact and self.fake.settings.compact)
        self.assertIn({"op": "compact", "on": True}, w.sent)
        self.assertTrue(w.on_top())             # маленький — поверх всех (efir_pinned по умолчанию)
        w.window_cmd("compact")
        self.assertFalse(w.compact)
        self.assertEqual(w.sent[-2:], [{"op": "compact", "on": False}, {"op": "top", "on": False}])

    def test_compact_size_checked_and_scaled(self):
        w = self.w
        w.window_cmd("compact_size", {"w": 640, "h": 440})       # не в маленьком режиме — мимо
        self.assertNotIn("compact_size", self.ops())
        w.set_compact(True)
        self.fake.settings.page_zoom = 150
        w.window_cmd("compact_size", {"w": 300, "h": 110})
        self.assertEqual(w.sent[-1], {"op": "compact_size", "w": 300, "h": 110, "k": 1.5})
        n = len(w.sent)
        for bad in ({"w": 99999, "h": 10}, {"w": "x", "h": 1}, "640x440", None):
            w.window_cmd("compact_size", bad)
        self.assertEqual(len(w.sent), n)

    def test_state_from_window(self):
        w = self.w
        seen = []
        w.state_changed.connect(lambda: seen.append(1))
        w.on_message({"ev": "state", "visible": True, "minimized": False, "maximized": True, "focused": True})
        self.assertTrue(w.isVisible() and w.isMaximized() and w.isActiveWindow())
        self.assertEqual(len(seen), 1)
        w.on_message({"ev": "state", "visible": True, "minimized": False, "maximized": True, "focused": True})
        self.assertEqual(len(seen), 1)          # то же самое — без лишних обновлений страницы
        w.on_message({"ev": "state", "visible": True, "minimized": True, "maximized": True, "focused": False})
        self.assertTrue(w.isMinimized())
        self.assertFalse(w.isActiveWindow())

    def test_show_hide_minimize_mirror(self):
        w = self.w
        w.show()
        self.assertTrue(w.isVisible())
        w.showMinimized()
        self.assertTrue(w.isMinimized())
        w.showMaximized()
        self.assertTrue(w.isMaximized() and not w.isMinimized())
        w.showNormal()
        self.assertFalse(w.isMaximized())
        w.hide()
        self.assertFalse(w.isVisible())
        self.assertEqual(self.ops()[-5:], ["show", "min", "max", "restore", "hide"])

    def test_places_from_window_go_to_settings_format(self):
        w = self.w
        got = []
        w.geometry_changed.connect(lambda: got.append(1))
        w.on_message({"ev": "geometry", "big": {"x": 1, "y": 2, "w": 1000, "h": 700, "max": False},
                      "small": {"x": 1500, "y": 200, "w": 360, "h": 600}})
        big, small = w.saved_places()
        self.assertEqual(json.loads(big), {"x": 1, "y": 2, "w": 1000, "h": 700, "max": False})
        self.assertEqual(json.loads(small), {"x": 1500, "y": 200, "w": 360, "h": 600})
        self.assertEqual(got, [1])
        w.on_message({"ev": "geometry", "big": {"x": "?"}, "small": None})    # испорченное — прежнее остаётся
        self.assertEqual(w.saved_places(), (big, small))

    def test_places_go_into_init(self):
        w = self.w
        w.restore_places(qt_blob(403, 235, 1476, 844, maximized=True), '{"x":10,"y":20,"w":360,"h":600}')
        w.set_taskbar_icon("C:/x/icon.ico")
        m = w._init_msg()
        self.assertEqual(m["big"], {"x": 403, "y": 235, "w": 1476, "h": 844, "max": True})
        self.assertEqual(m["small"], {"x": 10, "y": 20, "w": 360, "h": 600})
        self.assertEqual(m["icon"], "C:/x/icon.ico")
        self.assertEqual(m["appDetails"]["appId"], "autoprintcode.app")
        self.assertTrue(w.isMaximized())         # было развёрнуто — «Развернуть» на странице показывает «Вернуть»

    def test_close_asks_program(self):
        w = self.w
        asked = []

        def handler(e):
            asked.append(1)
            e.ignore()                            # в трей
        w.close_handler = handler
        w.on_message({"ev": "close"})            # Alt+F4 / панель задач
        w.window_cmd("close")                    # кнопка страницы
        self.assertEqual(asked, [1, 1])
        e = CloseEvent()
        e.ignore()
        self.assertFalse(e.isAccepted())

    def test_dropped_files_and_links(self):
        from PySide6.QtGui import QDesktopServices
        opened = []
        old = QDesktopServices.openUrl
        QDesktopServices.openUrl = staticmethod(lambda u: opened.append(u.toString()) or True)
        try:
            self.w.on_message({"ev": "drop", "paths": ["C:/x/урок.md", ""]})
            self.w.on_message({"ev": "open_url", "url": "https://example.com/a"})
            self.w.on_message({"ev": "open_url", "url": "file:///C:/Windows/win.ini"})   # не ссылка наружу
        finally:
            QDesktopServices.openUrl = old
        self.assertEqual(self.fake.drops, [["C:/x/урок.md"]])
        self.assertEqual(opened, ["https://example.com/a"])

    def test_title_only_when_changed(self):
        self.w.setWindowTitle("AutoPrintCode — Набираю")
        self.w.setWindowTitle("AutoPrintCode — Набираю")
        self.assertEqual(self.ops().count("title"), 1)

    def test_restart_never_grabs_keyboard(self):
        """Окно перезапустилось после сбоя: свёрнутое на время набора — не показывается; видное, но не в фокусе
        (человек печатает в другом окне) — показывается, не забирая клавиатуру; запуск программы — вперёд."""
        w = self.w
        w.show()
        self.assertEqual(w._show_mode(), "focus")                    # запуск программы
        w._restarting = True
        self.assertEqual(w._show_mode(), "inactive")                 # видно, фокус у редактора
        w.state["focused"] = True
        self.assertEqual(w._show_mode(), "focus")                    # человек был в окне программы
        w.showMinimized()
        self.assertEqual(w._show_mode(), "")                         # свёрнуто на время набора
        w.hide()
        self.assertEqual(w._show_mode(), "")
        self.assertEqual(w._init_msg()["show"], "")

    def test_dialogs_without_window(self):
        self.assertEqual(self.w.pick_open("Импорт", "", "PDF (*.pdf)", True), [])
        self.assertEqual(self.w.pick_save("Сохранить", "a.pdf", ""), "")
        self.assertFalse(self.w.print_pdf("x.pdf"))


class CommandTest(unittest.TestCase):
    def test_window_command_paths(self):
        import os
        old = dict(os.environ)
        try:
            os.environ["AUTOPRINT_WINDOW_EXE"] = r"C:\x\electron.exe"
            os.environ["AUTOPRINT_WINDOW_APP"] = r"C:\x\window"
            self.assertEqual(SW.window_command(), (r"C:\x\electron.exe", [r"C:\x\window"]))
            del os.environ["AUTOPRINT_WINDOW_EXE"]
            cmd = SW.window_command()             # из исходников — electron из window\node_modules (если поставлен)
            if cmd is not None:
                self.assertTrue(cmd[0].endswith("electron.exe"))
                self.assertEqual(Path(cmd[1][0]).name, "window")
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_missing_window_is_reported(self):
        import os
        fake = FakeApp(running=False, port=PORT + 3)
        os.environ["AUTOPRINT_WINDOW_EXE"] = str(Path(tempfile.gettempdir()) / "нет-такого-окна.exe")
        try:
            w = ShellWindow(fake, launch=True, hidden=True)
            failed = []
            w.page_failed.connect(failed.append)
            w.load()
            self.assertTrue(wait(lambda: failed, 10), "сбой запуска окна не сообщён")
            self.assertIn("Не удалось запустить окно программы", failed[0])
            self.assertTrue(fake.notes)            # и уведомлением у часов
            # окно поставили (или оно перестало падать): «Показать окно» запускает его снова, а не молчит
            if SW.window_command() is not None:
                del os.environ["AUTOPRINT_WINDOW_EXE"]
                fake.server.start()
                ready = []
                w.page_ready.connect(lambda: ready.append(1))
                w.load()
                self.assertTrue(wait(lambda: ready, 40), w.failure)
        finally:
            os.environ.pop("AUTOPRINT_WINDOW_EXE", None)
            w.stop()
            fake.close()

    def test_show_starts_window_after_giving_up(self):
        """Окно падало подряд (программа сдалась) — «Показать окно» из трея пробует запустить его снова."""
        if SW.window_command() is None:
            self.skipTest("окно Electron не поставлено")
        fake = FakeApp(port=PORT + 4)
        w = ShellWindow(fake, launch=True, hidden=True)
        ready = []
        w.page_ready.connect(lambda: ready.append(1))
        try:
            w._wanted = True                         # load() был, но окно так и не запустилось
            w._url = w.page_url()
            self.assertIsNone(w._proc)
            w.show()
            self.assertTrue(wait(lambda: ready, 40), w.failure)
            self.assertTrue(w.isVisible())
        finally:
            w.stop()
            fake.close()


@unittest.skipIf(SW.window_command() is None, "окно Electron не поставлено (npm install в window)")
class ElectronTest(unittest.TestCase):
    """Настоящее окно Electron, невидимо: одно на все проверки класса."""

    @classmethod
    def setUpClass(cls):
        cls.fake = FakeApp(port=PORT + 1)
        cls.w = ShellWindow(cls.fake, launch=True, hidden=True)
        cls.ready = []
        cls.w.page_ready.connect(lambda: cls.ready.append(1))
        cls.w.load()
        if not wait(lambda: cls.ready, 40):
            raise AssertionError("страница в окне Electron не запустилась: " + cls.w.failure)
        cls.w.show()
        pump(200)

    @classmethod
    def tearDownClass(cls):
        cls.w.stop()
        cls.fake.close()
        pump()

    def js(self, code, s: float = 8):
        res = []
        self.w.run_js(code, res.append)
        self.assertTrue(wait(lambda: res, s), f"нет ответа на {code}")
        return res[0]

    def hit(self, x_css, y_css):
        r = wintypes.RECT()
        user32.GetWindowRect(self.w.hwnd, ctypes.byref(r))
        dpr = self.js("devicePixelRatio")
        # GetWindowRect — с невидимыми краями Windows (по 8 px при 100 %): клиентская область — внутри
        client = self.js("[screenX, screenY]")
        sx, sy = int(client[0] * dpr + x_css * dpr), int(client[1] * dpr + y_css * dpr)
        return user32.SendMessageW(self.w.hwnd, 0x84, 0, ((sy & 0xFFFF) << 16) | (sx & 0xFFFF))

    def center(self, sel):
        c = self.js(f"(() => {{ const e = document.querySelector({json.dumps(sel)}); if (!e) return null; "
                    "const b = e.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; })()")
        self.assertIsNotNone(c, sel)
        return c

    def test_window_is_never_visible_in_tests(self):
        self.assertTrue(self.w.isVisible())                       # «как будто» показано
        self.assertFalse(user32.IsWindowVisible(self.w.hwnd))     # а на экране — ничего

    def test_page_works_and_knows_shell(self):
        self.assertTrue(self.js("window.__ready === true"))
        self.assertTrue(self.js("!!(window.autoprintShell && window.autoprintShell.electron)"))
        self.assertEqual(self.js("[innerWidth > 600, document.body.dataset.view]")[0], True)

    def test_drag_where_titlebar_is_empty(self):
        """Пустое место шапки — заголовок окна (тянуть, двойной щелчок, прилипание); кнопки и страница — нажимаются."""
        self.assertEqual(self.hit(*self.center(".tb-fill")), HTCAPTION)
        self.assertEqual(self.hit(*self.center("#closeBtn")), HTCLIENT)
        self.assertEqual(self.hit(*self.center("#zoomBtn")), HTCLIENT)
        self.assertEqual(self.hit(*self.center("#view")), HTCLIENT)
        self.assertEqual(self.hit(-3, 300), HTLEFT)                # невидимый край Windows — растягивать

    def test_drag_anywhere_marked_but_not_on_buttons(self):
        """[data-drag] (так помечено и табло маленького режима) — тянуть; кнопка и поле внутри — нажимаются."""
        self.js("(() => { const d = document.createElement('div'); d.id = 'dragProbe'; d.dataset.drag = '';"
                "d.style.cssText = 'position:fixed;left:200px;top:300px;width:300px;height:80px;z-index:999';"
                "d.innerHTML = '<span id=dpText>12:30</span><button id=dpBtn style=\"margin-left:150px\">×</button>"
                "<input id=dpIn style=\"width:60px\">'; document.body.append(d); return 1; })()")
        try:
            pump(150)
            self.assertEqual(self.hit(*self.center("#dpText")), HTCAPTION)
            self.assertEqual(self.hit(*self.center("#dpBtn")), HTCLIENT)
            self.assertEqual(self.hit(*self.center("#dpIn")), HTCLIENT)
        finally:
            self.js("(() => { document.getElementById('dragProbe').remove(); return 1; })()")

    def test_compact_round_trip(self):
        w = self.w
        big_before = dict(w.places.get("big") or {})
        try:
            w.set_compact(True)
            self.assertTrue(wait(lambda: (w.places.get("small") or {}).get("w") == 360, 10), w.places)
            small = w.places["small"]
            self.assertEqual(small["h"], 600)
            self.fake.settings.page_zoom = 100
            right = small["x"] + small["w"]
            w.compact_size({"w": 640, "h": 440})
            self.assertTrue(wait(lambda: w.places["small"]["w"] == 640, 10), w.places)
            self.assertEqual(w.places["small"]["x"] + w.places["small"]["w"], right)  # правый край на месте
        finally:
            w.set_compact(False)
        self.assertTrue(wait(lambda: self.js("innerWidth") > 640, 10))
        if big_before:
            self.assertEqual({k: w.places["big"][k] for k in "xywh"}, {k: big_before[k] for k in "xywh"})

    def test_pdf_has_white_margins_in_dark_theme(self):
        from PySide6.QtCore import QSize
        from PySide6.QtPdf import QPdfDocument
        out = Path(tempfile.mkdtemp(prefix="apc-pdf-")) / "урок.pdf"
        self.assertTrue(self.w.print_pdf(str(out), open_after=False))
        self.assertEqual(out.read_bytes()[:5], b"%PDF-")
        doc = QPdfDocument()
        doc.load(str(out))
        self.assertGreaterEqual(doc.pageCount(), 1)
        img = doc.render(0, QSize(595, 842))
        for x, y in ((5, 5), (590, 5), (5, 837), (297, 4)):
            c = img.pixelColor(x, y)                      # не закрашено (прозрачно) — белая бумага; иначе — почти белое
            self.assertTrue(c.alpha() < 10 or min(c.red(), c.green(), c.blue()) > 240,
                            f"поле страницы ({x},{y}) = {c.name()} α={c.alpha()}")

    def test_links_outside_open_in_browser(self):
        from PySide6.QtGui import QDesktopServices
        opened = []
        old = QDesktopServices.openUrl
        QDesktopServices.openUrl = staticmethod(lambda u: opened.append(u.toString()) or True)
        try:
            self.js("(() => { window.open('https://example.com/w', '_blank'); return 1; })()")
            self.assertTrue(wait(lambda: opened, 5))
            self.js("(() => { const a = document.createElement('a'); a.href = 'https://example.com/n'; "
                    "document.body.append(a); a.click(); a.remove(); return 1; })()")
            self.assertTrue(wait(lambda: len(opened) >= 2, 5), opened)
        finally:
            QDesktopServices.openUrl = old
        self.assertEqual(opened[:2], ["https://example.com/w", "https://example.com/n"])
        self.assertTrue(self.js("location.pathname.endsWith('/app') && window.__ready === true"))

    def test_dropped_files_reach_program_with_paths(self):
        """Файлы из Проводника, брошенные на окно, — программе настоящими путями; страница не уходит на file://."""
        self.assertTrue(self.js("window.autoprintShell.files === true"))
        f = Path(tempfile.mkdtemp(prefix="apc-drop-")) / "урок.md"
        f.write_text("# Урок\n", encoding="utf-8")
        self.fake.drops.clear()
        self.assertTrue(self.w.test_drop(files=[str(f)]))
        self.assertTrue(wait(lambda: self.fake.drops, 10), "брошенный файл не дошёл до программы")
        self.assertEqual([Path(p) for p in self.fake.drops[0]], [f])
        self.assertTrue(self.js("location.pathname.endsWith('/app') && window.__ready === true"))

    def test_dropped_link_opens_nothing(self):
        """Ссылку из браузера бросили на окно — окно не уходит на неё и браузер не открывается (как в 1.1)."""
        from PySide6.QtGui import QDesktopServices
        opened = []
        old = QDesktopServices.openUrl
        QDesktopServices.openUrl = staticmethod(lambda u: opened.append(u.toString()) or True)
        try:
            self.w.test_drop(items=[{"mimeType": "text/uri-list", "data": "https://example.com/drop"},
                                    {"mimeType": "text/plain", "data": "https://example.com/drop"}])
            pump(800)
        finally:
            QDesktopServices.openUrl = old
        self.assertEqual(opened, [])
        self.assertTrue(self.js("location.pathname.endsWith('/app') && window.__ready === true"))

    def test_page_errors_go_to_program_log(self):
        with self.assertLogs("autoprint.ui.shell_window", level="WARNING") as cm:
            self.js("(() => { console.error('проверка журнала окна'); return 1; })()")
            self.assertTrue(wait(lambda: any("проверка журнала окна" in r for r in cm.output), 5))
        self.assertTrue(any("Страница окна: проверка журнала окна" in r for r in cm.output), cm.output)

    def test_page_served_by_program(self):
        with urllib.request.urlopen(self.fake.server.url + "app", timeout=5) as r:
            self.assertIn(b"<html", r.read(2000).lower())

    def test_zz_window_restarts_after_crash(self):
        """Окно Electron упало — программа запускает его снова, страница открывается."""
        w = self.w
        old_pid = w.pid
        self.ready.clear()
        w._proc.kill()
        self.assertTrue(wait(lambda: self.ready and w.pid and w.pid != old_pid, 40), (w.pid, old_pid, w.failure))
        self.assertTrue(self.js("window.__ready === true"))


@unittest.skipIf(SW.window_command() is None, "окно Electron не поставлено (npm install в window)")
class FailTest(unittest.TestCase):
    def test_server_down_shows_message(self):
        fake = FakeApp(running=False, port=PORT + 2)
        fake.efir.ensure_server = lambda: False
        w = ShellWindow(fake, launch=True, hidden=True)
        failed = []
        w.page_failed.connect(failed.append)
        try:
            w.load()
            self.assertTrue(wait(lambda: failed, 30))
            self.assertIn("сервер окна не запустился", failed[0])
            res = []
            self.assertTrue(wait(lambda: (w.run_js("document.getElementById('text') && "
                                                   "document.getElementById('text').textContent", res.append)
                                          or pump(300) or any(res)), 15), res)
            self.assertIn("Не удалось запустить окно программы", next(r for r in res if r))
            # «Повторить» на странице сбоя: сервер запустился — окно получает адрес и открывает страницу
            fake.server.start()
            fake.efir.ensure_server = lambda: True
            ready = []
            w.page_ready.connect(lambda: ready.append(1))
            w.on_message({"ev": "retry"})
            self.assertTrue(wait(lambda: ready, 30), w.failure)
        finally:
            w.stop()
            fake.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
