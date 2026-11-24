"""Печать урока по хоткеям: что печатать, ход печати, шаги. Без виджетов — окно программы и экран урока
показывают состояние (snapshot) и шлют команды.

Печатается только код. Урок в фокусе — идущий урок («Эфир»), иначе открытый на экране урока. Следующий к
печати — Template.active_block (всегда блок кода); напечатали блок — указатель сам встаёт на следующий код.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from PySide6.QtCore import QObject, Signal

from .. import steps as S
from ..comments import comment_spans, comment_text, strip_comments
from ..printing import typing_slice
from ..sounds import KeySoundPlayer
from ..storage import BLOCK_CODE, PROFILES, Block, Settings, Template, is_printable
from ..typer import COUNTDOWN, FINISHED, IDLE, LINE_WAIT, PAUSED, RUNNING, TypingEngine, build_units

log = logging.getLogger(__name__)

BUSY = (RUNNING, COUNTDOWN, PAUSED, LINE_WAIT)
MODE_BLOCK, MODE_LINES, MODE_STEPS = "block", "lines", "steps"
MODES = (MODE_BLOCK, MODE_LINES, MODE_STEPS)
# настройки, после которых уже подготовленный текст нужно собрать заново
REBUILD_KEYS = {"profile", "strip_comments", "human_typing", "typos_per_100", "think_pause_s", "tab_width",
                "fast_indent", "indent_with_tab", "selection_whole_lines", "print_mode", "step_nav"}
# «Печать ⚙» на экране урока: короткое имя → поле настроек
OPTIONS = {"mode": "print_mode", "cpm": "cpm", "human": "human_typing", "sound": "sound_enabled",
           "strip": "strip_comments"}


# exe окна → как его назвать
APP_NAMES = {"code": "VS Code", "notepad": "Блокнот", "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox",
             "pycharm64": "PyCharm", "idea64": "IntelliJ IDEA", "windowsterminal": "Терминал",
             "sublime_text": "Sublime Text", "notepad++": "Notepad++", "yandex": "Яндекс Браузер",
             "browser": "Яндекс Браузер", "opera": "Opera", "cursor": "Cursor", "pythonw": "Python",
             "python": "Python", "jupyter-lab": "JupyterLab"}


def app_name(exe: str) -> str:
    base = exe.rsplit("\\", 1)[-1]
    if base.lower().endswith(".exe"):
        base = base[:-4]
    return APP_NAMES.get(base.lower(), base or "окно")


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 10 < n < 20:
        return many
    n %= 10
    return one if n == 1 else few if 2 <= n <= 4 else many


class PrintController(QObject):
    changed = Signal()                  # указатель, ход или состояние печати — экран урока и окно перерисовать
    notify = Signal(str, bool, bool)    # текст, предупреждение, тихо (без уведомления Windows)
    state = Signal(str)                 # состояние движка — значок в трее, заголовок окна
    store_changed = Signal()            # указатель сдвинулся — базу сохранить
    settings_touched = Signal()         # настройку поменяли отсюда — сохранить и показать в окне настроек

    def __init__(self, settings: Settings, store, guard, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.s = settings
        self.store = store
        self.engine = TypingEngine(settings)
        self.player = KeySoundPlayer(settings.sound_style, settings.sound_volume, settings.sound_enabled)
        self.engine.sound.connect(self.player.play)
        self.engine.state_changed.connect(self._on_state)
        self.engine.progress.connect(self._on_progress)
        self.engine.message.connect(lambda t: self.notify.emit(t, True, False))
        self.engine.countdown.connect(self._on_countdown)
        self.engine.finished.connect(self._on_finished)
        self.engine.target.connect(self._on_target)
        self.engine.interrupted.connect(lambda _kind: self.notify.emit("Пауза: вы кликнули мышью.", False, True))
        self.guard = guard
        self.engine.click_count = guard.click_count   # клики мышью во время печати (Raw Input)
        guard.tripped.connect(self._on_guard)
        guard.enter_pressed.connect(lambda: self.engine.continue_line(by_enter=True))
        self.job: dict | None = None    # {kind, tid, bid, base, text, omap, src_len[, step]}
        self.target = ""                # в какое окно идёт печать (для подписи)
        self.countdown_n = 0
        self.step_next: dict[str, int | None] = {}   # id блока → какой шаг печатать следующим (None — все)
        self.last = ""                  # последний напечатанный блок (Ctrl+F10 — ещё раз)
        self.focus_id = ""
        self.live_id: Callable[[], str] = lambda: ""   # id идущего урока (ставит окно программы — от «Эфира»)
        self._analysis: tuple | None = None
        self._last_pos = 0
        self._line_info: tuple[int, int] | None = None
        self._press_state: str | None = None

    # ================================================================ урок в фокусе
    def focus(self) -> Template | None:
        lid = self.live_id() or ""
        t = self.store.get(lid) if lid else None
        if t is not None:
            return t
        return self.store.get(self.focus_id) if self.focus_id else None

    def set_focus(self, tid: str) -> None:
        if tid == self.focus_id:
            return
        self.focus_id = tid
        self.on_store_changed()
        self.changed.emit()

    def armed(self) -> tuple[Template, Block] | None:
        """Следующий к печати → (урок, блок кода) или None."""
        t = self.focus()
        if t is None or not t.active_block:
            return None
        b = t.find_block(t.active_block)
        return (t, b) if b is not None and b.type == BLOCK_CODE else None

    def find_block(self, bid: str) -> tuple[Template | None, Block | None]:
        for t in self.store.templates:
            b = t.find_block(bid)
            if b:
                return t, b
        return None, None

    def on_store_changed(self) -> None:
        """Урок поменяли (правка, удаление, другой урок в фокусе): печатающийся блок пропал или он не из урока
        в фокусе — печать останавливается, недопечатывать то, чего уже нет."""
        job = self.job
        if not job or self.engine.state not in BUSY:
            return
        t = self.focus()
        b = t.find_block(job["bid"]) if t is not None else None
        if t is None or t.id != job["tid"] or b is None or b.type != BLOCK_CODE:
            self.stop()

    # ================================================================ указатель
    def arm(self, bid: str) -> bool:
        """Сделать блок кода следующим к печати. Заметку или картинку — нельзя (False)."""
        t = self.focus()
        b = t.find_block(bid) if t is not None else None
        if b is None or b.type != BLOCK_CODE:
            return False
        if t.active_block == bid:
            return True
        if self.job and self.job.get("bid") != bid and self.engine.state in BUSY:
            self.stop()
        t.active_block = bid
        self._invalidate_job_if_idle()
        self.store_changed.emit()
        self.changed.emit()
        return True

    def _set_pointer(self, t: Template, block: Block | None) -> None:
        t.active_block = block.id if block is not None else ""
        self.store_changed.emit()

    def step(self, d: int) -> None:
        """Ctrl+F12 / Ctrl+Shift+F12: следующий / предыдущий блок кода урока."""
        t = self.focus()
        if t is None:
            return
        cur = t.active_block if self.armed() else ""
        if cur:
            nxt = t.next_code(cur, back=d < 0)
        elif self.last and t.find_block(self.last):       # всё напечатано: вперёд — от последнего напечатанного
            nxt = t.next_code(self.last) if d > 0 else t.find_block(self.last)
        else:
            nxt = t.next_code() if d > 0 else None
        if nxt is None:
            return        # на краю урока переходить некуда — печать на паузе не сбрасываем
        if self.engine.state in BUSY:
            self.stop()
        self._set_pointer(t, nxt)
        self._invalidate_job_if_idle()
        codes = [b for b in t.blocks if is_printable(b)]
        where = f" ({codes.index(nxt) + 1} из {len(codes)})" if nxt in codes else ""
        self.notify.emit(f"Следующим: {nxt.display_title(t.code_number(nxt))}{where}", False, False)
        self.changed.emit()

    # ================================================================ что печатать
    def _typing_text(self, block: Block) -> tuple[str, int, list | None, int, str]:
        """Что печатать из блока «целиком» или «по строкам» → (текст, смещение в блоке, карта позиций
        без комментариев, длина куска в блоке, описание)."""
        text, base = typing_slice(block.text, block.sel, self.s.selection_whole_lines)
        src_len, omap = len(text), None
        part = "выделенные строки" if block.sel else "весь блок"
        if self.s.strip_comments:
            text, omap = strip_comments(text, block.lang)
            part += ", без комментариев"
        return text, base, omap, src_len, part

    # ---- по шагам: какой шаг следующий
    @staticmethod
    def _block_steps(block: Block) -> list[int]:
        return S.step_numbers(block.steps, block.text.count("\n") + 1)

    def step_pointer(self, bid: str) -> int | None:
        """Какой шаг блока печатать следующим; None — все шаги напечатаны."""
        _t, b = self.find_block(bid)
        if not b:
            return None
        nums = self._block_steps(b)
        if bid not in self.step_next:
            return nums[0]
        k = self.step_next[bid]
        if k is None:
            return None
        return next((n for n in nums if n >= k), None)   # разметку поменяли — ближайший следующий

    def _step_index(self, block: Block, k: int | None) -> tuple[int, int]:
        nums = self._block_steps(block)
        return (nums.index(k) + 1 if k in nums else len(nums)), len(nums)

    def set_step_pointer(self, bid: str, k: int | None) -> None:
        if self.job and self.job["bid"] == bid and self.engine.state in BUSY:
            self.stop()
        self.step_next[bid] = k
        self._invalidate_job_if_idle()
        self.changed.emit()

    def _lines_of(self, block: Block) -> list:
        """Разбор блока по шагам (с учётом «Без комментариев»). Запоминается: экран урока спрашивает его на
        каждое изменение, а в большом блоке разбор не бесплатный."""
        strip = self.s.strip_comments
        key = (block.id, block.text, tuple(block.steps), block.lang, strip)
        if self._analysis is None or self._analysis[0] != key:
            self._analysis = (key, S.analyze(block.text, block.steps, block.lang, strip))
        return self._analysis[1]

    def _advance_step(self, bid: str, k: int) -> int | None:
        """Шаг k напечатан → указатель на следующий. Возвращает его (None — шаги кончились)."""
        _t, b = self.find_block(bid)
        nums = self._block_steps(b) if b else []
        nxt = next((n for n in nums if n > k), None)
        self.step_next[bid] = nxt
        return nxt

    def step_back(self) -> None:
        """Шаг назад без печати: следующим снова будет предыдущий шаг (чтобы переснять его)."""
        a = self.armed()
        t = self.focus()
        if a is None and t is not None and self.last and t.find_block(self.last) and self.s.print_mode == MODE_STEPS:
            # блок допечатан, указатель ушёл дальше — шаг назад возвращает к последнему шагу этого блока
            self._set_pointer(t, t.find_block(self.last))
            a = self.armed()
        if self.s.print_mode != MODE_STEPS or not a:
            self.notify.emit("«Шаг назад» работает в режиме «По шагам» у блока кода.", False, False)
            return
        _t, block = a
        if self.engine.state in BUSY:
            self.stop()
        nums = self._block_steps(block)
        k = self.step_pointer(block.id)
        prev = nums[-1] if k is None else next((n for n in reversed(nums) if n < k), nums[0])
        self.set_step_pointer(block.id, prev)
        i, n = self._step_index(block, prev)
        where = ""
        if self.s.step_nav != "home":
            # стрелки отсчитываются от курсора: после стирания он мог остаться где угодно — подскажем где
            lines = self._lines_of(block)
            cur = S.cursor_before(lines, prev)
            if cur is None:
                where = " и поставьте курсор туда, где начинался урок"
            else:
                doc = [sl.typed for sl in lines if sl.typed is not None and sl.step < prev]
                txt = doc[cur].strip()
                txt = f" «{txt[:40]}{'…' if len(txt) > 40 else ''}»" if txt else " (пустой)"
                where = f", затем поставьте курсор в конец строки {cur + 1} урока{txt}"
        self.notify.emit(f"Следующим будет шаг {i} из {n}. Если он уже напечатан — сотрите его в редакторе{where}.",
                         False, False)

    # ---- по строкам: что дальше
    def _lines_next(self, block: Block) -> dict | None:
        """По строкам: следующая непустая строка и комментарии перед ней → {i, n, say, src_line}
        (i — номер строки задания, src_line — строка блока с 1; i == 0 — строки кончились). None — печатать нечего."""
        busy = self.engine.state in BUSY and self.job and self.job["bid"] == block.id
        job = self.job if busy and self.job.get("kind") == MODE_LINES else self.job_for_armed()
        if not job or job.get("kind") != MODE_LINES or job["bid"] != block.id:
            return None
        text = job["text"]
        rows = text.split("\n")
        pos = self._last_pos if busy else 0
        cur = text.count("\n", 0, pos) if busy and pos else -1
        nxt = next((r for r in range(cur + 1, len(rows)) if rows[r].strip()), None)
        if nxt is None:
            return {"i": 0, "n": len(rows), "say": [], "src_line": 0}
        starts = [0]
        for r in rows[:-1]:
            starts.append(starts[-1] + len(r) + 1)

        def src(i: int) -> int:   # позиция в тексте задания → в тексте блока
            omap = job["omap"]
            if omap is not None:
                i = omap[i] if i < len(omap) else job["src_len"]
            return job["base"] + i

        def row_start(r: int) -> int:
            """Начало строки r задания в тексте блока. Через «\\n» перед ней: он стоит сразу перед
            этой строкой исходника — после вырезанных строк-комментариев, а не перед ними."""
            if r == 0:
                return src(0) if rows[0] else job["base"]
            return src(starts[r] - 1) + 1

        def line_end(i: int) -> int:
            e = block.text.find("\n", i)
            return len(block.text) if e < 0 else e

        # что сказать: строки-комментарии после напечатанной строки (её хвостовой комментарий уже звучал)
        # и до конца следующей — вместе с её хвостовым комментарием, как и по шагам
        a_src = line_end(row_start(cur)) if cur >= 0 else job["base"]
        start = row_start(nxt)
        b_end = line_end(start)
        say = [comment_text(block.text[x:y]) for x, y in comment_spans(block.text, block.lang)
               if a_src <= x < b_end] if self.s.strip_comments else []
        # строка блока, с которой начинается следующая строка задания (пропуская вырезанные комментарии)
        first = block.text.count("\n", 0, max(0, min(len(block.text), start))) + 1
        return {"i": nxt + 1, "n": len(rows), "say": [t for t in say if t], "src_line": first}

    # ---- задание на печать
    def job_for_armed(self) -> dict | None:
        a = self.armed()
        if not a:
            return None
        t, block = a
        mode = self.s.print_mode
        profile = block.profile if block.profile in PROFILES else ""   # окно, выбранное у блока
        if mode == MODE_STEPS:
            k = self.step_pointer(block.id)
            if k is None or not block.text.strip():   # пустой блок — «нечего печатать», а не «шаг без кода»
                return None
            text, st, lang = block.text, list(block.steps), block.lang

            def build(s: Settings, text=text, st=st, lang=lang, k=k):
                return S.build_step_units(S.analyze(text, st, lang, s.strip_comments), k, s, s.step_nav)
            job = {"kind": MODE_STEPS, "tid": t.id, "bid": block.id, "step": k, "base": 0, "text": text,
                   "omap": None, "src_len": len(text), "builder": build, "profile": profile,
                   "key": (tuple(st), k, self.s.strip_comments, self.s.step_nav)}
            if not build(self.s):
                job["empty"] = True   # в шаге только комментарии — печатать нечего, это «слова»
            return job
        text, base, omap, src_len, _part = self._typing_text(block)
        if not text.strip():
            return None
        builder = None
        if mode == MODE_LINES:
            def builder(s: Settings, text=text):
                return build_units(text, s, line_wait=True)
        return {"kind": mode, "tid": t.id, "bid": block.id, "base": base, "text": text, "omap": omap,
                "src_len": src_len, "builder": builder, "key": None, "profile": profile}

    def _same_job(self, job: dict | None) -> bool:
        return bool(job and self.job and all(job.get(k) == self.job.get(k)
                                             for k in ("kind", "tid", "bid", "base", "text", "key", "profile")))

    def _load_job(self, job: dict) -> None:
        self._clear_progress()
        self.job = job
        self.engine.load(job["text"], job.get("profile", ""), job_key=job["bid"], builder=job.get("builder"))

    def _invalidate_job_if_idle(self) -> None:
        if self.engine.state in (IDLE, FINISHED):
            self.job = None

    def _start_params(self, countdown: int | None) -> tuple[float, int]:
        if countdown:
            return 0.0, countdown
        return self.s.hotkey_start_delay_ms / 1000, 0

    def _skip_empty_step(self, job: dict) -> None:
        """Шаг без кода (одни комментарии-слова): отмечаем сказанным и переходим к следующему."""
        _t, b = self.find_block(job["bid"])
        i, n = self._step_index(b, job["step"]) if b else (0, 0)
        nxt = self._advance_step(job["bid"], job["step"])
        tail = f" Дальше — шаг {i + 1}." if nxt is not None else " Шаги кончились."
        self.notify.emit(f"Шаг {i} из {n} — только слова, кода в нём нет.{tail}", False, False)
        if nxt is None:
            self._block_done(job)
        self.changed.emit()

    def remember_press(self) -> None:
        """Состояние в момент открытия меню трея: щелчок по значку — «клик мышью» и «сменилось окно»,
        печать сама встаёт на паузу. До щелчка печать шла — «Старт / пауза» должна оставить паузу."""
        st = self.engine.state
        if st == PAUSED and time.monotonic() - self.engine.auto_paused_at < 1.0:
            st = RUNNING
        self._press_state = st

    # ================================================================ команды
    def toggle(self, countdown: int | None = None, pressed: bool = False) -> None:
        """Ctrl+F9: старт, пауза, продолжить, «следующая строка»."""
        st = self.engine.state
        press_state, self._press_state = self._press_state, None
        if pressed and press_state in (RUNNING, COUNTDOWN) and st not in (RUNNING, COUNTDOWN):
            # «Старт / пауза» в трее во время печати — оставить паузу, а не продолжить
            if st == PAUSED:
                self.notify.emit("Пауза.", False, True)
            return
        if st == LINE_WAIT:
            # по строкам: хоткей = «следующая строка» — как продолжение после паузы
            self.engine.continue_line(False, *self._start_params(countdown))
            return
        if self.engine.active:   # печать идёт или готовится — пауза
            self.engine.pause()
            return
        if not self.armed() and st != PAUSED and not self._arm_first():
            return
        a = self.armed()
        if a and self.s.print_mode == MODE_STEPS and self.step_pointer(a[1].id) is None and st != PAUSED:
            self.notify.emit(f"Все шаги блока напечатаны. {self.s.hotkey_restart or 'Ctrl+F10'} — сначала, "
                             f"{self.s.hotkey_next_block or 'Ctrl+F12'} — следующий блок.", False, False)
            return
        job = self.job_for_armed()
        if job is None:
            self.notify.emit("Нечего печатать: блок кода пустой.", True, False)
            return
        if st == PAUSED and self._same_job(job):
            self.engine.resume(*self._start_params(countdown))
            return
        if job.get("empty"):
            if st == PAUSED:
                self.stop()   # на паузе стоит другое задание — его уже не продолжить
            self._skip_empty_step(job)
            return
        if not self._same_job(job) or st == FINISHED or st == PAUSED:
            if st == PAUSED:
                self.notify.emit("Текст для печати изменился (урок, выделение или настройки) — "
                                 "печать начнётся с начала.", False, False)
            self._load_job(job)
        self.engine.start(*self._start_params(countdown))

    def _arm_first(self) -> bool:
        """Указателя нет: урок ещё не печатали — следующим становится первый код. Весь код напечатан или
        урока нет — сообщить и ничего не печатать."""
        t = self.focus()
        if t is None:
            self.notify.emit("Откройте урок — печатается его код.", True, False)
            return False
        first = t.next_code()
        if first is None:
            self.notify.emit("В уроке нет кода — печатать нечего.", True, False)
            return False
        if self.last and t.find_block(self.last):
            nxt = t.next_code(self.last)         # после напечатанного могли дописать код
            if nxt is None:
                self.notify.emit(f"Весь код урока напечатан. {self.s.hotkey_restart or 'Ctrl+F10'} — ещё раз "
                                 "последний блок.", False, False)
                return False
            first = nxt
        self._set_pointer(t, first)
        return True

    def restart(self) -> None:
        """Ctrl+F10: во время печати или на паузе — этот блок заново; после — снова последний напечатанный
        (без печати: следующим, Ctrl+F9 — напечатать)."""
        busy = self.job is not None and self.engine.state in BUSY
        if busy:
            job = self.job
            _t, b = self.find_block(job["bid"])
            if b is not None and self.s.print_mode == MODE_STEPS:
                self.step_next[b.id] = self._block_steps(b)[0]
            job = self.job_for_armed() or job
            if job.get("empty"):
                self.stop()
                self._skip_empty_step(job)
                return
            self._load_job(job)
            self.engine.restart(*self._start_params(None))
            return
        t = self.focus()
        b = t.find_block(self.last) if t is not None and self.last else None
        if b is None or b.type != BLOCK_CODE:
            self.notify.emit("Ещё ничего не напечатано — Ctrl+F9 печатает следующий код.", False, False)
            return
        self.step_next.pop(b.id, None)       # по шагам — снова с первого шага
        self._set_pointer(t, b)
        self._invalidate_job_if_idle()
        self.notify.emit(f"Ещё раз: {b.display_title(t.code_number(b))} — {self.s.hotkey_toggle or 'Ctrl+F9'}.",
                         False, False)
        self.changed.emit()

    def stop(self) -> None:
        self.engine.stop()
        self._clear_progress()
        self.job = None
        self.changed.emit()

    def on_hotkey(self, action: str) -> bool:
        """Хоткей печати → команда. False — хоткей не про печать."""
        cmds = {"hotkey_toggle": self.toggle, "hotkey_restart": self.restart, "hotkey_stop": self.stop,
                "hotkey_next_block": lambda: self.step(+1), "hotkey_prev_block": lambda: self.step(-1),
                "hotkey_step_back": self.step_back}
        f = cmds.get(action)
        if f is None:
            return False
        f()
        return True

    # ================================================================ настройки
    def set_option(self, key: str, value) -> bool:
        """«Печать ⚙» на экране урока: mode | cpm | human | sound | strip. False — неверное значение."""
        field = OPTIONS.get(key)
        if field is None:
            return False
        if key == "mode":
            if value not in MODES:
                return False
        elif key == "cpm":
            try:
                value = max(30, min(3000, int(value)))
            except (TypeError, ValueError):
                return False
        else:
            value = bool(value)
        if getattr(self.s, field) == value:
            return True
        setattr(self.s, field, value)
        self.on_settings_changed(field)
        self.settings_touched.emit()
        return True

    def on_settings_changed(self, key: str) -> None:
        """Настройку поменяли (окно настроек или «Печать ⚙»)."""
        s = self.s
        if key == "print_mode" and self.engine.state in BUSY:
            self.stop()   # задание прежнего режима не продолжаем
        if key in REBUILD_KEYS:
            self._invalidate_job_if_idle()
        if key == "sound_enabled":
            self.player.enabled = s.sound_enabled
        elif key == "sound_volume":
            self.player.set_volume(s.sound_volume)
        elif key == "sound_style":
            self.player.set_style(s.sound_style)
        self.engine.rebuild()
        self.changed.emit()

    def apply_settings(self) -> None:
        """Все настройки заново (окно настроек закрыли, тема, запуск)."""
        s = self.s
        self.player.enabled = s.sound_enabled
        self.player.set_style(s.sound_style)
        self.player.set_volume(s.sound_volume)
        self.guard.enabled = s.guard_enabled
        self.engine.rebuild()
        self.changed.emit()

    # ================================================================ сигналы движка
    def _on_guard(self, kind: str) -> None:
        if self.engine.state != RUNNING:
            # защита осталась включённой, хотя печать уже стоит (запоздалый сигнал) — снять, иначе
            # хук глотал бы все клавиши пользователя
            self.guard.disarm()
            return
        self.engine.pause("нажата клавиша" if kind == "key" else "клик мышью")
        self.notify.emit("Пауза: вы нажали клавишу." if kind == "key" else "Пауза: вы кликнули мышью.", False, True)

    def _on_target(self, exe: str) -> None:
        self.target = app_name(exe)

    def _on_state(self, _signalled: str = "") -> None:
        # сигналы из потока печати приходят с опозданием: после «Стоп» может прийти запоздалое
        # «Печатает». Поэтому — только текущее состояние движка, иначе защита включится у стоящей печати
        st = self.engine.state
        if st == RUNNING and self.s.guard_enabled:
            self.guard.arm()
        else:
            self.guard.disarm()
        self.guard.watch_enter(st == LINE_WAIT)   # по строкам: ждём Enter пользователя
        if st == IDLE:
            self._clear_progress()
        if st != COUNTDOWN:
            self.countdown_n = 0
        self.state.emit(st)
        self.changed.emit()

    def _on_progress(self, pos: int, total: int) -> None:
        self._last_pos = pos
        # загрузка задания тоже шлёт progress(0) — ход считаем, только когда печать действительно идёт
        if self.engine.state in BUSY and self.job:
            text = self.job["text"]
            p = max(0, min(pos, len(text)))
            self._line_info = None if self.job.get("kind") == MODE_STEPS else \
                (text.count("\n", 0, p) + 1, text.count("\n") + 1)
            self.changed.emit()

    def _clear_progress(self) -> None:
        self._last_pos = 0
        self._line_info = None

    def _on_countdown(self, n: int) -> None:
        if self.engine.state == COUNTDOWN:   # после паузы отсчёт не возвращаем
            self.countdown_n = n
            self.changed.emit()

    def _on_finished(self) -> None:
        job = self.job
        if job and job.get("kind") == MODE_STEPS:
            _t, b = self.find_block(job["bid"])
            i, n = self._step_index(b, job["step"]) if b else (0, 0)
            nxt = self._advance_step(job["bid"], job["step"])
            self.job = None
            if nxt is not None:
                self.notify.emit(f"Шаг {i} из {n} напечатан. Дальше — шаг {i + 1}.", False, True)
                self.changed.emit()
                return
            self.notify.emit("Шаг напечатан — он был единственным." if n == 1 else
                             f"Все {n} {_plural(n, 'шаг', 'шага', 'шагов')} напечатаны.", False, True)
        if job:
            self._block_done(job)
        self.changed.emit()

    def _block_done(self, job: dict) -> None:
        """Блок напечатан: следующим становится следующий код урока."""
        self.last = job["bid"]
        t = self.store.get(job["tid"])
        if t is None:
            return
        nxt = t.next_code(job["bid"])
        if t.active_block == job["bid"]:
            self._set_pointer(t, nxt)
        if job.get("kind") != MODE_STEPS:
            if nxt is not None:
                self.notify.emit(f"Напечатано. Дальше — {nxt.display_title(t.code_number(nxt))}.", False, True)
            else:
                self.notify.emit("Напечатано. Весь код урока напечатан.", False, True)

    # ================================================================ для экрана урока
    def snapshot(self) -> dict:
        """Состояние печати для экрана урока и строки печати в окне программы."""
        s = self.s
        st = self.engine.state
        job = self.job if st in BUSY else None
        a = self.armed()
        bid = job["bid"] if job else (a[1].id if a else "")
        d = {"mode": s.print_mode, "cpm": s.cpm, "human": s.human_typing, "sound": s.sound_enabled,
             "strip": s.strip_comments, "hotkey": s.hotkey_toggle, "restart_hotkey": s.hotkey_restart,
             "state": st, "block": bid, "progress": 0.0, "step": None, "line": None, "next_lines": [],
             "say": [], "last": self.last, "target": self.target, "countdown": self.countdown_n}
        if job:
            text = job["text"]
            d["progress"] = round(max(0, min(self._last_pos, len(text))) / max(1, len(text)), 4)
            if self._line_info:
                d["line"] = {"i": self._line_info[0], "n": self._line_info[1]}
        _t, block = self.find_block(bid) if bid else (None, None)
        if block is None or block.type != BLOCK_CODE:
            return d
        if s.print_mode == MODE_STEPS:
            k = job["step"] if job and job.get("kind") == MODE_STEPS else self.step_pointer(block.id)
            nums = self._block_steps(block)
            if k is None:
                d["step"] = {"i": len(nums), "n": len(nums), "done": True}
                return d
            lines = self._lines_of(block)
            i, n = self._step_index(block, k)
            d["step"] = {"i": i, "n": n}
            d["next_lines"] = [sl.index + 1 for sl in lines if sl.step == k and sl.typed is not None]
            d["say"] = [x for x in S.narration(block.text, lines, k, block.lang) if x]
        elif s.print_mode == MODE_LINES:
            info = self._lines_next(block)
            if info:
                if info["src_line"]:
                    d["next_lines"] = [info["src_line"]]
                d["say"] = info["say"]
                if not job:
                    d["line"] = {"i": info["i"], "n": info["n"]}
        return d
