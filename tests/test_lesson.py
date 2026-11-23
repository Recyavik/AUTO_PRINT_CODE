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

from PySide6.QtCore import QObject  # noqa: E402
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

    def test_broken_office_file_is_value_error(self):
        from autoprint import materials
        for name, data in (("broken.docx", b"not a zip at all"), ("broken.pptx", b"PK\x03\x04garbage")):
            f = TMP / name
            f.write_bytes(data)
            with self.assertRaises(ValueError, msg=name):
                materials.extract(str(f))
        import zipfile
        bad_xml = TMP / "badxml.docx"
        with zipfile.ZipFile(bad_xml, "w") as z:
            z.writestr("word/document.xml", "<w:document><unclosed>")
        with self.assertRaises(ValueError):
            materials.extract(str(bad_xml))

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

    def test_parse_start_time(self):
        from autoprint import lesson_ai as L
        r = L.parse_lesson('{"start": "09:15", "blocks": [{"type": "stage", "title": "А", "min": 5}]}')
        self.assertEqual(r.template.start, "09:15")
        r = L.parse_lesson('{"start": "утром", "blocks": [{"type": "stage", "title": "А", "min": 5}]}')
        self.assertEqual(r.template.start, "")

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


PORT = 18891


class LessonServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from autoprint.efir.server import BroadcastServer
        cls.cmds = []
        cls.srv = BroadcastServer(PORT, on_command=cls.cmds.append)
        assert cls.srv.start()
        cls.base = cls.srv.url

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def get(self, path, headers=None):
        import urllib.request
        req = urllib.request.Request(self.base + path.lstrip("/"), headers=headers or {})
        return urllib.request.urlopen(req, timeout=5)

    def post(self, path, data, headers=None):
        import urllib.request
        req = urllib.request.Request(self.base + path.lstrip("/"), data=json.dumps(data).encode(),
                                     headers={"Content-Type": "application/json", **(headers or {})}, method="POST")
        return urllib.request.urlopen(req, timeout=5)

    def test_lesson_channel(self):
        self.srv.publish({"mode": "idle", "caption": "экран"})
        self.srv.publish({"lesson": {"title": "Тёмная тема"}}, channel="lesson")
        self.assertNotIn("lesson", self.srv.snapshot())
        self.assertEqual(self.srv.snapshot("lesson")["lesson"]["title"], "Тёмная тема")
        r = self.get("/events?ch=lesson")
        first = r.readline().decode("utf-8")
        self.assertEqual(json.loads(first[6:])["lesson"]["title"], "Тёмная тема")
        r.readline()
        self.srv.publish({"mode": "break"})                                   # экран — не канал урока
        self.srv.publish({"lesson": {"title": "Второй"}}, channel="lesson")
        second = r.readline().decode("utf-8")
        self.assertEqual(json.loads(second[6:])["lesson"]["title"], "Второй")
        r.close()
        s = self.get("/events")
        self.assertEqual(json.loads(s.readline().decode("utf-8")[6:])["mode"], "break")
        s.close()

    def test_lesson_page(self):
        html = self.get("/lesson").read().decode("utf-8")
        self.assertIn("Экран урока", html)

    def test_static_lang(self):
        import urllib.error
        r = self.get("/static/lang/python.svg")
        self.assertEqual((r.status, r.headers["Content-Type"]), (200, "image/svg+xml"))
        self.assertIn(b"<svg", r.read())
        for bad in ("/static/lang/../server.py", "/static/lang/%2e%2e%2fserver.py", "/static/lang/nope.svg",
                    "/static/screen.html"):
            with self.assertRaises(urllib.error.HTTPError, msg=bad) as cm:
                self.get(bad)
            self.assertEqual(cm.exception.code, 404, bad)

    def test_cmd_requires_header(self):
        import urllib.error
        self.cmds.clear()
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.post("/lesson/cmd", {"cmd": "start"})
        self.assertEqual(cm.exception.code, 403)
        self.assertEqual(self.cmds, [])
        r = self.post("/lesson/cmd", {"cmd": "start_at", "index": 2}, {"X-Suflor": "1"})
        self.assertTrue(json.loads(r.read())["ok"])
        self.assertEqual(self.cmds[-1], {"cmd": "start_at", "index": 2})

    def test_cmd_foreign_origin(self):
        import urllib.error
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.post("/lesson/cmd", {"cmd": "stop"}, {"X-Suflor": "1", "Origin": "http://evil.example"})
        self.assertEqual(cm.exception.code, 403)
        r = self.post("/lesson/cmd", {"cmd": "stop"}, {"X-Suflor": "1", "Origin": self.base.rstrip("/")})
        self.assertEqual(r.status, 200)


class FakeMain(QObject):
    def __init__(self, port: int):
        from autoprint.storage import Settings
        super().__init__()
        self.settings = Settings()
        self.settings.efir_port = port


class EfirLessonTest(unittest.TestCase):
    def setUp(self):
        from autoprint.efir import store as store_mod
        from autoprint.ui import efir_control
        self.data = TMP / f"efir-{time.time_ns()}"
        self._efir_dir = store_mod.efir_dir
        store_mod.efir_dir = lambda: self.data
        self.ctl = efir_control.EfirController(FakeMain(PORT + 20))

    def tearDown(self):
        from autoprint.efir import store as store_mod
        if self.ctl.timer_window is not None:
            self.ctl.timer_window.close_silently()
        if self.ctl.window is not None:
            self.ctl.window.close()
        self.ctl.server.stop()
        store_mod.efir_dir = self._efir_dir

    def lesson(self) -> Template:
        t = dark_theme_lesson()
        t.blocks.insert(1, stage("Отметка", 0))
        t.blocks.append(stage("Гимнастика для глаз", 5, kind="exercise"))
        return t

    def test_webinar_for(self):
        from autoprint.efir.model import KIND_BREAK, KIND_EXERCISE, KIND_NORMAL, Exercise, Webinar
        preset = Webinar(title="1Т", background="anim:cube", exercises=[Exercise("Глаза", "C:/v.mp4")],
                         break_min=15, break_title="ОТДЫХ")
        t = self.lesson()
        w = scenario.webinar_for(t, preset)
        self.assertEqual((w.id, w.lesson_id, w.title), ("lesson-" + t.id, t.id, t.title))
        self.assertEqual([(a.name, a.min, a.kind) for a in w.schedule],
                         [("Вступление", 2, KIND_NORMAL), ("Зачем нужна тёмная тема", 8, KIND_NORMAL),
                          ("Перерыв", 10, KIND_BREAK), ("Гимнастика для глаз", 5, KIND_EXERCISE)])
        self.assertEqual((w.background, w.break_title, w.break_min), ("anim:cube", "ОТДЫХ", 10))
        self.assertEqual([e.title for e in w.exercises], ["Глаза"])
        self.assertEqual(preset.exercises[0].title, "Глаза")             # пресет не тронут
        plain = scenario.webinar_for(t, None)
        self.assertEqual(plain.background, "color:#000000")

    def test_hidden_in_list(self):
        from autoprint.efir.model import Webinar
        from autoprint.efir.store import WebinarStore
        from autoprint.efir.model import Activity
        self.ctl.store.add([Webinar(title="1Т", schedule=[Activity("Теория", 20)])])
        self.ctl.store.put(scenario.webinar_for(self.lesson(), None))
        self.assertEqual([w.title for w in self.ctl.store.visible()], ["1Т"])
        again = WebinarStore(self.ctl.store.path)
        self.assertEqual(sorted(bool(w.lesson_id) for w in again.webinars), [False, True])

    def test_launch_lesson(self):
        from datetime import datetime
        from autoprint.efir.model import anchor_at
        t = self.lesson()
        self.assertTrue(self.ctl.launch_lesson(t, show=False))
        live = self.ctl.store.live
        self.assertEqual(live.webinar_id, "lesson-" + t.id)
        self.assertLess(abs((datetime.now() - live.anchor).total_seconds()), 5)
        self.assertEqual(self.ctl.live_lesson_id(), t.id)
        first = live.anchor
        t.blocks.append(stage("Итоги", 5))
        self.ctl.launch_lesson(t, show=False)                           # тот же урок — время не сбивается
        self.assertEqual(self.ctl.store.live.anchor, first)
        self.assertEqual(self.ctl.live_webinar().schedule[-1].name, "Итоги")
        other = Template(title="Другой", blocks=[stage("А", 5)])
        self.ctl.launch_lesson(other, start="09:30", show=False)
        self.assertEqual(self.ctl.store.live.anchor, anchor_at("09:30", datetime.now()))
        self.assertEqual([w.lesson_id for w in self.ctl.store.webinars if w.lesson_id], [other.id])   # старый убран
        self.ctl.stop_live()
        self.assertEqual(self.ctl.live_lesson_id(), "")

    def test_launch_start_is_lesson_time(self):
        """Начало урока — момент запуска или выбранное время, а не старт из шаблона-оформления."""
        from autoprint.efir.model import Activity, Webinar
        preset = Webinar(title="1Т", start="11:00", schedule=[Activity("Пара", 90)])
        self.ctl.store.add([preset])
        t = self.lesson()
        t.preset = preset.id
        self.ctl.launch_lesson(t, show=False)
        w = self.ctl.live_webinar()
        self.assertEqual(w.start, self.ctl.store.live.anchor.strftime("%H:%M"))
        self.ctl.launch_lesson(t, start="16:30", show=False)
        self.assertEqual(self.ctl.live_webinar().start, "16:30")

    def test_launch_without_minutes_refused(self):
        t = Template(title="Пусто", blocks=[stage("Ноль", 0), md("say", "Привет")])
        self.assertFalse(self.ctl.launch_lesson(t, show=False))
        self.assertIsNone(self.ctl.store.live)

    def test_efir_window_hides_lessons(self):
        from autoprint.efir.model import Webinar
        self.ctl.store.add([Webinar(title="1Т")])
        self.ctl.launch_lesson(self.lesson(), show=False)
        self.ctl.show_window()
        pump(50)
        from autoprint.ui.efir_window import WebinarCard
        cards = self.ctl.window.findChildren(WebinarCard)
        self.assertEqual([c.w.title for c in cards], ["1Т"])


def media(path) -> str:
    return "/media/0123456789abcdef/" + Path(path).name


def groups(les):
    """Блоки урока по этапам из плоского списка items (0.10): (до первого этапа, [блоки этапа 0, 1, …])."""
    intro, stages = [], []
    for it in les["items"]:
        if it["type"] == "stage":
            stages.append([])
        elif stages:
            stages[-1].append(it)
        else:
            intro.append(it)
    return intro, stages


def kind(it):
    return it.get("role") or it["type"]


class StateTest(unittest.TestCase):
    def state(self, t, **kw):
        args = dict(live_anchor_ms=None, armed="", media_url=media, presets=[], preset="", dark=True,
                    efir_mode="idle", tab="", hotkey="Ctrl+F9")
        args.update(kw)
        return scenario.lesson_state(t, **args)

    def test_state_stages(self):
        t = dark_theme_lesson()
        code = t.code_blocks()[0]
        st = self.state(t, live_anchor_ms=1_700_000_000_000, armed=code.id, presets=[("p1", "1Т")], preset="p1")
        les = st["lesson"]
        self.assertEqual((les["title"], les["total"], les["has_stages"]), ("Урок 3. Тёмная тема", 20, True))
        intro, blocks = groups(les)
        self.assertEqual([kind(b) for b in intro], ["task"])
        self.assertEqual([(s["start"], s["end"], s["kind"]) for s in les["stages"]],
                         [(0, 2, ""), (2, 10, ""), (10, 20, "break")])
        s1 = les["stages"][1]
        self.assertEqual((s1["title"], s1["part"], s1["note"]), ("Зачем нужна тёмная тема", "Тёмная тема", "теория"))
        self.assertEqual([kind(b) for b in blocks[1]], ["ask", "important", "code"])
        ask = blocks[1][0]
        self.assertEqual((ask["html"], ask["answers"]), ("<p>Какие темы вы предпочитаете?</p>", ["пишут в чат"]))
        cb = blocks[1][2]
        self.assertEqual((cb["id"], cb["label"], cb["icon"]), (code.id, "CSS", "css.svg"))
        self.assertIn("t-", cb["html"])
        self.assertEqual((st["armed"], st["hotkey"], st["live"]), (code.id, "Ctrl+F9", {"anchor": 1_700_000_000_000}))
        self.assertEqual((les["presets"], les["preset"]), ([{"id": "p1", "title": "1Т"}], "p1"))

    def test_state_no_stages(self):
        t = Template(title="Старое", blocks=[md("task", "## Задача"), Block(BLOCK_CODE, "print(1)")])
        les = self.state(t)["lesson"]
        self.assertFalse(les["has_stages"])
        self.assertEqual([kind(b) for b in groups(les)[0]], ["task", "code"])
        self.assertEqual(les["stages"], [])

    def test_state_missing_image(self):
        f = TMP / "slide-ok.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n")
        t = Template(title="К", blocks=[Block(BLOCK_IMAGE, str(f), title="Есть"),
                                        Block(BLOCK_IMAGE, str(TMP / "нет.png"), title="Нет"),
                                        Block(BLOCK_IMAGE, "https://x.y/a.png"),
                                        Block(BLOCK_IMAGE, "javascript:alert(1)")])
        imgs = self.state(t)["lesson"]["items"]
        self.assertEqual([(b["url"], b["missing"]) for b in imgs],
                         [(media(f), False), ("", True), ("https://x.y/a.png", False), ("", True)])
        self.assertEqual(imgs[0]["title"], "Есть")

    def test_state_escapes(self):
        t = Template(title="<b>Урок</b>", blocks=[stage("<i>Этап</i>", 5),
                                                  md("say", "<script>alert(1)</script>")])
        les = self.state(t)["lesson"]
        self.assertEqual(les["stages"][0]["title"], "<i>Этап</i>")          # простой текст: страница — textContent
        self.assertIn("&lt;script&gt;", groups(les)[1][0][0]["html"])
        self.assertNotIn("<script>", json.dumps(les, ensure_ascii=False).replace('\\u003c', '<').replace(
            "<script>alert(1)</script>", ""))


class ControllerTest(unittest.TestCase):
    """Главное окно (offscreen) + контроллер суфлёра: что уходит на страницу и что делают её команды."""

    @classmethod
    def setUpClass(cls):
        from autoprint.efir import store as store_mod
        from autoprint.storage import Settings, TemplateStore
        from autoprint.ui import lesson_control
        from autoprint.ui.main_window import MainWindow
        cls.data = TMP / "ctl-efir"
        cls._efir_dir = store_mod.efir_dir
        store_mod.efir_dir = lambda: cls.data
        cls.opened = []
        cls._launch = lesson_control.launch_app_window
        lesson_control.launch_app_window = lambda url: cls.opened.append(url) or True
        s = Settings()
        s.efir_port = PORT + 40
        cls.store = TemplateStore()
        cls.t = dark_theme_lesson()
        cls.store.insert(cls.t)
        cls.win = MainWindow(s, cls.store)
        cls.win.printer.set_focus(cls.t.id)
        pump(50)

    @classmethod
    def tearDownClass(cls):
        from autoprint.efir import store as store_mod
        from autoprint.ui import lesson_control
        cls.win.efir.stop_live()
        cls.win.efir.shutdown()
        cls.win.hotkeys.stop() if hasattr(cls.win.hotkeys, "stop") else None
        cls.win.close()
        lesson_control.launch_app_window = cls._launch
        store_mod.efir_dir = cls._efir_dir

    def snap(self):
        self.win.lesson.publish()
        return self.win.efir.server.snapshot("lesson")

    def test_publish_current(self):
        st = self.snap()
        self.assertEqual(st["lesson"]["title"], "Урок 3. Тёмная тема")
        self.assertEqual(st["hotkey"], self.win.settings.hotkey_toggle)
        self.assertIsNone(st["live"])

    def test_cmd_arm(self):
        code = self.t.code_blocks()[0]
        self.t.active_block = ""
        self.win.lesson.command({"cmd": "arm", "block": code.id})
        self.assertEqual(self.t.active_block, code.id)
        self.assertEqual(self.snap()["armed"], code.id)

    def test_cmd_start_at_and_stop(self):
        from datetime import datetime
        self.win.lesson.command({"cmd": "start", "now": True})
        self.assertEqual(self.win.efir.live_lesson_id(), self.t.id)
        self.assertIsNotNone(self.snap()["live"])
        self.win.lesson.command({"cmd": "start_at", "index": 2})             # этап «Перерыв» — с 10-й минуты
        anchor = self.win.efir.store.live.anchor
        self.assertLess(abs((datetime.now() - anchor).total_seconds() - 600), 5)
        self.win.lesson.command({"cmd": "shift_now"})                       # текущий — тот же этап
        self.assertLess(abs((datetime.now() - self.win.efir.store.live.anchor).total_seconds() - 600), 5)
        self.win.lesson.command({"cmd": "stop"})
        self.assertEqual(self.win.efir.live_lesson_id(), "")
        self.assertIsNone(self.snap()["live"])

    def test_live_edit_syncs_efir(self):
        self.win.lesson.command({"cmd": "start", "now": True})
        self.t.blocks.append(stage("Итоги", 5))
        try:
            self.win.lesson.schedule_publish()
            end = time.time() + 3                     # ждём результата, а не фиксированные полсекунды
            while time.time() < end and self.win.efir.live_webinar().schedule[-1].name != "Итоги":
                pump(20)
            self.assertEqual(self.win.efir.live_webinar().schedule[-1].name, "Итоги")
            self.assertEqual(self.win.efir.server.snapshot("lesson")["lesson"]["total"], 25)
        finally:                                      # провал не должен оставлять урок идущим для соседей
            self.t.blocks.pop()
            self.win.lesson.command({"cmd": "stop"})

    def test_break_without_live(self):
        self.win.lesson.command({"cmd": "break", "minutes": 7})
        self.assertEqual(self.win.efir.mode, "break")
        self.assertAlmostEqual(self.win.efir.brk_total, 420)
        self.win.lesson.command({"cmd": "background"})
        self.assertEqual(self.win.efir.mode, "idle")

    def test_open_page(self):
        self.opened.clear()
        self.win.lesson.open_page()
        self.assertTrue(self.opened and self.opened[-1].endswith("/lesson"))
        self.assertTrue(self.win.efir.server.running)

    def test_preset_saved(self):
        """0.10: урок выбирает оформление (Template.look); preset 0.9 не меняется — откат."""
        from autoprint.efir.model import Look
        look = Look(title="ФУ", background="anim:stars")
        self.win.efir.store.put_look(look)
        self.win.lesson.command({"cmd": "preset", "id": look.id})
        self.assertEqual((self.t.look, self.win.settings.lesson_look), (look.id, look.id))
        self.assertEqual(self.snap()["lesson"]["preset"], look.id)
        self.assertIn({"id": look.id, "title": "ФУ"}, self.snap()["lesson"]["presets"])

    def test_armed_stage_not_printed(self):
        st = next(b for b in self.t.blocks if b.type == BLOCK_STAGE and b.text)    # с пометкой «теория»
        keep = self.t.active_block
        self.t.active_block = st.id
        try:
            self.assertIsNone(self.win.printer.job_for_armed())
        finally:
            self.t.active_block = keep

    def test_edit_from_timer_keeps_lesson(self):
        """Ревью №2: «Изменить…» в таймере идущего урока правит его оформление, а не служебный эфир."""
        from autoprint.efir.model import Look
        look = Look(title="Оформление урока", background="anim:cube")
        self.win.efir.store.put_look(look)
        self.win.lesson.command({"cmd": "preset", "id": look.id})
        self.win.lesson.command({"cmd": "start", "now": True})
        try:
            ctl = self.win.efir
            ctl.edit_live()
            ed = ctl.editors[-1]
            self.assertEqual((ed.mode, ed.look.id), ("look", look.id))
            lk = ed.result()
            lk.background = "anim:stars"
            ctl.save_look(lk)
            pump(450)
            self.assertEqual(ctl.live_lesson_id(), self.t.id)                       # урок по-прежнему идёт
            self.assertEqual(ctl.live_webinar().background, "anim:stars")           # оформление — сразу
            self.assertEqual([x.title for x in ctl.store.looks].count("Оформление урока"), 1)
        finally:
            for e in list(self.win.efir.editors):
                e._dirty = False
                e.close()
            self.win.lesson.command({"cmd": "stop"})

    def test_set_start_cmd(self):
        from datetime import datetime
        from autoprint.efir.model import anchor_at
        self.win.lesson.command({"cmd": "set_start", "start": "16:30"})        # урок не идёт — запоминается
        self.assertEqual(self.t.start, "16:30")
        self.win.lesson.command({"cmd": "set_start", "start": "25:99"})       # неверное — не меняет
        self.assertEqual(self.t.start, "16:30")
        self.assertEqual(self.snap()["lesson"]["start"], "16:30")
        self.win.lesson.command({"cmd": "start", "at": "16:30"})
        try:
            self.assertEqual(self.win.efir.store.live.anchor, anchor_at("16:30", datetime.now()))
        finally:
            self.win.lesson.command({"cmd": "stop"})
            self.win.lesson.command({"cmd": "set_start", "start": ""})
        self.assertEqual(self.t.start, "")

    def test_same_state_not_republished(self):
        """Во время зарядки экран эфира шлёт ход видео раз в секунду — страница суфлёра не должна
        перерисовываться (и терять щелчки по кнопкам), если для неё ничего не поменялось."""
        srv = self.win.efir.server
        self.win.lesson.publish()
        rev = srv._revs["lesson"]
        self.win.lesson.publish()
        self.win.efir.screen_changed.emit()
        pump(450)
        self.assertEqual(srv._revs["lesson"], rev)
        self.t.title = "Урок 3. Тёмная тема!"
        try:
            self.win.lesson.publish()
            self.assertEqual(srv._revs["lesson"], rev + 1)
        finally:
            self.t.title = "Урок 3. Тёмная тема"

    def test_unknown_cmd_ignored(self):
        self.win.lesson.command({"cmd": "rm -rf"})
        self.win.lesson.command({"nothing": 1})
        self.win.lesson.command({"cmd": "arm", "block": "нет-такого"})
        self.win.lesson.command({"cmd": "start_at", "index": "x"})


def make_png(path: Path) -> Path:
    from PySide6.QtGui import QColor, QImage
    img = QImage(64, 36, QImage.Format.Format_RGB32)
    img.fill(QColor("#336699"))
    img.save(str(path))
    return path


class EditorTest(unittest.TestCase):
    """Картинки и экспорт урока (редактор блоков Qt удалён в 0.10 — правка урока на экране урока)."""

    def test_image_ref_survives_data_move(self):
        """Ревью №4: картинка хранится относительно папки данных — переезд данных её не ломает."""
        import shutil
        from autoprint import storage
        ref = storage.import_media(make_png(TMP / "move.png"))
        self.assertTrue(ref.startswith("media/"), ref)
        old_abs = storage.DATA_DIR / ref
        moved = TMP / f"moved-data-{time.time_ns()}"
        (moved / "media").mkdir(parents=True)
        shutil.copy2(old_abs, moved / ref)
        orig = storage.DATA_DIR
        storage.DATA_DIR = moved
        try:
            self.assertEqual(storage.media_path(ref), moved / ref)
            # старый урок с абсолютным путём из прежней папки данных — находится по имени в новой
            self.assertEqual(storage.media_path(str(TMP / "gone" / "data" / ref)), moved / ref)
            st = scenario.lesson_state(Template(title="К", blocks=[Block(BLOCK_IMAGE, ref)]), live_anchor_ms=None,
                                       armed="", media_url=media, presets=[], preset="", dark=True,
                                       efir_mode="idle", tab="", hotkey="")
            self.assertFalse(st["lesson"]["items"][0]["missing"])
            self.assertIsNone(storage.media_path("media/нет-такого.png"))
            self.assertIsNone(storage.media_path("https://x.y/a.png"))
        finally:
            storage.DATA_DIR = orig

    def test_export_students_and_roundtrip(self):
        from autoprint.importers import export_ipynb, import_ipynb
        t = dark_theme_lesson()
        t.blocks.append(Block(BLOCK_IMAGE, str(make_png(TMP / "e3.png")), title="Слайд"))
        full = TMP / "full.ipynb"
        export_ipynb(t, str(full))
        back = import_ipynb(str(full))
        self.assertEqual([(b.type, b.title, b.minutes, b.stage_kind) for b in back.blocks if b.type == BLOCK_STAGE],
                         [(BLOCK_STAGE, "Вступление", 2, ""), (BLOCK_STAGE, "Зачем нужна тёмная тема", 8, ""),
                          (BLOCK_STAGE, "Перерыв", 10, "break")])
        self.assertEqual([b.role for b in back.blocks if b.type == BLOCK_MARKDOWN], ["task", "say", "ask", "important"])
        self.assertEqual(back.blocks[-1].type, BLOCK_IMAGE)
        kids = TMP / "kids.ipynb"
        export_ipynb(t, str(kids), students=True)
        text = json.dumps(json.loads(kids.read_text(encoding="utf-8")), ensure_ascii=False)
        for gone in ("Очень рад видеть", "Какие темы", "Чистого чёрного #000", "## Зачем нужна тёмная тема"):
            self.assertNotIn(gone, text)
        self.assertIn(".darkTheme", text)
        cells = json.loads(kids.read_text(encoding="utf-8"))["cells"]
        self.assertTrue(cells and all(c["cell_type"] == "code" for c in cells))    # 0.10: ученикам — только код


class ImportTest(unittest.TestCase):
    def dialog(self):
        from autoprint.storage import Settings
        from autoprint.ui.import_dialog import TAB_AI, ImportDialog
        d = ImportDialog(None, Settings(), tab=TAB_AI)
        self.addCleanup(d.close)
        return d

    def test_scenario_options(self):
        from autoprint import lesson_ai as L
        d = self.dialog()
        d.style_seg.set_value(L.STYLE_SCENARIO)
        d._style_changed(L.STYLE_SCENARIO)
        d.minutes_spin.setValue(80)
        d.break_spin.setValue(10)
        d.material.setPlainText("x\n" * 400)               # большой текст — но это методичка, не разметка кода
        o = d._options()
        self.assertEqual((o.style, o.minutes, o.break_min, o.marks), (L.STYLE_SCENARIO, 80, 10, False))
        self.assertTrue(d.row_keep.isHidden() and d.row_task.isHidden())
        self.assertFalse(d.scenario_row.isHidden())
        d.style_seg.set_value(L.STYLE_STEPS)
        d._style_changed(L.STYLE_STEPS)
        self.assertFalse(d.row_keep.isHidden())
        self.assertTrue(d.scenario_row.isHidden())

    def test_material_from_pdf_and_slides(self):
        from autoprint import lesson_ai as L
        from autoprint.storage import DATA_DIR
        d = self.dialog()
        d.style_seg.set_value(L.STYLE_SCENARIO)
        d._style_changed(L.STYLE_SCENARIO)
        pdf = make_pdf(TMP / "lesson3.pdf", ["Цель урока", "Правила", "Пример YouTube"])
        d.load_material(str(pdf))
        self.assertIn("=== Страница 3 ===", d.material.toPlainText())
        d.answer_edit.setPlainText(SCENARIO_ANSWER)
        d._parse_answer()
        self.assertIsNotNone(d._ai_parsed)
        t = d._ai_parsed.template
        img = next(b for b in t.blocks if b.type == BLOCK_IMAGE)
        from autoprint.storage import media_path
        self.assertTrue(img.text.startswith("media/"), img.text)
        self.assertEqual(media_path(img.text).parent, DATA_DIR / "media")
        self.assertTrue(d.add_btn.isEnabled())

    def test_broken_material_no_crash(self):
        d = self.dialog()
        f = TMP / "broken2.docx"
        f.write_bytes(b"not a zip")
        d.material.setPlainText("прежний текст")
        d.load_material(str(f))                         # не исключение, а сообщение
        self.assertEqual(d.material.toPlainText(), "прежний текст")

    def test_material_docx(self):
        d = self.dialog()
        d.load_material(str(make_docx(TMP / "plan.docx", ["План урока", "Летучка — 5 минут"])))
        self.assertIn("Летучка — 5 минут", d.material.toPlainText())


if __name__ == "__main__":
    unittest.main(verbosity=2)
