"""«Импорт урока → Урок через нейросеть»: план, класс, промпт для своего чата (или встроенная нейросеть), ответ —
урок в Markdown со слайдами, фото по ссылкам и местами для картинок.

План выбран — промпт просит этапы строго по нему, а урок из ответа привязывается к плану (plans.link_topic).
Слайды «![Слайд N](slide:N)» берутся из PDF материала или из презентации, которую подставили; нет её — места
«Слайд N», подставить можно и позже на экране урока. Фото по ссылкам скачиваются при «Добавить урок» в фоне
(web_images.fetch_images): «Пропустить» — урок добавляется сразу, «Закрыть» — ничего не добавляется.
"""
from __future__ import annotations

import copy
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QHBoxLayout, QLineEdit, QPlainTextEdit, QScrollArea,
                               QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from .. import ai, lesson_ai as L, materials, web_images
from ..storage import BLOCK_CODE, BLOCK_IMAGE, BLOCK_MARKDOWN, BLOCK_STAGE, Settings, Template
from .widgets import Card, Row, accent_button, button, group_title, label

MATERIAL_FILTER = ("Методички, презентации и текст (*.pdf *.docx *.pptx *.txt *.md);;Все файлы (*.*)")
SLIDES_FILTER = "Презентация (*.pdf *.pptx)"


class _Job(QObject):
    """Запрос к нейросети в фоновом потоке; сигналы приходят в поток окна."""
    status = Signal(str)               # кто отвечает
    progress = Signal(str, int, str)   # фаза (connect | think | write), знаков, хвост ответа
    done = Signal(str, str)            # ответ, кто ответил
    failed = Signal(str)


class _Fetch(QObject):
    """Скачивание картинок в фоне."""
    progress = Signal(int, int)
    done = Signal(object, list)        # урок, замечания


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 11 <= n <= 14:
        return many
    return one if n % 10 == 1 else few if 2 <= n % 10 <= 4 else many


class LessonAIPage(QWidget):
    changed = Signal()                 # можно ли добавить урок — изменилось
    status_text = Signal(str)          # строка состояния окна

    def __init__(self, settings: Settings, plans=(), exercises=None, parent=None, notify=None,
                 open_ai_settings=None, live_check=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.plans: list[Template] = list(plans)
        self.exercises = exercises or (lambda plan: [])
        self.notify = notify or (lambda text, warn=False: None)
        self.open_ai_settings = open_ai_settings
        self.live_check = live_check or (lambda: False)
        self.fetch = web_images.fetch_images
        self._pdf: str | None = None
        self._slides: dict[tuple[str, int], str | None] = {}
        self._parsed: tuple[Template, list[str]] | None = None
        self._cancel: threading.Event | None = None       # встроенная нейросеть
        self._fetching: threading.Event | None = None     # скачивание картинок
        self._closed = False
        self._t0, self._who, self._phase, self._chars, self._preview = 0.0, "", "connect", 0, ""
        self._tick = QTimer(self, interval=500, timeout=self._refresh_progress)
        self._timer = QTimer(self, singleShot=True, interval=250, timeout=self.reparse)
        self._build()

    # ------------------------------------------------------------ вид
    def _build(self) -> None:
        s = self.settings
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(0)

        lay.addWidget(group_title("1. Как вести урок"))
        c = Card()
        self.plan_combo = QComboBox()
        from ..efir.model import fmt_minutes
        for p in self.plans:
            total = sum(b.minutes for b in p.blocks if b.type == BLOCK_STAGE)
            self.plan_combo.addItem(f"{p.title} · {fmt_minutes(total)}", p.id)
        self.plan_combo.addItem("Без плана", "")
        i = self.plan_combo.findData(s.lesson_plan)
        self.plan_combo.setCurrentIndex(i if i >= 0 else 0)
        self.plan_combo.currentIndexChanged.connect(self._plan_changed)
        c.add(Row("layers", "План", "Этапы и минуты — строго по плану; урок будет по нему", [self.plan_combo]))
        self.minutes_spin = QSpinBox()
        self.minutes_spin.setRange(10, 600)
        self.minutes_spin.setSingleStep(5)
        self.minutes_spin.setSuffix(" мин")
        self.minutes_spin.setValue(s.lesson_minutes)
        self.break_spin = QSpinBox()
        self.break_spin.setRange(0, 60)
        self.break_spin.setSuffix(" мин")
        self.break_spin.setSpecialValueText("без перерыва")
        self.break_spin.setValue(s.lesson_break)
        self.minutes_row = Row("clock", "Урок", "Длительность и перерыв — без плана", [self.minutes_spin, self.break_spin])
        c.add(self.minutes_row)
        self.class_edit = QLineEdit(s.lesson_class)
        self.class_edit.setPlaceholderText("например, 5 класс или 11–12 лет")
        self.class_edit.setMinimumWidth(220)
        c.add(Row("flag", "Класс / возраст", "Необязательно — иначе нейросеть определит по материалу", [self.class_edit]))
        lay.addWidget(c)

        head = QHBoxLayout()
        head.addWidget(group_title("2. Материал (необязательно)"))
        head.addStretch(1)
        from_file = button("Из файла…", "import", quiet=True)
        from_file.clicked.connect(self._material_from_file)
        head.addWidget(from_file)
        lay.addLayout(head)
        self.material = self._editor("Можно не заполнять — приложите файл прямо в чате. Или «Из файла…»: PDF, Word, "
                                     "PowerPoint — или вставьте текст методички.")
        self.material.setMinimumHeight(110)
        self.material.textChanged.connect(self._update_buttons)
        lay.addWidget(self.material)

        lay.addWidget(group_title("3. Нейросеть"))
        c2 = Card()
        self.copy_btn = button("Скопировать промпт", "copy")
        self.copy_btn.setToolTip("Промпт — в буфер обмена: вставьте в ChatGPT (или другой чат) и приложите "
                                 "презентацию или методичку")
        self.copy_btn.clicked.connect(self.copy_prompt)
        self.cancel_btn = button("Отмена", quiet=True)
        self.cancel_btn.clicked.connect(self._cancel_ask)
        self.cancel_btn.hide()
        self.ask_btn = accent_button("Составить встроенной нейросетью", "sparkles")
        self.ask_btn.clicked.connect(self.ask)
        c2.add(Row("cpu", "Урок", "", [self.copy_btn, self.cancel_btn, self.ask_btn]))
        hint = QWidget()
        hl = QVBoxLayout(hint)
        hl.setContentsMargins(48, 0, 16, 12)
        hl.setSpacing(4)
        self.ai_info = label("Вставьте промпт в ChatGPT (или другой чат), приложите презентацию или методичку — ответ "
                             "вставьте ниже.", "rowSub", wrap=True)
        self.progress_lbl = label("", "progressText")
        self.progress_tail = label("", "progressTail")
        self.progress_tail.setTextFormat(Qt.TextFormat.PlainText)
        for w in (self.ai_info, self.progress_lbl, self.progress_tail):
            hl.addWidget(w)
        c2.add(hint)
        lay.addWidget(c2)

        lay.addWidget(group_title("4. Ответ"))
        self.answer_edit = self._editor("Вставьте сюда ответ нейросети (Ctrl+V) — урок в блоке ~~~markdown.")
        self.answer_edit.setMinimumHeight(130)
        self.answer_edit.textChanged.connect(self._timer.start)
        lay.addWidget(self.answer_edit)
        self.info = label("", "answerInfo", wrap=True)
        self.info.setTextFormat(Qt.TextFormat.PlainText)
        self.info.setContentsMargins(2, 6, 0, 0)
        lay.addWidget(self.info)
        row = QHBoxLayout()
        self.slides_btn = button("Подставить слайды из презентации…", "presentation")
        self.slides_btn.setToolTip("PDF или PowerPoint той презентации, что приложили в чате: слайды встанут картинками")
        self.slides_btn.clicked.connect(self._pick_slides)
        row.addWidget(self.slides_btn)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)

        sc = QScrollArea()
        sc.setObjectName("importScroll")
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(sc)
        self.slides_btn.hide()
        self.progress_lbl.hide()
        self.progress_tail.hide()
        self._plan_changed()

    @staticmethod
    def _editor(placeholder: str) -> QPlainTextEdit:
        e = QPlainTextEdit()
        e.setObjectName("importText")
        e.setPlaceholderText(placeholder)
        e.setTabChangesFocus(True)
        e.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        return e

    # ------------------------------------------------------------ выбор
    def plan(self) -> Template | None:
        pid = self.plan_combo.currentData() or ""
        return next((p for p in self.plans if p.id == pid), None)

    def options(self) -> L.Options:
        return L.Options(style=L.STYLE_SCENARIO, minutes=self.minutes_spin.value(), break_min=self.break_spin.value(),
                         cls=self.class_edit.text().strip(), marks=False)

    def _remember(self) -> None:
        s = self.settings
        s.lesson_plan = self.plan_combo.currentData() or ""
        s.lesson_class = self.class_edit.text().strip()
        s.lesson_minutes, s.lesson_break = self.minutes_spin.value(), self.break_spin.value()

    def _plan_changed(self, *_a) -> None:
        self.minutes_row.setHidden(self.plan() is not None)
        self._update_buttons()
        if self.answer_edit.toPlainText().strip():
            self.reparse()

    def _update_buttons(self) -> None:
        busy = self._cancel is not None
        has = bool(self.material.toPlainText().strip())
        ok = ai.configured(self.settings)
        self.copy_btn.setEnabled(not busy)
        self.ask_btn.setEnabled(has and ok and not busy)
        self.ask_btn.setToolTip("" if ok else "Встроенная нейросеть не подключена: ⚙ Настройки → Нейросеть")
        self.ask_btn.setVisible(not busy)
        self.cancel_btn.setVisible(busy)

    # ------------------------------------------------------------ материал и слайды
    def _material_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Материал: методичка или презентация", "", MATERIAL_FILTER)
        if path:
            self.load_material(path)

    def load_material(self, path: str) -> None:
        try:
            m = materials.extract(path)
        except (OSError, ValueError, KeyError) as e:
            self.notify(f"Не прочитать файл: {e}", True)
            return
        if m.pdf:
            self._pdf = m.pdf
            self._slides.clear()
        self.material.setPlainText(m.text)
        if self.answer_edit.toPlainText().strip():
            self.reparse()

    def _pick_slides(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Презентация — для картинок слайдов", "", SLIDES_FILTER)
        if path:
            self.pick_slides(path)

    def pick_slides(self, path: str) -> bool:
        """PDF или PowerPoint с теми же слайдами, что приложили в чате, — картинки к местам «Слайд N»."""
        from .. import slides
        if self.live_check():
            self.notify("Идёт эфир — слайды из презентации подставьте после него: сохранение PowerPoint в PDF занимает "
                        "до минуты.", True)
            return False
        pdf = path
        if path.lower().endswith(".pptx"):
            pdf = slides.export_pdf(path)
            if not pdf:
                pick, _ = QFileDialog.getOpenFileName(self, f"PDF презентации «{Path(path).stem}» — для картинок слайдов",
                                                      str(Path(path).parent), "PDF (*.pdf)")
                pdf = pick or None
        if not pdf:
            return False
        self._pdf = pdf
        self._slides.clear()
        self.reparse()
        return True

    def _slide(self, n: int) -> str | None:
        if not self._pdf:
            return None
        key = (self._pdf, n)
        if key not in self._slides:
            from ..storage import DATA_DIR, MEDIA_FOLDER, media_ref
            out = materials.render_page(self._pdf, n, DATA_DIR / MEDIA_FOLDER)
            self._slides[key] = media_ref(out) if out else None
        return self._slides[key]

    # ------------------------------------------------------------ промпт и встроенная нейросеть
    def copy_prompt(self) -> None:
        self._remember()
        plan = self.plan()
        text = L.lesson_prompt(self.options(), material=self.material.toPlainText(), plan=plan,
                               exercises=self.exercises(plan))
        QGuiApplication.clipboard().setText(text)
        self.notify("Промпт скопирован: вставьте его в ChatGPT (Ctrl+V), приложите презентацию или методичку, "
                    "а ответ — в поле «Ответ».")
        self.answer_edit.setFocus()

    def ask(self) -> None:
        self._remember()
        plan = self.plan()
        opt = self.options()
        material = self.material.toPlainText()
        system = L.lesson_instruction(opt, plan=plan, exercises=self.exercises(plan), source="next")
        self._cancel = threading.Event()
        cancel = self._cancel
        job = _Job(self)
        job.status.connect(self._on_status)
        job.progress.connect(self._on_progress)
        job.done.connect(self._on_answer)
        job.failed.connect(self._on_failed)
        self._job = job
        self._t0 = time.monotonic()
        c = ai.config(self.settings)
        self._who, self._phase, self._chars, self._preview = c.provider.name if c else "", "connect", 0, ""
        self._update_buttons()
        self.progress_lbl.show()
        self.progress_tail.show()
        self._tick.start()
        self._refresh_progress()

        def work() -> None:
            try:
                text, who = ai.ask(self.settings, system, L.material_for(material, opt), cancel,
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

    def _cancel_ask(self) -> None:
        if self._cancel is not None:
            self._cancel.set()
        self._cancel = None
        self._stop_progress()
        self._update_buttons()

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
        n = f"{self._chars:,}".replace(",", " ")
        what = {"connect": "жду ответа", "think": f"думает — объём рассуждений {n}" if self._chars else "думает",
                "write": f"пишет урок — {n} знаков"}.get(self._phase, "работает")
        self.progress_lbl.setText(f"{self._who}: {what} · {sec // 60}:{sec % 60:02d}")
        self.progress_tail.setText(self._preview if self._phase == "write" else "")

    def _stop_progress(self) -> None:
        self._tick.stop()
        self.progress_lbl.hide()
        self.progress_tail.hide()

    def _on_answer(self, text: str, _who: str) -> None:
        self._cancel = None
        self._stop_progress()
        self._update_buttons()
        self.answer_edit.setPlainText(text)
        self.reparse()

    def _on_failed(self, msg: str) -> None:
        self._cancel = None
        self._stop_progress()
        self._update_buttons()
        self.info.setText(f"Нейросеть не ответила: {msg}")
        self.notify("Нейросеть не ответила — можно «Скопировать промпт» и спросить свой чат.", True)

    # ------------------------------------------------------------ ответ → что получится
    def parsed(self) -> tuple[Template, list[str]] | None:
        return self._parsed

    def ready(self) -> bool:
        return self._parsed is not None and self._fetching is None

    def reparse(self) -> None:
        text = self.answer_edit.toPlainText()
        self._parsed = None
        if not text.strip():
            self.info.setText("")
            self.slides_btn.hide()
            self.status_text.emit("Когда придёт ответ нейросети, здесь будет видно, что получится.")
            self.changed.emit()
            return
        try:
            p = L.parse_lesson(text, material=self.material.toPlainText(), style=L.STYLE_SCENARIO, slide=self._slide)
        except L.LessonError as e:
            self.info.setText(str(e))
            self.slides_btn.hide()
            self.status_text.emit("Ответ не разобрать.")
            self.changed.emit()
            return
        t = p.template
        plan = self.plan()
        notes = (plans_link(t, plan) if plan is not None else []) + list(p.warnings)
        self._parsed = (t, notes)
        self.info.setText(self._summary(t, plan) + ("\n" + "\n".join(notes) if notes else ""))
        self.slides_btn.setHidden(not any(b.type == BLOCK_IMAGE and b.slide and not b.text for b in t.blocks))
        self.status_text.emit("Готово — можно добавить урок." if not notes else "Готово, но проверьте замечания.")
        self.changed.emit()

    @staticmethod
    def _summary(t: Template, plan: Template | None) -> str:
        st = sum(1 for b in t.blocks if b.type == BLOCK_STAGE)
        nn = sum(1 for b in t.blocks if b.type == BLOCK_MARKDOWN)
        cc = sum(1 for b in t.blocks if b.type == BLOCK_CODE)
        imgs = [b for b in t.blocks if b.type == BLOCK_IMAGE]
        slides = [b for b in imgs if b.slide]
        web = [b for b in imgs if "://" in (b.text or "")]
        need = [b for b in imgs if not b.text and not b.slide]
        head = f"«{t.title}» — {st} {_plural(st, 'этап', 'этапа', 'этапов')}"
        head += f" по плану «{plan.title}»" if plan is not None else ""
        head += f", {nn} {_plural(nn, 'заметка', 'заметки', 'заметок')}"
        head += f", {cc} {_plural(cc, 'блок', 'блока', 'блоков')} кода." if cc else ", без кода."
        parts = [head]
        if slides:
            empty = sum(1 for b in slides if not b.text)
            parts.append(f"Слайды: {len(slides)}" + (" — подставьте из презентации." if empty else " — из материала."))
        if web:
            parts.append(f"Фото по ссылкам: {len(web)} — скачаются при добавлении.")
        if need:
            parts.append(f"Нужно вставить: {len(need)}.")
        return " ".join(parts)

    # ------------------------------------------------------------ добавить: скачать фото и отдать урок
    def downloading(self) -> bool:
        return self._fetching is not None

    def start_add(self, done) -> None:
        """«Добавить урок»: фото по ссылкам — в фоне; done(урок, замечания) — когда готово (или «Пропустить»)."""
        if self._parsed is None:
            return
        self._remember()
        t, notes = copy.deepcopy(self._parsed[0]), list(self._parsed[1])
        if not any(b.type == BLOCK_IMAGE and "://" in (b.text or "") for b in t.blocks):
            done(t, notes)
            return
        ev = threading.Event()
        self._fetching = ev
        job = _Fetch(self)
        self._fetch_job = job
        job.progress.connect(lambda a, b: self.status_text.emit(f"Скачиваю картинки: {a} из {b}… (Пропустить — урок "
                                                                 "добавится, фото останутся ссылками)"))
        job.done.connect(lambda tt, more: self._fetched(tt, notes + more, done))
        self.status_text.emit("Скачиваю картинки: 0 из …")
        self.changed.emit()
        fetch = self.fetch

        def work() -> None:
            try:
                more = fetch(t, cancel=ev, progress=job.progress.emit)
            except Exception as e:   # noqa: BLE001 — урок добавляется и без фото
                more = [f"Картинки не скачались: {e}"]
            job.done.emit(t, list(more or []))
        threading.Thread(target=work, name="lesson-images", daemon=True).start()

    def _fetched(self, t: Template, notes: list[str], done) -> None:
        self._fetching = None
        self.changed.emit()
        if self._closed:
            return
        done(t, notes)

    def skip_download(self) -> None:
        if self._fetching is not None:
            self._fetching.set()

    def close_page(self) -> None:
        """Окно закрывают: скачивание и нейросеть — отменить, ничего не добавлять."""
        self._closed = True
        for ev in (self._fetching, self._cancel):
            if ev is not None:
                ev.set()


def plans_link(t: Template, plan: Template) -> list[str]:
    from .. import plans
    return plans.link_topic(t, plan)
