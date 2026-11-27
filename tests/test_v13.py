"""1.3 — пульт: управление уроком снаружи (Macro Deck, Stream Deck, curl) — GET/POST /api/<команда>?key=…
и файлы со временем и этапами для кнопок. Без окон на экране.

    python tests/test_v13.py
"""
from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import quiet  # noqa: E402,F401  — до PySide6: offscreen, своя папка данных

from test_v10 import pump, stage  # noqa: E402
from test_v121 import close, videos, window  # noqa: E402

from autoprint.storage import BLOCK_IMAGE, Block, Template  # noqa: E402


class FakeEp:
    def __init__(self, dev_id, muted=False):
        self.id, self._m = dev_id, muted

    def muted(self):
        return self._m

    def set_muted(self, on):
        self._m = bool(on)


class FakeAudio:
    """Подставные устройства: настоящие звук и микрофон тесты не трогают никогда."""

    def __init__(self):
        from autoprint.audio import CAPTURE, RENDER
        self.eps = {CAPTURE: [FakeEp("mic-usb"), FakeEp("broadcast"), FakeEp("spare", muted=True)],
                    RENDER: [FakeEp("speakers"), FakeEp("tv")]}
        self.defaults = {CAPTURE: {"broadcast"}, RENDER: {"speakers"}}

    def endpoints(self, flow):
        return list(self.eps[flow])

    def default_ids(self, flow):
        return set(self.defaults[flow])

    def state(self, flow):
        return {e.id: e.muted() for e in self.eps[flow]}


def deck_lesson() -> Template:
    from autoprint.storage import BLOCK_MARKDOWN
    t = Template("Урок пульта", [
        stage("Зарядка для глаз", 5, id="d1", stage_kind="exercise"),
        stage("Тренажёры", 10, id="d2"),
        Block(BLOCK_MARKDOWN, "Напишите **average(nums)**\n\nПроверьте на [5, 4, 3]", role="task", id="tk1",
              title="Средний балл", minutes=5),
        Block(BLOCK_IMAGE, "s1.png", id="i1", slide=1), Block(BLOCK_IMAGE, "s2.png", id="i2", slide=2),
        Block(BLOCK_IMAGE, "s3.png", id="i3", slide=3),
        stage("Перерыв", 7, id="d3", stage_kind="break"),
        stage("Итоги первой части", 5, id="d4"),
    ], id="D")
    return t


class DeckTest(unittest.TestCase):
    port = 18950

    def setUp(self):
        from autoprint.efir.model import Look
        self.win = window([deck_lesson()], self.port)
        self.look = Look(title="Пульт", background="color:#123456", exercises=videos("Глаза 1", "Глаза 2"))
        self.win.efir.save_look(self.look)
        self.win.store.get("D").look = self.look.id
        self.win.printer.set_focus("D")
        self.win.settings.exercise_pick = "next"
        self.win.settings.deck_on = True
        self.win.deck.apply()
        self.key = self.win.deck.ensure_key()
        from autoprint.audio import Mute
        self.fake = FakeAudio()
        self.win.deck.audio = Mute(self.fake)       # настоящие звук и микрофон не трогаем

    def tearDown(self):
        if self.win.efir.live_webinar() is not None:
            self.win.efir.stop_live()
        close(self.win)

    # ---------------------------------------------------------------- запрос как от Macro Deck
    def api(self, cmd: str, key: str | None = None, method: str = "GET", headers: dict | None = None,
            query: str = "", host: str = "") -> tuple[int, dict]:
        """Запрос в потоке (сервер ждёт поток интерфейса — его крутим здесь)."""
        k = self.key if key is None else key
        qs = "&".join(x for x in ((f"key={k}" if k else ""), query) if x)
        url = f"http://127.0.0.1:{self.win.efir.server.port}/api/{cmd}" + ("?" + qs if qs else "")
        h = dict(headers or {})
        if host:
            h["Host"] = host
        req = urllib.request.Request(url, data=b"" if method == "POST" else None, method=method, headers=h)
        out: dict = {}

        def go():
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    out["r"] = (r.status, json.loads(r.read().decode("utf-8")))
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8") or "{}"
                e.close()
                out["r"] = (e.code, json.loads(body) if body.startswith("{") else {})

        th = threading.Thread(target=go)
        th.start()
        while th.is_alive():
            pump(10)
        return out["r"]

    def ok(self, cmd: str, **kw) -> dict:
        code, st = self.api(cmd, **kw)
        self.assertEqual(code, 200, st)
        self.assertTrue(st.get("ok"), st)
        return st

    def start_at(self, index: int):
        self.win.lesson.command({"cmd": "start", "force": True})
        self.win.lesson.command({"cmd": "start_at", "index": index})

    # ---------------------------------------------------------------- доступ
    def test_off_by_default(self):
        from autoprint.storage import Settings
        self.assertFalse(Settings().deck_on)
        self.win.settings.deck_on = False
        code, st = self.api("state")
        self.assertEqual(code, 403)
        self.assertIn("Пульт", st.get("error", ""))

    def test_key_required(self):
        self.assertEqual(self.api("black", key="")[0], 403)
        self.assertEqual(self.api("black", key="wrong-key")[0], 403)
        self.assertEqual(self.win.efir.mode, "idle")          # без ключа ничего не нажалось
        self.ok("state", key="", headers={"X-AutoPrint-Key": self.key})
        self.ok("state", method="POST")

    def test_foreign_host_refused(self):
        """Чужой сайт под своим именем на 127.0.0.1 (DNS-подмена) — не нажмёт, даже зная адрес."""
        self.assertEqual(self.api("black", host="evil.example")[0], 403)
        self.assertEqual(self.win.efir.mode, "idle")

    def test_unknown_command(self):
        code, st = self.api("format_disk")
        self.assertEqual(code, 404)
        self.assertFalse(st.get("ok"))

    def test_head_does_not_press(self):
        """HEAD (проверка «жив ли адрес») ничего не нажимает."""
        self.assertEqual(self.api("black", method="HEAD")[0], 405)
        self.assertEqual(self.win.efir.mode, "idle")

    def test_rejected_body_does_not_press(self):
        """POST со слишком большим телом — отказ, кнопка не нажата."""
        from autoprint.efir.server import BODY_LIMIT
        url = f"http://127.0.0.1:{self.win.efir.server.port}/api/black?key={self.key}"
        req = urllib.request.Request(url, data=b"x" * (BODY_LIMIT + 10), method="POST")
        out = {}

        def go():
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    out["code"] = r.status
            except urllib.error.HTTPError as e:
                out["code"] = e.code
                e.close()
            except OSError as e:
                out["code"] = repr(e)

        th = threading.Thread(target=go)
        th.start()
        while th.is_alive():
            pump(10)
        self.assertEqual(out["code"], 413)
        pump(50)
        self.assertEqual(self.win.efir.mode, "idle")

    def test_busy_program_does_not_press_twice(self):
        """Программа не ответила вовремя (поток окна занят) — «нажмите ещё раз», и запоздалое нажатие не
        выполняется: иначе повтор переключил бы «Чёрный» дважды."""
        from autoprint.ui import deck_control
        old = deck_control.CALL_TIMEOUT_S
        deck_control.CALL_TIMEOUT_S = 0.2
        try:
            out = {}
            th = threading.Thread(target=lambda: out.update(r=self.win.deck._from_server("black", {}, self.key)))
            th.start()
            th.join(5)                                     # окно не крутим — программа «занята»
            self.assertEqual(out["r"][0], 503)
            self.assertTrue(out["r"][1].get("retry"))
            pump(100)
            self.assertEqual(self.win.efir.mode, "idle")
        finally:
            deck_control.CALL_TIMEOUT_S = old

    def test_port_moved_shown(self):
        """8791 был занят — сервер на другом порту: в настройках об этом сказано (ссылки до перезапуска)."""
        srv = self.win.efir.server
        self.assertFalse(self.win.deck.info()["port_moved"])
        want = srv.want_port
        srv.want_port = srv.port - 1
        try:
            info = self.win.deck.info()
            self.assertTrue(info["port_moved"])
            self.assertIn(f":{srv.port}/api/", info["links"][0]["url"])
        finally:
            srv.want_port = want

    def test_new_key_stops_old_links(self):
        old = self.key
        self.key = self.win.deck.new_key()
        self.assertNotEqual(old, self.key)
        self.assertEqual(self.api("state", key=old)[0], 403)
        self.ok("state")

    # ---------------------------------------------------------------- экран учеников
    def test_black_toggles_and_background(self):
        st = self.ok("black")
        self.assertEqual(self.win.efir.mode, "black")
        self.assertEqual(st["screen"], "black")
        self.assertTrue(st["black"])
        st = self.ok("black")                                 # ещё раз — снова фон, как значок в программе
        self.assertEqual(self.win.efir.mode, "idle")
        self.assertFalse(st["black"])
        self.ok("black")
        self.ok("background")
        self.assertEqual(self.win.efir.mode, "idle")

    def test_exercise_starts_then_pauses(self):
        st = self.ok("exercise")
        ef = self.win.efir
        self.assertEqual(ef.mode, "exercise")
        self.assertTrue(st["exercise"])
        self.assertFalse(st["exercise_paused"])
        self.ok("exercise")                                   # сразу второй раз (двойное нажатие) — не пауза
        self.assertFalse(ef.ex_paused)
        ef.ex_started -= 10
        st = self.ok("exercise")                              # идёт — пауза
        self.assertTrue(ef.ex_paused)
        self.assertTrue(st["exercise_paused"])
        self.ok("exercise")                                   # ещё раз — дальше
        self.assertFalse(ef.ex_paused)
        self.assertEqual(ef.mode, "exercise")

    def test_exercise_ask_setting_plays_in_turn(self):
        """«Спросить, какое видео» — на пульте меню нет: видео по очереди."""
        self.win.settings.exercise_pick = "ask"
        self.ok("exercise")
        self.assertEqual(self.win.efir.mode, "exercise")

    def test_break_by_plan_during_break_stage(self):
        """Идёт этап «Перерыв» на 7 минут — перерыв ученикам на все 7 минут с этой минуты; второе нажатие его не
        начинает заново."""
        self.start_at(2)
        st = self.ok("break")
        ef = self.win.efir
        self.assertEqual(ef.mode, "break")
        self.assertEqual(ef.brk_total, 7 * 60)
        self.assertTrue(st["break"])
        self.assertRegex(st["break_left"], r"^0[67]:\d\d$")
        seq = ef.brk_seq
        self.ok("break")
        self.assertEqual(ef.brk_seq, seq)

    def test_break_before_its_stage_uses_plan_minutes(self):
        """Этап-перерыв ещё не наступил — перерыв всё равно его минут (как «По плану» в программе)."""
        self.start_at(1)
        self.ok("break")
        self.assertEqual(self.win.efir.brk_total, 7 * 60)

    def test_break_add(self):
        self.start_at(2)
        self.ok("break")
        ef = self.win.efir
        ends = ef.brk_ends
        self.ok("break_add")
        self.assertAlmostEqual(ef.brk_ends - ends, 300, delta=2)
        self.ok("break_add", query="min=1")
        self.assertAlmostEqual(ef.brk_ends - ends, 360, delta=2)

    def test_break_add_odd_values(self):
        self.start_at(2)
        self.ok("break")
        ef = self.win.efir
        ends = ef.brk_ends
        self.ok("break_add", query="min=0")               # ноль — ничего
        self.assertAlmostEqual(ef.brk_ends, ends, delta=1)
        self.ok("break_add", query="min=abc")             # не число — как без него, +5
        self.assertAlmostEqual(ef.brk_ends - ends, 300, delta=2)
        st = self.ok("break_add", query="min=1e400")      # огромное — не ошибка
        self.assertTrue(st["break"])

    def test_slide_toggle_and_arrows(self):
        st = self.ok("slide_next")                            # слайд не показан — стрелки ничего не делают
        self.assertEqual(self.win.efir.mode, "idle")
        self.assertTrue(st["slides"])
        self.assertEqual(st["slides_total"], 3)
        st = self.ok("slide")
        self.assertEqual(self.win.efir.mode, "slide")
        self.assertEqual(st["slide_text"], "1 / 3")
        st = self.ok("slide_next")
        self.assertEqual(st["slide_text"], "2 / 3")
        self.ok("slide_next")
        st = self.ok("slide_next")                            # последний — дальше некуда
        self.assertEqual(st["slide_text"], "3 / 3")
        st = self.ok("slide_prev")
        self.assertEqual(st["slide_text"], "2 / 3")
        st = self.ok("slide")                                 # ещё раз «Слайд» — снова фон
        self.assertEqual(self.win.efir.mode, "idle")
        self.assertFalse(st["slide"])
        self.assertEqual(st["slide_text"], "")
        st = self.ok("slide")                                 # и снова тот же слайд, а не первый
        self.assertEqual(st["slide_text"], "2 / 3")

    def test_slide_number_is_position(self):
        """Номера слайдов с пропусками (картинку удалили) — «2 / 3», а не «5 / 3»."""
        t = self.win.store.get("D")
        for b, n in zip([b for b in t.blocks if b.type == BLOCK_IMAGE], (1, 5, 9)):
            b.slide = n
        self.ok("slide")
        st = self.ok("slide_next")
        self.assertEqual(st["slide_text"], "2 / 3")

    def test_no_slides_in_lesson(self):
        t = self.win.store.get("D")
        t.blocks = [b for b in t.blocks if b.type != BLOCK_IMAGE]
        st = self.ok("slide")
        self.assertEqual(self.win.efir.mode, "idle")
        self.assertFalse(st["slides"])

    # ---------------------------------------------------------------- звук и микрофон
    def test_mic_toggle(self):
        from autoprint.audio import CAPTURE
        st = self.ok("state")
        self.assertFalse(st["mic_muted"])
        st = self.ok("mic")
        self.assertTrue(st["mic_muted"])
        self.assertTrue(all(self.fake.state(CAPTURE).values()))
        st = self.ok("mic")
        self.assertFalse(st["mic_muted"])
        self.ok("mic_off")
        self.ok("mic_off")                                    # «выключить» дважды — всё ещё выключено
        self.assertTrue(self.ok("state")["mic_muted"])
        self.assertFalse(self.ok("mic_on")["mic_muted"])

    def test_sound_toggle(self):
        from autoprint.audio import RENDER
        st = self.ok("sound")
        self.assertTrue(st["sound_muted"])
        self.assertEqual(self.fake.state(RENDER), {"speakers": True, "tv": True})
        self.assertFalse(self.ok("sound_on")["sound_muted"])
        self.win.deck.write_files()
        self.assertEqual(self.read("sound_muted.txt"), "false")
        self.ok("sound_off")
        self.win.deck.write_files()
        self.assertEqual(self.read("sound_muted.txt"), "true")

    # ---------------------------------------------------------------- подготовка
    def test_prepare_opens_tabs(self):
        """«Подготовка» — вкладки из настроек в браузере; вкладка учеников уже на связи — её второй раз не открывать."""
        from autoprint import app_cmd
        opened = []
        old = app_cmd.open_url
        app_cmd.open_url = lambda url: opened.append(url) or True
        tabs = []
        self.win.efir.open_tab = lambda: tabs.append(1)
        try:
            self.win.settings.deck_prepare = ["https://lms.example/course", "https://meet.example/room"]
            self.ok("prepare")
            self.assertEqual(opened, ["https://lms.example/course", "https://meet.example/room"])
            self.assertEqual(tabs, [])                       # вкладка учеников уже открыта (clients = 1)
            self.win.efir.clients = 0
            self.ok("prepare")
            self.assertEqual(tabs, [1])
            self.win.settings.deck_prepare_screen = False
            self.ok("prepare")
            self.assertEqual(tabs, [1])
            self.win.settings.deck_prepare = ["javascript:alert(1)", "file:///C:/Windows/win.ini"]
            opened.clear()
            self.ok("prepare")                               # не сайты — не открываем (на случай правки файла руками)
            self.assertEqual(opened, [])
        finally:
            app_cmd.open_url = old
            self.win.efir.clients = 1

    # ---------------------------------------------------------------- этапы и время
    def test_stages_around_current(self):
        """Идёт «Тренажёры»: слева «Зарядка для глаз», справа «Итоги…» не сразу — следующий «Перерыв»."""
        self.start_at(1)
        st = self.ok("state")
        self.assertEqual(st["phase"], "live")
        self.assertEqual(st["prev"], "Зарядка для глаз")
        self.assertEqual(st["now"], "Тренажёры")
        self.assertEqual(st["next"], "Перерыв")
        self.assertEqual((st["stage"], st["stages"]), (2, 4))
        self.assertRegex(st["left"], r"^(09:5\d|10:00)$")
        self.assertGreater(st["left_s"], 590)

    def test_first_and_last_stage(self):
        self.start_at(0)
        st = self.ok("state")
        self.assertEqual((st["prev"], st["now"], st["next"]), ("", "Зарядка для глаз", "Тренажёры"))
        self.start_at(3)
        st = self.ok("state")
        self.assertEqual((st["prev"], st["now"], st["next"]), ("Перерыв", "Итоги первой части", ""))

    def test_before_lesson(self):
        """Урок не начат — в центре название урока, справа первый этап, времени нет."""
        st = self.ok("state")
        self.assertEqual(st["phase"], "none")
        self.assertEqual(st["now"], "Урок пульта")
        self.assertEqual(st["next"], "Зарядка для глаз")
        self.assertEqual(st["left"], "")

    def test_after_lesson(self):
        from datetime import datetime, timedelta
        self.win.lesson.command({"cmd": "start", "force": True})
        live = self.win.efir.store.live
        self.win.efir.store.set_live(live.webinar_id, datetime.now() - timedelta(minutes=40))
        st = self.ok("state")
        self.assertEqual(st["phase"], "after")
        self.assertEqual(st["now"], "Урок закончен")
        self.assertEqual(st["prev"], "Итоги первой части")
        self.assertEqual(st["left"], "")

    # ---------------------------------------------------------------- файлы для кнопок
    def read(self, name: str) -> str:
        return (self.win.deck.folder / name).read_text(encoding="utf-8")

    def test_files_for_buttons(self):
        self.start_at(1)
        self.win.deck.write_files()
        self.assertEqual(self.read("prev.txt"), "Зарядка для глаз")
        self.assertEqual(self.read("now.txt"), "Тренажёры")
        self.assertEqual(self.read("next.txt"), "Перерыв")
        self.assertRegex(self.read("left.txt"), r"^(09:5\d|10:00)$")
        self.assertEqual(self.read("screen.txt"), "idle")
        self.assertEqual(self.read("black.txt"), "false")
        raw = (self.win.deck.folder / "now.txt").read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))      # без BOM и без перевода строки — ровно текст
        self.assertFalse(raw.endswith(b"\n"))
        self.ok("black")
        self.win.deck.write_files()
        self.assertEqual(self.read("black.txt"), "true")
        self.assertEqual(self.read("screen.txt"), "black")
        st = json.loads(self.read("state.json"))
        self.assertEqual(st["now"], "Тренажёры")

    def test_files_follow_screen_without_waiting(self):
        """Нажали «Чёрный» в программе — файл кнопки меняется сразу, а не через секунду."""
        self.win.deck.write_files()
        self.win.lesson.command({"cmd": "black"})
        pump(50)
        self.assertEqual(self.read("black.txt"), "true")

    def test_files_neutral_when_turned_off(self):
        """Пульт выключили — в файлах не застывшее время и не подсвеченный «Чёрный», а «выключено»."""
        self.start_at(1)
        self.ok("black")
        self.win.deck.write_files()
        self.assertEqual(self.read("black.txt"), "true")
        self.win.settings.deck_on = False
        self.win.deck.apply()
        self.assertEqual(self.read("black.txt"), "false")
        self.assertEqual(self.read("left.txt"), "")
        self.assertEqual(self.read("screen.txt"), "off")
        self.assertEqual(self.read("now.txt"), "Пульт выключен")

    def test_no_files_when_off(self):
        import shutil
        shutil.rmtree(self.win.deck.folder, ignore_errors=True)
        self.win.settings.deck_on = False
        self.win.deck.apply()
        self.win.deck.write_files()
        self.assertFalse((self.win.deck.folder / "now.txt").exists())


class MuteTest(unittest.TestCase):
    """Выключить все микрофоны / весь звук и включить обратно — только то, что выключили сами."""

    def setUp(self):
        from autoprint.audio import Mute
        self.fake = FakeAudio()
        self.m = Mute(self.fake)

    def test_mic_off_mutes_every_microphone(self):
        from autoprint.audio import CAPTURE
        self.assertFalse(self.m.muted(CAPTURE))
        self.assertTrue(self.m.toggle(CAPTURE))
        self.assertEqual(self.fake.state(CAPTURE), {"mic-usb": True, "broadcast": True, "spare": True})
        self.assertTrue(self.m.muted(CAPTURE))

    def test_mic_on_keeps_spare_muted(self):
        """Запасной микрофон был выключен ещё до нас — после «включить» он так и выключен."""
        from autoprint.audio import CAPTURE
        self.m.toggle(CAPTURE)
        self.assertFalse(self.m.toggle(CAPTURE))
        self.assertEqual(self.fake.state(CAPTURE), {"mic-usb": False, "broadcast": False, "spare": True})

    def test_on_after_restart_turns_on_default(self):
        """Выключили, программу перезапустили (что выключали — забыто): «включить» — устройство по умолчанию."""
        from autoprint.audio import CAPTURE, Mute
        self.m.set(CAPTURE, True)
        fresh = Mute(self.fake)
        fresh.set(CAPTURE, False)
        self.assertEqual(self.fake.state(CAPTURE), {"mic-usb": True, "broadcast": False, "spare": True})

    def test_sound_separate_from_mic(self):
        from autoprint.audio import CAPTURE, RENDER
        self.m.set(RENDER, True)
        self.assertEqual(self.fake.state(RENDER), {"speakers": True, "tv": True})
        self.assertFalse(self.m.muted(CAPTURE))

    def test_no_devices(self):
        from autoprint.audio import CAPTURE
        self.fake.eps[CAPTURE] = []
        self.assertIsNone(self.m.muted(CAPTURE))
        self.assertEqual(self.m.set(CAPTURE, True), 0)


class CoreAudioReadTest(unittest.TestCase):
    """Настоящие устройства Windows — только ЧИТАЕМ (выключено ли): ничего не меняем."""

    def test_read_real_devices(self):
        from autoprint.audio import CAPTURE, RENDER, CoreAudio, Mute
        ca = CoreAudio()
        for flow in (RENDER, CAPTURE):
            eps = ca.endpoints(flow)
            try:
                for ep in eps:
                    self.assertTrue(ep.id)
                    self.assertIn(ep.muted(), (True, False))
            finally:
                for ep in eps:
                    ep.close()
            self.assertIsInstance(ca.default_ids(flow), set)
            self.assertIn(Mute(ca).muted(flow), (True, False, None))


class FakeMD:
    """Подставной Macro Deck: что программа создаёт и какие значения шлёт (настоящий не трогаем). Новый профиль —
    как настоящий: сам заводит пустую главную страницу «Home»."""

    def __init__(self, pending=0, profiles=None, folders=None, variables=None, widgets=None):
        self.pending = pending
        self.profiles = profiles or []
        self.folders = folders or []
        self.vars_ = variables or []
        self.widgets = widgets or []
        self.applied = []
        self.sets = []
        self.actions = []
        self.down = False

    def _check(self):
        if self.down:
            from autoprint.macrodeck import MacroDeckError
            raise MacroDeckError("Macro Deck не отвечает — он запущен на этом компьютере?")

    def items(self, entity, **kw):
        self._check()
        if entity == "folders":
            return [f for f in self.folders if not kw.get("profileId") or f.get("profileId") == kw["profileId"]]
        if entity == "widgets":
            return [w for w in self.widgets if not kw.get("folderId") or w.get("folderId") == kw["folderId"]]
        return {"profiles": self.profiles, "variables": self.vars_}[entity]

    def apply(self, changes, dry=False):
        from autoprint.macrodeck import MacroDeckError
        self._check()
        if self.pending:
            self.pending -= 1
            raise MacroDeckError("An error occurred: CONFIRMATION_PENDING: Macro Deck is asking the user")
        self.applied.append(changes)
        ids = {}
        for c in changes:
            if c["op"] == "create" and c["entity"] == "widget" and c.get("ref"):
                ids[c["ref"]] = "wid-" + c["ref"][2:]
            if c["op"] == "create" and c["entity"] == "profile":
                ids[c["ref"]] = "prof-1"
                self.profiles.append({"id": "prof-1", "name": c["data"]["name"]})
                self.folders.append({"id": "home-1", "name": "Home", "profileId": "prof-1", "isDefault": True})
        return {"valid": True, "applied": True, "createdIds": ids, "confirmations": []}

    def call(self, tool, args):
        self._check()
        self.actions.append((tool, args))
        return {"status": "Succeeded"}

    def set_var(self, name, value):
        self._check()
        self.sets.append((name, value))


def svg_of(value: str) -> str:
    import base64
    return base64.b64decode(value.split(",", 1)[1]).decode("utf-8")


class MacroDeckPageTest(unittest.TestCase):
    """Страница «Урок» для Macro Deck: раскладка 7 × 3, кнопки — картинки программы и команды пульта."""

    def test_layout_fits_phone_grid(self):
        from autoprint import macrodeck as md
        w = md.layout("http://127.0.0.1:8791/api/?key=K")
        cells = set()
        for x in w:
            for dx in range(x["width"]):
                cell = (x["positionX"] + dx, x["positionY"])
                self.assertNotIn(cell, cells)                 # кнопки не налезают друг на друга
                self.assertLess(cell[0], md.COLS)
                self.assertLess(cell[1], md.ROWS)
                cells.add(cell)
        top = sorted((x["positionX"], x["width"], x["data"][md.MARK]) for x in w if x["positionY"] == 0)
        self.assertEqual(top, [(0, 2, "prev"), (2, 3, "now"), (5, 2, "next")])
        urls = [x["data"]["flows"][0]["children"][0]["parameters"][1]["value"] for x in w if x["data"].get("flows")]
        for c in ("background", "black", "exercise", "break", "slide", "slide_prev", "slide_next", "prepare", "sound", "mic"):
            self.assertIn(f"http://127.0.0.1:8791/api/{c}?key=K", urls)
        for x in w:
            self.assertEqual(x["data"]["label"], "")                       # подписи — на картинке, не поверх
            self.assertTrue(x["data"]["imageUrl"].startswith("data:image/svg+xml;base64,"))

    def test_images_show_what_students_see(self):
        from autoprint import deckart as a
        from autoprint import macrodeck as md
        st = {"phase": "live", "prev": "Зарядка для глаз", "now": "Тренажёры", "left": "12:40", "left_s": 760,
              "frac": 0.4, "next": "Итоги первой части", "screen": "black", "mic_muted": True, "slides": True}
        img = md.images(st, "tiles")
        self.assertIn(a.ACCENT, img["black"])                             # нажатое — янтарным
        self.assertNotIn(a.ACCENT, img["bg"])
        self.assertIn(a.LIVE, img["mic"])                                 # микрофон выключен — красным
        self.assertIn("Выключен", img["mic"])
        self.assertIn(a.OFF, img["prev_s"])                               # слайда нет — стрелки погашены
        self.assertIn("Тренажёры", img["now"])
        self.assertIn("Зарядка для глаз", img["prev"])
        self.assertNotIn("12:40", img["now"])                             # время — подписью Macro Deck
        pg = md.page(st, "tiles", "http://127.0.0.1:8791/api/?key=K")
        self.assertEqual(pg["now"]["label"], "{{ vars.apc_left }}")
        self.assertEqual(pg["now"]["labelColor"], a.TEXT)
        v = md.values(st)
        self.assertEqual((v["apc_prev"], v["apc_now"], v["apc_left"], v["apc_next"]),
                         ("Зарядка для глаз", "Тренажёры", "12:40", "Итоги первой части"))
        st2 = {"phase": "live", "now": "Перерыв", "left": "00:40", "left_s": 40, "screen": "break",
               "break_left": "08:12", "slide": False}
        pg = md.page(st2, "outline")
        self.assertEqual(pg["now"]["labelColor"], a.LIVE)                 # последняя минута — красным
        self.assertEqual(pg["break"]["label"], "{{ vars.apc_break_left }}")   # перерыв — отсчёт на кнопке
        self.assertEqual(md.values(st2)["apc_break_left"], "08:12")
        self.assertEqual(md.page({"screen": "idle"})["break"]["label"], "")
        img = md.images({"screen": "slide", "slide": True, "slides": True, "slide_text": "2 / 12"})
        self.assertIn("2/12", img["slide"])

    def test_long_names_fit(self):
        """Длинное название этапа — не шире кнопки: переносится и мельчает, в крайнем случае многоточие."""
        from autoprint import deckart as a
        lines, size = a.fit("ФУ 1.6 · Занятие 6 — практика: журнал, настройки и чёрный список", a.width_of(3) - 32, 18, 3, 12)
        self.assertLessEqual(len(lines), 3)
        for ln in lines:
            self.assertLessEqual(a.text_w(ln, size), a.width_of(3) - 32 + 0.5)
        lines, size = a.fit("Оченьдлинноеслово" * 4, 100, 15, 1, 10)
        self.assertTrue(lines[0].endswith("…"))
        self.assertLessEqual(a.text_w(lines[0], size), 100.5)

    def test_styles_differ(self):
        from autoprint import deckart as a
        from autoprint import macrodeck as md
        st = {"screen": "black"}
        looks = {style: md.images(st, style)["black"] for style in md.STYLES}
        self.assertEqual(set(md.STYLES), {"glass", "tiles", "outline"})
        self.assertEqual(len(set(looks.values())), 3)
        self.assertEqual(md.images(st, "nonsense")["black"], md.images(st, a.DEFAULT_STYLE)["black"])

    def test_glass_style(self):
        """«Стекло» (по макету владельца): тёмное стекло с переливом, белые значки, нажатое — синей рамкой
        и синим светом; идущий этап — синей панелью; урок не идёт — шапочка и название урока слева."""
        from autoprint import deckart as a
        from autoprint import macrodeck as md
        from autoprint.settings_spec import FIELDS
        from autoprint.storage import Settings
        self.assertEqual(a.DEFAULT_STYLE, "glass")
        self.assertEqual(Settings().deck_style, "glass")                 # новый человек — сразу «Стекло»
        self.assertIn("glass", FIELDS["deck_style"][1])
        st = {"phase": "live", "prev": "Опрос", "now": "Тренажёры", "left": "12:40", "left_s": 760, "frac": 0.4,
              "next": "Разбор множеств", "screen": "idle", "mic_muted": True, "slides": True}
        img = md.images(st, "glass")
        self.assertIn("linearGradient", img["black"])                     # стекло — переливом
        self.assertIn(a.GLASS_FG, img["black"])                           # значок и подпись — белые
        self.assertNotIn(a.GLASS_ON, img["black"])
        self.assertIn(a.GLASS_ON, img["bg"])                              # у учеников фон — синим
        self.assertIn(a.LIVE, img["mic"])                                 # микрофон выключен — красным
        self.assertIn(a.GLASS_OFF_FG, img["prev_s"])                      # слайда нет — стрелки погашены
        self.assertIn(a.GLASS_ON, img["now"])                             # идущий этап — синей панелью
        self.assertNotIn(a.ICONS["cap"], img["now"])
        for k, svg in img.items():
            self.assertNotIn("<filter", svg, k)                           # без фильтров: телефон рисует не всё
            self.assertNotIn("12:40", svg, k)                             # время — подписью Macro Deck
        self.assertEqual(md.page(st, "glass")["now"]["labelColor"], a.GLASS_FG)
        idle = md.images({"now": "ФУ 1.6 · Занятие 6 — практика: журнал, настройки и чёрный список"}, "glass")
        self.assertIn(a.ICONS["cap"], idle["now"])                        # урок не идёт — шапочка
        self.assertIn('text-anchor="start"', idle["now"])                 # и название слева от неё
        self.assertNotIn("Предыдущий", img["prev"] + img["next"])         # без слов «предыдущий / следующий»

    def test_every_template_variable_is_declared(self):
        """Каждая {{ vars.… }} в кнопках — среди переменных, которые программа создаёт и шлёт."""
        import re
        from autoprint import macrodeck as md
        st = {"phase": "live", "now": "Этап", "left": "05:00", "left_s": 300, "screen": "break", "break_left": "01:00"}
        used = set(re.findall(r"vars\.(apc_\w+)", json.dumps(md.layout("http://x/api/?key=K", st))))
        self.assertEqual(used, {"apc_left", "apc_break_left"})
        declared = {n for n, _, _ in md.variables()}
        self.assertEqual(used - declared, set())
        self.assertEqual(used - set(md.values({})), set())

    def test_setup_new_profile_on_its_home_page(self):
        """Новый профиль: кнопки — на его главной странице (её Macro Deck завёл сам), а не в соседней папке;
        телефоны переключаются на него."""
        from autoprint import macrodeck as md
        fake = FakeMD()
        r = md.setup(fake, "http://127.0.0.1:8791/api/?key=K")
        self.assertEqual((r["profile"], r["folder"]), ("prof-1", "home-1"))
        first, second = fake.applied
        self.assertEqual(first[0]["entity"], "profile")
        self.assertEqual(sum(c["entity"] == "variable" for c in first), len(md.variables()))
        self.assertIn({"op": "update", "entity": "folder", "id": "home-1", "data": {"name": "Урок"}}, second)
        widgets = [c for c in second if c["entity"] == "widget"]
        self.assertEqual(len(widgets), len(md.IMAGE_KEYS))
        self.assertTrue(all(c["data"]["folderId"] == "home-1" for c in widgets))
        self.assertFalse(any(c["entity"] == "folder" and c["op"] == "create" for c in second))
        shown = [a[1]["actionId"] for a in fake.actions]
        self.assertEqual(shown, ["change-profile", "change-folder"])
        self.assertEqual(set(r["widgets"]), set(md.IMAGE_KEYS))            # id своих кнопок — для обновлений

    def test_setup_again_keeps_owner_buttons(self):
        """Повторно: свои кнопки заново, кнопки человека на той же странице — как есть; папка прежней версии
        («Урок» рядом с пустой главной) — убрана; уже созданные переменные не создаются заново."""
        from autoprint import macrodeck as md
        fake = FakeMD(profiles=[{"id": "P", "name": "AutoPrintCode"}],
                      folders=[{"id": "H", "name": "Home", "profileId": "P", "isDefault": True},
                               {"id": "OLD", "name": "Урок", "profileId": "P", "isDefault": False},
                               {"id": "X", "name": "Свет", "profileId": "P", "isDefault": False}],
                      variables=[{"name": n} for n, _, _ in md.variables()],
                      widgets=[{"id": "w-ours", "folderId": "H", "data": {"apc": "bg"}},
                               {"id": "w-owner", "folderId": "H", "data": {"label": "Свет в комнате"}}])
        r = md.setup(fake, "http://127.0.0.1:8791/api/?key=K", profile_id="P")
        self.assertEqual(len(fake.applied), 1)                              # профиль и переменные уже есть
        ch = fake.applied[0]
        self.assertEqual(r["profile"], "P")
        self.assertIn({"op": "delete", "entity": "widget", "id": "w-ours"}, ch)
        self.assertNotIn({"op": "delete", "entity": "widget", "id": "w-owner"}, ch)
        self.assertIn({"op": "delete", "entity": "folder", "id": "OLD"}, ch)
        self.assertNotIn({"op": "delete", "entity": "folder", "id": "X"}, ch)
        self.assertFalse(any(c["entity"] in ("profile", "variable") for c in ch))

    def test_sync_updates_only_changed_buttons_whole(self):
        """Нажали «Чёрный» — в Macro Deck уходят только две кнопки (Фон и Чёрный), каждая целиком, с командой."""
        from autoprint import deckart as a
        from autoprint import macrodeck as md
        fake = FakeMD()
        ids = {k: "id-" + k for k in md.IMAGE_KEYS}
        sync = md.Sync(fake, ids, "F")
        base = "http://127.0.0.1:8791/api/?key=K"
        try:
            st = {"screen": "idle"}
            sync.push(md.values(st), md.page(st, "tiles", base))
            self.assertTrue(wait(lambda: len(fake.applied) == 1))
            self.assertEqual(len(fake.applied[0]), len(md.IMAGE_KEYS))        # первый раз — все
            st = {"screen": "black"}
            sync.push(md.values(st), md.page(st, "tiles", base))
            self.assertTrue(wait(lambda: len(fake.applied) == 2))
            ch = {c["id"]: c["data"]["data"] for c in fake.applied[1]}
            self.assertEqual(set(ch), {"id-bg", "id-black"})
            self.assertIn(a.ACCENT, svg_of(ch["id-black"]["imageUrl"]))
            self.assertIn("api/black?key=K", json.dumps(ch["id-black"]["flows"]))   # команда не потерялась
        finally:
            sync.stop()

    def test_sync_finds_buttons_after_restart(self):
        """Id кнопок забыты (программу переустановили) — свои кнопки находятся на странице по пометке."""
        from autoprint import macrodeck as md
        fake = FakeMD(widgets=[{"id": "real-" + k, "folderId": "F", "data": {md.MARK: k}} for k in md.IMAGE_KEYS]
                      + [{"id": "owner", "folderId": "F", "data": {"label": "Свет"}}])
        sync = md.Sync(fake, {}, "F")
        try:
            sync.push({}, md.page({"screen": "black"}))
            self.assertTrue(wait(lambda: len(fake.applied) == 1))
            self.assertIn("real-black", {c["id"] for c in fake.applied[0]})
            self.assertNotIn("owner", {c["id"] for c in fake.applied[0]})
        finally:
            sync.stop()

    def test_sync_sends_only_changes_and_survives_macro_deck_closed(self):
        from autoprint import macrodeck as md
        fake = FakeMD()
        sync = md.Sync(fake)
        sync.RETRY_S = 0.2
        try:
            sync.push({"apc_left": "12:40", "apc_now": "Тренажёры"})
            self.assertTrue(wait(lambda: len(fake.sets) == 2))
            sync.push({"apc_left": "12:39", "apc_now": "Тренажёры"})
            self.assertTrue(wait(lambda: len(fake.sets) == 3))
            self.assertEqual(fake.sets[-1], ("apc_left", "12:39"))
            fake.down = True                                   # Macro Deck закрыли
            sync.push({"apc_left": "12:38"})
            self.assertTrue(wait(lambda: bool(sync.error)))
            fake.down = False                                  # снова запущен — всё заново, а не только изменения
            sync.push({"apc_left": "12:37", "apc_now": "Тренажёры"})
            self.assertTrue(wait(lambda: ("apc_now", "Тренажёры") in fake.sets[3:] and ("apc_left", "12:37") in fake.sets))
            self.assertEqual(sync.error, "")
        finally:
            sync.stop()


def wait(pred, timeout=5.0):
    import time
    end = time.time() + timeout
    while time.time() < end:
        pump(20)
        if pred():
            return True
    return False


class MacroDeckConnectTest(unittest.TestCase):
    """«Настройки → Пульт → Macro Deck»: ключ вставили — страница собрана (ждёт разрешения), ключ зашифрован,
    значения идут; отключили — не идут."""
    port = 18952

    def setUp(self):
        from autoprint.audio import Mute
        self.win = window([deck_lesson()], self.port)
        self.win.printer.set_focus("D")
        self.win.deck.audio = Mute(FakeAudio())
        self.fake = FakeMD(pending=2)
        self.win.deck.md_client = lambda token: self.fake
        self.win.deck.PENDING_WAIT_S = 30

    def tearDown(self):
        self.win.deck._md_stop_sync()
        close(self.win)

    def test_connect_builds_page_and_streams(self):
        from autoprint.macrodeck import Sync
        Sync.RETRY_S = 0.2
        self.win.commands.call({"cmd": "deck_md_connect", "token": "mdmcp_secret_token"})
        self.assertTrue(self.win.settings.deck_on)                    # пульт включился сам
        info = self.win.deck.info()["md"]
        self.assertTrue(info["busy"])
        self.assertTrue(wait(lambda: not self.win.deck.md_busy, 20))
        s = self.win.settings
        self.assertTrue(s.md_token.startswith(("dpapi:", "plain:")))
        self.assertNotIn("mdmcp_secret_token", s.md_token if s.md_token.startswith("dpapi:") else "")
        self.assertEqual(s.md_profile, "prof-1")
        self.assertIn("AutoPrintCode", self.win.deck.md_status)
        widgets = [c for batch in self.fake.applied for c in batch if c["entity"] == "widget"]
        urls = json.dumps(widgets)
        self.assertIn(f"http://127.0.0.1:{self.win.efir.server.want_port}/api/black?key={s.deck_key}", urls)
        from autoprint import deckart

        def updated(key, pred=lambda d: True, since=0):
            return any(c["op"] == "update" and c["entity"] == "widget" and c["data"]["data"].get("apc") == key
                       and pred(c["data"]["data"])
                       for batch in self.fake.applied[since:] for c in batch)

        self.win.lesson.command({"cmd": "black"})
        self.assertTrue(wait(lambda: updated("black", lambda d: deckart.GLASS_ON in svg_of(d["imageUrl"]))))   # «Стекло»: синим
        n0 = len(self.fake.applied)
        self.win.commands.call({"cmd": "set", "key": "deck_style", "value": "outline"})     # другой вид — сразу
        self.assertTrue(wait(lambda: updated("bg", since=n0)))
        self.win.commands.call({"cmd": "deck_md_forget"})
        self.assertEqual(self.win.settings.md_token, "")
        n = len(self.fake.sets)
        self.win.lesson.command({"cmd": "background"})
        pump(300)
        self.assertEqual(len(self.fake.sets), n)

    def test_old_page_rebuilt_after_update(self):
        """Программу обновили, а страница в Macro Deck собрана прежней версией — пересобирается сама при запуске
        пульта, и только потом идут значения."""
        from autoprint import macrodeck as md
        from autoprint.ai import protect
        self.fake.pending = 0
        s = self.win.settings
        s.md_token, s.md_profile, s.md_layout = protect("mdmcp_old"), "", 1
        s.deck_on = True
        self.win.deck.apply()
        self.assertTrue(wait(lambda: not self.win.deck.md_busy and self.fake.applied, 10))
        self.assertTrue(wait(lambda: self.win.deck.md_sync is not None, 5))
        self.assertEqual(s.md_layout, md.LAYOUT)
        self.assertEqual(set(s.md_widgets), set(md.IMAGE_KEYS))
        n = len(self.fake.applied)
        self.win.deck.apply()                                       # уже новая — второй раз не пересобирает
        pump(300)
        self.assertFalse(any(c["entity"] == "profile" or (c["entity"] == "widget" and c["op"] == "create")
                             for batch in self.fake.applied[n:] for c in batch))

    def test_bad_token_reported(self):
        from autoprint.macrodeck import MacroDeckError

        class Refuses(FakeMD):
            def items(self, entity, **kw):
                raise MacroDeckError("Macro Deck не принял ключ — создайте новый: Macro Deck → Настройки → AI clients")

        self.win.deck.md_client = lambda token: Refuses()
        self.win.deck.md_connect("mdmcp_wrong")
        self.assertTrue(wait(lambda: not self.win.deck.md_busy, 10))
        self.assertIn("не принял ключ", self.win.deck.md_status)
        self.assertEqual(self.win.settings.md_token, "")              # неверный ключ не запоминаем


class LanAddressTest(unittest.TestCase):
    """«Адрес этого компьютера в сети» — домашняя сеть (Wi-Fi, провод), а не VPN, Hyper-V или WSL."""

    def test_owner_machine(self):
        """Как у владельца: VPN «Meta» 198.18.0.1, провод 192.168.2.21, Hyper-V и WSL, отключённый Wi-Fi."""
        from autoprint.ui.deck_control import lan_addresses
        nics = [("Meta", "unknown", True, ["198.18.0.1"]), ("Ethernet", "ethernet", True, ["192.168.2.21"]),
                ("Беспроводная сеть", "wifi", False, ["169.254.72.95"]),
                ("Сетевое подключение Bluetooth", "ethernet", False, ["169.254.93.124"]),
                ("Loopback Pseudo-Interface 1", "loopback", True, ["127.0.0.1"]),
                ("vEthernet (Default Switch)", "ethernet", True, ["192.168.160.1"]),
                ("vEthernet (WSL (Hyper-V firewall))", "ethernet", True, ["172.29.240.1"])]
        self.assertEqual(lan_addresses(nics), ["192.168.2.21"])

    def test_wifi_first_and_vpn_dropped(self):
        from autoprint.ui.deck_control import lan_addresses
        nics = [("Ethernet 2", "ethernet", True, ["10.0.0.5"]), ("Wi-Fi", "wifi", True, ["192.168.1.40"]),
                ("Tailscale", "unknown", True, ["100.101.102.103"]), ("VMware Network Adapter VMnet8", "ethernet", True,
                                                                        ["192.168.47.1"])]
        self.assertEqual(lan_addresses(nics), ["192.168.1.40", "10.0.0.5"])

    def test_real_interfaces_do_not_fail(self):
        from autoprint.ui.deck_control import lan_addresses
        self.assertIsInstance(lan_addresses(), list)


class TimerTest(unittest.TestCase):
    """1.3 таймер: на весь экран и задание с отсчётом; вид и конец — в оформлении урока."""
    port = 18953

    def setUp(self):
        from autoprint.efir.model import Look
        self.win = window([deck_lesson()], self.port)
        self.look = Look(title="Таймер", background="color:#123456", timer_min=4)
        self.win.efir.save_look(self.look)
        self.win.store.get("D").look = self.look.id
        self.win.printer.set_focus("D")

    def tearDown(self):
        if self.win.efir.live_webinar() is not None:
            self.win.efir.stop_live()
        close(self.win)

    def screen(self) -> dict:
        return self.win.efir.server._states["screen"]

    def test_look_keeps_timer_settings(self):
        from autoprint.efir.model import Look, look_from_dict
        lk = Look(timer_min=3, timer_task_style="strip", timer_full_style="digits", timer_end="text",
                  timer_end_text="Скоро продолжим", timer_background="color:#000000")
        back = look_from_dict(lk.to_dict())
        for k in ("timer_min", "timer_task_style", "timer_full_style", "timer_end", "timer_end_text", "timer_background"):
            self.assertEqual(getattr(back, k), getattr(lk, k))
        bad = look_from_dict({**lk.to_dict(), "timer_end": "boom", "timer_min": 9999, "timer_task_style": "x"})
        self.assertEqual((bad.timer_end, bad.timer_min, bad.timer_task_style), ("zero", 180, "corner"))
        self.assertEqual(look_from_dict({"title": "Старое"}).timer_end_text, "Время!")    # оформление до 1.3

    def test_full_screen_timer_uses_look_minutes(self):
        self.win.lesson.command({"cmd": "timer"})
        ef = self.win.efir
        self.assertEqual(ef.mode, "timer")
        tm = self.screen()["tmr"]
        self.assertEqual(tm["kind"], "full")
        self.assertEqual(tm["total"], 4 * 60 * 1000)                    # по оформлению урока
        self.assertEqual(tm["style"], "ring")
        self.assertEqual(tm["end"], "zero")
        self.assertIsNone(tm["task"])
        self.win.lesson.command({"cmd": "timer", "minutes": 3})          # своё время из меню
        self.assertEqual(self.screen()["tmr"]["total"], 3 * 60 * 1000)

    def test_task_timer_shows_task_with_its_minutes(self):
        self.win.lesson.command({"cmd": "task_timer", "block": "tk1"})
        ef = self.win.efir
        self.assertEqual(ef.mode, "task")
        tm = self.screen()["tmr"]
        self.assertEqual((tm["kind"], tm["style"]), ("task", "corner"))
        self.assertEqual(tm["total"], 5 * 60 * 1000)                    # минуты задания
        self.assertEqual(tm["task"]["title"], "Средний балл")
        self.assertIn("<b>average(nums)</b>", tm["task"]["html"])
        self.win.lesson.command({"cmd": "task_timer", "block": "tk1", "minutes": 3})   # «у меня быстрые ребята»
        self.assertEqual(self.screen()["tmr"]["total"], 3 * 60 * 1000)

    def test_end_and_style_from_look(self):
        self.look.timer_end, self.look.timer_end_text, self.look.timer_full_style = "text", "Скоро продолжим", "digits"
        self.win.efir.save_look(self.look)
        self.win.efir.webinar = None
        self.win.lesson.command({"cmd": "timer"})
        tm = self.screen()["tmr"]
        self.assertEqual((tm["end"], tm["end_text"], tm["style"]), ("text", "Скоро продолжим", "digits"))
        self.look.timer_end = "empty"
        self.win.efir.save_look(self.look)
        self.win.efir.webinar = None
        self.win.lesson.command({"cmd": "timer"})
        self.assertEqual((self.screen()["tmr"]["end"], self.screen()["tmr"]["end_text"]), ("empty", ""))

    def test_pause_add_restart_and_background(self):
        ef = self.win.efir
        self.win.lesson.command({"cmd": "timer", "minutes": 2})
        self.win.lesson.command({"cmd": "timer_pause"})
        self.assertIsNotNone(ef.tmr_paused)
        self.assertIsNotNone(self.screen()["tmr"]["paused_left"])
        left = ef.timer_left()
        self.win.lesson.command({"cmd": "timer_adjust", "seconds": 60})
        self.assertAlmostEqual(ef.timer_left(), left + 60, delta=1)
        self.win.lesson.command({"cmd": "timer_pause"})                  # дальше
        self.assertIsNone(ef.tmr_paused)
        self.win.lesson.command({"cmd": "timer_restart"})
        self.assertAlmostEqual(ef.timer_left(), ef.tmr_total, delta=1)
        self.win.lesson.command({"cmd": "background"})
        self.assertEqual(ef.mode, "idle")
        self.assertNotIn("tmr", self.screen())

    def test_timer_replaces_slide_and_break(self):
        self.win.lesson.command({"cmd": "start", "force": True})
        self.win.lesson.command({"cmd": "break", "minutes": 5})
        self.win.lesson.command({"cmd": "timer"})
        self.assertNotIn("brk", self.screen())
        self.assertIsNone(self.win.efir.store.brk)                       # перерыв не вернётся после перезапуска

    def test_page_knows_timer(self):
        self.win.lesson.command({"cmd": "task_timer", "block": "tk1"})
        self.win.lesson._last = None
        self.win.lesson.publish()
        lc = self.win.efir.server._states["lesson"]
        ex = lc["efir"]
        self.assertGreater(ex["timer_ends"], 0)
        self.assertEqual(ex["timer_task"], "tk1")
        self.assertEqual(ex["timer_min"], 4)
        item = next(x for x in lc["lesson"]["items"] if x["id"] == "tk1")
        self.assertEqual(item["minutes"], 5)

    def test_task_minutes_editable_and_in_markdown(self):
        from autoprint.lesson_edit import apply
        from autoprint.lesson_md import parse, to_md
        t = self.win.store.get("D")
        md = to_md(t, "media")
        self.assertIn("[!task] Средний балл · 5 мин", md)
        back = parse(md, None, "Урок")
        nb = next(x for x in back.blocks if x.role == "task")
        self.assertEqual((nb.title, nb.minutes), ("Средний балл", 5))
        apply(t, [{"op": "set", "block": "tk1", "fields": {"minutes": 3}}])
        self.assertEqual(t.find_block("tk1").minutes, 3)

    def test_pult_timer_and_task(self):
        from autoprint.audio import Mute
        self.win.settings.deck_on = True
        self.win.deck.apply()
        self.win.deck.audio = Mute(FakeAudio())
        d = self.win.deck
        st = d.run("timer")
        self.assertEqual(self.win.efir.mode, "timer")
        self.assertTrue(st["timer"])
        self.assertRegex(st["timer_left"], r"^0[34]:\d\d$")
        st = d.run("timer_add")
        self.assertRegex(st["timer_left"], r"^0[45]:\d\d$")
        st = d.run("timer")                                              # идёт — убрать
        self.assertEqual(self.win.efir.mode, "idle")
        st = d.run("task")
        self.assertEqual(self.win.efir.mode, "task")
        self.assertTrue(st["task"])
        self.assertTrue(st["has_task"])
        d.run("task")
        self.assertEqual(self.win.efir.mode, "idle")

    def test_phone_page_timer_buttons(self):
        from autoprint import macrodeck as md
        self.assertIn("timer", md.IMAGE_KEYS)
        self.assertIn("task", md.IMAGE_KEYS)
        st = {"screen": "timer", "timer": True, "timer_left": "02:41", "has_task": True}
        pg = md.page(st, "tiles", "http://127.0.0.1:8791/api/?key=K")
        self.assertEqual(pg["timer"]["label"], "{{ vars.apc_timer_left }}")
        self.assertEqual(pg["task"]["label"], "")
        self.assertIn("api/timer?key=K", json.dumps(pg["timer"]["flows"]))
        self.assertEqual(md.values(st)["apc_timer_left"], "02:41")
        img = md.images({"screen": "idle", "has_task": False}, "tiles")
        from autoprint import deckart
        self.assertIn(deckart.OFF, img["task"])                         # заданий в уроке нет — погашено


class ScreenTimerTest(unittest.TestCase):
    """Что видят ученики (вкладка в невидимом Edge): таймер на весь экран и задание с отсчётом; конец — по
    оформлению: 0:00, своя надпись или ничего."""
    port = 18954

    @classmethod
    def setUpClass(cls):
        from cdp import Edge
        from autoprint.efir.model import Look
        cls.win = window([deck_lesson()], cls.port)
        cls.look = Look(title="Таймер", background="color:#14234A", timer_min=4, text_color="#FFFFFF")
        cls.win.efir.save_look(cls.look)
        cls.win.store.get("D").look = cls.look.id
        cls.win.printer.set_focus("D")
        cls.edge = Edge.start(f"http://127.0.0.1:{cls.win.efir.server.port}/?nofade", pump=lambda: pump(5),
                              width=1280, height=720)

    @classmethod
    def tearDownClass(cls):
        cls.edge.close()
        close(cls.win)

    def look_set(self, **kw):
        for k, v in kw.items():
            setattr(self.look, k, v)
        self.win.efir.save_look(self.look)
        self.win.efir.webinar = None

    def js(self, code):
        return self.edge.eval(code)

    def wait(self, cond, timeout=8):
        return self.edge.wait(cond, timeout)

    def finish(self):
        import time
        self.win.efir.tmr_ends = time.time() - 1                         # время вышло
        self.win.efir.publish()

    def test_full_ring_then_zero(self):
        self.look_set(timer_full_style="ring", timer_end="zero")
        self.win.lesson.command({"cmd": "timer"})
        self.assertTrue(self.wait("document.querySelector('#tmr').classList.contains('on') && "
                                  "!!document.querySelector('#tmr .full .ring .arc')"))
        self.assertTrue(self.wait("/^[34]:\\d\\d$/.test(document.querySelector('#tmr .num').textContent)"))
        self.assertEqual(self.js("document.querySelector('#tmr .of').textContent"), "из 4 мин")
        self.finish()
        self.assertTrue(self.wait("document.querySelector('#tmr .num').textContent === '0:00'"))
        self.win.lesson.command({"cmd": "background"})
        self.assertTrue(self.wait("!document.querySelector('#tmr').classList.contains('on')"))

    def test_digits_with_minute_ticks_and_own_text(self):
        self.look_set(timer_full_style="digits", timer_end="text", timer_end_text="Скоро продолжим")
        self.win.lesson.command({"cmd": "timer", "minutes": 3})
        self.assertTrue(self.wait("document.querySelectorAll('#tmr .ticks i').length === 3"))
        self.finish()
        self.assertTrue(self.wait("(() => { const e = document.querySelector('#tmr .end'); return !!e && "
                                  "e.textContent === 'Скоро продолжим' && "
                                  "document.querySelector('#tmr .num').style.display === 'none'; })()"))
        self.win.lesson.command({"cmd": "background"})

    def test_empty_end(self):
        self.look_set(timer_full_style="ring", timer_end="empty")
        self.win.lesson.command({"cmd": "timer", "minutes": 1})
        self.finish()
        self.assertTrue(self.wait("(() => { const e = document.querySelector('#tmr .end'); return !!e && "
                                  "e.textContent === '' && document.querySelector('#tmr .num').style.display === 'none'; })()"))
        self.win.lesson.command({"cmd": "background"})

    def test_task_corner_and_strip(self):
        self.look_set(timer_task_style="corner", timer_end="zero")
        self.win.lesson.command({"cmd": "task_timer", "block": "tk1", "minutes": 3})
        self.assertTrue(self.wait("!!document.querySelector('#tmr .task .t') && "
                                  "document.querySelector('#tmr .task .t').textContent === 'Средний балл' && "
                                  "!!document.querySelector('#tmr .glass .ring .num')"))
        self.assertIn("average(nums)", self.js("document.querySelector('#tmr .task .body').textContent"))
        self.assertEqual(self.js("document.querySelector('#tmr .task .lbl').textContent"), "Задание · 3 мин")
        self.look_set(timer_task_style="strip")
        self.win.lesson.command({"cmd": "task_timer", "block": "tk1", "minutes": 3})
        self.assertTrue(self.wait("!!document.querySelector('#tmr .strip .pill .num') && "
                                  "parseFloat(document.querySelector('#tmr .strip .track i').style.width) > 90"))
        self.win.lesson.command({"cmd": "background"})


class PresetBackgroundTest(unittest.TestCase):
    """1.3: готовые картинки-фоны внутри программы («preset:<ключ>») — для фона, перерыва и таймера."""
    port = 18955

    def test_model_accepts_only_known_presets(self):
        from autoprint.efir.model import PRESET_IMAGES, look_from_dict
        lk = look_from_dict({"background": "preset:waves", "break_background": "preset:nope",
                             "timer_background": "preset:night"})
        self.assertEqual((lk.background, lk.break_background, lk.timer_background), ("preset:waves", "", "preset:night"))
        root = Path(__file__).resolve().parent.parent / "autoprint" / "efir" / "page" / "backgrounds"
        for key, title in PRESET_IMAGES:
            self.assertTrue((root / f"{key}.jpg").is_file(), key)
            self.assertTrue((root / f"{key}-s.jpg").is_file(), key)
            self.assertLess((root / f"{key}.jpg").stat().st_size, 600_000)          # программа не толстеет зря
            self.assertTrue(title)

    def test_served_and_resolved(self):
        win = window([deck_lesson()], self.port)
        try:
            ef = win.efir
            self.assertEqual(ef._bg("preset:waves"), {"kind": "image", "value": "waves.jpg", "url": "/static/bg/waves.jpg"})
            self.assertEqual(ef._bg("preset:nope")["kind"], "color")
            base = f"http://127.0.0.1:{ef.server.port}"
            with urllib.request.urlopen(base + "/static/bg/waves.jpg", timeout=5) as r:
                self.assertEqual(r.headers["Content-Type"], "image/jpeg")
                self.assertEqual(r.read(3), b"\xff\xd8\xff")
            for bad in ("/static/bg/../screen.html", "/static/bg/nope.jpg", "/static/bg/WAVES.JPG"):
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    urllib.request.urlopen(base + bad, timeout=5)
                self.assertEqual(cm.exception.code, 404)
                cm.exception.close()
            from autoprint.app_state import efir_state
            st = efir_state(win)
            self.assertIn(["waves", "Волны"], st["bg_presets"])
            self.assertIsInstance(st["own_images"], list)
        finally:
            close(win)

    def test_build_ships_backgrounds(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
        import build_exe
        datas = build_exe.collect_datas()
        dests = {(Path(src).name, dest) for src, dest in datas}
        self.assertIn(("waves.jpg", "autoprint/efir/page/backgrounds"), dests)
        self.assertIn(("waves-s.jpg", "autoprint/efir/page/backgrounds"), dests)


class AtomicWriteTest(unittest.TestCase):
    """Файл на миг занят (антивирус, индексатор Windows: «Отказано в доступе» при подмене) — запись повторяется,
    а не роняет сохранение урока или оформления."""

    def test_replace_retries_when_file_briefly_busy(self):
        import os
        import tempfile
        from autoprint import storage
        path = Path(tempfile.mkdtemp()) / "x.json"
        calls = []
        real = os.replace

        def flaky(a, b):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError(5, "Отказано в доступе")
            return real(a, b)

        storage.os.replace = flaky
        try:
            storage._atomic_write(path, {"a": 1})
        finally:
            storage.os.replace = real
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"a": 1})
        self.assertEqual(len(calls), 3)

    def test_gives_up_after_a_while(self):
        import os
        import tempfile
        from autoprint import storage
        path = Path(tempfile.mkdtemp()) / "x.json"
        real = os.replace

        def busy(a, b):
            raise PermissionError(5, "Отказано в доступе")

        storage.os.replace = busy
        try:
            with self.assertRaises(PermissionError):
                storage._atomic_write(path, {"a": 1})
        finally:
            storage.os.replace = real


class DeckSettingsTest(unittest.TestCase):
    port = 18951

    def setUp(self):
        self.win = window([deck_lesson()], self.port)

    def tearDown(self):
        close(self.win)

    def test_turn_on_makes_key_and_links(self):
        self.assertEqual(self.win.settings.deck_key, "")
        self.win.commands.call({"cmd": "set", "key": "deck_on", "value": True})
        info = self.win.commands.call({"cmd": "deck_info"})["result"]
        key = self.win.settings.deck_key
        self.assertGreaterEqual(len(key), 16)
        self.assertEqual(info["key"], key)
        urls = {x["cmd"]: x["url"] for x in info["links"]}
        base = f"http://127.0.0.1:{self.win.efir.server.port}/api/"
        self.assertEqual(urls["black"], base + "black?key=" + key)
        for c in ("background", "black", "exercise", "break", "slide", "slide_prev", "slide_next", "state"):
            self.assertIn(c, urls)
        self.assertTrue(info["folder"].endswith("deck"))
        new = self.win.commands.call({"cmd": "deck_new_key"})["result"]
        self.assertNotEqual(new["key"], key)
        self.assertEqual(self.win.settings.deck_key, new["key"])

    def test_prepare_list_setting(self):
        """Список вкладок в настройках: строкой по адресу; без https:// — допишется; не адрес — ошибка."""
        from autoprint.settings_spec import clean
        self.assertEqual(clean("deck_prepare", "lms.example/course\n\n https://meet.example/room \nlms.example/course"),
                         ["https://lms.example/course", "https://meet.example/room"])
        with self.assertRaises(ValueError):
            clean("deck_prepare", "javascript:alert(1)")
        with self.assertRaises(ValueError):
            clean("deck_prepare", "file:///C:/Windows/win.ini")
        r = self.win.commands.call({"cmd": "set", "key": "deck_prepare", "value": "a.example\nb.example"})
        self.assertEqual(r["result"]["value"], ["https://a.example", "https://b.example"])
        self.assertEqual(self.win.settings.deck_prepare, ["https://a.example", "https://b.example"])

    def test_key_saved_with_settings(self):
        from autoprint.storage import Settings
        s = Settings(deck_on=True, deck_key="abc")
        s.save()                                  # папка данных тестов (quiet), не настоящая
        s2 = Settings.load()
        self.assertTrue(s2.deck_on)
        self.assertEqual(s2.deck_key, "abc")


if __name__ == "__main__":
    unittest.main(verbosity=2)
