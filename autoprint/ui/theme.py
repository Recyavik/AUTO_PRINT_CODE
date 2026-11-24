"""Тема программы: «Как в Windows» (по умолчанию), «Тёмная», «Светлая».

С 1.0 всё окно — страница (её цвета — в page/app/app.css); здесь — что осталось на Qt: светлая или тёмная сейчас
(theme.dark, сигнал changed), цвета рамки окна и системных окошек (frameless.py), и простая таблица стилей для меню
значка в трее, подсказок, кнопок на заставке окна и окошек вроде QMessageBox.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

THEME_SYSTEM, THEME_DARK, THEME_LIGHT = "system", "dark", "light"
THEMES = {THEME_SYSTEM: "Как в Windows", THEME_DARK: "Тёмная", THEME_LIGHT: "Светлая"}


def _c(value: str, alpha: float | None = None) -> QColor:
    c = QColor(value)
    if alpha is not None:
        c.setAlphaF(alpha)
    return c


# те же цвета, что у страницы окна (page/app/app.css: --ground, --panel, --raised, --line, --text…)
DARK = {
    "bg": _c("#161A22"), "panel": _c("#1C212B"), "card": _c("#242A36"), "hover": _c("#2D3442"),
    "stroke": _c("#E9EDF3", .08), "stroke_strong": _c("#E9EDF3", .16),
    "text": _c("#E9EDF3"), "dim": _c("#A6AFBE"), "faint": _c("#858FA0"),
    "accent": _c("#F2B54D"), "accent_soft": _c("#F2B54D", .12), "on_accent": _c("#1E1606"), "live": _c("#FF6B5E"),
}
LIGHT = {
    "bg": _c("#EEF0F3"), "panel": _c("#FFFFFF"), "card": _c("#FFFFFF"), "hover": _c("#E7EAEF"),
    "stroke": _c("#161A22", .08), "stroke_strong": _c("#161A22", .16),
    "text": _c("#181C24"), "dim": _c("#525B6B"), "faint": _c("#636C7D"),
    "accent": _c("#2B58CF"), "accent_soft": _c("#2B58CF", .08), "on_accent": _c("#FFFFFF"), "live": _c("#D2382E"),
}


def css(c: QColor) -> str:
    """QColor → значение для QSS (с прозрачностью)."""
    if c.alpha() == 255:
        return c.name()
    return f"rgba({c.red()},{c.green()},{c.blue()},{c.alpha()})"


def _family(candidates: tuple[str, ...], fallback: str) -> str:
    families = set(QFontDatabase.families())
    return next((f for f in candidates if f in families), fallback)


class Theme(QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.mode = THEME_SYSTEM
        self.dark = True
        self.tokens = DARK
        self.ui_family = "Segoe UI"
        self._app: QApplication | None = None

    def c(self, name: str) -> QColor:
        return QColor(self.tokens[name])

    def css(self, name: str) -> str:
        return css(self.tokens[name])

    # ------------------------------------------------------------ установка
    def setup(self, app: QApplication, mode: str) -> None:
        self._app = app
        app.setStyle("Fusion")
        self.ui_family = _family(("Segoe UI Variable Text", "Segoe UI"), app.font().family())
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(lambda *_: self._apply() if self.mode == THEME_SYSTEM else None)
        self.mode = mode if mode in THEMES else THEME_SYSTEM
        self._apply()

    def set_mode(self, mode: str) -> None:
        mode = mode if mode in THEMES else THEME_SYSTEM
        if mode != self.mode:
            self.mode = mode
            self._apply()

    def _system_dark(self) -> bool:
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorScheme"):
            scheme = hints.colorScheme()
            if scheme == Qt.ColorScheme.Light:
                return False
            if scheme == Qt.ColorScheme.Dark:
                return True
        return True

    def _apply(self) -> None:
        self.dark = self._system_dark() if self.mode == THEME_SYSTEM else self.mode == THEME_DARK
        self.tokens = DARK if self.dark else LIGHT
        app = self._app
        if app is None:
            return
        app.setPalette(self._palette())
        app.setStyleSheet(self._qss())
        self.changed.emit()

    def _palette(self) -> QPalette:
        p = QPalette()
        t = self.tokens
        roles = {
            QPalette.ColorRole.Window: t["panel"], QPalette.ColorRole.WindowText: t["text"],
            QPalette.ColorRole.Base: t["bg"], QPalette.ColorRole.AlternateBase: t["panel"],
            QPalette.ColorRole.Text: t["text"], QPalette.ColorRole.Button: t["card"],
            QPalette.ColorRole.ButtonText: t["text"], QPalette.ColorRole.ToolTipBase: t["card"],
            QPalette.ColorRole.ToolTipText: t["text"], QPalette.ColorRole.Highlight: t["accent"],
            QPalette.ColorRole.HighlightedText: t["on_accent"], QPalette.ColorRole.Link: t["accent"],
            QPalette.ColorRole.PlaceholderText: t["faint"], QPalette.ColorRole.BrightText: t["live"],
        }
        for role, color in roles.items():
            p.setColor(role, QColor(color))
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
            p.setColor(QPalette.ColorGroup.Disabled, role, QColor(t["faint"]))
        return p

    def _qss(self) -> str:
        t = {k: css(v) for k, v in self.tokens.items()}
        return f"""
QWidget {{ color: {t['text']}; font-family: "{self.ui_family}"; font-size: 13px; }}
QDialog, QMessageBox {{ background: {t['panel']}; }}
QToolTip {{ background: {t['card']}; color: {t['text']}; border: 1px solid {t['stroke_strong']};
            border-radius: 6px; padding: 5px 8px; }}
QPushButton {{ background: {t['card']}; border: 1px solid {t['stroke_strong']}; border-radius: 8px;
               padding: 0 14px; min-height: 32px; color: {t['text']}; }}
QPushButton:hover {{ background: {t['hover']}; border-color: {t['accent']}; }}
QPushButton:default {{ background: {t['accent']}; color: {t['on_accent']}; border-color: {t['accent']}; font-weight: 600; }}
QPushButton:disabled {{ color: {t['faint']}; border-color: {t['stroke']}; }}
QMenu {{ background: {t['card']}; border: 1px solid {t['stroke_strong']}; border-radius: 10px; padding: 5px; }}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t['accent_soft']}; color: {t['text']}; }}
QMenu::item:disabled {{ color: {t['faint']}; }}
QMenu::icon {{ padding-left: 8px; }}
QMenu::separator {{ height: 1px; background: {t['stroke']}; margin: 5px 6px; }}
"""


theme = Theme()
