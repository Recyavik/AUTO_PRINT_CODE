"""0.10 — один экран урока: модель, печать только кода, окно-список, правки со страницы, «Эфир».
Всё без окон на экране.

    python tests/test_v10.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import quiet  # noqa: E402,F401  — до PySide6: offscreen, своя папка данных

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
quiet.patch()
from autoprint.ui.theme import theme  # noqa: E402
theme.setup(app, "dark")

from autoprint import storage  # noqa: E402
from autoprint.storage import (BLOCK_CODE, BLOCK_IMAGE, BLOCK_MARKDOWN, BLOCK_STAGE, Block,  # noqa: E402
                               Settings, Template, TemplateStore)

TMP = Path(tempfile.mkdtemp(prefix="v10-test-"))


def pump(ms: int = 50) -> None:
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def note(text: str = "заметка", role: str = "say", **kw) -> Block:
    return Block(BLOCK_MARKDOWN, text, role=role, **kw)


def code(text: str = "print(1)", **kw) -> Block:
    return Block(BLOCK_CODE, text, **kw)


def stage(title: str = "Этап", minutes: int = 5, **kw) -> Block:
    return Block(BLOCK_STAGE, "", title=title, minutes=minutes, **kw)


# ================================================================ Task 1: роли, урок, миграции

class RolesTest(unittest.TestCase):
    def test_new_roles(self):
        from autoprint.storage import ROLE_HINTS, ROLE_MORE, ROLE_ORDER, ROLES
        self.assertIn("term", ROLES)
        self.assertIn("output", ROLES)
        self.assertEqual(ROLES["task"][1], "Задание")
        self.assertEqual(ROLES["text"][1], "Заметка")
        self.assertEqual(ROLES["term"][1], "Термин")
        self.assertEqual(ROLES["output"][1], "Вывод")
        self.assertEqual(set(ROLE_ORDER + ROLE_MORE), set(ROLES))
        self.assertEqual(len(ROLE_ORDER + ROLE_MORE), len(ROLES))
        self.assertEqual(ROLE_ORDER[0], "say")
        self.assertEqual(set(ROLE_HINTS), set(ROLES))
        self.assertIn("дословно", ROLE_HINTS["say"])
        self.assertIn("своими словами", ROLE_HINTS["tell"])

    def test_new_lesson_shape(self):
        t = TemplateStore().add("X")
        self.assertEqual([(b.type, b.title, b.minutes) for b in t.blocks[:1]], [(BLOCK_STAGE, "Начало", 5)])
        self.assertEqual(len(t.blocks), 2)
        self.assertEqual((t.blocks[1].type, t.blocks[1].role, t.blocks[1].text), (BLOCK_MARKDOWN, "say", ""))

    def test_look_field_roundtrip(self):
        t = Template("L", [note()], look="abc")
        d = storage.asdict(t)
        self.assertEqual(storage._template_from(d).look, "abc")

    def test_settings_new_fields(self):
        names = set(Settings.__dataclass_fields__)
        for new in ("lesson_look", "page_open", "page_lesson"):
            self.assertIn(new, names)


class NextCodeTest(unittest.TestCase):
    def test_next_code(self):
        a, b = code("a = 1", id="A"), code("b = 2", id="B")
        t = Template("T", [note(), a, Block(BLOCK_IMAGE, "x.png"), code("  \n", id="E"), b])
        self.assertIs(t.next_code(), a)
        self.assertIs(t.next_code("A"), b)
        self.assertIsNone(t.next_code("B"))
        self.assertIs(t.next_code("B", back=True), a)
        self.assertIsNone(t.next_code("A", back=True))

    def test_is_printable(self):
        from autoprint.storage import is_printable
        self.assertTrue(is_printable(code("x")))
        self.assertFalse(is_printable(code("   ")))
        self.assertFalse(is_printable(note("x")))
        self.assertFalse(is_printable(Block(BLOCK_IMAGE, "x.png")))


class MigrationTest(unittest.TestCase):
    def setUp(self):
        storage.TEMPLATES_FILE.unlink(missing_ok=True)
        storage.TEMPLATES_FILE.with_suffix(".json.bak").unlink(missing_ok=True)
        (storage.DATA_DIR / "templates.before-0.10.json").unlink(missing_ok=True)

    def make_store(self):
        store = TemplateStore()
        n = note(id="n1")
        store.templates = [Template("С кодом", [n, code(id="c1")], active_block="n1"),
                           Template("Без кода", [note(id="n2")], active_block="n2"),
                           Template("Код активен", [code(id="c2")], active_block="c2")]
        store.save()
        return store

    def test_active_note_reset(self):
        from autoprint import migrations
        store = self.make_store()
        s = Settings()
        self.assertTrue(migrations.apply(s, store))
        self.assertEqual([t.active_block for t in store.templates], ["c1", "", "c2"])
        self.assertIn("roles_v10", s.migrations)
        self.assertFalse(migrations.apply(s, store))

    def test_backup_once(self):
        from autoprint import migrations
        store = self.make_store()
        before = storage.TEMPLATES_FILE.read_text(encoding="utf-8")
        migrations.apply(Settings(), store)
        bak = storage.DATA_DIR / "templates.before-0.10.json"
        self.assertTrue(bak.exists())
        self.assertEqual(bak.read_text(encoding="utf-8"), before)
        store.templates[0].title = "другое"
        store.save()
        migrations.apply(Settings(), store)
        self.assertEqual(bak.read_text(encoding="utf-8"), before)

    def test_tray_migration_moved(self):
        from autoprint import migrations
        s = Settings()
        s.close_to_tray = False
        migrations.apply(s, self.make_store())
        self.assertTrue(s.close_to_tray)
        self.assertIn("tray_v1", s.migrations)

    def test_window_geometry_reset_once(self):
        """Окно программы стало маленьким списком: размер большого окна 0.9 не восстанавливаем."""
        from autoprint import migrations
        s = Settings()
        s.window_geometry = "AAAA"
        migrations.apply(s)
        self.assertEqual(s.window_geometry, "")
        s.window_geometry = "BBBB"
        migrations.apply(s)
        self.assertEqual(s.window_geometry, "BBBB")


# ================================================================ Task 2, 3, 5: печать, окно, экран урока

SEEN = ["steps_v1", "tour_v1", "lesson_v1", "lesson_v2"]     # встроенные примеры уже добавлены — не мешают


def make_window(templates: list[Template], port: int = 18961):
    from autoprint.ui.main_window import MainWindow
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
    w = MainWindow(s, store)
    w.tray.showMessage = lambda *a, **k: None
    return w


class Recorder:
    """Подмена движка: что загрузили и сколько раз стартовали (настоящая печать в тестах не нужна)."""

    def __init__(self, printer) -> None:
        self.loaded: list[str] = []
        self.started = 0
        printer.engine.load = lambda text, *a, **k: self.loaded.append(text)
        printer.engine.start = lambda *a, **k: setattr(self, "started", self.started + 1)


class PrintTest(unittest.TestCase):
    def setUp(self):
        self.a, self.b = code("a = 1", id="ca"), code("b = 2", id="cb")
        self.m_code = code("m = 0", id="cm")
        self.L = Template("Идёт", [note(id="ln"), self.a, note("между", role="tell"), self.b], id="L")
        self.M = Template("Открыт", [self.m_code], id="M")
        self.N = Template("Без кода", [note(id="nn"), Block(BLOCK_IMAGE, "x.png", id="ni")], id="N",
                          active_block="ni")
        self.win = make_window([self.L, self.M, self.N])
        self.p = self.win.printer
        self.rec = Recorder(self.p)
        self.notes: list[str] = []
        self.p.notify.connect(lambda t, *_: self.notes.append(t))

    def tearDown(self):
        self.win._quitting = True
        self.win.close()
        pump()

    def test_note_never_armed(self):
        self.p.set_focus("L")
        self.assertFalse(self.p.arm("ln"))
        self.assertEqual(self.L.active_block, "")
        self.assertTrue(self.p.arm("cb"))
        self.assertEqual(self.L.active_block, "cb")

    def test_image_pointer_not_printed(self):
        self.p.set_focus("N")
        self.p.toggle()
        self.assertEqual(self.rec.loaded, [])
        self.assertEqual(self.rec.started, 0)
        self.assertTrue(any("нет кода" in n for n in self.notes), self.notes)

    def test_focus_is_live(self):
        self.p.live_id = lambda: "L"
        self.p.set_focus("M")
        self.assertEqual(self.p.focus().id, "L")
        self.p.toggle()
        self.assertEqual(self.rec.loaded, ["a = 1"])     # указателя не было — первый код идущего урока
        self.assertEqual(self.rec.started, 1)

    def test_auto_advance_and_restart(self):
        self.p.set_focus("L")
        self.p.arm("ca")
        self.p.job = self.p.job_for_armed()
        self.p._on_finished()
        self.assertEqual(self.L.active_block, "cb")
        self.assertEqual(self.p.last, "ca")
        self.p.restart()
        self.assertEqual(self.L.active_block, "ca")
        self.assertTrue(any(n.startswith("Ещё раз:") for n in self.notes), self.notes)

    def test_all_printed_message(self):
        self.p.set_focus("L")
        self.p.arm("cb")
        self.p.job = self.p.job_for_armed()
        self.p._on_finished()
        self.assertEqual(self.L.active_block, "")
        self.p.toggle()
        self.assertEqual(self.rec.loaded, [])
        self.assertTrue(any("Весь код урока напечатан" in n for n in self.notes), self.notes)

    def test_step_next_block(self):
        self.p.set_focus("L")
        self.p.step(+1)
        self.assertEqual(self.L.active_block, "ca")
        self.p.step(+1)
        self.assertEqual(self.L.active_block, "cb")
        self.p.step(+1)
        self.assertEqual(self.L.active_block, "cb")       # на краю — остаётся
        self.p.step(-1)
        self.assertEqual(self.L.active_block, "ca")

    def test_deleted_block_stops(self):
        from autoprint.typer import RUNNING
        self.p.set_focus("L")
        self.p.arm("ca")
        self.p.job = self.p.job_for_armed()
        self.p.engine.state = RUNNING
        stopped = []
        self.p.stop = lambda: stopped.append(1)
        self.L.blocks.remove(self.a)
        self.p.on_store_changed()
        self.assertEqual(stopped, [1])

    def test_focus_change_stops(self):
        from autoprint.typer import RUNNING
        self.p.set_focus("L")
        self.p.arm("ca")
        self.p.job = self.p.job_for_armed()
        self.p.engine.state = RUNNING
        stopped = []
        self.p.stop = lambda: stopped.append(1)
        self.p.set_focus("M")
        self.assertEqual(stopped, [1])

    def test_print_options(self):
        self.assertTrue(self.p.set_option("mode", "steps"))
        self.assertEqual(self.win.settings.print_mode, "steps")
        self.assertFalse(self.p.set_option("mode", "zzz"))
        self.assertTrue(self.p.set_option("cpm", "99999"))
        self.assertEqual(self.win.settings.cpm, 3000)
        self.assertTrue(self.p.set_option("strip", 1))
        self.assertTrue(self.win.settings.strip_comments)

    def test_snapshot_steps(self):
        b = code("# сначала имя\nname = 1\n# потом печать\nprint(name)", id="cs", steps=[1, 1, 2, 2])
        t = Template("Шаги", [b], id="S")
        self.win.store.templates.append(t)
        self.p.set_focus("S")
        self.p.set_option("mode", "steps")
        self.p.set_option("strip", True)
        self.p.arm("cs")
        snap = self.p.snapshot()
        self.assertEqual(snap["block"], "cs")
        self.assertEqual(snap["step"], {"i": 1, "n": 2})
        self.assertEqual(snap["next_lines"], [2])
        self.assertEqual(snap["say"], ["сначала имя"])


class OwnWindowTest(unittest.TestCase):
    """E13: в окно экрана урока (Edge, запущенный программой) печатать нельзя."""

    def test_own_pid_and_title(self):
        from autoprint import winapi
        pids = {11: 4242, 12: 5555, 13: 6666}
        titles = {11: "Урок", 12: "Пример — Экран урока — AutoPrintCode", 13: "Jupyter"}
        old_pid, old_title = winapi.window_pid, winapi.window_title
        winapi.window_pid = lambda h: pids.get(h, 0)
        winapi.window_title = lambda h: titles.get(h, "")
        try:
            winapi.own_pids.add(4242)
            self.assertTrue(winapi.is_own_window(11))
            self.assertTrue(winapi.is_own_window(12))
            self.assertFalse(winapi.is_own_window(13))
            self.assertFalse(winapi.is_own_window(0))
        finally:
            winapi.window_pid, winapi.window_title = old_pid, old_title
            winapi.own_pids.discard(4242)

    def test_page_window_pid_registered(self):
        from autoprint import winapi
        from autoprint.ui.lesson_control import PrompterWindow

        class Proc:
            pid = 7777

            def poll(self):
                return None
        w = PrompterWindow(TMP / "edge", popen=lambda *a, **k: Proc(), edge=lambda: "msedge.exe",
                           find_window=lambda pid: 0, raise_window=lambda h: None)
        self.assertTrue(w.open("http://127.0.0.1:1/lesson"))
        self.assertIn(7777, winapi.own_pids)
        winapi.own_pids.discard(7777)

    def test_engine_message(self):
        from pathlib import Path as P
        src = P(storage.__file__).with_name("typer.py").read_text(encoding="utf-8")
        self.assertIn("Поставьте курсор в Jupyter", src)


class WindowTest(unittest.TestCase):
    def setUp(self):
        self.L = Template("Идёт", [stage("A", 5), code("x", id="c1"), stage("B", 10), code("y")], id="L")
        self.M = Template("Другой", [note()], id="M")
        self.win = make_window([self.L, self.M], port=18962)
        self.opened: list[int] = []
        self.win.lesson.open_page = lambda: self.opened.append(1)

    def tearDown(self):
        self.win._quitting = True
        self.win.close()
        pump()

    def test_compact(self):
        from autoprint.ui.library import LibraryPanel
        from autoprint.ui.main_window import PrintBar
        self.assertIsNotNone(self.win.findChild(LibraryPanel))
        bar = self.win.findChild(PrintBar)
        self.assertIsNotNone(bar)
        self.assertTrue(bar.isHidden())
        self.assertEqual((self.win.width(), self.win.height()), (520, 720))
        import importlib.util
        for gone in ("control_strip", "template_view", "blocks", "prompter_window", "prompter_control",
                     "code_editor", "prompter"):
            self.assertIsNone(importlib.util.find_spec(f"autoprint.ui.{gone}"), gone)

    def test_open_lesson_sets_focus(self):
        self.assertTrue(self.win.open_lesson("M"))
        self.assertEqual(self.win.printer.focus_id, "M")
        self.assertEqual(self.opened, [1])
        self.assertEqual(self.win.settings.page_lesson, "M")

    def test_open_other_while_live_asks(self):
        from PySide6.QtWidgets import QMessageBox
        import autoprint.ui.main_window as MW
        self.win.efir.live_lesson_id = lambda: "L"
        stopped = []
        self.win.efir.stop_live = lambda: stopped.append(1)
        old = MW.QMessageBox.question
        try:
            MW.QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
            self.assertFalse(self.win.open_lesson("M"))
            self.assertEqual(stopped, [])
            self.assertEqual(self.opened, [])
            MW.QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
            self.assertTrue(self.win.open_lesson("M"))
            self.assertEqual(stopped, [1])
            self.assertEqual(self.win.printer.focus_id, "M")
        finally:
            MW.QMessageBox.question = old

    def test_library_meta(self):
        from autoprint.ui.library import ROLE_META
        it = self.win.library.list.item(0)
        self.assertEqual(it.data(ROLE_META), "15 мин · 2 этапа · 2 кода")
        self.assertEqual(self.win.library.list.item(1).data(ROLE_META), "без кода")

    def test_new_lesson_opens(self):
        n = len(self.win.store.templates)
        self.win.new_template()
        self.assertEqual(len(self.win.store.templates), n + 1)
        t = self.win.store.templates[-1]
        self.assertEqual(self.win.printer.focus_id, t.id)
        self.assertEqual(t.title, "Новый урок")

    def test_session_page(self):
        self.win.printer.set_focus("M")
        self.win.lesson.page_alive = lambda: True
        self.win._save_session()
        self.assertTrue(self.win.settings.page_open)
        self.assertEqual(self.win.settings.page_lesson, "M")


class LessonCtlTest(unittest.TestCase):
    def setUp(self):
        self.L = Template("Урок", [note(id="n1"), code("x = 1", id="c1")], id="L")
        self.M = Template("Второй", [code("y", id="c2")], id="M")
        self.win = make_window([self.L, self.M], port=18963)

    def tearDown(self):
        self.win._quitting = True
        self.win.close()
        pump()

    def test_current_is_focus(self):
        self.win.printer.set_focus("M")
        self.assertEqual(self.win.lesson.current().id, "M")
        self.win.efir.live_lesson_id = lambda: "L"
        self.win.printer.live_id = self.win.efir.live_lesson_id
        self.assertEqual(self.win.lesson.current().id, "L")

    def test_cmd_arm_note_ignored(self):
        self.win.printer.set_focus("L")
        self.win.lesson.command({"cmd": "arm", "block": "n1"})
        self.assertEqual(self.L.active_block, "")
        self.win.lesson.command({"cmd": "arm", "block": "c1"})
        self.assertEqual(self.L.active_block, "c1")


# ================================================================ Task 4: экспорт и .md

class ExportTest(unittest.TestCase):
    def test_students_code_only(self):
        from autoprint.importers import export_ipynb
        img = TMP / "pic.png"
        from PySide6.QtGui import QColor, QImage
        im = QImage(8, 8, QImage.Format.Format_RGB32)
        im.fill(QColor("#123456"))
        im.save(str(img))
        t = Template("Урок", [stage("Этап", 5), note("скажи это"), Block(BLOCK_IMAGE, str(img), title="Слайд"),
                              code("x = 1"), note("## Задание", role="task")])
        out = TMP / "kids.ipynb"
        export_ipynb(t, str(out), students=True)
        nb = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual([c["cell_type"] for c in nb["cells"]], ["code"])
        self.assertEqual("".join(nb["cells"][0]["source"]), "x = 1")

    def test_md_term_output_roundtrip(self):
        from autoprint import lesson_md
        term = "Функция\nименованный блок кода"
        t = Template("Урок", [stage("Теория", 8), note(term, role="term"),
                              code("print(2 + 2)"), note("4", role="output")])
        text = lesson_md.to_md(t, "x_files")
        self.assertIn("[!term]", text)
        self.assertIn("[!output]", text)
        back = lesson_md.parse(text, None, "Урок")
        got = [(b.type, b.role if b.type == BLOCK_MARKDOWN else "", b.text) for b in back.blocks if b.type != BLOCK_STAGE]
        self.assertEqual(got, [(BLOCK_MARKDOWN, "term", term), (BLOCK_CODE, "", "print(2 + 2)"),
                               (BLOCK_MARKDOWN, "output", "4")])
        self.assertEqual(lesson_md._role("Термин"), "term")
        self.assertEqual(lesson_md._role("вывод"), "output")


# ================================================================ Task 6: состояние экрана урока

def page_state(t, **kw):
    from autoprint import scenario
    args = dict(live_anchor_ms=None, armed="", media_url=lambda p: "/media/x/" + Path(p).name, presets=[],
                preset="", dark=True, efir_mode="idle", tab="", hotkey="Ctrl+F9")
    args.update(kw)
    return scenario.lesson_state(t, **args)


class StateTest(unittest.TestCase):
    def test_items_flat(self):
        t = Template("Урок", [note("привет", id="n1"), stage("Этап", 5, id="s1"), code("x = 1", id="c1"),
                              Block(BLOCK_IMAGE, "нет/такого.png", id="i1", title="Слайд")])
        st = page_state(t)
        items = st["lesson"]["items"]
        self.assertEqual([(i["id"], i["type"]) for i in items],
                         [("n1", "markdown"), ("s1", "stage"), ("c1", "code"), ("i1", "image")])
        c = items[2]
        self.assertEqual((c["text"], c["lang"], c["label"]), ("x = 1", "python", "Python"))
        self.assertIn("t-", c["html"])
        self.assertTrue(items[3]["missing"])
        self.assertEqual(items[1]["minutes"], 5)
        v_note, v_code, rev = items[0]["v"], items[2]["v"], st["lesson"]["rev"]
        t.blocks[2].text = "x = 2"
        st2 = page_state(t)
        self.assertNotEqual(st2["lesson"]["items"][2]["v"], v_code)
        self.assertEqual(st2["lesson"]["items"][0]["v"], v_note)
        self.assertNotEqual(st2["lesson"]["rev"], rev)

    def test_empty_blocks_present(self):
        t = Template("Урок", [note(""), code("")])
        self.assertEqual(len(page_state(t)["lesson"]["items"]), 2)     # пустые тоже: их правят на месте

    def test_term(self):
        t = Template("Урок", [note("Функция\nименованный блок кода", role="term")])
        it = page_state(t)["lesson"]["items"][0]
        self.assertEqual(it["term"], "Функция")
        self.assertIn("именованный", it["html"])
        self.assertNotIn("Функция", it["html"])

    def test_roles_and_lessons(self):
        from autoprint.storage import ROLE_MORE, ROLE_ORDER
        t = Template("Урок", [stage("A", 5), code("x")], id="L1")
        st = page_state(t, lessons=[{"id": "L1", "title": "Урок"}])
        self.assertEqual([r["key"] for r in st["roles"]], ROLE_ORDER + ROLE_MORE)
        self.assertEqual(st["roles"][0]["name"], "Говоришь")
        self.assertIn("дословно", st["roles"][0]["hint"])
        self.assertEqual(st["lessons"], [{"id": "L1", "title": "Урок"}])

    def test_print_in_state(self):
        a = code("a = 1", id="ca")
        L = Template("Урок", [note(id="n1"), a], id="L")
        win = make_window([L], port=18964)
        try:
            win.printer.set_focus("L")
            win.printer.arm("ca")
            win.lesson.publish()
            st = win.efir.server.snapshot("lesson")
            self.assertEqual(st["print"]["block"], "ca")
            self.assertEqual(st["armed"], "ca")
            self.assertEqual([x["id"] for x in st["lessons"]], ["L"])
            self.assertEqual(st["lessons"][0]["codes"], 1)
        finally:
            win._quitting = True
            win.close()
            pump()


if __name__ == "__main__":
    unittest.main(verbosity=2)
