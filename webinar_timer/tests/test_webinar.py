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
            b = self.win.break_min
            self.assertLess(b.fontMetrics().horizontalAdvance("120 мин"), b.lineEdit().width(), "длительность перерыва видна")
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
        self.assertFalse([c for c in self.win.notifier.cards if c.seg.activity.breaks], "вместо карточки — пульт")
        panel = self.win.break_panel
        self.assertTrue(screens.control_screen(self.win.settings).availableGeometry().contains(panel.geometry()))
        panel.refresh()
        self.assertEqual(panel.big.text(), "00:00")
        panel.stop_btn.click()                        # «Убрать» на пульте
        self.assertIsNone(self.win.overlay)
        self.assertFalse(panel.isVisible(), "пульт ушёл вместе с заставкой")

    def test_break_any_time_from_window_and_tray(self):
        """Перерыв в любой момент — без эфира, кнопкой в окне и из трея; план не сдвигается."""
        before = [s.start for s in self.win.scheduler.segs]
        self.win.break_min.setValue(7)
        self.win.break_btn.click()                           # эфир не ведётся — всё равно можно
        o = self.win.overlay
        self.assertIsNotNone(o)
        self.assertEqual(o.geometry(), screens.demo_screen(self.win.settings).geometry())
        self.assertEqual((o.end - self.clock.t, o.left_text()), (timedelta(minutes=7), "07:00"))
        self.assertEqual(self.win.notifier.cards, [], "у ведущего — пульт, а не карточка")
        self.assertEqual(self.win.break_panel.big.text(), "07:00")
        self.assertEqual(self.win.break_btn.text(), "■ Убрать с экрана")
        self.win.break_btn.click()                           # повторное нажатие — убрать
        self.assertEqual((self.win.overlay, self.win.notifier.cards), (None, []))
        self.assertEqual(self.win.break_btn.text(), "☕ Перерыв сейчас")

        self.win._fill_tray_break()                          # меню в трее
        items = [a.text() for a in self.win.tray_break.actions() if a.text()]
        self.assertEqual(items, ["☕ 7 мин (как в окне)", "5 мин", "10 мин", "15 мин", "20 мин", "■ Убрать заставку"])
        self.assertFalse(self.win.tray_break.actions()[-1].isEnabled(), "убирать пока нечего")
        next(a for a in self.win.tray_break.actions() if a.text() == "15 мин").trigger()
        self.assertEqual(self.win.overlay.left_text(), "15:00")
        self.win._fill_tray_break()
        self.win.tray_break.actions()[-1].trigger()          # «Убрать заставку» из трея
        self.assertIsNone(self.win.overlay)
        self.assertEqual([s.start for s in self.win.scheduler.segs], before, "расписание не сдвинулось")
        self.assertEqual(wstore.Settings.load().manual_break_min, 7, "длительность запомнилась")

    def test_eyes_any_time_from_window_and_tray(self):
        """Зарядка в любой момент, как перерыв: видео гимнастики — на экран демонстрации; повторно — убрать."""
        from PySide6.QtGui import QColor, QImage
        img = Path(wstore.DATA_DIR) / "eyes_now.png"
        q = QImage(32, 18, QImage.Format.Format_RGB32)
        q.fill(QColor("green"))
        q.save(str(img))
        self.win.settings.eyes_media = "нет-такого-файла.mp4"
        self.assertFalse(self.win.start_eyes(), "видео нет — подсказка, а не пустой экран")
        self.assertIsNone(self.win.media)
        self.win.settings.eyes_media = str(img)
        self.win.eyes_btn.click()                            # эфир не ведётся — всё равно можно
        self.assertIsNotNone(self.win.media)
        self.assertEqual(self.win.media.geometry(), screens.demo_screen(self.win.settings).geometry())
        self.assertEqual(self.win.eyes_btn.text(), "■ Убрать с экрана")
        self.win.eyes_btn.click()
        self.assertIsNone(self.win.media)
        self.assertEqual(self.win.eyes_btn.text(), "👁 Зарядка сейчас")
        tray = next(a for a in self.win.tray.contextMenu().actions() if a.text() == "👁 Зарядка сейчас")
        tray.trigger()                                       # из трея
        self.assertIsNotNone(self.win.media)
        self.win._hide_demo()

    def test_break_panel_pause_and_minutes(self):
        """Пульт перерыва: пауза замораживает отсчёт у зрителей, ±1 мин, «Заново»; после конца +1 мин — снова отсчёт."""
        self.win.start_break(10)
        o, panel = self.win.overlay, self.win.break_panel
        self.clock.t += timedelta(minutes=3)
        panel.refresh()
        self.assertEqual((o.left_text(), panel.big.text()), ("07:00", "07:00"))
        self.assertEqual(panel.progress.value(), 300)
        panel.pause_btn.click()
        self.assertEqual(panel.pause_btn.text(), "▶ Продолжить")
        self.clock.t += timedelta(minutes=2)
        self.assertEqual(o.left_text(), "07:00", "на паузе отсчёт стоит")
        panel.pause_btn.click()
        self.clock.t += timedelta(minutes=1)
        self.assertEqual(o.left_text(), "06:00")
        panel.more_btn.click()
        self.assertEqual(o.left_text(), "07:00")
        panel.less_btn.click()
        panel.less_btn.click()
        self.assertEqual(o.left_text(), "05:00")
        panel.restart_btn.click()
        self.assertEqual(o.left_text(), "09:00", "заново — на всю (уже изменённую) длительность")
        self.clock.t += timedelta(minutes=12)
        panel.refresh()
        self.assertEqual((o.left_text(), panel.big.text()), ("ПРОДОЛЖАЕМ", "00:00"))
        panel.more_btn.click()
        self.assertEqual(o.left_text(), "01:00", "время вышло, +1 мин — ещё минута отсчёта")
        for _ in range(3):
            panel.less_btn.click()
        self.assertEqual(o.left_text(), "ПРОДОЛЖАЕМ", "не меньше нуля")
        self.win._hide_break()
        self.assertIsNone(self.win.overlay)

    def test_video_has_player_on_control_monitor(self):
        """У видео — пульт на мониторе управления (у картинки — нет); «Убрать» — видео и пульт уходят вместе."""
        from PySide6.QtCore import QEvent
        from shiboken6 import isValid
        video = Path(wstore.DATA_DIR) / "eyes.mp4"
        video.write_bytes(b"")
        self.win._show_media(str(video))
        panel = self.win.player_panel
        self.assertIsNotNone(panel)
        self.assertTrue(screens.control_screen(self.win.settings).availableGeometry().contains(panel.geometry()))
        self.assertEqual(panel.title.text(), "eyes")
        panel.stop_btn.click()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertIsNone(self.win.media)
        self.assertFalse(isValid(panel) and panel.isVisible(), "пульт ушёл вместе с видео")
        self.assertIsNone(self.win.player_panel)
        self.assertEqual(self.win.eyes_btn.text(), "👁 Зарядка сейчас")

        from PySide6.QtGui import QColor, QImage
        img = Path(wstore.DATA_DIR) / "eyes_pic.png"
        q = QImage(32, 18, QImage.Format.Format_RGB32)
        q.fill(QColor("green"))
        q.save(str(img))
        self.win._show_media(str(img))
        self.assertIsNone(self.win.player_panel, "у картинки пульта нет")
        self.win._hide_demo()

    def test_player_panel_seek_pause_volume(self):
        """Пульт: пауза/играть, ±10 с (не дальше начала и конца), с начала, громкость, перетаскивание."""
        from PySide6.QtCore import QObject, QPoint, Signal
        from PySide6.QtMultimedia import QMediaPlayer

        from webinar.ui.player import PlayerPanel, fmt_ms

        class FakePlayer(QObject):
            positionChanged = Signal(int)
            durationChanged = Signal(int)
            playbackStateChanged = Signal(object)

            def __init__(self):
                super().__init__()
                self.pos, self.state = 5_000, QMediaPlayer.PlaybackState.PlayingState

            def position(self): return self.pos
            def duration(self): return 60_000
            def playbackState(self): return self.state
            def setPosition(self, ms): self.pos = ms
            def play(self): self.state = QMediaPlayer.PlaybackState.PlayingState
            def pause(self): self.state = QMediaPlayer.PlaybackState.PausedState

        class FakeAudio:
            vol, muted = 1.0, False
            def volume(self): return self.vol
            def setVolume(self, v): self.vol = v
            def isMuted(self): return self.muted
            def setMuted(self, m): self.muted = m

        p, a = FakePlayer(), FakeAudio()
        screen = screens.control_screen(self.win.settings)
        panel = PlayerPanel(p, a, "Гимнастика", screen)
        self.assertEqual(panel.time.text(), "0:05 / 1:00")
        self.assertEqual(panel.play_btn.text(), "❚❚ Пауза")
        panel.play_btn.click()
        self.assertEqual(p.state, QMediaPlayer.PlaybackState.PausedState)
        self.assertEqual(panel.play_btn.text(), "▶ Играть")
        panel.play_btn.click()
        self.assertEqual(p.state, QMediaPlayer.PlaybackState.PlayingState)
        panel.back_btn.click()
        self.assertEqual(p.pos, 0, "назад — не раньше начала")
        panel.fwd_btn.click()
        self.assertEqual(p.pos, 10_000)
        for _ in range(6):
            panel.fwd_btn.click()
        self.assertLess(p.pos, 60_000, "вперёд — не до самого конца: видео не закрывается само")
        panel.restart_btn.click()
        self.assertEqual((p.pos, panel.slider.value()), (0, 0))
        panel.volume.setValue(40)
        self.assertAlmostEqual(a.vol, 0.4)
        panel.mute_btn.click()
        self.assertTrue(a.muted)
        self.assertEqual(panel.mute_btn.text(), "🔇")
        self.assertEqual(fmt_ms(3_725_000), "1:02:05")

        area = screen.availableGeometry()
        panel.place()                                        # по умолчанию — внизу по центру
        self.assertTrue(area.contains(panel.geometry()))
        self.assertAlmostEqual(panel.geometry().center().x(), area.center().x(), delta=2)
        far = PlayerPanel(p, a, "x", screen, QPoint(-5000, 99999))     # чужая позиция — всё равно на экране
        far.place()
        self.assertTrue(area.contains(far.geometry()))
        moved = []
        panel.dropped.connect(moved.append)
        panel._drag_from = QPoint(0, 0)
        panel.move(area.left() + 40, area.top() + 50)
        panel.mouseReleaseEvent(None)
        self.assertEqual(moved, [QPoint(40, 50)])
        for w in (panel, far):
            w.close()

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

    def test_card_tint_follows_phase(self):
        """Что предстоит и что идёт — разными оттенками; карточка «скоро» сама перекрашивается в «сейчас»."""
        seg = segments(PLAN, DAY)[1]                         # «Зарядка» 11:02–11:05
        self.clock.t = at("11:01")
        card = notify.Card(seg, True, self.clock)
        self.assertEqual(card.phase, "soon")
        soon_css = card.frame.styleSheet()
        self.clock.t = at("11:03")
        card.refresh()
        self.assertEqual(card.phase, "now")
        self.assertNotEqual(card.frame.styleSheet(), soon_css, "другой оттенок")
        self.clock.t = at("11:06")
        card.refresh()
        self.assertEqual((card.phase, card.label.text()), ("over", "ВРЕМЯ ВЫШЛО"))
        backgrounds = {notify.PHASE_STYLE[ph][0] for ph in ("soon", "now", "over")}
        self.assertEqual(len(backgrounds), 3, "у фаз разные фоны")
        card.close()

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

        self.walk(at("11:09"))                               # следующее напоминание — «скоро перерыв»
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

    def test_media_paths_relative_to_app_folder(self):
        """Файлы из папки приложения хранятся относительными путями — папку webinar_timer можно перенести."""
        inside = wstore.MEDIA_DIR / "Фон.jpg"
        self.assertEqual(wstore.portable(str(inside)), "media/Фон.jpg")
        self.assertEqual(Path(wstore.resolve("media/Фон.jpg")), inside)
        outside = str(Path(tempfile.gettempdir()) / "чужой.mp4")
        self.assertEqual(wstore.portable(outside), outside, "вне папки — как есть")
        self.assertEqual(wstore.existing("media/нет-такого.mp4"), "")
        s = wstore.Settings()
        self.assertEqual((s.break_image, s.eyes_media), ("media/Фон.jpg", "media/Гимнастика для глаз.mp4"))
        self.assertEqual(wstore.APP_DIR.name, "webinar_timer")

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
