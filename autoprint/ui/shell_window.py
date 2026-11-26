"""Окно программы — отдельный процесс Electron (папка window/), внутри — страница /app с локального сервера.

С 1.2 окно не Qt: QtWebEngine рисовал страницу «за кадром», и край окна дёргался, когда его тянули. Electron (тот же
движок, что у Chrome и VS Code) рисует страницу в своём окне. Программа (этот модуль) запускает окно и говорит с ним
по именованному каналу (QLocalServer) строками JSON — см. window/main.js.

ShellWindow — то, что остальная программа знала у прежнего окна Qt: показать / скрыть / свернуть / развернуть,
состояние, заголовок, маленький режим, «поверх всех окон», печать, системные окна выбора файлов. Состояние окна
(видно, свёрнуто, развёрнуто, в фокусе) и его места на экране — зеркало того, что сообщает окно; команды уходят
окну. Окно упало — запускается снова (до 3 раз за минуту).

launch=False — без процесса (тесты): команды копятся в .sent, состояние меняется «как будто».
hidden — окно Electron не показывается никогда (тесты, --selftest).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import struct
import sys
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QEventLoop, QIODevice, QObject, QProcess, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QLocalServer

from .. import APP_NAME
from .theme import theme

log = logging.getLogger(__name__)

FAIL_PREFIX = "Не удалось запустить окно программы"
EXE_NAME = "AutoPrintCodeWindow.exe"
ROOT = Path(__file__).resolve().parents[2]
RESTARTS, RESTART_WINDOW_S = 3, 60
PDF_TIMEOUT_MS, PRINT_TIMEOUT_MS = 120_000, 600_000
APP_ID = "autoprintcode.app"


def _bg() -> str:
    return "#161A22" if theme.dark else "#EEF0F3"


def window_command() -> tuple[str, list[str]] | None:
    """Чем запускать окно. Собранная программа — window\\AutoPrintCodeWindow.exe рядом с AutoPrintCode.exe;
    из исходников — electron.exe из window\\node_modules (npm install в папке window). AUTOPRINT_WINDOW_EXE —
    свой exe (и AUTOPRINT_WINDOW_APP — папка окна для electron.exe)."""
    env = os.environ.get("AUTOPRINT_WINDOW_EXE")
    if env:
        app_dir = os.environ.get("AUTOPRINT_WINDOW_APP")
        return env, [app_dir] if app_dir else []
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve().parent / "window" / EXE_NAME
        return (str(exe), []) if exe.is_file() else None
    exe = ROOT / "window" / "node_modules" / "electron" / "dist" / "electron.exe"
    return (str(exe), [str(ROOT / "window")]) if exe.is_file() else None


def relaunch_command() -> str:
    """Команда для закреплённой кнопки на панели задач — запуск программы, а не окна."""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    exe = Path(sys.executable)
    gui = exe.with_name("pythonw.exe")
    return f'"{gui if gui.is_file() else exe}" "{ROOT / "app.py"}"'


# ---------------------------------------------------------------- места окна в настройках
def _rect(d, with_max: bool) -> dict | None:
    if not isinstance(d, dict):
        return None
    try:
        r = {k: int(d[k]) for k in ("x", "y", "w", "h")}
    except (KeyError, TypeError, ValueError):
        return None
    if r["w"] <= 0 or r["h"] <= 0:
        return None
    if with_max:
        r["max"] = bool(d.get("max"))
    return r


def _from_qt(blob: str) -> dict | None:
    """Место окна, сохранённое Qt до 1.2 (QWidget.saveGeometry, base64) → {x, y, w, h, max}. Формат Qt 6:
    магия 0x1D9D0CB, версия, рамка, обычный размер (QRect: left, top, right, bottom), экран, развёрнуто…"""
    try:
        raw = base64.b64decode(blob, validate=True)
        magic, _major, _minor = struct.unpack_from(">IHH", raw, 0)
        if magic != 0x1D9D0CB:
            return None
        left, top, right, bottom = struct.unpack_from(">4i", raw, 24)       # обычный (не развёрнутый) размер
        maximized = struct.unpack_from(">B", raw, 44)[0]
    except (ValueError, struct.error):
        return None
    w, h = right - left + 1, bottom - top + 1
    if w <= 0 or h <= 0:
        return None
    return {"x": left, "y": top, "w": w, "h": h, "max": bool(maximized)}


def parse_place(value: str, with_max: bool) -> dict | None:
    """Строка из настроек → место окна: JSON (1.2) или прежняя запись Qt; пусто или испорчено — None."""
    if not value:
        return None
    try:
        d = json.loads(value)
    except ValueError:
        d = _from_qt(value)
    r = _rect(d, with_max)
    return r


def qt_filters(flt: str) -> list[dict]:
    """Фильтр окна выбора файлов в записи Qt («PDF (*.pdf);;Все файлы (*.*)») → фильтры Electron."""
    out = []
    for part in str(flt or "").split(";;"):
        part = part.strip()
        if not part:
            continue
        name, _, pats = part.partition("(")
        exts = []
        for p in pats.rstrip(")").split():
            p = p.strip()
            if p in ("*", "*.*"):
                exts.append("*")
            elif p.startswith("*."):
                exts.append(p[2:])
        if exts:
            out.append({"name": name.strip() or "Файлы", "extensions": exts})
    return out


class CloseEvent:
    """Как QCloseEvent для close_handler программы: ignore() — окно не закрывать (в трей)."""

    def __init__(self) -> None:
        self._accepted = True

    def accept(self) -> None:
        self._accepted = True

    def ignore(self) -> None:
        self._accepted = False

    def isAccepted(self) -> bool:
        return self._accepted


class ShellWindow(QObject):
    loaded = Signal()           # страница загрузилась
    ready = Signal()            # прежнее имя: загрузилась
    page_ready = Signal()       # и её скрипты запустились (window.__ready)
    page_failed = Signal(str)   # не загрузилась или упала — текст для человека
    state_changed = Signal()    # видно / свёрнуто / развёрнуто / маленький режим
    geometry_changed = Signal()  # места окна на экране (для настроек)

    close_handler = None        # App.on_window_close: в трей или выход

    def __init__(self, app, launch: bool = True, hidden: bool | None = None) -> None:
        super().__init__()
        self.app = app
        self.launch = launch
        self.hidden = bool(os.environ.get("AUTOPRINT_WINDOW_HIDDEN")) if hidden is None else bool(hidden)
        self.compact = False
        self.state = {"visible": False, "minimized": False, "maximized": False, "focused": False}
        self.places: dict = {"big": None, "small": None}
        self.title = APP_NAME
        self.top = False
        self.sent: list[dict] = []          # launch=False: что ушло бы окну
        self.pid = 0
        self.hwnd = 0
        self.failure = ""
        self._loaded = False
        self._taskbar_icon = ""
        self._url, self._why = "", ""
        self._queue: list[dict] = []        # до подключения окна
        self._sock = None
        self._inbox = b""
        self._server: QLocalServer | None = None
        self._proc: QProcess | None = None
        self._pending: dict[int, tuple] = {}
        self._seq = 0
        self._starts: list[float] = []
        self._stopping = False
        self._wanted = False                # load() был: окно должно быть запущено
        self._restarting = False            # окно перезапускается после сбоя: показать, не забирая клавиатуру
        self._log_rotated = False
        self._npm: QProcess | None = None    # из исходников окна ещё нет — ставится (npm ci в window)
        self._npm_tried = False
        self.apply_pin()

    # ------------------------------------------------------------ канал
    def _send(self, msg: dict) -> None:
        if not self.launch:
            self.sent.append(msg)
            return
        if self._sock is None:
            # окна ещё (или уже) нет: состояние (видно, заголовок, режим, «поверх всех») уйдёт в init,
            # ждут только команды с ответом
            if "id" in msg and self._proc is not None:
                self._queue.append(msg)
            return
        self._write(msg)

    def _write(self, msg: dict) -> None:
        try:
            self._sock.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
            self._sock.flush()
        except RuntimeError:            # сокет уже удалён — окно закрылось
            pass

    def _show_mode(self) -> str:
        """Как показать окно, когда оно запустится: "focus" — вперёд; "inactive" — окно перезапустилось, пока человек
        работал в другом окне (печать кода!) — не забирать клавиатуру; "" — не показывать (скрыто в трей или
        свёрнуто на время набора: покажется, когда попросят)."""
        st = self.state
        if not st["visible"] or st["minimized"]:
            return ""
        if self._restarting and not st["focused"]:
            return "inactive"
        return "focus"

    def _init_msg(self) -> dict:
        return {"op": "init", "url": self._url, "why": self._why, "bg": _bg(), "dark": bool(theme.dark),
                "show": self._show_mode(),
                "title": self.title, "icon": self._taskbar_icon, "top": self.top, "compact": self.compact,
                "big": self.places.get("big"), "small": self.places.get("small"),
                "appDetails": {"appId": APP_ID, "appIconPath": self._taskbar_icon, "appIconIndex": 0,
                               "relaunchCommand": relaunch_command(), "relaunchDisplayName": APP_NAME}}

    def _on_connection(self) -> None:
        sock = self._server.nextPendingConnection() if self._server is not None else None
        if sock is None:
            return
        if self._sock is not None:          # второе подключение — не наше
            sock.disconnectFromServer()
            return
        self._sock = sock
        sock.readyRead.connect(self._on_read)
        self._write(self._init_msg())
        if self._restarting and self.state["minimized"]:
            # было свёрнуто (на время набора): новое окно не показано — «показать» потом развернёт его
            self.state = dict(self.state, visible=False, minimized=False, focused=False)
        self._restarting = False
        queue, self._queue = self._queue, []
        for m in queue:
            self._write(m)

    def _on_read(self) -> None:
        if self._sock is None:
            return
        self._inbox += bytes(self._sock.readAll())
        while b"\n" in self._inbox:
            line, self._inbox = self._inbox.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                m = json.loads(line.decode("utf-8"))
            except ValueError:
                log.warning("Окно программы: непонятная строка %r", line[:200])
                continue
            if isinstance(m, dict):
                self.on_message(m)

    def on_message(self, m: dict) -> None:
        """Сообщение от окна (тесты зовут напрямую)."""
        ev = m.get("ev")
        if ev == "reply":
            box = self._pending.pop(m.get("id"), None)
            if box is not None:
                loop, res, cb = box
                res.update(ok=bool(m.get("ok")), value=m.get("value"), error=str(m.get("error") or ""))
                if loop is not None:
                    loop.quit()
                elif cb is not None and res["ok"]:
                    cb(res["value"])
        elif ev == "state":
            self._on_state(m)
        elif ev == "geometry":
            self.places = {"big": _rect(m.get("big"), True) or self.places.get("big"),
                           "small": _rect(m.get("small"), False) or self.places.get("small")}
            self.geometry_changed.emit()
        elif ev == "hello":
            self.pid = int(m.get("pid") or 0)
            log.info("Окно программы: Electron %s (Chromium %s)", m.get("electron"), m.get("chrome"))
            if self.state.get("visible"):    # запуск программы: окно выйдет вперёд, а не мигнёт кнопкой на панели задач
                self._allow_foreground()
        elif ev == "hwnd":
            self.hwnd = int(m.get("hwnd") or 0)
        elif ev == "loaded":
            self._loaded = True
            self.failure = ""
            self.loaded.emit()
            self.ready.emit()
        elif ev == "page_ready":
            self.page_ready.emit()
        elif ev == "failed":
            self._loaded = False
            self.failure = f"{FAIL_PREFIX}: {m.get('why') or ''}"
            log.warning("%s %s", self.failure, m.get("detail") or "")
            self.page_failed.emit(self.failure)
        elif ev == "close":
            self.close()
        elif ev == "retry":                  # «Повторить» на странице сбоя: сервер — заново, адрес — окну
            self.load()
        elif ev == "drop":
            paths = [str(p) for p in (m.get("paths") or []) if p][:50]
            drop = getattr(self.app, "drop", None)
            if paths and callable(drop):
                drop(paths)
        elif ev == "open_url":
            url = QUrl(str(m.get("url") or ""))
            if url.scheme() in ("http", "https", "mailto"):
                QDesktopServices.openUrl(url)
        elif ev == "open_log":
            from ..logs import LOG_FILE
            if LOG_FILE.exists():
                os.startfile(LOG_FILE)
        elif ev == "log":
            level = {"error": logging.ERROR, "warning": logging.WARNING}.get(str(m.get("level")), logging.INFO)
            log.log(level, "%s", str(m.get("text") or "")[:2000])

    def _on_state(self, m: dict) -> None:
        new = {k: bool(m.get(k)) for k in ("visible", "minimized", "maximized", "focused")}
        changed = new != self.state
        self.state = new
        if changed:
            self.state_changed.emit()

    # ------------------------------------------------------------ процесс окна
    def page_url(self) -> str:
        server = self.app.efir.server
        return server.url + "app" if server.running and server.url else ""

    def load(self) -> None:
        """Открыть страницу (запустить окно, если его ещё нет). Сервер не запустился — окно покажет сообщение."""
        url = self.page_url()
        if not url:
            ensure = getattr(self.app.efir, "ensure_server", None)
            if callable(ensure) and ensure():
                url = self.page_url()
        self._url = url
        self._why = "" if url else "сервер окна не запустился (порты 8791–8799 заняты?)."
        self._wanted = True
        if not self.launch:
            return
        if self._proc is None:
            self._start()
        else:
            self._send({"op": "reload", "url": url, "why": self._why})

    retry = load

    def _start(self) -> None:
        if self._npm is not None:            # окно ставится — запустится, когда npm закончит
            return
        cmd = window_command()
        if cmd is None and self._install_window():
            return
        if cmd is None:
            self._give_up("не найдено окно программы (папка window). Переустановите программу.")
            return
        exe, args = cmd
        if self._server is None:
            self._server = QLocalServer(self)
            self._server.newConnection.connect(self._on_connection)
            name = f"autoprint-window-{os.getpid()}-{uuid.uuid4().hex[:8]}"
            if not self._server.listen(name):
                self._give_up(f"канал окна не открылся ({self._server.errorString()}).")
                return
        from ..storage import DATA_DIR
        args = args + [f"--autoprint-pipe={self._server.fullServerName()}",
                       f"--autoprint-data={DATA_DIR / 'web' / 'window'}"]
        if self.hidden:
            args.append("--autoprint-hidden=1")
        proc = QProcess(self)
        proc.setProgram(exe)
        proc.setArguments(args)
        out = DATA_DIR / "logs" / "window.log"           # сообщения Chromium — для разбора сбоев
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            if not self._log_rotated:                    # прошлый запуск программы — в window.log.1; перезапуски
                self._log_rotated = True                 # окна после сбоя дописывают (видно, отчего упало)
                if out.exists():
                    os.replace(out, out.with_name("window.log.1"))
            proc.setStandardOutputFile(str(out), QIODevice.OpenModeFlag.Append)
            proc.setStandardErrorFile(str(out), QIODevice.OpenModeFlag.Append)
        except OSError:
            proc.setStandardOutputFile(QProcess.nullDevice())
            proc.setStandardErrorFile(QProcess.nullDevice())
        proc.finished.connect(self._on_exit)
        proc.errorOccurred.connect(self._on_proc_error)
        self._proc = proc
        self._starts = [t for t in self._starts if time.monotonic() - t < RESTART_WINDOW_S] + [time.monotonic()]
        proc.start()

    def _install_window(self) -> bool:
        """Программа из исходников (git, архив, обновление 1.1 → 1.2): окна Electron ещё нет — поставить его
        (npm ci в папке window, один раз; нужен Node.js). True — ставится, окно запустится потом."""
        if getattr(sys, "frozen", False) or self._npm_tried:
            return False
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if not npm or not (ROOT / "window" / "package-lock.json").is_file():
            return False
        self._npm_tried = True
        proc = QProcess(self)
        proc.setProgram(npm)
        proc.setArguments(["ci", "--no-audit", "--no-fund"])
        proc.setWorkingDirectory(str(ROOT / "window"))
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._npm = proc

        def done(code, _status=None) -> None:
            out = bytes(proc.readAll()).decode("utf-8", "replace")
            self._npm = None
            proc.deleteLater()
            if code != 0 or window_command() is None:
                log.error("npm ci в window не прошёл (код %s): %s", code, out[-3000:])
                self._give_up("не удалось поставить окно (npm ci в папке window) — подробности в журнале.")
                return
            log.info("Окно программы поставлено (npm ci в window)")
            if not self._stopping:
                self._start()
        proc.finished.connect(done)
        log.info("Окна программы нет — ставлю: %s ci в %s", npm, ROOT / "window")
        notify = getattr(self.app, "notify", None)
        if callable(notify):
            notify("Ставлю окно программы (Electron) — один раз, нужен интернет; пара минут.", tray=True)
        proc.start()
        return True

    def _on_proc_error(self, err) -> None:
        if err == QProcess.ProcessError.FailedToStart:
            proc, self._proc = self._proc, None
            if proc is not None:
                proc.deleteLater()
            self._give_up(f"окно не запустилось ({proc.errorString() if proc is not None else 'нет файла'}).")

    def _on_exit(self, code, _status=None) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            proc.deleteLater()
        sock, self._sock = self._sock, None
        if sock is not None:
            sock.deleteLater()
        self._inbox = b""
        self._loaded = False
        for loop, res, _cb in list(self._pending.values()):
            res.setdefault("error", "окно закрылось")
            if loop is not None:
                loop.quit()
        self._pending.clear()
        self._queue = []
        if self._stopping:
            return
        if len(self._starts) > RESTARTS:                 # первый запуск + 3 перезапуска за минуту
            self._give_up(f"окно закрылось само (код {code}) несколько раз подряд.")
            return
        log.warning("Окно программы закрылось само (код %s) — запускаю снова", code)
        self._restarting = True
        self._start()

    def _ensure_running(self) -> None:
        """Окно попросили показать, а его нет (не запустилось, падало подряд): попробовать снова."""
        if self.launch and self._wanted and self._proc is None and not self._stopping:
            self._starts = []
            self._restarting = False
            self._start()

    def _give_up(self, why: str) -> None:
        self.failure = f"{FAIL_PREFIX}: {why}"
        log.error(self.failure)
        self.page_failed.emit(self.failure)
        notify = getattr(self.app, "notify", None)
        if callable(notify):
            notify(self.failure + " Подробности — в журнале работы.", tray=True, warn=True)

    def stop(self, wait_ms: int = 3000) -> None:
        """Выход программы: закрыть окно, прочитав его последние места на экране; не дождались — снять процесс."""
        self._stopping = True
        proc = self._proc
        if proc is None:
            return
        if self._sock is None:                            # окно ещё не подключилось (запускается) — ждать нечего
            proc.kill()
            proc.waitForFinished(1000)
            return
        self._write({"op": "quit"})
        end = time.monotonic() + wait_ms / 1000
        while self._proc is not None and time.monotonic() < end:     # места окна — до того, как оно закроется
            if self._sock is not None and self._sock.waitForReadyRead(50):
                self._on_read()
                continue
            proc.waitForFinished(50)                      # закрылось — _on_exit (сокет и процесс убраны)
        if self._proc is not None:
            log.warning("Окно программы не закрылось за %.0f с — завершаю", wait_ms / 1000)
            proc.kill()
            proc.waitForFinished(1000)

    def _request(self, msg: dict, timeout_ms: int | None = None, default=None):
        """Команда с ответом: ждать его (как модальное окно Qt), не останавливая программу."""
        if not self.launch or self._proc is None:
            return default
        self._seq += 1
        rid = msg["id"] = self._seq
        loop = QEventLoop()
        res: dict = {}
        self._pending[rid] = (loop, res, None)
        self._send(msg)
        if timeout_ms:
            QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()
        self._pending.pop(rid, None)
        if "ok" not in res:
            log.warning("Окно программы: нет ответа на %s", msg.get("op"))
            return default
        if not res["ok"]:
            log.warning("Окно программы: %s — %s", msg.get("op"), res.get("error"))
            return default
        return res.get("value")

    def run_js(self, code: str, callback=None) -> None:
        """Выполнить код на странице; callback(значение) — когда ответит."""
        msg = {"op": "js", "code": str(code)}
        if callback is not None and self.launch:
            self._seq += 1
            msg["id"] = self._seq
            self._pending[self._seq] = (None, {}, callback)
        self._send(msg)

    # ------------------------------------------------------------ видно / свёрнуто / развёрнуто
    def _allow_foreground(self) -> None:
        """Вывести окно вперёд может только тот, кому Windows это разрешила (программа — её щёлкнули): отдаём окну."""
        if self.pid:
            try:
                import ctypes
                ctypes.windll.user32.AllowSetForegroundWindow(int(self.pid))
            except (OSError, AttributeError):
                pass

    def _set(self, **kw) -> None:
        new = dict(self.state, **kw)
        if new != self.state:
            self.state = new
            self.state_changed.emit()

    def show(self) -> None:
        self._set(visible=True, minimized=False)
        self._ensure_running()
        self._allow_foreground()
        self._send({"op": "show"})

    present = show              # показать и вывести вперёд: свёрнутое — развернуть как было, скрытое — показать
    raise_ = show
    activateWindow = show

    def hide(self) -> None:
        self._set(visible=False, focused=False)
        self._send({"op": "hide"})

    def showMinimized(self) -> None:
        self._set(minimized=True, focused=False)
        self._send({"op": "min"})

    def showMaximized(self) -> None:
        self._set(visible=True, minimized=False, maximized=True)
        self._ensure_running()
        self._allow_foreground()
        self._send({"op": "max"})

    def showNormal(self) -> None:
        self._set(visible=True, minimized=False, maximized=False)
        self._ensure_running()
        self._allow_foreground()
        self._send({"op": "restore"})

    def isVisible(self) -> bool:
        return self.state["visible"]

    def isMinimized(self) -> bool:
        return self.state["minimized"]

    def isMaximized(self) -> bool:
        return self.state["maximized"]

    def isActiveWindow(self) -> bool:
        return self.state["focused"] and self.state["visible"] and not self.state["minimized"]

    def setWindowTitle(self, title: str) -> None:
        title = str(title)
        if title != self.title:
            self.title = title
            self._send({"op": "title", "title": title})

    def windowTitle(self) -> str:
        return self.title

    def set_taskbar_icon(self, icon_path: str) -> None:
        """Значок окна и кнопки на панели задач (.ico программы) — уходит окну при запуске."""
        self._taskbar_icon = str(icon_path)

    def restyle_frame(self) -> None:
        """Сменилась тема: фон окна под страницей (виден, пока она перерисовывается)."""
        self._send({"op": "theme", "dark": bool(theme.dark), "bg": _bg()})

    # ------------------------------------------------------------ кнопки окна, «поверх всех», маленький режим
    @property
    def pinned(self) -> bool:
        s = self.app.settings
        return bool(s.efir_pinned if self.compact else s.always_on_top)

    def on_top(self) -> bool:
        return self.top

    def apply_pin(self) -> None:
        on = self.pinned
        if on != self.top:
            self.top = on
            self._send({"op": "top", "on": on})

    def window_cmd(self, op: str, arg=None) -> None:
        s = self.app.settings
        if op == "min":
            self.showMinimized()
        elif op == "max":
            self.showMaximized()
        elif op == "restore":
            self.showNormal()
        elif op == "toggle_max":
            self._set(maximized=not self.state["maximized"])
            self._send({"op": "toggle_max"})
        elif op == "close":
            self.close()
        elif op == "pin":
            if self.compact:
                s.efir_pinned = not s.efir_pinned
            else:
                s.always_on_top = not s.always_on_top
            self.apply_pin()
        elif op == "compact":
            self.set_compact(not self.compact if arg is None else bool(arg))
        elif op == "compact_size":
            self.compact_size(arg)

    def set_compact(self, on: bool) -> None:
        on = bool(on)
        if on == self.compact:
            return
        self.compact = on
        if on:
            self._set(maximized=False)
        self.app.settings.compact = on
        self._send({"op": "compact", "on": on})
        self.apply_pin()
        self.state_changed.emit()

    def compact_size(self, arg) -> None:
        """Вид маленького режима из меню страницы: {w, h} в пикселях страницы × масштаб окна. Окно Electron
        держит правый верхний угол на месте и окно — в пределах экрана (window/geometry.js)."""
        if not self.compact or not isinstance(arg, dict):
            return
        try:
            cw, ch = int(arg.get("w")), int(arg.get("h"))
        except (TypeError, ValueError):
            return
        if not (100 <= cw <= 4000 and 50 <= ch <= 3000):
            return
        k = max(80, min(200, int(self.app.settings.page_zoom or 100))) / 100
        self._send({"op": "compact_size", "w": cw, "h": ch, "k": k})

    # ------------------------------------------------------------ места окна
    def restore_places(self, big: str, small: str) -> None:
        """Из настроек: где было большое окно (и развёрнуто ли) и маленькое. Прежние записи Qt — переводятся."""
        self.places = {"big": parse_place(big, True), "small": parse_place(small, False)}
        if self.places["big"] and self.places["big"].get("max"):
            self.state["maximized"] = True

    def place_default(self) -> None:
        self.places["big"] = None             # место по умолчанию считает окно (по центру экрана)

    def saved_places(self) -> tuple[str, str]:
        """Для настроек: JSON большого и маленького окна ("" — неизвестно)."""
        dump = (lambda d: json.dumps(d, separators=(",", ":")) if d else "")
        return dump(self.places.get("big")), dump(self.places.get("small"))

    # ------------------------------------------------------------ закрытие
    def close(self) -> None:
        """«Закрыть» (кнопка страницы, Alt+F4, панель задач): программа решает — в трей или выход."""
        e = CloseEvent()
        if self.close_handler is not None:
            self.close_handler(e)
            if not e.isAccepted():
                return
        self.stop()

    # ------------------------------------------------------------ печать, окна выбора файлов
    def print_pdf(self, path: str, open_after: bool = True) -> bool:
        """«Сохранить PDF…»: страница урока как при печати (@media print), A4, поля 12 мм; потом файл открывается."""
        ok = bool(self._request({"op": "pdf", "path": str(path)}, PDF_TIMEOUT_MS, False))
        if ok and open_after:
            try:
                os.startfile(str(path))
            except OSError as e:
                log.warning("PDF не открылся: %s", e)
        return ok

    def print_dialog(self) -> bool:
        """«Печать…»: системный выбор принтера и печать страницы урока. False — передумали или не напечаталось."""
        return bool(self._request({"op": "print"}, PRINT_TIMEOUT_MS, False))

    def pick_open(self, title: str, folder: str = "", flt: str = "", multi: bool = False) -> list[str]:
        """Системное окно «Открыть» поверх окна программы → пути (пусто — передумали)."""
        r = self._request({"op": "open_dialog", "title": str(title), "dir": str(folder or ""),
                           "filters": qt_filters(flt), "multi": bool(multi)}, None, [])
        return [str(p) for p in (r or []) if p]

    def pick_save(self, title: str, path: str = "", flt: str = "") -> str:
        """Системное окно «Сохранить как» → путь или "" (передумали)."""
        r = self._request({"op": "save_dialog", "title": str(title), "path": str(path or ""),
                           "filters": qt_filters(flt)}, None, "")
        return str(r or "")

    def test_drop(self, files=(), items=()) -> bool:
        """Проверки (окно hidden): «бросить» на окно файлы или ссылку — как из Проводника или браузера, без мыши."""
        return bool(self._request({"op": "test_drop", "files": [str(f) for f in files], "items": list(items)},
                                  15_000, False))


def selftest(timeout_s: float = 60.0) -> int:
    """`AutoPrintCode.exe --selftest`: невидимо открыть окно программы (Electron) и дождаться, пока страница
    запустится. 0 — запустилась."""
    import tempfile
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("AUTOPRINT_DATA", tempfile.mkdtemp(prefix="autoprint-selftest-"))
    from PySide6.QtWidgets import QApplication
    from ..efir.server import BroadcastServer
    from ..storage import Settings

    class _Efir:
        def __init__(self, server) -> None:
            self.server = server

    class _App:
        def __init__(self) -> None:
            self.settings = Settings()
            self.server = BroadcastServer()
            self.efir = _Efir(self.server)

    qa = QApplication.instance() or QApplication(sys.argv[:1])
    fake = _App()
    fake.server.start()
    w = ShellWindow(fake, launch=True, hidden=True)
    result = {"code": 1}

    def done() -> None:
        result["code"] = 0
        qa.quit()

    w.page_ready.connect(done)
    w.page_failed.connect(lambda text: (print("selftest:", text, flush=True), qa.quit()))
    QTimer.singleShot(int(timeout_s * 1000), qa.quit)
    w.load()
    qa.exec()
    w.stop()
    fake.server.stop()
    print("selftest:", "ok" if result["code"] == 0 else "fail", flush=True)
    return result["code"]
