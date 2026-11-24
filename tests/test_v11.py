"""0.11 — урок по событиям: «Мои настройки», экран учеников с экрана урока, роли, слайды и презентации,
промпт для своего чата, шаблоны структуры. Всё без окон на экране.

    python tests/test_v11.py
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import quiet  # noqa: E402,F401  — до PySide6: offscreen, своя папка данных

from test_v10 import TMP, code, make_window, note, pump, stage  # noqa: E402  (там же QApplication и тема)

from autoprint import storage  # noqa: E402
from autoprint.storage import BLOCK_CODE, BLOCK_IMAGE, BLOCK_MARKDOWN, BLOCK_STAGE, Block, Template  # noqa: E402,F401


def lesson_with_stages(tid: str = "L") -> Template:
    return Template("Урок", [stage("Начало", 10, id="s1"), note("Добрый день", id="n1"),
                             stage("Перерыв", 10, id="s2", stage_kind="break"),
                             stage("Практика", 20, id="s3"), code("print(1)", id="c1")], id=tid)


class Base(unittest.TestCase):
    port = 18970

    def setUp(self):
        self.L = lesson_with_stages()
        self.win = make_window([self.L], port=self.port)
        self.win.lesson.open_page = lambda: None
        self.win.printer.set_focus("L")

    def tearDown(self):
        ef = self.win.efir
        if ef.live_webinar() is not None:
            ef.stop_live()
        if ef.timer_window is not None:
            ef.timer_window.close_silently()
        self.win._quitting = True
        self.win.close()
        pump()

    def state(self) -> dict:
        self.win.lesson._last = None
        self.win.lesson.publish()
        return self.win.efir.server._states["lesson"]


# ================================================================ Task 1: «Мои настройки»

class PrefsTest(Base):
    def test_defaults(self):
        s = storage.Settings()
        self.assertEqual((s.page_zoom, s.page_plan, s.page_past, s.page_stage_timer, s.start_timer, s.start_screen),
                         (100, "strip", "dim", True, False, False))

    def test_prefs_command(self):
        cmd = self.win.lesson.command
        cmd({"cmd": "prefs", "key": "page_zoom", "value": 130})
        cmd({"cmd": "prefs", "key": "page_plan", "value": "side"})
        cmd({"cmd": "prefs", "key": "page_past", "value": "collapse"})
        cmd({"cmd": "prefs", "key": "page_stage_timer", "value": False})
        cmd({"cmd": "prefs", "key": "start_timer", "value": True})
        s = self.win.settings
        self.assertEqual((s.page_zoom, s.page_plan, s.page_past, s.page_stage_timer, s.start_timer),
                         (130, "side", "collapse", False, True))
        cmd({"cmd": "prefs", "key": "page_zoom", "value": 900})          # вне 80…200 — к краю
        self.assertEqual(s.page_zoom, 200)
        cmd({"cmd": "prefs", "key": "page_plan", "value": "zzz"})        # неизвестное — не меняется
        self.assertEqual(s.page_plan, "side")
        cmd({"cmd": "prefs", "key": "hotkey_toggle", "value": "x"})      # не настройка страницы
        self.assertEqual(s.hotkey_toggle, "Ctrl+F9")
        p = self.state()["prefs"]
        self.assertEqual(p["page_zoom"], 200)
        self.assertEqual(p["page_plan"], "side")
        self.assertEqual(p["start_timer"], True)


# ================================================================ Task 3: план строкой — сдвиг конца урока

class ShiftTest(Base):
    port = 18971

    def test_shift_after_restart_stage(self):
        from datetime import datetime, timedelta
        at = (datetime.now() - timedelta(minutes=15)).strftime("%H:%M")
        cmd = self.win.lesson.command
        cmd({"cmd": "start", "at": at})
        self.assertEqual(self.win.efir.live_lesson_id(), "L")
        self.assertEqual(self.state()["live"]["shift"], 0)
        cmd({"cmd": "shift_now"})                       # этап-перерыв (10–20 мин) начат заново сейчас
        shift = self.state()["live"]["shift"]
        self.assertTrue(5 <= shift <= 6, shift)
        cmd({"cmd": "set_start", "start": at})          # новое время начала — новый план, сдвига нет
        self.assertEqual(self.state()["live"]["shift"], 0)


# ================================================================ Task 4: экран учеников с экрана урока

class EfirPageTest(Base):
    port = 18972

    def test_start_no_timer(self):
        ef = self.win.efir
        opened = []
        ef.open_tab = lambda: opened.append(1)
        self.win.lesson.command({"cmd": "start"})
        self.assertEqual(ef.live_lesson_id(), "L")
        self.assertIsNone(ef.timer_window)                   # «Начать урок» не открывает окно таймера
        self.assertEqual(opened, [])
        ef.stop_live()
        self.win.settings.start_timer = self.win.settings.start_screen = True
        self.win.lesson.command({"cmd": "start"})
        self.assertIsNotNone(ef.timer_window)
        self.assertEqual(opened, [1])

    def test_start_at_no_timer(self):
        self.win.lesson.command({"cmd": "start_at", "index": 2})
        self.assertEqual(self.win.efir.live_lesson_id(), "L")
        self.assertIsNone(self.win.efir.timer_window)

    def test_break_default_and_minutes(self):
        ef = self.win.efir
        self.win.lesson.command({"cmd": "break"})           # без этапа — перерыв урока (этап «Перерыв» 10 мин)
        self.assertEqual(ef.mode, "break")
        self.assertAlmostEqual(ef.brk_total, 600, delta=1)
        st = self.state()["efir"]
        self.assertEqual(st["mode"], "break")
        self.assertGreater(st["break_ends"], time.time() * 1000)
        self.assertIn("tab_open", st)
        self.win.lesson.command({"cmd": "break", "minutes": 15})
        self.assertAlmostEqual(ef.brk_total, 900, delta=1)
        self.win.lesson.command({"cmd": "background"})
        self.assertEqual(ef.mode, "idle")

    def test_look_new_and_edit(self):
        ef = self.win.efir
        edited = []
        ef.edit_look = lambda lid=None: edited.append(lid)
        n0 = len(ef.store.looks)
        self.win.lesson.command({"cmd": "look_new"})
        self.assertEqual(len(ef.store.looks), n0 + 1)
        new = ef.store.looks[-1]
        self.assertEqual(self.L.look, new.id)                # урок сразу на новом оформлении
        self.assertEqual(edited, [new.id])
        self.win.lesson.command({"cmd": "look_edit"})
        self.assertEqual(edited, [new.id, new.id])


class TimerBreakTest(Base):
    port = 18973

    def test_popup_buttons(self):
        from PySide6.QtWidgets import QAbstractSpinBox, QPushButton
        ef = self.win.efir
        self.win.settings.start_timer = True
        self.win.lesson.command({"cmd": "start"})
        tw = ef.timer_window
        m = tw._break_menu()
        self.assertEqual(m.findChildren(QAbstractSpinBox), [])        # поле минут больше не забирает фокус
        texts = [b.text().strip() for b in m.findChildren(QPushButton)]
        self.assertEqual(texts[0], "10 мин")                            # по плану — первым
        self.assertIn("5 мин", texts)
        self.assertIn("20 мин", texts)
        started = []
        ef.start_break = lambda minutes, ends_at=None: started.append(minutes)
        [b for b in m.findChildren(QPushButton) if b.text().strip() == "15 мин"][0].click()
        self.assertEqual(started, [15])


# ================================================================ Task 7: роли и палитра

class RolesV11Test(unittest.TestCase):
    def test_roles(self):
        R = storage.ROLES
        self.assertEqual([R[k][1] for k in ("trap", "output", "hint", "homework", "goal")],
                         ["Типичные ошибки", "Результат кода", "Если застрял", "Домашнее задание", "Цель урока"])
        self.assertNotIn("hint", storage.ROLE_MORE)
        groups = dict(storage.ROLE_GROUPS)
        self.assertEqual(list(groups), ["Урок", "Речь", "Ученикам", "Действия", "Для себя", "Материалы"])
        self.assertEqual(groups["Речь"], ["say", "tell", "term", "ask"])
        self.assertEqual(groups["Ученикам"], ["task", "hint", "extra", "homework"])
        self.assertEqual(sorted(k for g in groups.values() for k in g), sorted(storage.ROLE_ORDER))

    def test_state_roles_how(self):
        from autoprint import scenario
        roles = {r["key"]: r for r in scenario.roles_state()}
        self.assertEqual(roles["say"]["how"], "дословно")
        self.assertEqual(roles["tell"]["how"], "своими словами")
        self.assertEqual(roles["ask"]["how"], "ответы учеников")
        self.assertEqual([g["title"] for g in scenario.role_groups_state()][0], "Урок")

    def test_md_names_old_and_new(self):
        from autoprint.lesson_md import _role
        for name, key in (("Ловушки", "trap"), ("Типичные ошибки", "trap"), ("Вывод", "output"),
                          ("Результат кода", "output"), ("Подсказка", "hint"), ("Если застрял", "hint"),
                          ("Домашнее задание", "homework"), ("Цель урока", "goal")):
            self.assertEqual(_role(name), key, name)

    def test_students_notebook_homework(self):
        import json
        from autoprint.importers import export_ipynb
        t = Template("У", [note("Скажи", id="a"), code("x = 1", id="b"),
                           note("Решить задачи 1–3", role="homework", id="c")])
        path = TMP / "students.ipynb"
        export_ipynb(t, str(path), students=True)
        cells = json.loads(path.read_text(encoding="utf-8"))["cells"]
        self.assertEqual([c["cell_type"] for c in cells], ["code", "markdown"])
        self.assertIn("Домашнее задание", "".join(cells[1]["source"]))
        self.assertIn("Решить задачи 1–3", "".join(cells[1]["source"]))

    def test_ai_knows_new_roles(self):
        from autoprint import lesson_ai as L
        prompt = L.build_prompt("материал", L.Options(style=L.STYLE_SCENARIO))
        for word in ("[!homework]", "Домашнее задание", "[!goal]", "Цель урока", "Если застрял", "Типичные ошибки"):
            self.assertIn(word, prompt, msg=word)      # 0.12: Markdown, как свой чат
        self.assertEqual(L._TYPE_ROLE.get("домашнее задание"), "homework")
        self.assertEqual(L._TYPE_ROLE.get("цель"), "goal")


# ================================================================ Task 8: слайды и экран учеников

def slide_png(n: int) -> str:
    """Картинка-слайд в data/media → ссылка блока."""
    from PySide6.QtGui import QColor, QImage
    folder = storage.DATA_DIR / storage.MEDIA_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"test-slide-{n}.png"
    im = QImage(32, 18, QImage.Format.Format_RGB32)
    im.fill(QColor(20 * n, 40, 80))
    im.save(str(p), "PNG")
    return storage.media_ref(p)


def slides_lesson(tid: str = "S") -> Template:
    return Template("Презентация", [stage("Презентация", 30, id="ps"),
                                     Block(BLOCK_IMAGE, slide_png(1), title="Титул", slide=1, id="sl1"),
                                     note("Скажи про тему", id="sn1"),
                                     Block(BLOCK_IMAGE, slide_png(2), title="План", slide=2, id="sl2"),
                                     Block(BLOCK_IMAGE, slide_png(3), title="Итоги", slide=3, id="sl3")], id=tid)


class SlideTest(Base):
    port = 18974

    def setUp(self):
        self.L = slides_lesson("L")
        self.win = make_window([self.L], port=self.port)
        self.win.lesson.open_page = lambda: None
        self.win.printer.set_focus("L")

    def test_show_slide_and_background(self):
        ef = self.win.efir
        self.win.lesson.command({"cmd": "slide", "block": "sl2"})
        self.assertEqual(ef.mode, "slide")
        st = ef.state()
        self.assertTrue(st["slide"]["src"].endswith("test-slide-2.png"), st["slide"])
        self.assertTrue(st["slide"]["next"].endswith("test-slide-3.png"), st["slide"])
        e = self.state()["efir"]
        self.assertEqual((e["mode"], e["slide_n"], e["slide_bid"]), ("slide", 2, "sl2"))
        self.win.lesson.command({"cmd": "background"})
        self.assertEqual(ef.mode, "idle")
        self.assertIsNone(ef.store.slide)

    def test_slide_step(self):
        ef = self.win.efir
        step = lambda d: self.win.lesson.command({"cmd": "slide_step", "d": d})
        step(1)
        self.assertEqual(ef.slide["bid"], "sl1")                       # ничего не показано — первый слайд
        step(1)
        step(1)
        self.assertEqual(ef.slide["bid"], "sl3")
        step(1)
        self.assertEqual(ef.slide["bid"], "sl3")                       # последний — остаётся
        step(-1)
        self.assertEqual(ef.slide["bid"], "sl2")
        self.win.lesson.command({"cmd": "slide", "block": "sn1"})      # заметку на экран не выводят
        self.assertEqual(ef.slide["bid"], "sl2")

    def test_slide_survives_restart(self):
        from autoprint.efir import store as store_mod
        from autoprint.ui.efir_control import EfirController
        ef = self.win.efir
        self.win.lesson.command({"cmd": "start"})
        self.win.lesson.command({"cmd": "slide", "block": "sl3"})
        folder = ef.store.path.parent
        old = store_mod.efir_dir
        store_mod.efir_dir = lambda: folder
        try:
            ctl2 = EfirController(None)
        finally:
            store_mod.efir_dir = old
        ctl2.settings = ef.settings
        ctl2.show_timer = lambda: None
        ctl2.server.want_port = 18975
        ctl2.ensure_server()
        try:
            ctl2.restore()
            self.assertEqual(ctl2.mode, "slide")
            self.assertTrue(ctl2.state()["slide"]["src"].endswith("test-slide-3.png"))
        finally:
            ctl2.server.stop()

    def test_md_slide_roundtrip(self):
        from autoprint import lesson_md
        text = lesson_md.to_md(self.L, "")
        self.assertIn("![Слайд 2 · План]", text)
        back = lesson_md.parse(text, storage.DATA_DIR, "П")
        self.assertEqual([(b.slide, b.title) for b in back.blocks if b.type == BLOCK_IMAGE],
                         [(1, "Титул"), (2, "План"), (3, "Итоги")])

    def test_item_state_slide(self):
        from autoprint import scenario
        it = scenario.item_state(self.L.find_block("sl2"), lambda p: "/m/" + Path(p).name)
        self.assertEqual(it["slide"], 2)


# ================================================================ Task 9: импорт презентаций

def make_pdf(path: Path, pages: list[str]) -> str:
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QFont, QPageSize, QPainter, QPdfWriter
    w = QPdfWriter(str(path))
    w.setPageSize(QPageSize(QPageSize.PageSizeId.A5))
    p = QPainter(w)
    p.setFont(QFont("Segoe UI", 28))
    for i, text in enumerate(pages):
        if i:
            w.newPage()
        p.drawText(QRect(200, 200, 4000, 3000), 0, text)
    p.end()
    return str(path)


P_NS = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" ' \
       'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" ' \
       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def _sp(text: str, ph: str = "") -> str:
    paras = "".join(f"<a:p><a:r><a:t>{t}</a:t></a:r></a:p>" for t in text.split("\n"))
    nv = f'<p:nvSpPr><p:cNvPr id="1" name="x"/><p:cNvSpPr/><p:nvPr>{f"<p:ph type={chr(34)}{ph}{chr(34)}/>" if ph else ""}</p:nvPr></p:nvSpPr>'
    return f"<p:sp>{nv}<p:txBody>{paras}</p:txBody></p:sp>"


def make_pptx(path: Path, slides: list[dict], sections: list[tuple[str, list[int]]] | None = None) -> str:
    """slides: [{"file": 3, "title": …, "body": …, "notes": …, "hidden": bool}] в порядке показа."""
    import zipfile
    ids = [256 + i for i in range(len(slides))]
    rels = "".join(f'<Relationship Id="rId{i + 10}" Target="slides/slide{s["file"]}.xml" '
                   f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"/>'
                   for i, s in enumerate(slides))
    sld = "".join(f'<p:sldId id="{ids[i]}" r:id="rId{i + 10}"/>' for i in range(len(slides)))
    sect = ""
    if sections:
        sect = ('<p:extLst><p:ext uri="{521415D9-36F7-43E2-AB2F-B90AF26B5E84}">'
                '<p14:sectionLst xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main">'
                + "".join(f'<p14:section name="{name}" id="{{S{k}}}"><p14:sldIdLst>'
                          + "".join(f'<p14:sldId id="{ids[i]}"/>' for i in idx) + "</p14:sldIdLst></p14:section>"
                          for k, (name, idx) in enumerate(sections))
                + "</p14:sectionLst></p:ext></p:extLst>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("ppt/presentation.xml", f"<p:presentation {P_NS}><p:sldIdLst>{sld}</p:sldIdLst>{sect}</p:presentation>")
        z.writestr("ppt/_rels/presentation.xml.rels",
                   f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>')
        for s in slides:
            f = s["file"]
            show = ' show="0"' if s.get("hidden") else ""
            z.writestr(f"ppt/slides/slide{f}.xml", f"<p:sld {P_NS}{show}><p:cSld><p:spTree>"
                       + _sp(s["title"], "title") + _sp(s.get("body", "")) + "</p:spTree></p:cSld></p:sld>")
            if s.get("notes"):
                z.writestr(f"ppt/slides/_rels/slide{f}.xml.rels",
                           '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                           f'<Relationship Id="rId2" Target="../notesSlides/notesSlide{f}.xml" Type="x"/></Relationships>')
                z.writestr(f"ppt/notesSlides/notesSlide{f}.xml", f"<p:notes {P_NS}><p:cSld><p:spTree>"
                           + _sp("", "sldImg") + _sp(s["notes"], "body") + _sp(str(f), "sldNum")
                           + "</p:spTree></p:cSld></p:notes>")
    return str(path)


class PresentationTest(unittest.TestCase):
    def test_pdf(self):
        from autoprint import slides
        pdf = make_pdf(TMP / "deck.pdf", ["Функции в Python", "Что такое аргумент", "Итоги урока"])
        t = slides.from_pdf(pdf)
        self.assertEqual(t.title, "deck")
        st = [b for b in t.blocks if b.type == BLOCK_STAGE]
        self.assertEqual([(b.title, b.minutes) for b in st], [("Презентация", 45)])
        imgs = [b for b in t.blocks if b.type == BLOCK_IMAGE]
        self.assertEqual([b.slide for b in imgs], [1, 2, 3])
        self.assertTrue(all(storage.media_path(b.text) is not None for b in imgs))
        self.assertIn("Функции", imgs[0].title)

    def test_pptx_order_sections_notes(self):
        from autoprint import slides
        deck = make_pptx(TMP / "deck.pptx", [
            {"file": 3, "title": "Титул", "notes": "Скажи: Добрый день, сегодня функции.\nЭто тема всего урока."},
            {"file": 1, "title": "Вопрос", "notes": "Спроси: Что такое функция?\n→ блок кода с именем\n→ команда"},
            {"file": 2, "title": "Практика", "notes": "Сделай: открой редактор.\n\nТермин: Аргумент — значение в скобках\n"
                                                         "Важно: отступ 4 пробела.\nЗадание: напишите функцию."},
        ], sections=[("Введение", [0]), ("Работа", [1, 2])])
        pdf = make_pdf(TMP / "deck-pages.pdf", ["Титул", "Вопрос", "Практика"])
        t, warns, need = slides.from_pptx(deck, pdf=pdf)
        self.assertFalse(need)
        self.assertEqual(warns, [])
        st = [(b.title, b.minutes) for b in t.blocks if b.type == BLOCK_STAGE]
        self.assertEqual(st, [("Введение", 15), ("Работа", 30)])
        imgs = [(b.slide, b.title) for b in t.blocks if b.type == BLOCK_IMAGE]
        self.assertEqual(imgs, [(1, "Титул"), (2, "Вопрос"), (3, "Практика")])
        notes = [(b.role, b.text) for b in t.blocks if b.type == BLOCK_MARKDOWN]
        self.assertEqual(notes, [("say", "Добрый день, сегодня функции.\nЭто тема всего урока."),
                                 ("ask", "Что такое функция?\n→ блок кода с именем\n→ команда"),
                                 ("do", "открой редактор."), ("term", "Аргумент\nзначение в скобках"),
                                 ("important", "отступ 4 пробела."), ("task", "напишите функцию.")])
        kinds = [b.type for b in t.blocks]
        self.assertEqual(kinds.index(BLOCK_IMAGE), 1)                  # слайд — сразу после этапа, заметки — под ним

    def test_hidden_slide(self):
        from autoprint import slides
        deck = make_pptx(TMP / "hidden.pptx", [{"file": 1, "title": "Один", "notes": "раз"},
                                               {"file": 2, "title": "Скрытый", "notes": "два", "hidden": True},
                                               {"file": 3, "title": "Три", "notes": "три"}])
        pdf = make_pdf(TMP / "hidden.pdf", ["Один", "Три"])
        t, warns, _ = slides.from_pptx(deck, pdf=pdf)
        imgs = [(b.slide, b.title, bool(b.text)) for b in t.blocks if b.type == BLOCK_IMAGE]
        self.assertEqual(imgs, [(1, "Один", True), (3, "Три", True)])
        self.assertTrue(any("2" in w and "скрыт" in w.lower() for w in warns), warns)

    def test_page_count_mismatch(self):
        from autoprint import slides
        deck = make_pptx(TMP / "mism.pptx", [{"file": i, "title": f"С{i}", "notes": ""} for i in (1, 2, 3)])
        pdf = make_pdf(TMP / "mism.pdf", ["С1", "С2"])
        t, warns, _ = slides.from_pptx(deck, pdf=pdf)
        imgs = [(b.slide, bool(b.text)) for b in t.blocks if b.type == BLOCK_IMAGE]
        self.assertEqual(imgs, [(1, True), (2, True), (3, False)])
        self.assertTrue(any("2" in w and "3" in w for w in warns), warns)

    def test_no_pdf_needs_pdf(self):
        from autoprint import slides
        deck = make_pptx(TMP / "nopdf.pptx", [{"file": 1, "title": "Один", "notes": "Скажи: привет"}])
        old = slides.export_pdf
        slides.export_pdf = lambda p: None
        try:
            t, warns, need = slides.from_pptx(deck)
        finally:
            slides.export_pdf = old
        self.assertTrue(need)
        self.assertEqual([(b.role, b.text) for b in t.blocks if b.type == BLOCK_MARKDOWN], [("say", "привет")])

    def test_export_pdf_mocked(self):
        import subprocess
        from autoprint import slides
        deck = make_pptx(TMP / "com.pptx", [{"file": 1, "title": "Один"}])
        calls = []

        def fake_run(args, **kw):
            calls.append((args, kw))
            Path(kw["env"]["AP_OUT"]).write_bytes(b"%PDF-1.4 fake")
            return subprocess.CompletedProcess(args, 0, "", "")

        old_run, old_pp = slides.subprocess.run, slides.powerpoint_installed
        slides.subprocess.run, slides.powerpoint_installed = fake_run, lambda: True
        try:
            out = slides.export_pdf(deck)
        finally:
            slides.subprocess.run, slides.powerpoint_installed = old_run, old_pp
        self.assertTrue(out and out.endswith(".pdf"))
        args, kw = calls[0]
        self.assertIn("-NonInteractive", args)
        self.assertTrue(kw["creationflags"] & 0x08000000)              # CREATE_NO_WINDOW — без окна
        script = args[-1]
        self.assertIn("SaveAs", script)
        self.assertIn("32", script)                                     # ppSaveAsPDF
        self.assertIn("Quit", script)
        self.assertIn("POWERPNT", script)                               # был открыт у учителя — не закрывать
        self.assertEqual(kw["env"]["AP_SRC"], str(Path(deck).resolve()))

    def test_load_file_pdf(self):
        from autoprint.importers import FILE_EXTS, load_file
        self.assertIn(".pdf", FILE_EXTS)
        self.assertIn(".pptx", FILE_EXTS)
        pdf = make_pdf(TMP / "lf.pdf", ["Один", "Два"])
        t = load_file(pdf)
        self.assertEqual(sum(b.type == BLOCK_IMAGE for b in t.blocks), 2)

    def test_import_dialog_pptx_with_pdf(self):
        from autoprint.ui.import_dialog import ImportDialog
        deck = make_pptx(TMP / "pair.pptx", [{"file": 1, "title": "Раз", "notes": "Скажи: привет"},
                                             {"file": 2, "title": "Два", "notes": "", "hidden": True},
                                             {"file": 3, "title": "Три", "notes": ""}])
        pdf = make_pdf(TMP / "pair.pdf", ["Раз", "Три"])
        d = ImportDialog(None, storage.Settings())
        try:
            d._take_files([deck, pdf])                              # PDF той же презентации — картинки, не урок
            self.assertEqual(len(d.result), 1)
            imgs = [(b.slide, bool(b.text)) for b in d.result[0].blocks if b.type == BLOCK_IMAGE]
            self.assertEqual(imgs, [(1, True), (3, True)])
            self.assertTrue(any("скрыт" in n.lower() for n in d.result_notes), d.result_notes)
        finally:
            d.close()
            d.deleteLater()

    def test_new_lesson_from_presentation(self):
        win = make_window([lesson_with_stages()], port=18976)
        win.lesson.open_page = lambda: None
        try:
            t = win.new_from_presentation(make_pdf(TMP / "newdeck.pdf", ["Один", "Два", "Три"]))
            self.assertIsNotNone(t)
            self.assertIn(t, win.store.templates)
            self.assertEqual(win.printer.focus_id, t.id)
            self.assertEqual(sum(b.type == BLOCK_IMAGE and b.slide > 0 for b in t.blocks), 3)
        finally:
            win._quitting = True
            win.close()
            pump()

    def test_materials_pptx_order(self):
        from autoprint import materials
        deck = make_pptx(TMP / "mat.pptx", [{"file": 2, "title": "Первый"}, {"file": 1, "title": "Второй"}])
        text = materials.extract(deck).text
        self.assertLess(text.index("Первый"), text.index("Второй"))
        self.assertIn("=== Слайд 1 ===\nПервый", text)


# ================================================================ Task 10: нейросеть в своём чате

CHAT_ANSWER = """Вот урок:

~~~markdown
---
title: Функции по слайдам
---

> [!goal]
> Ученики пишут функцию.

## Вступление · 10 мин

![Слайд 1](slide:1)

> [!say]
> Добрый день!

## Разбор · 15 мин

![Слайд 2](slide:2)

![Слайд 5](slide:5)

> [!ask]
> Что такое функция?
> → блок кода с именем

```python
print(1)
```
~~~
Если нужно — поправлю."""


class ChatPromptTest(unittest.TestCase):
    def test_copy_without_material(self):
        from autoprint import lesson_ai as L
        p = L.chat_prompt("", L.Options(style=L.STYLE_SCENARIO, minutes=45, break_min=0))
        self.assertIn("приложен к сообщению", p)
        self.assertIn("~~~markdown", p)
        self.assertIn("![Слайд 1](slide:1)", p)
        self.assertIn("ровно 45", p)
        self.assertIn("> [!homework]", p)
        p2 = L.chat_prompt("Тема: циклы", L.Options(style=L.STYLE_SCENARIO, minutes=90))
        self.assertIn("Тема: циклы", p2)
        self.assertNotIn("приложен к сообщению", p2)

    def test_slides_prompt(self):
        from autoprint import lesson_ai as L
        p = L.slides_prompt(slides_lesson())
        self.assertIn("с 1 по 3", p)
        self.assertIn("1. Титул", p)
        self.assertIn("3. Итоги", p)
        self.assertIn("ровно 30", p)

    def test_md_answer_in_dialog_parser(self):
        from autoprint import lesson_ai as L
        parsed = L.parse_lesson(CHAT_ANSWER, slide=lambda n: None)
        t = parsed.template
        self.assertEqual(t.title, "Функции по слайдам")
        self.assertEqual([b.title for b in t.blocks if b.type == BLOCK_STAGE], ["Вступление", "Разбор"])
        self.assertTrue(any(b.type == BLOCK_CODE and b.text == "print(1)" for b in t.blocks))

    def test_apply_answer_to_slides(self):
        from autoprint import slides
        base = slides_lesson()
        new, notes = slides.apply_chat_answer(base, CHAT_ANSWER)
        imgs = [(b.slide, b.text) for b in new.blocks if b.type == BLOCK_IMAGE and b.text]   # 0.12: слайд 5 — место
        self.assertEqual(imgs, [(1, base.find_block("sl1").text), (2, base.find_block("sl2").text)])
        self.assertEqual(new.title, "Функции по слайдам")
        self.assertEqual({b.id for b in new.blocks} & {b.id for b in base.blocks}, set())     # копия, свои id
        joined = " ".join(notes)
        self.assertIn("Слайда 5 нет в презентации", joined)
        self.assertIn("25 из 30", joined)
        self.assertIn("пропустила: 3", joined)                                     # слайд 3 нейросеть пропустила
        _new, notes2 = slides.apply_chat_answer(base, "~~~markdown\n## Э · 30 мин\n\n![Слайд 1](slide:1)\n\n"
                                                      "![Слайд 2](slide:2)\n\n> [!say]\n> Текст\n\n![Слайд 3](slide:3)\n~~~")
        self.assertIn("без заметок: 1, 3", " ".join(notes2))

    def test_page_commands(self):
        from PySide6.QtGui import QGuiApplication
        base = slides_lesson("L")
        win = make_window([base], port=18977)
        win.lesson.open_page = lambda: None
        win.printer.set_focus("L")
        try:
            win.lesson.command({"cmd": "chat_prompt"})
            self.assertIn("с 1 по 3", QGuiApplication.clipboard().text())
            win.lesson.command({"cmd": "apply_answer", "text": CHAT_ANSWER})
            self.assertEqual(len(win.store.templates), 2)
            new = win.store.templates[1]
            self.assertEqual(new.title, "Функции по слайдам")
            self.assertEqual(win.printer.focus_id, new.id)                     # урок не идёт — копия открыта
            win.lesson.command({"cmd": "apply_answer", "text": "просто текст"})   # не урок — ничего не добавлено
            self.assertEqual(len(win.store.templates), 2)
        finally:
            win._quitting = True
            win.close()
            pump()

    def test_chat_answer_saved_as_md_file(self):
        """ChatGPT прислал урок файлом .md — внутри строки ~~~markdown, их просит промпт."""
        import tempfile
        from autoprint.importers import load_file
        for text in (CHAT_ANSWER, CHAT_ANSWER.split("\n", 2)[2]):        # с фразой до блока и без неё
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "урок.md"
                p.write_text(text, encoding="utf-8")
                t = load_file(str(p))
            self.assertEqual(t.title, "Функции по слайдам")
            self.assertEqual([b.title for b in t.blocks if b.type == BLOCK_STAGE], ["Вступление", "Разбор"])
            self.assertTrue(any(b.type == BLOCK_CODE and b.text == "print(1)" for b in t.blocks))
            # слайды без PDF — места (пустой text), а не битые картинки
            self.assertTrue(all(not b.text and b.slide for b in t.blocks if b.type == BLOCK_IMAGE))

    def test_chat_answer_pasted_whole(self):
        """Скопирован весь ответ чата — с фразой и строками ~~~markdown — во вкладку «Вставить»."""
        from autoprint.importers import parse_pasted
        t, kind = parse_pasted(CHAT_ANSWER)
        self.assertEqual(kind, "урок в Markdown")
        self.assertEqual(t.title, "Функции по слайдам")
        self.assertEqual([b.title for b in t.blocks if b.type == BLOCK_STAGE], ["Вступление", "Разбор"])

    def test_markdown_example_inside_lesson_stays(self):
        """Урок про Markdown: пример ~~~markdown внутри этапа — пример кода, а не обёртка ответа."""
        import tempfile
        from autoprint.importers import load_file, parse_pasted
        text = ("## Разметка · 10 мин\n\n> [!say]\n> Заголовок — решётка.\n\n~~~markdown\n# Заголовок\n~~~\n\n"
                "## Практика · 5 мин\n\n> [!task]\n> Сделайте заголовок.\n")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "разметка.md"
            p.write_text(text, encoding="utf-8")
            t = load_file(str(p))
        t2, _kind = parse_pasted(text)
        for les in (t, t2):
            self.assertEqual([b.title for b in les.blocks if b.type == BLOCK_STAGE], ["Разметка", "Практика"])
            self.assertTrue(any(b.type == BLOCK_CODE and "# Заголовок" in b.text for b in les.blocks))

    def test_dialog_copy_enabled_without_material(self):
        from PySide6.QtGui import QGuiApplication
        from autoprint import lesson_ai as L
        from autoprint.ui.import_dialog import TAB_AI, ImportDialog
        s = storage.Settings()
        s.lesson_style = L.STYLE_SCENARIO
        d = ImportDialog(None, s, tab=TAB_AI)
        try:
            d._update_ai_buttons()
            self.assertTrue(d.copy_btn.isEnabled())
            d._copy_prompt()
            self.assertIn("приложен к сообщению", QGuiApplication.clipboard().text())
        finally:
            d.close()
            d.deleteLater()


# ================================================================ Task 12: новый урок по шаблону структуры

class StructureTest(Base):
    port = 18978

    def test_structures(self):
        st = storage.STRUCTURES
        self.assertEqual(list(st), ["empty", "school45", "online90", "pair90"])
        t = self.win.store.add_from_structure("school45")
        stages = [(b.title, b.minutes) for b in t.blocks if b.type == BLOCK_STAGE]
        self.assertEqual(stages, [("Оргмомент", 2), ("Цель и мотивация", 3), ("Актуализация знаний", 5),
                                  ("Новый материал", 15), ("Закрепление", 12), ("Домашнее задание", 3), ("Рефлексия", 5)])
        self.assertEqual(t.blocks[0].role, "goal")
        self.assertTrue(any(b.role == "homework" for b in t.blocks if b.type == BLOCK_MARKDOWN))
        t2 = self.win.store.add_from_structure("online90")
        self.assertEqual(sum(b.minutes for b in t2.blocks if b.type == BLOCK_STAGE), 90)
        self.assertIn("break", [b.stage_kind for b in t2.blocks if b.type == BLOCK_STAGE])
        t3 = self.win.store.add_from_structure("pair90")
        self.assertEqual([b.minutes for b in t3.blocks if b.type == BLOCK_STAGE], [45, 10, 45])

    def test_page_command_and_menu(self):
        n0 = len(self.win.store.templates)
        self.win.lesson.command({"cmd": "new_lesson", "structure": "pair90"})
        self.assertEqual(len(self.win.store.templates), n0 + 1)
        t = self.win.printer.focus()
        self.assertEqual([b.minutes for b in t.blocks if b.type == BLOCK_STAGE], [45, 10, 45])
        self.assertIn("structures", self.state())
        menu = self.win.library.new_menu()
        texts = [a.text() for a in menu.actions() if a.text()]
        for x in ("Пустой урок", "Школа, 45 мин", "Онлайн-занятие, 90 мин", "Пара, 2×45", "Из презентации…"):
            self.assertIn(x, texts)


# ================================================================ Task 13: образцовый урок v3

class SampleV3Test(unittest.TestCase):
    def test_sample_v3(self):
        from autoprint.samples_lesson import LESSON_SAMPLE_ID, lesson_sample
        self.assertEqual(LESSON_SAMPLE_ID, "lesson_v3")
        t = lesson_sample()
        notes = [b for b in t.blocks if b.type == BLOCK_MARKDOWN]
        self.assertEqual(t.blocks[0].role, "goal")
        roles = {b.role for b in notes}
        self.assertTrue(set(storage.ROLE_ORDER) <= roles, set(storage.ROLE_ORDER) - roles)
        self.assertFalse(any("Как читать" in (b.title + b.text) for b in notes))
        self.assertTrue(any(b.role == "ask" and b.title == "Рефлексия" for b in notes))
        stages = [b for b in t.blocks if b.type == BLOCK_STAGE]
        self.assertEqual((len(stages), sum(b.minutes for b in stages)), (12, 90))
        # «Спроси» после теории: в этапах «Что такое функция» и «Разбор 3» есть вопрос на понимание
        for name in ("Что такое функция", "Разбор 3"):
            i = next(k for k, b in enumerate(t.blocks) if b.type == BLOCK_STAGE and b.title.startswith(name))
            j = next((k for k in range(i + 1, len(t.blocks)) if t.blocks[k].type == BLOCK_STAGE), len(t.blocks))
            self.assertTrue(any(b.role == "ask" for b in t.blocks[i + 1:j] if b.type == BLOCK_MARKDOWN), name)

    def test_samples_v11_migration(self):
        from autoprint import migrations
        self.assertIn("f7db1365fceef3c9d1c6497df2017ed05c2a8b96", migrations.SAMPLE_V2_FINGERPRINTS)
        store = storage.TemplateStore.__new__(storage.TemplateStore)
        old = Template("Пример урока: функции и надёжный пароль", [stage("A", 5), note("x")])
        mine = Template("Мой урок", [stage("B", 5), note("y")])
        store.templates = [old, mine]
        store.save = lambda: None
        s = storage.Settings()
        s.migrations = ["tray_v1", "window_v10", "roles_v10", "samples_v10"]
        keep = migrations.SAMPLE_V2_FINGERPRINTS
        migrations.SAMPLE_V2_FINGERPRINTS = keep | {migrations.fingerprint(old)}
        try:
            migrations.apply(s, store)
        finally:
            migrations.SAMPLE_V2_FINGERPRINTS = keep
        self.assertEqual(store.templates, [mine])
        self.assertIn("samples_v11", s.migrations)


# ================================================================ Task 15: замечания методиста

class MethodologyFixTest(unittest.TestCase):
    def test_stage_line_tolerant(self):
        from autoprint import lesson_md
        md = ("---\ntitle: Т\n---\n\n## Разминка — 10 мин\n\nтекст\n\n## Теория (15 мин)\n\nтекст\n\n"
              "## Практика · 20 минут\n\nтекст\n\n## Перерыв · 10 мин · перерыв\n")
        t = lesson_md.parse(md, None, "Т")
        st = [(b.title, b.minutes, b.stage_kind) for b in t.blocks if b.type == BLOCK_STAGE]
        self.assertEqual(st, [("Разминка", 10, ""), ("Теория", 15, ""), ("Практика", 20, ""), ("Перерыв", 10, "break")])

    def test_notes_markers_extended(self):
        from autoprint.slides import notes_blocks
        text = ("Сказать: Добрый день.\nСегодня клетка.\n\nВопрос классу: Из чего состоит клетка?\nОтвет: из ядра и цитоплазмы\n"
                "Ответы:\n- ядро\n- мембрана\n\nДЗ: параграф 5\nЦель — узнать строение клетки\nПодсказка: вспомните микроскоп\n"
                "Для быстрых: нарисуйте клетку\nОшибки: путают ядро и ядрышко\nДля себя: проверить проектор\n"
                "Учитель: Откройте тетради.\nУченики: Открыли.\nОпределение: Клетка — единица живого\n[Покажи] слайд с ядром")
        got = [(b.role, b.text) for b in notes_blocks(text)]
        self.assertEqual(got, [
            ("say", "Добрый день.\nСегодня клетка."),
            ("ask", "Из чего состоит клетка?\n→ из ядра и цитоплазмы\n→ ядро\n→ мембрана"),
            ("homework", "параграф 5"), ("goal", "узнать строение клетки"), ("hint", "вспомните микроскоп"),
            ("extra", "нарисуйте клетку"), ("trap", "путают ядро и ядрышко"), ("text", "проверить проектор"),
            ("ask", "Откройте тетради.\n→ Открыли."), ("term", "Клетка\nединица живого"), ("show", "слайд с ядром")])

    def test_stage_marker_in_notes(self):
        from autoprint import slides
        deck = make_pptx(TMP / "stagenotes.pptx", [
            {"file": 1, "title": "Титул", "notes": "Сказать: привет"},
            {"file": 2, "title": "Клетка", "notes": "Этап: Новый материал · 15 мин\nСказать: клетка — основа"},
            {"file": 3, "title": "Тест", "notes": "Этап: Закрепление — 10 мин\nЗадание: тест"}])
        pdf = make_pdf(TMP / "stagenotes.pdf", ["Титул", "Клетка", "Тест"])
        t, _w, _n = slides.from_pptx(deck, pdf=pdf, minutes=45)
        order = [(b.type, b.title if b.type != BLOCK_MARKDOWN else b.role) for b in t.blocks]
        self.assertEqual(order, [(BLOCK_STAGE, "Презентация"), (BLOCK_IMAGE, "Титул"), (BLOCK_MARKDOWN, "say"),
                                 (BLOCK_STAGE, "Новый материал"), (BLOCK_IMAGE, "Клетка"), (BLOCK_MARKDOWN, "say"),
                                 (BLOCK_STAGE, "Закрепление"), (BLOCK_IMAGE, "Тест"), (BLOCK_MARKDOWN, "task")])
        self.assertEqual([b.minutes for b in t.blocks if b.type == BLOCK_STAGE], [20, 15, 10])

    def test_slides_prompt_keeps_notes(self):
        from autoprint import lesson_ai as L
        p = L.slides_prompt(slides_lesson())
        self.assertIn("Скажи про тему", p)                     # заметки учителя под слайдом 1 — в промпте
        self.assertIn("почти дословно", p)
        self.assertIn("Класс / возраст", p)
        self.assertIn("ОБЯЗАТЕЛЬНО", p)
        self.assertIn("→ частая ошибка", p)
        self.assertIn("Строка этапа строго", p)
        self.assertIn("Начни ответ строкой ~~~markdown", p)

    def test_school45_structure(self):
        st = storage.STRUCTURES["school45"][1]
        self.assertEqual([s[0] for s in st], ["Оргмомент", "Цель и мотивация", "Актуализация знаний", "Новый материал",
                                             "Закрепление", "Домашнее задание", "Рефлексия"])
        self.assertEqual(sum(s[1] for s in st), 45)


class ScreenKeysTest(Base):
    port = 18979

    def setUp(self):
        self.L = slides_lesson("L")
        self.win = make_window([self.L], port=self.port)
        self.win.lesson.open_page = lambda: None
        self.win.printer.set_focus("L")

    def test_keys_from_students_tab(self):
        ef = self.win.efir
        ef._on_report({"type": "key", "key": "PageDown"})       # щёлкнули по вкладке учеников — кликер листает и там
        pump(50)
        self.assertEqual((ef.slide or {}).get("bid"), "sl1")
        ef._on_report({"type": "key", "key": "ArrowRight"})
        pump(50)
        self.assertEqual(ef.slide["bid"], "sl2")
        ef._on_report({"type": "key", "key": "b"})
        pump(50)
        self.assertEqual(ef.mode, "idle")

    def test_screen_page_sends_keys(self):
        from autoprint.efir.server import PAGE_DIR
        html = (PAGE_DIR / "screen.html").read_text(encoding="utf-8")
        self.assertIn("report({ type: 'key'", html)


# ================================================================ Task 15: находки тестировщика

class QAFixTest(Base):
    port = 18980

    def setUp(self):
        self.L = slides_lesson("L")
        self.L.blocks.append(Block(BLOCK_IMAGE, slide_png(9), title="Схема", id="pic"))   # обычная картинка
        self.win = make_window([self.L], port=self.port)
        self.win.lesson.open_page = lambda: None
        self.win.printer.set_focus("L")

    def test_screen_key_ignored_during_webinar(self):
        from autoprint.efir.model import Activity, Webinar
        ef = self.win.efir
        w = ef.store.add([Webinar(title="Вебинар", schedule=[Activity("x", 30)])])[0]
        ef.launch(w.id, "")
        ef._on_report({"type": "key", "key": "PageDown"})
        pump(50)
        self.assertNotEqual(ef.mode, "slide")                      # слайды урока в чужой эфир не выводим

    def test_plain_image_to_screen(self):
        ef = self.win.efir
        self.win.lesson.command({"cmd": "slide", "block": "pic"})
        self.assertEqual((ef.slide or {}).get("bid"), "pic")

    def test_restore_respects_start_timer(self):
        from autoprint.efir import store as store_mod
        from autoprint.ui.efir_control import EfirController
        ef = self.win.efir
        self.win.lesson.command({"cmd": "start"})
        folder = ef.store.path.parent
        old = store_mod.efir_dir
        store_mod.efir_dir = lambda: folder
        try:
            ctl2 = EfirController(None)
        finally:
            store_mod.efir_dir = old
        ctl2.settings = ef.settings                     # start_timer = False (по умолчанию)
        shown = []
        ctl2.show_timer = lambda: shown.append(1)
        ctl2.server.want_port = 18981
        try:
            ctl2.restore()
            self.assertEqual(shown, [])
        finally:
            ctl2.server.stop()

    def test_break_zero_minutes_stage(self):
        self.L.blocks.insert(0, stage("Перерыв", 0, id="b0", stage_kind="break"))
        self.win.lesson.command({"cmd": "break", "stage": "b0"})
        self.assertEqual(self.win.efir.mode, "break")
        self.assertAlmostEqual(self.win.efir.brk_total, 600, delta=1)


class ParserFixTest(unittest.TestCase):
    def test_answer_parser_edges(self):
        from autoprint import lesson_ai as L
        from autoprint import slides
        base = slides_lesson()
        with self.assertRaises(ValueError):
            slides.apply_chat_answer(base, "~~~markdown\n~~~")
        text = ("```markdown\n## Э · 30 мин\n\n![Слайд 2](slide: 2)\n\n> [!say]\n> Текст\n\n```python\nprint(1)\n```\n```\n"
                "Пояснение:\n```\nНадеюсь, это поможет!\n```")
        md = L.md_answer(text)
        self.assertNotIn("Надеюсь", md)
        new, notes = slides.apply_chat_answer(base, text)
        self.assertEqual([b.slide for b in new.blocks if b.type == BLOCK_IMAGE], [2])
        self.assertEqual([b.text for b in new.blocks if b.type == BLOCK_CODE], ["print(1)"])
        _n, notes = slides.apply_chat_answer(base, "~~~markdown\n## Э · 30 мин\n\n![Слайд 9](slide:9)\n\n"
                                                  "![Слайд 9](slide:9)\n~~~")
        self.assertEqual(" ".join(notes).count("слайда 9") + " ".join(notes).count("Слайда 9"), 1)

    def test_important_bang_marker(self):
        from autoprint.slides import notes_blocks
        self.assertEqual([(b.role, b.text) for b in notes_blocks("Важно! не забыть отступы")],
                         [("important", "не забыть отступы")])

    def test_term_empty_head(self):
        from autoprint import scenario
        it = scenario.item_state(Block(BLOCK_MARKDOWN, "\nопределение без термина", role="term"), lambda p: "")
        self.assertEqual(it["term"], "")

    def test_md_escapes(self):
        from autoprint.scenario import md_html
        self.assertEqual(md_html("2024\\. Год"), "<p>2024. Год</p>")
        self.assertEqual(md_html("x\\*\\*2 + y\\*\\*2"), "<p>x**2 + y**2</p>")
        self.assertIn('href="https://ru.wikipedia.org/wiki/Python_(язык)"', md_html("[В](https://ru.wikipedia.org/wiki/Python_(язык))"))


# ================================================================ Task 16: итоговое ревью

class FinalReviewTest(unittest.TestCase):
    def test_code_spans_stay_literal(self):
        from autoprint.scenario import md_html
        self.assertEqual(md_html("`a\\.b`"), "<p><code>a\\.b</code></p>")
        self.assertEqual(md_html('`"C:\\\\Users"`'), "<p><code>&quot;C:\\\\Users&quot;</code></p>")
        self.assertEqual(md_html("x\\*\\*2 и `y**2`"), "<p>x**2 и <code>y**2</code></p>")
        self.assertEqual(md_html("\\• пункт"), "<p>• пункт</p>")
        md_html("\ue0009999999\ue001 текст")                     # подобранный текст не роняет публикацию

    def test_italic_unicode_words(self):
        from autoprint.scenario import md_html
        self.assertEqual(md_html("*при*вет"), "<p>*при*вет</p>")    # как и на странице (md.js)

    def test_block_slide_coerced(self):
        from autoprint import lesson_edit
        b = storage._block_from({"type": "image", "text": "x.png", "slide": "x"})
        self.assertEqual(b.slide, 0)
        t = Template("У", [stage("A", 5, id="s1")], id="T")
        with self.assertRaises(ValueError):
            lesson_edit.apply(t, [{"op": "insert", "after": "s1",
                                   "block": {"id": "img1", "type": "image", "text": "a.png", "slide": "x"}}])
        lesson_edit.apply(t, [{"op": "restore", "after": "s1",
                               "block": {"id": "img2", "type": "image", "text": "a.png", "slide": 4}}])
        self.assertEqual(t.find_block("img2").slide, 4)

    def test_chat_answer_no_local_files(self):
        from autoprint import lesson_ai as L
        from autoprint import slides
        secret = TMP / "secret.txt"
        secret.write_text("секрет", encoding="utf-8")
        text = (f"~~~markdown\n## Э · 30 мин\n\n![x]({secret.as_posix()})\n\n![y](//evil-host/share/p.png)\n\n"
                "![Слайд 1](slide:1)\n\n> [!say]\n> Текст\n~~~")
        new, notes = slides.apply_chat_answer(slides_lesson(), text)
        imgs = [b.text for b in new.blocks if b.type == BLOCK_IMAGE]
        self.assertEqual(len(imgs), 1)                                  # только слайд 1
        self.assertFalse(any("secret" in x or "evil" in x for x in imgs))
        self.assertTrue(any("картинк" in n.lower() for n in notes), notes)
        parsed = L.parse_lesson(text, slide=lambda n: None)
        # 0.12: слайд без PDF — место (пустой text), а не пропуск; файлов с компьютера по-прежнему нет
        self.assertEqual([(b.text, b.slide) for b in parsed.template.blocks if b.type == BLOCK_IMAGE], [("", 1)])
        self.assertIsNone(storage.media_path("//evil-host/share/p.png"))
        self.assertIsNone(storage.media_path("\\\\evil-host\\share\\p.png"))

    def test_hidden_slides_in_pdf_too(self):
        from autoprint import slides
        deck = make_pptx(TMP / "allpages.pptx", [{"file": 1, "title": "Один"}, {"file": 2, "title": "Два", "hidden": True},
                                                 {"file": 3, "title": "Три"}])
        pdf = make_pdf(TMP / "allpages.pdf", ["Один", "Два", "Три"])
        t, warns, _ = slides.from_pptx(deck, pdf=pdf)
        self.assertEqual([b.slide for b in t.blocks if b.type == BLOCK_IMAGE and b.text], [1, 2, 3])
        self.assertEqual(warns, [])


class FinalReviewWindowTest(Base):
    port = 18982

    def setUp(self):
        self.L = slides_lesson("L")
        self.win = make_window([self.L], port=self.port)
        self.win.lesson.open_page = lambda: None
        self.win.printer.set_focus("L")

    def test_import_refused_while_live(self):
        self.win.lesson.command({"cmd": "start"})
        self.assertIsNone(self.win.new_from_presentation(make_pdf(TMP / "live.pdf", ["Один"])))
        self.assertEqual(len(self.win.store.templates), 1)

    def test_break_clears_slide(self):
        ef = self.win.efir
        self.win.lesson.command({"cmd": "start"})
        self.win.lesson.command({"cmd": "slide", "block": "sl2"})
        self.assertIsNotNone(ef.store.slide)
        ef.start_break(5)
        self.assertIsNone(ef.store.slide)                               # после перезапуска не вернётся старый слайд

    def test_report_key_needs_own_origin(self):
        import urllib.request
        ef = self.win.efir
        ef.ensure_server()
        port = ef.server.port

        def post(origin):
            req = urllib.request.Request(f"http://127.0.0.1:{port}/report", data=b'{"type": "key", "key": "PageDown"}',
                                         headers={"Content-Type": "text/plain", "Origin": origin}, method="POST")
            try:
                urllib.request.urlopen(req, timeout=5).read()
            except Exception:  # noqa: BLE001 — отказ — тоже ответ
                pass
        from test_v10 import call_in_thread
        call_in_thread(lambda: post("https://evil.example"))
        pump(200)
        self.assertNotEqual(ef.mode, "slide")                           # чужой сайт слайды не листает
        call_in_thread(lambda: post(f"http://127.0.0.1:{port}"))
        pump(200)
        self.assertEqual(ef.mode, "slide")


if __name__ == "__main__":
    unittest.main(verbosity=2)
