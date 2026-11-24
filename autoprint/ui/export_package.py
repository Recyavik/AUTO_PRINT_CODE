"""Окно «Урок одним файлом»: что положить в файл .autoprint — план урока, оформление экрана учеников с видео
зарядок (с размером). Картинки урока внутри всегда."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QVBoxLayout

from ..storage import KIND_PLAN
from .widgets import accent_button, button, label, page_header


def _mb(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} МБ" if n >= 1024 * 1024 else f"{max(1, round(n / 1024))} КБ"


class ExportPackageDialog(QDialog):
    def __init__(self, parent, templates, main) -> None:
        super().__init__(parent)
        self.setWindowTitle("Урок одним файлом")
        self.setModal(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        one = len(templates) == 1
        lay.addWidget(page_header("Урок одним файлом" if one else f"Уроки одним файлом ({len(templates)})",
                                  "Один файл .autoprint — со всеми картинками. Отдайте его коллеге: он откроет его в "
                                  "«Импорт…», и у него всё будет как у вас."))
        base = main.package_media_size(templates, include_looks=False)
        full = main.package_media_size(templates, include_looks=True)
        pics = QCheckBox(f"Картинки и слайды урока — {_mb(base)}")
        pics.setChecked(True)
        pics.setEnabled(False)
        lay.addWidget(pics)
        linked = any(t.plan_id or t.kind == KIND_PLAN for t in templates)
        self.cb_plan = QCheckBox("План урока — этапы и минуты, по которым идёт урок")
        self.cb_plan.setChecked(linked)
        self.cb_plan.setEnabled(linked)
        lay.addWidget(self.cb_plan)
        self.cb_look = QCheckBox(f"Оформление экрана учеников: фон, заставка перерыва, видео зарядок — "
                                 f"{_mb(max(0, full - base))}")
        self.cb_look.setChecked(True)
        lay.addWidget(self.cb_look)
        lay.addWidget(label("Внутри — обычный архив: в нём и понятная копия урока (.md с картинками), её можно открыть "
                            "без AutoPrint.", "rowSub", wrap=True))
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button("Отмена", quiet=True)
        cancel.clicked.connect(self.reject)
        ok = accent_button("Сохранить…", "export")
        ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
        self.resize(560, self.sizeHint().height())

    def include_plans(self) -> bool:
        return self.cb_plan.isChecked()

    def include_looks(self) -> bool:
        return self.cb_look.isChecked()
