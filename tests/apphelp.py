"""Общий стенд тестов окна программы: App без встроенного браузера (offscreen) + страница /app в Edge без окна.

    class MyTest(AppPage):
        templates = staticmethod(lambda: [Template(...)])
        route = "#/lessons"

Страница та же, что во встроенном браузере окна; команды окна (перетаскивание, «поверх всех») уходят в AppWindow
без WebEngine. Настоящих окон, трея, уведомлений и нажатий нет.
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import quiet  # noqa: E402,F401  — до PySide6: offscreen, своя папка данных

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
quiet.patch()

from autoprint import storage  # noqa: E402
from autoprint.storage import (BLOCK_CODE, BLOCK_MARKDOWN, BLOCK_STAGE, Block, Settings, Template,  # noqa: E402
                               TemplateStore)
from cdp import Edge  # noqa: E402

SEEN = ["steps_v1", "tour_v1", "lesson_v1", "lesson_v2", "lesson_v3", "plan_v1"]


def pump(ms: int = 30) -> None:
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.003)


def note(text, role="say", **kw):
    return Block(BLOCK_MARKDOWN, text, role=role, **kw)


def code(text, **kw):
    return Block(BLOCK_CODE, text, **kw)


def stage(title, minutes=5, **kw):
    return Block(BLOCK_STAGE, "", title=title, minutes=minutes, **kw)


def default_lessons() -> list[Template]:
    return [Template("Проверка окна", [stage("Начало", 5, id="s1"), note("Привет", id="n1"),
                                       code("print('hello')", id="c1"), stage("Итоги", 5, id="s2")], id="L1")]


def make_app(templates: list[Template], port: int):
    from autoprint.app_core import App
    storage.TEMPLATES_FILE.unlink(missing_ok=True)
    storage.TEMPLATES_FILE.with_suffix(".json.bak").unlink(missing_ok=True)
    store = TemplateStore()
    store.templates = list(templates)
    store.save()
    s = Settings()
    s.efir_port = port
    s.update_auto_check = False
    s.sound_enabled = False
    s.samples_seen = list(SEEN)
    s.migrations = ["tray_v1", "window_v10"]
    return App(s, store, web=False)


class AppPage(unittest.TestCase):
    """Программа + страница окна в Edge без окна — одна на все тесты класса."""
    templates = None
    route = "#/lessons"
    port = 18991
    width, height = 1280, 860

    @classmethod
    def setUpClass(cls):
        cls.app = make_app(cls.templates() if cls.templates else default_lessons(), cls.port)
        cls.store = cls.app.store
        cls.app.efir.ensure_server()
        cls.app.publish_now()
        url = f"http://127.0.0.1:{cls.app.efir.server.port}/app{cls.route}"
        cls.edge = Edge.start(url, pump=lambda: app.processEvents(), width=cls.width, height=cls.height)
        ok = cls.edge.wait("window.__ready === true", 15)
        assert ok, "страница окна не получила состояние: " + "; ".join(cls.edge.errors())

    @classmethod
    def tearDownClass(cls):
        cls.edge.close()
        cls.app.efir.stop_live()
        cls.app._quitting = True
        cls.app.shutdown()
        cls.app.window.hide()
        pump()

    # ---------------------------------------------------------------- помощники
    def js(self, code_: str):
        return self.edge.eval(code_)

    def wait_js(self, cond: str, timeout: float = 5) -> bool:
        return self.edge.wait(cond, timeout)

    def click(self, selector: str) -> None:
        """Щелчок через JS (не настоящий): элемент должен быть на странице."""
        ok = self.js(f"(() => {{ const e = document.querySelector({selector!r}); if (!e) return false; e.click(); return true; }})()")
        self.assertTrue(ok, f"нет элемента {selector}")

    def wait_py(self, pred, timeout: float = 5) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            pump(20)
            if pred():
                return True
        return False

    def go(self, hash_: str, view: str | None = None) -> None:
        self.js(f"location.hash = {hash_!r}")
        if view:
            self.assertTrue(self.wait_js(f"document.body.dataset.view === {view!r}"), f"экран {view} не открылся")

    def go_live(self, minutes_ago: float = 0, tid: str | None = None) -> None:
        from datetime import timedelta
        ef = self.app.efir
        t = self.store.get(tid) if tid else self.app.printer.focus()
        ef.launch_lesson(t, start="", show=False)
        live = ef.store.live
        ef.store.set_live(live.webinar_id, live.anchor - timedelta(minutes=minutes_ago))
        ef.live_changed.emit()
        self.app.lesson.publish()
        self.app.publish_now()

    def stop_live(self) -> None:
        self.app.efir.stop_live()
        self.app.lesson.publish()
        self.app.publish_now()
        pump(100)

    def tearDown(self):
        errs = self.edge.errors()
        self.edge.events.clear()
        self.assertEqual(errs, [], "ошибки JavaScript на странице")
