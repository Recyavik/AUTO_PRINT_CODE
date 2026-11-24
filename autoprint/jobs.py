"""Фоновые работы программы: нейросеть составляет урок, скачиваются картинки по ссылкам.

Работа идёт в своём потоке; ход (что делает, сколько знаков, хвост ответа) виден в окне — в «Новом уроке» и в
«Уроках», даже если учитель ушёл на другой экран. «Отмена» — работа бросается, результат не нужен; «Пропустить»
(картинки) — работа заканчивается сразу тем, что есть. Выход из программы отменяет всё.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger(__name__)
KEEP_DONE_S = 6          # закончившаяся без ошибки работа видна ещё немного («Готово»), ошибка — пока не закроют


class Job:
    def __init__(self, jid: str, kind: str, title: str, ping: Callable[[], None]) -> None:
        self.id, self.kind, self.title = jid, kind, title
        self.t0 = time.monotonic()
        self.t_end = 0.0
        self.phase, self.chars, self.preview, self.who = "connect", 0, "", ""
        self.done, self.error, self.skipped = False, "", False
        self.cancel_event = threading.Event()
        self._ping = ping

    @property
    def cancelled(self) -> bool:
        """Работу отменили (а не «Пропустить»)."""
        return self.cancel_event.is_set() and not self.skipped

    def progress(self, phase: str, chars: int = 0, preview: str = "") -> None:
        """Из потока работы: connect | think | write | photos, сколько знаков (или картинок), хвост."""
        self.phase, self.chars = str(phase), int(chars or 0)
        if preview:
            self.preview = str(preview)[-240:]
        self._ping()

    def status(self, who: str) -> None:
        self.who, self.phase, self.chars, self.preview = str(who), "connect", 0, ""
        self._ping()

    def state(self) -> dict:
        end = self.t_end or time.monotonic()
        return {"id": self.id, "kind": self.kind, "title": self.title, "phase": self.phase, "chars": self.chars,
                "preview": self.preview, "who": self.who, "seconds": int(end - self.t0), "done": self.done,
                "error": self.error}


class Jobs(QObject):
    changed = Signal()
    _finished = Signal(object)       # (работа, результат, ошибка, on_done) — из потока работы в поток окна
    _pinged = Signal()

    def __init__(self, app=None) -> None:
        super().__init__(app if isinstance(app, QObject) else None)
        self.app = app
        self.items: list[Job] = []
        self._n = 0
        self._finished.connect(self._on_finished)
        self._debounce = QTimer(self, singleShot=True, interval=300, timeout=self.changed.emit)
        self._pinged.connect(lambda: self._debounce.isActive() or self._debounce.start())
        self._clock = QTimer(self, interval=1000, timeout=self._tick)     # секунды идущей работы

    def get(self, jid: str) -> Job | None:
        return next((j for j in self.items if j.id == jid), None)

    def start(self, kind: str, fn: Callable[[Job], object], on_done: Callable[[object], None], title: str) -> str:
        """fn(job) → результат — в фоне; on_done(результат) — в потоке окна, если работа не отменена и без ошибки."""
        self._n += 1
        job = Job(f"j{self._n}-{int(time.time())}", kind, title, self._pinged.emit)
        self.items.append(job)

        def work() -> None:
            result, err = None, ""
            try:
                result = fn(job)
            except Exception as e:   # noqa: BLE001 — любая беда в фоне — сообщение, а не падение программы
                from . import ai
                err = "Отменено." if isinstance(e, ai.Cancelled) else (str(e) or type(e).__name__)
                if not isinstance(e, ai.AIError):
                    log.exception("Фоновая работа «%s» упала", title)
            if job.cancelled:
                err = "Отменено."
            self._finished.emit((job, result, err, on_done))
        threading.Thread(target=work, name=f"job-{kind}", daemon=True).start()
        self._clock.start()
        self.changed.emit()
        return job.id

    def _on_finished(self, x) -> None:
        job, result, err, on_done = x
        if job.done and job.error:            # уже отменена учителем — результат не нужен
            return
        job.done, job.error, job.t_end = True, err, time.monotonic()
        if not err:
            try:
                on_done(result)
            except Exception as e:   # noqa: BLE001
                log.exception("Итог фоновой работы «%s» не принят", job.title)
                job.error = f"Не получилось: {e}"
        if not job.error:
            QTimer.singleShot(KEEP_DONE_S * 1000, lambda j=job: self.dismiss(j.id))
        self.changed.emit()

    def _tick(self) -> None:
        if any(not j.done for j in self.items):
            self.changed.emit()
        else:
            self._clock.stop()

    def cancel(self, jid: str) -> None:
        job = self.get(jid)
        if job is None or job.done:
            return
        job.cancel_event.set()
        job.done, job.error, job.t_end = True, "Отменено.", time.monotonic()
        self.changed.emit()

    def skip(self, jid: str) -> None:
        """«Пропустить»: закончить сразу тем, что уже есть (картинки — остаются ссылками)."""
        job = self.get(jid)
        if job is not None and not job.done:
            job.skipped = True
            job.cancel_event.set()

    def dismiss(self, jid: str) -> None:
        job = self.get(jid)
        if job is not None and job.done:
            self.items.remove(job)
            self.changed.emit()

    def cancel_all(self) -> None:
        for j in list(self.items):
            self.cancel(j.id)

    def busy(self) -> bool:
        return any(not j.done for j in self.items)

    def state(self) -> list[dict]:
        return [j.state() for j in self.items]
