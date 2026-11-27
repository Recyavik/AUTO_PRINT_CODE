"""Macro Deck 3 (1.3): страница «Урок» на телефоне — собирается сама по ключу Macro Deck, время идёт само.

Связь — сервер Macro Deck для ИИ-помощников (MCP, http://127.0.0.1:8193/mcp, ключ «mdmcp_…» из Macro Deck:
Настройки → AI clients). Через него программа:
  • setup(): создаёт профиль «AutoPrintCode» с папкой «Урок» (7 × 3 — телефон боком): сверху прошедший, идущий
    (крупно, сколько осталось) и следующий этап; ниже Фон, Чёрный, Зарядка, Перерыв, Слайд, ◀ ▶; ещё ниже
    Подготовка, Звук, Микрофон. Кнопки шлют команды пульту программы (/api/<команда>?key=…). Повторная настройка
    пересобирает папку «Урок» (профиль тот же; свои папки и кнопки человека не трогаем).
  • values() → переменные apc_*: подписи и цвета кнопок; Sync шлёт изменившиеся раз в секунду в своём потоке
    (действие «Задать переменную») — нажатая кнопка подсвечена, время идёт.
"""
from __future__ import annotations

import base64
import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

MCP_URL = "http://127.0.0.1:8193/mcp"
PROTOCOL = "2025-11-25"
PROFILE_NAME = "AutoPrintCode"
FOLDER_NAME = "Урок"
COLS, ROWS = 7, 3
PREFIX = "apc_"

# цвета — как в окне программы (тёмная тема)
GROUND, PANEL, RAISED = "#161A22", "#1C212B", "#242A36"
TEXT, DIM, FAINT, OFF = "#E9EDF3", "#A6AFBE", "#858FA0", "#4A5160"
ACCENT, ON_ACCENT, LIVE, ON_LIVE = "#F2B54D", "#1E1606", "#FF6B5E", "#2A0B08"

# значки окна программы (icons.js), 24×24, линия 1.8
ICONS = {
    "image": '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><circle cx="9" cy="10" r="1.7"/>'
             '<path d="M21 16l-5-5-9.5 8.5"/>',
    "blackout": '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><rect x="6.5" y="8" width="11" height="8" '
                'rx="1" fill="currentColor" stroke="none"/>',
    "activity": '<path d="M3 12h4l3-7 4 14 3-7h4"/>',
    "cup": '<path d="M4.5 9h12v5a5 5 0 0 1-5 5h-2a5 5 0 0 1-5-5z"/><path d="M16.5 10.5h1.3a2.3 2.3 0 0 1 0 4.6h-1.3"/>'
           '<path d="M8.5 3.5v2.5M12.5 3.5v2.5"/>',
    "slide": '<rect x="3" y="4.5" width="18" height="13" rx="2.5"/><path d="M10.5 8.5v5l4-2.5z"/><path d="M9 21h6"/>',
    "prev": '<path d="M14.5 6l-6 6 6 6"/>',
    "next": '<path d="M9.5 6l6 6-6 6"/>',
    "open": '<path d="M14 4.5h5.5V10M19.5 4.5l-8 8"/><path d="M18 14v4.5A1.5 1.5 0 0 1 16.5 20h-11A1.5 1.5 0 0 1 4 '
            '18.5v-11A1.5 1.5 0 0 1 5.5 6H10"/>',
    "volume": '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
}

# кнопки: ключ → (x, y, команда пульта, значок, подпись)
BUTTONS = [
    ("bg", 0, 1, "background", "image", "Фон"),
    ("black", 1, 1, "black", "blackout", "Чёрный"),
    ("ex", 2, 1, "exercise", "activity", "Зарядка"),
    ("break", 3, 1, "break", "cup", "{{ vars.apc_break_label }}"),
    ("slide", 4, 1, "slide", "slide", "{{ vars.apc_slide_label }}"),
    ("prev_s", 5, 1, "slide_prev", "prev", ""),
    ("next_s", 6, 1, "slide_next", "next", ""),
    ("prepare", 0, 2, "prepare", "open", "Подготовка"),
    ("sound", 1, 2, "sound", "volume", "{{ vars.apc_sound_label }}"),
    ("mic", 2, 2, "mic", "mic", "{{ vars.apc_mic_label }}"),
]
TEXT_VARS = ("prev", "now", "left", "next", "stage", "break_label", "slide_label", "sound_label", "mic_label")
COLOR_KEYS = [b[0] for b in BUTTONS] + ["left"]


class MacroDeckError(Exception):
    """Macro Deck не ответил или отказал — текст для человека."""


def _icon_url(name: str) -> str:
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" '
           f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" color="#FFFFFF">{ICONS[name]}</svg>')
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


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
def _button(cid: str, x: int, y: int, url: str, icon: str, label: str, w: int = 1) -> dict:
    flows = [{"triggerId": "onShortPress", "triggerType": "onShortPress", "children": [{
        "id": "apc-" + cid, "type": "action", "blockType": "app.macro-deck.http.send-request",
        "integrationId": "app.macro-deck.http", "actionId": "send-request",
        "parameters": [{"name": "method", "value": "GET"}, {"name": "url", "value": url},
                       {"name": "timeout", "value": 5000}]}]}]
    data = {"label": label, "imageUrl": _icon_url(icon), "iconDisplay": {"fit": "contain", "zoom": 46, "offsetY": -12},
            "labelPosition": "bottom", "fontSize": 15, "labelShadow": False,
            "backgroundColor": "{{ vars.apc_c_%s }}" % cid, "labelColor": "{{ vars.apc_f_%s }}" % cid,
            "iconColor": "{{ vars.apc_f_%s }}" % cid, "flows": flows}
    return {"type": "ActionButton", "positionX": x, "positionY": y, "width": w, "height": 1, "data": data}


def _info(x: int, w: int, label: str, size: int, color: str) -> dict:
    return {"type": "ActionButton", "positionX": x, "positionY": 0, "width": w, "height": 1,
            "data": {"label": label, "fontSize": size, "labelColor": color, "backgroundColor": PANEL,
                     "labelPosition": "center", "textAlign": "center", "labelShadow": False}}


def layout(base: str) -> list[dict]:
    """Кнопки папки «Урок» (без folderId). base — «http://127.0.0.1:8791/api/», ключ — в каждой ссылке."""
    key_q = base.split("?", 1)
    root, q = key_q[0], ("?" + key_q[1]) if len(key_q) > 1 else ""
    out = [_info(0, 2, "{{ vars.apc_prev }}", 15, FAINT),
           _info(2, 3, "{{ vars.apc_now }}\n{{ vars.apc_left }}", 26, "{{ vars.apc_f_left }}"),
           _info(5, 2, "{{ vars.apc_next }}", 15, FAINT)]
    for cid, x, y, cmd, icon, label in BUTTONS:
        out.append(_button(cid, x, y, f"{root}{cmd}{q}", icon, label))
    return out


def variables() -> list[tuple[str, str, str]]:
    """(имя, тип, начальное значение) переменных страницы."""
    out = [(PREFIX + k, "text", "") for k in TEXT_VARS]
    for k in COLOR_KEYS:
        out.append((PREFIX + "c_" + k, "color", RAISED))
        out.append((PREFIX + "f_" + k, "color", TEXT))
    return out


def values(st: dict) -> dict[str, str]:
    """Состояние пульта (DeckControl.state()) → значения переменных страницы."""
    v = {PREFIX + k: str(st.get(k) or "") for k in ("prev", "now", "left", "next")}
    v[PREFIX + "stage"] = str(st.get("stage_text") or "")
    v[PREFIX + "break_label"] = st.get("break_left") or "Перерыв"
    v[PREFIX + "slide_label"] = ("Слайд " + st["slide_text"].replace(" ", "")) if st.get("slide_text") else "Слайд"
    v[PREFIX + "mic_label"] = "Микрофон выкл." if st.get("mic_muted") else "Микрофон"
    v[PREFIX + "sound_label"] = "Звук выкл." if st.get("sound_muted") else "Звук"
    screen = st.get("screen") or "idle"
    on = {"bg": screen == "idle", "black": screen == "black", "ex": screen == "exercise", "break": screen == "break",
          "slide": screen == "slide"}
    for k, active in on.items():
        v[PREFIX + "c_" + k], v[PREFIX + "f_" + k] = (ACCENT, ON_ACCENT) if active else (RAISED, TEXT)
    arrows = bool(st.get("slide"))
    for k in ("prev_s", "next_s"):
        v[PREFIX + "c_" + k], v[PREFIX + "f_" + k] = (RAISED, TEXT) if arrows else (PANEL, OFF)
    v[PREFIX + "c_prepare"], v[PREFIX + "f_prepare"] = RAISED, TEXT
    for k in ("mic", "sound"):
        muted = bool(st.get(k + "_muted"))
        v[PREFIX + "c_" + k], v[PREFIX + "f_" + k] = (LIVE, ON_LIVE) if muted else (RAISED, TEXT)
    left = int(st.get("left_s") or 0)
    v[PREFIX + "c_left"] = PANEL
    v[PREFIX + "f_left"] = LIVE if st.get("phase") == "live" and 0 < left <= 60 else TEXT
    if st.get("off"):
        v = {k: ("" if k[len(PREFIX):] in TEXT_VARS else val) for k, val in v.items()}
        v[PREFIX + "now"] = st.get("now") or "Программа закрыта"
    return v


def setup(client: Client, base: str, profile_id: str = "", dry: bool = False) -> dict:
    """Собрать страницу: профиль (свой — по id, иначе по имени, иначе новый), папку «Урок» заново, переменные
    (недостающие — создать). → {"profile": id, "folder": id, "created": n}."""
    profiles = client.items("profiles")
    prof = next((p for p in profiles if p.get("id") == profile_id), None) if profile_id else None
    prof = prof or next((p for p in profiles if p.get("name") == PROFILE_NAME), None)
    changes: list[dict] = []
    if prof is None:
        changes.append({"op": "create", "entity": "profile", "ref": "p",
                        "data": {"name": PROFILE_NAME, "defaultRows": ROWS, "defaultColumns": COLS}})
        pid = "@p"
    else:
        pid = prof["id"]
        for f in client.items("folders", profileId=pid):
            if f.get("name") == FOLDER_NAME:
                changes.append({"op": "delete", "entity": "folder", "id": f["id"]})
    changes.append({"op": "create", "entity": "folder", "ref": "f",
                    "data": {"profileId": pid, "name": FOLDER_NAME, "rows": ROWS, "columns": COLS,
                             "backgroundColor": GROUND}})
    have = {v.get("name"): v for v in client.items("variables")}
    for name, typ, init in variables():
        if name not in have:
            changes.append({"op": "create", "entity": "variable",
                            "data": {"name": name, "scope": "global", "type": typ, "value": init}})
    for i, w in enumerate(layout(base)):
        changes.append({"op": "create", "entity": "widget", "ref": f"w{i}", "data": {"folderId": "@f", **w}})
    r = client.apply(changes, dry=dry)
    ids = r.get("createdIds") or {}
    return {"profile": ids.get("p", "") if pid == "@p" else pid, "folder": ids.get("f", ""),
            "created": len(changes), "confirmations": r.get("confirmations") or []}


class Sync:
    """Шлёт изменившиеся значения в Macro Deck в своём потоке (окно программы не ждёт). Macro Deck закрыт —
    пробует снова раз в 5 с и тогда шлёт всё заново."""

    RETRY_S = 5.0

    def __init__(self, client: Client) -> None:
        self.client = client
        self._q: queue.Queue = queue.Queue()
        self._sent: dict[str, str] = {}
        self.error = ""
        self._stop = False
        self._th = threading.Thread(target=self._run, name="macrodeck-sync", daemon=True)
        self._th.start()

    def push(self, vals: dict[str, str]) -> None:
        self._q.put(dict(vals))

    def stop(self) -> None:
        self._stop = True
        self._q.put(None)

    def _run(self) -> None:
        pending: dict[str, str] = {}
        down_until = 0.0
        while not self._stop:
            try:
                item = self._q.get(timeout=1.0)
            except queue.Empty:
                item = {}
            if item is None:
                break
            pending.update(item)
            while True:                              # свежее значение — последнее в очереди
                try:
                    nxt = self._q.get_nowait()
                except queue.Empty:
                    break
                if nxt is None:
                    return
                pending.update(nxt)
            if time.monotonic() < down_until:
                continue
            for name, val in list(pending.items()):
                if self._sent.get(name) == val:
                    pending.pop(name, None)
                    continue
                try:
                    self.client.set_var(name, val)
                    self._sent[name] = val
                    pending.pop(name, None)
                    self.error = ""
                except MacroDeckError as e:
                    if not self.error:
                        log.info("Macro Deck: %s", e)
                    self.error = str(e)
                    self._sent.clear()               # потом — всё заново
                    down_until = time.monotonic() + self.RETRY_S
                    break
