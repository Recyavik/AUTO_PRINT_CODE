"""Элементы интерфейса в стиле PasteTalk: переключатель, сегменты, карточка со строками, тост и т. п."""
from __future__ import annotations

from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation, QRect, QRectF, QSize, Qt,
                            QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox,
                               QApplication, QButtonGroup, QComboBox, QDoubleSpinBox, QFrame,
                               QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLayout, QPushButton, QScrollBar,
                               QMenu, QSizePolicy, QSlider, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from . import icons
from .theme import theme


def repolish(w: QWidget) -> None:
    """После смены динамического свойства (setProperty) QSS нужно применить заново."""
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


# ---------------------------------------------------------------- колёсико

def _wheel_target(w: QWidget | None) -> QWidget | None:
    """Счётчик, список или ползунок, которому достанется колесо (событие приходит и в их внутреннее поле)."""
    for _ in range(3):
        if w is None:
            return None
        if isinstance(w, (QAbstractSpinBox, QComboBox)) or \
                (isinstance(w, QAbstractSlider) and not isinstance(w, QScrollBar)):
            return w
        w = w.parentWidget()
    return None


class WheelGuard(QObject):
    """Колёсико над счётчиком, выпадающим списком или ползунком меняет значение, только если по нему уже
    щёлкнули (у него фокус). Иначе колесо крутит страницу вокруг — минуты и типы блоков не «уезжают»,
    пока прокручиваешь ленту. Ставится на всё приложение (install_wheel_guard)."""

    def eventFilter(self, obj, ev) -> bool:
        t = ev.type()
        if t == QEvent.Type.Polish:
            _no_wheel_focus(obj)
            return False
        if t != QEvent.Type.Wheel or not isinstance(obj, QWidget):
            return False
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            return False                    # Ctrl+колесо — масштаб блока (ZoomWheelFilter)
        target = _wheel_target(obj)
        if target is None:
            return False
        fw = QApplication.focusWidget()
        if fw is not None and (fw is target or target.isAncestorOf(fw)):
            return False                    # щёлкнули — значение меняется колесом, как обычно
        area = target.parentWidget()
        while area is not None and not isinstance(area, QAbstractScrollArea):
            area = area.parentWidget()
        if area is not None:
            d = ev.angleDelta()
            bar = area.horizontalScrollBar() if abs(d.x()) > abs(d.y()) else area.verticalScrollBar()
            QApplication.sendEvent(bar, ev)
        return True


def _no_wheel_focus(w) -> None:
    """Счётчики и списки по умолчанию берут фокус от колеса (WheelFocus): у настоящей мыши Qt отдаёт им фокус
    раньше любых фильтров — и значение менялось. Фокус — только щелчком или Tab."""
    if isinstance(w, (QAbstractSpinBox, QComboBox)) or (isinstance(w, QAbstractSlider) and not isinstance(w, QScrollBar)):
        if w.focusPolicy() == Qt.FocusPolicy.WheelFocus:
            w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)


def install_wheel_guard(app: QApplication) -> WheelGuard:
    guard = app.property("_wheel_guard_obj")
    if isinstance(guard, WheelGuard):
        return guard
    guard = WheelGuard(app)
    app.installEventFilter(guard)
    app.setProperty("_wheel_guard_obj", guard)
    for w in QApplication.allWidgets():      # созданные до установки — тоже
        _no_wheel_focus(w)
    return guard


# ---------------------------------------------------------------- переключатель

class Switch(QAbstractButton):
    """Переключатель PasteTalk; текст (если задан) — справа, щелчок по тексту тоже переключает."""
    W, H = 36, 20

    def __init__(self, text: str = "", checked: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setText(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._pos = 1.0 if checked else 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self.toggled.connect(self._animate)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        theme.changed.connect(self.update)

    def _on_anim(self, v) -> None:
        self._pos = float(v)
        self.update()

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def setChecked(self, on: bool) -> None:   # без анимации при программной установке
        super().setChecked(on)
        anim = getattr(self, "_anim", None)
        if anim is not None:
            anim.stop()
        self._pos = 1.0 if on else 0.0
        self.update()

    def sizeHint(self) -> QSize:
        w = self.W
        if self.text():
            w += 9 + QFontMetrics(self.font()).horizontalAdvance(self.text()) + 2
        return QSize(w, max(self.H, QFontMetrics(self.font()).height()) + 2)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.45)
        y = (self.height() - self.H) / 2
        track = QRectF(0.5, y + 0.5, self.W - 1, self.H - 1)
        on = self._pos
        off_bg, on_bg = theme.c("bg"), theme.c("accent")
        bg = off_bg if on < 0.5 else on_bg
        p.setPen(QPen(theme.c("accent") if on >= 0.5 else
                      (theme.c("dim") if self.underMouse() else theme.c("stroke_strong")), 1))
        p.setBrush(bg)
        p.drawRoundedRect(track, self.H / 2, self.H / 2)
        d = 10
        x = 5 + on * (self.W - 10 - d)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("on_accent") if on >= 0.5 else theme.c("dim"))
        p.drawEllipse(QRectF(x, y + (self.H - d) / 2, d, d))
        if self.hasFocus():
            p.setPen(QPen(theme.c("accent"), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(track.adjusted(-2, -2, 2, 2), self.H / 2 + 2, self.H / 2 + 2)
        if self.text():
            p.setPen(theme.c("text"))
            p.setFont(self.font())
            p.drawText(QRect(self.W + 9, 0, self.width() - self.W - 9, self.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        p.end()

    def enterEvent(self, e) -> None:
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self.update()
        super().leaveEvent(e)


# ---------------------------------------------------------------- ползунок

class Slider(QSlider):
    """Тонкая дорожка и круглая ручка (как в PasteTalk). Щелчок по дорожке ставит значение сразу."""
    H = 22

    def __init__(self, lo: int = 0, hi: int = 100, parent=None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(lo, hi)
        self.setFixedHeight(self.H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        theme.changed.connect(self.update)

    def _x_for(self, value: int) -> float:
        span = max(1, self.maximum() - self.minimum())
        return 8 + (self.width() - 16) * (value - self.minimum()) / span

    def _set_from_x(self, x: float) -> None:
        span = self.maximum() - self.minimum()
        frac = (x - 8) / max(1, self.width() - 16)
        self.setValue(round(self.minimum() + max(0.0, min(1.0, frac)) * span))

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.setSliderDown(True)
            self._set_from_x(e.position().x())
            e.accept()
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:
        if self.isSliderDown():
            self._set_from_x(e.position().x())
        self.update()

    def mouseReleaseEvent(self, e) -> None:
        if self.isSliderDown():
            self.setSliderDown(False)
        self.update()

    def leaveEvent(self, e) -> None:
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isEnabled()
        cy = self.height() / 2
        x = self._x_for(self.value())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("stroke_strong"))
        p.drawRoundedRect(QRectF(8, cy - 2, self.width() - 16, 4), 2, 2)
        p.setBrush(theme.c("accent") if on else theme.c("faint"))
        p.drawRoundedRect(QRectF(8, cy - 2, max(0.0, x - 8), 4), 2, 2)
        r = 7.5 if (self.underMouse() or self.isSliderDown()) and on else 7
        p.setBrush(theme.c("accent_hover" if self.isSliderDown() else "accent") if on else theme.c("faint"))
        p.drawEllipse(QRectF(x - r, cy - r, 2 * r, 2 * r))
        p.end()


# ---------------------------------------------------------------- сегменты

class _SegButton(QPushButton):
    """Сегмент: ширина — под полужирный текст. Выбранный сегмент в QSS полужирный, а размер кнопки
    считается по обычному шрифту — без запаса выбранное название обрезалось («Целико…»)."""

    def sizeHint(self) -> QSize:
        s = super().sizeHint()
        bold = self.font()
        bold.setWeight(QFont.Weight.DemiBold)
        need = QFontMetrics(bold).horizontalAdvance(self.text()) + 2 * 11 + 4   # поля из QSS + рамка
        return QSize(max(s.width(), need), s.height())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()


class Segmented(QWidget):
    """Кнопки-сегменты «Медленно | Стандарт | Быстро». value — ключ выбранного или None."""
    changed = Signal(object)

    def __init__(self, options: list[tuple[object, str]], parent=None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[object, QPushButton] = {}
        n = len(options)
        for i, (key, label) in enumerate(options):
            b = _SegButton(label)
            b.setObjectName("segBtn")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setProperty("pos", "only" if n == 1 else "first" if i == 0 else "last" if i == n - 1 else "mid")
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            self.group.addButton(b)
            self.buttons[key] = b
            lay.addWidget(b)

    def value(self):
        return next((k for k, b in self.buttons.items() if b.isChecked()), None)

    def set_value(self, key) -> None:
        self.group.setExclusive(False)
        for k, b in self.buttons.items():
            b.setChecked(k == key)
        self.group.setExclusive(True)


# ---------------------------------------------------------------- кнопки

class IconButton(QToolButton):
    """Кнопка-значок; цвет значка следует теме."""

    def __init__(self, name: str, tip: str = "", size: int = 16, color: str = "dim", box: int = 28,
                 framed: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("iconBtn")
        self._name, self._color, self._size = name, color, size
        self.setToolTip(tip)
        self.setIconSize(QSize(size, size))
        self.setFixedSize(box, box)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        if framed:
            self.setProperty("framed", True)
        self._refresh()
        theme.changed.connect(self._refresh)

    def set_icon(self, name: str, color: str | None = None) -> None:
        self._name = name
        if color:
            self._color = color
        self._refresh()

    def _refresh(self) -> None:
        self.setIcon(icons.icon(self._name, self._color, self._size))


class NavButton(QPushButton):
    """Пункт бокового меню: значок + текст; выбранный — фон карточки и янтарная черта слева."""

    def __init__(self, icon_name: str, text: str, parent=None) -> None:
        super().__init__(text, parent)
        self.setObjectName("navBtn")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._icon = icon_name
        self.setIconSize(QSize(16, 16))
        self.toggled.connect(lambda _: self._refresh())
        theme.changed.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        self.setIcon(icons.icon(self._icon, "accent" if self.isChecked() else "dim"))

    def paintEvent(self, e) -> None:
        super().paintEvent(e)
        if self.isChecked():
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.c("accent"))
            h = 16
            p.drawRoundedRect(QRectF(0, (self.height() - h) / 2, 3, h), 1.5, 1.5)
            p.end()


class ThemedButton(QPushButton):
    """Кнопка со значком в цвет темы. Значок обновляет собственный метод кнопки — при удалении
    кнопки Qt сам отключает его от theme.changed (замыкание осталось бы висеть на мёртвом объекте)."""

    def __init__(self, text: str, icon_name: str = "", color: str = "dim", parent=None) -> None:
        super().__init__(f" {text}" if icon_name else text, parent)   # пробел — зазор между значком и текстом
        self._icon_name, self._color = icon_name, color
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if icon_name:
            self._refresh()
            theme.changed.connect(self._refresh)

    def _refresh(self) -> None:
        self.setIcon(icons.icon(self._icon_name, self._color))


def accent_button(text: str, icon_name: str = "") -> QPushButton:
    b = ThemedButton(text, icon_name, "on_accent")
    b.setProperty("accent", True)
    return b


def button(text: str, icon_name: str = "", quiet: bool = False) -> QPushButton:
    b = ThemedButton(text, icon_name, "dim")
    if quiet:
        b.setProperty("quiet", True)
    return b


# ---------------------------------------------------------------- подписи, разделители

def label(text: str = "", name: str = "", wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    if wrap:
        lb.setWordWrap(True)
    return lb


def vsep(height: int = 22) -> QFrame:
    f = QFrame()
    f.setObjectName("vsep")
    f.setFixedHeight(height)
    return f


def flow_sep(height: int = 22, pad: int = 6) -> QWidget:
    """Вертикальный разделитель для FlowLayout: прячется в начале и в конце строки."""
    w = QWidget()
    w.setProperty("flowSep", True)
    lay = QHBoxLayout(w)
    lay.setContentsMargins(pad, 0, pad, 0)
    lay.addWidget(vsep(height))
    return w


def hsep() -> QFrame:
    f = QFrame()
    f.setObjectName("hsep")
    return f


class Pill(QLabel):
    def __init__(self, text: str = "", tone: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setObjectName("pill")
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        self.setProperty("tone", tone)
        repolish(self)


class IconLabel(QLabel):
    """Значок в цвет темы (обновляется при смене темы)."""

    def __init__(self, name: str, color: str = "dim", size: int = 18, parent=None) -> None:
        super().__init__(parent)
        self._name, self._color, self._size = name, color, size
        self.setFixedSize(size, size)
        self._refresh()
        theme.changed.connect(self._refresh)

    def set_color(self, color: str) -> None:
        self._color = color
        self._refresh()

    def _refresh(self) -> None:
        self.setPixmap(icons.pixmap(self._name, theme.c(self._color), self._size, 1.8))


# ---------------------------------------------------------------- карточка со строками (страницы настроек)

class Row(QWidget):
    """Строка карточки: [значок] [название / пояснение] … [элементы управления]."""

    def __init__(self, icon_name: str, title: str, sub: str = "", controls: list[QWidget] | None = None,
                 stack: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("row")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("first", False)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(14)
        if icon_name:
            ic = IconLabel(icon_name, "dim", 18)
            outer.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop if stack else Qt.AlignmentFlag.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = label(title, "rowTitle")
        text.addWidget(self.title)
        self.sub = label(sub, "rowSub", wrap=True)
        if not sub:
            # только скрывать: setVisible(True) у ещё не вставленной подписи показал бы её отдельным окном —
            # при открытии настроек на панели задач мелькали десятки окон «AutoPrintCode»
            self.sub.hide()
        text.addWidget(self.sub)
        self.controls = QHBoxLayout()
        self.controls.setSpacing(8)
        for c in controls or []:
            self.controls.addWidget(c)
        if stack:
            text.addSpacing(8)
            text.addLayout(self.controls)
            outer.addLayout(text, 1)
        else:
            outer.addLayout(text, 1)
            outer.addLayout(self.controls)
        self.setMinimumHeight(52)

    def set_enabled_look(self, on: bool) -> None:
        for w in (self.title, self.sub):
            w.setEnabled(on)


class Card(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        self.rows: list[QWidget] = []

    def add(self, row: QWidget) -> QWidget:
        row.setProperty("first", not self.rows)
        repolish(row)
        self.rows.append(row)
        self.lay.addWidget(row)
        return row


class Note(QFrame):
    """Пояснение на мягком янтарном фоне со значком."""

    def __init__(self, text: str, icon_name: str = "info", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("note")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)
        lay.addWidget(IconLabel(icon_name, "accent", 18), 0, Qt.AlignmentFlag.AlignTop)
        self.text = label(text, "noteText", wrap=True)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setOpenExternalLinks(True)
        lay.addWidget(self.text, 1)


def page_header(title: str, lede: str) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lay.addWidget(label(title, "pageTitle"))
    lb = label(lede, "lede", wrap=True)
    lay.addWidget(lb)
    return w


def group_title(text: str) -> QLabel:
    lb = label(text, "groupTitle")
    lb.setContentsMargins(2, 18, 0, 6)
    return lb


def spin(lo: int, hi: int, value: int, suffix: str = "", step: int = 1, width: int = 120) -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setValue(value)
    if suffix:
        s.setSuffix(suffix)
    s.setFixedWidth(width)
    s.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return s


def dspin(lo: float, hi: float, value: float, suffix: str = "", step: float = 0.5, width: int = 120) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(1)
    s.setValue(value)
    if suffix:
        s.setSuffix(suffix)
    s.setFixedWidth(width)
    s.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return s


def combo(items: dict, current, width: int = 0) -> QComboBox:
    c = QComboBox()
    for k, v in items.items():
        c.addItem(v, k)
    i = c.findData(current)
    c.setCurrentIndex(max(0, i))
    if width:
        c.setFixedWidth(width)
    return c


# ---------------------------------------------------------------- тост

class Toast(QFrame):
    """Сообщение внизу окна (вместо строки состояния). Исчезает само."""

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.host = host
        self.setObjectName("toast")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 9, 16, 9)
        lay.setSpacing(10)
        self.ic = IconLabel("info", "accent", 16)
        lay.addWidget(self.ic)
        self.text = label("", "toastText")
        self.text.setWordWrap(True)
        lay.addWidget(self.text)
        self.effect = QGraphicsOpacityEffect(self)
        self.effect.setOpacity(0.0)
        self.setGraphicsEffect(self.effect)
        self.anim = QPropertyAnimation(self.effect, b"opacity", self)
        self.anim.setDuration(160)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._fade_out)
        self.anim.finished.connect(self._after_anim)
        host.installEventFilter(self)
        self.hide()

    def show_message(self, text: str, warn: bool = False, ms: int = 4500) -> None:
        self.text.setText(text)
        # ширина — по тексту (до 620 px), иначе перенос слов сжимает тост в узкий столбик
        width = self.text.fontMetrics().horizontalAdvance(text) + 8
        self.text.setFixedWidth(max(120, min(620, width, self.host.width() - 120)))
        self.setProperty("tone", "warn" if warn else "")
        repolish(self)
        self.ic.set_color("live" if warn else "accent")
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        self.anim.stop()
        self.anim.setStartValue(self.effect.opacity())
        self.anim.setEndValue(1.0)
        self.anim.start()
        self.timer.start(ms)

    def _fade_out(self) -> None:
        self.anim.stop()
        self.anim.setStartValue(self.effect.opacity())
        self.anim.setEndValue(0.0)
        self.anim.start()

    def _after_anim(self) -> None:
        if self.effect.opacity() <= 0.01:
            self.hide()

    def _place(self) -> None:
        h = self.host
        self.move(QPoint((h.width() - self.width()) // 2, h.height() - self.height() - 22))

    def eventFilter(self, obj, ev) -> bool:
        if obj is self.host and ev.type() == QEvent.Type.Resize and self.isVisible():
            self._place()
        return False


# ---------------------------------------------------------------- раскладка «с переносом»

class FlowLayout(QLayout):
    """Элементы в строку; если не помещаются — переносятся на следующую (пульт в узком окне)."""

    def __init__(self, parent=None, hspacing: int = 8, vspacing: int = 8) -> None:
        super().__init__(parent)
        self._items = []
        self._h, self._v = hspacing, vspacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    @staticmethod
    def _is_sep(it) -> bool:
        w = it.widget()
        return w is not None and bool(w.property("flowSep"))

    def _do_layout(self, rect: QRect, test: bool) -> int:
        """Разделители (property flowSep) ставятся только между элементами одной строки —
        в начале и в конце строки они не нужны и прячутся."""
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        lines: list[list] = []
        cur: list = []
        x = r.x()
        pending = None
        hidden = []
        for it in self._items:
            w = it.widget()
            if w is not None and w.isHidden():
                continue
            if self._is_sep(it):
                if pending is not None:
                    hidden.append(pending)
                pending = it
                continue
            width = it.sizeHint().width()
            sep_w = pending.sizeHint().width() + self._h if pending is not None and cur else 0
            if cur and x + sep_w + width > r.right() + 1:
                lines.append(cur)
                cur, x = [], r.x()
                if pending is not None:
                    hidden.append(pending)
                    pending = None
                sep_w = 0
            if pending is not None:
                if cur:
                    cur.append(pending)
                    x += sep_w
                else:
                    hidden.append(pending)
                pending = None
            cur.append(it)
            x += width + self._h
        if pending is not None:
            hidden.append(pending)
        if cur:
            lines.append(cur)
        y = r.y()
        for line in lines:
            h = max(it.sizeHint().height() for it in line)
            if not test:
                lx = r.x()
                for it in line:
                    sh = it.sizeHint()
                    it.setGeometry(QRect(QPoint(lx, y + (h - sh.height()) // 2), sh))
                    lx += sh.width() + self._h
            y += h + self._v
        if not test:
            for it in hidden:
                it.setGeometry(QRect(-10000, -10000, 0, 0))
        total = (y - self._v if lines else y) - rect.y() + m.bottom()
        return total


class MenuButton(QToolButton):
    """Кнопка, меню которой строится только по щелчку (fill(menu) — заполнить)."""

    def __init__(self, fill, object_name: str = "pickBtn") -> None:
        super().__init__()
        self._fill = fill
        self.setObjectName(object_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setIconSize(QSize(13, 13))
        self.clicked.connect(self.popup)

    def build_menu(self) -> QMenu:
        m = QMenu(self)
        self._fill(m)
        return m

    def popup(self) -> None:
        m = self.build_menu()
        m.exec(self.mapToGlobal(QPoint(0, self.height())))
        m.deleteLater()
