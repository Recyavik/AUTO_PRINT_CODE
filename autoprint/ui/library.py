"""Список уроков — тело окна программы: поиск, уроки (название и «1 ч 30 мин · 12 этапов · 5 кодов»),
кнопки «Открыть», «Новый урок», «Импорт», «Из методички». Урок открывается на экране урока (в браузере)."""
from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLineEdit, QListWidget, QMenu, QPushButton,
                               QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from . import icons
from .theme import theme
from .widgets import accent_button, button, label

ROLE_ID = Qt.ItemDataRole.UserRole
ROLE_META = Qt.ItemDataRole.UserRole + 1      # подпись под названием: длительность, этапы, коды
ROLE_LIVE = Qt.ItemDataRole.UserRole + 2      # урок идёт — красная точка


def lesson_meta(t) -> str:
    """«1 ч 30 мин · 12 этапов · 5 кодов» — что в уроке, одной строкой."""
    from ..efir.model import fmt_minutes
    from ..storage import BLOCK_STAGE, is_printable
    from .print_control import _plural
    stages = [b for b in t.blocks if b.type == BLOCK_STAGE]
    codes = sum(1 for b in t.blocks if is_printable(b))
    parts = []
    if stages:
        total = sum(max(0, int(b.minutes or 0)) for b in stages)
        parts.append(fmt_minutes(total))
        parts.append(f"{len(stages)} {_plural(len(stages), 'этап', 'этапа', 'этапов')}")
    parts.append(f"{codes} {_plural(codes, 'код', 'кода', 'кодов')}" if codes else "без кода")
    return " · ".join(parts)


class LibraryDelegate(QStyledItemDelegate):
    ROW_H = 50

    def paint(self, p: QPainter, opt, index) -> None:
        r = QRectF(opt.rect).adjusted(0, 2, 0, -2)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        hover = bool(opt.state & QStyle.StateFlag.State_MouseOver)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        if selected or hover:
            p.setBrush(theme.c("card") if selected else theme.c("stroke"))
            p.drawRoundedRect(r, 7, 7)
        if selected:
            p.setBrush(theme.c("accent"))
            p.drawRoundedRect(QRectF(r.left(), r.center().y() - 10, 3, 20), 1.5, 1.5)
        ic = icons.pixmap("presentation", theme.c("accent" if selected else "dim"), 16, 1.8)
        p.drawPixmap(int(r.left() + 12), int(r.center().y() - 8), ic)
        right = int(r.right() - 12)
        if index.data(ROLE_LIVE):
            p.setBrush(theme.c("live"))
            p.drawEllipse(QRectF(right - 8, r.center().y() - 4, 8, 8))
            right -= 18
        left = int(r.left() + 40)
        f = theme.font(13)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(theme.c("text"))
        top = int(r.top() + 6)
        title = QFontMetrics(f).elidedText(index.data(Qt.ItemDataRole.DisplayRole) or "",
                                           Qt.TextElideMode.ElideRight, right - left)
        p.drawText(QRect(left, top, right - left, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, title)
        f2 = theme.font(11)
        p.setFont(f2)
        p.setPen(theme.c("dim"))
        meta = QFontMetrics(f2).elidedText(index.data(ROLE_META) or "", Qt.TextElideMode.ElideRight, right - left)
        p.drawText(QRect(left, top + 20, right - left, 18), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   meta)
        p.restore()

    def sizeHint(self, opt, index) -> QSize:
        return QSize(opt.rect.width(), self.ROW_H)

    def updateEditorGeometry(self, editor, opt, index) -> None:
        editor.setGeometry(opt.rect.adjusted(36, 6, -8, -22))


class LibraryPanel(QWidget):
    """Поиск, список уроков, кнопки. Объявление об обновлении — над кнопками."""
    open_requested = Signal()
    new_requested = Signal()
    new_structure = Signal(str)      # «Новый урок ▾»: ключ STRUCTURES или "presentation"
    import_requested = Signal()
    ai_requested = Signal()
    update_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("navPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Поиск уроков…")
        self.search.setClearButtonEnabled(True)
        self._search_action = self.search.addAction(icons.icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        lay.addWidget(self.search)
        lay.addWidget(label("Уроки", "navGroup"))

        self.list = QListWidget()
        self.list.setObjectName("library")
        self.list.setItemDelegate(LibraryDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        # двойной щелчок открывает урок; переименовать — F2 или меню
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.itemDoubleClicked.connect(lambda _it: self.open_requested.emit())
        self.list.itemActivated.connect(lambda _it: self.open_requested.emit())
        lay.addWidget(self.list, 1)

        self.update_btn = QPushButton()
        self.update_btn.setObjectName("updateBtn")
        self.update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_btn.clicked.connect(self.update_clicked)
        self.update_btn.hide()
        lay.addWidget(self.update_btn)

        self.btn_open = accent_button("Открыть урок", "presentation")
        self.btn_open.setToolTip("Открыть урок на экране урока: подготовка и ведение (Enter)")
        self.btn_open.clicked.connect(self.open_requested)
        lay.addWidget(self.btn_open)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_new = button("Новый урок ▾", "plus")
        self.btn_new.setToolTip("Новый урок: пустой, по шаблону структуры или из презентации (Ctrl+N — пустой)")
        self.btn_new.clicked.connect(lambda: self.new_menu().exec(self.btn_new.mapToGlobal(self.btn_new.rect().bottomLeft())))
        self.btn_import = button("Импорт…", "import")
        self.btn_import.setToolTip("Урок из файла: .ipynb (Jupyter), .md, .py или .json (Ctrl+O)")
        self.btn_import.clicked.connect(self.import_requested)
        self.btn_ai = button("Из методички…", "sparkles")
        self.btn_ai.setToolTip("Урок из методички, презентации или выгрузки — нейросетью")
        self.btn_ai.clicked.connect(self.ai_requested)
        for b in (self.btn_new, self.btn_import, self.btn_ai):
            row.addWidget(b, 1)
        lay.addLayout(row)
        theme.changed.connect(self._on_theme)

    def new_menu(self) -> QMenu:
        """«Новый урок ▾»: пустой, по шаблону структуры (этапы с минутами), из презентации."""
        from ..storage import STRUCTURES
        m = QMenu(self)
        for key, (title, stages) in STRUCTURES.items():
            hint = f" — {len(stages)} этапов" if stages else ""
            a = m.addAction(title)
            a.setToolTip(title + hint)
            a.triggered.connect(lambda _=False, k=key: self.new_structure.emit(k))
            if key == "empty":
                m.addSeparator()
        m.addSeparator()
        a = m.addAction("Из презентации…")
        a.triggered.connect(lambda: self.new_structure.emit("presentation"))
        return m

    def _on_theme(self) -> None:
        self._search_action.setIcon(icons.icon("search"))
        self.update_btn.setIcon(icons.icon("upgrade", "accent"))
        self.list.viewport().update()

    def show_update(self, text: str | None) -> None:
        if text:
            self.update_btn.setText(text)
            self.update_btn.setIcon(icons.icon("upgrade", "accent"))
            self.update_btn.show()
        else:
            self.update_btn.hide()
