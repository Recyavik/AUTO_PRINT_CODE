"""0.12 — план урока и уроки по нему, урок через нейросеть с картинками и зарядкой, «Закрепить сбоку»,
понятное время. Всё без окон на экране.

    python tests/test_v12.py
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import quiet  # noqa: E402,F401  — до PySide6: offscreen, своя папка данных

from test_v10 import TMP, code, make_window, note, pump, stage  # noqa: E402,F401  (там же QApplication и тема)

from autoprint import plans, storage  # noqa: E402
from autoprint.storage import BLOCK_CODE, BLOCK_IMAGE, BLOCK_MARKDOWN, BLOCK_STAGE, Block, Template  # noqa: E402,F401


def plan90() -> Template:
    return Template("Онлайн 90", [stage("Приветствие", 5, id="p1"), stage("Теория", 20, id="p2"),
                                  stage("Перерыв", 10, id="p3", stage_kind="break"), stage("Практика", 30, id="p4")],
                    id="P", kind="plan")


def close(win) -> None:
    win._quitting = True
    win.close()
    pump()


def wait(pred, timeout: float = 5) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        pump(20)
        if pred():
            return True
    return False


def stages_of(t: Template) -> list[Block]:
    return [b for b in t.blocks if b.type == BLOCK_STAGE]


# ================================================================ Task 1: модель и синхронизация плана

class PlansTest(unittest.TestCase):
    def test_new_topic_copies_stages_and_drafts(self):
        p = plan90()
        p.blocks.insert(1, note("Проверить звук", role="do", id="d1"))
        t = plans.new_topic(p, "Функции")
        st = stages_of(t)
        self.assertEqual([(b.title, b.minutes, b.link) for b in st],
                         [("Приветствие", 5, "p1"), ("Теория", 20, "p2"), ("Перерыв", 10, "p3"), ("Практика", 30, "p4")])
        self.assertEqual((t.plan_id, t.kind, t.title), ("P", "", "Функции"))
        self.assertEqual(t.blocks[0].role, "goal")                                   # перед уроком — цель
        do = [b for b in t.blocks if b.type == BLOCK_MARKDOWN and b.role == "do"]
        self.assertEqual(do[0].text, "Проверить звук")
        self.assertNotEqual(do[0].id, "d1")                                          # копия, свои id
        self.assertEqual({b.id for b in st} & {b.id for b in p.blocks}, set())
        after_break = t.blocks[t.blocks.index(st[2]) + 1]
        self.assertEqual(after_break.type, BLOCK_STAGE)                              # под перерывом — ничего
        after_theory = t.blocks[t.blocks.index(st[1]) + 1]
        self.assertEqual((after_theory.type, after_theory.role, after_theory.text), (BLOCK_MARKDOWN, "say", ""))

    def test_sync_minutes_rename_order_add(self):
        p = plan90()
        t = plans.new_topic(p, "Функции")
        p.find_block("p2").minutes = 25
        p.find_block("p2").title = "Новая тема"
        p.blocks.insert(1, stage("Разминка", 5, id="p5"))
        self.assertTrue(plans.sync_topic(t, p))
        self.assertEqual([(b.title, b.minutes) for b in stages_of(t)],
                         [("Приветствие", 5), ("Разминка", 5), ("Новая тема", 25), ("Перерыв", 10), ("Практика", 30)])
        self.assertFalse(plans.sync_topic(t, p))                                     # второй раз — без изменений
        p.blocks.insert(0, p.blocks.pop(p.blocks.index(p.find_block("p4"))))          # «Практика» — первой
        plans.sync_topic(t, p)
        self.assertEqual(stages_of(t)[0].link, "p4")

    def test_removed_stage_keeps_notes(self):
        p = plan90()
        t = plans.new_topic(p, "Функции")
        s2 = next(b for b in t.blocks if b.link == "p2")
        t.blocks.insert(t.blocks.index(s2) + 1, note("Функция — блок кода", id="mine"))
        p.blocks.remove(p.find_block("p2"))
        plans.sync_topic(t, p)
        ids = [b.id for b in t.blocks]
        self.assertIn("mine", ids)
        marker = next(b for b in t.blocks if b.type == BLOCK_MARKDOWN and "больше нет в плане" in b.text)
        self.assertEqual(marker.text, "Из этапа «Теория», которого больше нет в плане")
        self.assertEqual((marker.role, marker.link), ("text", "p2"))
        self.assertLess(ids.index(marker.id), ids.index("mine"))
        owner = [b for b in t.blocks[:ids.index("mine")] if b.type == BLOCK_STAGE][-1]
        self.assertEqual(owner.link, "p1")                                           # ушли в предыдущий этап
        self.assertEqual([b.link for b in stages_of(t)], ["p1", "p3", "p4"])

    def test_restored_stage_takes_notes_back(self):        # «Вернуть» на странице плана — тот же id
        p = plan90()
        t = plans.new_topic(p, "Функции")
        s2 = next(b for b in t.blocks if b.link == "p2")
        t.blocks.insert(t.blocks.index(s2) + 1, note("Функция — блок кода", id="mine"))
        removed = p.find_block("p2")
        i = p.blocks.index(removed)
        p.blocks.remove(removed)
        plans.sync_topic(t, p)
        p.blocks.insert(i, removed)
        plans.sync_topic(t, p)
        owner = [b for b in t.blocks[:[b.id for b in t.blocks].index("mine")] if b.type == BLOCK_STAGE][-1]
        self.assertEqual(owner.link, "p2")
        self.assertFalse(any("больше нет в плане" in b.text for b in t.blocks))       # разделитель убран

    def test_drafts_and_look_from_plan(self):
        p = plan90()
        p.look = "L1"
        p.blocks.insert(0, note("Цель плана", role="goal", id="g"))
        p.blocks.insert(p.blocks.index(p.find_block("p4")) + 1, code("print(1)", id="c"))
        t = plans.new_topic(p, "Функции")
        self.assertEqual((t.look, t.blocks[0].text), ("L1", "Цель плана"))
        self.assertEqual(sum(1 for b in t.blocks if b.role == "goal" and b.type == BLOCK_MARKDOWN), 1)
        self.assertTrue(any(b.type == BLOCK_CODE and b.text == "print(1)" and b.id != "c" for b in t.blocks))
        p.look = "L2"
        plans.sync_topic(t, p)
        self.assertEqual(t.look, "L2")

    def test_link_topic_by_title_then_order(self):
        p = plan90()
        t = Template("Ответ", [note("Цель", role="goal"), stage("приветствие ", 3), note("Здравствуйте", id="a"),
                               stage("Объяснение", 15), note("Теория тут", id="b"), stage("Отдых", 5, stage_kind="break"),
                               stage("Разбор", 20), note("Практика тут", id="d"), stage("Лишний", 5),
                               note("Сверху", id="c")])
        notes = plans.link_topic(t, p)
        self.assertEqual([(b.title, b.minutes, b.link) for b in stages_of(t)],
                         [("Приветствие", 5, "p1"), ("Теория", 20, "p2"), ("Перерыв", 10, "p3"), ("Практика", 30, "p4")])
        self.assertTrue({"a", "b", "c", "d"} <= {b.id for b in t.blocks})
        self.assertEqual(t.plan_id, "P")
        owner = [b for b in t.blocks[:[b.id for b in t.blocks].index("c")] if b.type == BLOCK_STAGE][-1]
        self.assertEqual(owner.link, "p4")                                          # заметки «Лишнего» — в «Практику»
        self.assertEqual(notes, ["Этап «Лишний» не нашёлся в плане — его заметки перенесены в «Практика»"])

    def test_link_topic_empty_plan_stages_reported(self):
        p = plan90()
        t = Template("Ответ", [stage("Приветствие", 5), note("Здравствуйте")])
        notes = plans.link_topic(t, p)
        self.assertEqual(notes, ["Этап плана «Теория» в ответе пустой", "Этап плана «Практика» в ответе пустой"])
        self.assertEqual(len(stages_of(t)), 4)                                      # перерыв без заметок — норма

    def test_plan_from_lesson_links_lesson(self):
        t = Template("Функции", [stage("А", 5), note("x"), stage("Б", 10)])
        p = plans.plan_from_lesson(t)
        self.assertEqual((p.kind, p.title), ("plan", "План: Функции"))
        self.assertEqual([b.type for b in p.blocks], [BLOCK_STAGE, BLOCK_STAGE])
        self.assertEqual([(b.title, b.minutes) for b in p.blocks], [("А", 5), ("Б", 10)])
        self.assertEqual(t.plan_id, p.id)
        self.assertEqual([b.link for b in stages_of(t)], [b.id for b in p.blocks])

    def test_unlink(self):
        p = plan90()
        t = plans.new_topic(p)
        plans.unlink(t)
        self.assertEqual(t.plan_id, "")
        self.assertTrue(all(not b.link for b in t.blocks))

    def test_store_dangling_links_dropped(self):
        st = storage.TemplateStore()
        p = plan90()
        t = plans.new_topic(p)
        st.templates = [t]
        st.save()
        st.load()
        t2 = st.templates[0]
        self.assertEqual(t2.plan_id, "")
        self.assertTrue(all(not b.link for b in t2.blocks))
        self.assertEqual(len(stages_of(t2)), 4)                                      # этапы остались

    def test_store_roundtrip_and_queries(self):
        st = storage.TemplateStore()
        p = plan90()
        t = plans.new_topic(p)
        st.templates = [p, t]
        st.save()
        st.load()
        self.assertEqual([x.id for x in st.plans()], ["P"])
        self.assertEqual(st.get("P").kind, "plan")
        self.assertEqual([x.id for x in st.topics_of("P")], [t.id])
        self.assertEqual(stages_of(st.get(t.id))[0].link, "p1")
        q = st.add_plan_from_structure("online90")
        self.assertEqual((q.kind, sum(b.minutes for b in stages_of(q))), ("plan", 90))
        self.assertTrue(q.title.startswith("План: "))
        self.assertEqual([b.type for b in q.blocks], [BLOCK_STAGE] * len(q.blocks))

    def test_import_drops_link_duplicate_keeps(self):
        p = plan90()
        t = plans.new_topic(p, "Функции")
        f = TMP / "topic.json"
        storage.TemplateStore.export_template(t, str(f))
        imp = storage.TemplateStore.read_template_file(str(f))
        self.assertEqual(imp.plan_id, "")
        self.assertTrue(all(not b.link for b in imp.blocks))
        storage.TemplateStore.export_template(p, str(f))
        self.assertEqual(storage.TemplateStore.read_template_file(str(f)).kind, "plan")   # план остаётся планом
        from autoprint.importers import parse_pasted
        pasted, _kind = parse_pasted(f.read_text(encoding="utf-8").replace('"kind": "plan"', '"kind": ""')
                                     .replace('"plan_id": ""', '"plan_id": "P"'))
        self.assertEqual(pasted.plan_id, "")                                         # вставка .json — без связи
        st = storage.TemplateStore()
        st.templates = [p, t]
        c = st.duplicate(t)
        self.assertEqual(c.plan_id, "P")
        self.assertEqual([b.link for b in stages_of(c)], ["p1", "p2", "p3", "p4"])


# ================================================================ Task 2: формат урока

class FormatTest(unittest.TestCase):
    def test_exercise_tail(self):
        from autoprint import lesson_md
        t = lesson_md.parse("## Зарядка · 3 мин · зарядка: Гимнастика для глаз\n\n## Перерыв · 10 мин · перерыв\n\n"
                            "## Разбор (10 мин)\n", None, "x")
        st = stages_of(t)
        self.assertEqual([(b.title, b.minutes, b.stage_kind, b.exercise) for b in st],
                         [("Зарядка", 3, "exercise", "Гимнастика для глаз"), ("Перерыв", 10, "break", ""),
                          ("Разбор", 10, "", "")])
        self.assertEqual(lesson_md.stage_line(st[0]), "## Зарядка · 3 мин · зарядка: Гимнастика для глаз")
        self.assertEqual(lesson_md.stage_line(st[1]), "## Перерыв · 10 мин · перерыв")

    def test_photo_and_slide_placeholders(self):
        from autoprint import lesson_md
        t = lesson_md.parse("## Э · 5 мин\n\n![Кот у ноутбука](фото)\n\n![Слайд 4](slide:4)\n\n![x](?)\n\n"
                            "![Схема](slide:5)\n\n![пусто]()\n", None, "x")
        imgs = [(b.text, b.title, b.slide) for b in t.blocks if b.type == BLOCK_IMAGE]
        self.assertEqual(imgs, [("", "Кот у ноутбука", 0), ("", "", 4), ("", "x", 0), ("", "Схема", 5), ("", "пусто", 0)])

    def test_export_roundtrip_placeholders(self):
        from autoprint import lesson_md
        t = Template("У", [stage("Зарядка", 3, stage_kind="exercise", exercise="Глаза"), Block(BLOCK_IMAGE, "", title="Кот"),
                           Block(BLOCK_IMAGE, "", slide=2)])
        md = lesson_md.to_md(t, "x_files")
        self.assertIn("## Зарядка · 3 мин · зарядка: Глаза", md)
        self.assertIn("![Кот](фото)", md)
        self.assertIn("![Слайд 2](slide:2)", md)
        back = lesson_md.parse(md, None, "x")
        self.assertEqual([(b.text, b.title, b.slide) for b in back.blocks if b.type == BLOCK_IMAGE],
                         [("", "Кот", 0), ("", "", 2)])
        self.assertEqual(stages_of(back)[0].exercise, "Глаза")

    def test_plan_kind_in_md(self):
        from autoprint import lesson_md
        p = Template("Онлайн 90", [stage("А", 5)], kind="plan")
        md = lesson_md.to_md(p, "x_files")
        self.assertIn("kind: plan", md.split("---")[1])
        self.assertEqual(lesson_md.parse(md, None, "x").kind, "plan")
        self.assertEqual(lesson_md.parse("---\ntitle: У\n---\n## А · 5 мин\n", None, "x").kind, "")
        self.assertNotIn("kind:", lesson_md.to_md(Template("У", [stage("А", 5)]), "x_files"))

    def test_chat_answer_keeps_slide_places(self):
        from autoprint import lesson_ai as L
        p = L.parse_lesson("~~~markdown\n## Э · 5 мин\n\n![Слайд 3](slide:3)\n\n![Кот](фото)\n\n> [!say]\n> Т\n~~~",
                           slide=lambda n: None)
        imgs = [(b.text, b.slide, b.title) for b in p.template.blocks if b.type == BLOCK_IMAGE]
        self.assertEqual(imgs, [("", 3, ""), ("", 0, "Кот")])
        self.assertTrue(any("Слайд 3" in w and "подставьте слайды" in w for w in p.warnings), p.warnings)
        filled = L.parse_lesson("~~~markdown\n## Э · 5 мин\n\n![Слайд 3](slide:3)\n~~~", slide=lambda n: "media/s3.png")
        self.assertEqual([(b.text, b.slide) for b in filled.template.blocks if b.type == BLOCK_IMAGE], [("media/s3.png", 3)])


# ================================================================ Task 3: правка этапов — только в плане

def window(templates, port):
    win = make_window(templates, port=port)
    win.lesson.open_page = lambda: None
    return win


class PlanEditTest(unittest.TestCase):
    def test_fixed_stage_ops_refused(self):
        from autoprint import lesson_edit
        p = plan90()
        t = plans.new_topic(p)
        sid = stages_of(t)[0].id
        for op in ({"op": "set", "block": sid, "fields": {"minutes": 7}}, {"op": "delete", "block": sid},
                   {"op": "insert", "after": "", "block": {"id": "zz1", "type": "stage"}},
                   {"op": "restore", "after": "", "block": {"id": "zz2", "type": "stage", "title": "Х"}},
                   {"op": "move_stage", "stage": sid, "after_stage": ""}):
            with self.assertRaisesRegex(ValueError, "Этапы этого урока задаёт план «Онлайн 90» — меняйте их в плане"):
                lesson_edit.apply(t, [op], fixed_stages="Онлайн 90")
        self.assertEqual(stages_of(t)[0].minutes, 5)
        n = next(b.id for b in t.blocks if b.type == BLOCK_MARKDOWN)
        lesson_edit.apply(t, [{"op": "set", "block": n, "fields": {"text": "ок"}}], fixed_stages="Онлайн 90")   # заметки — можно
        self.assertEqual(t.find_block(n).text, "ок")

    def test_last_plan_stage_kept(self):
        from autoprint import lesson_edit
        p = Template("П", [stage("А", 5, id="a"), stage("Б", 5, id="b")], kind="plan")
        lesson_edit.apply(p, [{"op": "delete", "block": "b"}], keep_one_stage=True)
        with self.assertRaisesRegex(ValueError, "В плане должен остаться хотя бы один этап"):
            lesson_edit.apply(p, [{"op": "delete", "block": "a"}], keep_one_stage=True)
        self.assertEqual([b.id for b in p.blocks], ["a"])

    def test_page_edit_of_plan_syncs_topics(self):
        p = plan90()
        t = plans.new_topic(p, "Функции")
        win = window([p, t], 18901)
        try:
            p, t = win.store.get("P"), win.store.get(t.id)
            res = win.lesson.apply_edit({"lesson": "P", "ops": [{"op": "set", "block": "p2", "fields": {"minutes": 25}}]})
            self.assertTrue(res["ok"])
            self.assertEqual(next(b.minutes for b in t.blocks if b.link == "p2"), 25)
            with self.assertRaisesRegex(ValueError, "задаёт план"):
                win.lesson.apply_edit({"lesson": t.id, "ops": [{"op": "set", "fields": {"minutes": 3},
                                                                  "block": next(b.id for b in t.blocks if b.link == "p2")}]})
            code_, body = win.lesson._edit_from_server({"lesson": t.id, "ops": [
                {"op": "delete", "block": next(b.id for b in t.blocks if b.link == "p2")}]})
            self.assertEqual(code_, 400)
            self.assertIn("задаёт план «Онлайн 90»", body["error"])
            with self.assertRaisesRegex(ValueError, "хотя бы один этап"):
                win.lesson.apply_edit({"lesson": "P", "ops": [{"op": "delete", "block": x}
                                                              for x in ("p1", "p2", "p3", "p4")]})
        finally:
            close(win)

    def test_live_topic_keeps_current_stage_clock(self):   # Review Focus 1
        from datetime import timedelta
        p = plan90()
        t = plans.new_topic(p, "Функции")
        win = window([p, t], 18902)
        try:
            t = win.store.get(t.id)
            win.printer.set_focus(t.id)
            win.efir.launch_lesson(t, start="")
            live = win.efir.store.live
            win.efir.store.set_live(live.webinar_id, live.anchor - timedelta(minutes=12))   # идёт «Теория» (5..25)
            win.lesson.publish()
            before = win.efir.store.live.anchor
            win.lesson.apply_edit({"lesson": "P", "ops": [{"op": "set", "block": "p1", "fields": {"minutes": 8}}]})
            pump(400)
            win.lesson.publish()
            self.assertEqual(win.efir.store.live.anchor, before - timedelta(minutes=3))   # «Теория» — на тех же часах
            self.assertEqual([a.min for a in win.efir.live_webinar().schedule][:2], [8, 20])
        finally:
            win.efir.stop_live()
            close(win)

    def test_delete_plan_unlinks_topics(self):
        p = plan90()
        t = plans.new_topic(p, "Функции")
        win = window([p, t], 18903)
        try:
            p, t = win.store.get("P"), win.store.get(t.id)
            self.assertTrue(win.delete_lesson(p, ask=False))
            self.assertEqual(t.plan_id, "")
            self.assertIn(t, win.store.templates)
            self.assertEqual(len(stages_of(t)), 4)
        finally:
            close(win)

    def test_main_window_plan_actions(self):
        win = window([Template("Функции", [stage("А", 5), note("x")], id="F")], 18904)
        try:
            f = win.store.get("F")
            p = win.make_plan(f)
            self.assertEqual((f.plan_id, p.kind), (p.id, "plan"))
            self.assertIn(p, win.store.templates)
            topic = win.new_topic(p.id)
            self.assertEqual(topic.plan_id, p.id)
            self.assertIn(topic, win.store.templates)
            win.unlink_plan(topic)
            self.assertEqual(topic.plan_id, "")
            notes = win.link_plan(topic, p.id)
            self.assertEqual(topic.plan_id, p.id)
            self.assertIsInstance(notes, list)
            q = win.new_plan("school45")
            self.assertEqual((q.kind, len(stages_of(q))), ("plan", 7))
            c = win.store.duplicate(f)
            self.assertEqual(c.plan_id, p.id)                                       # копия урока — с тем же планом
            cp = win.store.duplicate(p)
            self.assertEqual(win.store.topics_of(cp.id), [])
            self.assertIsNone(win.make_plan(win.store.get(topic.id)))                # уже по плану — нового не делаем
        finally:
            close(win)


# ================================================================ Task 4: список — планы и уроки

# ================================================================ Task 5: состояние страницы — план и урок по плану

BASE = dict(live_anchor_ms=None, media_url=lambda p: "", presets=[], preset="", dark=True, efir_mode="", tab="",
            hotkey="Ctrl+F9")


class StateTest(unittest.TestCase):
    def test_state_for_topic_and_plan(self):
        from autoprint import scenario
        p = plan90()
        t = plans.new_topic(p, "Функции")
        t2 = plans.new_topic(p, "Циклы")
        t2.blocks = [b for b in t2.blocks if not (b.type == BLOCK_MARKDOWN and b.role == "say")]   # под этапами пусто
        s = scenario.lesson_state(t, plan=p, topics=[], plans=[p], **BASE)
        L = s["lesson"]
        self.assertEqual((L["kind"], L["plan"], L["fixed"], L["topics"]), ("", {"id": "P", "title": "Онлайн 90"}, True, []))
        self.assertEqual(s["plans"], [{"id": "P", "title": "Онлайн 90", "minutes": 65}])
        s2 = scenario.lesson_state(p, plan=None, topics=[t, t2], plans=[p], **BASE)
        L2 = s2["lesson"]
        self.assertEqual((L2["kind"], L2["fixed"], L2["plan"]), ("plan", False, None))
        self.assertEqual(L2["topics"], [{"id": t.id, "title": "Функции"}, {"id": t2.id, "title": "Циклы"}])
        self.assertEqual(L2["stage_use"], {"p1": 1, "p2": 1, "p3": 0, "p4": 1})        # «Циклы» — без заметок
        free = scenario.lesson_state(Template("Св", [stage("А", 5)]), **BASE)["lesson"]
        self.assertEqual((free["kind"], free["plan"], free["fixed"]), ("", None, False))
        ls = scenario.lessons_state([p, t])
        self.assertEqual([(x["kind"], x["plan"]) for x in ls], [("plan", ""), ("", "Онлайн 90")])

    def test_page_commands(self):
        p = plan90()
        f = Template("Свободный", [stage("А", 5), note("x")], id="F")
        win = window([f, p], 18909)
        try:
            win.printer.set_focus("F")
            win.lesson.command({"cmd": "new_lesson", "plan": "P"})
            self.assertEqual(len(win.store.topics_of("P")), 1)
            win.lesson.command({"cmd": "new_plan", "structure": "school45"})
            self.assertEqual(len(win.store.plans()), 2)
            win.printer.set_focus("F")
            win.lesson.command({"cmd": "link_plan", "plan": "P"})
            self.assertEqual(win.store.get("F").plan_id, "P")
            win.lesson.command({"cmd": "unlink_plan"})
            self.assertEqual(win.store.get("F").plan_id, "")
            win.lesson.command({"cmd": "make_plan"})
            self.assertTrue(win.store.get("F").plan_id)
            self.assertEqual(len(win.store.plans()), 3)
        finally:
            close(win)


# ================================================================ Task 7: зарядка — видео по этапу

class ExerciseTest(unittest.TestCase):
    def test_exercise_by_stage_title_and_fallback(self):     # Review Focus 6
        from autoprint.efir.model import Exercise, Look
        video = TMP / "zaryadka.mp4"
        video.write_bytes(b"\x00" * 16)
        t = Template("У", [stage("Зарядка", 3, id="z", stage_kind="exercise", exercise="Шея")], id="U")
        win = window([t], 18910)
        try:
            t = win.store.get("U")
            look = Look(title="С зарядками", exercises=[Exercise("Глаза", str(video)), Exercise("Шея", str(video))])
            win.efir.save_look(look)
            t.look = look.id
            win.printer.set_focus("U")
            win.lesson.command({"cmd": "exercise", "stage": "z"})
            self.assertEqual(win.efir.ex_index, 1)
            t.blocks[0].exercise = "Нет такого"
            win.lesson.command({"cmd": "exercise", "stage": "z"})
            self.assertEqual(win.efir.ex_index, 0)
            self.assertEqual(win.exercise_titles(t), ["Глаза", "Шея"])
            from autoprint import scenario
            st = scenario.item_state(t.blocks[0], lambda p: "")
            self.assertEqual(st["exercise"], "Нет такого")
            win.lesson._last = None
            win.lesson.publish()
            self.assertEqual(win.efir.server._states["lesson"]["exercises"], ["Глаза", "Шея"])
        finally:
            win.efir.show_background()
            close(win)

    def test_exercise_field_editable_and_synced(self):
        from autoprint import lesson_edit
        p = plan90()
        p.blocks.append(stage("Зарядка", 3, id="p5", stage_kind="exercise"))
        lesson_edit.apply(p, [{"op": "set", "block": "p5", "fields": {"exercise": "Глаза"}}], keep_one_stage=True)
        t = plans.new_topic(p)
        self.assertEqual(stages_of(t)[-1].exercise, "Глаза")
        with self.assertRaises(ValueError):
            lesson_edit.apply(p, [{"op": "set", "block": "p5", "fields": {"exercise": "x" * 201}}])


# ================================================================ Task 8: промпт урока

class PromptTest(unittest.TestCase):
    def test_plan_stages_in_prompt(self):
        from autoprint import lesson_ai as L
        p = plan90()
        p.blocks.append(stage("Зарядка для глаз", 3, stage_kind="exercise", exercise="Глаза"))
        s = L.lesson_prompt(L.Options(style=L.STYLE_SCENARIO, cls="5 класс", break_min=10), plan=p, exercises=["Глаза", "Шея"])
        self.assertIn("строго по плану учителя", s)
        for line in ("## Приветствие · 5 мин", "## Перерыв · 10 мин · перерыв", "## Зарядка для глаз · 3 мин · зарядка: Глаза"):
            self.assertIn(line, s)
        self.assertIn("ровно 68", s)                                  # минуты — из плана (65 + 3)
        self.assertNotIn("отдельным этапом в середине", s)
        self.assertIn("Класс / возраст учеников: 5 класс", s)
        self.assertIn("«Глаза», «Шея»", s)
        self.assertIn("![что должно быть на картинке](фото)", s)
        self.assertIn("приложен к сообщению", s)
        self.assertNotIn("Добавь зарядку", s)                         # с планом зарядку решает план

    def test_no_plan_no_videos(self):
        from autoprint import lesson_ai as L
        s = L.lesson_prompt(L.Options(style=L.STYLE_SCENARIO, minutes=90, break_min=10))
        self.assertIn("распиши упражнения в [!say]", s)
        self.assertIn("Добавь зарядку 3–5 минут", s)
        self.assertIn("___ (если не указан", s)
        self.assertIn("перерыв 10 мин отдельным этапом в середине", s)
        s45 = L.lesson_prompt(L.Options(style=L.STYLE_SCENARIO, minutes=45))
        self.assertNotIn("Добавь зарядку", s45)
        with_material = L.lesson_prompt(L.Options(style=L.STYLE_SCENARIO), material="Тема: циклы")
        self.assertIn("Тема: циклы", with_material)
        self.assertNotIn("приложен к сообщению", with_material)
        self.assertEqual(L.chat_prompt("", L.Options(style=L.STYLE_SCENARIO, minutes=45)),
                         L.lesson_prompt(L.Options(style=L.STYLE_SCENARIO, minutes=45)))

    def test_builtin_scenario_is_markdown(self):
        from autoprint import lesson_ai as L
        sys_ = L.instruction(L.Options(style=L.STYLE_SCENARIO))
        self.assertIn("~~~markdown", sys_)
        self.assertNotIn('"blocks"', sys_)
        self.assertIn("следующим сообщением", sys_)
        self.assertNotIn("приложен к сообщению", sys_)
        self.assertIn("Методичка", L.material_for("Методичка", L.Options(style=L.STYLE_SCENARIO)))

    def test_page_prompt_uses_topic_plan(self):
        from PySide6.QtGui import QGuiApplication
        p = plan90()
        t = plans.new_topic(p, "Функции")
        win = window([p, t], 18911)
        try:
            win.printer.set_focus(t.id)
            win.lesson.command({"cmd": "chat_prompt"})
            text = QGuiApplication.clipboard().text()
            self.assertIn("## Теория · 20 мин", text)
            self.assertIn("строго по плану учителя", text)
            win.printer.set_focus("P")
            QGuiApplication.clipboard().setText("")
            win.lesson.command({"cmd": "chat_prompt"})
            self.assertIn("## Практика · 30 мин", QGuiApplication.clipboard().text())
        finally:
            close(win)


# ================================================================ Task 9: картинки по ссылкам

PNG = __import__("base64").b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


class FakeResp:
    def __init__(self, url, ctype, body, final=None):
        self.url, self.body, self.final = url, body, final or url
        self.headers = {"Content-Type": ctype}
        self.pos = 0

    def read(self, n=-1):
        chunk = self.body[self.pos:self.pos + n] if n > 0 else self.body[self.pos:]
        self.pos += len(chunk)
        return chunk

    def geturl(self):
        return self.final

    def close(self):
        pass


def fake(cases, seen=None):
    def opener(url, timeout):
        if seen is not None:
            seen.append(url)
        c = cases.get(url)
        if c is None:
            raise OSError("нет сети")
        return FakeResp(url, *c)
    return opener


class WebImagesTest(unittest.TestCase):
    def test_downloads_public_png(self):
        from autoprint import web_images
        t = Template("У", [Block(BLOCK_IMAGE, "https://ex.org/cat.png", title="Кот", id="i")])
        seen = []
        notes = web_images.fetch_images(t, opener=fake({"https://ex.org/cat.png": ("image/png", PNG)}),
                                        resolve=lambda h: ["93.184.216.34"], progress=lambda a, b: seen.append((a, b)))
        self.assertEqual(notes, [])
        self.assertIsNotNone(storage.media_path(t.find_block("i").text))
        self.assertEqual(seen[-1], (1, 1))
        self.assertEqual(t.find_block("i").title, "Кот")

    def test_private_html_big_redirect_refused(self):   # Review Focus 4
        from autoprint import web_images
        cases = {"http://192.168.1.1/x.png": ("image/png", PNG), "https://ex.org/page": ("text/html", b"<html>"),
                 "https://ex.org/big.png": ("image/png", b"0" * (web_images.MAX_BYTES + 1)),
                 "https://ex.org/redir.png": ("image/png", PNG, "http://127.0.0.1/x.png"), "ftp://ex.org/a.png": None,
                 "https://ex.org/a.svg": ("image/svg+xml", b"<svg/>")}
        t = Template("У", [Block(BLOCK_IMAGE, u, title=f"к{i}", id=f"b{i}") for i, u in enumerate(cases)])
        res = {"192.168.1.1": ["192.168.1.1"], "127.0.0.1": ["127.0.0.1"]}
        seen = []
        notes = web_images.fetch_images(t, opener=fake(cases, seen), resolve=lambda h: res.get(h, ["93.184.216.34"]))
        texts = [b.text for b in t.blocks]
        # не интернет (частный адрес, перенаправление туда, не http) — место «Нужна картинка», ссылка убрана
        self.assertEqual([texts[0], texts[3], texts[4]], ["", "", ""])
        self.assertEqual([t.blocks[i].title for i in (0, 3, 4)], ["к0", "к3", "к4"])
        # интернет, но не картинка / слишком большая / SVG — ссылка остаётся
        self.assertEqual([texts[1], texts[2], texts[5]], ["https://ex.org/page", "https://ex.org/big.png", "https://ex.org/a.svg"])
        self.assertIn("Не скачалось: 3", " ".join(notes))
        self.assertIn("не из интернета: 3", " ".join(notes))
        self.assertNotIn("http://192.168.1.1/x.png", seen)                       # в локальную сеть даже не ходили
        self.assertNotIn("ftp://ex.org/a.png", seen)

    def test_cancel_and_limit(self):
        import threading
        from autoprint import web_images
        t = Template("У", [Block(BLOCK_IMAGE, f"https://ex.org/{i}.png") for i in range(45)])
        ev = threading.Event()
        ev.set()
        web_images.fetch_images(t, cancel=ev, opener=fake({}), resolve=lambda h: ["93.184.216.34"])
        self.assertTrue(all(b.text.startswith("https://") for b in t.blocks))
        seen = []
        cases = {f"https://ex.org/{i}.png": ("image/png", PNG) for i in range(45)}
        web_images.fetch_images(t, opener=fake(cases, seen), resolve=lambda h: ["93.184.216.34"])
        self.assertEqual(len(seen), 40)                                           # не больше 40 на урок
        self.assertEqual(sum(1 for b in t.blocks if b.text.startswith("https://")), 5)

    def test_is_local_url(self):
        from autoprint import web_images
        for u in ("http://localhost/a.png", "http://192.168.0.5/a.png", "http://[::1]/a.png", "http://printer.local/a.png",
                  "http://10.0.0.1/a", "http://169.254.1.1/a", "file:///C:/x.png", "ftp://ex.org/a.png", "http://127.0.0.1:8791/x"):
            self.assertTrue(web_images.is_local_url(u), u)
        for u in ("https://ex.org/a.png", "http://93.184.216.34/a.png"):
            self.assertFalse(web_images.is_local_url(u), u)


# ================================================================ Task 10: «Урок через нейросеть»

ANSWER_PLAN = """Вот урок:

~~~markdown
---
title: Функции
---

> [!goal]
> Ученики пишут функцию.

## Приветствие · 5 мин

> [!say]
> Здравствуйте!

## Теория · 20 мин

![Слайд 2](slide:2)

![Кот у ноутбука](https://ex.org/cat.png)

![Схема функции](фото)

```python
def f(x):
    return x
```

## Перерыв · 10 мин · перерыв
~~~
"""


class ImportLessonTest(unittest.TestCase):
    """1.0: «Новый урок» — «Вставить текст» и «Составит нейросеть» (wizard.py) вместо вкладки «Урок через нейросеть»."""

    def test_copy_prompt_with_plan_and_class(self):
        from autoprint import lesson_ai as L, wizard
        txt = wizard.copy_prompt("lesson", L.Options(style=L.STYLE_SCENARIO, cls="5 класс"), plan=plan90(),
                                 exercises=["Глаза"])
        self.assertIn("## Теория · 20 мин", txt)
        self.assertIn("5 класс", txt)
        self.assertIn("«Глаза»", txt)

    def test_answer_preview_and_add_links_plan(self):
        from autoprint import wizard
        r = wizard.paste_parse(ANSWER_PLAN, plan=plan90())
        for part in ("по плану «Онлайн 90»", "Слайды: 1", "Фото по ссылкам: 1", "Нужно вставить: 1"):
            self.assertIn(part, r.summary)
        self.assertTrue(any("«Практика» в ответе пустой" in n for n in r.notes), r.notes)
        t = r.template
        self.assertEqual(t.plan_id, "P")
        self.assertEqual([b.link for b in stages_of(t)], ["p1", "p2", "p3", "p4"])

    def _paste(self, win):
        from autoprint import wizard
        r = wizard.paste_parse(ANSWER_PLAN, plan=win.store.get("P"))
        return r.template, r.notes

    def test_cancel_while_downloading_adds_nothing(self):
        win = window([plan90()], 18904)
        started = []

        def slow(t, cancel=None, progress=None, **kw):
            started.append(1)
            cancel.wait(5)
            return []
        win.fetch_images = slow
        try:
            n0 = len(win.store.templates)
            t, notes = self._paste(win)
            jid = win.add_new_lesson(t, notes)
            self.assertTrue(wait(lambda: bool(started)))
            win.jobs.cancel(jid)
            pump(300)
            self.assertEqual(len(win.store.templates), n0)
        finally:
            close(win)

    def test_skip_download_adds_lesson(self):
        win = window([plan90()], 18905)
        said = []
        orig = win._notify
        win._notify = lambda text, *a, **k: said.append(text) or orig(text, *a, **k)

        def slow(t, cancel=None, progress=None, **kw):
            cancel.wait(5)
            return ["Не скачалось: 1 — эти картинки покажутся из интернета."]
        win.fetch_images = slow
        try:
            n0 = len(win.store.templates)
            t, notes = self._paste(win)
            jid = win.add_new_lesson(t, notes)
            win.jobs.skip(jid)
            self.assertTrue(wait(lambda: len(win.store.templates) == n0 + 1))
            self.assertTrue(any("Не скачалось" in x for x in said), said)
        finally:
            close(win)

    def test_code_options_never_scenario(self):
        from autoprint import lesson_ai as L, wizard
        self.assertEqual(wizard.code_options({"style": L.STYLE_SCENARIO}).style, L.STYLE_STEPS)


# ================================================================ Task 11: места для картинок, слайды, ответ на странице

class PlacesTest(unittest.TestCase):
    def test_fill_slides(self):
        from autoprint import slides
        png = TMP / "s1.png"
        png.write_bytes(PNG)
        t = Template("У", [Block(BLOCK_IMAGE, "", title="", slide=1, id="a"), Block(BLOCK_IMAGE, "", slide=9, id="b"),
                           Block(BLOCK_IMAGE, "", title="Кот", id="c")])
        notes = slides.fill_slides(t, "x.pdf", render=lambda pdf, n, out: png if n == 1 else None)
        self.assertTrue(storage.media_path(t.find_block("a").text))
        self.assertEqual((t.find_block("b").text, t.find_block("c").text), ("", ""))
        self.assertEqual(notes, ["Нет слайдов: 9"])
        self.assertEqual(slides.fill_slides(Template("П", [stage("А")]), "x.pdf", render=lambda *a: None), [])

    def test_fill_slides_command(self):
        from test_v11 import make_pdf
        t = Template("У", [stage("А", 5), Block(BLOCK_IMAGE, "", slide=2, id="a")], id="U")
        win = window([t], 18913)
        try:
            t = win.store.get("U")
            pdf = make_pdf(TMP / "fill.pdf", ["Один", "Два"])
            self.assertTrue(win.lesson.fill_slides_from(t, pdf))
            self.assertTrue(storage.media_path(t.find_block("a").text))
            t.find_block("a").text = ""
            win.efir.launch_lesson(t, start="")                                    # идёт эфир — не подставляем
            try:
                self.assertFalse(win.lesson.fill_slides_from(t, pdf))
                self.assertEqual(t.find_block("a").text, "")
            finally:
                win.efir.stop_live()
        finally:
            close(win)

    def test_places_not_in_slide_stepping(self):
        from autoprint.ui.lesson_control import LessonController
        png = TMP / "s2.png"
        png.write_bytes(PNG)
        t = Template("У", [Block(BLOCK_IMAGE, "", slide=1), Block(BLOCK_IMAGE, storage.import_media(png), slide=2, id="s2")])
        self.assertEqual([b.id for b in LessonController._slides(t)], ["s2"])

    def test_item_state_places_and_local_links(self):
        from autoprint import scenario
        for u in ("http://localhost/a.png", "http://192.168.0.5/a.png", "http://[::1]/a.png", "http://printer.local/a.png",
                  "file:///C:/secret.png"):
            d = scenario.item_state(Block(BLOCK_IMAGE, u, title="Кот"), lambda p: "")
            self.assertEqual((d["url"], d["missing"], d["place"]), ("", True, "photo"), u)
        d = scenario.item_state(Block(BLOCK_IMAGE, "https://ex.org/a.png"), lambda p: "")
        self.assertEqual((d["url"], d["place"]), ("https://ex.org/a.png", ""))
        self.assertEqual(scenario.item_state(Block(BLOCK_IMAGE, "", slide=3), lambda p: "")["place"], "slide")
        self.assertEqual(scenario.item_state(Block(BLOCK_IMAGE, "", title="Кот"), lambda p: "")["place"], "photo")

    def test_find_image_opens_search(self):
        from PySide6.QtGui import QDesktopServices
        t = Template("У", [stage("А", 5), Block(BLOCK_IMAGE, "", title="Кот у ноутбука", id="c")], id="U")
        win = window([t], 18914)
        opened = []
        orig = QDesktopServices.openUrl
        QDesktopServices.openUrl = staticmethod(lambda url: opened.append(url.toString()) or True)
        try:
            win.printer.set_focus("U")
            win.lesson.command({"cmd": "find_image", "block": "c"})
            self.assertEqual(len(opened), 1)
            self.assertTrue(opened[0].startswith("https://yandex.ru/images/search?text="), opened[0])
            self.assertIn("text=Кот у ноутбука", opened[0])                     # QUrl показывает раскодированным
        finally:
            QDesktopServices.openUrl = orig
            close(win)

    def test_page_answer_links_plan_and_fetches_in_background(self):
        p = plan90()
        t = plans.new_topic(p, "Функции")
        win = window([p, t], 18915)
        fetched = []

        def fake_fetch(tt, **kw):
            fetched.append(tt.title)
            return ["Не скачалось: 1 — эти картинки покажутся из интернета."]
        win.lesson.fetch = fake_fetch
        try:
            win.printer.set_focus("P")
            win.lesson.command({"cmd": "apply_answer", "text": ANSWER_PLAN})
            self.assertTrue(wait(lambda: len(win.store.topics_of("P")) == 2))
            new = win.store.topics_of("P")[-1]
            self.assertEqual((new.plan_id, new.title, new.kind), ("P", "Функции", ""))
            self.assertEqual([b.link for b in stages_of(new)], ["p1", "p2", "p3", "p4"])
            self.assertEqual(fetched, ["Функции"])
        finally:
            close(win)


# ================================================================ Task 12: образец плана

class SamplePlanTest(unittest.TestCase):
    def test_sample_plan(self):
        from autoprint.samples_lesson import PLAN_SAMPLE_ID, PLAN_TITLE, plan_sample
        p = plan_sample()
        st = stages_of(p)
        self.assertEqual((PLAN_SAMPLE_ID, p.title, p.kind), ("plan_v1", PLAN_TITLE, "plan"))
        self.assertEqual(PLAN_TITLE, "Пример плана: онлайн-урок 90 мин")
        self.assertEqual(sum(b.minutes for b in st), 90)
        self.assertEqual([b.title for b in st], ["Приветствие и проверка связи", "Повторение", "Новая тема", "Зарядка для глаз",
                                                 "Практика 1", "Перерыв", "Практика 2", "Итоги и рефлексия", "Домашнее задание"])
        self.assertEqual([b.minutes for b in st], [5, 10, 20, 3, 12, 10, 20, 7, 3])
        self.assertEqual((st[3].stage_kind, st[5].stage_kind), ("exercise", "break"))
        self.assertTrue(any(b.role == "do" and "Проверить звук и демонстрацию" in b.text for b in p.blocks))
        self.assertTrue(any(b.role == "ask" and "Что сегодня получилось? Что было трудно?" in b.text for b in p.blocks))
        self.assertTrue(any(b.role == "homework" for b in p.blocks))

    def test_sample_plan_added_once_at_the_end(self):
        win = window([Template("Мой", [stage("А", 5)], id="M")], 18916)
        try:
            self.assertEqual(win.store.plans(), [])                              # уже видели — не добавляется
            win.settings.samples_seen.remove("plan_v1")
            win._ensure_samples()
            self.assertEqual([p.title for p in win.store.plans()], ["Пример плана: онлайн-урок 90 мин"])
            self.assertEqual(win.store.templates[0].id, "M")                       # в конец: урок в фокусе не меняется
            self.assertIn("plan_v1", win.settings.samples_seen)
            win._ensure_samples()
            self.assertEqual(len(win.store.plans()), 1)
        finally:
            close(win)


# ================================================================ итоговое ревью: исправления

class FinalReviewTest(unittest.TestCase):
    def test_numeric_ipv4_and_cgnat_are_local(self):
        """Находка 1: 127.1, 2130706433, 0x7f000001, 0177.0.0.1 — браузер читает их как 127.0.0.1; 100.64/10 — не интернет."""
        from autoprint import scenario, web_images
        for u in ("http://127.1/a.png", "http://2130706433/a.png", "http://0x7f000001/a.png", "http://0177.0.0.1/a.png",
                  "http://3232235777/a.png", "http://100.64.0.1/a.png", "http://[::ffff:127.0.0.1]/a.png",
                  "http://192.168.1/a.png", "http://0/a.png"):
            self.assertTrue(web_images.is_local_url(u), u)
            self.assertEqual(scenario.item_state(Block(BLOCK_IMAGE, u, title="к"), lambda p: "")["url"], "", u)
        self.assertFalse(web_images.is_local_url("http://8.8.8.8/a.png"))
        self.assertFalse(web_images.is_local_url("https://img.example.org/cat.jpg"))
        t = Template("У", [Block(BLOCK_IMAGE, "https://cgnat.example/a.png", id="c")])
        web_images.fetch_images(t, opener=fake({"https://cgnat.example/a.png": ("image/png", PNG)}),
                                resolve=lambda h: ["100.64.3.4"])
        self.assertEqual(t.find_block("c").text, "")                                 # имя ведёт в 100.64/10 — место

    def test_download_deadline_and_skip_inside_read(self):
        """Находка 5: «15 с на картинку» — на всю картинку, а не на каждое чтение; «Пропустить» — сразу, не дожидаясь
        картинки, которая качается."""
        import threading
        from autoprint import web_images

        class Slow(FakeResp):
            def read(self, n=-1):
                time.sleep(0.05)
                return b"0" * 1024                                            # поток не кончается — медленный сервер

        def opener(url, timeout):
            return Slow(url, "image/png", b"")
        orig = web_images.TIMEOUT
        web_images.TIMEOUT = 0.4
        try:
            t = Template("У", [Block(BLOCK_IMAGE, "https://ex.org/slow.png", id="s")])
            t0 = time.monotonic()
            notes = web_images.fetch_images(t, opener=opener, resolve=lambda h: ["93.184.216.34"])
            self.assertLess(time.monotonic() - t0, 2)
            self.assertEqual(t.find_block("s").text, "https://ex.org/slow.png")
            self.assertIn("Не скачалось: 1", " ".join(notes))
        finally:
            web_images.TIMEOUT = orig
        ev = threading.Event()
        threading.Timer(0.3, ev.set).start()
        t = Template("У", [Block(BLOCK_IMAGE, "https://ex.org/slow.png", id="s"), Block(BLOCK_IMAGE, "https://ex.org/2.png")])
        t0 = time.monotonic()
        web_images.fetch_images(t, cancel=ev, opener=opener, resolve=lambda h: ["93.184.216.34"])
        self.assertLess(time.monotonic() - t0, 2)                                    # не ждали 15 с медленной картинки

    def test_exercise_name_in_quotes(self):
        """Находка 7: промпт показывает видео в «ёлочках» — нейросеть так и пишет; видео всё равно находится."""
        from autoprint import lesson_md
        from autoprint.efir.model import Exercise, Look
        t = lesson_md.parse("## Зарядка · 3 мин · зарядка: «Гимнастика для глаз»\n", None, "x")
        self.assertEqual(stages_of(t)[0].exercise, "Гимнастика для глаз")
        video = TMP / "q.mp4"
        video.write_bytes(b"\x00" * 16)
        u = Template("У", [stage("Зарядка", 3, id="z", stage_kind="exercise", exercise="«шея »")], id="U")
        win = window([u], 18919)
        try:
            u = win.store.get("U")
            look = Look(title="З", exercises=[Exercise("Глаза", str(video)), Exercise("Шея", str(video))])
            win.efir.save_look(look)
            u.look = look.id
            win.printer.set_focus("U")
            win.lesson.command({"cmd": "exercise", "stage": "z"})
            self.assertEqual(win.efir.ex_index, 1)
        finally:
            win.efir.show_background()
            close(win)

    def test_plan_look_reaches_topics(self):
        """Находка 4: сменили оформление у плана — у уроков по нему оно то же (видео зарядки находится)."""
        from autoprint.efir.model import Look
        p = plan90()
        t = plans.new_topic(p, "Функции")
        win = window([p, t], 18918)
        try:
            look = Look(title="Кабинет 12")
            win.efir.save_look(look)
            win.printer.set_focus("P")
            win.lesson.command({"cmd": "preset", "id": look.id})
            self.assertEqual(win.store.get("P").look, look.id)
            self.assertEqual(win.store.get(t.id).look, look.id)
        finally:
            close(win)

    def test_page_answer_download_has_overall_limit(self):
        """Находка 5, экран урока: «Вставить ответ нейросети» с фото — урок добавляется не позже общего срока."""
        from autoprint.ui import lesson_control
        p = plan90()
        win = window([p], 18917)
        orig = lesson_control.ANSWER_FETCH_LIMIT
        lesson_control.ANSWER_FETCH_LIMIT = 0.3

        def stuck(tt, cancel=None, **kw):
            cancel.wait(30)                                                       # сеть «висит», пока не отменят
            return []
        win.lesson.fetch = stuck
        try:
            win.printer.set_focus("P")
            t0 = time.monotonic()
            win.lesson.command({"cmd": "apply_answer", "text": ANSWER_PLAN})
            self.assertTrue(wait(lambda: len(win.store.topics_of("P")) == 1, 5))
            self.assertLess(time.monotonic() - t0, 4)
        finally:
            lesson_control.ANSWER_FETCH_LIMIT = orig
            close(win)


# ================================================================ 0.12.1: мелочи по отзыву учителя

class TabAutoOpenTest(unittest.TestCase):
    def test_break_exercise_slide_open_the_tab_once(self):
        """Вкладка экрана учеников не открыта, а учитель включает перерыв / зарядку / слайд — программа сама её
        открывает (один раз, не на каждое нажатие) и говорит, что её надо показать ученикам."""
        from autoprint.efir.model import Exercise, Look
        video = TMP / "tab.mp4"
        video.write_bytes(b"\x00" * 16)
        t = Template("У", [stage("А", 5, id="a"), stage("Зарядка", 3, id="z", stage_kind="exercise")], id="U")
        win = window([t], 18920)
        opened, said = [], []
        win.efir.open_tab = lambda: opened.append(1)
        win.efir.message.connect(lambda text, warn: said.append(text))
        try:
            t = win.store.get("U")
            look = Look(title="З", exercises=[Exercise("Глаза", str(video))])
            win.efir.save_look(look)
            t.look = look.id
            win.printer.set_focus("U")
            win.efir.clients = 0
            win.lesson.command({"cmd": "break", "stage": "", "minutes": 5})
            self.assertEqual(len(opened), 1)
            self.assertTrue(any("открыл" in s.lower() and "покажите" in s.lower() for s in said), said)
            win.lesson.command({"cmd": "exercise", "stage": "z"})
            self.assertEqual(len(opened), 1)                                          # только что открыли — не снова
            win.efir.clients = 1
            win.efir._tab_opened_at = 0
            win.lesson.command({"cmd": "break", "stage": "", "minutes": 5})
            self.assertEqual(len(opened), 1)                                          # вкладка на связи — не открываем
            self.assertFalse(any("никто не увидит" in s for s in said), said)
        finally:
            win.efir.show_background()
            close(win)


class ExerciseSoundTest(unittest.TestCase):
    def test_lesson_page_knows_when_exercise_is_silent_or_waiting(self):
        """Зарядка без звука или стоит до щелчка (браузер не дал автозапуск) — экран урока это видит и говорит, что
        сделать; щелчок по вкладке учеников это снимает."""
        from autoprint.efir.model import Exercise, Look
        video = TMP / "ex-sound.mp4"
        video.write_bytes(b"\x00" * 16)
        t = Template("У", [stage("Зарядка", 3, id="z", stage_kind="exercise")], id="U")
        win = window([t], 18926)
        said = []
        win.efir.message.connect(lambda text, warn: said.append(text))
        try:
            t = win.store.get("U")
            look = Look(title="З", exercises=[Exercise("Глаза", str(video))])
            win.efir.save_look(look)
            t.look = look.id
            win.printer.set_focus("U")
            win.efir.clients = 1
            win.lesson.command({"cmd": "exercise", "stage": "z"})
            ef = win.efir
            ef._on_report({"type": "blocked", "seq": ef.ex_seq, "all": True})     # даже без звука браузер не запускает
            win.lesson._last = None
            win.lesson.publish()
            st = ef.server._states["lesson"]["efir"]
            self.assertEqual((st["ex_waiting"], st["ex_muted"]), (True, True))
            self.assertTrue(any("ждёт щелчка" in s for s in said), said)
            ef._on_report({"type": "video", "seq": ef.ex_seq, "pos": 1, "dur": 60, "paused": False, "muted": True})
            win.lesson.publish()
            st = ef.server._states["lesson"]["efir"]
            self.assertEqual((st["ex_waiting"], st["ex_muted"]), (False, True))   # идёт, но без звука
            ef._on_report({"type": "unlock"})
            ef._on_report({"type": "video", "seq": ef.ex_seq, "pos": 2, "dur": 60, "paused": False, "muted": False})
            win.lesson.publish()
            st = ef.server._states["lesson"]["efir"]
            self.assertEqual((st["ex_waiting"], st["ex_muted"]), (False, False))
        finally:
            win.efir.show_background()
            close(win)

    def test_missing_exercise_file_known_in_advance(self):
        from autoprint.efir.model import Exercise, Look
        t = Template("У", [stage("Зарядка", 3, id="z", stage_kind="exercise")], id="U")
        win = window([t], 18927)
        try:
            t = win.store.get("U")
            look = Look(title="З", exercises=[Exercise("Глаза", str(TMP / "нет-такого.mp4"))])
            win.efir.save_look(look)
            t.look = look.id
            win.printer.set_focus("U")
            win.lesson._last = None
            win.lesson.publish()
            self.assertEqual(win.efir.server._states["lesson"]["exercises_missing"], ["Глаза"])
        finally:
            close(win)

    def test_screen_page_retries_and_unmutes(self):
        """Экран учеников: видимая вкладка — снова запустить видео; щелчок — запустить стоящее и включить звук."""
        html = (Path(storage.__file__).resolve().parent / "efir" / "page" / "screen.html").read_text(encoding="utf-8")
        self.assertIn("visibilitychange", html)
        self.assertIn("all: true", html)
        self.assertIn("unlock", html)


class PackageTest(unittest.TestCase):
    """Урок одним файлом (.autoprint): уроки, план, оформление с видео зарядок и все картинки — внутри."""

    def lesson_with_media(self):
        png = TMP / "pkg-cat.png"
        png.write_bytes(PNG)
        p = plan90()
        t = plans.new_topic(p, "Функции")
        t.blocks.append(Block(BLOCK_IMAGE, storage.import_media(png), title="Кот", id="img1"))
        return p, t

    def look_with_media(self):
        from autoprint.efir.model import Exercise, Look
        vid = TMP / "pkg-eyes.mp4"
        vid.write_bytes(b"\x00\x01" * 50)
        bg = TMP / "pkg-break.png"
        bg.write_bytes(PNG)
        return Look(title="Кабинет", break_background="image:" + str(bg), exercises=[Exercise("Глаза", str(vid))])

    def test_roundtrip_lesson_plan_look(self):
        import zipfile
        from autoprint import package
        p, t = self.lesson_with_media()
        look = self.look_with_media()
        t.look = look.id
        f = TMP / "урок.autoprint"
        summary = package.export_package(f, lessons=[t], plans=[p], looks=[look])
        self.assertEqual((summary["lessons"], summary["plans"], summary["looks"]), (1, 1, 1))
        with zipfile.ZipFile(f) as z:
            names = z.namelist()
        self.assertIn("manifest.json", names)
        self.assertTrue(any(n.startswith("media/") for n in names))
        self.assertTrue(any(n.startswith("looks_media/") and n.endswith(".mp4") for n in names))
        self.assertTrue(any(n.endswith(".md") for n in names))                      # и для людей — урок .md
        pkg = package.read_package(f)
        self.assertEqual([x.title for x in pkg.plans], ["Онлайн 90"])
        new = pkg.lessons[0]
        newp = pkg.plans[0]
        self.assertNotEqual(new.id, t.id)
        self.assertEqual(new.plan_id, newp.id)                                    # связь сохранена
        self.assertEqual([b.link for b in stages_of(new)], [b.id for b in stages_of(newp)])
        self.assertFalse(plans.sync_topic(new, newp))
        img = next(b for b in new.blocks if b.type == BLOCK_IMAGE)
        self.assertEqual(storage.media_path(img.text).read_bytes(), PNG)          # картинка внутри файла
        lk = pkg.looks[0]
        self.assertEqual((lk.id, new.look), (look.id, look.id))
        self.assertTrue(Path(lk.exercises[0].path).is_file())
        self.assertTrue(Path(lk.break_background[6:]).is_file())

    def test_ai_zip_with_md_and_images(self):
        """Архив от нейросети: .md и картинки рядом; пути наружу и файлы с компьютера — не берём."""
        import zipfile
        from autoprint import package
        secret = TMP / "secret-photo.png"
        secret.write_bytes(PNG)
        f = TMP / "от-нейросети.zip"
        with zipfile.ZipFile(f, "w") as z:
            z.writestr("lesson/урок.md", "---\ntitle: Циклы\n---\n\n## Тема · 10 мин\n\n![Кот](images/cat.png)\n\n"
                                         f"![Чужое]({secret.as_posix()})\n\n> [!say]\n> Привет\n")
            z.writestr("lesson/images/cat.png", PNG)
        pkg = package.read_package(f)
        t = pkg.lessons[0]
        self.assertEqual(t.title, "Циклы")
        imgs = [b for b in t.blocks if b.type == BLOCK_IMAGE]
        self.assertEqual(storage.media_path(imgs[0].text).read_bytes(), PNG)
        self.assertIsNone(storage.media_path(imgs[1].text))                        # файл с компьютера не взят

    def test_zip_slip_refused(self):
        import zipfile
        from autoprint import package
        f = TMP / "злой.autoprint"
        with zipfile.ZipFile(f, "w") as z:
            z.writestr("manifest.json", '{"format": "autoprintcode-package", "version": 1}')
            z.writestr("../evil.txt", "x")
        with self.assertRaises(ValueError):
            package.read_package(f)

    def test_import_through_window(self):
        from autoprint import package
        p, t = self.lesson_with_media()
        look = self.look_with_media()
        t.look = look.id
        f = TMP / "в-окно.autoprint"
        package.export_package(f, lessons=[t], plans=[p], looks=[look])
        win = window([Template("Мой", [stage("А", 5)], id="M")], 18928)
        try:
            res = win.import_paths([str(f)])                       # 1.0: «Уже есть файл урока?» / файл на окне
            self.assertEqual(len(res["added"]), 2)
            self.assertEqual(len(win.store.plans()), 1)
            lesson = next(x for x in win.store.templates if x.title == "Функции")
            self.assertEqual(lesson.plan_id, win.store.plans()[0].id)
            self.assertIsNotNone(win.efir.store.look(look.id))                     # оформление с видео — у получателя
        finally:
            close(win)

    def test_window_export_options(self):
        """Экспорт из окна: галочки «план» и «оформление с видео» решают, что попадёт в файл."""
        import zipfile
        p, t = self.lesson_with_media()
        win = window([p, t], 18929)
        try:
            t = win.store.get(t.id)
            look = self.look_with_media()
            win.efir.save_look(look)
            t.look = look.id
            f = TMP / "из-окна.autoprint"
            s = win.export_package([t], f, include_plans=False, include_looks=False)
            self.assertEqual((s["plans"], s["looks"]), (0, 0))
            with zipfile.ZipFile(f) as z:
                self.assertFalse(any(n.startswith("looks_media/") for n in z.namelist()))
            s = win.export_package([t], f, include_plans=True, include_looks=True)
            self.assertEqual((s["plans"], s["looks"]), (1, 1))
            self.assertGreater(win.package_media_size([t], include_looks=True), 100)
            sizes = win.commands.call_export_sizes({"id": t.id})        # 1.0: размеры для листа «Экспорт»
            self.assertTrue(sizes["linked"])
            self.assertGreater(sizes["looks"], 100)
        finally:
            close(win)


class LiveSafetyTest(unittest.TestCase):
    def test_timer_close_hides_for_lesson(self):
        """× мини-таймера во время урока — только прячет таймер; урок идёт дальше, таймер открывается снова."""
        from PySide6.QtWidgets import QMessageBox
        t = Template("У", [stage("А", 5), stage("Б", 10)], id="U")
        win = window([t], 18921)
        orig = QMessageBox.exec
        asked = []
        QMessageBox.exec = lambda box: asked.append(box.text()) or 0
        try:
            t = win.store.get("U")
            win.efir.launch_lesson(t, show=True)
            tw = win.efir.timer_window
            self.assertIsNotNone(tw)
            tw.close()
            pump(50)
            self.assertEqual(asked, [])                                              # не спрашивает
            self.assertFalse(tw.isVisible())
            self.assertTrue(win.efir.live_lesson_id())                               # урок идёт
            win.efir.show_timer()
            self.assertTrue(win.efir.timer_window.isVisible())
        finally:
            QMessageBox.exec = orig
            win.efir.stop_live()
            close(win)

    def slides_win(self, port):
        from test_v11 import slide_png
        t = Template("С", [stage("А", 10), Block(BLOCK_IMAGE, slide_png(1), slide=1, id="s1"),
                           Block(BLOCK_IMAGE, slide_png(2), slide=2, id="s2"), Block(BLOCK_IMAGE, slide_png(3), slide=3, id="s3")],
                     id="S")
        win = window([t], port)
        win.printer.set_focus("S")
        win.efir.clients = 1                                                       # вкладка учеников «на связи»
        return win

    def test_clicker_resumes_last_slide(self):
        """После «фон» / перерыва кликер продолжает с того же слайда (как B в PowerPoint), а не с первого."""
        win = self.slides_win(18922)
        try:
            ef = win.efir
            win.lesson.command({"cmd": "slide", "block": "s2"})
            self.assertEqual((ef.mode, (ef.slide or {}).get("bid")), ("slide", "s2"))
            win.lesson._screen_key("b")                                            # B — фон
            self.assertEqual(ef.mode, "idle")
            win.lesson._screen_key("b")                                            # B ещё раз — тот же слайд
            self.assertEqual((ef.mode, ef.slide.get("bid")), ("slide", "s2"))
            win.lesson.command({"cmd": "break", "stage": "", "minutes": 5})
            win.lesson._screen_key("ArrowRight")                                    # после перерыва — с того же слайда
            self.assertEqual(ef.slide.get("bid"), "s2")
            win.lesson._screen_key("ArrowRight")
            self.assertEqual(ef.slide.get("bid"), "s3")
        finally:
            win.efir.show_background()
            close(win)

    def test_break_controls_copy_url_and_restore_anchor(self):
        from datetime import timedelta
        from PySide6.QtGui import QGuiApplication
        win = self.slides_win(18923)
        try:
            ef = win.efir
            win.lesson.command({"cmd": "break", "stage": "", "minutes": 5})
            ends = ef.brk_ends
            win.lesson.command({"cmd": "break_adjust", "seconds": 300})
            self.assertAlmostEqual(ef.brk_ends - ends, 300, delta=1)
            win.lesson.command({"cmd": "break_pause"})
            self.assertIsNotNone(ef.brk_left_paused)
            win.lesson.command({"cmd": "break_restart"})
            self.assertIsNone(ef.brk_left_paused)
            ef.show_background()
            win.lesson.command({"cmd": "copy_url"})
            self.assertEqual(QGuiApplication.clipboard().text(), ef.server.url)
            ef.launch_lesson(win.store.get("S"), start="")
            live = ef.store.live
            old = live.anchor - timedelta(minutes=3)
            ef.store.set_live(live.webinar_id, old)
            win.lesson.command({"cmd": "shift_now"})
            self.assertNotEqual(ef.store.live.anchor, old)
            win.lesson.command({"cmd": "restore_anchor", "ms": int(old.timestamp() * 1000)})
            self.assertEqual(ef.store.live.anchor, old)                              # «Вернуть» после сдвига
        finally:
            win.efir.stop_live()
            close(win)

    def test_notice_reaches_lesson_page(self):
        """Сообщения программы — и на экране урока (окно программы скрыто, трей пропадает за 3 с)."""
        win = self.slides_win(18924)
        try:
            win._notify("Проверка: курсор в Jupyter", warn=True)
            win.lesson._last = None
            win.lesson.publish()
            n = win.efir.server._states["lesson"]["notice"]
            self.assertEqual((n["text"], n["warn"]), ("Проверка: курсор в Jupyter", True))
            seq = n["seq"]
            win._notify("Второе")
            win.lesson.publish()
            self.assertEqual(win.efir.server._states["lesson"]["notice"]["seq"], seq + 1)
            win.efir.ensure_server()
            win.efir.unlocked = True
            self.assertEqual(win.efir.tab_status()[0], "Вкладка экрана учеников на связи")
        finally:
            close(win)


if __name__ == "__main__":
    unittest.main()
