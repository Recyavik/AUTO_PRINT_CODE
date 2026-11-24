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

class LibraryTest(unittest.TestCase):
    def test_groups_and_meta(self):
        from PySide6.QtCore import Qt
        from autoprint.ui.library import ROLE_HEADER, ROLE_META
        p = plan90()
        t = plans.new_topic(p, "Функции")
        f = Template("Свободный", [stage("А", 5)])
        win = window([t, f, p], 18905)
        try:
            lib = win.library.list
            rows = [(lib.item(i).text(), bool(lib.item(i).data(ROLE_HEADER))) for i in range(lib.count())]
            self.assertEqual(rows, [("Планы уроков", True), ("Онлайн 90", False), ("Уроки", True), ("Функции", False),
                                    ("Свободный", False)])
            self.assertEqual(lib.item(1).data(ROLE_META), "План · 1 ч 5 мин · 4 этапа · уроков: 1")
            self.assertEqual(lib.item(3).data(ROLE_META), "1 ч 5 мин · 4 этапа · без кода · план «Онлайн 90»")
            self.assertFalse(lib.item(0).flags() & Qt.ItemFlag.ItemIsSelectable)
            self.assertTrue(win.library.group_label.isHidden())                    # подпись «Уроки» над списком — в списке
            self.assertNotEqual(lib.currentRow(), 0)                                # заголовок не выбирается
            win.library.search.setText("функ")
            self.assertEqual([lib.item(i).text() for i in range(lib.count()) if not lib.item(i).isHidden()],
                             ["Уроки", "Функции"])                                 # пустая группа прячет заголовок
        finally:
            close(win)

    def test_no_plans_looks_like_before(self):
        from autoprint.ui.library import ROLE_HEADER
        win = window([Template("Свободный", [stage("А", 5)])], 18906)
        try:
            lib = win.library.list
            self.assertEqual([bool(lib.item(i).data(ROLE_HEADER)) for i in range(lib.count())], [False])
            self.assertFalse(win.library.group_label.isHidden())
        finally:
            close(win)

    def test_new_menu_lists_plans(self):
        win = window([plan90()], 18907)
        try:
            m = win.library.new_menu([("P", "Онлайн 90")])
            texts = [a.text() for a in m.actions() if a.text()]
            self.assertEqual(texts[0], "По плану «Онлайн 90»")
            self.assertIn("Новый план урока", texts)
            self.assertIn("Из презентации…", texts)
            sub = next(a.menu() for a in m.actions() if a.text() == "Новый план урока")
            self.assertEqual([a.text() for a in sub.actions() if a.text()][0], "Пустой план")
            self.assertEqual([a.text() for a in win.library.new_menu().actions() if a.text()][0], "По плану «Онлайн 90»")
            win.library.new_structure.emit("plan:P")
            self.assertTrue(any(x.plan_id == "P" for x in win.store.templates))
            win.library.new_structure.emit("newplan:pair90")
            self.assertEqual(len(win.store.plans()), 2)
        finally:
            close(win)

    def test_context_menu_actions(self):
        p = plan90()
        t = plans.new_topic(p, "Функции")
        f = Template("Свободный", [stage("А", 5)], id="F")
        win = window([t, f, p], 18908)
        try:
            texts = {x: [a.text() for a in win._library_menu_for(win.store.get(x)).actions() if a.text()]
                     for x in ("P", t.id, "F")}
            self.assertEqual(texts["P"][0], "Новый урок по этому плану")
            self.assertIn("Отвязать от плана", texts[t.id])
            self.assertNotIn("Сделать из этапов план", texts[t.id])
            self.assertIn("Сделать из этапов план", texts["F"])
            self.assertIn("Привязать к плану", texts["F"])
            self.assertNotIn("Отвязать от плана", texts["F"])
        finally:
            close(win)


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


if __name__ == "__main__":
    unittest.main()
