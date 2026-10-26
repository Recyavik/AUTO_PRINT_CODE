"""Тесты таймера вебинара: повестка по часам, события напоминаний, шаблоны, мониторы, окна.

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ.setdefault("WEBINAR_DATA", tempfile.mkdtemp(prefix="webinar-test-"))
os.environ.setdefault("AUTOPRINT_DATA", tempfile.mkdtemp(prefix="autoprint-test-"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from webinar.model import (DEMO_NONE, DEMO_OFF, DEMO_ON, Activity, Plan, default_plan, fmt_left,  # noqa: E402
                           plan_from, plan_to, segments, state_at)
from webinar.scheduler import Scheduler  # noqa: E402

app = QApplication.instance() or QApplication([])
DAY = date(2026, 10, 26)


def at(hm: str, sec: int = 0) -> datetime:
    h, m = map(int, hm.split(":"))
    return datetime(2026, 10, 26, h, m, sec)


class FakeClock:
    def __init__(self, t: datetime) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t


class ModelTest(unittest.TestCase):
    def test_segments_follow_the_clock(self):
        segs = segments(default_plan(), DAY)
        self.assertEqual(segs[0].start, at("11:00"))
        self.assertEqual([s.start.strftime("%H:%M") for s in segs[:4]], ["11:00", "11:01", "11:06", "11:20"])
        self.assertEqual(segs[-1].end, at("11:00") + timedelta(minutes=default_plan().total_min))

    def test_state(self):
        segs = segments(default_plan(), DAY)
        self.assertEqual(state_at(segs, at("10:59")).phase, "before")
        st = state_at(segs, at("11:21", 30))
        self.assertEqual((st.phase, segs[st.index].activity.name), ("running", "Зарядка для глаз"))
        self.assertEqual(fmt_left(st.remaining), "03:30")
        self.assertEqual(state_at(segs, at("13:00")).phase, "after")

    def test_defaults_remind_and_break(self):
        a = {x.name: x for x in default_plan().schedule}
        self.assertFalse(a["ПРЕЗЕНТАЦИЯ"].reminds, "о презентации не напоминаем")
        self.assertTrue(a["Зарядка для глаз"].reminds and a["Выводы"].reminds)
        self.assertTrue(a["ПЕРЕРЫВ"].breaks and a["ПЕРЕРЫВ"].kind == "break")
        self.assertEqual(a["Зарядка для глаз"].kind, "eyes")
        self.assertFalse(Activity("Выводы", remind=False).reminds, "явная отметка важнее")
        self.assertTrue(Activity("Отдых", is_break=True).breaks)

    def test_json_from_agenda_page_and_roundtrip(self):
        page = {"start": "9:05", "scale": "medium",
                "schedule": [{"name": "Приветствие", "demo": "on", "min": 1}, {"name": "Перерыв", "demo": "none", "min": 10}]}
        p = plan_from(page, "Из HTML")
        self.assertEqual((p.title, p.start, len(p.schedule)), ("Из HTML", "09:05", 2))
        back = plan_from(json.loads(json.dumps(plan_to(p))))
        self.assertEqual(plan_to(back), plan_to(p))

    def test_bad_json_messages(self):
        for bad, text in (({"start": "25:00", "schedule": [{"name": "a", "min": 1}]}, "времени"),
                          ({"start": "11:00", "schedule": []}, "пустое"),
                          ({"start": "11:00", "schedule": [{"name": "", "min": 1}]}, "пустое название"),
                          ({"start": "11:00", "schedule": [{"name": "a", "min": 0}]}, "больше нуля"),
                          ([1, 2], "объект")):
            with self.assertRaises(ValueError) as e:
                plan_from(bad)
            self.assertIn(text, str(e.exception).lower().replace("время", "времени"))


PLAN = Plan("Тест", "11:00", [Activity("Приветствие", DEMO_ON, 2), Activity("Зарядка", DEMO_OFF, 3),
                              Activity("ПРЕЗЕНТАЦИЯ", DEMO_ON, 5), Activity("ПЕРЕРЫВ", DEMO_NONE, 4),
                              Activity("Выводы", DEMO_OFF, 2)])


class SchedulerTest(unittest.TestCase):
    def make(self, t: datetime):
        clock = FakeClock(t)
        s = Scheduler(clock)
        events: list[tuple[str, str]] = []
        s.heads_up.connect(lambda seg: events.append(("head", seg.activity.name)))
        s.block_started.connect(lambda seg: events.append(("start", seg.activity.name)))
        s.break_started.connect(lambda seg: events.append(("break+", seg.activity.name)))
        s.break_ended.connect(lambda seg: events.append(("break-", seg.activity.name)))
        s.finished.connect(lambda: events.append(("finished", "")))
        s.set_plan(PLAN, DAY)
        return s, clock, events

    def walk(self, s, clock, until: datetime, step=timedelta(seconds=15)):
        while clock.t < until:
            clock.t += step
            s.poll()

    def test_whole_webinar_events_in_order_once(self):
        s, clock, events = self.make(at("10:58"))
        s.start()
        self.walk(s, clock, at("11:20"))
        self.assertEqual(events, [
            ("head", "Зарядка"), ("start", "Зарядка"),            # за минуту и в начале
            ("head", "ПЕРЕРЫВ"), ("break+", "ПЕРЕРЫВ"), ("start", "ПЕРЕРЫВ"),
            ("head", "Выводы"),                                   # за минуту до конца перерыва — пора возвращаться
            ("break-", "ПЕРЕРЫВ"), ("start", "Выводы"),           # конец перерыва — начало «Выводов»
            ("finished", ""),
        ], "о приветствии и презентации не напоминаем; каждое событие — один раз")

    def test_nothing_before_start_button(self):
        s, clock, events = self.make(at("11:00"))
        self.walk(s, clock, at("11:20"))
        self.assertEqual(events, [], "пока эфир не включён — только табло")

    def test_started_late_reports_current_block_only(self):
        s, clock, events = self.make(at("11:12"))          # посреди перерыва (11:10–11:14)
        s.start()
        self.assertEqual(events, [("break+", "ПЕРЕРЫВ"), ("start", "ПЕРЕРЫВ")], "о прошлых блоках — ничего")

    def test_stop_hides_break(self):
        s, clock, events = self.make(at("11:11"))
        s.start()
        s.stop()
        self.assertEqual(events[-1], ("break-", "ПЕРЕРЫВ"))
        events.clear()
        self.walk(s, clock, at("11:20"))
        self.assertEqual(events, [], "после остановки — тишина")

    def test_heads_up_off(self):
        s, clock, events = self.make(at("10:58"))
        s.heads_up_min = 0
        s.start()
        self.walk(s, clock, at("11:06"))
        self.assertEqual(events, [("start", "Зарядка")])


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------- шаблоны и окна

from webinar import store as wstore  # noqa: E402
from webinar.ui import screens  # noqa: E402
from webinar.ui import notify, overlay  # noqa: E402
from PySide6.QtWidgets import QLabel as QLabel_, QPushButton as QPushButton_  # noqa: E402

from webinar.ui.editor import C_HANDLE, C_MIN, C_NAME, ROW_MIME, PlanEditor  # noqa: E402
from webinar.ui.main_window import MainWindow  # noqa: E402
from webinar.ui.settings_dialog import SettingsDialog  # noqa: E402


class StoreTest(unittest.TestCase):
    def setUp(self):
        for f in wstore.DATA_DIR.glob("plans*"):
            f.unlink()

    def test_first_run_has_example_and_roundtrip(self):
        st = wstore.PlanStore()
        self.assertEqual(len(st.plans), 1)
        st.plans.append(plan_from({"title": "Практикум", "start": "18:30", "schedule": [{"name": "Код", "min": 40}]}))
        st.save()
        again = wstore.PlanStore()
        self.assertEqual([p.title for p in again.plans], [st.plans[0].title, "Практикум"])
        self.assertEqual(again.plans[1].start, "18:30")

    def test_broken_file_recovered_from_backup(self):
        st = wstore.PlanStore()
        st.plans[0].title = "Мой вебинар"
        st.save()
        st.save()                                   # вторая запись оставляет копию первой
        wstore.PLANS_FILE.write_text("{не json", encoding="utf-8")
        again = wstore.PlanStore()
        self.assertEqual(again.plans[0].title, "Мой вебинар")
        self.assertIn("резервной копии", again.warning)


class _WindowBase(unittest.TestCase):
    """Главное окно с подменными часами (10:58) и тестовым шаблоном PLAN."""

    def setUp(self):
        for f in wstore.DATA_DIR.glob("plans*"):
            f.unlink()
        self.clock = FakeClock(at("10:58"))
        self.store = wstore.PlanStore()
        self.store.plans = [PLAN]
        self.win = MainWindow(self.store, wstore.Settings(), self.clock)
        self.win.scheduler._timer.stop()            # время двигает тест

    def tearDown(self):
        self.win.quit_app()

    def walk(self, until: datetime):
        while self.clock.t < until:
            self.clock.t += timedelta(seconds=15)
            self.win.scheduler.poll()



class WindowsTest(_WindowBase):
    def test_agenda_and_start_time(self):
        self.win.start_edit.setTime(self.win.start_edit.time().fromString("11:00", "HH:mm"))
        self.assertEqual(len(self.win.rows), len(PLAN.schedule))
        self.assertEqual(self.win.hero_label.text(), "ДО НАЧАЛА")
        self.assertEqual(self.win.hero_timer.text(), "02:00")

    def test_layout_fits_narrow_and_wide_window(self):
        """Отсчёт не обрезается в узком окне, повестка остаётся читаемой, старт виден целиком."""
        from PySide6.QtGui import QFontMetrics
        self.clock.t = at("02:00")                           # «До начала 9:00:00» — самый длинный отсчёт
        self.win.scheduler.poll()
        for width in (1020, 1700):
            self.win.resize(width, 800)
            self.win.show()
            app.processEvents()
            t = self.win.hero_timer
            self.assertLessEqual(QFontMetrics(t.font()).horizontalAdvance(t.text()), t.width(), width)
            self.assertGreaterEqual(self.win.agenda_scroll.width(), 340, width)
            e = self.win.start_edit
            self.assertLess(e.fontMetrics().horizontalAdvance("23:50"), e.lineEdit().width(), "старт виден")
        self.assertEqual(len(self.win.agenda.findChildren(type(self.win.rows[0]))), len(self.win.rows),
                         "старых строк повестки не осталось")

    def test_reminders_on_control_screen_until_acked(self):
        self.win.run_btn.setChecked(True)
        self.walk(at("11:02"))                        # «Зарядка» — с 11:02
        cards = self.win.notifier.cards
        self.assertEqual([(c.seg.activity.name, c.heads_up) for c in cards], [("Зарядка", False)],
                         "«сейчас» заменило «скоро»")
        area = screens.control_screen(self.win.settings).availableGeometry()
        self.assertTrue(area.contains(cards[0].geometry()), "карточка — на мониторе управления")
        self.walk(at("11:05"))
        self.assertEqual(len(self.win.notifier.cards), 1, "висит, пока не отметили, даже после конца блока")
        self.win.notifier.close(cards[0])
        self.assertEqual(self.win.notifier.cards, [])

    def test_break_overlay_on_demo_screen_stays_until_hidden(self):
        self.win.run_btn.setChecked(True)
        self.walk(at("11:10"))                        # перерыв 11:10–11:14
        o = self.win.overlay
        self.assertIsNotNone(o)
        self.assertEqual(o.geometry(), screens.demo_screen(self.win.settings).geometry(), "весь экран демонстрации")
        self.assertEqual(o.left_text(), "04:00")
        self.walk(at("11:15"))
        self.assertIs(self.win.overlay, o, "после конца перерыва заставка ждёт, пока её уберут")
        self.assertEqual(o.left_text(), "ПРОДОЛЖАЕМ")
        brk = next(c for c in self.win.notifier.cards if c.seg.activity.breaks)
        brk.hide_break.emit()                         # кнопка «Убрать заставку» на мониторе управления
        self.assertIsNone(self.win.overlay)

    def test_stop_clears_everything(self):
        self.win.run_btn.setChecked(True)
        self.walk(at("11:11"))
        self.win.run_btn.setChecked(False)
        self.assertEqual((self.win.notifier.cards, self.win.overlay), ([], None))
        self.walk(at("11:20"))
        self.assertEqual(self.win.notifier.cards, [], "эфир не ведётся — напоминаний нет")

    def test_plans_new_duplicate_delete(self):
        self.win.plans.setCurrentRow(0)
        self.win.duplicate_plan()
        self.assertEqual([p.title for p in self.store.plans], ["Тест", "Тест (копия)"])
        self.assertNotEqual(self.store.plans[0].id, self.store.plans[1].id)
        self.assertEqual(self.win.current_plan().title, "Тест (копия)", "копия выбрана")
        self.assertEqual([p.title for p in wstore.PlanStore().plans], ["Тест", "Тест (копия)"], "сохранено")


class ButtonsAndMediaTest(_WindowBase):
    """Кнопки напоминания и файл активности на экране демонстрации."""

    def test_snooze_close_next(self):
        from PySide6.QtCore import QEventLoop, QTimer
        from PySide6.QtGui import QColor, QImage
        img = Path(wstore.DATA_DIR) / "eyes.png"
        q = QImage(64, 36, QImage.Format.Format_RGB32)
        q.fill(QColor("green"))
        q.save(str(img))
        self.win.settings.eyes_media = str(img)
        self.win.run_btn.setChecked(True)
        self.walk(at("11:02"))
        card = self.win.notifier.cards[0]
        self.assertEqual(card.seg.activity.name, "Зарядка")

        notify.SNOOZE_MS, old = 50, notify.SNOOZE_MS        # «через минуту» — в тесте через 50 мс
        try:
            card.snoozed.emit(card)
            self.assertEqual(self.win.notifier.cards, [], "спрятано")
            loop = QEventLoop()
            QTimer.singleShot(200, loop.quit)
            loop.exec()
            self.assertEqual([c.seg.activity.name for c in self.win.notifier.cards], ["Зарядка"], "напомнило снова")
        finally:
            notify.SNOOZE_MS = old

        card = self.win.notifier.cards[0]
        card.next.emit(card)                                 # «Далее ▶»
        self.assertEqual(self.win.notifier.cards, [])
        self.assertIsNotNone(self.win.media, "гимнастика — на экране демонстрации")
        self.assertEqual(self.win.media.geometry(), screens.demo_screen(self.win.settings).geometry())
        self.win._hide_demo()
        self.assertIsNone(self.win.media)

    def test_drag_card_saves_position(self):
        """Карточку перетащили мышью — столбик переехал, позиция сохранена и действует для следующих."""
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        self.win.run_btn.setChecked(True)
        self.walk(at("11:02"))
        card = self.win.notifier.cards[0]
        self.assertLessEqual(card.width(), notify.WIDTH, "компактная карточка")
        area = screens.control_screen(self.win.settings).availableGeometry()
        start = card.pos()
        grip = QPoint(card.width() // 2, 6)                  # верхний край — не кнопка
        h = card.windowHandle()
        QTest.mousePress(h, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, grip)
        QTest.mouseMove(h, grip + QPoint(-200, 150))
        # карточка переехала вместе с курсором — он снова над той же точкой карточки
        QTest.mouseRelease(h, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, grip)
        self.assertEqual(card.pos(), start + QPoint(-200, 150), "карточка там, где отпустили")
        self.assertEqual(self.win.settings.note_pos, f"{card.x() - area.left()},{card.y() - area.top()}")
        self.assertEqual(wstore.Settings.load().note_pos, self.win.settings.note_pos, "сохранено в файл")

        self.walk(at("11:10"))                               # следующее напоминание — перерыв
        names = [c.seg.activity.name for c in self.win.notifier.cards]
        self.assertIn("ПЕРЕРЫВ", names)
        self.assertEqual(self.win.notifier.cards[0].pos(), card.pos(), "столбик начинается с той же точки")

        self.win.notifier.anchor = QPoint(10_000, 10_000)    # монитор сменили — не уехать за край
        self.win.notifier.layout()
        for c in self.win.notifier.cards:
            self.assertTrue(area.contains(c.geometry()), "карточка на экране")

    def test_block_media_overrides_settings_and_missing_file_ignored(self):
        seg = segments(Plan("x", "11:00", [Activity("Зарядка для глаз", DEMO_OFF, 5, media="нет-такого.mp4")]), DAY)[0]
        self.win.settings.eyes_media = ""
        self.assertEqual(self.win.media_of(seg), "", "нет файла — ничего не показываем")
        self.win._start_activity(seg)
        self.assertIsNone(self.win.media)

    def test_break_title_font_is_furore_when_installed(self):
        from PySide6.QtGui import QFontDatabase
        f = overlay.title_font(100)
        expected = "Furore" if "Furore" in QFontDatabase.families() else "Segoe UI"
        self.assertEqual((f.family(), f.pixelSize()), (expected, 100))


class SettingsSaveTest(unittest.TestCase):
    def test_save_after_identify_closes_dialog(self):
        """«Сохранить» не закрывало окно, если перед этим показывали номера мониторов (значки уже удалены)."""
        from PySide6.QtCore import QEventLoop, QTimer
        dlg = SettingsDialog(wstore.Settings())
        dlg._keep(screens.identify(dlg._collect(), ms=50))
        loop = QEventLoop()
        QTimer.singleShot(300, loop.quit)
        loop.exec()                                          # значки закрылись и удалились
        dlg.show()
        dlg.accept()
        self.assertFalse(dlg.isVisible())
        self.assertEqual(dlg.result(), 1)

    def test_reminder_clickable_while_settings_or_editor_open(self):
        """Щелчок «как от Windows» (через окно): карточка нажимается, пока открыты настройки или редактор."""
        from PySide6.QtCore import QEventLoop, Qt, QTimer
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QPushButton
        for make in (lambda: SettingsDialog(wstore.Settings()), lambda: PlanEditor(PLAN)):
            dlg = make()
            result = {}

            def click_card(dlg=dlg, result=result):
                card = notify.Card(segments(PLAN, DAY)[1], False, datetime.now)
                card.show()
                card.acked.connect(lambda c: result.setdefault("clicked", True))
                btn = next(b for b in card.findChildren(QPushButton) if b.text() == "Закрыть")
                QTest.mouseClick(card.windowHandle(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                                 btn.mapTo(card, btn.rect().center()))
                card.close()
                result["modality"] = dlg.windowModality()
                dlg.reject()

            QTimer.singleShot(50, click_card)
            dlg.exec()                                       # как в программе — exec(), не show()
            self.assertEqual(result.get("modality"), Qt.WindowModality.WindowModal, type(dlg).__name__)
            self.assertTrue(result.get("clicked"), f"кнопка карточки не нажалась при открытом {type(dlg).__name__}")
            QEventLoop().processEvents()

    def test_media_roundtrip(self):
        p = plan_from({"start": "11:00", "schedule": [{"name": "Зарядка", "min": 5, "media": "C:/v/eyes.mp4"}]})
        self.assertEqual(p.schedule[0].media, "C:/v/eyes.mp4")
        self.assertEqual(plan_to(p)["schedule"][0]["media"], "C:/v/eyes.mp4")


class EditorTest(unittest.TestCase):
    def test_edit_and_json(self):
        dlg = PlanEditor(PLAN)
        dlg.title.setText("Новый")
        dlg._add()
        dlg.table.cellWidget(5, C_NAME).setText("Перерыв на кофе")
        self.assertTrue(dlg.plan.schedule[5].breaks, "по названию — перерыв")
        dlg.move_row(5, 4)                                  # перетащили на строку выше
        dlg._save()
        p = dlg.result_plan
        self.assertEqual((p.title, p.id, p.schedule[4].name), ("Новый", PLAN.id, "Перерыв на кофе"))
        self.assertEqual(len(PLAN.schedule), 5, "исходный шаблон не меняется до сохранения")

        dlg = PlanEditor(PLAN)
        dlg.json.setPlainText('{"start": "9:30", "schedule": [{"name": "Код", "demo": "on", "min": 45}]}')
        dlg._apply_json()
        self.assertEqual((dlg.start.time().toString("HH:mm"), len(dlg.plan.schedule)), ("09:30", 1))
        dlg.json.setPlainText("{плохой")
        dlg._apply_json()
        self.assertIn("Не получилось", dlg.error.text())

    def test_enter_finishes_input(self):
        """Enter в поле — выход из поля (ввод зафиксирован); блок не добавляется (раньше жал «+ Добавить блок»)."""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        dlg = PlanEditor(PLAN)
        dlg.show()
        name = dlg.table.cellWidget(1, C_NAME)
        name.setFocus()
        QTest.keyClicks(name, " intro")                     # латиница: QTest.keyClicks в PySide падает на кириллице
        QTest.keyClick(name, Qt.Key.Key_Return)
        app.processEvents()
        self.assertEqual((len(dlg.plan.schedule), dlg.isVisible(), dlg.result_plan), (5, True, None))
        self.assertFalse(name.hasFocus(), "вышли из поля")
        self.assertEqual(dlg.plan.schedule[1].name, "Зарядка intro", "введённое сохранено")
        spin = dlg.table.cellWidget(1, C_MIN)
        spin.setFocus()
        QTest.keyClick(spin, Qt.Key.Key_Return)
        self.assertFalse(spin.hasFocus(), "и из счётчика минут")
        last = dlg.table.cellWidget(4, C_NAME)
        last.setFocus()
        QTest.keyClick(last, Qt.Key.Key_Return)
        self.assertEqual(len(dlg.plan.schedule), 5, "и в последнем блоке Enter ничего не добавляет")
        settings = SettingsDialog(wstore.Settings())
        self.assertFalse(any(b.autoDefault() or b.isDefault() for b in settings.findChildren(QPushButton_)))
        dlg.close()

    def test_drag_rows(self):
        """Перенос блоков мышью: вниз, вверх, на своё место; бросок над таблицей — через dropEvent."""
        from PySide6.QtCore import QMimeData, QPointF, Qt
        from PySide6.QtGui import QDropEvent
        dlg = PlanEditor(PLAN)
        names = lambda: [a.name for a in dlg.plan.schedule]  # noqa: E731
        self.assertEqual(names(), ["Приветствие", "Зарядка", "ПРЕЗЕНТАЦИЯ", "ПЕРЕРЫВ", "Выводы"])
        dlg.move_row(0, 3)                                  # первый — перед четвёртым
        self.assertEqual(names(), ["Зарядка", "ПРЕЗЕНТАЦИЯ", "Приветствие", "ПЕРЕРЫВ", "Выводы"])
        dlg.move_row(4, 0)                                  # последний — в начало
        self.assertEqual(names()[0], "Выводы")
        before = names()
        dlg.move_row(2, 2)
        dlg.move_row(2, 3)
        self.assertEqual(names(), before, "на своё место — без изменений")
        self.assertIsInstance(dlg.table.cellWidget(0, C_HANDLE), QLabel_)

        dlg.resize(900, 600)
        dlg.show()
        mime = QMimeData()
        mime.setData(ROW_MIME, b"0")
        rect = dlg.table.visualRect(dlg.table.model().index(3, C_NAME))
        drop = QDropEvent(QPointF(rect.center().x(), rect.bottom() - 2), Qt.DropAction.MoveAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        first = names()[0]
        dlg.table.dropEvent(drop)                            # нижняя половина 4-й строки — встать после неё
        self.assertEqual(names()[3], first)
        dlg.close()

    def test_spin_arrows_clickable_in_every_style(self):
        """Стрелки ▲▼ счётчиков (минуты, старт) нажимаются: поле ввода не перекрывает кнопки.
        В стиле windows11 (Windows 11) поле раньше закрывало стрелки — они не нажимались."""
        from PySide6.QtWidgets import QSpinBox, QStyle, QStyleFactory, QStyleOptionSpinBox, QTimeEdit
        from webinar.ui.style import APP_QSS
        old_style, old_qss = app.style().name(), app.styleSheet()
        try:
            for name in QStyleFactory.keys():
                app.setStyle(name)
                app.setStyleSheet(APP_QSS)
                for w in (QSpinBox(), QTimeEdit()):
                    w.resize(118, 29)
                    w.show()
                    app.processEvents()
                    opt = QStyleOptionSpinBox()
                    w.initStyleOption(opt)
                    for sc in (QStyle.SubControl.SC_ScrollBarAddLine, QStyle.SubControl.SC_ScrollBarSubLine):
                        r = w.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, opt, sc, w)
                        self.assertIsNone(w.childAt(r.center()), f"{name}: {type(w).__name__} {sc.name}")
                    w.close()
        finally:
            app.setStyle(old_style)
            app.setStyleSheet(old_qss)

    def test_part_limit_45(self):
        """Части занятия до и после перерыва — не больше 45 минут: счётчик не даёт превысить, сохранить нельзя."""
        p = default_plan()
        self.assertEqual([p.part_total(x) for x in p.parts()], [45, 45], "пример: 45 + перерыв + 45")
        dlg = PlanEditor(p)
        spin = dlg.table.cellWidget(1, C_MIN)              # «Целеполагание», 1-я часть заполнена
        spin.stepUp()
        self.assertEqual((spin.value(), dlg.plan.schedule[1].min), (5, 5), "часть полна — не увеличить")
        dlg.table.cellWidget(2, C_MIN).setValue(10)          # презентацию 14 → 10: освободилось 4 мин
        spin.stepUp()
        self.assertEqual(dlg.plan.schedule[1].min, 6, "теперь можно")
        self.assertEqual(spin.maximum(), 9)
        brk = dlg.table.cellWidget(6, C_MIN)                 # сам перерыв не ограничен
        brk.setValue(30)
        self.assertEqual(dlg.plan.schedule[6].min, 30)
        self.assertIn("42</b>/45", dlg.parts_lbl.text())      # 45 − 4 + 1

        dlg.move_row(8, 2)                                   # презентацию 2-й части (20 мин) — в 1-ю
        self.assertEqual([t for _n, t in dlg.plan.over_limit()], [62])
        dlg._save()
        self.assertIsNone(dlg.result_plan, "превышение — не сохраняется")
        self.assertIn("1-я часть — 62 мин из 45", dlg.error.text())

        dlg.part.setValue(0)                                 # без предела
        dlg._save()
        self.assertEqual(dlg.result_plan.part_min, 0)
        self.assertEqual(plan_from(plan_to(dlg.result_plan)).part_min, 0, "предел — в JSON шаблона")
        self.assertEqual(plan_from({"start": "11:00", "schedule": [{"name": "a", "min": 1}]}).part_min, 45)

    def test_settings_dialog_screens(self):
        s = wstore.Settings()
        dlg = SettingsDialog(s)
        self.assertEqual(dlg.demo.count(), len(screens.screens()))
        out = dlg.result_settings()
        self.assertEqual(screens.demo_screen(out).name(), dlg.demo.currentData())
