"""Главное окно: шаблоны вебинаров, табло эфира (как «Повестка эфира»), значок в трее."""
from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QByteArray, QPoint, QPointF, QRectF, Qt, QTime, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFontMetrics, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton,
                               QScrollArea, QSpinBox, QSystemTrayIcon, QTimeEdit, QVBoxLayout, QWidget)
from shiboken6 import isValid

from .. import APP_NAME, __version__, chime, updater
from ..model import DEMO_NONE, DEMO_ON, DEMO_TEXT, Activity, Plan, Segment, State, default_plan, fmt_left, lessons, \
    parse_time, plan_from, plan_to
from ..scheduler import Scheduler
from ..store import TEMPLATES_DIR, PlanStore, Settings, existing
from . import screens, style
from .style import tabular_digits
from .editor import PlanEditor
from .lessons import LessonPanel, TimelineBar
from .notify import Notifier, parse_pos
from .overlay import BreakOverlay, MediaOverlay, is_video
from .player import BreakPanel, PlayerPanel
from .settings_dialog import SettingsDialog

log = logging.getLogger("webinar")


def make_icon(color: str = style.BRAND, size: int = 64) -> QIcon:
    """Значок: циферблат со стрелками — для окна и трея."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QRectF(2, 2, size - 4, size - 4))
    pen = QPen(QColor("white"), size * 0.09, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    c = QPointF(size / 2, size / 2)
    p.drawLine(c, QPointF(size / 2, size * 0.2))
    p.drawLine(c, QPointF(size * 0.72, size * 0.58))
    p.end()
    return QIcon(pm)


class FitLabel(QLabel):
    """Крупная надпись (отсчёт), которая уменьшается под ширину карточки, а не обрезается в узком окне."""

    def __init__(self, max_px: int = 130, min_px: int = 28, css: str = "") -> None:
        super().__init__()
        self.max_px, self.min_px, self.css = max_px, min_px, css
        self.px = 0
        self.setMinimumWidth(1)          # не распирать карточку длинным текстом
        self._fit()

    def setText(self, text: str) -> None:
        if text != self.text():
            super().setText(text)
            self._fit()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._fit()

    def _fit(self) -> None:
        # размер — через своё оформление: общее (QWidget { font-size }) перекрыло бы setFont
        f = self.font()
        f.setPixelSize(self.max_px)
        f.setWeight(f.Weight.ExtraBold)
        width = QFontMetrics(f).horizontalAdvance(self.text() or "0:00:00")
        avail = max(1, self.width() - 8)
        px = max(self.min_px, min(self.max_px, int(self.max_px * avail / max(1, width))))
        while px > self.min_px:          # ширина растёт не строго пропорционально размеру — проверяем точно
            f.setPixelSize(px)
            if QFontMetrics(f).horizontalAdvance(self.text() or "0:00:00") <= avail:
                break
            px -= 1
        if px != self.px:
            self.px = px
            self.setStyleSheet(f"{self.css} font-size: {px}px;")


class AgendaRow(QFrame):
    start_here = Signal(object)         # «▶ Начать эфир с этой активности» — Segment

    def __init__(self, seg: Segment) -> None:
        super().__init__()
        self.seg = seg
        self.setToolTip("Двойной щелчок — начать эфир с этой активности")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        a = seg.activity
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        self.time = QLabel(f"{seg.start:%H:%M}")
        self.time.setFixedWidth(52)
        glyph = "☕ " if a.kind == "break" else ("👁 " if a.kind == "eyes" else "")
        self.name = QLabel(glyph + a.name)
        self.bell = QLabel("🔔" if a.reminds or a.breaks else "")
        self.bell.setToolTip("Напоминание в начале блока")
        demo = {DEMO_ON: "ВКЛ", DEMO_NONE: "—"}.get(a.demo, "ВЫКЛ")
        self.demo = QLabel(demo)
        self.demo.setToolTip(DEMO_TEXT.get(a.demo) or "Без демонстрации")
        self.dur = QLabel(f"{a.min} мин")
        for w in (self.time, self.name):
            lay.addWidget(w)
        lay.addStretch(1)
        for w in (self.bell, self.demo, self.dur):
            lay.addWidget(w)
        self.set_mode("")

    def mouseDoubleClickEvent(self, _e) -> None:
        self.start_here.emit(self.seg)

    def _menu(self, pos) -> None:
        m = QMenu(self)
        m.addAction("▶ Начать эфир с этой активности", lambda: self.start_here.emit(self.seg))
        m.exec(self.mapToGlobal(pos))

    def set_mode(self, mode: str) -> None:
        """mode: now | past | next | ""."""
        a = self.seg.activity
        color = {"break": style.AMBER, "eyes": style.EYE}.get(a.kind, style.INK)
        bg = {"now": style.ROW_NOW, "past": "transparent"}.get(
            mode, style.ROW_EYES if a.kind == "eyes" else (style.ROW_BREAK if a.kind == "break" else "transparent"))
        border = style.BRAND if mode == "now" else (style.LINE if mode == "next" else "transparent")
        self.setStyleSheet(f"AgendaRow {{ background: {bg}; border: 1px solid {border}; border-radius: 12px; }}")
        dim = mode == "past"
        self.name.setStyleSheet(f"color: {style.MUTED if dim else (style.ROW_NOW_INK if mode == 'now' else color)};"
                                f" font-weight: 600; font-size: 12pt;")
        self.time.setStyleSheet(f"color: {style.BRAND_BRIGHT if mode == 'now' else style.DIM};"
                                f" font-weight: {'700' if mode == 'now' else '500'};")
        demo_color = style.ON if a.demo == DEMO_ON else style.DIM
        self.demo.setStyleSheet(f"color: {style.DIM if dim else demo_color}; font-weight: 600;")
        self.dur.setStyleSheet(f"color: {style.DIM if dim else style.MUTED};")


class MainWindow(QMainWindow):
    def __init__(self, store: PlanStore, settings: Settings, clock=datetime.now) -> None:
        super().__init__()
        self.store, self.settings, self.clock = store, settings, clock
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setWindowIcon(make_icon())
        self.resize(1200, 720)
        self.overlay: BreakOverlay | None = None
        self.media: MediaOverlay | None = None        # видео/картинка активности на экране демонстрации
        self.player_panel: PlayerPanel | None = None  # пульт этого видео на мониторе управления
        self.break_panel: BreakPanel | None = None    # пульт перерыва (вместо карточки с отсчётом)
        self._break_index = -1                        # какой блок-перерыв сейчас на заставке (-1 — вне расписания)
        self.rows: list[AgendaRow] = []
        self.lesson_panels: list[LessonPanel] = []
        self._quitting = False
        self._last_index = -2

        self.scheduler = Scheduler(clock, self)
        self.scheduler.heads_up_min = settings.heads_up_min
        self.scheduler.tick.connect(self._on_tick)
        self.scheduler.heads_up.connect(lambda seg: self._remind(seg, True))
        self.scheduler.block_started.connect(lambda seg: self._remind(seg, False))
        self.scheduler.break_started.connect(self._show_break)
        self.scheduler.finished.connect(self._on_finished)
        self.notifier = Notifier(lambda: screens.control_screen(self.settings), clock)
        # перерыв уже идёт — у ведущего его пульт, карточка «сейчас» не нужна (и после «Напомнить через минуту»)
        self.notifier.accepts = lambda seg, heads_up: not (seg.activity.breaks and not heads_up
                                                           and self.break_panel is not None)
        self.notifier.anchor = parse_pos(settings.note_pos)
        self.notifier.on_moved = self._save_note_pos
        self.notifier.on_next = self._start_activity
        self.notifier.action_of = self._action_label

        self._build()
        self._build_tray()
        self._style_theme()
        self._fill_plans()
        if settings.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(settings.window_geometry.encode()))
        self.scheduler.watch()   # табло идёт всегда; напоминания — только когда эфир ведётся
        self._resume_live()
        # обновления: через 10 с после запуска и раз в сутки — только сообщить, ставит пользователь
        self.update_release = None
        self._update_check = None
        QTimer.singleShot(10_000, self._auto_check_updates)
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._auto_check_updates)
        self._update_timer.start(24 * 3600 * 1000)

    # ================================================================ интерфейс
    def _build(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(10)

        head = QHBoxLayout()
        self.brand = QLabel()
        head.addWidget(self.brand)
        head.addStretch(1)
        self.today = QLabel(objectName="muted")
        self.clock_lbl = QLabel()
        self.clock_lbl.setStyleSheet("font-size: 18pt; font-weight: 700;")
        tabular_digits(self.clock_lbl)   # часы не «дышат» шириной каждую секунду
        self.status = QLabel()
        gear = QPushButton("⚙ Настройки")
        gear.clicked.connect(self.open_settings)
        self.update_btn = QPushButton(objectName="primary")
        self.update_btn.setToolTip("Вышла новая версия таймера — подробности и установка в ⚙ Настройки")
        self.update_btn.clicked.connect(self.open_settings)
        self.update_btn.hide()
        self.theme_btn = QPushButton()
        self.theme_btn.clicked.connect(lambda: self.set_theme("light" if style.current == "dark" else "dark"))
        for w in (self.today, self.clock_lbl, self.status, self.update_btn, self.theme_btn, gear):
            head.addWidget(w)
        outer.addLayout(head)
        # весь эфир: уроки и перерывы в масштабе времени, рядом — сколько прошло и сколько осталось
        line = QHBoxLayout()
        line.setSpacing(12)
        self.overall = TimelineBar()
        self.overall_lbl = QLabel(objectName="muted")
        self.overall_lbl.setStyleSheet("font-size: 10pt; font-weight: 600;")
        self.overall_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        tabular_digits(self.overall_lbl)
        self._fit_overall_lbl()
        line.addWidget(self.overall, 1)
        line.addWidget(self.overall_lbl)
        outer.addLayout(line)

        body = QHBoxLayout()
        body.setSpacing(14)
        outer.addLayout(body, 1)

        # ---- слева: шаблоны и управление эфиром
        left = QFrame(objectName="card")
        left.setFixedWidth(300)
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("<b>Шаблоны вебинаров</b>"))
        self.plans = QListWidget()
        self.plans.currentItemChanged.connect(self._on_plan_selected)
        self.plans.itemDoubleClicked.connect(lambda _i: self.edit_plan())
        ll.addWidget(self.plans, 1)
        grid = QGridLayout()
        for i, (text, fn) in enumerate((("+ Новый", self.new_plan), ("✎ Изменить", self.edit_plan),
                                        ("⧉ Копия", self.duplicate_plan), ("✕ Удалить", self.delete_plan),
                                        ("⇪ Импорт JSON", self.import_plan), ("⇩ Экспорт", self.export_plan))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            grid.addWidget(b, i // 2, i % 2)
        ll.addLayout(grid)
        # надпись — отдельной строкой: в узкой панели рядом с ней поле времени сжималось до одной цифры
        ll.addWidget(QLabel("Старт:"))
        st = QHBoxLayout()
        self.start_edit = QTimeEdit()
        self.start_edit.setMinimumWidth(130)
        self.start_edit.setDisplayFormat("HH:mm")
        self.start_edit.setToolTip("Время начала эфира — сразу сохраняется в выбранном шаблоне")
        self.start_edit.timeChanged.connect(self._on_start_changed)
        # время старта сохраняется в шаблон с короткой задержкой: стрелки и колёсико меняют его шаг за шагом
        self._start_save = QTimer(self)
        self._start_save.setSingleShot(True)
        self._start_save.setInterval(600)
        self._start_save.timeout.connect(self._save_start)
        now_btn = QPushButton("Сейчас")
        now_btn.setToolTip("Начать эфир с текущей минуты")
        now_btn.clicked.connect(lambda: self.start_edit.setTime(QTime(self.clock().hour, self.clock().minute)))
        st.addWidget(self.start_edit, 1)
        st.addWidget(now_btn)
        ll.addLayout(st)

        # перерыв в любой момент: не по расписанию, план не сдвигает
        br = QHBoxLayout()
        self.break_btn = QPushButton("☕ Перерыв сейчас")
        self.break_btn.setToolTip("Заставка перерыва с отсчётом — на экран демонстрации прямо сейчас.\n"
                                  "Повторное нажатие — убрать заставку.")
        self.break_btn.clicked.connect(self._toggle_break)
        self.break_min = QSpinBox()
        self.break_min.setRange(1, 120)
        self.break_min.setSuffix(" мин")
        self.break_min.setMinimumWidth(110)
        self.break_min.setValue(max(1, min(120, self.settings.manual_break_min)))
        self.break_min.setToolTip("Сколько длится перерыв")
        self.break_min.valueChanged.connect(self._save_break_min)
        br.addWidget(QLabel("Перерыв:"))
        br.addWidget(self.break_min, 1)
        ll.addLayout(br)
        ll.addWidget(self.break_btn)     # во всю ширину: рядом со счётчиком в узкой панели не помещалось
        self.eyes_btn = QPushButton("👁 Зарядка сейчас")
        self.eyes_btn.setToolTip("Видео гимнастики для глаз — на экран демонстрации прямо сейчас.\n"
                                 "Повторное нажатие — убрать. Видео выбирается в ⚙ Настройках.")
        self.eyes_btn.clicked.connect(self._toggle_eyes)
        ll.addWidget(self.eyes_btn)

        self.run_btn = QPushButton("▶ Вести эфир", objectName="primary")
        self.run_btn.setCheckable(True)
        self.run_btn.setMinimumHeight(44)
        self.run_btn.setToolTip("Включить напоминания и заставку перерыва для выбранного шаблона")
        self.run_btn.toggled.connect(self._on_run)
        ll.addWidget(self.run_btn)
        body.addWidget(left)

        # ---- в центре: текущий блок
        hero = QFrame(objectName="card")
        hero.setMinimumWidth(240)        # отсчёт сам уменьшается — карточке хватает и узкой
        hl = QVBoxLayout(hero)
        hl.setContentsMargins(30, 26, 30, 26)
        hl.addStretch(1)
        self.hero_label = QLabel()
        self.hero_name = QLabel()
        self.hero_name.setWordWrap(True)
        self.hero_name.setStyleSheet("font-size: 26pt; font-weight: 700;")
        self.hero_timer = FitLabel(max_px=130)
        self.hero_sub = QLabel(objectName="muted")
        self.hero_bar = QProgressBar()
        self.hero_bar.setTextVisible(False)
        self.hero_bar.setRange(0, 1000)
        self.hero_demo = QLabel()
        self.hero_next = QLabel(objectName="muted")
        for w in (self.hero_sub, self.hero_demo, self.hero_next):
            w.setWordWrap(True)          # длинные строки переносятся — не отнимают ширину у повестки
        for w in (self.hero_label, self.hero_name, self.hero_timer, self.hero_sub, self.hero_bar, self.hero_demo,
                  self.hero_next):
            hl.addWidget(w)
        hl.addStretch(1)
        body.addWidget(hero, 4)

        # ---- справа: повестка
        self.agenda = QWidget()
        self.agenda_lay = QVBoxLayout(self.agenda)
        self.agenda_lay.setContentsMargins(6, 6, 6, 6)
        self.agenda_lay.setSpacing(4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.agenda)
        scroll.setObjectName("card")
        scroll.setMinimumWidth(340)      # названия блоков повестки должны читаться и в узком окне
        self.agenda_scroll = scroll
        body.addWidget(scroll, 5)

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(make_icon(), self)
        menu = QMenu()
        menu.addAction("Показать окно", self._show)
        self.tray_run = QAction("Вести эфир", menu, checkable=True)
        self.tray_run.toggled.connect(self.run_btn.setChecked)
        menu.addAction(self.tray_run)
        # перерыв в любой момент — прямо из трея, не открывая окно
        self.tray_break = menu.addMenu("☕ Перерыв сейчас")
        self.tray_break.aboutToShow.connect(self._fill_tray_break)
        menu.addAction("👁 Зарядка сейчас", self.start_eyes)
        menu.addAction("Убрать с экрана демонстрации", self._hide_demo)
        menu.addAction("Убрать все напоминания", self.notifier.clear)
        menu.addSeparator()
        menu.addAction("Выход", self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: r == QSystemTrayIcon.ActivationReason.Trigger and self._show())
        self.tray.setToolTip(APP_NAME)
        self.tray.show()

    # ================================================================ шаблоны
    def current_plan(self) -> Plan | None:
        item = self.plans.currentItem()
        return self.store.get(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _fill_plans(self, select: str = "") -> None:
        select = select or self.settings.current_plan
        self.plans.blockSignals(True)
        self.plans.clear()
        for p in self.store.plans:
            it = QListWidgetItem(f"{p.title}\n{p.start} · {p.total_min} мин")
            it.setData(Qt.ItemDataRole.UserRole, p.id)
            self.plans.addItem(it)
        self.plans.blockSignals(False)
        ids = [p.id for p in self.store.plans]
        self.plans.setCurrentRow(ids.index(select) if select in ids else 0)
        if self.plans.currentItem() is None:
            self._on_plan_selected()

    def _on_plan_selected(self, *_a) -> None:
        if self._start_save.isActive():
            new = self.current_plan()
            self._save_start(new.id if new else "")   # время прежнего шаблона — сохранить; выбран остаётся новый
        p = self.current_plan()
        if p is None:
            return
        if self.run_btn.isChecked() and self.scheduler.plan is not None and p.id != self.scheduler.plan.id:
            self.run_btn.setChecked(False)   # выбран другой шаблон — эфир по прежнему остановить
        self.settings.current_plan = p.id
        h, m = parse_time(p.start)
        self.start_edit.blockSignals(True)
        self.start_edit.setTime(QTime(h, m))
        self.start_edit.blockSignals(False)
        self._apply_plan()

    def _on_start_changed(self, *_a) -> None:
        p = self.current_plan()
        # запомнить, чьё это время: шаблон могут переключить раньше, чем сработает отложенное сохранение
        self._start_pending = (p.id, self.start_edit.time().toString("HH:mm")) if p else None
        if not self.run_btn.isChecked():
            self._apply_plan()       # эфир не идёт — табло сразу показывает новое время
        # во время эфира — только по окончании правки (_save_start): иначе стрелка вверх с 11:00 до 11:10
        # «прошла» бы через каждую минуту — лишние напоминания, а то и заставка перерыва у зрителей
        self._start_save.start()

    def _save_start(self, select: str = "") -> None:
        """Время из поля «Старт» — в шаблон (одно время на шаблон); список шаблонов показывает новое.
        select — какой шаблон выделить после (при переключении — уже новый)."""
        self._start_save.stop()
        pending, self._start_pending = getattr(self, "_start_pending", None), None
        if not pending:
            return
        if self.run_btn.isChecked():
            self._apply_plan()
        p = self.store.get(pending[0])
        if p is None or p.start == pending[1]:
            return
        p.start = pending[1]
        self._save_plans(select or self.settings.current_plan)
        log.info("Время старта «%s» сохранено в шаблоне: %s", p.title, p.start)

    def _set_start_quiet(self, h: int, m: int) -> None:
        """Время старта для этого эфира, без записи в шаблон: «начать с активности», продолжение после
        перезапуска. В шаблоне остаётся обычное время — иначе его навсегда сдвинул бы старт с середины."""
        self.start_edit.blockSignals(True)
        self.start_edit.setTime(QTime(h, m))
        self.start_edit.blockSignals(False)
        self._apply_plan()

    def _apply_plan(self, *_a) -> None:
        """План на сегодня: шаблон + время старта из поля «Старт»."""
        p = self.current_plan()
        if p is None:
            return
        today = copy.deepcopy(p)
        today.start = self.start_edit.time().toString("HH:mm")
        running = self.run_btn.isChecked()
        self.scheduler.set_plan(today)
        if running:
            self.scheduler.start()
            self._save_live()            # другое время старта — помнить и его
        self._rebuild_agenda()

    def _save_plans(self, select: str = "") -> None:
        live = self.scheduler.plan
        if self.run_btn.isChecked() and live is not None and self.store.get(live.id) is not None:
            select = live.id         # эфир идёт — выбранным остаётся его шаблон (смена шаблона остановила бы эфир)
        try:
            self.store.save()
        except OSError as e:
            log.error("Шаблоны не сохранены: %s", e)
            QMessageBox.warning(self, APP_NAME, f"Шаблоны не сохранены: {e}")
        self._fill_plans(select)

    def new_plan(self) -> None:
        title, ok = QInputDialog.getText(self, "Новый шаблон", "Название (например, «Практикум по Python»):")
        if ok and title.strip():
            p = default_plan()
            p.title = title.strip()
            self.store.plans.append(p)
            self._save_plans(p.id)
            self.edit_plan(p)        # именно новый: во время эфира выбранным остаётся шаблон эфира

    def edit_plan(self, plan: Plan | None = None) -> None:
        if self._start_save.isActive():
            self._save_start()
        p = plan or self.current_plan()
        if p is None:
            return
        dlg = PlanEditor(p, self, self.settings.lesson_min, self.settings.manual_break_min)
        ok = dlg.exec() and dlg.result_plan
        dlg.deleteLater()
        if ok:
            i = self.store.plans.index(p)
            self.store.plans[i] = dlg.result_plan
            self._save_plans(dlg.result_plan.id)

    def duplicate_plan(self) -> None:
        p = self.current_plan()
        if p is None:
            return
        c = plan_from({**plan_to(p), "id": "", "title": p.title + " (копия)"})   # без id — получит новый
        self.store.plans.insert(self.store.plans.index(p) + 1, c)
        self._save_plans(c.id)

    def delete_plan(self) -> None:
        p = self.current_plan()
        if p is None or len(self.store.plans) <= 1:
            return
        if QMessageBox.question(self, "Удалить шаблон", f"Удалить шаблон «{p.title}»?") \
                == QMessageBox.StandardButton.Yes:
            self.store.plans.remove(p)
            self._save_plans()

    def import_plan(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Импорт шаблона", str(TEMPLATES_DIR), "JSON (*.json)")
        if not path:
            return
        try:
            p = plan_from(json.loads(Path(path).read_text(encoding="utf-8-sig")), Path(path).stem)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Импорт", f"Не получилось: {e}")
            return
        if self.store.get(p.id):
            p = plan_from({**plan_to(p), "id": ""})   # такой уже есть — импорт как новый
        self.store.plans.append(p)
        self._save_plans(p.id)

    def export_plan(self) -> None:
        p = self.current_plan()
        if p is None:
            return
        # по умолчанию — в templates/: оттуда шаблоны получают коллеги вместе с папкой программы
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт шаблона", str(TEMPLATES_DIR / f"{p.title}.json"),
                                              "JSON (*.json)")
        if path:
            try:
                Path(path).write_text(json.dumps(plan_to(p), ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError as e:
                QMessageBox.warning(self, "Экспорт", f"Не получилось: {e}")

    # ================================================================ эфир
    def start_from(self, seg: Segment) -> None:
        """Начать эфир с активности seg: время старта — так, чтобы она начиналась сейчас; напоминание о ней — сразу."""
        now = self.clock()
        before = sum(a.min for a in self.scheduler.plan.schedule[:seg.index])
        start = now.replace(second=0, microsecond=0) - timedelta(minutes=before)
        if start.date() != now.date():
            QMessageBox.information(self, APP_NAME, "Эфир с этой активности начался бы вчера — выберите активность позже.")
            return
        log.info("Эфир с активности «%s» (старт %s)", seg.activity.name, f"{start:%H:%M}")
        self._set_start_quiet(start.hour, start.minute)
        if self.run_btn.isChecked():
            self.scheduler.rearm()       # эфир уже шёл — заново с этого места: напомнить о выбранной активности
        else:
            self.run_btn.setChecked(True)
        self._save_live()

    def _save_live(self) -> None:
        """Запомнить идущий эфир — чтобы после перезапуска таймера продолжить его, а не начинать сначала."""
        p = self.scheduler.plan
        live = (f"{p.id}|{self.start_edit.time().toString('HH:mm')}|{self.clock():%Y-%m-%d}"
                if self.run_btn.isChecked() and p is not None else "")
        if live != self.settings.live:
            self.settings.live = live
            self.settings.save()

    def _resume_live(self) -> None:
        """Таймер перезапустили во время эфира — продолжить тот же эфир (шаблон и время старта), если он не кончился."""
        try:
            pid, start, day = self.settings.live.split("|")
            h, m = parse_time(start)
        except ValueError:
            return
        now = self.clock()
        p = self.store.get(pid)
        if p is None or day != f"{now:%Y-%m-%d}":
            return
        end = now.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(minutes=p.total_min)
        if now >= end:
            return
        self._fill_plans(pid)
        self._set_start_quiet(h, m)
        self.run_btn.setChecked(True)
        log.info("Эфир продолжен после перезапуска: «%s», старт %s", p.title, start)

    def _on_run(self, on: bool) -> None:
        self.tray_run.blockSignals(True)
        self.tray_run.setChecked(on)
        self.tray_run.blockSignals(False)
        self.run_btn.setText("■ Остановить эфир" if on else "▶ Вести эфир")
        if on:
            log.info("Эфир: «%s», старт %s", self.scheduler.plan.title if self.scheduler.plan else "?",
                     self.start_edit.time().toString("HH:mm"))
            self.scheduler.start()
        else:
            self.scheduler.stop()
            self.notifier.clear()
            self._hide_demo()
            self._on_tick(self.scheduler.state())     # табло — сразу в покой
        self._save_live()

    def _save_note_pos(self, anchor: QPoint | None) -> None:
        self.settings.note_pos = f"{anchor.x()},{anchor.y()}" if anchor is not None else ""
        self.settings.save()

    def _remind(self, seg: Segment, heads_up: bool) -> None:
        self.notifier.show(seg, heads_up)
        if self.settings.sound:
            chime.play(self.settings.sound_volume)
        if self.settings.windows_toast:
            when = f"через {self.settings.heads_up_min} мин" if heads_up else "сейчас"
            self.tray.showMessage(APP_NAME, f"{when}: {seg.activity.name}", make_icon(), 8000)
        log.info("Напоминание (%s): %s", "заранее" if heads_up else "начало", seg.activity.name)

    def media_of(self, seg: Segment) -> str:
        """Файл активности на экран демонстрации: свой у блока, у зарядки для глаз — из настроек."""
        a = seg.activity
        return existing(a.media) or (existing(self.settings.eyes_media) if a.kind == "eyes" else "")

    def _show_break(self, seg: Segment) -> None:
        if self.overlay is not None and seg.index >= 0 and self._break_index == seg.index:
            return      # этот перерыв уже на экране (начали заранее — «☕ Начать перерыв»): пауза и ±мин остаются
        self._hide_demo()
        self._break_index = seg.index
        image = existing(seg.activity.media) or existing(self.settings.break_image)
        self.overlay = BreakOverlay(screens.demo_screen(self.settings), seg.end, self.clock, image, seg.activity.name,
                                    self.settings.break_text_color)
        o = self.overlay
        o.closed.connect(lambda: self.overlay is o and setattr(self, "overlay", None))
        o.show()
        o.raise_()
        self._show_break_panel(o)
        log.info("Перерыв: заставка до %s", f"{seg.end:%H:%M}")

    def _show_break_panel(self, o: BreakOverlay) -> None:
        """Пульт перерыва — на монитор управления: отсчёт, пауза, ±1 мин, заново, убрать. Заменяет карточку."""
        for c in [c for c in self.notifier.cards if c.seg.activity.breaks]:
            self.notifier.close(c)
        panel = BreakPanel(o, screens.control_screen(self.settings), parse_pos(self.settings.player_pos))
        self.break_panel = panel
        panel.stop_requested.connect(lambda: self._remove_from_demo(o, "перерыв"))
        panel.dropped.connect(self._save_player_pos)
        o.closed.connect(panel.close)            # заставку убрали — пульт уходит вместе с ней
        panel.destroyed.connect(lambda: self.break_panel is panel and setattr(self, "break_panel", None))
        panel.place()
        panel.show()

    def _action_label(self, seg: Segment) -> str:
        """Кнопка действия в напоминании — только если активности есть что показать зрителям."""
        if seg.activity.breaks:
            return "☕ Начать перерыв"
        path = self.media_of(seg)
        if not path:
            return ""
        return "▶ Показать видео" if is_video(path) else "▶ Показать картинку"

    def _start_activity(self, seg: Segment) -> None:
        """Кнопка действия в напоминании: перерыв — заставка, у активности с файлом — файл на экран демонстрации."""
        if seg.activity.breaks:
            if self.overlay is None:
                self._show_break(seg)
            return
        path = self.media_of(seg)
        if path:
            self._show_media(path)

    def _show_media(self, path: str) -> None:
        """Видео или картинка — на весь экран демонстрации (видео само закроется в конце)."""
        self._hide_demo()
        self.media = MediaOverlay(screens.demo_screen(self.settings), path)
        m = self.media
        m.closed.connect(lambda: self.media is m and setattr(self, "media", None))
        m.show()
        m.raise_()
        if m.player is not None:
            self._show_player(m, Path(path).stem)
        self._sync_break_btn()
        log.info("На экран демонстрации: %s", Path(path).name)

    def _show_player(self, m: MediaOverlay, title: str) -> None:
        """Пульт видео — на монитор управления: зрители видят только само видео."""
        panel = PlayerPanel(m.player, m.audio, title, screens.control_screen(self.settings),
                            parse_pos(self.settings.player_pos))
        self.player_panel = panel
        panel.stop_requested.connect(lambda: self._remove_from_demo(m, "видео"))
        panel.dropped.connect(self._save_player_pos)
        m.closed.connect(panel.close)            # видео кончилось или его убрали — пульт уходит вместе с ним
        panel.destroyed.connect(lambda: self.player_panel is panel and setattr(self, "player_panel", None))
        panel.place()
        panel.show()

    def _save_player_pos(self, anchor: QPoint) -> None:
        self.settings.player_pos = f"{anchor.x()},{anchor.y()}"
        self.settings.save()

    def start_break(self, minutes: int | None = None) -> None:
        """Перерыв в любой момент: заставка на экран демонстрации, пульт с отсчётом — на монитор управления."""
        minutes = minutes or self.break_min.value()
        now = self.clock()
        seg = Segment(-1, Activity("ПЕРЕРЫВ", DEMO_NONE, minutes, remind=True, is_break=True),
                      now, now + timedelta(minutes=minutes))
        self._show_break(seg)
        log.info("Перерыв вне расписания: %d мин", minutes)
        self._sync_break_btn()

    def _fill_tray_break(self) -> None:
        m = self.tray_break
        m.clear()
        own = self.break_min.value()
        m.addAction(f"☕ {own} мин (как в окне)", lambda: self.start_break(own))
        m.addSeparator()
        for n in (5, 10, 15, 20):
            if n != own:
                m.addAction(f"{n} мин", lambda n=n: self.start_break(n))
        m.addSeparator()
        hide = m.addAction("■ Убрать заставку", self._hide_break)
        hide.setEnabled(self.overlay is not None)

    def start_eyes(self) -> bool:
        """Зарядка для глаз в любой момент: видео гимнастики — на экран демонстрации. False — видео не найдено."""
        path = existing(self.settings.eyes_media)
        if not path:
            self.tray.showMessage(APP_NAME, "Видео гимнастики не найдено: выберите его в ⚙ Настройки → "
                                  "«Гимнастика для глаз».", make_icon(), 6000)
            return False
        self._show_media(path)
        log.info("Зарядка вне расписания: %s", Path(path).name)
        return True

    def _toggle_eyes(self) -> None:
        if self.media is not None:
            self._hide_demo()
        else:
            self.start_eyes()

    def _toggle_break(self) -> None:
        if self.overlay is not None:
            self._hide_break()
        else:
            self.start_break()

    def _save_break_min(self, v: int) -> None:
        self.settings.manual_break_min = v
        self.settings.save()

    def _sync_break_btn(self) -> None:
        for btn, on, label in ((self.break_btn, self.overlay is not None, "☕ Перерыв сейчас"),
                               (self.eyes_btn, self.media is not None, "👁 Зарядка сейчас")):
            text = "■ Убрать с экрана" if on else label
            if btn.text() != text:
                btn.setText(text)

    def _remove_from_demo(self, w, what: str) -> None:
        """«Убрать» на пульте: закрыть именно ту заставку или видео, к которому пульт относится
        (не полагаясь на то, что окно таймера считает показанным сейчас)."""
        log.info("Пульт: «Убрать» (%s)", what)
        if isValid(w):
            w.close()                    # closed → пульт закроется сам, ссылка в окне таймера обнулится
        if self.overlay is w:
            self.overlay = None
        if self.media is w:
            self.media = None
        self._sync_break_btn()

    def _hide_break(self) -> None:
        if self.overlay is not None:
            o, self.overlay = self.overlay, None
            o.close()
        self._sync_break_btn()

    def _hide_demo(self) -> None:
        """Убрать с экрана демонстрации всё наше: заставку перерыва и файл активности."""
        if self.media is not None:
            m, self.media = self.media, None
            m.close()
        self._hide_break()

    def _on_finished(self) -> None:
        log.info("Эфир завершён по расписанию")

    # ================================================================ табло
    def _rebuild_agenda(self) -> None:
        while self.agenda_lay.count():
            w = self.agenda_lay.takeAt(0).widget()
            if w:
                w.setParent(None)        # убрать сразу: иначе старые строки мелькают поверх новых до удаления
                w.deleteLater()
        segs = self.scheduler.segs
        self.rows = [AgendaRow(s) for s in segs]
        for r in self.rows:
            r.start_here.connect(self.start_from)
        # каждый урок — своя панель с заголовком; перерывы — между панелями
        self.lesson_panels = []
        panel = None
        for s, r in zip(segs, self.rows, strict=True):
            if s.activity.breaks:
                panel = None
                self.agenda_lay.addWidget(r)
                continue
            if panel is None:
                group = next(g for g in lessons(segs) if g[0] is s)
                plan = self.scheduler.plan
                limit = plan.lesson_min if plan.lesson_min is not None else self.settings.lesson_min
                n = len(self.lesson_panels)
                panel = LessonPanel(n + 1, group, limit, plan.lesson_name(n))
                self.lesson_panels.append(panel)
                self.agenda_lay.addWidget(panel)
            panel.add_row(r)
        self.agenda_lay.addStretch(1)
        self.overall.set_segments(segs, self.scheduler.plan.lesson_names)
        self._last_index = -2
        self._on_tick(self.scheduler.state())

    def _on_tick(self, st: State) -> None:
        self._sync_break_btn()   # заставку могли убрать щелчком по ней или из напоминания
        now = self.clock()
        self.clock_lbl.setText(f"{now:%H:%M:%S}")
        self.today.setText(now.strftime("%d.%m.%Y"))
        segs = self.scheduler.segs
        if not segs:
            return
        if segs[0].start.date() != now.date() and not self.run_btn.isChecked():
            self._apply_plan()           # наступил новый день (таймер ночевал в трее) — повестка на сегодня
            return
        if not self.run_btn.isChecked():
            self._show_idle(segs)        # эфир не идёт — табло стоит: без отсчёта и «текущего» блока
            return
        self.overall.set_now(now)
        begin, end = segs[0].start, segs[-1].end
        if now < begin:
            text = f"до начала {fmt_left(begin - now)} · всего {fmt_left(end - begin)}"
        elif now < end:
            passed = timedelta(seconds=int((now - begin).total_seconds()))   # прошедшее — вниз, до целых секунд
            text = f"прошло {fmt_left(passed)} · осталось {fmt_left(end - now)}"
        else:
            text = f"всего {fmt_left(end - begin)} · {begin:%H:%M}–{end:%H:%M}"
        if self.overall_lbl.text() != text:
            self.overall_lbl.setText(text)
        for p in self.lesson_panels:
            p.set_state("now" if st.index >= 0 and p.contains(st.index) else
                        ("past" if now >= p.segs[-1].end else ""))
        for i, r in enumerate(self.rows):
            mode = "now" if i == st.index else ("past" if now >= r.seg.end else
                                                ("next" if (st.phase == "before" and i == 0) or i == st.index + 1
                                                 and st.index >= 0 else ""))
            if getattr(r, "_mode", None) != mode:
                r._mode = mode
                r.set_mode(mode)
        if st.index != self._last_index:
            self._last_index = st.index
            if 0 <= st.index < len(self.rows):   # повестка могла ещё не успеть перестроиться под новый шаблон
                self.agenda_scroll.ensureWidgetVisible(self.rows[st.index], 0, 60)

        if st.phase == "before":
            self.hero_label.setText("ДО НАЧАЛА")
            self.hero_name.setText(self.scheduler.plan.title)
            self.hero_timer.setText(fmt_left(st.remaining))
            self.hero_sub.setText(f"Старт в {segs[0].start:%H:%M} · первый блок «{segs[0].activity.name}»")
            self.hero_bar.setValue(0)
            self.hero_demo.setText("")
            self.hero_next.setText("")
            pill = ("До начала " + fmt_left(st.remaining), style.AMBER)
        elif st.phase == "running":
            s = segs[st.index]
            self.hero_label.setText("СЕЙЧАС")
            self.hero_name.setText(s.activity.name)
            self.hero_timer.setText(fmt_left(st.remaining))
            self.hero_sub.setText(f"{s.start:%H:%M} – {s.end:%H:%M} · {s.activity.min} мин")
            self.hero_bar.setValue(int(st.progress * 1000))
            demo = DEMO_TEXT.get(s.activity.demo, "")
            color = style.ON if s.activity.demo == DEMO_ON else style.DIM
            self.hero_demo.setText(f"<span style='color:{color}; font-weight:600'>{demo}</span>" if demo else "")
            nxt = segs[st.index + 1] if st.index + 1 < len(segs) else None
            self.hero_next.setText(f"Далее: {nxt.activity.name} в {nxt.start:%H:%M}" if nxt else "Последний блок")
            pill = ("В эфире", style.ON)
        else:
            self.hero_label.setText("ЭФИР ЗАВЕРШЁН")
            self.hero_name.setText("Спасибо!")
            self.hero_timer.setText(fmt_left(segs[-1].end - segs[0].start))
            self.hero_sub.setText(f"Общая длительность · {segs[0].start:%H:%M} – {segs[-1].end:%H:%M}")
            self.hero_bar.setValue(1000)
            self.hero_demo.setText("")
            self.hero_next.setText("")
            pill = ("Завершено", style.MUTED)
        self._set_status(*pill)

    def _set_status(self, text: str, color: str) -> None:
        self.status.setText(f"<span style='color:{color}; font-weight:600'>● {text}</span>")
        tip = f"{APP_NAME}: {self.hero_name.text()} · {self.hero_timer.text()}"
        if self.tray.toolTip() != tip:
            self.tray.setToolTip(tip)

    def _show_idle(self, segs: list[Segment]) -> None:
        """Эфир не идёт (не включали или остановили): шаблон в покое — без отсчёта, подсветки и заполнения полосы."""
        begin, end = segs[0].start, segs[-1].end
        self.overall.set_now(None)
        text = f"всего {fmt_left(end - begin)} · {begin:%H:%M}–{end:%H:%M}"
        if self.overall_lbl.text() != text:
            self.overall_lbl.setText(text)
        for p in self.lesson_panels:
            p.set_state("")
        for r in self.rows:
            if getattr(r, "_mode", None) != "":
                r._mode = ""
                r.set_mode("")
        self._last_index = -2            # при включении — прокрутить к текущему блоку
        self.hero_label.setText("ЭФИР НЕ ИДЁТ")
        self.hero_name.setText(self.scheduler.plan.title)
        self.hero_timer.setText(fmt_left(end - begin))
        self.hero_sub.setText(f"Старт в {begin:%H:%M} · всего {self.scheduler.plan.total_min} мин")
        self.hero_bar.setValue(0)
        self.hero_demo.setText("")
        self.hero_next.setText("Начать: «▶ Вести эфир» — по расписанию, двойной щелчок по активности — с неё")
        self._set_status("Эфир не идёт", style.MUTED)

    # ================================================================ окно и выход
    # ================================================================ тема
    def _fit_overall_lbl(self) -> None:
        """Постоянная ширина подписи «прошло · осталось» — по самому длинному из её вариантов.
        Иначе полоса эфира рядом сдвигается каждую секунду и при смене «38:18» на «1:38:18»."""
        lbl = self.overall_lbl
        lbl.ensurePolished()
        fm = QFontMetrics(lbl.font())
        samples = ("до начала 8:88:88 · всего 8:88:88", "прошло 8:88:88 · осталось 8:88:88",
                   "всего 8:88:88 · 88:88–88:88")
        lbl.setFixedWidth(max(fm.horizontalAdvance(t) for t in samples) + 6)

    def set_theme(self, name: str) -> None:
        """Сменить тему на лету: общая таблица стилей и всё, что оформлено своими цветами (повестка, карточки,
        пульты). Эфир не прерывается; экран демонстрации не меняется."""
        style.apply(name)
        QApplication.instance().setStyleSheet(style.APP_QSS)
        if self.settings.theme != style.current:
            self.settings.theme = style.current
            self.settings.save()
        self._style_theme()
        self._fit_overall_lbl()
        self._rebuild_agenda()
        self.overall.update()
        for c in self.notifier.cards:
            c.restyle()
        for panel in (self.player_panel, self.break_panel):
            if panel is not None and isValid(panel):
                panel.restyle()
        log.info("Тема: %s", style.THEME_NAMES[style.current])

    def _style_theme(self) -> None:
        self.brand.setText(f"<b style='color:{style.BRAND_BRIGHT}; font-size:20pt'>1Т</b>"
                           f"&nbsp;&nbsp;<span style='color:{style.MUTED}; font-size:12pt'>Таймер вебинара</span>")
        self.hero_label.setStyleSheet(f"color: {style.BRAND_BRIGHT}; font-weight: 700; letter-spacing: 3px;")
        self.hero_timer.css = f"font-weight: 800; color: {style.BRAND_BRIGHT};"
        self.hero_timer.px = 0                   # пересчитать и перекрасить
        self.hero_timer._fit()
        dark = style.current == "dark"
        self.theme_btn.setText("☀" if dark else "🌙")
        self.theme_btn.setToolTip("Светлая тема" if dark else "Тёмная тема")

    def _auto_check_updates(self) -> None:
        if not (self.settings.auto_update_check and updater.can_update()) or self._update_check is not None:
            return
        self._update_check = updater.CheckThread(self)
        self._update_check.found.connect(self._on_update_found)
        self._update_check.finished.connect(lambda: setattr(self, "_update_check", None))
        self._update_check.start()

    def _on_update_found(self, rel) -> None:
        if rel is None:
            return
        first = self.update_release is None or self.update_release.version != rel.version
        self.update_release = rel
        self.update_btn.setText(f"⬆ Обновление {rel.version}")
        self.update_btn.show()
        if first:
            self.tray.showMessage(APP_NAME, f"Вышла версия {rel.version}. Установить — ⚙ Настройки → «Обновления».",
                                  make_icon(), 8000)
            log.info("Доступно обновление %s", rel.version)

    def open_settings(self) -> None:
        before = copy.deepcopy(self.settings)
        dlg = SettingsDialog(self.settings, self, self.update_release, self.run_btn.isChecked)
        dlg.install_started.connect(self.quit_app)     # установщик закроет и снова откроет таймер
        ok = dlg.exec()
        if dlg.release is not None:
            self._on_update_found(dlg.release)
        dlg.deleteLater()
        if ok:
            # только то, что поменяли в окне: карточки и пульт могли передвинуть, пока оно было открыто
            new = dlg.result_settings()
            for k, v in vars(new).items():
                if v != getattr(before, k):
                    setattr(self.settings, k, v)
            if self.settings.theme != style.current:
                self.set_theme(self.settings.theme)
            self.scheduler.heads_up_min = self.settings.heads_up_min
            self.settings.save()
            self.notifier.anchor = parse_pos(self.settings.note_pos)
            self.notifier.layout()
            self._rebuild_agenda()               # продолжительность урока — в заголовках панелей

    def _show(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e) -> None:
        if self._start_save.isActive():
            self._save_start()           # время старта изменили только что — не потерять
        self.settings.window_geometry = bytes(self.saveGeometry().toBase64()).decode()
        self.settings.save()
        if not self._quitting and self.tray.isVisible():
            e.ignore()       # закрытие окна — в трей: эфир продолжается
            self.hide()
            if self.run_btn.isChecked():
                self.tray.showMessage(APP_NAME, "Эфир ведётся, таймер — в трее.", make_icon(), 3000)
            return
        self.notifier.clear()
        self._hide_demo()
        self.tray.hide()
        super().closeEvent(e)

    def quit_app(self) -> None:
        self._quitting = True
        self.close()
        from PySide6.QtWidgets import QApplication
        QApplication.quit()
