"""Длина видео — для редактора шаблона: ролик зарядки длиннее блока видно заранее, а не в эфире.

Длину отдаёт QMediaPlayer, загрузив файл без показа и звука (асинхронно — окно не подвисает);
результат запоминается по пути файла, второй раз ролик не открывается.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QUrl

log = logging.getLogger(__name__)

_cache: dict[str, int | None] = {}                      # путь → длина в мс (None — не открылось)
_waiting: dict[str, list[Callable[[int | None], None]]] = {}
_players: dict[str, object] = {}                         # загружающиеся плееры — держим, пока не ответят


def _key(path: str) -> str:
    return str(Path(path).resolve()).lower()


def fmt_len(ms: int) -> str:
    s = ms // 1000                                          # как на пульте видео: 4:13.9 — «4:13»
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def video_ms(path: str, done: Callable[[int | None], None]) -> None:
    """Сообщить done(длина в мс | None) — сразу, если уже известно, иначе когда файл загрузится."""
    key = _key(path)
    if key in _cache:
        done(_cache[key])
        return
    _waiting.setdefault(key, []).append(done)
    if key in _players:
        return
    from PySide6.QtMultimedia import QMediaPlayer
    player = QMediaPlayer()
    _players[key] = player

    def finish(ms: int | None) -> None:
        if key not in _players:
            return
        _players.pop(key)
        _cache[key] = ms
        player.deleteLater()
        for cb in _waiting.pop(key, []):
            cb(ms)

    def on_status(status) -> None:
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia) \
                and player.duration() > 0:
            finish(player.duration())
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            log.warning("Длина видео не определена: %s", Path(path).name)
            finish(None)

    player.durationChanged.connect(lambda ms: ms > 0 and finish(ms))
    player.mediaStatusChanged.connect(on_status)
    player.setSource(QUrl.fromLocalFile(str(Path(path).resolve())))
