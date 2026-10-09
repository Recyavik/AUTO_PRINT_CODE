"""Регресс-тест печати в настоящих редакторах.

    python tests/run_editors.py notepad vscode browser

Блокнот и VS Code: открываем пустой файл, печатаем, Ctrl+S, сравниваем файл с образцом.
Браузер (Monaco = Colab, CodeMirror 6 = JupyterLab): страница кладёт текст редактора
в заголовок окна. Перед браузерным тестом один раз: cd tests/pages && npm i && npm run build.
VS Code запускается изолированным экземпляром (свой профиль, настройки по умолчанию).
AP_TAB=1 — отступы набираются клавишей Tab (настройка indent_with_tab).
Во время прогона НЕ трогать клавиатуру и мышь — тест управляет фокусом.
"""
import functools
import http.server
import os, subprocess, sys, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SP = os.environ.get("SP") or str(ROOT / "tests" / "_run")
os.makedirs(SP, exist_ok=True)
os.environ.setdefault("AUTOPRINT_DATA", os.path.join(SP, "data"))  # не трогать рабочую data/
from PySide6.QtCore import QCoreApplication
from autoprint.storage import Settings
from autoprint.typer import FINISHED, IDLE, PAUSED, TypingEngine
from autoprint import winapi as w
app = QCoreApplication([])

PAGES = ROOT / "tests" / "pages"
_server = http.server.ThreadingHTTPServer(
    ("127.0.0.1", 8765), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(PAGES)))
threading.Thread(target=_server.serve_forever, daemon=True).start()

import ctypes
from ctypes import wintypes
_u = ctypes.windll.user32
_EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def activate(part):
    """Найти видимое окно по части заголовка и вывести вперёд (нажатие Alt снимает блокировку фокуса)."""
    found = []
    def cb(h, _):
        if _u.IsWindowVisible(h) and part.lower() in w.window_title(h).lower():
            found.append(h)
        return True
    _u.EnumWindows(_EnumProc(cb), 0)
    if found:
        w.tap(w.VK_MENU)
        _u.SetForegroundWindow(found[0])


def wait_fg(part, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        t = w.window_title(w.foreground_window())
        if part.lower() in t.lower():
            return True
        activate(part)
        time.sleep(0.5)
    print("  foreground is:", w.describe_window(w.foreground_window()))
    return False

def run(name, cmd, fname, code, profile, cpm=1500, settle=1.5, close_keys=None):
    path = os.path.join(SP, fname)
    open(path, "w", encoding="utf-8").write("")
    # без VSCODE_*/ELECTRON_* — иначе Code.exe запускается как node (ELECTRON_RUN_AS_NODE)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("VSCODE", "ELECTRON"))}
    subprocess.Popen(cmd + [path], shell=False, env=env)
    if not wait_fg(fname, 60):
        print(f"[{name}] окно не получило фокус"); return
    time.sleep(settle)
    s = Settings(); s.profile = profile; s.cpm = cpm; s.jitter = 0; s.newline_pause_ms = 40; s.punct_pause_ms = 0
    s.indent_with_tab = bool(os.environ.get("AP_TAB"))   # AP_TAB=1 — отступы клавишей Tab
    e = TypingEngine(s); msgs = []
    e.message.connect(msgs.append)
    e.load(code); e.start(0.05)
    wait_engine(e, app)
    app.processEvents()
    time.sleep(0.5)
    w.tap(ord("S"), w.VK_CONTROL); time.sleep(1.0)
    got = open(path, encoding="utf-8-sig").read().replace("\r\n", "\n")
    ok = got.rstrip("\n") == code.rstrip("\n")
    print(f"[{name}] state={e.state} {'MATCH' if ok else 'DIFF'} {msgs}")
    if not ok:
        print("  GOT:", repr(got)); print("  EXP:", repr(code))
    if close_keys:
        close_keys()

def wait_engine(e, app, timeout=180.0):
    """Ждёт конца печати. Пауза (сменилось окно) или зависание — не ждём вечно."""
    end = time.time() + timeout
    while e.active or e.state not in (FINISHED, IDLE, PAUSED):
        if time.time() > end:
            print("  ! печать не закончилась за", timeout, "с — останавливаю"); e.stop(); break
        app.processEvents(); time.sleep(0.01)
    if e.state == PAUSED:
        print("  ! печать встала на паузу (сменилось окно?)"); e.stop()
    app.processEvents()


PY = '''import os


def load(path, default=None):
    """Читает файл."""
    if not os.path.exists(path):
        return default or {}
    with open(path, encoding="utf-8") as f:
        data = [line.strip() for line in f if line]
    items = {"a": [1, 2], "b": (3, 4)}
    print(f"Строк: {len(data)}", items['a'])
    return data


class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y
'''.rstrip("\n")

JS = '''function sum(arr) {
  let total = 0;
  for (const n of arr) {
    if (n > 0) {
      total += n;
    }
  }
  return total;
}

const el = document.getElementById("app");
el.innerHTML = `<div class="x">${sum([1, 2, 3])}</div>`;
console.log({ ok: true, list: [1, 2] });'''

which = sys.argv[1:]
if "notepad" in which:
    run("Блокнот/plain", ["notepad.exe"], "np_plain.txt", PY, "plain", close_keys=lambda: w.tap(ord("W"), w.VK_CONTROL))
    time.sleep(1)
    run("Блокнот/ide", ["notepad.exe"], "np_ide.txt", PY, "ide", close_keys=lambda: w.tap(ord("W"), w.VK_CONTROL))
code_cmd = [r"C:\Users\ADMIN\AppData\Local\Programs\Microsoft VS Code\Code.exe",
            f"--user-data-dir={SP}/vscode-data", f"--extensions-dir={SP}/vscode-ext", "--disable-extensions",
            "--skip-welcome", "--skip-release-notes", "--disable-workspace-trust", "-n"]
if "vscode" in which:
    run("VS Code/py", code_cmd, "vs_test.py", PY, "ide", settle=8)
    run("VS Code/js", code_cmd, "vs_test.js", JS, "ide", settle=4)


import base64
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def run_browser(name, page, lang, code, cpm=1500):
    url = f"http://127.0.0.1:8765/{page}#{lang}"
    subprocess.Popen([CHROME, "--new-window", f"--app={url}", f"--user-data-dir={SP}/chrome-profile",
                      "--no-first-run", "--no-default-browser-check"])
    if not wait_fg("ready", 40):
        print(f"[{name}] редактор не загрузился"); return
    time.sleep(1.5)
    s = Settings(); s.profile = "ide"; s.cpm = cpm; s.jitter = 0; s.newline_pause_ms = 40; s.punct_pause_ms = 0
    s.indent_with_tab = bool(os.environ.get("AP_TAB"))   # AP_TAB=1 — отступы клавишей Tab
    e = TypingEngine(s); msgs = []
    e.message.connect(msgs.append)
    e.load(code); e.start(0.05)
    wait_engine(e, app)
    app.processEvents()
    got = None
    end = time.time() + 15
    while time.time() < end:
        t = w.window_title(w.foreground_window())
        if t.startswith("RESULT:"):
            got = base64.b64decode(t[7:].split(" ")[0]).decode("utf-8"); break
        time.sleep(0.3)
    ok = got is not None and got.replace("\r\n", "\n").rstrip("\n") == code.rstrip("\n")
    print(f"[{name}] state={e.state} {'MATCH' if ok else 'DIFF'} {msgs}")
    if not ok:
        print("  GOT:", repr(got)); print("  EXP:", repr(code))
    w.tap(ord("W"), w.VK_CONTROL)
    time.sleep(1)


if "browser" in which:
    run_browser("Monaco/py", "monaco.html", "py", PY)
    run_browser("Monaco/js", "monaco.html", "js", JS)
    run_browser("CM6/py", "cm6.html", "py", PY)
    run_browser("CM6/js", "cm6.html", "js", JS)
