"""«Новый урок» без страницы: свой план, разбор вставленного, задание нейросети (по теме, по файлу, разбор кода),
фоновые работы. Claude Code и Codex читают сам файл материала.

    .venv\\Scripts\\python.exe tests\\test_wizard_core.py
"""
from __future__ import annotations

import http.server
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import quiet  # noqa: E402,F401

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
quiet.patch()

from autoprint import ai, lesson_ai as L, wizard  # noqa: E402
from autoprint.storage import BLOCK_CODE, BLOCK_IMAGE, BLOCK_STAGE, Block, Settings, Template  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="autoprint-wizard-"))
CODE = "grades = [5, 4, 3, 5]\naverage = sum(grades) / len(grades)\nprint(average)"


def pump(ms: int = 30) -> None:
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def plan90() -> Template:
    return wizard.plan_from_spec("Онлайн 90", [
        {"title": "Приветствие", "minutes": 5}, {"title": "Теория", "minutes": 20},
        {"title": "Перерыв", "minutes": 10, "kind": "break"}, {"title": "Практика", "minutes": 30},
        {"title": "Зарядка", "minutes": 5, "kind": "exercise", "exercise": "Глаза"}])


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

```python
def f(x):
    return x
```

## Перерыв · 10 мин · перерыв

## Практика · 30 мин

> [!task]
> Напишите функцию.

## Зарядка · 5 мин · зарядка: Глаза
~~~
"""


class FakeJob:
    def __init__(self):
        self.cancel_event = threading.Event()
        self.log = []

    @property
    def cancelled(self):
        return self.cancel_event.is_set()

    def progress(self, phase, chars=0, preview=""):
        self.log.append((phase, chars))

    def status(self, who):
        self.log.append(("who", who))


class PlanAndPasteTest(unittest.TestCase):
    def test_plan_from_spec_kinds_and_minutes(self):
        p = wizard.plan_from_spec("  Мой план ", [{"title": "Начало", "minutes": "7"}, {"title": "", "minutes": 900},
                                                  {"title": "Отдых", "minutes": 10, "kind": "break"},
                                                  {"title": "Зарядка", "minutes": 3, "kind": "exercise", "exercise": "Шея"},
                                                  {"title": "Странный", "minutes": -4, "kind": "magic"}])
        self.assertEqual(p.kind, "plan")
        self.assertEqual(p.title, "Мой план")
        st = [(b.title, b.minutes, b.stage_kind, b.exercise) for b in p.blocks]
        self.assertEqual(st, [("Начало", 7, "", ""), ("Этап", 600, "", ""), ("Отдых", 10, "break", ""),
                              ("Зарядка", 3, "exercise", "Шея"), ("Странный", 0, "", "")])
        self.assertTrue(all(b.type == BLOCK_STAGE for b in p.blocks))
        with self.assertRaises(ValueError):
            wizard.plan_from_spec("Пустой", [])
        self.assertEqual(wizard.plan_from_spec("", [{"title": "А", "minutes": 5}]).title, "Новый план")

    def test_paste_detects_answer_md_notebook_code(self):
        r = wizard.paste_parse(ANSWER)
        self.assertEqual(r.kind, "ответ нейросети")
        self.assertIn("«Функции» — 5 этапов", r.summary)
        self.assertIn("Фото по ссылкам: 1", r.summary)
        p = plan90()
        r = wizard.paste_parse(ANSWER, plan=p)                              # по плану — этапы связаны с планом
        self.assertEqual(r.template.plan_id, p.id)
        self.assertIn("по плану «Онлайн 90»", r.summary)
        md = "# Тема\n\nТекст\n\n```python\nprint(1)\n```\n"
        self.assertEqual(wizard.paste_parse(md).kind, "Markdown с блоками кода")
        nb = json.dumps({"cells": [{"cell_type": "code", "source": ["print(2)"]}], "metadata": {}, "nbformat": 4})
        self.assertEqual(wizard.paste_parse(nb).kind, "тетрадка Jupyter")
        r = wizard.paste_parse("function double(a) {\n  return a * 2;\n}")
        self.assertTrue(r.kind.startswith("код"), r.kind)
        self.assertIn("javascript", r.kind)
        self.assertEqual(r.template.code_blocks()[0].lang, "javascript")
        with self.assertRaises(ValueError):
            wizard.paste_parse("   ")

    def test_paste_code_answer_steps_style(self):
        r = wizard.paste_parse("Вот занятие:\n```json\n" + L._EXAMPLES[L.STYLE_STEPS] + "\n```")
        self.assertIn("шагов: 3", r.summary)
        self.assertEqual(r.style, L.STYLE_STEPS)                             # печать «По шагам» включится


class PromptTest(unittest.TestCase):
    def test_topic_only_prompt_has_topic_plan_class(self):
        opt = L.Options(style=L.STYLE_SCENARIO, cls="5 класс", topic="Циклы for")
        text = wizard.copy_prompt("lesson", opt, plan=plan90(), exercises=["Глаза"])
        for part in ("Циклы for", "5 класс", "## Теория · 20 мин", "зарядка: Глаза", "видео учитель выберет на уроке", "~~~markdown"):
            self.assertIn(part, text)
        self.assertIn("составь урок по теме", text.lower())                   # без материала — по теме
        no_plan = wizard.copy_prompt("lesson", L.Options(style=L.STYLE_SCENARIO, minutes=45, break_min=5, topic="Дроби"))
        self.assertIn("УРОК: 45 мин, перерыв 5 мин", no_plan)

    def test_code_style_prompt(self):
        opt = wizard.code_options({"style": "steps", "task": True, "explain": True, "keep": True, "detail": "short"}, CODE)
        self.assertEqual(opt.style, L.STYLE_STEPS)
        text = wizard.copy_prompt("code", opt, material=CODE)
        self.assertIn(CODE, text)
        self.assertIn(L.FORMAT, text)
        self.assertIn("ПОШАГОВОЙ", text)
        big = "\n".join(f"value_{i} = compute({i})" for i in range(L.BIG_LINES + 30))
        bopt = wizard.code_options({"style": "steps"}, big)
        self.assertTrue(bopt.marks)                                         # большой код — разметка строк
        self.assertIn("1| value_0", wizard.copy_prompt("code", bopt, material=big))


class CliFilesTest(unittest.TestCase):
    def test_cli_args_allow_read_with_files(self):
        c = ai.config(Settings(), "claudeCli")
        args = ai._cli_args(c, "sys.txt", files=True)
        i = args.index("--tools")
        self.assertEqual(args[i + 1], "Read")
        self.assertEqual(ai._cli_args(c, "sys.txt")[i + 1], "")                 # без файлов — без инструментов
        cx = ai.config(Settings(), "codexCli")
        a2 = ai._cli_args(cx, "sys.txt", files=True)
        self.assertEqual(a2[a2.index("-s") + 1], "read-only")

    def test_cli_copies_files_into_request_folder(self):
        src = TMP / "методичка.pdf"
        src.write_bytes(b"%PDF-1.4 test")
        seen = {}

        class FakeProc:
            def __init__(self, args, stdin=None, stdout=None, stderr=None, creationflags=0, cwd=None):
                seen["cwd"], seen["args"] = cwd, args
                seen["files"] = sorted(p.name for p in Path(cwd).iterdir())
                out = json.dumps({"type": "result", "result": "готово", "is_error": False}) + "\n"
                import io
                self.stdin = io.BytesIO()
                self.stdin.close = lambda: seen.setdefault("stdin", self.stdin.getvalue().decode("utf-8"))
                self.stdout = io.BytesIO(out.encode())
                self.stderr = io.BytesIO(b"")
                self.returncode = 0
                self.pid = 1

            def poll(self):
                return 0
        import subprocess
        old = subprocess.Popen
        subprocess.Popen = FakeProc
        old_path = ai.cli_path
        ai.cli_path = lambda p: "claude.exe"
        try:
            c = ai.config(Settings(), "claudeCli")
            text = ai.chat(c, "система", "тема: функции", 30, files=[str(src)])
        finally:
            subprocess.Popen = old
            ai.cli_path = old_path
        self.assertEqual(text, "готово")
        self.assertEqual(seen["files"], ["методичка.pdf"])                       # копия — в папке запроса
        self.assertNotEqual(Path(seen["cwd"]), Path(ai._empty_dir()))
        self.assertIn("Файлы материала лежат в текущей папке: методичка.pdf", seen.get("stdin", ""))
        self.assertFalse(Path(seen["cwd"]).exists())                              # после ответа папка убрана
        self.assertTrue(src.exists())                                             # исходный файл не тронут


class LessonTaskTest(unittest.TestCase):
    def test_lesson_task_links_plan(self):
        p = plan90()
        calls = []
        old = ai.ask

        def fake(settings, system, user, cancel=None, on_status=None, on_progress=None, files=()):
            calls.append((system, user, list(files)))
            if on_progress:
                on_progress("write", 100, "…")
            return ANSWER, "Тест"
        ai.ask = fake
        try:
            opt = L.Options(style=L.STYLE_SCENARIO, topic="Функции в Python", cls="7 класс")
            fn = wizard.lesson_task(Settings(), opt, plan=p, exercises=["Глаза"])
            job = FakeJob()
            res = fn(job)
        finally:
            ai.ask = old
        t = res["template"]
        self.assertEqual(t.plan_id, p.id)
        self.assertEqual([b.link for b in t.blocks if b.type == BLOCK_STAGE], [b.id for b in p.blocks])
        self.assertEqual(t.title, "Функции в Python")                            # тема учителя — название урока
        self.assertIn("Функции в Python", calls[0][0])
        self.assertIn(("write", 100), job.log)
        self.assertTrue(any(b.type == BLOCK_IMAGE and "://" in b.text for b in t.blocks))

    def test_lesson_task_cancelled(self):
        old = ai.ask

        def slow(settings, system, user, cancel=None, **kw):
            cancel.wait(5)
            raise ai.Cancelled("Отменено.")
        ai.ask = slow
        try:
            job = FakeJob()
            fn = wizard.lesson_task(Settings(), L.Options(style=L.STYLE_SCENARIO, topic="x"))
            th = threading.Thread(target=lambda: self.assertRaises(ai.Cancelled, fn, job))
            th.start()
            job.cancel_event.set()
            th.join(5)
            self.assertFalse(th.is_alive())
        finally:
            ai.ask = old

    def test_backup_gets_file_text_when_agent_fails(self):
        """Claude Code читал файл материала и не ответил — запасная (обычный сервер) получает текст файла, а не одну тему."""
        import tempfile
        d = Path(tempfile.mkdtemp())
        f = d / "методичка.md"
        f.write_text("# Циклы\n\nУникальная строка материала 7319.", encoding="utf-8")
        s = Settings()
        s.ai_provider, s.ai_backup_provider, s.ai_backup_enabled = "claudeCli", "custom", True
        s.ai_urls["custom"], s.ai_models["custom"] = "http://127.0.0.1:9", "m"
        calls = []

        def one(settings, c, system, user, cancel, progress, files=()):
            calls.append((c.provider.id, system, user, tuple(files)))
            if c.provider.kind == "cli":
                raise ai.AIError("агент не ответил")
            return ANSWER
        old_one, old_problem = ai._ask_one, ai.problem
        ai._ask_one = one
        ai.problem = lambda c: None
        try:
            m = wizard.gather([str(f)], "", agent=True)
            self.assertEqual(m.files, [str(f)])
            opt = L.Options(style=L.STYLE_SCENARIO, topic="Циклы")
            res = wizard.lesson_task(s, opt, material=m.text, files=m.files, pdf=m.pdf)(FakeJob())
        finally:
            ai._ask_one, ai.problem = old_one, old_problem
        self.assertEqual([c[0] for c in calls], ["claudeCli", "custom"])
        self.assertEqual(calls[1][3], ())                                  # запасной файлы не передаются…
        self.assertIn("Уникальная строка материала 7319", calls[1][2])     # …а их текст — в запросе
        self.assertIsNotNone(res["template"])

    def test_code_task_with_fake_server(self):
        """Своя OpenAI-совместимая нейросеть (подставной сервер) разбирает код по шагам."""
        class Fake(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                body = json.dumps({"choices": [{"message": {"content": L._EXAMPLES[L.STYLE_STEPS]}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        s = Settings()
        s.ai_provider = "custom"
        s.ai_urls["custom"] = f"http://127.0.0.1:{srv.server_address[1]}"
        s.ai_models["custom"] = "teacher-7b"
        try:
            opt = wizard.code_options({"style": "steps"}, CODE)
            res = wizard.lesson_task(s, opt, material=CODE, what="code")(FakeJob())
        finally:
            srv.shutdown()
        self.assertEqual(res["style"], L.STYLE_STEPS)
        self.assertTrue(any(len(set(b.steps)) > 1 for b in res["template"].code_blocks()))


class JobsTest(unittest.TestCase):
    def test_jobs_done_error_cancel(self):
        from autoprint.jobs import Jobs
        jobs = Jobs()
        got = []
        j1 = jobs.start("ai", lambda job: (job.progress("write", 5, "x"), 42)[1], got.append, "Урок")
        self.assertTrue(self.wait(lambda: got == [42]))
        self.assertTrue(jobs.get(j1).done and not jobs.get(j1).error)

        def boom(job):
            raise ai.AIError("нет связи")
        j2 = jobs.start("ai", boom, got.append, "Урок 2")
        self.assertTrue(self.wait(lambda: jobs.get(j2).done))
        self.assertEqual(jobs.get(j2).error, "нет связи")

        def wait_cancel(job):
            job.cancel_event.wait(5)
            return "поздно"
        j3 = jobs.start("ai", wait_cancel, got.append, "Урок 3")
        jobs.cancel(j3)
        self.assertTrue(self.wait(lambda: jobs.get(j3).done))
        pump(200)
        self.assertEqual(jobs.get(j3).error, "Отменено.")
        self.assertEqual(got, [42])                                          # отменённая не добавила ничего
        st = {x["id"]: x for x in jobs.state()}
        self.assertEqual(st[j2]["error"], "нет связи")
        for k in ("id", "kind", "title", "phase", "chars", "preview", "seconds", "done", "error"):
            self.assertIn(k, st[j2])

    def test_skip_finishes_with_result(self):
        from autoprint.jobs import Jobs
        jobs = Jobs()
        got = []

        def fetch(job):
            job.cancel_event.wait(5)
            return "со ссылками"
        jid = jobs.start("photos", fetch, got.append, "Картинки")
        jobs.skip(jid)
        self.assertTrue(self.wait(lambda: got == ["со ссылками"]))
        self.assertEqual(jobs.get(jid).error, "")

    def wait(self, pred, timeout=5):
        end = time.time() + timeout
        while time.time() < end:
            pump(20)
            if pred():
                return True
        return False


if __name__ == "__main__":
    unittest.main(verbosity=2)
