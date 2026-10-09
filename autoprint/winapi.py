"""Тонкая обёртка над WinAPI: эмуляция клавиатуры (SendInput), активное окно, модификаторы.

Символы печатаются через KEYEVENTF_UNICODE — не зависит от раскладки
(кириллица, спецсимволы, эмодзи работают одинаково).
"""
from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MAPVK_VK_TO_VSC = 0

VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_ESCAPE = 0x1B
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_DELETE = 0x2E
VK_LWIN = 0x5B
VK_RWIN = 0x5C

# Клавиши, которым нужен флаг EXTENDEDKEY (иначе Windows считает их цифровым блоком).
_EXTENDED = {VK_HOME, VK_END, VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN, VK_DELETE, 0x21, 0x22, 0x2D}

ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)


def _key_input(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
    return inp


def _send(inputs: list[INPUT]) -> None:
    if not inputs:
        return
    arr = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise OSError(ctypes.get_last_error(), "SendInput заблокирован (окно с правами администратора?)")


def _vk_events(vk: int, up: bool) -> INPUT:
    flags = KEYEVENTF_KEYUP if up else 0
    if vk in _EXTENDED:
        flags |= KEYEVENTF_EXTENDEDKEY
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    return _key_input(vk=vk, scan=scan, flags=flags)


def type_char(ch: str) -> None:
    """Печатает один символ (включая символы вне BMP — суррогатной парой)."""
    data = ch.encode("utf-16-le")
    units = [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]
    inputs = []
    for u in units:
        inputs.append(_key_input(scan=u, flags=KEYEVENTF_UNICODE))
        inputs.append(_key_input(scan=u, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
    _send(inputs)


def tap(vk: int, *modifiers: int) -> None:
    """Нажимает клавишу vk, удерживая модификаторы (например tap(VK_HOME, VK_SHIFT))."""
    inputs = [_vk_events(m, False) for m in modifiers]
    inputs.append(_vk_events(vk, False))
    inputs.append(_vk_events(vk, True))
    inputs.extend(_vk_events(m, True) for m in reversed(modifiers))
    _send(inputs)


_MODIFIER_VKS = (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN)


def modifiers_down() -> bool:
    return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in _MODIFIER_VKS)


def wait_modifiers_released(timeout: float = 5.0, cancelled=lambda: False) -> bool:
    """Ждёт, пока пользователь отпустит Ctrl/Alt/Shift/Win после нажатия хоткея.

    Иначе напечатанное «а» превратится в Ctrl+A и т.п. False — не отпустили за timeout
    или ожидание прервано (cancelled() вернул True: пауза, стоп).
    """
    deadline = time.monotonic() + timeout
    while modifiers_down():
        if time.monotonic() > deadline or cancelled():
            return False
        time.sleep(0.01)
    time.sleep(0.03)
    return True


def foreground_window() -> int:
    return user32.GetForegroundWindow() or 0


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def is_own_window(hwnd: int) -> bool:
    return bool(hwnd) and window_pid(hwnd) == os.getpid()


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD))
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def window_process_name(hwnd: int) -> str:
    """Имя exe процесса окна (code.exe, notepad.exe…) — для журнала."""
    pid = window_pid(hwnd)
    if not pid:
        return "?"
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return f"pid {pid}"
    try:
        buf = ctypes.create_unicode_buffer(520)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1]
        return f"pid {pid}"
    finally:
        kernel32.CloseHandle(h)


def describe_window(hwnd: int) -> str:
    title = window_title(hwnd)
    if len(title) > 60:
        title = title[:57] + "…"
    return f"{window_process_name(hwnd)} «{title}»"


def window_title(hwnd: int) -> str:
    if not hwnd:
        return ""
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
advapi32.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
advapi32.GetTokenInformation.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                         ctypes.POINTER(wintypes.DWORD))
kernel32.GetCurrentProcess.restype = wintypes.HANDLE
TOKEN_QUERY = 0x0008
TokenElevation = 20


def _process_elevated(hproc) -> bool | None:
    tok = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(hproc, TOKEN_QUERY, ctypes.byref(tok)):
        return None
    try:
        val = wintypes.DWORD()
        size = wintypes.DWORD()
        if not advapi32.GetTokenInformation(tok, TokenElevation, ctypes.byref(val), ctypes.sizeof(val),
                                            ctypes.byref(size)):
            return None
        return bool(val.value)
    finally:
        kernel32.CloseHandle(tok)


def self_elevated() -> bool:
    return bool(_process_elevated(kernel32.GetCurrentProcess()))


def window_elevated(hwnd: int) -> bool:
    """Окно принадлежит процессу с правами администратора?

    Из обычного процесса ввод в такое окно молча отбрасывается Windows (UIPI),
    причём SendInput не сообщает об ошибке — поэтому проверяем заранее.
    Если права узнать нельзя (доступ запрещён) — скорее всего, процесс повышенный.
    """
    pid = window_pid(hwnd)
    if not pid:
        return False
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return True
    try:
        elevated = _process_elevated(h)
        # маркер повышенного процесса обычному процессу обычно не прочитать — значит, повышенный
        return True if elevated is None else elevated
    finally:
        kernel32.CloseHandle(h)
