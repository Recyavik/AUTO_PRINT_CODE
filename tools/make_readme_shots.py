"""Снимки для README (docs/images/): экран урока в Edge без окна, окно программы и таймер — в памяти.

    python tools/make_readme_shots.py

На экране ничего не появляется: Qt рисует вне экрана (tests/quiet.py), Edge запускается с --headless=new
и своим временным профилем и закрывается по своему pid. Данные — временная папка с образцовым уроком.
"""
from __future__ import annotations

import base64
import sys
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))
import quiet  # noqa: E402,F401  — до PySide6: offscreen, временная папка данных

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
quiet.patch()
from autoprint.ui.theme import theme  # noqa: E402

theme.setup(app, "dark")
from autoprint.samples_lesson import lesson_sample  # noqa: E402
from autoprint.storage import Settings, TemplateStore  # noqa: E402
from autoprint.ui.main_window import MainWindow  # noqa: E402
from cdp import Edge  # noqa: E402

OUT = ROOT / "docs" / "images"
W, H = 1360, 860


def pump(ms: int = 40) -> None:
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.003)


def main() -> int:
    store = TemplateStore()
    t = lesson_sample()
    store.templates = [t]
    store.save()
    s = Settings()
    s.efir_port = 18994
    s.samples_seen = ["steps_v1", "tour_v1", "lesson_v1", "lesson_v2"]
    s.migrations = ["tray_v1", "window_v10", "roles_v10", "samples_v10"]
    s.update_auto_check = False
    win = MainWindow(s, store)
    win.resize(520, 480)
    win.show()
    pump(300)
    win.grab().save(str(OUT / "window-dark.png"))
    print("снимок", OUT / "window-dark.png")
    win.open_settings("print")
    sw = win.settings_win
    sw.resize(1000, 720)
    pump(400)
    sw.grab().save(str(OUT / "settings-print.png"))
    print("снимок", OUT / "settings-print.png")
    sw.close()
    pump(100)

    win.printer.set_focus(t.id)
    win.printer.arm(t.next_code().id)
    win.efir.ensure_server()
    win.lesson.publish()
    e = Edge.start(f"http://127.0.0.1:{win.efir.server.port}/lesson", pump=app.processEvents, width=W, height=H)
    try:
        if not e.wait("window.__ready === true", 20):
            print("страница не загрузилась")
            return 1

        def shot(name: str, clip: dict | None = None) -> None:
            pump(500)
            params = {"format": "png"}
            if clip:
                params["clip"] = dict(clip, scale=1)
            data = e.call("Page.captureScreenshot", params)["data"]
            (OUT / name).write_bytes(base64.b64decode(data))
            print("снимок", OUT / name)

        def mode(m: str) -> None:
            e.eval(f"document.querySelector('.seg.modes button:{'first' if m == 'prep' else 'last'}-child').click()")
            pump(400)

        # Подготовка: заметки и код рядом, правка на месте
        mode("prep")
        y = e.eval("(() => { const b = [...document.querySelectorAll('.blk[data-type=code]')][1];"
                   " return b.getBoundingClientRect().top + scrollY - 330; })()")
        e.eval(f"window.scrollTo(0, {int(y)})")
        shot("lesson-prep.png")

        # Урок идёт: третий этап — текущий, пройденные свёрнуты
        win.lesson._start_stage_now(t, 2)
        live = win.efir.store.live
        win.efir.store.set_live(live.webinar_id, live.anchor - timedelta(minutes=2))
        win.efir.live_changed.emit()
        mode("lesson")
        to_current = ("(() => { const s = document.querySelector('.stage.current');"
                      " window.scrollTo(0, s ? s.getBoundingClientRect().top + scrollY - 250 : 0); })()")
        e.eval(to_current)
        shot("lesson-dark.png")

        # «Печать ⚙»: меню печати
        e.eval("[...document.querySelectorAll('#tools button')].find((b) => b.textContent.trim() === 'Печать').click()")
        pump(300)
        r = e.eval("(() => { const m = document.querySelector('.menu'); const r = m.getBoundingClientRect();"
                   " return {x: r.left, y: r.top, w: r.width, h: r.height}; })()")
        shot("print-menu.png", {"x": max(0, r["x"] - 16), "y": max(0, r["y"] - 16),
                                "width": r["w"] + 32, "height": r["h"] + 32})
        e.key("Escape", "Escape", 27)
        e.eval("document.body.click()")

        tw = win.efir.timer_window
        if tw is not None:
            tw.resize(520, 400)
            pump(300)
            tw.grab().save(str(OUT / "timer.png"))
            print("снимок", OUT / "timer.png")

        theme.set_mode("light")
        pump(900)
        e.eval(to_current)
        shot("lesson-light.png")
        errs = e.errors()
        if errs:
            print("ошибки страницы:", errs)
    finally:
        e.close()
        if win.efir.timer_window is not None:
            win.efir.timer_window.close_silently()
        win.efir.shutdown()
        win._quitting = True
        win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
