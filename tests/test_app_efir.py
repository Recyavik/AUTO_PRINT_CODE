"""«Эфир» в окне программы: расписания (список, повестка, «Запустить», «Новый эфир», правка), оформления (фон, зарядки,
перерыв; «есть изменения»; удалить нельзя, пока используется; нет файла — «Заменить…»; «Скопировать в программу»),
идущий вебинар (табло, «Завершить эфир»).

    .venv\\Scripts\\python.exe tests\\test_app_efir.py
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from apphelp import AppPage, note, pump, stage  # noqa: F401

from autoprint import storage
from autoprint.efir.model import Activity, Exercise, Look, Webinar
from autoprint.storage import Template

OUT = Path(tempfile.mkdtemp(prefix="autoprint-efir-out-"))


def lessons() -> list[Template]:
    return [Template("Урок с оформлением", [stage("Начало", 5, id="u1"), note("x", id="un")], id="U")]


class EfirPage(AppPage):
    port = 18966
    templates = staticmethod(lessons)
    route = "#/efir"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ef = cls.app.efir
        ef.store.webinars.clear()
        ef.store.looks.clear()
        cls.look = Look(title="Синий фон", background="color:#123456")
        ef.save_look(cls.look)
        cls.w1 = ef.store.add([Webinar(title="Пара 1Т", start="09:15", look_id=cls.look.id, schedule=[
            Activity("Приветствие", 5), Activity("Теория", 20, demo="on"), Activity("Перерыв", 10, kind="break", demo="none"),
            Activity("Практика", 30, demo="off")])])[0]
        cls.w2 = ef.store.add([Webinar(title="Пара 2Т", start="12:00", look_id=cls.look.id, schedule=[Activity("Одна", 45)])])[0]
        ef.store.imported_legacy = True

    def setUp(self):
        if self.app.efir.live_webinar() is not None:
            self.stop_live()
        self.app.publish_now()
        self.go("#/lessons", "lessons")

    def tearDown(self):
        self.js("window.appUI.closePop(); document.querySelectorAll('.scrim').forEach(s => s.remove())")
        if self.app.efir.live_webinar() is not None:
            self.stop_live()
        super().tearDown()

    def patch(self, obj, name, fn):
        old = getattr(obj, name)
        setattr(obj, name, fn)
        self.addCleanup(setattr, obj, name, old)

    def set_value(self, sel, value, ev="input"):
        self.js(f"{{ const e = document.querySelector({sel!r}); e.value = {value!r}; e.dispatchEvent(new Event({ev!r}, {{bubbles: true}})); }}")

    def sheet_answer(self, ok: bool):
        self.assertTrue(self.wait_js("!!document.querySelector('.scrim .sheet')"))
        self.js("{ const b = [...document.querySelectorAll('.scrim .sheet .sfoot button')];"
                f" (b.find(x => x.classList.contains({'primary' if ok else 'ghost'!r}) || ({str(ok).lower()} && x.classList.contains('danger'))) || b[b.length - 1]).click(); }}")

    def menu_click(self, label):
        self.assertTrue(self.wait_js("!!document.querySelector('.pop .menu')"))
        self.js(f"[...document.querySelectorAll('.pop .menu .mi')].find(b => b.textContent.trim().startsWith({label!r})).click()")


class SchedulesTest(EfirPage):
    def test_list_and_detail(self):
        self.go("#/efir", "efir")
        self.assertTrue(self.wait_js("document.querySelectorAll('#wlist .witem').length === 2"))
        self.click(f"#wlist .witem[data-id='{self.w1.id}']")
        self.assertTrue(self.wait_js(f"location.hash === '#/efir/{self.w1.id}' && document.querySelector('#wdetail .wtitle').textContent === 'Пара 1Т'"))
        self.assertEqual(self.js("document.querySelectorAll('#wagenda .arow').length"), 4)
        meta = self.js("document.querySelector('#wdetail .wmeta').textContent")
        for part in ("1 ч 5 мин", "4 блока", "перерыв", "Синий фон"):
            self.assertIn(part, meta)
        self.assertIn("0:25", self.js("document.querySelectorAll('#wagenda .arow')[2].textContent"))      # время от начала
        self.assertTrue(self.js("document.querySelectorAll('#wagenda .arow')[1].querySelector('.demo.on') !== null"))
        self.assertIn("Синий фон", self.js("document.querySelector('#wdetail .wlooks').textContent"))

    def test_launch_panel_times(self):
        self.go(f"#/efir/{self.w1.id}", "efir")
        self.assertTrue(self.wait_js("!!document.querySelector('#launchBtn')"))
        self.click("#launchBtn")
        self.assertTrue(self.wait_js("!!document.querySelector('.launchpanel')"))
        self.assertEqual(self.js("document.querySelector('.launchpanel .lnow').textContent.trim()"), "Сейчас")
        slots = self.js("[...document.querySelectorAll('.launchpanel .lslot')].map(b => b.textContent.trim())")
        self.assertEqual(len(slots), 2)
        for s in slots:
            self.assertRegex(s, r"^\d{1,2}:(00|30)$")
        self.assertIn("09:15", self.js("document.querySelector('.launchpanel .lpast').textContent"))
        self.click(".launchpanel .lnow")
        self.assertTrue(self.wait_py(lambda: (self.app.efir.live_webinar() or Webinar()).id == self.w1.id))
        self.assertTrue(self.wait_js("location.hash === '#/efir/live'"))

    def test_launch_replaces_live_only_after_question(self):
        self.app.efir.launch(self.w2.id, "")
        self.app.publish_now()
        self.go(f"#/efir/{self.w1.id}", "efir")
        self.assertTrue(self.wait_js("!!document.querySelector('#launchBtn')"))
        self.click("#launchBtn")
        self.click(".launchpanel .lnow")
        self.assertTrue(self.wait_js("!!document.querySelector('.scrim .sheet') && document.querySelector('.scrim .sheet').textContent.includes('Пара 2Т')"))
        self.sheet_answer(False)
        pump(300)
        self.assertEqual(self.app.efir.live_webinar().id, self.w2.id)

    def test_new_empty_and_paste_json(self):
        n0 = len(self.app.efir.store.visible())
        self.go("#/efir/new", "efir")
        self.assertTrue(self.wait_js("!!document.querySelector('#wnew .newopt[data-how=empty]')"))
        self.click("#wnew .newopt[data-how=empty]")
        self.assertTrue(self.wait_py(lambda: len(self.app.efir.store.visible()) == n0 + 1))
        new = self.app.efir.store.visible()[-1]
        self.assertTrue(self.wait_js(f"location.hash === '#/efir/{new.id}/edit'"))
        self.app.efir.delete_webinar(new.id)
        self.app.publish_now()
        self.go("#/efir/new", "efir")
        self.click("#wnew .newopt[data-how=paste]")
        self.assertTrue(self.wait_js("!!document.querySelector('#newPaste')"))
        self.set_value("#newPaste", 'Ответ:\n{"title": "ИИ", "schedule": [{"name": "А", "min": 3}]}')
        self.click("#newPasteGo")
        self.assertTrue(self.wait_py(lambda: any(w.title == "ИИ" for w in self.app.efir.store.visible())))
        self.app.efir.delete_webinar(next(w for w in self.app.efir.store.visible() if w.title == "ИИ").id)

    def test_new_by_description_ai(self):
        from autoprint import ai
        s = self.app.settings
        s.ai_provider, s.ai_urls["custom"], s.ai_models["custom"] = "custom", "http://127.0.0.1:9", "m"
        self.addCleanup(setattr, s, "ai_provider", "")
        answer = '```json\n{"title": "Пара ИИ", "start": "12:00", "schedule": [{"name": "Теория", "min": 20}, {"name": "Перерыв", "min": 10}]}\n```'
        self.patch(ai, "ask", lambda settings, system, user, cancel=None, **k: (answer, "Тест"))
        self.app.publish_now()
        self.go("#/efir/new", "efir")
        self.click("#wnew .newopt[data-how=ai]")
        self.set_value("#newDesc", "теория 20, перерыв 10")
        self.click("#newAiGo")
        self.assertTrue(self.wait_py(lambda: any(w.title == "Пара ИИ" for w in self.app.efir.store.visible()), 8))
        w = next(x for x in self.app.efir.store.visible() if x.title == "Пара ИИ")
        self.assertEqual([a.kind for a in w.schedule], ["", "break"])
        self.app.efir.delete_webinar(w.id)

    def test_edit_kind_guess_until_manual(self):
        self.go(f"#/efir/{self.w2.id}/edit", "efir")
        self.assertTrue(self.wait_js("document.querySelectorAll('#wrows .wrow').length === 1"))
        self.click("#addBlock")
        self.assertTrue(self.wait_js("document.querySelectorAll('#wrows .wrow').length === 2"))
        last = "#wrows .wrow:last-child"
        self.set_value(f"{last} .rn", "Перерыв")
        self.assertEqual(self.js(f"document.querySelector('{last} .rk').value"), "break")
        self.set_value(f"{last} .rk", "", "change")                 # вид выбран руками — больше не угадывается
        self.set_value(f"{last} .rn", "Зарядка для глаз")
        self.assertEqual(self.js(f"document.querySelector('{last} .rk').value"), "")
        self.set_value(f"{last} .rm", "7")
        self.click("#wsave")
        self.assertTrue(self.wait_py(lambda: len(self.app.efir.store.get(self.w2.id).schedule) == 2))
        a = self.app.efir.store.get(self.w2.id).schedule[1]
        self.assertEqual((a.name, a.kind, a.min), ("Зарядка для глаз", "", 7))
        w = self.app.efir.store.get(self.w2.id)
        w.schedule = w.schedule[:1]
        self.app.efir.store.put(w)
        self.app.publish_now()

    def test_min_one_block(self):
        self.go(f"#/efir/{self.w2.id}/edit", "efir")
        self.assertTrue(self.wait_js("document.querySelectorAll('#wrows .wrow').length === 1"))
        self.assertTrue(self.js("document.querySelector('#wrows .wrow .del').disabled"))

    def test_unsaved_leave_asks(self):
        self.go(f"#/efir/{self.w2.id}/edit", "efir")
        self.assertTrue(self.wait_js("!!document.querySelector('#wtitle')"))
        self.set_value("#wtitle", "Пара 2Т — правка")
        self.js("location.hash = '#/lessons'")
        self.assertTrue(self.wait_js("!!document.querySelector('.scrim .sheet') && document.querySelector('.scrim .sheet').textContent.includes('не сохранены')"))
        self.sheet_answer(False)                                  # остаться
        self.assertTrue(self.wait_js(f"location.hash === '#/efir/{self.w2.id}/edit' && document.querySelector('#wtitle').value === 'Пара 2Т — правка'"))
        self.js("location.hash = '#/lessons'")
        self.sheet_answer(True)                                   # уйти без сохранения
        self.assertTrue(self.wait_js("document.body.dataset.view === 'lessons'"))
        self.assertEqual(self.app.efir.store.get(self.w2.id).title, "Пара 2Т")

    def test_menu_copy_and_delete(self):
        self.go(f"#/efir/{self.w2.id}", "efir")
        self.assertTrue(self.wait_js("!!document.querySelector('#wmenuBtn')"))
        n0 = len(self.app.efir.store.visible())
        self.click("#wmenuBtn")
        self.menu_click("Сделать копию")
        self.assertTrue(self.wait_py(lambda: len(self.app.efir.store.visible()) == n0 + 1))
        c = self.app.efir.store.visible()[-1]
        self.go(f"#/efir/{c.id}", "efir")
        self.assertTrue(self.wait_js("!!document.querySelector('#wmenuBtn')"))
        self.click("#wmenuBtn")
        self.menu_click("Удалить")
        self.sheet_answer(True)
        self.assertTrue(self.wait_py(lambda: self.app.efir.store.get(c.id) is None))


class LooksTest(EfirPage):
    port = 18965

    def test_look_change_marks_dirty(self):
        self.go(f"#/efir/looks/{self.look.id}", "efir")
        self.assertTrue(self.wait_js("!!document.querySelector('#lookedit')"))
        self.assertTrue(self.js("document.querySelector('#lkdirty').hidden"))
        self.click("#lkbg .bgopt[data-value='anim:pipes']")
        self.assertTrue(self.wait_js("!document.querySelector('#lkdirty').hidden"))     # регресс: смена фона — «есть изменения»
        self.click("#lksave")
        self.assertTrue(self.wait_py(lambda: self.app.efir.store.look(self.look.id).background == "anim:pipes"))
        self.assertTrue(self.wait_js("document.querySelector('#lkdirty').hidden"))
        lk = self.app.efir.store.look(self.look.id)
        lk.background = "color:#123456"
        self.app.efir.save_look(lk)

    def test_font_and_color_mark_dirty(self):
        self.go(f"#/efir/looks/{self.look.id}", "efir")
        self.assertTrue(self.wait_js("!!document.querySelector('#lkfont')"))
        self.set_value("#lkfont", "Oswald", "change")
        self.assertTrue(self.wait_js("!document.querySelector('#lkdirty').hidden"))
        self.click("#lkcancel")
        self.assertTrue(self.wait_js("document.querySelector('#lkdirty').hidden"))

    def test_look_delete_blocked_when_used(self):
        self.go(f"#/efir/looks/{self.look.id}", "efir")
        self.assertTrue(self.wait_js("!!document.querySelector('#lkdelete')"))
        self.assertTrue(self.js("document.querySelector('#lkdelete').disabled"))
        self.assertIn("Пара 1Т", self.js("document.querySelector('#lookedit .lkusers').textContent"))

    def test_missing_file_mark_and_replace(self):
        ef = self.app.efir
        lk = Look(title="С видео", exercises=[Exercise("Глаза", str(OUT / "нет-видео.mp4"))])
        ef.save_look(lk)
        newv = OUT / "глаза-новое.mp4"
        newv.write_bytes(b"V" * 64)
        self.patch(self.app.commands, "call_pick_files", lambda d: [str(newv)])
        self.app.publish_now()
        self.go(f"#/efir/looks/{lk.id}", "efir")
        self.assertTrue(self.wait_js("!!document.querySelector('#lkex .exrow .exmissing')"))
        self.assertIn("Файл удалён или перемещён", self.js("document.querySelector('#lkex .exrow').textContent"))
        self.click("#lkex .exrow .exreplace")
        self.assertTrue(self.wait_js("!document.querySelector('#lkex .exrow .exmissing') && !document.querySelector('#lkdirty').hidden"))
        self.click("#lksave")
        self.assertTrue(self.wait_py(lambda: Path(ef.store.look(lk.id).exercises[0].path).is_file()))
        self.assertEqual(Path(ef.store.look(lk.id).exercises[0].path).parent, storage.DATA_DIR / storage.MEDIA_FOLDER)  # копия в программе
        ef.delete_look(lk.id)

    def test_copy_to_program_button(self):
        ef = self.app.efir
        img = OUT / "фон-снаружи.png"
        img.write_bytes(b"\x89PNG" + b"0" * 2000)
        lk = Look(title="Снаружи", background="image:" + str(img))
        ef.save_look(lk)
        self.app.publish_now()
        self.go(f"#/efir/looks/{lk.id}", "efir")
        self.assertTrue(self.wait_js("!!document.querySelector('#lkoutside') && !document.querySelector('#lkoutside').hidden"))
        self.assertIn("Файлы снаружи программы", self.js("document.querySelector('#lkoutside').textContent"))
        self.click("#lkcopy")
        self.assertTrue(self.wait_py(lambda: ef.store.look(lk.id).background != "image:" + str(img), 8))
        p = Path(ef.store.look(lk.id).background[6:])
        self.assertEqual(p.parent, storage.DATA_DIR / storage.MEDIA_FOLDER)
        self.assertTrue(img.exists())
        ef.delete_look(lk.id)

    def test_new_look_and_list(self):
        n0 = len(self.app.efir.store.looks)
        self.go("#/efir/looks", "efir")
        self.assertTrue(self.wait_js("document.querySelectorAll('#looklist .lkitem').length >= 1"))
        self.click("#efirNew")
        self.assertTrue(self.wait_js("location.hash === '#/efir/looks/new' && !!document.querySelector('#lktitle')"))
        self.set_value("#lktitle", "Зелёное")
        self.click("#lksave")
        self.assertTrue(self.wait_py(lambda: len(self.app.efir.store.looks) == n0 + 1))
        lk = next(x for x in self.app.efir.store.looks if x.title == "Зелёное")
        self.assertTrue(self.wait_js(f"location.hash === '#/efir/looks/{lk.id}'"))
        self.click("#lkdelete")
        self.sheet_answer(True)
        self.assertTrue(self.wait_py(lambda: self.app.efir.store.look(lk.id) is None))

    def test_lesson_strip_look_edit_navigates(self):
        self.app.printer.set_focus("U")
        self.store.get("U").look = self.look.id
        self.app.lesson.command({"cmd": "look_edit"})
        self.assertTrue(self.wait_js(f"location.hash === '#/efir/looks/{self.look.id}'"))


class LiveTest(EfirPage):
    port = 18964

    def test_live_webinar_board(self):
        self.app.efir.launch(self.w1.id, "")
        self.app.publish_now()
        self.go("#/efir/live", "efir")
        self.assertTrue(self.wait_js("!!document.querySelector('#efirLive') && document.querySelector('#efirLive').textContent.includes('Приветствие')", 6))
        text = self.js("document.querySelector('#efirLive').textContent")
        self.assertIn("Дальше", text)
        self.assertIn("Теория", text)
        self.assertEqual(self.js("document.querySelectorAll('#liveAgenda .la-row').length"), 4)
        self.assertRegex(self.js("document.querySelector('#efirLive .lb-time').textContent"), r"^\d:\d\d$")
        self.click("#liveStatus")
        self.menu_click("Начать с блока")
        self.menu_click("Практика")
        self.assertTrue(self.wait_py(lambda: self.app.efir.agenda().index == 3))
        self.click("#liveEnd")
        self.sheet_answer(True)
        self.assertTrue(self.wait_py(lambda: self.app.efir.live_webinar() is None))

    def test_live_screen_controls_without_lesson(self):
        """Вебинар без урока: перерыв ученикам — из табло эфира (урок для этого не нужен)."""
        self.app.printer.set_focus("")
        self.app.efir.clients = 1
        self.app.efir.launch(self.w1.id, "")
        self.app.publish_now()
        self.go("#/efir/live", "efir")
        self.assertTrue(self.wait_js("!!document.querySelector('#efirLive .lscr [data-op=break]')", 6))
        self.click("#efirLive .lscr [data-op=break]")
        self.menu_click("5 мин")
        self.assertTrue(self.wait_py(lambda: self.app.efir.mode == "break"))
        self.click("#efirLive .lscr [data-op=background]")
        self.assertTrue(self.wait_py(lambda: self.app.efir.mode == "idle"))


class OldWindowsRemovedTest(unittest.TestCase):
    def test_efir_windows_removed(self):
        ui = Path(storage.__file__).parent / "ui"
        for name in ("efir_window.py", "efir_editor.py", "efir_start.py", "efir_timer.py"):
            self.assertFalse((ui / name).exists(), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
