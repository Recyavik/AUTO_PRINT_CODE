"""«Новый урок» в окне: шаг 1 — план (карточки, «Без плана», «Свой план», «Уже есть файл урока?»), шаг 2 — тема и
откуда взять текст («Составит нейросеть», «Вставить текст», «Заполню сам»), ход работы нейросети и картинок.

    .venv\\Scripts\\python.exe tests\\test_app_wizard.py
"""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from apphelp import AppPage, make_app, note, pump, stage  # noqa: F401

from autoprint import ai, app_state
from autoprint.storage import BLOCK_IMAGE, BLOCK_STAGE, Template

TMP = Path(tempfile.mkdtemp(prefix="autoprint-wizpage-"))

ANSWER = """Вот урок:

~~~markdown
---
title: Функции
---

## Приветствие · 5 мин

> [!say]
> Здравствуйте!

## Теория · 20 мин

![Кот у ноутбука](https://ex.org/cat.png)

## Практика · 30 мин

> [!task]
> Напишите функцию.
~~~
"""


def lessons() -> list[Template]:
    p1 = Template("Онлайн 45", [stage("Начало", 10, id="a1"), stage("Практика", 35, id="a2")], id="P1", kind="plan")
    p2 = Template("Онлайн 90", [stage("Приветствие", 5, id="b1"), stage("Теория", 20, id="b2"),
                                stage("Перерыв", 10, id="b3", stage_kind="break"), stage("Практика", 30, id="b4")],
                  id="P2", kind="plan")
    return [Template("Старый урок", [stage("А", 5, id="z1"), note("x", id="zn")], id="L0"), p1, p2]


class WizardTest(AppPage):
    port = 18974
    templates = staticmethod(lessons)
    route = "#/lessons"

    def setUp(self):
        s = self.app.settings
        s.lesson_plan, s.ai_provider = "P2", ""
        app_state._CLI = {"claude": False, "codex": False}
        self.app.publish_now()
        self.js("location.hash = '#/lessons'")
        self.assertTrue(self.wait_js("document.body.dataset.view === 'lessons'"))

    def tearDown(self):
        for j in list(self.app.jobs.items):
            self.app.jobs.cancel(j.id)
            self.app.jobs.dismiss(j.id)
        app_state._CLI = None
        super().tearDown()

    def patch(self, obj, name, fn):
        old = getattr(obj, name)
        setattr(obj, name, fn)
        self.addCleanup(setattr, obj, name, old)

    def step2(self, plan="P2"):
        self.go(f"#/new/text?plan={plan}", "wizard")
        self.assertTrue(self.wait_js("!!document.querySelector('#topic')"))

    def source(self, src):
        self.click(f".wsrc[data-src={src}]")
        self.assertTrue(self.wait_js(f"document.querySelector('.wsrc[data-src={src}]').getAttribute('aria-pressed') === 'true'"))

    def set_value(self, sel, value):
        self.js(f"{{ const e = document.querySelector({sel!r}); e.value = {value!r}; e.dispatchEvent(new Event('input', {{bubbles: true}})); }}")

    def new_ids(self, before):
        return [t.id for t in self.store.templates if t.id not in before]

    # ---------------------------------------------------------------- шаг 1
    def test_step1_cards_and_default_plan(self):
        self.go("#/new", "wizard")
        self.assertTrue(self.wait_js("document.querySelectorAll('#planCards .wplan').length === 3"))     # 2 плана + «Без плана»
        self.assertEqual(self.js("document.querySelector('.wplan[aria-pressed=true]').dataset.id"), "P2")
        self.assertIn("Теория", self.js("document.querySelector('.wplan[data-id=P2]').textContent"))
        self.assertTrue(self.js("!!document.querySelector('#ownPlan') && !!document.querySelector('#pickLessonFile')"))
        self.assertEqual(self.js("document.querySelector('.wsteps .on').textContent.trim()"), "1План")
        self.click(".wplan[data-id=P1]")
        self.click("#wizNext")
        self.assertTrue(self.wait_js("location.hash === '#/new/text?plan=P1'"))

    def test_own_plan_subflow_saves_and_selects(self):
        self.go("#/new", "wizard")
        self.click("#ownPlan")
        self.assertTrue(self.wait_js("location.hash === '#/new/plan' && !!document.querySelector('#planTitle')"))
        self.set_value("#planTitle", "Мой план")
        self.click("#planStart button[data-value=pair90]")
        self.assertTrue(self.wait_js("document.querySelectorAll('#planStages .pstage').length === 3"))
        self.set_value("#planStages .pstage:first-child .pmins", "40")
        self.click("#addStage")
        self.assertTrue(self.wait_js("document.querySelectorAll('#planStages .pstage').length === 4"))
        self.js("{ const s = document.querySelector('#planStages .pstage:last-child .pkind'); s.value = 'exercise'; s.dispatchEvent(new Event('change', {bubbles: true})); }")
        self.assertTrue(self.wait_js("document.querySelector('#planTotal').textContent.includes('1 ч 40 мин')"))
        self.click("#savePlan")
        self.assertTrue(self.wait_py(lambda: any(t.title == "Мой план" for t in self.store.plans())))
        p = next(t for t in self.store.plans() if t.title == "Мой план")
        self.assertEqual([(b.minutes, b.stage_kind) for b in p.blocks], [(40, ""), (10, "break"), (45, ""), (5, "exercise")])
        self.assertTrue(self.wait_js(f"location.hash === '#/new' && document.querySelector('.wplan[aria-pressed=true]') "
                                     f"&& document.querySelector('.wplan[aria-pressed=true]').dataset.id === {p.id!r}"))
        self.app.delete_lesson(p)

    def test_import_file_skips_step2(self):
        md = TMP / "урок.md"
        md.write_text("# Импортный\n\nТекст урока\n\n```python\nprint(1)\n```\n", encoding="utf-8")
        self.patch(self.app.commands, "call_pick_files", lambda d: [str(md)])
        before = {t.id for t in self.store.templates}
        self.go("#/new", "wizard")
        self.click("#pickLessonFile")
        self.assertTrue(self.wait_py(lambda: len(self.new_ids(before)) == 1))
        nid = self.new_ids(before)[0]
        self.assertTrue(self.wait_js(f"location.hash === '#/lesson/{nid}'"))
        self.app.delete_lesson(self.store.get(nid))

    # ---------------------------------------------------------------- шаг 2
    def test_no_plan_shows_minutes_and_break(self):
        self.step2("none")
        self.assertTrue(self.js("!!document.querySelector('#minutes') && !!document.querySelector('#breakMin')"))
        self.assertEqual(self.js("document.querySelector('#minutes').value"), str(self.app.settings.lesson_minutes))
        self.step2("P2")
        self.assertFalse(self.js("!!document.querySelector('#minutes')"))
        self.assertIn("Онлайн 90", self.js("document.querySelector('#planLine').textContent"))
        self.assertEqual(self.js("document.activeElement && document.activeElement.id"), "topic")
        self.assertEqual(self.js("document.querySelector('.wsteps .on').textContent.trim()"), "2Тема и текст")

    def test_ai_card_shows_who_and_use_cli(self):
        app_state._CLI = {"claude": True, "codex": False}
        self.app.publish_now()
        self.step2()
        self.source("ai")
        self.assertTrue(self.wait_js("!!document.querySelector('#useClaude') && !document.querySelector('#useCodex')"))
        self.assertIn("Использовать Claude Code (по подписке)", self.js("document.querySelector('#useClaude').textContent"))
        self.patch(ai, "cli_path", lambda p: "claude.exe")
        self.click("#useClaude")
        self.assertTrue(self.wait_py(lambda: self.app.settings.ai_provider == "claudeCli"))
        self.assertTrue(self.wait_js("document.querySelector('#aiWho') && document.querySelector('#aiWho').textContent.includes('Claude')"))
        self.assertIn("Сменить", self.js("document.querySelector('#aiWho').textContent"))

    def test_ai_not_connected_offers_settings(self):
        self.step2()
        self.source("ai")
        self.assertTrue(self.wait_js("!!document.querySelector('#connectAi')"))
        self.click("#connectAi")
        self.assertTrue(self.wait_js("location.hash.startsWith('#/settings/ai')"))

    def test_paste_card_summary_line(self):
        self.step2()
        self.source("paste")
        self.set_value("#pasteText", ANSWER)
        self.assertTrue(self.wait_js("document.querySelector('#pasteSummary').textContent.includes('Фото по ссылкам: 1')", 6))
        self.assertIn("по плану «Онлайн 90»", self.js("document.querySelector('#pasteSummary').textContent"))

    def test_paste_js_code_creates_lesson(self):
        self.step2("none")
        self.source("paste")
        self.set_value("#pasteText", "function double(a) {\n  return a * 2;\n}")
        self.assertTrue(self.wait_js("document.querySelector('#pasteSummary').textContent.includes('javascript')", 6))
        before = {t.id for t in self.store.templates}
        self.click("#createLesson")
        self.assertTrue(self.wait_py(lambda: len(self.new_ids(before)) == 1))
        t = self.store.get(self.new_ids(before)[0])
        self.assertEqual(t.code_blocks()[0].lang, "javascript")
        self.app.delete_lesson(t)

    def test_manual_creates_and_opens(self):
        self.step2("P2")
        self.set_value("#topic", "Дроби")
        self.source("manual")
        before = {t.id for t in self.store.templates}
        self.click("#createLesson")
        self.assertTrue(self.wait_py(lambda: len(self.new_ids(before)) == 1))
        t = self.store.get(self.new_ids(before)[0])
        self.assertEqual((t.title, t.plan_id), ("Дроби", "P2"))
        self.assertEqual(len([b for b in t.blocks if b.type == BLOCK_STAGE]), 4)
        self.assertTrue(self.wait_js(f"location.hash === '#/lesson/{t.id}'"))
        self.app.delete_lesson(t)

    def test_ai_create_with_answer(self):
        """Подключённая нейросеть (подменена ответом) — урок по плану создаётся и открывается."""
        s = self.app.settings
        s.ai_provider = "custom"
        s.ai_urls["custom"] = "http://127.0.0.1:9"
        s.ai_models["custom"] = "m"
        seen = []

        def fake(settings, system, user, cancel=None, on_status=None, on_progress=None, files=()):
            seen.append(system)
            return ANSWER, "Своё"
        self.patch(ai, "ask", fake)
        self.patch(self.app, "fetch_images", lambda t, cancel=None, progress=None, **kw: [])
        self.app.publish_now()
        self.step2("P2")
        self.set_value("#topic", "Функции в Python")
        self.source("ai")
        before = {t.id for t in self.store.templates}
        self.click("#createLesson")
        self.assertTrue(self.wait_py(lambda: len(self.new_ids(before)) == 1, 8))
        t = self.store.get(self.new_ids(before)[0])
        self.assertEqual((t.title, t.plan_id), ("Функции в Python", "P2"))
        self.assertIn("Функции в Python", seen[0])
        self.app.delete_lesson(t)

    # ---------------------------------------------------------------- работа в фоне
    def test_job_progress_and_cancel(self):
        done = []

        def fn(job):
            job.progress("write", 120, "хвост ответа")
            job.cancel_event.wait(10)
            return None
        jid = self.app.jobs.start("ai", fn, done.append, "Урок «Тест»")
        self.step2()
        sel = f"#jobs .job[data-id={jid!r}]"
        self.assertTrue(self.wait_js(f"!!document.querySelector({sel!r}) && document.querySelector({sel!r}).textContent.includes('пишет — 120 знаков')"))
        self.assertIn("хвост ответа", self.js(f"document.querySelector({sel!r}).textContent"))
        self.click(f"{sel} [data-act=cancel]")
        self.assertTrue(self.wait_py(lambda: self.app.jobs.get(jid) is not None and self.app.jobs.get(jid).error == "Отменено."))
        pump(300)
        self.assertEqual(done, [])

    def test_job_survives_navigation(self):
        ev = threading.Event()
        jid = self.app.jobs.start("ai", lambda job: (job.progress("think", 3), ev.wait(10))[1], lambda r: None, "Урок «Долгий»")
        self.addCleanup(ev.set)
        self.step2()
        self.assertTrue(self.wait_js(f"!!document.querySelector('#jobs .job[data-id={jid}]')"))
        self.go("#/lessons", "lessons")
        self.assertTrue(self.wait_js(f"!!document.querySelector('.libjobs .job[data-id={jid}]')"))     # и в «Уроках»
        self.step2()
        self.assertTrue(self.wait_js(f"document.querySelector('#jobs .job[data-id={jid}]').textContent.includes('думает')"))

    def test_photo_fetch_skip(self):
        started = []

        def slow(t, cancel=None, progress=None, **kw):
            started.append(1)
            if progress:
                progress(0, 1)
            cancel.wait(10)
            return ["Не скачалось: 1 — эти картинки покажутся из интернета."]
        self.patch(self.app, "fetch_images", slow)
        self.step2("none")
        self.source("paste")
        self.set_value("#pasteText", ANSWER)
        self.assertTrue(self.wait_js("document.querySelector('#pasteSummary').textContent.includes('Фото')", 6))
        before = {t.id for t in self.store.templates}
        self.click("#createLesson")
        self.assertTrue(self.wait_py(lambda: bool(started)))
        self.assertTrue(self.wait_js("!!document.querySelector('#jobs .job [data-act=skip]')"))
        self.assertEqual(self.new_ids(before), [])                                  # пока качаются — урока нет
        self.click("#jobs .job [data-act=skip]")
        self.assertTrue(self.wait_py(lambda: len(self.new_ids(before)) == 1))
        t = self.store.get(self.new_ids(before)[0])
        self.assertTrue(any(b.type == BLOCK_IMAGE and b.text.startswith("https://") for b in t.blocks))
        self.app.delete_lesson(t)


class QuitTest(unittest.TestCase):
    def test_quit_cancels_jobs(self):
        a = make_app(lessons(), 18973)
        ev = threading.Event()
        jid = a.jobs.start("ai", lambda job: job.cancel_event.wait(10), lambda r: None, "Урок")
        try:
            a._quitting = True
            a.shutdown()
            self.assertTrue(a.jobs.get(jid).cancel_event.is_set())
            self.assertEqual(a.jobs.get(jid).error, "Отменено.")
        finally:
            ev.set()
            a.window.hide()
            pump()


class OldDialogsRemovedTest(unittest.TestCase):
    def test_import_dialogs_removed(self):
        from autoprint import storage
        ui = Path(storage.__file__).parent / "ui"
        self.assertFalse((ui / "import_dialog.py").exists())
        self.assertFalse((ui / "import_lesson.py").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
