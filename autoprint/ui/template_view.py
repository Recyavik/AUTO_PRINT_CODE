"""Образец: заголовок и все блоки одной лентой."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QScrollArea, QVBoxLayout, QWidget

from .. import scenario
from ..storage import BLOCK_CODE, BLOCK_IMAGE, BLOCK_MARKDOWN, BLOCK_STAGE, Block, Template
from .blocks import (BlockWidget, CodeBlockWidget, MarkdownBlockWidget, StageBlockWidget,
                     make_block_widget)
from .widgets import button


class ZoomWheelFilter(QObject):
    """Ctrl/Shift + колёсико над блоком образца → масштаб этого блока, а не прокрутка.
    Ставится на всё приложение: колёсико сначала получают сами редакторы внутри блоков."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._acc = 0   # тачпады шлют мелкие шаги — копим до одного «щелчка» колеса (120)

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() != QEvent.Type.Wheel or not isinstance(obj, QWidget):
            return False
        if not ev.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            return False
        w = obj
        while w is not None and not isinstance(w, BlockWidget):
            w = w.parentWidget()
        if w is None:
            return False
        d = ev.angleDelta()
        self._acc += d.y() or d.x()   # с Shift Qt иногда отдаёт шаг по горизонтали
        steps = int(self._acc / 120)
        self._acc -= steps * 120
        if steps:
            w.zoom_by(steps)
        return True


def _plural(n: int, one: str, few: str, many: str) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return few
    return many


class TemplateView(QWidget):
    changed = Signal()            # содержимое образца изменилось → сохранить
    armed_changed = Signal(str)   # id активного блока кода
    zoom_changed = Signal(int)    # масштаб какого-то блока изменился, %
    steps_changed = Signal(str)   # разметка шагов блока (id) поменялась
    step_pointer_requested = Signal(str, int)   # (id блока, шаг) — печатать дальше с этого шага
    suflor_requested = Signal()   # «Суфлёр урока» — открыть страницу суфлёра

    def __init__(self, template: Template) -> None:
        super().__init__()
        self.template = template
        self.widgets: list[BlockWidget] = []
        self.step_mode = False
        self.step_pointer = lambda _bid: None   # главное окно подставляет: id блока → следующий шаг

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.page = QWidget()
        self.page.setObjectName("page")
        self.page_lay = QVBoxLayout(self.page)
        self.page_lay.setContentsMargins(2, 6, 12, 28)
        self.page_lay.setSpacing(10)

        head = QWidget()
        hrow = QHBoxLayout(head)
        hrow.setContentsMargins(0, 0, 0, 6)
        hrow.setSpacing(12)
        hl = QVBoxLayout()
        hl.setSpacing(2)
        self.title_lbl = QLabel()
        self.title_lbl.setObjectName("pageTitle")
        self.lede = QLabel()
        self.lede.setObjectName("lede")
        hl.addWidget(self.title_lbl)
        hl.addWidget(self.lede)
        hrow.addLayout(hl, 1)
        self.suflor_btn = button("Суфлёр урока", "presentation")
        self.suflor_btn.setToolTip("Страница суфлёра в отдельном окне браузера: этапы по времени, что сказать, "
                                   "спросить и показать. Ученики её не видят — они видят только захваченную вкладку")
        self.suflor_btn.clicked.connect(self.suflor_requested)
        hrow.addWidget(self.suflor_btn, 0, Qt.AlignmentFlag.AlignTop)
        self.page_lay.addWidget(head)

        add_row = QHBoxLayout()
        add_row.setSpacing(10)
        for text, kind, tip in (("Текст", BLOCK_MARKDOWN, "Текст в Markdown: условие, пояснение, подсказки суфлёра "
                                                          "(говоришь, спроси, делаешь…) — тип выбирается в шапке блока"),
                                ("Код", BLOCK_CODE, "Блок кода — его печатает программа"),
                                ("Этап урока", BLOCK_STAGE, "Этап урока для суфлёра: название и минуты"),
                                ("Картинка", BLOCK_IMAGE, "Слайд или скриншот для суфлёра")):
            b = button(text, "plus")
            b.setObjectName("addBtn")
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=kind: self.add_block(k))
            add_row.addWidget(b, 1)
        self.page_lay.addLayout(add_row)
        self.page_lay.addStretch(1)
        self.scroll.setWidget(self.page)
        lay.addWidget(self.scroll, 1)

        self.changed.connect(self.refresh_header)
        self.changed.connect(self.refresh_stage_times)
        self._rebuild()

    # ------------------------------------------------------------ заголовок
    def refresh_header(self) -> None:
        t = self.template
        self.title_lbl.setText(t.title)
        n, code = len(t.blocks), len(t.code_blocks())
        k = sum(b.type == BLOCK_STAGE for b in t.blocks)
        stages = f"{k} {_plural(k, 'этап', 'этапа', 'этапов')} · {scenario.total_minutes(t)} мин · " if k else ""
        self.lede.setText(f"{stages}{n} {_plural(n, 'блок', 'блока', 'блоков')} · "
                          f"кода — {code} · двойной щелчок по названию слева — переименовать")

    def refresh_stage_times(self) -> None:
        """Время этапов от начала урока («0:10–0:20») — в шапках блоков-этапов."""
        _intro, stages = scenario.stages(self.template)
        by_id = {s.block.id: s for s in stages}
        for w in self.widgets:
            if isinstance(w, StageBlockWidget) and w.block.id in by_id:
                s = by_id[w.block.id]
                w.set_time(s.start_min, s.end_min)

    # ------------------------------------------------------------ блоки
    def _rebuild(self, keep_scroll: bool = False) -> None:
        scroll_pos = self.scroll.verticalScrollBar().value()
        for wdg in self.widgets:
            wdg.setParent(None)
            wdg.deleteLater()
        self.widgets = []
        n = 0
        for b in self.template.blocks:
            if b.type == BLOCK_CODE:
                n += 1
            wdg = make_block_widget(b, n)
            if b.zoom != 100:
                wdg.set_zoom(b.zoom)
            self._wire(wdg)
            self.page_lay.insertWidget(1 + len(self.widgets), wdg)
            self.widgets.append(wdg)
        # если в образце ещё нет активного блока — делаем активным первый блок кода
        codes = [w for w in self.widgets if isinstance(w, CodeBlockWidget)]
        if codes and not self.template.find_block(self.template.active_block):
            self.arm(codes[0].block.id)   # активный блок — код или текст; нет никакого — первый блок кода
        self._apply_armed()
        self.refresh_header()
        self.refresh_stage_times()
        if keep_scroll:
            QTimer.singleShot(0, self, lambda: self.scroll.verticalScrollBar().setValue(scroll_pos))
        else:
            self.scroll.verticalScrollBar().setValue(0)

    def reset_zoom(self) -> None:
        for w in self.widgets:
            w.apply_zoom(100)

    def _wire(self, wdg: BlockWidget) -> None:
        wdg.changed.connect(self.changed)
        wdg.move_requested.connect(self._move_block)
        wdg.delete_requested.connect(self._delete_block)
        wdg.type_requested.connect(self._change_type)
        wdg.insert_requested.connect(self._insert_near)
        wdg.zoom_changed.connect(self.zoom_changed)
        wdg.arm_requested.connect(lambda w: self.arm(w.block.id))   # и текст печатается
        if isinstance(wdg, CodeBlockWidget):
            wdg.steps_changed.connect(lambda w: self.steps_changed.emit(w.block.id))
            wdg.step_pointer_requested.connect(lambda w, k: self.step_pointer_requested.emit(w.block.id, k))
            wdg.set_step_mode(self.step_mode, self.step_pointer(wdg.block.id))

    def _renumber(self) -> None:
        n = 0
        for w in self.widgets:
            if isinstance(w, CodeBlockWidget):
                n += 1
                w.set_number(n)

    def add_block(self, kind: str) -> None:
        """Кнопки внизу: новый блок встаёт сразу после активного блока, а если активного нет — в конец."""
        bl = self.template.blocks
        active = self.template.find_block(self.template.active_block)
        self._insert_block(bl.index(active) + 1 if active else len(bl), kind)

    def _insert_near(self, wdg: BlockWidget, after: int, kind: str) -> None:
        """Кнопки «вставить выше / ниже» в шапке блока."""
        self._insert_block(self.template.blocks.index(wdg.block) + after, kind)

    def _insert_block(self, idx: int, kind: str) -> None:
        bl = self.template.blocks
        b = Block(kind, "", minutes=5 if kind == BLOCK_STAGE else 0)
        if kind == BLOCK_CODE:
            last = next((x for x in reversed(bl[:idx]) if x.type == BLOCK_CODE), None) \
                or next((x for x in bl if x.type == BLOCK_CODE), None)
            if last:
                b.lang = last.lang
        bl.insert(idx, b)
        self._rebuild(keep_scroll=True)
        wdg = self.widgets[idx]
        if isinstance(wdg, CodeBlockWidget):
            self.arm(b.id)
            wdg.editor.setFocus()
        elif isinstance(wdg, MarkdownBlockWidget):
            wdg.set_editing(True)
        elif isinstance(wdg, StageBlockWidget):
            wdg.title.setFocus()
        QTimer.singleShot(50, wdg, lambda: self.scroll.ensureWidgetVisible(wdg))
        self.changed.emit()

    def _move_block(self, wdg: BlockWidget, d: int) -> None:
        """Переставляет блок без пересборки страницы — редакторы сохраняют состояние."""
        bl = self.template.blocks
        i = bl.index(wdg.block)
        j = i + d
        if not 0 <= j < len(bl):
            return
        bl[i], bl[j] = bl[j], bl[i]
        self.widgets[i], self.widgets[j] = self.widgets[j], self.widgets[i]
        self.page_lay.removeWidget(wdg)
        self.page_lay.insertWidget(1 + j, wdg)
        self._renumber()
        QTimer.singleShot(30, wdg, lambda: self.scroll.ensureWidgetVisible(wdg, 0, 40))
        self.changed.emit()

    def _change_type(self, wdg: BlockWidget, key: str) -> None:
        """Смена типа: роль Markdown-блока или превращение текст ⇄ код (текст, выделение и «активный» сохраняются).
        В этап или картинку: прежний текст или код уходит отдельным блоком ниже (у этапа — без первой строки,
        она становится его названием)."""
        b = wdg.block
        if key == "code":
            if b.type != BLOCK_CODE:
                last = next((x for x in self.template.blocks if x.type == BLOCK_CODE), None)
                b.lang = last.lang if last else b.lang
            b.type = BLOCK_CODE
        elif key in (BLOCK_STAGE, BLOCK_IMAGE) and b.type != key:
            # у этапа и картинки своё содержимое: прежний текст или код не теряется — уходит блоком ниже
            keep = None
            if b.type == BLOCK_CODE:
                if b.text.strip():
                    keep = Block(BLOCK_CODE, b.text, lang=b.lang, steps=list(b.steps), title=b.title,
                                 profile=b.profile)
                b.title = ""
            elif b.type == BLOCK_MARKDOWN and b.text.strip():
                lines = b.text.strip().split("\n")
                rest = b.text.strip()
                if key == BLOCK_STAGE:
                    b.title = b.title or lines[0].lstrip("# ").strip()[:120]   # первая строка — название этапа
                    rest = "\n".join(lines[1:]).strip()
                if rest:
                    keep = Block(BLOCK_MARKDOWN, rest, role=b.role, print_as=b.print_as)
            b.text, b.sel, b.steps = "", [], []
            if key == BLOCK_STAGE:
                b.minutes = b.minutes or 5
            b.type = key
            if keep is not None:
                bl = self.template.blocks
                bl.insert(bl.index(b) + 1, keep)
                if self.template.active_block == b.id:
                    self.template.active_block = keep.id    # печатать можно только сам код, а не этап
        elif key in (BLOCK_STAGE, BLOCK_IMAGE):
            pass
        else:
            b.type = BLOCK_MARKDOWN
            b.role = key
        self._rebuild(keep_scroll=True)
        self.armed_changed.emit(self.template.active_block)
        self.changed.emit()

    def _delete_block(self, wdg: BlockWidget) -> None:
        if wdg.block.text.strip() and QMessageBox.question(
                self, "Удалить блок", "Удалить блок вместе с содержимым?") != QMessageBox.StandardButton.Yes:
            return
        self.template.blocks.remove(wdg.block)
        if wdg.block.id == self.template.active_block:
            self.template.active_block = ""
        self._rebuild(keep_scroll=True)
        if not self.template.active_block:
            self.armed_changed.emit("")
        self.changed.emit()

    # ------------------------------------------------------------ активный блок / прогресс
    def arm(self, block_id: str) -> None:
        if self.template.active_block != block_id:
            self.template.active_block = block_id
            self.changed.emit()
        self._apply_armed()
        self.armed_changed.emit(block_id)

    def _apply_armed(self) -> None:
        for w in self.widgets:
            on = w.block.id == self.template.active_block
            w.set_armed(on)
            if not on and w.block.sel:
                w.clear_selection()   # выделение — только у активного блока

    def code_widget(self, block_id: str) -> CodeBlockWidget | None:
        return next((w for w in self.widgets if isinstance(w, CodeBlockWidget) and w.block.id == block_id), None)

    def block_widget(self, block_id: str) -> BlockWidget | None:
        return next((w for w in self.widgets if w.block.id == block_id), None)

    def clear_progress(self) -> None:
        for w in self.widgets:
            if isinstance(w, CodeBlockWidget):
                w.clear_progress()

    def apply_step_mode(self, on: bool) -> None:
        """Режим «По шагам» и указатели «следующий шаг» — во все блоки кода."""
        self.step_mode = on
        for w in self.widgets:
            if isinstance(w, CodeBlockWidget):
                w.set_step_mode(on, self.step_pointer(w.block.id))

    def go_to_block(self, block_id: str) -> None:
        if not self.template.find_block(block_id):
            return
        self.arm(block_id)
        w = self.block_widget(block_id)
        if w:
            QTimer.singleShot(30, w, lambda: self.scroll.ensureWidgetVisible(w, 0, 40))
