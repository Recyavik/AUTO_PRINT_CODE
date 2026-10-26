"""Мониторы: какой показывают зрителям (демонстрация), на какой выводить подсказки (управление)."""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QScreen
from PySide6.QtWidgets import QWidget

from ..store import Settings
from . import style


def screens() -> list[QScreen]:
    return QGuiApplication.screens()


def describe(screen: QScreen) -> str:
    i = screens().index(screen) + 1 if screen in screens() else 0
    g = screen.geometry()
    model = (screen.model() or screen.manufacturer() or "").strip()
    primary = " · основной" if screen == QGuiApplication.primaryScreen() else ""
    return f"Монитор {i}: {g.width()}×{g.height()}{' · ' + model if model else ''}{primary}"


def by_name(name: str) -> QScreen | None:
    return next((s for s in screens() if s.name() == name), None) if name else None


def demo_screen(s: Settings) -> QScreen:
    """Монитор демонстрации: выбранный, иначе основной (обычно его и показывают)."""
    return by_name(s.demo_screen) or QGuiApplication.primaryScreen()


def control_screen(s: Settings) -> QScreen:
    """Монитор управления: выбранный (если это не монитор демонстрации), иначе любой другой.
    Если монитор один — тот же: подсказка встанет в угол."""
    demo = demo_screen(s)
    chosen = by_name(s.control_screen)
    if chosen is not None and chosen != demo:
        return chosen
    return next((x for x in screens() if x != demo), demo)


class _Badge(QWidget):
    """Крупный номер монитора — «Показать номера мониторов»."""

    def __init__(self, screen: QScreen, number: int, note: str) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.number, self.note = number, note
        g = screen.geometry()
        w, h = 420, 300
        self.setGeometry(QRect(g.center().x() - w // 2, g.center().y() - h // 2, w, h))

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(style.SURFACE2))
        p.setPen(QColor(style.BRAND))
        p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 28, 28)
        p.setPen(QColor(style.BRAND_BRIGHT))
        p.setFont(QFont("Segoe UI", 110, QFont.Weight.Black))
        p.drawText(self.rect().adjusted(0, -30, 0, -30), Qt.AlignmentFlag.AlignCenter, str(self.number))
        p.setPen(QColor(style.INK))
        p.setFont(QFont("Segoe UI", 14, QFont.Weight.DemiBold))
        p.drawText(self.rect().adjusted(10, 0, -10, -24), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                   self.note)


def identify(s: Settings, ms: int = 3000) -> list[QWidget]:
    """На каждом мониторе — его номер и роль на пару секунд."""
    demo, control = demo_screen(s), control_screen(s)
    shown = []
    for i, sc in enumerate(screens(), start=1):
        role = "демонстрация" if sc == demo else ("управление" if sc == control else "")
        b = _Badge(sc, i, role)
        b.show()
        QTimer.singleShot(ms, b.close)
        shown.append(b)
    return shown
