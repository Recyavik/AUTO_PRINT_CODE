"""AutoPrintCode — запуск: python app.py"""
from __future__ import annotations

import logging
import os
import signal
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QLockFile
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from autoprint import APP_NAME


def main() -> int:
    if sys.platform != "win32":
        print("AutoPrintCode работает только в Windows (использует WinAPI SendInput).")
        return 1
    if "--selftest" in sys.argv:
        # проверка сборки: невидимо загрузить окно программы со встроенным браузером. Данные — во временной папке:
        # storage ещё не импортирован, своя папка данных задаётся до него
        import tempfile
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["AUTOPRINT_DATA"] = tempfile.mkdtemp(prefix="autoprint-selftest-")
        from autoprint.ui.app_window import selftest
        return selftest()
    from autoprint.storage import DATA_DIR, Settings, TemplateStore, migrate_legacy_data, user_data_dir
    from autoprint import taskbar
    # своя иконка на панели задач, а не иконка python.exe
    taskbar.set_process_app_id()

    # 1.0: размер — масштаб страницы окна (page_zoom), без перезапуска. Масштаб Qt, выставленный прежней версией
    # (ui_scale), перезапущенная программа могла унаследовать — свою переменную убираем, чужую не трогаем
    if os.environ.get("AUTOPRINT_QT_SCALE") and os.environ.get("AUTOPRINT_QT_SCALE") == os.environ.get("QT_SCALE_FACTOR"):
        os.environ.pop("QT_SCALE_FACTOR", None)
    os.environ.pop("AUTOPRINT_QT_SCALE", None)

    import PySide6.QtWebEngineWidgets  # noqa: F401  — встроенный браузер окна: до QApplication (общий OpenGL)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    # программа живёт и в трее (без окон): выходит только явно — из меню или кнопкой «Закрыть»
    app.setQuitOnLastWindowClosed(False)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    from autoprint import system
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    channel = system.instance_name(DATA_DIR)
    lock = QLockFile(str(DATA_DIR / ".lock"))
    # после обновления старый экземпляр может ещё завершаться — подождём его
    if not lock.tryLock(15000 if "--updated" in sys.argv else 100):
        # уже запущено: просим тот экземпляр показать окно (он мог быть свёрнут в трей). Право вывести окно
        # на передний план есть у нас (запустил пользователь) — отдаём его, иначе Windows лишь мигнёт кнопкой
        import ctypes
        ctypes.windll.user32.AllowSetForegroundWindow(-1)   # ASFW_ANY
        sock = QLocalSocket()
        sock.connectToServer(channel)
        if sock.waitForConnected(1000):
            sock.write(b"show")
            sock.flush()
            sock.waitForBytesWritten(1000)
            sock.disconnectFromServer()
            return 0
        QMessageBox.information(None, APP_NAME, "AutoPrintCode уже запущен (ищите значок в трее).")
        return 0

    # установка в Program Files: данные — в профиле; первый запуск переносит их из прежней установки
    migrated = DATA_DIR == user_data_dir() and migrate_legacy_data()

    from autoprint.logs import setup_logging
    crash_box_open = False
    live: dict = {}                       # программа, когда она создана (окно со страницей — лист вместо окошка)

    def on_crash(text: str) -> None:
        nonlocal crash_box_open
        # показать можно только из GUI-потока; ошибки фоновых потоков остаются в журнале.
        # Одна и та же ошибка может повторяться — второе окошко поверх первого не показываем
        if threading.current_thread() is not threading.main_thread() or crash_box_open:
            return
        prog_ = live.get("prog")
        if prog_ is not None and getattr(prog_.window, "_loaded", False):
            prog_.show_crash(text)        # лист «Внутренняя ошибка: …» с «Сообщить об ошибке…»
            return
        crash_box_open = True             # страница окна ещё не загрузилась — системное окошко
        try:
            box = QMessageBox(QMessageBox.Icon.Critical, APP_NAME,
                              f"Внутренняя ошибка: {text}\n\nПодробности — в журнале. Отчёт без личных данных "
                              "поможет её исправить.", parent=QApplication.activeWindow())
            save_btn = box.addButton("Сохранить отчёт на Рабочий стол", QMessageBox.ButtonRole.ActionRole)
            box.addButton("Закрыть", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is save_btn:
                try:
                    from PySide6.QtCore import QStandardPaths
                    from autoprint import report
                    desk = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
                    path = report.save_zip(report.collect(), Path(desk or Path.home()) / report.default_zip_name())
                    QMessageBox.information(None, APP_NAME, f"Отчёт сохранён: {path}\n\nПришлите этот файл автору.")
                except Exception:   # иначе ошибку сохранения молча проглотил бы обработчик исключений
                    logging.getLogger("autoprint.app").exception("Отчёт об ошибке не сохранён")
        finally:
            crash_box_open = False

    setup_logging(on_crash=on_crash)
    if migrated:
        logging.getLogger("autoprint").info("Данные прежней установки перенесены в %s", DATA_DIR)

    try:
        store = TemplateStore()
    except RuntimeError as e:
        QMessageBox.critical(None, APP_NAME, str(e))
        return 1
    if store.warning:
        QMessageBox.warning(None, APP_NAME, store.warning)

    from autoprint.app_core import App
    from autoprint.ui import logo
    from autoprint.ui.frameless import NativeFrameStyler
    from autoprint.ui.theme import theme
    settings = Settings.load()
    theme.setup(app, settings.theme)
    styler = NativeFrameStyler(app)   # системные рамки диалогов — в цветах темы
    app.installEventFilter(styler)
    app.setWindowIcon(logo.make_icon(logo.APP))   # и для диалогов
    prog = App(settings, store)
    live["prog"] = prog
    win = prog.window
    icon_file = DATA_DIR / "autoprintcode.ico"
    if logo.save_ico(icon_file):
        win.set_taskbar_icon(str(icon_file))
    win.load()
    # повторный запуск программы присылает сюда «show» — показываем окно
    server = QLocalServer()
    QLocalServer.removeServer(channel)

    def on_second_instance() -> None:
        sock = server.nextPendingConnection()
        if sock is not None:   # содержимое не важно — сам факт подключения значит «покажи окно»
            sock.disconnectFromServer()
            sock.deleteLater()
        prog.show_window()

    if server.listen(channel):
        server.newConnection.connect(on_second_instance)
    if "--tray" not in sys.argv:   # автозапуск с Windows — сразу в трей, без окна
        win.show()
    code = app.exec()
    # канал «один экземпляр» и блокировку освобождаем до перезапуска: новая версия стартует, пока этот
    # процесс ещё завершается, и должна сама занять канал (иначе её окно не покажется при повторном запуске)
    server.close()
    lock.unlock()
    if prog.relaunch_requested:   # установлено обновление: запустить уже новую версию
        from autoprint import updater
        updater.relaunch()
    return code


if __name__ == "__main__":
    sys.exit(main())
