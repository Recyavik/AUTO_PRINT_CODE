"""Проверка интерфейса без участия человека: собирает главное окно и окно настроек в обеих темах
на временной папке данных и сохраняет снимки.

    python tests/ui_smoke.py <папка для снимков>

Тихий режим (tests/quiet.py): окна рисуются в памяти, без трея и уведомлений. Рабочая папка data/ не используется.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["AUTOPRINT_DATA"] = tempfile.mkdtemp(prefix="autoprint-ui-")
import quiet  # noqa: E402,F401 — окна только в памяти, без трея и уведомлений

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="autoprint-shots-"))
OUT.mkdir(parents=True, exist_ok=True)


def settle(app: QApplication, n: int = 6) -> None:
    for _ in range(n):
        app.processEvents()


def shot(w, name: str) -> None:
    QApplication.processEvents()
    w.grab().save(str(OUT / f"{name}.png"))
    print("снимок:", OUT / f"{name}.png")


def main() -> int:
    app = QApplication(sys.argv)
    quiet.patch()
    from autoprint.storage import Settings, TemplateStore
    from autoprint.typer import RUNNING
    from autoprint.ui.main_window import MainWindow
    from autoprint.ui.settings_window import PAGES
    from autoprint.ui.theme import theme

    settings = Settings()
    theme.setup(app, "dark")
    store = TemplateStore()
    win = MainWindow(settings, store)
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    win.show()
    settle(app)
    shot(win, "main-dark")

    # печать «идёт»: строка печати внизу окна
    t = store.templates[0]
    win.printer.set_focus(t.id)
    first = t.next_code()
    assert first, "в примере должен быть код"
    win.printer.arm(first.id)
    job = win.printer.job_for_armed()
    win.printer.job = job
    win.printer.target = "VS Code"
    win.printer._last_pos = len(job["text"]) // 3
    win.engine.state = RUNNING
    win.print_bar.refresh()
    settle(app)
    assert win.print_bar.isVisible(), "строка печати не видна"
    shot(win, "main-dark-running")
    win.printer.job = None
    win.engine.state = "idle"
    win.print_bar.refresh()

    settings.theme = "light"
    theme.set_mode("light")
    settle(app)
    shot(win, "main-light")
    win.resize(420, 520)
    settle(app)
    shot(win, "main-light-small")
    win.resize(520, 720)

    settings.theme = "dark"
    theme.set_mode("dark")
    win.open_settings()
    sw = win.settings_win
    sw.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    sw.show()
    settle(app)
    for key, _ic, _t in PAGES:
        sw.show_page(key)
        settle(app)
        shot(sw, f"settings-{key}-dark")
    settings.theme = "light"
    theme.set_mode("light")
    sw.show_page("human")
    settle(app)
    shot(sw, "settings-human-light")

    # всплывающее меню логотипа
    settings.theme = "dark"
    theme.set_mode("dark")
    win._fill_logo_menu()
    win.logo_menu.adjustSize()
    shot(win.logo_menu, "logo-menu-dark")
    sw.close()
    win.close()
    settle(app)
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
