"""Обход всего интерфейса: каждое окно, диалог и меню программы открывается по очереди. Проверяется:
- нет «лишних окон» — виджетов, показанных самостоятельным окном до вставки в окно программы
  (они мелькают на панели задач как «AutoPrintCode» / «Python»);
- у каждого диалога есть окно-владелец (иначе у него своя кнопка на панели задач);
- ни одного исключения;
- сторож в самой программе (frameless.NativeFrameStyler) пишет лишнее окно в журнал.

    python tests/ui_sweep.py

Тихий режим (tests/quiet.py): окна только в памяти, без трея, уведомлений и хоткеев. Модальные диалоги и меню
закрываются сами; файловые диалоги, сеть, микрофон и открытие файлов в других программах — заглушки.
Рабочая папка data/ не используется.
"""
from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import quiet  # noqa: E402 — первым: окна только в памяти, своя папка данных

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QContextMenuEvent  # noqa: E402
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QLabel, QPushButton, QToolButton,  # noqa: E402
                               QWidget)

app = QApplication(sys.argv)
quiet.patch()
errors: list[str] = []
sys.excepthook = lambda t, v, tb: errors.append("".join(traceback.format_exception(t, v, tb)))

# файловые диалоги — сразу «Отмена»
QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([], ""))
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
from autoprint import updater  # noqa: E402
from autoprint.ui import frameless  # noqa: E402

failed: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(f"[{'OK' if ok else 'FAIL'}] {name}{' — ' + extra if extra else ''}")
    if not ok:
        failed.append(name)


class Spy(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.phase = "старт"
        self.stray: dict[str, set] = {}
        self.unowned: dict[str, set] = {}
        self.shown: dict[str, int] = {}

    def eventFilter(self, obj, ev) -> bool:
        if not isinstance(obj, QWidget):
            return False
        if ev.type() == QEvent.Type.Show and obj.isWindow():
            cls = type(obj).__name__
            self.shown[cls] = self.shown.get(cls, 0) + 1
            if frameless.is_stray_window(obj):
                fr = [f for f in traceback.extract_stack()[:-1] if "autoprint" in f.filename.replace("\\", "/")]
                where = " ← ".join(f"{Path(f.filename).name}:{f.lineno}" for f in reversed(fr[-3:]))
                self.stray.setdefault(f"{cls} «{obj.objectName()}» {where}", set()).add(self.phase)
            elif obj.windowType() in (Qt.WindowType.Dialog, Qt.WindowType.Window) and obj.parentWidget() is None \
                    and cls not in ("MainWindow", "TimerWindow"):
                # таймер эфира — нарочно своё окно с кнопкой на панели задач: его сворачивают, и он не должен
                # пропадать, когда сворачивают главное окно
                self.unowned.setdefault(cls, set()).add(self.phase)
        return False


spy = Spy()
app.installEventFilter(spy)


def closer() -> None:
    p = QApplication.activePopupWidget()
    if p is not None:
        p.close()
        return
    m = QApplication.activeModalWidget()
    if m is not None:
        m.reject() if isinstance(m, QDialog) else m.close()


auto = QTimer()
auto.timeout.connect(closer)
auto.start(120)


def step(name: str, fn) -> None:
    spy.phase = name
    try:
        fn()
    except Exception:
        errors.append(f"[{name}] " + traceback.format_exc())
    for _ in range(6):
        app.processEvents()


def main() -> int:
    from autoprint.storage import Settings, TemplateStore
    from autoprint.ui.main_window import MainWindow
    from autoprint.ui.settings_window import PAGES
    from autoprint.ui.theme import theme

    s = Settings()
    s.sound_enabled = False
    s.update_auto_check = False
    theme.setup(app, "dark")
    store = TemplateStore()
    win = MainWindow(s, store)
    win.check_updates = lambda manual=True: None   # без сети
    win._restart = lambda: None                     # «перезапустить сейчас» — не перезапускать тест
    step("главное окно", win.show)

    # образцы, режимы, меню блоков и контекстное меню кода
    for t in list(store.templates):
        step(f"образец «{t.title}»", lambda t=t: win.open_template(t.id))
        for w in list(win.current_view().widgets):
            for b in w.findChildren(QToolButton):
                if b.menu() is not None and b.isVisibleTo(w):
                    step(f"меню блока «{b.objectName() or b.text()}»", b.showMenu)
            ed = getattr(w, "editor", None)
            if ed is not None:
                step("контекстное меню кода", lambda ed=ed: QApplication.sendEvent(
                    ed.viewport(), QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(8, 8),
                                                     ed.mapToGlobal(QPoint(8, 8)))))
        for mode in ("lines", "steps", "block"):
            step(f"режим {mode}", lambda m=mode: win._on_mode(m))
    step("без комментариев", lambda: (win.strip.sw_strip.setChecked(True), win.strip.sw_strip.setChecked(False)))
    step("сообщение внизу окна", lambda: win._notify("проверка"))
    step("шаг назад", lambda: (win._on_mode("steps"), win.cmd_step_back(), win._on_mode("block")))
    step("меню библиотеки", lambda: win._library_menu(QPoint(10, 10)))
    step("новый образец", win.new_template)
    step("смена темы", lambda: (theme.set_mode("light"), theme.set_mode("dark")))

    # меню логотипа — каждый пункт, кроме «Выход»
    win._fill_logo_menu()
    for a in list(win.logo_menu.actions()):
        txt = a.text().split("\t")[0]
        if a.isSeparator() or not txt or "Выход" in txt:
            continue
        step(f"меню логотипа: {txt}", a.trigger)
        if win.settings_win is not None and win.settings_win.isVisible():
            win.settings_win.close()

    # меню трея (без «Старт» и «Выход»)
    for a in list(win.tray_menu.actions()):
        if a.text() in ("Показать окно", "Стоп", "Настройки…"):
            step(f"трей: {a.text()}", a.trigger)
    step("трей: меню", lambda: win.tray_menu.popup(QPoint(50, 50)))

    # настройки: все страницы, запись звука, кнопки «О программе»
    step("настройки", win.open_settings)
    sw = win.settings_win
    for key, _ic, _t in PAGES:
        step(f"настройки/{key}", lambda k=key: sw.show_page(k))
    step("записать звук клавиатуры", sw._record_sound)
    for b in sw.findChildren(QPushButton):
        if b.text().strip() in ("Сообщить об ошибке", "Журнал работы", "Папка с данными"):
            step(f"настройки: «{b.text().strip()}»", b.click)
    step("закрыть настройки", sw.close)

    # обновление — выдуманный выпуск, без сети
    rel = updater.Release("9.9.9", "v9.9.9", "9.9.9", "## Что нового\n- проверка", "https://example.invalid",
                          "https://example.invalid/z.zip", "2026-10-08")
    win.updates.latest = rel
    step("кнопка обновления", lambda: win._show_update_button(rel))
    step("окно обновления", win.open_update_dialog)

    # сторож в самой программе: лишнее окно попадает в журнал
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    logging.getLogger(frameless.__name__).addHandler(handler)
    styler = frameless.NativeFrameStyler()
    app.installEventFilter(styler)
    spy.phase = "проверка сторожа"
    lb = QLabel("лишнее")
    lb.setVisible(True)            # нарочно: показать до вставки в окно
    app.processEvents()
    lb.close()
    app.removeEventFilter(styler)
    logging.getLogger(frameless.__name__).removeHandler(handler)
    check("сторож пишет лишнее окно в журнал", any("Лишнее окно" in r.getMessage() for r in records),
          f"{len(records)} записей")
    spy.stray = {k: v for k, v in spy.stray.items() if "проверка сторожа" not in v}

    win._quitting = True
    step("выход", win.close)
    auto.stop()

    opened = spy.shown
    check("открылись все окна и диалоги",
          all(opened.get(k, 0) > 0 for k in ("MainWindow", "SettingsWindow", "RecordDialog", "ReportDialog",
                                             "UpdateDialog", "QInputDialog")) and opened.get("QMenu", 0) >= 10,
          repr(dict(sorted(opened.items()))))
    check("нет лишних окон на панели задач", not spy.stray,
          "; ".join(f"{k} [{', '.join(sorted(v))[:80]}]" for k, v in spy.stray.items())[:600])
    check("у каждого диалога есть окно-владелец", not spy.unowned,
          "; ".join(f"{k} [{', '.join(sorted(v))[:80]}]" for k, v in spy.unowned.items()))
    check("без исключений", not errors, errors[0].strip().splitlines()[-1][:200] if errors else "")
    for e in errors[:5]:
        print(e, file=sys.stderr)
    print("OK" if not failed else f"FAIL: {failed}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
