"""«Импорт урока»: из файла, вставкой или с помощью нейросети.

- «Из файла» — .ipynb, .md, .py, .json (перетащить или выбрать);
- «Вставить» — код, Markdown с ```-блоками, тетрадка Jupyter или ответ нейросети (JSON): что это — видно сразу;
- «С помощью нейросети» — код или задание с решением → нейросеть раскладывает его в урок: с комментариями
  для преподавателя, по шагам или по частям. Подключённая нейросеть (⚙ → Нейросеть) отвечает сама; без неё —
  «Скопировать промпт» в свой чат (ChatGPT, Claude…) и вставить ответ обратно.

Результат — список уроков в self.result и стиль разбора в self.result_style (чтобы окно программы включило
подходящий режим печати).
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QScrollArea, QSizePolicy, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from .. import ai, lesson_ai as L, materials
from ..highlighter import LANGUAGES
from ..importers import FILE_EXTS, FILE_FILTER, load_file, parse_pasted
from ..storage import Settings, Template
from .theme import theme
from .widgets import Card, Note, Row, Segmented, Switch, Toast, accent_button, button, group_title, hsep, label, \
    page_header

TAB_FILE, TAB_PASTE, TAB_AI = "file", "paste", "ai"


def pptx_lesson(parent, path: str, pdf: str | None = None) -> tuple[Template, list[str]]:
    """PowerPoint → урок по слайдам. Картинок нет (PowerPoint не сохранил PDF) — попросить PDF этой презентации."""
    from .. import slides
    t, warns, need = slides.from_pptx(path, pdf=pdf)
    if need:
        pick, _ = QFileDialog.getOpenFileName(parent, f"PDF презентации «{Path(path).stem}» — для картинок слайдов",
                                              str(Path(path).parent), "PDF (*.pdf)")
        if pick:
            t, warns, _need = slides.from_pptx(path, pdf=pick, export=False)
    return t, warns

log = logging.getLogger("autoprint.ai")

STYLE_HINTS = {
    L.STYLE_COMMENTS: "Код целиком, в нём комментарии — что сказать перед каждым куском. Печать «По строкам»: "
                      "комментарий — над кодом на экране урока («Скажи: …»), Enter — следующая строка.",
    L.STYLE_STEPS: "Код с разметкой шагов: что за чем писать, с возвратом наверх (import) и вставкой в середину. "
                   "Печать «По шагам»: прочитали «Скажи: …» на экране урока — Ctrl+F9.",
    L.STYLE_PARTS: "Несколько блоков кода, между ними пояснения для учеников. Печать «Целиком»: блок за блоком "
                   "(Ctrl+F12 — следующий).",
    L.STYLE_SCENARIO: "Урок из методички, плана или презентации: этапы с минутами, что сказать, какой термин "
                      "дать, что спросить, сделать и показать. Слайды из PDF прикрепляются к этапам картинками. "
                      "Урок сразу открывается на экране урока.",
}
MATERIAL_FILTER = ("Методички, презентации и код (*.pdf *.docx *.pptx *.txt *.md *.py *.ipynb *.html *.js *.css "
                   "*.java *.kt *.cs *.cpp *.sql);;Все файлы (*.*)")
CODE_PLACEHOLDER = ("Вставьте код — или задание вместе с решением. Нейросеть добавит комментарии для преподавателя "
                    "и разложит код по шагам или частям.")
SCENARIO_PLACEHOLDER = ("Вставьте методичку, план урока или текст презентации — или «Из файла…»: PDF, Word (.docx), "
                        "PowerPoint (.pptx). Нейросеть разложит урок по этапам: что сказать, спросить, показать.")


class _Job(QObject):
    """Запрос к нейросети в фоновом потоке; сигналы приходят в поток окна."""
    status = Signal(str)         # кто отвечает
    progress = Signal(str, int, str)   # фаза (connect | think | write), знаков, хвост ответа
    done = Signal(str, str)      # ответ, кто ответил
    failed = Signal(str)


class ImportDialog(QDialog):
    def __init__(self, parent=None, settings: Settings | None = None, tab: str = TAB_FILE,
                 open_ai_settings=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Импорт урока")
        self.setModal(False)   # из окна можно открыть ⚙ → Нейросеть и вернуться
        self.settings = settings or Settings.load()
        self.open_ai_settings = open_ai_settings      # «Подключить нейросеть…» — открыть ⚙ → Нейросеть
        self.result: list[Template] = []
        self.result_notes: list[str] = []        # замечания импорта (презентация: скрытые слайды, нет PDF)
        self.result_style = ""
        self._paste_parsed: Template | None = None
        self._ai_parsed: L.Parsed | None = None
        self._cancel: threading.Event | None = None
        self._material_pdf: str | None = None     # PDF материала: из него — картинки слайдов ("slide": N)
        self._slides: dict[tuple[str, int], str | None] = {}
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 18)
        root.setSpacing(0)
        root.addWidget(page_header("Импорт урока", "Из файла, вставкой из буфера обмена или с помощью нейросети: "
                                   "она разложит код в урок с подсказками для преподавателя."))
        root.addSpacing(14)
        self.tabs = Segmented([(TAB_FILE, "Из файла"), (TAB_PASTE, "Вставить"), (TAB_AI, "С помощью нейросети")])
        self.tabs.changed.connect(self._show_tab)
        root.addWidget(self.tabs, 0, Qt.AlignmentFlag.AlignLeft)
        # разбор вставленного — с небольшой задержкой после последнего изменения (до страниц: им нужны таймеры)
        self._paste_timer = QTimer(self, singleShot=True, interval=250, timeout=self._parse_paste)
        self._answer_timer = QTimer(self, singleShot=True, interval=250, timeout=self._parse_answer)
        root.addSpacing(14)
        self.stack = QStackedWidget()
        self.pages = {TAB_FILE: self._page_file(), TAB_PASTE: self._page_paste(), TAB_AI: self._page_ai()}
        for p in self.pages.values():
            self.stack.addWidget(p)
        root.addWidget(self.stack, 1)

        root.addSpacing(12)
        root.addWidget(hsep())
        root.addSpacing(12)
        nav = QHBoxLayout()
        close = button("Закрыть", quiet=True)
        close.clicked.connect(self.reject)
        nav.addWidget(close)
        nav.addStretch(1)
        self.status = label("", "importStatus", wrap=True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        nav.addWidget(self.status, 3)
        self.add_btn = accent_button("Добавить урок", "plus")
        self.add_btn.clicked.connect(self._add)
        nav.addWidget(self.add_btn)
        root.addLayout(nav)
        for b in self.findChildren(QPushButton):   # Enter в полях — новая строка, а не кнопка
            b.setAutoDefault(False)
            b.setDefault(False)

        self.toast = Toast(self.stack)
        self._tick = QTimer(self, interval=500, timeout=self._refresh_progress)   # часы хода работы
        self._t0, self._who, self._phase, self._chars, self._preview = 0.0, "", "connect", 0, ""
        self.paste_edit.textChanged.connect(self._paste_timer.start)
        self.answer_edit.textChanged.connect(self._answer_timer.start)
        self._restyle()
        theme.changed.connect(self._restyle)
        self._fit_screen()
        self.tabs.set_value(tab)
        self._show_tab(tab)

    # ------------------------------------------------------------ страницы
    def _page_file(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        drop = QFrame()
        drop.setObjectName("dropZone")
        dl = QVBoxLayout(drop)
        dl.setContentsMargins(24, 34, 24, 34)
        dl.setSpacing(10)
        t = label("Перетащите сюда файлы", "dropTitle")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dl.addWidget(t)
        s = label(".ipynb (Jupyter) · .md (Markdown) · .py · .json · презентация .pdf или .pptx (урок по слайдам)", "dropSub")
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dl.addWidget(s)
        pick = button("Выбрать файлы…", "import")
        pick.clicked.connect(self._pick_files)
        dl.addWidget(pick, 0, Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(drop)
        lay.addWidget(Note("Тетрадка Jupyter — каждая ячейка становится блоком. Markdown — текст между ```-блоками "
                           "становится пояснениями, сами блоки — кодом. Python — один блок кода, а с разметкой "
                           "«# %%» — по ячейке на блок. Можно выбрать сразу несколько файлов.", "help"))
        lay.addStretch(1)
        return w

    def _page_paste(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.paste_edit = self._editor("Вставьте сюда (Ctrl+V): код, Markdown с ```-блоками, тетрадку Jupyter "
                                       "или ответ нейросети в формате JSON — программа сама поймёт, что это.")
        lay.addWidget(self.paste_edit, 1)
        row = QHBoxLayout()
        row.addWidget(label("Если это просто код, язык:", "importLabel"))
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("определить сам", "")
        for lang in LANGUAGES:
            self.lang_combo.addItem(lang, lang)
        self.lang_combo.currentIndexChanged.connect(self._paste_timer.start)
        row.addWidget(self.lang_combo)
        row.addStretch(1)
        paste = button("Вставить из буфера", "copy")
        paste.clicked.connect(lambda: self.paste_edit.setPlainText(QGuiApplication.clipboard().text()))
        row.addWidget(paste)
        lay.addLayout(row)
        return w

    def _page_ai(self) -> QWidget:
        s = self.settings
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(0)

        head = QHBoxLayout()
        head.addWidget(group_title("1. Что разобрать"))
        head.addStretch(1)
        from_file = button("Из файла…", "import", quiet=True)
        from_file.clicked.connect(self._material_from_file)
        head.addWidget(from_file)
        lay.addLayout(head)
        self.material = self._editor(CODE_PLACEHOLDER)
        self.material.setMinimumHeight(150)
        self.material.textChanged.connect(self._update_ai_buttons)
        lay.addWidget(self.material)

        lay.addWidget(group_title("2. Как разложить"))
        c = Card()
        self.style_seg = Segmented([(k, v) for k, v in L.STYLES.items()])
        self.style_seg.set_value(s.lesson_style if s.lesson_style in L.STYLES else L.STYLE_STEPS)
        self.style_hint = label("", "rowSub", wrap=True)
        self.style_seg.changed.connect(self._style_changed)
        c.add(Row("layers", "Разбор", "", [self.style_seg]))
        hint_row = QWidget()
        hl = QHBoxLayout(hint_row)
        hl.setContentsMargins(48, 0, 16, 12)
        hl.addWidget(self.style_hint)
        c.add(hint_row)
        # сценарий урока: длительность и перерыв
        self.minutes_spin = QSpinBox()
        self.minutes_spin.setRange(10, 600)
        self.minutes_spin.setSingleStep(5)
        self.minutes_spin.setSuffix(" мин")
        self.minutes_spin.setValue(s.lesson_minutes)
        self.minutes_spin.setToolTip("Длительность урока: сумма минут всех этапов")
        self.break_spin = QSpinBox()
        self.break_spin.setRange(0, 60)
        self.break_spin.setSuffix(" мин")
        self.break_spin.setSpecialValueText("без перерыва")
        self.break_spin.setValue(s.lesson_break)
        self.break_spin.setToolTip("Перерыв отдельным этапом в середине урока. «Без перерыва» — только если он "
                                   "есть в материале")
        self.scenario_row = Row("clock", "Урок", "Длительность и перерыв", [self.minutes_spin, self.break_spin])
        c.add(self.scenario_row)
        self.sw_task = Switch(checked=s.lesson_task)
        self.row_task = Row("file-text", "Краткое условие задачи", "Блок «Условие» в начале; нет условия — "
                            "нейросеть сформулирует его по коду", [self.sw_task])
        c.add(self.row_task)
        self.sw_explain = Switch(checked=s.lesson_explain)
        self.row_explain = Row("info", "Пояснения для учеников", "Текстовые блоки: что будем делать (в разборе "
                               "«По частям» — всегда)", [self.sw_explain])
        c.add(self.row_explain)
        self.sw_keep = Switch(checked=s.lesson_keep_code)
        self.row_keep = Row("code", "Не менять код — только комментарии и разметка",
                            "Выключите, если код можно поправить для объяснения", [self.sw_keep])
        c.add(self.row_keep)
        self.detail_seg = Segmented([(L.DETAIL_SHORT, "Коротко"), (L.DETAIL_FULL, "Подробно")])
        self.detail_seg.set_value(s.lesson_detail if s.lesson_detail in (L.DETAIL_SHORT, L.DETAIL_FULL)
                                  else L.DETAIL_SHORT)
        c.add(Row("pencil", "Комментарии", "Коротко — одна строка; подробно — с «зачем»", [self.detail_seg]))
        lay.addWidget(c)

        lay.addWidget(group_title("3. Нейросеть"))
        c2 = Card()
        self.ai_info = label("", "rowSub", wrap=True)
        self.ai_info.setTextFormat(Qt.TextFormat.RichText)
        self.ai_info.linkActivated.connect(lambda _: self._connect_ai())
        self.ask_btn = accent_button("Разобрать нейросетью", "sparkles")
        self.ask_btn.clicked.connect(self._ask)
        self.cancel_btn = button("Отмена", quiet=True)
        self.cancel_btn.clicked.connect(self._cancel_job)
        self.cancel_btn.hide()
        self.copy_btn = button("Скопировать промпт", "copy")
        self.copy_btn.setToolTip("Промпт с вашим кодом — в буфер обмена: вставьте его в свой чат (ChatGPT, Claude…), "
                                 "а ответ — в поле ниже")
        self.copy_btn.clicked.connect(self._copy_prompt)
        c2.add(Row("cpu", "Разобрать", "", [self.copy_btn, self.cancel_btn, self.ask_btn]))
        info_row = QWidget()
        il = QHBoxLayout(info_row)
        il.setContentsMargins(48, 0, 16, 12)
        il.addWidget(self.ai_info)
        c2.add(info_row)
        # ход работы: кто отвечает, что делает (думает / пишет ответ), сколько прошло, хвост ответа
        self.progress_row = QWidget()
        pl = QVBoxLayout(self.progress_row)
        pl.setContentsMargins(48, 0, 16, 12)
        pl.setSpacing(4)
        self.progress_lbl = label("", "progressText")
        self.progress_tail = label("", "progressTail")
        self.progress_tail.setTextFormat(Qt.TextFormat.PlainText)
        pl.addWidget(self.progress_lbl)
        pl.addWidget(self.progress_tail)
        self.progress_row.hide()
        c2.add(self.progress_row)
        lay.addWidget(c2)

        lay.addWidget(group_title("4. Ответ нейросети"))
        self.answer_edit = self._editor("Сюда придёт ответ подключённой нейросети. Или вставьте ответ своего чата "
                                        "(Ctrl+V) — JSON из промпта.")
        self.answer_edit.setMinimumHeight(130)
        lay.addWidget(self.answer_edit)
        self.answer_info = label("", "answerInfo", wrap=True)
        self.answer_info.setTextFormat(Qt.TextFormat.PlainText)
        self.answer_info.setContentsMargins(2, 6, 0, 0)
        lay.addWidget(self.answer_info)
        lay.addStretch(1)

        sc = QScrollArea()
        self.ai_scroll = sc
        sc.setObjectName("importScroll")
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setWidget(inner)
        self._style_changed(self.style_seg.value())
        return sc

    def _editor(self, placeholder: str) -> QPlainTextEdit:
        e = QPlainTextEdit()
        e.setObjectName("importText")
        e.setPlaceholderText(placeholder)
        e.setTabChangesFocus(True)
        e.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        e.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        return e

    # ------------------------------------------------------------ оформление
    def _restyle(self) -> None:
        t = theme
        self.setStyleSheet(f"""
QPlainTextEdit#importText {{ background: {t.css('editor_bg')}; border: 1px solid {t.css('stroke_strong')};
    border-radius: 5px; padding: 6px 8px; font-family: "{t.mono_family}"; font-size: 12px;
    selection-background-color: {t.css('editor_sel')}; selection-color: {t.css('text')}; }}
QPlainTextEdit#importText:focus {{ border-color: {t.css('accent')}; }}
QFrame#dropZone {{ border: 2px dashed {t.css('stroke_strong')}; border-radius: 10px; background: {t.css('panel')}; }}
QFrame#dropZone[hot="true"] {{ border-color: {t.css('accent')}; }}
QLabel#dropTitle {{ font-size: 16px; font-weight: 600; }}
QLabel#dropSub, QLabel#importLabel {{ color: {t.css('dim')}; }}
QLabel#importStatus {{ color: {t.css('dim')}; }}
QLabel#answerInfo {{ color: {t.css('dim')}; }}
QLabel#progressText {{ color: {t.css('accent')}; font-weight: 600; }}
QLabel#progressTail {{ color: {t.css('faint')}; font-family: "{t.mono_family}"; font-size: 11px; }}
QScrollArea#importScroll, QScrollArea#importScroll > QWidget > QWidget {{ background: transparent; }}
""")

    def _fit_screen(self) -> None:
        scr = (self.parentWidget().screen() if self.parentWidget() else None) or QGuiApplication.primaryScreen()
        avail = scr.availableGeometry() if scr else None
        w, h = 860, 860
        if avail is not None:
            w, h = min(w, avail.width() - 40), min(h, avail.height() - 60)
        self.setMinimumSize(min(640, w), min(560, h))
        self.resize(w, h)

    # ------------------------------------------------------------ вкладки и состояние
    def _show_tab(self, key) -> None:
        self.stack.setCurrentWidget(self.pages[key])
        self.add_btn.setVisible(key != TAB_FILE)
        if key == TAB_AI:
            self._update_ai_buttons()
            self._parse_answer()
        elif key == TAB_PASTE:
            self._parse_paste()
            self.paste_edit.setFocus()
        else:
            self.status.setText("")

    def _style_changed(self, key) -> None:
        self.style_hint.setText(STYLE_HINTS.get(key, ""))
        self.sw_explain.setEnabled(key != L.STYLE_PARTS)
        scenario = key == L.STYLE_SCENARIO
        self.scenario_row.setHidden(not scenario)
        for row in (self.row_task, self.row_explain, self.row_keep):   # это про разбор кода
            row.setHidden(scenario)
        self.material.setPlaceholderText(SCENARIO_PLACEHOLDER if scenario else CODE_PLACEHOLDER)
        if hasattr(self, "ask_btn"):
            self._update_ai_buttons()

    def _options(self) -> L.Options:
        style = self.style_seg.value() or L.STYLE_STEPS
        return L.Options(style=style, task=self.sw_task.isChecked(),
                         explain=self.sw_explain.isChecked(), keep_code=self.sw_keep.isChecked(),
                         detail=self.detail_seg.value() or L.DETAIL_SHORT,
                         marks=style != L.STYLE_SCENARIO and L.is_big(self.material.toPlainText()),
                         minutes=self.minutes_spin.value(), break_min=self.break_spin.value())

    def _remember_options(self) -> None:
        o = self._options()
        s = self.settings
        s.lesson_style, s.lesson_task, s.lesson_explain = o.style, o.task, o.explain
        s.lesson_keep_code, s.lesson_detail = o.keep_code, o.detail
        s.lesson_minutes, s.lesson_break = o.minutes, o.break_min

    def _update_ai_buttons(self) -> None:
        has = bool(self.material.toPlainText().strip())
        busy = self._cancel is not None
        ok = ai.configured(self.settings)
        self.copy_btn.setEnabled(has and not busy)
        self.ask_btn.setEnabled(has and ok and not busy)
        self.ask_btn.setVisible(not busy)
        self.cancel_btn.setVisible(busy)
        if busy:
            return
        c = ai.config(self.settings)
        material = self.material.toPlainText()
        big = (f"<br>Код большой ({len(L.source_lines(material))} строк): нейросеть не будет переписывать его, "
               "а только разметит строки — шаги и что сказать. Так быстрее, и код останется точно вашим."
               if has and self._options().marks else "")
        if has and self._material_pdf and self.style_seg.value() == L.STYLE_SCENARIO:
            big += "<br>Материал — PDF: слайды, на которые сошлётся нейросеть, вставятся картинками."
        if ok:
            self.ai_info.setText(f"Ответит: <b>{c.provider.name}</b>{(' · ' + c.model) if c.model else ''}. "
                                 "<a href='ai'>Сменить…</a>" + big)
        elif c is not None:
            self.ai_info.setText(f"{c.provider.name}: {ai.problem(c) or 'не настроено'} "
                                 "<a href='ai'>Настроить…</a> Или «Скопировать промпт» — в свой чат." + big)
        else:
            self.ai_info.setText("Нейросеть не подключена. <a href='ai'>Подключить…</a> — или «Скопировать "
                                 "промпт»: вставьте его в свой чат (ChatGPT, Claude…), а ответ — в поле ниже." + big)

    def _connect_ai(self) -> None:
        if self.open_ai_settings:
            self.open_ai_settings()
            QTimer.singleShot(400, self._update_ai_buttons)

    # ------------------------------------------------------------ из файла
    def _pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Импорт уроков", "", FILE_FILTER)
        self._take_files(paths)

    def _take_files(self, paths: list[str]) -> None:
        done, errors, notes = [], [], []
        pdfs = {Path(p).stem.lower(): p for p in paths if p.lower().endswith(".pdf")}
        pptx = {Path(p).stem.lower() for p in paths if p.lower().endswith(".pptx")}
        for p in paths:
            if p.lower().endswith(".pdf") and Path(p).stem.lower() in pptx:
                continue                         # PDF той же презентации — картинки к слайдам PPTX
            try:
                if p.lower().endswith(".pptx"):
                    t, warns = pptx_lesson(self, p, pdfs.get(Path(p).stem.lower()))
                    notes += warns
                else:
                    t = load_file(p)
            except Exception as e:   # noqa: BLE001 — показать причину по каждому файлу
                errors.append(f"{Path(p).name}: {e}")
                continue
            if not t.blocks:
                errors.append(f"{Path(p).name}: нет блоков для импорта")
                continue
            done.append(t)
        if errors:
            self.toast.show_message("Не импортировано — " + "; ".join(errors)[:400], warn=True, ms=9000)
        if done:
            self.result = done
            self.result_notes = notes
            self.accept()

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._hot(True)

    def dragLeaveEvent(self, e) -> None:
        self._hot(False)

    def dropEvent(self, e) -> None:
        self._hot(False)
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        files = [p for p in paths if Path(p).suffix.lower() in FILE_EXTS]
        if not files:
            self.toast.show_message("Подходят файлы .ipynb, .md, .py и .json.", warn=True)
            return
        self._take_files(files)

    def _hot(self, on: bool) -> None:
        z = self.pages[TAB_FILE].findChild(QFrame, "dropZone")
        if z is not None:
            z.setProperty("hot", on)
            z.style().unpolish(z)
            z.style().polish(z)

    # ------------------------------------------------------------ вставить
    def _parse_paste(self) -> None:
        if self.stack.currentWidget() is not self.pages[TAB_PASTE]:
            return
        text = self.paste_edit.toPlainText()
        self._paste_parsed = None
        if not text.strip():
            self.status.setText("Вставьте текст — здесь будет видно, что получится.")
            self.add_btn.setEnabled(False)
            return
        try:
            t, kind = parse_pasted(text, self.lang_combo.currentData() or "")
        except (ValueError, L.LessonError) as e:
            self.status.setText(str(e))
            self.add_btn.setEnabled(False)
            return
        self._paste_parsed = t
        codes = t.code_blocks()
        self.status.setText(f"Распознано: {kind} · блоков: {len(t.blocks)}, из них кода: {len(codes)}")
        self.add_btn.setEnabled(True)

    # ------------------------------------------------------------ нейросеть
    def _material_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Материал: методичка, презентация, код", "", MATERIAL_FILTER)
        if path:
            self.load_material(path)

    def load_material(self, path: str) -> None:
        """Материал из файла: PDF, DOCX, PPTX — текстом (страницы и слайды помечены), остальное — как есть."""
        try:
            m = materials.extract(path)
        except (OSError, ValueError, KeyError) as e:      # KeyError — повреждённый .docx/.pptx без нужных частей
            self.toast.show_message(f"Не прочитать файл: {e}", warn=True)
            return
        self._material_pdf = m.pdf
        self._slides.clear()
        self.material.setPlainText(m.text)
        if m.pages and self.style_seg.value() != L.STYLE_SCENARIO and Path(path).suffix.lower() in (".pdf", ".pptx"):
            self.toast.show_message("Похоже на методичку или презентацию — для неё подойдёт «Сценарий урока».", ms=6000)

    def _slide(self, n: int) -> str | None:
        """Картинка слайда N материала (PDF) → файл в данных программы."""
        if not self._material_pdf:
            return None
        key = (self._material_pdf, n)
        if key not in self._slides:
            from ..storage import DATA_DIR, MEDIA_FOLDER, media_ref
            out = materials.render_page(self._material_pdf, n, DATA_DIR / MEDIA_FOLDER)
            self._slides[key] = media_ref(out) if out else None
        return self._slides[key]

    def _copy_prompt(self) -> None:
        self._remember_options()
        QGuiApplication.clipboard().setText(L.build_prompt(self.material.toPlainText(), self._options()))
        self.toast.show_message("Промпт скопирован: вставьте его в чат нейросети (Ctrl+V), а её ответ — в поле "
                                "«Ответ нейросети».", ms=7000)
        self._show_answer()
        self.answer_edit.setFocus()

    def _ask(self) -> None:
        self._remember_options()
        opt = self._options()
        material = self.material.toPlainText()
        self._cancel = threading.Event()
        cancel = self._cancel
        job = _Job(self)
        job.status.connect(self._on_status)
        job.progress.connect(self._on_progress)
        job.done.connect(self._on_answer)
        job.failed.connect(self._on_failed)
        self._job = job
        self._t0 = time.monotonic()
        self._who, self._phase, self._chars, self._preview = ai.config(self.settings).provider.name, "connect", 0, ""
        self._update_ai_buttons()
        self.answer_info.setText("")
        self.progress_row.show()
        self._tick.start()
        self._refresh_progress()
        self._show_answer()

        def work() -> None:
            try:
                text, who = ai.ask(self.settings, L.instruction(opt), L.material_for(material, opt),
                                   cancel,
                                   on_status=job.status.emit, on_progress=job.progress.emit)
                if not cancel.is_set():
                    job.done.emit(text, who)
            except ai.Cancelled:
                pass
            except ai.AIError as e:
                if not cancel.is_set():
                    job.failed.emit(str(e))
            except Exception as e:   # noqa: BLE001 — что угодно в фоне не должно ронять окно
                if not cancel.is_set():
                    job.failed.emit(f"Ошибка: {e}")
        threading.Thread(target=work, name="ai-lesson", daemon=True).start()

    def _cancel_job(self) -> None:
        if self._cancel is not None:
            self._cancel.set()
        self._cancel = None
        self._stop_progress()
        self._update_ai_buttons()
        self.answer_info.setText("Отменено.")

    def _on_status(self, who: str) -> None:
        self._who, self._phase, self._chars, self._preview = who, "connect", 0, ""
        self._refresh_progress()

    def _on_progress(self, phase: str, chars: int, preview: str) -> None:
        self._phase, self._chars = phase, chars
        if preview:
            self._preview = preview
        self._refresh_progress()

    def _refresh_progress(self) -> None:
        if self._cancel is None:
            return
        sec = int(time.monotonic() - self._t0)
        clock = f"{sec // 60}:{sec % 60:02d}"
        n = f"{self._chars:,}".replace(",", " ")
        what = {"connect": "жду ответа",
                "think": f"думает — объём рассуждений {n}" if self._chars else "думает",
                "write": f"пишет ответ — {n} знаков"}.get(self._phase, "работает")
        self.progress_lbl.setText(f"{self._who}: {what} · {clock}")
        tail = self._preview if self._phase == "write" else ("Связь есть, ответ формируется — это нормально, "
                                                               "большой код разбирается несколько минут." if sec > 20 else "")
        self.progress_tail.setText(tail)

    def _stop_progress(self) -> None:
        self._tick.stop()
        self.progress_row.hide()

    def _on_answer(self, text: str, who: str) -> None:
        self._cancel = None
        self._stop_progress()
        self._update_ai_buttons()
        self.answer_edit.setPlainText(text)
        self._parse_answer(who)
        self._show_answer()

    def _on_failed(self, msg: str) -> None:
        self._cancel = None
        self._stop_progress()
        self._update_ai_buttons()
        self.answer_info.setText(f"Нейросеть не ответила: {msg}")
        self.toast.show_message("Нейросеть не ответила — можно «Скопировать промпт» и спросить свой чат.", warn=True)

    def _show_answer(self) -> None:
        """Прокрутить к ответу нейросети: там видно, что получится, и замечания."""
        QTimer.singleShot(0, lambda: self.ai_scroll.ensureWidgetVisible(self.answer_info, 0, 40))

    def _parse_answer(self, who: str = "") -> None:
        if self.stack.currentWidget() is not self.pages[TAB_AI]:
            return
        text = self.answer_edit.toPlainText()
        self._ai_parsed = None
        if not text.strip():
            self.status.setText("Когда придёт ответ нейросети, здесь будет видно, что получится.")
            self.add_btn.setEnabled(False)
            if self._cancel is None and not self.answer_info.text().startswith(("Нейросеть не ответила", "Отменено")):
                self.answer_info.setText("")
            return
        style = self._options().style
        try:
            parsed = L.parse_lesson(text, material=self.material.toPlainText(), style=style, slide=self._slide)
        except L.LessonError as e:
            self.status.setText("Ответ не разобрать.")
            self.answer_info.setText(str(e))
            self.add_btn.setEnabled(False)
            return
        self._ai_parsed = parsed
        notes = list(parsed.warnings)
        if self.sw_keep.isChecked() and style != L.STYLE_SCENARIO:   # материал сценария — методичка, а не код
            diff = L.code_changes(self.material.toPlainText(), parsed)
            if diff:
                notes.insert(0, "Внимание: нейросеть изменила код (без учёта комментариев):\n  "
                             + "\n  ".join(diff[:8]))
        head = f"«{parsed.template.title}» — {parsed.summary}" + (f" · ответил {who}" if who else "")
        if who:
            log.info("Импорт нейросетью: %s · замечаний: %d", parsed.summary, len(notes))
        self.answer_info.setText(head + ("\n" + "\n".join(notes) if notes else ""))
        self.status.setText("Готово — можно добавить урок." if not notes else "Готово, но проверьте замечания.")
        self.add_btn.setEnabled(True)

    # ------------------------------------------------------------ итог
    def _add(self) -> None:
        key = self.tabs.value()
        if key == TAB_PASTE and self._paste_parsed is not None:
            self.result = [self._paste_parsed]
            t = self._paste_parsed
            self.result_style = L.STYLE_STEPS if any(len(set(b.steps)) > 1 for b in t.code_blocks()) else ""
        elif key == TAB_AI and self._ai_parsed is not None:
            self.result = [self._ai_parsed.template]
            self.result_style = self._options().style
            self._remember_options()
        else:
            return
        self.accept()

    def reject(self) -> None:
        if self._cancel is not None:
            self._cancel.set()
        super().reject()

    def changeEvent(self, e) -> None:
        super().changeEvent(e)
        # вернулись из ⚙ → Нейросеть — показать, какая нейросеть теперь подключена
        if e.type() == e.Type.ActivationChange and self.isActiveWindow() and hasattr(self, "ask_btn"):
            self._update_ai_buttons()
