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
        for word in ('"homework"', "Домашнее задание", '"goal"', "Цель урока", "Если застрял", "Типичные ошибки"):
            self.assertIn(word, prompt)
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
        self.assertEqual(notes, [("say", "Добрый день, сегодня функции."), ("tell", "Это тема всего урока."),
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
        imgs = [(b.slide, b.text) for b in new.blocks if b.type == BLOCK_IMAGE]
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
