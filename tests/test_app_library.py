"""Экран «Уроки»: продолжить, планы, все уроки по группам, поиск, открыть, переименовать, меню урока, удалить,
импорт перетаскиванием (перенос проверок старого списка уроков Qt: test_v10 / test_v12).

    .venv\\Scripts\\python.exe tests\\test_app_library.py
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from apphelp import AppPage, code, note, pump, stage  # noqa: F401

from autoprint import plans
from autoprint.storage import KIND_PLAN, Template


def plan90() -> Template:
    p = Template("Онлайн 90", [stage("Приветствие", 5, id="ps1"), stage("Теория", 30, id="ps2"),
                               stage("Перерыв", 10, id="ps3", stage_kind="break"), stage("Практика", 20, id="ps4")], id="P")
    p.kind = KIND_PLAN
    return p


def lessons() -> list[Template]:
    p = plan90()
    t1 = plans.new_topic(p, "Функции")
    t1.id = "T1"
    t2 = plans.new_topic(p, "Циклы")
    t2.id = "T2"
    free = Template("Свободный", [stage("А", 5), code("x", id="fc1"), stage("Б", 10), code("y", id="fc2")], id="F")
    nocode = Template("Без кода", [note("Привет", id="nn")], id="N")
    return [t1, t2, free, nocode, p]


class LibraryTest(AppPage):
    port = 18995
    templates = staticmethod(lessons)
    route = "#/lessons"

    def setUp(self):
        self.go("#/lessons", "lessons")
        self.app.publish_now()                   # прошлый тест мог только что удалить урок — страница видит свежее
        n = len(self.store.templates)
        self.assertTrue(self.wait_js(f"window.S.lessons.length === {n} && "
                                     f"document.querySelectorAll('#lessonList .lrow').length === "
                                     f"{len([t for t in self.store.templates if t.kind != 'plan'])}"))

    def rows(self) -> list[str]:
        return self.js("[...document.querySelectorAll('#lessonList .grp, #lessonList .lrow')]"
                       ".filter(e => !e.hidden).map(e => e.classList.contains('grp') ? '# ' + e.dataset.title"
                       " : e.querySelector('.tt').textContent)")

    def test_groups_by_plan(self):
        self.assertEqual(self.rows(), ["# Онлайн 90", "Функции", "Циклы", "# Без плана", "Свободный", "Без кода"])

    def test_meta_lines(self):
        """Перенос test_v10.test_library_meta и test_v12 meta: что в уроке — одной строкой."""
        meta = self.js("Object.fromEntries([...document.querySelectorAll('#lessonList .lrow')]"
                       ".map(r => [r.dataset.id, r.querySelector('.lm').textContent]))")
        self.assertEqual(meta["F"], "15 мин · 2 этапа · 2 кода")
        self.assertEqual(meta["N"], "без кода")
        self.assertEqual(meta["T1"], "1 ч 5 мин · 4 этапа · без кода · план «Онлайн 90»")

    def test_plan_cards_with_bar(self):
        card = "#plansGrid .pcard[data-id=P]"
        self.assertTrue(self.wait_js(f"!!document.querySelector('{card}')"))
        grows = self.js(f"[...document.querySelectorAll('{card} .minibar i')].map(i => i.style.flexGrow)")
        self.assertEqual(grows, ["5", "30", "10", "20"])
        self.assertTrue(self.js(f"document.querySelector('{card} .minibar i:nth-child(3)').classList.contains('br')"))
        self.assertIn("4 этапа · 2 урока", self.js(f"document.querySelector('{card}').textContent"))
        self.assertTrue(self.js("!!document.querySelector('#newPlanCard')"))

    def test_search_filters_and_hides_empty_groups(self):
        self.js("{ const s = document.querySelector('#libSearch'); s.value = 'функ'; s.dispatchEvent(new Event('input')) }")
        self.assertTrue(self.wait_js("[...document.querySelectorAll('#lessonList .lrow')].filter(r => !r.hidden).length === 1"))
        self.assertEqual(self.rows(), ["# Онлайн 90", "Функции"])
        self.js("{ const s = document.querySelector('#libSearch'); s.value = ''; s.dispatchEvent(new Event('input')) }")

    def test_open_on_click_once_and_enter(self):
        opened = []
        self.app.navigate.connect(opened.append)
        try:
            self.js("{ const r = document.querySelector('#lessonList .lrow[data-id=F]'); r.click();"
                    " r.dispatchEvent(new MouseEvent('dblclick', {bubbles: true})) }")
            self.assertTrue(self.wait_py(lambda: "#/lesson/F" in opened))
            pump(300)
            self.assertEqual(opened.count("#/lesson/F"), 1)          # двойной щелчок — одно открытие
            self.go("#/lessons", "lessons")
            self.js("{ const r = document.querySelector('#lessonList .lrow[data-id=N]'); r.focus();"
                    " r.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true})) }")
            self.assertTrue(self.wait_py(lambda: "#/lesson/N" in opened))
        finally:
            self.app.navigate.disconnect(opened.append)
        self.go("#/lessons", "lessons")

    def test_rename_f2(self):
        self.js("{ const r = document.querySelector('#lessonList .lrow[data-id=N]'); r.focus();"
                " r.dispatchEvent(new KeyboardEvent('keydown', {key: 'F2', bubbles: true})) }")
        self.assertTrue(self.wait_js("!!document.querySelector('#lessonList .lrow[data-id=N] input')"))
        self.js("{ const i = document.querySelector('#lessonList .lrow[data-id=N] input'); i.value = 'Новое имя';"
                " i.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true})) }")
        self.assertTrue(self.wait_py(lambda: self.store.get("N").title == "Новое имя"))
        self.store.get("N").title = "Без кода"
        self.app.touch(self.store.get("N"))

    def test_context_menu_flat(self):
        self.js("document.querySelector('#lessonList .lrow[data-id=T1]').dispatchEvent("
                "new MouseEvent('contextmenu', {bubbles: true, clientX: 300, clientY: 300}))")
        self.assertTrue(self.wait_js("!!document.querySelector('.pop .menu')"))
        items = self.js("[...document.querySelectorAll('.pop .menu .mi .ml')].map(e => e.textContent)")
        for x in ("Открыть", "Переименовать", "Дублировать", "Удалить…"):
            self.assertIn(x, items)
        self.assertEqual(self.js("document.querySelectorAll('.pop .menu .menu').length"), 0)   # без подменю
        self.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
        self.js("document.querySelector('#plansGrid .pcard[data-id=P]').dispatchEvent("
                "new MouseEvent('contextmenu', {bubbles: true, clientX: 300, clientY: 300}))")
        self.assertTrue(self.wait_js("!!document.querySelector('.pop .menu')"))
        items = self.js("[...document.querySelectorAll('.pop .menu .mi .ml')].map(e => e.textContent)")
        self.assertEqual(items[0], "Новый урок по плану")
        self.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")

    def test_new_topic_from_plan_card(self):
        n = len(self.store.topics_of("P"))
        self.click("#plansGrid .pcard[data-id=P] .newtopic")
        self.assertTrue(self.wait_py(lambda: len(self.store.topics_of("P")) == n + 1))
        t = self.store.topics_of("P")[-1]
        self.app.delete_lesson(t)
        self.go("#/lessons", "lessons")

    def test_delete_asks_and_deletes(self):
        d = self.app.duplicate(self.store.get("N"))
        self.assertTrue(self.wait_js(f"!!document.querySelector('#lessonList .lrow[data-id=\"{d.id}\"]')"))
        self.js(f"document.querySelector('#lessonList .lrow[data-id=\"{d.id}\"]').dispatchEvent("
                "new MouseEvent('contextmenu', {bubbles: true, clientX: 300, clientY: 300}))")
        self.js("[...document.querySelectorAll('.pop .menu .mi')].find(b => b.textContent.includes('Удалить')).click()")
        self.assertTrue(self.wait_js("!!document.querySelector('.sheet')"))
        self.assertIn("templates.json.bak", self.js("document.querySelector('.sheet').textContent"))
        self.js("[...document.querySelectorAll('.sheet .btn')].find(b => b.textContent === 'Удалить').click()")
        self.assertTrue(self.wait_py(lambda: self.store.get(d.id) is None))

    def test_continue_card_and_live(self):
        self.app.settings.page_lesson = "F"
        self.app.publish_now()
        self.assertTrue(self.wait_js("document.querySelector('#continueCard') && document.querySelector('#continueCard').textContent.includes('Свободный')"))
        self.go_live(1, tid="F")
        try:
            self.assertTrue(self.wait_js("document.querySelector('#continueCard').textContent.includes('Идёт урок')"))
            self.assertIn("Вернуться к уроку", self.js("document.querySelector('#continueCard').textContent"))
            self.assertTrue(self.js("!!document.querySelector('#lessonList .lrow[data-id=F] .livemark')"))
        finally:
            self.stop_live()

    def test_drop_imports_md(self):
        f = Path(tempfile.mkdtemp()) / "Перетащенный.md"
        f.write_text("# Перетащенный\n\nТекст.\n\n```python\nprint(1)\n```\n", encoding="utf-8")
        n = len(self.store.templates)
        opened = []
        self.app.navigate.connect(opened.append)
        try:
            self.app.drop([str(f)])
            self.assertTrue(self.wait_py(lambda: len(self.store.templates) == n + 1, 8))
            t = next(x for x in self.store.templates if x.title == "Перетащенный")
            self.assertTrue(self.wait_py(lambda: f"#/lesson/{t.id}" in opened))
        finally:
            self.app.navigate.disconnect(opened.append)
        self.app.delete_lesson(t)
        self.go("#/lessons", "lessons")

    def test_presentation_refused_while_live(self):
        f = Path(tempfile.mkdtemp()) / "слайды.pdf"
        f.write_bytes(b"%PDF-1.4\n%%EOF\n")
        self.go_live(1, tid="F")
        try:
            r = self.app.import_paths([str(f)])
            self.assertEqual(r["added"], [])
            self.assertIn("идёт эфир — презентацию импортируйте после него", " ".join(r["errors"]))
        finally:
            self.stop_live()

    def test_new_lesson_button_goes_wizard(self):
        self.click("#newLessonBtn")
        self.assertTrue(self.wait_js("location.hash === '#/new'"))
        self.go("#/lessons", "lessons")


if __name__ == "__main__":
    unittest.main(verbosity=2)
