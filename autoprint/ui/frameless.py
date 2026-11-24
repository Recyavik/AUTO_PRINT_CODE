"""Свой заголовок окна (как в PasteTalk), но окно остаётся «настоящим» окном Windows.

Окно создаётся без рамки Qt, а затем ему возвращаются стили обычного окна (WS_CAPTION,
WS_THICKFRAME…). Неклиентская область убирается в WM_NCCALCSIZE, а WM_NCHITTEST сообщает Windows,
где края (растягивание) и где заголовок (перетаскивание). Поэтому работают прилипание к краям
экрана, Win+стрелки, двойной щелчок по заголовку, системное меню, тень и скруглённые углы Windows 11.

Обычные диалоги (QMessageBox, выбор файла) остаются с системной рамкой — ей задаются цвета темы.
"""
from __future__ import annotations

import ctypes
import logging
from pathlib import Path
from ctypes import wintypes

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from .theme import theme

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
try:
    dwmapi = ctypes.WinDLL("dwmapi")
except OSError:   # без DWM — останется просто окно без тени
    dwmapi = None

GWL_STYLE = -16
WS_CAPTION, WS_THICKFRAME, WS_SYSMENU = 0x00C00000, 0x00040000, 0x00080000
WS_MINIMIZEBOX, WS_MAXIMIZEBOX = 0x00020000, 0x00010000
SWP_FLAGS = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020 | 0x0200   # без размера/места/порядка, рамка изменилась
WM_NCCALCSIZE, WM_NCHITTEST = 0x0083, 0x0084
HTCLIENT, HTCAPTION = 1, 2
HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT, HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 10, 11, 12, 13, 14, 15, 16, 17
SM_CXSIZEFRAME, SM_CYSIZEFRAME, SM_CXPADDEDBORDER = 32, 33, 92
DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_WINDOW_CORNER_PREFERENCE = 20, 33
DWMWA_BORDER_COLOR, DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR = 34, 35, 36
DWMWCP_ROUND = 2

user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, wintypes.UINT)
user32.IsZoomed.argtypes = (wintypes.HWND,)
user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
user32.ScreenToClient.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))


class MARGINS(ctypes.Structure):
    _fields_ = [("left", ctypes.c_int), ("right", ctypes.c_int), ("top", ctypes.c_int), ("bottom", ctypes.c_int)]


class NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


MONITOR_DEFAULTTONEAREST = 2
user32.MonitorFromWindow.restype = wintypes.HANDLE
user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
user32.GetMonitorInfoW.argtypes = (wintypes.HANDLE, ctypes.POINTER(MONITORINFO))


def _work_area(hwnd: int) -> wintypes.RECT | None:
    """Рабочая область монитора окна (без панели задач)."""
    mon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if not mon:
        return None
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
        return None
    return mi.rcWork


def _metric(index: int, dpi: int) -> int:
    try:
        return user32.GetSystemMetricsForDpi(index, dpi)
    except AttributeError:   # до Windows 10 1607
        return user32.GetSystemMetrics(index)


def _dpi(hwnd: int) -> int:
    try:
        return user32.GetDpiForWindow(hwnd) or 96
    except AttributeError:
        return 96


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
    return w.isWindow() and w.windowType() == Qt.WindowType.Window and not isinstance(w, (FramelessWindow, QDialog))


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
            if not isinstance(obj, FramelessWindow) \
                    and obj.windowType() in (Qt.WindowType.Dialog, Qt.WindowType.Window):
                style_native_frame(int(obj.winId()))
            if is_stray_window(obj):
                _log_stray(obj)
        return False

    def _restyle_all(self) -> None:
        for w in QApplication.topLevelWidgets():
            if w.isVisible() and not isinstance(w, FramelessWindow) \
                    and w.windowType() in (Qt.WindowType.Dialog, Qt.WindowType.Window):
                style_native_frame(int(w.winId()))


# ---------------------------------------------------------------- кнопки окна

class WinButton(QToolButton):
    """«Свернуть / Развернуть / Закрыть» — тонкие значки как у Windows 11 (рисуются сами)."""
    MIN, MAX, RESTORE, CLOSE = "min", "max", "restore", "close"

    def __init__(self, kind: str, parent=None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.setObjectName("winClose" if kind == self.CLOSE else "winBtn")
        self.setFixedSize(46, 40)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip({self.MIN: "Свернуть", self.MAX: "Развернуть", self.RESTORE: "Восстановить",
                         self.CLOSE: "Закрыть"}[kind])

    def set_kind(self, kind: str) -> None:
        self.kind = kind
        self.setToolTip("Восстановить" if kind == self.RESTORE else "Развернуть")
        self.update()

    def paintEvent(self, e) -> None:
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.kind == self.CLOSE and self.underMouse():
            color = Qt.GlobalColor.white   # на красном фоне
        else:
            color = theme.c("text") if self.underMouse() else theme.c("dim")
        pen = QPen(color, 1.0)
        p.setPen(pen)
        cx, cy = self.width() / 2, self.height() / 2
        s = 5
        if self.kind == self.MIN:
            p.drawLine(QPointF(cx - s, cy), QPointF(cx + s, cy))
        elif self.kind == self.MAX:
            p.drawRoundedRect(QRectF(cx - s, cy - s, 2 * s, 2 * s), 1.5, 1.5)
        elif self.kind == self.RESTORE:
            p.drawRoundedRect(QRectF(cx - s, cy - s + 2, 2 * s - 2, 2 * s - 2), 1.5, 1.5)
            p.drawLine(QPointF(cx - s + 2, cy - s), QPointF(cx + s - 1, cy - s))
            p.drawLine(QPointF(cx + s, cy - s + 1), QPointF(cx + s, cy + s - 2))
        else:
            p.drawLine(QPointF(cx - s, cy - s), QPointF(cx + s, cy + s))
            p.drawLine(QPointF(cx + s, cy - s), QPointF(cx - s, cy + s))
        p.end()


class StatusDot(QWidget):
    """Цветная точка состояния в заголовке."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(QSize(8, 8))
        self.token = "ok"
        self.setProperty("drag", True)

    def set_token(self, token: str) -> None:
        self.token = token
        self.update()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c(self.token))
        p.drawEllipse(QRectF(0.5, 0.5, 7, 7))
        p.end()


class TitleBar(QWidget):
    """Полоса заголовка: [логотип][название][• состояние] … [доп. кнопки][— ▢ ✕]."""
    HEIGHT = 40

    def __init__(self, window: QWidget, title: str, minimize: bool = True, maximize: bool = True) -> None:
        super().__init__(window)
        self.window_ = window
        self.setObjectName("titleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(self.HEIGHT)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 0, 0)
        lay.setSpacing(6)
        self.left = QHBoxLayout()
        self.left.setSpacing(6)
        lay.addLayout(self.left)
        self.title = QLabel(title)
        self.title.setObjectName("titleText")
        self.title.setProperty("drag", True)
        lay.addWidget(self.title)
        lay.addSpacing(6)
        self.dot = StatusDot()
        self.dot.hide()
        lay.addWidget(self.dot)
        self.status = QLabel()
        self.status.setObjectName("titleStatus")
        self.status.setProperty("drag", True)
        lay.addWidget(self.status, 1)
        self.right = QHBoxLayout()
        self.right.setSpacing(2)
        lay.addLayout(self.right)
        lay.addSpacing(6)
        self.btn_min = self.btn_max = None
        if minimize:
            self.btn_min = WinButton(WinButton.MIN)
            self.btn_min.clicked.connect(window.showMinimized)
            lay.addWidget(self.btn_min)
        if maximize:
            self.btn_max = WinButton(WinButton.MAX)
            self.btn_max.clicked.connect(self._toggle_max)
            lay.addWidget(self.btn_max)
        self.btn_close = WinButton(WinButton.CLOSE)
        self.btn_close.clicked.connect(window.close)
        lay.addWidget(self.btn_close)

    def set_status(self, text: str, token: str | None = None) -> None:
        self.status.setText(text)
        if token:
            self.dot.set_token(token)
            self.dot.show()
        else:
            self.dot.hide()

    def _toggle_max(self) -> None:
        w = self.window_
        w.showNormal() if w.isMaximized() else w.showMaximized()

    def sync_state(self) -> None:
        if self.btn_max:
            self.btn_max.set_kind(WinButton.RESTORE if self.window_.isMaximized() else WinButton.MAX)


# ---------------------------------------------------------------- окно

class FramelessWindow(QWidget):
    """Окно верхнего уровня со своим заголовком. Наследник кладёт содержимое в self.body."""
    closed = Signal()

    def __init__(self, title: str, minimize: bool = True, maximize: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowTitle(title)
        self.titlebar = TitleBar(self, title, minimize, maximize)
        self._maximizable = maximize
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.titlebar)
        self.body = QWidget()
        lay.addWidget(self.body, 1)
        self._styled_hwnd = 0

    # ---- стили окна Windows
    def _apply_frame(self) -> None:
        hwnd = int(self.winId())
        if not hwnd:
            return
        style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
        want = style | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX
        if self._maximizable:
            want |= WS_MAXIMIZEBOX
        if want != style:
            user32.SetWindowLongPtrW(hwnd, GWL_STYLE, want)
        if dwmapi is not None:
            m = MARGINS(1, 1, 1, 1)   # тень окна
            try:
                dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), ctypes.byref(m))
            except OSError:
                pass
            _dwm_set(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)
            _dwm_set(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if theme.dark else 0)
            _dwm_set(hwnd, DWMWA_BORDER_COLOR, _colorref(theme.c("panel")))
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_FLAGS)
        self._styled_hwnd = hwnd

    def restyle_frame(self) -> None:
        """После смены темы — цвет системной каймы окна."""
        if self._styled_hwnd:
            _dwm_set(self._styled_hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if theme.dark else 0)
            _dwm_set(self._styled_hwnd, DWMWA_BORDER_COLOR, _colorref(theme.c("panel")))

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if int(self.winId()) != self._styled_hwnd:
            self._apply_frame()

    def event(self, e) -> bool:
        t = e.type()
        if t == QEvent.Type.WinIdChange:
            self._styled_hwnd = 0
            if self.isVisible():
                self._apply_frame()
        elif t == QEvent.Type.WindowStateChange:
            self.titlebar.sync_state()
        return super().event(e)

    # ---- сообщения Windows
    def nativeEvent(self, event_type, message):
        try:
            msg = wintypes.MSG.from_address(int(message))
        except (TypeError, ValueError):
            return super().nativeEvent(event_type, message)
        if msg.message == WM_NCCALCSIZE and msg.wParam:
            if user32.IsZoomed(msg.hWnd):
                # развёрнутое окно Windows выдвигает за край экрана на толщину рамки, а Qt для окон без рамки
                # иногда сразу ставит его по рабочей области — в обоих случаях содержимое = рабочая область
                work = _work_area(msg.hWnd)
                if work is not None:
                    r = NCCALCSIZE_PARAMS.from_address(msg.lParam).rgrc[0]
                    r.left, r.top, r.right, r.bottom = work.left, work.top, work.right, work.bottom
            return True, 0
        if msg.message == WM_NCHITTEST:
            return True, self._hit_test(msg)
        return super().nativeEvent(event_type, message)

    def _hit_test(self, msg) -> int:
        x = ctypes.c_short(msg.lParam & 0xFFFF).value
        y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
        hwnd = msg.hWnd
        if not user32.IsZoomed(hwnd) and self._maximizable_or_resizable():
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            dpi = _dpi(hwnd)
            b = _metric(SM_CXSIZEFRAME, dpi) + _metric(SM_CXPADDEDBORDER, dpi)
            left, right = x < rect.left + b, x >= rect.right - b
            top, bottom = y < rect.top + b, y >= rect.bottom - b
            if top and left:
                return HTTOPLEFT
            if top and right:
                return HTTOPRIGHT
            if bottom and left:
                return HTBOTTOMLEFT
            if bottom and right:
                return HTBOTTOMRIGHT
            if left:
                return HTLEFT
            if right:
                return HTRIGHT
            if top:
                return HTTOP
            if bottom:
                return HTBOTTOM
        pt = wintypes.POINT(x, y)
        user32.ScreenToClient(hwnd, ctypes.byref(pt))
        dpr = self.devicePixelRatioF() or 1.0
        return self.client_hit(pt.x / dpr, pt.y / dpr)

    def client_hit(self, lx: float, ly: float) -> int:
        """Точка внутри окна (логические пиксели): заголовок (тянуть) или содержимое. Наследник может решать иначе —
        окно программы спрашивает страницу (ui/app_window.py)."""
        if 0 <= ly < self.titlebar.height():
            child = self.childAt(int(lx), int(ly))
            if child is None or child is self.titlebar or child.property("drag"):
                return HTCAPTION
        return HTCLIENT

    def _maximizable_or_resizable(self) -> bool:
        return self.minimumSize() != self.maximumSize()

    def closeEvent(self, e) -> None:
        super().closeEvent(e)
        if e.isAccepted():
            self.closed.emit()
