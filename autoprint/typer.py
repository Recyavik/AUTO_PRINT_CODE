"""Движок печати: превращает текст в последовательность «единиц» и печатает их в активное окно.

Профиль IDE компенсирует «умные» редакторы (VS Code/Monaco, CodeMirror, Jupyter):
  * перед Enter и перед закрывающими ) ] } " ' ` — Shift+End, пробел, Backspace:
    стирает всё, что редактор сам дописал справа от курсора (автоскобки, автокавычки)
    и закрывает подсказки, чтобы Enter не принял автодополнение. На «перепечатывание»
    автоскобок не полагаемся: в CodeMirror 6 оно ломает тройные кавычки;
  * после Enter — Shift+Home, пробел, Backspace: убирает автоотступ, после чего
    отступ строки печатается ровно как в образце.
Трюк «пробел + Backspace» безопасен и когда выделение пустое (ничего не меняет),
в отличие от Delete, который склеил бы строки.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, replace

from PySide6.QtCore import QObject, Signal

from . import winapi as w
from .human import humanize
from .storage import PROFILE_IDE, PROFILE_PLAIN, PROFILE_TERMINAL, Settings

# Минимальный интервал между нажатиями задаётся настройкой key_gap_ms.
# Замер на Блокноте Windows 11: при 8–12 мс символы теряются и переставляются,
# при 30 мс — набор точный. Редакторы на Electron/браузере ещё чувствительнее.
PUNCT = set(",;:)]}>")
# Профиль IDE: перед этими символами очищается правая часть строки (там может быть
# только то, что редактор дописал сам — автоскобки и автокавычки).
CLEAR_BEFORE = set(")]}\"'`")
# После этих символов редактор может дописать справа закрывающую пару (автоскобки, автокавычки).
OPENERS = set("([{\"'`")
CLOSE_BRACKETS = set(")]}")


def _ident_char(ch: str) -> bool:
    """После буквы, цифры или «_» редактор мог открыть подсказку автодополнения: Enter её бы принял."""
    return bool(ch) and (ch.isalnum() or ch == "_")

log = logging.getLogger(__name__)

IDLE, COUNTDOWN, RUNNING, PAUSED, FINISHED = "idle", "countdown", "running", "paused", "finished"

# окна, где почти всегда редактор кода с автоотступами: профиль «Блокнот» там удвоит отступы и скобки
CODE_EDITOR_EXES = {"code.exe", "code - insiders.exe", "cursor.exe", "windsurf.exe", "msedge.exe", "chrome.exe",
                    "firefox.exe", "brave.exe", "opera.exe", "yandex.exe", "browser.exe", "pycharm64.exe",
                    "idea64.exe", "webstorm64.exe", "sublime_text.exe", "notepad++.exe"}
LINE_WAIT = "line_wait"   # печать по строкам: строка готова, ждём Enter пользователя (или хоткей)

# клавиши перемещения (единицы «nav», печать по шагам) → (vk, модификаторы)
NAV_KEYS = {"ctrl_home": (w.VK_HOME, (w.VK_CONTROL,)), "ctrl_end": (w.VK_END, (w.VK_CONTROL,)),
            "down": (w.VK_DOWN, ()), "up": (w.VK_UP, ()), "end": (w.VK_END, ()), "home": (w.VK_HOME, ()),
            "enter_raw": (w.VK_RETURN, ())}


@dataclass
class Unit:
    kind: str            # char | fast | tab | back | newline | cleanup | nav
    text: str = ""
    src_end: int = 0     # позиция в исходном тексте после этой единицы
    k: float = 1.0       # множитель задержки после единицы (имитация ручного ввода)
    pause: float = 0.0   # пауза перед единицей, с (обдумывание)
    wait: bool = False   # newline: печать по строкам — перед ним ждём Enter пользователя


def build_units(text: str, settings: Settings, line_wait: bool = False, cleanup: bool = True) -> list[Unit]:
    """Текст → единицы печати. line_wait — печать по строкам: после каждой непустой строки ждать Enter
    (пустые строки идут сами). cleanup — в профиле IDE в конце убрать то, что редактор дописал справа."""
    tab = " " * max(1, settings.tab_width)
    units: list[Unit] = []
    src = 0
    lines = text.split("\n")
    for li, line in enumerate(lines):
        if li > 0:
            src += 1
            units.append(Unit("newline", "\n", src, wait=line_wait and bool(lines[li - 1].strip())))
        m = len(line) - len(line.lstrip(" \t"))
        # в терминале Tab — автодополнение, отступ только пробелами
        if m and settings.indent_with_tab and settings.profile != PROFILE_TERMINAL:
            # как человек: Tab на каждый уровень отступа, остаток — пробелами
            col, cols = 0, []      # cols[i] — ширина отступа после i+1 исходных символов
            for ch in line[:m]:
                col += len(tab) if ch == "\t" else 1
                cols.append(col)
            done = 0               # сколько исходных символов отступа уже набрано
            for level in range(1, col // len(tab) + 1):
                done = next(i for i, c in enumerate(cols) if c >= level * len(tab)) + 1
                units.append(Unit("tab", "\t", src + done))
            for i in range(col % len(tab)):
                units.append(Unit("char", " ", src + min(m, done + i + 1)))
        elif m:
            indent = line[:m].replace("\t", tab)
            if settings.fast_indent:
                units.append(Unit("fast", indent, src + m))
            else:
                for i, ch in enumerate(line[:m]):
                    units.append(Unit("char", tab if ch == "\t" else ch, src + i + 1))
        for i, ch in enumerate(line[m:], start=m):
            units.append(Unit("char", tab if ch == "\t" else ch, src + i + 1))
        src += len(line)
    if settings.human_typing:
        units = humanize(units, settings)
    if cleanup and settings.profile == PROFILE_IDE and units:
        units.append(Unit("cleanup", "", src))
    return units


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


class TypingEngine(QObject):
    state_changed = Signal(str)
    progress = Signal(int, int)        # (позиция в исходном тексте, длина)
    message = Signal(str)
    countdown = Signal(int)
    sound = Signal(str)
    finished = Signal()
    target = Signal(str)               # имя exe окна, в которое идёт печать (для пульта)
    interrupted = Signal(str)          # пауза из-за пользователя: "mouse" — клик мышью вне окна программы

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.state = IDLE
        self.pause_reason = ""            # почему последняя пауза: «клик мышью», «нажата клавиша», «сменилось окно»…
        self._text = ""
        self._units: list[Unit] = []
        self._pos = 0
        self._gen = 0
        self._run = threading.Event()    # снят — пауза: поток печати ждёт
        # пауза (GUI-поток) и переход в «печать» (поток печати) — под одной блокировкой,
        # иначе пауза во время отсчёта терялась бы, а состояние показывало «печать»
        self._lock = threading.RLock()
        self._resume_delay = 0.0
        self._resume_countdown = 0
        self._thread: threading.Thread | None = None
        self._builder = None   # как собрать единицы заново (печать по строкам / по шагам)
        self._target_hwnd = 0
        self._line_go = threading.Event()   # печать по строкам: «дальше» (Enter пользователя или хоткей)
        self._line_by_enter = False
        # профиль IDE — что могло остаться в строке редактора (чтобы не делать лишних служебных нажатий):
        self._dirty = False            # справа могут быть дописанные редактором скобки/кавычки
        self._last_ident = False       # последней была буква/цифра — могла открыться подсказка
        self._indent_pending = False   # после Enter — автоотступ редактора ещё не заменён
        self._in_word = self._word_alpha = False   # идёт слово; начато с буквы (у чисел подсказок нет)
        self._typed_on_line = False    # в этой строке уже что-то набрали (после Enter или перехода к месту вставки)
        self._line_text = False        # …и не только отступ
        self.job_key = None    # чем занят движок (id блока) — для UI
        # счётчик нажатий кнопок мыши не над окном программы (guard.InputGuard.click_count, Raw Input):
        # ловит и короткий тап тачпада между опросами кнопок. Клики до старта/продолжения не считаются
        self.click_count = lambda: 0
        self._clicks_seen = 0
        self.auto_paused_at = float("-inf")   # когда печать сама встала на паузу (клик, смена окна)
        # окно — терминал: печать без приёмов профиля IDE (Shift+Home/End дали бы в строке «H» и «F»)
        self._terminal = False
        # печать настоящими клавишами (Windows PowerShell 5.1 в консоли): раскладку задаём сами и помним —
        # консоль не сообщает её честно
        self._keys_hwnd = 0
        self._layout = 0          # какую раскладку мы последней попросили
        self._layout_orig = 0     # вернуть по окончании
        self._profile = ""        # окно, выбранное у блока; пусто — как в настройках
        self._plain_warned: set[str] = set()   # где уже подсказали про профиль «Блокнот» (раз за запуск)

    # ------------------------------------------------------------ API (GUI-поток)
    @property
    def profile(self) -> str:
        """Профиль окна этой печати: выбранный у блока или общий из настроек."""
        return self._profile or self.settings.profile

    def load(self, text: str, profile: str = "", job_key=None, builder=None) -> None:
        """Загружает новый текст. Текущая печать прерывается.
        builder(settings) → единицы — если печатать нужно не «как есть» (по строкам, по шагам);
        тогда text задаёт только длину для шкалы прогресса (позиции src_end — в нём).
        profile — окно, выбранное у блока (пусто — как в настройках)."""
        self._cancel()
        self._text = normalize(text)
        self._builder = builder
        self._profile = profile
        self._units = self._build()
        self._pos = 0
        self._set_state(IDLE)
        self.progress.emit(0, len(self._text))

    def _build(self) -> list[Unit]:
        s = replace(self.settings, profile=self.profile) if self._profile else self.settings   # окно блока
        return self._builder(s) if self._builder else build_units(self._text, s)

    def continue_line(self, by_enter: bool, delay: float = 0.0, countdown: int = 0) -> bool:
        """Печать по строкам: продолжить со следующей строки. by_enter — пользователь сам нажал Enter
        (он уже дошёл до редактора, повторно не нажимаем). Enter в другом окне не считается.
        Хоткей или кнопка — как продолжение после паузы: delay/countdown, ожидание отпускания Ctrl/Shift."""
        if self.state != LINE_WAIT:
            return False
        if by_enter and w.foreground_window() != self._target_hwnd:
            return False
        self._line_by_enter = by_enter
        self._resume_delay, self._resume_countdown = delay, countdown
        self._line_go.set()
        return True

    @property
    def active(self) -> bool:
        """Печать идёт или готовится (отсчёт, задержка хоткея, ожидание отпускания Ctrl/Alt/Shift).
        Ожидание Enter по строкам — не «идёт»: там «дальше», а не пауза."""
        return self.state in (RUNNING, COUNTDOWN) or (self.state != LINE_WAIT and bool(
            self._thread and self._thread.is_alive() and self._run.is_set()))

    def start(self, delay: float = 0.0, countdown: int = 0) -> None:
        """Старт с текущей позиции (с начала, если закончили)."""
        if not self._units:
            self.message.emit("Нечего печатать: выберите непустой блок.")
            return
        if self.state == PAUSED:
            self.resume(delay, countdown)
            return
        if self.state in (RUNNING, COUNTDOWN):
            return
        if self.state == FINISHED:
            self._pos = 0
        self._cancel()
        self._gen += 1
        self._run.set()
        self._thread = threading.Thread(target=self._worker, args=(self._gen, delay, countdown), daemon=True)
        self._thread.start()

    def pause(self, reason: str = "хоткей/кнопка") -> None:
        with self._lock:
            if not self.active:
                return
            self._run.clear()
            self.pause_reason = reason
            self._set_state(PAUSED)
        log.info("Пауза (%s) на %d/%d", reason, self._pos, len(self._units))

    def resume(self, delay: float = 0.0, countdown: int = 0) -> None:
        if self.state != PAUSED:
            return
        if not (self._thread and self._thread.is_alive()):
            self._set_state(IDLE)
            self.start(delay, countdown)
            return
        self._resume_delay = delay
        self._resume_countdown = countdown
        self._run.set()

    def toggle(self, delay: float = 0.0, countdown: int = 0) -> None:
        if self.state == LINE_WAIT:
            self.continue_line(False, delay, countdown)
        elif self.state in (RUNNING, COUNTDOWN):
            self.pause()
        else:
            self.start(delay, countdown)

    def restart(self, delay: float = 0.0, countdown: int = 0) -> None:
        self._cancel()
        self._pos = 0
        self._set_state(IDLE)
        self.progress.emit(0, len(self._text))
        self.start(delay, countdown)

    def stop(self) -> None:
        if self.state not in (IDLE,):
            log.info("Стоп на %d/%d", self._pos, len(self._units))
        self._cancel()
        self._pos = 0
        self._set_state(IDLE)
        self.progress.emit(0, len(self._text))

    def rebuild(self) -> None:
        """Пересобрать единицы после смены настроек (только если печать не идёт)."""
        if self.state in (IDLE, FINISHED) and self._text:
            self._units = self._build()
            self._pos = 0

    # ------------------------------------------------------------ внутреннее
    def _cancel(self) -> None:
        self._gen += 1
        self._run.set()  # разбудить поток, чтобы он увидел смену поколения
        self._line_go.set()
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(1.0)
        self._thread = None
        self._run.clear()

    def _set_state(self, st: str) -> None:
        if self.state != st:
            self.state = st
            self.state_changed.emit(st)

    def _wset(self, gen: int, st: str) -> bool:
        """Смена состояния из рабочего потока — только пока его печать не отменена. Поток, который
        «Стоп» не дождался (ждал отпускания Ctrl), иначе вернул бы «Печатает» уже остановленной печати —
        и защита от нажатий глотала бы клавиши. RUNNING с учётом паузы, поставленной в это же время
        (под той же блокировкой, что и pause(): пауза во время подготовки не теряется)."""
        with self._lock:
            if not self._alive(gen):
                return False
            if st == RUNNING and not self._run.is_set():
                st = PAUSED
            self._set_state(st)
            return True

    def _alive(self, gen: int) -> bool:
        return gen == self._gen

    def _sleep(self, gen: int, seconds: float) -> bool:
        """Сон, прерываемый остановкой (и кликом мышью — пауза). False — если печать отменена."""
        end = time.perf_counter() + seconds
        while True:
            if not self._alive(gen):
                return False
            if self._mouse_interrupt(gen):
                return True
            left = end - time.perf_counter()
            if left <= 0:
                return True
            time.sleep(min(left, 0.02))

    def _think(self, gen: int, seconds: float) -> bool:
        """Пауза-обдумывание: обрывается, если поставили на паузу. False — если печать отменена."""
        end = time.perf_counter() + seconds
        while self._run.is_set():
            if not self._alive(gen):
                return False
            if self._mouse_interrupt(gen):
                break
            left = end - time.perf_counter()
            if left <= 0:
                break
            time.sleep(min(left, 0.02))
        return self._alive(gen)

    def _mouse_interrupt(self, gen: int) -> bool:
        """Клик мышью вне окна программы во время печати — пауза: курсор в редакторе мог сместиться.
        Клики по самой программе (кнопка «Пауза», её меню) не в счёт — они управляют печатью.
        Нажатие видно двумя путями: счётчик Raw Input (ловит и короткий тап) и опрос «кнопка нажата сейчас»."""
        clicks = self.click_count()
        if self.state != RUNNING or not self.settings.guard_enabled or not self._alive(gen):
            self._clicks_seen = clicks
            return False
        clicked, self._clicks_seen = clicks != self._clicks_seen, clicks
        if not clicked and (not w.mouse_pressed() or w.cursor_over_own_window()):
            return False
        self.auto_paused_at = time.monotonic()
        self._pause_from_worker(gen, "клик мышью")
        log.info("Пауза (клик мышью) на %d/%d", self._pos, len(self._units))
        self.interrupted.emit("mouse")
        return True

    def _forget_clicks(self) -> None:
        """Печать (снова) пошла: клики, которыми курсор ставили до этого, — не вмешательство."""
        self._clicks_seen = self.click_count()

    def _prepare(self, gen: int, delay: float, countdown: int, next_line: bool = False) -> int | None:
        """Отсчёт, ожидание отпускания модификаторов, захват целевого окна.
        next_line — продолжение печати по строкам хоткеем: в журнал не пишем (это каждая строка)."""
        if countdown > 0:
            self._wset(gen, COUNTDOWN)
            for n in range(countdown, 0, -1):
                self.countdown.emit(n)
                if not self._think(gen, 1.0):   # секунда отсчёта; обрывается паузой
                    return None
                if not self._run.is_set():
                    log.info("Отсчёт прерван паузой")
                    return None
            self.countdown.emit(0)
        if not w.wait_modifiers_released(cancelled=lambda: not self._alive(gen) or not self._run.is_set()):
            if not self._alive(gen) or not self._run.is_set():
                return None      # «Стоп» или пауза, пока ждали отпускания клавиш
            log.warning("Не начато: модификаторы удерживаются дольше 5 с")
            self.message.emit("Отпустите Ctrl/Alt/Shift — печать не начата.")
            return None
        if not self._alive(gen):   # «Стоп», пока ждали отпускания клавиш
            return None
        if delay and not self._sleep(gen, delay):
            return None
        hwnd = w.foreground_window()
        if w.is_own_window(hwnd):
            log.info("Не начато: в фокусе окно самого AutoPrintCode")
            self.message.emit("Поставьте курсор в Jupyter (или другой редактор) и нажмите хоткей там — "
                              "сейчас впереди окно AutoPrintCode.")
            return None
        if not w.self_elevated() and w.window_elevated(hwnd):
            log.warning("Не начато: окно с правами администратора %s", w.describe_window(hwnd))
            self.message.emit("Окно запущено от имени администратора — Windows не пропустит в него ввод. "
                              "Запустите AutoPrintCode тоже от имени администратора.")
            return None
        self._forget_clicks()
        profile = self.profile
        self._terminal = profile == PROFILE_TERMINAL or (profile == PROFILE_IDE and w.is_terminal_window(hwnd))
        if self._terminal and w.needs_real_keys(hwnd):
            if self._keys_hwnd != hwnd:
                self._keys_hwnd, self._layout, self._layout_orig = hwnd, 0, w.window_layout(hwnd)
            if not next_line:
                log.info("Windows PowerShell в консоли — печать клавишами раскладки")
        else:
            self._keys_hwnd = 0
        if self._terminal and profile == PROFILE_IDE and not next_line:
            log.info("Окно — терминал: приёмы профиля IDE отключены")
            if not self._pos:
                self.message.emit("Печать в терминал: приёмы профиля IDE отключены (иначе в строке появились бы "
                                  "«F» и «H»). Для терминала есть свой профиль «Терминал».")
        if profile == PROFILE_PLAIN and not self._pos and not next_line:
            exe = w.window_process_name(hwnd).lower()
            if exe in CODE_EDITOR_EXES and exe not in self._plain_warned:
                # «Блокнот» печатает как есть, а редактор кода сам ставит отступы и скобки — они удвоятся.
                # Сам не переключаем: в браузере бывает и простое поле (чат, форма) — подсказываем раз за запуск
                self._plain_warned.add(exe)
                log.info("Профиль «Блокнот», а окно — %s: подсказка про профиль IDE", exe)
                self.message.emit("Профиль «Блокнот», а печать идёт в редактор кода или браузер. Если там редактор "
                                  "с автоотступами (VS Code, Jupyter, Colab, веб-IDE), отступы и скобки удвоятся — "
                                  "выберите «IDE» в ⚙ Настройки → Печать или у блока: «⋯ → Куда печатать».")
        if not next_line:
            log.info("Печать %s с %d/%d → %s · профиль=%s · %d симв/мин",
                     "продолжена" if self._pos else "начата", self._pos, len(self._units),
                     w.describe_window(hwnd), profile, self.settings.cpm)
        self.target.emit(w.window_process_name(hwnd))
        self._target_hwnd = hwnd
        return hwnd

    def _pause_from_worker(self, gen: int, reason: str = "") -> None:
        if self._alive(gen):
            self._run.clear()
            self.pause_reason = reason
            self._wset(gen, PAUSED)

    def _worker(self, gen: int, delay: float, countdown: int) -> None:
        self._dirty = self._last_ident = self._indent_pending = self._in_word = self._typed_on_line = False
        self._line_text = False
        target = self._prepare(gen, delay, countdown)
        if target is None:
            if not (self._alive(gen) and not self._run.is_set() and self.state == PAUSED):
                if self._wset(gen, PAUSED if self._pos else IDLE):
                    self._run.clear()
                return
            # пауза во время отсчёта или ожидания отпускания клавиш: остаёмся на паузе, «продолжить»
            # пройдёт подготовку заново (цикл ниже), — а не сбрасываемся в «Готов»
        # паузу могли поставить, пока ждали отпускания клавиш: тогда не «Печатает», а «Пауза» —
        # иначе включится защита от нажатий и проглотит следующую клавишу пользователя (это делает _wset)
        elif not self._wset(gen, RUNNING):
            return
        total = len(self._text)
        thought = -1    # для какой единицы пауза-обдумывание уже выдержана
        waited = -1     # перед какой единицей «дальше» (Enter пользователя или хоткей) уже получено
        entered = -1    # перед какой единицей пользователь сам нажал Enter — повторно не нажимаем
        while self._alive(gen) and self._pos < len(self._units):
            # «Пауза» при поднятом _run — «продолжить» пришло сразу после паузы, которую поставил сам поток
            # (клик, смена окна): всё равно пройти подготовку — окно, отсчёт, состояние «Печатает»
            if not self._run.is_set() or self.state == PAUSED:
                self._run.wait()
                if not self._alive(gen):
                    return
                target = self._prepare(gen, self._resume_delay, self._resume_countdown)
                if target is None:
                    self._pause_from_worker(gen)
                    continue
                if not self._wset(gen, RUNNING) or self.state != RUNNING:   # снова пауза, пока готовились
                    continue
            unit = self._units[self._pos]
            if unit.wait and waited != self._pos:
                # печать по строкам: строка набрана — ждём Enter пользователя или хоткей
                if not self._wait_line(gen):
                    return
                waited = self._pos
                if self._line_by_enter:
                    entered = self._pos
                    time.sleep(self._gap() * 2)   # Enter уже в редакторе — дать ему вставить автоотступ
                else:
                    # хоткей или кнопка «Дальше» — как продолжение после паузы: дождаться, пока отпустят
                    # Ctrl/Shift (иначе Enter уйдёт как Ctrl+Enter, а Shift+End — как Ctrl+Shift+End и
                    # выделит весь хвост файла), проверить окно, при старте кнопкой — отсчёт
                    target = self._prepare(gen, self._resume_delay, self._resume_countdown, next_line=True)
                    if target is None:
                        self._pause_from_worker(gen)
                        continue
                if not self._wset(gen, RUNNING) or self.state != RUNNING:   # паузу поставили, пока готовились
                    continue
            if unit.pause and thought != self._pos:
                # обдумывание: прерывается паузой и остановкой; после него заново проверяем окно
                if not self._think(gen, unit.pause):
                    return
                thought = self._pos
                continue
            if self._mouse_interrupt(gen):
                continue
            fg = w.foreground_window()
            # в окно самой программы печатать нельзя никогда (набор правил бы образец) — даже если
            # автопауза при смене окна выключена
            if fg != target and (self.settings.autopause_on_focus_change or w.is_own_window(fg)):
                self.auto_paused_at = time.monotonic()
                self._pause_from_worker(gen, "сменилось окно")
                log.info("Пауза (сменилось окно → %s) на %d/%d", w.describe_window(fg), self._pos, len(self._units))
                self.message.emit("Пауза: сменилось активное окно. Вернитесь в нужное окно и продолжите.")
                continue
            try:
                self._execute(unit, gen, enter_done=entered == self._pos)
            except OSError as e:
                log.error("Ошибка SendInput на %d/%d: %s", self._pos, len(self._units), e)
                self._pause_from_worker(gen, "ошибка ввода")
                self.message.emit(f"Ошибка ввода: {e}")
                continue
            self._pos += 1
            self.progress.emit(unit.src_end, total)
            if not self._sleep(gen, self._delay_after(unit)):
                return
        self._restore_layout()
        if self._wset(gen, FINISHED):
            log.info("Набор завершён: %d единиц", len(self._units))
            self.finished.emit()

    def _wait_line(self, gen: int) -> bool:
        """Печать по строкам: строка набрана — ждём «дальше». False — если печать отменена."""
        if self.profile == PROFILE_IDE and not self._terminal:
            # убрать дописанное редактором справа (автоскобки, закрывающий тег после «>», « */» после «/**»)
            # и закрыть подсказки — иначе Enter пользователя примет автодополнение вместо новой строки
            if self._indent_pending:
                self._clear_indent()
            else:
                self._clear_right()
        self._line_go.clear()
        self._line_by_enter = False
        if not self._wset(gen, LINE_WAIT):
            return False
        while not self._line_go.wait(0.05):
            if not self._alive(gen):
                return False
        self._forget_clicks()   # щёлкнуть в редакторе, пока ждали Enter, можно: строка пойдёт от курсора
        # сразу «Печатает»: защита снова ловит случайные клавиши, пока ждём отпускания Ctrl после хоткея
        return self._wset(gen, RUNNING)

    def _start_line_text(self, u: Unit) -> None:
        """Профиль IDE: перед первым символом строки убрать автоотступ редактора. Не сразу после Enter, а
        здесь — иначе во время паузы «на обдумывание» строка стояла бы без отступа, а потом он впрыгивал
        (рывок). Автоотступ выделяется (Shift+Home), и первый набранный символ его заменяет."""
        self._indent_pending = False
        swap = u.kind == "fast" or (u.kind == "char" and u.text not in OPENERS and u.text not in CLEAR_BEFORE)
        if swap:
            w.tap(w.VK_HOME, w.VK_SHIFT)
            time.sleep(self._gap())
        else:   # Tab с выделением сдвинул бы строки, а скобка/кавычка — «обернула» бы выделение
            self._clear_indent()

    def _execute(self, u: Unit, gen: int | None = None, enter_done: bool = False) -> None:
        s = self.settings
        ide = self.profile == PROFILE_IDE and not self._terminal
        if ide and self._indent_pending and u.kind not in ("newline", "cleanup", "nav"):
            self._start_line_text(u)
        if u.kind in ("char", "fast", "tab", "back"):
            self._typed_on_line = True
        if u.kind == "char":
            if ide and u.text in CLEAR_BEFORE:
                # не полагаемся на «перепечатывание» автоскобок — оно у редакторов разное
                # (CodeMirror 6 ломает тройные кавычки): убираем дописанное справа и вставляем символ.
                # Но только когда справа может что-то быть — лишние нажатия видны как дёрганье.
                if self._last_ident:
                    self._clear_right()      # могла открыться подсказка автодополнения — закрыть
                elif u.text in CLOSE_BRACKETS and not self._line_text:
                    # закрывающая скобка — первая в строке (после отступа): без «пробел + стереть» перед ней
                    # VS Code переставляет отступ строки по своим правилам (уровень 4 пробела) — «  }» из
                    # образца с отступом в 2 пробела становилась «}» (проверено на настоящем VS Code)
                    self._clear_right()
                elif self._dirty:
                    if u.text in CLOSE_BRACKETS:
                        w.tap(w.VK_END, w.VK_SHIFT)   # выделить дописанное — скобка его заменит
                        time.sleep(self._gap())
                    else:
                        self._clear_right()  # кавычка с выделением «обернула» бы его
                self._dirty = False
            self._char(u.text) if len(u.text) == 1 else self._fast(u.text, gen)
            self.sound.emit("space" if u.text == " " else "key")
            if u.text.strip():
                self._line_text = True
            if ide:
                ch = u.text[-1:]
                if ch in OPENERS:
                    self._dirty = True      # редактор мог дописать справа закрывающую пару
                if _ident_char(ch):
                    if not self._in_word:   # подсказки бывают у слов с буквы/«_», у чисел — нет
                        self._in_word, self._word_alpha = True, not ch.isdigit()
                    self._last_ident = self._word_alpha
                else:
                    self._in_word = self._last_ident = False
        elif u.kind == "fast":
            self.sound.emit("space")
            self._fast(u.text, gen)
            self._last_ident = self._in_word = False
        elif u.kind == "tab":
            if self._terminal:   # Tab в терминале — автодополнение
                self._fast(" " * max(1, s.tab_width))
            else:
                w.tap(w.VK_TAB)
            self.sound.emit("key")
            self._last_ident = self._in_word = False
        elif u.kind == "back":
            w.tap(w.VK_BACK)
            self.sound.emit("key")
        elif u.kind == "nav":
            # печать по шагам: перейти к месту вставки (без звука — так обычно щёлкают мышью)
            if ide and self._indent_pending:
                self._clear_indent()   # кусок из одной пустой строки: автоотступ не оставлять в ней
            vk, mods = NAV_KEYS[u.text]
            w.tap(vk, *mods)
            self._typed_on_line = self._line_text = False
        elif u.kind == "newline":
            if not enter_done:   # печать по строкам: Enter пользователь уже нажал сам
                if ide:
                    if s.esc_before_enter:
                        w.tap(w.VK_ESCAPE)
                        time.sleep(self._gap())
                    if self._indent_pending:
                        # пустая строка: автоотступ выделить — Enter заменит его, хвостов пробелов не будет
                        w.tap(w.VK_HOME, w.VK_SHIFT)
                        time.sleep(self._gap())
                    elif self._last_ident:
                        self._clear_right()   # закрыть подсказку: иначе Enter её примет; заодно хвост
                    elif self._typed_on_line:
                        # что редактор дописал справа (скобки, кавычки, закрывающий тег после «>», « */»
                        # после «/**») — выделить, Enter заменит. Если справа пусто, нажатие ничего не меняет.
                        # Только если в строке что-то набрали: сразу после перехода к месту вставки (↑/↓, End)
                        # Блокнот Windows 11 выделил бы Shift+End ещё и перенос строки — Enter заменил бы его,
                        # и следующая строка документа пропала бы под набранным текстом
                        w.tap(w.VK_END, w.VK_SHIFT)
                        time.sleep(self._gap())
                w.tap(w.VK_RETURN)
                self.sound.emit("enter")
            self._dirty = self._last_ident = self._in_word = self._typed_on_line = self._line_text = False
            if ide:
                time.sleep(self._gap() * 2)  # дать редактору вставить автоотступ
                self._indent_pending = True   # уберём его перед первым символом новой строки
        elif u.kind == "cleanup":
            if ide:
                if self._indent_pending:
                    self._clear_indent()
                else:
                    self._clear_right()   # конец печати: хвост, дописанный редактором, и подсказки — убрать
            self._indent_pending = self._dirty = self._last_ident = False

    def _clear_right(self) -> None:
        """Стереть всё справа от курсора до конца строки и закрыть подсказки: Shift+End, пробел, Backspace.
        Безопасно и при пустом выделении (в отличие от Delete, который склеил бы строки)."""
        w.tap(w.VK_END, w.VK_SHIFT)
        time.sleep(self._gap())
        w.type_char(" ")
        time.sleep(self._gap())
        w.tap(w.VK_BACK)
        time.sleep(self._gap())
        self._dirty = self._last_ident = self._in_word = False

    def _clear_indent(self) -> None:
        """Убрать автоотступ в начале строки: Shift+Home, пробел, Backspace."""
        w.tap(w.VK_HOME, w.VK_SHIFT)
        time.sleep(self._gap())
        w.type_char(" ")
        time.sleep(self._gap())
        w.tap(w.VK_BACK)
        time.sleep(self._gap())
        self._indent_pending = False

    def _gap(self) -> float:
        return max(5, self.settings.key_gap_ms) / 1000

    def _fast(self, text: str, gen: int | None = None) -> None:
        for ch in text:
            if gen is not None and not self._alive(gen):
                return   # стоп посреди длинного отступа — дальше не печатаем
            self._char(ch)
            time.sleep(self._gap())

    def _char(self, ch: str) -> None:
        if not self._keys_hwnd:
            w.type_char(ch)
            return
        # текущая раскладка, иначе первая, где есть такая клавиша (как человек переключает Alt+Shift)
        layouts = ([self._layout] if self._layout else []) + [x for x in w.keyboard_layouts() if x != self._layout]
        layout = next((x for x in layouts if w.key_for(ch, x) is not None), 0)
        if not layout:
            w.type_char(ch)       # символа нет ни в одной раскладке — как получится
            return
        self._switch_layout(layout)
        w.type_key(ch, w.key_for(ch, layout))

    def _switch_layout(self, layout: int) -> None:
        if layout != self._layout:
            w.request_layout(self._keys_hwnd, layout)
            time.sleep(0.15)      # окно меняет раскладку не сразу
            self._layout = layout

    def _restore_layout(self) -> None:
        if self._keys_hwnd and self._layout and self._layout_orig and self._layout != self._layout_orig:
            self._switch_layout(self._layout_orig)

    def _delay_after(self, u: Unit) -> float:
        s = self.settings
        base = 60.0 / max(30, s.cpm)
        j = max(0, min(90, s.jitter)) / 100
        if s.human_typing:
            # ритм (очереди слов и паузы между ними) задаёт human.py через k. Внутри слова k < 1 — шум
            # слабый, чтобы очередь оставалась ровной; на промежутках (k ≥ 2) — полный, разброс там уместен.
            # Логнормальный множитель со средним 1 — скорость в среднем не меняется
            lo, hi = 0.06 + 0.2 * j, 0.1 + 0.5 * j
            sigma = lo + (hi - lo) * min(1.0, max(0.0, u.k - 1.0))
            d = base * u.k * random.lognormvariate(-sigma * sigma / 2, sigma)
        else:
            d = base * random.uniform(1 - j, 1 + j)
        if u.kind == "newline":
            d += s.newline_pause_ms / 1000
        elif u.kind == "char" and u.text in PUNCT:
            d += s.punct_pause_ms / 1000
        elif u.kind == "fast":
            d = base * 0.5
        elif u.kind == "nav":
            d = self._gap() * 1.5   # перемещение — быстрая служебная очередь
        elif u.kind == "cleanup":
            d = 0
        return max(d, self._gap())
