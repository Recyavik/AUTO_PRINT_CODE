"""Доработка 0.9: колёсико, тема без зависаний, трей и окно суфлёра, начало эфира при запуске, редактор
«Эфира», таймер, суфлёр как PDF, картинки в редакторе, пример урока, урок в Markdown, картинка в Jupyter.
Всё без окон на экране.

    python tests/test_v09.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import quiet  # noqa: E402,F401  — до PySide6: offscreen, своя папка данных

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import (QApplication, QComboBox, QLineEdit, QPlainTextEdit, QScrollArea,  # noqa: E402
                               QSpinBox, QVBoxLayout, QWidget)

app = QApplication.instance() or QApplication([])
quiet.patch()
from autoprint.ui.theme import theme  # noqa: E402
theme.setup(app, "dark")

TMP = Path(tempfile.mkdtemp(prefix="v09-test-"))
PORT = 18950


def pump(ms: int = 50) -> None:
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def wheel(w: QWidget, dy: int = -120) -> None:
    pos = QPointF(w.width() / 2, w.height() / 2)
    ev = QWheelEvent(pos, QPointF(w.mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, dy),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(w, ev)


# ================================================================ Task 1: колёсико

class WheelTest(unittest.TestCase):
    """Колёсико над счётчиком или списком без фокуса крутит страницу, а не значение."""

    @classmethod
    def setUpClass(cls):
        from autoprint.ui.widgets import install_wheel_guard
        install_wheel_guard(app)

    def page(self, child: QWidget) -> tuple[QScrollArea, QWidget]:
        area = QScrollArea()
        area.setWidgetResizable(True)
        host = QWidget()
        lay = QVBoxLayout(host)
        sink = QLineEdit()                          # фокус — где-то ещё на странице, как в жизни
        lay.addWidget(sink)
        lay.addWidget(child)
        lay.addSpacing(3000)                        # страница выше окна — есть что прокручивать
        area.setWidget(host)
        area.resize(400, 300)
        area.show()
        pump(30)
        sink.setFocus()
        pump(10)
        return area, host

    def test_unfocused_spin_scrolls_page(self):
        sp = QSpinBox()
        sp.setRange(0, 100)
        sp.setValue(50)
        area, _ = self.page(sp)
        wheel(sp)
        pump(30)
        self.assertEqual(sp.value(), 50)
        self.assertGreater(area.verticalScrollBar().value(), 0)
        area.close()

    def test_focused_spin_changes(self):
        sp = QSpinBox()
        sp.setRange(0, 100)
        sp.setValue(50)
        area, _ = self.page(sp)
        area.activateWindow()
        sp.setFocus()
        pump(30)
        if not sp.hasFocus():
            self.skipTest("offscreen: фокус не встал")
        wheel(sp)
        pump(30)
        self.assertNotEqual(sp.value(), 50)
        area.close()

    def test_unfocused_combo_unchanged(self):
        cb = QComboBox()
        cb.addItems(["Обычный", "Перерыв", "Зарядка"])
        area, _ = self.page(cb)
        wheel(cb)
        wheel(cb)
        pump(30)
        self.assertEqual(cb.currentIndex(), 0)
        area.close()

    def test_text_editor_wheel_not_blocked(self):
        ed = QPlainTextEdit("\n".join(f"строка {i}" for i in range(300)))
        ed.setFixedHeight(120)
        area, _ = self.page(ed)
        wheel(ed.viewport())
        pump(30)
        self.assertGreater(ed.verticalScrollBar().value(), 0)
        area.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
