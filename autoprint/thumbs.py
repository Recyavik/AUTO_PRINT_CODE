"""Уменьшенные копии картинок для экрана урока.

Слайды — 1600–1920 px, бывает и 3840 px: на экране урока они шириной ~900 px, но браузер распаковывает их целиком —
при первой прокрутке урок подлагивает. Страница просит «/media/<id>/<имя>?w=1280» — сервер отдаёт копию этой ширины
(готовит один раз, хранит в data/cache/thumbs). Ученикам и в просмотре картинки — по-прежнему оригинал.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path

log = logging.getLogger(__name__)

SIZES = (320, 640, 960, 1280, 1600, 1920)        # какие ширины просит страница
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}   # gif — нет: анимация потерялась бы
QUALITY = 86

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def cache_dir() -> Path:
    from .storage import DATA_DIR
    return DATA_DIR / "cache" / "thumbs"


def _lock(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _format(has_alpha: bool) -> tuple[str, str]:
    from PySide6.QtGui import QImageWriter
    fmts = {bytes(f).decode().lower() for f in QImageWriter.supportedImageFormats()}
    if "webp" in fmts:
        return "WEBP", ".webp"
    return ("PNG", ".png") if has_alpha else ("JPG", ".jpg")


def thumb_for(src: str | os.PathLike, width: int, cache: Path | None = None) -> Path | None:
    """Копия картинки src шириной width (одна из SIZES). None — отдать оригинал: не картинка, уже не шире width,
    не читается или файла нет. Копия — по пути, времени и размеру файла: файл поменяли — будет новая."""
    p = Path(src)
    if width not in SIZES or p.suffix.lower() not in IMAGE_EXT:
        return None
    try:
        st = p.stat()
    except OSError:
        return None
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QImageReader
    reader = QImageReader(str(p))
    size = reader.size()
    if not size.isValid() or size.width() <= width:
        return None
    cache = Path(cache) if cache is not None else cache_dir()
    key = hashlib.sha1(f"{os.path.normcase(str(p.resolve()))}|{st.st_mtime_ns}|{st.st_size}|{width}".encode()).hexdigest()[:20]
    with _lock(key):
        for ext in (".webp", ".jpg", ".png"):
            done = cache / f"{key}{ext}"
            if done.is_file():
                return done
        img = reader.read()
        if img.isNull():
            log.info("Копия картинки не сделана (%s): %s", p.name, reader.errorString())
            return None
        h = max(1, round(size.height() * width / size.width()))
        small = img.scaled(QSize(width, h), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        fmt, ext = _format(small.hasAlphaChannel())
        out = cache / f"{key}{ext}"
        tmp = cache / f"{key}.{threading.get_ident()}.tmp"
        try:
            cache.mkdir(parents=True, exist_ok=True)
            if not small.save(str(tmp), fmt, QUALITY):
                return None
            os.replace(tmp, out)
        except OSError as e:
            log.info("Копия картинки не сохранена (%s): %s", p.name, e)
            tmp.unlink(missing_ok=True)
            return None
        return out
