"""Регресс-тест интерфейса: ошибки, найденные на ревью нового вида. Окна на экран не выводятся,
в другие окна ничего не печатается.

    python tests/ui_regress.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["AUTOPRINT_DATA"] = tempfile.mkdtemp(prefix="autoprint-regress-")
import quiet  # noqa: E402,F401 — окна только в памяти, без трея и уведомлений

from PySide6.QtCore import QEvent, QObject, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QWidget  # noqa: E402

app = QApplication(sys.argv)
quiet.patch()
errors: list[str] = []


def _hook(t, v, tb) -> None:
    text = "".join(traceback.format_exception(t, v, tb))
    errors.append(text)
    print(text, file=sys.stderr)


sys.excepthook = _hook

from autoprint.storage import BLOCK_CODE, BLOCK_MARKDOWN, Block, Settings, TemplateStore  # noqa: E402
from autoprint.typer import IDLE, PAUSED, RUNNING, TypingEngine  # noqa: E402
from autoprint.ui.main_window import MainWindow  # noqa: E402
from autoprint.ui.theme import theme  # noqa: E402

failed: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(f"[{'OK' if ok else 'FAIL'}] {name}{' — ' + extra if extra else ''}")
    if not ok:
        failed.append(name)


def pump(seconds: float = 0.2) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


class StraySpy(QObject):
    """Виджет, показанный самостоятельным окном (setVisible(True)/show() до вставки в родителя), мелькает
    на панели задач. Ждём только настоящие окна программы, меню и подсказки."""
    EXPECTED = ("MainWindow", "SettingsWindow", "ReportDialog", "QMenu", "QTipLabel", "QComboBoxPrivateContainer")

    def __init__(self) -> None:
        super().__init__()
        self.stray: list[str] = []

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow() \
                and type(obj).__name__ not in self.EXPECTED and not isinstance(obj, QMenu):
            self.stray.append(f"{type(obj).__name__} «{obj.objectName()}»")
        return False


def main() -> int:
    s = Settings()
    s.sound_enabled = False
    theme.setup(app, "dark")
    spy = StraySpy()
    app.installEventFilter(spy)
    store = TemplateStore()
    # блок с ролью, которой нет в программе (такое приходит из чужих .ipynb / .json)
    store.templates[0].blocks.insert(0, Block(BLOCK_MARKDOWN, "чужая роль", role="warning"))
    win = MainWindow(s, store)
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    win.show()
    pump()

    check("при запуске образец выделен в библиотеке", win.library.list.currentRow() == 0)

    # смена темы после закрытия настроек и после вставки блока — без ошибок
    win.open_settings()
    win.settings_win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    win.settings_win.show()
    pump()
    win.settings_win.close()
    pump()
    v = win.current_view()
    v.add_block(BLOCK_CODE)   # новый пустой блок становится активным — удаляем его же
    pump()
    new = next(w for w in v.widgets if w.block.id == v.template.active_block)
    v._delete_block(new)
    pump()
    errors.clear()
    for mode in ("light", "dark", "light"):
        s.theme = mode
        theme.set_mode(mode)
        pump()
    check("смена темы без ошибок", not errors, errors[0].splitlines()[-1] if errors else "")
    check("пульт перекрашен в светлую тему", theme.c("ok").name() in win.strip.state_lbl.text(),
          win.strip.state_lbl.text())

    # сочетания в меню логотипа — только подписи, иначе они перебивают сочетания окна
    win._fill_logo_menu()
    check("в меню логотипа нет двойных сочетаний", all(a.shortcut().isEmpty() for a in win.logo_menu.actions()))

    # сорвавшийся старт: задание загружено (progress 0), но печать не началась — блок не гаснет
    job = win._job_for_armed()
    win._load_job(job)
    pump()
    cw = win.current_view().code_widget(job["bid"])
    check("блок не гаснет без печати", cw.editor._progress is None, str(cw.editor._progress))
    win.cmd_stop()

    # окно настроек принадлежит главному (иначе при «поверх остальных» оно под ним)
    win.open_settings()
    check("настройки — окно-владелец главного", win.settings_win.parentWidget() is win)
    win.settings_win.close()
    pump()

    # окно «Сообщить об ошибке» — тоже из строк-карточек
    from autoprint.ui.report_dialog import ReportDialog
    d = ReportDialog(win, s)
    d.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    d.show()
    pump()
    d.close()
    pump()
    check("настройки и отчёт открываются без лишних окон на панели задач", not spy.stray,
          f"{len(spy.stray)}: {', '.join(sorted(set(spy.stray)))[:200]}")

    # пауза во время отсчёта: печать не начинается и не превращается в «Печатает» — остаётся «Пауза»
    # (с v0.5.0: следующее «старт» продолжит с новой подготовкой, а не начнёт с нуля)
    e = TypingEngine(Settings())
    states = []
    e.state_changed.connect(states.append)
    e.load("abc")
    e.start(0.0, countdown=3)
    pump(0.4)
    e.pause()
    pump(1.1)
    alive = e._thread is not None and e._thread.is_alive()
    st = e.state
    e.stop()
    pump(0.2)
    check("пауза во время отсчёта: остаётся «Пауза», печать не началась", st == PAUSED and RUNNING not in states
          and e.state == IDLE, f"состояние={st}, поток жив={alive}, история={states}")

    # узкое окно: кнопки пульта переносятся на третью строку — и она не обрезается
    win.resize(win.minimumWidth(), 700)
    pump(0.3)
    sw = win.strip.sw_strip
    top = sw.parentWidget()
    check("узкое окно: «Без комментариев» на пульте видно целиком",
          sw.geometry().bottom() <= top.height() and sw.geometry().right() <= top.width(),
          f"переключатель {sw.geometry()}, строка {top.size()}")
    win.resize(1320, 840)
    pump()

    # выбранный сегмент полужирный — его название не обрезается
    from PySide6.QtGui import QFont, QFontMetrics
    for b in win.strip.mode.buttons.values():
        bold = QFont(b.font())
        bold.setWeight(QFont.Weight.DemiBold)
        if b.width() < QFontMetrics(bold).horizontalAdvance(b.text()) + 16:
            check(f"сегмент «{b.text()}» шире полужирного названия", False, f"{b.width()} px")
            break
    else:
        check("сегменты пульта шире полужирных названий", True)

    # Shift+Enter в редакторе кода — настоящая новая строка (иначе номера строк и шаги разъезжаются)
    from PySide6.QtTest import QTest
    cw = win.current_view().code_widget(win.current_view().template.active_block)
    ed = cw.editor
    c = ed.textCursor()
    c.movePosition(c.MoveOperation.End)
    ed.setTextCursor(c)
    QTest.keyClick(ed, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClicks(ed, "z = 0")
    pump()
    check("Shift+Enter в коде — новая строка документа",
          ed.blockCount() == cw.block.text.count("\n") + 1 == len(ed.line_steps()) and " " not in
          ed.document().toRawText(), f"строк {ed.blockCount()}, в тексте {cw.block.text.count(chr(10)) + 1}")
    ed.undo()
    ed.undo()

    # хоткей без Ctrl/Alt/Win (просто буква) не принимается — он перестал бы печататься во всех программах
    from autoprint.ui.settings_window import HotkeyField
    f = HotkeyField("Ctrl+F9")
    got = []
    f.edited.connect(got.append)
    f.capturing = True
    QTest.keyClick(f, Qt.Key.Key_A)
    f.capturing = True
    QTest.keyClick(f, Qt.Key.Key_F8, Qt.KeyboardModifier.ShiftModifier)
    check("хоткей: буква без Ctrl отклонена, Shift+F8 принят", got == ["Shift+F8"], repr(got))

    # переводы строк Windows в образце из файла — как в редакторе
    from autoprint.storage import _block_from
    blk = _block_from({"type": "code", "text": "a = 1\r\nb = 2", "steps": ["1", 2]})
    check("образец из файла: \\r\\n → \\n, шаги — числа", blk.text == "a = 1\nb = 2" and blk.steps == [1, 2],
          repr((blk.text, blk.steps)))

    win.close()
    pump()
    check("закрытие без ошибок", not errors, errors[0].splitlines()[-1] if errors else "")
    print("OK" if not failed else f"FAIL: {failed}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
