"""Меню урока одним списком и листы урока: экспорт (формат, галочки .autoprint с размерами), печать и PDF, план урока,
ответ нейросети, «Подставить слайды», «Разложить по этапам». Листы окна: обновление, «Сообщить об ошибке», запись
звука клавиатуры, внутренняя ошибка.

    .venv\\Scripts\\python.exe tests\\test_app_sheets.py
"""
from __future__ import annotations

import base64
import tempfile
import unittest
import zipfile
from pathlib import Path

from apphelp import AppPage, code, note, pump, stage  # noqa: F401

from autoprint import storage
from autoprint.storage import BLOCK_IMAGE, BLOCK_STAGE, Block, Template

PNG_1x1 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
TMP = Path(tempfile.mkdtemp(prefix="autoprint-sheets-"))


def media_png(name: str) -> str:
    folder = storage.DATA_DIR / storage.MEDIA_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    p.write_bytes(base64.b64decode(PNG_1x1) * 1)
    return storage.media_ref(p)


def lessons() -> list[Template]:
    p = Template("Онлайн 45", [stage("Начало", 10, id="p1"), stage("Практика", 35, id="p2")], id="P", kind="plan")
    a = Template("Циклы", [stage("Начало", 10, id="a1"), note("Привет", id="an"), code("for i in range(3):\n    print(i)", id="ac"),
                           Block(BLOCK_IMAGE, media_png("sheets-a.png"), title="Схема", id="ai")], id="A")
    e = Template("Со слайдами", [stage("Слайды", 10, id="e1"), Block(BLOCK_IMAGE, "", slide=2, id="es")], id="E")
    s = Template("Сценарий", [note("## ⏱ 00:00–00:05 · Приветствие\nЗдравствуйте", role="text", id="sn1"),
                              note("## ⏱ 00:05–00:10 · Разбор\nСмотрим код", role="text", id="sn2")], id="S")
    return [a, p, e, s]


ANSWER = "~~~markdown\n---\ntitle: По ответу\n---\n\n## Всё · 30 мин\n\n> [!say]\n> Текст по ответу\n~~~"


class SheetsTest(AppPage):
    port = 18979
    templates = staticmethod(lessons)
    route = "#/lesson/A"

    def setUp(self):
        if self.app.efir.live_webinar() is not None:
            self.stop_live()
        self.open_lesson("A")

    def tearDown(self):
        self.js("window.appUI.closePop(); document.querySelectorAll('.scrim').forEach(s => s.remove())")
        super().tearDown()

    def open_lesson(self, lid):
        self.app.open_lesson(lid, ask=False)
        self.app.lesson.publish()
        self.app.publish_now()
        self.go(f"#/lesson/{lid}", "lesson")
        title = self.store.get(lid).title
        self.assertTrue(self.wait_js(f"document.title === {title + ' — AutoPrintCode'!r}"))

    def menu_labels(self) -> list[str]:
        self.js("window.appUI.closePop()")
        self.click("#lessonMenuBtn")
        self.assertTrue(self.wait_js("!!document.querySelector('.pop .menu')"))
        return self.js("[...document.querySelectorAll('.pop .menu .mi .ml')].map(x => x.textContent)")

    def menu_pick(self, label: str):
        self.menu_labels()
        self.js(f"[...document.querySelectorAll('.pop .menu .mi')].find(b => b.querySelector('.ml').textContent === {label!r}).click()")

    def sheet(self) -> str:
        self.assertTrue(self.wait_js("!!document.querySelector('.scrim .sheet')"))
        return self.js("[...document.querySelectorAll('.scrim .sheet')].pop().textContent")

    def sheet_click(self, text: str):
        """Кнопка листа по надписи (у пунктов списка — по названию, без пояснения)."""
        f = (f"[...document.querySelectorAll('.scrim .sheet button')].filter(b => b.textContent.trim() === {text!r} || "
             f"(b.querySelector('.ml') && b.querySelector('.ml').textContent === {text!r}))")
        self.assertTrue(self.wait_js(f"{f}.length > 0"), text)
        self.js(f"{f}.pop().click()")

    def patch(self, obj, name, fn):
        old = getattr(obj, name)
        setattr(obj, name, fn)
        self.addCleanup(setattr, obj, name, old)

    # ---------------------------------------------------------------- меню
    def test_menu_is_flat_and_complete(self):
        labels = self.menu_labels()
        self.assertEqual(labels, ["Переименовать", "Дублировать", "Экспорт…", "Печать или PDF…", "План урока…",
                                  "Обновить по ответу нейросети…", "Удалить…"])
        self.assertFalse(self.js("!!document.querySelector('.pop .menu .sub, .pop .menu .menu')"))     # без подменю
        self.open_lesson("E")
        self.assertIn("Подставить слайды из презентации…", self.menu_labels())
        self.open_lesson("S")
        self.assertIn("Разложить по этапам (⏱ этапы, 🗣 реплики)", self.menu_labels())

    # ---------------------------------------------------------------- экспорт
    def test_export_md_writes_file(self):
        out = TMP / "cikly.md"
        self.patch(self.app.commands, "call_pick_save", lambda d: str(out))
        self.menu_pick("Экспорт…")
        self.assertIn("Экспорт", self.sheet())
        self.js("document.querySelector('.scrim .sheet .seg button[data-value=md]').click()")
        self.sheet_click("Сохранить…")
        self.assertTrue(self.wait_py(lambda: out.is_file()))
        self.assertIn("Циклы", out.read_text(encoding="utf-8"))
        self.assertTrue(self.wait_js("!document.querySelector('.scrim')"))

    def test_export_package_sizes_and_flags(self):
        out = TMP / "cikly.autoprint"
        self.patch(self.app.commands, "call_pick_save", lambda d: str(out))
        self.menu_pick("Экспорт…")
        self.sheet()
        self.assertTrue(self.wait_js("document.querySelector('.scrim .sheet').textContent.includes('Картинки и слайды урока —')"))
        text = self.sheet()
        self.assertRegex(text, r"Картинки и слайды урока — \d+(\.\d)? (КБ|МБ)")
        self.assertIn("Оформление экрана учеников", text)
        self.js("{ const c = [...document.querySelectorAll('.scrim .sheet label.switch')].find(l => l.textContent.includes('Оформление'));"
                " const i = c.querySelector('input'); i.checked = false; i.dispatchEvent(new Event('change')); }")
        self.sheet_click("Сохранить…")
        self.assertTrue(self.wait_py(lambda: out.is_file()))
        names = zipfile.ZipFile(out).namelist()
        self.assertFalse([n for n in names if n.startswith("looks/")], names)
        self.assertTrue([n for n in names if n.startswith("media/")], names)

    def test_export_all_from_library(self):
        out = TMP / "all.autoprint"
        self.patch(self.app.commands, "call_pick_save", lambda d: str(out))
        self.go("#/lessons", "lessons")
        self.click("#exportAll")
        self.assertIn("Все уроки одним файлом", self.sheet())
        self.sheet_click("Сохранить…")
        self.assertTrue(self.wait_py(lambda: out.is_file()))
        self.assertGreaterEqual(len([n for n in zipfile.ZipFile(out).namelist() if n.startswith("lessons/")]), 3)

    # ---------------------------------------------------------------- печать и PDF
    def test_print_sheet_buttons(self):
        out = TMP / "cikly.pdf"
        pdf, printed = [], []
        self.patch(self.app.commands, "call_pick_save", lambda d: str(out))
        self.patch(self.app.window, "print_pdf", lambda path: pdf.append(path) or True)
        self.patch(self.app.window, "print_dialog", lambda: printed.append(1) or True)
        self.menu_pick("Печать или PDF…")
        text = self.sheet()
        for x in ("Размер текста", "Слайды и картинки", "Ответы к вопросам", "Код"):
            self.assertIn(x, text)
        self.js("[...document.querySelectorAll('.scrim .sheet .seg button')].find(b => b.textContent === 'Крупно').click()")
        self.sheet_click("Сохранить PDF…")
        self.assertTrue(self.wait_py(lambda: pdf == [str(out)]))
        self.assertTrue(self.wait_js("!document.querySelector('.scrim') && !/print-/.test(document.body.className)"))
        self.menu_pick("Печать или PDF…")
        self.sheet_click("Печать…")
        self.assertTrue(self.wait_py(lambda: printed == [1]))
        self.assertTrue(self.wait_js("!/print-/.test(document.body.className)"))

    # ---------------------------------------------------------------- план урока
    def test_plan_sheet_link_unlink(self):
        self.menu_pick("План урока…")
        text = self.sheet()
        self.assertIn("Онлайн 45", text)                                     # «Привязать к плану» — список планов
        self.assertIn("Сделать из этапов план", text)
        self.sheet_click("Онлайн 45")
        self.assertTrue(self.wait_py(lambda: self.store.get("A").plan_id == "P"))
        self.app.publish_now()
        self.app.lesson.publish()
        self.menu_pick("План урока…")
        text = self.sheet()
        self.assertIn("Открыть план «Онлайн 45»", text)
        self.sheet_click("Отвязать от плана")
        self.assertIn("Отвязать урок «Циклы» от плана «Онлайн 45»", self.sheet())
        self.sheet_click("Отвязать")
        self.assertTrue(self.wait_py(lambda: self.store.get("A").plan_id == ""))

    def test_plan_sheet_make_plan(self):
        n0 = len(self.store.plans())
        self.menu_pick("План урока…")
        self.sheet_click("Сделать из этапов план")
        self.assertTrue(self.wait_py(lambda: len(self.store.plans()) == n0 + 1))
        new = [p for p in self.store.plans() if p.id != "P"][0]
        self.app.unlink_plan(self.store.get("A"))
        self.app.delete_lesson(new)

    # ---------------------------------------------------------------- ответ нейросети
    def test_answer_sheet_adds_copy(self):
        before = [(b.id, b.text) for b in self.store.get("A").blocks]
        self.menu_pick("Обновить по ответу нейросети…")
        text = self.sheet()
        self.assertIn("Скопировать задание", text)
        self.sheet_click("Скопировать задание")
        from PySide6.QtGui import QGuiApplication
        self.assertTrue(self.wait_py(lambda: "markdown" in QGuiApplication.clipboard().text().lower()))
        self.js(f"{{ const t = document.querySelector('.scrim .sheet textarea'); t.value = {ANSWER!r}; t.dispatchEvent(new Event('input')); }}")
        self.sheet_click("Добавить урок")
        self.assertTrue(self.wait_py(lambda: any(x.title == "По ответу" for x in self.store.templates)))
        self.assertEqual([(b.id, b.text) for b in self.store.get("A").blocks], before)    # исходный не изменён
        new = next(x for x in self.store.templates if x.title == "По ответу")
        self.app.delete_lesson(new)

    def test_answer_empty_keeps_sheet(self):
        self.menu_pick("Обновить по ответу нейросети…")
        self.sheet()
        self.sheet_click("Добавить урок")
        pump(200)
        self.assertTrue(self.js("!!document.querySelector('.scrim .sheet textarea')"))     # пусто — лист не закрылся

    # ---------------------------------------------------------------- слайды и сценарий
    def test_slides_fill_picks_presentation(self):
        picked, filled = [], []
        self.patch(self.app.commands, "call_pick_files", lambda d: picked.append(d.get("purpose")) or [str(TMP / "deck.pdf")])
        self.patch(self.app.lesson, "fill_slides_from", lambda t, path: filled.append((t.id, path)) or True)
        self.open_lesson("E")
        self.menu_pick("Подставить слайды из презентации…")
        self.assertTrue(self.wait_py(lambda: filled == [("E", str(TMP / "deck.pdf"))]))
        self.assertEqual(picked, ["presentation"])

    def test_recognize_only_for_scenario(self):
        self.assertNotIn("Разложить по этапам (⏱ этапы, 🗣 реплики)", self.menu_labels())
        self.open_lesson("S")
        n0 = len(self.store.templates)
        self.menu_pick("Разложить по этапам (⏱ этапы, 🗣 реплики)")
        self.assertTrue(self.wait_py(lambda: len(self.store.templates) == n0 + 1))
        new = self.store.templates[self.store.templates.index(self.store.get("S")) + 1]
        self.assertEqual(sum(b.type == BLOCK_STAGE for b in new.blocks), 2)
        self.app.delete_lesson(new)

    def test_library_menu_same_items(self):
        self.go("#/lessons", "lessons")
        self.assertTrue(self.wait_js("!!document.querySelector('.lrow[data-id=A]')"))
        self.js("document.querySelector('.lrow[data-id=A]').dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, clientX: 200, clientY: 200}))")
        self.assertTrue(self.wait_js("!!document.querySelector('.pop .menu')"))
        labels = self.js("[...document.querySelectorAll('.pop .menu .mi .ml')].map(x => x.textContent)")
        self.assertEqual(labels[0], "Открыть")
        self.assertEqual(labels[1:], ["Переименовать", "Дублировать", "Экспорт…", "Печать или PDF…", "План урока…",
                                      "Обновить по ответу нейросети…", "Удалить…"])


# ================================================================ Task 15: листы окна — обновление, отчёт, запись, сбой

class WindowSheetsTest(AppPage):
    port = 18986
    templates = staticmethod(lessons)
    route = "#/lessons"

    def setUp(self):
        self.go("#/lessons", "lessons")
        self.opened: list[str] = []
        from autoprint import app_cmd
        self.patch(app_cmd, "open_url", lambda url: self.opened.append(url) or True)

    def tearDown(self):
        self.js("window.appUI.closePop(); document.querySelectorAll('.scrim').forEach(s => s.remove())")
        if self.app.record is not None:
            self.app.close_record()
        super().tearDown()

    def patch(self, obj, name, fn):
        old = getattr(obj, name)
        setattr(obj, name, fn)
        self.addCleanup(setattr, obj, name, old)

    def sheet(self) -> str:
        self.assertTrue(self.wait_js("!!document.querySelector('.scrim .sheet')"))
        return self.js("[...document.querySelectorAll('.scrim .sheet')].pop().textContent")

    def sheet_has(self, text: str, timeout: float = 5) -> bool:
        return self.wait_js(f"[...document.querySelectorAll('.scrim .sheet')].some(s => s.textContent.includes({text!r}))", timeout)

    def sheet_click(self, text: str):
        f = f"[...document.querySelectorAll('.scrim .sheet button')].filter(b => b.textContent.trim() === {text!r} && !b.disabled)"
        self.assertTrue(self.wait_js(f"{f}.length > 0"), text)
        self.js(f"{f}.pop().click()")

    def no_sheet(self) -> bool:
        return self.wait_js("!document.querySelector('.scrim .sheet')")

    # ---------------------------------------------------------------- обновление
    def release(self):
        from autoprint.updater import Release
        return Release("9.9.9", "v9.9.9", "AutoPrintCode 9.9.9", "## Что нового\n\n- Быстрее печать", "https://example.org/rel",
                       "", "2026-11-25")

    def test_update_sheet_buttons_by_state(self):
        up = self.app.updates
        rel = self.release()
        self.patch(up, "latest", rel)
        self.patch(up, "installable", lambda r: True)
        started = []
        self.patch(up, "download", lambda r: started.append(r.version))
        self.app.open_update_dialog()
        text = self.sheet()
        self.assertIn("Доступно обновление", text)
        self.assertIn("9.9.9", text)
        self.assertIn("Быстрее печать", text)
        self.sheet_click("Обновить и перезапустить")
        self.assertTrue(self.wait_py(lambda: started == ["9.9.9"]))
        up.downloading = True
        self.app.update_progress = {"stage": "Загрузка", "got": 1048576, "total": 4194304}
        self.app.publish_now()
        self.assertTrue(self.sheet_has("Отменить загрузку"))
        self.assertTrue(self.sheet_has("Загрузка: 1.0 МБ из 4.0 МБ"))
        up.downloading = False
        self.patch(up, "staged", (rel, Path(".")))
        self.app.update_progress = None
        self.app.publish_now()
        self.assertTrue(self.sheet_has("Перезапустить и обновить"))
        restarted = []
        self.patch(self.app, "install_update_and_restart", lambda: restarted.append(1))
        self.sheet_click("Перезапустить и обновить")
        self.assertTrue(self.wait_py(lambda: restarted == [1]))
        self.assertTrue(self.no_sheet())

    def test_update_sheet_manual_download_and_skip(self):
        up = self.app.updates
        self.patch(up, "latest", self.release())
        self.patch(up, "installable", lambda r: False)
        self.patch(up, "block_reason", lambda r: "В выпуске нет сборки для Windows.")
        self.app.open_update_dialog()
        self.assertTrue(self.sheet_has("В выпуске нет сборки"))
        self.sheet_click("Скачать…")
        self.assertTrue(self.wait_py(lambda: self.opened == ["https://example.org/rel"]))
        self.assertTrue(self.no_sheet())
        self.app.open_update_dialog()
        self.sheet()
        self.sheet_click("Пропустить эту версию")
        self.assertTrue(self.wait_py(lambda: self.app.settings.update_skip_version == "9.9.9"))
        self.assertTrue(self.no_sheet())
        self.app.settings.update_skip_version = ""

    # ---------------------------------------------------------------- сообщить об ошибке
    def test_report_sheet_preview_and_save(self):
        from autoprint.logs import LOG_FILE
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write("2026-11-25 10:00:00,000 CRITICAL MainThread autoprint: Необработанное исключение\n"
                    "Traceback (most recent call last):\n  File \"x.py\", line 1, in <module>\nValueError: boom\n")
        self.app.open_report()
        text = self.sheet()
        self.assertIn("Сообщить об ошибке", text)
        self.assertTrue(self.sheet_has("ValueError: boom"))                      # строка с последней ошибкой
        self.js("{ const t = document.querySelector('#repDesc'); t.value = 'Нажал Ctrl+F9 — строки съехали'; "
                "t.dispatchEvent(new Event('input', {bubbles: true})); }")
        self.assertTrue(self.wait_js("document.querySelector('#repPreview').textContent.includes('строки съехали')"))
        self.assertTrue(self.wait_js("document.querySelector('#repPreview').textContent.includes('hotkey_toggle')"))
        self.click("#repSettings")
        self.assertTrue(self.wait_js("!document.querySelector('#repPreview').textContent.includes('hotkey_toggle')"))
        out = TMP / "из-окна.zip"
        self.patch(self.app.commands, "call_pick_save", lambda d: str(out))
        self.sheet_click("Сохранить отчёт…")
        self.assertTrue(self.wait_py(lambda: out.is_file()))
        with zipfile.ZipFile(out) as z:
            self.assertTrue(any("строки съехали" in z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith(".md")))
        self.sheet_click("Открыть на GitHub")
        self.assertTrue(self.wait_py(lambda: len(self.opened) == 1))
        from urllib.parse import parse_qs, urlsplit
        body = parse_qs(urlsplit(self.opened[0]).query).get("body", [""])[0]
        self.assertIn("из-окна.zip", body)
        self.assertIn("строки съехали", body)
        self.sheet_click("Скопировать")
        from PySide6.QtGui import QGuiApplication
        self.assertTrue(self.wait_py(lambda: "строки съехали" in QGuiApplication.clipboard().text()))

    # ---------------------------------------------------------------- запись звука
    def fake_recorder(self):
        import test_record_flow as T
        from autoprint import record_flow
        self.patch(record_flow, "make_recorder", lambda parent=None: T.FakeRecorder(parent))
        return T

    def test_record_sheet_steps_and_close_ask(self):
        T = self.fake_recorder()
        self.app.commands.cmd_record_sound({})
        self.assertTrue(self.sheet_has("Записать звук клавиатуры"))
        self.assertTrue(self.wait_js("[...document.querySelectorAll('#recDevice option')].length === 2"))
        self.assertTrue(self.wait_py(lambda: self.app.record is not None and self.app.record.monitoring))
        self.assertTrue(self.wait_py(lambda: bool(self.app.hotkeys._bindings) is False))      # хоткеи сняты
        self.sheet_click("Далее")
        self.assertTrue(self.sheet_has("Обычные клавиши"))
        self.assertTrue(self.wait_js("[...document.querySelectorAll('.scrim .sheet button')].find(b => b.textContent.trim() === 'Далее').disabled"))
        T.FakeRecorder.next_samples = T.clicks(9)
        self.sheet_click("Начать запись")
        self.assertTrue(self.wait_py(lambda: self.app.record.recording == "key"))
        self.sheet_click("Стоп")
        self.assertTrue(self.sheet_has("Найдено: 9 ударов — хорошо"))
        self.assertTrue(self.wait_js("!![...document.querySelectorAll('.scrim .sheet button')].find(b => b.textContent.trim() === 'Далее' && !b.disabled)"))
        # закрыть с записями — спросить
        self.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
        self.assertTrue(self.sheet_has("Закрыть без сохранения? Записи пропадут."))
        self.sheet_click("Отмена")
        self.assertTrue(self.sheet_has("Найдено: 9 ударов"))
        self.assertIsNotNone(self.app.record)
        self.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
        self.assertTrue(self.sheet_has("Закрыть без сохранения?"))
        self.sheet_click("Закрыть")
        self.assertTrue(self.no_sheet())
        self.assertTrue(self.wait_py(lambda: self.app.record is None))
        self.assertTrue(self.wait_py(lambda: bool(self.app.hotkeys._bindings)))              # хоткеи вернулись

    def test_record_sheet_saves_style(self):
        T = self.fake_recorder()
        from autoprint import sounds
        self.app.commands.cmd_record_sound({})
        self.assertTrue(self.sheet_has("Микрофон"))
        self.sheet_click("Далее")
        T.FakeRecorder.next_samples = T.clicks(8)
        self.sheet_click("Начать запись")
        self.sheet_click("Стоп")
        self.sheet_click("Далее")
        self.assertTrue(self.sheet_has("Пробел"))
        self.sheet_click("Пропустить — возьмём обычные клавиши")
        self.assertTrue(self.sheet_has("Enter"))
        self.sheet_click("Пропустить — возьмём обычные клавиши")
        self.assertTrue(self.sheet_has("Назовите набор"))
        self.js("{ const t = document.querySelector('#recName'); t.value = 'Лист'; t.dispatchEvent(new Event('input', {bubbles: true})); }")
        self.sheet_click("Сохранить")
        self.assertTrue(self.no_sheet())
        self.assertTrue(self.wait_py(lambda: self.app.settings.sound_style.startswith("my_")))
        key = self.app.settings.sound_style
        self.assertEqual(sounds.available_styles()[key], "Своя: Лист")
        self.app.settings.sound_style = sounds.DEFAULT_STYLE
        self.app.on_setting_changed("sound_style")
        sounds.delete_custom(key)

    # ---------------------------------------------------------------- урок в эфире
    def test_open_other_while_live_sheet(self):
        """Идёт урок — открыть другой: лист с вопросом; «Отмена» ничего не трогает, «Завершить и открыть» — да."""
        a = self.app
        a.printer.set_focus("A")
        self.assertTrue(a.efir.launch_lesson(a.store.get("A"), start="", show=False))
        try:
            self.assertFalse(a.open_lesson("E"))
            self.assertTrue(self.sheet_has("Идёт урок «Циклы»"))
            self.sheet_click("Отмена")
            self.assertTrue(self.no_sheet())
            self.assertEqual(a.efir.live_lesson_id(), "A")
            self.assertFalse(a.open_lesson("E"))
            self.assertTrue(self.sheet_has("Завершить и открыть"))
            self.sheet_click("Завершить и открыть")
            self.assertTrue(self.wait_py(lambda: a.efir.live_lesson_id() == "" and a.printer.focus_id == "E"))
        finally:
            a.efir.stop_live()

    # ---------------------------------------------------------------- внутренняя ошибка
    def test_crash_sheet(self):
        self.app.show_crash("ValueError: boom")
        self.assertTrue(self.sheet_has("Внутренняя ошибка: ValueError: boom"))
        self.sheet_click("Сообщить об ошибке…")
        self.assertTrue(self.sheet_has("Что случилось?"))


class OldDialogsRemovedTest(unittest.TestCase):
    def test_old_dialogs_removed(self):
        ui = Path(storage.__file__).parent / "ui"
        for name in ("report_dialog.py", "record_dialog.py"):
            self.assertFalse((ui / name).exists(), name)
        self.assertNotIn("class UpdateDialog", (ui / "updates.py").read_text(encoding="utf-8"))


PDF_PROBE = r'''
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["AUTOPRINT_DATA"] = tempfile.mkdtemp(prefix="autoprint-pdf-")
sys.path.insert(0, sys.argv[1])
import PySide6.QtWebEngineWidgets  # noqa — до QApplication
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from autoprint.efir.server import BroadcastServer
from autoprint.storage import Settings
from autoprint.ui.app_window import AppWindow
qa = QApplication(sys.argv[:1])
class E: pass
class A:
    settings = Settings()
    efir = E()
srv = BroadcastServer(18978); srv.start(); A.efir.server = srv
w = AppWindow(A(), web=True)
res = {}
def go():
    res["ok"] = w.print_pdf(sys.argv[2], open_after=False)
    qa.quit()
w.ready.connect(lambda: QTimer.singleShot(300, go))
QTimer.singleShot(60000, qa.quit)
w.load(); qa.exec(); srv.stop()
print("pdf:", res.get("ok"))
'''


class PdfRealTest(unittest.TestCase):
    """«Сохранить PDF…» во встроенном браузере по-настоящему (offscreen, отдельный процесс, файл не открывается)."""

    def test_print_pdf_writes_file(self):
        import os
        import subprocess
        import sys
        out = TMP / "real.pdf"
        root = str(Path(__file__).resolve().parent.parent)
        r = subprocess.run([sys.executable, "-c", PDF_PROBE, root, str(out)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.assertIn("pdf: True", r.stdout, r.stdout + r.stderr[-2000:])
        self.assertTrue(out.is_file())
        self.assertEqual(out.read_bytes()[:5], b"%PDF-")
        # 1.1: поля страницы (12 мм) — белые и в тёмной теме окна, а не чёрная рамка вокруг урока
        from PySide6.QtCore import QSize
        from PySide6.QtPdf import QPdfDocument
        doc = QPdfDocument()
        doc.load(str(out))
        img = doc.render(0, QSize(420, 594))
        for x, y in ((6, 6), (210, 4), (414, 300), (210, 590)):
            c = img.pixelColor(x, y)                      # не закрашено (прозрачно) — белая бумага; иначе — почти белое
            self.assertTrue(c.alpha() < 10 or min(c.red(), c.green(), c.blue()) > 240,
                            f"поле страницы ({x},{y}) = {c.name()} α={c.alpha()}")


class ExportModuleRemovedTest(unittest.TestCase):
    def test_old_export_dialog_removed(self):
        self.assertFalse((Path(storage.__file__).parent / "ui" / "export_package.py").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
