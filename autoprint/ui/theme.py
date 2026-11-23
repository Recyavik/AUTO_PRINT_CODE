"""Оформление в стиле PasteTalk: токены цвета, шрифты, палитра Qt и таблица стилей (QSS).

Тема: «Как в Windows» (по умолчанию), «Тёмная», «Светлая». Виджеты, которые рисуют себя сами
(переключатель, библиотека, редактор кода), берут цвета через theme.c(...) в момент отрисовки
и перерисовываются по сигналу theme.changed.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

THEME_SYSTEM, THEME_DARK, THEME_LIGHT = "system", "dark", "light"
THEMES = {THEME_SYSTEM: "Как в Windows", THEME_DARK: "Тёмная", THEME_LIGHT: "Светлая"}


def _c(value: str, alpha: float | None = None) -> QColor:
    c = QColor(value)
    if alpha is not None:
        c.setAlphaF(alpha)
    return c


# Токены PasteTalk (app/renderer/settings/settings.css) + цвета редактора кода и ролей блоков
DARK = {
    "bg": _c("#1B1B1F"), "panel": _c("#232329"), "card": _c("#2A2A31"), "card_hover": _c("#32323A"),
    "stroke": _c("#FFFFFF", .075), "stroke_strong": _c("#FFFFFF", .16),
    "text": _c("#F4F4F7"), "dim": _c("#A6A6B2"), "faint": _c("#6E6E7A"),
    "accent": _c("#E9A72C"), "accent_hover": _c("#F0B54A"), "accent_soft": _c("#E9A72C", .13),
    "on_accent": _c("#1B1B1F"), "live": _c("#F2686C"), "ok": _c("#3FB950"), "close_hover": _c("#C42B1C"),
    "editor_bg": _c("#1F1F24"), "editor_fg": _c("#E6E6EC"), "editor_line": _c("#FFFFFF", .04),
    "editor_sel": _c("#3A4A6B"), "editor_gutter": _c("#5D5D68"), "editor_todo": _c("#5E5E69"),
    "editor_mark": _c("#E9A72C", .45),
    "role_text": _c("#A6A6B2"), "role_task": _c("#E9A72C"), "role_explain": _c("#7FB4FF"),
    "role_hint": _c("#B28CFF"),
    # суфлёр урока
    "role_say": _c("#7FB4FF"), "role_tell": _c("#6FD382"), "role_ask": _c("#E9A72C"), "role_do": _c("#A6A6B2"),
    "role_important": _c("#F2686C"), "role_show": _c("#B28CFF"), "role_trap": _c("#F2686C"),
    "role_extra": _c("#B28CFF"), "role_stage": _c("#E9A72C"), "role_image": _c("#6FC3DF"),
    "shadow": _c("#000000", .45),
}
LIGHT = {
    "bg": _c("#EDEDF1"), "panel": _c("#F6F6F9"), "card": _c("#FFFFFF"), "card_hover": _c("#F7F7FA"),
    "stroke": _c("#000000", .08), "stroke_strong": _c("#000000", .18),
    "text": _c("#16161A"), "dim": _c("#5A5A66"), "faint": _c("#9A9AA6"),
    "accent": _c("#B87400"), "accent_hover": _c("#A56800"), "accent_soft": _c("#B87400", .10),
    "on_accent": _c("#FFFFFF"), "live": _c("#C0272D"), "ok": _c("#237A32"), "close_hover": _c("#C42B1C"),
    "editor_bg": _c("#F7F7FA"), "editor_fg": _c("#16161A"), "editor_line": _c("#000000", .035),
    "editor_sel": _c("#D3E1FB"), "editor_gutter": _c("#A0A0AC"), "editor_todo": _c("#B9B9C3"),
    "editor_mark": _c("#B87400", .35),
    "role_text": _c("#5A5A66"), "role_task": _c("#B87400"), "role_explain": _c("#1F5FBF"),
    "role_hint": _c("#7A3DB8"),
    "role_say": _c("#1F5FBF"), "role_tell": _c("#237A32"), "role_ask": _c("#B87400"), "role_do": _c("#5A5A66"),
    "role_important": _c("#C0272D"), "role_show": _c("#7A3DB8"), "role_trap": _c("#C0272D"),
    "role_extra": _c("#7A3DB8"), "role_stage": _c("#B87400"), "role_image": _c("#0F7A99"),
    "shadow": _c("#1E2230", .18),
}

# Цвет состояния печати (точка в заголовке, полоса пульта)
STATE_TOKENS = {"idle": "ok", "countdown": "accent", "running": "accent", "paused": "live", "finished": "ok",
                "line_wait": "accent"}


def css(c: QColor) -> str:
    """QColor → значение для QSS (с прозрачностью)."""
    if c.alpha() == 255:
        return c.name()
    return f"rgba({c.red()},{c.green()},{c.blue()},{c.alpha()})"


def mix(a: QColor, b: QColor, t: float) -> QColor:
    """Смешать два цвета: t=0 — a, t=1 — b (прозрачность b учитывается)."""
    t *= b.alphaF()
    return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * t, a.greenF() + (b.greenF() - a.greenF()) * t,
                           a.blueF() + (b.blueF() - a.blueF()) * t, a.alphaF())


def _family(candidates: tuple[str, ...], fallback: str) -> str:
    families = set(QFontDatabase.families())
    return next((f for f in candidates if f in families), fallback)


class Theme(QObject):
    changed = Signal()
    about_to_change = Signal()     # перед сменой таблицы стилей: тяжёлые виджеты можно убрать и собрать заново

    def __init__(self) -> None:
        super().__init__()
        self.mode = THEME_SYSTEM
        self.dark = True
        self.tokens = DARK
        self.ui_family = "Segoe UI"
        self.display_family = "Segoe UI"
        self.mono_family = "Consolas"
        self._assets = Path(tempfile.gettempdir()) / "autoprintcode-ui"
        self._app: QApplication | None = None

    # ------------------------------------------------------------ доступ к цветам
    def c(self, name: str) -> QColor:
        return QColor(self.tokens[name])

    def css(self, name: str) -> str:
        return css(self.tokens[name])

    def font(self, px: int = 13, weight: QFont.Weight = QFont.Weight.Normal, family: str = "") -> QFont:
        f = QFont(family or self.ui_family)
        f.setPixelSize(px)
        f.setWeight(weight)
        return f

    def mono(self, px: int = 13) -> QFont:
        f = QFont(self.mono_family)
        f.setPixelSize(px)
        f.setStyleHint(QFont.StyleHint.Monospace)
        return f

    # ------------------------------------------------------------ установка
    def setup(self, app: QApplication, mode: str) -> None:
        self._app = app
        app.setStyle("Fusion")
        self.ui_family = _family(("Segoe UI Variable Text", "Segoe UI"), app.font().family())
        self.display_family = _family(("Segoe UI Variable Display", "Segoe UI Semibold", "Segoe UI"),
                                      self.ui_family)
        self.mono_family = _family(("Cascadia Mono", "Cascadia Code", "Consolas"), "Courier New")
        app.setFont(self.font(13))
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
        dark = self._system_dark() if self.mode == THEME_SYSTEM else self.mode == THEME_DARK
        self.dark = dark
        self.tokens = DARK if dark else LIGHT
        app = self._app
        if app is None:
            return
        self.about_to_change.emit()
        app.setPalette(self._palette())
        app.setStyleSheet(self._qss())
        self.changed.emit()

    def _palette(self) -> QPalette:
        p = QPalette()
        t = self.tokens
        roles = {
            QPalette.ColorRole.Window: t["bg"], QPalette.ColorRole.WindowText: t["text"],
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

    # ------------------------------------------------------------ картинки для QSS
    def _asset(self, name: str, svg: str) -> str:
        """QSS берёт стрелки и галочки только из файлов — пишем маленькие SVG во временную папку."""
        self._assets.mkdir(parents=True, exist_ok=True)
        path = self._assets / f"{name}-{'dark' if self.dark else 'light'}.svg"
        if not path.exists() or path.read_text(encoding="utf-8") != svg:
            path.write_text(svg, encoding="utf-8")
        return path.as_posix()

    def _chevron(self, name: str, d: str, color: QColor) -> str:
        return self._asset(name, f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="12" '
                                 f'height="12" fill="none" stroke="{color.name()}" stroke-width="2.4" '
                                 f'stroke-linecap="round" stroke-linejoin="round"><path d="{d}"/></svg>')

    # ------------------------------------------------------------ таблица стилей
    ROLE_CHIP_TOKENS = {"text": "role_text", "task": "role_task", "explain": "role_explain", "hint": "role_hint",
                        "say": "role_say", "tell": "role_tell", "ask": "role_ask", "do": "role_do",
                        "important": "role_important", "show": "role_show", "trap": "role_trap",
                        "extra": "role_extra", "code": "accent", "stage": "role_stage", "image": "role_image"}

    def _role_chips(self) -> str:
        """Плашка типа блока в редакторе — цвет роли на лёгком фоне того же цвета (как на суфлёре)."""
        out = []
        for key, tok in self.ROLE_CHIP_TOKENS.items():
            c = self.c(tok)
            bg = QColor(c)
            bg.setAlphaF(0.16 if self.dark else 0.11)
            out.append(f'QToolButton#roleChip[role="{key}"] {{ color: {css(c)}; background: {css(bg)}; }}')
        return "\n".join(out)

    def _qss(self) -> str:
        t = {k: css(v) for k, v in self.tokens.items()}
        down = self._chevron("chevron-down", "m6 9 6 6 6-6", self.c("dim"))
        up = self._chevron("chevron-up", "m18 15-6-6-6 6", self.c("dim"))
        check = self._chevron("check", "M20 6 9 17l-5-5", self.c("on_accent"))
        mono = self.mono_family
        display = self.display_family
        # смешанные (непрозрачные) цвета для заливки — rgba поверх карточки выглядит грязно
        hover = css(mix(self.c("bg"), self.c("stroke_strong"), 0.5))
        accent_pressed = css(mix(self.c("accent"), self.c("bg"), 0.15))
        kbd = self.c("on_accent")
        kbd.setAlphaF(0.62)
        kbd = css(kbd)
        return f"""
* {{ outline: none; }}
QWidget {{ color: {t['text']}; font-family: "{self.ui_family}"; font-size: 13px; }}
QLabel:disabled {{ color: {t['faint']}; }}
QMainWindow, QDialog, #appRoot, #settingsRoot {{ background: {t['bg']}; }}
QToolTip {{ background: {t['card']}; color: {t['text']}; border: 1px solid {t['stroke_strong']};
            border-radius: 4px; padding: 5px 8px; }}

/* ---------- заголовок окна ---------- */
#titleBar {{ background: {t['panel']}; border-bottom: 1px solid {t['stroke']}; }}
#titleText {{ font-size: 12px; font-weight: 600; }}
#titleStatus {{ color: {t['dim']}; font-size: 12px; }}
QToolButton#winBtn {{ background: transparent; border: none; border-radius: 0; }}
QToolButton#winBtn:hover {{ background: {t['stroke']}; }}
QToolButton#winBtn:pressed {{ background: {t['stroke_strong']}; }}
QToolButton#winClose {{ background: transparent; border: none; border-radius: 0; }}
QToolButton#winClose:hover {{ background: {t['close_hover']}; }}
QToolButton#logoBtn {{ background: transparent; border: none; border-radius: 5px; padding: 3px; }}
QToolButton#logoBtn:hover {{ background: {t['stroke']}; }}
QToolButton#logoBtn::menu-indicator {{ image: none; width: 0; }}
QToolButton#titleTool {{ background: transparent; border: none; border-radius: 5px; padding: 4px; }}
QToolButton#titleTool:hover {{ background: {t['stroke']}; }}
QToolButton#efirBtn {{ background: transparent; border: none; border-radius: 5px; padding: 4px 9px 4px 7px;
                       font-weight: 600; font-size: 12px; }}
QToolButton#efirBtn:hover {{ background: {t['stroke']}; }}

/* ---------- панели ---------- */
#navPanel {{ background: {t['panel']}; border-right: 1px solid {t['stroke']}; }}
#navGroup {{ color: {t['dim']}; font-size: 12px; font-weight: 600; padding: 2px 10px; }}
#navSep {{ background: {t['stroke']}; max-height: 1px; min-height: 1px; }}
QPushButton#navBtn {{ background: transparent; border: none; border-radius: 5px; text-align: left;
                      padding: 0 12px; min-height: 34px; color: {t['text']}; }}
QPushButton#navBtn:hover {{ background: {t['stroke']}; }}
QPushButton#navBtn:checked {{ background: {t['card']}; }}
QPushButton#updateBtn {{ background: {t['accent_soft']}; color: {t['accent']}; border: 1px solid {t['accent_soft']};
                         border-radius: 5px; text-align: left; padding: 0 10px; min-height: 32px; font-weight: 600; }}
QPushButton#updateBtn:hover {{ border-color: {t['accent']}; }}

QFrame#card {{ background: {t['card']}; border: 1px solid {t['stroke']}; border-radius: 7px; }}
#row {{ background: transparent; }}
#row[first="false"] {{ border-top: 1px solid {t['stroke']}; }}
#rowTitle {{ font-size: 13px; }}
#rowSub {{ color: {t['dim']}; font-size: 12px; }}
#rowTitle:disabled, #rowSub:disabled {{ color: {t['faint']}; }}
#groupTitle {{ color: {t['dim']}; font-size: 12px; font-weight: 600; }}
#pageTitle {{ font-family: "{display}"; font-size: 22px; font-weight: 600; }}
#lede {{ color: {t['dim']}; font-size: 13px; }}
#dim {{ color: {t['dim']}; }}
#faint {{ color: {t['faint']}; }}
#mono {{ font-family: "{mono}"; color: {t['dim']}; font-size: 12px; }}
QFrame#note {{ background: {t['accent_soft']}; border: none; border-radius: 7px; }}
#noteText {{ color: {t['text']}; }}
QFrame#vsep {{ background: {t['stroke']}; min-width: 1px; max-width: 1px; border: none; }}
QFrame#hsep {{ background: {t['stroke']}; min-height: 1px; max-height: 1px; border: none; }}
#prompterTitle {{ font-size: 12px; font-weight: 600; color: {t['dim']}; }}
#prompterSay {{ font-family: "{display}"; font-size: 18px; color: {t['text']}; }}
#prompterCode {{ font-family: "{mono}"; font-size: 12px; color: {t['dim']}; }}
#pill {{ border: 1px solid {t['stroke_strong']}; border-radius: 3px; padding: 0 6px; font-size: 11px;
         color: {t['dim']}; }}
#pill[tone="accent"] {{ border-color: {t['accent']}; color: {t['accent']}; }}
#pill[tone="ok"] {{ border-color: {t['ok']}; color: {t['ok']}; }}
#pill[tone="warn"] {{ border-color: {t['live']}; color: {t['live']}; }}

/* ---------- кнопки ---------- */
QPushButton {{ background: {t['bg']}; border: 1px solid {t['stroke_strong']}; border-radius: 4px;
               padding: 0 12px; min-height: 30px; color: {t['text']}; }}
QPushButton:hover {{ background: {hover}; }}
QPushButton:pressed {{ background: {t['stroke_strong']}; }}
QPushButton:disabled {{ color: {t['faint']}; border-color: {t['stroke']}; }}
QPushButton[accent="true"] {{ background: {t['accent']}; color: {t['on_accent']}; border: 1px solid {t['accent']};
                              font-weight: 600; }}
QPushButton[accent="true"]:hover {{ background: {t['accent_hover']}; border-color: {t['accent_hover']}; }}
QPushButton[accent="true"]:pressed {{ background: {accent_pressed}; }}
QPushButton[accent="true"]:disabled {{ background: {t['stroke_strong']}; border-color: transparent;
                                       color: {t['faint']}; }}
QPushButton[quiet="true"] {{ background: transparent; border-color: transparent; color: {t['dim']}; }}
QPushButton[quiet="true"]:hover {{ color: {t['text']}; background: {t['stroke']}; }}
QPushButton#bigBtn {{ min-height: 36px; padding: 0; }}
QPushButton[accent="true"] QLabel {{ color: {t['on_accent']}; background: transparent; }}
QPushButton[accent="true"] QLabel#bigBtnText {{ font-weight: 600; }}
QPushButton[accent="true"] QLabel#kbd {{ color: {kbd}; font-family: "{mono}"; font-size: 11px; }}
QPushButton#addBtn {{ background: transparent; border: 1px dashed {t['stroke_strong']}; color: {t['dim']};
                      min-height: 34px; }}
QPushButton#addBtn:hover {{ color: {t['text']}; border-color: {t['accent']}; background: {t['accent_soft']}; }}
QPushButton#segBtn {{ background: {t['bg']}; border: 1px solid {t['stroke_strong']}; border-radius: 0;
                      padding: 0 11px; min-height: 28px; color: {t['dim']}; margin-left: -1px; }}
QPushButton#segBtn[pos="first"] {{ border-top-left-radius: 4px; border-bottom-left-radius: 4px; margin-left: 0; }}
QPushButton#segBtn[pos="last"] {{ border-top-right-radius: 4px; border-bottom-right-radius: 4px; }}
QPushButton#segBtn[pos="only"] {{ border-radius: 4px; margin-left: 0; }}
QPushButton#segBtn:hover {{ color: {t['text']}; }}
QPushButton#segBtn:checked {{ background: {t['accent_soft']}; color: {t['accent']}; font-weight: 600; }}
QPushButton#combo {{ font-family: "{mono}"; font-size: 12px; min-width: 150px; text-align: center; }}
QPushButton#combo[capturing="true"] {{ border-color: {t['accent']}; color: {t['accent']}; }}
QPushButton#combo[clash="true"] {{ border-color: {t['live']}; color: {t['live']}; }}
QToolButton#iconBtn {{ background: transparent; border: 1px solid transparent; border-radius: 4px; padding: 3px; }}
QToolButton#iconBtn:hover {{ background: {t['stroke']}; }}
QToolButton#iconBtn:pressed {{ background: {t['stroke_strong']}; }}
QToolButton#iconBtn:checked {{ background: transparent; }}
QToolButton#iconBtn[framed="true"] {{ background: {t['bg']}; border: 1px solid {t['stroke_strong']}; }}
QToolButton#iconBtn[framed="true"]:hover {{ background: {hover}; }}
QToolButton#iconBtn::menu-indicator {{ image: none; width: 0; }}
QToolButton#armBtn {{ background: transparent; border: 1px solid {t['stroke_strong']}; border-radius: 4px;
                      padding: 1px 8px; color: {t['dim']}; font-size: 12px; }}
QToolButton#armBtn:hover {{ color: {t['text']}; border-color: {t['accent']}; }}
QToolButton#armBtn:checked {{ border-color: {t['accent']}; color: {t['accent']}; background: {t['accent_soft']};
                              font-weight: 600; }}
QToolButton#textBtn {{ background: transparent; border: none; border-radius: 4px; padding: 2px 8px;
                       color: {t['dim']}; font-size: 12px; }}
QToolButton#textBtn:hover {{ background: {t['stroke']}; color: {t['text']}; }}
QToolButton#pickBtn {{ background: transparent; border: 1px solid transparent; border-radius: 4px; padding: 1px 8px;
                       color: {t['dim']}; font-size: 12px; min-height: 22px; }}
QToolButton#pickBtn:hover {{ border-color: {t['stroke_strong']}; color: {t['text']}; }}
QToolButton#pickBtn::menu-indicator, QToolButton#roleChip::menu-indicator {{ image: none; width: 0; }}
QToolButton#roleChip {{ border: 1px solid transparent; border-radius: 10px; padding: 1px 9px 1px 7px;
                        font-size: 11px; font-weight: 700; min-height: 20px; }}
QToolButton#roleChip:hover {{ border-color: {t['stroke_strong']}; }}
{self._role_chips()}

/* ---------- поля ввода ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit#mdEdit, QKeySequenceEdit QLineEdit {{
    background: {t['bg']}; border: 1px solid {t['stroke_strong']}; border-radius: 4px; padding: 0 8px;
    min-height: 28px; selection-background-color: {t['accent']}; selection-color: {t['on_accent']}; }}
QPlainTextEdit#mdEdit {{ padding: 6px 8px; font-family: "{mono}"; font-size: 12px; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit#mdEdit:focus {{
    border-color: {t['accent']}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    color: {t['faint']}; border-color: {t['stroke']}; }}
QLineEdit#search {{ background: {t['bg']}; padding-left: 4px; }}
QLineEdit#blockTitle {{ background: transparent; border: 1px solid transparent; font-weight: 600; padding: 0 4px;
                        min-height: 24px; }}
QLineEdit#blockTitle:hover {{ border-color: {t['stroke']}; }}
QLineEdit#blockTitle:focus {{ border-color: {t['accent']}; background: {t['bg']}; }}
QSpinBox, QDoubleSpinBox {{ padding-right: 22px; font-family: "{mono}"; font-size: 12px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right;
    width: 20px; border: none; background: transparent; margin-top: 2px; margin-right: 2px; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right;
    width: 20px; border: none; background: transparent; margin-bottom: 2px; margin-right: 2px; }}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {t['stroke']}; border-radius: 3px; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{up}"); width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{down}"); width: 10px; height: 10px; }}
QComboBox {{ padding-right: 26px; }}
QComboBox:hover {{ background: {hover}; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 24px; border: none; }}
QComboBox::down-arrow {{ image: url("{down}"); width: 11px; height: 11px; }}
QComboBox QAbstractItemView {{ background: {t['card']}; border: 1px solid {t['stroke_strong']}; padding: 4px;
                               selection-background-color: {t['accent_soft']}; selection-color: {t['text']};
                               outline: none; }}
QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 0 8px; border-radius: 4px; }}
QComboBox#kindCombo, QComboBox#langCombo {{ background: transparent; border: 1px solid transparent; min-height: 24px;
                                            color: {t['dim']}; font-size: 12px; padding-left: 6px; }}
QComboBox#kindCombo:hover, QComboBox#langCombo:hover {{ border-color: {t['stroke_strong']}; color: {t['text']}; }}
QComboBox#langCombo QLineEdit {{ background: transparent; border: none; min-height: 20px; padding: 0;
                                 color: {t['dim']}; font-size: 12px; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {t['stroke_strong']};
                        background: {t['bg']}; }}
QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; image: url("{check}"); }}

/* ---------- прогресс (ползунок рисуется сам — widgets.Slider) ---------- */
QProgressBar {{ background: {t['stroke']}; border: none; border-radius: 2px; max-height: 4px; min-height: 4px; }}
QProgressBar::chunk {{ background: {t['accent']}; border-radius: 2px; }}

/* ---------- прокрутка ---------- */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget#page {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['stroke_strong']}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t['faint']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t['stroke_strong']}; border-radius: 3px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: {t['faint']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* ---------- списки, меню ---------- */
QListWidget#library {{ background: transparent; border: none; }}
QListWidget#library QLineEdit {{ min-height: 26px; }}
QMenu {{ background: {t['card']}; border: 1px solid {t['stroke_strong']}; border-radius: 7px; padding: 5px; }}
QMenu::item {{ padding: 6px 26px 6px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {t['accent_soft']}; color: {t['text']}; }}
QMenu::item:disabled {{ color: {t['faint']}; }}
QMenu::icon {{ padding-left: 8px; }}
QMenu::separator {{ height: 1px; background: {t['stroke']}; margin: 5px 6px; }}

/* ---------- блоки образца ---------- */
QFrame#block {{ background: {t['card']}; border: 1px solid {t['stroke']}; border-radius: 7px; padding: 1px; }}
QFrame#block[armed="true"] {{ border: 2px solid {t['accent']}; padding: 0; }}
QFrame#codeFrame {{ background: {t['editor_bg']}; border: 1px solid {t['stroke']}; border-radius: 5px; }}
QPlainTextEdit#codeEditor {{ background: transparent; border: none; color: {t['editor_fg']};
                             selection-background-color: {t['editor_sel']}; selection-color: {t['editor_fg']}; }}
QTextBrowser#mdView {{ background: transparent; border: none; padding: 0; color: {t['text']}; }}

/* ---------- тост ---------- */
QFrame#toast {{ background: {t['card']}; border: 1px solid {t['stroke_strong']}; border-radius: 7px; }}
QFrame#toast[tone="warn"] {{ border-color: {t['live']}; }}
#toastText {{ color: {t['text']}; }}

/* ---------- диалоги ---------- */
QMessageBox, QInputDialog {{ background: {t['panel']}; }}
QTextBrowser {{ background: {t['bg']}; border: 1px solid {t['stroke']}; border-radius: 5px; padding: 6px; }}
"""


theme = Theme()
