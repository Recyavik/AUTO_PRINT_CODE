"""Системные рамки окошек Qt (QMessageBox до загрузки окна программы) — в цветах темы; сторож «лишних окон».

С 1.2 окно программы — Electron (ui/shell_window.py); своей рамки Qt (WM_NCCALCSIZE/WM_NCHITTEST) больше нет.
"""
from __future__ import annotations

import ctypes
import logging
from pathlib import Path
from ctypes import wintypes

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QWidget

from .theme import theme

log = logging.getLogger(__name__)

try:
    dwmapi = ctypes.WinDLL("dwmapi")
except OSError:   # без DWM — рамки останутся системного цвета
    dwmapi = None

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR, DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR = 34, 35, 36


def _colorref(c) -> int:
    return c.red() | (c.green() << 8) | (c.blue() << 16)


def _dwm_set(hwnd: int, attr: int, value: int) -> None:
    if dwmapi is None:
        return
    v = ctypes.c_int(value)
    try:
        dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v))
    except OSError:
        pass


def style_native_frame(hwnd: int) -> None:
    """Системная рамка обычных диалогов — в цветах темы (Windows 11; на 10 — только тёмный режим)."""
    _dwm_set(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if theme.dark else 0)
    _dwm_set(hwnd, DWMWA_CAPTION_COLOR, _colorref(theme.c("panel")))
    _dwm_set(hwnd, DWMWA_TEXT_COLOR, _colorref(theme.c("text")))
    _dwm_set(hwnd, DWMWA_BORDER_COLOR, _colorref(theme.c("panel")))


_strays_logged: set[str] = set()


def is_stray_window(w: QWidget) -> bool:
    """Обычный виджет, показанный самостоятельным окном. Так бывает, если setVisible(True)/show() вызвать
    до вставки виджета в окно программы: Windows успевает показать его отдельным окном с кнопкой на
    панели задач («мелькают окна AutoPrintCode / Python»). Окна программы, диалоги, меню и подсказки — не в счёт."""
    from PySide6.QtWidgets import QDialog
    return w.isWindow() and w.windowType() == Qt.WindowType.Window and not isinstance(w, QDialog)


def _log_stray(w: QWidget) -> None:
    """Лишнее окно — в журнал (раз на место в коде): так оно попадёт и в отчёт об ошибке."""
    import traceback
    frames = [f for f in traceback.extract_stack()[:-2] if "autoprint" in f.filename.replace("\\", "/")]
    where = " ← ".join(f"{Path(f.filename).name}:{f.lineno}" for f in reversed(frames[-4:])) or "?"
    key = f"{type(w).__name__}|{w.objectName()}|{where}"
    if key not in _strays_logged:
        _strays_logged.add(key)
        log.warning("Лишнее окно: %s «%s» показано до вставки в окно программы (%s)",
                    type(w).__name__, w.objectName(), where)


class NativeFrameStyler(QObject):
    """Ставится на приложение: красит системные рамки диалогов при показе и при смене темы.
    Заодно сторожит «лишние окна» (is_stray_window) — пишет в журнал, откуда такое окно показали."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        theme.changed.connect(self._restyle_all)

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            if obj.windowType() in (Qt.WindowType.Dialog, Qt.WindowType.Window):
                style_native_frame(int(obj.winId()))
            if is_stray_window(obj):
                _log_stray(obj)
        return False

    def _restyle_all(self) -> None:
        for w in QApplication.topLevelWidgets():
            if w.isVisible() and w.windowType() in (Qt.WindowType.Dialog, Qt.WindowType.Window):
                style_native_frame(int(w.winId()))
