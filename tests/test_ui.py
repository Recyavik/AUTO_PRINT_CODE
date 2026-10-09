"""Тесты интерфейса без окна (Qt offscreen): активный блок и выделение в текстовых блоках.

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("AUTOPRINT_DATA", tempfile.mkdtemp(prefix="autoprint-ui-"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtGui import QFocusEvent, QTextCursor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autoprint.storage import BLOCK_CODE, BLOCK_MARKDOWN, Block, Template  # noqa: E402
from autoprint.ui.blocks import MarkdownBlockWidget  # noqa: E402
from autoprint.ui.template_view import TemplateView  # noqa: E402

app = QApplication.instance() or QApplication([])

MD = "## Заголовок\n\nстрока один\nстрока два\nстрока три"


def select_in_view(w: MarkdownBlockWidget, fragment: str) -> None:
    doc = w.view.toPlainText()
    i = doc.index(fragment)
    c = w.view.textCursor()
    c.setPosition(i)
    c.setPosition(i + len(fragment), QTextCursor.MoveMode.KeepAnchor)
    w.view.setTextCursor(c)


class MarkdownSelectionTest(unittest.TestCase):
    def setUp(self):
        self.t = Template("t", [Block(BLOCK_MARKDOWN, MD), Block(BLOCK_CODE, "print(1)")])
        self.view = TemplateView(self.t)
        self.md: MarkdownBlockWidget = self.view.widgets[0]
        self.block = self.t.blocks[0]

    def selected(self) -> str:
        a, b = self.block.sel
        return self.block.text[a:b]

    def test_first_code_block_armed_on_open(self):
        self.assertEqual(self.t.active_block, self.t.blocks[1].id)

    def test_view_selection_maps_to_source_lines(self):
        select_in_view(self.md, "строка два")
        self.assertEqual(self.selected(), "строка два")
        self.assertTrue(self.md.info.isVisibleTo(self.md))

    def test_zoom_keeps_selection(self):
        select_in_view(self.md, "строка два")
        self.md.apply_zoom(130)
        self.assertEqual(self.selected(), "строка два")

    def test_edit_mode_shows_selection_and_edits_drop_stale_offsets(self):
        select_in_view(self.md, "строка два")
        self.md.set_editing(True, focus=False)
        self.assertEqual(self.md.edit.textCursor().selectedText(), "строка два")
        c = QTextCursor(self.md.edit.document())   # правка выше выделения — оно сдвигается вместе с текстом
        c.insertText("Новая строка\n")
        self.assertEqual(self.selected(), "строка два")
        c = self.md.edit.textCursor()              # набор поверх выделения — выделения больше нет
        c.insertText("X")
        self.md.edit.setTextCursor(c)
        self.assertEqual(self.block.sel, [])
        self.assertFalse(self.md.info.isVisibleTo(self.md))

    def test_focus_in_editor_arms_block(self):
        self.md.set_editing(True, focus=False)
        QApplication.sendEvent(self.md.edit, QFocusEvent(QEvent.Type.FocusIn))
        self.assertEqual(self.t.active_block, self.block.id)

    def test_role_change_keeps_selection_and_active(self):
        self.view.arm(self.block.id)
        select_in_view(self.md, "строка два")
        self.view._change_type(self.md, "hint")
        self.assertEqual((self.block.role, self.selected(), self.t.active_block), ("hint", "строка два", self.block.id))

    def test_arming_other_block_clears_selection(self):
        self.view.arm(self.block.id)
        select_in_view(self.md, "строка два")
        self.view.arm(self.t.blocks[1].id)
        self.assertEqual(self.block.sel, [])


if __name__ == "__main__":
    unittest.main()
