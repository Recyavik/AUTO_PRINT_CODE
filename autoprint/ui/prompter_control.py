"""Суфлёр в отдельном окне: что показать и что делают «Дальше» / «Назад».

«Печатает программа» — «Дальше» = старт/пауза печати (как хоткей), суфлёр показывает следующий шаг
(строку, блок) и что сказать; блок допечатан — суфлёр сам переходит к следующему блоку занятия.
«Печатаю сам» — программа не печатает: «Дальше»/«Назад» (и хоткеи старта и «шага назад») листают шаги.
Шаги — разметка блока, а если её нет — куски по комментариям (или по пустым строкам).
"""
from __future__ import annotations

import re

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QGuiApplication

from .. import steps as S
from ..storage import BLOCK_CODE, BLOCK_MARKDOWN, Block
from ..typer import COUNTDOWN, LINE_WAIT, PAUSED, RUNNING
from .prompter_window import MODE_AUTO, MODE_SELF, PromptCard, PrompterWindow

MODE_BLOCK, MODE_LINES, MODE_STEPS = "block", "lines", "steps"
BUSY = (RUNNING, PAUSED, COUNTDOWN, LINE_WAIT)
CODE_LIMIT = 60     # строк кода в окне (остальное — «… и ещё строк»)


def plain(md: str, limit: int = 700) -> str:
    """Markdown → простой текст для суфлёра."""
    out = []
    for ln in md.split("\n"):
        ln = re.sub(r"^\s*#{1,6}\s*", "", ln)
        ln = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), ln)
        ln = re.sub(r"`([^`]*)`", r"\1", ln)
        ln = re.sub(r"^\s*[-*]\s+", "• ", ln)
        out.append(ln.rstrip())
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def chunk_view(lines: list[S.SrcLine], k: int, limit: int = CODE_LIMIT) -> tuple[list[tuple[str, list[str]]], int]:
    """Код шага k кусками и куда каждый кусок вставить (если не в конец). → (куски, строк не показано)."""
    doc = [sl.typed for sl in lines if sl.typed is not None and sl.step < k]
    out: list[tuple[str, list[str]]] = []
    shown = hidden = 0
    for ch in S.plan(lines, k):
        rows = [sl.typed for sl in ch.lines]
        where = ""
        if doc and ch.anchor < len(doc):
            if ch.anchor == 0:
                where = "↑ в самое начало — над первой строкой"
            else:
                above = next((doc[i] for i in range(ch.anchor - 1, -1, -1) if doc[i].strip()), "")
                where = f"↳ после строки {ch.anchor}" + (f": {above.strip()[:48]}" if above.strip() else "")
        elif doc and len(out) and ch.anchor == len(doc):
            where = "↓ в конец"
        doc[ch.anchor:ch.anchor] = rows
        trimmed = list(rows)
        while trimmed and not trimmed[0].strip():
            trimmed.pop(0)
        while trimmed and not trimmed[-1].strip():
            trimmed.pop()
        if not trimmed:
            continue
        room = max(0, limit - shown)
        if room == 0:
            hidden += len(trimmed)
            continue
        out.append((where, trimmed[:room]))
        shown += min(room, len(trimmed))
        hidden += max(0, len(trimmed) - room)
    return out, hidden


def walk_steps(block: Block) -> list[int]:
    """Шаги для «Печатаю сам»: разметка блока, а если её нет — куски по комментариям или пустым строкам."""
    n = block.text.count("\n") + 1
    own = S.norm_steps(block.steps, n)
    if len(set(own)) > 1:
        return own
    for auto in (S.auto_by_comments(block.text, block.lang), S.auto_by_blank_lines(block.text)):
        if len(set(auto)) > 1:
            return auto
    return [1] * n


class PrompterController(QObject):
    def __init__(self, win) -> None:
        super().__init__(win)
        self.win = win
        self.window: PrompterWindow | None = None
        self.walk: dict[str, int] = {}      # «Печатаю сам»: id блока → номер шага по порядку (с 0)
        self._walk_cache: tuple | None = None

    @property
    def s(self):
        return self.win.settings

    # ------------------------------------------------------------ окно
    def visible(self) -> bool:
        return self.window is not None and self.window.isVisible()

    def self_mode(self) -> bool:
        return self.visible() and self.s.prompter_mode == MODE_SELF

    def toggle(self) -> None:
        if self.visible():
            self.window.close()
        else:
            self.show()

    def show(self) -> None:
        if self.window is None:
            w = PrompterWindow(self.s.prompter_mode, self.s.prompter_font)
            if self.s.prompter_geometry:
                w.restore(self.s.prompter_geometry)
            else:
                # справа вверху: внизу справа его закрывали бы уведомления Windows (и кнопку «Дальше» тоже)
                scr = self.win.screen() or QGuiApplication.primaryScreen()
                if scr is not None:
                    a = scr.availableGeometry()
                    w.move(a.right() - w.width() - 24, a.top() + 64)
            w.next_pressed.connect(self.win._remember_press)
            w.next_clicked.connect(self.next)
            w.back_clicked.connect(self.back)
            w.mode_changed.connect(self._set_mode)
            w.font_changed.connect(lambda n: self._save(prompter_font=n))
            w.geometry_changed.connect(lambda g: self._save(prompter_geometry=g))
            w.closed.connect(self._on_closed)
            self.window = w
        self.window.show()
        self._save(prompter_window=True)
        self.win._refresh_prompter()

    def _on_closed(self) -> None:
        self._save(prompter_window=False)
        QTimer.singleShot(0, self.win._refresh_prompter)    # вернуть суфлёр под пультом

    def _save(self, **kw) -> None:
        for k, v in kw.items():
            setattr(self.s, k, v)
        self.win._settings_timer.start()
        if "prompter_window" in kw:
            self.win.strip.set_prompter_on(kw["prompter_window"])

    def _set_mode(self, mode: str) -> None:
        self._save(prompter_mode=mode)
        if mode == MODE_SELF and self.win.engine.state in BUSY:
            self.win.cmd_stop()      # «печатаю сам» — программа не печатает
        self.refresh()

    def shutdown(self) -> None:
        """Выход из программы: окно спрятать, но запомнить открытым — в следующий раз откроется само."""
        if self.window is not None:
            self.window.closed.disconnect(self._on_closed)
            self.window.close()

    # ------------------------------------------------------------ содержимое
    def refresh(self) -> None:
        if self.visible():
            self.window.show_card(self.card())

    def card(self) -> PromptCard:
        a = self.win._armed()
        if not a:
            return PromptCard(title="", empty="Щёлкните блок кода в занятии — здесь появится, что сказать "
                                              "и что набрать.", can_next=False, can_back=False)
        v, block = a
        if block.type != BLOCK_CODE:
            return self._block_card(v, block)     # текст (условие, пояснение) — целиком, в обоих режимах
        if self.s.prompter_mode == MODE_SELF:
            return self._self_card(v, block)
        mode = self.win._mode_for(block)
        if mode == MODE_STEPS:
            return self._steps_card(v, block)
        if mode == MODE_LINES:
            return self._lines_card(v, block)
        return self._block_card(v, block)

    def _sub(self, v, block: Block) -> str:
        t = v.template
        j = t.code_number(block)
        n = len(t.code_blocks())
        return f"{t.title} · {block.display_title(j)}" + (f" · блок {j} из {n}" if j and n > 1 else "")

    @staticmethod
    def _intro(v, block: Block) -> list[str]:
        """Текстовые блоки занятия перед этим блоком кода (после предыдущего) — условие, пояснения."""
        out: list[str] = []
        for b in v.template.blocks:
            if b.id == block.id:
                return [t for t in out if t]
            if b.type == BLOCK_CODE:
                out = []
            elif b.type == BLOCK_MARKDOWN:       # этап урока и картинка — не «что сказать»
                out.append(plain(b.text))
        return []

    def _neighbor(self, v, block: Block, d: int) -> Block | None:
        """Следующий (d=+1) или предыдущий блок кода по ленте занятия — и от текстового блока тоже."""
        bl = v.template.blocks
        i = bl.index(block) if block in bl else -1
        if i < 0:
            return None
        rng = range(i + 1, len(bl)) if d > 0 else range(i - 1, -1, -1)
        return next((bl[j] for j in rng if bl[j].type == BLOCK_CODE), None)

    def _busy_buttons(self, c: PromptCard, hk: str) -> PromptCard:
        st = self.win.engine.state
        if st in (RUNNING, COUNTDOWN):
            c.next_text, c.next_icon = "Пауза", "pause"
            c.hint = f"печатается… {hk} — пауза" if hk else "печатается…"
        elif st == PAUSED:
            c.next_text, c.next_icon = "Продолжить", "play"
            c.hint = f"пауза · {hk} — продолжить" if hk else "пауза"
        elif st == LINE_WAIT:
            c.next_text, c.next_icon = "Следующая строка", "enter"
            c.hint = f"Enter или {hk}" if hk else "Enter"
        return c

    def _steps_card(self, v, block: Block) -> PromptCard:
        win, hk = self.win, self.s.hotkey_toggle
        job = win.job
        busy = win.engine.state in BUSY and job and job["bid"] == block.id and job.get("kind") == MODE_STEPS
        k = job["step"] if busy else win._step_pointer(block.id)
        sub = self._sub(v, block)
        if k is None:
            nxt = self._neighbor(v, block, +1)
            return PromptCard(title="все шаги напечатаны", sub=sub,
                              empty=("Блок напечатан. «Следующий блок» — перейти к нему." if nxt else
                                     "Занятие напечатано. «Сначала» — снова с первого шага этого блока."),
                              next_text="Следующий блок" if nxt else "Сначала",
                              next_icon="next" if nxt else "restart")
        lines = win._lines_of(block)
        i, n = win._step_index(block, k)
        say = (self._intro(v, block) if i == 1 else []) + S.narration(block.text, lines, k, block.lang)
        chunks, hidden = chunk_view(lines, k)
        c = PromptCard(title=f"шаг {i} из {n}", sub=sub, say=say, chunks=chunks, hidden=hidden,
                       hint=f"{hk} — напечатать шаг" if hk else "", next_text="Напечатать", next_icon="play",
                       can_back=i > 1 or self._neighbor(v, block, -1) is not None)
        if not chunks:
            c.empty = "В этом шаге только слова — кода нет. «Дальше» — к следующему шагу."
            c.next_text, c.next_icon = "Дальше", "next"
        return self._busy_buttons(c, hk) if busy else c

    def _lines_card(self, v, block: Block) -> PromptCard:
        hk = self.s.hotkey_toggle
        info = self.win._lines_prompt(block)
        sub = self._sub(v, block)
        if info is None:
            return PromptCard(title="", sub=sub, empty="Нечего печатать: блок пустой.", can_next=False)
        title, say, row = info
        busy = self.win.engine.state in BUSY and self.win.job and self.win.job["bid"] == block.id
        if not busy:
            say = self._intro(v, block) + say
        c = PromptCard(title=title, sub=sub, say=say, chunks=[("", [row])] if row else [],
                       hint=f"{hk} — начать" if hk else "", next_text="Начать", next_icon="play",
                       can_back=self._neighbor(v, block, -1) is not None)
        if not row:
            c.empty = "Строки блока напечатаны."
        return self._busy_buttons(c, hk) if busy else c

    def _block_card(self, v, block: Block) -> PromptCard:
        hk = self.s.hotkey_toggle
        text, *_rest, part = self.win._typing_text(v.template, block)   # как напечатается: без комментариев,
        rows = text.split("\n")                                          # текст — в выбранном виде
        shown = rows[:CODE_LIMIT]
        busy = self.win.engine.state in BUSY and self.win.job and self.win.job["bid"] == block.id
        is_code = block.type == BLOCK_CODE
        c = PromptCard(title="блок целиком" if is_code else part, sub=self._sub(v, block),
                       say=self._intro(v, block) if is_code else [],
                       chunks=[("", shown)] if text.strip() else [], hidden=max(0, len(rows) - len(shown)),
                       hint=f"{hk} — напечатать блок" if hk else "", next_text="Напечатать", next_icon="play",
                       can_back=self._neighbor(v, block, -1) is not None)
        if self.s.prompter_mode == MODE_SELF:
            nxt = self._neighbor(v, block, +1)
            c.hint = (f"{hk} — дальше" if hk else "") + " · программа не печатает"
            c.next_text, c.next_icon, c.can_next = "Следующий блок", "next", nxt is not None
        return self._busy_buttons(c, hk) if busy else c

    # ---- «Печатаю сам»
    def _walk_of(self, block: Block) -> tuple[list[int], list[int], list[S.SrcLine]]:
        key = (block.id, block.text, tuple(block.steps), block.lang, self.s.strip_comments)
        if self._walk_cache is None or self._walk_cache[0] != key:
            steps = walk_steps(block)
            lines = S.analyze(block.text, steps, block.lang, self.s.strip_comments)
            self._walk_cache = (key, (steps, sorted(set(steps)), lines))
        return self._walk_cache[1]

    def _self_card(self, v, block: Block) -> PromptCard:
        hk = self.s.hotkey_toggle
        _steps, nums, lines = self._walk_of(block)
        idx = min(self.walk.get(block.id, 0), len(nums))
        sub = self._sub(v, block)
        nxt = self._neighbor(v, block, +1)
        if idx >= len(nums):
            return PromptCard(title="конец блока", sub=sub,
                              empty="Блок пройден." + (" «Дальше» — следующий блок." if nxt else
                                                       " Это был последний блок занятия."),
                              can_next=nxt is not None, hint=f"{hk} — дальше" if hk else "")
        k = nums[idx]
        say = (self._intro(v, block) if idx == 0 else []) + S.narration(block.text, lines, k, block.lang)
        chunks, hidden = chunk_view(lines, k)
        last = idx == len(nums) - 1
        c = PromptCard(title=f"шаг {idx + 1} из {len(nums)} · набираете вы", sub=sub, say=say, chunks=chunks,
                       hidden=hidden, hint=(f"{hk} — дальше" if hk else "") + " · программа не печатает",
                       next_text="Следующий блок" if last and nxt else "Дальше", next_icon="next",
                       can_next=not last or nxt is not None,
                       can_back=idx > 0 or self._neighbor(v, block, -1) is not None)
        if not chunks:
            c.empty = "Здесь только слова — кода нет."
        return c

    # ------------------------------------------------------------ «Дальше» / «Назад»
    def _goto(self, v, block: Block) -> None:
        if self.win.engine.state in BUSY:
            self.win.cmd_stop()
        v.go_to_block(block.id)
        self.win._update_armed_label()

    def next(self) -> None:
        a = self.win._armed()
        if not a:
            return
        v, block = a
        if self.s.prompter_mode == MODE_SELF and block.type != BLOCK_CODE:
            self.win._press_state = None
            nxt = self._neighbor(v, block, +1)
            if nxt is not None:
                self.walk[nxt.id] = 0
                self._goto(v, nxt)
            self.refresh()
            return
        if self.s.prompter_mode == MODE_SELF:
            self.win._press_state = None
            _steps, nums, _lines = self._walk_of(block)
            idx = self.walk.get(block.id, 0) + 1
            nxt = self._neighbor(v, block, +1)
            if idx >= len(nums) and nxt is not None:
                self.walk[nxt.id] = 0
                self._goto(v, nxt)
            else:
                self.walk[block.id] = min(idx, len(nums))
            self.refresh()
            return
        st = self.win.engine.state
        if self.win._mode_for(block) == MODE_STEPS and st not in BUSY and self.win._step_pointer(block.id) is None:
            self.win._press_state = None
            nxt = self._neighbor(v, block, +1)
            if nxt is not None:
                if self.win._step_pointer(nxt.id) is None:
                    self.win.step_next[nxt.id] = self.win._block_steps(nxt)[0]
                self._goto(v, nxt)
            else:
                self.win._set_step_pointer(block.id, self.win._block_steps(block)[0])
            self.refresh()
            return
        # печатает программа: как хоткей старта (без отсчёта и сворачивания — фокус остался в редакторе)
        self.win.cmd_toggle(pressed=True)

    def back(self) -> None:
        a = self.win._armed()
        if not a:
            return
        v, block = a
        prev = self._neighbor(v, block, -1)
        if self.s.prompter_mode == MODE_SELF:
            idx = self.walk.get(block.id, 0) if block.type == BLOCK_CODE else 0
            if idx > 0:
                self.walk[block.id] = idx - 1
            elif prev is not None:
                self.walk[prev.id] = len(self._walk_of(prev)[1]) - 1
                self._goto(v, prev)
            self.refresh()
            return
        if self.win._mode_for(block) == MODE_STEPS:
            if self.win._step_pointer(block.id) == self.win._block_steps(block)[0] and prev is not None:
                # на первом шаге блока — к последнему шагу предыдущего блока
                self._goto(v, prev)
                self.win._set_step_pointer(prev.id, self.win._block_steps(prev)[-1])
            else:
                self.win.cmd_step_back()
            return
        if prev is not None:
            self._goto(v, prev)

    def on_hotkey(self, action: str) -> bool:
        """«Печатаю сам»: хоткеи старта, шага назад и «сначала» листают суфлёр. True — хоткей обработан."""
        if not self.self_mode():
            return False
        if action == "hotkey_toggle":
            self.next()
        elif action == "hotkey_step_back":
            self.back()
        elif action == "hotkey_restart":
            a = self.win._armed()
            if a:
                self.walk[a[1].id] = 0
                self.refresh()
        else:
            return False
        return True

    def after_block_done(self) -> bool:
        """Блок допечатан, суфлёр открыт («печатает программа») — перейти к следующему блоку занятия."""
        if not self.visible() or self.s.prompter_mode != MODE_AUTO:
            return False
        a = self.win._armed()
        if not a:
            return False
        v, block = a
        nxt = self._neighbor(v, block, +1)
        if nxt is None:
            return False
        if self.win._mode_for(nxt) == MODE_STEPS and self.win._step_pointer(nxt.id) is None:
            self.win.step_next[nxt.id] = self.win._block_steps(nxt)[0]
        QTimer.singleShot(400, lambda: self._goto(v, nxt) if self.win._armed() == (v, block) else None)
        return True
