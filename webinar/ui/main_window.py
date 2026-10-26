"""Главное окно: шаблоны вебинаров, табло эфира (как «Повестка эфира»), значок в трее."""
from __future__ import annotations

import copy
import json
import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QByteArray, QPoint, QPointF, QRectF, Qt, QTime
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QFileDialog, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton,
                               QScrollArea, QSystemTrayIcon, QTimeEdit, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from ..model import DEMO_NONE, DEMO_ON, DEMO_TEXT, Plan, Segment, State, default_plan, fmt_left, parse_time, plan_from, \
    plan_to
from ..scheduler import Scheduler
from ..store import PlanStore, Settings
from . import screens, style
from .editor import PlanEditor
from .notify import Notifier, parse_pos
from .overlay import BreakOverlay, MediaOverlay
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


def _sound() -> None:
    try:
        import winsound
        winsound.PlaySound("SystemNotification", winsound.SND_ALIAS | winsound.SND_ASYNC)
    except Exception:   # нет звука — не беда
        pass


class AgendaRow(QFrame):
    def __init__(self, seg: Segment) -> None:
        super().__init__()
        self.seg = seg
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

    def set_mode(self, mode: str) -> None:
        """mode: now | past | next | ""."""
        a = self.seg.activity
        color = {"break": style.AMBER, "eyes": style.EYE}.get(a.kind, style.INK)
        bg = {"now": "rgba(142,77,255,0.28)", "past": "transparent"}.get(
            mode, "rgba(95,208,160,0.08)" if a.kind == "eyes" else
            ("rgba(255,255,255,0.05)" if a.kind == "break" else "transparent"))
        border = style.BRAND if mode == "now" else (style.LINE if mode == "next" else "transparent")
        self.setStyleSheet(f"AgendaRow {{ background: {bg}; border: 1px solid {border}; border-radius: 12px; }}")
        dim = mode == "past"
        self.name.setStyleSheet(f"color: {style.MUTED if dim else ('white' if mode == 'now' else color)};"
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
        self.rows: list[AgendaRow] = []
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
        self.notifier.on_hide_break = self._hide_break
        self.notifier.anchor = parse_pos(settings.note_pos)
        self.notifier.on_moved = self._save_note_pos
        self.notifier.on_next = self._start_activity

        self._build()
        self._build_tray()
        self._fill_plans()
        if settings.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(settings.window_geometry.encode()))
        self.scheduler.watch()   # табло идёт всегда; напоминания — только когда эфир ведётся

    # ================================================================ интерфейс
    def _build(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(10)

        head = QHBoxLayout()
        brand = QLabel(f"<b style='color:{style.BRAND_BRIGHT}; font-size:20pt'>1Т</b>"
                       f"&nbsp;&nbsp;<span style='color:{style.MUTED}; font-size:12pt'>Таймер вебинара</span>")
        head.addWidget(brand)
        head.addStretch(1)
        self.today = QLabel(objectName="muted")
        self.clock_lbl = QLabel()
        self.clock_lbl.setStyleSheet("font-size: 18pt; font-weight: 700;")
        self.status = QLabel()
        gear = QPushButton("⚙ Настройки")
        gear.clicked.connect(self.open_settings)
        for w in (self.today, self.clock_lbl, self.status, gear):
            head.addWidget(w)
        outer.addLayout(head)
        self.overall = QProgressBar()
        self.overall.setTextVisible(False)
        self.overall.setRange(0, 1000)
        self.overall.setFixedHeight(5)
        outer.addWidget(self.overall)

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
        st = QHBoxLayout()
        st.addWidget(QLabel("Старт сегодня:"))
        self.start_edit = QTimeEdit()
        self.start_edit.setDisplayFormat("HH:mm")
        self.start_edit.setToolTip("Время начала эфира сегодня (в шаблоне сохраняется кнопкой «Изменить»)")
        self.start_edit.timeChanged.connect(self._apply_plan)
        now_btn = QPushButton("Сейчас")
        now_btn.setToolTip("Начать эфир с текущей минуты")
        now_btn.clicked.connect(lambda: self.start_edit.setTime(QTime(self.clock().hour, self.clock().minute)))
        st.addWidget(self.start_edit, 1)
        st.addWidget(now_btn)
        ll.addLayout(st)
        self.run_btn = QPushButton("▶ Вести эфир", objectName="primary")
        self.run_btn.setCheckable(True)
        self.run_btn.setMinimumHeight(44)
        self.run_btn.setToolTip("Включить напоминания и заставку перерыва для выбранного шаблона")
        self.run_btn.toggled.connect(self._on_run)
        ll.addWidget(self.run_btn)
        body.addWidget(left)

        # ---- в центре: текущий блок
        hero = QFrame(objectName="card")
        hero.setMinimumWidth(380)
        hl = QVBoxLayout(hero)
        hl.setContentsMargins(30, 26, 30, 26)
        hl.addStretch(1)
        self.hero_label = QLabel()
        self.hero_label.setStyleSheet(f"color: {style.BRAND_BRIGHT}; font-weight: 700; letter-spacing: 3px;")
        self.hero_name = QLabel()
        self.hero_name.setWordWrap(True)
        self.hero_name.setStyleSheet("font-size: 26pt; font-weight: 700;")
        self.hero_timer = QLabel()
        self.hero_timer.setStyleSheet(f"font-size: 72pt; font-weight: 800; color: {style.BRAND_BRIGHT};")
        self.hero_sub = QLabel(objectName="muted")
        self.hero_bar = QProgressBar()
        self.hero_bar.setTextVisible(False)
        self.hero_bar.setRange(0, 1000)
        self.hero_demo = QLabel()
        self.hero_next = QLabel(objectName="muted")
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
        self.agenda_scroll = scroll
        body.addWidget(scroll, 5)

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(make_icon(), self)
        menu = QMenu()
        menu.addAction("Показать окно", self._show)
        self.tray_run = QAction("Вести эфир", menu, checkable=True)
        self.tray_run.toggled.connect(self.run_btn.setChecked)
        menu.addAction(self.tray_run)
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

    def _apply_plan(self, *_a) -> None:
        """План на сегодня: шаблон + время старта из поля «Старт сегодня»."""
        p = self.current_plan()
        if p is None:
            return
        today = copy.deepcopy(p)
        today.start = self.start_edit.time().toString("HH:mm")
        running = self.run_btn.isChecked()
        self.scheduler.set_plan(today)
        if running:
            self.scheduler.start()
        self._rebuild_agenda()

    def _save_plans(self, select: str = "") -> None:
        self.store.save()
        self._fill_plans(select)

    def new_plan(self) -> None:
        title, ok = QInputDialog.getText(self, "Новый шаблон", "Название (например, «Практикум по Python»):")
        if ok and title.strip():
            p = default_plan()
            p.title = title.strip()
            self.store.plans.append(p)
            self._save_plans(p.id)
            self.edit_plan()

    def edit_plan(self) -> None:
        p = self.current_plan()
        if p is None:
            return
        dlg = PlanEditor(p, self)
        if dlg.exec() and dlg.result_plan:
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
        path, _ = QFileDialog.getOpenFileName(self, "Импорт шаблона", "", "JSON (*.json)")
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
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт шаблона", f"{p.title}.json", "JSON (*.json)")
        if path:
            Path(path).write_text(json.dumps(plan_to(p), ensure_ascii=False, indent=2), encoding="utf-8")

    # ================================================================ эфир
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

    def _save_note_pos(self, anchor: QPoint | None) -> None:
        self.settings.note_pos = f"{anchor.x()},{anchor.y()}" if anchor is not None else ""
        self.settings.save()

    def _remind(self, seg: Segment, heads_up: bool) -> None:
        self.notifier.show(seg, heads_up)
        if self.settings.sound:
            _sound()
        if self.settings.windows_toast:
            when = f"через {self.settings.heads_up_min} мин" if heads_up else "сейчас"
            self.tray.showMessage(APP_NAME, f"{when}: {seg.activity.name}", make_icon(), 8000)
        log.info("Напоминание (%s): %s", "заранее" if heads_up else "начало", seg.activity.name)

    def media_of(self, seg: Segment) -> str:
        """Файл активности на экран демонстрации: свой у блока, у зарядки для глаз — из настроек."""
        a = seg.activity
        path = a.media or (self.settings.eyes_media if a.kind == "eyes" else "")
        return path if path and Path(path).is_file() else ""

    def _show_break(self, seg: Segment) -> None:
        self._hide_demo()
        image = seg.activity.media or self.settings.break_image
        self.overlay = BreakOverlay(screens.demo_screen(self.settings), seg.end, self.clock, image, seg.activity.name)
        o = self.overlay
        o.closed.connect(lambda: self.overlay is o and setattr(self, "overlay", None))
        o.show()
        o.raise_()
        log.info("Перерыв: заставка до %s", f"{seg.end:%H:%M}")

    def _start_activity(self, seg: Segment) -> None:
        """«Далее ▶» в напоминании: перерыв — заставка, у активности с файлом — файл на экран демонстрации."""
        if seg.activity.breaks:
            if self.overlay is None:
                self._show_break(seg)
            return
        path = self.media_of(seg)
        if not path:
            return
        self._hide_demo()
        self.media = MediaOverlay(screens.demo_screen(self.settings), path)
        m = self.media
        m.closed.connect(lambda: self.media is m and setattr(self, "media", None))
        m.show()
        m.raise_()
        log.info("На экран демонстрации: %s", Path(path).name)

    def _hide_break(self) -> None:
        if self.overlay is not None:
            o, self.overlay = self.overlay, None
            o.close()

    def _hide_demo(self) -> None:
        """Убрать с экрана демонстрации всё наше: заставку перерыва и файл активности."""
        self._hide_break()
        if self.media is not None:
            m, self.media = self.media, None
            m.close()

    def _on_finished(self) -> None:
        log.info("Эфир завершён по расписанию")

    # ================================================================ табло
    def _rebuild_agenda(self) -> None:
        while self.agenda_lay.count():
            w = self.agenda_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.rows = [AgendaRow(s) for s in self.scheduler.segs]
        for r in self.rows:
            self.agenda_lay.addWidget(r)
        self.agenda_lay.addStretch(1)
        self._last_index = -2
        self._on_tick(self.scheduler.state())

    def _on_tick(self, st: State) -> None:
        now = self.clock()
        self.clock_lbl.setText(f"{now:%H:%M:%S}")
        self.today.setText(now.strftime("%d.%m.%Y"))
        segs = self.scheduler.segs
        if not segs:
            return
        self.overall.setValue(int(st.overall * 1000))
        running = self.run_btn.isChecked()
        for i, r in enumerate(self.rows):
            mode = "now" if i == st.index else ("past" if now >= r.seg.end else
                                                ("next" if (st.phase == "before" and i == 0) or i == st.index + 1
                                                 and st.index >= 0 else ""))
            if getattr(r, "_mode", None) != mode:
                r._mode = mode
                r.set_mode(mode)
        if st.index != self._last_index:
            self._last_index = st.index
            if st.index >= 0:
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
        if not running and st.phase != "after":
            pill = (pill[0] + " · напоминания выкл.", style.MUTED)
        self.status.setText(f"<span style='color:{pill[1]}; font-weight:600'>● {pill[0]}</span>")
        tip = f"{APP_NAME}: {self.hero_name.text()} · {self.hero_timer.text()}"
        if self.tray.toolTip() != tip:
            self.tray.setToolTip(tip)

    # ================================================================ окно и выход
    def open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            new = dlg.result_settings()
            for k, v in vars(new).items():
                setattr(self.settings, k, v)
            self.scheduler.heads_up_min = self.settings.heads_up_min
            self.settings.save()
            self.notifier.anchor = parse_pos(self.settings.note_pos)
            self.notifier.layout()

    def _show(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e) -> None:
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
