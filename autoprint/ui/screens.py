"""На каком мониторе открывать окно при запуске.

Настройка start_screen: "" — где было в прошлый раз, "primary" — основной монитор, иначе имя экрана Qt
(модель монитора, например «LG HDR 4K»). Нужна, чтобы случайно закрытое окно при новом запуске не появилось
на мониторе демонстрации. Если выбранного монитора сейчас нет — берётся основной.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QGuiApplication, QScreen
from PySide6.QtWidgets import QWidget

LAST = ""
PRIMARY = "primary"


def screen_choices(current: QScreen | None = None) -> list[tuple[str, str]]:
    """[(подпись, значение)] для выбора в настройках."""
    primary = QGuiApplication.primaryScreen()
    out = [("Где было в прошлый раз", LAST), ("Основной монитор", PRIMARY)]
    pc = primary.geometry().center()
    # сначала основной, затем слева направо — как в веб-версии
    screens = sorted(QGuiApplication.screens(), key=lambda sc: (sc is not primary, sc.geometry().x(), sc.geometry().y()))
    for i, sc in enumerate(screens, start=1):
        c = sc.geometry().center()
        side = "" if sc is primary else ("слева" if c.x() < pc.x() else "справа" if c.x() > pc.x()
                                         else "сверху" if c.y() < pc.y() else "снизу")
        label = f"Монитор {i}: {sc.name() or sc.model() or '?'}"
        notes = [n for n, on in (("основной", sc is primary), (side, bool(side)), ("окно сейчас здесь", sc is current)) if on]
        if notes:
            label += f" ({', '.join(notes)})"
        out.append((label, sc.name()))
    return out


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
