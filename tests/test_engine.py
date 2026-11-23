"""Движок печати и главное окно вместе — против эмулятора редактора. Настоящие нажатия НЕ отправляются:
функции SendInput в autoprint.winapi подменены, защита от нажатий и глобальные хоткеи — заглушки
(хуки клавиатуры не ставятся). Окна на экран не выводятся.

    python tests/test_engine.py

Проверяется: печать по шагам и по строкам целиком (профиль IDE — с автоотступом и автоскобками), хоткей
«дальше» с ещё зажатым Ctrl, запоздалые сигналы состояния и защита, отмена печати, суфлёр по строкам.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["AUTOPRINT_DATA"] = tempfile.mkdtemp(prefix="autoprint-engine-")
import quiet  # noqa: E402,F401 — окна только в памяти, без трея и уведомлений

from PySide6.QtCore import QObject, Qt, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
quiet.patch()   # свои заглушки защиты и хоткеев тест ставит ниже
errors: list[str] = []


def _hook(t, v, tb) -> None:
    errors.append("".join(traceback.format_exception(t, v, tb)))
    print(errors[-1], file=sys.stderr)


sys.excepthook = _hook

from autoprint import steps as S  # noqa: E402
from autoprint import winapi as W  # noqa: E402
from autoprint.comments import comment_spans  # noqa: E402
from autoprint.storage import (BLOCK_CODE, PROFILE_IDE, PROFILE_PLAIN, Block, Settings, Template,  # noqa: E402
                               TemplateStore)
from autoprint.typer import FINISHED, IDLE, LINE_WAIT, RUNNING, TypingEngine, build_units  # noqa: E402
from autoprint.storage import STEPS_SAMPLE_CODE as S_CODE, STEPS_SAMPLE_STEPS as S_STEPS  # noqa: E402

failed: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {name}{' — ' + str(extra) if extra else ''}")
    if not ok:
        failed.append(name)


# ---------------------------------------------------------------- эмулятор редактора

KEYS = {W.VK_BACK: "back", W.VK_TAB: "tab", W.VK_RETURN: "enter", W.VK_ESCAPE: "esc", W.VK_END: "end",
        W.VK_HOME: "home", W.VK_UP: "up", W.VK_DOWN: "down"}


class Editor:
    """Документ, курсор, выделение в строке. ide=True — автоотступ после Enter и автоскобки, как в VS Code.
    held — «физически зажатые» пользователем модификаторы: они добавляются к каждому нажатию."""

    def __init__(self) -> None:
        self.reset()

    def reset(self, ide: bool = False, tags: bool = False, richedit: bool = False) -> None:
        self.lines, self.r, self.c, self.sel, self.ide = [""], 0, 0, None, ide
        self.tags = tags                  # как HTML в VS Code: после «<div>» справа появляется «</div>»
        # как Блокнот Windows 11 (RichEdit): курсор пришёл ↑/↓ с более длинной строки — Shift+End выделяет и
        # перенос строки; набранная буква его не трогает, а Enter заменяет (новой строки не получается)
        self.richedit = richedit
        self.want = 0                     # «желаемый» столбец при ↑/↓
        self.overshoot = False            # строка короче желаемого столбца
        self.sel_eol = False              # в выделение попал перенос строки
        self.held: set[int] = set()
        self.bad: list[str] = []          # нажатия с зажатым Ctrl — так печать идти не должна
        self.lock = threading.Lock()

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def _del_sel(self) -> None:
        if self.sel is not None and self.sel != self.c:
            a, b = sorted((self.sel, self.c))
            ln = self.lines[self.r]
            self.lines[self.r], self.c = ln[:a] + ln[b:], a
        self.sel = None

    def char(self, ch: str) -> None:
        with self.lock:
            if W.VK_CONTROL in self.held:
                self.bad.append(f"Ctrl+{ch!r}")
            self._del_sel()
            ln = self.lines[self.r]
            closer = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}.get(ch, "") if self.ide else ""
            m = re.search(r"<(\w+)>$", ln[:self.c] + ch) if self.tags else None
            if m:
                closer = f"</{m.group(1)}>"
            self.lines[self.r] = ln[:self.c] + ch + closer + ln[self.c:]
            self.c += 1
            self.want, self.overshoot, self.sel_eol = self.c, False, False

    def tap(self, vk: int, *mods: int) -> None:
        with self.lock:
            mods = set(mods) | self.held
            name, shift, ctrl = KEYS[vk], W.VK_SHIFT in mods, W.VK_CONTROL in mods
            if W.VK_CONTROL in self.held:
                self.bad.append(f"Ctrl+{name}")
            eol = self.sel_eol
            self.sel_eol = False
            if self.richedit and name == "end" and shift and not ctrl and self.overshoot \
                    and self.r < len(self.lines) - 1:
                self.sel_eol = True       # особенность RichEdit — см. reset()
            if name == "enter" and eol:
                self.sel = None
                self.r, self.c = self.r + 1, 0   # перенос заменён переносом: курсор — в начале следующей строки
                self.want, self.overshoot = 0, False
                return
            if name in ("up", "down"):
                self.sel = None
                self.r = max(0, self.r - 1) if name == "up" else min(len(self.lines) - 1, self.r + 1)
                self.c = min(self.want, len(self.lines[self.r]))
                self.overshoot = self.want > len(self.lines[self.r])
                return
            if name in ("home", "end") and ctrl:
                self.sel = None
                self.r = 0 if name == "home" else len(self.lines) - 1
                self.c = 0 if name == "home" else len(self.lines[self.r])
            elif name in ("home", "end"):
                self.sel = (self.c if self.sel is None else self.sel) if shift else None
                self.c = 0 if name == "home" else len(self.lines[self.r])
                # End после ↑/↓ особенность Блокнота не снимает (проверено на настоящем Блокноте)
            elif name == "back":
                if self.sel is not None and self.sel != self.c:
                    self._del_sel()
                elif self.c:
                    ln = self.lines[self.r]
                    self.lines[self.r] = ln[:self.c - 1] + ln[self.c:]
                    self.c -= 1
                elif self.r:
                    prev = self.lines[self.r - 1]
                    self.lines[self.r - 1:self.r + 1] = [prev + self.lines[self.r]]
                    self.r, self.c = self.r - 1, len(prev)
                self.sel = None
            elif name == "enter":
                self._del_sel()
                ln = self.lines[self.r]
                head = ln[:self.c]
                indent = head[:len(head) - len(head.lstrip(" "))] if self.ide else ""
                if self.ide and head.rstrip().endswith(":"):
                    indent += "    "
                self.lines[self.r:self.r + 1] = [head, indent + ln[self.c:]]
                self.r, self.c = self.r + 1, len(indent)
            elif name == "tab":
                self._del_sel()
                ln = self.lines[self.r]
                self.lines[self.r] = ln[:self.c] + "    " + ln[self.c:]
                self.c += 4
            if name in ("back", "enter", "tab"):
                self.want, self.overshoot = self.c, False


ED = Editor()
TARGET = 4242
W.type_char = ED.char
W.tap = ED.tap
W.foreground_window = lambda: TARGET
W.is_own_window = lambda h: False
W.self_elevated = lambda: False
W.window_elevated = lambda h: False
W.window_process_name = lambda h: "notepad.exe"   # «Блокнот»-профиль здесь уместен (без подсказки про IDE)
W.describe_window = lambda h: "notepad.exe «тест»"


def _wait_mods(timeout: float = 5.0, cancelled=lambda: False) -> bool:
    end = time.monotonic() + timeout
    while ED.held:
        if time.monotonic() > end or cancelled():
            return False
        time.sleep(0.01)
    return True


W.wait_modifiers_released = _wait_mods
# клики мыши — подменены (настоящая мышь тесту не мешает); clicks — счётчик Raw Input (guard.click_count)
MOUSE = {"down": False, "own": False, "clicks": 0}
W.mouse_pressed = lambda: MOUSE["down"]
W.cursor_over_own_window = lambda: MOUSE["own"]
DELAY = {"s": 0.0}
TypingEngine._delay_after = lambda self, u: DELAY["s"]   # быстро: темп здесь не проверяется
TypingEngine._gap = lambda self: 0.0005


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
        return MOUSE["clicks"]


class FakeHotkeys(QObject):
    triggered = Signal(str)
    failed = Signal(str)

    def set_bindings(self, _b) -> None:
        pass

    def shutdown(self) -> None:
        pass


import autoprint.ui.main_window as M  # noqa: E402

M.InputGuard, M.HotkeyManager = FakeGuard, FakeHotkeys
from autoprint.ui.theme import theme  # noqa: E402


def pump(seconds: float = 0.05) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.002)


def wait_for(pred, timeout: float = 10.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.002)
    return False


def make_window(profile: str):
    s = Settings()
    s.sound_enabled = False
    s.update_auto_check = False
    s.profile = profile
    s.button_countdown_s = 0
    s.hotkey_start_delay_ms = 0
    store = TemplateStore()
    win = M.MainWindow(s, store)
    win.tray.showMessage = lambda *a, **k: None   # без всплывающих уведомлений Windows
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    win.show()
    pump()
    return win, s, store


def focus(win, t) -> None:
    """Урок — на экран урока (в фокус печати), его первый код — следующим к печати."""
    win.printer.set_focus(t.id)
    first = t.next_code()
    if first is not None:
        win.printer.arm(first.id)
    pump()


def press_enter(win) -> bool:
    """Пользователь нажал Enter в редакторе: Enter дошёл до редактора, хук сообщил о нём программе."""
    pos = win.engine._pos
    ED.tap(W.VK_RETURN)
    win.guard.enter_pressed.emit()
    return wait_for(lambda: win.engine._pos > pos or win.engine.state == FINISHED, 5)


def steps_lesson(profile: str, strip: bool) -> None:
    ED.reset(ide=profile == PROFILE_IDE)
    win, s, store = make_window(profile)
    t = next(t for t in store.templates if t.title.startswith("Пример: пошаговый"))
    focus(win, t)
    win.printer.set_option("strip", strip)
    win.printer.set_option("mode", "steps")
    pump()
    b = t.code_blocks()[0]
    ok, detail = True, ""
    for k in S.step_numbers(b.steps, b.text.count("\n") + 1):
        win.printer.toggle()
        if not wait_for(lambda: win.engine.state == FINISHED and win.printer.job is None):
            ok, detail = False, f"шаг {k}: не закончился ({win.engine.state})"
            break
        lines = S.analyze(b.text, b.steps, b.lang, strip)
        exp = "\n".join(sl.typed for sl in lines if sl.typed is not None and sl.step <= k)
        if ED.text != exp:
            ok, detail = False, f"шаг {k}:\n  есть {ED.text!r}\n  ждём {exp!r}"
            break
    check(f"по шагам, {profile}, без комментариев={strip}: в редакторе ровно шаги 1…k", ok, detail)
    check(f"по шагам, {profile}: после урока все шаги напечатаны, защита снята",
          win.printer.step_pointer(b.id) is None and not win.guard.armed and not win.guard.watching)
    # «шаг назад» со стрелками: подсказка, куда поставить курсор после стирания шага
    notes: list[str] = []
    win.printer.notify.connect(lambda text, *_a: notes.append(text))
    win.printer.step_back()
    check(f"по шагам, {profile}: «шаг назад» подсказывает, где оставить курсор",
          bool(notes) and "в конец строки" in notes[-1], notes[-1:] or "нет сообщения")
    win.close()
    pump()


def run_units(units, s: Settings) -> None:
    """Единицы — прямо в эмулятор (как поток печати, но без пауз и состояний)."""
    e = TypingEngine(s)
    for u in units:
        e._execute(u)


def steps_blank_chunk() -> None:
    """Шаг, кусок которого — одна пустая строка: автоотступ после Enter не должен «съесть» следующую вставку."""
    text = "def f():\n    a = 1\n\n    b = 2\n    c = 3"
    steps = [1, 1, 2, 1, 2]
    for nav in ("arrows", "home"):
        ED.reset(ide=True)
        s = Settings()
        s.profile, s.human_typing = PROFILE_IDE, False
        lines = S.analyze(text, steps, "python", False)
        got = []
        for k in (1, 2):
            run_units(S.build_step_units(lines, k, s, nav), s)
            got.append(ED.text)
        exp = ["def f():\n    a = 1\n    b = 2", text]
        check(f"по шагам ({nav}): кусок из одной пустой строки — код не теряется", got == exp,
              f"\n  есть {got!r}\n  ждём {exp!r}")
    # пустая строка — последний кусок шага: в ней не остаётся отступа
    ED.reset(ide=True)
    lines = S.analyze("def g():\n    x = 1\n", [1, 1, 2], "python", False)
    for k in (1, 2):
        run_units(S.build_step_units(lines, k, s, "arrows"), s)
    check("по шагам: пустая строка в конце шага — без хвоста пробелов", ED.text == "def g():\n    x = 1\n",
          repr(ED.text))


def notepad_steps() -> None:
    """Пошаговый урок, профиль IDE, но окно — Блокнот Windows 11: курсор к месту вставки идёт ↑ с более
    длинной строки, и Shift+End перед Enter выделил бы перенос — следующая строка урока пропадала."""
    lines = S.analyze(S_CODE, S_STEPS, "python", True)
    exp = "\n".join(sl.typed for sl in lines if sl.typed is not None)
    s = Settings()
    s.profile, s.human_typing = PROFILE_IDE, False
    ED.reset(ide=False, richedit=True)
    for k in sorted(set(S_STEPS)):
        run_units(S.build_step_units(lines, k, s, "arrows"), s)
    check("по шагам в Блокноте (IDE): вставка в середину не съедает следующую строку", ED.text == exp,
          f"\n  есть {ED.text!r}\n  ждём {exp!r}")


def bracket_first_on_line() -> None:
    """Профиль IDE: перед закрывающей скобкой, которая первая в строке (после отступа), — «Shift+End, пробел,
    стереть». Без них настоящий VS Code сам переставлял отступ такой строки: «  }» → «}» (образец с отступом 2)."""
    code = "function sum(arr) {\n  for (const n of arr) {\n    if (n) {\n      t += n;\n    }\n  }\n}"
    ED.reset(ide=True)
    log: list[str] = []
    orig_char, orig_tap = W.type_char, W.tap

    def char(ch: str) -> None:
        log.append(f"char:{ch}")
        orig_char(ch)

    def tap(vk: int, *mods: int) -> None:
        log.append(("shift+" if W.VK_SHIFT in mods else "") + KEYS[vk])
        orig_tap(vk, *mods)
    W.type_char, W.tap = char, tap
    try:
        s = Settings()
        s.profile, s.human_typing = PROFILE_IDE, False
        run_units(build_units(code, s), s)
    finally:
        W.type_char, W.tap = orig_char, orig_tap
    before = [log[i - 3:i] for i, x in enumerate(log) if x == "char:}"]
    ok = len(before) == 3 and all(b == ["shift+end", "char: ", "back"] for b in before)
    check("закрывающая скобка первой в строке — перед ней «Shift+End, пробел, стереть»", ok and ED.text == code,
          f"{before} {ED.text!r}" if not ok or ED.text != code else "")


def closing_tag_tail() -> None:
    """Профиль IDE: закрывающий тег, который редактор дописал после «>», не остаётся лишним в коде."""
    code = "<t>\n    1 + 2\n</t>"
    ED.reset(ide=True, tags=True)
    s = Settings()
    s.profile, s.human_typing = PROFILE_IDE, False
    run_units(build_units(code, s), s)
    check("закрывающий тег от редактора (HTML) — не дублируется", ED.text == code, repr(ED.text))


def lines_block(profile: str, strip: bool, hotkey_with_ctrl: bool) -> None:
    ED.reset(ide=profile == PROFILE_IDE)
    win, s, store = make_window(profile)
    focus(win, store.templates[0])
    win.printer.set_option("strip", strip)
    win.printer.set_option("mode", "lines")
    pump()
    job = win.printer.job_for_armed()
    win.printer.toggle()
    waits, watch_ok = 0, True
    while wait_for(lambda: win.engine.state in (LINE_WAIT, FINISHED)) and win.engine.state == LINE_WAIT:
        pump(0.01)
        watch_ok &= win.guard.watching and not win.guard.armed
        waits += 1
        if hotkey_with_ctrl:
            # Ctrl+F9: хоткей сработал, а Ctrl ещё зажат — печать должна дождаться отпускания
            ED.held = {W.VK_CONTROL}
            pos = win.engine._pos
            win.printer.toggle()
            threading.Timer(0.15, ED.held.clear).start()
            wait_for(lambda: win.engine._pos > pos or win.engine.state == FINISHED, 5)
        elif not press_enter(win):
            break
    name = f"по строкам, {profile}, без комментариев={strip}, {'хоткей с Ctrl' if hotkey_with_ctrl else 'Enter'}"
    check(f"{name}: напечатано всё ({waits} ожиданий)", ED.text == job["text"],
          f"\n  есть {ED.text!r}\n  ждём {job['text']!r}" if ED.text != job["text"] else "")
    check(f"{name}: в ожидании Enter только слушаем клавиатуру", watch_ok and waits > 0)
    if hotkey_with_ctrl:
        check(f"{name}: ни одного нажатия с зажатым Ctrl", not ED.bad, ED.bad[:4])
    win.close()
    pump()


def races() -> None:
    ED.reset()
    win, s, store = make_window(PROFILE_PLAIN)
    focus(win, store.templates[0])
    # запоздалый сигнал «Печатает» после «Стоп» не включает защиту
    win.printer._on_state(RUNNING)
    check("запоздалое «Печатает» у стоящей печати не включает защиту", not win.guard.armed)
    win.guard.armed = True
    win.printer._on_guard("key")
    check("срабатывание защиты у стоящей печати её снимает", not win.guard.armed)

    # «Стоп», пока движок ждёт отпускания Ctrl после хоткея (дольше, чем ждёт «Стоп»)
    before = ED.text
    ED.held = {W.VK_CONTROL}
    win.printer.toggle()
    pump(0.1)
    win.printer.stop()
    threading.Timer(1.4, ED.held.clear).start()
    pump(2.0)
    check("остановленный поток не возвращает «Печатает»/«Пауза»", win.engine.state == IDLE and not win.guard.armed,
          win.engine.state)
    check("остановленный поток ничего не печатает", ED.text == before, repr(ED.text[len(before):][:30]))

    # смена режима в окне настроек во время печати — печать остановлена
    DELAY["s"] = 0.02
    win.printer.toggle()
    wait_for(lambda: win.engine.state == RUNNING)
    s.print_mode = "lines"
    win._on_setting_changed("print_mode")
    pump()
    check("режим сменили в настройках во время печати — печать остановлена", win.engine.state == IDLE,
          win.engine.state)
    s.print_mode = "block"
    win._on_setting_changed("print_mode")

    # блок, который печатается, удалили — печать остановлена
    t = Template("удаление", [Block(BLOCK_CODE, "a = 1\nb = 2\nc = 3")])
    store.insert(t)
    win._fill_library(t.id)
    focus(win, t)
    win.printer.toggle()
    wait_for(lambda: win.engine.state == RUNNING)
    t.blocks.pop(0)          # блок удалили (на экране урока) — урок изменился
    win.touch(t)
    pump(0.2)
    check("удалили печатающийся блок — печать остановлена", win.engine.state == IDLE, win.engine.state)
    DELAY["s"] = 0.0
    win.close()
    pump()


def prompter_lines() -> None:
    ED.reset()
    win, s, store = make_window(PROFILE_PLAIN)
    t = Template("суфлёр", [Block(BLOCK_CODE, "# в начале\nx = 1  # хвост x\n# между\ny = 2\n\n# перед z\n"
                                              "z = 3  # хвост z")])
    store.insert(t)
    win._fill_library(t.id)
    focus(win, t)
    win.printer.set_option("strip", True)
    win.printer.set_option("mode", "lines")
    pump(0.3)

    def say() -> str:
        return "\n".join(win.printer.snapshot()["say"])
    said = [say()]
    lines = [win.printer.snapshot()["next_lines"]]
    win.printer.toggle()
    while wait_for(lambda: win.engine.state in (LINE_WAIT, FINISHED)) and win.engine.state == LINE_WAIT:
        pump(0.02)
        said.append(say())
        lines.append(win.printer.snapshot()["next_lines"])
        if not press_enter(win):
            break
    exp = ["в начале\nхвост x", "между", "перед z\nхвост z"]
    check("экран урока по строкам: «Скажи» — комментарии между строками и хвостовые", said == exp, repr(said))
    check("экран урока по строкам: подсвечена следующая строка блока", lines == [[2], [4], [7]], repr(lines))
    check("суфлёр по строкам: напечатан код без комментариев", ED.text == "x = 1\ny = 2\n\nz = 3", repr(ED.text))
    win.close()
    pump()


def notes_never_print() -> None:
    """0.10: печатается только код. Заметка «Задание» — не печатается и следующей не становится;
    Ctrl+F9 печатает код урока. Окно у блока кода. «Следующий блок» на краю урока не сбрасывает паузу."""
    from autoprint.storage import BLOCK_MARKDOWN, PROFILE_TERMINAL
    ED.reset()
    win, s, store = make_window(PROFILE_PLAIN)
    task = Block(BLOCK_MARKDOWN, "## Задача\nПосчитать **сумму** списка.", role="task")
    code = Block(BLOCK_CODE, "total = 0\nfor n in nums:\n    total += n", lang="python")
    t = Template("заметка и код", [task, code])
    store.insert(t)
    win._fill_library(t.id)
    win.printer.set_focus(t.id)
    check("заметку нельзя сделать следующей к печати", not win.printer.arm(task.id) and t.active_block == "")

    def print_active() -> str:
        ED.reset()
        win.printer.toggle()
        wait_for(lambda: win.engine.state == FINISHED and win.printer.job is not None, 10)
        pump(0.05)
        return ED.text
    check("Ctrl+F9 без указателя — первый код урока, а не заметка", print_active() == code.text, repr(ED.text))
    check("после кода указатель снят (больше кода нет), последний — этот код",
          t.active_block == "" and win.printer.last == code.id)
    # окно у блока: «Терминал» при общем «Блокнот»
    code.profile = PROFILE_TERMINAL
    win.printer.restart()                       # «ещё раз» — снова этот код следующим
    print_active()
    check("окно у блока: «Терминал» — в задании и у движка",
          win.printer.job["profile"] == PROFILE_TERMINAL and win.engine.profile == PROFILE_TERMINAL)
    code.profile = ""
    win.printer.arm(code.id)
    DELAY["s"] = 0.02
    ED.reset()
    win.printer.toggle()
    wait_for(lambda: win.engine.state == RUNNING, 5)
    win.engine.pause()
    wait_for(lambda: win.engine.state == "paused", 5)
    win.printer.step(+1)
    check("на краю урока «следующий блок» не сбрасывает печать на паузе",
          win.engine.state == "paused" and t.active_block == code.id, win.engine.state)
    DELAY["s"] = 0.0
    win.printer.stop()
    win.close()
    pump()


def plain_in_editor_hint() -> None:
    """Профиль «Блокнот», а окно — редактор кода или браузер: подсказка про IDE, один раз за запуск;
    в Блокноте — без подсказок (там «Блокнот» и нужен)."""
    s = Settings()
    s.profile = PROFILE_PLAIN
    s.hotkey_start_delay_ms = 0
    e = TypingEngine(s)
    msgs: list[str] = []
    e.message.connect(msgs.append)
    real = W.window_process_name
    try:
        for exe in ("msedge.exe", "msedge.exe", "notepad.exe"):
            W.window_process_name = lambda h, exe=exe: exe
            ED.reset()
            e.load("x = 1")
            e.start()
            wait_for(lambda: e.state == FINISHED, 5)
            pump(0.05)
    finally:
        W.window_process_name = real
    hints = [m for m in msgs if "«Блокнот»" in m]
    check("«Блокнот» в браузере: подсказка про IDE — один раз за запуск, в Блокноте — нет",
          len(hints) == 1 and "IDE" in hints[0], repr(msgs))


def comments_speed() -> None:
    rows = []
    for i in range(500):
        if i % 10 == 0:
            rows.append(f"# Шаг {i // 10}: комментарий")
        rows.append(f"    value_{i} = compute({i}, 'text', [1, 2, 3])  # хвост {i}")
    text = "\n".join(rows)
    t0 = time.perf_counter()
    for _ in range(10):
        spans = comment_spans(text, "python")
    ms = (time.perf_counter() - t0) / 10 * 1000
    check("разбор комментариев блока в 550 строк быстрый (печать в редакторе не тормозит)", ms < 15 and
          len(spans) == 550, f"{ms:.1f} мс, комментариев {len(spans)}")


def smooth_newlines() -> None:
    """Профиль IDE: лишних служебных нажатий нет — после Enter автоотступ не трогают до первого символа
    (иначе строка «прыгает» во время паузы), «пробел + Backspace» — только где могла быть подсказка."""
    code = "def total(nums):\n    s = 0\n    for n in nums:\n        s += n\n\n    return s"
    ED.reset(ide=True)
    log: list[str] = []
    orig_char, orig_tap = W.type_char, W.tap

    def char(ch: str) -> None:
        log.append(f"char:{ch}")
        orig_char(ch)

    def tap(vk: int, *mods: int) -> None:
        log.append(("shift+" if W.VK_SHIFT in mods else "") + KEYS[vk])
        orig_tap(vk, *mods)
    W.type_char, W.tap = char, tap
    try:
        s = Settings()
        s.profile, s.human_typing = PROFILE_IDE, False
        e = TypingEngine(s)
        e.load(code)
        e.start()
        wait_for(lambda: e.state == FINISHED, 10)
    finally:
        W.type_char, W.tap = orig_char, orig_tap
    check("плавный перенос: текст точно как в образце", ED.text == code, repr(ED.text))
    pairs = sum(1 for a, b in zip(log, log[1:]) if a == "char: " and b == "back")
    # «пробел + Backspace» нужен только перед «)» после «nums», перед Enter после «s += n» и в конце после «s»
    # (после «s = 0» — нет: у чисел подсказок автодополнения не бывает)
    check("плавный перенос: «пробел + стереть» только где нужно", pairs == 3, f"{pairs} раз; было бы 11")
    after_enter = [log[i + 1] for i, x in enumerate(log[:-1]) if x == "enter"]
    check("плавный перенос: сразу после Enter отступ не трогают", all(x != "char: " for x in after_enter),
          after_enter)


def mouse_click_pauses() -> None:
    """Клик мышью в редакторе во время печати — пауза; клик по окну самой программы — нет."""
    ED.reset(ide=False)
    s = Settings()
    s.profile, s.human_typing = PROFILE_PLAIN, False
    e = TypingEngine(s)
    hits: list[str] = []
    e.interrupted.connect(hits.append)
    DELAY["s"] = 0.03
    try:
        e.load("x" * 200)
        e.start()
        wait_for(lambda: e.state == RUNNING, 5)
        MOUSE.update(down=True, own=True)        # кнопка «Пауза» в окне программы — не вмешательство
        pump(0.2)
        own_ok = e.state == RUNNING
        MOUSE.update(down=True, own=False)       # клик в редакторе
        paused = wait_for(lambda: e.state == "paused", 3)
        MOUSE.update(down=False, own=False)
        pump(0.1)
        e.stop()
    finally:
        DELAY["s"] = 0.0
        MOUSE.update(down=False, own=False)
    check("клик по окну программы не ставит паузу", own_ok)
    check("клик мышью в редакторе — пауза", paused and hits == ["mouse"], hits)

    # короткий тап (кнопка уже отпущена к опросу) — виден по счётчику Raw Input
    e = TypingEngine(s)
    e.click_count = lambda: MOUSE["clicks"]
    hits.clear()
    e.interrupted.connect(hits.append)
    DELAY["s"] = 0.03
    try:
        MOUSE["clicks"] += 1                     # клик до старта (поставили курсор) — не вмешательство
        e.load("y" * 200)
        e.start()
        wait_for(lambda: e.state == RUNNING, 5)
        pump(0.2)
        before_ok = e.state == RUNNING
        MOUSE["clicks"] += 1                     # тап тачпада во время печати
        tapped = wait_for(lambda: e.state == "paused", 3)
        MOUSE["clicks"] += 1                     # щёлкнули в редакторе на паузе, потом продолжили
        e.resume()
        wait_for(lambda: e.state == RUNNING, 5)
        pump(0.2)
        resumed = e.state
        e.stop()
    finally:
        DELAY["s"] = 0.0
    check("клик до старта печати не ставит паузу", before_ok)
    check("короткий тап во время печати — пауза", tapped and hits[:1] == ["mouse"], hits)
    check("клик на паузе не мешает продолжить", resumed == RUNNING and hits == ["mouse"], f"{resumed} {hits}")


def tour_sample() -> None:
    """«Пример занятия: все возможности»: в новой базе — один и открыт первым; у обновившихся (база есть,
    а пример ещё не показывали) — добавляется наверх и открывается."""
    from autoprint.samples import TOUR_TITLE
    ED.reset()
    win, s, store = make_window(PROFILE_PLAIN)
    titles = [t.title for t in store.templates]
    check("новая база: экскурсия одна и в фокусе", titles.count(TOUR_TITLE) == 1 and
          win.printer.focus().title == TOUR_TITLE, repr(titles))
    win.close()
    pump()
    win, s, store = make_window(PROFILE_PLAIN)   # тот же templates.json, но в настройках пример ещё не видели
    check("после обновления: экскурсия добавлена наверх и в фокусе", store.templates[0].title == TOUR_TITLE and
          win.printer.focus() is store.templates[0] and "tour_v1" in s.samples_seen)
    win.close()
    pump()


def tray_click_keeps_pause() -> None:
    """«Старт / пауза» из меню трея во время печати: щелчок по значку (окно Проводника) уже поставил паузу
    «кликом мышью» — пункт меню её оставляет, а не продолжает печать."""
    ED.reset()
    win, s, store = make_window(PROFILE_PLAIN)
    focus(win, store.templates[0])
    DELAY["s"] = 0.03
    try:
        win.printer.toggle()
        wait_for(lambda: win.engine.state == RUNNING, 5)
        MOUSE["clicks"] += 1                     # правый щелчок по значку в трее
        wait_for(lambda: win.engine.state == "paused", 3)
        win.printer.remember_press()             # меню открылось (aboutToShow)
        win.printer.toggle(countdown=0, pressed=True)   # пункт «Старт / пауза»
        pump(0.3)
        st = win.engine.state
    finally:
        DELAY["s"] = 0.0
        win.printer.stop()
    check("меню трея «Старт / пауза» во время печати — пауза остаётся", st == "paused", st)
    win.close()
    pump()


def main() -> int:
    theme.setup(app, "dark")
    tour_sample()   # первым: проверяет новую базу
    smooth_newlines()
    mouse_click_pauses()
    tray_click_keeps_pause()
    steps_blank_chunk()
    notepad_steps()
    bracket_first_on_line()
    closing_tag_tail()
    for profile in (PROFILE_PLAIN, PROFILE_IDE):
        for strip in (False, True):
            steps_lesson(profile, strip)
    lines_block(PROFILE_IDE, False, hotkey_with_ctrl=False)
    lines_block(PROFILE_PLAIN, True, hotkey_with_ctrl=False)
    lines_block(PROFILE_IDE, True, hotkey_with_ctrl=True)
    races()
    prompter_lines()
    notes_never_print()
    plain_in_editor_hint()
    comments_speed()
    check("без исключений", not errors, errors[0].splitlines()[-1] if errors else "")
    print("ГОТОВО" if not failed else f"ОШИБКИ: {failed}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
