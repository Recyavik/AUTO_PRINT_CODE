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

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

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
    from autoprint.app_core import App
    from autoprint.storage import Settings, TemplateStore
    s = Settings()
    s.efir_port = port
    store = TemplateStore()
    win = App(s, store, web=False)
    win.window.show()
    pump(30)
    return win, store


def drop_main(win) -> None:
    """Программа теста — удалить совсем: иначе следующая смена темы перекрашивает и её окно."""
    import shiboken6
    win.window.hide()
    win.efir.shutdown()
    shiboken6.delete(win.window)
    shiboken6.delete(win)
    pump(10)


class TrayTest(unittest.TestCase):
    def test_default_is_tray(self):
        from autoprint.storage import Settings
        self.assertTrue(Settings().close_to_tray)

    def test_migration_turns_tray_on_once(self):
        from autoprint.storage import Settings
        from autoprint.app_core import apply_migrations
        s = Settings()
        s.close_to_tray = False                 # так было сохранено у тех, кто ставил 0.8 и раньше
        self.assertTrue(apply_migrations(s))
        self.assertTrue(s.close_to_tray)
        self.assertIn("tray_v1", s.migrations)
        s.close_to_tray = False                 # выключили сами после обновления — больше не трогаем
        self.assertFalse(apply_migrations(s))
        self.assertFalse(s.close_to_tray)


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
        cls.win.printer.set_focus(cls.t.id)

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

    def test_stray_signal_does_not_delay_sync(self):
        """Ревью №4: правка идущего урока доходит до таймера не позже ~0,3 с, даже если следом прилетает
        посторонний сигнал (вкладка подключилась, экран сменился) — отложенная отправка не начинается заново."""
        from autoprint.storage import BLOCK_STAGE, Block
        self.win.lesson.command({"cmd": "start"})
        pump(400)
        t0 = time.time()
        self.t.blocks.append(Block(BLOCK_STAGE, title="Итоги", minutes=5))
        try:
            self.win.lesson.schedule_publish()
            pump(250)
            self.win.efir.tab_changed.emit()            # посторонний сигнал прямо перед отправкой
            while time.time() - t0 < 0.45:
                app.processEvents()
                time.sleep(0.005)
            self.assertEqual(self.win.efir.live_webinar().schedule[-1].name, "Итоги")
        finally:
            self.t.blocks.pop()

    def test_set_start_live(self):
        from datetime import datetime
        from autoprint.efir.model import anchor_at
        self.win.lesson.command({"cmd": "start"})
        self.win.lesson.command({"cmd": "set_start", "start": "07:45"})
        self.assertEqual(self.win.efir.store.live.anchor, anchor_at("07:45", datetime.now()))
        self.win.lesson.command({"cmd": "set_start", "start": "99:99"})     # неверное — без изменений
        self.assertEqual(self.win.efir.store.live.anchor, anchor_at("07:45", datetime.now()))



# ================================================================ Task 5: редактор шаблона «Эфира»

class EfirLookTest(unittest.TestCase):
    """Оформление: надпись перерыва, предпросмотр (редактор — с 1.0 на странице «Эфир», tests/test_app_efir.py)."""

    def setUp(self):
        from autoprint.efir.model import sample_webinar
        self.ctl = efir_ctl("editor")
        self.w = self.ctl.store.add([sample_webinar()])[0]

    def tearDown(self):
        self.ctl.server.stop()

    def test_break_show_title_roundtrip(self):
        from autoprint.efir.model import look_from_dict, webinar_from_dict
        lk = self.ctl.put_look({"title": "Без надписи", "break_show_title": False})
        self.assertFalse(self.ctl.store.look(lk.id).break_show_title)
        self.assertFalse(look_from_dict(lk.to_dict()).break_show_title)
        self.assertTrue(webinar_from_dict({"schedule": [{"name": "А", "min": 5}]}).break_show_title)

    def test_state_hides_title(self):
        self.w.break_show_title = False
        self.ctl.webinar = self.w
        self.ctl.start_break(5)
        self.assertEqual(self.ctl.state()["brk"]["title"], "")
        self.ctl.show_background()

    def test_preview_published(self):
        from autoprint.efir.model import Webinar, compose, look_from_dict
        url = self.ctl.preview_break(compose(Webinar(title="П"), look_from_dict({"break_title": "ОТДЫХАЕМ"})))
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
    def test_screen_no_hint(self):
        from autoprint.efir.server import PAGE_DIR
        html = (PAGE_DIR / "screen.html").read_text(encoding="utf-8")
        self.assertNotIn("Щёлкните по странице", html)
        self.assertNotIn('id="hint"', html)


# ================================================================ Task 7: суфлёр как PDF — плашки ролей

class PageTest(unittest.TestCase):
    def test_block_state_has_label_title(self):
        from autoprint import scenario
        from autoprint.storage import BLOCK_MARKDOWN, Block
        st = scenario.item_state(Block(BLOCK_MARKDOWN, "Здравствуйте!", role="say", title="Повторение"),
                                 lambda p: "")
        self.assertEqual((st["role"], st["title"]), ("say", "Повторение"))
        st = scenario.item_state(Block(BLOCK_MARKDOWN, "Вопрос?\n→ ответ", role="ask"), lambda p: "")
        self.assertEqual((st["role"], st["title"], st["answers"]), ("ask", "", ["ответ"]))

    def test_page_role_styles(self):
        from autoprint.efir.server import PAGE_DIR
        css = (PAGE_DIR / "app" / "lesson.css").read_text(encoding="utf-8")      # 1.0: урок — в окне программы
        for role in ("say", "tell", "ask", "do", "important", "show", "trap", "extra", "term", "output"):
            self.assertIn(f".r-{role} {{ --rc:", css, role)
        self.assertIn("color-mix(in srgb, var(--rc)", css)
        self.assertIn('el("div", "lbl")', (PAGE_DIR / "lesson" / "render.js").read_text(encoding="utf-8"))



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


class SampleTest(unittest.TestCase):
    def test_has_everything(self):
        from autoprint import scenario
        from autoprint.samples_lesson import lesson_sample
        from autoprint.storage import BLOCK_CODE, BLOCK_IMAGE, BLOCK_STAGE, media_path
        t = lesson_sample()
        stages = [b for b in t.blocks if b.type == BLOCK_STAGE]
        self.assertGreaterEqual(len(stages), 6)
        self.assertEqual({b.stage_kind for b in stages} >= {"", "break", "exercise"}, True)
        self.assertEqual(scenario.total_minutes(t), 90)
        roles = {b.role for b in t.blocks if b.type == "markdown"}
        self.assertTrue({"say", "tell", "ask", "do", "important", "show", "trap", "extra"} <= roles, roles)
        self.assertEqual({b.lang for b in t.blocks if b.type == BLOCK_CODE}, {"python"})     # 0.10: урок по Python
        images = [b for b in t.blocks if b.type == BLOCK_IMAGE]
        self.assertGreaterEqual(len(images), 3)
        for b in images:
            self.assertTrue(b.text.startswith("media/"), b.text)
            self.assertIsNotNone(media_path(b.text), b.text)
            self.assertTrue(b.title)
        self.assertTrue(len({b.part for b in stages if b.part}) >= 2)

    def test_added_once(self):
        win, store = make_main(PORT + 5)
        try:
            from autoprint.samples_lesson import LESSON_SAMPLE_ID, LESSON_TITLE
            n = sum(t.title == LESSON_TITLE for t in store.templates)
            self.assertEqual(n, 1)
            self.assertIn(LESSON_SAMPLE_ID, win.settings.samples_seen)
            win._ensure_samples()
            self.assertEqual(sum(t.title == LESSON_TITLE for t in store.templates), 1)
        finally:
            win.efir.shutdown()
            drop_main(win)

    def test_sample_page_state(self):
        from autoprint import scenario
        from autoprint.samples_lesson import lesson_sample
        t = lesson_sample()
        st = scenario.lesson_state(t, live_anchor_ms=None, armed="", media_url=lambda p: "/media/x/" + Path(p).name,
                                   presets=[], preset="", dark=True, efir_mode="idle", tab="", hotkey="Ctrl+F9")
        imgs = [b for b in st["lesson"]["items"] if b["type"] == "image"]
        self.assertTrue(imgs and all(b["url"] and not b["missing"] for b in imgs))



# ================================================================ Task 10: урок в Markdown, картинки в .ipynb

def shape(t):
    """Что должно пережить .md: типы, роли, заголовки, минуты, виды, разделы, текст, код и язык, подписи картинок."""
    out = []
    for b in t.blocks:
        if b.type == "stage":
            out.append(("stage", b.title, b.minutes, b.stage_kind, b.part, b.text.strip()))
        elif b.type == "image":
            out.append(("image", b.title))
        elif b.type == "code":
            out.append(("code", b.lang, b.title, b.text, list(b.steps)))
        else:
            out.append(("md", b.role, b.title, b.text.strip()))
    return out


class MdTest(unittest.TestCase):
    def test_roundtrip_sample(self):
        from autoprint import lesson_md
        from autoprint.samples_lesson import lesson_sample
        t = lesson_sample()
        t.blocks[2].steps = []
        path = TMP / "md-rt" / "Функции.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        lesson_md.export_md(t, path)
        text = path.read_text(encoding="utf-8")
        self.assertTrue(lesson_md.looks_like_lesson(text))
        self.assertIn("## Приветствие и цель · 4 мин", text)
        self.assertIn("> [!say]", text)
        back = lesson_md.parse(text, path.parent, "x")
        self.assertEqual(back.title, t.title)
        self.assertEqual(shape(back), shape(t))

    def test_images_copied_back(self):
        from autoprint import lesson_md
        from autoprint.samples_lesson import lesson_sample
        from autoprint.storage import media_path
        t = lesson_sample()
        path = TMP / "md-img" / "Урок с картинками.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        lesson_md.export_md(t, path)
        folder = path.parent / "Урок с картинками_files"
        self.assertEqual(len(list(folder.glob("*.png"))), 3)
        back = lesson_md.parse(path.read_text(encoding="utf-8"), path.parent, "x")
        imgs = [b for b in back.blocks if b.type == "image"]
        self.assertEqual(len(imgs), 3)
        for b in imgs:
            self.assertTrue(b.text.startswith("media/"), b.text)
            self.assertIsNotNone(media_path(b.text))

    def test_load_file_uses_lesson_format(self):
        from autoprint import importers, lesson_md
        from autoprint.samples_lesson import lesson_sample
        path = TMP / "md-load" / "урок.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        lesson_md.export_md(lesson_sample(), path)
        t = importers.load_file(str(path))
        self.assertEqual(sum(b.type == "stage" for b in t.blocks), 12)

    def test_plain_md_unchanged(self):
        from autoprint import importers, lesson_md
        text = "# Заметки\n\nПросто текст.\n\n```python\nprint(1)\n```\n"
        self.assertFalse(lesson_md.looks_like_lesson(text))
        path = TMP / "plain.md"
        path.write_text(text, encoding="utf-8")
        t = importers.load_file(str(path))
        self.assertEqual([b.type for b in t.blocks], ["markdown", "code"])

    def test_unknown_role_text(self):
        from autoprint import lesson_md
        t = lesson_md.parse("## Этап · 5 мин\n\n> [!NOTE] Заметка\n> текст\n", None, "x")
        self.assertEqual(shape(t)[1], ("md", "text", "Заметка", "текст"))

    def test_russian_role_names(self):
        from autoprint import lesson_md
        t = lesson_md.parse("## Этап · 5 мин · перерыв\n\n> [!Говоришь]\n> Привет\n\n> [!для быстрых]\n> ещё\n",
                            None, "x")
        self.assertEqual(shape(t), [("stage", "Этап", 5, "break", "", ""), ("md", "say", "", "Привет"),
                                    ("md", "extra", "", "ещё")])

    def test_crlf_and_spaces(self):
        from autoprint import lesson_md
        folder = TMP / "md-crlf" / "мои картинки"
        folder.mkdir(parents=True, exist_ok=True)
        img = make_image("слайд 1.png", 40, 30)
        (folder / "слайд 1.png").write_bytes(img.read_bytes())
        text = "---\r\ntitle: Урок\r\n---\r\n\r\n## А · 2 мин\r\n*пометка*\r\n\r\n![Слайд](<мои картинки/слайд 1.png>)\r\n"
        t = lesson_md.parse(text, folder.parent, "x")
        self.assertEqual(t.title, "Урок")
        self.assertEqual(shape(t), [("stage", "А", 2, "", "", "пометка"), ("image", "Слайд")])
        self.assertTrue(t.blocks[1].text.startswith("media/"))

    def test_missing_image(self):
        from autoprint import lesson_md
        t = lesson_md.parse("## А · 2 мин\n\n![нет](пропало/x.png)\n", TMP, "x")
        self.assertEqual(t.blocks[1].type, "image")
        self.assertEqual(t.blocks[1].text, "пропало/x.png")      # блок есть — суфлёр покажет «нет файла»

    def test_fence_inside_callout_and_long_fence(self):
        from autoprint import lesson_md
        from autoprint.storage import BLOCK_CODE, BLOCK_MARKDOWN, Block, Template
        t = Template(title="Т", blocks=[Block(BLOCK_MARKDOWN, "Смотри:\n```py\nx = 1\n```", role="tell"),
                                         Block(BLOCK_CODE, 'print("```")', lang="python")])
        back = lesson_md.parse(lesson_md.to_md(t, ""), None, "x")
        self.assertEqual(shape(back), shape(t))


class MdReviewTest(unittest.TestCase):
    """Ревью №8 (переоценено в Important): импорт .md не теряет текст и не путает заметки с уроком."""

    def test_github_alert_is_not_lesson(self):
        from autoprint import importers, lesson_md
        text = "# Заметки\n\n> [!IMPORTANT]\n> Не забыть\n\n## Раздел\n\nтекст\n"
        self.assertFalse(lesson_md.looks_like_lesson(text))
        path = TMP / "gh-notes.md"
        path.write_text(text, encoding="utf-8")
        t = importers.load_file(str(path))
        self.assertFalse(any(b.type == "stage" for b in t.blocks))
        self.assertIn("Не забыть", "\n".join(b.text for b in t.blocks))

    def test_heading_without_stage_kept(self):
        from autoprint import lesson_md
        t = lesson_md.parse("## Этап · 5 мин\n\n> [!say]\n> привет\n\n# Домашнее задание\n\nСделать тёмную тему\n",
                            None, "x")
        text = "\n".join(b.text for b in t.blocks if b.type == "markdown")
        self.assertIn("Домашнее задание", text)
        self.assertIn("Сделать тёмную тему", text)

    def test_heading_before_stage_is_part(self):
        from autoprint import lesson_md
        t = lesson_md.parse("# Часть 1\n\n## Этап · 5 мин\n", None, "x")
        self.assertEqual([(b.type, b.part) for b in t.blocks], [("stage", "Часть 1")])


class MdExampleTest(unittest.TestCase):
    def test_example_file_in_sync(self):
        """examples/ — тот же урок, что встроенный образцовый (не отстаёт от кода)."""
        from autoprint import lesson_md
        from autoprint.samples_lesson import lesson_sample
        f = Path(__file__).resolve().parent.parent / "examples" / "Пример урока — функции и пароль.md"
        t = lesson_md.parse(f.read_text(encoding="utf-8"), f.parent, "x")
        self.assertEqual(shape(t), shape(lesson_sample()))
        self.assertTrue(all(b.text.startswith("media/") for b in t.blocks if b.type == "image"))


class IpynbTest(unittest.TestCase):
    def test_image_attachment(self):
        import json
        from autoprint.importers import export_ipynb, import_ipynb
        from autoprint.samples_lesson import lesson_sample
        t = lesson_sample()
        out = TMP / "урок.ipynb"
        export_ipynb(t, str(out))     # полный урок: картинки — вложениями (ученикам в 0.10 — только код)
        nb = json.loads(out.read_text(encoding="utf-8"))
        cells = [c for c in nb["cells"] if c.get("attachments")]
        self.assertEqual(len(cells), 3)
        src = "".join(cells[0]["source"])
        name = next(iter(cells[0]["attachments"]))
        self.assertIn(f"(attachment:{name})", src)
        self.assertIn("image/png", cells[0]["attachments"][name])
        self.assertNotIn("file:///", out.read_text(encoding="utf-8"))   # никаких путей с именем пользователя
        back = import_ipynb(str(out))
        self.assertEqual(sum(b.type == "image" for b in back.blocks), 3)




class ImageArmTest(unittest.TestCase):
    """Ревью №2: картинку можно сделать активной — кнопкой в редакторе и на странице суфлёра."""

    def test_live_start_field_commits_on_enter(self):
        """Ревью №3: «Начало» идущего урока — не на каждое нажатие (набрали «1» поверх 17:30 — это не 01:30),
        а по Enter/уходу из поля; шапка не перерисовывается, пока в ней печатают. Поведение в Edge проверено
        отдельно (CDP: «1» → нет команды, фокус на месте; «1830» Enter → одна команда 18:30)."""
        from autoprint.efir.server import PAGE_DIR
        js = (PAGE_DIR / "app" / "lessonview.js").read_text(encoding="utf-8")       # 1.0: панель «Идёт урок»
        self.assertNotIn('tm.onchange = () => { if (tm.value) cmd({ cmd: "set_start"', js)
        self.assertIn('tm.addEventListener("blur", commit)', js)

if __name__ == "__main__":
    unittest.main(verbosity=2)
