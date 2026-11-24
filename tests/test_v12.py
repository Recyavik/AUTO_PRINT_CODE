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


if __name__ == "__main__":
    unittest.main()
