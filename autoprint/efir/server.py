"""Локальный сервер экрана эфира: http://127.0.0.1:8791/

- GET  /              — страница экрана эфира (её вкладку захватывают в демонстрации);
- GET  /gallery       — та же страница: все фоны вживую, щелчок выбирает фон в редакторе шаблона;
- GET  /events        — состояние экрана (Server-Sent Events): при каждом изменении и раз в 15 с;
- GET  /state         — состояние одним JSON;
- GET  /media/<id>/<имя> — видео, картинки, шрифты (с Range — для перемотки видео);
- POST /report        — страница сообщает: подключилась, звук разрешён, ход видео, видео кончилось;
- POST /pick          — выбран фон в галерее.
- GET  /lesson        — страница суфлёра урока (свой канал состояния: /events?ch=lesson);
- GET  /static/lang/<язык>.svg — значки языков программирования для кода на странице суфлёра;
- POST /lesson/cmd    — команды со страницы суфлёра (начать урок, начать с этапа, печатать этот блок…);
- POST /lesson/edit   — правки урока с экрана урока (autoprint/lesson_edit.py), ответ — новый HTML блоков;
- POST /lesson/upload — картинка в урок (тело — сам файл; png, jpg, gif, webp — по содержимому);
- GET  /static/lesson/<файл>.js, /static/vendor/<файл>.js — скрипты экрана урока (CodeMirror — в vendor).
  Все POST /lesson/… — только с заголовком X-Suflor и со своей страницы (Origin), иначе 403.
Слушает только 127.0.0.1. Порт постоянный (8791, если занят — следующие): открытая вкладка переживает
перезапуск программы — EventSource сам переподключается к тому же адресу.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs


log = logging.getLogger(__name__)

PAGE_DIR = Path(__file__).resolve().parent / "page"
DEFAULT_PORT = 8791
PORT_TRIES = 9
HEARTBEAT_S = 15
CHUNK = 256 * 1024

mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("video/mp4", ".m4v")
mimetypes.add_type("video/webm", ".webm")
mimetypes.add_type("video/quicktime", ".mov")
mimetypes.add_type("font/otf", ".otf")
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/svg+xml", ".svg")

# screen — экран эфира для учеников, lesson — страница суфлёра урока, preview — предпросмотр из редактора шаблона
CHANNELS = ("screen", "lesson", "preview")
_LANG_ICON = re.compile(r"/static/lang/([a-z0-9+#-]+\.svg)")
_STATIC = re.compile(r"/static/(lesson|vendor)/([a-z0-9-]+\.(js|css|txt))")
_STATIC_TYPES = {"js": "text/javascript; charset=utf-8", "css": "text/css; charset=utf-8",
                 "txt": "text/plain; charset=utf-8"}
BODY_LIMIT = 2 * 1024 * 1024          # команды и правки урока
UPLOAD_LIMIT = 25 * 1024 * 1024       # картинка в урок
DRAIN_LIMIT = 64 * 1024 * 1024        # больше — даже не читаем, рвём соединение


def image_ext(data: bytes) -> str | None:
    """Расширение картинки по первым байтам; None — это не png / jpg / gif / webp."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False      # на Windows reuse разрешает двум процессам один порт — не надо

    def __init__(self, addr, handler, owner: "BroadcastServer") -> None:
        self.owner = owner
        super().__init__(addr, handler)

    def handle_error(self, request, client_address) -> None:
        # браузер постоянно рвёт соединения (видео, закрытая вкладка) — это не ошибка, печатать незачем
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
            return
        log.exception("Экран эфира: ошибка запроса от %s", client_address)


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args) -> None:     # без вывода в консоль
        pass

    # ------------------------------------------------------------ защита
    def _host_ok(self) -> bool:
        # DNS rebinding: чужой сайт под своим именем на 127.0.0.1 не получит ни состояние, ни файлы
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        return host in ("127.0.0.1", "localhost", "")

    def _origin_ok(self) -> bool:
        """Команды суфлёра — только со своей страницы: чужой сайт в браузере их не пришлёт."""
        origin = (self.headers.get("Origin") or "").rstrip("/")
        if not origin:
            return True
        port = self.server.server_address[1]        # порт этого сервера (у остановленного owner.port уже 0)
        return origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, code: int = 200) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    # ------------------------------------------------------------ GET
    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        if not self._host_ok():
            return self._send(403, b"forbidden", "text/plain")
        path, _, query = self.path.partition("?")
        owner = self.server.owner
        try:
            if path in ("/", "/gallery", "/index.html"):
                body = (PAGE_DIR / "screen.html").read_bytes()
                return self._send(200, body, "text/html; charset=utf-8")
            if path == "/lesson":
                body = (PAGE_DIR / "lesson.html").read_bytes()
                return self._send(200, body, "text/html; charset=utf-8")
            if path == "/state":
                return self._json(owner.snapshot(self._channel(query)))
            if path == "/events":
                return self._events(self._channel(query))
            m = _STATIC.fullmatch(path)
            if m:
                f = PAGE_DIR / m.group(1) / m.group(2)
                if f.is_file():
                    return self._send(200, f.read_bytes(), _STATIC_TYPES[m.group(3)])
                return self._send(404, b"not found", "text/plain")
            m = _LANG_ICON.fullmatch(path)
            if m:
                f = PAGE_DIR / "lang" / m.group(1)
                if f.is_file():
                    return self._send(200, f.read_bytes(), "image/svg+xml", {"Cache-Control": "max-age=86400"})
                return self._send(404, b"not found", "text/plain")
            if path in ("/favicon.svg", "/favicon.ico"):
                # знак AutoPrintCode — значок вкладки эфира и окна суфлёра
                return self._send(200, (PAGE_DIR / "favicon.svg").read_bytes(), "image/svg+xml",
                                  {"Cache-Control": "max-age=86400"})
            m = re.fullmatch(r"/media/([0-9a-f]{16})/[^/]*", path)
            if m:
                f = owner.media_path(m.group(1))
                if f is None or not f.is_file():
                    return self._send(404, b"not found", "text/plain")
                return self._file(f)
            self._send(404, b"not found", "text/plain")
        except (ConnectionError, OSError):
            pass      # вкладку закрыли или браузер отменил запрос (видео дергает Range постоянно)

    @staticmethod
    def _channel(query: str) -> str:
        ch = (parse_qs(query).get("ch") or ["screen"])[0]
        return ch if ch in CHANNELS else "screen"

    def _events(self, channel: str = "screen") -> None:
        owner = self.server.owner
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        owner._client(+1, channel)
        try:
            rev = -1
            while not owner.stopping:
                state, new_rev = owner.wait_change(rev, HEARTBEAT_S, channel)
                if owner.stopping:
                    break
                if new_rev != rev:
                    rev = new_rev
                    data = json.dumps(state, ensure_ascii=False)
                    self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                else:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (ConnectionError, OSError):
            pass
        finally:
            owner._client(-1, channel)
            self.close_connection = True

    def _file(self, f: Path) -> None:
        size = f.stat().st_size
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        rng = self.headers.get("Range", "")
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng.strip())
        start, end = 0, size - 1
        partial = False
        if m and (m.group(1) or m.group(2)):
            partial = True
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
            else:                                   # bytes=-N — последние N байт
                start = max(0, size - int(m.group(2)))
            end = min(end, size - 1)
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(f, "rb") as fh:
            fh.seek(start)
            left = length
            while left > 0 and not self.server.owner.stopping:
                buf = fh.read(min(CHUNK, left))
                if not buf:
                    break
                self.wfile.write(buf)
                left -= len(buf)

    # ------------------------------------------------------------ POST
    def _read_body(self, limit: int) -> bytes | None:
        """Тело запроса; None — больше limit (тело дочитано и выброшено, ответ — 413)."""
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            if n <= DRAIN_LIMIT:
                left = n
                while left > 0:
                    chunk = self.rfile.read(min(CHUNK, left))
                    if not chunk:
                        break
                    left -= len(chunk)
            else:
                self.close_connection = True
            return None
        return self.rfile.read(n) if n > 0 else b""

    def do_POST(self) -> None:
        if not self._host_ok():
            return self._send(403, b"forbidden", "text/plain")
        path, _, query = self.path.partition("?")
        owner = self.server.owner
        if owner.stopping:
            # сервер останавливается (выход, перезапуск): правку не терять — страница повторит её позже
            self.close_connection = True
            return self._json({"ok": False, "retry": True}, 503)
        if path.startswith("/lesson/") and (self.headers.get("X-Suflor") != "1" or not self._origin_ok()):
            self.close_connection = True
            return self._json({"ok": False}, 403)
        try:
            raw = self._read_body(UPLOAD_LIMIT if path == "/lesson/upload" else BODY_LIMIT)
        except (ValueError, OSError):
            return self._json({"ok": False}, 400)
        if raw is None:
            return self._json({"ok": False, "error": "Слишком большой запрос"}, 413)
        if path == "/lesson/upload":
            q = parse_qs(query)
            ext = image_ext(raw)
            if ext is None:
                return self._json({"ok": False, "error": "Это не картинка (png, jpg, gif, webp)"}, 415)
            code, res = owner._on_upload({"lesson": (q.get("lesson") or [""])[0], "after": (q.get("after") or [""])[0],
                                          "id": (q.get("id") or [""])[0], "ext": ext, "data": raw})
            return self._json(res, code)
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return self._json({"ok": False}, 400)
        if not isinstance(data, dict):
            return self._json({"ok": False}, 400)
        if path == "/lesson/edit":
            code, res = owner._on_edit(data)
            return self._json(res, code)
        if path == "/lesson/cmd":
            owner._on_command(data)
            return self._json({"ok": True})
        if path == "/report":
            owner._on_report(data)
            return self._json({"ok": True})
        if path == "/pick":
            owner._on_pick(data)
            return self._json({"ok": True})
        self._json({"ok": False}, 404)


class BroadcastServer:
    """Сервер в своём потоке. publish() — новое состояние экрана; страницы получают его сразу (SSE).
    on_report / on_pick вызываются из потоков сервера — подписчик сам переносит их в поток интерфейса."""

    def __init__(self, port: int = DEFAULT_PORT, on_report: Callable[[dict], None] | None = None,
                 on_pick: Callable[[dict], None] | None = None,
                 on_command: Callable[[dict], None] | None = None) -> None:
        self.want_port = port
        self.port = 0
        self.on_report = on_report
        self.on_pick = on_pick
        self.on_command = on_command
        # правка и загрузка: вызываются в потоке сервера и возвращают (код ответа, JSON)
        self.on_edit: Callable[[dict], tuple[int, dict]] | None = None
        self.on_upload: Callable[[dict], tuple[int, dict]] | None = None
        self.stopping = False
        self._httpd: _Server | None = None
        self._thread: threading.Thread | None = None
        self._cond = threading.Condition()
        # экран эфира до первого настоящего состояния — «ждать»: открытая вкладка учеников держит прежний кадр
        # (после перезапуска программы она не мигает чёрным, идущий перерыв не пропадает)
        self._states: dict[str, dict] = {"screen": {"mode": "wait"}, "lesson": {}, "preview": {}}
        self._revs: dict[str, int] = {ch: 0 for ch in CHANNELS}
        self._media: dict[str, Path] = {}
        self._media_ids: dict[str, str] = {}
        self._counts: dict[str, int] = {ch: 0 for ch in CHANNELS}

    # ------------------------------------------------------------ запуск
    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/" if self.port else ""

    def start(self) -> bool:
        if self._httpd:
            return True
        self.stopping = False
        for port in range(self.want_port, self.want_port + PORT_TRIES):
            try:
                self._httpd = _Server(("127.0.0.1", port), _Handler, self)
            except OSError:
                continue
            self.port = port
            break
        else:
            log.warning("Экран эфира: порты %d…%d заняты", self.want_port, self.want_port + PORT_TRIES - 1)
            return False
        self._thread = threading.Thread(target=self._httpd.serve_forever, kwargs={"poll_interval": 0.3},
                                        name="efir-server", daemon=True)
        self._thread.start()
        log.info("Экран эфира: %s", self.url)
        return True

    def stop(self) -> None:
        if not self._httpd:
            return
        self.stopping = True
        with self._cond:
            self._cond.notify_all()
        httpd, self._httpd = self._httpd, None
        try:
            httpd.shutdown()
            httpd.server_close()
        except OSError:
            pass
        self.port = 0

    # ------------------------------------------------------------ состояние
    def publish(self, state: dict, channel: str = "screen") -> None:
        with self._cond:
            self._states[channel] = dict(state)
            self._revs[channel] += 1
            self._cond.notify_all()

    def snapshot(self, channel: str = "screen") -> dict:
        with self._cond:
            s = dict(self._states[channel])
        s["server_now"] = int(time.time() * 1000)
        return s

    def wait_change(self, rev: int, timeout: float, channel: str = "screen") -> tuple[dict, int]:
        deadline = time.monotonic() + timeout
        with self._cond:
            # ждём своего канала: изменения другого будят всех, но отдавать по ним нечего
            while rev == self._revs[channel] and not self.stopping:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self._cond.wait(left)
            s = dict(self._states[channel])
            r = self._revs[channel]
        s["server_now"] = int(time.time() * 1000)
        return s, r

    @property
    def clients(self) -> int:
        """Открытых вкладок экрана эфира (страницы суфлёра не считаются)."""
        return self._counts["screen"]

    def _client(self, d: int, channel: str = "screen") -> None:
        with self._cond:
            self._counts[channel] = max(0, self._counts[channel] + d)
            n = self._counts[channel]
        if self.on_report and channel != "preview":
            self.on_report({"type": "clients" if channel == "screen" else "lesson_clients", "count": n})

    # ------------------------------------------------------------ файлы
    def media_url(self, path: str | os.PathLike) -> str:
        """Адрес файла для страницы. Файл раздаётся только после регистрации здесь."""
        p = Path(path)
        key = os.path.normcase(str(p.resolve() if p.exists() else p))
        mid = self._media_ids.get(key)
        if not mid:
            mid = uuid.uuid4().hex[:16]
            self._media_ids[key] = mid
            self._media[mid] = p
        from urllib.parse import quote
        return f"/media/{mid}/{quote(p.name)}"

    def media_path(self, mid: str) -> Path | None:
        return self._media.get(mid)

    # ------------------------------------------------------------ от страницы
    def _on_report(self, data: dict) -> None:
        if self.on_report:
            try:
                self.on_report(data)
            except Exception:     # ошибка подписчика не должна ронять поток сервера
                log.exception("on_report")

    def _on_command(self, data: dict) -> None:
        if self.on_command:
            try:
                self.on_command(data)
            except Exception:
                log.exception("on_command")

    def _on_edit(self, data: dict) -> tuple[int, dict]:
        if not self.on_edit:
            return 503, {"ok": False, "retry": True}
        try:
            return self.on_edit(data)
        except Exception:
            log.exception("on_edit")
            return 500, {"ok": False}

    def _on_upload(self, data: dict) -> tuple[int, dict]:
        if not self.on_upload:
            return 503, {"ok": False, "retry": True}
        try:
            return self.on_upload(data)
        except Exception:
            log.exception("on_upload")
            return 500, {"ok": False}

    def _on_pick(self, data: dict) -> None:
        if self.on_pick:
            try:
                self.on_pick(data)
            except Exception:
                log.exception("on_pick")


