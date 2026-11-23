"""Окно настроек в стиле PasteTalk: слева разделы, справа карточки со строками.

Изменения применяются и сохраняются сразу (кнопки «ОК» нет): окно меняет общий объект Settings
и сообщает главному окну ключ изменённой настройки сигналом changed.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QKeyCombination, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea,
                               QStackedWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__, updater
from ..hotkeys import parse_hotkey
from ..sounds import DEFAULT_STYLE, available_styles, delete_custom, is_custom, resolve_style
from ..storage import PROFILES, Settings
from ..updater import RELEASES_PAGE
from . import logo
from .ai_settings import build_page as build_ai_page
from .frameless import FramelessWindow
from .theme import THEMES, theme
from .updates import INTERVALS, MODE_NOTIFY, UPDATE_MODES
from .widgets import (Card, IconButton, NavButton, Note, Row, Segmented, Slider, Switch, Toast, accent_button,
                      button, combo, dspin, group_title, label, page_header, repolish, spin)

HOTKEYS = [
    ("hotkey_toggle", "Старт / пауза / продолжить", "command"),
    ("hotkey_restart", "Начать сначала", "restart"),
    ("hotkey_stop", "Остановить", "stop"),
    ("hotkey_next_block", "Следующий блок кода", "arrow-down"),
    ("hotkey_prev_block", "Предыдущий блок кода", "arrow-up"),
    ("hotkey_next_tab", "Следующий урок", "file-code"),
    ("hotkey_step_back", "Шаг назад без печати (режим «По шагам»)", "layers"),
]

PAGES = [
    ("print", "keyboard", "Печать"),
    ("human", "hand", "Как человек"),
    ("sound", "music", "Звук"),
    ("hotkeys", "command", "Горячие клавиши"),
    ("behavior", "sliders", "Поведение"),
    ("look", "contrast", "Вид"),
    ("ai", "sparkles", "Нейросеть"),
    ("updates", "refresh", "Обновления"),
    ("about", "info", "О программе"),
]

_MODIFIER_KEYS = {Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta, Qt.Key.Key_AltGr}


class HotkeyField(QPushButton):
    """Поле хоткея: щелчок — запись сочетания, Esc — отмена, Backspace — без хоткея."""
    edited = Signal(str)
    capture = Signal(bool)   # запись началась / закончилась (на это время глобальные хоткеи снимаются)

    def __init__(self, value: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("combo")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.value = value
        self.capturing = False
        self.clicked.connect(self._start)
        self._show()

    def _show(self) -> None:
        self.setText(self.value or "—")

    def set_value(self, value: str) -> None:
        self.value = value
        self.set_clash(False)
        self._show()

    def set_clash(self, on: bool) -> None:
        self.setProperty("clash", on)
        repolish(self)

    def _set_capturing(self, on: bool) -> None:
        if self.capturing == on:
            return
        self.capturing = on
        self.setProperty("capturing", on)
        repolish(self)
        if on:
            self.setText("Нажмите сочетание…")
            self.grabKeyboard()
        else:
            self.releaseKeyboard()
            self._show()
        self.capture.emit(on)

    def _start(self) -> None:
        self.set_clash(False)
        self._set_capturing(not self.capturing)

    def cancel(self) -> None:
        self._set_capturing(False)

    def keyPressEvent(self, e) -> None:
        if not self.capturing:
            super().keyPressEvent(e)
            return
        key = Qt.Key(e.key())
        mods = e.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        if key == Qt.Key.Key_Escape and not mods:
            self._set_capturing(False)
            return
        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete) and not mods:
            self._set_capturing(False)
            self.edited.emit("")
            return
        if key in _MODIFIER_KEYS:   # пока зажат только модификатор — подсказка «Ctrl+…»
            names = [n for flag, n in ((Qt.KeyboardModifier.ControlModifier, "Ctrl"),
                                       (Qt.KeyboardModifier.AltModifier, "Alt"),
                                       (Qt.KeyboardModifier.ShiftModifier, "Shift"),
                                       (Qt.KeyboardModifier.MetaModifier, "Win")) if mods & flag]
            self.setText("+".join(names + ["…"]))
            return
        text = QKeySequence(QKeyCombination(mods, key)).toString(QKeySequence.SequenceFormat.PortableText)
        self._set_capturing(False)
        if parse_hotkey(text) is None:
            self.setText(f"{text} — не подходит")
            self.set_clash(True)
            return
        # хоткей глобальный: просто буква, пробел, Enter или Tab перестали бы печататься во всех программах
        # (а Enter нужен и самой печати по строкам). Без Ctrl/Alt/Win — только F1…F24, Pause, Scroll Lock
        strong = mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
                         | Qt.KeyboardModifier.MetaModifier)
        solo = int(Qt.Key.Key_F1) <= int(key) <= int(Qt.Key.Key_F24) or key in (Qt.Key.Key_Pause,
                                                                                Qt.Key.Key_ScrollLock)
        if not strong and not solo:
            self.setText(f"{text} — нужен Ctrl, Alt или Win")
            self.set_clash(True)
            return
        self.edited.emit(text)

    def focusOutEvent(self, e) -> None:
        super().focusOutEvent(e)
        self._set_capturing(False)


class SettingsWindow(FramelessWindow):
    changed = Signal(str)            # ключ изменённой настройки (или группа: "hotkeys")
    test_sound = Signal(str, int)    # (стиль, громкость)
    check_updates = Signal()
    open_log = Signal()
    open_data = Signal()
    hotkey_capture = Signal(bool)
    restart_requested = Signal()     # перезапустить программу (новый размер интерфейса)
    report_requested = Signal()      # «Сообщить об ошибке»

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(f"{APP_NAME} — Настройки", minimize=True, maximize=True, parent=parent)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.s = settings
        self._loaders: list = []
        self.resize(1040, 720)
        self.setMinimumSize(820, 540)
        self.logo_lbl = QLabel()
        self.logo_lbl.setFixedSize(18, 18)
        self.logo_lbl.setProperty("drag", True)
        self.titlebar.left.addWidget(self.logo_lbl)

        root = QHBoxLayout(self.body)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.body.setObjectName("settingsRoot")
        self.body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        nav = QWidget()
        nav.setObjectName("navPanel")
        nav.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        nav.setFixedWidth(230)
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(8, 12, 8, 12)
        nl.setSpacing(2)
        self.stack = QStackedWidget()
        self.nav: dict[str, NavButton] = {}
        builders = {"print": self._page_print, "human": self._page_human, "sound": self._page_sound,
                    "hotkeys": self._page_hotkeys, "behavior": self._page_behavior, "look": self._page_look,
                    "ai": lambda: build_ai_page(self), "updates": self._page_updates,
                    "about": self._page_about}
        for i, (key, ic, title) in enumerate(PAGES):
            if key == "updates":
                sep = QWidget()
                sep.setObjectName("navSep")
                sep.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                nl.addSpacing(6)
                nl.addWidget(sep)
                nl.addSpacing(6)
            b = NavButton(ic, title)
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self.nav[key] = b
            nl.addWidget(b)
            self.stack.addWidget(builders[key]())
        nl.addStretch(1)
        root.addWidget(nav)
        root.addWidget(self.stack, 1)
        self.toast = Toast(self.stack)
        self._refresh_logo()
        theme.changed.connect(self._refresh_logo)
        # Esc: во время записи хоткея — отмена записи, иначе — закрыть окно
        QShortcut(QKeySequence("Esc"), self, self._on_escape)
        self.reload()
        self.show_page("print")

    def _on_escape(self) -> None:
        for f in self.hk_fields.values():
            if f.capturing:
                f.cancel()
                return
        self.close()

    # ------------------------------------------------------------ навигация
    def show_page(self, key: str) -> None:
        keys = [k for k, _i, _t in PAGES]
        if key not in keys:
            key = "print"
        for k, b in self.nav.items():
            b.setChecked(k == key)
        self.stack.setCurrentIndex(keys.index(key))
        if key == "about":
            self._refresh_help()
        if key == "updates":
            self.refresh_update_info()

    def _refresh_logo(self) -> None:
        self.logo_lbl.setPixmap(logo.pixmap(logo.IDLE, 18, theme.c("accent"), self.devicePixelRatioF() or 1.0))
        if hasattr(self, "src_link"):
            self.src_link.setText(self._link_html())
        self.restyle_frame()

    @staticmethod
    def _link_html() -> str:
        return f'<a href="{RELEASES_PAGE}" style="color:{theme.c("accent").name()}">Выпуски на GitHub</a>'

    def reload(self) -> None:
        """Перечитать значения из Settings (их могли поменять в главном окне)."""
        for load in self._loaders:
            load()

    # ------------------------------------------------------------ каркас страницы
    def _page(self, title: str, lede: str) -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        page.setObjectName("page")
        outer = QHBoxLayout(page)
        outer.setContentsMargins(32, 26, 32, 40)
        col = QWidget()
        col.setMaximumWidth(780)
        lay = QVBoxLayout(col)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(page_header(title, lede))
        outer.addStretch(0)
        outer.addWidget(col, 1)
        outer.addStretch(0)
        scroll.setWidget(page)
        return scroll, lay

    @staticmethod
    def _finish(lay: QVBoxLayout) -> None:
        lay.addStretch(1)

    # ------------------------------------------------------------ привязка элементов к настройкам
    def _set(self, key: str, value) -> None:
        if getattr(self.s, key) != value:
            setattr(self.s, key, value)
            self.changed.emit(key)

    def _switch(self, key: str) -> Switch:
        w = Switch()
        w.toggled.connect(lambda on: self._set(key, on))
        self._loaders.append(lambda: _quiet(w, lambda: w.setChecked(getattr(self.s, key))))
        return w

    def _spin(self, key: str, lo: int, hi: int, suffix: str = "", step: int = 1, width: int = 130):
        w = spin(lo, hi, getattr(self.s, key), suffix, step, width)
        w.valueChanged.connect(lambda v: self._set(key, int(v)))
        self._loaders.append(lambda: _quiet(w, lambda: w.setValue(getattr(self.s, key))))
        return w

    def _dspin(self, key: str, lo: float, hi: float, suffix: str = "", step: float = 0.5, width: int = 130):
        w = dspin(lo, hi, getattr(self.s, key), suffix, step, width)
        w.valueChanged.connect(lambda v: self._set(key, float(v)))
        self._loaders.append(lambda: _quiet(w, lambda: w.setValue(getattr(self.s, key))))
        return w

    def _combo(self, key: str, items: dict, width: int = 0, other=None):
        """other(значение) → подпись для значения из settings.json, которого нет в списке: его не теряем."""
        w = combo(items, getattr(self.s, key), width)

        def load() -> None:
            v = getattr(self.s, key)
            if other is not None and w.findData(v) < 0:
                w.addItem(other(v), v)
            w.setCurrentIndex(max(0, w.findData(v)))
        _quiet(w, load)
        w.currentIndexChanged.connect(lambda _i: self._set(key, w.currentData()))
        self._loaders.append(lambda: _quiet(w, load))
        return w

    # ------------------------------------------------------------ страницы
    def _page_print(self) -> QWidget:
        page, lay = self._page("Печать", "Режим, темп набора и то, как текст попадает в редактор.")
        lay.addWidget(group_title("Режим печати"))
        c = Card()
        mode = Segmented([("block", "Целиком"), ("lines", "По строкам"), ("steps", "По шагам")])
        mode.changed.connect(lambda k: self._set("print_mode", k))
        self._loaders.append(lambda: mode.set_value(self.s.print_mode))
        c.add(Row("layers", "Как печатать блок кода", "Целиком — за раз · По строкам — строка, затем ваш Enter — "
                  "следующая · По шагам — урок частями, с возвратом наверх. Есть и в «Печать ⚙» на экране урока",
                  [mode]))
        c.add(Row("next", "Шаги: к месту вставки", "Стрелками от курсора — код может продолжать уже написанный "
                  "в файле, но между шагами курсор не трогать. От начала документа — переживает щелчки, "
                  "но код должен начинаться с первой строки файла",
                  [self._combo("step_nav", {"arrows": "Стрелками от курсора", "home": "От начала документа"},
                               230)]))
        lay.addWidget(c)
        lay.addSpacing(12)
        lay.addWidget(Note(
            "<b>Печатается только код.</b> Заметки, картинки и этапы урока — подсказки вам, они не печатаются. "
            "<b>По шагам:</b> на экране урока в «Подготовке» слева от номеров строк кода — номер шага; выделите "
            "строки и нажмите <b>Alt+1…9</b> (Alt+0 — новый шаг). Хоткей старта печатает следующий шаг; программа "
            "сама ведёт курсор к месту вставки — как, задаёт строка «Шаги: к месту вставки» выше. Перенос длинных "
            "строк в редакторе должен быть выключен.",
            "help"))
        lay.addWidget(group_title("Темп"))
        c = Card()
        c.add(Row("gauge", "Скорость", "Знаков в минуту. Ползунок — и в «Печать ⚙» на экране урока",
                  [self._spin("cpm", 30, 3000, " зн/мин", 10)]))
        c.add(Row("activity", "Разброс темпа", "Насколько неровно идут нажатия. 0 — ровно, как метроном",
                  [self._spin("jitter", 0, 90, " %")]))
        c.add(Row("enter", "Пауза после Enter", "Добавляется к обычной задержке между нажатиями",
                  [self._spin("newline_pause_ms", 0, 3000, " мс", 10)]))
        c.add(Row("type", "Пауза после знаков", "После , ; : ) ] } >",
                  [self._spin("punct_pause_ms", 0, 1000, " мс", 10)]))
        lay.addWidget(c)

        lay.addWidget(group_title("Отступы и выделение"))
        c = Card()
        c.add(Row("zap", "Отступы печатать быстро", "Пробелы в начале строки идут быстрой очередью",
                  [self._switch("fast_indent")]))
        c.add(Row("indent", "Отступы клавишей Tab", "Одно нажатие на каждый уровень, как программист. "
                  "Не для простых полей в браузере: там Tab переводит фокус", [self._switch("indent_with_tab")]))
        c.add(Row("space", "Таб в коде", "Сколько пробелов считать одним уровнем отступа",
                  [self._spin("tab_width", 1, 8, " пробела")]))
        c.add(Row("select", "Выделение до целых строк", "Если выделить часть строки, напечатается вся строка",
                  [self._switch("selection_whole_lines")]))
        c.add(Row("comment-off", "Не печатать комментарии", "Строки-комментарии пропускаются, хвостовые "
                  "отрезаются — их читают вслух (экран урока показывает «Скажи: …»). Сам урок не меняется",
                  [self._switch("strip_comments")]))
        lay.addWidget(c)

        lay.addWidget(group_title("Целевое окно"))
        c = Card()
        c.add(Row("monitor", "Профиль окна", "IDE убирает автоскобки и автоотступы редактора; "
                  "Блокнот — печать как есть", [self._combo("profile", PROFILES, 250)]))
        c.add(Row("escape", "Esc перед Enter", "Закрывает подсказки автодополнения. Не включайте для Jupyter",
                  [self._switch("esc_before_enter")]))
        c.add(Row("timer", "Мин. интервал нажатий", "Если в редакторе пропадают или переставляются символы — "
                  "увеличьте", [self._spin("key_gap_ms", 5, 200, " мс", 5)]))
        lay.addWidget(c)
        self._finish(lay)
        return page

    def _page_human(self) -> QWidget:
        page, lay = self._page("Как человек", "Живой ритм, паузы на обдумывание и опечатки, которые тут же "
                                              "исправляются. Итоговый текст всегда совпадает с исходным кодом.")
        lay.addWidget(group_title("Имитация ручного ввода"))
        c = Card()
        sw = self._switch("human_typing")
        c.add(Row("hand", "Печатать как человек", "То же, что «Как человек» в «Печать ⚙» на экране урока", [sw]))
        typos = Row("spell", "Опечатки", "В среднем на 100 символов текста, случайно. 0 — без опечаток",
                    [self._dspin("typos_per_100", 0, 10, " на 100 симв.", 0.5, 170)])
        think = Row("hourglass", "Обдумывание строки", "Пауза перед новой строкой; перед новым куском кода — "
                    "дольше", [self._dspin("think_pause_s", 0, 10, " с", 0.5)])
        c.add(typos)
        c.add(think)
        lay.addWidget(c)

        def deps() -> None:
            on = self.s.human_typing
            for r in (typos, think):
                r.setEnabled(on)
        sw.toggled.connect(lambda _: deps())
        self._loaders.append(deps)
        lay.addSpacing(16)
        lay.addWidget(Note(
            "<b>Как набирает человек.</b> Знакомые слова (print, return, self) идут быстрой очередью, первая "
            "буква слова, заглавные и символы с Shift — медленнее, темп плавно «гуляет». Перед новой строкой — "
            "пауза, перед новым куском кода — дольше.<br><b>Опечатки</b> случайны, в среднем столько, сколько "
            "задано на 100 символов: соседняя клавиша, переставленные буквы, двойное нажатие, пропущенная "
            "буква, промах с Shift, лишняя клавиша. Ошибку «замечают» через 0–3 буквы, стирают Backspace "
            "(иногда на букву больше) и набирают верно. Опечатки бывают только внутри слов — скобки, "
            "кавычки, отступы и Enter не задеваются, итог всегда совпадает с исходным кодом. Из-за пауз набор идёт "
            "медленнее заданной скорости."))
        self._finish(lay)
        return page

    def _page_sound(self) -> QWidget:
        page, lay = self._page("Звук", "Звук настоящей клавиатуры во время печати.")
        lay.addWidget(group_title("Клавиатура"))
        c = Card()
        c.add(Row("volume", "Звук клавиш", "Если звук пишется отдельно, его можно выключить",
                  [self._switch("sound_enabled")]))
        # список звуков меняется (свои записи) — заполняется заново, а не один раз
        self.style_combo = QComboBox()
        self.style_combo.setFixedWidth(320)
        self.style_combo.currentIndexChanged.connect(self._on_style_combo)
        self._loaders.append(self._fill_styles)
        listen = button("Послушать", "play")
        listen.clicked.connect(lambda: self.test_sound.emit(self.s.sound_style, self.s.sound_volume))
        c.add(Row("keyboard", "Какая клавиатура", "Записи настоящих клавиатур (CC0) и ваши собственные",
                  [self.style_combo, listen]))
        rec = accent_button("Записать звук клавиатуры…", "mic")
        rec.clicked.connect(self._record_sound)
        self.del_sound = button("Удалить свой звук", "trash")
        self.del_sound.clicked.connect(self._delete_sound)
        c.add(Row("mic", "Своя клавиатура", "Запишите микрофоном любую клавиатуру: несколько нажатий обычных "
                  "клавиш, пробела и Enter — и программа будет звучать как она", [self.del_sound, rec]))
        vol = Slider(0, 100)
        vol.setFixedWidth(190)
        val = label("", "mono")
        val.setFixedWidth(44)

        def on_vol(v: int) -> None:
            val.setText(f"{v} %")
            self._set("sound_volume", int(v))
        vol.valueChanged.connect(on_vol)
        vol.sliderReleased.connect(lambda: self.test_sound.emit(self.s.sound_style, self.s.sound_volume))

        def load_vol() -> None:
            _quiet(vol, lambda: vol.setValue(self.s.sound_volume))
            val.setText(f"{self.s.sound_volume} %")
        self._loaders.append(load_vol)
        c.add(Row("music", "Громкость", "Отдельно от общей громкости Windows", [vol, val]))
        lay.addWidget(c)
        self._finish(lay)
        return page

    def _on_style_combo(self, _i: int) -> None:
        key = self.style_combo.currentData() or DEFAULT_STYLE
        self._set("sound_style", key)
        self.del_sound.setVisible(is_custom(key))

    def _fill_styles(self) -> None:
        c = self.style_combo
        c.blockSignals(True)
        c.clear()
        for k, v in available_styles().items():
            c.addItem(v, k)
        c.setCurrentIndex(max(0, c.findData(resolve_style(self.s.sound_style))))
        c.blockSignals(False)
        self.del_sound.setVisible(is_custom(self.s.sound_style))

    def _record_sound(self) -> None:
        from .record_dialog import RecordDialog
        self.hotkey_capture.emit(True)    # пока пишем звук — глобальные хоткеи не перехватывают клавиши
        try:
            d = RecordDialog(self, volume=max(40, self.s.sound_volume))
            d.exec()
            key = d.style_key
        finally:
            self.hotkey_capture.emit(False)
        if key:
            self._set("sound_style", key)
            self._fill_styles()
            self.toast.show_message("Свой звук сохранён и выбран. «Послушать» — как он звучит при печати.")

    def _delete_sound(self) -> None:
        key = self.s.sound_style
        if not is_custom(key):
            return
        name = available_styles().get(key, key)
        if QMessageBox.question(self, "Удалить звук", f"Удалить «{name}»?") != QMessageBox.StandardButton.Yes:
            return
        self._set("sound_style", DEFAULT_STYLE)   # сначала переключить: файлы набора освободятся
        delete_custom(key)
        self._fill_styles()

    def _page_hotkeys(self) -> QWidget:
        page, lay = self._page("Горячие клавиши", "Работают в любом окне и до самого окна не доходят. "
                                                  "Щёлкните по полю и нажмите сочетание.")
        lay.addWidget(group_title("Печать"))
        c = Card()
        self.hk_fields: dict[str, HotkeyField] = {}
        for key, title, ic in HOTKEYS:
            f = HotkeyField(getattr(self.s, key))
            f.edited.connect(lambda v, k=key: self._on_hotkey(k, v))
            f.capture.connect(self.hotkey_capture)
            if key == "hotkey_toggle":   # без этого хоткея не обойтись — кнопки «очистить» нет
                clear = QWidget()
                clear.setFixedSize(30, 30)
            else:
                clear = IconButton("x", "Без хоткея", 14, box=30)
                clear.clicked.connect(lambda _=False, k=key: self._on_hotkey(k, ""))
            self.hk_fields[key] = f
            c.add(Row(ic, title, "", [f, clear]))
            self._loaders.append(lambda k=key, f=f: f.set_value(getattr(self.s, k)))
        lay.addWidget(c)
        lay.addSpacing(16)
        lay.addWidget(Note("Удобны F-клавиши с Ctrl или Shift: они редко заняты в редакторах. Пока поле ждёт "
                           "сочетание, глобальные хоткеи отключены. Esc — отмена, Backspace — без хоткея."))
        self._finish(lay)
        return page

    def _on_hotkey(self, key: str, value: str) -> None:
        f = self.hk_fields[key]
        if key == "hotkey_toggle" and not value:
            f.set_value(self.s.hotkey_toggle)
            self.toast.show_message("Хоткей «Старт / пауза» нужен всегда.", warn=True)
            return
        if value:
            wanted = parse_hotkey(value)   # сравниваем клавиши, а не текст: «Ctrl++» и «Ctrl+=» — одно и то же
            for k, title, _ic in HOTKEYS:
                if k != key and parse_hotkey(getattr(self.s, k)) == wanted:
                    f.setText(value)
                    f.set_clash(True)
                    self.toast.show_message(f"«{value}» уже назначен: «{title}».", warn=True)
                    return
        f.set_value(value)
        if getattr(self.s, key) != value:
            setattr(self.s, key, value)
            self.changed.emit("hotkeys")

    def _page_behavior(self) -> QWidget:
        page, lay = self._page("Поведение", "Как начинается печать и что её останавливает.")
        lay.addWidget(group_title("Старт"))
        c = Card()
        c.add(Row("timer", "Задержка старта по хоткею", "Чтобы успеть отпустить клавиши",
                  [self._spin("hotkey_start_delay_ms", 0, 3000, " мс", 50)]))
        c.add(Row("clock", "Отсчёт при старте из меню трея", "Время, чтобы поставить курсор в нужное окно",
                  [self._spin("button_countdown_s", 0, 10, " с")]))
        lay.addWidget(c)
        lay.addWidget(group_title("Защита во время печати"))
        c = Card()
        c.add(Row("monitor", "Пауза, если сменилось активное окно", "Текст не уйдёт не туда",
                  [self._switch("autopause_on_focus_change")]))
        c.add(Row("shield", "Пауза при нажатии клавиши или клике", "Случайная клавиша не попадёт в код. "
                  "Что именно нажато, не записывается", [self._switch("guard_enabled")]))
        lay.addWidget(c)
        lay.addWidget(group_title("Окно"))
        c = Card()
        c.add(Row("layers", "Окно поверх остальных", "AutoPrintCode не прячется за редактором",
                  [self._switch("always_on_top")]))
        lay.addWidget(c)
        lay.addWidget(group_title("Трей и запуск"))
        c = Card()
        c.add(Row("minimize", "Сворачивать в трей при закрытии", "Крестик прячет окно, хоткеи продолжают "
                  "работать. Выход — из меню логотипа или значка в трее", [self._switch("close_to_tray")]))
        c.add(Row("pin", "Значок всегда виден у часов", "Не прячется в «скрытые значки» (стрелка ^) — "
                  "как у Telegram. Значок меняется: готов · печатает · пауза", [self._switch("pin_tray_icon")]))
        c.add(Row("power", "Запускать вместе с Windows", "Сразу в трей, без окна",
                  [self._switch("autostart")]))
        lay.addWidget(c)
        self._finish(lay)
        return page

    def _page_look(self) -> QWidget:
        page, lay = self._page("Вид", "Оформление программы.")
        lay.addWidget(group_title("Тема"))
        c = Card()
        seg = Segmented(list(THEMES.items()))
        seg.changed.connect(lambda k: self._set("theme", k))
        self._loaders.append(lambda: seg.set_value(self.s.theme))
        c.add(Row("contrast", "Тема оформления", "«Как в Windows» следует за светлой или тёмной темой системы",
                  [seg]))
        lay.addWidget(c)

        lay.addWidget(group_title("Размер"))
        c = Card()
        scale = Segmented([(100, "100 %"), (125, "125 %"), (150, "150 %"), (175, "175 %")])
        restart = button("Перезапустить сейчас", "refresh")
        restart.setVisible(False)
        restart.clicked.connect(self.restart_requested)
        self._scale_at_start = self.s.ui_scale

        def on_scale(v) -> None:
            self._set("ui_scale", int(v))
            restart.setVisible(int(v) != self._scale_at_start)
        scale.changed.connect(on_scale)
        self._loaders.append(lambda: scale.set_value(self.s.ui_scale))
        c.add(Row("zoom", "Размер интерфейса", "Крупнее — всё окно целиком: текст, кнопки, значки. Применится "
                  "после перезапуска программы", [scale, restart]))
        c.add(Row("code", "Размер кода в блоке", "Ctrl или Shift + колёсико мыши над блоком — крупнее/мельче, "
                  "Ctrl+0 — обычный размер, Ctrl+Shift+0 — все блоки занятия", []))
        lay.addWidget(c)
        self._finish(lay)
        return page

    def _page_updates(self) -> QWidget:
        page, lay = self._page("Обновления", "Новые версии программы с GitHub. Занятия и настройки при "
                                             "обновлении не меняются.")
        lay.addWidget(group_title("Проверка"))
        c = Card()
        auto = self._switch("update_auto_check")
        c.add(Row("refresh", "Проверять автоматически", "Во время печати программа не обновляется и "
                  "не отвлекает уведомлениями", [auto]))
        interval = Row("clock", "Как часто", "", [self._combo("update_interval_h", INTERVALS, 220, other=lambda h: f"Каждые {h} ч")])
        # сборка, которая не может заменить свои файлы (нет _internal, папка без права записи), — только сообщает
        modes = UPDATE_MODES if updater.can_self_update() else {MODE_NOTIFY: UPDATE_MODES[MODE_NOTIFY]}
        mode = Row("bell", "Найдя новую версию", "", [self._combo("update_mode", modes, 300)])
        c.add(interval)
        c.add(mode)
        c.add(Row("flask", "Бета-версии", "Предлагать предварительные выпуски (pre-release)",
                  [self._switch("update_prerelease")]))
        lay.addWidget(c)

        def deps() -> None:
            for r in (interval, mode):
                r.setEnabled(self.s.update_auto_check)
        auto.toggled.connect(lambda _: deps())
        self._loaders.append(deps)

        lay.addWidget(group_title("Версия"))
        c = Card()
        check = accent_button("Проверить сейчас", "refresh")
        check.clicked.connect(self.check_updates)
        self.upd_row = Row("upgrade", "", "", [check])
        c.add(self.upd_row)
        self.unskip_btn = button("Снова предлагать")
        self.unskip_btn.clicked.connect(self._unskip)
        self.skip_row = Row("x", "Пропущенная версия", "", [self.unskip_btn])
        c.add(self.skip_row)
        lay.addWidget(c)
        self._finish(lay)
        return page

    def refresh_update_info(self) -> None:
        last = (time.strftime("%d.%m.%Y %H:%M", time.localtime(self.s.update_last_check))
                if self.s.update_last_check else "ещё не было")
        self.upd_row.title.setText(f"Установлена версия {__version__}")
        self.upd_row.sub.setText(f"Последняя проверка: {last}")
        self.upd_row.sub.show()
        skip = self.s.update_skip_version
        self.skip_row.setVisible(bool(skip))
        if skip:
            self.skip_row.sub.setText(f"Версия {skip} не предлагается")
            self.skip_row.sub.show()

    def _unskip(self) -> None:
        self._set("update_skip_version", "")
        self.refresh_update_info()

    def _page_about(self) -> QWidget:
        page, lay = self._page(APP_NAME, "Агент для живых демонстраций кода: печатает заготовленный код "
                                         "в любое окно без ошибок и в заданном темпе.")
        lay.addSpacing(18)
        head = QHBoxLayout()
        head.setSpacing(16)
        self.about_logo = QLabel()
        self.about_logo.setFixedSize(64, 64)
        self.about_logo.setPixmap(logo.pixmap(logo.APP, 64, dpr=self.devicePixelRatioF() or 1.0))
        head.addWidget(self.about_logo)
        info = QVBoxLayout()
        info.setSpacing(4)
        info.addStretch(1)
        info.addWidget(label(f"Версия {__version__}", "rowTitle"))
        info.addWidget(label("Занятия и настройки хранятся в папке data рядом с программой.", "rowSub"))
        info.addStretch(1)
        head.addLayout(info, 1)
        lay.addLayout(head)
        lay.addSpacing(16)
        row = QHBoxLayout()
        row.setSpacing(8)
        b = accent_button("Проверить обновления", "refresh")
        b.clicked.connect(self.check_updates)
        row.addWidget(b)
        b = button("Журнал работы", "file-text")
        b.clicked.connect(self.open_log)
        row.addWidget(b)
        b = button("Папка с данными", "folder")
        b.clicked.connect(self.open_data)
        row.addWidget(b)
        b = button("Сообщить об ошибке", "bug")
        b.clicked.connect(self.report_requested)
        row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(group_title("Как пользоваться"))
        self.help_note = Note("", "help")
        lay.addWidget(self.help_note)
        lay.addSpacing(12)
        self.src_link = label(self._link_html(), "dim")
        self.src_link.setOpenExternalLinks(True)
        lay.addWidget(self.src_link)
        self._finish(lay)
        return page

    def _refresh_help(self) -> None:
        s = self.s
        self.help_note.text.setText(
            "1. Выберите урок в списке и нажмите <b>Открыть урок</b> (или <b>Новый урок</b>, <b>Импорт</b>, "
            "<b>Из методички</b>). Урок открывается на экране урока: в «Подготовке» его правят на месте, "
            "в «Уроке» ведут по времени этапов.<br>"
            "2. Печатается только код. Тот, что пойдёт следующим, отмечен «▶ Следующим»; другой — кнопка "
            "«Следующим» у блока. Нужны только некоторые строки — выделите их в «Подготовке».<br>"
            "3. Поставьте курсор в окне, куда печатать: Jupyter, VS Code, Блокнот.<br>"
            f"4. Нажмите <b>{s.hotkey_toggle}</b> — начнётся набор. Ещё раз — пауза, ещё раз — продолжение. "
            "Напечатали — следующим встаёт следующий код урока.<br><br>"
            f"<b>{s.hotkey_restart or '—'}</b> — этот код ещё раз · <b>{s.hotkey_stop or '—'}</b> — стоп · "
            f"<b>{s.hotkey_next_block or '—'}</b> / <b>{s.hotkey_prev_block or '—'}</b> — следующий / "
            "предыдущий код. Если во время печати сменилось окно, вы нажали клавишу или щёлкнули мышью "
            "вне программы — печать встанет на паузу.")


def _quiet(w: QWidget, fn) -> None:
    """Выполнить fn, не вызывая сигналов виджета (загрузка значения, а не правка пользователем)."""
    w.blockSignals(True)
    try:
        fn()
    finally:
        w.blockSignals(False)
