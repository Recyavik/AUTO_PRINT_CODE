"""Оформление в стиле страницы «Повестка эфира» (1Т): две темы — тёмная (тёмно-фиолетовый фон) и светлая.

Цвета — переменные модуля (style.BG, style.INK…): виджеты берут их в момент оформления, поэтому apply(тема)
меняет всё сразу — окно перерисовывает себя заново (MainWindow.set_theme), без перезапуска и не прерывая эфир.
Экран демонстрации (заставка перерыва, видео) от темы не зависит: это то, что видят зрители.
"""
from pathlib import Path

# галочка флажка — своя картинка: на тёмной теме у стандартного флажка пропадала рамка
CHECK_SVG = (Path(__file__).resolve().parent / "check.svg").as_posix()
# стрелки счётчиков — тоже свои: иначе поле ввода счётчика перекрывало кнопки ▲▼ и они не нажимались;
# у светлой темы — тёмные (arrow_up_light.svg)
_UI = Path(__file__).resolve().parent

THEME_NAMES = {"dark": "Тёмная", "light": "Светлая"}

THEMES = {
    "dark": {
        "BG": "#130C1F", "SURFACE": "#221836", "SURFACE2": "#2A1E44", "LINE": "#3A2B5C",
        "BRAND": "#8E4DFF", "BRAND_BRIGHT": "#B98CFF", "INK": "#F4EFFC", "MUTED": "#9C8FBC", "DIM": "#6E6191",
        "ON": "#39C08A", "EYE": "#5FD0A0", "AMBER": "#F2B64B", "RED": "#F2688B",
        # подложки поверх фона: поля ввода, кнопки, полосы
        "TINT": "rgba(255,255,255,0.05)", "TINT2": "rgba(255,255,255,0.08)", "TINT_LIST": "rgba(255,255,255,0.02)",
        "HOVER": "rgba(142,77,255,0.18)", "SELECT": "rgba(142,77,255,0.30)", "ON_BRAND": "white",
        # повестка: строка «сейчас», зарядка, перерыв; панель урока
        "ROW_NOW": "rgba(142,77,255,0.28)", "ROW_NOW_INK": "white", "ROW_EYES": "rgba(95,208,160,0.08)",
        "ROW_BREAK": "rgba(255,255,255,0.05)", "LESSON_BG": "rgba(255,255,255,0.02)",
        "LESSON_NOW_BG": "rgba(142,77,255,0.07)",
        # полоса эфира
        "TL_BASE": "rgba(255,255,255,0.06)", "TL_BREAK": "rgba(242,182,75,0.16)", "TL_BREAK_DONE_INK": "#1A1206",
        "TL_MARK": "white",
        # карточки напоминаний: (фон, рамка) — скоро / сейчас / время вышло
        "CARD_SOON": ("#1C2140", "#34406E"), "CARD_NOW": ("#3A2068", "#5B3A99"), "CARD_OVER": ("#3A1A2E", "#6E2E4E"),
        # пульты: (фон, рамка, кнопка, кнопка при наведении) — видео / перерыв
        "PANEL_VIDEO": ("#1A2E2A", "#2F5A4E", "#2E7D62", "#379873"),
        "PANEL_BREAK": ("#2E2516", "#5E4A26", "#9A6B14", "#B07C18"),
        # полоса «Уроки» в редакторе
        "STRIP": ("rgba(110,175,255,0.10)", "rgba(110,175,255,0.35)", "rgba(110,175,255,0.25)"),
        "ARROWS": "",
    },
    "light": {
        # мягкая лаванда вместо белого: фон приглушённый, панели на тон светлее, белых пятен нет
        "BG": "#D9D1E8", "SURFACE": "#E3DBEF", "SURFACE2": "#D5CBE7", "LINE": "#B9ABD3",
        "BRAND": "#7A3FE0", "BRAND_BRIGHT": "#6430C4", "INK": "#241A38", "MUTED": "#5E5378", "DIM": "#8C82A6",
        "ON": "#17805A", "EYE": "#15806A", "AMBER": "#9C6410", "RED": "#BE3150",
        "TINT": "rgba(255,255,255,0.30)", "TINT2": "rgba(36,26,56,0.08)", "TINT_LIST": "rgba(255,255,255,0.15)",
        "HOVER": "rgba(122,63,224,0.12)", "SELECT": "rgba(122,63,224,0.18)", "ON_BRAND": "white",
        "ROW_NOW": "rgba(122,63,224,0.17)", "ROW_NOW_INK": "#241A38", "ROW_EYES": "rgba(21,128,106,0.09)",
        "ROW_BREAK": "rgba(156,100,16,0.08)", "LESSON_BG": "rgba(255,255,255,0.14)",
        "LESSON_NOW_BG": "rgba(122,63,224,0.07)",
        "TL_BASE": "rgba(36,26,56,0.09)", "TL_BREAK": "rgba(156,100,16,0.15)", "TL_BREAK_DONE_INK": "white",
        "TL_MARK": "#241A38",
        "CARD_SOON": ("#D2D8EC", "#AAB5DA"), "CARD_NOW": ("#DACCF1", "#B69CE3"), "CARD_OVER": ("#E8CFD8", "#D3A2B3"),
        "PANEL_VIDEO": ("#CCE4DA", "#9CCBB8", "#15806A", "#119371"),
        "PANEL_BREAK": ("#E8DAC0", "#D2B583", "#9C6410", "#B07316"),
        "STRIP": ("rgba(59,130,246,0.09)", "rgba(59,130,246,0.32)", "rgba(59,130,246,0.18)"),
        "ARROWS": "_light",
    },
}

current = ""
KIND_COLOR: dict[str, str] = {}
APP_QSS = ""


def apply(name: str) -> str:
    """Включить тему: цвета модуля и общая таблица стилей. Неизвестная — тёмная. Возвращает имя темы."""
    global current, KIND_COLOR, APP_QSS
    name = name if name in THEMES else "dark"
    t = THEMES[name]
    globals().update(t)
    current = name
    KIND_COLOR = {"break": t["AMBER"], "eyes": t["EYE"], "": t["BRAND_BRIGHT"]}
    APP_QSS = _qss()
    return name


def _qss() -> str:
    g = globals()
    up = (_UI / f"arrow_up{g['ARROWS']}.svg").as_posix()
    down = (_UI / f"arrow_down{g['ARROWS']}.svg").as_posix()
    return f"""
QWidget {{ background: {g['BG']}; color: {g['INK']}; font-family: 'Segoe UI', 'Rubik', sans-serif; font-size: 10.5pt; }}
QDialog, QMainWindow {{ background: {g['BG']}; }}
QFrame#card {{ background: {g['SURFACE']}; border: 1px solid {g['LINE']}; border-radius: 16px; }}
QLabel {{ background: transparent; }}
QLabel#muted {{ color: {g['MUTED']}; }}
QLabel#hint {{ color: {g['DIM']}; font-size: 9pt; }}
QGroupBox {{ border: 1px solid {g['LINE']}; border-radius: 10px; margin-top: 10px; padding: 10px 8px 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {g['MUTED']}; }}
QPushButton {{ background: {g['TINT']}; border: 1px solid {g['LINE']}; border-radius: 9px;
  padding: 6px 14px; color: {g['INK']}; }}
QPushButton:hover {{ border-color: {g['BRAND']}; background: {g['HOVER']}; }}
QPushButton:checked, QPushButton#primary {{ background: {g['BRAND']}; border-color: {g['BRAND']}; color: {g['ON_BRAND']}; }}
QPushButton#primary:hover {{ background: {g['BRAND_BRIGHT']}; }}
QLineEdit, QSpinBox, QTimeEdit, QComboBox, QPlainTextEdit {{ background: {g['TINT']};
  border: 1px solid {g['LINE']}; border-radius: 8px; padding: 4px 6px; color: {g['INK']};
  selection-background-color: {g['BRAND']}; selection-color: {g['ON_BRAND']}; }}
QLineEdit:focus, QSpinBox:focus, QTimeEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {g['BRAND_BRIGHT']}; }}
QLineEdit:disabled, QComboBox:disabled {{ color: {g['DIM']}; }}
QComboBox QAbstractItemView {{ background: {g['SURFACE']}; border: 1px solid {g['LINE']}; color: {g['INK']};
  selection-background-color: {g['BRAND']}; selection-color: {g['ON_BRAND']}; }}
QListWidget, QTableWidget {{ background: {g['TINT_LIST']}; border: 1px solid {g['LINE']}; border-radius: 12px;
  outline: none; gridline-color: {g['LINE']}; }}
QListWidget::item {{ padding: 8px 10px; border-radius: 8px; }}
QListWidget::item:selected {{ background: {g['SELECT']}; color: {g['INK']}; }}
QHeaderView::section {{ background: {g['SURFACE']}; color: {g['MUTED']}; border: none; padding: 6px; }}
QTableWidget::item:selected {{ background: {g['SELECT']}; }}
QAbstractSpinBox {{ padding-right: 52px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ subcontrol-origin: border; width: 22px;
  border: none; border-left: 1px solid {g['LINE']}; background: {g['TINT']}; }}
QAbstractSpinBox::up-button {{ subcontrol-position: center right; right: 24px; top: 0; bottom: 0; }}
QAbstractSpinBox::down-button {{ subcontrol-position: center right; right: 1px; top: 0; bottom: 0;
  border-top-right-radius: 7px; border-bottom-right-radius: 7px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {g['HOVER']}; }}
QAbstractSpinBox::up-arrow {{ image: url("{up}"); width: 11px; height: 8px; }}
QAbstractSpinBox::down-arrow {{ image: url("{down}"); width: 11px; height: 8px; }}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::down-arrow:disabled,
QAbstractSpinBox::up-arrow:off, QAbstractSpinBox::down-arrow:off {{ image: none; }}
QCheckBox {{ background: transparent; spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border: 2px solid {g['MUTED']}; border-radius: 5px;
  background: {g['TINT']}; }}
QCheckBox::indicator:hover {{ border-color: {g['BRAND_BRIGHT']}; }}
QCheckBox::indicator:checked {{ background: {g['BRAND']}; border-color: {g['BRAND']}; image: url("{CHECK_SVG}"); }}
QCheckBox::indicator:checked:hover {{ background: {g['BRAND_BRIGHT']}; border-color: {g['BRAND_BRIGHT']}; }}
QCheckBox::indicator:disabled {{ border-color: {g['DIM']}; }}
QProgressBar {{ background: {g['TINT2']}; border: none; border-radius: 4px; max-height: 8px; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {g['BRAND']}, stop:1 {g['BRAND_BRIGHT']});
  border-radius: 4px; }}
QMenu {{ background: {g['SURFACE']}; border: 1px solid {g['LINE']}; color: {g['INK']}; padding: 4px; }}
QMenu::item {{ padding: 6px 30px 6px 12px; border-radius: 4px; }}   /* запас справа: цветные значки (🔓) шире расчётного */
QMenu::item:selected {{ background: {g['BRAND']}; color: {g['ON_BRAND']}; }}
QToolTip {{ background: {g['SURFACE']}; color: {g['INK']}; border: 1px solid {g['LINE']}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {g['LINE']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""


apply("dark")


def tabular_digits(w) -> None:
    """Цифры одинаковой ширины (в Segoe UI «1» уже остальных): тикающее время не меняет ширину надписи."""
    from PySide6.QtGui import QFont
    f = w.font()
    f.setFeature(QFont.Tag("tnum"), 1)
    w.setFont(f)
