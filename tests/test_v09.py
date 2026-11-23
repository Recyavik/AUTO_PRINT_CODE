"""Доработка 0.9: колёсико, тема без зависаний, трей и окно суфлёра, начало эфира при запуске, редактор
«Эфира», таймер, суфлёр как PDF, картинки в редакторе, пример урока, урок в Markdown, картинка в Jupyter.
Всё без окон на экране.

    python tests/test_v09.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import quiet  # noqa: E402,F401  — до PySide6: offscreen, своя папка данных

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import (QApplication, QComboBox, QLineEdit, QPlainTextEdit, QScrollArea,  # noqa: E402
                               QSpinBox, QVBoxLayout, QWidget)

app = QApplication.instance() or QApplication([])
quiet.patch()
from autoprint.ui.theme import theme  # noqa: E402
theme.setup(app, "dark")

TMP = Path(tempfile.mkdtemp(prefix="v09-test-"))
PORT = 18950


def pump(ms: int = 50) -> None:
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def wheel(w: QWidget, dy: int = -120) -> None:
    pos = QPointF(w.width() / 2, w.height() / 2)
    ev = QWheelEvent(pos, QPointF(w.mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, dy),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(w, ev)


# ================================================================ Task 1: колёсико

class WheelTest(unittest.TestCase):
    """Колёсико над счётчиком или списком без фокуса крутит страницу, а не значение."""

    @classmethod
    def setUpClass(cls):
        from autoprint.ui.widgets import install_wheel_guard
        install_wheel_guard(app)

    def page(self, child: QWidget) -> tuple[QScrollArea, QWidget]:
        area = QScrollArea()
        area.setWidgetResizable(True)
        host = QWidget()
        lay = QVBoxLayout(host)
        sink = QLineEdit()                          # фокус — где-то ещё на странице, как в жизни
        lay.addWidget(sink)
        lay.addWidget(child)
        lay.addSpacing(3000)                        # страница выше окна — есть что прокручивать
        area.setWidget(host)
        area.resize(400, 300)
        area.show()
        pump(30)
        sink.setFocus()
        pump(10)
        return area, host

    def test_unfocused_spin_scrolls_page(self):
        sp = QSpinBox()
        sp.setRange(0, 100)
        sp.setValue(50)
        area, _ = self.page(sp)
        wheel(sp)
        pump(30)
        self.assertEqual(sp.value(), 50)
        self.assertGreater(area.verticalScrollBar().value(), 0)
        area.close()

    def test_focused_spin_changes(self):
        sp = QSpinBox()
        sp.setRange(0, 100)
        sp.setValue(50)
        area, _ = self.page(sp)
        area.activateWindow()
        sp.setFocus()
        pump(30)
        if not sp.hasFocus():
            self.skipTest("offscreen: фокус не встал")
        wheel(sp)
        pump(30)
        self.assertNotEqual(sp.value(), 50)
        area.close()

    def test_unfocused_combo_unchanged(self):
        cb = QComboBox()
        cb.addItems(["Обычный", "Перерыв", "Зарядка"])
        area, _ = self.page(cb)
        wheel(cb)
        wheel(cb)
        pump(30)
        self.assertEqual(cb.currentIndex(), 0)
        area.close()

    def test_text_editor_wheel_not_blocked(self):
        ed = QPlainTextEdit("\n".join(f"строка {i}" for i in range(300)))
        ed.setFixedHeight(120)
        area, _ = self.page(ed)
        wheel(ed.viewport())
        pump(30)
        self.assertGreater(ed.verticalScrollBar().value(), 0)
        area.close()



# ================================================================ Task 2: тема без зависаний

def big_template(n: int = 120, title: str = "Большое занятие"):
    from autoprint.storage import BLOCK_CODE, BLOCK_MARKDOWN, Block, Template
    blocks = []
    roles = ["say", "ask", "do", "important", "tell", "text"]
    for i in range(n):
        if i % 3 == 2:
            blocks.append(Block(BLOCK_CODE, f"x{i} = {i}\nprint(x{i})"))
        else:
            blocks.append(Block(BLOCK_MARKDOWN, f"Текст блока **{i}**\n\n- пункт", role=roles[i % len(roles)]))
    return Template(title=title, blocks=blocks)


def make_main(port: int):
    from autoprint.storage import Settings, TemplateStore
    from autoprint.ui.main_window import MainWindow
    s = Settings()
    s.efir_port = port
    store = TemplateStore()
    win = MainWindow(s, store)
    win.show()
    pump(30)
    return win, store


class ThemeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.win, cls.store = make_main(PORT + 1)
        cls.ts = [cls.store.insert(big_template(30, f"Занятие {k}")) for k in range(4)]

    @classmethod
    def tearDownClass(cls):
        theme.set_mode("dark")
        cls.win.efir.shutdown()

    def test_block_widget_count(self):
        from autoprint.storage import BLOCK_CODE, BLOCK_MARKDOWN, Block, Template
        from autoprint.ui.blocks import BlockWidget
        from autoprint.ui.template_view import TemplateView
        t = Template(title="x", blocks=[Block(BLOCK_MARKDOWN, "привет **мир**", role="say"),
                                        Block(BLOCK_CODE, "print(1)\nprint(2)")])
        v = TemplateView(t)
        v.show()
        pump(20)
        for b in v.findChildren(BlockWidget):
            n = len(b.findChildren(QWidget))
            self.assertLessEqual(n, 32, f"{type(b).__name__}: {n} виджетов")
        v.close()

    def test_role_chip_menu(self):
        from autoprint.storage import BLOCK_MARKDOWN, Block
        from autoprint.ui.blocks import MarkdownBlockWidget
        w = MarkdownBlockWidget(Block(BLOCK_MARKDOWN, "текст", role="text"))
        got = []
        w.type_requested.connect(lambda wdg, key: got.append(key))
        m = w.kind.build_menu()
        act = next(a for a in m.actions() if a.text() == "Говоришь")
        act.trigger()
        self.assertEqual(got, ["say"])
        self.assertEqual(w.kind.text(), "ТЕКСТ")

    def test_views_lru(self):
        for t in self.ts:
            self.win.open_template(t.id)
            pump(10)
        self.assertLessEqual(len(self.win.views), 2)
        self.assertIn(self.ts[-1].id, self.win.views)

    def test_running_job_view_kept(self):
        from autoprint.typer import RUNNING
        a, b, c = self.ts[0], self.ts[1], self.ts[2]
        self.win.open_template(a.id)
        old_job, old_state = self.win.job, self.win.engine.state
        self.win.job = {"tid": a.id, "bid": a.blocks[0].id}
        self.win.engine.state = RUNNING
        try:
            self.win.open_template(b.id)
            self.win.open_template(c.id)
            pump(10)
            self.assertIn(a.id, self.win.views)
        finally:
            self.win.job, self.win.engine.state = old_job, old_state

    def test_theme_rebuild_keeps_place(self):
        t = self.store.insert(big_template(120, "Сто двадцать блоков"))
        v = self.win.open_template(t.id)
        pump(50)
        target = t.blocks[60]
        v.arm(target.id)
        bar = v.scroll.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        pump(20)
        pos = bar.value()
        theme.set_mode("light" if theme.dark else "dark")
        pump(80)
        v2 = self.win.current_view()
        self.assertIsNot(v2, v)
        self.assertEqual(v2.template.id, t.id)
        self.assertEqual(v2.template.active_block, target.id)
        self.assertLess(abs(v2.scroll.verticalScrollBar().value() - pos), 80)

    def test_theme_switch_fast(self):
        t = self.store.insert(big_template(120, "Ещё сто двадцать"))
        self.win.open_template(t.id)
        pump(50)
        t0 = time.time()
        theme.set_mode("light" if theme.dark else "dark")
        app.processEvents()
        took = time.time() - t0
        self.assertLess(took, 3.0, f"смена темы {took:.1f} с")



# ================================================================ Task 3: трей, окно суфлёра, логотип

class TrayTest(unittest.TestCase):
    def test_default_is_tray(self):
        from autoprint.storage import Settings
        self.assertTrue(Settings().close_to_tray)

    def test_migration_turns_tray_on_once(self):
        from autoprint.storage import Settings
        from autoprint.ui.main_window import apply_migrations
        s = Settings()
        s.close_to_tray = False                 # так было сохранено у тех, кто ставил 0.8 и раньше
        self.assertTrue(apply_migrations(s))
        self.assertTrue(s.close_to_tray)
        self.assertIn("tray_v1", s.migrations)
        s.close_to_tray = False                 # выключили сами после обновления — больше не трогаем
        self.assertFalse(apply_migrations(s))
        self.assertFalse(s.close_to_tray)


class FakeProc:
    def __init__(self, args):
        self.args = args
        self.code = None
        self.terminated = False
        self.pid = 4242

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated = True
        self.code = 1


class PrompterWinTest(unittest.TestCase):
    def make(self, edge="C:/Edge/msedge.exe", window=True):
        from autoprint.ui.lesson_control import PrompterWindow
        self.launched, self.raised = [], []

        def popen(args, **_kw):
            proc = FakeProc(args)
            self.launched.append(proc)
            return proc
        return PrompterWindow(TMP / "edge-suflor", popen=popen, edge=lambda: edge,
                              find_window=lambda pid: 77 if window else 0,
                              raise_window=lambda hwnd: self.raised.append(hwnd))

    def test_single_window(self):
        w = self.make()
        self.assertTrue(w.open("http://127.0.0.1:1/lesson"))
        self.assertTrue(w.open("http://127.0.0.1:1/lesson"))
        self.assertEqual(len(self.launched), 1)
        self.assertEqual(self.raised, [77])

    def test_relaunch_after_closed(self):
        w = self.make()
        w.open("http://x/lesson")
        self.launched[0].code = 0                # окно закрыли руками — процесс вышел
        w.open("http://x/lesson")
        self.assertEqual(len(self.launched), 2)

    def test_relaunch_when_no_window(self):
        w = self.make(window=False)              # процесс жив (фоновый режим Edge), а окна нет
        w.open("http://x/lesson")
        w.open("http://x/lesson")
        self.assertEqual(len(self.launched), 2)

    def test_profile_dir_own(self):
        w = self.make()
        w.open("http://x/lesson")
        args = self.launched[0].args
        self.assertIn("--app=http://x/lesson", args)
        self.assertIn(f"--user-data-dir={TMP / 'edge-suflor'}", args)

    def test_closed_on_shutdown(self):
        w = self.make()
        w.open("http://x/lesson")
        w.close()
        self.assertTrue(self.launched[0].terminated)
        w.close()                                # второй раз — без ошибок

    def test_no_edge_falls_back(self):
        w = self.make(edge=None)
        self.assertFalse(w.open("http://x/lesson"))
        self.assertEqual(self.launched, [])


class FaviconTest(unittest.TestCase):
    def test_favicon_and_logo(self):
        import urllib.request
        from autoprint.efir.server import BroadcastServer
        srv = BroadcastServer(PORT + 2)
        self.assertTrue(srv.start())
        try:
            with urllib.request.urlopen(srv.url + "favicon.svg", timeout=5) as r:
                self.assertIn("svg", r.headers["Content-Type"])
                body = r.read().decode("utf-8")
            self.assertIn("#E9A72C", body.upper())
            for page in ("lesson", ""):
                with urllib.request.urlopen(srv.url + page, timeout=5) as r:
                    self.assertIn('rel="icon" href="/favicon.svg"', r.read().decode("utf-8"))
        finally:
            srv.stop()

    def test_title_logo_is_brand(self):
        from autoprint.ui import logo
        from autoprint.ui.main_window import title_logo_icon
        a = title_logo_icon().pixmap(32, 32).toImage()
        b = logo.make_icon(logo.APP).pixmap(32, 32).toImage()
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
