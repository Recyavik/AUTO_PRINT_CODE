"""«Записать звук клавиатуры» без окна: микрофон → обычные клавиши → пробел → Enter → название.

Шаги показывает лист в окне программы (sheets.js, recordSheet); здесь — запись, нарезка на удары, прослушивание и
сохранение набора (recorder.save_custom_pack). Пробел и Enter можно пропустить — тогда они звучат как обычные клавиши,
ниже по тону. Пока лист открыт и микрофон слушается, состояние (уровень, волна) уходит странице ~10 раз в секунду
(сигнал changed).
"""
from __future__ import annotations

import math
import random
import shutil
import tempfile
import time
from collections import deque
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal

from . import sounds
from .recorder import RATE, AudioRecorder, cut_clip, filter_hits, hit_spans, normalize_groups, save_custom_pack

DEFAULT_NAME = "Моя клавиатура"
MAX_RECORD_S = 45          # запись останавливается сама — вдруг про «Стоп» забыли
KIND_TARGET = {"key": 8, "space": 4, "enter": 4}   # сколько ударов хорошо бы найти
MIN_KEY_HITS = 3           # меньше — набор не собрать
KINDS = ("key", "space", "enter")
WAVE_POINTS = 600


def make_recorder(parent=None):
    """Микрофон (тесты подменяют)."""
    return AudioRecorder(parent)


def db_scale(level: float) -> float:
    """Уровень 0..1 → доля шкалы −60…0 дБ (так слышно и тихий шорох, и удар)."""
    if level <= 1e-6:
        return 0.0
    return max(0.0, min(1.0, (20 * math.log10(level) + 60) / 60))


def hits_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "удар"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "удара"
    return "ударов"


class Player(QObject):
    """Проигрывает отрезки по очереди: пишет их во временные WAV и запускает QSoundEffect."""

    def __init__(self, volume: float, parent=None) -> None:
        super().__init__(parent)
        self._dir = Path(tempfile.mkdtemp(prefix="autoprint-rec-"))
        self._volume = volume
        self._n = 0
        self._effects: list = []
        self._timers: list[QTimer] = []

    def play(self, clips: list[list[float]], gap_ms: int) -> None:
        from PySide6.QtMultimedia import QSoundEffect
        self.stop()
        self._dir.mkdir(parents=True, exist_ok=True)
        for i, c in enumerate(clips):
            self._n += 1   # всегда новый файл: прежний может ещё держать проигрыватель
            path = self._dir / f"p{self._n}.wav"
            sounds.write_wav(path, c)
            e = QSoundEffect(self)
            e.setSource(QUrl.fromLocalFile(str(path)))
            e.setVolume(self._volume)
            t = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(e.play)
            t.start(120 + i * gap_ms)   # 120 мс — файл успевает загрузиться
            self._effects.append(e)
            self._timers.append(t)

    def stop(self) -> None:
        for t in self._timers:
            t.stop()
            t.deleteLater()
        for e in self._effects:
            e.stop()
            e.deleteLater()
        self._timers, self._effects = [], []

    def cleanup(self) -> None:
        self.stop()
        shutil.rmtree(self._dir, ignore_errors=True)


class RecordFlow(QObject):
    """Запись своей клавиатуры. changed — состояние поменялось (для страницы)."""
    changed = Signal()

    def __init__(self, volume: int = 60, recorder=None, parent=None) -> None:
        super().__init__(parent)
        self.rec = recorder if recorder is not None else make_recorder(self)
        self.rec.level.connect(self._on_level)
        self.rec.error.connect(self._on_error)
        self.player = Player(max(0, min(100, volume)) / 100, self)
        self.raw: dict[str, list[list[float]]] = {k: [] for k in KINDS}
        self._samples: dict[str, list[float]] = {k: [] for k in KINDS}
        self._spans: dict[str, list[tuple[int, int]]] = {k: [] for k in KINDS}
        self._cache: dict[str, dict] = {}    # итог записи (удары, волна, отметки) — считается один раз, при «Стоп»
        self.skipped: set[str] = set()
        self.recording = ""          # вид клавиш, который сейчас пишется
        self.monitoring = False      # шаг «Микрофон»: только уровень
        self.device = ""
        self.level = 0.0
        self.error = ""
        self.saved = ""
        self._started = 0.0
        self._live: deque[float] = deque(maxlen=WAVE_POINTS)
        self._tick = QTimer(self)
        self._tick.setInterval(100)  # и страница видит уровень ~10 раз в секунду
        self._tick.timeout.connect(self._on_tick)

    # ------------------------------------------------------------ микрофон
    def devices(self) -> list[tuple[str, str, bool]]:
        default = self.rec.default_device()
        return [(i, name, i == default) for i, name in self.rec.devices()]

    def monitor(self, device: str | None = None) -> bool:
        """Шаг «Микрофон»: индикатор уровня, запись не копится."""
        if self.recording:
            return False
        if device is not None:
            self.device = device
        self.error = ""
        self.level = 0.0
        ok = self.rec.start(self.device or None, keep=False)
        self.monitoring = ok
        if ok:
            self._tick.start()
        self.changed.emit()
        return ok

    def quiet(self) -> None:
        """Уйти с шага «Микрофон»: перестать слушать."""
        if self.monitoring and not self.recording:
            self.rec.stop()
        self.monitoring = False
        self.level = 0.0
        if not self.recording:
            self._tick.stop()
        self.changed.emit()

    def _on_level(self, level: float) -> None:
        self.level = db_scale(level)
        if self.recording:
            self._live.append(round(self.level, 3))

    def _on_error(self, msg: str) -> None:
        self.error = msg
        self.changed.emit()

    # ------------------------------------------------------------ запись
    def start(self, kind: str, device: str | None = None) -> bool:
        if kind not in KINDS or self.recording:
            return False
        self.player.stop()
        if device is not None:
            self.device = device
        self.monitoring = False
        self.error = ""
        if not self.rec.start(self.device or None, keep=True):
            self.changed.emit()
            return False
        self.recording = kind
        self.skipped.discard(kind)
        self._cache.pop(kind, None)
        self._started = time.monotonic()
        self._live.clear()
        self._tick.start()
        self.changed.emit()
        return True

    def stop(self) -> None:
        kind = self.recording
        if not kind:
            return
        self._tick.stop()
        samples = self.rec.stop()
        spans = hit_spans(samples)
        dc = sum(samples) / len(samples) if samples else 0.0
        self.raw[kind] = [cut_clip(samples, a, b, RATE, dc) for a, b in spans]
        self._samples[kind], self._spans[kind] = samples, spans
        self._cache.pop(kind, None)
        self.recording = ""
        self.level = 0.0
        self.changed.emit()

    def skip(self, kind: str) -> None:
        if kind not in ("space", "enter") or self.recording:
            return
        self.raw[kind], self._samples[kind], self._spans[kind] = [], [], []
        self._cache.pop(kind, None)
        self.skipped.add(kind)
        self.changed.emit()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._started if self.recording else 0.0

    def _on_tick(self) -> None:
        if self.recording and self.elapsed >= MAX_RECORD_S:
            self.stop()
            return
        self.changed.emit()

    # ------------------------------------------------------------ что получилось
    def _summary(self, kind: str) -> dict:
        c = self._cache.get(kind)
        if c is None:
            c = self._cache[kind] = {"hits": len(filter_hits(self.raw[kind])), "wave": self._wave_of(kind),
                                     "marks": self._marks_of(kind)}
        return c

    def hits(self, kind: str) -> int:
        return self._summary(kind)["hits"]

    def noise(self, kind: str) -> int:
        return len(self.raw[kind]) - self.hits(kind)

    def _status(self, kind: str) -> tuple[str, str]:
        good, noise, target = self.hits(kind), self.noise(kind), KIND_TARGET[kind]
        if kind in self.skipped:
            return "Пропущено — будут звучать обычные клавиши, ниже и громче", ""
        if self.recording == kind:
            return "Идёт запись — нажимайте клавиши. Кнопки окна сейчас не реагируют на клавиатуру", "accent"
        if not self._samples[kind]:
            return "Ещё ничего не записано", ""
        if good == 0:
            text, tone = "Ударов не найдено. Нажимайте отчётливее или поставьте микрофон ближе", "live"
        elif good < target:
            text, tone = (f"Найдено: {good} {hits_word(good)} — маловато, лучше записать ещё раз "
                          f"(хорошо бы {target} и больше)"), "live"
        else:
            text, tone = f"Найдено: {good} {hits_word(good)} — хорошо", "ok"
        if noise:
            text += f" · не похоже на удар и отброшено: {noise}"
        return text, tone

    def status(self, kind: str) -> str:
        return self._status(kind)[0]

    def tone(self, kind: str) -> str:
        return self._status(kind)[1]

    def can_next(self, step: str) -> bool:
        if self.recording:
            return False
        if step == "mic":
            return bool(self.rec.devices())
        if step == "key":
            return self.hits("key") >= MIN_KEY_HITS
        return True

    def wave(self, kind: str) -> list[float]:
        """Волна для рисунка: ≤ 600 точек 0..1 (идёт запись — уровни по ходу, потом — пики записи)."""
        if self.recording == kind:
            return list(self._live)
        return self._summary(kind)["wave"]

    def _wave_of(self, kind: str) -> list[float]:
        s = self._samples[kind]
        if not s:
            return []
        n = min(WAVE_POINTS, len(s))
        step = len(s) / n
        out = []
        for i in range(n):
            a, b = int(i * step), max(int(i * step) + 1, int((i + 1) * step))
            out.append(round(db_scale(max(abs(x) for x in s[a:b])), 3))
        return out

    def marks(self, kind: str) -> list[list[float]]:
        """Найденные удары — доли длины записи [начало, конец]."""
        return self._summary(kind)["marks"]

    def _marks_of(self, kind: str) -> list[list[float]]:
        n = len(self._samples[kind])
        return [[round(a / n, 4), round(b / n, 4)] for a, b in self._spans[kind]] if n else []

    # ------------------------------------------------------------ прослушивание и сохранение
    def preview(self, kind: str) -> bool:
        """kind — одна группа (до 10 ударов) или "all": несколько нажатий подряд, как при печати."""
        if kind == "all":
            groups = normalize_groups(self.raw)
            if not groups["key"]:
                return False
            v = sounds.custom_variants(groups, random.Random(), 4)
            self.player.play([v["key"][0], v["key"][1], v["key"][2], v["space"][0], v["key"][3], v["key"][1],
                              v["enter"][0]], 150)
            return True
        if kind not in KINDS or not self.raw[kind]:
            return False
        self.player.play(normalize_groups({kind: self.raw[kind]})[kind][:10], 260)
        return True

    @property
    def dirty(self) -> bool:
        return not self.saved and any(self.raw.values())

    def save(self, name: str) -> str:
        """Сохранить набор → ключ «my_<slug>». ValueError — мало записей обычных клавиш."""
        if self.hits("key") < MIN_KEY_HITS:
            raise ValueError("Мало записей обычных клавиш — вернитесь на шаг «Обычные клавиши» и запишите их")
        groups = normalize_groups(self.raw)
        try:
            key = save_custom_pack(name.strip() or DEFAULT_NAME, groups)
        except OSError as e:
            raise ValueError(f"Не удалось сохранить набор: {e}") from None
        self.saved = key
        self._cache.clear()
        self.changed.emit()
        return key

    def state(self) -> dict:
        return {
            "devices": [list(d) for d in self.devices()], "device": self.device, "level": round(self.level, 3),
            "monitoring": self.monitoring, "recording": self.recording, "elapsed": round(self.elapsed, 1),
            "max_s": MAX_RECORD_S, "error": self.error, "min_key": MIN_KEY_HITS, "saved": self.saved,
            "kinds": {k: {"hits": self.hits(k), "target": KIND_TARGET[k], "has": bool(self.raw[k]),
                          "skipped": k in self.skipped, "status": self.status(k), "tone": self.tone(k),
                          "wave": self.wave(k), "marks": self.marks(k)} for k in KINDS},
        }

    def close(self) -> None:
        self._tick.stop()
        if self.rec.recording:
            self.rec.stop()
        self.recording, self.monitoring = "", False
        self.player.cleanup()
