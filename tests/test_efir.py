"""«Эфир»: шаблоны вебинаров, повестка по часам, сервер экрана эфира, контроллер и окна (без окон на экране).

    python tests/test_efir.py
EFIR_SHOTS=<папка> — сохранить снимки окна таймера разных размеров (для глаза).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import quiet  # noqa: E402,F401  — до PySide6: offscreen, своя папка данных

from PySide6.QtCore import QObject  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication.instance() or QApplication([])
quiet.patch()
from autoprint.ui.theme import theme  # noqa: E402
theme.setup(app, "dark")

from autoprint.efir import legacy  # noqa: E402
from autoprint.efir.model import (BG_BLACK, KIND_BREAK, KIND_EXERCISE, KIND_NORMAL, Activity, Exercise,  # noqa: E402
                                  Webinar, agenda_at, ai_prompt, anchor_for, anchor_to_start_at, export_json,
                                  fmt_left, guess_kind, parse_webinars, sample_webinar, segments)
from autoprint.efir.server import BroadcastServer  # noqa: E402
from autoprint.efir.store import WebinarStore, media_dir  # noqa: E402
from autoprint.storage import Settings  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="efir-test-"))
PORT = 18791


def pump(ms: int = 50) -> None:
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def fake_timer_folder() -> Path:
    """Папка «Таймера вебинара» как у Виктора: data/plans.json, data/settings.json, media/."""
    root = TMP / f"timer-{time.time_ns()}"
    (root / "data").mkdir(parents=True)
    (root / "media").mkdir()
    (root / "media" / "Гимнастика для глаз.mp4").write_bytes(b"\x00" * 2048)
    (root / "media" / "Фон.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
    (root / "media" / "Furore.otf").write_bytes(b"OTTO" + b"\x00" * 100)
    plans = {"version": 1, "plans": [
        {"id": "abcdef123456", "title": "Вебинар 1Т (Первая пара)", "start": "11:00", "schedule": [
            {"name": "Приветствие", "demo": "on", "min": 1},
            {"name": "ЗАРЯДКА ДЛЯ ГЛАЗ", "demo": "off", "min": 5},
            {"name": "ПЕРЕРЫВ", "demo": "none", "min": 10, "remind": True},
            {"name": "Теория", "demo": "on", "min": 14, "locked": True}]},
        {"title": "Вторая пара", "start": "04:50", "schedule": [{"name": "Викторина", "demo": "on", "min": 7}]}]}
    (root / "data" / "plans.json").write_text(json.dumps(plans, ensure_ascii=False), encoding="utf-8")
    settings = {"break_image": "media/Фон.jpg", "eyes_media": "media/Гимнастика для глаз.mp4",
                "manual_break_min": 12, "break_text_color": "#FFEEAA"}
    (root / "data" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    return root


# ====================================================================== модель
class ModelTest(unittest.TestCase):
    def test_agenda_by_clock(self):
        w = Webinar(start="11:00", schedule=[Activity("А", 10), Activity("Б", 5), Activity("В", 20)])
        anchor = datetime(2026, 11, 23, 11, 0)
        segs = segments(w, anchor)
        self.assertEqual([s.start.strftime("%H:%M") for s in segs], ["11:00", "11:10", "11:15"])
        before = agenda_at(segs, anchor - timedelta(minutes=3))
        self.assertEqual(before.phase, "before")
        self.assertAlmostEqual(before.left_s, 180)
        live = agenda_at(segs, anchor + timedelta(minutes=12))
        self.assertEqual((live.phase, live.index, live.next.activity.name), ("live", 1, "В"))
        self.assertAlmostEqual(live.left_s, 180)
        self.assertAlmostEqual(live.frac, 0.4)
        last = agenda_at(segs, anchor + timedelta(minutes=30))
        self.assertIsNone(last.next)
        self.assertEqual(agenda_at(segs, anchor + timedelta(minutes=35)).phase, "after")

    def test_start_from_block_now(self):
        w = Webinar(schedule=[Activity("А", 10), Activity("Б", 5), Activity("В", 20)])
        segs = segments(w, datetime(2026, 11, 23, 11, 0))
        now = datetime(2026, 11, 23, 13, 7, 30)
        anchor = anchor_to_start_at(segs, 2, now)
        ag = agenda_at(segments(w, anchor), now)
        self.assertEqual((ag.phase, ag.index), ("live", 2))
        self.assertAlmostEqual(ag.left_s, 20 * 60)

    def test_fmt(self):
        self.assertEqual(fmt_left(0), "00:00")
        self.assertEqual(fmt_left(59.2), "01:00")
        self.assertEqual(fmt_left(3725), "1:02:05")
        self.assertEqual(anchor_for("09:05", datetime(2026, 1, 2).date()), datetime(2026, 1, 2, 9, 5))

    def test_guess_kind(self):
        self.assertEqual(guess_kind("ПЕРЕРЫВ"), KIND_BREAK)
        self.assertEqual(guess_kind("Зарядка для глаз"), KIND_EXERCISE)
        self.assertEqual(guess_kind("Гимнастика"), KIND_EXERCISE)
        self.assertEqual(guess_kind("Теория"), KIND_NORMAL)

    def test_parse_html_agenda_format(self):
        text = json.dumps({"start": "10:30", "schedule": [{"name": "Приветствие", "demo": "on", "min": 1},
                                                          {"name": "Перерыв", "demo": "none", "min": 10}]})
        [w] = parse_webinars(text)
        self.assertEqual(w.start, "10:30")
        self.assertEqual([(a.name, a.min, a.kind, a.demo) for a in w.schedule],
                         [("Приветствие", 1, KIND_NORMAL, "on"), ("Перерыв", 10, KIND_BREAK, "none")])
        self.assertEqual(w.background, BG_BLACK)

    def test_parse_ai_answer_with_text_and_fences(self):
        answer = ('Вот расписание:\n```json\n{"title": "Пара", "start": "9:00", "break_min": 15, "schedule": ['
                  '{"name": "Теория", "min": 20, "kind": "", "demo": "on"},'
                  '{"name": "Зарядка", "min": 5, "kind": "exercise", "demo": "off"}]}\n```\nУдачи!')
        [w] = parse_webinars(answer)
        self.assertEqual((w.title, w.start, w.break_min), ("Пара", "9:00", 15))
        self.assertEqual(w.schedule[1].kind, KIND_EXERCISE)

    def test_parse_errors_are_readable(self):
        with self.assertRaisesRegex(ValueError, "JSON"):
            parse_webinars("просто текст")
        with self.assertRaisesRegex(ValueError, "schedule"):
            parse_webinars('{"title": "x"}')
        with self.assertRaisesRegex(ValueError, "пустое"):
            parse_webinars('{"schedule": [{"name": ""}]}')

    def test_export_roundtrip(self):
        w = sample_webinar()
        w.exercises = [Exercise("Глаза", r"C:\v.mp4")]
        w.background = "anim:cube"
        w.break_background = "image:C:\\bg.jpg"
        w.font = "file:C:\\f.otf"
        [back] = parse_webinars(export_json([w]))
        self.assertEqual(back.to_dict(), w.to_dict())
        two = parse_webinars(export_json([w, w.copy("Копия")]))
        self.assertEqual([x.title for x in two], [w.title, "Копия"])

    def test_bad_values_are_cleaned(self):
        [w] = parse_webinars(json.dumps({"start": "25:99", "background": "anim:nope", "text_color": "red",
                                         "font": "Comic", "break_min": -4,
                                         "schedule": [{"name": "А", "min": "abc", "demo": "maybe"}]}))
        self.assertEqual((w.start, w.background, w.text_color, w.font, w.break_min),
                         ("11:00", BG_BLACK, "#FFFFFF", "Montserrat", 1))
        self.assertEqual((w.schedule[0].min, w.schedule[0].demo), (5, "on"))

    def test_ai_prompt_has_example_without_local_files(self):
        w = sample_webinar()
        w.exercises = [Exercise("Глаза", r"C:\secret\v.mp4")]
        w.break_background = r"image:C:\secret\bg.jpg"
        text = ai_prompt(w)
        self.assertIn('"schedule"', text)
        self.assertNotIn("secret", text)
        example = text[text.index("{"):text.rindex("}") + 1]
        self.assertTrue(parse_webinars(example))


# ====================================================================== хранение и перенос
class StoreTest(unittest.TestCase):
    def setUp(self):
        self.path = TMP / f"store-{time.time_ns()}" / "webinars.json"

    def test_add_put_live_reload(self):
        s = WebinarStore(self.path)
        a = sample_webinar()
        s.add([a])
        added = s.add([a, Webinar(title=a.title, schedule=[Activity("x", 1)])])
        self.assertEqual(len(s.webinars), 3)
        self.assertNotEqual(added[0].id, a.id)                      # тот же id — новый
        self.assertEqual(added[1].title, f"{a.title} (3)")
        anchor = datetime(2026, 11, 23, 11, 5)
        s.set_live(a.id, anchor)
        s2 = WebinarStore(self.path)
        self.assertEqual([w.title for w in s2.webinars], [w.title for w in s.webinars])
        self.assertEqual((s2.live.webinar_id, s2.live.anchor), (a.id, anchor))
        s2.remove(a.id)
        self.assertIsNone(WebinarStore(self.path).live)

    def test_broken_file_falls_back_to_backup(self):
        s = WebinarStore(self.path)
        s.add([sample_webinar()])
        shutil.copy2(s.path, s.path.with_suffix(".json.bak"))          # 0.10: расписания — schedules.json
        s.path.write_text("{broken", encoding="utf-8")
        self.assertEqual(len(WebinarStore(self.path).webinars), 1)

    def test_legacy_import(self):
        root = fake_timer_folder()
        items = legacy.import_from(root)
        self.assertEqual([w.title for w in items], ["Вебинар 1Т (Первая пара)", "Вторая пара"])
        w = items[0]
        self.assertEqual([a.kind for a in w.schedule], [KIND_NORMAL, KIND_EXERCISE, KIND_BREAK, KIND_NORMAL])
        self.assertEqual(len(w.exercises), 1)
        ex = Path(w.exercises[0].path)
        self.assertEqual(ex.parent, media_dir())                     # видео скопировано к нам
        self.assertTrue(ex.is_file())
        self.assertTrue(w.break_background.startswith("image:") and Path(w.break_background[6:]).is_file())
        self.assertTrue(w.font.startswith("file:") and w.font.endswith("Furore.otf"))
        self.assertEqual((w.break_min, w.text_color, w.background), (12, "#FFEEAA", BG_BLACK))
        shutil.rmtree(root)                                           # таймер удалили — наши файлы остались
        self.assertTrue(ex.is_file())

    def test_legacy_staging_copy_is_used_in_place(self):
        """Копия таймера от установщика (data/efir/webinar-timer) — видео не копируется второй раз."""
        from autoprint.efir.store import efir_dir
        staged = efir_dir() / "webinar-timer"
        if staged.exists():
            shutil.rmtree(staged)
        shutil.copytree(fake_timer_folder(), staged)
        try:
            self.assertEqual(legacy.find(), staged)
            [w, _] = legacy.import_from(staged)
            self.assertEqual(Path(w.exercises[0].path), staged / "media" / "Гимнастика для глаз.mp4")
        finally:
            shutil.rmtree(staged)


# ====================================================================== сервер
class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reports, cls.picks = [], []
        cls.srv = BroadcastServer(PORT + 50, on_report=cls.reports.append, on_pick=cls.picks.append)
        assert cls.srv.start()
        cls.base = cls.srv.url

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def get(self, path, headers=None):
        req = urllib.request.Request(self.base + path.lstrip("/"), headers=headers or {})
        return urllib.request.urlopen(req, timeout=5)

    def test_page_and_state(self):
        html = self.get("/").read().decode("utf-8")
        self.assertIn("Экран эфира", html)
        self.assertIn("/gallery", html)
        self.assertIn("Экран эфира", self.get("/gallery?select=anim:cube").read().decode("utf-8"))
        self.srv.publish({"mode": "idle", "bg": {"kind": "anim", "value": "cube"}})
        st = json.loads(self.get("/state").read())
        self.assertEqual(st["bg"]["value"], "cube")
        self.assertGreater(st["server_now"], 0)

    def test_sse_pushes_changes(self):
        self.srv.publish({"mode": "idle", "caption": "раз"})
        r = self.get("/events")
        first = r.readline().decode("utf-8")
        self.assertTrue(first.startswith("data: "))
        self.assertEqual(json.loads(first[6:])["caption"], "раз")
        r.readline()
        self.srv.publish({"mode": "break", "caption": "два"})
        second = r.readline().decode("utf-8")
        self.assertEqual(json.loads(second[6:])["mode"], "break")
        r.close()

    def test_media_with_range(self):
        f = TMP / "clip.mp4"
        data = bytes(range(256)) * 40
        f.write_bytes(data)
        url = self.srv.media_url(f)
        self.assertTrue(url.startswith("/media/") and url.endswith("/clip.mp4"))
        self.assertEqual(self.srv.media_url(f), url)                  # тот же файл — тот же адрес
        full = self.get(url)
        self.assertEqual((full.status, full.headers["Content-Type"]), (200, "video/mp4"))
        self.assertEqual(full.read(), data)
        part = self.get(url, {"Range": "bytes=100-199"})
        self.assertEqual(part.status, 206)
        self.assertEqual(part.headers["Content-Range"], f"bytes 100-199/{len(data)}")
        self.assertEqual(part.read(), data[100:200])
        tail = self.get(url, {"Range": "bytes=-10"})
        self.assertEqual(tail.read(), data[-10:])
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get("/media/0123456789abcdef/x.mp4")
        self.assertEqual(cm.exception.code, 404)

    def test_foreign_host_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get("/state", {"Host": "evil.example:8791"})
        self.assertEqual(cm.exception.code, 403)

    def test_report_and_pick(self):
        def post(path, data):
            req = urllib.request.Request(self.base + path, data=json.dumps(data).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            return json.loads(urllib.request.urlopen(req, timeout=5).read())
        self.assertTrue(post("report", {"type": "unlock"})["ok"])
        self.assertTrue(post("pick", {"background": "anim:stars"})["ok"])
        self.assertIn({"type": "unlock"}, self.reports)
        self.assertEqual(self.picks[-1], {"background": "anim:stars"})

    def test_busy_port_moves_on(self):
        other = BroadcastServer(self.srv.port)
        try:
            self.assertTrue(other.start())
            self.assertNotEqual(other.port, self.srv.port)
        finally:
            other.stop()


# ====================================================================== контроллер и окна
class FakeMain(QObject):
    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.settings.efir_port = PORT


class ControllerTest(unittest.TestCase):
    def setUp(self):
        from autoprint.ui import efir_control
        from autoprint.efir import store as store_mod
        self.data = TMP / f"ctl-{time.time_ns()}"
        self._efir_dir = store_mod.efir_dir
        store_mod.efir_dir = lambda: self.data
        self.main = FakeMain()
        self.ctl = efir_control.EfirController(self.main)
        self.video = self.data / "v.mp4"
        self.video.parent.mkdir(parents=True, exist_ok=True)
        self.video.write_bytes(b"\x00" * 64)
        w = sample_webinar()
        w.title = "Тест"
        w.exercises = [Exercise("Глаза", str(self.video)), Exercise("Шея", str(self.video))]
        w.break_min = 7
        self.ctl.store.add([w])
        self.w = w

    def tearDown(self):
        from autoprint.efir import store as store_mod
        if self.ctl.timer_window is not None:
            self.ctl.timer_window.close_silently()
        for e in list(self.ctl.editors):
            e._dirty = False
            e.close()
        if self.ctl.window is not None:
            self.ctl.window.close()
        self.ctl.server.stop()
        store_mod.efir_dir = self._efir_dir
        pump(20)

    def test_launch_break_exercise_flow(self):
        ctl = self.ctl
        ctl.launch(self.w.id)
        self.assertIsNotNone(ctl.timer_window)
        self.assertTrue(ctl.server.running)
        self.assertEqual(ctl.store.live.webinar_id, self.w.id)
        st = ctl.server.snapshot()
        self.assertEqual((st["mode"], st["bg"]), ("idle", {"kind": "color", "value": "#000000"}))
        # перерыв: 7 мин, ±, пауза
        ctl.start_break(7)
        st = ctl.server.snapshot()
        self.assertEqual(st["mode"], "break")
        self.assertAlmostEqual(st["brk"]["ends_at"] / 1000 - time.time(), 420, delta=2)
        ctl.break_adjust(60)
        self.assertAlmostEqual(ctl.break_left(), 480, delta=2)
        ctl.break_adjust(-120)
        self.assertAlmostEqual(ctl.break_left(), 360, delta=2)
        ctl.break_pause()
        left = ctl.break_left()
        time.sleep(0.2)
        self.assertEqual(ctl.break_left(), left)
        self.assertIsNotNone(ctl.server.snapshot()["brk"]["paused_left"])
        ctl.break_pause()
        self.assertIsNone(ctl.server.snapshot()["brk"]["paused_left"])
        # время вышло, «+1 мин» — снова отсчёт
        ctl.brk_ends = time.time() - 5
        ctl.break_adjust(60)
        self.assertAlmostEqual(ctl.break_left(), 60, delta=2)
        # зарядка поверх перерыва, затем конец ролика → фон
        ctl.start_exercise(1)
        st = ctl.server.snapshot()
        self.assertEqual((st["mode"], st["exercise"]["title"]), ("exercise", "Шея"))
        self.assertTrue(st["exercise"]["url"].startswith("/media/"))
        seq = ctl.ex_seq
        ctl._on_report({"type": "video", "seq": seq, "pos": 10, "dur": 70, "muted": False})
        self.assertAlmostEqual(ctl.exercise_left(), 60)
        ctl._on_report({"type": "ended", "seq": seq - 1})            # чужой (старый) ролик — не трогаем
        self.assertEqual(ctl.mode, "exercise")
        ctl._on_report({"type": "ended", "seq": seq})
        self.assertEqual(ctl.server.snapshot()["mode"], "idle")
        # вкладка: подключилась, звук не разрешён → разрешён
        ctl._on_report({"type": "clients", "count": 1})
        ctl._on_report({"type": "hello", "unlocked": False})
        self.assertEqual(ctl.tab_status()[1], "accent")
        ctl._on_report({"type": "unlock"})
        self.assertEqual(ctl.tab_status()[1], "ok")

    def test_missing_exercise_file_is_reported(self):
        msgs = []
        self.ctl.message.connect(lambda t, warn: msgs.append((t, warn)))
        self.w.exercises[0].path = str(self.data / "нет.mp4")
        self.ctl.store.put(self.w)
        self.ctl.launch(self.w.id)
        self.ctl.start_exercise(0)
        self.assertEqual(self.ctl.mode, "idle")
        self.assertTrue(any("Нет файла" in t for t, _ in msgs))

    def test_shift_schedule_and_restore(self):
        ctl = self.ctl
        ctl.launch(self.w.id)
        ctl.start_now(3)
        ag = ctl.agenda()
        self.assertEqual((ag.phase, ag.index), ("live", 3))
        anchor = ctl.store.live.anchor
        ctl.timer_window.close_silently()
        ctl.timer_window = None
        ctl.restore()                                                # перезапуск программы — эфир продолжается
        self.assertIsNotNone(ctl.timer_window)
        self.assertEqual(ctl.store.live.anchor, anchor)
        ctl.stop_live()
        self.assertIsNone(ctl.store.live)
        self.assertIsNone(ctl.timer_window)

    def test_close_timer_asks_and_ends_live(self):
        ctl = self.ctl
        ctl.launch(self.w.id)
        tw = ctl.timer_window
        orig, orig_clicked = QMessageBox.exec, QMessageBox.clickedButton
        try:
            QMessageBox.exec = lambda box: box.button(QMessageBox.StandardButton.NoButton) or 0
            # «Отмена»: окно и эфир остаются
            QMessageBox.clickedButton = lambda box: None
            tw.close()
            self.assertTrue(tw.isVisible())
            self.assertIsNotNone(ctl.store.live)
            # «Завершить эфир»
            QMessageBox.clickedButton = lambda box: next(b for b in box.buttons()
                                                         if b.text() == "Завершить эфир")
            tw.close()
            self.assertFalse(tw.isVisible())
            self.assertIsNone(ctl.store.live)
            self.assertIsNone(ctl.timer_window)
        finally:
            QMessageBox.exec = orig
            QMessageBox.clickedButton = orig_clicked

    def test_timer_window_all_sizes_render(self):
        from PySide6.QtGui import QImage
        ctl = self.ctl
        ctl.launch(self.w.id)
        tw = ctl.timer_window
        shots = os.environ.get("EFIR_SHOTS")
        cases = [("before", None), ("live", 2), ("break", 6)]
        sizes = [(150, 70), (230, 110), (300, 170), (440, 270), (900, 500), (420, 720)]
        for phase, idx in cases:
            if idx is None:
                ctl.store.set_live(self.w.id, datetime.now() + timedelta(minutes=12))
            else:
                ctl.start_now(idx)
            for wd, ht in sizes:
                tw.resize(wd, ht)
                pump(10)
                img = tw.grab().toImage()
                self.assertFalse(img.isNull())
                self.assertEqual(tw.strip.isVisible(), wd >= 300 and ht >= 170)
                if shots:
                    Path(shots).mkdir(parents=True, exist_ok=True)
                    img.save(str(Path(shots) / f"timer_{phase}_{wd}x{ht}.png"))
        # кнопка «Зарядка» видна, когда есть зарядки; без зарядок — нет
        tw.resize(440, 270)
        pump(10)
        self.assertTrue(tw.btn_ex.isVisible())
        self.w.exercises = []
        ctl.save_webinar(self.w)
        tw._refresh()
        self.assertFalse(tw.btn_ex.isVisible())
        self.assertIsInstance(QImage(), QImage)

    def test_pin_toggles_setting(self):
        ctl = self.ctl
        ctl.launch(self.w.id)
        tw = ctl.timer_window
        self.assertTrue(tw.btn_pin.isChecked())
        tw.btn_pin.setChecked(False)
        self.assertFalse(self.main.settings.efir_pinned)
        tw.btn_pin.setChecked(True)
        self.assertTrue(self.main.settings.efir_pinned)

    def test_editor_saves_everything(self):
        ctl = self.ctl
        ctl.edit(self.w.id)
        ed = ctl.editors[-1]
        ed.title.setText("Финансовый университет")
        ed.rows[0].minutes.setValue(3)
        ed.add_row()
        ed.rows[-1].name.setText("Перерыв")
        ed.rows[-1]._name_edited("Перерыв")
        ed.break_min.setValue(15)
        ed.save()
        # 0.10: фон, зарядки, экран перерыва — в оформлении (своё окно редактора)
        ctl.edit_look(ctl.store.get(self.w.id).look_id)
        led = ctl.editors[-1]
        self.assertEqual(led.mode, "look")
        led.bg.set_value("anim:pipes")
        led.break_bg.set_value("")
        led.countdown.setChecked(False)
        led._on_picked("anim:aurora")                                 # без запроса галереи — не трогаем
        self.assertEqual(led.bg.value(), "anim:pipes")
        led._pick_target = led.break_bg
        led._on_picked("anim:aurora")
        led.save()
        w = ctl.store.get(self.w.id)
        self.assertEqual(w.title, "Финансовый университет")
        self.assertEqual(w.schedule[0].min, 3)
        self.assertEqual((w.schedule[-1].name, w.schedule[-1].kind), ("Перерыв", KIND_BREAK))
        self.assertEqual((w.background, w.break_background, w.break_min, w.break_countdown),
                         ("anim:pipes", "anim:aurora", 15, False))
        self.assertEqual(len(w.exercises), 2)

    def test_new_template_editor(self):
        self.ctl.edit(None)
        ed = self.ctl.editors[-1]
        self.assertTrue(ed.is_new)
        ed.title.setText("Новый")
        ed.save()
        self.assertIn("Новый", [w.title for w in self.ctl.store.webinars])

    def test_window_lists_imports_and_auto_imports_legacy(self):
        from PySide6.QtGui import QGuiApplication
        from autoprint.ui.efir_window import WebinarCard
        root = fake_timer_folder()
        orig = legacy.candidates
        legacy.candidates = lambda: [root]
        try:
            self.ctl.store.webinars.clear()                             # пусто → перенос из «Таймера вебинара»
            self.ctl.store.save()
            self.ctl.show_window()
            win = self.ctl.window
            pump(20)
            cards = win.list_host.findChildren(WebinarCard)
            self.assertEqual(sorted(c.w.title for c in cards), ["Вебинар 1Т (Первая пара)", "Вторая пара"])
            QGuiApplication.clipboard().setText('Ответ:\n{"title": "ИИ", "schedule": [{"name": "А", "min": 3}]}')
            win.import_clipboard()
            pump(20)
            self.assertIn("ИИ", [w.title for w in self.ctl.store.webinars])
            self.ctl.store.webinars.clear()                             # второй раз сам не переносит
            self.ctl.auto_import_legacy()
            self.assertEqual(self.ctl.store.webinars, [])
        finally:
            legacy.candidates = orig


class AiComposeTest(ControllerTest.__base__):
    """«Нейросеть → Составить по описанию»: ответ разбирается в шаблон и открывается в редакторе."""

    def setUp(self):
        from autoprint.ui import efir_control
        from autoprint.efir import store as store_mod
        self.data = TMP / f"ai-{time.time_ns()}"
        self._efir_dir = store_mod.efir_dir
        store_mod.efir_dir = lambda: self.data
        self.ctl = efir_control.EfirController(FakeMain())
        self.ctl.store.imported_legacy = True

    def tearDown(self):
        from autoprint.efir import store as store_mod
        for e in list(self.ctl.editors):
            e._dirty = False
            e.close()
        if self.ctl.window is not None:
            self.ctl.window.close()
        self.ctl.server.stop()
        store_mod.efir_dir = self._efir_dir

    def test_answer_becomes_template(self):
        from autoprint import ai
        self.ctl.show_window()
        win = self.ctl.window
        orig_cfg, orig_ask = ai.configured, ai.ask
        try:
            ai.configured = lambda s: True
            answer = ('```json\n{"title": "Пара ИИ", "start": "12:00", "schedule": '
                      '[{"name": "Теория", "min": 20}, {"name": "Перерыв", "min": 10}]}\n```')
            ai.ask = lambda s, system, user, **k: (answer, "Тест")
            from PySide6.QtWidgets import QInputDialog
            QInputDialog_orig = QInputDialog.getMultiLineText
            QInputDialog.getMultiLineText = staticmethod(lambda *a, **k: ("теория 20, перерыв 10", True))
            win.compose_ai()
            for _ in range(100):
                pump(20)
                if not win._ai_busy:
                    break
            w = next(x for x in self.ctl.store.webinars if x.title == "Пара ИИ")
            self.assertEqual([a.kind for a in w.schedule], [KIND_NORMAL, KIND_BREAK])
            self.assertTrue(any(e.w.id == w.id for e in self.ctl.editors))
            win._on_ai_done("", "нет сети")
            self.assertFalse(win._ai_busy)
        finally:
            ai.configured, ai.ask = orig_cfg, orig_ask
            QInputDialog.getMultiLineText = QInputDialog_orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
