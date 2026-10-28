"""Глобальная клавиша Windows: срабатывает, даже когда активно другое окно (PowerPoint, браузер с эфиром).

RegisterHotKey без окна — сообщение WM_HOTKEY приходит в очередь потока; Qt отдаёт его фильтру нативных событий.
Не на Windows или клавиша занята другой программой — просто не работает (кнопки в окне и в трее остаются).
"""
from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, Qt, QTimer
from PySide6.QtGui import QKeySequence

log = logging.getLogger(__name__)

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x4000
WM_HOTKEY = 0x0312
_EVENT_TYPES = (b"windows_generic_MSG", b"windows_dispatcher_MSG")

_ALONE = {Qt.Key.Key_ScrollLock, Qt.Key.Key_Pause}      # почти не нужны программам — годятся и без Ctrl/Alt
_SPECIAL = {Qt.Key.Key_ScrollLock: 0x91, Qt.Key.Key_Space: 0x20, Qt.Key.Key_Pause: 0x13, Qt.Key.Key_Insert: 0x2D, Qt.Key.Key_Delete: 0x2E,
            Qt.Key.Key_Home: 0x24, Qt.Key.Key_End: 0x23, Qt.Key.Key_PageUp: 0x21, Qt.Key.Key_PageDown: 0x22,
            Qt.Key.Key_Left: 0x25, Qt.Key.Key_Up: 0x26, Qt.Key.Key_Right: 0x27, Qt.Key.Key_Down: 0x28}


def normalized(text: str) -> str:
    """Сочетание в одном виде для настроек и подписей: «Ctrl+Alt+Z» (пусто — не задано)."""
    seq = QKeySequence.fromString(text.strip(), QKeySequence.SequenceFormat.PortableText)
    if seq.isEmpty():
        return ""
    return QKeySequence(seq[0]).toString(QKeySequence.SequenceFormat.PortableText)


def parse(text: str) -> tuple[int, int] | None:
    """«Ctrl+Alt+Z» → (модификаторы, код клавиши Windows). None — пусто или не годится для общей клавиши:
    буква, цифра и т. п. без Ctrl/Alt — мешала бы печатать (без них можно только F1–F24, Scroll Lock и Pause)."""
    seq = QKeySequence.fromString(text.strip(), QKeySequence.SequenceFormat.PortableText)
    if seq.isEmpty() or seq.count() != 1:
        return None
    combo = seq[0]
    key, m = combo.key(), combo.keyboardModifiers()
    mods = ((MOD_CONTROL if m & Qt.KeyboardModifier.ControlModifier else 0)
            | (MOD_ALT if m & Qt.KeyboardModifier.AltModifier else 0)
            | (MOD_SHIFT if m & Qt.KeyboardModifier.ShiftModifier else 0))
    k = key.value if hasattr(key, "value") else int(key)
    if Qt.Key.Key_A.value <= k <= Qt.Key.Key_Z.value or Qt.Key.Key_0.value <= k <= Qt.Key.Key_9.value:
        vk, free = k, False                                   # у букв и цифр код Windows совпадает с ASCII
    elif Qt.Key.Key_F1.value <= k <= Qt.Key.Key_F24.value:
        vk, free = 0x70 + k - Qt.Key.Key_F1.value, True
    elif key in _SPECIAL:
        vk, free = _SPECIAL[key], key in _ALONE
    else:
        return None
    if not (mods & (MOD_CONTROL | MOD_ALT)) and not free:
        return None
    return mods, vk


class GlobalHotkey(QAbstractNativeEventFilter):
    _next_id = 0xB170

    def __init__(self, text: str, callback: Callable[[], None]) -> None:
        """text — сочетание «Ctrl+Alt+Z»; пусто или не годится — клавиша выключена (ok = False)."""
        super().__init__()
        portable = normalized(text)
        label = QKeySequence.fromString(portable, QKeySequence.SequenceFormat.PortableText).toString(
            QKeySequence.SequenceFormat.NativeText).replace("ScrollLock", "Scroll Lock")   # для подписей
        self.label, self.callback = label, callback
        self.id = GlobalHotkey._next_id
        GlobalHotkey._next_id += 1
        self.ok = False
        keys = parse(portable)
        if sys.platform != "win32" or keys is None:
            return
        mods, vk = keys
        self.ok = bool(ctypes.windll.user32.RegisterHotKey(None, self.id, mods | MOD_NOREPEAT, vk))
        if self.ok:
            QCoreApplication.instance().installNativeEventFilter(self)
            log.info("Клавиша %s — включена", label)
        else:
            log.warning("Клавиша %s занята другой программой — не работает", label)

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) in _EVENT_TYPES:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == self.id:
                QTimer.singleShot(0, self.callback)     # не изнутри обработки сообщения Windows
                return True, 0
        return False, 0

    def unregister(self) -> None:
        if self.ok:
            ctypes.windll.user32.UnregisterHotKey(None, self.id)
            QCoreApplication.instance().removeNativeEventFilter(self)
            self.ok = False
