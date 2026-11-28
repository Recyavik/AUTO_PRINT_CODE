"""1.3.1 — пульт в Macro Deck после первого урока с ним:
 * вид кнопок меняется на телефоне сразу: веб-интерфейс Macro Deck 3.0.5 не обновляет картинку у существующей кнопки
   (подпись — обновляет), поэтому кнопка, у которой поменялся вид, удаляется и создаётся заново на той же клетке;
 * Таймер, Задание, Перерыв и Зарядка открывают свой экран: минуты (или видео), «Убрать», «Назад»; после выбора —
   назад на главный экран.
Без окон на экране; настоящий Macro Deck не трогается.

    python tests/test_v131.py
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import quiet  # noqa: E402,F401  — до PySide6: offscreen, своя папка данных

from test_v121 import close, videos, window  # noqa: E402
import test_v13  # noqa: E402
from test_v13 import FakeAudio, FakeMD, deck_lesson, wait  # noqa: E402

BASE = "http://127.0.0.1:8791/api/?key=K"
API = "http://127.0.0.1:8791/api/"
FOLDERS = {"main": "F", "timer": "FT", "task": "FK", "break": "FB", "ex": "FE"}


def blocks(data: dict) -> list[dict]:
    return [b for f in data.get("flows") or [] for b in f["children"]]


def urls(data: dict) -> list[str]:
    return [p["value"] for b in blocks(data) for p in b["parameters"] if p["name"] == "url"]


def navs(data: dict) -> list[str]:
    return [p["value"] for b in blocks(data) if b["actionId"] == "change-folder" for p in b["parameters"]
            if p["name"] == "folderId"]


class LiveMD(FakeMD):
    """Подставной Macro Deck, который помнит кнопки, как настоящий: новые id при каждом создании, удалить
    несуществующую — ошибка, занятая клетка — ошибка, больше 100 изменений за раз — ошибка (как 3.0.5)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.n = 0

    def apply(self, changes, dry=False):
        from autoprint.macrodeck import MacroDeckError
        self._check()
        if not 1 <= len(changes) <= 100:
            raise MacroDeckError("An error occurred invoking 'apply_changes': INVALID_ARGUMENT: changes must hold "
                                 "1 to 100 entries.")
        have = {w["id"] for w in self.widgets}
        for c in changes:
            if c["op"] == "delete" and c["entity"] == "widget" and c["id"] not in have:
                raise MacroDeckError("Macro Deck не принял страницу: widget not found")
        r = super().apply(changes, dry)
        ids = {}
        for c in changes:
            if c["op"] == "create" and c["entity"] == "widget":
                self.n += 1
                wid = f"w{self.n}"
                if c.get("ref"):
                    ids[c["ref"]] = wid
                self.widgets.append(dict(c["data"], id=wid))
            if c["op"] == "create" and c["entity"] == "folder":
                self.n += 1
                fid = f"f{self.n}"
                ids[c["ref"]] = fid
                self.folders.append(dict(c["data"], id=fid))
        r["createdIds"] = {**r.get("createdIds", {}), **ids}
        return r


class PhonePageTest(unittest.TestCase):
    """Страницы пульта: главная и четыре экрана выбора."""

    def test_sub_screens_fit_and_navigate(self):
        from autoprint import macrodeck as md
        w = md.layout(BASE, {}, folders=FOLDERS)
        by_folder: dict[str, list] = {}
        for x in w:
            by_folder.setdefault(x["folder"], []).append(x)
        self.assertEqual(set(by_folder), {"main", "timer", "task", "break", "ex"})
        for f, items in by_folder.items():
            cells = set()
            for x in items:
                for dx in range(x["width"]):
                    cell = (x["positionX"] + dx, x["positionY"])
                    self.assertNotIn(cell, cells, (f, x["data"][md.MARK]))    # кнопки не налезают друг на друга
                    self.assertLess(cell[0], md.COLS)
                    self.assertLess(cell[1], md.ROWS)
                    cells.add(cell)
        pg = {x["data"][md.MARK]: x["data"] for x in w}
        self.assertEqual(set(pg), set(md.ALL_KEYS))
        for key, sub in (("timer", "FT"), ("task", "FK"), ("break", "FB"), ("ex", "FE")):
            self.assertEqual(navs(pg[key]), [sub], key)                       # открывает свой экран
            self.assertEqual(urls(pg[key]), [], key)                          # и ничего не включает сам
        self.assertEqual(urls(pg["black"]), [API + "black?key=K"])             # остальные — команды, как были
        for sub in ("timer", "task", "break", "ex"):
            self.assertEqual(navs(pg[f"{sub}.back"]), ["F"])
            self.assertEqual(urls(pg[f"{sub}.back"]), [])
        # минуты — команда с минутами, потом назад (сначала команда: Macro Deck ждёт её ответа)
        self.assertEqual(urls(pg["timer.m5"]), [API + "timer?key=K&min=5"])
        self.assertEqual([b["actionId"] for b in blocks(pg["timer.m5"])], ["send-request", "change-folder"])
        self.assertEqual(navs(pg["timer.m5"]), ["F"])
        self.assertEqual(urls(pg["task.m10"]), [API + "task?key=K&min=10"])
        self.assertEqual(urls(pg["task.own"]), [API + "task?key=K&min=0"])
        self.assertEqual(urls(pg["break.m15"]), [API + "break?key=K&min=15"])
        self.assertEqual(urls(pg["break.plan"]), [API + "break?key=K&plan=1"])
        self.assertEqual(urls(pg["timer.stop"]), [API + "stop?key=K&what=timer"])
        self.assertEqual(urls(pg["break.stop"]), [API + "stop?key=K&what=break"])
        self.assertEqual(urls(pg["ex.stop"]), [API + "stop?key=K&what=exercise"])
        self.assertEqual(navs(pg["timer.stop"]), ["F"])
        # прибавить и пауза — остаться на экране: нажимают несколько раз
        self.assertEqual(urls(pg["timer.plus"]), [API + "timer_add?key=K&min=1"])
        self.assertEqual(urls(pg["timer.minus"]), [API + "timer_add?key=K&min=-1"])
        self.assertEqual(navs(pg["timer.plus"]), [])
        self.assertEqual(urls(pg["break.minus5"]), [API + "break_add?key=K&min=-5"])
        self.assertEqual(urls(pg["break.pause"]), [API + "break_pause?key=K"])
        self.assertEqual(navs(pg["break.pause"]), [])
        self.assertEqual(urls(pg["ex.next"]), [API + "exercise?key=K&pick=next"])
        self.assertEqual(urls(pg["ex.random"]), [API + "exercise?key=K&pick=random"])
        self.assertEqual(urls(pg["ex.pause"]), [API + "ex_pause?key=K"])
        self.assertEqual(urls(pg["ex.restart"]), [API + "ex_restart?key=K"])

    def test_without_folders_main_buttons_still_command(self):
        """Экраны ещё не созданы (страница прежней версии) — главные кнопки работают командой, как раньше."""
        from autoprint import macrodeck as md
        pg = md.page({}, "glass", BASE)
        self.assertEqual(urls(pg["timer"]), [API + "timer?key=K"])
        self.assertEqual(navs(pg["timer"]), [])

    def test_countdown_in_screen_title(self):
        from autoprint import macrodeck as md
        st = {"screen": "timer", "timer": True, "timer_left": "02:41"}
        pg = md.page(st, "glass", BASE, FOLDERS)
        self.assertEqual(pg["timer.title"]["label"], "{{ vars.apc_timer_left }}")
        self.assertEqual(pg["timer.title"]["textAlign"], "right")             # справа от названия, не поверх
        self.assertEqual(md.page({}, "glass", BASE, FOLDERS)["timer.title"]["label"], "")
        st = {"screen": "break", "break": True, "break_left": "08:12"}
        self.assertEqual(md.page(st, "glass", BASE, FOLDERS)["break.title"]["label"], "{{ vars.apc_break_left }}")

    def test_exercise_screen_lists_videos(self):
        from autoprint import deckart as a
        from autoprint import macrodeck as md
        st = {"screen": "exercise", "exercises": ["Глаза 1", "Гимнастика для глаз и шеи"], "ex_index": 1}
        img = md.images(st, "glass")
        pg = md.page(st, "glass", BASE, FOLDERS)
        self.assertIn("Глаза 1", img["ex.v0"])
        self.assertIn("Гимнастика", img["ex.v1"])
        self.assertIn(a.GLASS_ON, img["ex.v1"])                               # идущее видео — подсвечено
        self.assertNotIn(a.GLASS_ON, img["ex.v0"])
        self.assertEqual(urls(pg["ex.v1"]), [API + "exercise?key=K&index=1"])
        self.assertEqual(navs(pg["ex.v1"]), ["F"])
        self.assertEqual(img["ex.v5"], "")                                    # видео нет — пустая клетка
        self.assertNotIn("imageUrl", pg["ex.v5"])
        self.assertEqual(blocks(pg["ex.v5"]), [])
        none = md.images({"screen": "idle", "exercises": []}, "glass")
        self.assertIn(a.GLASS_OFF_FG, none["ex.next"])                         # зарядок в оформлении нет — погашено

    def test_controls_dim_when_nothing_running(self):
        from autoprint import deckart as a
        from autoprint import macrodeck as md
        idle = md.images({"screen": "idle", "has_task": True, "exercises": ["Глаза"]}, "glass")
        for k in ("timer.stop", "timer.plus", "timer.minus", "task.stop", "break.stop", "break.pause",
                  "break.plus5", "ex.stop", "ex.pause", "ex.restart"):
            self.assertIn(a.GLASS_OFF_FG, idle[k], k)
        for k in ("timer.m5", "task.m5", "break.m10", "break.plan", "ex.next", "ex.v0"):
            self.assertNotIn(a.GLASS_OFF_FG, idle[k], k)
        run = md.images({"screen": "timer", "timer": True, "timer_left": "03:00"}, "glass")
        self.assertNotIn(a.GLASS_OFF_FG, run["timer.stop"])
        self.assertIn(a.GLASS_ON, run["timer.title"])                         # идёт — заголовок синий
        paused = md.images({"screen": "break", "break": True, "break_left": "05:00", "break_paused": True}, "glass")
        self.assertIn("Продолжить", paused["break.pause"])
        notask = md.images({"screen": "idle", "has_task": False}, "glass")
        self.assertIn(a.GLASS_OFF_FG, notask["task.m5"])                      # заданий нет — минуты погашены
        self.assertIn("нет заданий", notask["task.title"])

    def test_minute_tiles(self):
        from autoprint import macrodeck as md
        img = md.images({"has_task": True, "task_min": 5, "break_plan_min": 7}, "glass")
        self.assertIn(">5<", img["timer.m5"])
        self.assertIn("мин", img["timer.m5"])
        self.assertIn("7 мин", img["break.plan"])                              # «По плану» — сколько это
        self.assertIn("5 мин", img["task.own"])                                # «Как в задании» — сколько это
        self.assertIn("+1", img["timer.plus"])
        self.assertIn("−5", img["break.minus5"])

    def test_every_style_draws_every_button(self):
        from autoprint import macrodeck as md
        st = {"screen": "break", "break_left": "03:00", "exercises": ["Глаза"], "has_task": True}
        for style in md.STYLES:
            imgs = md.images(st, style)
            self.assertEqual(set(imgs), set(md.ALL_KEYS), style)
            for k, svg in imgs.items():
                if k.startswith("ex.v") and k != "ex.v0":
                    continue
                self.assertTrue(svg.startswith("<svg"), (style, k))
                self.assertNotIn("<filter", svg, (style, k))
        off = md.images({"off": True, "now": "Пульт выключен"}, "glass")         # пульт выключили — всё погашено
        self.assertEqual(set(off), set(md.ALL_KEYS))

    def test_every_template_variable_is_declared(self):
        from autoprint import macrodeck as md
        for st in ({"screen": "timer", "timer_left": "01:00", "left": "05:00", "phase": "live"},
                   {"screen": "break", "break_left": "01:00"}):
            used = set(re.findall(r"vars\.(apc_\w+)", json.dumps(md.layout(BASE, st, folders=FOLDERS))))
            declared = {n for n, _, _ in md.variables()}
            self.assertEqual(used - declared, set())

    def test_layout_version_bumped(self):
        """Страница с экранами выбора — новая раскладка: после обновления программа пересоберёт её сама."""
        from autoprint import macrodeck as md
        self.assertGreaterEqual(md.LAYOUT, 5)


class RecreateSyncTest(unittest.TestCase):
    """Вид кнопки поменялся — кнопка удаляется и создаётся заново на своей клетке (так телефон её перерисует)."""

    def test_changed_button_recreated_in_its_cell(self):
        from autoprint import deckart as a
        from autoprint import macrodeck as md
        from test_v13 import svg_of
        fake = LiveMD()
        sync = md.Sync(fake, {}, FOLDERS)
        try:
            st = {"screen": "idle"}
            sync.push(md.values(st), md.page(st, "glass", BASE, FOLDERS))
            self.assertTrue(wait(lambda: len(fake.applied) == 1))
            first = fake.applied[0]
            self.assertEqual(sum(c["op"] == "create" for c in first), len(md.ALL_KEYS))   # первый раз — все
            ids = {w["data"][md.MARK]: w["id"] for w in fake.widgets}
            st = {"screen": "black"}
            sync.push(md.values(st), md.page(st, "glass", BASE, FOLDERS))
            self.assertTrue(wait(lambda: len(fake.applied) == 2))
            ch = fake.applied[1]
            self.assertEqual({c["id"] for c in ch if c["op"] == "delete"}, {ids["bg"], ids["black"]})
            made = {c["data"]["data"][md.MARK]: c["data"] for c in ch if c["op"] == "create"}
            self.assertEqual(set(made), {"bg", "black"})
            self.assertEqual((made["black"]["folderId"], made["black"]["positionX"], made["black"]["positionY"],
                              made["black"]["width"]), ("F", 1, 1, 1))
            self.assertIn(a.GLASS_ON, svg_of(made["black"]["data"]["imageUrl"]))
            self.assertIn("api/black?key=K", json.dumps(made["black"]["data"]["flows"]))   # команда не потерялась
            # ещё раз — удаляется уже новая кнопка, а не прежняя
            new_black = next(w["id"] for w in fake.widgets if w["data"][md.MARK] == "black")
            st = {"screen": "idle"}
            sync.push(md.values(st), md.page(st, "glass", BASE, FOLDERS))
            self.assertTrue(wait(lambda: len(fake.applied) == 3))
            self.assertIn(new_black, {c["id"] for c in fake.applied[2] if c["op"] == "delete"})
            self.assertEqual(sync.error, "")
            self.assertEqual(len(fake.widgets), len(md.ALL_KEYS))              # ни одной лишней кнопки
        finally:
            sync.stop()

    def test_sub_screen_button_in_its_folder(self):
        from autoprint import macrodeck as md
        fake = LiveMD()
        sync = md.Sync(fake, {}, FOLDERS)
        try:
            sync.push({}, md.page({"screen": "idle"}, "glass", BASE, FOLDERS))
            self.assertTrue(wait(lambda: len(fake.applied) == 1))
            st = {"screen": "timer", "timer": True, "timer_left": "04:59"}
            sync.push(md.values(st), md.page(st, "glass", BASE, FOLDERS))
            self.assertTrue(wait(lambda: len(fake.applied) == 2))
            made = {c["data"]["data"][md.MARK]: c["data"] for c in fake.applied[1] if c["op"] == "create"}
            self.assertEqual((made["timer.stop"]["folderId"], made["timer.stop"]["positionX"],
                              made["timer.stop"]["positionY"]), ("FT", 6, 0))
            self.assertEqual(made["timer.title"]["width"], 5)
        finally:
            sync.stop()

    def test_buttons_found_by_mark_on_start(self):
        """Программу перезапустили: id кнопок берутся у Macro Deck по пометке, во всех папках пульта."""
        from autoprint import macrodeck as md
        fake = LiveMD(widgets=[
            {"id": "real-black", "folderId": "F", "positionX": 1, "positionY": 1, "width": 1, "data": {md.MARK: "black"}},
            {"id": "real-m5", "folderId": "FT", "positionX": 3, "positionY": 1, "width": 1,
             "data": {md.MARK: "timer.m5"}},
            {"id": "owner", "folderId": "F", "positionX": 6, "positionY": 2, "width": 1, "data": {"label": "Свет"}}])
        sync = md.Sync(fake, {"black": "stale-id"}, FOLDERS)
        try:
            sync.push({}, md.page({"screen": "idle"}, "glass", BASE, FOLDERS))
            self.assertTrue(wait(lambda: len(fake.applied) == 1))
            gone = {c["id"] for c in fake.applied[0] if c["op"] == "delete"}
            self.assertEqual(gone, {"real-black", "real-m5"})
            self.assertIn("owner", {w["id"] for w in fake.widgets})
            self.assertEqual(sync.error, "")
        finally:
            sync.stop()

    def test_all_buttons_recreated_in_parts(self):
        """Запуск программы при собранной странице: все 81 кнопка — удалить и создать (162 изменения), а Macro Deck
        берёт не больше 100 за раз — частями; каждая кнопка в итоге одна."""
        from autoprint import macrodeck as md
        fake = LiveMD()
        md.setup(fake, BASE)
        folders = {"main": "home-1", **{k: v for k, v in md.setup(fake, BASE, "prof-1")["folders"].items()
                                        if k != "main"}}
        sync = md.Sync(fake, {}, folders)
        try:
            n = len(fake.applied)
            sync.push({}, md.page({"screen": "black"}, "glass", BASE, folders))
            self.assertTrue(wait(lambda: sync.error == "" and sum(len(b) for b in fake.applied[n:]) >= 162))
            self.assertTrue(all(len(b) <= 100 for b in fake.applied))
            marks = [w["data"][md.MARK] for w in fake.widgets]
            self.assertEqual(sorted(marks), sorted(md.ALL_KEYS))
        finally:
            sync.stop()

    def test_button_deleted_in_macro_deck_comes_back(self):
        """Кнопку удалили в Macro Deck руками — ошибка, затем кнопка находится заново (её нет) и создаётся."""
        from autoprint import macrodeck as md
        fake = LiveMD()
        sync = md.Sync(fake, {}, FOLDERS)
        sync.RETRY_S = 0.2
        try:
            sync.push({}, md.page({"screen": "idle"}, "glass", BASE, FOLDERS))
            self.assertTrue(wait(lambda: len(fake.applied) == 1))
            fake.widgets = [w for w in fake.widgets if w["data"][md.MARK] != "black"]
            st = {"screen": "black"}
            sync.push({}, md.page(st, "glass", BASE, FOLDERS))
            self.assertTrue(wait(lambda: bool(sync.error)))
            sync.push({}, md.page(st, "glass", BASE, FOLDERS))
            self.assertTrue(wait(lambda: sync.error == "" and len(fake.applied) >= 2, 5))
            marks = [w["data"][md.MARK] for w in fake.widgets]
            self.assertEqual(marks.count("black"), 1)
            self.assertEqual(len(marks), len(md.ALL_KEYS))
        finally:
            sync.stop()


class SetupTest(unittest.TestCase):
    def test_setup_makes_sub_screens(self):
        """Новая страница: кроме главной — четыре экрана выбора отдельными страницами профиля."""
        from autoprint import macrodeck as md
        fake = LiveMD()
        r = md.setup(fake, BASE)
        self.assertEqual(set(r["folders"]), {"main", "timer", "task", "break", "ex"})
        names = {f["name"] for f in fake.folders}
        self.assertTrue({"Таймер", "Задание", "Перерыв", "Зарядка"} <= names)
        self.assertIn({"op": "update", "entity": "folder", "id": "home-1", "data": {"name": "Урок"}},
                      [c for b in fake.applied for c in b])
        self.assertEqual(set(r["widgets"]), set(md.ALL_KEYS))
        by_mark = {w["data"][md.MARK]: w for w in fake.widgets}
        self.assertEqual(by_mark["timer.m5"]["folderId"], r["folders"]["timer"])
        self.assertEqual(by_mark["black"]["folderId"], r["folders"]["main"])
        self.assertEqual(navs(by_mark["timer"]["data"]), [r["folders"]["timer"]])
        self.assertEqual(navs(by_mark["timer.back"]["data"]), [r["folders"]["main"]])
        shown = [a[1]["actionId"] for a in fake.actions]
        self.assertEqual(shown, ["change-profile", "change-folder"])            # телефоны — на главную

    def test_setup_again_reuses_screens(self):
        """Повторно: экраны те же (не плодятся), свои кнопки на них — заново, кнопки человека — как есть."""
        from autoprint import macrodeck as md
        fake = LiveMD()
        r1 = md.setup(fake, BASE)
        fake.widgets.append({"id": "owner", "folderId": r1["folders"]["break"], "positionX": 6, "positionY": 2,
                             "width": 1, "data": {"label": "Свет"}})
        n_folders = len(fake.folders)
        r2 = md.setup(fake, BASE, r1["profile"])
        self.assertEqual(len(fake.folders), n_folders)
        self.assertEqual(r2["folders"], r1["folders"])
        self.assertIn("owner", {w["id"] for w in fake.widgets})
        marks = [w["data"].get(md.MARK) for w in fake.widgets if w["id"] != "owner"]
        self.assertEqual(sorted(marks), sorted(md.ALL_KEYS))                 # ни одной лишней


class SubScreenCommandsTest(unittest.TestCase):
    """Команды экранов выбора: минуты включают сразу (и заново, если уже идёт), «Убрать» — только своё."""
    port = 18960
    setUp = test_v13.DeckTest.setUp
    tearDown = test_v13.DeckTest.tearDown
    api = test_v13.DeckTest.api
    ok = test_v13.DeckTest.ok
    start_at = test_v13.DeckTest.start_at

    def test_timer_minutes_start_and_restart(self):
        d, ef = self.win.deck, self.win.efir
        d.run("timer", {"min": "5"})
        self.assertEqual((ef.mode, ef.tmr_total), ("timer", 300))
        d.run("timer", {"min": "10"})                                  # идёт — новые минуты, а не «убрать»
        self.assertEqual((ef.mode, ef.tmr_total), ("timer", 600))
        d.run("timer")                                                  # без минут — как раньше: убрать
        self.assertEqual(ef.mode, "idle")

    def test_task_minutes(self):
        d, ef = self.win.deck, self.win.efir
        d.run("task", {"min": "3"})
        self.assertEqual((ef.mode, ef.tmr_total), ("task", 180))
        d.run("task", {"min": "7"})
        self.assertEqual((ef.mode, ef.tmr_total), ("task", 420))
        d.run("task", {"min": "0"})                                     # «Как в задании» — его 5 минут
        self.assertEqual((ef.mode, ef.tmr_total), ("task", 300))

    def test_stop_removes_only_its_own(self):
        d, ef = self.win.deck, self.win.efir
        d.run("slide")
        self.assertEqual(ef.mode, "slide")
        d.run("stop", {"what": "timer"})                                # таймера нет — слайд остаётся
        self.assertEqual(ef.mode, "slide")
        d.run("timer", {"min": "2"})
        d.run("stop", {"what": "break"})
        self.assertEqual(ef.mode, "timer")
        d.run("stop", {"what": "timer"})
        self.assertEqual(ef.mode, "idle")
        d.run("task", {"min": "3"})
        d.run("stop", {"what": "timer"})                                # задание с отсчётом — тоже «таймер»
        self.assertEqual(ef.mode, "idle")
        d.run("exercise", {"pick": "next"})
        self.assertEqual(ef.mode, "exercise")
        d.run("stop", {"what": "exercise"})
        self.assertEqual(ef.mode, "idle")

    def test_break_minutes_plan_and_pause(self):
        d, ef = self.win.deck, self.win.efir
        self.start_at(1)
        d.run("break", {"min": "15"})
        self.assertEqual((ef.mode, ef.brk_total), ("break", 900))
        d.run("break", {"min": "5"})                                    # идёт — заново на новые минуты
        self.assertEqual(ef.brk_total, 300)
        d.run("break", {"plan": "1"})                                   # «По плану» — этап-перерыв, 7 минут
        self.assertEqual(ef.brk_total, 420)
        st = d.run("break_pause")
        self.assertIsNotNone(ef.brk_left_paused)
        self.assertTrue(st["break_paused"])
        d.run("break_pause")                                            # ещё раз — дальше
        self.assertIsNone(ef.brk_left_paused)
        d.run("stop", {"what": "break"})
        self.assertEqual(ef.mode, "idle")

    def test_exercise_by_video_and_in_turn(self):
        d, ef = self.win.deck, self.win.efir
        self.start_at(0)                                                # идёт этап-зарядка со своим видео
        self.win.store.get("D").find_block("d1").exercise = "Глаза 1"
        d.run("exercise", {"index": "1"})                               # выбрано на телефоне — оно, не этапа
        self.assertEqual((ef.mode, ef.ex_index), ("exercise", 1))
        st = d.run("ex_pause")
        self.assertTrue(ef.ex_paused)
        self.assertTrue(st["exercise_paused"])
        d.run("ex_pause")
        self.assertFalse(ef.ex_paused)
        n = ef.ex_restart
        d.run("ex_restart")
        self.assertEqual(ef.ex_restart, n + 1)
        ef.ex_started -= 10
        seq = ef.ex_seq
        d.run("exercise", {"pick": "next"})                             # идёт — следующее по очереди, а не пауза
        self.assertEqual(ef.ex_seq, seq + 1)
        self.assertEqual(ef.ex_index, 0)
        self.assertFalse(ef.ex_paused)
        d.run("exercise", {"index": "7"})                               # такого видео нет — ничего не ломается
        self.assertEqual(ef.mode, "exercise")

    def test_pause_commands_do_nothing_when_not_running(self):
        d, ef = self.win.deck, self.win.efir
        for cmd in ("break_pause", "ex_pause", "ex_restart"):
            d.run(cmd)
            self.assertEqual(ef.mode, "idle", cmd)

    def test_state_for_sub_screens(self):
        st = self.win.deck.run("state")
        self.assertEqual(st["exercises"], ["Глаза 1", "Глаза 2"])
        self.assertEqual(st["ex_index"], -1)
        self.assertEqual(st["task_min"], 5)
        self.assertEqual(st["task_title"], "Средний балл")
        self.assertEqual(st["break_plan_min"], 7)
        self.win.deck.run("exercise", {"index": "1"})
        self.assertEqual(self.win.deck.run("state")["ex_index"], 1)

    def test_minutes_over_http(self):
        self.ok("timer", query="min=2")
        self.assertEqual(self.win.efir.tmr_total, 120)
        self.ok("stop", query="what=timer")
        self.assertEqual(self.win.efir.mode, "idle")


class ConnectSubScreensTest(unittest.TestCase):
    """Через программу: страница собрана с экранами, их id запомнены, значения идут во все папки."""
    port = 18962

    def setUp(self):
        from autoprint.audio import Mute
        self.win = window([deck_lesson()], self.port)
        self.win.printer.set_focus("D")
        self.win.deck.audio = Mute(FakeAudio())
        self.fake = LiveMD()
        self.win.deck.md_client = lambda token: self.fake

    def tearDown(self):
        self.win.deck._md_stop_sync()
        close(self.win)

    def test_connect_remembers_screens_and_recreates(self):
        from autoprint import deckart
        from autoprint import macrodeck as md
        from autoprint.macrodeck import Sync
        from test_v13 import svg_of
        Sync.RETRY_S = 0.2
        self.win.commands.call({"cmd": "deck_md_connect", "token": "mdmcp_secret_token"})
        self.assertTrue(wait(lambda: not self.win.deck.md_busy, 20))
        s = self.win.settings
        self.assertEqual(set(s.md_folders), {"timer", "task", "break", "ex"})
        self.assertEqual(s.md_layout, md.LAYOUT)
        self.assertTrue(wait(lambda: self.win.deck.md_sync is not None, 5))
        n = len(self.fake.applied)
        self.win.lesson.command({"cmd": "black"})

        def recreated(key, pred):
            return any(c["op"] == "create" and c["entity"] == "widget" and c["data"]["data"].get(md.MARK) == key
                       and pred(c["data"]) for batch in self.fake.applied[n:] for c in batch)
        self.assertTrue(wait(lambda: recreated("black", lambda d: deckart.GLASS_ON in svg_of(d["data"]["imageUrl"]))))
        self.assertTrue(recreated("black", lambda d: d["folderId"] == s.md_folder))
        marks = [w["data"].get(md.MARK) for w in self.fake.widgets]
        self.assertEqual(sorted(marks), sorted(md.ALL_KEYS))                 # пересоздание не плодит кнопки


if __name__ == "__main__":
    unittest.main(verbosity=2)
