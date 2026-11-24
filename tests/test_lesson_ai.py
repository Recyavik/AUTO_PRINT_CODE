"""Занятие от нейросети: промпт, разбор ответа, распознавание вставленного текста и подключение нейросети
(на подставном локальном сервере — без интернета и ключей).

    python tests/test_lesson_ai.py
"""
from __future__ import annotations

import http.server
import json
import os
import sys
import tempfile
import textwrap
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["AUTOPRINT_DATA"] = tempfile.mkdtemp(prefix="autoprint-lessonai-")

from autoprint import ai, lesson_ai as L  # noqa: E402
from autoprint import steps as S  # noqa: E402
from autoprint.importers import guess_lang, parse_pasted  # noqa: E402
from autoprint.storage import BLOCK_CODE, Settings, Template, TemplateStore  # noqa: E402

failed: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {name}{' — ' + extra if extra else ''}")
    if not ok:
        failed.append(name)


CODE = "import statistics\n\ngrades = [5, 4, 3]\naverage = sum(grades) / len(grades)\nprint(average)"


def test_prompt() -> None:
    for style in L.STYLES:
        p = L.build_prompt(CODE, L.Options(style=style))
        if style == L.STYLE_SCENARIO:        # 0.12: урок — в Markdown, как в своём чате
            check(f"промпт «{L.STYLES[style]}»: формат урока в Markdown, пример и материал",
                  "~~~markdown" in p and CODE in p and "Пример ответа" in p and "## Название этапа · 10 мин" in p)
            continue
        check(f"промпт «{L.STYLES[style]}»: правила стиля, формат, пример и материал",
              L.FORMAT in p and CODE in p and L._STYLE_RULES[style].split("\n")[0] in p and "Пример ответа" in p)
    p = L.instruction(L.Options(keep_code=True, task=False, explain=False))
    check("промпт: «код не меняй», без условия и пояснений — сказано явно",
          "Код НЕ МЕНЯЙ" in p and "Блоков \"explain\" не добавляй" in p and "условие задачи" not in p.lower()
          .split("пример ответа")[0].replace("если в материале есть условие задачи", ""))


def test_parse() -> None:
    for style, example in L._EXAMPLES.items():
        r = L.parse_lesson(example)
        check(f"пример из промпта «{L.STYLES[style]}» разбирается", bool(r.template.code_blocks()), r.summary)
    r = L.parse_lesson(L._EXAMPLES[L.STYLE_STEPS])
    code = r.template.code_blocks()[0]
    check("по шагам: import наверху с шагом 3, номера 1..3 по строкам",
          code.text.split("\n")[0] == "import statistics" and code.steps[0] == 3 and sorted(set(code.steps)) == [1, 2, 3],
          f"{code.steps}")
    lines = S.analyze(code.text, code.steps, code.lang, True)
    plan_ok = [ch.anchor for ch in S.plan(lines, 3)] == [0, 2] or len(S.plan(lines, 3)) == 2
    check("по шагам: шаг 3 печатается двумя кусками (наверх и вниз)", plan_ok)
    chatty = "Конечно! Вот занятие:\n```json\n" + L._EXAMPLES[L.STYLE_PARTS].replace("]}", "],}") + "\n```\nУдачи!"
    r = L.parse_lesson(chatty)
    check("ответ с пояснениями вокруг, ```json и лишней запятой — разбирается",
          len(r.template.code_blocks()) == 2 and r.template.title == "Чётные числа")
    for bad, why in (("просто текст без json", "нет JSON"), ('{"title": "x"}', "нет blocks"),
                     ('{"blocks": [{"type": "explain", "text": "a"}]}', "нет кода")):
        try:
            L.parse_lesson(bad)
            check(f"ошибка: {why}", False, "исключения нет")
        except L.LessonError as e:
            check(f"ошибка: {why} — понятное сообщение", bool(str(e)))
    r = L.parse_lesson('{"blocks": [{"type": "code", "lang": "python", "lines": [[5, "a = 1"], [9, "b = 2"]]}]}')
    check("номера шагов выравниваются (5, 9 → 1, 2) с предупреждением",
          r.template.code_blocks()[0].steps == [1, 2] and r.warnings, str(r.warnings))
    r = L.parse_lesson('{"blocks": [{"type": "code", "code": "x = 1"}, {"type": "weird", "text": "t"}]}')
    check("неизвестный тип блока → текст с предупреждением", len(r.template.blocks) == 2 and r.warnings)


def test_code_changes() -> None:
    commented = ("# берём модуль\nimport statistics\n\n# оценки\ngrades = [5, 4, 3]  # список\n"
                 "average = sum(grades) / len(grades)\nprint(average)")
    r = L.parse_lesson(json.dumps({"blocks": [{"type": "code", "lang": "python", "code": commented}]}))
    check("код с добавленными комментариями — «не изменён»", L.code_changes(CODE, r) == [])
    changed = commented.replace("sum(grades)", "sum(grades) + 1")
    r = L.parse_lesson(json.dumps({"blocks": [{"type": "code", "lang": "python", "code": changed}]}))
    d = L.code_changes(CODE, r)
    check("изменённый код — видно, какие строки", any("+ 1" in x for x in d), str(d))


def test_pasted() -> None:
    t, kind = parse_pasted(L._EXAMPLES[L.STYLE_COMMENTS])
    check("вставка: ответ нейросети", "нейросети" in kind and t.code_blocks(), kind)
    store_t = Template("Мой урок", [])
    from autoprint.storage import BLOCK_MARKDOWN, Block
    store_t.blocks = [Block(BLOCK_MARKDOWN, "## Задача", role="task"), Block(BLOCK_CODE, "x = 1", steps=[1])]
    path = Path(os.environ["AUTOPRINT_DATA"]) / "t.json"
    TemplateStore.export_template(store_t, str(path))
    t, kind = parse_pasted(path.read_text(encoding="utf-8"))
    check("вставка: наш .json — роли и заголовок сохраняются",
          t.title == "Мой урок" and t.blocks[0].role == "task" and "AutoPrintCode" in kind, kind)
    t, kind = parse_pasted("Задача про сумму.\n\n```python\nprint(1)\n```\n\nИ ещё:\n```js\nconsole.log(2)\n```")
    check("вставка: Markdown с блоками кода — языки по меткам",
          [b.lang for b in t.code_blocks()] == ["python", "js"] and "Markdown" in kind, kind)
    t, kind = parse_pasted("function f(a) {\n  return a * 2;\n}")
    check("вставка: просто код JavaScript — язык угадан", t.code_blocks()[0].lang == "javascript", kind)
    check("угадывание языка: python / cpp / sql", guess_lang("def f():\n    pass") == "python"
          and guess_lang("#include <iostream>\nint main() {}") == "cpp" and guess_lang("SELECT * FROM t") == "sql")
    try:
        parse_pasted("   ")
        check("пустая вставка — ошибка", False)
    except ValueError:
        check("пустая вставка — понятная ошибка", True)


# ---------------------------------------------------------------- подставной OpenAI-совместимый сервер

class Fake(http.server.BaseHTTPRequestHandler):
    calls: list[dict] = []
    reject_json_mode = False
    fail = False
    sse = False
    cut = False

    def log_message(self, *a) -> None:
        pass

    def _send(self, code: int, obj) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._send(200, {"data": [{"id": "coder-7b"}, {"id": "text-embedding-3"}, {"id": "whisper-1"}]})

    def do_POST(self) -> None:
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        req["_auth"] = self.headers.get("Authorization", "")
        Fake.calls.append(req)
        if Fake.fail:
            return self._send(500, {"error": {"message": "boom"}})
        if Fake.reject_json_mode and "response_format" in req:
            return self._send(400, {"error": {"message": "response_format unsupported"}})
        content = "<think>размышляю</think>" + L._EXAMPLES[L.STYLE_COMMENTS]
        if Fake.cut:
            return self._send(200, {"choices": [{"message": {"content": content[:50]}, "finish_reason": "length"}]})
        if req.get("stream") and Fake.sse:
            # поток, как у настоящих серверов: рассуждения, затем ответ кусками
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            chunks = [{"reasoning_content": "думаю"}] + [{"content": content[i:i + 40]}
                                                          for i in range(0, len(content), 40)]
            for d in chunks:
                self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": d}]}).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            return
        self._send(200, {"choices": [{"message": {"content": content}}]})


def test_ai() -> None:
    check("ключ шифруется DPAPI и читается обратно", ai.protect("sk-секрет").startswith("dpapi:")
          and ai.unprotect(ai.protect("sk-секрет")) == "sk-секрет")
    check("чужой/битый ключ — пусто, а не падение", ai.unprotect("dpapi:AAAA") == "")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    s = Settings()
    s.ai_provider = "openai"
    s.ai_urls = {"openai": url}
    s.ai_keys = {"openai": ai.protect("sk-test")}
    s.ai_models = {"openai": "coder-7b"}
    check("настроено: адрес, ключ, модель", ai.configured(s))
    text, who = ai.ask(s, L.instruction(L.Options()), L.material_message(CODE))
    call = Fake.calls[-1]
    check("запрос: system + user, модель, ключ, «только JSON»",
          call["messages"][0]["role"] == "system" and CODE in call["messages"][1]["content"]
          and call["model"] == "coder-7b" and call["_auth"] == "Bearer sk-test" and "response_format" in call)
    check("ответ без <think> и разбирается в занятие", "<think>" not in text and L.parse_lesson(text).template.code_blocks())
    Fake.reject_json_mode = True
    n = len(Fake.calls)
    text, _ = ai.ask(s, "sys", "user")
    check("сервер не понял response_format (400) — повтор без него", len(Fake.calls) == n + 2
          and "response_format" not in Fake.calls[-1] and text)
    Fake.reject_json_mode = False
    Fake.sse = True
    seen: list[tuple] = []
    text, _ = ai.ask(s, "sys", "user", on_progress=lambda ph, n, tail: seen.append((ph, n)))
    Fake.sse = False
    phases = [ph for ph, _n in seen]
    check("поток (SSE): ответ собран, ход виден — думает, затем пишет",
          L.parse_lesson(text).template.code_blocks() and "think" in phases and "write" in phases
          and phases.index("think") < phases.index("write") and seen[-1][1] == len(text) + len("<think>размышляю</think>"),
          f"{len(seen)} событий")
    Fake.cut = True
    try:
        ai.ask(s, "sys", "user")
        check("ответ оборвался — ошибка", False)
    except ai.AIError as e:
        check("ответ оборвался на пределе длины — так и сказано", "оборвался" in str(e), str(e)[:70])
    Fake.cut = False
    check("список моделей — без эмбеддингов и whisper", ai.list_models(ai.config(s)) == ["coder-7b"])
    ms, sample = ai.check(ai.config(s))
    check("проверка связи — время и ответ", ms >= 0 and bool(sample), f"{ms} мс")
    # основной лежит — отвечает запасной
    s.ai_urls = {"openai": "http://127.0.0.1:9", "custom": url}
    s.ai_backup_enabled, s.ai_backup_provider = True, "custom"
    s.ai_models["custom"] = "coder-7b"
    statuses: list[str] = []
    text, who = ai.ask(s, "sys", "user", on_status=statuses.append)
    check("основной не ответил — ответил запасной", "Своё" in who and len(statuses) == 2, who)
    s.ai_backup_provider = "deepseek"   # запасная без ключа — не пробовать, сказать почему
    try:
        ai.ask(s, "sys", "user")
        check("запасная без ключа — ошибка", False)
    except ai.AIError as e:
        check("запасная не настроена — не пробуем, причина в ошибке", "Запасная (DeepSeek) не настроена" in str(e),
              str(e)[-70:])
    s.ai_backup_enabled = False
    try:
        ai.ask(s, "sys", "user")
        check("без запасного — ошибка с причиной", False)
    except ai.AIError as e:
        check("без запасного — понятная ошибка", "не отвечает" in str(e), str(e)[:80])
    Fake.fail = True
    s.ai_urls = {"openai": url}
    try:
        ai.ask(s, "sys", "user")
    except ai.AIError as e:
        check("ошибка сервера 500 — с текстом", "500" in str(e), str(e)[:80])
    Fake.fail = False
    s.ai_keys = {}
    check("ChatGPT без ключа — не настроен, причина понятна", not ai.configured(s)
          and "ключ" in (ai.problem(ai.config(s)) or ""))
    srv.shutdown()


def test_cli() -> None:
    """Агент по подписке: «голый» запуск, системный промпт — файлом, материал — в stdin, ход — потоком событий;
    отмена убивает процесс."""
    d = Path(tempfile.mkdtemp(prefix="autoprint-fakecli-"))
    script = d / "fake.py"
    # как claude -p --output-format stream-json: думает, пишет ответ кусками, в конце — result
    script.write_text(textwrap.dedent("""\
        import sys, time, json, os
        args = sys.argv[1:]
        src = sys.stdin.read()
        sysp = open(args[args.index("--system-prompt-file") + 1], encoding="utf-8").read()
        json.dump({"args": args, "cwd": os.getcwd(), "system": sysp, "stdin": src},
                  open(os.environ["FAKE_LOG"], "w", encoding="utf-8"))
        if "SLOW" in src:
            time.sleep(30)
        if "FAIL" in src:
            print(json.dumps({"type": "result", "is_error": True, "result": "Not logged in"}))
            sys.exit(1)
        out = json.dumps({"blocks": [{"type": "code", "code": "got " + str(len(src))}]})
        def ev(o):
            print(json.dumps(o), flush=True)
        ev({"type": "system", "subtype": "init"})
        ev({"type": "system", "subtype": "thinking_tokens", "estimated_tokens": 120})
        for i in range(0, len(out), 10):
            ev({"type": "stream_event", "event": {"type": "content_block_delta",
                "delta": {"type": "text_delta", "text": out[i:i + 10]}}})
        ev({"type": "result", "subtype": "success", "is_error": False, "result": out})
        """), encoding="utf-8")
    log = d / "call.json"
    os.environ["FAKE_LOG"] = str(log)
    cmd = d / "claude.cmd"
    cmd.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    real = ai.cli_path
    ai.cli_path = lambda p: str(cmd)
    try:
        s = Settings()
        s.ai_provider = "claudeCli"
        seen: list[tuple] = []
        text, who = ai.ask(s, "СИСТЕМНЫЙ", "МАТЕРИАЛ", on_progress=lambda ph, n, tail: seen.append((ph, n)))
        call = json.loads(log.read_text(encoding="utf-8"))
        args = call["args"]
        check("агент по подписке: ответ из потока событий", "got" in text and "Claude" in who, text[:60])
        check("ход работы виден: подключение → думает → пишет",
              [ph for ph, _ in seen][:2] == ["connect", "think"] and seen[-1][0] == "write", str(seen[:3]))
        check("«голый» запуск: без инструментов, MCP и настроек, модель sonnet",
              "--tools" in args and args[args.index("--tools") + 1] == "" and "--strict-mcp-config" in args
              and "--setting-sources" in args and args[args.index("--model") + 1] == "sonnet", " ".join(args)[:120])
        check("системный промпт — файлом, материал — в stdin, папка пустая",
              "СИСТЕМНЫЙ" in call["system"] and call["stdin"] == "МАТЕРИАЛ" and "AutoPrintCode-ai" in call["cwd"])
        s.ai_models = {"claudeCli": ""}
        ai.ask(s, "sys", "user")
        check("модель «как в Claude Code» — без --model",
              "--model" not in json.loads(log.read_text(encoding="utf-8"))["args"])
        try:
            ai.ask(s, "sys", "FAIL")
            check("вход истёк — ошибка", False)
        except ai.AIError as e:
            check("вход истёк — понятная подсказка", "войдите" in str(e), str(e)[:80])
        ev = threading.Event()
        threading.Timer(1.0, ev.set).start()
        import time
        t0 = time.monotonic()
        try:
            ai.ask(s, "sys", "SLOW", cancel=ev)
            check("отмена агента", False, "не отменилось")
        except ai.Cancelled:
            check("отмена агента — быстро и без зависания", time.monotonic() - t0 < 8,
                  f"{time.monotonic() - t0:.1f} с")
    finally:
        ai.cli_path = real
    check("модели агентов: готовый список, «как в программе» — первым",
          ai.provider("codexCli").models[0][0] == "" and len(ai.provider("codexCli").models) >= 3
          and ai.list_models(ai.config(Settings(), "codexCli"))[0] == "")


def test_marks() -> None:
    """Большой код: нейросеть отвечает разметкой строк, код берётся из материала без изменений."""
    big = "\n".join(f"x{i} = {i}" for i in range(L.BIG_LINES + 5))
    check("большой код — разбор разметкой", L.is_big(big) and not L.is_big(CODE))
    opt = L.Options(style=L.STYLE_STEPS, marks=True)
    prompt = L.build_prompt(CODE, opt)
    check("промпт разметки: строки пронумерованы, код не переписывать, пример",
          "1| import statistics" in prompt and "НЕ ПЕРЕПИСЫВАЙ" in prompt and '"marks"' in prompt
          and '"lines"' not in prompt)
    exp_steps = [3, 3, 3, 1, 1, 2, 2, 3]   # import наверху с шагом 3, его комментарий тоже
    for style in L.STYLES:
        if style == L.STYLE_SCENARIO:
            continue        # сценарий урока — не разбор кода: разметки большого кода у него нет
        ans = L._MARKS_EXAMPLES[style]
        p = L.parse_lesson(ans, material=CODE, style=style)
        codes = p.template.code_blocks()
        ok = not L.code_changes(CODE, p) and not p.warnings
        if style == L.STYLE_STEPS:
            ok = ok and codes[0].steps == exp_steps and codes[0].text.startswith("# Медиану")
        if style == L.STYLE_PARTS:
            ok = ok and len(codes) == 2 and p.template.blocks[0].role == "explain"
        if style == L.STYLE_COMMENTS:
            ok = ok and codes[0].steps == [] and codes[0].text.count("# ") == 3
        check(f"разметка «{L.STYLES[style]}»: код из материала, комментарии на месте", ok,
              f"{p.summary} {p.warnings}")
    # начало файла нейросеть не разметила: docstring — код, условие задачи — нет
    doc = '"""Модуль оценок."""\nimport statistics\n\ngrades = [5, 4]'
    p = L.parse_lesson('{"mode": "marks", "marks": [{"from": 2, "to": 4, "step": 1, "say": "Начнём"}]}',
                       material=doc, style=L.STYLE_STEPS)
    check("неразмеченный docstring в начале — остаётся в коде", not L.code_changes(doc, p)
          and p.template.code_blocks()[0].text.startswith("# Начнём\n\"\"\"Модуль"), p.template.code_blocks()[0].text)
    task = "Задача: посчитать среднее.\n\n```python\nimport statistics\ngrades = [5, 4]\n```"
    p = L.parse_lesson('{"mode": "marks", "marks": [{"from": 4, "to": 5, "say": "Код"}]}', material=task,
                       style=L.STYLE_COMMENTS)
    check("условие задачи перед кодом и ``` — не код", p.template.code_blocks()[0].text
          == "# Код\nimport statistics\ngrades = [5, 4]" and any("условие" in w for w in p.warnings), str(p.warnings))
    inside = 'def f():\n    """Длинное\n    описание."""\n    return 1'
    p = L.parse_lesson('{"mode": "marks", "marks": [{"from": 1, "to": 2, "say": "Функция"},'
                       ' {"from": 3, "to": 4, "say": "Внутри строки"}]}', material=inside, style=L.STYLE_COMMENTS)
    text = p.template.code_blocks()[0].text
    check("комментарий внутри многострочной строки не вставляется", "Внутри строки" not in text
          and "# Функция" in text and any("многострочной" in w for w in p.warnings), text)
    js = "const a = 1;\nconsole.log(a);"
    p = L.parse_lesson('{"mode": "marks", "lang": "javascript", "marks": [{"from": 1, "to": 2, "say": "Выводим"}]}',
                       material=js)
    check("JavaScript: комментарий через //", p.template.code_blocks()[0].text.startswith("// Выводим\n"))
    try:
        L.parse_lesson('{"mode": "marks", "marks": [{"from": 1, "to": 2}]}')
        check("разметка без кода — ошибка", False)
    except L.LessonError as e:
        check("разметка без материала — понятная ошибка", "вместе с кодом" in str(e))


def main() -> int:
    test_prompt()
    test_parse()
    test_code_changes()
    test_marks()
    test_pasted()
    test_ai()
    test_cli()
    print("ГОТОВО" if not failed else f"ОШИБКИ: {failed}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
