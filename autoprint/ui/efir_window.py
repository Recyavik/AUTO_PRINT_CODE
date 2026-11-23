"""Окно «Эфир»: расписания вебинаров (запустить, изменить, импорт/экспорт, нейросеть) и оформления экрана эфира
(фон, зарядки, экран перерыва) — две вкладки. Расписание ссылается на оформление; урок выбирает своё."""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QByteArray, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox,
                               QScrollArea,
                               QToolButton, QVBoxLayout, QWidget)

from ..efir.model import ANIMATION_NAMES, Look, Webinar, ai_prompt, export_json, fmt_minutes, parse_webinars
from . import icons
from .frameless import FramelessWindow
from .theme import theme
from .widgets import IconButton, Note, Segmented, Toast, accent_button, button, label


def bg_title(spec: str) -> str:
    if not spec:
        return "как основной фон"
    kind, _, value = spec.partition(":")
    if kind == "anim":
        return ANIMATION_NAMES.get(value, value)
    if kind == "image":
        return f"картинка «{Path(value).name}»"
    if kind == "color":
        return "чёрный" if value.lower() == "#000000" else f"цвет {value}"
    return spec


class WebinarCard(QFrame):
    def __init__(self, win: "EfirWindow", w: Webinar, live: bool) -> None:
        super().__init__()
        self.setObjectName("card")
        self.win, self.w = win, w
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 12, 12)
        lay.setSpacing(12)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("radio", theme.c("ok" if live else "accent"), 22))
        ic.setFixedSize(26, 26)
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(3)
        title = label(w.title + ("   ● идёт эфир" if live else ""), "rowTitle")
        title.setStyleSheet("font-size: 15px; font-weight: 600;" + (f"color: {theme.css('ok')};" if live else ""))
        text.addWidget(title)
        look = win.ctl.store.look(w.look_id)
        meta = (f"{fmt_minutes(w.total_min)} · блоков: {len(w.schedule)} · перерыв {w.break_min} мин · "
                f"оформление: {look.title if look else 'нет'}")
        m = label(meta, "rowSub", wrap=True)
        text.addWidget(m)
        names = " → ".join(a.name for a in w.schedule[:8]) + (" → …" if len(w.schedule) > 8 else "")
        sub = label(names, "dim", wrap=True)
        sub.setStyleSheet("font-size: 12px;")
        text.addWidget(sub)
        lay.addLayout(text, 1)
        go = accent_button(" Запустить" if not live else " Открыть таймер", "play")
        go.setFixedHeight(34)
        go.clicked.connect(lambda: win.ctl.launch(w.id) if live else win.ask_launch(w, go))
        edit = IconButton("pencil", "Изменить шаблон", 16, box=34, framed=True)
        edit.clicked.connect(lambda: win.ctl.edit(w.id))
        more = IconButton("more", "Ещё", 16, box=34, framed=True)
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        menu = QMenu(more)
        menu.addAction(icons.icon("copy"), "Сделать копию", lambda: win.duplicate(w.id))
        menu.addAction(icons.icon("export"), "Экспорт в JSON…", lambda: win.export(w.id))
        menu.addAction(icons.icon("sparkles"), "Скопировать для нейросети (с этим примером)",
                       lambda: win.copy_ai(w.id))
        menu.addSeparator()
        menu.addAction(icons.icon("arrow-up"), "Выше", lambda: win.move(w.id, -1))
        menu.addAction(icons.icon("arrow-down"), "Ниже", lambda: win.move(w.id, +1))
        menu.addSeparator()
        menu.addAction(icons.icon("trash"), "Удалить…", lambda: win.remove(w.id))
        more.setMenu(menu)
        for b in (go, edit, more):
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)


class LookCard(QFrame):
    """Оформление экрана эфира: фон, зарядки, экран перерыва; какие расписания его используют."""

    def __init__(self, win: "EfirWindow", lk: Look) -> None:
        super().__init__()
        self.setObjectName("card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 12, 12)
        lay.setSpacing(12)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("palette", theme.c("accent"), 22))
        ic.setFixedSize(26, 26)
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(3)
        title = label(lk.title, "rowTitle")
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        text.addWidget(title)
        ex = len(lk.exercises)
        brk = ("надпись «" + lk.break_title + "»" if lk.break_show_title else "без надписи") + \
              (", отсчёт" if lk.break_countdown else "")
        text.addWidget(label(f"фон: {bg_title(lk.background)} · зарядок: {ex if ex else 'нет'} · перерыв: {brk}",
                             "rowSub", wrap=True))
        users = win.ctl.store.users_of(lk.id)
        sub = label(("Расписания: " + ", ".join(w.title for w in users)) if users else "Не используется расписаниями",
                    "dim", wrap=True)
        sub.setStyleSheet("font-size: 12px;")
        text.addWidget(sub)
        lay.addLayout(text, 1)
        edit = accent_button(" Изменить", "pencil")
        edit.setFixedHeight(34)
        edit.clicked.connect(lambda: win.ctl.edit_look(lk.id))
        more = IconButton("more", "Ещё", 16, box=34, framed=True)
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        menu = QMenu(more)
        menu.addAction(icons.icon("copy"), "Сделать копию", lambda: win.duplicate_look(lk.id))
        menu.addSeparator()
        menu.addAction(icons.icon("trash"), "Удалить…", lambda: win.remove_look(lk.id))
        more.setMenu(menu)
        for b in (edit, more):
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)


AI_SYSTEM = ("Ты помогаешь преподавателю составить расписание вебинара для программы AutoPrintCode. "
             "Отвечай только JSON в указанном формате, без пояснений.")


class EfirWindow(FramelessWindow):
    _ai_done = Signal(str, str)      # ответ нейросети, ошибка (из потока)

    def __init__(self, ctl, parent=None) -> None:
        super().__init__("Эфир", minimize=False, maximize=True, parent=parent)
        self.ctl = ctl
        self.settings = ctl.settings
        self.setObjectName("efirWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(560, 420)
        self.resize(820, 640)
        tb = self.titlebar
        ic = QLabel()
        ic.setPixmap(icons.pixmap("radio", theme.c("accent"), 18))
        tb.left.addWidget(ic)

        root = QVBoxLayout(self.body)
        root.setContentsMargins(22, 14, 22, 14)
        root.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(8)
        tl = QVBoxLayout()
        tl.setSpacing(2)
        tl.addWidget(label("Эфир", "pageTitle"))
        self.lede = label("", "lede", wrap=True)
        tl.addWidget(self.lede)
        head.addLayout(tl, 1)
        self.btn_new = accent_button(" Новый", "plus")
        self.btn_new.clicked.connect(lambda: self.ctl.edit_look(None) if self.tab() == "looks" else self.ctl.edit(None))
        self.btn_import = button(" Импорт", "import")
        imp = QMenu(self.btn_import)
        imp.addAction(icons.icon("file-text"), "Из файла JSON…", self.import_file)
        imp.addAction(icons.icon("copy"), "Из буфера обмена (JSON или ответ нейросети)", self.import_clipboard)
        imp.addAction(icons.icon("radio"), "Из «Таймера вебинара»", lambda: self.ctl.import_legacy())
        self.btn_import.setMenu(imp)
        self.btn_ai = button(" Нейросеть", "sparkles")
        self.btn_ai.setToolTip("Составить шаблон по описанию — подключённой нейросетью или через свой чат "
                               "(промпт с примером JSON — в буфер, ответ — «Импорт → Из буфера обмена»)")
        ai_menu = QMenu(self.btn_ai)
        ai_menu.addAction(icons.icon("sparkles"), "Составить по описанию (подключённая нейросеть)…", self.compose_ai)
        ai_menu.addAction(icons.icon("copy"), "Скопировать промпт с примером — для своего чата",
                          lambda: self.copy_ai(None))
        ai_menu.addAction(icons.icon("import"), "Вставить ответ нейросети (из буфера обмена)", self.import_clipboard)
        self.btn_ai.setMenu(ai_menu)
        self._ai_done.connect(self._on_ai_done)
        self._ai_busy = False
        for b in (self.btn_ai, self.btn_import, self.btn_new):
            b.setFixedHeight(34)
            head.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(head)
        self.tabs = Segmented([("schedules", "Расписания"), ("looks", "Оформления")])
        self.tabs.set_value("schedules")
        self.tabs.changed.connect(lambda _k: self.refill())
        tr = QHBoxLayout()
        tr.addWidget(self.tabs)
        tr.addStretch(1)
        root.addLayout(tr)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.list_host = QWidget()
        self.list_host.setObjectName("page")
        self.list_lay = QVBoxLayout(self.list_host)
        self.list_lay.setContentsMargins(0, 0, 6, 0)
        self.list_lay.setSpacing(10)
        self.scroll.setWidget(self.list_host)
        root.addWidget(self.scroll, 1)

        foot = QFrame()
        foot.setObjectName("card")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(14, 8, 10, 8)
        fl.setSpacing(8)
        self.tab_ic = QLabel()
        self.tab_ic.setFixedSize(18, 18)
        fl.addWidget(self.tab_ic)
        self.tab_text = label("", "rowSub", wrap=True)
        fl.addWidget(self.tab_text, 1)
        b_open = button(" Открыть вкладку", "external")
        b_open.setToolTip("Открыть экран эфира в браузере по умолчанию. Эту вкладку и захватывайте в демонстрации")
        b_open.clicked.connect(self.ctl.open_tab)
        b_copy = button(" Адрес", "copy")
        b_copy.setToolTip("Скопировать адрес вкладки — чтобы открыть её в нужном браузере")
        b_copy.clicked.connect(self.ctl.copy_url)
        fl.addWidget(b_copy)
        fl.addWidget(b_open)
        root.addWidget(foot)
        self.toast = Toast(self.body)

        ctl.webinars_changed.connect(self.refill)
        ctl.live_changed.connect(self.refill)
        ctl.tab_changed.connect(self._tab)
        ctl.message.connect(self._message)
        theme.changed.connect(self.refill)
        geo = getattr(self.settings, "efir_window_geometry", "")
        if geo:
            self.restoreGeometry(QByteArray.fromBase64(geo.encode()))
        self.ctl.auto_import_legacy()
        self.refill()

    # ------------------------------------------------------------ список
    def tab(self) -> str:
        return self.tabs.value() or "schedules"

    def refill(self) -> None:
        while self.list_lay.count():
            it = self.list_lay.takeAt(0)
            wd = it.widget()
            if wd is not None:
                wd.setParent(None)               # сразу из окна; удалится потом
                wd.deleteLater()
        live = self.ctl.store.live
        looks_tab = self.tab() == "looks"
        self.btn_import.setVisible(not looks_tab)
        self.btn_ai.setVisible(not looks_tab)
        self.lede.setText("Оформление — что видят ученики на экране эфира: фон, видео зарядок, экран перерыва. "
                          "Его выбирают расписания и уроки." if looks_tab else
                          "Расписание — блоки по минутам и оформление экрана. «Запустить» — таймер для вас и "
                          "вкладка браузера для учеников. Уроки запускаются с экрана урока.")
        if looks_tab:
            if not self.ctl.store.looks:
                self.list_lay.addWidget(Note("Оформлений пока нет. Нажмите «Новый»: фон, зарядки, экран перерыва.",
                                             "info"))
            for lk in self.ctl.store.looks:
                self.list_lay.addWidget(LookCard(self, lk))
            self.list_lay.addStretch(1)
            self._tab()
            return
        items = self.ctl.store.visible()
        if not items:
            note = Note("Шаблонов пока нет. Нажмите «Новый» — задайте расписание, фон, зарядки и перерыв. "
                        "Или «Импорт»: JSON-файл, ответ нейросети, шаблоны «Таймера вебинара».", "info")
            self.list_lay.addWidget(note)
            if self.ctl.legacy_folder():
                b = button(" Перенести шаблоны из «Таймера вебинара»", "import")
                b.clicked.connect(lambda: self.ctl.import_legacy())
                self.list_lay.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        for w in items:
            self.list_lay.addWidget(WebinarCard(self, w, bool(live and live.webinar_id == w.id)))
        self.list_lay.addStretch(1)
        self._tab()

    def _tab(self) -> None:
        text, token = self.ctl.tab_status()
        self.tab_ic.setPixmap(icons.pixmap("monitor", theme.c(token), 18))
        self.tab_text.setText(f"{text}.  Адрес: {self.ctl.url}  — откройте его в браузере, где идёт трансляция, "
                              "и захватите эту вкладку.")

    def _message(self, text: str, warn: bool) -> None:
        if self.isVisible():
            self.toast.show_message(text, warn=warn)

    # ------------------------------------------------------------ действия
    def ask_launch(self, w: Webinar, anchor: QWidget) -> None:
        """«Запустить»: начало — сейчас или в выбранное время (в шаблоне его нет)."""
        from .efir_start import ask_start
        v = ask_start(self, anchor.mapToGlobal(QPoint(0, anchor.height())), last=w.start,
                      title=f"Начало: {w.title}")
        if v is not None:
            self.ctl.launch(w.id, v)

    def duplicate(self, wid: str) -> None:
        w = self.ctl.store.get(wid)
        if w:
            self.ctl.store.add([w.copy(w.title + " — копия")])
            self.ctl.webinars_changed.emit()

    def duplicate_look(self, lid: str) -> None:
        lk = self.ctl.store.look(lid)
        if lk is None:
            return
        c = Look(**{**lk.to_dict(), "exercises": list(lk.exercises)})
        c.id = Look().id
        c.title = lk.title + " — копия"
        self.ctl.save_look(c)

    def remove_look(self, lid: str) -> None:
        lk = self.ctl.store.look(lid)
        if lk is None:
            return
        users = self.ctl.store.users_of(lid)
        if users:
            QMessageBox.information(self, "Оформление используется",
                                    "Это оформление выбрано в расписаниях: " + ", ".join(w.title for w in users)
                                    + ". Сначала выберите там другое оформление.")
            return
        if QMessageBox.question(self, "Удалить оформление", f"Удалить оформление «{lk.title}»?") \
                == QMessageBox.StandardButton.Yes:
            self.ctl.store.remove_look(lid)
            self.ctl.webinars_changed.emit()

    def move(self, wid: str, d: int) -> None:
        self.ctl.store.move(wid, d)
        self.refill()

    def remove(self, wid: str) -> None:
        w = self.ctl.store.get(wid)
        if not w:
            return
        r = QMessageBox.question(self, "Удалить шаблон", f"Удалить шаблон «{w.title}»?")
        if r == QMessageBox.StandardButton.Yes:
            live = self.ctl.store.live
            if live and live.webinar_id == wid:
                self.ctl.stop_live()
            self.ctl.store.remove(wid)
            self.ctl.webinars_changed.emit()

    def export(self, wid: str) -> None:
        w = self.ctl.store.get(wid)
        if not w:
            return
        safe = "".join(c for c in w.title if c not in '\\/:*?"<>|').strip() or "Вебинар"
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт шаблона", str(Path.home() / "Documents" / f"{safe}.json"),
                                              "JSON (*.json)")
        if not path:
            return
        try:
            Path(path).write_text(export_json([w]), encoding="utf-8")
        except OSError as e:
            self.toast.show_message(f"Не сохранено: {e}", warn=True)
            return
        self.toast.show_message(f"Сохранено: {path}")

    def import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Импорт шаблонов", str(Path.home() / "Documents"),
                                              "JSON (*.json);;Все файлы (*.*)")
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8-sig")
        except OSError as e:
            self.toast.show_message(f"Файл не прочитан: {e}", warn=True)
            return
        self._import_text(text)

    def import_clipboard(self) -> None:
        self._import_text(QGuiApplication.clipboard().text())

    def _import_text(self, text: str) -> None:
        try:
            items = parse_webinars(text)
        except ValueError as e:
            self.toast.show_message(f"Не получилось: {e}", warn=True)
            return
        added = self.ctl.store.add(items)
        self.ctl.webinars_changed.emit()
        self.toast.show_message(f"Добавлено шаблонов: {len(added)} — " + ", ".join(w.title for w in added))

    def copy_ai(self, wid: str | None) -> None:
        w = self.ctl.store.get(wid) if wid else (self.ctl.store.visible()[0] if self.ctl.store.visible() else None)
        QGuiApplication.clipboard().setText(ai_prompt(w))
        self.toast.show_message("Промпт скопирован. Вставьте его в чат нейросети и допишите своё расписание; "
                                "ответ скопируйте и нажмите «Импорт → Из буфера обмена».", ms=9000)

    def compose_ai(self) -> None:
        from .. import ai
        if self._ai_busy:
            self.toast.show_message("Нейросеть ещё составляет расписание…")
            return
        if not ai.configured(self.settings):
            self.copy_ai(None)
            self.toast.show_message("Нейросеть не подключена (⚙ Настройки → Нейросеть). Промпт с примером "
                                    "скопирован — вставьте его в свой чат, ответ — «Импорт → Из буфера обмена».",
                                    warn=True, ms=10000)
            return
        text, ok = QInputDialog.getMultiLineText(
            self, "Составить расписание нейросетью",
            "Опишите вебинар своими словами: когда старт, какие блоки и сколько минут, где перерыв и зарядки.",
            "Старт в 11:00. Приветствие 2 мин, теория 20 мин, зарядка для глаз 5 мин, практика 20 мин, "
            "перерыв 10 мин, разбор заданий 25 мин, выводы 5 мин.")
        if not ok or not text.strip():
            return
        example = self.ctl.store.visible()[0] if self.ctl.store.visible() else None
        self._ai_busy = True
        self.toast.show_message("Нейросеть составляет расписание… это до минуты", ms=60000)

        def work() -> None:
            try:
                answer, _name = ai.ask(self.settings, AI_SYSTEM, ai_prompt(example) + text.strip())
                self._ai_done.emit(answer, "")
            except Exception as e:      # ошибка сети/ключа — показать человеку, не уронить поток
                self._ai_done.emit("", str(e))

        threading.Thread(target=work, name="efir-ai", daemon=True).start()

    def _on_ai_done(self, answer: str, error: str) -> None:
        self._ai_busy = False
        if error:
            self.toast.show_message(f"Нейросеть не справилась: {error}", warn=True, ms=10000)
            return
        try:
            items = parse_webinars(answer)
        except ValueError as e:
            self.toast.show_message(f"Ответ нейросети не разобрался: {e}", warn=True, ms=10000)
            return
        added = self.ctl.store.add(items)
        self.ctl.webinars_changed.emit()
        self.toast.show_message("Готово — проверьте шаблон и добавьте фон и зарядки")
        if added:
            self.ctl.edit(added[0].id)

    # ------------------------------------------------------------ окно
    def show_and_raise(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def save_geometry(self) -> None:
        if self.settings is not None:
            self.settings.efir_window_geometry = bytes(self.saveGeometry().toBase64()).decode()
            self.settings.save()

    def closeEvent(self, e) -> None:
        self.save_geometry()
        super().closeEvent(e)

    def sizeHint(self) -> QSize:
        return QSize(820, 640)
