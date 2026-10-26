"""Редактор шаблона вебинара: название, время старта, активности (как в «Настройках повестки»)."""
from __future__ import annotations

import copy
import json

from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, QRect, Qt, QTime, QTimer, Signal
from PySide6.QtGui import QColor, QDrag, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPlainTextEdit, QPushButton, QSpinBox, QTableWidget, QTimeEdit, QToolButton,
                               QVBoxLayout, QWidget)

from ..model import (DEMO_NONE, DEMO_OFF, DEMO_ON, Activity, Plan, parse_time, plan_from, plan_to, reorder_lessons,
                     split_lessons)
from ..store import MEDIA_DIR, portable, resolve
from . import style
from .lessons import LessonLengthEdit

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
            table = self.parentWidget().parentWidget() if self.parentWidget() else None
            if isinstance(table, _RowTable):
                table.select(self.row)

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


LINE_COLOR = QColor(242, 182, 75, 128)        # границы уроков — золотые, прозрачность 50 %
SELECT_COLOR = QColor(110, 175, 255, 150)     # рамка выбранного блока


class _LessonLines(QWidget):
    """Поверх таблицы (щелчки проходят насквозь): линии границ уроков и рамка выбранного блока."""

    def __init__(self, table: "_RowTable") -> None:
        super().__init__(table.viewport())
        self.table = table
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        sel = self.table.selected
        if sel is not None and 0 <= sel < self.table.rowCount():
            p.setPen(QPen(SELECT_COLOR, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            y = self.table.rowViewportPosition(sel)
            p.drawRoundedRect(1, y + 1, self.width() - 3, self.table.rowHeight(sel) - 3, 6, 6)
        p.setPen(QPen(LINE_COLOR, 2))
        for row in self.table.marks:
            if row < self.table.rowCount():
                y = self.table.rowViewportPosition(row)
            else:
                y = self.table.rowViewportPosition(row - 1) + self.table.rowHeight(row - 1) - 2
            p.drawLine(0, max(1, y), self.width(), max(1, y))


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
        self.marks: list[int] = []      # строки, над которыми проходит граница урока (вокруг перерывов)
        self.selected: int | None = None    # выбранный блок: «+ Добавить блок» вставит новый после него
        self._lessons = _LessonLines(self)
        self.verticalScrollBar().valueChanged.connect(lambda _v: self._lessons.update())

    def set_marks(self, rows: list[int]) -> None:
        self.marks = rows
        self._lessons.setGeometry(self.viewport().rect())
        self._lessons.raise_()
        self._lessons.update()

    def select(self, row: int | None) -> None:
        if row != self.selected:
            self.selected = row
            self._lessons.update()

    def row_of(self, w: QWidget | None) -> int | None:
        """Строка, в которой стоит поле w (или None — поле не в таблице)."""
        while w is not None and w.parentWidget() is not self.viewport():
            w = w.parentWidget()
        if w is None:
            return None
        for r in range(self.rowCount()):
            if any(self.cellWidget(r, c) is w for c in range(self.columnCount())):
                return r
        return None

    def mousePressEvent(self, e) -> None:
        if self.rowAt(e.position().toPoint().y()) < 0:
            self.select(None)           # щелчок мимо блоков — ничего не выбрано: новый блок — в конец
        super().mousePressEvent(e)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._lessons.setGeometry(self.viewport().rect())

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


class _LessonStrip(QListWidget):
    """Плитки уроков в ряд: перетащить плитку — переставить урок целиком (все его блоки);
    двойной щелчок — название урока."""
    reordered = Signal(list)            # новый порядок: исходные номера уроков (с 0)
    rename = Signal(int)                # номер урока (с 0)

    def __init__(self) -> None:
        super().__init__()
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(False)
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(46)
        self.setSpacing(3)
        self.setToolTip("Двойной щелчок — название урока. Перетащите урок, чтобы поменять уроки местами: "
                        "блоки урока переезжают вместе, перерывы остаются на своих местах")
        self.itemDoubleClicked.connect(lambda it: self.rename.emit(it.data(Qt.ItemDataRole.UserRole)))
        self.setStyleSheet(f"""
            QListWidget {{ background: transparent; border: none; }}
            QListWidget::item {{ background: rgba(110,175,255,0.10); border: 1px solid rgba(110,175,255,0.35);
              border-radius: 8px; padding: 4px 10px; color: {style.INK}; }}
            QListWidget::item:selected {{ background: rgba(110,175,255,0.25); }}
        """)

    def set_lessons(self, labels: list[str]) -> None:
        if [self.item(i).text() for i in range(self.count())] == labels:
            return
        self.clear()
        for i, text in enumerate(labels):
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, i)
            self.addItem(it)

    def dropEvent(self, e) -> None:
        super().dropEvent(e)
        order = [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]
        if order != sorted(order):
            QTimer.singleShot(0, lambda: self.reordered.emit(order))   # после того, как список закончит перенос


class PlanEditor(QDialog):
    def __init__(self, plan: Plan, parent=None, lesson_min: int | None = None, break_min: int = 10) -> None:
        """lesson_min — продолжительность урока из общих настроек (у шаблона может быть своя);
        break_min — перерыв перед уроком, который добавляет «+ Добавить урок»."""
        super().__init__(parent)
        self.setWindowTitle("Шаблон вебинара")
        # модально только для главного окна: напоминание, пришедшее во время правки, остаётся нажимаемым
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(820, 640)
        self.plan = copy.deepcopy(plan)
        self.default_lesson = plan.part_min if lesson_min is None else lesson_min
        self._apply_lesson(self.plan)
        self.break_min = break_min
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
        top.addWidget(QLabel("Урок:"))
        self.lesson_edit = LessonLengthEdit(follow=self.default_lesson)
        self.lesson_edit.setValue(self.plan.lesson_min)
        self.lesson_edit.setToolTip("Продолжительность урока — предел каждой части занятия: до перерыва и после "
                                    "него.<br>Минуты блока нельзя увеличить, если урок уже заполнен.<br>"
                                    "«Как в настройках» — из ⚙ Настройки; можно задать свою для этого шаблона.")
        self.lesson_edit.changed.connect(self._on_lesson)
        top.addWidget(self.lesson_edit)
        lay.addLayout(top)

        self.lessons_row = QWidget()
        lr = QHBoxLayout(self.lessons_row)
        lr.setContentsMargins(0, 0, 0, 0)
        lr.addWidget(QLabel("Уроки:", objectName="hint"))
        self.lessons_list = _LessonStrip()
        self.lessons_list.reordered.connect(self.reorder_lessons)
        self.lessons_list.rename.connect(self.rename_lesson)
        lr.addWidget(self.lessons_list, 1)
        lay.addWidget(self.lessons_row)

        self.table = _RowTable(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.row_moved.connect(self.move_row)
        hh = self.table.horizontalHeader()
        for c in range(len(COLS)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch if c == C_NAME
                                    else QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.table, 1)
        QApplication.instance().focusChanged.connect(self._focus_changed)

        row = QHBoxLayout()
        add = QPushButton("+ Добавить блок")
        add.setToolTip("После выбранного блока; если блок не выбран — в конец")
        add.clicked.connect(self._add)
        row.addWidget(add)
        add_lesson = QPushButton("+ Добавить урок")
        add_lesson.setToolTip("Ещё один урок в конце: перерыв и блок на всю продолжительность урока")
        add_lesson.clicked.connect(self.add_lesson)
        row.addWidget(add_lesson)
        for b in (add, add_lesson):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)    # нажатие не снимает выбор с блока
        row.addStretch(1)
        self.parts_lbl = QLabel()
        row.addWidget(self.parts_lbl)
        row.addSpacing(16)
        self.total = QLabel(objectName="muted")
        row.addWidget(self.total)
        lay.addLayout(row)
        note = QLabel("Блоки переставляются мышью за «⠿», уроки целиком — на полосе «Уроки» (двойной щелчок по уроку — "
                      "его название). Новый блок встаёт "
                      "после выбранного (в конец, если ничего не выбрано). «Напомнить» — в начале блока на мониторе управления появится напоминание, оно висит, пока "
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

    def done(self, r: int) -> None:
        QApplication.instance().focusChanged.disconnect(self._focus_changed)   # подписка — на всё приложение
        super().done(r)

    # ---------------------------------------------------------------- продолжительность урока
    @property
    def lesson_min(self) -> int:
        """Действующая продолжительность урока: своя у шаблона или из настроек."""
        return self.plan.part_min

    def _apply_lesson(self, plan: Plan) -> None:
        plan.part_min = plan.lesson_min if plan.lesson_min is not None else self.default_lesson

    def _on_lesson(self, v: int | None) -> None:
        self.plan.lesson_min = v
        self._apply_lesson(self.plan)
        self._sync_total()

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

    def _apply_limits(self) -> None:
        """Счётчик минут блока не даёт выйти за предел его части (до перерыва / после)."""
        breaks = [i for i, a in enumerate(self.plan.schedule) if a.breaks]
        self.table.set_marks(sorted({0, *breaks, *(i + 1 for i in breaks)}) if breaks else [])
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
                            ("Урок уже заполнен — сначала уменьшите другой блок" if room <= 0
                             else f"Можно добавить ещё {room} мин"))
        self._fill_lessons()
        parts = self.plan.parts()
        if not self.plan.part_min or not parts:
            self.parts_lbl.setText("")
            return
        bits = []
        for n, part in enumerate(parts, 1):
            t = self.plan.part_total(part)
            color = "#F2688B" if t > self.plan.part_min else ("#39C08A" if t == self.plan.part_min else "#9C8FBC")
            bits.append(f"<span style='color:{color}'>{n}-й урок: <b>{t}</b>/{self.plan.part_min}</span>")
        self.parts_lbl.setText(" · ".join(bits))

    def _fill_lessons(self) -> None:
        groups, _seps = split_lessons(self.plan.schedule)
        labels = [f"⠿ {n} · {self.plan.lesson_name(n - 1) or 'без названия'} · {sum(a.min for a in g)} мин"
                  for n, g in enumerate(groups, 1)]
        self.lessons_list.set_lessons(labels)

    def _sync_total(self) -> None:
        self._apply_limits()
        total = self.plan.total_min
        t0 = self.start.time()
        t1 = t0.addSecs(total * 60)
        self.total.setText(f"Итого {total} мин · {t0.toString('HH:mm')} – {t1.toString('HH:mm')}")
        if not self.json.hasFocus():
            self.json.setPlainText(json.dumps(self._collect_dict(), ensure_ascii=False, indent=2))

    def add_lesson(self) -> None:
        """Ещё урок: перерыв (если последним не стоит перерыв) и блок на всю продолжительность урока."""
        s = self.plan.schedule
        if s and not s[-1].breaks:
            s.append(Activity("ПЕРЕРЫВ", DEMO_NONE, self.break_min, remind=True, is_break=True))
        s.append(Activity(f"Урок {len(self.plan.parts()) + 1}", DEMO_ON, self.lesson_min or 45, remind=True))
        self._fill()
        self._focus_row(len(s) - 1)

    def _focus_changed(self, _old, new) -> None:
        """Выбранный блок — тот, в поле которого стоит курсор. Фокус ушёл в другое поле окна — выбора нет;
        Enter (фокус никуда) выбор не снимает."""
        if new is None or not self.isAncestorOf(new):
            return
        self.table.select(self.table.row_of(new))

    def _add(self) -> None:
        """Новый блок — после выбранного; если ничего не выбрано — в конец."""
        sel = self.table.selected
        i = sel + 1 if sel is not None and 0 <= sel < len(self.plan.schedule) else len(self.plan.schedule)
        self.plan.schedule.insert(i, Activity("Новый блок", DEMO_OFF, 5))
        room = self.plan.room(i)
        if room is not None and room < 0:          # в уроке места мало — сколько осталось, но не меньше 1
            self.plan.schedule[i].min = max(1, 5 + room)
        self._fill()
        self._focus_row(i)

    def _focus_row(self, i: int) -> None:
        self.table.select(i)
        self.table.scrollTo(self.table.model().index(i, C_NAME))
        self.table.cellWidget(i, C_NAME).setFocus()

    def reorder_lessons(self, order: list[int]) -> None:
        """Урок перетащили на полосе «Уроки»: все его блоки и название переезжают вместе, перерывы — на местах."""
        self.plan.schedule = reorder_lessons(self.plan.schedule, order)
        self.plan.lesson_names = [self.plan.lesson_name(i) for i in order]
        self.table.select(None)
        self._fill()

    def rename_lesson(self, i: int) -> None:
        name, ok = QInputDialog.getText(self, "Название урока", f"Урок {i + 1}:", text=self.plan.lesson_name(i))
        if ok:
            self.set_lesson_name(i, name)

    def set_lesson_name(self, i: int, name: str) -> None:
        names = self.plan.lesson_names
        names += [""] * (i + 1 - len(names))
        names[i] = name.strip()
        self._sync_total()

    def move_row(self, src: int, dst: int) -> None:
        """Перенос блока мышью: src — откуда, dst — место вставки (индекс до переноса, 0…len)."""
        s = self.plan.schedule
        if not 0 <= src < len(s):
            return
        dst = max(0, min(len(s), dst))
        if dst in (src, src + 1):
            return              # на своё же место
        block = s.pop(src)
        to = dst - 1 if dst > src else dst
        s.insert(to, block)
        self.table.select(to)
        self._fill()

    def _remove(self, i: int) -> None:
        if len(self.plan.schedule) > 1:
            del self.plan.schedule[i]
            self.table.select(None)
            self._fill()

    # ---------------------------------------------------------------- JSON и сохранение
    def _collect_dict(self) -> dict:
        d = plan_to(self.plan)
        d["title"] = self.title.text().strip() or "Вебинар"
        d["start"] = self.start.time().toString("HH:mm")
        return d

    def _apply_json(self) -> None:
        try:
            p = plan_from(json.loads(self.json.toPlainText()), self.title.text())
        except ValueError as e:              # и JSONDecodeError — это ValueError
            self.error.setText(f"Не получилось: {e}")
            return
        self.error.setText("")
        p.id = self.plan.id
        self._apply_lesson(p)                  # своя продолжительность из JSON или из настроек
        self.plan = p
        self.lesson_edit.setValue(p.lesson_min)
        self.title.setText(p.title)
        h, m = parse_time(p.start)
        self.start.setTime(QTime(h, m))
        self._fill()

    def _save(self) -> None:
        over = self.plan.over_limit()
        if over:
            self.json_toggle.setChecked(True)
            self.error.setText("Не сохранено: " + "; ".join(
                f"{n}-й урок — {t} мин из {self.plan.part_min}" for n, t in over) +
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
