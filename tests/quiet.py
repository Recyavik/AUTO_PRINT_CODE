"""Тихий режим тестов интерфейса: человек за компьютером ничего не видит и не слышит.

    import quiet   # первой строкой — до импорта PySide6 и autoprint
    ...
    quiet.patch()  # после создания QApplication

- QT_QPA_PLATFORM=offscreen — окна рисуются в памяти, на экран не попадает ничего; окно Electron —
  с --autoprint-hidden=1 (AUTOPRINT_WINDOW_HIDDEN);
- своя временная папка данных — рабочая data/ не трогается;
- без значка в трее и без уведомлений Windows;
- глобальные хоткеи и перехват клавиатуры — заглушки (не мешают настоящей программе и человеку);
- открытие файлов, папок и ссылок в других программах, микрофон — заглушки.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# у offscreen своих шрифтов нет (вместо букв — квадраты): берём шрифты Windows — размеры текста как в жизни
os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
os.environ.setdefault("AUTOPRINT_DATA", tempfile.mkdtemp(prefix="autoprint-test-"))
# окно программы (Electron) в проверках не показывается никогда: видно/свёрнуто — «как будто»
os.environ.setdefault("AUTOPRINT_WINDOW_HIDDEN", "1")


def patch() -> None:
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QSystemTrayIcon

    QSystemTrayIcon.show = lambda self: None
    QSystemTrayIcon.setVisible = lambda self, on: None
    QSystemTrayIcon.showMessage = lambda self, *a, **k: None
    QDesktopServices.openUrl = staticmethod(lambda *a, **k: True)
    os.startfile = lambda *a, **k: None

    from autoprint import recorder
    recorder.AudioRecorder.start = lambda self, *a, **k: False

    class FakeGuard(QObject):
        tripped = Signal(str)
        enter_pressed = Signal()

        def __init__(self) -> None:
            super().__init__()
            self.enabled, self.armed, self.watching = True, False, False

        def set_hotkeys(self, _hk) -> None:
            pass

        def arm(self) -> None:
            self.armed = self.enabled

        def disarm(self) -> None:
            self.armed = False

        def watch_enter(self, on: bool) -> None:
            self.watching = on

        def shutdown(self) -> None:
            self.armed = self.watching = False

        def click_count(self) -> int:
            return 0

    class FakeHotkeys(QObject):
        triggered = Signal(str)
        failed = Signal(str)
        _bindings: dict = {}

        def set_bindings(self, b) -> None:      # как у настоящего: что назначено сейчас (видно тестам)
            self._bindings = dict(b)

        def shutdown(self) -> None:
            pass

    import autoprint.app_core as M
    if not getattr(M.InputGuard, "_test_fake", False):   # у теста могут быть свои заглушки — не перебивать
        FakeGuard._test_fake = True
        M.InputGuard, M.HotkeyManager = FakeGuard, FakeHotkeys
