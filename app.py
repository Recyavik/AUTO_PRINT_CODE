"""AutoPrintCode — запуск: python app.py"""
from __future__ import annotations

import signal
import sys
import threading

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox

from autoprint import APP_NAME
from autoprint.storage import DATA_DIR, Settings, TemplateStore


def main() -> int:
    if sys.platform != "win32":
        print("AutoPrintCode работает только в Windows (использует WinAPI SendInput).")
        return 1
    from autoprint import taskbar
    # своя иконка на панели задач, а не иконка python.exe
    taskbar.set_process_app_id()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(True)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(DATA_DIR / ".lock"))
    # после обновления старый экземпляр может ещё завершаться — подождём его
    if not lock.tryLock(15000 if "--updated" in sys.argv else 100):
        QMessageBox.information(None, APP_NAME, "AutoPrintCode уже запущен (ищите значок в трее).")
        return 0

    from autoprint.logs import setup_logging
    def on_crash(text: str) -> None:
        # окно можно показать только из GUI-потока; ошибки фоновых потоков остаются в журнале
        if threading.current_thread() is threading.main_thread():
            QMessageBox.critical(None, APP_NAME, f"Внутренняя ошибка: {text}\n\n"
                                                 "Подробности — в журнале (Файл → Открыть журнал работы).")

    setup_logging(on_crash=on_crash)

    try:
        store = TemplateStore()
    except RuntimeError as e:
        QMessageBox.critical(None, APP_NAME, str(e))
        return 1
    if store.warning:
        QMessageBox.warning(None, APP_NAME, store.warning)

    from autoprint.ui.main_window import STATE_COLORS, MainWindow, save_ico
    from autoprint.typer import IDLE
    win = MainWindow(Settings.load(), store)
    app.setWindowIcon(win.windowIcon())   # и для диалогов
    icon_file = DATA_DIR / "autoprintcode.ico"
    if save_ico(STATE_COLORS[IDLE], icon_file):
        win.set_taskbar_icon(str(icon_file))
    win.show()
    code = app.exec()
    lock.unlock()
    if win.relaunch_requested:   # установлено обновление: запустить уже новую версию
        from autoprint import updater
        updater.relaunch()
    return code


if __name__ == "__main__":
    sys.exit(main())
