"""Снимки всех экранов окна программы (headless Edge, без окон на экране): build/screens/<экран>-<тема>[-150].png.

    .venv\\Scripts\\python.exe tools\\screens.py [экран ...] [--out папка] [--themes dark,light] [--no-zoom]

Без аргументов — все экраны (SCENES) в обеих темах; экраны из ZOOMED — ещё и при масштабе 150 %. Данные — временные:
образцовый урок и план, несколько уроков, вебинар. Микрофон, печать и браузер не задействуются (печать на снимке
«набор» — подставное состояние), рабочая data/ не трогается.
"""
from __future__ import annotations

import base64
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))
import apphelp  # noqa: E402  — до PySide6: offscreen, временная папка данных
from apphelp import code, make_app, note, pump, stage  # noqa: E402

from autoprint.efir.model import Activity, Webinar  # noqa: E402
from autoprint.samples_lesson import lesson_sample, plan_sample  # noqa: E402
from autoprint.storage import Template  # noqa: E402
from cdp import Edge  # noqa: E402

W, H = 1360, 860
PORT = 18999
ZOOMED = {"lessons", "wizard-1", "wizard-2", "lesson-prep", "lesson-live", "compact-side", "compact-tall",
          "settings-typing", "settings-ai", "efir-live", "sheet-report"}


def data() -> list[Template]:
    t = lesson_sample()
    p = plan_sample()
    more = [Template("Циклы for и while — очень длинное название урока, чтобы проверить обрезку в списке и в шапке",
                     [stage("Повторение", 5), note("Что такое цикл?", role="ask"),
                      code("for i in range(3):\n    print(i)"), stage("Практика", 25)]),
            Template("Функции", [stage("Разминка", 10), note("Функция — именованный кусок кода"), stage("Практика", 30)])]
    return [p, t, *more]


class Shots:
    def __init__(self, out: Path, themes: list[str], zoom: bool) -> None:
        self.out, self.themes, self.zoom = out, themes, zoom
        self.templates = data()
        self.t = self.templates[1]
        self.plan = self.templates[0]
        self.app = make_app(self.templates, PORT)
        ef = self.app.efir
        ef.ensure_server()
        self.web = ef.store.add([Webinar(title="Вебинар «Python с нуля»", start="19:00", schedule=[
            Activity("Приветствие", 5), Activity("Теория", 25), Activity("Зарядка для глаз", 5, kind="exercise", demo="off"),
            Activity("Перерыв", 10, kind="break", demo="none"), Activity("Практика", 35),
            Activity("Вопросы", 10, demo="off")])])[0]
        self.app.publish_now()
        self.e = Edge.start(f"http://127.0.0.1:{ef.server.port}/app#/lessons", pump=apphelp.app.processEvents, width=W, height=H)
        if not self.e.wait("window.__ready === true", 20):
            raise SystemExit("страница не загрузилась")
        self.saved: list[Path] = []

    # ------------------------------------------------------------ помощники
    def js(self, code_: str):
        return self.e.eval(code_)

    def go(self, hash_: str, ms: int = 600) -> None:
        self.js(f"location.hash = {hash_!r}; true")
        pump(ms)

    def size(self, w: int, h: int) -> None:
        self.e.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": False})
        pump(300)

    def unsize(self) -> None:
        self.e.call("Emulation.clearDeviceMetricsOverride", {})
        pump(200)

    def set(self, **kw) -> None:
        for k, v in kw.items():
            setattr(self.app.settings, k, v)
            self.app.on_setting_changed(k)
        self.app.lesson.publish()
        self.app.publish_now()
        pump(400)

    def close_sheets(self) -> None:
        self.js("window.appUI && window.appUI.closePop && window.appUI.closePop();"
                " document.querySelectorAll('.scrim').forEach(s => s.remove()); true")
        pump(150)

    def click_text(self, sel: str, text: str) -> bool:
        return bool(self.js(f"(() => {{ const b = [...document.querySelectorAll({sel!r})].find(x => x.textContent.trim().startsWith({text!r}));"
                            f" if (!b) return false; b.click(); return true; }})()"))

    def menu(self, label: str) -> bool:
        self.js("document.querySelector('#lessonMenuBtn') && document.querySelector('#lessonMenuBtn').click(); true")
        pump(300)
        return self.click_text(".pop .menu .mi", label)

    def snap(self, name: str, wait: int = 700) -> None:
        pump(wait)
        for theme in self.themes:
            self.set(theme=theme)
            pump(300)
            self.save(f"{name}-{theme}")
        if self.zoom and name in ZOOMED:
            self.set(theme=self.themes[0], page_zoom=150)
            self.save(f"{name}-{self.themes[0]}-150", wait=500)
            self.set(page_zoom=100)

    def save(self, fname: str, wait: int = 200) -> None:
        pump(wait)
        data_ = self.e.call("Page.captureScreenshot", {"format": "png"})["data"]
        p = self.out / f"{fname}.png"
        p.write_bytes(base64.b64decode(data_))
        self.saved.append(p)

    def open_lesson(self, t: Template) -> None:
        self.app.open_lesson(t.id, ask=False)
        self.app.lesson.publish()
        self.app.publish_now()
        self.go(f"#/lesson/{t.id}", 900)

    def live(self, stage_i: int = 2) -> None:
        a = self.app
        a.lesson._start_stage_now(self.t, stage_i)
        lv = a.efir.store.live
        a.efir.store.set_live(lv.webinar_id, lv.anchor - timedelta(minutes=2))
        a.efir.live_changed.emit()
        a.lesson.publish()
        a.publish_now()
        pump(800)

    # ------------------------------------------------------------ экраны
    def scenes(self) -> dict:
        return {
            "lessons": self.s_lessons, "wizard-1": self.s_wizard1, "wizard-2": self.s_wizard2, "wizard-plan": self.s_wizard_plan,
            "lesson-prep": self.s_prep, "lesson-edit": self.s_edit, "lesson-plan-top": self.s_plan_top,
            "lesson-plan-hidden": self.s_plan_hidden, "lesson-live": self.s_live, "lesson-typing": self.s_typing,
            "compact-tiny": self.s_compact("tiny", 300, 140), "compact-strip": self.s_compact("strip", 1100, 150),
            "compact-side": self.s_compact("side", 720, 420), "compact-tall": self.s_compact("tall", 380, 640),
            "efir": self.s_efir, "efir-edit": self.s_efir_edit, "efir-look": self.s_efir_look, "efir-live": self.s_efir_live,
            **{f"settings-{k}": self.s_settings(k) for k in ("view", "lesson", "typing", "sound", "hotkeys", "behavior", "ai",
                                                           "updates", "about")},
            "sheet-export": self.s_sheet_menu("Экспорт…"), "sheet-print": self.s_sheet_menu("Печать или PDF…"),
            "sheet-plan": self.s_sheet_menu("План урока…"), "sheet-answer": self.s_sheet_menu("Обновить по ответу нейросети…"),
            "sheet-delete": self.s_sheet_menu("Удалить…"), "sheet-update": self.s_update, "sheet-report": self.s_report,
            "sheet-record": self.s_record, "sheet-crash": self.s_crash,
            # 1.1: по отзыву после первого урока на 1.0
            "lesson-slide": self.s_slide, "lesson-break": self.s_break, "lesson-shift": self.s_shift,
            "zoom-panel": self.s_zoom_panel, "compact-menu": self.s_compact_menu, "look-from-lesson": self.s_look_from_lesson,
        }

    def s_slide(self):
        self.s_live()
        self.app.lesson.command({"cmd": "slide_step", "d": 1})
        self.app.lesson.publish()
        pump(600)

    def s_break(self):
        self.s_live()
        self.app.lesson.command({"cmd": "break", "minutes": 10})
        self.app.lesson.publish()
        pump(600)
    s_break.__dict__["after"] = None

    def s_shift(self):
        self.s_live()
        self.app.lesson.command({"cmd": "start_at", "index": 3})
        self.app.lesson.publish()
        pump(600)

    def s_zoom_panel(self):
        self.open_lesson(self.t)
        self.js("document.querySelector('#zoomBtn').click()")

    def s_compact_menu(self):
        self.app.set_compact(True)
        self.app.publish_now()
        self.size(380, 640)
        pump(400)
        self.js("document.querySelector('#compactLayout').click()")
    s_compact_menu.__dict__["after"] = None

    def s_look_from_lesson(self):
        self.open_lesson(self.t)
        self.app.lesson.command({"cmd": "look_edit"})
        pump(900)

    def s_lessons(self):
        self.go("#/lessons")

    def s_wizard1(self):
        self.go("#/new")

    def s_wizard2(self):
        self.go(f"#/new/text?plan={self.plan.id}")

    def s_wizard_plan(self):
        self.go("#/new/plan")

    def s_prep(self):
        self.set(page_plan="side")
        self.open_lesson(self.t)

    def s_edit(self):
        self.open_lesson(self.t)
        self.js("(() => { if (!document.body.classList.contains('editing')) document.querySelector('#editToggle').click(); })()")
        pump(300)
        self.js("(() => { const c = [...document.querySelectorAll('#main .blk[data-id] .row > .c')].find(x => x.closest('.blk').querySelector('.r-ask'));"
                " if (!c) return; c.closest('.blk').scrollIntoView({block: 'center'}); c.click(); })()")

    def s_plan_top(self):
        self.set(page_plan="top")
        self.open_lesson(self.t)

    def s_plan_hidden(self):
        self.set(page_plan="hidden")
        self.open_lesson(self.t)

    def s_live(self):
        self.set(page_plan="side")
        self.open_lesson(self.t)
        self.live()
        self.js("(() => { const s = document.querySelector('.stage.current'); if (s) s.scrollIntoView({block: 'start'}); })()")

    def s_typing(self):
        p = self.app.printer
        real = p.snapshot

        def fake():
            d = real()
            d.update(state="paused", progress=0.42, block=self.t.next_code().id if self.t.next_code() else d["block"])
            return d
        p.snapshot = fake
        self.app.lesson.publish()
        self.app.publish_now()
        self.js("(() => { const b = document.querySelector('.blk[data-type=code]'); if (b) b.scrollIntoView({block: 'center'}); })()")
        self._restore_snapshot = lambda: setattr(p, "snapshot", real)

    def s_compact(self, kind: str, w: int, h: int):
        def run():
            self.app.set_compact(True)
            self.app.publish_now()
            self.size(w, h)
        run.after = lambda: (self.unsize(), self.app.set_compact(False))
        return run

    def s_efir(self):
        self.app.efir.stop_live()
        self.app.publish_now()
        self.go(f"#/efir/{self.web.id}")

    def s_efir_edit(self):
        self.go(f"#/efir/{self.web.id}/edit")

    def s_efir_look(self):
        looks = self.app.efir.store.looks
        if looks:
            self.go(f"#/efir/looks/{looks[0].id}")

    def s_efir_live(self):
        self.app.efir.launch(self.web.id, "")
        self.app.publish_now()
        self.go("#/efir/live", 900)

    def s_settings(self, sec: str):
        return lambda: self.go(f"#/settings/{sec}")

    def s_sheet_menu(self, label: str):
        def run():
            if not self.js("location.hash").startswith(f"#/lesson/{self.t.id}"):
                self.open_lesson(self.t)
            if not self.menu(label):
                print("пункт меню не найден:", label)
        run.after = self.close_sheets
        return run

    def s_update(self):
        from autoprint.updater import Release
        up = self.app.updates
        up.latest = Release("1.1.0", "v1.1.0", "AutoPrintCode 1.1", "## Что нового\n\n- Быстрее печать\n- Новые фоны", "https://example.org",
                            "", "2026-12-01")
        up.installable = lambda r: True
        self.app.open_update_dialog()
    s_update.__dict__["after"] = None

    def s_report(self):
        self.app.open_report()
        pump(800)

    def s_record(self):
        import test_record_flow as T
        from autoprint import record_flow
        record_flow.make_recorder = lambda parent=None: T.FakeRecorder(parent)
        self.app.open_record()

    def s_crash(self):
        self.app.show_crash("KeyError: 'stage'")

    def run(self, only: list[str]) -> None:
        scenes = self.scenes()
        for name, fn in scenes.items():
            if only and name not in only:
                continue
            try:
                fn()
                self.snap(name)
            except Exception as ex:  # один экран не должен ронять остальные
                print("не снято:", name, ex)
            after = getattr(fn, "after", None)
            if after:
                after()
            if name.startswith("sheet-"):
                self.close_sheets()
                if name == "sheet-record":
                    self.app.close_record()
            if name == "lesson-typing" and getattr(self, "_restore_snapshot", None):
                self._restore_snapshot()
            if name in ("lesson-slide", "lesson-break"):
                self.app.efir.show_background()
            if name in ("zoom-panel", "compact-menu"):
                self.js("window.appUI && window.appUI.closePop()")
            if name == "compact-menu":
                self.unsize()
                self.app.set_compact(False)
            if name == "efir-live":               # дальше — без идущего эфира («Эфир ● идёт» в меню слева)
                self.app.efir.stop_live()
                self.app.publish_now()
        errs = self.e.errors()
        if errs:
            print("ошибки страницы:", errs)

    def close(self) -> None:
        self.e.close()
        self.app.efir.stop_live()
        self.app._quitting = True
        self.app.shutdown()


def main() -> int:
    args = sys.argv[1:]
    out = ROOT / "build" / "screens"
    themes = ["dark", "light"]
    zoom = "--no-zoom" not in args
    args = [a for a in args if a != "--no-zoom"]
    if "--out" in args:
        i = args.index("--out")
        out = Path(args[i + 1])
        del args[i:i + 2]
    if "--themes" in args:
        i = args.index("--themes")
        themes = args[i + 1].split(",")
        del args[i:i + 2]
    out.mkdir(parents=True, exist_ok=True)
    s = Shots(out, themes, zoom)
    try:
        s.run(args)
    finally:
        s.close()
    print(f"снимков: {len(s.saved)} → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
