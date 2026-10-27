"""Оформление AutoPrintCode в стиле 1Т — как у «Таймера вебинара»: тёмная и мягкая светлая (сиреневая) темы.

apply(тема) задаёт цвета модуля и общую таблицу стилей; окно меняет тему на лету (MainWindow.set_theme).
Редактор кода — по теме: в светлой подложка на тон темнее панели, чтобы код выделялся (highlighter.py).
Палитры совпадают с таймером; у каждого приложения своя копия — они ставятся и обновляются независимо.
"""
from pathlib import Path

_UI = Path(__file__).resolve().parent
CHECK_SVG = (_UI / "check.svg").as_posix()

THEME_NAMES = {"dark": "Тёмная", "light": "Светлая"}

THEMES = {
    "dark": {
        "BG": "#130C1F", "SURFACE": "#221836", "LINE": "#3A2B5C",
        "BRAND": "#8E4DFF", "BRAND_BRIGHT": "#B98CFF", "INK": "#F4EFFC", "MUTED": "#9C8FBC", "DIM": "#6E6191",
        "OK": "#39C08A", "WARN": "#F2B64B", "RED": "#F2688B",
        "TINT": "rgba(255,255,255,0.05)", "TINT2": "rgba(255,255,255,0.08)", "TINT_LIST": "rgba(255,255,255,0.02)",
        "HOVER": "rgba(142,77,255,0.18)", "SELECT": "rgba(142,77,255,0.30)", "ON_BRAND": "white",
        "ARROWS": "",
    },
    "light": {
        "BG": "#D9D1E8", "SURFACE": "#E3DBEF", "LINE": "#B9ABD3",
        "BRAND": "#7A3FE0", "BRAND_BRIGHT": "#6430C4", "INK": "#241A38", "MUTED": "#5E5378", "DIM": "#8C82A6",
        "OK": "#17805A", "WARN": "#9C6410", "RED": "#BE3150",
        "TINT": "rgba(255,255,255,0.30)", "TINT2": "rgba(36,26,56,0.08)", "TINT_LIST": "rgba(255,255,255,0.15)",
        "HOVER": "rgba(122,63,224,0.12)", "SELECT": "rgba(122,63,224,0.18)", "ON_BRAND": "white",
        "ARROWS": "_light",
    },
}

current = ""
APP_QSS = ""


def apply(name: str) -> str:
    """Включить тему: цвета модуля и общая таблица стилей. Неизвестная — тёмная. Возвращает имя темы."""
    global current, APP_QSS
    name = name if name in THEMES else "dark"
    globals().update(THEMES[name])
    current = name
    APP_QSS = _qss(THEMES[name])
    from .. import highlighter
    highlighter.set_editor_theme(name)
    return name


def _qss(g: dict) -> str:
    up = (_UI / f"arrow_up{g['ARROWS']}.svg").as_posix()
    down = (_UI / f"arrow_down{g['ARROWS']}.svg").as_posix()
    close = (_UI / f"close{g['ARROWS']}.svg").as_posix()
    return f"""
QWidget {{ background: {g['BG']}; color: {g['INK']}; font-family: 'Segoe UI', sans-serif; font-size: 10pt; }}
QMainWindow, QDialog {{ background: {g['BG']}; }}
QLabel {{ background: transparent; }}
QMenuBar {{ background: {g['BG']}; color: {g['INK']}; }}
QMenuBar::item {{ padding: 4px 10px; background: transparent; border-radius: 6px; }}
QMenuBar::item:selected {{ background: {g['HOVER']}; }}
QMenu {{ background: {g['SURFACE']}; border: 1px solid {g['LINE']}; color: {g['INK']}; padding: 4px; }}
QMenu::item {{ padding: 5px 22px 5px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {g['BRAND']}; color: {g['ON_BRAND']}; }}
QMenu::item:disabled {{ color: {g['DIM']}; }}
QMenu::separator {{ height: 1px; background: {g['LINE']}; margin: 4px 8px; }}
QToolTip {{ background: {g['SURFACE']}; color: {g['INK']}; border: 1px solid {g['LINE']}; }}
QStatusBar {{ background: {g['BG']}; color: {g['MUTED']}; }}
QGroupBox {{ border: 1px solid {g['LINE']}; border-radius: 10px; margin-top: 10px; padding: 10px 8px 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {g['MUTED']}; }}
QPushButton {{ background: {g['TINT']}; border: 1px solid {g['LINE']}; border-radius: 8px;
  padding: 5px 12px; color: {g['INK']}; }}
QPushButton:hover {{ border-color: {g['BRAND']}; background: {g['HOVER']}; }}
QPushButton:checked, QPushButton:default, QPushButton#primary {{ background: {g['BRAND']}; border-color: {g['BRAND']};
  color: {g['ON_BRAND']}; }}
QPushButton:disabled {{ color: {g['DIM']}; }}
QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 7px; padding: 3px 6px;
  color: {g['INK']}; }}
QToolButton:hover {{ border-color: {g['LINE']}; background: {g['HOVER']}; }}
QToolButton:checked {{ background: {g['SELECT']}; border-color: {g['BRAND']}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QTextBrowser {{ background: {g['TINT']};
  border: 1px solid {g['LINE']}; border-radius: 7px; padding: 3px 6px; color: {g['INK']};
  selection-background-color: {g['INK']}; selection-color: {g['TINT']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus {{
  border-color: {g['BRAND_BRIGHT']}; }}
QComboBox QAbstractItemView {{ background: {g['SURFACE']}; border: 1px solid {g['LINE']}; color: {g['INK']};
  selection-background-color: {g['BRAND']}; selection-color: {g['ON_BRAND']}; }}
QAbstractSpinBox {{ padding-right: 46px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ subcontrol-origin: border; width: 20px;
  border: none; border-left: 1px solid {g['LINE']}; background: {g['TINT']}; }}
QAbstractSpinBox::up-button {{ subcontrol-position: center right; right: 21px; top: 0; bottom: 0; }}
QAbstractSpinBox::down-button {{ subcontrol-position: center right; right: 1px; top: 0; bottom: 0;
  border-top-right-radius: 6px; border-bottom-right-radius: 6px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {g['HOVER']}; }}
QAbstractSpinBox::up-arrow {{ image: url("{up}"); width: 11px; height: 8px; }}
QAbstractSpinBox::down-arrow {{ image: url("{down}"); width: 11px; height: 8px; }}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::down-arrow:disabled,
QAbstractSpinBox::up-arrow:off, QAbstractSpinBox::down-arrow:off {{ image: none; }}
QCheckBox, QRadioButton {{ background: transparent; spacing: 7px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 2px solid {g['MUTED']}; border-radius: 4px;
  background: {g['TINT']}; }}
QCheckBox::indicator:hover {{ border-color: {g['BRAND_BRIGHT']}; }}
QCheckBox::indicator:checked {{ background: {g['BRAND']}; border-color: {g['BRAND']}; image: url("{CHECK_SVG}"); }}
QCheckBox::indicator:disabled {{ border-color: {g['DIM']}; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border: 2px solid {g['MUTED']}; border-radius: 9px;
  background: {g['TINT']}; }}
QRadioButton::indicator:checked {{ background: {g['BRAND']}; border-color: {g['BRAND']}; }}
QListWidget {{ background: {g['TINT_LIST']}; border: 1px solid {g['LINE']}; border-radius: 10px; outline: none; }}
QListWidget::item {{ padding: 6px 8px; border-radius: 7px; }}
QListWidget::item:selected {{ background: {g['SELECT']}; color: {g['INK']}; }}
QListWidget::item:hover {{ background: {g['HOVER']}; }}
QTabWidget::pane {{ border: 1px solid {g['LINE']}; border-radius: 8px; top: -1px; }}
QTabBar::tab {{ background: {g['TINT']}; color: {g['MUTED']}; padding: 6px 12px; border: 1px solid {g['LINE']};
  border-bottom: none; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {g['SURFACE']}; color: {g['INK']}; border-color: {g['BRAND']}; }}
QTabBar::tab:hover:!selected {{ background: {g['HOVER']}; }}
QTabBar::close-button {{ image: url("{close}"); subcontrol-position: right; border-radius: 4px; }}
QTabBar::close-button:hover {{ background: {g['HOVER']}; }}
QSlider::groove:horizontal {{ height: 6px; background: {g['TINT2']}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {g['BRAND']}; border-radius: 3px; }}
QSlider::handle:horizontal {{ width: 14px; margin: -5px 0; border-radius: 7px; background: {g['INK']}; }}
QProgressBar {{ background: {g['TINT2']}; border: none; border-radius: 6px; color: {g['INK']}; text-align: center;
  min-height: 16px; }}
QProgressBar::chunk {{ background: {g['BRAND']}; border-radius: 6px; }}
QSplitter::handle {{ background: transparent; }}
QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {g['LINE']}; border-radius: 5px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {g['LINE']}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
"""


apply("dark")
