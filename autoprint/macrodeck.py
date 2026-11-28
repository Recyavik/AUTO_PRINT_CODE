"""Macro Deck 3 (1.3): страница «Урок» на телефоне — собирается сама по ключу Macro Deck, время идёт само.

Связь — сервер Macro Deck для ИИ-помощников (MCP, http://127.0.0.1:8193/mcp, ключ «mdmcp_…» из Macro Deck:
Настройки → AI clients). Через него программа:
  • setup(): профиль «AutoPrintCode» (новый — создаёт), на его главной странице (7 × 3 — телефон боком): сверху
    прошедший, идущий (крупно, сколько осталось) и следующий этап; ниже Фон, Чёрный, Зарядка, Перерыв, Слайд,
    ◀ ▶; ещё ниже Подготовка, Звук, Микрофон. Кнопки шлют команды пульту программы (/api/<команда>?key=…).
    Повторно — только свои кнопки (помечены "apc") заново; кнопки, которые человек добавил сам, не трогаем. После
    сборки телефоны переключаются на этот профиль.
  • Каждая кнопка — картинка (deckart: «Стекло», «Плитки» или «Контур», текст раскладывает программа). values() →
    переменные apc_* (время, этапы — подписями кнопок; их Macro Deck обновляет на телефоне сам); Sync шлёт
    изменившиеся в своём потоке (действие «Задать переменную»): время идёт.
  • 1.3.1: вид кнопки поменялся (нажата, выключен звук, новый этап) — Sync удаляет её и создаёт заново на той же
    клетке. Веб-интерфейс Macro Deck 3.0.5 не перерисовывает картинку существующей кнопки (подпись — да): кнопка с
    новой картинкой на телефоне оставалась прежней до перезапуска Macro Deck. Пересоздание — ~50 мс, разрешения
    не спрашивает (проверено на 3.0.5).
  • 1.3.1: Таймер, Задание, Перерыв, Зарядка открывают свой экран (отдельная страница профиля): минуты или видео,
    «Убрать», «Назад». Выбор — команда пульта и сразу назад на главную (Macro Deck ждёт ответа команды, потом
    переходит).
"""
from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import deckart

log = logging.getLogger(__name__)

MCP_URL = "http://127.0.0.1:8193/mcp"
PROTOCOL = "2025-11-25"
PROFILE_NAME = "AutoPrintCode"
FOLDER_NAME = "Урок"
COLS, ROWS = 7, 3
PREFIX = "apc_"
MARK = "apc"                    # пометка в данных кнопки: её собрала программа (пересборка заменяет только такие)
STYLES = ("glass", "tiles", "outline")   # «Стекло», «Плитки», «Контур»
LAYOUT = 5                      # устройство страницы: сменили (кнопки, данные) — программа пересоберёт её сама
# (4: 1.3.0 записывал «собрано», хотя Macro Deck ничего не создал — клетки занимали кнопки первой сборки;
#  5: 1.3.1 — экраны выбора Таймер, Задание, Перерыв, Зарядка)

# кнопки: ключ → (x, y, команда пульта, значок, подпись)
BUTTONS = [
    ("bg", 0, 1, "background", "image", "Фон"),
    ("black", 1, 1, "black", "blackout", "Чёрный"),
    ("ex", 2, 1, "exercise", "activity", "Зарядка"),
    ("break", 3, 1, "break", "cup", "Перерыв"),
    ("slide", 4, 1, "slide", "slide", "Слайд"),
    ("prev_s", 5, 1, "slide_prev", "prev", ""),
    ("next_s", 6, 1, "slide_next", "next", ""),
    ("prepare", 0, 2, "prepare", "open", "Подготовка"),
    ("sound", 1, 2, "sound", "volume", "Звук"),
    ("mic", 2, 2, "mic", "mic", "Микрофон"),
    ("timer", 3, 2, "timer", "timer", "Таймер"),
    ("task", 4, 2, "task", "task", "Задание"),
]
# верхний ряд: ключ → (x, ширина в ячейках)
INFO = [("prev", 0, 2), ("now", 2, 3), ("next", 5, 2)]
TEXT_VARS = ("prev", "now", "left", "next", "stage", "break_left", "timer_left")
IMAGE_KEYS = [k for k, _, _ in INFO] + [b[0] for b in BUTTONS]

# экраны выбора (1.3.1): ключ кнопки главной страницы → название страницы профиля
MAIN = "main"
SUBS = (("timer", "Таймер"), ("task", "Задание"), ("break", "Перерыв"), ("ex", "Зарядка"))
SUB_NAMES = dict(SUBS)
EX_SLOTS = 10                   # видео зарядки на экране (остальные — «По очереди» и «Случайная»)
TITLE_TIME = 30                 # кегль отсчёта в заголовке экрана


def _sub_spec() -> dict[str, dict]:
    """Кнопки экранов выбора: ключ «экран.имя» → где стоит, что шлёт пульту (cmd, q) и вернуться ли на главную
    (back). Ряд 0: «Назад», заголовок (5 клеток, справа — отсчёт), «Убрать». Ряды 1–2: выбор."""
    S: dict[str, dict] = {}

    def put(key, folder, x, y, w=1, **kw):
        S[key] = {"folder": folder, "x": x, "y": y, "w": w, **kw}

    stop = {"timer": "timer", "task": "timer", "break": "break", "ex": "exercise"}
    for sub, _name in SUBS:
        put(f"{sub}.back", sub, 0, 0, kind="back")
        put(f"{sub}.title", sub, 1, 0, 5, kind="title")
        put(f"{sub}.stop", sub, 6, 0, kind="stop", cmd="stop", q={"what": stop[sub]}, back=True)

    def minutes(sub, cmd, cells):
        for m, (x, y) in cells:
            put(f"{sub}.m{m}", sub, x, y, kind="min", n=m, cmd=cmd, q={"min": m}, back=True)

    row1, row2 = [(x, 1) for x in range(7)], [(x, 2) for x in range(7)]
    minutes("timer", "timer", zip((1, 2, 3, 5, 7, 10, 15, 20, 25, 30, 45, 60), row1 + row2[:5]))
    put("timer.minus", "timer", 5, 2, kind="adj", n=-1, cmd="timer_add", q={"min": -1})
    put("timer.plus", "timer", 6, 2, kind="adj", n=1, cmd="timer_add", q={"min": 1})
    put("task.own", "task", 0, 1, kind="own", cmd="task", q={"min": 0}, back=True)
    minutes("task", "task", zip((2, 3, 5, 7, 10, 15, 20, 25, 30, 40, 45), row1[1:] + row2[:5]))
    put("task.minus", "task", 5, 2, kind="adj", n=-1, cmd="timer_add", q={"min": -1})
    put("task.plus", "task", 6, 2, kind="adj", n=1, cmd="timer_add", q={"min": 1})
    put("break.plan", "break", 0, 1, kind="plan", cmd="break", q={"plan": 1}, back=True)
    minutes("break", "break", zip((5, 10, 15, 20, 30, 45), row1[1:]))
    put("break.pause", "break", 0, 2, kind="pause", cmd="break_pause")
    for x, (name, n) in enumerate((("minus5", -5), ("minus1", -1), ("plus1", 1), ("plus5", 5)), start=1):
        put(f"break.{name}", "break", x, 2, kind="adj", n=n, cmd="break_add", q={"min": n})
    put("ex.next", "ex", 0, 1, kind="pick", cmd="exercise", q={"pick": "next"}, back=True)
    put("ex.random", "ex", 1, 1, kind="pick", cmd="exercise", q={"pick": "random"}, back=True)
    put("ex.pause", "ex", 2, 1, kind="pause", cmd="ex_pause")
    put("ex.restart", "ex", 3, 1, kind="restart", cmd="ex_restart")
    for i, (x, y) in enumerate(row1[4:] + row2):
        put(f"ex.v{i}", "ex", x, y, kind="video", n=i, cmd="exercise", q={"index": i}, back=True)
    return S


SUB_SPEC = _sub_spec()
ALL_KEYS = IMAGE_KEYS + list(SUB_SPEC)


class MacroDeckError(Exception):
    """Macro Deck не ответил или отказал — текст для человека."""


class Client:
    """Сессия MCP Macro Deck (Streamable HTTP). Каждый вызов — свой запрос; сессия заводится сама."""

    def __init__(self, token: str, url: str = MCP_URL, timeout: float = 10) -> None:
        self.token = (token or "").strip()
        self.url = url
        self.timeout = timeout
        self._sid = ""
        self._id = 0
        self._lock = threading.Lock()

    def _post(self, body: dict) -> dict | None:
        h = {"Authorization": "Bearer " + self.token, "Content-Type": "application/json",
             "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": PROTOCOL}
        if self._sid:
            h["Mcp-Session-Id"] = self._sid
        req = urllib.request.Request(self.url, data=json.dumps(body).encode("utf-8"), headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                self._sid = r.headers.get("Mcp-Session-Id") or self._sid
                raw = r.read().decode("utf-8", "replace")
                ctype = r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise MacroDeckError("Macro Deck не принял ключ — создайте новый: Macro Deck → Настройки → AI clients") from None
            if e.code == 404 and self._sid:
                self._sid = ""                    # сессия устарела (Macro Deck перезапускали) — заново
                raise _Expired() from None
            raise MacroDeckError(f"Macro Deck ответил ошибкой {e.code}") from None
        except (urllib.error.URLError, OSError, TimeoutError):
            raise MacroDeckError("Macro Deck не отвечает — он запущен на этом компьютере?") from None
        if "id" not in body:
            return None
        if "text/event-stream" in ctype:
            for line in raw.splitlines():
                if line.startswith("data:") and line[5:].strip():
                    m = json.loads(line[5:])
                    if m.get("id") == body["id"]:
                        return m
            return {}
        return json.loads(raw) if raw.strip() else {}

    def _rpc(self, method: str, params: dict) -> dict:
        self._id += 1
        return self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}) or {}

    def _init(self) -> None:
        self._sid = ""
        r = self._rpc("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                     "clientInfo": {"name": "AutoPrintCode", "version": "1"}})
        if "error" in r:
            raise MacroDeckError("Macro Deck не начал сеанс: " + str(r["error"].get("message", ""))[:200])
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call(self, tool: str, args: dict) -> dict:
        """Вызов инструмента Macro Deck → ответ (JSON из текста). Ошибка — MacroDeckError."""
        with self._lock:
            for attempt in (0, 1):
                try:
                    if not self._sid:
                        self._init()
                    r = self._rpc("tools/call", {"name": tool, "arguments": args})
                    break
                except _Expired:
                    if attempt:
                        raise MacroDeckError("Macro Deck сбросил сеанс") from None
        if "error" in r:
            raise MacroDeckError(str(r["error"].get("message", "Macro Deck: ошибка"))[:300])
        res = r.get("result") or {}
        text = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        try:
            data = json.loads(text) if text.strip() else {}
        except ValueError:
            data = {"text": text}
        if res.get("isError"):
            raise MacroDeckError(str(data.get("message") or data.get("error") or text)[:300])
        return data

    # ------------------------------------------------------------ удобные
    def items(self, entity: str, **kw) -> list[dict]:
        return list(self.call("list", {"entity": entity, **kw}).get("items") or [])

    def apply(self, changes: list[dict], dry: bool = False) -> dict:
        """Изменения одним пакетом. Macro Deck может ответить «проверено, но не применено» (клетки заняты, ждёт
        разрешения человека) — это ошибка, а не успех: иначе программа скажет «Готово», а на телефоне пусто."""
        r = self.call("apply_changes", {"changes": changes, "dryRun": dry})
        probs = r.get("problems") or []
        text = "; ".join(f"{p.get('path', '')}: {p.get('message', '')}".strip(": ") for p in probs)
        if not r.get("valid", False):
            raise MacroDeckError("Macro Deck не принял страницу: " + (text or json.dumps(r, ensure_ascii=False))[:400])
        if dry or r.get("applied", True) is not False:
            return r
        if any(p.get("code") == "PositionOccupied" for p in probs):
            raise MacroDeckError("Macro Deck: на странице «Урок» клетки заняты другими кнопками — перенесите или "
                                 "удалите их и нажмите «Пересобрать страницу»")
        if r.get("confirmations"):
            raise MacroDeckError("CONFIRMATION_PENDING: Macro Deck ждёт разрешения")
        raise MacroDeckError("Macro Deck не применил изменения" + (": " + text[:300] if text else ""))

    def set_var(self, name: str, value: str) -> None:
        r = self.call("run_action", {"integrationId": "app.macro-deck.variables", "actionId": "set-variable",
                                     "parameters": {"variable": name, "value": value}})
        if str(r.get("status", "")).lower() not in ("succeeded", "success", "accepted", ""):
            raise MacroDeckError(f"переменная {name}: {r.get('message') or r.get('status')}")


MAX_CHANGES = 100              # Macro Deck 3.0.5: «changes must hold 1 to 100 entries»


def apply_all(client: Client, changes: list[dict], dry: bool = False) -> dict:
    """Изменения частями не больше MAX_CHANGES (пересборка: 81 кнопка удалить и создать — 162), по порядку;
    id созданного и запросы разрешения — из всех частей. Удаление и создание одной кнопки — в одной части."""
    out: dict = {"valid": True, "applied": True, "createdIds": {}, "confirmations": []}
    part: list[dict] = []

    def send() -> None:
        r = client.apply(list(part), dry=dry)
        out["createdIds"].update(r.get("createdIds") or {})
        out["confirmations"] += r.get("confirmations") or []
        part.clear()

    i = 0
    while i < len(changes):
        c = changes[i]
        pair = (c.get("op") == "delete" and i + 1 < len(changes) and changes[i + 1].get("op") == "create"
                and changes[i + 1].get("ref"))
        group = changes[i:i + 2] if pair else [c]
        if len(part) + len(group) > MAX_CHANGES:
            send()
        part.extend(group)
        i += len(group)
    if part:
        send()
    return out


class _Expired(Exception):
    pass


# ---------------------------------------------------------------- страница
def _http(cid: str, url: str) -> dict:
    return {"id": "apc-" + cid.replace(".", "-"), "type": "action", "blockType": "app.macro-deck.http.send-request",
            "integrationId": "app.macro-deck.http", "actionId": "send-request",
            "parameters": [{"name": "method", "value": "GET"}, {"name": "url", "value": url},
                           {"name": "timeout", "value": 5000}]}


def _go(cid: str, folder_id: str) -> dict:
    """Перейти на страницу — только телефону, на котором нажали (устройство не указано)."""
    return {"id": "apc-" + cid.replace(".", "-") + "-go", "type": "action",
            "blockType": "app.macro-deck.deck.change-folder", "integrationId": "app.macro-deck.deck",
            "actionId": "change-folder", "parameters": [{"name": "folderId", "value": folder_id}]}


def _press(*blocks: dict) -> list[dict]:
    return [{"triggerId": "onShortPress", "triggerType": "onShortPress", "children": list(blocks)}]


def _flow(cid: str, url: str) -> list[dict]:
    return _press(_http(cid, url))


POS = {k: (x, 0, w) for k, x, w in INFO} | {b[0]: (b[1], b[2], 1) for b in BUTTONS}
# где стоит каждая кнопка: ключ → (страница: MAIN или экран, x, y, ширина)
PLACE = {k: (MAIN, *p) for k, p in POS.items()} | {k: (s["folder"], s["x"], s["y"], s["w"]) for k, s in SUB_SPEC.items()}
CMD = {b[0]: b[3] for b in BUTTONS}
TIME_SIZE = 30                  # кегль времени этапа (подпись Macro Deck), отсчёта перерыва — BREAK_SIZE
BREAK_SIZE = 20


def _cmd_url(base: str, cmd: str, q: dict | None = None) -> str:
    root, _, qs = base.partition("?")
    url = f"{root}{cmd}" + ("?" + qs if qs else "")
    if q:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(q)
    return url


def _flows(cid: str, base: str, folders: dict) -> list[dict] | None:
    """Что делает кнопка: главная — команда пульта (Таймер, Задание, Перерыв, Зарядка — свой экран, если он
    есть); экран выбора — «Назад», команда, команда и назад на главную. Нечего делать — None."""
    main = folders.get(MAIN, "")
    if cid in CMD:
        if cid in SUB_NAMES and folders.get(cid):
            return _press(_go(cid, folders[cid]))
        return _flow(cid, _cmd_url(base, CMD[cid])) if base else None
    s = SUB_SPEC.get(cid)
    if s is None or s["kind"] == "title":
        return None
    if s["kind"] == "back":
        return _press(_go(cid, main)) if main else None
    if not base:
        return None
    blocks = [_http(cid, _cmd_url(base, s["cmd"], s.get("q")))]
    if s.get("back") and main:
        blocks.append(_go(cid, main))
    return _press(*blocks)


def page(st: dict, style: str = "glass", base: str = "", folders: dict | None = None) -> dict[str, dict]:
    """Данные каждой кнопки страниц целиком (главной и экранов выбора; кнопка пересоздаётся целиком): картинка
    нынешнего вида (подсветка, этапы) и, у кнопок, что она делает. Время этапа и отсчёты — подписью из переменной
    (её Macro Deck обновляет сам каждую секунду), в пустом месте картинки. folders — id страниц: MAIN и экраны
    (нет — главные кнопки шлют команду сами, как до 1.3.1)."""
    style = style if style in deckart.STYLES else deckart.DEFAULT_STYLE
    folders = folders or {}
    imgs = images(st, style)
    out: dict[str, dict] = {}
    for cid in ALL_KEYS:
        data = {"label": "", "backgroundColor": "transparent", "iconDisplay": {"fit": "contain", "zoom": 100},
                "labelShadow": False, MARK: cid}
        if imgs.get(cid):
            data["imageUrl"] = deckart.data_url(imgs[cid])
        if cid == "now" and st.get("left") and not st.get("off"):
            left_s = int(st.get("left_s") or 0)
            warn = st.get("phase") == "live" and 0 < left_s <= 60
            data.update(label="{{ vars.apc_left }}", labelPosition="center", textAlign="center", fontSize=TIME_SIZE,
                        labelColor=deckart.time_color(warn, style))
        if cid == "break" and (st.get("screen") == "break") and st.get("break_left") and not st.get("off"):
            data.update(label="{{ vars.apc_break_left }}", labelPosition="bottom", textAlign="center",
                        fontSize=BREAK_SIZE, labelColor=deckart.timer_color(style))
        running = {"timer": st.get("screen") == "timer", "task": st.get("screen") == "task"}
        if running.get(cid) and st.get("timer_left") and not st.get("off"):
            data.update(label="{{ vars.apc_timer_left }}", labelPosition="bottom", textAlign="center",
                        fontSize=BREAK_SIZE, labelColor=deckart.timer_color(style))
        if not st.get("off"):                       # заголовок экрана: отсчёт справа от названия
            counting = st.get("screen") in ("timer", "task") and st.get("timer_left")
            if cid in ("timer.title", "task.title") and counting:
                data.update(label="{{ vars.apc_timer_left }}", labelPosition="center", textAlign="right",
                            fontSize=TITLE_TIME, labelColor=deckart.timer_color(style))
            if cid == "break.title" and st.get("screen") == "break" and st.get("break_left"):
                data.update(label="{{ vars.apc_break_left }}", labelPosition="center", textAlign="right",
                            fontSize=TITLE_TIME, labelColor=deckart.timer_color(style))
        fl = _flows(cid, base, folders)
        if fl and not (cid.startswith("ex.v") and not imgs.get(cid)):    # пустая клетка видео — ничего не делает
            data["flows"] = fl
        out[cid] = data
    return out


def layout(base: str, st: dict | None = None, style: str = "glass", folders: dict | None = None) -> list[dict]:
    """Кнопки страниц в нынешнем виде; "folder" — чья кнопка: MAIN или экран выбора (не id страницы).
    base — «http://127.0.0.1:8791/api/?key=…»."""
    out = []
    for cid, data in page(st or {}, style, base, folders).items():
        folder, x, y, w = PLACE[cid]
        out.append({"type": "ActionButton", "positionX": x, "positionY": y, "width": w, "height": 1, "data": data,
                    "folder": folder})
    return out


def variables() -> list[tuple[str, str, str]]:
    """(имя, тип, начальное значение) переменных страницы (текст: подписи и для своих кнопок человека)."""
    return [(PREFIX + k, "text", "") for k in TEXT_VARS]


def images(st: dict, style: str = "glass") -> dict[str, str]:
    """Состояние пульта (DeckControl.state()) → картинки кнопок (SVG) по ключам IMAGE_KEYS. Время этапа и отсчёт
    перерыва на картинке не рисуются (их пишет Macro Deck подписью) — ход этапа полосой, с шагом 5 %."""
    style = style if style in deckart.STYLES else deckart.DEFAULT_STYLE
    if st.get("off"):
        out = {k: deckart.stage("", w, style=style) for k, _, w in INFO}
        out["now"] = deckart.now(st.get("now") or "Пульт выключен", "", style=style)
        for cid, _x, _y, _cmd, icon, label in BUTTONS:
            out[cid] = deckart.button(icon, label, "off", style=style)
        out.update(_sub_images(st, style))
        return out
    left_s = int(st.get("left_s") or 0)
    warn = st.get("phase") == "live" and 0 < left_s <= 60
    frac = round(float(st.get("frac") or 0) * 20) / 20
    out = {"prev": deckart.stage(st.get("prev") or "", 2, "left", style),
           "now": deckart.now(st.get("now") or "", st.get("left") or "", frac, warn, "", 3, style, draw_left=False),
           "next": deckart.stage(st.get("next") or "", 2, "right", style)}
    screen = st.get("screen") or "idle"
    active = {"bg": "idle", "black": "black", "ex": "exercise", "break": "break", "slide": "slide", "timer": "timer",
              "task": "task"}
    for cid, _x, _y, _cmd, icon, label in BUTTONS:
        mode, sub = "", ""
        if cid in active and screen == active[cid]:
            mode = "on"
        if cid == "break" and screen == "break" and st.get("break_left"):
            out[cid] = deckart.timer("", style=style, draw_text=False)
            continue
        if cid in ("timer", "task") and screen == cid and st.get("timer_left"):
            out[cid] = deckart.timer("", style=style, draw_text=False, icon=icon)
            continue
        if cid == "task" and not st.get("has_task"):
            mode = "off"
        if cid == "ex" and mode == "on" and st.get("exercise_paused"):
            sub = "пауза"
        if cid == "slide" and st.get("slide_text"):
            sub = st["slide_text"].replace(" ", "")
        if cid in ("prev_s", "next_s") and not st.get("slide"):
            mode = "off"
        if cid == "slide" and not st.get("slides") and screen != "slide":
            mode = "off"
        if cid in ("mic", "sound") and st.get(cid + "_muted"):
            mode, icon, label = "alert", icon + "-off" if cid == "mic" else "volume-off", "Выключен"
        out[cid] = deckart.button(icon, label, mode, sub, style=style)
    out.update(_sub_images(st, style))
    return out


def _min_text(m) -> str:
    try:
        f = float(m)
    except (TypeError, ValueError):
        return ""
    return (f"{f:g}".replace(".", ",") + " мин") if f > 0 else ""


def _sub_images(st: dict, style: str) -> dict[str, str]:
    """Картинки экранов выбора. Чего сейчас нет у учеников, то не убрать и не поставить на паузу — погашено;
    идёт — заголовок экрана синий (отсчёт пишет Macro Deck справа)."""
    A = deckart
    off = bool(st.get("off"))
    screen = "" if off else (st.get("screen") or "idle")
    timing, brk, ex = screen in ("timer", "task"), screen == "break", screen == "exercise"
    has_task = bool(st.get("has_task")) and not off
    exs = [str(x) for x in (st.get("exercises") or [])][:EX_SLOTS]

    def m(on: bool) -> str:
        return "" if on else "off"

    out: dict[str, str] = {}
    for sub, _name in SUBS:
        out[f"{sub}.back"] = A.button("back", "Назад", m(not off), style=style)
    task_sub = (st.get("task_title") or "") if has_task else ("" if off else "в уроке нет заданий")
    ex_i = st.get("ex_index", -1) if ex else -1
    playing = exs[ex_i] if isinstance(ex_i, int) and 0 <= ex_i < len(exs) else ""
    out["timer.title"] = A.title("Таймер", "на весь экран", "timer", "on" if screen == "timer" else "", style=style)
    out["task.title"] = A.title("Задание", task_sub, "task", "on" if screen == "task" else "", style=style)
    out["break.title"] = A.title("Перерыв", "на паузе" if brk and st.get("break_paused") else "", "cup",
                                 "on" if brk else "", style=style)
    out["ex.title"] = A.title("Зарядка", playing or ("" if exs or off else "в оформлении урока нет видео"),
                              "activity", "on" if ex else "", style=style)
    out["timer.stop"] = A.button("stop", "Убрать", m(timing), style=style)
    out["task.stop"] = A.button("stop", "Убрать", m(timing), style=style)
    out["break.stop"] = A.button("stop", "Закончить", m(brk), style=style)
    out["ex.stop"] = A.button("stop", "Убрать", m(ex), style=style)
    for key, s in SUB_SPEC.items():
        kind = s["kind"]
        if kind == "min":
            can = has_task if s["folder"] == "task" else not off
            out[key] = A.number(str(s["n"]), "мин", m(can), style=style)
        elif kind == "adj":
            n = s["n"]
            can = brk if s["folder"] == "break" else timing
            out[key] = A.number(("+" if n > 0 else "−") + str(abs(n)), "мин", m(can), style=style)
    out["task.own"] = A.button("task", "Как в задании", m(has_task), _min_text(st.get("task_min")) if has_task else "",
                               style=style)
    out["break.plan"] = A.button("plan", "По плану", m(not off), _min_text(st.get("break_plan_min")), style=style)
    paused = brk and st.get("break_paused")
    out["break.pause"] = A.button("play" if paused else "pause", "Продолжить" if paused else "Пауза", m(brk),
                                  style=style)
    out["ex.next"] = A.button("queue", "По очереди", m(bool(exs) and not off), style=style)
    out["ex.random"] = A.button("shuffle", "Случайная", m(len(exs) > 1 and not off), style=style)
    ex_paused = ex and st.get("exercise_paused")
    out["ex.pause"] = A.button("play" if ex_paused else "pause", "Продолжить" if ex_paused else "Пауза", m(ex),
                               style=style)
    out["ex.restart"] = A.button("restart", "Сначала", m(ex), style=style)
    for i in range(EX_SLOTS):
        out[f"ex.v{i}"] = (A.video(exs[i], "on" if i == ex_i else ("off" if off else ""), style) if i < len(exs)
                           else "")
    return out


def values(st: dict, style: str = "glass") -> dict[str, str]:
    """Состояние пульта → текстовые переменные страницы (время, отсчёт перерыва, этапы — и для своих кнопок)."""
    v = {PREFIX + k: str(st.get(k) or "") for k in ("prev", "now", "left", "next")}
    v[PREFIX + "stage"] = str(st.get("stage_text") or "")
    v[PREFIX + "break_left"] = str(st.get("break_left") or "")
    v[PREFIX + "timer_left"] = str(st.get("timer_left") or "")
    return v


def _home_folder(client: Client, pid: str) -> dict | None:
    """Главная страница профиля: та, что открывается на телефоне (isDefault), иначе первая."""
    folders = [f for f in client.items("folders", profileId=pid) if f.get("profileId", pid) == pid]
    if not folders:
        return None
    return next((f for f in folders if f.get("isDefault")), None) or min(folders, key=lambda f: f.get("order") or 0)


def _ref(key: str) -> str:
    return "w_" + key.replace(".", "-")


REFS = {_ref(k): k for k in ALL_KEYS}


def setup(client: Client, base: str, profile_id: str = "", dry: bool = False, st: dict | None = None,
          style: str = "glass") -> dict:
    """Собрать страницы: профиль (свой — по id, иначе по имени, иначе новый), на его главной странице и на экранах
    выбора (страницы «Таймер», «Задание», «Перерыв», «Зарядка»; нет — создать) — свои кнопки заново в нынешнем
    виде (чужие не трогаем), переменные (недостающие — создать); телефоны — на этот профиль. → {"profile": id,
    "folder": id главной, "folders": {MAIN и экраны: id}, "widgets": {ключ: id кнопки}, "created": n}."""
    profiles = client.items("profiles")
    prof = next((p for p in profiles if p.get("id") == profile_id), None) if profile_id else None
    prof = prof or next((p for p in profiles if p.get("name") == PROFILE_NAME), None)
    have = {v.get("name") for v in client.items("variables")}
    first: list[dict] = []
    if prof is None:
        first.append({"op": "create", "entity": "profile", "ref": "p",
                      "data": {"name": PROFILE_NAME, "defaultRows": ROWS, "defaultColumns": COLS}})
    for name, typ, init in variables():
        if name not in have:
            first.append({"op": "create", "entity": "variable",
                          "data": {"name": name, "scope": "global", "type": typ, "value": init}})
    pid = prof["id"] if prof is not None else ""
    if first:
        r = client.apply(first, dry=dry)
        pid = pid or (r.get("createdIds") or {}).get("p", "")
    if dry and not pid:
        return {"profile": "", "folder": "", "folders": {}, "created": len(first), "confirmations": []}
    home = _home_folder(client, pid)
    have_f = [f for f in client.items("folders", profileId=pid) if f.get("profileId", pid) == pid]
    # страницы — до кнопок: id нужны кнопкам «Назад» и переходам на экраны
    made: list[dict] = []
    if home is None:
        made.append({"op": "create", "entity": "folder", "ref": "f", "data": {"profileId": pid, "name": FOLDER_NAME}})
    subs: dict[str, str] = {}
    for sub, name in SUBS:
        f = next((x for x in have_f if x.get("name") == name and (home is None or x.get("id") != home.get("id"))), None)
        if f is not None:
            subs[sub] = f["id"]
        else:
            made.append({"op": "create", "entity": "folder", "ref": "s_" + sub, "data": {"profileId": pid, "name": name}})
    old_subs = dict(subs)
    fid = home["id"] if home is not None else ""
    if made:
        r = apply_all(client, made, dry=dry)
        ids = r.get("createdIds") or {}
        fid = fid or ids.get("f") or "@f"
        for sub, _name in SUBS:
            subs.setdefault(sub, ids.get("s_" + sub) or "@s_" + sub)
    folders = {MAIN: fid, **subs}
    changes: list[dict] = []
    for f in old_subs.values():                       # экраны прежней сборки: свои кнопки — заново
        for w in client.items("widgets", folderId=f):
            d = w.get("data")
            if isinstance(d, dict) and d.get(MARK):
                changes.append({"op": "delete", "entity": "widget", "id": w["id"]})
    if home is not None:
        if home.get("name") != FOLDER_NAME:
            changes.append({"op": "update", "entity": "folder", "id": fid, "data": {"name": FOLDER_NAME}})
        cells = {(x + dx, y) for x, y, wd in POS.values() for dx in range(wd)}
        for w in client.items("widgets", folderId=fid):
            d = w.get("data")
            # без пометки (первая сборка 1.3.0) — только на клетках страницы: свою кнопку человека на команду
            # пульта в свободной клетке не трогаем
            mine = isinstance(d, dict) and bool(d.get(MARK))
            spot = {(int(w.get("positionX") or 0) + dx, int(w.get("positionY") or 0))
                    for dx in range(int(w.get("width") or 1))}
            if mine or (ours(d) and spot & cells):
                changes.append({"op": "delete", "entity": "widget", "id": w["id"]})
    # страница прежней версии 1.3 («Урок» отдельной папкой рядом с пустой главной) — убрать
    for f in client.items("folders", profileId=pid):
        if home is not None and f.get("id") != fid and f.get("name") == FOLDER_NAME and f.get("profileId", pid) == pid:
            changes.append({"op": "delete", "entity": "folder", "id": f["id"]})
    for w in layout(base, st, style, folders):
        changes.append({"op": "create", "entity": "widget", "ref": _ref(w["data"][MARK]),
                        "data": {"folderId": folders[w["folder"]], "type": w["type"], "positionX": w["positionX"],
                                 "positionY": w["positionY"], "width": w["width"], "height": w["height"],
                                 "data": w["data"]}})
    r = apply_all(client, changes, dry=dry)
    ids = r.get("createdIds") or {}
    if not dry:
        show(client, pid, fid)
    widgets = {REFS[k]: v for k, v in ids.items() if k in REFS}
    return {"profile": pid, "folder": fid, "folders": folders, "widgets": widgets,
            "created": len(first) + len(made) + len(changes), "confirmations": r.get("confirmations") or []}


_OUR_URL = re.compile(r"http://127\.0\.0\.1:\d+/api/[a-z_]+\?key=")


def ours(data) -> bool:
    """Кнопку собрала программа: с пометкой "apc"; у первой сборки 1.3.0 пометки нет — тогда подпись из её
    переменных (apc_…) или команда её пульта (http://127.0.0.1:<порт>/api/<команда>?key=…)."""
    if not isinstance(data, dict):
        return False
    if data.get(MARK):
        return True
    if "vars." + PREFIX in str(data.get("label") or ""):
        return True
    return bool(_OUR_URL.search(json.dumps(data.get("flows") or [])))


def find_widgets(client: Client, folder_id: str) -> dict[str, str]:
    """Свои кнопки на странице (по пометке) → {ключ: id} — после перезапуска программы."""
    out = {}
    for w in client.items("widgets", folderId=folder_id):
        d = w.get("data")
        if isinstance(d, dict) and isinstance(d.get(MARK), str):
            out[d[MARK]] = w["id"]
    return out


def show(client: Client, profile_id: str, folder_id: str = "") -> None:
    """Телефоны — на страницу урока (без устройства — все подключённые). Не вышло — не беда: выберут сами."""
    try:
        client.call("run_action", {"integrationId": "app.macro-deck.deck", "actionId": "change-profile",
                                   "parameters": {"profileId": profile_id}})
        if folder_id:
            client.call("run_action", {"integrationId": "app.macro-deck.deck", "actionId": "change-folder",
                                       "parameters": {"folderId": folder_id}})
    except MacroDeckError as e:
        log.info("Macro Deck: переключить телефоны не вышло: %s", e)


class Sync:
    """Шлёт в Macro Deck в своём потоке (окно программы не ждёт): изменившиеся переменные (время — каждую секунду)
    и кнопки, у которых поменялся вид (нажали — подсветка; новый этап; шаг полосы) — одним пакетом: такая кнопка
    удаляется и создаётся заново на своей клетке (иначе телефон показывал бы прежнюю картинку, см. начало модуля).
    Id кнопок при первой отправке берутся у Macro Deck по пометке (запомненные могли устареть). Macro Deck закрыт
    или кнопку удалили руками — пробует снова раз в 5 с, найдя кнопки заново, и шлёт всё."""

    RETRY_S = 5.0

    def __init__(self, client: Client, widgets: dict[str, str] | None = None, folder: str | dict = "") -> None:
        self.client = client
        self.widgets = dict(widgets or {})
        # страницы: MAIN (главная) и экраны выбора → id; строкой — только главная (как до 1.3.1)
        self.folders = dict(folder) if isinstance(folder, dict) else ({MAIN: folder} if folder else {})
        self.folders = {k: v for k, v in self.folders.items() if v}
        self.folder = self.folders.get(MAIN, "")
        self._found = False
        self._q: queue.Queue = queue.Queue()
        self._sent: dict[str, str] = {}
        self._shown: dict[str, str] = {}       # ключ кнопки → её данные (JSON), что уже в Macro Deck
        self.error = ""
        self._stop = False
        self._th = threading.Thread(target=self._run, name="macrodeck-sync", daemon=True)
        self._th.start()

    def push(self, vals: dict[str, str], pages: dict[str, dict] | None = None) -> None:
        self._q.put((dict(vals), dict(pages or {})))

    def stop(self) -> None:
        self._stop = True
        self._q.put(None)

    def _find(self) -> None:
        found: dict[str, str] = {}
        for fid in dict.fromkeys(self.folders.values()):
            found.update(find_widgets(self.client, fid))
        self.widgets = found
        self._found = True

    def _send_pages(self, pages: dict[str, dict]) -> None:
        todo = {k: d for k, d in pages.items() if self._shown.get(k) != json.dumps(d, sort_keys=True)}
        if not todo:
            return
        if not self._found and self.folders:
            self._find()
        changes: list[dict] = []
        for k, d in todo.items():
            place = PLACE.get(k)
            fid = self.folders.get(place[0], "") if place else ""
            if not fid:
                continue                             # страницы нет (собрана прежней версией) — не на что ставить
            if k in self.widgets:
                changes.append({"op": "delete", "entity": "widget", "id": self.widgets[k]})
            _f, x, y, w = place
            changes.append({"op": "create", "entity": "widget", "ref": _ref(k), "data": {
                "folderId": fid, "type": "ActionButton", "positionX": x, "positionY": y, "width": w, "height": 1,
                "data": d}})
        if changes:
            r = apply_all(self.client, changes)
            for ref, wid in (r.get("createdIds") or {}).items():
                if ref in REFS:
                    self.widgets[REFS[ref]] = wid
        for k, d in todo.items():
            self._shown[k] = json.dumps(d, sort_keys=True)

    def _run(self) -> None:
        vals: dict[str, str] = {}
        pages: dict[str, dict] = {}
        down_until = 0.0
        while not self._stop:
            try:
                item = self._q.get(timeout=1.0)
            except queue.Empty:
                item = ({}, {})
            if item is None:
                break
            vals.update(item[0])
            pages.update(item[1])
            while True:                              # свежее — последнее в очереди
                try:
                    nxt = self._q.get_nowait()
                except queue.Empty:
                    break
                if nxt is None:
                    return
                vals.update(nxt[0])
                pages.update(nxt[1])
            if time.monotonic() < down_until:
                continue
            try:
                if pages:
                    self._send_pages(pages)
                    pages = {}
                for name, val in list(vals.items()):
                    if self._sent.get(name) != val:
                        self.client.set_var(name, val)
                        self._sent[name] = val
                    vals.pop(name, None)
                self.error = ""
            except MacroDeckError as e:
                if not self.error:
                    log.info("Macro Deck: %s", e)
                self.error = str(e)
                self._sent.clear()                   # потом — всё заново
                self._shown.clear()
                if self.folders:
                    self.widgets = {}                # кнопку могли удалить в Macro Deck — найти свои заново
                    self._found = False
                down_until = time.monotonic() + self.RETRY_S
