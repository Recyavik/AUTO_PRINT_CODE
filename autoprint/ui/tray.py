"""Значок программы в трее: состояние набора кода, меню, сообщения, когда окно скрыто."""
from __future__ import annotations

from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .. import APP_NAME
from . import logo


class Tray:
    """Меню: «Показать окно», «Маленький режим», «Старт / пауза», «Стоп», «Обновление…» (только если есть),
    «Настройки…», «Выход». Щелчок по значку — показать окно."""

    def __init__(self, app) -> None:
        self.app = app
        self.icons = {k: logo.make_icon(k) for k in (logo.IDLE, logo.RUNNING, logo.PAUSED)}
        self.icon = QSystemTrayIcon(self.icons[logo.IDLE], app)
        menu = QMenu()
        menu.addAction("Показать окно", app.show_window)
        menu.addAction("Маленький режим", lambda: app.set_compact(True))
        menu.addSeparator()
        menu.addAction("Старт / пауза", lambda: app.printer.toggle(
            countdown=max(1, int(app.settings.button_countdown_s)), pressed=True))
        menu.aboutToShow.connect(app.printer.remember_press)
        menu.addAction("Стоп", app.printer.stop)
        menu.addSeparator()
        self.update_action = menu.addAction("Обновление…", app.open_update_dialog)
        self.update_action.setVisible(False)
        menu.addAction("Настройки…", lambda: app.open_settings())
        menu.addAction("Выход", app.quit_app)
        self.menu = menu
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(lambda r: app.show_window()
                                    if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.icon.setToolTip(APP_NAME)
        self.icon.show()

    def items(self) -> list[str]:
        """Подписи пунктов меню (для проверки)."""
        return [a.text() for a in self.menu.actions() if not a.isSeparator()]

    def set_state(self, kind: str, tip: str) -> None:
        self.icon.setIcon(self.icons.get(kind, self.icons[logo.IDLE]))
        self.icon.setToolTip(tip)

    def message(self, text: str, warn: bool = False, ms: int = 3000) -> None:
        self.icon.showMessage(APP_NAME, text, self.icons[logo.PAUSED if warn else logo.IDLE], ms)

    def show_update(self, text: str | None) -> None:
        self.update_action.setVisible(bool(text))
        if text:
            self.update_action.setText(text)

    def visible(self) -> bool:
        return self.icon.isVisible()

    def hide(self) -> None:
        self.icon.hide()
