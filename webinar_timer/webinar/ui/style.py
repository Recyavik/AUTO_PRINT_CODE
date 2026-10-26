"""Оформление в стиле страницы «Повестка эфира» (1Т): тёмно-фиолетовый фон, яркий фиолетовый акцент."""
from pathlib import Path

# галочка флажка — своя картинка: на тёмной теме у стандартного флажка пропадала рамка
CHECK_SVG = (Path(__file__).resolve().parent / "check.svg").as_posix()
# стрелки счётчиков — тоже свои: иначе поле ввода счётчика перекрывало кнопки ▲▼ и они не нажимались
UP_SVG = (Path(__file__).resolve().parent / "arrow_up.svg").as_posix()
DOWN_SVG = (Path(__file__).resolve().parent / "arrow_down.svg").as_posix()

BG = "#130C1F"
SURFACE = "#221836"
SURFACE2 = "#2A1E44"
LINE = "#3A2B5C"
BRAND = "#8E4DFF"
BRAND_BRIGHT = "#B98CFF"
INK = "#F4EFFC"
MUTED = "#9C8FBC"
DIM = "#6E6191"
ON = "#39C08A"
EYE = "#5FD0A0"
AMBER = "#F2B64B"
RED = "#F2688B"

KIND_COLOR = {"break": AMBER, "eyes": EYE, "": BRAND_BRIGHT}

APP_QSS = f"""
QWidget {{ background: {BG}; color: {INK}; font-family: 'Segoe UI', 'Rubik', sans-serif; font-size: 10.5pt; }}
QDialog, QMainWindow {{ background: {BG}; }}
QFrame#card {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 16px; }}
QLabel {{ background: transparent; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#hint {{ color: {DIM}; font-size: 9pt; }}
QPushButton {{ background: rgba(255,255,255,0.05); border: 1px solid {LINE}; border-radius: 9px;
  padding: 6px 14px; color: {INK}; }}
QPushButton:hover {{ border-color: {BRAND}; background: rgba(142,77,255,0.18); }}
QPushButton:checked, QPushButton#primary {{ background: {BRAND}; border-color: {BRAND}; color: white; }}
QPushButton#primary:hover {{ background: {BRAND_BRIGHT}; }}
QLineEdit, QSpinBox, QTimeEdit, QComboBox, QPlainTextEdit {{ background: rgba(255,255,255,0.05);
  border: 1px solid {LINE}; border-radius: 8px; padding: 4px 6px; color: {INK}; selection-background-color: {BRAND}; }}
QLineEdit:focus, QSpinBox:focus, QTimeEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {BRAND_BRIGHT}; }}
QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid {LINE}; selection-background-color: {BRAND}; }}
QListWidget, QTableWidget {{ background: rgba(255,255,255,0.02); border: 1px solid {LINE}; border-radius: 12px;
  outline: none; gridline-color: {LINE}; }}
QListWidget::item {{ padding: 8px 10px; border-radius: 8px; }}
QListWidget::item:selected {{ background: rgba(142,77,255,0.30); color: white; }}
QHeaderView::section {{ background: {SURFACE}; color: {MUTED}; border: none; padding: 6px; }}
QTableWidget::item:selected {{ background: rgba(142,77,255,0.25); }}
QAbstractSpinBox {{ padding-right: 52px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ subcontrol-origin: border; width: 22px;
  border: none; border-left: 1px solid {LINE}; background: rgba(255,255,255,0.03); }}
QAbstractSpinBox::up-button {{ subcontrol-position: center right; right: 24px; top: 0; bottom: 0; }}
QAbstractSpinBox::down-button {{ subcontrol-position: center right; right: 1px; top: 0; bottom: 0;
  border-top-right-radius: 7px; border-bottom-right-radius: 7px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: rgba(142,77,255,0.35); }}
QAbstractSpinBox::up-arrow {{ image: url("{UP_SVG}"); width: 11px; height: 8px; }}
QAbstractSpinBox::down-arrow {{ image: url("{DOWN_SVG}"); width: 11px; height: 8px; }}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::down-arrow:disabled,
QAbstractSpinBox::up-arrow:off, QAbstractSpinBox::down-arrow:off {{ image: none; }}
QCheckBox {{ background: transparent; spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border: 2px solid {MUTED}; border-radius: 5px;
  background: rgba(255,255,255,0.04); }}
QCheckBox::indicator:hover {{ border-color: {BRAND_BRIGHT}; }}
QCheckBox::indicator:checked {{ background: {BRAND}; border-color: {BRAND}; image: url("{CHECK_SVG}"); }}
QCheckBox::indicator:checked:hover {{ background: {BRAND_BRIGHT}; border-color: {BRAND_BRIGHT}; }}
QCheckBox::indicator:disabled {{ border-color: {DIM}; }}
QProgressBar {{ background: rgba(255,255,255,0.08); border: none; border-radius: 4px; max-height: 8px; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {BRAND}, stop:1 {BRAND_BRIGHT});
  border-radius: 4px; }}
QMenu {{ background: {SURFACE}; border: 1px solid {LINE}; }}
QMenu::item:selected {{ background: {BRAND}; }}
QToolTip {{ background: {SURFACE}; color: {INK}; border: 1px solid {LINE}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""
