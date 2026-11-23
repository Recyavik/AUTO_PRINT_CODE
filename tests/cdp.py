"""Edge без окна (--headless=new) для тестов экрана урока: протокол отладки (CDP) поверх WebSocket на stdlib.

    edge = Edge.start("http://127.0.0.1:8899/lesson", pump=lambda: app.processEvents())
    edge.wait("window.__ready === true")
    edge.eval("document.title")
    edge.close()

Окон на экране нет; свой временный профиль — браузер человека не трогается; закрывается только свой процесс.
pump — что делать, пока ждём ответа браузера (крутить цикл событий Qt: правки со страницы применяет он).
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path


def edge_path() -> str | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            p = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if p.is_file():
                return str(p)
    return None


class _WS:
    """Минимальный клиент WebSocket: текстовые кадры, маска, ping/pong, продолжения."""

    def __init__(self, url: str) -> None:
        assert url.startswith("ws://")
        hostport, _, path = url[5:].partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port or 80)), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("WebSocket: соединение закрыто при рукопожатии")
            buf += chunk
        head, _, rest = buf.partition(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise ConnectionError("WebSocket: " + head.split(b"\r\n")[0].decode(errors="replace"))
        self.buf = rest
        self.sock.settimeout(0.02)

    def send(self, text: str) -> None:
        data = text.encode("utf-8")
        head = bytearray([0x81])
        n = len(data)
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head.append(0x80 | 126)
            head += struct.pack(">H", n)
        else:
            head.append(0x80 | 127)
            head += struct.pack(">Q", n)
        mask = os.urandom(4)
        head += mask
        body = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.settimeout(10)
        self.sock.sendall(bytes(head) + body)
        self.sock.settimeout(0.02)

    def _read(self, n: int, deadline: float, pump) -> bytes | None:
        while len(self.buf) < n:
            try:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise ConnectionError("WebSocket закрыт")
                self.buf += chunk
            except (socket.timeout, BlockingIOError):
                if pump:
                    pump()
                if time.time() > deadline:
                    return None
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self, deadline: float, pump=None) -> str | None:
        parts = []
        while True:
            hdr = self._read(2, deadline, pump)
            if hdr is None:
                return None
            fin, op, n = hdr[0] & 0x80, hdr[0] & 0x0F, hdr[1] & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2, deadline + 5, pump))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8, deadline + 5, pump))[0]
            payload = self._read(n, deadline + 10, pump) or b""
            if op == 0x9:                       # ping
                self.sock.settimeout(10)
                self.sock.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                self.sock.settimeout(0.02)
                continue
            if op == 0x8:
                raise ConnectionError("WebSocket: браузер закрыл соединение")
            parts.append(payload)
            if fin:
                return b"".join(parts).decode("utf-8", errors="replace")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class Edge:
    def __init__(self) -> None:
        self.proc = None
        self.ws: _WS | None = None
        self.tmp = ""
        self.n = 0
        self.events: list[dict] = []
        self.pump = None

    @classmethod
    def start(cls, url: str, pump=None, width: int = 1360, height: int = 900) -> "Edge":
        exe = edge_path()
        if not exe:
            raise unittest.SkipTest("Edge не найден — тесты страницы пропущены")
        e = cls()
        e.pump = pump
        e.tmp = tempfile.mkdtemp(prefix="suflor-edge-")
        e.proc = subprocess.Popen([exe, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={e.tmp}",
                                   "--no-first-run", "--no-default-browser-check", "--disable-extensions",
                                   "--disable-background-networking", "--disable-sync", "--mute-audio",
                                   f"--window-size={width},{height}", "about:blank"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port_file = Path(e.tmp) / "DevToolsActivePort"
        end = time.time() + 20
        while time.time() < end and not port_file.exists():
            time.sleep(0.05)
        if not port_file.exists():
            e.close()
            raise RuntimeError("Edge не открыл протокол отладки")
        port = int(port_file.read_text().split()[0])
        target = None
        while time.time() < end and target is None:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
                    target = next((t for t in json.loads(r.read()) if t.get("type") == "page"), None)
            except OSError:
                time.sleep(0.05)
        if target is None:
            e.close()
            raise RuntimeError("Edge: нет вкладки")
        e.ws = _WS(target["webSocketDebuggerUrl"])
        e.call("Page.enable")
        e.call("Runtime.enable")
        e.call("Page.navigate", {"url": url})
        e.wait("document.readyState === 'complete'", 15)
        return e

    def call(self, method: str, params: dict | None = None, timeout: float = 15) -> dict:
        self.n += 1
        mid = self.n
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while True:
            msg = self.ws.recv(deadline, self.pump)
            if msg is None:
                raise TimeoutError(f"CDP: нет ответа на {method}")
            d = json.loads(msg)
            if d.get("id") == mid:
                if "error" in d:
                    raise RuntimeError(f"CDP {method}: {d['error']}")
                return d.get("result", {})
            self.events.append(d)
            if len(self.events) > 500:
                del self.events[:250]

    def eval(self, js: str, timeout: float = 15):
        r = self.call("Runtime.evaluate", {"expression": js, "awaitPromise": True, "returnByValue": True}, timeout)
        if r.get("exceptionDetails"):
            ex = r["exceptionDetails"]
            raise RuntimeError("JS: " + str(ex.get("exception", {}).get("description") or ex.get("text")))
        return r.get("result", {}).get("value")

    def wait(self, js: str, timeout: float = 10) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.eval(js):
                    return True
            except RuntimeError:
                pass
            if self.pump:
                self.pump()
            time.sleep(0.02)
        return False

    def errors(self) -> list[str]:
        """Ошибки JavaScript на странице (Runtime.exceptionThrown)."""
        return [str(e["params"]["exceptionDetails"].get("exception", {}).get("description") or e["params"]["exceptionDetails"].get("text"))
                for e in self.events if e.get("method") == "Runtime.exceptionThrown"]

    def text(self, s: str) -> None:
        self.call("Input.insertText", {"text": s})

    def key(self, key: str, code: str = "", vk: int = 0, modifiers: int = 0) -> None:
        """modifiers: 1 Alt, 2 Ctrl, 4 Meta, 8 Shift."""
        base = {"key": key, "code": code or key, "windowsVirtualKeyCode": vk, "modifiers": modifiers}
        self.call("Input.dispatchKeyEvent", {"type": "rawKeyDown", **base})
        self.call("Input.dispatchKeyEvent", {"type": "keyUp", **base})

    def close(self) -> None:
        if self.ws is not None:
            try:
                self.ws.send(json.dumps({"id": 999999, "method": "Browser.close"}))
            except OSError:
                pass
            self.ws.close()
            self.ws = None
        if self.proc is not None:
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()           # только свой процесс — браузер человека не трогается
            self.proc = None
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.tmp = ""
