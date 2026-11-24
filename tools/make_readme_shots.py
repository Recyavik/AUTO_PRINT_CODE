"""Снимки для README (docs/images/): окно программы — его страница /app в Edge без окна, на временных данных с
образцовым уроком и планом.

    python tools/make_readme_shots.py

На экране ничего не появляется: Qt — вне экрана (tests/quiet.py), Edge запускается с --headless=new и своим
временным профилем и закрывается по своему pid. Снимки — в обеих темах там, где README показывает обе.
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

OUT = ROOT / "docs" / "images"
W, H = 1360, 860
PORT = 18993


def lessons() -> list[Template]:
    t = lesson_sample()
    p = plan_sample()
    more = [Template("Циклы for и while", [stage("Повторение", 5), note("Что такое цикл?", role="ask"),
                                           code("for i in range(3):\n    print(i)"), stage("Практика", 25)]),
            Template("Функции", [stage("Разминка", 10), note("Функция — именованный кусок кода"), stage("Практика", 30)]),
            Template("Списки и словари", [stage("Начало", 10), code("d = {'a': 1}\nprint(d['a'])"), stage("Задачи", 30)])]
    return [p, t, *more]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    templates = lessons()
    win = make_app(templates, PORT)
    s = win.settings
    t = templates[1]
    ef = win.efir
    ef.ensure_server()
    ef.store.add([Webinar(title="Вебинар «Python с нуля»", start="19:00", schedule=[
        Activity("Приветствие", 5), Activity("Теория", 25), Activity("Зарядка для глаз", 5, kind="exercise", demo="off"),
        Activity("Перерыв", 10, kind="break", demo="none"), Activity("Практика", 35), Activity("Вопросы", 10, demo="off")])])
    win.publish_now()
    e = Edge.start(f"http://127.0.0.1:{ef.server.port}/app#/lessons", pump=apphelp.app.processEvents, width=W, height=H)
    try:
        if not e.wait("window.__ready === true", 20):
            print("страница не загрузилась")
            return 1

        def shot(name: str, wait: int = 700) -> None:
            pump(wait)
            data = e.call("Page.captureScreenshot", {"format": "png"})["data"]
            (OUT / name).write_bytes(base64.b64decode(data))
            print("снимок", OUT / name)

        def go(hash_: str, wait: int = 500) -> None:
            e.eval(f"location.hash = {hash_!r}; true")
            pump(wait)

        def theme(mode: str) -> None:
            s.theme = mode
            win.on_setting_changed("theme")
            win.publish_now()
            pump(500)

        theme("dark")
        shot("library-dark.png")
        go("#/new")
        shot("new-lesson.png")
        go("#/efir")
        shot("efir.png")
        for sec in ("typing", "ai", "sound"):
            go(f"#/settings/{sec}")
            shot(f"settings-{sec}.png")
        win.open_report()
        pump(1200)
        shot("report.png")
        e.eval("document.querySelectorAll('.scrim').forEach(s => s.remove()); true")

        # подготовка: правка заметки «как в Word»
        win.open_lesson(t.id, ask=False)
        win.lesson.publish()
        win.publish_now()
        go(f"#/lesson/{t.id}", 900)
        e.eval("(() => { if (!document.body.classList.contains('editing')) document.querySelector('#editToggle').click(); })()")
        pump(400)
        ok = e.eval("(() => { const c = [...document.querySelectorAll('#main .blk[data-id] .row > .c')]"
                    ".find(x => x.closest('.blk').querySelector('.r-tell')); if (!c) return false;"
                    " c.closest('.blk').scrollIntoView({block: 'center'}); c.click(); return true; })()")
        if not ok:
            print("заметка «Расскажи» не нашлась")
        shot("lesson-prep.png")
        e.eval("document.activeElement && document.activeElement.blur(); true")

        # урок идёт: третий этап — текущий
        win.lesson._start_stage_now(t, 2)
        live = ef.store.live
        ef.store.set_live(live.webinar_id, live.anchor - timedelta(minutes=2))
        ef.live_changed.emit()
        win.lesson.publish()
        win.publish_now()
        pump(900)
        e.eval("(() => { const s = document.querySelector('.stage.current'); if (s) s.scrollIntoView({block: 'start'}); })()")
        shot("lesson-dark.png")
        theme("light")
        shot("lesson-light.png")
        theme("dark")

        # маленький режим: то же окно поверх всех, раскладка по размеру
        win.set_compact(True)
        win.publish_now()
        e.call("Emulation.setDeviceMetricsOverride", {"width": 380, "height": 520, "deviceScaleFactor": 1, "mobile": False})
        shot("compact.png", 900)
        e.call("Emulation.clearDeviceMetricsOverride", {})
        win.set_compact(False)
        errs = e.errors()
        if errs:
            print("ошибки страницы:", errs)
    finally:
        e.close()
        ef.stop_live()
        win._quitting = True
        win.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
