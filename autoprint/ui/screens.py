"""На каком мониторе открывать окно при запуске.

Настройка start_screen: "" — где было в прошлый раз, "primary" — основной монитор, иначе имя экрана Qt
(модель монитора, например «LG HDR 4K»). Нужна, чтобы случайно закрытое окно при новом запуске не появилось
на мониторе демонстрации. Если выбранного монитора сейчас нет — берётся основной.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen, QScreen
from PySide6.QtWidgets import QWidget

LAST = ""
PRIMARY = "primary"


def ordered_screens() -> list[QScreen]:
    """Мониторы в порядке номеров: сначала основной, затем по положению — как в веб-версии."""
    primary = QGuiApplication.primaryScreen()
    return sorted(QGuiApplication.screens(), key=lambda sc: (sc is not primary, sc.geometry().x(), sc.geometry().y()))


def screen_choices(current: QScreen | None = None) -> list[tuple[str, str]]:
    """[(подпись, значение)] для выбора в настройках. Номер — как у «Определить»."""
    primary = QGuiApplication.primaryScreen()
    out = [("Где было в прошлый раз", LAST), ("Основной монитор", PRIMARY)]
    for i, sc in enumerate(ordered_screens(), start=1):
        label = f"Монитор {i}: {sc.name() or sc.model() or '?'}"
        notes = [n for n, on in (("основной", sc is primary), ("окно сейчас здесь", sc is current)) if on]
        if notes:
            label += f" ({', '.join(notes)})"
        out.append((label, sc.name()))
    return out


class _Badge(QWidget):
    """Крупный номер монитора на пару секунд — кнопка «Определить»."""

    def __init__(self, screen: QScreen, number: int, note: str) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.number, self.note = number, note
        rect = QRect(0, 0, 420, 300)
        rect.moveCenter(screen.geometry().center())
        self.setGeometry(rect)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor("#1e2229"))
        p.setPen(QPen(QColor("#8b5cf6"), 4))
        p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 28, 28)
        p.setPen(QColor("#a78bfa"))
        p.setFont(QFont("Segoe UI", 110, QFont.Weight.Black))
        p.drawText(self.rect().adjusted(0, -30, 0, -30), Qt.AlignmentFlag.AlignCenter, str(self.number))
        p.setPen(QColor("#e6e8eb"))
        p.setFont(QFont("Segoe UI", 14, QFont.Weight.DemiBold))
        p.drawText(self.rect().adjusted(10, 0, -10, -24), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                   self.note)


def identify(ms: int = 2500) -> list[QWidget]:
    """На каждом мониторе — его номер (как в списке «Окно при запуске») на пару секунд."""
    primary = QGuiApplication.primaryScreen()
    shown = []
    for i, sc in enumerate(ordered_screens(), start=1):
        b = _Badge(sc, i, "основной" if sc is primary else (sc.name() or ""))
        b.show()
        QTimer.singleShot(ms, b.close)
        shown.append(b)
    return shown


def target_screen(value: str) -> QScreen | None:
    if value == LAST:
        return None
    primary = QGuiApplication.primaryScreen()
    if value == PRIMARY:
        return primary
    return next((sc for sc in QGuiApplication.screens() if sc.name() == value), primary)


def place_on_start_screen(win: QWidget, value: str) -> None:
    """Перенести окно (ещё не показанное, после restoreGeometry) на выбранный монитор."""
    sc = target_screen(value)
    if sc is None:
        return
    avail = sc.availableGeometry()
    geo = win.normalGeometry() if win.isMaximized() or win.isFullScreen() else win.geometry()
    if geo.isValid() and avail.contains(geo.center()):
        return   # уже на нужном мониторе — положение из прошлого раза сохраняем
    w = min(geo.width() if geo.isValid() else 1200, avail.width())
    h = min(geo.height() if geo.isValid() else 780, avail.height())
    rect = QRect(0, 0, w, h)
    rect.moveCenter(avail.center())
    state = win.windowState()
    if state & (Qt.WindowState.WindowMaximized | Qt.WindowState.WindowFullScreen):
        # развёрнутое окно разворачивается там, где лежит его обычное положение
        win.setWindowState(Qt.WindowState.WindowNoState)
        win.setGeometry(rect)
        win.setWindowState(state)
    else:
        win.setGeometry(rect)
