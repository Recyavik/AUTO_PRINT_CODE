"""Виджеты блоков образца: текстовый (Markdown) и код."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPainter, QTextCursor
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu,
                               QPlainTextEdit, QSizePolicy, QStackedWidget, QStyle, QStyleOptionComboBox,
                               QStylePainter, QTextBrowser, QToolButton, QVBoxLayout)

from ..highlighter import LANGUAGES
from ..storage import BLOCK_CODE, BLOCK_MARKDOWN, PROFILE_SHORT, PROFILES, ROLES, Block
from ..textprint import PRINT_MODES, find_selection
from . import icons
from .code_editor import CodeEditor, code_font
from .theme import css, mix, theme
from .widgets import IconButton, repolish

ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 50, 300, 10

CODE_TYPE = "code"
ROLE_ICONS = {"text": "text", "task": "file-text", "explain": "info", "hint": "help"}
TYPE_ITEMS = [(name, key, ROLE_ICONS.get(key, "text"), f"role_{key}") for key, (_i, name, _c) in ROLES.items()] \
    + [("Код", CODE_TYPE, "code", "accent")]


class IconCombo(QComboBox):
    """Тип блока: в шапке — только значок, в раскрытом списке — значок и название."""

    def paintEvent(self, e) -> None:
        p = QStylePainter(self)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        opt.currentText = ""
        opt.currentIcon = QIcon()
        p.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, opt)
        ic = self.itemIcon(self.currentIndex())
        if not ic.isNull():
            s = self.iconSize()
            p.drawPixmap(8, (self.height() - s.height()) // 2, ic.pixmap(s))

    def sizeHint(self) -> QSize:
        return QSize(50, 26)

    def minimumSizeHint(self) -> QSize:
        return QSize(50, 26)

    def showPopup(self) -> None:
        self.view().setMinimumWidth(180)
        super().showPopup()


class BlockWidget(QFrame):
    changed = Signal()
    arm_requested = Signal(object)                # сделать блок активным для печати (код или текст)
    move_requested = Signal(object, int)          # (виджет, -1|+1)
    delete_requested = Signal(object)
    type_requested = Signal(object, str)          # (виджет, роль | "code")
    insert_requested = Signal(object, int, str)   # (виджет, 0 — выше | 1 — ниже, тип нового блока)
    zoom_changed = Signal(int)                    # новый масштаб блока, % — для сообщения

    def __init__(self, block: Block, code_number: int = 0) -> None:
        super().__init__()
        self.block = block
        self.code_number = code_number
        self.setObjectName("block")
        self.setProperty("armed", False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 10, 12)
        lay.setSpacing(8)

        # шапка: [тип][заголовок][доп. слева] … [доп. справа][＋↑][＋↓][↑][↓][✕]
        self.header = QHBoxLayout()
        self.header.setSpacing(4)
        self.kind = IconCombo()
        self.kind.setObjectName("kindCombo")
        self.kind.setIconSize(QSize(15, 15))
        self.kind.setToolTip("Тип блока: текст, условие, пояснение, подсказка или код")
        for text, key, _ic, _tok in TYPE_ITEMS:
            self.kind.addItem(text, key)
        self.kind.setCurrentIndex(self.kind.findData(CODE_TYPE if block.type == BLOCK_CODE else block.role))
        self.kind.activated.connect(self._on_kind)
        self.header.addWidget(self.kind)

        self.title = QLineEdit(block.title)
        self.title.setObjectName("blockTitle")
        self.title.setToolTip("Заголовок блока — щёлкните, чтобы изменить")
        self.title.setMinimumWidth(80)
        self.title.setMaximumWidth(320)
        self.title.textEdited.connect(self._on_title)
        self.header.addWidget(self.title)
        self._update_placeholder()

        self.left_slot = QHBoxLayout()
        self.left_slot.setSpacing(8)
        self.header.addLayout(self.left_slot)
        self.armed = False
        self.arm_btn = QToolButton()
        self.arm_btn.setObjectName("armBtn")
        self.arm_btn.setCheckable(True)
        self.arm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.arm_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.arm_btn.setIconSize(QSize(11, 11))
        self.arm_btn.setToolTip("Сделать этот блок активным для печати по хоткею")
        self.arm_btn.clicked.connect(lambda: self.arm_requested.emit(self))
        self.left_slot.addWidget(self.arm_btn)
        self.header.addStretch(1)
        self.right_slot = QHBoxLayout()
        self.right_slot.setSpacing(4)
        self.header.addLayout(self.right_slot)
        # окно для этого блока: терминал на сайте (git в браузере) Windows не отличит от редактора — выбирают здесь
        self.window = QComboBox()
        self.window.setObjectName("langCombo")
        self.window.setFixedWidth(172)
        self.window.addItem("Как на пульте", "")
        for key, name in PROFILE_SHORT.items():
            self.window.addItem(name, key)
        self.window.setCurrentIndex(max(0, self.window.findData(block.profile)))
        self.window.setToolTip("Куда печатается этот блок:\n"
                               + "\n".join(f"• {PROFILE_SHORT[k]} — {v}" for k, v in PROFILES.items())
                               + "\nКак на пульте — как выбрано в «Куда печатаем» на пульте.\n"
                                 "Терминал на сайте (git в браузере) — выберите «Терминал»: иначе в строке появятся «F».")
        self.window.activated.connect(self._on_window)
        self.right_slot.addWidget(self.window)
        self._refresh_window_icons()
        self.header.addSpacing(4)

        self._insert_actions = []
        for name, tip, after in (("insert-above", "Вставить блок выше", 0), ("insert-below", "Вставить блок ниже", 1)):
            b = IconButton(name, tip, 15, box=26)
            m = QMenu(b)
            self._insert_actions += [
                (m.addAction("Текст (Markdown)", lambda a=after: self.insert_requested.emit(self, a, BLOCK_MARKDOWN)),
                 "text"),
                (m.addAction("Блок кода", lambda a=after: self.insert_requested.emit(self, a, BLOCK_CODE)), "code")]
            b.setMenu(m)
            b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            self.header.addWidget(b)

        for name, tip, slot in (("arrow-up", "Блок выше", lambda: self.move_requested.emit(self, -1)),
                                ("arrow-down", "Блок ниже", lambda: self.move_requested.emit(self, +1)),
                                ("trash", "Удалить блок", lambda: self.delete_requested.emit(self))):
            b = IconButton(name, tip, 15, box=26)
            b.clicked.connect(slot)
            self.header.addWidget(b)
        lay.addLayout(self.header)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(self.body)
        self._refresh_kind_icons()
        theme.changed.connect(self._refresh_kind_icons)

    def _refresh_window_icons(self) -> None:
        for i in range(self.window.count()):   # своё окно у блока — значок цветом акцента
            self.window.setItemIcon(i, icons.icon("monitor", "dim" if i == 0 else "accent", 13))

    def _refresh_kind_icons(self) -> None:
        if hasattr(self, "window"):
            self._refresh_window_icons()
        for i, (_t, _k, ic, tok) in enumerate(TYPE_ITEMS):
            self.kind.setItemIcon(i, icons.icon(ic, tok, 14))
        for action, ic in self._insert_actions:
            action.setIcon(icons.icon(ic))
        self.update()

    def role_token(self) -> str:
        if self.block.type == BLOCK_CODE:
            return "accent"
        # роль приходит и из импорта (.ipynb, .json) — незнакомая рисуется как обычный текст
        return f"role_{self.block.role}" if self.block.role in ROLES else "role_text"

    def paintEvent(self, e) -> None:
        super().paintEvent(e)
        if self.block.type != BLOCK_CODE:
            # цветная черта роли слева, как отметка выбранного пункта в PasteTalk
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.c(self.role_token()))
            p.drawRoundedRect(QRectF(1, 12, 3, self.height() - 24), 1.5, 1.5)
            p.end()

    def zoom_by(self, steps: int) -> None:
        self.apply_zoom(self.block.zoom + steps * ZOOM_STEP)

    def apply_zoom(self, zoom: int) -> None:
        """Масштаб только этого блока; хранится в самом блоке."""
        zoom = max(ZOOM_MIN, min(ZOOM_MAX, zoom))
        if zoom != self.block.zoom:
            self.block.zoom = zoom
            self.set_zoom(zoom)
            self.changed.emit()
        self.zoom_changed.emit(zoom)

    def set_zoom(self, zoom: int) -> None:
        """Шрифт содержимого под масштаб, % — переопределяют наследники."""

    def _update_placeholder(self) -> None:
        self.title.setPlaceholderText(Block(self.block.type, role=self.block.role, title="")
                                      .display_title(self.code_number))

    def _on_title(self, text: str) -> None:
        self.block.title = text
        self.changed.emit()

    def _on_kind(self, _i: int) -> None:
        key = self.kind.currentData()
        current = CODE_TYPE if self.block.type == BLOCK_CODE else self.block.role
        if key != current:
            self.type_requested.emit(self, key)

    def _on_window(self, _i: int) -> None:
        self.block.profile = self.window.currentData()
        self.changed.emit()
        self.arm_requested.emit(self)

    def clear_selection(self) -> None:
        """Снять выделение (оно бывает только у активного блока) — переопределяют наследники."""

    def set_armed(self, on: bool) -> None:
        self.armed = on
        self.arm_btn.setChecked(on)
        self.arm_btn.setText("Активный" if on else "Печатать этот")
        self.arm_btn.setIcon(icons.icon("play", "accent" if on else "dim", 11))
        if self.property("armed") != on:
            self.setProperty("armed", on)
            repolish(self)


# ------------------------------------------------------------------ Markdown

class _AutoBrowser(QTextBrowser):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("mdView")
        self.setOpenExternalLinks(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.viewport().setAutoFillBackground(False)
        self.document().setDocumentMargin(2)

    def fit(self) -> None:
        self.document().setTextWidth(self.viewport().width())
        self.setFixedHeight(max(26, int(self.document().size().height()) + 4))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.fit()


def _markdown_css() -> str:
    code_bg = mix(theme.c("card"), theme.c("text"), 0.08).name()
    return (f'code {{ font-family: "{theme.mono_family}"; background-color: {code_bg}; }}'
            f'pre {{ font-family: "{theme.mono_family}"; background-color: {code_bg}; }}'
            f'a {{ color: {theme.c("accent").name()}; }}'
            f'h1, h2, h3 {{ font-family: "{theme.display_family}"; }}')


class MarkdownBlockWidget(BlockWidget):
    """Текст: условие, пояснение, подсказка. Тоже печатается — как Markdown, простым текстом или комментарием
    в коде; выделенные строки — только они (как у блока кода)."""

    def __init__(self, block: Block) -> None:
        super().__init__(block)
        self._rendering = False   # setMarkdown сбрасывает курсор просмотра — это не выбор пользователя
        self.print_as = QComboBox()
        self.print_as.setObjectName("langCombo")
        self.print_as.setFixedWidth(176)
        for key, name in PRINT_MODES.items():
            self.print_as.addItem(name[0].upper() + name[1:], key)   # «Как Markdown», «Простым текстом»…
        self.print_as.setCurrentIndex(max(0, self.print_as.findData(block.print_as)))
        self.print_as.setToolTip("Как печатать этот блок:\n"
                                 "• как Markdown — исходник с ## и `…` (markdown-ячейка Jupyter, .md-файл);\n"
                                 "• простым текстом — без разметки (Блокнот, Word, чат);\n"
                                 "• комментарием в коде — каждая строка с # или // по языку блока кода рядом")
        self.print_as.activated.connect(self._on_print_as)
        self.left_slot.addWidget(self.print_as)
        self.info = QLabel()
        self.info.setObjectName("dim")
        self.left_slot.addWidget(self.info)
        self.toggle = QToolButton()
        self.toggle.setObjectName("textBtn")
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setIconSize(QSize(14, 14))
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle.setToolTip("Переключить: просмотр / редактирование Markdown")
        self.toggle.clicked.connect(self.toggle_mode)
        self.right_slot.addWidget(self.toggle)

        self.stack = QStackedWidget()
        self.view = _AutoBrowser()
        self.view.viewport().installEventFilter(self)
        self.edit = QPlainTextEdit(block.text)
        self.edit.setObjectName("mdEdit")
        self.edit.installEventFilter(self)
        self.edit.setFont(code_font(10))
        self.edit.setPlaceholderText("Текст в формате Markdown: условие, пояснение к коду, подсказка…")
        self.edit.textChanged.connect(self._on_text)
        self.view.selectionChanged.connect(self._on_view_selection)
        self.edit.selectionChanged.connect(self._on_edit_selection)
        self.stack.addWidget(self.view)
        self.stack.addWidget(self.edit)
        self.body.addWidget(self.stack)
        self.body.setContentsMargins(6, 0, 0, 0)
        theme.changed.connect(self._on_theme)
        self._render()
        self.set_editing(not block.text.strip(), focus=False)
        self._update_info()
        self.set_armed(False)

    def _on_theme(self) -> None:
        self._render()
        self._update_toggle()
        self.set_armed(self.armed)

    # ---- выделение: печатаются только выделенные строки (как в блоке кода)
    def _on_view_selection(self) -> None:
        if self._rendering or self.stack.currentWidget() is not self.view:
            return   # перерисовка (выход из правки, масштаб) — выделение не трогаем
        c = self.view.textCursor()
        sel = []
        if c.hasSelection():
            hint = c.selectionStart() / max(1, self.view.document().characterCount())
            sel = find_selection(self.block.text, c.selection().toPlainText(), hint)
        self._set_sel(sel)

    def _on_edit_selection(self) -> None:
        if self.stack.currentWidget() is self.edit:
            self._sel_from_edit()

    def _sel_from_edit(self) -> None:
        c = self.edit.textCursor()
        self._set_sel([c.selectionStart(), c.selectionEnd()] if c.hasSelection() else [])

    def _restore_edit_selection(self) -> None:
        """Сохранённое выделение (из просмотра или с прошлого запуска) — видимым в редакторе."""
        c = self.edit.textCursor()
        if len(self.block.sel) == 2:
            n = len(self.block.text)
            a, b = (min(max(0, x), n) for x in self.block.sel)
            c.setPosition(a)
            c.setPosition(b, QTextCursor.MoveMode.KeepAnchor)
        else:
            c.clearSelection()
        self.edit.setTextCursor(c)

    def _set_sel(self, sel: list[int]) -> None:
        if sel != self.block.sel:
            self.block.sel = sel
            self._update_info()
            self.changed.emit()

    def _update_info(self) -> None:
        if self.block.sel:
            a, b = self.block.sel
            n = self.block.text[a:b].rstrip("\n").count("\n") + 1
            self.info.setText(f"<span style='color:{css(theme.c('accent'))}'>выделено строк: {n}</span>")
        self.info.setVisible(bool(self.block.sel))

    def clear_selection(self) -> None:
        for w in (self.view, self.edit):
            c = w.textCursor()
            c.clearSelection()
            w.setTextCursor(c)
        self._set_sel([])

    def eventFilter(self, obj, ev) -> bool:
        t = ev.type()
        if obj is self.edit:
            if t == ev.Type.FocusIn:
                self.arm_requested.emit(self)   # правка блока — блок активный, как у блока кода
            return False
        if t == ev.Type.MouseButtonDblClick:
            self.set_editing(True)
            return True
        if t == ev.Type.MouseButtonPress:
            self.arm_requested.emit(self)       # щелчок по тексту — блок активный, как у блока кода
        elif t == ev.Type.MouseButtonRelease and self.stack.currentWidget() is self.view \
                and not self.view.textCursor().hasSelection():
            self._set_sel([])                   # щелчок без выделения — печатать весь блок
        return False

    def _on_print_as(self, _i: int) -> None:
        self.block.print_as = self.print_as.currentData()
        self.changed.emit()
        self.arm_requested.emit(self)

    def _on_text(self) -> None:
        self.block.text = self.edit.toPlainText()
        self._sel_from_edit()                   # прежние позиции выделения после правки неверны
        self._fit_edit()
        self.changed.emit()

    def _render(self) -> None:
        self.view.document().setDefaultStyleSheet(_markdown_css())
        self._rendering = True
        try:
            self.view.setMarkdown(self.block.text or "*Пустой блок — дважды щёлкните, чтобы написать*")
        finally:
            self._rendering = False
        QTimer.singleShot(0, self, self._fit)

    def _fit(self) -> None:
        if self.stack.currentWidget() is self.view:
            self.view.fit()
            self.stack.setFixedHeight(self.view.height())
        else:
            self._fit_edit()

    def _fit_edit(self) -> None:
        if self.stack.currentWidget() is self.edit:
            lines = max(4, min(25, self.edit.document().blockCount() + 1))
            h = lines * self.edit.fontMetrics().lineSpacing() + 18
            self.edit.setFixedHeight(h)
            self.stack.setFixedHeight(h)

    def _update_toggle(self) -> None:
        editing = self.stack.currentWidget() is self.edit
        self.toggle.setText("Готово" if editing else "Править")
        self.toggle.setIcon(icons.icon("check" if editing else "pencil", "accent" if editing else "dim", 14))

    def set_editing(self, on: bool, focus: bool = True) -> None:
        """focus=False — при создании виджета: фокус в редакторе сделал бы блок активным."""
        if on:
            self.stack.setCurrentWidget(self.edit)
            self._restore_edit_selection()
            if focus:
                self.edit.setFocus()
        else:
            self._render()
            self.stack.setCurrentWidget(self.view)
        self._update_toggle()
        self._fit()

    def toggle_mode(self) -> None:
        self.set_editing(self.stack.currentWidget() is self.view)

    def set_zoom(self, zoom: int) -> None:
        f = QApplication.font()
        base = f.pixelSize() if f.pixelSize() > 0 else 13
        f.setPixelSize(max(6, round(base * zoom / 100)))
        self.view.setFont(f)
        self.edit.setFont(code_font(max(5, round(10 * zoom / 100))))
        self._render()
        self._fit()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        QTimer.singleShot(0, self, self._fit)


# ------------------------------------------------------------------ Код

class CodeBlockWidget(BlockWidget):
    selection_changed = Signal(object)
    steps_changed = Signal(object)              # разметка шагов поменялась
    step_pointer_requested = Signal(object, int)   # «печатать дальше с шага k»

    def __init__(self, block: Block, number: int) -> None:
        super().__init__(block, number)
        self.step_mode = False
        self.step_next: int | None = None       # какой шаг печатать следующим (None — все напечатаны)
        self.info = QLabel()
        self.info.setObjectName("dim")
        self.left_slot.addWidget(self.info)
        self.steps_btn = QToolButton()
        self.steps_btn.setObjectName("armBtn")
        self.steps_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.steps_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.steps_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.steps_btn.setIconSize(QSize(12, 12))
        self.steps_btn.setToolTip("Печать по шагам: шаг строки — правый щелчок по строке, Alt+1…9 "
                                  "или щелчок по цветному номеру слева")
        self.steps_menu = QMenu(self.steps_btn)
        self.steps_menu.aboutToShow.connect(self._fill_steps_menu)
        self.steps_btn.setMenu(self.steps_menu)
        self.left_slot.addWidget(self.steps_btn)
        self.lang = QComboBox()
        self.lang.setObjectName("langCombo")
        self.lang.setEditable(True)
        self.lang.addItems(LANGUAGES)
        self.lang.setCurrentText(block.lang)
        self.lang.setFixedWidth(118)
        self.lang.setToolTip("Язык подсветки (на печать не влияет)")
        self.lang.currentTextChanged.connect(self._on_lang)
        self.right_slot.addWidget(self.lang)

        self.frame = QFrame()
        self.frame.setObjectName("codeFrame")
        fl = QVBoxLayout(self.frame)
        fl.setContentsMargins(0, 2, 0, 0)
        self.editor = CodeEditor(block.text, block.lang)
        self.editor.setPlaceholderText("Код занятия. Выделите строки — будут напечатаны только они.")
        self.editor.textChanged.connect(self._on_text)
        self.editor.selectionChanged.connect(self._on_selection)
        self.editor.focused.connect(lambda: self.arm_requested.emit(self))
        self.editor.height_changed.connect(self._fit)
        self.editor.set_steps(block.steps)
        self.editor.steps_changed.connect(self._on_steps)
        self.editor.markup_requested.connect(self._markup)
        fl.addWidget(self.editor)
        self.body.addWidget(self.frame)
        self._restore_selection()
        self._fit()
        self._update_info()
        self.set_armed(False)
        self._update_steps()
        theme.changed.connect(self._on_theme)

    def _on_theme(self) -> None:
        self._update_info()
        self.set_armed(self.armed)
        self._update_steps()

    # ---- шаги
    def step_numbers(self) -> list[int]:
        return sorted(set(self.editor.line_steps())) or [1]

    def _on_steps(self) -> None:
        steps = self.editor.line_steps()
        self.block.steps = [] if all(s == 1 for s in steps) else steps
        self._update_steps()
        self.steps_changed.emit(self)
        self.changed.emit()

    def _markup(self, key: str) -> None:
        from .. import steps as S
        text = self.block.text
        if key == "comments":
            new = S.auto_by_comments(text, self.block.lang)
        elif key == "blank":
            new = S.auto_by_blank_lines(text)
        else:
            new = []
        self.editor.set_steps(new)
        self.editor.set_steps_visible(True)
        self._on_steps()

    def set_step_mode(self, on: bool, next_step: int | None) -> None:
        self.step_mode, self.step_next = on, next_step
        self._update_steps()

    def _update_steps(self) -> None:
        nums = self.step_numbers()
        multi = len(nums) > 1
        self.editor.set_steps_visible(multi or self.step_mode)
        self.steps_btn.setVisible(multi or self.step_mode)
        if self.step_mode:
            if self.step_next is None:
                text = f"Шаги: все {len(nums)} готовы"
            else:
                idx = nums.index(self.step_next) + 1 if self.step_next in nums else 1
                text = f"Шаг {idx} из {len(nums)}"
            self.editor.set_step_view(self.step_next if self.step_next is not None else max(nums) + 1)
        else:
            text = f"Шагов: {len(nums)}"
            self.editor.set_step_view(None)
        self.steps_btn.setText(text)
        self.steps_btn.setIcon(icons.icon("layers", "accent" if self.step_mode else "dim", 12))

    def _fill_steps_menu(self) -> None:
        m = self.steps_menu
        m.clear()
        nums = self.step_numbers()
        head = m.addAction("Печатать дальше с шага:")
        head.setEnabled(False)
        counts = {k: 0 for k in nums}
        for s in self.editor.line_steps():
            counts[s] = counts.get(s, 0) + 1
        for i, k in enumerate(nums, start=1):
            a = m.addAction(f"Шаг {i}  ·  строк: {counts.get(k, 0)}")
            a.setCheckable(True)
            a.setChecked(self.step_mode and k == self.step_next)
            a.triggered.connect(lambda _=False, k=k: self.step_pointer_requested.emit(self, k))
        m.addSeparator()
        for key, text in (("comments", "Разметить по комментариям"), ("blank", "Разметить по пустым строкам"),
                          ("reset", "Сбросить: весь блок — шаг 1")):
            m.addAction(text, lambda key=key: self._markup(key))
        m.addSeparator()
        hint = m.addAction("Шаг строки: правый щелчок по строке, Alt+1…9, Alt+0 — новый")
        hint.setEnabled(False)

    def set_step_progress(self, step: int, pos: int) -> None:
        self.editor.set_step_view(step, pos)

    def set_number(self, n: int) -> None:
        self.code_number = n
        self._update_placeholder()

    def _fit(self) -> None:
        self.editor.setFixedHeight(self.editor.content_height())

    def set_zoom(self, zoom: int) -> None:
        self.editor.setFont(code_font(max(5, round(11 * zoom / 100))))
        self.editor.update_gutter_width()
        self._fit()

    def _on_lang(self, lang: str) -> None:
        self.block.lang = lang.strip().lower() or "text"
        self.editor.highlighter.set_language(self.block.lang)
        self.changed.emit()

    def _on_text(self) -> None:
        self.block.text = self.editor.toPlainText()
        self._update_info()
        self.changed.emit()

    def _on_selection(self) -> None:
        c = self.editor.textCursor()
        self.block.sel = [c.selectionStart(), c.selectionEnd()] if c.hasSelection() else []
        self._update_info()
        self.selection_changed.emit(self)
        self.changed.emit()

    def _restore_selection(self) -> None:
        if len(self.block.sel) == 2:
            n = len(self.block.text)
            a, b = (min(max(0, x), n) for x in self.block.sel)
            if b > a:
                c = self.editor.textCursor()
                c.setPosition(a)
                c.setPosition(b, QTextCursor.MoveMode.KeepAnchor)
                self.editor.setTextCursor(c)

    def clear_selection(self) -> None:
        c = self.editor.textCursor()
        c.clearSelection()
        self.editor.setTextCursor(c)

    def _update_info(self) -> None:
        text = self.block.text
        lines = text.count("\n") + 1 if text else 0
        if self.block.sel:
            a, b = self.block.sel
            n = text[a:b].rstrip("\n").count("\n") + 1
            self.info.setText(f"<span style='color:{css(theme.c('accent'))}'>выделено строк: {n} из {lines}</span>")
        else:
            self.info.setText(f"{lines} стр. · {len(text)} симв.")

    def set_progress(self, start: int, pos: int, end: int) -> None:
        self.editor.set_progress(start, pos, end)

    def clear_progress(self) -> None:
        self.editor.clear_progress()
        self._update_steps()   # вид шагов — снова «что дальше», а не ход печати

    def typing_text(self, whole_lines: bool) -> tuple[str, int]:
        return typing_slice(self.block.text, self.block.sel, whole_lines)


def typing_slice(text: str, sel: list[int], whole_lines: bool) -> tuple[str, int]:
    """Что печатать: выделение (расширенное до целых строк) или весь блок. → (текст, смещение)."""
    if len(sel) != 2 or sel[1] <= sel[0]:
        return text, 0
    a, b = max(0, sel[0]), min(len(text), sel[1])
    if whole_lines:
        a = text.rfind("\n", 0, a) + 1
        if b > a and text[b - 1] == "\n":
            b -= 1
        nl = text.find("\n", b)
        b = len(text) if nl < 0 else nl
    return text[a:b], a


def make_block_widget(block: Block, code_number: int) -> BlockWidget:
    if block.type == BLOCK_CODE:
        return CodeBlockWidget(block, code_number)
    return MarkdownBlockWidget(block)
