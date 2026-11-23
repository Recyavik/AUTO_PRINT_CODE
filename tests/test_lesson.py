"""Суфлёр урока: формат (этапы, роли, картинки), HTML для страницы, материалы, нейросеть, сервер, «Эфир»
по этапам, контроллер страницы и редактор (без окон на экране).

    python tests/test_lesson.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import quiet  # noqa: E402,F401  — до PySide6: offscreen, своя папка данных

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
quiet.patch()
from autoprint.ui.theme import theme  # noqa: E402
theme.setup(app, "dark")

from autoprint import scenario  # noqa: E402
from autoprint.storage import (BLOCK_CODE, BLOCK_IMAGE, BLOCK_MARKDOWN, BLOCK_STAGE, ROLES, Block,  # noqa: E402
                               Template, _template_from)

TMP = Path(tempfile.mkdtemp(prefix="lesson-test-"))


def pump(ms: int = 50) -> None:
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def stage(title: str, minutes: int, kind: str = "", part: str = "", note: str = "") -> Block:
    return Block(BLOCK_STAGE, note, title=title, minutes=minutes, stage_kind=kind, part=part)


def md(role: str, text: str) -> Block:
    return Block(BLOCK_MARKDOWN, text, role=role)


def dark_theme_lesson() -> Template:
    """Кусок «М8.У3 Тёмная тема»: вступление, два этапа, перерыв."""
    return Template(title="Урок 3. Тёмная тема", blocks=[
        md("task", "## Тёмная тема\nЦель: переключение тем."),
        stage("Вступление", 2, part="Летучка"),
        md("say", "Очень рад видеть вас всех снова!"),
        stage("Зачем нужна тёмная тема", 8, part="Тёмная тема", note="теория"),
        md("ask", "Какие темы вы предпочитаете?\n→ пишут в чат"),
        md("important", "Чистого чёрного #000 на сайте нет."),
        Block(BLOCK_CODE, ".darkTheme {\n    color: #fff;\n}", lang="css"),
        stage("Перерыв", 10, kind="break"),
    ])


class ModelTest(unittest.TestCase):
    def test_old_json_loads(self):
        old = {"title": "Старое", "blocks": [{"type": "markdown", "text": "## Задача", "role": "task"},
                                             {"type": "code", "text": "print(1)", "lang": "python"}]}
        t = _template_from(old)
        self.assertEqual([b.minutes for b in t.blocks], [0, 0])
        self.assertEqual([b.stage_kind for b in t.blocks], ["", ""])
        self.assertEqual((t.start, t.preset), ("", ""))
        self.assertFalse(scenario.has_stages(t))

    def test_roundtrip_new_fields(self):
        t = dark_theme_lesson()
        t.start, t.preset = "16:00", "abc"
        t.blocks.append(Block(BLOCK_IMAGE, "C:/x/slide.png", title="Слайд 3"))
        back = _template_from(json.loads(json.dumps(asdict(t))))
        self.assertEqual((back.start, back.preset), ("16:00", "abc"))
        st = back.blocks[3]
        self.assertEqual((st.type, st.title, st.minutes, st.part, st.text), (BLOCK_STAGE, "Зачем нужна тёмная тема",
                                                                             8, "Тёмная тема", "теория"))
        self.assertEqual(back.blocks[-2].stage_kind, "break")
        self.assertEqual((back.blocks[-1].type, back.blocks[-1].title), (BLOCK_IMAGE, "Слайд 3"))
        self.assertEqual(back.blocks[2].role, "say")

    def test_new_roles_known(self):
        for key in ("say", "tell", "ask", "do", "important", "show", "trap", "extra"):
            self.assertIn(key, ROLES)

    def test_stages_split(self):
        t = dark_theme_lesson()
        intro, stages = scenario.stages(t)
        self.assertEqual([b.role for b in intro], ["task"])
        self.assertEqual([(s.start_min, s.end_min) for s in stages], [(0, 2), (2, 10), (10, 20)])
        self.assertEqual([s.index for s in stages], [0, 1, 2])
        self.assertEqual([len(s.blocks) for s in stages], [1, 3, 0])
        self.assertEqual(stages[1].block.title, "Зачем нужна тёмная тема")
        self.assertEqual(scenario.total_minutes(t), 20)
        self.assertTrue(scenario.has_stages(t))

    def test_zero_minutes(self):
        t = Template(title="Ноль", blocks=[stage("Мгновенный", 0), stage("Пять", 5)])
        _intro, stages = scenario.stages(t)
        self.assertEqual([(s.start_min, s.end_min) for s in stages], [(0, 0), (0, 5)])
        self.assertEqual(scenario.total_minutes(t), 5)

    def test_display_title(self):
        self.assertEqual(stage("Перерыв", 10).display_title(), "Перерыв")
        self.assertEqual(Block(BLOCK_STAGE).display_title(), "Этап")
        self.assertEqual(Block(BLOCK_IMAGE).display_title(), "Картинка")
        self.assertEqual(md("say", "x").display_title(), "Говоришь")


class HtmlTest(unittest.TestCase):
    def test_escape(self):
        h = scenario.md_html('<script>alert("x")</script> & \'кавычки\'')
        self.assertNotIn("<script>", h)
        self.assertIn("&lt;script&gt;", h)
        self.assertIn("&amp;", h)

    def test_js_link_not_link(self):
        h = scenario.md_html("[жми](javascript:alert(1)) и [x](data:text/html,1)")
        self.assertNotIn('href="javascript', h)
        self.assertNotIn('href="data', h)
        self.assertIn("жми", h)

    def test_links(self):
        h = scenario.md_html("Сайт https://www.youtube.com/watch?v=1&t=2 и [Kahoot](https://kahoot.it).")
        self.assertIn('<a href="https://www.youtube.com/watch?v=1&amp;t=2" target="_blank" rel="noopener">', h)
        self.assertIn('<a href="https://kahoot.it" target="_blank" rel="noopener">Kahoot</a>', h)
        self.assertNotIn('kahoot.it).', h.replace('kahoot.it">', ''))   # точка после ссылки — не часть адреса

    def test_lists_bold_code(self):
        h = scenario.md_html("## Правила\n- **не** чёрный\n- `#121212`\n\n1. первое\n2. второе\n\nАбзац *курсив*")
        self.assertIn("<h3>Правила</h3>", h)
        self.assertIn("<ul><li><b>не</b> чёрный</li><li><code>#121212</code></li></ul>", h)
        self.assertIn("<ol><li>первое</li><li>второе</li></ol>", h)
        self.assertIn("<p>Абзац <i>курсив</i></p>", h)

    def test_fenced_code_in_markdown(self):
        h = scenario.md_html("Пример:\n```\na < b\n```")
        self.assertIn("<pre>a &lt; b</pre>", h)

    def test_ask_parts(self):
        self.assertEqual(scenario.ask_parts("Какие темы?\nЗачем?\n→ пишут в чат\n-> ждём: глаза"),
                         ("Какие темы?\nЗачем?", ["пишут в чат", "ждём: глаза"]))
        self.assertEqual(scenario.ask_parts("Вопрос без ответа"), ("Вопрос без ответа", []))

    def test_code_html_classes(self):
        h = scenario.code_html("def f():\n    return '<b>'", "python")
        self.assertIn('class="t-k"', h)
        self.assertIn("&lt;b&gt;", h)
        self.assertNotIn("<b>", h)
        self.assertEqual(scenario.code_html("x", "no-such-lang"), "x")

    def test_lang_info(self):
        self.assertEqual(scenario.lang_info("python"), ("Python", "python.svg"))
        self.assertEqual(scenario.lang_info("js"), ("JavaScript", "javascript.svg"))
        self.assertEqual(scenario.lang_info("css"), ("CSS", "css.svg"))
        self.assertEqual(scenario.lang_info("brainfuck"), ("brainfuck", ""))
        page = Path(scenario.__file__).parent / "efir" / "page" / "lang"
        for lang in ("python", "javascript", "css", "html", "kotlin", "java", "sql", "bash"):
            label, icon = scenario.lang_info(lang)
            if icon:
                svg = (page / icon).read_text(encoding="utf-8")
                self.assertIn("<svg", svg)
                self.assertNotIn("<script", svg.lower())


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'


def make_docx(path: Path, paragraphs: list[str], colored: str = "") -> Path:
    import zipfile
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    if colored:
        body += ('<w:p><w:r><w:t xml:space="preserve">Скажи: </w:t></w:r><w:r><w:rPr><w:color w:val="7030A0"/>'
                 f'</w:rPr><w:t>{colored}</w:t></w:r></w:p>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {W}><w:body>{body}</w:body></w:document>')
    return path


def make_pptx(path: Path, slides: list[str]) -> Path:
    import zipfile
    with zipfile.ZipFile(path, "w") as z:
        for i, text in enumerate(slides, 1):
            z.writestr(f"ppt/slides/slide{i}.xml",
                       f'<?xml version="1.0"?><p:sld xmlns:p="x" {A}><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:sld>')
    return path


def make_pdf(path: Path, pages: list[str]) -> Path:
    from PySide6.QtGui import QFont, QPainter, QPdfWriter
    w = QPdfWriter(str(path))
    p = QPainter(w)
    p.setFont(QFont("Arial", 24))
    for i, text in enumerate(pages):
        if i:
            w.newPage()
        p.drawText(400, 1200, text)
    p.end()
    return path


class MaterialsTest(unittest.TestCase):
    def test_docx(self):
        from autoprint import materials
        m = materials.extract(str(make_docx(TMP / "m.docx", ["Первый абзац", "Второй абзац"])))
        self.assertIn("Первый абзац\nВторой абзац", m.text)
        self.assertIsNone(m.pdf)

    def test_docx_colored_marked(self):
        from autoprint import materials
        m = materials.extract(str(make_docx(TMP / "c.docx", ["Обычный"], colored="Это читаем дословно")))
        self.assertIn("Скажи: ⟦Это читаем дословно⟧", m.text)
        self.assertIn("⟦", m.text.split("\n")[0])        # пояснение про ⟦…⟧ — в начале материала

    def test_pptx(self):
        from autoprint import materials
        slides = [f"Текст слайда {i}" for i in range(1, 12)]
        m = materials.extract(str(make_pptx(TMP / "s.pptx", slides)))
        self.assertIn("=== Слайд 2 ===\nТекст слайда 2", m.text)
        self.assertLess(m.text.index("Слайд 2 ==="), m.text.index("Слайд 10 ==="))   # 10 после 2, не после 1

    def test_pdf_text_and_render(self):
        from autoprint import materials
        pdf = make_pdf(TMP / "p.pdf", ["Привет мир", "Страница два"])
        m = materials.extract(str(pdf))
        self.assertEqual((m.pdf, m.pages), (str(pdf), 2))
        self.assertIn("=== Страница 1 ===", m.text)
        self.assertIn("Привет мир", m.text)
        self.assertIn("Страница два", m.text)
        png = materials.render_page(str(pdf), 2, TMP / "media", width=320)
        self.assertTrue(png and png.is_file() and png.suffix == ".png")
        self.assertIsNone(materials.render_page(str(pdf), 7, TMP / "media"))

    def test_txt_cp1251(self):
        from autoprint import materials
        f = TMP / "t.txt"
        f.write_bytes("Тема урока: циклы".encode("cp1251"))
        self.assertEqual(materials.extract(str(f)).text.strip(), "Тема урока: циклы")

    def test_old_doc_explains(self):
        from autoprint import materials
        f = TMP / "old.doc"
        f.write_bytes(b"\xd0\xcf\x11\xe0")
        with self.assertRaisesRegex(ValueError, "docx"):
            materials.extract(str(f))


SCENARIO_ANSWER = """Вот сценарий:
```json
{"format": "autoprintcode-lesson", "version": 2, "title": "Тёмная тема",
 "blocks": [
  {"type": "task", "text": "## Цель\\nПереключение светлой и тёмной темы."},
  {"type": "stage", "title": "Зачем нужна тёмная тема", "min": 10, "part": "Тёмная тема", "note": "теория"},
  {"type": "say", "text": "Сейчас тёмная тема — главный тренд."},
  {"type": "ask", "text": "Какие темы вы предпочитаете?", "answer": ["пишут в чат", "глаза меньше устают"]},
  {"type": "image", "slide": 3, "caption": "Пример YouTube"},
  {"type": "stage", "title": "Перерыв", "minutes": 10, "kind": "перерыв"},
  {"type": "stage", "title": "Создание тёмной темы", "min": 25, "kind": "practice"},
  {"type": "show", "text": "Задание на платформе"},
  {"type": "code", "lang": "css", "code": ".darkTheme {\\n  color: #fff;\\n}"},
  {"type": "trap", "text": "- чистый #000"},
 ]}
```"""


class ScenarioAiTest(unittest.TestCase):
    def test_prompt_mentions_blocks(self):
        from autoprint import lesson_ai as L
        opt = L.Options(style=L.STYLE_SCENARIO, minutes=80, break_min=10)
        p = L.build_prompt("Методичка: тёмная тема", opt)
        for word in ('"stage"', '"say"', '"ask"', '"answer"', '"do"', '"show"', '"image"', '"slide"', "80",
                     '"kind": "break"', "10 мин", "Методичка: тёмная тема"):
            self.assertIn(word, p)
        self.assertIn("Сценарий урока", L.STYLES.values())

    def test_parse_scenario(self):
        from autoprint import lesson_ai as L
        asked = []

        def slide(n):
            asked.append(n)
            return str(TMP / f"slide-{n}.png")

        r = L.parse_lesson(SCENARIO_ANSWER, slide=slide)
        t = r.template
        kinds = [(b.type, b.role if b.type == BLOCK_MARKDOWN else b.title) for b in t.blocks]
        self.assertEqual(kinds[0], (BLOCK_MARKDOWN, "task"))
        st = [b for b in t.blocks if b.type == BLOCK_STAGE]
        self.assertEqual([(b.title, b.minutes, b.stage_kind) for b in st],
                         [("Зачем нужна тёмная тема", 10, ""), ("Перерыв", 10, "break"),
                          ("Создание тёмной темы", 25, "")])
        self.assertEqual((st[0].part, st[0].text), ("Тёмная тема", "теория"))
        ask = next(b for b in t.blocks if b.role == "ask")
        self.assertEqual(ask.text, "Какие темы вы предпочитаете?\n→ пишут в чат\n→ глаза меньше устают")
        img = next(b for b in t.blocks if b.type == BLOCK_IMAGE)
        self.assertEqual((asked, img.text, img.title), ([3], str(TMP / "slide-3.png"), "Пример YouTube"))
        self.assertEqual(t.active_block, t.code_blocks()[0].id)
        self.assertEqual(t.title, "Тёмная тема")
        self.assertIn("этапов: 3", r.summary)

    def test_parse_no_code_ok(self):
        from autoprint import lesson_ai as L
        r = L.parse_lesson('{"blocks": [{"type": "stage", "title": "Вступление", "min": 5},'
                           ' {"type": "say", "text": "Привет"}]}')
        self.assertEqual(len(r.template.blocks), 2)
        self.assertEqual(r.template.active_block, "")

    def test_parse_nothing_error(self):
        from autoprint import lesson_ai as L
        with self.assertRaises(L.LessonError):
            L.parse_lesson('{"blocks": [{"type": "say", "text": "только речь"}]}')

    def test_image_without_source_warns(self):
        from autoprint import lesson_ai as L
        r = L.parse_lesson('{"blocks": [{"type": "stage", "title": "А", "min": 5},'
                           ' {"type": "image", "slide": 4}, {"type": "image", "url": "https://x.y/a.png"},'
                           ' {"type": "image", "url": "javascript:alert(1)"}]}')
        imgs = [b for b in r.template.blocks if b.type == BLOCK_IMAGE]
        self.assertEqual([b.text for b in imgs], ["https://x.y/a.png"])
        self.assertTrue(any("слайд 4" in w.lower() for w in r.warnings))

    def test_unknown_type_warns(self):
        from autoprint import lesson_ai as L
        r = L.parse_lesson('{"blocks": [{"type": "stage", "title": "А", "min": 5}, {"type": "wow", "text": "т"}]}')
        self.assertTrue(r.warnings)
        self.assertEqual(r.template.blocks[1].role, "text")


if __name__ == "__main__":
    unittest.main(verbosity=2)
