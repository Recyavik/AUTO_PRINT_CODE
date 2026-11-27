"""Macro Deck 3 (1.3): страница «Урок» на телефоне — собирается сама по ключу Macro Deck, время идёт само.

Связь — сервер Macro Deck для ИИ-помощников (MCP, http://127.0.0.1:8193/mcp, ключ «mdmcp_…» из Macro Deck:
Настройки → AI clients). Через него программа:
  • setup(): профиль «AutoPrintCode» (новый — создаёт), на его главной странице (7 × 3 — телефон боком): сверху
    прошедший, идущий (крупно, сколько осталось) и следующий этап; ниже Фон, Чёрный, Зарядка, Перерыв, Слайд,
    ◀ ▶; ещё ниже Подготовка, Звук, Микрофон. Кнопки шлют команды пульту программы (/api/<команда>?key=…).
    Повторно — только свои кнопки (помечены "apc") заново; кнопки, которые человек добавил сам, не трогаем. После
    сборки телефоны переключаются на этот профиль.
  • Каждая кнопка — картинка (deckart: стиль «Плитки» или «Контур», текст раскладывает программа). values() →
    переменные apc_img_* (картинки) и apc_* (текст — для своих кнопок); Sync шлёт изменившиеся в своём потоке
    (действие «Задать переменную»): нажатая кнопка подсвечена, время идёт.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
import urllib.error
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
STYLES = ("tiles", "outline")   # «Плитки», «Контур»
LAYOUT = 2                      # устройство страницы: сменили (кнопки, данные) — программа пересоберёт её сама

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
]
# верхний ряд: ключ → (x, ширина в ячейках)
INFO = [("prev", 0, 2), ("now", 2, 3), ("next", 5, 2)]
TEXT_VARS = ("prev", "now", "left", "next", "stage", "break_left")
IMAGE_KEYS = [k for k, _, _ in INFO] + [b[0] for b in BUTTONS]


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
        r = self.call("apply_changes", {"changes": changes, "dryRun": dry})
        if not r.get("valid", False):
            probs = "; ".join(f"{p.get('path', '')}: {p.get('message', '')}" for p in r.get("problems") or [])
            raise MacroDeckError("Macro Deck не принял страницу: " + (probs or json.dumps(r, ensure_ascii=False))[:400])
        return r

    def set_var(self, name: str, value: str) -> None:
        r = self.call("run_action", {"integrationId": "app.macro-deck.variables", "actionId": "set-variable",
                                     "parameters": {"variable": name, "value": value}})
        if str(r.get("status", "")).lower() not in ("succeeded", "success", "accepted", ""):
            raise MacroDeckError(f"переменная {name}: {r.get('message') or r.get('status')}")


class _Expired(Exception):
    pass


# ---------------------------------------------------------------- страница
def _flow(cid: str, url: str) -> list[dict]:
    return [{"triggerId": "onShortPress", "triggerType": "onShortPress", "children": [{
        "id": "apc-" + cid, "type": "action", "blockType": "app.macro-deck.http.send-request",
        "integrationId": "app.macro-deck.http", "actionId": "send-request",
        "parameters": [{"name": "method", "value": "GET"}, {"name": "url", "value": url},
                       {"name": "timeout", "value": 5000}]}]}]


POS = {k: (x, 0, w) for k, x, w in INFO} | {b[0]: (b[1], b[2], 1) for b in BUTTONS}
CMD = {b[0]: b[3] for b in BUTTONS}
TIME_SIZE = 30                  # кегль времени этапа (подпись Macro Deck), отсчёта перерыва — BREAK_SIZE
BREAK_SIZE = 20


def _cmd_url(base: str, cmd: str) -> str:
    root, _, q = base.partition("?")
    return f"{root}{cmd}" + ("?" + q if q else "")


def page(st: dict, style: str = "tiles", base: str = "") -> dict[str, dict]:
    """Данные каждой кнопки страницы целиком (Macro Deck заменяет данные кнопки целиком): картинка нынешнего вида
    (подсветка, этапы) и, у кнопок, команда пульта. Время этапа и отсчёт перерыва — подписью из переменной (её
    Macro Deck обновляет сам каждую секунду), в пустой середине картинки."""
    style = style if style in deckart.STYLES else deckart.DEFAULT_STYLE
    imgs = images(st, style)
    out: dict[str, dict] = {}
    for cid in IMAGE_KEYS:
        data = {"label": "", "imageUrl": deckart.data_url(imgs[cid]), "backgroundColor": "transparent",
                "iconDisplay": {"fit": "contain", "zoom": 100}, "labelShadow": False, MARK: cid}
        if cid == "now" and st.get("left") and not st.get("off"):
            left_s = int(st.get("left_s") or 0)
            warn = st.get("phase") == "live" and 0 < left_s <= 60
            data.update(label="{{ vars.apc_left }}", labelPosition="center", textAlign="center", fontSize=TIME_SIZE,
                        labelColor=deckart.time_color(warn, style))
        if cid == "break" and (st.get("screen") == "break") and st.get("break_left") and not st.get("off"):
            data.update(label="{{ vars.apc_break_left }}", labelPosition="bottom", textAlign="center",
                        fontSize=BREAK_SIZE, labelColor=deckart.timer_color(style))
        if cid in CMD and base:
            data["flows"] = _flow(cid, _cmd_url(base, CMD[cid]))
        out[cid] = data
    return out


def layout(base: str, st: dict | None = None, style: str = "tiles") -> list[dict]:
    """Кнопки страницы (без folderId) в нынешнем виде. base — «http://127.0.0.1:8791/api/?key=…»."""
    out = []
    for cid, data in page(st or {}, style, base).items():
        x, y, w = POS[cid]
        out.append({"type": "ActionButton", "positionX": x, "positionY": y, "width": w, "height": 1, "data": data})
    return out


def variables() -> list[tuple[str, str, str]]:
    """(имя, тип, начальное значение) переменных страницы (текст: подписи и для своих кнопок человека)."""
    return [(PREFIX + k, "text", "") for k in TEXT_VARS]


def images(st: dict, style: str = "tiles") -> dict[str, str]:
    """Состояние пульта (DeckControl.state()) → картинки кнопок (SVG) по ключам IMAGE_KEYS. Время этапа и отсчёт
    перерыва на картинке не рисуются (их пишет Macro Deck подписью) — ход этапа полосой, с шагом 5 %."""
    style = style if style in deckart.STYLES else deckart.DEFAULT_STYLE
    if st.get("off"):
        out = {k: deckart.stage("", w, style=style) for k, _, w in INFO}
        out["now"] = deckart.now(st.get("now") or "Пульт выключен", "", style=style)
        for cid, _x, _y, _cmd, icon, label in BUTTONS:
            out[cid] = deckart.button(icon, label, "off", style=style)
        return out
    left_s = int(st.get("left_s") or 0)
    warn = st.get("phase") == "live" and 0 < left_s <= 60
    frac = round(float(st.get("frac") or 0) * 20) / 20
    out = {"prev": deckart.stage(st.get("prev") or "", 2, "left", style),
           "now": deckart.now(st.get("now") or "", st.get("left") or "", frac, warn, "", 3, style, draw_left=False),
           "next": deckart.stage(st.get("next") or "", 2, "right", style)}
    screen = st.get("screen") or "idle"
    active = {"bg": "idle", "black": "black", "ex": "exercise", "break": "break", "slide": "slide"}
    for cid, _x, _y, _cmd, icon, label in BUTTONS:
        mode, sub = "", ""
        if cid in active and screen == active[cid]:
            mode = "on"
        if cid == "break" and screen == "break" and st.get("break_left"):
            out[cid] = deckart.timer("", style=style, draw_text=False)
            continue
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
    return out


def values(st: dict, style: str = "tiles") -> dict[str, str]:
    """Состояние пульта → текстовые переменные страницы (время, отсчёт перерыва, этапы — и для своих кнопок)."""
    v = {PREFIX + k: str(st.get(k) or "") for k in ("prev", "now", "left", "next")}
    v[PREFIX + "stage"] = str(st.get("stage_text") or "")
    v[PREFIX + "break_left"] = str(st.get("break_left") or "")
    return v


def _home_folder(client: Client, pid: str) -> dict | None:
    """Главная страница профиля: та, что открывается на телефоне (isDefault), иначе первая."""
    folders = [f for f in client.items("folders", profileId=pid) if f.get("profileId", pid) == pid]
    if not folders:
        return None
    return next((f for f in folders if f.get("isDefault")), None) or min(folders, key=lambda f: f.get("order") or 0)


def setup(client: Client, base: str, profile_id: str = "", dry: bool = False, st: dict | None = None,
          style: str = "tiles") -> dict:
    """Собрать страницу: профиль (свой — по id, иначе по имени, иначе новый), на его главной странице — свои
    кнопки заново в нынешнем виде (чужие не трогаем), переменные (недостающие — создать); телефоны — на этот
    профиль. → {"profile": id, "folder": id, "widgets": {ключ: id кнопки}, "created": n}."""
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
        return {"profile": "", "folder": "", "created": len(first), "confirmations": []}
    home = _home_folder(client, pid)
    changes: list[dict] = []
    if home is None:
        changes.append({"op": "create", "entity": "folder", "ref": "f",
                        "data": {"profileId": pid, "name": FOLDER_NAME}})
        fid = "@f"
    else:
        fid = home["id"]
        if home.get("name") != FOLDER_NAME:
            changes.append({"op": "update", "entity": "folder", "id": fid, "data": {"name": FOLDER_NAME}})
        for w in client.items("widgets", folderId=fid):
            if isinstance(w.get("data"), dict) and w["data"].get(MARK):
                changes.append({"op": "delete", "entity": "widget", "id": w["id"]})
    # страница прежней версии 1.3 («Урок» отдельной папкой рядом с пустой главной) — убрать
    for f in client.items("folders", profileId=pid):
        if home is not None and f.get("id") != fid and f.get("name") == FOLDER_NAME and f.get("profileId", pid) == pid:
            changes.append({"op": "delete", "entity": "folder", "id": f["id"]})
    for w in layout(base, st, style):
        changes.append({"op": "create", "entity": "widget", "ref": "w_" + w["data"][MARK],
                        "data": {"folderId": fid, **w}})
    r = client.apply(changes, dry=dry)
    ids = r.get("createdIds") or {}
    fid = ids.get("f", fid) if fid == "@f" else fid
    if not dry:
        show(client, pid, fid)
    widgets = {k[2:]: v for k, v in ids.items() if k.startswith("w_")}
    return {"profile": pid, "folder": fid, "widgets": widgets, "created": len(first) + len(changes),
            "confirmations": r.get("confirmations") or []}


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
    и кнопки, у которых поменялся вид (нажали — подсветка; новый этап; шаг полосы) — одним пакетом, целиком.
    Macro Deck закрыт — пробует снова раз в 5 с и тогда шлёт всё заново."""

    RETRY_S = 5.0

    def __init__(self, client: Client, widgets: dict[str, str] | None = None, folder: str = "") -> None:
        self.client = client
        self.widgets = dict(widgets or {})
        self.folder = folder
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

    def _send_pages(self, pages: dict[str, dict]) -> None:
        todo = {k: d for k, d in pages.items() if self._shown.get(k) != json.dumps(d, sort_keys=True)}
        if not todo:
            return
        if any(k not in self.widgets for k in todo) and self.folder:
            self.widgets.update(find_widgets(self.client, self.folder))
        changes = [{"op": "update", "entity": "widget", "id": self.widgets[k], "data": {"data": d}}
                   for k, d in todo.items() if k in self.widgets]
        if changes:
            self.client.apply(changes)
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
                if self.folder:
                    self.widgets = {}                # кнопку могли удалить в Macro Deck — найти свои заново
                down_until = time.monotonic() + self.RETRY_S
