"""Редактор шаблона вебинара: расписание и всё для экрана эфира (фон, зарядки, перерыв) — на одной странице."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (QColorDialog, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from ..efir.model import (ANIMATIONS, BG_BLACK, DEMO_NONE, DEMO_OFF, DEMO_ON, DEMOS, FONTS, KIND_BREAK,
                          KIND_EXERCISE, KIND_NORMAL, Activity, Exercise, Webinar, ai_prompt, export_json,
                          fmt_minutes, guess_kind, sample_webinar)
from . import icons
from .frameless import FramelessWindow
from .theme import theme
from .widgets import IconButton, MenuButton, Note, Switch, Toast, accent_button, button, group_title, label

VIDEO_FILTER = "Видео и картинки (*.mp4 *.webm *.mov *.m4v *.png *.jpg *.jpeg *.gif *.webp);;Все файлы (*.*)"
IMAGE_FILTER = "Картинки (*.png *.jpg *.jpeg *.gif *.webp *.bmp);;Все файлы (*.*)"
FONT_FILTER = "Шрифты (*.otf *.ttf *.woff *.woff2);;Все файлы (*.*)"


class BackgroundPicker(QWidget):
    """Выбор фона: список (чёрный, анимации, цвет, картинка) + «Посмотреть вживую» (галерея в браузере)."""

    def __init__(self, editor: "EditorWindow", value: str, allow_same: bool = False) -> None:
        super().__init__()
        self.editor = editor
        self.allow_same = allow_same
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.combo = QComboBox()
        self.combo.setMinimumWidth(230)
        if allow_same:
            self.combo.addItem(icons.icon("layers"), "Как основной фон", "")
        self.combo.addItem(icons.icon("monitor"), "Чёрный", BG_BLACK)
        for key, title in ANIMATIONS:
            self.combo.addItem(icons.icon("sparkles"), f"Анимация: {title}", f"anim:{key}")
        self.combo.addItem(icons.icon("palette"), "Свой цвет…", "pick-color")
        self.combo.addItem(icons.icon("image"), "Картинка…", "pick-image")
        self.combo.activated.connect(self._on_activated)
        lay.addWidget(self.combo)
        self.swatch = QLabel()
        self.swatch.setFixedSize(26, 26)
        lay.addWidget(self.swatch)
        self.live = button(" Галерея фонов", "external")
        self.live.setToolTip("Откроется страница со всеми фонами в браузере — щёлкните по нужному, "
                             "и он подставится сюда")
        self.live.clicked.connect(lambda: editor.open_gallery(self))
        lay.addWidget(self.live)
        lay.addStretch(1)
        self._value = ""
        self.set_value(value)

    def value(self) -> str:
        return self._value

    def set_value(self, value: str) -> None:
        self._value = value
        i = self.combo.findData(value)
        if i < 0:
            kind = value.partition(":")[0]
            title = f"Картинка: {Path(value[6:]).name}" if kind == "image" else f"Цвет {value[6:]}"
            ic = icons.icon("image" if kind == "image" else "palette")
            # отдельная строка для своего цвета/картинки — перед «Свой цвет…»
            old = self.combo.findData("custom", Qt.ItemDataRole.UserRole + 1)
            if old >= 0:
                self.combo.removeItem(old)
            pos = self.combo.findData("pick-color")
            self.combo.insertItem(pos, ic, title, value)
            self.combo.setItemData(pos, "custom", Qt.ItemDataRole.UserRole + 1)
            i = pos
        self.combo.setCurrentIndex(i)
        self._swatch()

    def _swatch(self) -> None:
        v = self._value
        color = "transparent"
        if v.startswith("color:"):
            color = v[6:]
        elif v.startswith("anim:"):
            color = "#16324a"
        elif v.startswith("image:"):
            color = "#3a2f55"
        border = theme.css("stroke_strong")
        self.swatch.setStyleSheet(f"background: {color}; border: 1px solid {border}; border-radius: 6px;")
        self.swatch.setVisible(bool(v))

    def _on_activated(self, _i: int) -> None:
        data = self.combo.currentData()
        if data == "pick-color":
            start = QColor(self._value[6:]) if self._value.startswith("color:") else QColor("#000000")
            c = QColorDialog.getColor(start, self, "Цвет фона")
            if c.isValid():
                self.set_value(f"color:{c.name().upper()}")
            else:
                self.set_value(self._value)
        elif data == "pick-image":
            path, _ = QFileDialog.getOpenFileName(self, "Картинка для фона", str(Path.home() / "Pictures"),
                                                  IMAGE_FILTER)
            if path:
                self.set_value(f"image:{path}")
            else:
                self.set_value(self._value)
        else:
            self.set_value(str(data))


KIND_LOOK = {KIND_NORMAL: ("Обычный", "text", "dim"), KIND_BREAK: ("Перерыв", "coffee", "accent"),
             KIND_EXERCISE: ("Зарядка", "eye", "role_explain")}
DEMO_LOOK = {DEMO_ON: ("Экран вкл", "monitor", "ok"), DEMO_OFF: ("Экран выкл", "monitor", "faint"),
             DEMO_NONE: ("Экран —", "minus", "faint")}


class ActivityRow(QFrame):
    """Строка расписания: время от начала, название, минуты, вид и демонстрация — маленькими кнопками с меню
    (не выпадающими списками: их легко «прокрутить» колесом, не заметив)."""

    def __init__(self, editor: "EditorWindow", a: Activity) -> None:
        super().__init__()
        self.editor = editor
        self.setObjectName("efirRow")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 3, 4, 3)
        lay.setSpacing(6)
        self.time_lbl = QLabel()
        self.time_lbl.setObjectName("mono")
        self.time_lbl.setFixedWidth(44)
        lay.addWidget(self.time_lbl)
        self.name = QLineEdit(a.name)
        self.name.setPlaceholderText("Название блока")
        self.name.textEdited.connect(self._name_edited)
        self.name.textEdited.connect(editor._touch)
        lay.addWidget(self.name, 1)
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 600)
        self.minutes.setValue(a.min)
        self.minutes.setSuffix(" мин")
        self.minutes.setFixedWidth(106)
        self.minutes.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.minutes.valueChanged.connect(editor.update_times)
        self.minutes.valueChanged.connect(editor._touch)
        lay.addWidget(self.minutes)
        self._kind = a.kind if a.kind in KIND_LOOK else KIND_NORMAL
        self._demo = a.demo if a.demo in DEMO_LOOK else DEMO_ON
        self._kind_touched = False
        self.kind_btn = MenuButton(self._fill_kind)
        self.kind_btn.setFixedWidth(104)
        self.kind_btn.setToolTip("Вид блока: перерыв и зарядка подсвечиваются в повестке таймера")
        self.demo_btn = MenuButton(self._fill_demo)
        self.demo_btn.setFixedWidth(112)
        self.demo_btn.setToolTip("Подсказка вам: в этом блоке демонстрация экрана включена или выключена")
        lay.addWidget(self.kind_btn)
        lay.addWidget(self.demo_btn)
        self._paint()
        for name, tip, fn in (("arrow-up", "Выше", lambda: editor.move_row(self, -1)),
                              ("arrow-down", "Ниже", lambda: editor.move_row(self, +1)),
                              ("insert-below", "Добавить блок ниже", lambda: editor.add_row(after=self)),
                              ("trash", "Удалить блок", lambda: editor.remove_row(self))):
            b = IconButton(name, tip, 15, box=28)
            b.clicked.connect(fn)
            lay.addWidget(b)

    def _fill_kind(self, m) -> None:
        for key, (text, ic, tok) in KIND_LOOK.items():
            a = m.addAction(icons.icon(ic, tok, 14), text, lambda k=key: self._set_kind(k, touched=True))
            a.setCheckable(True)
            a.setChecked(key == self._kind)

    def _fill_demo(self, m) -> None:
        for key, title in DEMOS:
            a = m.addAction(icons.icon(DEMO_LOOK[key][1], DEMO_LOOK[key][2], 14),
                            "Демонстрация: не важно" if key == DEMO_NONE else title, lambda k=key: self._set_demo(k))
            a.setCheckable(True)
            a.setChecked(key == self._demo)

    def _set_kind(self, key: str, touched: bool = False) -> None:
        if touched:
            self._kind_touched = True
        if key != self._kind:
            self._kind = key
            self._paint()
            self.editor._touch()

    def _set_demo(self, key: str) -> None:
        if key != self._demo:
            self._demo = key
            self._paint()
            self.editor._touch()

    def _paint(self) -> None:
        text, ic, tok = KIND_LOOK[self._kind]
        self.kind_btn.setText(text)
        self.kind_btn.setIcon(icons.icon(ic, tok, 13))
        self.kind_btn.setStyleSheet("" if self._kind == KIND_NORMAL else f"color: {theme.css(tok)};")
        text, ic, tok = DEMO_LOOK[self._demo]
        self.demo_btn.setText(text)
        self.demo_btn.setIcon(icons.icon(ic, tok, 13))

    def _name_edited(self, text: str) -> None:
        if not self._kind_touched:           # «Перерыв», «Зарядка для глаз» — вид по названию, пока не меняли вручную
            self._set_kind(guess_kind(text))

    def activity(self) -> Activity:
        return Activity(self.name.text().strip() or "Блок", self.minutes.value(), self._kind, self._demo)


class ExerciseRow(QFrame):
    def __init__(self, editor: "EditorWindow", ex: Exercise) -> None:
        super().__init__()
        self.editor = editor
        self.setObjectName("efirRow")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 3, 4, 3)
        lay.setSpacing(6)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("video", theme.c("dim"), 16))
        lay.addWidget(ic)
        self.title = QLineEdit(ex.title)
        self.title.setPlaceholderText("Название кнопки, например «Гимнастика для глаз»")
        self.title.setFixedWidth(240)
        lay.addWidget(self.title)
        self.path = ex.path
        self.path_lbl = label("", "dim")
        self.path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.path_lbl, 1)
        pick = button(" Файл…", "folder")
        pick.clicked.connect(self._pick)
        lay.addWidget(pick)
        rm = IconButton("trash", "Убрать зарядку", 15, box=28)
        rm.clicked.connect(lambda: editor.remove_exercise(self))
        lay.addWidget(rm)
        self._show_path()

    def _show_path(self) -> None:
        p = Path(self.path)
        ok = p.is_file()
        size = f" · {p.stat().st_size / 1_048_576:.0f} МБ" if ok else ""
        self.path_lbl.setText((p.name + size) if ok else f"⚠ нет файла: {self.path}")
        self.path_lbl.setToolTip(self.path)
        self.path_lbl.setStyleSheet("" if ok else f"color: {theme.css('live')};")

    def _pick(self) -> None:
        start = str(Path(self.path).parent) if self.path else str(Path.home() / "Videos")
        path, _ = QFileDialog.getOpenFileName(self, "Видео зарядки", start, VIDEO_FILTER)
        if path:
            self.path = path
            if not self.title.text().strip():
                self.title.setText(Path(path).stem)
            self._show_path()

    def exercise(self) -> Exercise | None:
        if not self.path:
            return None
        return Exercise(self.title.text().strip() or Path(self.path).stem, self.path)


class EditorWindow(FramelessWindow):
    def __init__(self, ctl, w: Webinar | None, parent=None) -> None:
        super().__init__("Шаблон вебинара", minimize=False, maximize=True, parent=parent)
        self.ctl = ctl
        self.settings = ctl.settings
        self.is_new = w is None
        self.w = w.copy() if w else sample_webinar()
        if w:
            self.w.id = w.id                    # правка того же шаблона
        else:
            self.w.title = "Новый вебинар"
        self._pick_target: BackgroundPicker | None = None
        self._dirty = False
        self.setObjectName("efirEditor")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(760, 520)
        self.resize(980, 820)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("pencil", theme.c("accent"), 16))
        self.titlebar.left.addWidget(ic)

        outer = QVBoxLayout(self.body)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        page = QWidget()
        page.setObjectName("page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(26, 10, 26, 18)
        lay.setSpacing(6)
        scroll.setWidget(page)
        outer.addWidget(scroll, 1)

        # ---- основное
        lay.addWidget(group_title("Основное"))
        row = QHBoxLayout()
        row.setSpacing(10)
        self.title = QLineEdit(self.w.title)
        self.title.setPlaceholderText("Например: 1Т — первая пара")
        self.title.setStyleSheet("font-size: 15px;")
        self.title.textEdited.connect(self._touch)
        row.addWidget(label("Название", "rowTitle"))
        row.addWidget(self.title, 1)
        lay.addLayout(row)
        lay.addWidget(label("Время начала в шаблоне не хранится — его выбирают при запуске («Сейчас» или «в 18:00»).",
                            "dim", wrap=True))

        # ---- расписание: итог — сразу в заголовке
        sh = QHBoxLayout()
        sh.addWidget(group_title("Расписание"))
        sh.addStretch(1)
        self.total = label("", "rowTitle")
        sh.addWidget(self.total, 0, Qt.AlignmentFlag.AlignBottom)
        lay.addLayout(sh)
        self.rows_host = QVBoxLayout()
        self.rows_host.setSpacing(4)
        lay.addLayout(self.rows_host)
        add = button(" Добавить блок", "plus")
        add.clicked.connect(lambda: self.add_row())
        ar = QHBoxLayout()
        ar.addWidget(add)
        ar.addStretch(1)
        lay.addLayout(ar)
        self.rows: list[ActivityRow] = []
        for a in self.w.schedule:
            self.add_row(a, focus=False)

        # ---- экран эфира: фон
        lay.addWidget(group_title("Экран эфира — фон (он же занавес)"))
        lay.addWidget(label("Виден ученикам, пока нет зарядки и перерыва. По умолчанию — чёрный: "
                            "без логотипов и фирменных цветов.", "dim", wrap=True))
        self.bg = BackgroundPicker(self, self.w.background)
        lay.addWidget(self.bg)
        cr = QHBoxLayout()
        cr.addWidget(label("Надпись на фоне", "rowTitle"))
        self.caption = QLineEdit(self.w.caption)
        self.caption.setPlaceholderText("Необязательно, например «Сейчас продолжим»")
        cr.addWidget(self.caption, 1)
        lay.addLayout(cr)

        # ---- зарядки
        lay.addWidget(group_title("Зарядки"))
        lay.addWidget(label("Видео со звуком на экран эфира. Доиграло — снова фон. Зарядок нет — нет и кнопки "
                            "«Зарядка» в таймере; несколько — кнопка предложит выбрать.", "dim", wrap=True))
        self.ex_host = QVBoxLayout()
        self.ex_host.setSpacing(4)
        lay.addLayout(self.ex_host)
        self.ex_rows: list[ExerciseRow] = []
        for ex in self.w.exercises:
            self._add_exercise_row(ex)
        er = QHBoxLayout()
        b = button(" Добавить видео (можно несколько)…", "video")
        b.clicked.connect(self.add_exercise)
        er.addWidget(b)
        er.addStretch(1)
        lay.addLayout(er)

        # ---- перерыв
        lay.addWidget(group_title("Перерыв"))
        br = QHBoxLayout()
        br.setSpacing(10)
        br.addWidget(label("По умолчанию", "rowTitle"))
        self.break_min = QSpinBox()
        self.break_min.setRange(1, 180)
        self.break_min.setValue(self.w.break_min)
        self.break_min.setSuffix(" мин")
        self.break_min.setFixedWidth(96)
        br.addWidget(self.break_min)
        br.addWidget(label("— подставится в «Перерыв» таймера; поменять можно и при запуске, и во время (±1 мин).",
                           "dim"), 1)
        lay.addLayout(br)
        bb = QHBoxLayout()
        bb.addWidget(label("Фон перерыва", "rowTitle"))
        lay.addLayout(bb)
        self.break_bg = BackgroundPicker(self, self.w.break_background, allow_same=True)
        lay.addWidget(self.break_bg)

        # ---- надпись на экране перерыва
        lay.addWidget(group_title("Надпись на экране перерыва"))
        tr = QHBoxLayout()
        tr.setSpacing(10)
        self.show_title = Switch("Показывать надпись")
        self.show_title.setChecked(self.w.break_show_title)
        tr.addWidget(self.show_title)
        self.break_title = QLineEdit(self.w.break_title)
        self.break_title.setFixedWidth(200)
        self.show_title.toggled.connect(self.break_title.setEnabled)
        self.break_title.setEnabled(self.w.break_show_title)
        tr.addWidget(self.break_title)
        tr.addSpacing(16)
        self.countdown = Switch("Обратный отсчёт")
        self.countdown.setChecked(self.w.break_countdown)
        tr.addWidget(self.countdown)
        tr.addStretch(1)
        lay.addLayout(tr)
        dr = QHBoxLayout()
        dr.setSpacing(10)
        dr.addWidget(label("Когда время вышло", "rowTitle"))
        self.break_done = QLineEdit(self.w.break_done)
        self.break_done.setFixedWidth(200)
        self.break_done.setPlaceholderText("Пусто — снова надпись")
        dr.addWidget(self.break_done)
        dr.addStretch(1)
        lay.addLayout(dr)
        fr = QHBoxLayout()
        fr.setSpacing(10)
        fr.addWidget(label("Шрифт", "rowTitle"))
        self.font = QComboBox()
        for key, title in FONTS:
            self.font.addItem(title, key)
        self.font.addItem(icons.icon("folder"), "Свой файл шрифта…", "pick-font")
        self.font.setMinimumWidth(230)
        self._font_value = ""
        self._set_font(self.w.font)
        self.font.activated.connect(self._on_font)
        fr.addWidget(self.font)
        fr.addSpacing(12)
        fr.addWidget(label("Цвет", "rowTitle"))
        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(46, 28)
        self.color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._color = self.w.text_color
        self.color_btn.clicked.connect(self._pick_color)
        self._paint_color()
        fr.addWidget(self.color_btn)
        fr.addStretch(1)
        prev = button(" Предпросмотр перерыва", "eye")
        prev.setToolTip("Экран перерыва с этими настройками — в новой вкладке браузера (ученики его не видят)")
        prev.clicked.connect(self.preview_break)
        fr.addWidget(prev)
        lay.addLayout(fr)
        lay.addSpacing(10)
        lay.addWidget(Note("Совет: перед эфиром откройте вкладку эфира (окно «Эфир» → «Открыть вкладку»), "
                           "щёлкните по ней один раз — браузер разрешит звук роликов, — и захватите её в "
                           "демонстрации.", "info"))
        lay.addStretch(1)

        # ---- низ
        bottom = QFrame()
        bottom.setObjectName("efirBottom")
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(22, 10, 22, 12)
        bl.setSpacing(8)
        b_json = button(" Экспорт JSON…", "export")
        b_json.clicked.connect(self._export)
        b_ai = button(" Для нейросети", "sparkles")
        b_ai.setToolTip("Скопировать промпт с этим расписанием как примером")
        b_ai.clicked.connect(self._copy_ai)
        bl.addWidget(b_json)
        bl.addWidget(b_ai)
        bl.addStretch(1)
        cancel = button("Отмена")
        cancel.clicked.connect(self.close)
        self.save_btn = accent_button(" Сохранить", "check")
        self.save_btn.clicked.connect(self.save)
        for b in (cancel, self.save_btn):
            b.setFixedHeight(34)
            bl.addWidget(b)
        outer.addWidget(bottom)
        self.toast = Toast(self.body)

        ctl.picked.connect(self._on_picked)
        theme.changed.connect(self._restyle)
        self._restyle()
        geo = getattr(self.settings, "efir_editor_geometry", "")
        if geo:
            self.restoreGeometry(QByteArray.fromBase64(geo.encode()))
        self.update_times()
        self._dirty = False
        self.titlebar.title.setText("Новый шаблон вебинара" if self.is_new else f"Шаблон: {self.w.title}")
        if self.is_new:
            QTimer.singleShot(0, lambda: (self.title.setFocus(), self.title.selectAll()))

    def _restyle(self) -> None:
        t = theme
        self.setStyleSheet(f"""
QWidget#efirEditor {{ background: {t.css('bg')}; }}
QFrame#efirRow {{ background: {t.css('card')}; border: 1px solid {t.css('stroke')}; border-radius: 8px; }}
QFrame#efirBottom {{ background: {t.css('panel')}; border-top: 1px solid {t.css('stroke')}; }}
""")

    def _touch(self, *_a) -> None:
        self._dirty = True

    # ------------------------------------------------------------ расписание
    def add_row(self, a: Activity | None = None, after: ActivityRow | None = None, focus: bool = True) -> None:
        r = ActivityRow(self, a or Activity("Новый блок", 5))
        idx = self.rows.index(after) + 1 if after in self.rows else len(self.rows)
        self.rows.insert(idx, r)
        self.rows_host.insertWidget(idx, r)
        self.update_times()
        if focus:
            self._dirty = True
            r.name.setFocus()
            r.name.selectAll()

    def remove_row(self, r: ActivityRow) -> None:
        if len(self.rows) <= 1:
            self.toast.show_message("В расписании должен остаться хотя бы один блок", warn=True)
            return
        self.rows.remove(r)
        r.setParent(None)
        r.deleteLater()
        self._dirty = True
        self.update_times()

    def move_row(self, r: ActivityRow, d: int) -> None:
        i = self.rows.index(r)
        j = i + d
        if not 0 <= j < len(self.rows):
            return
        self.rows[i], self.rows[j] = self.rows[j], self.rows[i]
        self.rows_host.removeWidget(r)
        self.rows_host.insertWidget(j, r)
        self._dirty = True
        self.update_times()

    def update_times(self, *_a) -> None:
        """Время блоков — от начала эфира («0:00», «0:05»…): само начало выбирают при запуске."""
        total = 0
        for r in self.rows:
            r.time_lbl.setText(f"{total // 60}:{total % 60:02d}")
            total += r.minutes.value()
        self.total.setText(f"Всего {fmt_minutes(total)} · блоков: {len(self.rows)}")

    # ------------------------------------------------------------ зарядки
    def _add_exercise_row(self, ex: Exercise) -> ExerciseRow:
        r = ExerciseRow(self, ex)
        self.ex_rows.append(r)
        self.ex_host.addWidget(r)
        return r

    def add_exercise(self) -> None:
        """Можно выбрать сразу несколько видео — каждое станет своей зарядкой."""
        paths, _ = QFileDialog.getOpenFileNames(self, "Видео зарядки (можно несколько)", str(Path.home() / "Videos"),
                                                VIDEO_FILTER)
        for path in paths:
            self._add_exercise_row(Exercise(Path(path).stem, path))
        if paths:
            self._dirty = True

    def remove_exercise(self, r: ExerciseRow) -> None:
        self.ex_rows.remove(r)
        r.setParent(None)
        r.deleteLater()
        self._dirty = True

    # ------------------------------------------------------------ шрифт, цвет, фон
    def _set_font(self, value: str) -> None:
        self._font_value = value
        i = self.font.findData(value)
        if i < 0 and value.startswith("file:"):
            old = self.font.findData("custom", Qt.ItemDataRole.UserRole + 1)
            if old >= 0:
                self.font.removeItem(old)
            pos = self.font.findData("pick-font")
            self.font.insertItem(pos, icons.icon("type"), f"Файл: {Path(value[5:]).name}", value)
            self.font.setItemData(pos, "custom", Qt.ItemDataRole.UserRole + 1)
            i = pos
        self.font.setCurrentIndex(max(0, i))

    def _on_font(self, _i: int) -> None:
        data = self.font.currentData()
        if data == "pick-font":
            path, _ = QFileDialog.getOpenFileName(self, "Файл шрифта", str(Path.home()), FONT_FILTER)
            self._set_font(f"file:{path}" if path else self._font_value)
        else:
            self._font_value = str(data)

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(QColor(self._color), self, "Цвет надписей")
        if c.isValid():
            self._color = c.name().upper()
            self._paint_color()

    def _paint_color(self) -> None:
        self.color_btn.setStyleSheet(f"background: {self._color}; border: 1px solid {theme.css('stroke_strong')};"
                                     "border-radius: 6px;")
        self.color_btn.setToolTip(self._color)

    def preview_break(self) -> str:
        url = self.ctl.preview_break(self.result())
        if url:
            self.toast.show_message("Предпросмотр перерыва открыт в браузере — ученики его не видят", ms=5000)
        return url

    def open_gallery(self, picker: BackgroundPicker) -> None:
        self._pick_target = picker
        self.ctl.open_gallery(picker.value())
        self.toast.show_message("В браузере открылись все фоны — щёлкните по нужному, он подставится сюда.", ms=6000)

    def _on_picked(self, value: str) -> None:
        if self._pick_target is not None and value:
            self._pick_target.set_value(value)
            self._dirty = True
            self.toast.show_message("Фон выбран")
            self.show_and_raise()

    # ------------------------------------------------------------ сохранить
    def result(self) -> Webinar:
        w = Webinar(id=self.w.id, lesson_id=self.w.lesson_id)   # эфир урока из суфлёра остаётся эфиром урока
        w.title = self.title.text().strip() or "Вебинар"
        w.start = self.w.start                  # прошлое время старта — подставится при следующем запуске
        w.schedule = [r.activity() for r in self.rows]
        w.background = self.bg.value() or BG_BLACK
        w.caption = self.caption.text().strip()
        w.exercises = [e for e in (r.exercise() for r in self.ex_rows) if e]
        w.break_min = self.break_min.value()
        w.break_countdown = self.countdown.isChecked()
        w.break_background = self.break_bg.value()
        w.break_title = self.break_title.text().strip() or "ПЕРЕРЫВ"
        w.break_show_title = self.show_title.isChecked()
        w.break_done = self.break_done.text().strip()
        w.font = self._font_value or "Montserrat"
        w.text_color = self._color
        return w

    def save(self) -> None:
        w = self.result()
        self.ctl.save_webinar(w)
        self._dirty = False
        self.w = w
        self.close()

    def _export(self) -> None:
        w = self.result()
        safe = "".join(c for c in w.title if c not in '\\/:*?"<>|').strip() or "Вебинар"
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт шаблона", str(Path.home() / "Documents" / f"{safe}.json"),
                                              "JSON (*.json)")
        if path:
            try:
                Path(path).write_text(export_json([w]), encoding="utf-8")
                self.toast.show_message(f"Сохранено: {path}")
            except OSError as e:
                self.toast.show_message(f"Не сохранено: {e}", warn=True)

    def _copy_ai(self) -> None:
        QGuiApplication.clipboard().setText(ai_prompt(self.result()))
        self.toast.show_message("Промпт скопирован: вставьте в чат нейросети, допишите расписание, ответ — "
                                "«Импорт → Из буфера обмена» в окне «Эфир».", ms=8000)

    # ------------------------------------------------------------ окно
    def show_and_raise(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e) -> None:
        if self._dirty and self._changed():
            r = QMessageBox.question(self, "Шаблон не сохранён", "Сохранить изменения в шаблоне?",
                                     QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                                     | QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel:
                e.ignore()
                return
            if r == QMessageBox.StandardButton.Save:
                self.ctl.save_webinar(self.result())
        if self.settings is not None:
            self.settings.efir_editor_geometry = bytes(self.saveGeometry().toBase64()).decode()
            self.settings.save()
        try:
            self.ctl.picked.disconnect(self._on_picked)
        except (RuntimeError, TypeError):
            pass
        super().closeEvent(e)

    def _changed(self) -> bool:
        old = self.ctl.store.get(self.w.id)
        new = self.result()
        return old is None or old.to_dict() != new.to_dict()
