"""Редактор шаблона вебинара: название, время старта, активности (как в «Настройках повестки»)."""
from __future__ import annotations

import copy
import json

from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, QRect, Qt, QTime, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget,
                               QTimeEdit, QToolButton, QVBoxLayout, QWidget)

from ..model import DEMO_NONE, DEMO_OFF, DEMO_ON, Activity, Plan, parse_time, plan_from, plan_to
from ..store import MEDIA_DIR, portable, resolve

DEMO_ITEMS = [("ВКЛ", DEMO_ON), ("ВЫКЛ", DEMO_OFF), ("нет", DEMO_NONE)]
COLS = ["", "Активность", "Демонстрация", "Минуты", "Напомнить", "Перерыв", "На экран", ""]
C_HANDLE, C_NAME, C_DEMO, C_MIN, C_REMIND, C_BREAK, C_MEDIA, C_DEL = range(len(COLS))
ROW_MIME = "application/x-webinar-row"
MEDIA_FILTER = "Видео и картинки (*.mp4 *.mov *.avi *.mkv *.webm *.wmv *.m4v *.png *.jpg *.jpeg *.bmp *.webp)"


def _center(w: QWidget) -> QWidget:
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addStretch(1)
    lay.addWidget(w)
    lay.addStretch(1)
    return box


def finish_on_enter(dialog: QDialog, e) -> bool:
    """Enter в поле ввода — закончить ввод: выйти из поля (значение уже записано). True — обработано."""
    if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
        w = dialog.focusWidget()
        if w is not None:
            w.clearFocus()
        e.accept()
        return True
    return False


def _no_enter_buttons(dialog: QDialog) -> None:
    """Enter в поле ввода не нажимает кнопки окна. По умолчанию в диалоге Qt Enter жмёт «кнопку
    по умолчанию» — так Enter в названии активности добавлял новый блок."""
    for b in dialog.findChildren(QPushButton):
        b.setAutoDefault(False)
        b.setDefault(False)


class _Handle(QLabel):
    """Ручка «⠿» слева от блока: потянуть мышью — перенести блок на другое место."""

    def __init__(self, row: int) -> None:
        super().__init__("⠿")
        self.row = row
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Потяните, чтобы перенести блок")
        self.setStyleSheet("font-size: 15pt; color: #9C8FBC; padding: 0 6px;")
        self._press: QPoint | None = None

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()

    def mouseMoveEvent(self, e) -> None:
        if self._press is None or (e.position().toPoint() - self._press).manhattanLength() \
                < QApplication.startDragDistance():
            return
        self._press = None
        mime = QMimeData()
        mime.setData(ROW_MIME, str(self.row).encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        view = self.parentWidget()      # область таблицы: под курсором — вся строка блока
        drag.setPixmap(view.grab(QRect(0, self.y(), view.width(), self.height())) if view else self.grab())
        drag.setHotSpot(QPoint(self.x() + self.width() // 2, self.height() // 2))
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, _e) -> None:
        self._press = None


class _RowTable(QTableWidget):
    """Таблица блоков, принимающая перенос строки за ручку. Линия показывает, куда встанет блок."""
    row_moved = Signal(int, int)        # (откуда, куда — индекс вставки до переноса)

    def __init__(self, rows: int, cols: int) -> None:
        super().__init__(rows, cols)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QTableWidget.DragDropMode.DropOnly)
        self._line = QFrame(self.viewport())
        self._line.setStyleSheet("background: #B98CFF; border-radius: 1px;")
        self._line.hide()

    def _target(self, y: int) -> int:
        row = self.rowAt(y)
        if row < 0:
            return self.rowCount() if y > 0 else 0
        rect = self.visualRect(self.model().index(row, 0))
        return row + 1 if y > rect.center().y() else row

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasFormat(ROW_MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e) -> None:
        if not e.mimeData().hasFormat(ROW_MIME):
            return
        e.acceptProposedAction()
        t = self._target(e.position().toPoint().y())
        if t < self.rowCount():
            y = self.visualRect(self.model().index(t, 0)).top()
        else:
            y = self.visualRect(self.model().index(self.rowCount() - 1, 0)).bottom()
        self._line.setGeometry(0, max(0, y - 1), self.viewport().width(), 3)
        self._line.show()
        self._line.raise_()

    def dragLeaveEvent(self, _e) -> None:
        self._line.hide()

    def dropEvent(self, e) -> None:
        self._line.hide()
        if not e.mimeData().hasFormat(ROW_MIME):
            return
        e.acceptProposedAction()
        src = int(bytes(e.mimeData().data(ROW_MIME)).decode())
        self.row_moved.emit(src, self._target(e.position().toPoint().y()))


class PlanEditor(QDialog):
    def __init__(self, plan: Plan, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Шаблон вебинара")
        # модально только для главного окна: напоминание, пришедшее во время правки, остаётся нажимаемым
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(820, 640)
        self.plan = copy.deepcopy(plan)
        self.result_plan: Plan | None = None

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Название:"))
        self.title = QLineEdit(self.plan.title)
        top.addWidget(self.title, 1)
        top.addWidget(QLabel("Старт:"))
        self.start = QTimeEdit()
        self.start.setDisplayFormat("HH:mm")
        h, m = parse_time(self.plan.start)
        self.start.setTime(QTime(h, m))
        self.start.timeChanged.connect(self._sync_total)
        top.addWidget(self.start)
        top.addWidget(QLabel("Часть занятия:"))
        self.part = QSpinBox()
        self.part.setRange(0, 240)
        self.part.setSuffix(" мин")
        self.part.setSpecialValueText("без предела")
        self.part.setValue(self.plan.part_min)
        self.part.setToolTip("Предел каждой части занятия: до перерыва и после него (академический час — 45 мин).\n"
                             "Минуты блока нельзя увеличить, если его часть уже достигла предела.")
        self.part.valueChanged.connect(self._on_part)
        top.addWidget(self.part)
        lay.addLayout(top)

        self.table = _RowTable(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.row_moved.connect(self.move_row)
        hh = self.table.horizontalHeader()
        for c in range(len(COLS)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch if c == C_NAME
                                    else QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        add = QPushButton("+ Добавить блок")
        add.clicked.connect(self._add)
        row.addWidget(add)
        row.addStretch(1)
        self.parts_lbl = QLabel()
        row.addWidget(self.parts_lbl)
        row.addSpacing(16)
        self.total = QLabel(objectName="muted")
        row.addWidget(self.total)
        lay.addLayout(row)
        note = QLabel("Блоки переставляются мышью за «⠿». «Напомнить» — в начале блока на мониторе управления появится напоминание, оно висит, пока "
                      "его не отметите. «Перерыв» — на экран демонстрации выводится заставка с отсчётом.",
                      objectName="hint")
        note.setWordWrap(True)
        lay.addWidget(note)

        # обмен JSON — тот же формат, что у страницы «Повестка эфира» и её config.json
        self.json_toggle = QPushButton("JSON: обмен с «Повесткой эфира» ▾")
        self.json_toggle.setCheckable(True)
        lay.addWidget(self.json_toggle)
        self.json_box = QWidget()
        jl = QVBoxLayout(self.json_box)
        jl.setContentsMargins(0, 0, 0, 0)
        self.json = QPlainTextEdit()
        self.json.setMinimumHeight(140)
        jl.addWidget(self.json)
        jr = QHBoxLayout()
        copy_btn = QPushButton("Скопировать")
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(self.json.toPlainText()))
        apply_btn = QPushButton("Применить JSON")
        apply_btn.clicked.connect(self._apply_json)
        jr.addWidget(copy_btn)
        jr.addWidget(apply_btn)
        jr.addStretch(1)
        jl.addLayout(jr)
        self.error = QLabel(objectName="hint")
        self.error.setStyleSheet("color: #F2688B;")
        jl.addWidget(self.error)
        self.json_box.setVisible(False)
        self.json_toggle.toggled.connect(self.json_box.setVisible)
        lay.addWidget(self.json_box)

        foot = QHBoxLayout()
        foot.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Сохранить", objectName="primary")
        save.clicked.connect(self._save)
        foot.addWidget(cancel)
        foot.addWidget(save)
        lay.addLayout(foot)
        self._fill()

    def keyPressEvent(self, e) -> None:
        if not finish_on_enter(self, e):
            super().keyPressEvent(e)

    # ---------------------------------------------------------------- таблица
    def _fill(self) -> None:
        self.table.setRowCount(0)
        for i, a in enumerate(self.plan.schedule):
            self.table.insertRow(i)
            self.table.setCellWidget(i, C_HANDLE, _Handle(i))
            name = QLineEdit(a.name)
            # от названия зависят галочки по умолчанию («перерыв» в названии — перерыв)
            name.textChanged.connect(lambda t, a=a: (setattr(a, "name", t), self._refresh_flags()))
            self.table.setCellWidget(i, C_NAME, name)

            demo = QComboBox()
            for label, key in DEMO_ITEMS:
                demo.addItem(label, key)
            demo.setCurrentIndex(max(0, demo.findData(a.demo)))
            demo.currentIndexChanged.connect(lambda _i, a=a, d=demo: (setattr(a, "demo", d.currentData()),
                                                                      self._refresh_flags()))
            self.table.setCellWidget(i, C_DEMO, demo)

            mins = QSpinBox()
            mins.setRange(1, 600)
            mins.setValue(a.min)
            mins.valueChanged.connect(lambda v, a=a: (setattr(a, "min", v), self._sync_total()))
            self.table.setCellWidget(i, C_MIN, mins)

            remind = QCheckBox()
            remind.setToolTip("Напоминать о начале этого блока")
            remind.toggled.connect(lambda on, a=a: (setattr(a, "remind", on), self._sync_total()))
            self.table.setCellWidget(i, C_REMIND, _center(remind))

            brk = QCheckBox()
            brk.setToolTip("Перерыв: заставка с отсчётом на экран демонстрации")
            brk.toggled.connect(lambda on, a=a: (setattr(a, "is_break", on), self._refresh_flags()))
            self.table.setCellWidget(i, C_BREAK, _center(brk))
            self.table.setCellWidget(i, C_MEDIA, self._media_cell(a))

            delete = QToolButton()
            delete.setText("✕")
            delete.setToolTip("Удалить блок")
            delete.clicked.connect(lambda _c=False, i=i: self._remove(i))
            self.table.setCellWidget(i, C_DEL, _center(delete))
        _no_enter_buttons(self)
        self._refresh_flags()

    def _media_cell(self, a: Activity) -> QWidget:
        """Файл блока на экран демонстрации (видео гимнастики, фон перерыва). Пусто — из настроек."""
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        pick = QPushButton(Path(a.media).name[:18] if a.media else "из настроек")
        pick.setToolTip(a.media or "Свой файл не выбран: у «Зарядки для глаз» — видео из настроек, "
                                   "у перерыва — фон из настроек")

        def choose() -> None:
            start = str(Path(resolve(a.media)).parent) if a.media else str(MEDIA_DIR)
            path, _ = QFileDialog.getOpenFileName(self, f"Файл для «{a.name}»", start, MEDIA_FILTER)
            if path:
                a.media = portable(path)
                self._fill()

        def clear() -> None:
            a.media = ""
            self._fill()

        pick.clicked.connect(choose)
        lay.addWidget(pick)
        if a.media:
            x = QToolButton()
            x.setText("✕")
            x.setToolTip("Убрать свой файл")
            x.clicked.connect(clear)
            lay.addWidget(x)
        return box

    def _refresh_flags(self) -> None:
        """Галочки показывают действующее значение (в том числе выведенное из названия и демонстрации)."""
        for i, a in enumerate(self.plan.schedule):
            for col, value in ((C_REMIND, a.reminds), (C_BREAK, a.breaks)):
                cb = self.table.cellWidget(i, col).findChild(QCheckBox)
                cb.blockSignals(True)
                cb.setChecked(value)
                cb.blockSignals(False)
        self._sync_total()

    def _on_part(self, v: int) -> None:
        self.plan.part_min = v
        self._sync_total()

    def _apply_limits(self) -> None:
        """Счётчик минут блока не даёт выйти за предел его части (до перерыва / после)."""
        for i, a in enumerate(self.plan.schedule):
            spin = self.table.cellWidget(i, C_MIN)
            if spin is None:
                continue
            room = self.plan.room(i)
            top = 600 if room is None else max(a.min, a.min + room)
            if spin.maximum() != top:
                spin.blockSignals(True)
                spin.setMaximum(top)
                spin.blockSignals(False)
            spin.setToolTip("" if room is None else
                            ("Часть занятия уже заполнена — сначала уменьшите другой блок" if room <= 0
                             else f"Можно добавить ещё {room} мин"))
        parts = self.plan.parts()
        if not self.plan.part_min or not parts:
            self.parts_lbl.setText("")
            return
        bits = []
        for n, part in enumerate(parts, 1):
            t = self.plan.part_total(part)
            color = "#F2688B" if t > self.plan.part_min else ("#39C08A" if t == self.plan.part_min else "#9C8FBC")
            bits.append(f"<span style='color:{color}'>{n}-я часть: <b>{t}</b>/{self.plan.part_min}</span>")
        self.parts_lbl.setText(" · ".join(bits))

    def _sync_total(self) -> None:
        self._apply_limits()
        total = self.plan.total_min
        t0 = self.start.time()
        t1 = t0.addSecs(total * 60)
        self.total.setText(f"Итого {total} мин · {t0.toString('HH:mm')} – {t1.toString('HH:mm')}")
        if not self.json.hasFocus():
            self.json.setPlainText(json.dumps(self._collect_dict(), ensure_ascii=False, indent=2))

    def _add(self) -> None:
        self.plan.schedule.append(Activity("Новый блок", DEMO_OFF, 5))
        room = self.plan.room(len(self.plan.schedule) - 1)
        if room is not None and room < 0:          # в последней части места мало — сколько осталось, но не меньше 1
            self.plan.schedule[-1].min = max(1, 5 + room)
        self._fill()
        self.table.scrollToBottom()
        self.table.cellWidget(self.table.rowCount() - 1, C_NAME).setFocus()

    def move_row(self, src: int, dst: int) -> None:
        """Перенос блока мышью: src — откуда, dst — место вставки (индекс до переноса, 0…len)."""
        s = self.plan.schedule
        if not 0 <= src < len(s):
            return
        dst = max(0, min(len(s), dst))
        if dst in (src, src + 1):
            return              # на своё же место
        block = s.pop(src)
        s.insert(dst - 1 if dst > src else dst, block)
        self._fill()

    def _remove(self, i: int) -> None:
        if len(self.plan.schedule) > 1:
            del self.plan.schedule[i]
            self._fill()

    # ---------------------------------------------------------------- JSON и сохранение
    def _collect_dict(self) -> dict:
        d = plan_to(self.plan)
        d["title"] = self.title.text().strip() or "Вебинар"
        d["start"] = self.start.time().toString("HH:mm")
        d["part_min"] = self.part.value()
        return d

    def _apply_json(self) -> None:
        try:
            p = plan_from(json.loads(self.json.toPlainText()), self.title.text())
        except (ValueError, json.JSONDecodeError) as e:
            self.error.setText(f"Не получилось: {e}")
            return
        self.error.setText("")
        p.id = self.plan.id
        self.plan = p
        self.title.setText(p.title)
        h, m = parse_time(p.start)
        self.start.setTime(QTime(h, m))
        self.part.setValue(p.part_min)
        self._fill()

    def _save(self) -> None:
        over = self.plan.over_limit()
        if over:
            self.json_toggle.setChecked(True)
            self.error.setText("Не сохранено: " + "; ".join(
                f"{n}-я часть — {t} мин из {self.plan.part_min}" for n, t in over) +
                ". Уменьшите блоки или перенесите их через перерыв.")
            return
        try:
            p = plan_from(self._collect_dict())
        except ValueError as e:
            self.json_toggle.setChecked(True)
            self.error.setText(f"Не получилось сохранить: {e}")
            return
        p.id = self.plan.id
        self.result_plan = p
        self.accept()
