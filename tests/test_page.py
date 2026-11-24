"""Экран урока в Edge без окна (CDP): правка на месте, «+», перенос, удаление, картинки, «Урок», печать, скорость.
Окон на экране нет; программа — offscreen, своя папка данных и порт.

    python tests/test_page.py
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

app = QApplication.instance() or QApplication([])
quiet.patch()
from autoprint.ui.theme import theme  # noqa: E402
theme.setup(app, "dark")

from autoprint import storage  # noqa: E402
from autoprint.storage import BLOCK_CODE, BLOCK_IMAGE, BLOCK_MARKDOWN, BLOCK_STAGE, Block, Settings, Template, TemplateStore  # noqa: E402
from cdp import Edge  # noqa: E402

PORT = 18990


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


def lesson() -> Template:
    return Template("Проверка экрана", [
        note("Цель: научиться писать функции.", role="task", id="intro1"),
        stage("Приветствие", 5, id="s1"),
        note("Добрый день! Сегодня — функции.", id="n1"),
        note("Что такое функция?\n→ кусок кода с именем", role="ask", id="n2"),
        stage("Разбор", 10, id="s2", part="Первая половина"),
        note("Функция\nименованный блок кода", role="term", id="n3"),
        code("def hello(name):\n    return 'Привет, ' + name\n\nprint(hello('мир'))", id="c1"),
        note("Привет, мир", role="output", id="o1"),
        stage("Итоги", 5, id="s3"),
        note("Вопросы?", role="tell", id="n4"),
    ], id="L1")


class Page(unittest.TestCase):
    """Программа (offscreen) + экран урока в Edge без окна — одна на все тесты класса."""
    templates = None

    @classmethod
    def setUpClass(cls):
        from autoprint.ui.main_window import MainWindow
        storage.TEMPLATES_FILE.unlink(missing_ok=True)
        storage.TEMPLATES_FILE.with_suffix(".json.bak").unlink(missing_ok=True)
        store = TemplateStore()
        store.templates = cls.templates() if cls.templates else [lesson()]
        store.save()
        s = Settings()
        s.efir_port = PORT
        s.update_auto_check = False
        s.sound_enabled = False
        s.samples_seen = ["steps_v1", "tour_v1", "lesson_v1", "lesson_v2", "lesson_v3"]
        s.migrations = ["tray_v1", "window_v10"]
        cls.win = MainWindow(s, store)
        cls.win.tray.showMessage = lambda *a, **k: None
        cls.store = store
        cls.t = store.templates[0]
        cls.win.printer.set_focus(cls.t.id)
        cls.win.efir.ensure_server()
        cls.win.lesson.publish()
        cls.port = cls.win.efir.server.port
        cls.edge = Edge.start(f"http://127.0.0.1:{cls.port}/lesson", pump=lambda: app.processEvents())
        ok = cls.edge.wait("window.__ready === true", 15)
        assert ok, "страница не получила состояние: " + "; ".join(cls.edge.errors())

    @classmethod
    def tearDownClass(cls):
        cls.edge.close()
        cls.win.efir.shutdown()
        cls.win._quitting = True
        cls.win.close()
        pump()

    def js(self, code_):
        return self.edge.eval(code_)

    def wait_py(self, pred, timeout: float = 5) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            pump(20)
            if pred():
                return True
        return False

    def mode(self, m):
        self.js(f"document.querySelector('.seg.modes button:{'first' if m == 'prep' else 'last'}-child').click()")
        self.assertTrue(self.edge.wait(f"document.body.classList.contains('mode-{m}')"))

    def republish(self):
        self.win.lesson._last = None
        self.win.lesson.publish()
        pump(100)

    def go_live(self, minutes_ago: float = 0):
        from datetime import timedelta
        ef = self.win.efir
        ef.launch_lesson(self.win.printer.focus(), start="")
        live = ef.store.live
        ef.store.set_live(live.webinar_id, live.anchor - timedelta(minutes=minutes_ago))
        ef.live_changed.emit()
        self.win.lesson.publish()

    def stop_live(self):
        self.win.efir.stop_live()
        self.win.lesson.publish()
        pump(200)

    def tearDown(self):
        errs = self.edge.errors()
        self.edge.events.clear()
        self.assertEqual(errs, [], "ошибки JavaScript на странице")


class SmokeTest(Page):
    def test_renders(self):
        self.assertEqual(self.js("document.querySelectorAll('.blk[data-id]').length"), 7)
        self.assertEqual(self.js("document.querySelectorAll('.stage').length"), 3)
        self.assertEqual(self.js("document.querySelectorAll('#plan .prow').length"), 3)
        self.assertIn("Проверка экрана", self.js("document.title"))
        self.assertTrue(self.js("document.title.endsWith(' — AutoPrintCode')"))
        self.assertEqual(self.js("document.querySelector('[data-id=n3] .term').textContent"), "Функция")
        self.assertIn("hello", self.js("document.querySelector('[data-id=c1] pre').textContent"))


PNG_1x1 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


class PageEditTest(Page):
    """Task 9: «Подготовка» — правка на месте."""

    def setUp(self):
        self.mode("prep")

    def block(self, bid):
        return self.t.find_block(bid)

    def test_click_edit_same_height(self):
        h0 = self.js("document.querySelector('[data-id=n1] .row > .c').getBoundingClientRect().height")
        self.js("document.querySelector('[data-id=n1] .row > .c').click()")
        self.assertTrue(self.edge.wait("document.activeElement && document.activeElement.isContentEditable"))
        h1 = self.js("document.activeElement.getBoundingClientRect().height")
        self.assertLessEqual(abs(h1 - h0), 2, f"было {h0}, в правке {h1}")
        self.js("document.activeElement.blur()")

    def test_type_saves(self):
        self.js("document.querySelector('[data-id=n4] .row > .c').click()")
        self.assertTrue(self.edge.wait("document.activeElement && document.activeElement.isContentEditable"))
        self.edge.text(" Привет!")
        self.assertTrue(self.wait_py(lambda: self.block("n4").text.endswith(" Привет!")), self.block("n4").text)
        self.js("document.activeElement.blur()")
        self.assertTrue(self.edge.wait("!document.querySelector('[data-id=n4] .rich') && "
                                       "document.querySelector('[data-id=n4] .c').textContent.includes('Привет!')"))

    def test_echo_keeps_caret(self):
        self.js("document.querySelector('[data-id=n2] .row > .c').click()")
        self.assertTrue(self.edge.wait("document.activeElement && document.activeElement.isContentEditable"))
        self.js("{ const t = document.activeElement; t.__mark = 1; const tn = t.querySelector('p').firstChild;"
                " const r = document.createRange(); r.setStart(tn, 3); r.collapse(true);"
                " const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r); }")
        self.block("intro1").text = "Цель: научиться писать функции (обновлено)."
        self.win.lesson.publish()
        self.assertTrue(self.edge.wait("document.querySelector('[data-id=intro1] .c').textContent.includes('обновлено')"))
        self.assertTrue(self.js("document.activeElement.__mark === 1 && getSelection().anchorOffset === 3"))
        self.js("document.activeElement.blur()")

    # ---------------------------------------------------------------- 0.11 Task 5: правка как в Word
    def select_text(self, bid, word):
        self.js(f"""{{ const root = document.querySelector('[data-id={bid}] .rich');
            const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT); let n;
            while ((n = w.nextNode())) {{ const i = n.data.indexOf({word!r}); if (i >= 0) {{
              const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + {len(word)});
              const s = getSelection(); s.removeAllRanges(); s.addRange(r); break; }} }} }}""")

    def tool(self, cmd_):
        self.js(f"{{ const b = document.querySelector('.rtb [data-cmd={cmd_}]');"
                " b.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true})); b.click(); }")

    def test_rich_bold(self):
        self.js("document.querySelector('[data-id=n1] .row > .c').click()")
        self.assertTrue(self.edge.wait("document.activeElement && document.activeElement.isContentEditable"))
        self.assertTrue(self.edge.wait("!!document.querySelector('.rtb [data-cmd=bold]')"))
        self.select_text("n1", "Сегодня")
        self.tool("bold")
        self.assertTrue(self.wait_py(lambda: "**Сегодня**" in self.block("n1").text), self.block("n1").text)
        self.assertNotIn("*", self.js("document.querySelector('[data-id=n1] .rich').textContent"))
        self.select_text("n1", "Сегодня")
        self.tool("bold")                                                          # снять жирный
        self.assertTrue(self.wait_py(lambda: "*" not in self.block("n1").text), self.block("n1").text)
        self.js("document.activeElement.blur()")

    def test_rich_roundtrip(self):
        md = ("**a** *b* `c` [d](https://x.ru) и https://y.ru\n\n- e\n- f\n\n1. g\n2. h\n\n# Заголовок\n\n"
              "строка\nещё строка")
        once = self.js(f"window.__rt.roundtrip({md!r})")
        self.assertEqual(once, md)
        self.assertEqual(self.js("window.__rt.roundtrip('**a** b\\n- e')"), "**a** b\n\n- e")
        before = self.block("n3").text
        self.js("document.querySelector('[data-id=n3] .row > .c').click()")
        self.assertTrue(self.edge.wait("document.activeElement && document.activeElement.isContentEditable"))
        self.js("document.activeElement.blur()")
        pump(600)
        self.assertEqual(self.block("n3").text, before)                         # открыть и закрыть — текст тот же

    def test_rich_escapes_and_paste_sources(self):
        md = self.js("(() => { const d = document.createElement('div');"
                     " d.innerHTML = '<p>2024. Год начала курса!</p><p>x**2 + y**2</p>'; return window.__rt.toMarkdown(d); })()")
        self.assertEqual(md, "2024\\. Год начала курса!\n\nx\\*\\*2 + y\\*\\*2")       # набранное — как есть
        self.assertEqual(self.js(f"window.__rt.roundtrip({md!r})"), md)
        gdocs = ('<b style="font-weight:normal" id="docs-internal-guid-1"><p>Первая</p>'
                 '<p><b>Жирное</b> обычное</p></b>')
        got = self.js(f"(() => {{ const d = document.createElement('div'); d.innerHTML = window.__rt.cleanPaste({gdocs!r});"
                      " return window.__rt.toMarkdown(d); })()")
        self.assertEqual(got, "Первая\n\n**Жирное** обычное")                           # обёртка Google Docs — не жирный
        table = "<table><tr><td>int</td><td>42</td></tr></table>"
        got = self.js(f"(() => {{ const d = document.createElement('div'); d.innerHTML = window.__rt.cleanPaste({table!r});"
                      " return window.__rt.toMarkdown(d); })()")
        self.assertIn("int 42", got)

    def test_final_review_richtext(self):
        md = "`a\\.b` и `\"C:\\\\Users\"`"
        self.assertEqual(self.js(f"window.__rt.roundtrip({md!r})"), md)                  # внутри кода — как есть
        word = "<p><b style='mso-bidi-font-weight:normal'>Жирный</b> обычный</p>"
        got = self.js(f"(() => {{ const d = document.createElement('div'); d.innerHTML = window.__rt.cleanPaste({word!r});"
                      " return window.__rt.toMarkdown(d); })()")
        self.assertEqual(got, "**Жирный** обычный")                                     # жирный из Word остаётся
        got = self.js("(() => { const d = document.createElement('div'); d.innerHTML = '<p><b>а<br>б</b></p>';"
                      " return window.__rt.toMarkdown(d); })()")
        self.assertEqual(got, "**а**\n**б**")                                           # по строкам — разбор поймёт

    def test_homework_copy_item(self):
        b = self.block("n4")
        b.role = "homework"
        self.win.lesson.publish()
        try:
            self.assertTrue(self.edge.wait("!!document.querySelector('[data-id=n4] .r-homework')"))
            self.js("document.querySelector('[data-id=n4] .bmore').click()")
            self.assertTrue(self.edge.wait("!!document.querySelector('.menu')"))
            self.assertTrue(self.js("[...document.querySelectorAll('.menu .mi')].some(b => b.textContent.includes('Скопировать для чата'))"))
            self.js("document.body.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}))")
        finally:
            self.block("n4").role = "tell"
            self.win.lesson.publish()

    def test_ask_fields(self):
        q = "Что такое функция?\n→ кусок кода с именем"
        self.assertEqual(self.block("n2").text, q)
        self.js("document.querySelector('[data-id=n2] .row > .c').click()")
        self.assertTrue(self.edge.wait("document.querySelectorAll('[data-id=n2] .ansin').length === 1"))
        self.assertEqual(self.js("document.querySelector('[data-id=n2] .ansin').value"), "кусок кода с именем")
        self.assertNotIn("→", self.js("document.querySelector('[data-id=n2] .rich').textContent"))
        self.js("document.querySelector('[data-id=n2] .addans').click()")
        self.assertTrue(self.edge.wait("document.activeElement && document.activeElement.classList.contains('ansin')"))
        self.edge.text("блок с именем")
        self.assertTrue(self.wait_py(lambda: self.block("n2").text == q + "\n→ блок с именем"), self.block("n2").text)
        self.js("document.querySelectorAll('[data-id=n2] .ansdel')[1].click()")
        self.assertTrue(self.wait_py(lambda: self.block("n2").text == q), self.block("n2").text)
        self.js("document.activeElement.blur()")

    def test_term_fields(self):
        t0 = self.block("n3").text
        term, definition = t0.split("\n", 1)
        self.js("document.querySelector('[data-id=n3] .row > .c').click()")
        self.assertTrue(self.edge.wait("!!document.querySelector('[data-id=n3] .termin')"))
        self.assertEqual(self.js("document.querySelector('[data-id=n3] .termin').value"), term)
        self.js("{ const i = document.querySelector('[data-id=n3] .termin'); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }")
        self.edge.text(" Python")
        self.assertTrue(self.wait_py(lambda: self.block("n3").text == f"{term} Python\n{definition}"), self.block("n3").text)
        for _ in range(7):
            self.edge.key("Backspace", "Backspace", 8)
        self.assertTrue(self.wait_py(lambda: self.block("n3").text == t0), self.block("n3").text)
        self.js("document.activeElement.blur()")

    def test_paste_word(self):
        ids = lambda: [b.id for b in self.t.blocks]
        self.js("document.querySelector('.ins[data-after=n4] .insbtn').click()")
        self.assertTrue(self.edge.wait("!!document.querySelector('.menu')"))
        self.js("[...document.querySelectorAll('.menu .mi')].find(b => b.querySelector('.ml').textContent === 'Заметка').click()")
        self.assertTrue(self.wait_py(lambda: ids()[-1] != "n4"))
        new = ids()[-1]
        self.assertTrue(self.edge.wait("document.activeElement && document.activeElement.isContentEditable"))
        html = ('<html><head><style>p{color:red}</style></head><body><!--StartFragment-->'
                '<p class=MsoNormal style="margin:0"><b><span style="font-size:14pt">Жир</span></b> '
                '<span style="color:red;font-family:Calibri">текст</span></p>'
                '<ul><li style="mso-list:l0">раз</li><li>два</li></ul><script>x()</script><!--EndFragment--></body></html>')
        self.js(f"""{{ const dt = new DataTransfer(); dt.setData('text/html', {html!r}); dt.setData('text/plain', 'Жир текст');
            document.activeElement.dispatchEvent(new ClipboardEvent('paste', {{clipboardData: dt, bubbles: true, cancelable: true}})); }}""")
        self.assertTrue(self.wait_py(lambda: (self.block(new) or Block(BLOCK_MARKDOWN, "")).text == "**Жир** текст\n\n- раз\n- два"),
                        (self.block(new) or Block(BLOCK_MARKDOWN, "")).text)
        self.assertEqual(self.js("document.querySelector('.rich [style], .rich script, .rich span') === null"), True)
        self.js("document.activeElement.blur()")
        self.js(f"document.querySelector('[data-id=\"{new}\"] .lbl').click()")
        self.edge.key("Delete", "Delete", 46)
        self.assertTrue(self.wait_py(lambda: new not in ids()))

    def test_other_nodes_kept(self):
        self.js("document.querySelectorAll('.blk[data-id]').forEach(n => n.__keep = 1)")
        self.block("n3").text = "Функция\nименованный кусок кода"
        self.win.lesson.publish()
        self.assertTrue(self.edge.wait("document.querySelector('[data-id=n3] .def').textContent.includes('кусок')"))
        self.assertTrue(self.js("[...document.querySelectorAll('.blk[data-id]')].filter(n => n.dataset.id !== 'n3')"
                                ".every(n => n.__keep === 1)"))
        self.assertFalse(self.js("document.querySelector('[data-id=n3]').__keep === 1"))

    def test_plus_inserts_role(self):
        n0 = len(self.t.blocks)
        self.js("document.querySelector('.ins[data-after=n1] .insbtn').click()")
        self.assertTrue(self.edge.wait("!!document.querySelector('.menu')"))
        self.js("[...document.querySelectorAll('.menu .mi')].find(b => b.querySelector('.ml').textContent === 'Спроси').click()")
        self.assertTrue(self.wait_py(lambda: len(self.t.blocks) == n0 + 1))
        ids = [b.id for b in self.t.blocks]
        new = self.t.blocks[ids.index("n1") + 1]
        self.assertEqual((new.type, new.role), (BLOCK_MARKDOWN, "ask"))
        self.assertTrue(self.edge.wait("document.activeElement && document.activeElement.isContentEditable"))
        self.edge.text("Новый вопрос?")
        self.js("document.activeElement.blur()")
        self.assertTrue(self.wait_py(lambda: self.block(new.id).text == "Новый вопрос?"))   # правка заменяет объекты блоков

    def test_minutes_in_plan(self):
        self.js("{ const i = document.querySelector('#pr-s3 .pmin'); i.dispatchEvent(new WheelEvent('wheel', {deltaY: -100, bubbles: true})); }")
        self.assertEqual(self.js("document.querySelector('#pr-s3 .pmin').value"), "5")
        self.js("{ const i = document.querySelector('#pr-s3 .pmin'); i.focus(); i.select(); }")
        self.edge.text("12")
        self.edge.key("Enter", "Enter", 13)
        self.assertTrue(self.wait_py(lambda: self.block("s3").minutes == 12))
        self.assertTrue(self.edge.wait("document.querySelector('#plan .ptotal').textContent === '27 мин'"))

    def test_move_keys(self):
        ids = lambda: [b.id for b in self.t.blocks]
        self.js("document.querySelector('[data-id=n4] .lbl').click()")          # выделить блок, не правя текст
        self.edge.key("ArrowUp", "ArrowUp", 38, modifiers=1)                     # Alt+↑ — выше этапа «Итоги»
        self.assertTrue(self.wait_py(lambda: ids().index("n4") == ids().index("s3") - 1), ids())
        self.edge.key("ArrowDown", "ArrowDown", 40, modifiers=1)
        self.assertTrue(self.wait_py(lambda: ids().index("n4") == ids().index("s3") + 1), ids())
        self.js("window.__moveStage('s3', '')")                                  # «Итоги» — первым этапом
        self.assertTrue(self.wait_py(lambda: [i for i in ids() if i.startswith("s")][0] == "s3"), ids())
        self.js("window.__moveStage('s3', 's2')")
        self.assertTrue(self.wait_py(lambda: [i for i in ids() if i.startswith("s")] == ["s1", "s2", "s3"]), ids())

    def test_paste_image(self):
        n0 = sum(b.type == BLOCK_IMAGE for b in self.t.blocks)
        self.js("document.querySelector('[data-id=o1] .lbl').click()")
        self.js(f"""(() => {{
            const bin = atob('{PNG_1x1}'); const a = new Uint8Array(bin.length);
            for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i);
            const dt = new DataTransfer(); dt.items.add(new File([a], 'p.png', {{type: 'image/png'}}));
            document.dispatchEvent(new ClipboardEvent('paste', {{clipboardData: dt, bubbles: true}}));
        }})()""")
        self.assertTrue(self.wait_py(lambda: sum(b.type == BLOCK_IMAGE for b in self.t.blocks) == n0 + 1))
        ids = [b.id for b in self.t.blocks]
        self.assertEqual(self.t.blocks[ids.index("o1") + 1].type, BLOCK_IMAGE)
        self.assertTrue(self.edge.wait("!!document.querySelector('.blk[data-type=image] figure img')"))

    def test_undo_insert_keeps_text(self):
        """Ctrl+Z после «+» и набора текста: блок с текстом уходит с «Вернуть», а не пропадает насовсем."""
        ids = lambda: [b.id for b in self.t.blocks]
        self.mode("prep")
        self.js("document.querySelector('.ins[data-after=n3] .insbtn').click()")
        self.assertTrue(self.edge.wait("!!document.querySelector('.menu')"))
        self.js("[...document.querySelectorAll('.menu .mi')].find(b => b.querySelector('.ml').textContent === 'Говоришь').click()")
        self.assertTrue(self.wait_py(lambda: ids()[ids().index("n3") + 1] != "c1"))
        new = ids()[ids().index("n3") + 1]
        self.assertTrue(self.edge.wait("document.activeElement && document.activeElement.isContentEditable"))
        self.edge.text("Определение — дословно.")
        self.js("document.activeElement.blur()")
        self.assertTrue(self.wait_py(lambda: (self.block(new) or Block(BLOCK_MARKDOWN, "")).text == "Определение — дословно."))
        self.js("document.getElementById('toast').hidden = true")
        self.edge.key("z", "KeyZ", 90, modifiers=2)                               # Ctrl+Z
        self.assertTrue(self.wait_py(lambda: new not in ids()))
        self.assertTrue(self.edge.wait("!document.getElementById('toast').hidden && !!document.querySelector('#toast button')"))
        self.js("document.querySelector('#toast button').click()")
        self.assertTrue(self.wait_py(lambda: new in ids() and self.block(new).text == "Определение — дословно."))
        self.js(f"document.querySelector('[data-id=\"{new}\"] .lbl').click()")
        self.edge.key("Delete", "Delete", 46)                                    # убрать за собой
        self.assertTrue(self.wait_py(lambda: new not in ids()))

    def test_code_selection_resets(self):
        """Выделение в коде = «печатать только это», пока код не правили; пустое выделение его снимает (как в 0.9)."""
        self.mode("prep")
        sel = lambda: list(self.block("c1").sel)
        self.js("document.querySelector('[data-id=c1] .codebox pre').click()")
        self.assertTrue(self.edge.wait("!!(document.activeElement && document.activeElement.closest('[data-id=c1] .cm-editor'))", 10))
        self.edge.key("Home", "Home", 36, modifiers=2)                            # Ctrl+Home
        self.edge.key("ArrowDown", "ArrowDown", 40, modifiers=8)                  # Shift+↓ — первая строка
        self.assertTrue(self.wait_py(lambda: sel() != []), sel())
        self.edge.text("y")                                                       # набрали поверх выделения
        self.assertTrue(self.wait_py(lambda: sel() == [] and self.block("c1").text.startswith("y")), sel())
        self.edge.key("ArrowDown", "ArrowDown", 40, modifiers=8)
        self.assertTrue(self.wait_py(lambda: sel() != []), sel())
        self.edge.key("ArrowRight", "ArrowRight", 39)                              # выделение снято
        self.assertTrue(self.wait_py(lambda: sel() == []), sel())
        self.js("document.activeElement.blur()")

    def test_z_delete_undo(self):
        ids = lambda: [b.id for b in self.t.blocks]
        before = ids()[ids().index("n2") - 1]
        self.js("document.querySelector('[data-id=n2] .lbl').click()")
        self.edge.key("Delete", "Delete", 46)
        self.assertTrue(self.wait_py(lambda: "n2" not in ids()))
        self.assertTrue(self.edge.wait("!document.querySelector('[data-id=n2]')"))
        self.js("document.querySelector('#toast button').click()")
        self.assertTrue(self.wait_py(lambda: "n2" in ids()))
        self.assertEqual(ids()[ids().index("n2") - 1], before)
        self.assertIn("→ кусок кода с именем", self.block("n2").text)

    def test_zz_offline_queue(self):
        n0 = len(self.t.blocks)
        self.win.efir.server.stop()
        pump(200)
        self.js("document.querySelector('[data-id=n1] .row > .c').click()")
        self.assertTrue(self.edge.wait("document.activeElement && document.activeElement.isContentEditable"))
        self.edge.text(" (без связи)")
        self.js("document.activeElement.blur()")
        self.js("document.querySelector('.ins[data-after=n1] .insbtn').click()")
        self.assertTrue(self.edge.wait("!!document.querySelector('.menu')"))
        self.js("[...document.querySelectorAll('.menu .mi')].find(b => b.querySelector('.ml').textContent === 'Делаешь').click()")
        self.js("document.activeElement.blur()")
        self.assertTrue(self.edge.wait("document.getElementById('saveChip').textContent.includes('Нет связи')", 8))
        self.assertTrue(self.js("!!localStorage.getItem('suflor.pending.' + 'L1')"))
        self.win.efir.ensure_server()
        self.assertTrue(self.wait_py(lambda: self.block("n1").text.endswith(" (без связи)") and len(self.t.blocks) == n0 + 1, 25))
        pump(1500)
        self.assertEqual(len(self.t.blocks), n0 + 1)
        self.assertEqual(self.block("n1").text.count("(без связи)"), 1)
        self.assertTrue(self.edge.wait("document.getElementById('saveChip').textContent.includes('Сохранено')", 8))


def two_codes() -> list[Template]:
    return [Template("Код и зарядка", [
        stage("Разбор", 10, id="s1"),
        note("Смотрим код", id="n1"),
        code("a = 1\nprint(a)", id="c1"),
        code("b = 2\nprint(b)", id="c2"),
        stage("Зарядка", 5, id="s2", stage_kind="exercise"),
    ], id="L2")]


class PageLessonTest(Page):
    """Task 10: «Урок», «Печать ⚙», редактор кода."""
    templates = staticmethod(two_codes)

    def test_arm_code_only(self):
        self.mode("lesson")
        self.t.active_block = ""
        self.js("document.querySelector('[data-id=n1] .c').click()")
        pump(300)
        self.assertEqual(self.t.active_block, "")
        self.win.lesson.publish()
        self.assertTrue(self.edge.wait("!!document.querySelector('[data-id=c2] .armbtn')"))
        self.js("document.querySelector('[data-id=c2] .armbtn').click()")
        self.assertTrue(self.wait_py(lambda: self.t.active_block == "c2"))
        self.assertTrue(self.edge.wait("!!document.querySelector('[data-id=c2] .armed-chip') && "
                                       "document.querySelector('[data-id=c2] .armed-chip').textContent.includes('Следующим')"))

    def test_other_live_asks_on_page(self):
        """Идёт вебинар по расписанию — «Начать урок» спрашивает на странице (окно программы может быть за браузером)."""
        from autoprint.efir.model import Activity, Webinar
        ctl = self.win.efir
        w = ctl.store.add([Webinar(title="Пара 1Т", schedule=[Activity("x", 30)])])[0]
        asked_qt = []
        ctl.confirm_replace = lambda cur, new: asked_qt.append(cur) or False
        ctl.launch(w.id, "")
        try:
            self.win.lesson.publish()
            self.mode("lesson")
            start = "[...document.querySelectorAll('#tools button')].find(b => b.textContent === 'Начать урок')"
            self.assertTrue(self.edge.wait(f"!!{start}"))
            self.js("window.__asked = ''; window.__confirm = window.confirm; window.confirm = (m) => { window.__asked = m; return false; }")
            self.js(f"{start}.click()")
            pump(300)
            self.assertIn("Пара 1Т", self.js("window.__asked"))
            self.assertEqual(asked_qt, [])
            self.assertEqual(ctl.live_webinar().id, w.id)
        finally:
            ctl.stop_live()
            del ctl.confirm_replace
            self.js("if (window.__confirm) window.confirm = window.__confirm")
            self.win.lesson.publish()

    def test_print_popover(self):
        self.js("[...document.querySelectorAll('#tools .iconbtn')].find(b => b.textContent.includes('Печать')).click()")
        self.assertTrue(self.edge.wait("!!document.querySelector('.pmenu')"))
        self.js("[...document.querySelectorAll('.pmenu .seg button')].find(b => b.textContent === 'По шагам').click()")
        self.assertTrue(self.wait_py(lambda: self.win.settings.print_mode == "steps"))
        self.js("[...document.querySelectorAll('.pmenu .seg button')].find(b => b.textContent === 'Целиком').click()")
        self.assertTrue(self.wait_py(lambda: self.win.settings.print_mode == "block"))
        self.js("document.body.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}))")

    def test_code_edit(self):
        self.mode("prep")
        self.js("document.querySelector('[data-id=c1] .codebox pre').click()")
        self.assertTrue(self.edge.wait("!!document.querySelector('[data-id=c1] .cm-editor')", 10))
        self.assertTrue(self.edge.wait("!!(document.activeElement && document.activeElement.closest('.cm-editor'))"))
        self.edge.text("x=1\n")
        self.assertTrue(self.wait_py(lambda: "x=1" in self.t.find_block("c1").text), self.t.find_block("c1").text)
        self.js("document.querySelector('[data-id=c2] .codebox pre').click()")
        self.assertTrue(self.edge.wait("!!document.querySelector('[data-id=c2] .cm-editor')", 10))
        self.assertTrue(self.edge.wait("document.querySelectorAll('.cm-editor').length === 1", 5))
        self.assertTrue(self.edge.wait("document.querySelector('[data-id=c1] pre').textContent.includes('x=1')", 5))
        self.js("document.activeElement.blur()")

    def test_code_steps_keys(self):
        self.mode("prep")
        self.js("document.querySelector('[data-id=c2] .codebox pre').click()")
        self.assertTrue(self.edge.wait("!!(document.activeElement && document.activeElement.closest('[data-id=c2] .cm-editor'))", 10))
        self.edge.key("End", "End", 35, modifiers=2)                              # Ctrl+End — последняя строка
        self.edge.key("2", "Digit2", 50, modifiers=1)                             # Alt+2 — шаг 2
        self.assertTrue(self.wait_py(lambda: self.t.find_block("c2").steps[-1:] == [2]), self.t.find_block("c2").steps)
        self.js("document.activeElement.blur()")

    def test_no_exercise_button_without_video(self):
        self.mode("lesson")
        self.assertFalse(self.js("!!document.querySelector('[data-act=exercise]')"))
        self.assertIn("нет видео", self.js("document.querySelector('#st-s2 .efirnote').textContent"))


class PageV11Test(Page):
    """0.11: «Мои настройки», урок без автоматики, план строкой, экран учеников с экрана урока."""

    def setUp(self):
        s = self.win.settings
        s.page_zoom, s.page_plan, s.page_past, s.page_stage_timer = 100, "strip", "dim", True
        self.win.lesson._last = None
        self.win.lesson.publish()
        pump(100)

    def test_zoom_keys(self):
        s = self.win.settings
        self.js("document.activeElement && document.activeElement.blur && document.activeElement.blur()")
        self.edge.key("=", "Equal", 187, modifiers=2)                               # Ctrl+=
        self.assertTrue(self.wait_py(lambda: s.page_zoom == 110), s.page_zoom)
        self.assertTrue(self.edge.wait("document.documentElement.style.zoom === '1.1'"))
        self.edge.key("0", "Digit0", 48, modifiers=2)                               # Ctrl+0 — обычный
        self.assertTrue(self.wait_py(lambda: s.page_zoom == 100), s.page_zoom)
        self.assertTrue(self.edge.wait("document.documentElement.style.zoom === '1'"))

    def test_zoom_menus_in_view_and_print(self):
        s = self.win.settings
        s.page_zoom = 150
        self.win.lesson._last = None
        self.win.lesson.publish()
        try:
            self.assertTrue(self.edge.wait("document.documentElement.style.zoom === '1.5'"))
            more = "[...document.querySelectorAll('#tools .iconbtn.only')].find(b => b.getAttribute('aria-label') === 'Ещё')"
            self.js(f"{more}.click()")
            self.assertTrue(self.edge.wait("!!document.querySelector('.menu')"))
            r = self.js(f"""(() => {{ const m = document.querySelector('.menu').getBoundingClientRect();
                const a = {more}.getBoundingClientRect();
                return [m.left, m.top, m.right, m.bottom, innerWidth, innerHeight, a.bottom]; }})()""")
            left, top, right, bottom, vw, vh, abot = r
            self.assertGreaterEqual(left, 0)
            self.assertLessEqual(right, vw + 1)
            self.assertLessEqual(bottom, vh + 1)                                    # меню целиком в окне
            # у кнопки — или, если длинное, во всю высоту окна (с прокруткой), а не где-то внизу за краем
            self.assertTrue(abs(top - abot) < 40 or bottom >= vh - 24, r)
            self.js("document.body.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}))")
            self.edge.call("Emulation.setEmulatedMedia", {"media": "print"})
            self.assertEqual(self.js("getComputedStyle(document.documentElement).zoom"), "1")   # на бумагу — без экранного масштаба
        finally:
            self.edge.call("Emulation.setEmulatedMedia", {"media": ""})
            s.page_zoom = 100
            self.win.lesson.publish()
            self.edge.wait("document.documentElement.style.zoom === '1'")

    def test_prefs_menu(self):
        s = self.win.settings
        self.js("document.querySelector('#tools .prefsbtn').click()")
        self.assertTrue(self.edge.wait("!!document.querySelector('.menu .prefs')"))
        self.assertIn("Мои настройки", self.js("document.querySelector('.menu .prefs').textContent"))
        self.js("[...document.querySelectorAll('.menu .prefs .seg.plan button')].find(b => b.textContent === 'Сбоку').click()")
        self.assertTrue(self.wait_py(lambda: s.page_plan == "side"))
        self.js("[...document.querySelectorAll('.menu .prefs button')].find(b => b.textContent === '+').click()")
        self.assertTrue(self.wait_py(lambda: s.page_zoom == 110))
        self.js("document.body.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}))")

    # ---------------------------------------------------------------- Task 2: «Урок» ничего не делает сам
    def test_no_auto_collapse(self):
        self.mode("lesson")
        try:
            self.go_live(1)
            self.assertTrue(self.edge.wait("document.getElementById('st-s1').classList.contains('current')"))
            self.js("window.scrollTo(0, 120)")
            y0 = self.js("scrollY")
            self.go_live(6)                                                          # «Приветствие» (5 мин) прошло
            self.assertTrue(self.edge.wait("document.getElementById('st-s2').classList.contains('current')"))
            pump(1500)
            self.assertEqual(self.js("document.querySelectorAll('.stage.collapsed').length"), 0)
            self.assertEqual(self.js("scrollY"), y0)
            self.assertEqual(self.js("document.querySelector('#st-s2 .left .lbl2').textContent"), "Сейчас")   # время — в строке плана
            self.assertEqual(self.js("document.querySelector('#st-s3 .left .lbl2').textContent"), "")   # без «через»
        finally:
            self.stop_live()

    def test_now_banner(self):
        self.mode("lesson")
        self.edge.call("Emulation.setDeviceMetricsOverride", {"width": 1360, "height": 320, "deviceScaleFactor": 1, "mobile": False})
        try:
            self.go_live(6)
            self.assertTrue(self.edge.wait("document.getElementById('st-s2').classList.contains('current')"))
            self.js("window.scrollTo(0, document.body.scrollHeight)")
            self.assertTrue(self.edge.wait("!document.getElementById('nowbar').hidden && "
                                           "document.getElementById('nowbar').textContent.includes('Разбор')", 5))
            self.js("document.getElementById('nowbar').click()")
            self.assertTrue(self.edge.wait("document.getElementById('nowbar').hidden", 5))
        finally:
            self.edge.call("Emulation.clearDeviceMetricsOverride")
            self.stop_live()

    def test_collapse_all_and_past(self):
        self.mode("lesson")
        more = "[...document.querySelectorAll('#tools .iconbtn.only')].find(b => b.getAttribute('aria-label') === 'Ещё')"
        item = "[...document.querySelectorAll('.menu .mi')].find(b => b.textContent.includes('{}'))"
        self.js(f"{more}.click()")
        self.assertTrue(self.edge.wait("!!document.querySelector('.menu')"))
        self.js(item.format("Свернуть все этапы") + ".click()")
        self.assertTrue(self.edge.wait("document.querySelectorAll('.stage.collapsed').length === 3"))
        self.js(f"{more}.click()")
        self.js(item.format("Развернуть все этапы") + ".click()")
        self.assertTrue(self.edge.wait("document.querySelectorAll('.stage.collapsed').length === 0"))
        self.win.settings.page_past = "collapse"
        try:
            self.go_live(6)
            self.assertTrue(self.edge.wait("document.getElementById('st-s1').classList.contains('collapsed') && "
                                           "!document.getElementById('st-s2').classList.contains('collapsed')"))
        finally:
            self.win.settings.page_past = "dim"
            self.stop_live()

    # ---------------------------------------------------------------- Task 4: экран учеников с экрана урока
    def test_screen_controls(self):
        ef = self.win.efir
        opened = []
        ef.open_tab = lambda: opened.append(1)
        self.mode("lesson")
        chip = "document.querySelector('#strip .scrchip')"
        btn = "[...document.querySelectorAll('header button')].find(b => b.textContent.trim() === '{}')"
        try:
            self.assertTrue(self.edge.wait(f"!!{chip} && {chip}.textContent.includes('Экран учеников')"))
            self.assertFalse(self.js(f"!!{btn.format('Перерыв')}"))     # в уроке нет этапа-перерыва — кнопки нет
            self.js(f"{chip}.click()")
            self.assertTrue(self.edge.wait("!!document.querySelector('.menu')"))
            self.js("[...document.querySelectorAll('.menu .mi')].find(b => b.textContent.includes('Перерыв по плану')).click()")
            self.assertTrue(self.wait_py(lambda: ef.mode == "break"))
            self.assertTrue(self.edge.wait(f"{chip}.textContent.includes('перерыв')"))
            self.js(btn.format("Вернуть фон") + ".click()")
            self.assertTrue(self.wait_py(lambda: ef.mode == "idle"))
            self.js(f"{chip}.click()")
            self.assertTrue(self.edge.wait("!!document.querySelector('.menu')"))
            self.js("[...document.querySelectorAll('.menu .mi')].find(b => b.textContent.includes('Открыть экран учеников')).click()")
            self.assertTrue(self.wait_py(lambda: opened == [1]))
            self.assertEqual(self.js("document.body.textContent.includes('Этап заново')"), False)
        finally:
            del ef.open_tab
            ef.show_background()

    # ---------------------------------------------------------------- Task 7: роли и палитра
    def test_palette_groups(self):
        self.mode("prep")
        self.assertEqual(self.js("document.querySelector('[data-id=n1] .lbl .how').textContent"), "· дословно")
        self.js("document.querySelector('.ins[data-after=n1] .insbtn').click()")
        self.assertTrue(self.edge.wait("!!document.querySelector('.menu')"))
        heads = self.js("[...document.querySelectorAll('.menu .mhead')].map(h => h.textContent)")
        self.assertEqual(heads, ["Урок", "Речь", "Ученикам", "Действия", "Для себя", "Материалы"])
        labels = self.js("[...document.querySelectorAll('.menu .mi .ml')].map(x => x.textContent)")
        self.assertEqual(labels[-1], "Код")
        for name in ("Этап", "Цель урока", "Если застрял", "Домашнее задание", "Типичные ошибки", "Результат кода"):
            self.assertIn(name, labels)
        self.js("document.body.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}))")
        printbtn = "[...document.querySelectorAll('#tools .iconbtn')].find(b => b.textContent.includes('Печать'))"
        self.assertTrue(self.js(f"!{printbtn}.hidden"))
        self.win.store.templates.append(Template("Без кода", [stage("Один", 10, id="z1"), note("Текст", id="z2")], id="NC"))
        try:
            self.win.open_lesson("NC", ask=False)
            self.win.lesson.publish()
            self.assertTrue(self.edge.wait(f"document.getElementById('titleText').textContent === 'Без кода' && {printbtn}.hidden"))
        finally:
            self.win.open_lesson(self.t.id, ask=False)
            self.win.store.templates[:] = [x for x in self.win.store.templates if x.id != "NC"]
            self.win.lesson.publish()
            self.assertTrue(self.edge.wait(f"document.getElementById('titleText').textContent === '{self.t.title}'"))

    # ---------------------------------------------------------------- Task 11: печать
    def test_print_options(self):
        more = "[...document.querySelectorAll('#tools .iconbtn.only')].find(b => b.getAttribute('aria-label') === 'Ещё')"
        self.js(f"{more}.click()")
        self.assertTrue(self.edge.wait("!!document.querySelector('.menu')"))
        self.js("[...document.querySelectorAll('.menu .mi')].find(b => b.textContent.includes('Распечатать')).click()")
        self.assertTrue(self.edge.wait("!!document.querySelector('.modal .printbox')"))
        pick = "[...document.querySelectorAll('.printbox button')].find(b => b.textContent === '{}').click()"
        self.js(pick.format("Крупно"))
        self.js(pick.format("Миниатюрами"))
        self.js("{ const c = document.querySelector('.printbox input[name=answers]'); c.checked = false; }")
        self.js("{ const c = document.querySelector('.printbox input[name=code]'); c.checked = false; }")
        self.js("window.__printed = null; window.__print = window.print; window.print = () => { window.__printed = document.body.className; }")
        try:
            self.js("[...document.querySelectorAll('.modal button')].find(b => b.textContent === 'Печать').click()")
            self.assertTrue(self.edge.wait("window.__printed !== null"))
            cls = self.js("window.__printed").split()
            for c in ("print-size-large", "print-no-answers", "print-no-code", "print-slides-thumbs"):
                self.assertIn(c, cls)
            self.assertFalse(self.js("!!document.querySelector('.modal')"))
            self.assertFalse(self.js("document.body.className.includes('print-size-large')"))   # после печати — как было
        finally:
            self.js("window.print = window.__print")

    # ---------------------------------------------------------------- Task 3: план строкой
    def test_plan_strip(self):
        self.mode("lesson")
        try:
            self.assertTrue(self.edge.wait("getComputedStyle(document.getElementById('plan')).display === 'none'"))
            self.go_live(6)
            self.assertTrue(self.edge.wait("document.querySelector('#strip .cur') && "
                                           "document.querySelector('#strip .cur').textContent.includes('Разбор')"))
            self.assertEqual(self.js("getComputedStyle(document.getElementById('strip')).display"), "flex")
            self.assertGreater(self.js("document.querySelector('#strip .cur').getBoundingClientRect().height"), 0)
            self.assertGreater(self.js("document.querySelector('#strip .scrchip').getBoundingClientRect().height"), 0)
            self.assertIn("Приветствие", self.js("document.querySelector('#strip .prev').textContent"))
            self.assertIn("Итоги", self.js("document.querySelector('#strip .next').textContent"))
            self.assertIn("конец", self.js("document.querySelector('#strip').textContent"))
            self.js("document.querySelector('#strip .more').click()")
            self.assertTrue(self.edge.wait("getComputedStyle(document.getElementById('plan')).display !== 'none'"))
            self.js("document.querySelector('#strip .more').click()")
            self.assertTrue(self.edge.wait("getComputedStyle(document.getElementById('plan')).display === 'none'"))
            self.mode("prep")
            self.assertTrue(self.edge.wait("getComputedStyle(document.getElementById('plan')).display !== 'none' && "
                                           "getComputedStyle(document.getElementById('strip')).display === 'none'"))
        finally:
            self.stop_live()


def slide_ref(n: int) -> str:
    from PySide6.QtGui import QColor, QImage
    folder = storage.DATA_DIR / storage.MEDIA_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"page-slide-{n}.png"
    im = QImage(64, 36, QImage.Format.Format_RGB32)
    im.fill(QColor(30 * n, 60, 90))
    im.save(str(p), "PNG")
    return storage.media_ref(p)


def slides_lesson() -> list[Template]:
    return [Template("Слайды", [stage("Презентация", 30, id="ps"),
                                Block(BLOCK_IMAGE, slide_ref(1), title="Титул", slide=1, id="sl1"),
                                note("Скажи про тему", id="sn1"),
                                Block(BLOCK_IMAGE, slide_ref(2), title="План", slide=2, id="sl2"),
                                Block(BLOCK_IMAGE, slide_ref(3), title="Итоги", slide=3, id="sl3")], id="SL")]


class PageSlidesTest(Page):
    """0.11 Task 8: слайды — «На экран», кликер ◀ ▶ / PageUp / PageDown, B — фон."""
    templates = staticmethod(slides_lesson)

    def shown(self):
        ef = self.win.efir
        return (ef.slide or {}).get("bid") if ef.mode == "slide" else ""

    def test_slide_button(self):
        self.mode("lesson")
        self.assertEqual(self.js("document.querySelector('[data-id=sl2] .lbl .rname').textContent"), "Слайд 2")
        self.js("document.querySelector('[data-id=sl2] .toscreen').click()")
        self.assertTrue(self.wait_py(lambda: self.shown() == "sl2"))
        self.assertTrue(self.edge.wait("!!document.querySelector('.blk.onscreen[data-id=sl2]')"))
        self.assertTrue(self.edge.wait("document.querySelector('#strip .scrchip').textContent.includes('слайд 2')"))
        self.win.efir.show_background()

    def test_paste_answer_box(self):
        self.mode("prep")
        more = "[...document.querySelectorAll('#tools .iconbtn.only')].find(b => b.getAttribute('aria-label') === 'Ещё')"
        self.js(f"{more}.click()")
        self.assertTrue(self.edge.wait("!!document.querySelector('.menu')"))
        self.assertTrue(self.js("[...document.querySelectorAll('.menu .mi .ml')].some(x => x.textContent === 'Промпт для слайдов…')"))
        self.js("[...document.querySelectorAll('.menu .mi')].find(b => b.textContent.includes('Вставить ответ нейросети')).click()")
        self.assertTrue(self.edge.wait("!!document.querySelector('.modal .ansta')"))
        answer = "~~~markdown\n---\ntitle: По ответу\n---\n\n## Всё · 30 мин\n\n![Слайд 2](slide:2)\n\n> [!say]\n> Текст\n~~~"
        self.js(f"document.querySelector('.modal .ansta').value = {answer!r}")
        self.js("[...document.querySelectorAll('.modal button')].find(b => b.textContent === 'Добавить урок').click()")
        self.assertTrue(self.wait_py(lambda: any(x.title == "По ответу" for x in self.win.store.templates)))
        self.assertTrue(self.edge.wait("!document.querySelector('.modal')"))
        new = next(x for x in self.win.store.templates if x.title == "По ответу")
        self.assertEqual([b.slide for b in new.blocks if b.type == BLOCK_IMAGE], [2])
        self.win.open_lesson(self.t.id, ask=False)
        self.win.store.templates[:] = [x for x in self.win.store.templates if x.id != new.id]
        self.win.lesson.publish()
        self.assertTrue(self.edge.wait(f"document.getElementById('titleText').textContent === '{self.t.title}'"))

    def test_restore_keeps_slide_number(self):
        self.mode("prep")
        ids = lambda: [b.id for b in self.t.blocks]
        self.js("document.querySelector('[data-id=sl3] .lbl').click()")
        self.edge.key("Delete", "Delete", 46)
        self.assertTrue(self.wait_py(lambda: "sl3" not in ids()))
        self.js("document.querySelector('#toast button').click()")                       # «Вернуть»
        self.assertTrue(self.wait_py(lambda: "sl3" in ids()))
        self.assertEqual(self.t.find_block("sl3").slide, 3)                              # снова «Слайд 3», не картинка

    def test_clicker_quiet_with_modal(self):
        self.mode("lesson")
        more = "[...document.querySelectorAll('#tools .iconbtn.only')].find(b => b.getAttribute('aria-label') === 'Ещё')"
        self.js(f"{more}.click()")
        self.assertTrue(self.edge.wait("!!document.querySelector('.menu')"))
        self.js("[...document.querySelectorAll('.menu .mi')].find(b => b.textContent.includes('Распечатать')).click()")
        self.assertTrue(self.edge.wait("!!document.querySelector('.modal')"))
        self.edge.key("ArrowRight", "ArrowRight", 39)
        pump(500)
        self.assertEqual(self.win.efir.mode, "idle")                                    # окно печати открыто — слайды не листаем
        self.js("document.querySelector('.modal').remove()")

    def test_clicker_keys(self):
        self.mode("lesson")
        self.js("document.activeElement && document.activeElement.blur && document.activeElement.blur()")
        self.edge.key("ArrowRight", "ArrowRight", 39)
        self.assertTrue(self.wait_py(lambda: self.shown() == "sl1"), self.shown())
        self.edge.key("PageDown", "PageDown", 34)
        self.assertTrue(self.wait_py(lambda: self.shown() == "sl2"), self.shown())
        self.edge.key("PageUp", "PageUp", 33)
        self.assertTrue(self.wait_py(lambda: self.shown() == "sl1"), self.shown())
        self.edge.key("b", "KeyB", 66)
        self.assertTrue(self.wait_py(lambda: self.win.efir.mode == "idle"))
        self.mode("prep")                                           # правка заметки — стрелки двигают курсор
        self.js("document.querySelector('[data-id=sn1] .row > .c').click()")
        self.assertTrue(self.edge.wait("document.activeElement && document.activeElement.isContentEditable"))
        self.edge.key("ArrowRight", "ArrowRight", 39)
        pump(600)
        self.assertEqual(self.win.efir.mode, "idle")
        self.js("document.activeElement.blur()")


def big_lesson() -> list[Template]:
    blocks = []
    for k in range(10):
        blocks.append(stage(f"Этап {k + 1}", 9))
        for j in range(8):
            if j % 3 == 2:
                blocks.append(code("\n".join(f"value_{k}_{j}_{i} = compute({i}, 'text')" for i in range(15))))
            else:
                blocks.append(note(f"Текст заметки **{k}.{j}** — что сказать ученикам на этом шаге урока.",
                                   role=["say", "tell", "ask", "do", "important"][j % 5]))
    return [Template("Большой урок", blocks[:90], id="BIG")]


class PagePerfTest(Page):
    """Task 11: большой урок — быстро, ввод не перерисовывает ленту."""
    templates = staticmethod(big_lesson)

    def test_big_lesson(self):
        self.assertGreaterEqual(self.js("document.querySelectorAll('.blk[data-id]').length"), 70)
        ms = self.js("window.__applyMs")
        self.assertLess(ms, 300, f"{ms:.0f} мс")

    def test_typing_no_rerender(self):
        self.mode("prep")
        before = self.js("window.__renders()")
        self.js("document.querySelectorAll('.blk[data-type=markdown] .row > .c')[3].click()")
        self.assertTrue(self.edge.wait("document.activeElement && document.activeElement.isContentEditable"))
        for ch in "двадцать букв подряд":
            self.edge.text(ch)
        pump(1200)
        self.assertEqual(self.js("window.__renders()"), before)
        self.js("document.activeElement.blur()")


def plan_lessons() -> list[Template]:
    """Урок «Функции» по плану «Онлайн 90» (этапы ts1…ts4), сам план и обычный урок."""
    from autoprint import plans
    p = Template("Онлайн 90", [stage("Приветствие", 5, id="p1"), stage("Теория", 20, id="p2"),
                               stage("Перерыв", 10, id="p3", stage_kind="break"), stage("Практика", 30, id="p4")],
                 id="P", kind="plan")
    t = plans.new_topic(p, "Функции")
    t.id = "T"
    for i, b in enumerate(b for b in t.blocks if b.type == BLOCK_STAGE):
        b.id = f"ts{i + 1}"
    return [t, p, Template("Свободный", [stage("А", 5, id="fa"), note("Текст", id="fn")], id="F")]


class PageV12Test(Page):
    """0.12: урок по плану, страница плана, меню «По плану»."""
    templates = staticmethod(plan_lessons)

    def setUp(self):
        self.js("window.confirm = () => true")
        if self.win.printer.focus_id != "T":
            self.open_lesson("T")

    def open_lesson(self, lid):
        self.win.open_lesson(lid, ask=False)
        self.republish()
        title = self.store.get(lid).title
        self.assertTrue(self.edge.wait(f"document.getElementById('titleText').textContent === {title!r}"))

    def close_menu(self):
        self.js("document.body.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}))")

    def test_fixed_topic_stage_readonly(self):
        self.mode("prep")
        self.assertTrue(self.edge.wait("!!document.querySelector('#st-ts1 .mins.fixed')"))
        self.assertTrue(self.js("document.querySelector('#st-ts1 .kindbtn').disabled"))
        self.assertFalse(self.js("!!document.querySelector('#plan input.pmin')"))
        self.assertIn("из плана «Онлайн 90»", self.js("document.querySelector('#plan .phint').textContent"))
        self.assertIn("Онлайн 90", self.js("document.getElementById('planlink').textContent"))
        self.assertFalse(self.js("document.getElementById('planlink').hidden"))
        self.js("document.querySelector('.ins .insbtn').click()")
        self.assertTrue(self.edge.wait("!!document.querySelector('.menu')"))
        self.assertFalse(self.js("[...document.querySelectorAll('.menu .mi')].some(b => b.textContent.startsWith('Этап'))"))
        self.close_menu()

    def test_refused_edit_shows_message_no_retry(self):     # Review Focus 5
        self.js("window.__suflor.push({op: 'set', block: 'ts1', fields: {minutes: 3}})")
        self.assertTrue(self.edge.wait("document.getElementById('toast').textContent.includes('задаёт план')"))
        self.assertTrue(self.edge.wait("window.__suflor.busy() === 0", 5))
        self.assertEqual(self.store.get("T").find_block("ts1").minutes, 5)

    def test_edit_in_plan_while_live_asks(self):            # Review Focus 1, вторая часть
        self.mode("lesson")
        self.go_live(1)
        try:
            self.mode("prep")
            self.js("window.__confirmText = ''; window.confirm = (t) => { window.__confirmText = t; return false; }")
            self.js("document.querySelector('#st-ts1 .smore').click()")
            self.assertTrue(self.edge.wait("!!document.querySelector('.menu')"))
            self.js("[...document.querySelectorAll('.menu .mi')].find(b => b.textContent.startsWith('Изменить в плане')).click()")
            self.assertIn("Завершить его и открыть «Онлайн 90»", self.js("window.__confirmText"))
            pump(200)
            self.assertEqual(self.win.printer.focus_id, "T")                         # отказались — урок идёт дальше
            self.assertTrue(self.win.efir.live_lesson_id())
        finally:
            self.stop_live()

    def test_unlink_from_stage_menu(self):
        self.mode("prep")
        self.js("document.querySelector('#st-ts2 .smore').click()")
        self.assertTrue(self.edge.wait("!!document.querySelector('.menu')"))
        self.js("[...document.querySelectorAll('.menu .mi')].find(b => b.textContent.startsWith('Отвязать урок от плана')).click()")
        self.assertTrue(self.wait_py(lambda: self.store.get("T").plan_id == ""))
        self.assertTrue(self.edge.wait("!document.querySelector('#st-ts1 .mins.fixed')"))
        self.win.link_plan(self.store.get("T"), "P")                                 # вернуть для других тестов
        self.republish()

    def test_plan_stage_delete_asks_when_used(self):
        self.open_lesson("P")
        self.mode("prep")
        self.js("window.__confirmText = ''; window.confirm = (t) => { window.__confirmText = t; return false; }")
        self.js("document.querySelector('#st-p2 .smore').click()")
        self.assertTrue(self.edge.wait("!!document.querySelector('.menu')"))
        self.js("[...document.querySelectorAll('.menu .mi')].find(b => b.textContent.startsWith('Удалить этап')).click()")
        self.assertIn("В уроках по этому плану (1) заметки этапа «Теория» переедут в «Приветствие»",
                      self.js("window.__confirmText"))
        pump(200)
        self.assertIsNotNone(self.store.get("P").find_block("p2"))

    def test_plan_page_banner_and_new_topic(self):
        self.open_lesson("P")
        self.mode("prep")
        self.assertTrue(self.edge.wait("document.getElementById('planbanner').textContent.includes('Функции')"))
        self.assertFalse(self.js("document.getElementById('planbanner').hidden"))
        self.js("document.getElementById('lessonsBtn').click()")
        self.assertTrue(self.edge.wait("!!document.querySelector('.menu .mi.newl')"))
        self.assertIn("По плану «Онлайн 90»", self.js("document.querySelector('.menu .mi.newl').textContent"))
        heads = self.js("[...document.querySelectorAll('.menu .mhead, .menu .head')].map(x => x.textContent)")
        self.assertIn("Планы", heads)
        self.close_menu()
        self.open_lesson("F")
        self.assertTrue(self.js("document.getElementById('planbanner').hidden"))
        self.assertTrue(self.js("document.getElementById('planlink').hidden"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
