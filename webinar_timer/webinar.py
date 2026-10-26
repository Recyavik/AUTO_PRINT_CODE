"""Таймер вебинара — запуск: python webinar.py (или webinar.bat).

Повестка эфира по часам, напоминания на мониторе управления, заставка перерыва на мониторе демонстрации.
Работает отдельно от AutoPrintCode (и рядом с его веб-версией). Папка самодостаточна:
data/ — шаблоны и настройки, media/ — фон перерыва, видео гимнастики, шрифт Furore.
"""
from __future__ import annotations

import logging
import signal
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox

from webinar import APP_NAME, __version__
from webinar.store import DATA_DIR, PlanStore, Settings



def setup_logging() -> None:
    (DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(DATA_DIR / "logs" / "webinar.log", maxBytes=500_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    logging.getLogger("webinar").info("==== %s %s запущен", APP_NAME, __version__)


def main() -> int:
    if sys.platform == "win32":
        from webinar import taskbar
        taskbar.set_process_app_id()         # своя кнопка на панели задач, а не «Python»
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)     # закрытое окно — в трее, эфир продолжается
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(DATA_DIR / ".lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, APP_NAME, "Таймер вебинара уже запущен (значок — в трее).")
        return 0
    setup_logging()

    from webinar.ui.main_window import MainWindow, make_icon
    from webinar.ui.style import APP_QSS
    app.setStyleSheet(APP_QSS)
    store = PlanStore()
    win = MainWindow(store, Settings.load())
    app.setWindowIcon(make_icon())
    if store.warning:
        QMessageBox.warning(win, APP_NAME, store.warning)
    win.show()
    if sys.platform == "win32":
        ico = DATA_DIR / "webinar.ico"
        if make_icon().pixmap(256).save(str(ico), "ICO"):
            from webinar import taskbar
            taskbar.apply_to_window(int(win.winId()), str(ico), APP_NAME)
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
