"""Мягкий звук напоминания вместо системного «Уведомления» Windows.

Один мягкий «пим»: чистый тон с тихим обертоном, плавная атака без щелчка и короткое
затухание. Громкость задаётся настройкой; файл синтезируется один раз на каждую громкость
в data/sounds/ и играется без задержки (winsound, асинхронно).
"""
from __future__ import annotations

import logging
import math
import struct
import wave
from pathlib import Path

from .store import DATA_DIR

log = logging.getLogger("webinar")

RATE = 44100
SOUND_DIR = DATA_DIR / "sounds"
_VERSION = 2

# (начало, с; частота, Гц; длительность, с) — одна нота ми второй октавы: слышно, но не тревожно
_NOTES = ((0.0, 659.25, 0.9),)


def _synth(volume: float) -> list[float]:
    total = max(start + dur for start, _f, dur in _NOTES)
    out = [0.0] * int(RATE * total)
    for start, freq, dur in _NOTES:
        a = int(RATE * start)
        for i in range(int(RATE * dur)):
            t = i / RATE
            env = min(1.0, t / 0.015) * math.exp(-t * 5.5)   # 15 мс атака — без щелчка; затухание ~0,7 с
            s = math.sin(2 * math.pi * freq * t) + 0.22 * math.sin(2 * math.pi * freq * 2 * t) * math.exp(-t * 6)
            out[a + i] += 0.45 * env * s
    fade = int(RATE * 0.03)   # последние 30 мс — к нулю: без щелчка на обрыве
    for i in range(fade):
        out[-1 - i] *= i / fade
    peak = max(abs(x) for x in out) or 1.0
    return [x / peak * 0.9 * volume for x in out]


def chime_file(volume: int) -> Path:
    """WAV колокольчика для громкости 0–100 (кэшируется)."""
    v = max(0, min(100, volume))
    path = SOUND_DIR / f"chime-v{_VERSION}-{v}.wav"
    if not path.exists():
        SOUND_DIR.mkdir(parents=True, exist_ok=True)
        # громкость на слух: квадратичная кривая — 50 % звучит заметно тише 100 %
        samples = _synth((v / 100) ** 2)
        tmp = path.with_suffix(".tmp")
        with wave.open(str(tmp), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(b"".join(struct.pack("<h", round(x * 32767)) for x in samples))
        tmp.replace(path)
    return path


def play(volume: int) -> None:
    """Сыграть колокольчик. Ошибки звука не мешают напоминанию."""
    if volume <= 0:
        return
    try:
        import winsound
        winsound.PlaySound(str(chime_file(volume)), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception as e:   # нет звуковой карты, нет прав на запись — не беда
        log.warning("Звук напоминания не сыгран: %s", e)
