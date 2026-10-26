"""Ведение эфира: следит за часами и сообщает о событиях повестки.

Строго по часам: блоки начинаются в расписанное время, задержка ведущего план не сдвигает.
События (каждое — один раз за эфир):
  * heads_up(seg)      — за settings.heads_up_min минут до блока с напоминанием;
  * block_started(seg) — начался блок с напоминанием (или перерыв);
  * break_started(seg) / break_ended(seg) — перерыв: заставку показать / начался следующий блок;
  * finished()         — эфир завершён.
Если эфир включили посреди блока, о текущем блоке тоже сообщается (предупреждения о прошлом — нет).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from .model import Plan, Segment, State, segments, state_at


class Scheduler(QObject):
    tick = Signal(object)              # State — для табло
    heads_up = Signal(object)          # Segment
    block_started = Signal(object)     # Segment
    break_started = Signal(object)     # Segment
    break_ended = Signal(object)       # Segment
    finished = Signal()

    def __init__(self, clock: Callable[[], datetime] = datetime.now, parent=None) -> None:
        super().__init__(parent)
        self.clock = clock
        self.plan: Plan | None = None
        self.segs: list[Segment] = []
        self.heads_up_min = 1
        self.running = False
        self._fired: set[tuple[str, int]] = set()
        self._break_on: Segment | None = None
        self._finished = False
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.poll)

    # ---------------------------------------------------------------- управление
    def set_plan(self, plan: Plan | None, day: date | None = None) -> None:
        """Показать план на табло (без напоминаний, пока эфир не включён)."""
        self.plan = plan
        self.segs = segments(plan, day or self.clock().date()) if plan else []
        self._reset()
        self.poll()

    def watch(self) -> None:
        """Обновлять табло (сигнал tick) — без напоминаний, пока эфир не включён."""
        self._timer.start()

    def start(self) -> None:
        self.running = True
        self._reset()
        self._timer.start()
        self.poll()

    def stop(self) -> None:
        self.running = False
        if self._break_on:
            seg, self._break_on = self._break_on, None
            self.break_ended.emit(seg)
        self._reset()

    def _reset(self) -> None:
        self._fired.clear()
        self._break_on = None
        self._finished = False

    def state(self) -> State:
        return state_at(self.segs, self.clock())

    # ---------------------------------------------------------------- проверка часов
    def poll(self) -> None:
        if not self.segs:
            return
        now = self.clock()
        st = state_at(self.segs, now)
        self.tick.emit(st)
        if not self.running:
            return
        cur = self.segs[st.index] if st.index >= 0 else None

        # перерыв закончился (или эфир кончился) — заставку убрать
        if self._break_on and (cur is None or cur.index != self._break_on.index):
            seg, self._break_on = self._break_on, None
            self.break_ended.emit(seg)

        if cur is not None and self._once("start", cur.index):
            self._once("head", cur.index)        # предупреждать о начавшемся блоке поздно
            if cur.activity.breaks:
                self._break_on = cur
                self.break_started.emit(cur)
            if cur.activity.reminds or cur.activity.breaks:
                self.block_started.emit(cur)

        if self.heads_up_min > 0:
            lead = timedelta(minutes=self.heads_up_min)
            for s in self.segs:
                if now < s.start <= now + lead and (s.activity.reminds or s.activity.breaks) \
                        and (cur is None or s.index > cur.index) and self._once("head", s.index):
                    self.heads_up.emit(s)
                    break                           # одно предупреждение за раз — о ближайшем блоке

        if st.phase == "after" and not self._finished:
            self._finished = True
            self.finished.emit()

    def _once(self, what: str, index: int) -> bool:
        key = (what, index)
        if key in self._fired:
            return False
        self._fired.add(key)
        return True
