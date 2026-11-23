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


def drop_main(win) -> None:
    """Главное окно теста — удалить совсем: иначе следующая смена темы перекрашивает и его."""
    import shiboken6
    win.hide()
    shiboken6.delete(win)
    pump(10)


class ThemeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.win, cls.store = make_main(PORT + 1)
        cls.ts = [cls.store.insert(big_template(30, f"Занятие {k}")) for k in range(4)]

    @classmethod
    def tearDownClass(cls):
        theme.set_mode("dark")
        cls.win.efir.shutdown()
        drop_main(cls.win)

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
        """Смена темы стоит не больше, чем открыть то же занятие заново (раньше — в 2–4 раза дольше и росла
        с каждой открытой вкладкой). Сравниваем с открытием, а не с секундами: машины и нагрузка разные."""
        t = self.store.insert(big_template(120, "Ещё сто двадцать"))
        t0 = time.time()
        self.win.open_template(t.id)
        app.processEvents()
        opened = time.time() - t0
        t0 = time.time()
        theme.set_mode("light" if theme.dark else "dark")
        app.processEvents()
        took = time.time() - t0
        self.assertLess(took, opened * 1.6 + 0.5, f"смена темы {took:.1f} с, открытие {opened:.1f} с")



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



# ================================================================ Task 4: начало эфира — при запуске

class FakeMain(QWidget):
    def __init__(self):
        super().__init__()
        from autoprint.storage import Settings
        self.settings = Settings()
        self.settings.efir_port = PORT + 3


def efir_ctl(tag: str):
    from autoprint.efir import store as store_mod
    from autoprint.ui import efir_control
    data = TMP / f"efir-{tag}-{time.time_ns()}"
    old = store_mod.efir_dir
    store_mod.efir_dir = lambda: data
    try:
        ctl = efir_control.EfirController(FakeMain())
    finally:
        store_mod.efir_dir = old
    return ctl


class StartTest(unittest.TestCase):
    def setUp(self):
        from autoprint.efir.model import sample_webinar
        self.ctl = efir_ctl("start")
        self.w = sample_webinar()
        self.w.title = "1Т"
        self.ctl.store.add([self.w])

    def tearDown(self):
        if self.ctl.timer_window is not None:
            self.ctl.timer_window.close_silently()
        self.ctl.server.stop()

    def test_anchor_at_future_today(self):
        from datetime import datetime
        from autoprint.efir.model import anchor_at
        now = datetime(2026, 11, 23, 17, 12, 30)
        self.assertEqual(anchor_at("18:00", now), datetime(2026, 11, 23, 18, 0))

    def test_anchor_at_passed_today(self):
        from datetime import datetime
        from autoprint.efir.model import anchor_at
        now = datetime(2026, 11, 23, 18, 20)
        self.assertEqual(anchor_at("18:00", now), datetime(2026, 11, 23, 18, 0))      # опоздал — идёт 20 минут

    def test_anchor_at_midnight(self):
        from datetime import datetime
        from autoprint.efir.model import anchor_at
        self.assertEqual(anchor_at("00:10", datetime(2026, 11, 23, 23, 50)), datetime(2026, 11, 24, 0, 10))
        self.assertEqual(anchor_at("23:50", datetime(2026, 11, 24, 0, 5)), datetime(2026, 11, 23, 23, 50))

    def test_anchor_at_bad_is_now(self):
        from datetime import datetime
        from autoprint.efir.model import anchor_at
        now = datetime(2026, 11, 23, 17, 12, 30)
        self.assertEqual(anchor_at("", now), datetime(2026, 11, 23, 17, 12, 30))
        self.assertEqual(anchor_at("25:99", now), datetime(2026, 11, 23, 17, 12, 30))

    def test_quick_times(self):
        from datetime import datetime
        from autoprint.ui.efir_start import quick_times
        self.assertEqual(quick_times(datetime(2026, 1, 1, 17, 12)), ["17:30", "18:00"])
        self.assertEqual(quick_times(datetime(2026, 1, 1, 17, 30)), ["18:00", "18:30"])
        self.assertEqual(quick_times(datetime(2026, 1, 1, 23, 40)), ["00:00", "00:30"])

    def test_launch_now(self):
        from datetime import datetime
        self.ctl.launch(self.w.id, "")
        self.assertLess(abs((datetime.now() - self.ctl.store.live.anchor).total_seconds()), 3)

    def test_launch_at_remembers_start(self):
        from datetime import datetime
        from autoprint.efir.model import anchor_at
        self.ctl.launch(self.w.id, "18:00")
        self.assertEqual(self.ctl.store.live.anchor, anchor_at("18:00", datetime.now()))
        self.assertEqual(self.ctl.store.get(self.w.id).start, "18:00")

    def test_relaunch_keeps_anchor(self):
        self.ctl.launch(self.w.id, "18:00")
        a = self.ctl.store.live.anchor
        self.ctl.launch(self.w.id)                  # «Открыть таймер» у идущего — время не сбивается
        self.assertEqual(self.ctl.store.live.anchor, a)

    def test_set_start_moves_anchor(self):
        from datetime import datetime
        from autoprint.efir.model import anchor_at
        self.ctl.launch(self.w.id, "")
        self.ctl.set_start("09:00")
        self.assertEqual(self.ctl.store.live.anchor, anchor_at("09:00", datetime.now()))
        self.ctl.set_start("")                      # «Сейчас» — с первого блока с этой минуты
        self.assertLess(abs((datetime.now() - self.ctl.store.live.anchor).total_seconds()), 3)

    def test_editor_has_no_start_field(self):
        from PySide6.QtWidgets import QTimeEdit
        from autoprint.ui.efir_editor import EditorWindow
        ed = EditorWindow(self.ctl, self.w)
        try:
            self.assertEqual(ed.findChildren(QTimeEdit), [])
            ed.w.start = "18:00"
            self.assertEqual(ed.result().start, "18:00")          # прошлое время старта не теряется
        finally:
            ed._dirty = False
            ed.close()

    def test_row_times_relative(self):
        from autoprint.ui.efir_editor import EditorWindow
        ed = EditorWindow(self.ctl, self.w)
        try:
            self.assertEqual([r.time_lbl.text() for r in ed.rows[:4]], ["0:00", "0:01", "0:06", "0:20"])
        finally:
            ed._dirty = False
            ed.close()

    def test_start_picker(self):
        from datetime import datetime
        from autoprint.ui.efir_start import StartPicker
        p = StartPicker(last="11:00", now=datetime(2026, 1, 1, 17, 12))
        got = []
        p.chosen.connect(got.append)
        texts = [b.text() for b in p.quick_buttons]
        self.assertEqual(texts, ["17:30", "18:00", "11:00"])
        p.now_btn.click()
        p.quick_buttons[1].click()
        p.time_edit.setTime(p.time_edit.time().fromString("19:15", "HH:mm"))
        p.at_btn.click()
        self.assertEqual(got, ["", "18:00", "19:15"])


class LessonStartTest(unittest.TestCase):
    """Урок в суфлёре: «Начать сейчас» или «в ЧЧ:ММ»; начало идущего урока можно поправить."""

    @classmethod
    def setUpClass(cls):
        from autoprint.efir import store as store_mod
        from autoprint.storage import BLOCK_STAGE, Block, Template
        cls.data = TMP / "lesson-start-efir"
        cls._efir_dir = store_mod.efir_dir
        store_mod.efir_dir = lambda: cls.data
        cls.win, cls.store = make_main(PORT + 4)
        cls.t = cls.store.insert(Template(title="Урок", blocks=[
            Block(BLOCK_STAGE, title="Вступление", minutes=5), Block(BLOCK_STAGE, title="Теория", minutes=20)]))
        cls.win.open_template(cls.t.id)

    @classmethod
    def tearDownClass(cls):
        from autoprint.efir import store as store_mod
        cls.win.efir.stop_live()
        cls.win.efir.shutdown()
        store_mod.efir_dir = cls._efir_dir
        drop_main(cls.win)

    def tearDown(self):
        self.win.lesson.command({"cmd": "stop"})

    def test_start_now(self):
        from datetime import datetime
        self.win.lesson.command({"cmd": "start"})
        self.assertEqual(self.win.efir.live_lesson_id(), self.t.id)
        self.assertLess(abs((datetime.now() - self.win.efir.store.live.anchor).total_seconds()), 3)

    def test_start_at(self):
        from datetime import datetime
        from autoprint.efir.model import anchor_at
        self.win.lesson.command({"cmd": "start", "at": "18:00"})
        self.assertEqual(self.win.efir.store.live.anchor, anchor_at("18:00", datetime.now()))
        self.assertEqual(self.t.start, "18:00")                 # запомнено — подставится в следующий раз

    def test_set_start_live(self):
        from datetime import datetime
        from autoprint.efir.model import anchor_at
        self.win.lesson.command({"cmd": "start"})
        self.win.lesson.command({"cmd": "set_start", "start": "07:45"})
        self.assertEqual(self.win.efir.store.live.anchor, anchor_at("07:45", datetime.now()))
        self.win.lesson.command({"cmd": "set_start", "start": "99:99"})     # неверное — без изменений
        self.assertEqual(self.win.efir.store.live.anchor, anchor_at("07:45", datetime.now()))



# ================================================================ Task 5: редактор шаблона «Эфира»

class EfirEditorTest(unittest.TestCase):
    def setUp(self):
        from autoprint.efir.model import sample_webinar
        from autoprint.ui.efir_editor import EditorWindow
        self.ctl = efir_ctl("editor")
        self.w = sample_webinar()
        self.ctl.store.add([self.w])
        self.ed = EditorWindow(self.ctl, self.w)
        self.ed.show()
        pump(30)

    def tearDown(self):
        import shiboken6
        self.ed._dirty = False
        self.ed.close()
        shiboken6.delete(self.ed)
        self.ctl.server.stop()

    def test_total_on_top(self):
        self.assertEqual(self.ed.total.text(), "Всего 1 ч 40 мин · блоков: 12")
        y_total = self.ed.total.mapTo(self.ed, QPoint(0, 0)).y()
        y_row = self.ed.rows[0].mapTo(self.ed, QPoint(0, 0)).y()
        self.assertLess(y_total, y_row)

    def test_kind_button_sets_kind(self):
        r = self.ed.rows[0]
        next(a for a in r.kind_btn.build_menu().actions() if a.text() == "Перерыв").trigger()
        self.assertEqual(r.activity().kind, "break")
        self.assertIn("Перерыв", r.kind_btn.text())
        self.assertTrue(self.ed._dirty)

    def test_demo_button_sets_demo(self):
        r = self.ed.rows[0]
        next(a for a in r.demo_btn.build_menu().actions() if a.text() == "Демонстрация ВЫКЛ").trigger()
        self.assertEqual(r.activity().demo, "off")

    def test_name_guesses_kind_until_touched(self):
        r = self.ed.rows[1]
        r.name.setText("Зарядка для глаз")
        r._name_edited("Зарядка для глаз")
        self.assertEqual(r.activity().kind, "exercise")

    def test_add_several_exercises(self):
        from PySide6.QtWidgets import QFileDialog
        a, b = TMP / "Гимнастика.mp4", TMP / "Шея.mp4"
        for f in (a, b):
            f.write_bytes(b"0" * 10)
        old, old1 = QFileDialog.getOpenFileNames, QFileDialog.getOpenFileName
        QFileDialog.getOpenFileNames = staticmethod(lambda *x, **k: ([str(a), str(b)], ""))
        QFileDialog.getOpenFileName = staticmethod(lambda *x, **k: ("", ""))    # одиночный выбор — не диалог
        try:
            n = len(self.ed.ex_rows)
            self.ed.add_exercise()
        finally:
            QFileDialog.getOpenFileNames, QFileDialog.getOpenFileName = old, old1
        self.assertEqual([r.exercise().title for r in self.ed.ex_rows[n:]], ["Гимнастика", "Шея"])

    def test_break_show_title_roundtrip(self):
        from autoprint.efir.model import webinar_from_dict
        self.ed.show_title.setChecked(False)
        w = self.ed.result()
        self.assertFalse(w.break_show_title)
        self.assertFalse(webinar_from_dict(w.to_dict()).break_show_title)
        self.assertTrue(webinar_from_dict({"schedule": [{"name": "А", "min": 5}]}).break_show_title)

    def test_state_hides_title(self):
        self.w.break_show_title = False
        self.ctl.webinar = self.w
        self.ctl.start_break(5)
        self.assertEqual(self.ctl.state()["brk"]["title"], "")
        self.ctl.show_background()

    def test_preview_published(self):
        self.ed.break_title.setText("ОТДЫХАЕМ")
        url = self.ed.preview_break()
        self.assertIn("ch=preview", url)
        st = self.ctl.server.snapshot("preview")
        self.assertEqual((st["mode"], st["brk"]["title"]), ("break", "ОТДЫХАЕМ"))
        self.assertEqual(self.ctl.mode, "idle")              # на настоящий экран эфира ничего не ушло

    def test_screen_page_reads_channel(self):
        from autoprint.efir.server import PAGE_DIR
        html = (PAGE_DIR / "screen.html").read_text(encoding="utf-8")
        self.assertIn("PREVIEW", html)
        self.assertIn("'/events' + (CH ?", html)



# ================================================================ Task 6: таймер, кнопка «Эфир», экран

class TimerTest(unittest.TestCase):
    def test_agenda_window(self):
        from autoprint.ui.efir_timer import agenda_window
        self.assertEqual(agenda_window(13, 0), (0, 3))
        self.assertEqual(agenda_window(13, 6), (4, 9))
        self.assertEqual(agenda_window(13, 12), (10, 13))
        self.assertEqual(agenda_window(3, 1), (0, 3))
        self.assertEqual(agenda_window(0, 0), (0, 0))

    def test_board_mode(self):
        from autoprint.ui.efir_timer import board_mode
        self.assertEqual(board_mode(900, 160), "strip")
        self.assertEqual(board_mode(700, 400), "side")
        self.assertEqual(board_mode(300, 500), "below")
        self.assertEqual(board_mode(200, 80), "hero")
        self.assertEqual(board_mode(420, 200), "hero")

    def test_efir_token(self):
        from autoprint.ui.main_window import efir_token
        self.assertEqual(efir_token("", "idle"), "dim")
        self.assertEqual(efir_token("before", "idle"), "accent")
        self.assertEqual(efir_token("live", "idle"), "live")
        self.assertEqual(efir_token("live", "break"), "accent")
        self.assertEqual(efir_token("after", "idle"), "dim")

    def test_screen_no_hint(self):
        from autoprint.efir.server import PAGE_DIR
        html = (PAGE_DIR / "screen.html").read_text(encoding="utf-8")
        self.assertNotIn("Щёлкните по странице", html)
        self.assertNotIn('id="hint"', html)


class TimerWindowTest(unittest.TestCase):
    def setUp(self):
        from autoprint.efir.model import sample_webinar
        self.ctl = efir_ctl("timer")
        self.w = sample_webinar()
        self.ctl.store.add([self.w])
        self.ctl.launch(self.w.id, "")
        self.tw = self.ctl.timer_window

    def tearDown(self):
        if self.ctl.timer_window is not None:
            self.ctl.timer_window.close_silently()
        self.ctl.server.stop()

    def test_open_tab_button(self):
        self.tw.resize(520, 300)
        pump(30)
        self.ctl.clients = 0
        self.ctl.tab_changed.emit()
        self.assertTrue(self.tw.btn_tab.isVisibleTo(self.tw))
        self.ctl.clients = 1
        self.ctl.tab_changed.emit()
        self.assertFalse(self.tw.btn_tab.isVisibleTo(self.tw))

    def test_board_paints_all_sizes(self):
        for size in ((900, 190), (700, 420), (320, 560), (220, 110), (1600, 900)):
            self.tw.resize(*size)
            pump(20)
            img = self.tw.grab()
            self.assertFalse(img.isNull(), size)
        self.assertIn(self.tw.board.mode, ("strip", "side", "below", "hero"))



# ================================================================ Task 7: суфлёр как PDF — плашки ролей

class PageTest(unittest.TestCase):
    def test_block_state_has_label_title(self):
        from autoprint import scenario
        from autoprint.storage import BLOCK_MARKDOWN, Block
        st = scenario._block_state(Block(BLOCK_MARKDOWN, "Здравствуйте!", role="say", title="Повторение"),
                                   lambda p: "")
        self.assertEqual((st["label"], st["title"]), ("Говоришь", "Повторение"))
        st = scenario._block_state(Block(BLOCK_MARKDOWN, "Вопрос?\n→ ответ", role="ask"), lambda p: "")
        self.assertEqual((st["label"], st["title"]), ("Спроси", ""))

    def test_page_role_styles(self):
        from autoprint.efir.server import PAGE_DIR
        css = (PAGE_DIR / "lesson.html").read_text(encoding="utf-8")
        for role in ("say", "tell", "ask", "do", "important", "show", "trap", "extra"):
            self.assertIn(f".r-{role} {{ --rc:", css, role)
        self.assertIn("border-left: 4px solid var(--rc)", css)
        self.assertIn("color-mix(in srgb, var(--rc)", css)
        self.assertIn('el("div", "lbl")', css)



# ================================================================ Task 8: картинка во всю ширину, цвет ролей

def make_image(name: str, w: int, h: int) -> Path:
    from PySide6.QtGui import QColor, QImage
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#3a6ea5"))
    out = TMP / name
    img.save(str(out), "PNG")
    return out


def hosted(widget: QWidget, width: int = 900) -> QWidget:
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(widget)
    host.resize(width, 1200)
    host.show()
    pump(60)
    return host


class EditorBlocksTest(unittest.TestCase):
    def image_widget(self, w: int, h: int):
        from autoprint.storage import BLOCK_IMAGE, Block
        from autoprint.ui.blocks import ImageBlockWidget
        f = make_image(f"img-{w}x{h}.png", w, h)
        wd = ImageBlockWidget(Block(BLOCK_IMAGE, str(f), title="Стандартный диалог"))
        return wd, hosted(wd)

    def test_image_fits_width(self):
        wd, host = self.image_widget(3840, 2160)
        self.assertGreaterEqual(wd.preview_size().width(), 800)
        host.close()

    def test_small_image_not_upscaled(self):
        wd, host = self.image_widget(320, 200)
        self.assertEqual((wd.preview_size().width(), wd.preview_size().height()), (320, 200))
        host.close()

    def test_image_height_capped(self):
        wd, host = self.image_widget(1000, 4000)
        self.assertLessEqual(wd.preview_size().height(), 520)
        host.close()

    def test_image_click_opens_viewer(self):
        wd, host = self.image_widget(1600, 900)
        dlg = wd.open_viewer()
        try:
            self.assertTrue(dlg.isVisible())
            self.assertEqual(dlg.image_size().width(), 1600)
        finally:
            dlg.close()
            host.close()

    def test_no_role_chip_on_image_and_stage(self):
        from autoprint.storage import BLOCK_IMAGE, BLOCK_MARKDOWN, BLOCK_STAGE, Block
        from autoprint.ui.blocks import ImageBlockWidget, MarkdownBlockWidget, StageBlockWidget
        for cls, b, chip in ((ImageBlockWidget, Block(BLOCK_IMAGE, ""), False),
                             (StageBlockWidget, Block(BLOCK_STAGE, "", title="Этап", minutes=5), False),
                             (MarkdownBlockWidget, Block(BLOCK_MARKDOWN, "текст", role="say"), True)):
            w = cls(b)
            host = hosted(w)
            self.assertEqual(w.kind.isVisibleTo(w), chip, cls.__name__)
            host.close()

    def test_role_tint_painted(self):
        from autoprint.storage import BLOCK_MARKDOWN, Block
        from autoprint.ui.blocks import MarkdownBlockWidget
        say = MarkdownBlockWidget(Block(BLOCK_MARKDOWN, "а", role="say"))
        plain = MarkdownBlockWidget(Block(BLOCK_MARKDOWN, "а", role="text"))
        h1, h2 = hosted(say, 600), hosted(plain, 600)
        a = say.grab().toImage().pixelColor(say.width() - 30, say.height() - 6)
        b = plain.grab().toImage().pixelColor(plain.width() - 30, plain.height() - 6)
        self.assertNotEqual(a.name(), b.name())
        self.assertGreater(a.blue(), b.blue())          # «Говоришь» — голубоватый фон
        h1.close()
        h2.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
