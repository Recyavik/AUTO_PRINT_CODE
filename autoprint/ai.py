"""Подключение нейросети — так же, как в PasteTalk.

Провайдеры двух видов:
- «openai» — любой сервер с /v1/chat/completions: ChatGPT (OpenAI), DeepSeek, AITunnel, LM Studio и Ollama
  на этом компьютере, своё OpenAI-совместимое;
- «cli» — агент, уже установленный на компьютере (Claude Code, Codex): работает по подписке человека,
  ключ не нужен. Запрос уходит в stdin.

Один запасной провайдер: основной не ответил (не отмена) — тот же запрос один раз уходит запасному.
Ключи хранятся в settings.json зашифрованными Windows (DPAPI, «dpapi:…»): прочитать их может только эта
учётная запись на этом компьютере. На другом компьютере ключ придётся ввести заново.

Модуль без Qt: функции блокирующие, вызываются из фонового потока (jobs.py: «Новый урок» через нейросеть).
"""
from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("autoprint.ai")


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    kind: str                    # openai | cli
    url: str = ""                # адрес по умолчанию (openai)
    model: str = ""              # модель по умолчанию
    needs_key: bool = False
    json_mode: bool = False      # сервер понимает response_format: json_object
    models: tuple = ()           # готовый список моделей: ((id, подпись), …)
    hint: str = ""


PROVIDERS: tuple[Provider, ...] = (
    Provider("claudeCli", "Claude — по подписке (Claude Code)", "cli", model="sonnet",
             models=(("", "Как в Claude Code"), ("haiku", "Haiku — быстрая"), ("sonnet", "Sonnet — рабочая лошадка"),
                     ("opus", "Opus — самая сильная")),
             hint="Через установленную программу Claude Code и вашу подписку Claude — ключ не нужен. Запрос "
                  "уходит «голой» модели: без инструментов и настроек проекта — быстрее и дешевле."),
    Provider("codexCli", "ChatGPT — по подписке (Codex CLI)", "cli", model="",
             models=(("", "Как в Codex"), ("gpt-5.6-luna", "gpt-5.6-luna — полегче"),
                     ("gpt-5.6-terra", "gpt-5.6-terra — средняя"), ("gpt-5.6-sol", "gpt-5.6-sol — по умолчанию у Codex")),
             hint="Через установленную программу Codex и вашу подписку ChatGPT — ключ не нужен."),
    Provider("freeai", "FreeAI (бесплатные лимиты)", "openai", url="https://freeai.dev.appswire.ru/v1",
             model="text-medium", needs_key=True,
             models=(("text-medium", "text-medium"), ("text-hard", "text-hard"), ("text", "text"),
                     ("text-easy", "text-easy")),
             hint="Сам подбирает доступную бесплатную модель. text-medium — по умолчанию, text-hard — сильнее "
                  "(для большого кода), text-easy — быстрее. Ключ «fk-…» — в FreeAI."),
    Provider("openai", "ChatGPT (OpenAI API)", "openai", url="https://api.openai.com/v1", model="gpt-4o-mini",
             needs_key=True, json_mode=True, hint="Ключ — на platform.openai.com → API keys. Оплата по запросам."),
    Provider("deepseek", "DeepSeek", "openai", url="https://api.deepseek.com/v1", model="deepseek-chat",
             needs_key=True, json_mode=True, hint="Ключ — на platform.deepseek.com. Недорого и хорошо с кодом."),
    Provider("aitunnel", "AITunnel (доступ из России)", "openai", url="https://api.aitunnel.ru/v1",
             model="deepseek-chat", needs_key=True,
             hint="Шлюз к разным моделям с оплатой из России. Ключ — на aitunnel.ru."),
    Provider("lmstudio", "LM Studio (на этом компьютере)", "openai", url="http://localhost:1234/v1",
             hint="Модель запущена в LM Studio на этом компьютере — код никуда не уходит. Для разбора кода "
                  "нужна модель от 7B, лучше специальная для кода (Qwen Coder и т. п.)."),
    Provider("ollama", "Ollama (на этом компьютере)", "openai", url="http://localhost:11434/v1",
             model="qwen2.5-coder:7b",
             hint="Модель запущена в Ollama на этом компьютере — код никуда не уходит."),
    Provider("custom", "Своё, OpenAI-совместимое", "openai",
             hint="Любой сервер с /v1/chat/completions: OpenRouter, Groq, свой и т. п."),
)
_BY_ID = {p.id: p for p in PROVIDERS}


def provider(pid: str) -> Provider | None:
    return _BY_ID.get(pid)


class AIError(Exception):
    """Понятная человеку ошибка запроса."""


class Cancelled(AIError):
    pass


# ---------------------------------------------------------------- ключи: DPAPI

class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    src, dst = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0x1, ctypes.byref(dst)):   # UI_FORBIDDEN
        raise OSError(ctypes.GetLastError(), "DPAPI")
    try:
        return ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        kernel32.LocalFree(dst.pbData)


def protect(secret: str) -> str:
    if not secret:
        return ""
    try:
        return "dpapi:" + base64.b64encode(_dpapi(secret.encode("utf-8"), True)).decode("ascii")
    except (OSError, AttributeError):   # не Windows — хранить как есть лучше, чем потерять
        return "plain:" + secret


_UNPROTECTED: dict[str, str] = {}      # расшифрованное — в памяти процесса (настройки окну уходят часто)


def unprotect(stored: str) -> str:
    if not stored:
        return ""
    if stored.startswith("plain:"):
        return stored[6:]
    if stored.startswith("dpapi:"):
        if stored in _UNPROTECTED:
            return _UNPROTECTED[stored]
        try:
            out = _dpapi(base64.b64decode(stored[6:]), False).decode("utf-8")
        except (OSError, ValueError, AttributeError):
            return ""   # другой компьютер или учётная запись — ключ придётся ввести заново
        if len(_UNPROTECTED) > 32:
            _UNPROTECTED.clear()
        _UNPROTECTED[stored] = out
        return out
    return stored


# ---------------------------------------------------------------- настройки провайдера

@dataclass
class Config:
    provider: Provider
    url: str
    key: str
    model: str


def config(settings, pid: str | None = None) -> Config | None:
    """Адрес, ключ и модель провайдера pid (по умолчанию — основного) из настроек."""
    p = provider(pid if pid is not None else settings.ai_provider)
    if p is None:
        return None
    # модель: выбранная (в том числе пустая — «как в программе» у агентов), а если не выбирали — по умолчанию
    model = settings.ai_models[p.id] if p.id in settings.ai_models else p.model
    return Config(p, (settings.ai_urls.get(p.id) or p.url).strip(), unprotect(settings.ai_keys.get(p.id, "")),
                  (model or "").strip())


def configured(settings) -> bool:
    """Основной провайдер выбран и для него есть всё нужное."""
    c = config(settings)
    if c is None:
        return False
    if c.provider.kind == "cli":
        return cli_path(c.provider) is not None
    return bool(c.url) and (bool(c.key) or not c.provider.needs_key)


def problem(c: Config) -> str | None:
    """Почему с этими настройками запрос не уйдёт (None — уйдёт)."""
    if c.provider.kind == "cli":
        if cli_path(c.provider) is None:
            prog = "Claude Code" if c.provider.id == "claudeCli" else "Codex"
            return f"Не найдена программа {prog} — установите её или выберите другого провайдера."
        return None
    if not c.url:
        return "Не указан адрес сервера."
    if c.provider.needs_key and not c.key:
        return "Не указан ключ доступа."
    return None


# ---------------------------------------------------------------- запросы
#
# Ход запроса виден: on_progress(phase, chars, preview) — «connect» (жду ответа), «think» (думает: chars —
# примерно сколько «токенов рассуждений»), «write» (пишет ответ: chars — сколько знаков уже пришло, preview —
# хвост ответа). Без ограничения «5 минут»: большой код агент по подписке разбирает и дольше — ждём до 20 минут
# (настройка), а у сервера — пока данные идут (2 минуты тишины — ошибка).

IDLE_S = 120          # сервер замолчал дольше — ошибка
CLI_DEFAULT_S = 1200  # агент по подписке — до 20 минут


def timeout_for(settings, text_len: int, cli: bool) -> float:
    """Сколько ждать ответа целиком."""
    if settings.ai_timeout_s > 0:
        return float(settings.ai_timeout_s)
    return float(CLI_DEFAULT_S) if cli else min(120 + text_len * 0.05, 1200)


def chat_url(base: str) -> str:
    b = base.rstrip("/")
    if not re.search(r"/v\d+$", b):
        b += "/v1"
    return b + "/chat/completions"


_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def _clean(text: str) -> str:
    return _THINK.sub("", text or "").strip()


def _tail(text: str, n: int = 90) -> str:
    t = " ".join(text[-400:].split())
    return t[-n:]


def _request(url: str, payload: dict | None, key: str) -> urllib.request.Request:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json", "User-Agent": "AutoPrintCode"})
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    return req


def _http_error(e: urllib.error.HTTPError) -> AIError:
    body = e.read().decode("utf-8", errors="replace")[:400]
    msg = body
    try:
        j = json.loads(body)
        msg = (j.get("error") or {}).get("message") if isinstance(j.get("error"), dict) else j.get("error") or body
    except ValueError:
        pass
    err = AIError(_http_hint(e.code, str(msg)))
    err.status = e.code
    return err


def _http_json(url: str, payload: dict | None, key: str, timeout: float) -> dict:
    try:
        with urllib.request.urlopen(_request(url, payload, key), timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        raise _http_error(e) from None
    except urllib.error.URLError as e:
        raise AIError(f"Сервер не отвечает: {e.reason}. Проверьте адрес и что сервер запущен.") from None
    except TimeoutError:
        raise AIError("Нейросеть не ответила вовремя — попробуйте ещё раз или модель полегче.") from None
    except ValueError:
        raise AIError("Сервер ответил не JSON — проверьте адрес (нужен OpenAI-совместимый /v1).") from None


def _http_hint(code: int, msg: str) -> str:
    if code == 401:
        return "Ключ не подошёл (401) — проверьте ключ доступа."
    if code == 402:
        return "На счёте закончились деньги (402)."
    if code == 404:
        return f"Не найдено (404): {msg[:160]} — проверьте адрес и название модели."
    if code == 429:
        return "Слишком много запросов или исчерпан лимит (429) — подождите и попробуйте снова."
    if code in (502, 503, 504):
        return (f"Сервер-посредник не дождался ответа модели ({code}) — модель перегружена или думает дольше, "
                "чем ждёт сервер. Попробуйте ещё раз или другую модель.")
    return f"Ошибка сервера {code}: {msg[:200]}"


def _openai_stream(c: Config, payload: dict, deadline: float, cancel, progress) -> str:
    """Потоковый ответ (SSE): видно, как он приходит. Сервер не умеет поток — ответит обычным JSON, разберём его."""
    payload = dict(payload, stream=True)
    try:
        r = urllib.request.urlopen(_request(chat_url(c.url), payload, c.key), timeout=IDLE_S)
    except urllib.error.HTTPError as e:
        raise _http_error(e) from None
    except urllib.error.URLError as e:
        raise AIError(f"Сервер не отвечает: {e.reason}. Проверьте адрес и что сервер запущен.") from None
    except TimeoutError:
        raise AIError("Сервер не ответил за 2 минуты — попробуйте ещё раз или другую модель.") from None
    parts: list[str] = []
    thinking = 0
    finish = ""
    try:
        with r:
            if "event-stream" not in (r.headers.get("Content-Type") or ""):
                data = json.loads(r.read().decode("utf-8", errors="replace"))
                choice = data["choices"][0]
                if choice.get("finish_reason") == "length":
                    raise _cut_off(len(choice["message"].get("content") or ""))
                return choice["message"]["content"] or ""
            for raw in r:
                if cancel is not None and cancel.is_set():
                    raise Cancelled("Отменено.")
                if time.monotonic() > deadline:
                    raise AIError("Нейросеть отвечает слишком долго — попробуйте модель полегче или увеличьте "
                                  "ожидание (⚙ → Нейросеть).")
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if body == "[DONE]":
                    break
                try:
                    choice = json.loads(body)["choices"][0]
                    delta = choice.get("delta") or {}
                except (ValueError, KeyError, IndexError, TypeError):
                    continue
                finish = choice.get("finish_reason") or finish
                if delta.get("reasoning_content") or delta.get("reasoning"):
                    thinking += len(delta.get("reasoning_content") or delta.get("reasoning") or "")
                    if progress:
                        progress("think", thinking, "")
                if delta.get("content"):
                    parts.append(delta["content"])
                    if progress:
                        text = "".join(parts)
                        progress("write", len(text), _tail(text))
    except TimeoutError:
        raise AIError("Сервер замолчал больше чем на 2 минуты — попробуйте ещё раз.") from None
    except (KeyError, IndexError, TypeError, ValueError):
        raise AIError("Сервер ответил не в формате chat/completions.") from None
    if finish == "length":
        raise _cut_off(len("".join(parts)))
    return "".join(parts)


def _cut_off(chars: int) -> AIError:
    return AIError(f"Ответ оборвался на {chars} знаках: модель упёрлась в предел длины ответа. Выберите модель "
                   "сильнее или разберите код по частям.")


def _openai_chat(c: Config, system: str, user: str, timeout: float, json_mode: bool, cancel=None,
                 progress=None) -> str:
    payload = {"model": c.model, "temperature": 0.2,
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if json_mode and c.provider.json_mode:
        payload["response_format"] = {"type": "json_object"}
    deadline = time.monotonic() + timeout
    for attempt in range(2):
        try:
            return _clean(_openai_stream(c, payload, deadline, cancel, progress))
        except AIError as e:
            if attempt == 0 and getattr(e, "status", 0) in (400, 422) and "response_format" in payload:
                payload.pop("response_format")   # сервер не понял «ответ строго JSON» — без него
                continue
            raise
    raise AIError("Сервер не ответил.")


_CLI_SEEN: dict[str, tuple[float, str | None]] = {}
CLI_RECHECK_S = 60          # поставили Claude Code при открытой программе — увидим через минуту


def cli_path(p: Provider) -> str | None:
    """Где программа агента (поиск по PATH — не на каждую публикацию состояния окна, а раз в минуту)."""
    name = "claude" if p.id == "claudeCli" else "codex"
    hit = _CLI_SEEN.get(name)
    now = time.monotonic()
    if hit is None or now - hit[0] > CLI_RECHECK_S:
        hit = _CLI_SEEN[name] = (now, shutil.which(name))
    return hit[1]


def _empty_dir() -> str:
    """Пустая папка для агента: без CLAUDE.md/AGENTS.md и файлов чужого проекта."""
    import tempfile
    d = os.path.join(tempfile.gettempdir(), "AutoPrintCode-ai")
    os.makedirs(d, exist_ok=True)
    return d


def _cli_args(c: Config, system_file: str, files: bool = False) -> list[str]:
    exe = cli_path(c.provider)
    if c.provider.id == "claudeCli":
        # «голая» модель: свой системный промпт вместо агентского, без MCP, хуков и настроек. Инструментов нет —
        # ей нужно только переписать текст; есть файлы материала — только чтение (Read) в папке запроса
        tools = ["--tools", "Read", "--allowedTools", "Read"] if files else ["--tools", ""]
        args = [exe, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                "--system-prompt-file", system_file, *tools, "--strict-mcp-config",
                "--setting-sources", "", "--no-session-persistence", "--disable-slash-commands"]
        if c.model:
            args += ["--model", c.model]
        return args
    args = [exe, "exec", "--json", "--skip-git-repo-check", "--ephemeral", "-s", "read-only"]
    if c.model:
        args += ["-m", c.model]
    return args + ["-"]


_CLI_ERRORS = ((re.compile(r"login|log in|authenticat|not logged|unauthori", re.I),
                "Вход в программу истёк — войдите заново (claude login / codex login)."),
               (re.compile(r"rate.?limit|usage limit|quota|limit reached", re.I),
                "Упёрлись в лимит подписки — подождите или выберите другого провайдера."))


def _kill_tree(proc: subprocess.Popen) -> None:
    """claude/codex в Windows бывает обёрткой .cmd: убить нужно всё дерево, иначе сам агент продолжит работать."""
    try:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=10,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        proc.kill()


def _cli_event(c: Config, ev: dict, state: dict, progress) -> None:
    """Событие потока агента → ход работы и ответ."""
    t = ev.get("type")
    if c.provider.id == "claudeCli":
        if t == "system" and ev.get("subtype") == "thinking_tokens":
            state["think"] = int(ev.get("estimated_tokens") or 0)
            if progress:
                progress("think", state["think"], "")
        elif t == "stream_event":
            d = (ev.get("event") or {}).get("delta") or {}
            if d.get("stop_reason") == "max_tokens":
                state["cut"] = True
            if d.get("type") == "text_delta":
                state["text"] += d.get("text") or ""
                if progress:
                    progress("write", len(state["text"]), _tail(state["text"]))
        elif t == "result":
            state["result"] = ev.get("result") or ""
            state["error"] = bool(ev.get("is_error"))
        return
    # Codex: item.completed (рассуждения, сообщения), turn.completed
    if t == "item.completed":
        item = ev.get("item") or {}
        if item.get("type") == "agent_message":
            state["result"] = item.get("text") or ""
            if progress:
                progress("write", len(state["result"]), _tail(state["result"]))
        elif item.get("type") == "reasoning" and progress:
            state["think"] += 1
            progress("think", state["think"], "")
    elif t in ("turn.failed", "error"):
        state["error"] = True
        state["result"] = json.dumps(ev, ensure_ascii=False)[:300]


def _request_dir(files) -> tuple[str, list[str]]:
    """Своя пустая папка запроса с копиями файлов материала (агент читает только их). → (папка, имена)."""
    import shutil
    import tempfile
    d = tempfile.mkdtemp(prefix="req-", dir=_empty_dir())
    names: list[str] = []
    for f in files:
        src = Path(f)
        if not src.is_file():
            continue
        name = re.sub(r'[\\/:*?"<>|]', "_", src.name) or "material"
        while name in names:
            name = "_" + name
        shutil.copy2(src, os.path.join(d, name))
        names.append(name)
    return d, names


def _cli_chat(c: Config, system: str, user: str, timeout: float, cancel: threading.Event | None,
              progress=None, files=()) -> str:
    import shutil
    import tempfile
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    fd, sys_file = tempfile.mkstemp(prefix="apc-system-", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("Ты — молчаливый инструмент: выполни задание и выведи только результат, без вступлений.\n\n" + system)
    work, names = _request_dir(files) if files else (_empty_dir(), [])
    if names:
        user = (user + "\n\n" if user.strip() else "") + ("Файлы материала лежат в текущей папке: " + ", ".join(names)
                                                         + ". Прочитай их целиком (и картинки слайдов) — урок по ним.")
    stdin_text = user if c.provider.id == "claudeCli" else (
        "Ты — молчаливый инструмент: выполни задание и выведи только результат, без вступлений.\n\n"
        + system + "\n\n" + user)

    def cleanup() -> None:
        try:
            os.unlink(sys_file)
        except OSError:
            pass
        if names:
            shutil.rmtree(work, ignore_errors=True)
    try:
        proc = subprocess.Popen(_cli_args(c, sys_file, files=bool(names)), stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags, cwd=work)
    except OSError as e:
        cleanup()
        raise AIError(f"Не удалось запустить {c.provider.name}: {e}") from None
    state = {"text": "", "think": 0, "result": None, "error": False}
    err_buf: list[bytes] = []

    def feed() -> None:
        try:
            proc.stdin.write(stdin_text.encode("utf-8"))
            proc.stdin.close()
        except OSError:
            pass

    def read_out() -> None:
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("{"):
                continue
            try:
                _cli_event(c, json.loads(line), state, progress)
            except ValueError:
                continue

    def read_err() -> None:
        err_buf.append(proc.stderr.read())
    threads = [threading.Thread(target=f, daemon=True) for f in (feed, read_out, read_err)]
    for th in threads:
        th.start()
    if progress:
        progress("connect", 0, "")
    end = time.monotonic() + timeout
    try:
        while proc.poll() is None:
            time.sleep(0.2)
            if cancel is not None and cancel.is_set():
                _kill_tree(proc)
                raise Cancelled("Отменено.")
            if time.monotonic() > end:
                _kill_tree(proc)
                raise AIError(f"{c.provider.name} не закончил за {int(timeout // 60)} мин — попробуйте модель "
                              "побыстрее или увеличьте ожидание (⚙ → Нейросеть).")
        for th in threads[1:]:
            th.join(5)
    finally:
        cleanup()
    err = b"".join(err_buf).decode("utf-8", errors="replace")
    result = state["result"] if state["result"] is not None else state["text"]
    if state.get("cut"):
        raise _cut_off(len(result or ""))
    if proc.returncode != 0 or state["error"] or not (result or "").strip():
        blob = f"{err}\n{result or ''}"
        for rx, hint in _CLI_ERRORS:
            if rx.search(blob):
                raise AIError(hint)
        raise AIError(f"{c.provider.name} завершился с ошибкой: {(err or result or 'пустой ответ').strip()[:300]}")
    return _clean(result)


def chat(c: Config, system: str, user: str, timeout: float, cancel: threading.Event | None = None,
         json_mode: bool = True, progress=None, files=()) -> str:
    """Один запрос к провайдеру. AIError — с понятной причиной. files — файлы материала: Claude Code и Codex читают
    их сами (копии в папке запроса, только чтение); остальным текст материала передают в user."""
    why = problem(c)
    if why:
        raise AIError(why)
    if c.provider.kind == "cli":
        return _cli_chat(c, system, user, timeout, cancel, progress, files=files)
    result: dict = {}

    def run():
        try:
            result["t"] = _openai_chat(c, system, user, timeout, json_mode, cancel, progress)
        except Exception as e:   # noqa: BLE001
            result["x"] = e
    th = threading.Thread(target=run, daemon=True)
    th.start()
    if progress:
        progress("connect", 0, "")
    while th.is_alive():
        th.join(0.2)
        if cancel is not None and cancel.is_set():
            raise Cancelled("Отменено.")   # запрос дойдёт сам — его ответ просто не нужен
    if "x" in result:
        raise result["x"] if isinstance(result["x"], AIError) else AIError(str(result["x"]))
    return result["t"]


def _ask_one(settings, c: Config, system: str, user: str, cancel, progress, files=()) -> str:
    n = len(system) + len(user)
    t0 = time.monotonic()
    log.info("Нейросеть: запрос → %s · модель %s · %d знаков · файлов %d", c.provider.name, c.model or "по умолчанию",
             n, len(files))
    try:
        text = chat(c, system, user, timeout_for(settings, n, c.provider.kind == "cli"), cancel, progress=progress,
                    files=files)
    except Cancelled:
        log.info("Нейросеть: отменено через %.0f с", time.monotonic() - t0)
        raise
    except AIError as e:
        log.warning("Нейросеть: %s не ответил за %.0f с: %s", c.provider.name, time.monotonic() - t0, e)
        raise
    log.info("Нейросеть: ответ от %s за %.0f с · %d знаков", c.provider.name, time.monotonic() - t0, len(text))
    return text


def ask(settings, system: str, user: str, cancel: threading.Event | None = None,
        on_status=None, on_progress=None, files=(), as_text=None) -> tuple[str, str]:
    """Запрос основному провайдеру, при ошибке — запасному. → (ответ, имя провайдера). files — файлы материала
    (читают только Claude Code и Codex; для остальных текст материала уже в user). as_text() → (system, user) с текстом
    этих файлов — для запасной, которая файлы читать не умеет (иначе она составила бы урок по одной теме)."""
    main = config(settings)
    if main is None:
        raise AIError("Нейросеть не подключена — ⚙ Настройки → Нейросеть, или «Скопировать промпт».")
    try:
        if on_status:
            on_status(main.provider.name)
        return _ask_one(settings, main, system, user, cancel, on_progress, files), main.provider.name
    except Cancelled:
        raise
    except AIError as e:
        back = config(settings, settings.ai_backup_provider) if settings.ai_backup_enabled else None
        if back is None or back.provider.id == main.provider.id:
            raise
        why = problem(back)
        if why:   # запасная не настроена (например, без ключа) — её ошибка только запутала бы
            log.warning("Запасная %s не настроена (%s) — не пробую", back.provider.name, why)
            raise AIError(f"{e} Запасная ({back.provider.name}) не настроена: {why}") from None
        log.warning("Основной провайдер не справился (%s) — пробую запасной: %s", e, back.provider.name)
        if on_status:
            on_status(back.provider.name + f" (запасная: {main.provider.name} не ответил)")
        b_system, b_user, b_files = system, user, files
        if files and back.provider.kind != "cli":          # запасная файлы не читает — материал текстом
            if as_text is None:
                raise AIError(f"{e} Запасная ({back.provider.name}) не читает файлы материала.") from None
            b_system, b_user = as_text()
            b_files = ()
        try:
            return _ask_one(settings, back, b_system, b_user, cancel, on_progress, b_files), back.provider.name
        except AIError as e2:
            if isinstance(e2, Cancelled):
                raise
            raise AIError(f"Не ответили оба. {main.provider.name}: {e}  {back.provider.name}: {e2}") from None


_NOT_TEXT = re.compile(r"embed|whisper|tts|rerank|moderation|audio|image|diffusion|flux|nova-|dall-e", re.I)


def list_models(c: Config, timeout: float = 15) -> list[str]:
    """Модели сервера (GET /v1/models) — только текстовые; у cli — свой список."""
    if c.provider.kind == "cli":
        return [m for m, _t in c.provider.models]
    why = problem(c)
    if why:
        raise AIError(why)
    url = chat_url(c.url).rsplit("/chat/completions", 1)[0] + "/models"
    data = _http_json(url, None, c.key, timeout)
    ids = [str(m.get("id")) for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
    presets = [m for m, _t in c.provider.models]
    rest = sorted(i for i in ids if not _NOT_TEXT.search(i) and i not in presets)
    return [m for m in presets if m in ids or not ids] + rest


def check(c: Config, timeout: float = 60) -> tuple[int, str]:
    """Проверка связи: короткий запрос. → (миллисекунды, ответ). AIError — не вышло."""
    t0 = time.monotonic()
    text = chat(c, "Ответь одним словом.", "Скажи «готово».", timeout, json_mode=False)
    return int((time.monotonic() - t0) * 1000), text.strip()[:80]
