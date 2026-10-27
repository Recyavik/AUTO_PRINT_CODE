"""Редактор кода образца: номера строк, подсветка синтаксиса; цвета — по теме окна (apply_theme)."""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QTextCursor, QTextFormat
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

from .. import highlighter as hl
from ..highlighter import CodeHighlighter


def code_font(size: int = 11) -> QFont:
    families = set(QFontDatabase.families())
    for name in ("JetBrains Mono", "Cascadia Code", "Cascadia Mono", "Consolas", "Courier New"):
        if name in families:
            f = QFont(name, size)
            break
    else:
        f = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        f.setPointSize(size)
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f


class _Gutter(QWidget):
    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event) -> None:
        self.editor.paint_gutter(event)


class CodeEditor(QPlainTextEdit):
    height_changed = Signal()
    focused = Signal()

    MIN_LINES = 3
    MAX_LINES = 40

    def __init__(self, text: str = "", lang: str = "python", parent=None) -> None:
        super().__init__(parent)
        self.setFont(code_font())
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabChangesFocus(False)
        self._style()
        self.setPlainText(text)
        self.highlighter = CodeHighlighter(self.document(), lang)
        self._gutter = _Gutter(self)
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._refresh_extra)
        self.blockCountChanged.connect(lambda *_: self.height_changed.emit())
        self._update_gutter_width()
        self._refresh_extra()

    def _style(self) -> None:
        self.setStyleSheet(
            f"QPlainTextEdit {{ background:{hl.EDITOR_BG}; color:{hl.EDITOR_FG}; border:none;"
            # выделенное (то, что напечатается) — инверсией: в любой теме видно сразу, цвета подсветки тоже
            f" selection-background-color:{hl.EDITOR_FG}; selection-color:{hl.EDITOR_BG}; }}")

    def apply_theme(self) -> None:
        """Тему окна сменили: фон, номера строк, текущая строка и подсветка — в новых цветах."""
        self._style()
        self.highlighter.refresh()
        self._refresh_extra()

    # ---- высота по содержимому (блоки идут в общей прокрутке страницы)
    def content_height(self) -> int:
        lines = max(self.MIN_LINES, min(self.MAX_LINES, self.document().blockCount()))
        sb = self.horizontalScrollBar().sizeHint().height()
        return int(lines * self.fontMetrics().lineSpacing() + 2 * self.document().documentMargin() + sb + 6)

    # ---- номера строк
    def gutter_width(self) -> int:
        digits = max(2, len(str(self.blockCount())))
        return 14 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_gutter_width(self, *_):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def update_gutter_width(self) -> None:
        """После смены шрифта (масштаб): ширина колонки номеров строк и её геометрия."""
        self._update_gutter_width()
        cr = self.contentsRect()
        self._gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def _update_gutter(self, rect, dy):
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, event) -> None:
        p = QPainter(self._gutter)
        p.fillRect(event.rect(), QColor(hl.EDITOR_BG))
        block = self.firstVisibleBlock()
        num = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        sel = self._selected_lines()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                in_sel = sel and sel[0] <= num <= sel[1]
                p.setPen(QColor(hl.EDITOR_GUTTER_SEL if in_sel else hl.EDITOR_GUTTER))
                p.drawText(0, top, self._gutter.width() - 6, self.fontMetrics().height(),
                           Qt.AlignmentFlag.AlignRight, str(num + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            num += 1

    def _selected_lines(self) -> tuple[int, int] | None:
        c = self.textCursor()
        if not c.hasSelection():
            return None
        doc = self.document()
        a = doc.findBlock(c.selectionStart()).blockNumber()
        b = doc.findBlock(c.selectionEnd()).blockNumber()
        return a, b

    # ---- подсветка текущей строки
    def _refresh_extra(self) -> None:
        extras = []
        if self.hasFocus() and not self.textCursor().hasSelection():
            s = QTextEdit.ExtraSelection()
            s.format.setBackground(QColor(hl.EDITOR_LINE))
            s.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            s.cursor = self.textCursor()
            s.cursor.clearSelection()
            extras.append(s)
        self.setExtraSelections(extras)
        self._gutter.update()

    def focusInEvent(self, e) -> None:
        super().focusInEvent(e)
        self._refresh_extra()
        self.focused.emit()

    def focusOutEvent(self, e) -> None:
        super().focusOutEvent(e)
        self._refresh_extra()

    # ---- Tab → пробелы, Shift+Tab — снять отступ
    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Tab and not e.modifiers():
            c = self.textCursor()
            if c.hasSelection():
                self._indent_selection(+1)
            else:
                c.insertText("    ")
            return
        if e.key() == Qt.Key.Key_Backtab:
            self._indent_selection(-1)
            return
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not e.modifiers():
            line = self.textCursor().block().text()
            indent = line[:len(line) - len(line.lstrip(" "))]
            if line.rstrip().endswith((":", "{", "[", "(")):
                indent += "    "
            self.textCursor().insertText("\n" + indent)
            return
        super().keyPressEvent(e)

    def _indent_selection(self, direction: int) -> None:
        c = self.textCursor()
        doc = self.document()
        first = doc.findBlock(c.selectionStart())
        end = c.selectionEnd()
        if c.hasSelection() and end > c.selectionStart() and doc.findBlock(end).position() == end:
            end -= 1  # выделение до начала строки не захватывает эту строку
        last = doc.findBlock(end)
        c.beginEditBlock()
        b = first
        while b.isValid():
            bc = QTextCursor(b)
            if direction > 0:
                bc.insertText("    ")
            else:
                n = len(b.text()) - len(b.text().lstrip(" "))
                bc.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, min(4, n))
                bc.removeSelectedText()
            if b == last:
                break
            b = b.next()
        c.endEditBlock()
