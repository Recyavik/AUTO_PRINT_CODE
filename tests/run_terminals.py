"""Печать в настоящие терминалы: Git Bash (mintty и консоль Windows), PowerShell, Windows Terminal.

    python tests/run_terminals.py                    — профиль «Терминал» во всех терминалах
    python tests/run_terminals.py --profile ide      — то же с профилем IDE (для сравнения)
    python tests/run_terminals.py mintty powershell  — только выбранные терминалы
    python tests/run_terminals.py --human            — «как человек»: опечатки и Backspace

Печатаются команды, которые пишут строки в файл out.txt; файл сравнивается с ожидаемым —
так видно и лишние символы («F» от Shift+End), и потерянные. Каждый терминал открывается
в своей временной папке и закрывается командой exit. Печать идёт только в окно с заголовком
этой папки: если фокус уйдёт, движок встанет на паузу. Во время прогона НЕ трогать клавиатуру и мышь.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("AUTOPRINT_DATA", tempfile.mkdtemp(prefix="apc-term-data-"))   # рабочая data/ не нужна

from PySide6.QtCore import QCoreApplication  # noqa: E402

from autoprint import winapi as w  # noqa: E402
from autoprint.storage import Settings  # noqa: E402
from autoprint.typer import FINISHED, IDLE, PAUSED, TypingEngine  # noqa: E402

app = QCoreApplication([])
_u = ctypes.windll.user32
_EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

GIT = Path(r"C:\Program Files\Git")
BASH = str(GIT / "bin" / "bash.exe")
WT = shutil.which("wt.exe")

# git-команды для демонстрации: кавычки, скобки, кириллица, двойной дефис
BASH_SCRIPT = """echo "git commit -m 'Первый коммит' (v1) [ok]" > out.txt
printf '%s\\n' "git log --oneline" "git diff -- \\"file.txt\\"" >> out.txt
echo {a,b} $((1+2)) >> out.txt
exit"""
BASH_EXPECTED = """git commit -m 'Первый коммит' (v1) [ok]
git log --oneline
git diff -- "file.txt"
a b 3
"""
PS_SCRIPT = """Set-Content -Encoding utf8 out.txt "git commit -m 'Первый коммит' (v1) [ok]"
Add-Content -Encoding utf8 out.txt ('git log ' + "--oneline")
exit"""
PS_EXPECTED = """git commit -m 'Первый коммит' (v1) [ok]
git log --oneline
"""


def terminals(d: Path) -> dict[str, tuple[list[str], str, str]]:
    """имя → (команда запуска, сценарий, ожидаемое содержимое out.txt). Окно узнаём по имени папки d."""
    t = {
        "mintty": ([str(GIT / "git-bash.exe"), f"--cd={d}"], BASH_SCRIPT, BASH_EXPECTED),
        "conhost-bash": (["conhost.exe", BASH, "--login", "-i"], BASH_SCRIPT, BASH_EXPECTED),
        "powershell": (["conhost.exe", "powershell.exe", "-NoLogo", "-NoProfile", "-NoExit", "-Command",
                        f"$Host.UI.RawUI.WindowTitle = '{d.name}'; "
                        f"Set-PSReadLineOption -HistorySavePath '{d / 'hist.txt'}'"], PS_SCRIPT, PS_EXPECTED),
    }
    if WT:
        t["windows-terminal"] = ([WT, "-w", "new", "--suppressApplicationTitle", "--title", d.name, "-d", str(d),
                                  BASH, "--login", "-i"], BASH_SCRIPT, BASH_EXPECTED)
    return t


def find_window(part: str) -> int:
    found: list[int] = []

    def cb(h, _):
        if _u.IsWindowVisible(h) and part.lower() in w.window_title(h).lower():
            found.append(h)
        return True
    _u.EnumWindows(_EnumProc(cb), 0)
    return found[0] if found else 0


def read_console(hwnd: int, width: int = 120, height: int = 40) -> str:
    """Текст на экране консоли Windows (conhost) — что на самом деле оказалось в строке ввода."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    pid = w.window_pid(hwnd)
    k32.FreeConsole()
    if not pid or not k32.AttachConsole(pid):
        return f"<не подключиться к консоли pid {pid}>"
    try:
        out = k32.CreateFileW("CONOUT$", 0xC0000000, 3, None, 3, 0, None)
        buf = ctypes.create_unicode_buffer(width * height)
        n = wintypes.DWORD()
        k32.ReadConsoleOutputCharacterW(out, buf, width * height, 0, ctypes.byref(n))
        k32.CloseHandle(out)
    finally:
        k32.FreeConsole()
    lines = [buf.value[i:i + width].rstrip() for i in range(0, len(buf.value), width)]
    return "\n".join(x for x in lines if x)


def focus(part: str, timeout: float = 30) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if part.lower() in w.window_title(w.foreground_window()).lower():
            return True
        h = find_window(part)
        if h:
            w.tap(w.VK_MENU)   # нажатие Alt снимает запрет Windows на смену фокуса
            _u.SetForegroundWindow(h)
        time.sleep(0.4)
    return False


def type_text(text: str, settings: Settings) -> str:
    e = TypingEngine(settings)
    msgs: list[str] = []
    e.message.connect(msgs.append)
    e.load(text)
    e.start(0.1)
    end = time.time() + 120
    while e.active or e.state not in (FINISHED, IDLE, PAUSED):
        if time.time() > end:
            e.stop()
            return "не закончилось за 120 с"
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    if e.state == PAUSED:
        e.stop()
        return f"пауза, в фокусе {w.describe_window(w.foreground_window())}: " + " ".join(msgs)
    return " ".join(msgs)


def run(name: str, profile: str, human: bool = False) -> bool:
    d = Path(tempfile.mkdtemp(prefix=f"apc-term-{name}-"))
    cmd, script, expected = terminals(d)[name]
    # bash после каждой команды дописывает её в hist.txt — видно, что именно попало в строку ввода
    env = {**os.environ, "HISTFILE": str(d / "hist.txt"), "PROMPT_COMMAND": "history -a"}
    proc = subprocess.Popen(cmd, cwd=d, env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)
    try:
        if not focus(d.name):
            print(f"[{name}] окно с заголовком {d.name} не появилось")
            return False
        time.sleep(4)     # оболочка загрузилась и показала приглашение (--login читает профиль)
        s = replace(Settings(), profile=profile, cpm=900, jitter=0, newline_pause_ms=400, punct_pause_ms=0,
                    key_gap_ms=30, human_typing=human, typo_per_100_words=30, think_pause_s=0.3,
                    autopause_on_focus_change=True)
        problem = type_text(script, s)
        out = d / "out.txt"
        for _ in range(30):   # exit закрывает окно; файл уже записан
            if out.exists():
                break
            time.sleep(0.2)
        time.sleep(1.0)
        got = out.read_text(encoding="utf-8-sig").replace("\r\n", "\n") if out.exists() else "<нет out.txt>"
        ok = got == expected
        mode = " (как человек, с опечатками)" if human else ""
        print(f"[{name}] профиль={profile}{mode}: {'OK' if ok else 'НЕ СОВПАЛО'} {problem}".rstrip())
        hist = d / "hist.txt"
        if not ok and hist.exists():
            print("    введено:")
            for line in hist.read_text(encoding="utf-8", errors="replace").splitlines():
                print("      ", repr(line))
        if not ok:
            for a, b in zip(expected.splitlines() + ["<конец>"] * 5, got.splitlines() + ["<конец>"] * 5):
                if a != b:
                    print(f"    ждали:    {a!r}\n    получили: {b!r}")
        return ok
    finally:
        time.sleep(0.5)
        h = find_window(d.name)
        if h:
            _u.PostMessageW(h, 0x0010, 0, 0)   # WM_CLOSE, если exit не напечатался
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            pass
        shutil.rmtree(d, ignore_errors=True)


def main() -> int:
    args = sys.argv[1:]
    profile = "terminal"
    if "--profile" in args:
        i = args.index("--profile")
        profile = args[i + 1]
        del args[i:i + 2]
    human = "--human" in args
    args = [a for a in args if a != "--human"]
    names = args or list(terminals(Path("x")))
    results = [run(n, profile, human) for n in names]
    print("\nИтог:", "всё совпало." if all(results) else f"не совпало: {results.count(False)} из {len(results)}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
