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
        self.assertEqual(ROLES["output"][1], "Результат кода")       # 0.11: было «Вывод»
        self.assertEqual(set(ROLE_ORDER + ROLE_MORE), set(ROLES))
        self.assertEqual(len(ROLE_ORDER + ROLE_MORE), len(ROLES))
        self.assertEqual(ROLE_ORDER[0], "goal")                      # 0.11: группы, «Урок» первым
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

SEEN = ["steps_v1", "tour_v1", "lesson_v1", "lesson_v2", "lesson_v3", "plan_v1"]   # встроенные примеры уже добавлены — не мешают


def make_window(templates: list[Template], port: int = 18961):
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
    return App(s, store, web=False)     # 1.0: программа без старого окна Qt; страница — в тестах окна


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

    def test_engine_message(self):
        from pathlib import Path as P
        src = P(storage.__file__).with_name("typer.py").read_text(encoding="utf-8")
        self.assertIn("Поставьте курсор в Jupyter", src)


class WindowTest(unittest.TestCase):
    def setUp(self):
        self.L = Template("Идёт", [stage("A", 5), code("x", id="c1"), stage("B", 10), code("y")], id="L")
        self.M = Template("Другой", [note()], id="M")
        self.win = make_window([self.L, self.M], port=18962)
        self.opened: list[str] = []
        self.win.navigate.connect(self.opened.append)      # 1.0: урок открывается в окне программы

    def tearDown(self):
        self.win._quitting = True
        self.win.close()
        pump()

    def test_one_window(self):
        """1.0: одно окно со встроенным браузером; старого списка уроков и строки печати Qt нет."""
        from autoprint.ui.app_window import AppWindow
        self.assertIsInstance(self.win.window, AppWindow)
        import importlib.util
        for gone in ("control_strip", "template_view", "blocks", "prompter_window", "prompter_control",
                     "code_editor", "prompter", "main_window", "library"):
            self.assertIsNone(importlib.util.find_spec(f"autoprint.ui.{gone}"), gone)

    def test_open_lesson_sets_focus(self):
        self.assertTrue(self.win.open_lesson("M"))
        self.assertEqual(self.win.printer.focus_id, "M")
        self.assertEqual(self.opened, ["#/lesson/M"])
        self.assertEqual(self.win.settings.page_lesson, "M")

    def test_open_other_while_live_asks(self):
        """Идёт урок — другой урок сам не открывается: вопрос (с действием) уходит на страницу."""
        self.win.efir.live_lesson_id = lambda: "L"
        stopped = []
        self.win.efir.stop_live = lambda: stopped.append(1)
        self.assertFalse(self.win.open_lesson("M"))
        self.assertEqual(stopped, [])
        self.assertEqual(self.opened, [])
        self.assertEqual(self.win.notice["action"]["cmd"], {"cmd": "open", "lesson": "M", "force": True})
        self.assertTrue(self.win.open_lesson("M", ask=False))       # страница спросила — ответили «да»
        self.assertEqual(stopped, [1])
        self.assertEqual(self.win.printer.focus_id, "M")

    def test_new_lesson_opens(self):
        n = len(self.win.store.templates)
        self.win.new_template()
        self.assertEqual(len(self.win.store.templates), n + 1)
        t = self.win.store.templates[-1]
        self.assertEqual(self.win.printer.focus_id, t.id)
        self.assertEqual(t.title, "Новый урок")

    def test_session_page(self):
        self.win.printer.set_focus("M")
        self.win._save_session()
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
        say = next(r for r in st["roles"] if r["key"] == "say")
        self.assertEqual(say["name"], "Говоришь")
        self.assertIn("дословно", say["hint"])
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


# ================================================================ Task 12: оформление отдельно от расписаний

class LooksTest(unittest.TestCase):
    def setUp(self):
        self.dir = TMP / f"efir-{time.time_ns()}"
        self.dir.mkdir()

    def test_split_compose(self):
        from autoprint.efir.model import Activity, Exercise, Webinar, compose, split
        w = Webinar(title="1Т", schedule=[Activity("Теория", 20), Activity("Перерыв", 10, "break")],
                    background="anim:stars", caption="Сейчас начнём", exercises=[Exercise("Глаза", "C:/v.mp4")],
                    break_min=12, break_title="ОТДЫХ", text_color="#FFEE00")
        s, look = split(w)
        self.assertEqual((s.title, s.break_min, [a.name for a in s.schedule]), ("1Т", 12, ["Теория", "Перерыв"]))
        self.assertEqual((look.background, look.caption, look.break_title), ("anim:stars", "Сейчас начнём", "ОТДЫХ"))
        back = compose(s, look)
        a, b = w.to_dict(), back.to_dict()
        for d in (a, b):
            d.pop("id"); d.pop("look_id")
        self.assertEqual(a, b)

    def test_migration_from_webinars_json(self):
        from autoprint.efir.model import Activity, Webinar
        from autoprint.efir.store import WebinarStore
        old = [Webinar(title="Пара 1", schedule=[Activity("A", 10)], background="anim:cube", id="w1aaaa"),
               Webinar(title="Пара 2", schedule=[Activity("B", 20)], background="anim:cube", id="w2bbbb"),
               Webinar(title="Урок", schedule=[Activity("C", 5)], lesson_id="L1", id="wlesson")]
        raw = {"version": 1, "webinars": [w.to_dict() for w in old], "live": None}
        (self.dir / "webinars.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        before = (self.dir / "webinars.json").read_text(encoding="utf-8")
        s = WebinarStore(self.dir / "webinars.json")
        self.assertEqual(len(s.looks), 1)                                   # одинаковые оформления — одно
        self.assertEqual(s.looks[0].title, "Оформление · Пара 1")
        self.assertEqual([w.title for w in s.visible()], ["Пара 1", "Пара 2"])
        self.assertTrue(all(w.look_id == s.looks[0].id for w in s.visible()))
        self.assertIsNone(s.get("wlesson"))                                  # служебный эфир урока не переносится
        self.assertTrue((self.dir / "schedules.json").exists() and (self.dir / "looks.json").exists())
        self.assertEqual((self.dir / "webinars.json").read_text(encoding="utf-8"), before)   # откат на 0.9
        s.put(s.get("w1aaaa"))
        again = WebinarStore(self.dir / "webinars.json")
        self.assertEqual([w.id for w in again.visible()], ["w1aaaa", "w2bbbb"])
        self.assertEqual(len(again.looks), 1)
        self.assertEqual((self.dir / "webinars.json").read_text(encoding="utf-8"), before)

    def test_put_look_updates_schedules(self):
        from autoprint.efir.model import Activity, Webinar
        from autoprint.efir.store import WebinarStore
        s = WebinarStore(self.dir / "webinars.json")
        s.add([Webinar(title="Пара", schedule=[Activity("A", 10)])])
        w = s.visible()[0]
        look = s.look(w.look_id)
        look.background = "anim:aurora"
        s.put_look(look)
        self.assertEqual(s.get(w.id).background, "anim:aurora")
        self.assertEqual(WebinarStore(self.dir / "webinars.json").get(w.id).background, "anim:aurora")
        self.assertFalse(s.remove_look(look.id))                             # расписание ссылается — нельзя
        self.assertIsNotNone(s.look(look.id))

    def test_lesson_webinar(self):
        from autoprint.efir.model import Look
        from autoprint.scenario import webinar_for
        t = Template("Урок", [stage("Теория", 20), stage("Перерыв", 15, stage_kind="break"), stage("Практика", 30)])
        look = Look(title="ФУ", background="anim:stars")
        w = webinar_for(t, look)
        self.assertEqual((w.break_min, w.background, w.look_id), (15, "anim:stars", look.id))
        t2 = Template("Без перерыва", [stage("Теория", 20)])
        self.assertEqual(webinar_for(t2, None).break_min, 10)


def efir_controller(name: str, port: int):
    """«Эфир» на своей временной папке (без главного окна)."""
    from autoprint.efir import store as store_mod
    from autoprint.ui.efir_control import EfirController

    class Main:
        settings = Settings()
    Main.settings.efir_port = port
    folder = TMP / f"efir-{name}-{time.time_ns()}"
    old = store_mod.efir_dir
    store_mod.efir_dir = lambda: folder
    try:
        ctl = EfirController(None)
    finally:
        store_mod.efir_dir = old
    ctl.settings = Main.settings
    return ctl


class EfirWindowTest(unittest.TestCase):
    """Task 15: окно «Эфир» — «Расписания» и «Оформления»."""

    def setUp(self):
        from autoprint.efir.model import Activity, Webinar
        self.ctl = efir_controller("win", 18970)
        self.w = self.ctl.store.add([Webinar(title="Пара 1Т", schedule=[Activity("Теория", 40)],
                                             background="anim:stars")])[0]

    def tearDown(self):
        for ed in list(self.ctl.editors):
            ed._dirty = False
            ed.close()
        if self.ctl.window is not None:
            self.ctl.window.close()
        self.ctl.server.stop()
        pump()

    def test_tabs(self):
        from autoprint.ui.efir_window import LookCard, WebinarCard
        self.ctl.show_window()
        win = self.ctl.window
        pump()
        self.assertEqual([c.w.title for c in win.findChildren(WebinarCard)], ["Пара 1Т"])
        win.tabs.set_value("looks")
        win.refill()
        pump()
        self.assertEqual(len(win.findChildren(LookCard)), 1)
        self.assertFalse(win.btn_import.isVisibleTo(win))

    def test_look_editor_saves(self):
        self.ctl.edit_look(self.w.look_id)
        led = self.ctl.editors[-1]
        led.bg.set_value("anim:aurora")
        led.save()
        self.assertEqual(self.ctl.store.look(self.w.look_id).background, "anim:aurora")
        self.assertEqual(self.ctl.store.get(self.w.id).background, "anim:aurora")     # расписание видит новое
        self.assertEqual([a.name for a in self.ctl.store.get(self.w.id).schedule], ["Теория"])

    def test_cant_delete_used_look(self):
        from PySide6.QtWidgets import QMessageBox
        import autoprint.ui.efir_window as EW
        self.ctl.show_window()
        shown = []
        old = EW.QMessageBox.information
        EW.QMessageBox.information = staticmethod(lambda *a, **k: shown.append(a[1]) or QMessageBox.StandardButton.Ok)
        try:
            self.ctl.window.remove_look(self.w.look_id)
        finally:
            EW.QMessageBox.information = old
        self.assertTrue(shown)
        self.assertIsNotNone(self.ctl.store.look(self.w.look_id))

    def test_schedule_editor_picks_look(self):
        from autoprint.efir.model import Look
        other = Look(title="ФУ", background="anim:cube")
        self.ctl.store.put_look(other)
        self.ctl.edit(self.w.id)
        ed = self.ctl.editors[-1]
        self.assertFalse(ed.bg.isVisibleTo(ed))                                     # фона в расписании нет
        ed.look_combo.setCurrentIndex(ed.look_combo.findData(other.id))
        ed.save()
        w = self.ctl.store.get(self.w.id)
        self.assertEqual((w.look_id, w.background), (other.id, "anim:cube"))


# ================================================================ Task 13: ошибки «Эфира» из разбора

class FixTest(unittest.TestCase):
    def test_anchor_rule(self):
        from datetime import datetime
        from autoprint.efir.model import anchor_at
        d = datetime(2026, 11, 24, 7, 0)
        self.assertEqual(anchor_at("20:00", d), datetime(2026, 11, 24, 20, 0))      # за 13 ч — сегодня, не вчера
        self.assertEqual(anchor_at("20:00", datetime(2026, 11, 24, 20, 20)), datetime(2026, 11, 24, 20, 0))
        self.assertEqual(anchor_at("00:10", datetime(2026, 11, 24, 23, 50)), datetime(2026, 11, 25, 0, 10))
        self.assertEqual(anchor_at("23:50", datetime(2026, 11, 25, 3, 0)), datetime(2026, 11, 24, 23, 50))
        self.assertEqual(anchor_at("08:00", datetime(2026, 11, 24, 15, 0)), datetime(2026, 11, 25, 8, 0))

    def lesson_window(self, port):
        t = Template("Урок", [stage("A", 10, id="sA"), stage("B", 10, id="sB"), stage("C", 10, id="sC")], id="LT")
        win = make_window([t], port=port)
        win.printer.set_focus("LT")
        return win, t

    def close(self, win):
        win.efir.stop_live()
        win.efir.shutdown()
        win._quitting = True
        win.close()
        pump()

    def test_live_edit_keeps_stage(self):
        from datetime import datetime, timedelta
        win, t = self.lesson_window(18975)
        try:
            win.lesson.command({"cmd": "start"})
            store = win.efir.store
            anchor = datetime.now().replace(microsecond=0) - timedelta(minutes=15)      # идёт этап B с 5-й минуты
            store.set_live(store.live.webinar_id, anchor)
            win.lesson.publish()
            t.find_block("sA").minutes = 20
            win.lesson.publish()
            self.assertEqual(store.live.anchor, anchor - timedelta(minutes=10))           # B — на тех же часах
            self.assertEqual(win.efir.live_webinar().schedule[0].min, 20)
            t.blocks.remove(t.find_block("sB"))                                            # удалили текущий этап
            before = store.live.anchor
            win.lesson.publish()
            self.assertEqual(store.live.anchor, before)
        finally:
            self.close(win)

    def test_break_until_stage_end(self):
        from datetime import datetime, timedelta
        win, t = self.lesson_window(18976)
        try:
            t.find_block("sB").stage_kind = "break"
            win.lesson.command({"cmd": "start"})
            store = win.efir.store
            anchor = datetime.now().replace(microsecond=0) - timedelta(minutes=13)        # перерыв идёт 3 минуты
            store.set_live(store.live.webinar_id, anchor)
            win.lesson.command({"cmd": "break", "stage": "sB", "minutes": 10})
            end = (anchor + timedelta(minutes=20)).timestamp()
            self.assertEqual(win.efir.mode, "break")
            self.assertLess(abs(win.efir.brk_ends - end), 2)
            win.efir.show_background()
            win.lesson.command({"cmd": "break"})                                           # вне плана
            self.assertAlmostEqual(win.efir.brk_total, 600, delta=1)                       # break_min урока — 10
        finally:
            self.close(win)

    def test_break_auto_background(self):
        ctl = efir_controller("auto", 18977)
        from autoprint.efir.model import Activity, Webinar
        w = ctl.store.add([Webinar(title="Пара", schedule=[Activity("A", 30)])])[0]
        ctl.launch(w.id, "")
        ctl.start_break(1)
        ctl.brk_ends = time.time() - 61
        ctl._tick()
        self.assertEqual(ctl.mode, "idle")
        self.assertIsNone(ctl.store.brk)
        ctl.stop_live()
        ctl.server.stop()

    def test_replace_asks(self):
        ctl = efir_controller("replace", 18978)
        from autoprint.efir.model import Activity, Webinar
        a, b = ctl.store.add([Webinar(title="A", schedule=[Activity("x", 30)]),
                              Webinar(title="B", schedule=[Activity("y", 30)])])
        asked = []
        ctl.confirm_replace = lambda cur, new: asked.append((cur, new)) or False
        ctl.launch(a.id, "")
        self.assertEqual(asked, [])
        ctl.launch(b.id, "")
        self.assertEqual(asked, [("A", "B")])
        self.assertEqual(ctl.live_webinar().id, a.id)
        ctl.confirm_replace = lambda cur, new: True
        ctl.launch(b.id, "")
        self.assertEqual(ctl.live_webinar().id, b.id)
        ctl.stop_live()
        ctl.server.stop()

    def test_restart_keeps_break(self):
        from autoprint.efir import store as store_mod
        from autoprint.efir.model import Activity, Webinar
        from autoprint.ui.efir_control import EfirController
        ctl = efir_controller("restart", 18979)
        folder = ctl.store.path.parent
        w = ctl.store.add([Webinar(title="Пара", schedule=[Activity("A", 60)])])[0]
        ctl.launch(w.id, "")
        ctl.start_break(10)
        ends = ctl.brk_ends
        ctl.timer_window and ctl.timer_window.close_silently()
        ctl.server.stop()
        old = store_mod.efir_dir
        store_mod.efir_dir = lambda: folder
        try:
            ctl2 = EfirController(None)
        finally:
            store_mod.efir_dir = old
        ctl2.settings = ctl.settings
        ctl2.show_timer = lambda: None
        ctl2.ensure_server()
        self.assertEqual(ctl2.server.snapshot("screen")["mode"], "wait")       # до восстановления — прежний кадр
        ctl2.restore()
        self.assertEqual(ctl2.mode, "break")
        self.assertAlmostEqual(ctl2.brk_ends, ends, delta=1)
        self.assertEqual(ctl2.server.snapshot("screen")["mode"], "break")
        ctl2.stop_live()
        ctl2.server.stop()

    def test_stale_exercise_keeps_break(self):
        ctl = efir_controller("stale", 18980)
        from autoprint.efir.model import Activity, Webinar
        w = ctl.store.add([Webinar(title="Пара", schedule=[Activity("A", 30)])])[0]
        ctl.launch(w.id, "")
        ctl.ex_index = 3
        ctl.start_break(5)
        ctl.refresh_live()
        self.assertEqual(ctl.mode, "break")
        ctl.stop_live()
        ctl.server.stop()

    def test_editor_cancel_asks(self):
        from PySide6.QtWidgets import QMessageBox
        import autoprint.ui.efir_editor as ED
        ctl = efir_controller("cancel", 18981)
        from autoprint.efir.model import Activity, Webinar
        w = ctl.store.add([Webinar(title="Пара", schedule=[Activity("A", 30)])])[0]
        ctl.edit_look(w.look_id)
        led = ctl.editors[-1]
        led.caption.setText("Новая надпись")
        led.caption.textEdited.emit("Новая надпись")                 # как при наборе с клавиатуры
        asked = []
        old = ED.QMessageBox.question
        ED.QMessageBox.question = staticmethod(lambda *a, **k: asked.append(a[1]) or QMessageBox.StandardButton.Discard)
        try:
            led.close()
        finally:
            ED.QMessageBox.question = old
        self.assertTrue(asked)
        ctl.server.stop()


# ================================================================ Task 16, 17: образцовый урок, примеры в базе

class SampleLessonTest(unittest.TestCase):
    def test_example(self):
        import contextlib
        import io
        import re
        from autoprint import scenario
        from autoprint.samples_lesson import LESSON_SAMPLE_ID, LESSON_TITLE, lesson_sample
        from autoprint.storage import ROLE_ORDER, media_path
        self.assertEqual(LESSON_SAMPLE_ID, "lesson_v3")
        t = lesson_sample()
        self.assertEqual(t.title, LESSON_TITLE)
        self.assertEqual(scenario.total_minutes(t), 90)
        stages = [b for b in t.blocks if b.type == BLOCK_STAGE]
        self.assertEqual(len(stages), 12)
        self.assertEqual(sorted(b.stage_kind for b in stages if b.stage_kind), ["break", "exercise"])
        self.assertEqual({b.part for b in stages}, {"Первая половина", "Вторая половина"})
        roles = {b.role for b in t.blocks if b.type == BLOCK_MARKDOWN}
        self.assertTrue(set(ROLE_ORDER) <= roles, set(ROLE_ORDER) - roles)
        codes = [i for i, b in enumerate(t.blocks) if b.type == BLOCK_CODE]
        self.assertGreaterEqual(len(codes), 5)
        imgs = [b for b in t.blocks if b.type == BLOCK_IMAGE]
        self.assertEqual(len(imgs), 3)
        self.assertTrue(all(media_path(b.text) for b in imgs), [b.text for b in imgs])
        ns: dict = {}
        for i in codes:
            out_block = t.blocks[i + 1]
            self.assertEqual((out_block.type, out_block.role), (BLOCK_MARKDOWN, "output"), t.blocks[i].title)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                exec(t.blocks[i].text, ns)                          # весь код урока — рабочий, по порядку
            want = re.sub(r"^```\w*\n|\n?```$", "", out_block.text.strip()).strip()
            self.assertEqual(buf.getvalue().strip(), want, t.blocks[i].title)

    def test_example_file_in_examples(self):
        """examples/ — тот же урок, что встроен в программу (его можно открыть в любом редакторе)."""
        root = Path(storage.__file__).resolve().parent.parent
        src = (root / "autoprint" / "samples" / "lesson-example.md").read_text(encoding="utf-8")
        ex = root / "examples" / "Пример урока — функции и пароль.md"
        self.assertEqual(ex.read_text(encoding="utf-8"), src)
        self.assertTrue((root / "examples" / "lesson-example_files" / "func-scheme.png").exists())


class SamplesMigrationTest(unittest.TestCase):
    def test_exact_sample_copies_removed(self):
        from autoprint import migrations
        from autoprint.samples_lesson import LESSON_TITLE
        storage.TEMPLATES_FILE.unlink(missing_ok=True)
        storage.TEMPLATES_FILE.with_suffix(".json.bak").unlink(missing_ok=True)
        store = TemplateStore()
        old = Template("Пример: пошаговый урок", [Block(BLOCK_MARKDOWN, "Так записывают урок…", role="explain"),
                                                  code("x = 1", steps=[1])], id="old")
        edited = Template(old.title, [Block(BLOCK_MARKDOWN, "Так записывают урок… (моя правка)", role="explain"),
                                      code("x = 1", steps=[1])], id="edited")
        store.templates = [old, edited, Template("Мой урок", [note("моё")], id="mine")]
        keep = migrations.SAMPLE_FINGERPRINTS
        migrations.SAMPLE_FINGERPRINTS = frozenset({migrations.fingerprint(old)})   # точная копия — по отпечатку
        try:
            s = Settings()
            s.migrations = ["tray_v1", "window_v10", "roles_v10"]
            migrations.apply(s, store)
            self.assertEqual([t.id for t in store.templates], ["edited", "mine"])      # изменённую копию не трогаем
            self.assertIn("samples_v10", s.migrations)
            self.assertFalse(migrations.apply(s, store))
        finally:
            migrations.SAMPLE_FINGERPRINTS = keep

    def test_real_fingerprints(self):
        from autoprint import migrations
        self.assertEqual(len(migrations.SAMPLE_FINGERPRINTS), 3)
        self.assertIn("01a2940b7512461244c0ce21258cb21b72690369", migrations.SAMPLE_FINGERPRINTS)


# ================================================================ Task 18: сценарные тетрадки → урок

SCENARIO_CELLS = [
    ("markdown", "# 🎬 Занятие 7\n\n## Тема: функции\n\n### 🔑 Как читать этот файл\n\n| Значок | Что значит |\n|---|---|\n"
                 "| 🗣 | говоришь |"),
    ("code", "def set_input(*lines):\n    pass"),
    ("markdown", "---\n---\n# 🟦 ПЕРВАЯ ПОЛОВИНА — 45 минут\n---\n# ⏱ 00:00–00:03 · Приветствие и цель\n\n"
                 "🗣 **Говоришь:**\n\n> Добрый день. Сегодня — функции.\n> Начнём с разминки."),
    ("markdown", "---\n# ⏱ 00:03–00:08 · Разминка, 5 вопросов\n\n🗣 **Говоришь:**\n\n> Пять вопросов, отвечаем вслух."),
    ("markdown", "---\n# ⏱ 00:08–00:18 · Разбор 1. Проверка события\n\n🗣 **Говоришь:**\n\n> Первая задача."),
    ("code", "def ok(x):\n    return x > 0"),
    ("markdown", "🗣 **Говоришь, показывая на код:**\n\n> Смотрите, как устроена функция."),
    ("code", "print(ok(5))"),
    ("markdown", "✅ **Ожидаемый вывод:** `True`\n\n🗣 **Говоришь при разборе:**\n\n> Разберём построчно."),
    ("markdown", "**Решение — показываешь через 4 минуты:**\n\n👀 **Показываешь строку с return.**\n\n"
                 "⌨️ **Печатаешь шаг 2:**"),
    ("markdown", "---\n---\n# 🧘 ⏱ 00:18–00:23 · ЗАРЯДКА ДЛЯ ГЛАЗ, 5 МИНУТ\n\n🗣 **Говоришь:**\n\n> Пауза на пять минут."),
    ("markdown", "---\n---\n# 🧘 ⏱ 00:23–00:33 · ПЕРЕРЫВ 10 МИНУТ\n\n🗣 **Говоришь:**\n\n> Перерыв десять минут."),
    ("markdown", "---\n---\n# 🟩 ВТОРАЯ ПОЛОВИНА — 45 минут\n---\n# ✍️ ⏱ 00:33–00:40 · Мини-задание 1\n\n"
                 "🗣 **Говоришь:**\n\n> Пробуете сами.\n\nℹ️ Функцию переопределяем ниже."),
]


def scenario_template() -> Template:
    blocks = [Block(BLOCK_MARKDOWN if k == "markdown" else BLOCK_CODE, text, role="text") for k, text in SCENARIO_CELLS]
    return Template("Занятие 7", blocks)


class ScenarioTest(unittest.TestCase):
    def test_looks_like_scenario(self):
        from autoprint.scenario_import import looks_like_scenario
        self.assertTrue(looks_like_scenario(scenario_template().blocks))
        self.assertFalse(looks_like_scenario([note("# ⏱ 00:00–00:05 · Один этап")]))

    def test_stages(self):
        from autoprint.scenario_import import recognize
        r = recognize(scenario_template())
        st = [b for b in r.blocks if b.type == BLOCK_STAGE]
        self.assertEqual([(b.title, b.minutes) for b in st],
                         [("Приветствие и цель", 3), ("Разминка, 5 вопросов", 5), ("Разбор 1. Проверка события", 10),
                          ("Зарядка для глаз, 5 минут", 5), ("Перерыв 10 минут", 10), ("Мини-задание 1", 7)])
        self.assertEqual([b.stage_kind for b in st], ["", "", "", "exercise", "break", ""])
        self.assertEqual([b.part for b in st], ["Первая половина"] * 5 + ["Вторая половина"])
        self.assertEqual(st[-1].text, "задание")

    def test_roles(self):
        from autoprint.scenario_import import recognize
        r = recognize(scenario_template())
        notes = [(b.role, b.title, b.text) for b in r.blocks if b.type == BLOCK_MARKDOWN]
        self.assertIn(("say", "", "Добрый день. Сегодня — функции.\nНачнём с разминки."), notes)
        self.assertIn(("say", "показывая на код", "Смотрите, как устроена функция."), notes)
        self.assertIn(("output", "", "True"), notes)
        self.assertIn(("say", "при разборе", "Разберём построчно."), notes)
        self.assertIn(("do", "", "Решение — показываешь через 4 минуты"), notes)
        self.assertIn(("text", "", "Функцию переопределяем ниже."), notes)
        self.assertIn(("show", "", "**Показываешь строку с return.**"), notes)
        self.assertIn(("do", "", "**Печатаешь шаг 2:**"), notes)
        codes = [b.text for b in r.blocks if b.type == BLOCK_CODE]
        self.assertEqual(codes, ["def set_input(*lines):\n    pass", "def ok(x):\n    return x > 0", "print(ok(5))"])
        first_stage = next(i for i, b in enumerate(r.blocks) if b.type == BLOCK_STAGE)
        self.assertEqual(r.blocks[first_stage - 1].text, "def set_input(*lines):\n    pass")   # служебное — до урока
        self.assertTrue(any("Как читать" in b.text for b in r.blocks[:first_stage]))

    def test_copy(self):
        from autoprint.scenario_import import recognize
        t = scenario_template()
        before = [(b.type, b.text) for b in t.blocks]
        r = recognize(t)
        self.assertEqual([(b.type, b.text) for b in t.blocks], before)
        self.assertEqual(r.title, "Занятие 7 (сценарий)")
        self.assertNotEqual(r.id, t.id)

    def test_recognize_command(self):
        t = scenario_template()
        t.id = "SC"
        win = make_window([t], port=18983)
        win.lesson.open_page = lambda: None
        try:
            win.printer.set_focus("SC")
            win.lesson.command({"cmd": "recognize"})
            self.assertEqual(len(win.store.templates), 2)
            new = win.store.templates[1]
            self.assertEqual(new.title, "Занятие 7 (сценарий)")
            self.assertEqual(win.printer.focus_id, new.id)
            self.assertEqual(win.store.templates[0].blocks[0].type, BLOCK_MARKDOWN)    # исходник не тронут
        finally:
            win._quitting = True
            win.close()
            pump()

    def test_import_ipynb_recognizes(self):
        from autoprint.importers import import_ipynb
        nb = {"cells": [{"cell_type": k, "source": text, "metadata": {}, **({"outputs": [], "execution_count": None}
                         if k == "code" else {})} for k, text in SCENARIO_CELLS],
              "metadata": {"language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
        path = TMP / "Занятие 7.ipynb"
        path.write_text(json.dumps(nb, ensure_ascii=False), encoding="utf-8")
        t = import_ipynb(str(path))
        self.assertEqual(sum(b.type == BLOCK_STAGE for b in t.blocks), 6)
        self.assertEqual(t.title, "Занятие 7")


# ================================================================ Task 19: нейросеть, версия, чистка

class AiTest(unittest.TestCase):
    def test_prompt_roles(self):
        from autoprint import lesson_ai as L
        opt = L.Options(style=L.STYLE_SCENARIO)
        text = L.build_prompt("Материал урока", opt)
        self.assertIn("[!term]", text)                 # 0.12: Markdown, как свой чат
        self.assertIn("[!output]", text)
        self.assertIn("печатает только код", text)
        self.assertIn("обязательно и дословно", text)
        self.assertIn("своими словами", text)
        self.assertNotIn("Условие", text)

    def test_parse_new_roles(self):
        from autoprint import lesson_ai as L
        r = L.parse_lesson('{"format": "%s", "version": 2, "title": "Т", "blocks": ['
                           '{"type": "stage", "title": "А", "min": 5},'
                           '{"type": "term", "text": "Функция\\nблок кода"},'
                           '{"type": "code", "lang": "python", "code": "print(1)"},'
                           '{"type": "output", "text": "1"},'
                           '{"type": "вывод", "text": "1"}, {"type": "термин", "text": "X\\nY"}]}' % L.FORMAT, "Т")
        roles = [b.role for b in r.template.blocks if b.type == BLOCK_MARKDOWN]
        self.assertEqual(roles, ["term", "output", "output", "term"])


class VersionTest(unittest.TestCase):
    def test_version(self):
        import autoprint
        self.assertGreaterEqual(tuple(map(int, autoprint.__version__.split("."))), (0, 10, 0))

    def test_dead_code_gone(self):
        root = Path(storage.__file__).resolve().parent
        files = {f.name: f.read_text(encoding="utf-8") for f in root.rglob("*.py") if f.name != "textprint.py"}
        hits = [(dead, name) for dead in ("store_image_file", "auto_advance", "show_prompter", "prompter_mode",
                                          "PRINT_MARKDOWN", "anchor_for(", "next_in_s", "lesson_clients",
                                          "steps_sample_template", "tour_template")
                for name, src in files.items() if dead in src]
        self.assertEqual(hits, [])         # textprint.py остаётся для эталонов веб-версии

    def test_readme_current(self):
        """README описывает 0.10: картинки на месте, нет пульта, окна суфлёра и удалённых примеров."""
        import re
        root = Path(storage.__file__).resolve().parent.parent
        text = (root / "README.md").read_text(encoding="utf-8")
        missing = [p for p in re.findall(r"docs/images/[\w.-]+\.png", text) if not (root / p).exists()]
        self.assertEqual(missing, [])
        stale = [w for w in ("пульт", "Суфлёр в отдельном окне", "Без комментариев", "Пример занятия",
                             "make_screenshots", "тёмная тема.md", "tests/test_ui.py") if w in text]
        self.assertEqual(stale, [])

    def test_ui_texts_current(self):
        """Справка и окно импорта не ссылаются на ленту блоков, янтарную рамку и «Суфлёр урока» в шапке занятия."""
        root = Path(storage.__file__).resolve().parent / "ui"
        src = (root / "settings_window.py").read_text(encoding="utf-8") + (
            root.parent / "efir" / "page" / "app" / "wizard.js").read_text(encoding="utf-8")      # 1.0: «Новый урок»
        stale = [w for w in ("янтарная рамка", "Занятие — лента", "на суфлёре", "в шапке занятия",
                             "Добавить занятие") if w in src]
        self.assertEqual(stale, [])


# ================================================================ Task 7: правки урока со страницы

class EditTest(unittest.TestCase):
    """lesson_edit.apply — действия страницы над уроком, без Qt."""

    def lesson(self):
        return Template("Урок", [note("до этапа", id="n0"), stage("A", 5, id="sA"), note("в A", id="nA"),
                                 code("a = 1", id="cA"), stage("B", 10, id="sB"), note("в B", id="nB")])

    def ids(self, t):
        return [b.id for b in t.blocks]

    def test_set_text_and_fields(self):
        from autoprint import lesson_edit
        t = self.lesson()
        got = lesson_edit.apply(t, [{"op": "set", "block": "nA", "fields": {"text": "новый", "role": "ask",
                                                                            "title": "Вопрос"}},
                                    {"op": "set", "block": "sB", "fields": {"minutes": 12, "stage_kind": "break"}},
                                    {"op": "set", "block": "cA", "fields": {"steps": [1, 2], "sel": [0, 3],
                                                                            "lang": "javascript"}}])
        self.assertEqual(set(got), {"nA", "sB", "cA"})
        b = t.find_block("nA")
        self.assertEqual((b.text, b.role, b.title), ("новый", "ask", "Вопрос"))
        self.assertEqual((t.find_block("sB").minutes, t.find_block("sB").stage_kind), (12, "break"))
        c = t.find_block("cA")
        self.assertEqual((c.steps, c.sel, c.lang), ([1, 2], [0, 3], "javascript"))

    def test_bad_op_changes_nothing(self):
        from autoprint import lesson_edit
        t = self.lesson()
        before = [(b.id, b.text, b.role) for b in t.blocks]
        for ops in ([{"op": "set", "block": "nA", "fields": {"text": "x"}},
                     {"op": "set", "block": "nA", "fields": {"role": "zzz"}}],
                    [{"op": "set", "block": "nA", "fields": {"minutes": 5}}],          # у заметки нет минут
                    [{"op": "set", "block": "sA", "fields": {"minutes": 9999}}],
                    [{"op": "insert", "after": "", "block": {"id": "bad id!", "type": "markdown"}}],
                    [{"op": "insert", "after": "", "block": {"id": "aaaaaaaaaaaa", "type": "video"}}],
                    [{"op": "zzz"}],
                    [{"op": "set_lesson", "title": "   "}]):
            with self.assertRaises(ValueError):
                lesson_edit.apply(t, ops)
            self.assertEqual([(b.id, b.text, b.role) for b in t.blocks], before)

    def test_insert_idempotent(self):
        from autoprint import lesson_edit
        t = self.lesson()
        op = {"op": "insert", "after": "nA", "block": {"id": "aaaaaaaaaaaa", "type": "markdown", "role": "say",
                                                        "text": "новая"}}
        lesson_edit.apply(t, [op])
        lesson_edit.apply(t, [op])                       # повтор после обрыва связи — второй блок не появляется
        self.assertEqual(self.ids(t).count("aaaaaaaaaaaa"), 1)
        self.assertEqual(self.ids(t).index("aaaaaaaaaaaa"), self.ids(t).index("nA") + 1)
        lesson_edit.apply(t, [{"op": "insert", "after": "", "block": {"id": "bbbbbbbbbbbb", "type": "stage",
                                                                      "title": "Начало", "minutes": 3}}])
        self.assertEqual(t.blocks[0].id, "bbbbbbbbbbbb")
        self.assertEqual(t.blocks[0].minutes, 3)

    def test_delete_stage_keeps_blocks(self):
        from autoprint import lesson_edit
        t = self.lesson()
        lesson_edit.apply(t, [{"op": "delete", "block": "sB"}])
        self.assertEqual(self.ids(t), ["n0", "sA", "nA", "cA", "nB"])
        lesson_edit.apply(t, [{"op": "delete", "block": "sB"}])     # повтор — ничего
        self.assertEqual(len(t.blocks), 5)

    def test_move(self):
        from autoprint import lesson_edit
        t = self.lesson()
        lesson_edit.apply(t, [{"op": "move", "block": "nA", "after": "cA"}])
        self.assertEqual(self.ids(t), ["n0", "sA", "cA", "nA", "sB", "nB"])
        lesson_edit.apply(t, [{"op": "move", "block": "nB", "after": ""}])
        self.assertEqual(self.ids(t)[0], "nB")

    def test_move_stage(self):
        from autoprint import lesson_edit
        t = self.lesson()
        lesson_edit.apply(t, [{"op": "move_stage", "stage": "sA", "after_stage": "sB"}])
        self.assertEqual(self.ids(t), ["n0", "sB", "nB", "sA", "nA", "cA"])
        lesson_edit.apply(t, [{"op": "move_stage", "stage": "sA", "after_stage": ""}])
        self.assertEqual(self.ids(t), ["n0", "sA", "nA", "cA", "sB", "nB"])

    def test_restore(self):
        from autoprint import lesson_edit
        from dataclasses import asdict
        t = self.lesson()
        snap = asdict(t.find_block("cA"))
        lesson_edit.apply(t, [{"op": "delete", "block": "cA"}])
        lesson_edit.apply(t, [{"op": "restore", "block": snap, "after": "nA"}])
        self.assertEqual(self.ids(t), ["n0", "sA", "nA", "cA", "sB", "nB"])
        self.assertEqual(t.find_block("cA").text, "a = 1")

    def test_set_lesson_title(self):
        from autoprint import lesson_edit
        t = self.lesson()
        lesson_edit.apply(t, [{"op": "set_lesson", "title": "Новое название"}])
        self.assertEqual(t.title, "Новое название")


def post(port: int, path: str, body: bytes, headers: dict | None = None) -> tuple[int, dict]:
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Content-Type": "application/json", "X-Suflor": "1"}
    h.update(headers or {})
    h = {k: v for k, v in h.items() if v is not None}
    c.request("POST", path, body=body, headers=h)
    r = c.getresponse()
    raw = r.read()
    c.close()
    try:
        return r.status, json.loads(raw.decode("utf-8") or "{}")
    except ValueError:
        return r.status, {}


def get(port: int, path: str) -> tuple[int, str, bytes]:
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", path)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, r.getheader("Content-Type") or "", data


def call_in_thread(fn):
    """Запрос к серверу — из другого потока, а этот (интерфейс) крутит цикл событий: правку применяет он."""
    import threading
    out = {}
    th = threading.Thread(target=lambda: out.setdefault("r", fn()), daemon=True)
    th.start()
    end = time.time() + 10
    while th.is_alive() and time.time() < end:
        app.processEvents()
        time.sleep(0.005)
    return out.get("r")


class EditServerTest(unittest.TestCase):
    PORT = 18965

    @classmethod
    def setUpClass(cls):
        cls.t = Template("Урок", [stage("A", 5, id="sA"), note("привет", id="nA"), code("a = 1", id="cA")], id="L")
        cls.win = make_window([cls.t], port=cls.PORT)
        cls.win.printer.set_focus("L")
        cls.win.efir.ensure_server()
        cls.port = cls.win.efir.server.port

    @classmethod
    def tearDownClass(cls):
        cls.win.efir.shutdown()
        cls.win._quitting = True
        cls.win.close()
        pump()

    def edit(self, ops, headers=None, raw: bytes | None = None):
        body = raw if raw is not None else json.dumps({"lesson": "L", "ops": ops}).encode("utf-8")
        return call_in_thread(lambda: post(self.port, "/lesson/edit", body, headers))

    def test_edit_roundtrip(self):
        code_, res = self.edit([{"op": "set", "block": "nA", "fields": {"text": "**жирный** текст"}}])
        self.assertEqual(code_, 200, res)
        self.assertTrue(res["ok"])
        self.assertIn("<b>жирный</b>", res["items"]["nA"]["html"])
        self.assertEqual(self.t.find_block("nA").text, "**жирный** текст")
        self.assertIn("rev", res)

    def test_edit_delete_returns_null(self):
        self.edit([{"op": "insert", "after": "nA", "block": {"id": "cccccccccccc", "type": "markdown"}}])
        code_, res = self.edit([{"op": "delete", "block": "cccccccccccc"}])
        self.assertEqual(code_, 200)
        self.assertIsNone(res["items"]["cccccccccccc"])

    def test_edit_guards(self):
        self.assertEqual(self.edit([], headers={"X-Suflor": None})[0], 403)
        self.assertEqual(self.edit([], headers={"Origin": "http://evil.example"})[0], 403)
        big = b'{"lesson": "L", "ops": [], "pad": "' + b"x" * (3 * 1024 * 1024) + b'"}'
        self.assertEqual(self.edit(None, raw=big)[0], 413)
        code_, res = self.edit([{"op": "set", "block": "nA", "fields": {"role": "zzz"}}])
        self.assertEqual(code_, 400)
        self.assertFalse(res["ok"])

    def test_upload(self):
        from PySide6.QtCore import QBuffer, QIODevice
        from PySide6.QtGui import QColor, QImage
        im = QImage(2, 2, QImage.Format.Format_RGB32)
        im.fill(QColor("#ff0000"))
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        im.save(buf, "PNG")
        png = bytes(buf.data())
        code_, res = call_in_thread(lambda: post(self.port, "/lesson/upload?lesson=L&after=nA&id=dddddddddddd", png,
                                                 {"Content-Type": "image/png"}))
        self.assertEqual(code_, 200, res)
        ids = [b.id for b in self.t.blocks]
        self.assertEqual(ids[ids.index("nA") + 1], "dddddddddddd")
        b = self.t.find_block("dddddddddddd")
        self.assertEqual(b.type, BLOCK_IMAGE)
        self.assertTrue(storage.media_path(b.text).is_file())
        self.assertFalse(res["item"]["missing"])
        code_, _ = call_in_thread(lambda: post(self.port, "/lesson/upload?lesson=L&after=nA", b"hello",
                                               {"Content-Type": "image/png"}))
        self.assertEqual(code_, 415)

    def test_static(self):
        st, ctype, body = get(self.port, "/static/lesson/render.js")
        self.assertEqual(st, 200)
        self.assertIn("javascript", ctype)
        self.assertEqual(get(self.port, "/static/lesson/../server.py")[0], 404)
        self.assertEqual(get(self.port, "/static/lesson/nope.js")[0], 404)


# ================================================================ Task 20: итоговое ревью

class ReviewFixTest(unittest.TestCase):
    """Замечания итогового ревью: указатель «следующим», распознавание во время урока, строка печати, тексты,
    сценарий из .md, замена идущего эфира со страницы."""

    def setUp(self):
        self.L = Template("Идёт", [note(id="ln"), code("a = 1", id="ca"), code("b = 2", id="cb"),
                                   code("c = 3", id="cc")], id="L")
        self.win = make_window([self.L], port=18984)
        self.win.lesson.open_page = lambda: None
        self.p = self.win.printer
        self.rec = Recorder(self.p)
        self.notes: list[str] = []
        self.p.notify.connect(lambda t, *_: self.notes.append(t))
        self.p.set_focus("L")

    def tearDown(self):
        if self.win.efir.live_webinar() is not None:
            self.win.efir.stop_live()
        self.win._quitting = True
        self.win.close()
        pump()

    def lesson(self):
        return self.win.store.get("L")

    def print_block(self, bid):
        self.p.arm(bid)
        self.p.job = self.p.job_for_armed()
        self.p._on_finished()

    def test_deleted_pointer_moves_on(self):
        from autoprint import lesson_edit
        self.print_block("ca")
        self.assertEqual(self.lesson().active_block, "cb")
        lesson_edit.apply(self.lesson(), [{"op": "delete", "block": "cb"}])
        self.assertEqual(self.lesson().active_block, "cc")        # следующий код после удалённого
        self.p.toggle()
        self.assertEqual(self.rec.loaded, ["c = 3"])

    def test_deleted_last_pointer_clears(self):
        from autoprint import lesson_edit
        self.print_block("cb")
        lesson_edit.apply(self.lesson(), [{"op": "delete", "block": "cc"}])
        self.assertEqual(self.lesson().active_block, "")

    def test_new_code_after_all_printed(self):
        from autoprint import lesson_edit
        self.print_block("cc")
        self.assertEqual(self.lesson().active_block, "")
        lesson_edit.apply(self.lesson(), [{"op": "insert", "after": "cc",
                                           "block": {"id": "cd", "type": "code", "text": "d = 4"}}])
        self.notes.clear()                     # «весь код напечатан» было правдой до вставки — теперь нет
        self.p.toggle()
        self.assertEqual(self.rec.loaded, ["d = 4"])
        self.assertFalse(any("Весь код урока напечатан" in n for n in self.notes), self.notes)

    def test_step_after_all_printed_goes_forward(self):
        from autoprint import lesson_edit
        self.print_block("cc")
        lesson_edit.apply(self.lesson(), [{"op": "insert", "after": "cc",
                                           "block": {"id": "cd", "type": "code", "text": "d = 4"}}])
        self.p.step(+1)
        self.assertEqual(self.lesson().active_block, "cd")        # не назад к первому коду

    def test_all_printed_still_said(self):
        self.print_block("cc")
        self.p.toggle()
        self.assertEqual(self.rec.loaded, [])
        self.assertTrue(any("Весь код урока напечатан" in n for n in self.notes), self.notes)

    def test_recognize_keeps_live_lesson(self):
        t = scenario_template()
        t.id = "SC"
        self.win.store.templates.append(t)
        self.L.blocks.insert(0, stage("Начало", 10, id="s0"))
        self.win.efir.confirm_replace = lambda *a: self.fail("не спрашивать: эфира, кроме урока, нет")
        self.assertTrue(self.win.efir.launch_lesson(self.L, start=""))
        self.assertEqual(self.win.efir.live_lesson_id(), "L")
        self.win.recognize_lesson(t)
        self.assertEqual(self.win.efir.live_lesson_id(), "L")        # идущий урок не завершён молча
        self.assertEqual(self.p.focus().id, "L")
        self.assertTrue(any(x.title == "Занятие 7 (сценарий)" for x in self.win.store.templates))

    def test_no_pult_in_messages(self):
        root = Path(storage.__file__).resolve().parent
        self.assertNotIn("на пульте", (root / "typer.py").read_text(encoding="utf-8"))

    def test_import_md_scenario(self):
        from autoprint.importers import load_file
        text = "\n\n".join(t if k == "markdown" else f"```python\n{t}\n```" for k, t in SCENARIO_CELLS)
        path = TMP / "Занятие 8.md"
        path.write_text(text, encoding="utf-8")
        t = load_file(str(path))
        self.assertEqual(sum(b.type == BLOCK_STAGE for b in t.blocks), 6)
        self.assertEqual(t.title, "Занятие 8")

    def test_other_live_on_page_and_force(self):
        from autoprint.efir.model import Activity, Webinar
        ctl = self.win.efir
        w = ctl.store.add([Webinar(title="1Т — первая пара", schedule=[Activity("x", 30)])])[0]
        ctl.launch(w.id, "")
        self.L.blocks.insert(0, stage("Начало", 10, id="s0"))
        self.win.lesson.publish()
        self.assertEqual(ctl.server._states["lesson"].get("other_live"), "1Т — первая пара")
        asked = []
        ctl.confirm_replace = lambda cur, new: asked.append(cur) or False
        self.win.lesson.command({"cmd": "start", "force": 1})     # страница уже спросила
        self.assertEqual(asked, [])
        self.assertEqual(ctl.live_lesson_id(), "L")
        self.win.lesson.publish()
        self.assertEqual(ctl.server._states["lesson"].get("other_live"), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
