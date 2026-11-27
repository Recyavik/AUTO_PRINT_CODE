"""Правка урока в окне программы: переключатель «Правка», правка на месте, «+», перенос, удаление с «Вернуть»,
картинки и места для них, урок по плану (замок «из плана»), план как документ, слайды кликером, скорость.
Перенесено со старого экрана урока (tests/test_page.py) на окно программы.

    .venv\\Scripts\\python.exe tests\\test_app_edit.py
"""
from __future__ import annotations

import unittest
from pathlib import Path

from apphelp import AppPage, code, note, pump, stage  # noqa: F401

from autoprint import storage
from autoprint.storage import BLOCK_IMAGE, BLOCK_MARKDOWN, BLOCK_STAGE, Block, Template

PNG_1x1 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
PASTE_PNG = f"""(() => {{
    const bin = atob('{PNG_1x1}'); const a = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i);
    const dt = new DataTransfer(); dt.items.add(new File([a], 'p.png', {{type: 'image/png'}}));
    document.dispatchEvent(new ClipboardEvent('paste', {{clipboardData: dt, bubbles: true}}));
}})()"""
EDITABLE = "document.activeElement && document.activeElement.isContentEditable"


class EditPage(AppPage):
    """Окно программы на экране урока + помощники правки."""
    lesson_id = ""

    def setUp(self):
        if self.app.efir.live_webinar() is not None:
            self.stop_live()
        self.open_lesson(self.lesson_id)

    def tearDown(self):
        self.js("window.appUI.closePop(); document.querySelectorAll('.scrim').forEach(s => s.remove());"
                " document.querySelectorAll('body > .menu').forEach(m => m.remove())")
        if self.app.efir.live_webinar() is not None:
            self.stop_live()
        super().tearDown()

    @property
    def t(self) -> Template:
        return self.store.get(self.lesson_id)

    def block(self, bid, tid=None):
        return self.store.get(tid or self.lesson_id).find_block(bid)

    def ids(self, tid=None):
        return [b.id for b in self.store.get(tid or self.lesson_id).blocks]

    def republish(self):
        self.app.lesson._last = None
        self.app.lesson.publish()
        pump(100)

    def open_lesson(self, lid):
        if self.app.printer.focus_id != lid or not self.js(f"location.hash === '#/lesson/{lid}'"):
            self.app.open_lesson(lid, ask=False)
        self.republish()
        self.go(f"#/lesson/{lid}", "lesson")
        title = self.store.get(lid).title
        self.assertTrue(self.wait_js(f"document.title === {title + ' — AutoPrintCode'!r}"), title)
        self.assertTrue(self.wait_js("!!document.querySelector('#main .stage, #main .blk[data-id]')"))

    def editing(self, on: bool = True):
        if self.js("document.body.classList.contains('editing')") != on:
            self.click("#editToggle")
        self.assertTrue(self.wait_js(f"document.body.classList.contains('editing') === {str(on).lower()}"))

    def toast_text(self) -> str:
        return self.js("(document.getElementById('toasts') || {}).textContent || ''")

    def toast_action(self):
        self.assertTrue(self.wait_js("[...document.querySelectorAll('#toasts .toast button')].length > 0"))
        self.js("[...document.querySelectorAll('#toasts .toast button')].pop().click()")

    def sheet_text(self) -> str:
        self.assertTrue(self.wait_js("!!document.querySelector('.scrim .sheet')"))
        return self.js("document.querySelector('.scrim .sheet').textContent")

    def sheet_answer(self, ok: bool):
        self.js("{ const b = [...document.querySelectorAll('.scrim .sheet .sfoot button')];"
                f" (b.find(x => x.classList.contains({'primary' if ok else 'ghost'!r})"
                f" || ({str(ok).lower()} && x.classList.contains('danger'))) || b[b.length - 1]).click(); }}")
        self.assertTrue(self.wait_js("!document.querySelector('.scrim')"))

    def menu_click(self, starts: str):
        self.assertTrue(self.wait_js("!!document.querySelector('.menu')"))
        self.js(f"[...document.querySelectorAll('.menu .mi')].find(b => b.textContent.trim().startsWith({starts!r})).click()")

    def no_confirm(self):
        """Правка спрашивает листом окна, а не confirm() браузера."""
        self.js("window.confirm = () => { throw new Error('confirm() вместо листа'); }")


# ================================================================ обычный урок: правка на месте
def lesson() -> list[Template]:
    return [Template("Проверка экрана", [
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
    ], id="L1")]


class EditTest(EditPage):
    port = 18985
    templates = staticmethod(lesson)
    route = "#/lesson/L1"
    lesson_id = "L1"

    def setUp(self):
        super().setUp()
        self.no_confirm()
        self.editing(True)

    def test_edit_toggle_default(self):
        self.assertTrue(self.js("document.querySelector('#editToggle').getAttribute('aria-pressed') === 'true'"))
        self.go_live(1, tid="L1")
        self.assertTrue(self.wait_js("!document.body.classList.contains('editing')", 6))      # идёт урок — правка выкл.
        self.assertEqual(self.js("document.querySelector('#editToggle').getAttribute('aria-pressed')"), "false")
        self.click("#editToggle")
        self.assertTrue(self.wait_js("document.body.classList.contains('editing')"))            # опечатку на уроке — можно
        self.stop_live()
        self.assertTrue(self.wait_js("document.body.classList.contains('editing')"))

    def test_selected_block_keeps_its_height(self):
        """Выбранный блок (класс sel) — не выпадающий список (.sel у <select> — 40 px): заметка в правке не схлопывается."""
        self.js("document.querySelector('[data-id=n1] .row > .c').click()")
        self.assertTrue(self.wait_js(EDITABLE))
        self.assertTrue(self.wait_js("document.querySelector('[data-id=n1]').classList.contains('sel')"))
        blk, row = self.js("[document.querySelector('[data-id=n1]').getBoundingClientRect().bottom, "
                           "document.querySelector('[data-id=n1] .row').getBoundingClientRect().bottom]")
        self.assertGreaterEqual(blk + 1, row, "строка заметки вылезает из блока")
        self.js("document.activeElement.blur()")

    def test_click_edit_same_height(self):
        h0 = self.js("document.querySelector('[data-id=n1] .row > .c').getBoundingClientRect().height")
        self.js("document.querySelector('[data-id=n1] .row > .c').click()")
        self.assertTrue(self.wait_js(EDITABLE))
        h1 = self.js("document.activeElement.getBoundingClientRect().height")
        self.assertLessEqual(abs(h1 - h0), 2, f"было {h0}, в правке {h1}")
        self.js("document.activeElement.blur()")

    def test_type_saves(self):
        self.js("document.querySelector('[data-id=n4] .row > .c').click()")
        self.assertTrue(self.wait_js(EDITABLE))
        self.edge.text(" Привет!")
        self.assertTrue(self.wait_py(lambda: self.block("n4").text.endswith(" Привет!")), self.block("n4").text)
        self.js("document.activeElement.blur()")
        self.assertTrue(self.wait_js("!document.querySelector('[data-id=n4] .rich') && "
                                     "document.querySelector('[data-id=n4] .c').textContent.includes('Привет!')"))
        self.assertTrue(self.wait_js("document.getElementById('saveChip').textContent.includes('Сохранено')"))
        self.block("n4").text = "Вопросы?"
        self.republish()

    def test_echo_keeps_caret(self):
        self.js("document.querySelector('[data-id=n2] .row > .c').click()")
        self.assertTrue(self.wait_js(EDITABLE))
        self.js("{ const t = document.activeElement; t.__mark = 1; const tn = t.querySelector('p').firstChild;"
                " const r = document.createRange(); r.setStart(tn, 3); r.collapse(true);"
                " const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r); }")
        self.block("intro1").text = "Цель: научиться писать функции (обновлено)."
        self.app.lesson.publish()
        self.assertTrue(self.wait_js("document.querySelector('[data-id=intro1] .c').textContent.includes('обновлено')"))
        self.assertTrue(self.js("document.activeElement.__mark === 1 && getSelection().anchorOffset === 3"))
        self.js("document.activeElement.blur()")

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
        self.assertTrue(self.wait_js(EDITABLE))
        self.assertTrue(self.wait_js("!!document.querySelector('.rtb [data-cmd=bold]')"))
        self.select_text("n1", "Сегодня")
        self.tool("bold")
        self.assertTrue(self.wait_py(lambda: "**Сегодня**" in self.block("n1").text), self.block("n1").text)
        self.assertNotIn("*", self.js("document.querySelector('[data-id=n1] .rich').textContent"))
        self.select_text("n1", "Сегодня")
        self.tool("bold")
        self.assertTrue(self.wait_py(lambda: "*" not in self.block("n1").text), self.block("n1").text)
        self.js("document.activeElement.blur()")

    def test_rich_roundtrip(self):
        md = ("**a** *b* `c` [d](https://x.ru) и https://y.ru\n\n- e\n- f\n\n1. g\n2. h\n\n# Заголовок\n\n"
              "строка\nещё строка")
        self.assertEqual(self.js(f"window.__rt.roundtrip({md!r})"), md)
        self.assertEqual(self.js("window.__rt.roundtrip('**a** b\\n- e')"), "**a** b\n\n- e")
        before = self.block("n3").text
        self.js("document.querySelector('[data-id=n3] .row > .c').click()")
        self.assertTrue(self.wait_js(EDITABLE))
        self.js("document.activeElement.blur()")
        pump(600)
        self.assertEqual(self.block("n3").text, before)

    def test_rich_escapes_and_paste_sources(self):
        md = self.js("(() => { const d = document.createElement('div');"
                     " d.innerHTML = '<p>2024. Год начала курса!</p><p>x**2 + y**2</p>'; return window.__rt.toMarkdown(d); })()")
        self.assertEqual(md, "2024\\. Год начала курса!\n\nx\\*\\*2 + y\\*\\*2")
        self.assertEqual(self.js(f"window.__rt.roundtrip({md!r})"), md)
        gdocs = ('<b style="font-weight:normal" id="docs-internal-guid-1"><p>Первая</p>'
                 '<p><b>Жирное</b> обычное</p></b>')
        got = self.js(f"(() => {{ const d = document.createElement('div'); d.innerHTML = window.__rt.cleanPaste({gdocs!r});"
                      " return window.__rt.toMarkdown(d); })()")
        self.assertEqual(got, "Первая\n\n**Жирное** обычное")

    def test_homework_copy_item(self):
        self.block("n4").role = "homework"
        self.republish()
        try:
            self.assertTrue(self.wait_js("!!document.querySelector('[data-id=n4] .r-homework')"))
            self.js("document.querySelector('[data-id=n4] .bmore').click()")
            self.assertTrue(self.wait_js("!!document.querySelector('.menu')"))
            self.assertTrue(self.js("[...document.querySelectorAll('.menu .mi')].some(b => b.textContent.includes('Скопировать для чата'))"))
        finally:
            self.block("n4").role = "tell"
            self.republish()

    def test_ask_fields(self):
        q = "Что такое функция?\n→ кусок кода с именем"
        self.assertEqual(self.block("n2").text, q)
        self.js("document.querySelector('[data-id=n2] .row > .c').click()")
        self.assertTrue(self.wait_js("document.querySelectorAll('[data-id=n2] .ansin').length === 1"))
        self.assertEqual(self.js("document.querySelector('[data-id=n2] .ansin').value"), "кусок кода с именем")
        self.js("document.querySelector('[data-id=n2] .addans').click()")
        self.assertTrue(self.wait_js("document.activeElement && document.activeElement.classList.contains('ansin')"))
        self.edge.text("блок с именем")
        self.assertTrue(self.wait_py(lambda: self.block("n2").text == q + "\n→ блок с именем"), self.block("n2").text)
        self.js("document.querySelectorAll('[data-id=n2] .ansdel')[1].click()")
        self.assertTrue(self.wait_py(lambda: self.block("n2").text == q), self.block("n2").text)
        self.js("document.activeElement.blur()")

    def test_paste_word(self):
        self.js("document.querySelector('.ins[data-after=n4] .insbtn').click()")
        self.menu_click("Заметка")
        self.assertTrue(self.wait_py(lambda: self.ids()[-1] != "n4"))
        new = self.ids()[-1]
        self.assertTrue(self.wait_js(EDITABLE))
        html = ('<html><body><!--StartFragment--><p class=MsoNormal style="margin:0"><b><span style="font-size:14pt">Жир</span></b> '
                '<span style="color:red">текст</span></p><ul><li>раз</li><li>два</li></ul><!--EndFragment--></body></html>')
        self.js(f"""{{ const dt = new DataTransfer(); dt.setData('text/html', {html!r}); dt.setData('text/plain', 'Жир текст');
            document.activeElement.dispatchEvent(new ClipboardEvent('paste', {{clipboardData: dt, bubbles: true, cancelable: true}})); }}""")
        self.assertTrue(self.wait_py(lambda: (self.block(new) or Block(BLOCK_MARKDOWN, "")).text == "**Жир** текст\n\n- раз\n- два"))
        self.js("document.activeElement.blur()")
        self.js(f"document.querySelector('[data-id=\"{new}\"] .lbl').click()")
        self.edge.key("Delete", "Delete", 46)
        self.assertTrue(self.wait_py(lambda: new not in self.ids()))

    def test_plus_inserts_role(self):
        n0 = len(self.t.blocks)
        self.js("document.querySelector('.ins[data-after=n1] .insbtn').click()")
        self.menu_click("Спроси")
        self.assertTrue(self.wait_py(lambda: len(self.t.blocks) == n0 + 1))
        ids = self.ids()
        new = self.t.blocks[ids.index("n1") + 1]
        self.assertEqual((new.type, new.role), (BLOCK_MARKDOWN, "ask"))
        self.assertTrue(self.wait_js(EDITABLE))
        self.edge.text("Новый вопрос?")
        self.js("document.activeElement.blur()")
        self.assertTrue(self.wait_py(lambda: self.block(new.id).text == "Новый вопрос?"))
        self.js(f"document.querySelector('[data-id=\"{new.id}\"] .lbl').click()")
        self.edge.key("Delete", "Delete", 46)
        self.assertTrue(self.wait_py(lambda: new.id not in self.ids()))

    def test_palette_groups(self):
        self.assertEqual(self.js("document.querySelector('[data-id=n1] .lbl .how').textContent"), "· дословно")
        self.js("document.querySelector('.ins[data-after=n1] .insbtn').click()")
        self.assertTrue(self.wait_js("!!document.querySelector('.menu')"))
        heads = self.js("[...document.querySelectorAll('.menu .mhead')].map(h => h.textContent)")
        self.assertEqual(heads, ["Урок", "Речь", "Ученикам", "Действия", "Для себя", "Материалы"])
        labels = self.js("[...document.querySelectorAll('.menu .mi .ml')].map(x => x.textContent)")
        self.assertEqual(labels[-1], "Код")
        for name in ("Этап", "Цель урока", "Если застрял", "Домашнее задание", "Результат кода"):
            self.assertIn(name, labels)

    def test_minutes_in_plan(self):
        self.app.settings.page_plan = "side"
        self.app.publish_now()
        self.assertTrue(self.wait_js("document.body.classList.contains('plan-side') && !!document.querySelector('#pr-s3 .pmin')"))
        self.js("{ const i = document.querySelector('#pr-s3 .pmin'); i.focus(); i.select(); }")
        self.edge.text("12")
        self.edge.key("Enter", "Enter", 13)
        self.assertTrue(self.wait_py(lambda: self.block("s3").minutes == 12))
        self.assertTrue(self.wait_js("document.querySelector('#plan .ptotal').textContent === '27 мин'"))
        self.block("s3").minutes = 5
        self.republish()

    def test_move_keys(self):
        ids = self.ids
        self.js("document.querySelector('[data-id=n4] .lbl').click()")          # выделить блок, не правя текст
        self.edge.key("ArrowUp", "ArrowUp", 38, modifiers=1)                     # Alt+↑ — выше этапа «Итоги»
        self.assertTrue(self.wait_py(lambda: ids().index("n4") == ids().index("s3") - 1), ids())
        self.edge.key("ArrowDown", "ArrowDown", 40, modifiers=1)
        self.assertTrue(self.wait_py(lambda: ids().index("n4") == ids().index("s3") + 1), ids())
        self.js("window.__moveStage('s3', '')")
        self.assertTrue(self.wait_py(lambda: [i for i in ids() if i.startswith("s")][0] == "s3"), ids())
        self.js("window.__moveStage('s3', 's2')")
        self.assertTrue(self.wait_py(lambda: [i for i in ids() if i.startswith("s")] == ["s1", "s2", "s3"]), ids())

    def test_paste_image(self):
        n0 = sum(b.type == BLOCK_IMAGE for b in self.t.blocks)
        self.js("document.querySelector('[data-id=o1] .lbl').click()")
        self.js(PASTE_PNG)
        self.assertTrue(self.wait_py(lambda: sum(b.type == BLOCK_IMAGE for b in self.t.blocks) == n0 + 1))
        ids = self.ids()
        new = self.t.blocks[ids.index("o1") + 1]
        self.assertEqual(new.type, BLOCK_IMAGE)
        self.assertTrue(self.wait_js("!!document.querySelector('.blk[data-type=image] figure img')"))
        self.js(f"document.querySelector('[data-id=\"{new.id}\"] .lbl').click()")
        self.edge.key("Delete", "Delete", 46)
        self.assertTrue(self.wait_py(lambda: new.id not in self.ids()))

    def test_undo_insert_keeps_text(self):
        self.js("document.querySelector('.ins[data-after=n3] .insbtn').click()")
        self.menu_click("Говоришь")
        self.assertTrue(self.wait_py(lambda: self.ids()[self.ids().index("n3") + 1] != "c1"))
        new = self.ids()[self.ids().index("n3") + 1]
        self.assertTrue(self.wait_js(EDITABLE))
        self.edge.text("Определение — дословно.")
        self.js("document.activeElement.blur()")
        self.assertTrue(self.wait_py(lambda: (self.block(new) or Block(BLOCK_MARKDOWN, "")).text == "Определение — дословно."))
        self.edge.key("z", "KeyZ", 90, modifiers=2)                               # Ctrl+Z
        self.assertTrue(self.wait_py(lambda: new not in self.ids()))
        self.toast_action()                                                       # «Вернуть»
        self.assertTrue(self.wait_py(lambda: new in self.ids() and self.block(new).text == "Определение — дословно."))
        self.js(f"document.querySelector('[data-id=\"{new}\"] .lbl').click()")
        self.edge.key("Delete", "Delete", 46)
        self.assertTrue(self.wait_py(lambda: new not in self.ids()))

    def test_z_delete_undo(self):
        before = self.ids()[self.ids().index("n2") - 1]
        self.js("document.querySelector('[data-id=n2] .lbl').click()")
        self.edge.key("Delete", "Delete", 46)
        self.assertTrue(self.wait_py(lambda: "n2" not in self.ids()))
        self.assertTrue(self.wait_js("!document.querySelector('[data-id=n2]')"))
        self.toast_action()
        self.assertTrue(self.wait_py(lambda: "n2" in self.ids()))
        self.assertEqual(self.ids()[self.ids().index("n2") - 1], before)
        self.assertIn("→ кусок кода с именем", self.block("n2").text)

    def test_zz_offline_queue(self):
        n0 = len(self.t.blocks)
        self.app.efir.server.stop()
        pump(200)
        try:
            self.js("document.querySelector('[data-id=n1] .row > .c').click()")
            self.assertTrue(self.wait_js(EDITABLE))
            self.edge.text(" (без связи)")
            self.js("document.activeElement.blur()")
            self.js("document.querySelector('.ins[data-after=n1] .insbtn').click()")
            self.menu_click("Делаешь")
            self.js("document.activeElement.blur()")
            self.assertTrue(self.wait_js("document.getElementById('saveChip').textContent.includes('Нет связи')", 8))
            self.assertTrue(self.js("!!localStorage.getItem('suflor.pending.' + 'L1')"))
        finally:
            self.app.efir.ensure_server()
        self.assertTrue(self.wait_py(lambda: self.block("n1").text.endswith(" (без связи)") and len(self.t.blocks) == n0 + 1, 25))
        pump(1500)
        self.assertEqual(len(self.t.blocks), n0 + 1)
        self.assertEqual(self.block("n1").text.count("(без связи)"), 1)
        self.assertTrue(self.wait_js("document.getElementById('saveChip').textContent.includes('Сохранено')", 8))


# ================================================================ код: правка редактором
def two_codes() -> list[Template]:
    return [Template("Код и зарядка", [stage("Разбор", 10, id="s1"), note("Смотрим код", id="n1"),
                                       code("a = 1\nprint(a)", id="c1"), code("b = 2\nprint(b)", id="c2"),
                                       stage("Зарядка", 5, id="s2", stage_kind="exercise")], id="L2")]


class CodeEditTest(EditPage):
    port = 18984
    templates = staticmethod(two_codes)
    route = "#/lesson/L2"
    lesson_id = "L2"

    def setUp(self):
        super().setUp()
        self.editing(True)

    def test_code_edit(self):
        self.js("document.querySelector('[data-id=c1] .codebox pre').click()")
        self.assertTrue(self.wait_js("!!document.querySelector('[data-id=c1] .cm-editor')", 10))
        self.assertTrue(self.wait_js("!!(document.activeElement && document.activeElement.closest('.cm-editor'))"))
        self.edge.text("x=1\n")
        self.assertTrue(self.wait_py(lambda: "x=1" in self.block("c1").text), self.block("c1").text)
        self.js("document.querySelector('[data-id=c2] .codebox pre').click()")
        self.assertTrue(self.wait_js("!!document.querySelector('[data-id=c2] .cm-editor')", 10))
        self.assertTrue(self.wait_js("document.querySelectorAll('.cm-editor').length === 1", 5))
        self.assertTrue(self.wait_js("document.querySelector('[data-id=c1] pre').textContent.includes('x=1')", 5))
        self.js("document.activeElement.blur()")

    def test_code_steps_keys(self):
        self.js("document.querySelector('[data-id=c2] .codebox pre').click()")
        self.assertTrue(self.wait_js("!!(document.activeElement && document.activeElement.closest('[data-id=c2] .cm-editor'))", 10))
        self.edge.key("End", "End", 35, modifiers=2)                              # Ctrl+End — последняя строка
        self.edge.key("2", "Digit2", 50, modifiers=1)                             # Alt+2 — шаг 2
        self.assertTrue(self.wait_py(lambda: self.block("c2").steps[-1:] == [2]), self.block("c2").steps)
        self.js("document.activeElement.blur()")

    def test_type_button_not_edit_click(self):
        """«Набрать» в шапке кода в правке — набор, а не начало правки кода."""
        sent = []
        old = self.app.lesson._type
        self.app.lesson._type = lambda bid: sent.append(bid)
        try:
            self.click(".blk[data-id=c1] .typeBtn")
            self.assertTrue(self.wait_py(lambda: sent == ["c1"]))
            self.assertFalse(self.js("!!document.querySelector('.cm-editor')"))
        finally:
            self.app.lesson._type = old


# ================================================================ слайды: «На экран», кликер
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


class SlidesTest(EditPage):
    port = 18983
    templates = staticmethod(slides_lesson)
    route = "#/lesson/SL"
    lesson_id = "SL"

    def setUp(self):
        super().setUp()
        self.app.efir.clients = 1
        self.app.efir.show_background()

    def shown(self):
        ef = self.app.efir
        return (ef.slide or {}).get("bid") if ef.mode == "slide" else ""

    def test_slide_button(self):
        self.editing(False)
        self.assertEqual(self.js("document.querySelector('[data-id=sl2] .lbl .rname').textContent"), "Слайд 2")
        self.click("[data-id=sl2] .toscreen")
        self.assertTrue(self.wait_py(lambda: self.shown() == "sl2"))
        self.assertTrue(self.wait_js("!!document.querySelector('.blk.onscreen[data-id=sl2]')"))
        self.assertTrue(self.wait_js("document.querySelector('#screenThumb').dataset.tip.includes('слайд 2')"))

    def test_restore_keeps_slide_number(self):
        self.editing(True)
        self.js("document.querySelector('[data-id=sl3] .lbl').click()")
        self.edge.key("Delete", "Delete", 46)
        self.assertTrue(self.wait_py(lambda: "sl3" not in self.ids()))
        self.toast_action()
        self.assertTrue(self.wait_py(lambda: "sl3" in self.ids()))
        self.assertEqual(self.block("sl3").slide, 3)

    def test_clicker_quiet_with_sheet(self):
        self.editing(False)
        self.js("window.appUI.ask('Проверка'); true")
        self.assertTrue(self.wait_js("!!document.querySelector('.scrim .sheet')"))
        self.edge.key("ArrowRight", "ArrowRight", 39)
        pump(500)
        self.assertEqual(self.app.efir.mode, "idle")                    # открыт лист — слайды не листаем
        self.sheet_answer(False)

    def test_clicker_keys(self):
        self.editing(False)
        self.js("document.activeElement && document.activeElement.blur && document.activeElement.blur()")
        self.edge.key("ArrowRight", "ArrowRight", 39)
        self.assertTrue(self.wait_py(lambda: self.shown() == "sl1"), self.shown())
        self.edge.key("PageDown", "PageDown", 34)
        self.assertTrue(self.wait_py(lambda: self.shown() == "sl2"), self.shown())
        self.edge.key("PageUp", "PageUp", 33)
        self.assertTrue(self.wait_py(lambda: self.shown() == "sl1"), self.shown())
        self.edge.key("b", "KeyB", 66)
        self.assertTrue(self.wait_py(lambda: self.app.efir.mode == "idle"))
        self.editing(True)                                               # правка заметки — стрелки двигают курсор
        self.js("document.querySelector('[data-id=sn1] .row > .c').click()")
        self.assertTrue(self.wait_js(EDITABLE))
        self.edge.key("ArrowRight", "ArrowRight", 39)
        pump(600)
        self.assertEqual(self.app.efir.mode, "idle")
        self.js("document.activeElement.blur()")


# ================================================================ скорость
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


class PerfTest(EditPage):
    port = 18982
    templates = staticmethod(big_lesson)
    route = "#/lesson/BIG"
    lesson_id = "BIG"

    def test_big_lesson(self):
        self.assertGreaterEqual(self.js("document.querySelectorAll('.blk[data-id]').length"), 70)
        self.republish()
        self.assertTrue(self.wait_js("window.__applyMs > 0"))
        ms = self.js("window.__applyMs")
        self.assertLess(ms, 300, f"{ms:.0f} мс")

    def test_typing_no_rerender(self):
        self.editing(True)
        before = self.js("window.__renders()")
        self.js("document.querySelectorAll('.blk[data-type=markdown] .row > .c')[3].click()")
        self.assertTrue(self.wait_js(EDITABLE))
        for ch in "двадцать букв подряд":
            self.edge.text(ch)
        pump(1200)
        self.assertEqual(self.js("window.__renders()"), before)
        self.js("document.activeElement.blur()")


# ================================================================ урок по плану, план как документ, места
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
    return [t, p, Template("Свободный", [stage("А", 5, id="fa"), note("Текст", id="fn"),
                                         Block(BLOCK_IMAGE, "", title="Кот", id="ph"), Block(BLOCK_IMAGE, "", slide=3, id="ps"),
                                         stage("Зарядка", 3, id="fz", stage_kind="exercise")], id="F")]


class PlanTest(EditPage):
    port = 18981
    templates = staticmethod(plan_lessons)
    route = "#/lesson/T"
    lesson_id = "T"

    def setUp(self):
        super().setUp()
        self.no_confirm()
        self.app.settings.page_plan = "side"
        self.app.publish_now()

    def test_linked_stage_minutes_locked(self):
        self.editing(True)
        self.assertTrue(self.wait_js("!!document.querySelector('#st-ts1 .mins.fixed')"))
        self.assertIn("из плана", self.js("document.querySelector('#st-ts1 .mins.fixed').title"))
        self.assertTrue(self.js("document.querySelector('#st-ts1 .kindbtn').disabled"))
        self.assertFalse(self.js("!!document.querySelector('#plan input.pmin')"))
        self.assertIn("из плана «Онлайн 90»", self.js("document.querySelector('#plan .phint').textContent"))
        self.assertEqual(self.js("document.querySelector('#plan .openplan').textContent"), "Изменить план")
        self.js("document.querySelector('.ins .insbtn').click()")
        self.assertTrue(self.wait_js("!!document.querySelector('.menu')"))
        self.assertFalse(self.js("[...document.querySelectorAll('.menu .mi')].some(b => b.textContent.startsWith('Этап'))"))
        self.js("document.querySelectorAll('body > .menu').forEach(m => m.remove())")
        self.click("#plan .openplan")                                   # урок не идёт — план открывается сразу
        self.assertTrue(self.wait_py(lambda: self.app.printer.focus_id == "P"))

    def test_refused_edit_shows_message_no_retry(self):
        self.editing(True)
        self.js("window.__suflor.push({op: 'set', block: 'ts1', fields: {minutes: 3}})")
        self.assertTrue(self.wait_js("(document.getElementById('toasts') || {}).textContent.includes('задаёт план')"))
        self.assertTrue(self.wait_js("window.__suflor.busy() === 0", 5))
        self.assertEqual(self.block("ts1").minutes, 5)
        self.assertTrue(self.wait_js("document.querySelector('#st-ts1 .mins').textContent === '5'"))

    def test_fixed_title_not_editable(self):
        self.editing(True)
        self.js("document.querySelector('#st-ts1 .stitle').click()")
        pump(200)
        self.assertFalse(self.js("!!document.querySelector('#st-ts1 .inl-stage')"))
        self.assertIn("из плана", self.js("document.querySelector('#st-ts1 .stitle').title"))
        self.assertTrue(self.wait_js("(document.getElementById('toasts') || {}).textContent.includes('из плана «Онлайн 90»')"))

    def test_plan_banner_and_topics(self):
        self.open_lesson("P")
        self.assertTrue(self.wait_js("!document.getElementById('planbanner').hidden"))
        text = self.js("document.getElementById('planbanner').textContent")
        self.assertIn("План урока: этапы и минуты для всех уроков по нему (1)", text)
        self.assertIn("Функции", text)
        self.assertTrue(self.wait_js("document.querySelector('#startBtn').textContent.includes('Начать по плану')"))
        n0 = len(self.store.topics_of("P"))
        self.click("#newTopicBtn")                                     # «Новый урок по плану»
        self.assertTrue(self.wait_py(lambda: len(self.store.topics_of("P")) == n0 + 1))
        new = [x for x in self.store.topics_of("P") if x.id != "T"][0]
        self.app.delete_lesson(new, ask=False)
        self.open_lesson("F")
        self.assertTrue(self.js("document.getElementById('planbanner').hidden"))

    def test_banner_link_asks_while_live(self):
        self.open_lesson("P")
        self.go_live(1, tid="P")
        self.assertTrue(self.wait_js("document.querySelector('#lessonStatus').textContent.includes('этап 1 из 4')", 6))
        self.editing(True)
        self.click("#planbanner .linkbtn")
        self.assertIn("Завершить его и открыть «Функции»", self.sheet_text())
        self.sheet_answer(False)
        pump(200)
        self.assertEqual(self.app.printer.focus_id, "P")
        self.assertTrue(self.app.efir.live_lesson_id())

    def test_edit_in_plan_while_live_asks(self):
        self.go_live(1, tid="T")
        self.assertTrue(self.wait_js("document.querySelector('#lessonStatus').textContent.includes('этап 1 из 4')", 6))
        self.editing(True)
        self.click("#st-ts1 .smore")
        self.menu_click("Изменить в плане")
        self.assertIn("Завершить его и открыть «Онлайн 90»", self.sheet_text())
        self.sheet_answer(False)
        pump(200)
        self.assertEqual(self.app.printer.focus_id, "T")
        self.assertTrue(self.app.efir.live_lesson_id())

    def test_unlink_from_stage_menu_asks_sheet(self):
        self.editing(True)
        self.click("#st-ts2 .smore")
        self.menu_click("Отвязать урок от плана")
        self.assertIn("Отвязать урок «Функции» от плана «Онлайн 90»", self.sheet_text())
        self.sheet_answer(True)
        self.assertTrue(self.wait_py(lambda: self.store.get("T").plan_id == ""))
        self.assertTrue(self.wait_js("!document.querySelector('#st-ts1 .mins.fixed')"))
        self.app.link_plan(self.store.get("T"), "P")                    # вернуть для других тестов
        self.republish()

    def test_delete_block_asks_sheet(self):
        """Удаление этапа плана, по которому есть уроки, — вопрос листом окна (confirm() браузера бросает)."""
        self.open_lesson("P")
        self.editing(True)
        self.click("#st-p2 .smore")
        self.menu_click("Удалить этап")
        self.assertIn("В уроках по этому плану (1) заметки этапа «Теория» переедут в «Приветствие»", self.sheet_text())
        self.sheet_answer(False)
        pump(200)
        self.assertIsNotNone(self.store.get("P").find_block("p2"))

    def test_undo_deleted_exercise_stage_keeps_video(self):
        self.store.get("F").find_block("fz").exercise = "Шея"
        self.open_lesson("F")
        self.editing(True)
        self.click("#st-fz .smore")
        self.menu_click("Удалить этап")
        self.assertTrue(self.wait_py(lambda: self.store.get("F").find_block("fz") is None))
        self.js("document.activeElement && document.activeElement.blur && document.activeElement.blur()")
        self.edge.key("z", "KeyZ", 90, modifiers=2)                                  # Ctrl+Z
        self.assertTrue(self.wait_py(lambda: (self.store.get("F").find_block("fz") or Block("x")).exercise == "Шея"))

    def test_time_labels(self):
        self.editing(False)
        clock = "document.querySelector('#st-ts1 .clock')"
        self.assertTrue(self.wait_js(f"{clock}.textContent === '0:00–0:05'"))
        self.assertIn("От начала урока", self.js(f"{clock}.title"))
        self.go_live(1, tid="T")
        self.assertTrue(self.wait_js(f"/^\\d{{1,2}}:\\d\\d–\\d{{1,2}}:\\d\\d$/.test({clock}.textContent) && "
                                     f"{clock}.textContent !== '0:00–0:05'", 6))
        self.assertIn("от начала урока", self.js(f"{clock}.title"))
        self.assertRegex(self.js("document.querySelector('#pr-ts2 .t').textContent"), r"^\d{1,2}:\d\d$")

    def test_plan_click_while_live_only_scrolls(self):
        self.go_live(1, tid="T")
        self.assertTrue(self.wait_js("document.querySelector('#lessonStatus').textContent.includes('этап 1 из 4')", 6))
        before = self.app.efir.store.live.anchor
        self.click("#pr-ts3 .n")
        pump(300)
        self.assertFalse(self.js("!!document.querySelector('.scrim')"))
        self.assertEqual(self.app.efir.store.live.anchor, before)

    def test_exercise_choice_in_kind_menu(self):
        from autoprint.efir.model import Exercise, Look
        video = Path(storage.DATA_DIR) / "zaryadka-test.mp4"
        video.write_bytes(b"\x00" * 16)
        look = Look(title="С зарядками", exercises=[Exercise("Глаза", str(video)), Exercise("Шея", str(video))])
        self.app.efir.save_look(look)
        self.store.get("F").look = look.id
        self.store.get("F").find_block("fz").exercise = ""
        self.open_lesson("F")
        self.editing(True)
        self.assertTrue(self.wait_js("!!document.querySelector('#st-fz .efirbtn')"))
        # 1.2.1: своего видео у этапа нет, видео два — кнопка включает следующее по очереди и называет его
        # («Спросить» в настройках — снова «Выбрать зарядку ученикам…», см. test_app_lesson)
        self.assertRegex(self.js("document.querySelector('#st-fz .efirbtn').textContent"),
                         r"^Включить зарядку ученикам · (Глаза|Шея)$")
        self.click("#st-fz .kindbtn")
        self.menu_click("Шея")
        self.assertTrue(self.wait_py(lambda: self.store.get("F").find_block("fz").exercise == "Шея"))
        self.assertTrue(self.wait_js("document.querySelector('#st-fz .efirbtn').textContent.includes('Шея')"))

    def test_places_render_and_replace(self):
        self.open_lesson("F")
        self.editing(True)
        self.assertTrue(self.wait_js("!!document.querySelector('[data-id=ph] .placebox')"))
        self.assertIn("Нужна картинка: Кот", self.js("document.querySelector('[data-id=ph]').textContent"))
        self.assertIn("Слайд 3 — картинки нет", self.js("document.querySelector('[data-id=ps]').textContent"))
        # 1.1.4: на месте — значок картинки (урок, сохранённый без картинок, показывает, что картинка здесь была)
        self.assertTrue(self.js("!!document.querySelector('[data-id=ps] .placebox .pico svg')"))
        self.assertTrue(self.js("!!document.querySelector('[data-id=ph] .find')"))
        self.assertTrue(self.js("!!document.querySelector('[data-id=ps] .fillslides')"))
        self.assertFalse(self.js("!!document.querySelector('[data-id=ps] .toscreen')"))
        self.js("document.querySelector('[data-id=ps] .lbl').click()")                    # выделить место
        self.js(PASTE_PNG)
        F = lambda: self.store.get("F")
        self.assertTrue(self.wait_py(lambda: F().find_block("ps") is None and any(b.slide == 3 and b.text for b in F().blocks)))

    def test_place_pick_file(self):
        """«Выбрать файл…» на месте картинки — системное окно программы, картинка встаёт на место с подписью."""
        import base64
        import tempfile
        png = Path(tempfile.mkdtemp()) / "kot.png"
        png.write_bytes(base64.b64decode(PNG_1x1))
        self.store.get("F").blocks.insert(1, Block(BLOCK_IMAGE, "", title="Пёс", id="ph2"))
        self.open_lesson("F")
        self.editing(True)
        cmds = self.app.commands
        old = cmds.call_pick_files
        cmds.call_pick_files = lambda d: [str(png)] if d.get("purpose") == "image" else []
        try:
            self.assertTrue(self.wait_js("!!document.querySelector('[data-id=ph2] [data-act=place-insert]')"))
            self.assertEqual(self.js("document.querySelector('[data-id=ph2] [data-act=place-insert]').textContent"), "Выбрать файл…")
            self.click("[data-id=ph2] [data-act=place-insert]")
            F = lambda: self.store.get("F")
            self.assertTrue(self.wait_py(lambda: F().find_block("ph2") is None and
                                         any(b.type == BLOCK_IMAGE and b.title == "Пёс" and b.text for b in F().blocks)),
                            self.toast_text() + " | " + str([(b.id, b.type, b.title, b.text) for b in F().blocks]))
        finally:
            cmds.call_pick_files = old

    def test_efir_row_open_tab_button(self):
        opened = []
        orig = self.app.efir.open_tab
        self.app.efir.open_tab = lambda: opened.append(1)
        self.app.efir.clients = 0
        try:
            self.open_lesson("F")
            self.assertTrue(self.wait_js("!!document.querySelector('#st-fz .efirbtn.opentab')"))
            self.click("#st-fz .efirbtn.opentab")
            self.assertTrue(self.wait_py(lambda: len(opened) == 1))
        finally:
            self.app.efir.open_tab = orig
            self.app.efir.clients = 1


# ================================================================ старый адрес экрана урока
class RouteTest(unittest.TestCase):
    def test_lesson_route_redirect(self):
        import http.client
        from autoprint.efir.server import BroadcastServer
        srv = BroadcastServer(18980)
        self.assertTrue(srv.start())
        try:
            c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
            c.request("GET", "/lesson", headers={"Host": f"127.0.0.1:{srv.port}"})
            r = c.getresponse()
            self.assertEqual(r.status, 302)
            self.assertEqual(r.getheader("Location"), "/app#/lesson")
            c.close()
        finally:
            srv.stop()

    def test_old_page_removed(self):
        from autoprint.efir.server import PAGE_DIR
        self.assertFalse((PAGE_DIR / "lesson.html").exists())
        self.assertFalse((PAGE_DIR / "lesson" / "app.js").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
