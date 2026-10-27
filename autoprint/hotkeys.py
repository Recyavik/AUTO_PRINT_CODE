"""Глобальные хоткеи через RegisterHotKey в отдельном потоке с очередью сообщений.

Работают, когда в фокусе любое окно. Нажатие хоткея перехватывается системой
и до целевого окна не доходит.
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.PeekMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_APP_RELOAD = 0x8000 + 1

_NAMED_KEYS = {
    "SPACE": 0x20, "PAUSE": 0x13, "INS": 0x2D, "INSERT": 0x2D, "DEL": 0x2E, "DELETE": 0x2E,
    "HOME": 0x24, "END": 0x23, "PGUP": 0x21, "PGDOWN": 0x22, "LEFT": 0x25, "UP": 0x26,
    "RIGHT": 0x27, "DOWN": 0x28, "ESC": 0x1B, "ESCAPE": 0x1B, "RETURN": 0x0D, "ENTER": 0x0D,
    "TAB": 0x09, "BACKSPACE": 0x08, "SCROLLLOCK": 0x91, "PRINT": 0x2C,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, ";": 0xBA, "'": 0xDE,
    ",": 0xBC, ".": 0xBE, "/": 0xBF, "\\": 0xDC,
}


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """'Ctrl+Alt+F9' → (modifiers, vk). Формат — как QKeySequence.toString()."""
    if not text:
        return None
    parts = [p for p in text.replace(" ", "").split("+")]
    # «Ctrl++» — клавиша плюс
    if text.endswith("++"):
        parts = parts[:-2] + ["="]
    mods = 0
    key = None
    for p in parts:
        u = p.upper()
        if u in ("CTRL", "CONTROL"):
            mods |= MOD_CONTROL
        elif u == "ALT":
            mods |= MOD_ALT
        elif u == "SHIFT":
            mods |= MOD_SHIFT
        elif u in ("META", "WIN"):
            mods |= MOD_WIN
        elif p:
            key = u
    if key is None:
        return None
    if len(key) == 1 and ("A" <= key <= "Z" or "0" <= key <= "9"):
        vk = ord(key)
    elif key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    elif key in _NAMED_KEYS:
        vk = _NAMED_KEYS[key]
    else:
        return None
    return mods, vk


class HotkeyManager(QObject):
    """Регистрирует хоткеи {action: 'Ctrl+F9'} и шлёт сигнал triggered(action)."""

    triggered = Signal(str)
    failed = Signal(str)  # список хоткеев, которые не удалось зарегистрировать
    ok = Signal()         # все хоткеи заняты успешно

    def __init__(self) -> None:
        super().__init__()
        self._bindings: dict[str, str] = {}
        self._lock = threading.Lock()
        self._thread_id = 0
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(2)

    def set_bindings(self, bindings: dict[str, str]) -> None:
        with self._lock:
            self._bindings = dict(bindings)
        user32.PostThreadMessageW(self._thread_id, WM_APP_RELOAD, 0, 0)

    def shutdown(self) -> None:
        user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread.join(1)

    # --- поток ---
    def _run(self) -> None:
        msg = wintypes.MSG()
        # Создаём очередь сообщений потока до того, как в неё начнут писать.
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        self._thread_id = kernel32.GetCurrentThreadId()
        self._ready.set()
        ids: dict[int, str] = {}
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                action = ids.get(int(msg.wParam))
                if action:
                    self.triggered.emit(action)
            elif msg.message == WM_APP_RELOAD:
                for hid in ids:
                    user32.UnregisterHotKey(None, hid)
                ids.clear()
                with self._lock:
                    bindings = dict(self._bindings)
                bad = []
                for i, (action, text) in enumerate(bindings.items(), start=1):
                    parsed = parse_hotkey(text)
                    if not parsed:
                        if text:
                            bad.append(text)
                        continue
                    mods, vk = parsed
                    if user32.RegisterHotKey(None, i, mods | MOD_NOREPEAT, vk):
                        ids[i] = action
                    else:
                        bad.append(text)
                if bad:
                    self.failed.emit(", ".join(bad))
                else:
                    self.ok.emit()
        for hid in ids:
            user32.UnregisterHotKey(None, hid)
