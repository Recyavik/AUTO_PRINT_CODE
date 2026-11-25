"""Файлы оформлений экрана учеников (фон, заставка перерыва, видео зарядок, свой шрифт): где лежат и копия в программу.

С 1.0 выбранный в оформлении файл сразу копируется в data/media (take_file), и оформление ссылается на копию — флешку
вынули, папку переименовали, а эфир работает. Оформления до 1.0 при обновлении не трогаются (видео бывают по сотне
МБ): у них «Файлы снаружи программы: N МБ» и «Скопировать в программу» (copy_look_files — в фоне, с ходом и отменой;
ссылки меняются только после удачной копии всех файлов).
"""
from __future__ import annotations

import copy
import os
import shutil
from pathlib import Path
from typing import Callable

from . import storage
from .efir.model import Look


class Cancelled(Exception):
    """Копирование отменили — ничего не поменялось."""


def _inside(p: Path) -> bool:
    try:
        p.resolve().relative_to(storage.DATA_DIR.resolve())
        return True
    except ValueError:
        return False


def file_status(path: str) -> str:
    """"ok" — файл в программе, "outside" — есть, но снаружи программы, "missing" — нет файла."""
    if not path:
        return "missing"
    p = Path(path)
    if not p.is_file():
        return "missing"
    return "ok" if _inside(p) else "outside"


def look_files(look: Look) -> list[str]:
    """Пути файлов оформления: фон и заставка (картинки), видео зарядок, свой шрифт."""
    out = []
    for v in (look.background, look.break_background):
        if (v or "").startswith("image:"):
            out.append(v[6:])
    out += [e.path for e in look.exercises if e.path]
    if (look.font or "").startswith("file:"):
        out.append(look.font[5:])
    return out


def outside_size(look: Look) -> int:
    """Сколько байт файлов оформления лежит снаружи программы."""
    seen, total = set(), 0
    for p in look_files(look):
        if p not in seen and file_status(p) == "outside":
            seen.add(p)
            total += Path(p).stat().st_size
    return total


def _unique(dest: Path, name: str) -> Path:
    stem, suf = os.path.splitext(name)
    p, n = dest / name, 2
    while p.exists():
        p = dest / f"{stem}-{n}{suf}"
        n += 1
    return p


TAKE_SYNC_LIMIT = 16 * 1024 * 1024      # файлы больше копируются в фоне (видео с флешки — секунды)


def existing_copy(src: Path, dest: Path) -> Path | None:
    """Уже сделанная копия этого файла в dest (то же имя, размер и время изменения) — чтобы не плодить «-2», «-3»."""
    try:
        st = src.stat()
    except OSError:
        return None
    stem, suf = os.path.splitext(src.name)
    for p in [dest / src.name, *sorted(dest.glob(f"{stem}-*{suf}"))]:
        try:
            q = p.stat()
        except OSError:
            continue
        if q.st_size == st.st_size and int(q.st_mtime) == int(st.st_mtime):
            return p
    return None


def take_file(path: str, dest: Path | None = None) -> str:
    """Выбрали файл для оформления — копия в data/media (уже в программе — тот же путь; уже копировали — та же
    копия). OSError — не скопировался."""
    src = Path(path)
    if file_status(str(src)) != "outside":
        return str(src)
    dest = dest or storage.DATA_DIR / storage.MEDIA_FOLDER
    dest.mkdir(parents=True, exist_ok=True)
    have = existing_copy(src, dest)
    if have is not None:
        return str(have)
    out = _unique(dest, src.name)
    shutil.copy2(src, out)
    return str(out)


def copy_look_files(look: Look, dest_dir: Path, progress: Callable[[int, int, str], None] | None = None,
                    cancel=None) -> Look:
    """Копия оформления, чьи файлы снаружи программы скопированы в dest_dir. Исходное оформление не меняется.
    OSError — что-то не скопировалось (начатое убрано); Cancelled — отменили (начатое убрано)."""
    todo = [p for p in dict.fromkeys(look_files(look)) if file_status(p) == "outside"]
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    done: dict[str, str] = {}
    made: list[Path] = []
    try:
        for i, src in enumerate(todo):
            if cancel is not None and cancel.is_set():
                raise Cancelled("Копирование отменено")
            out = _unique(dest_dir, Path(src).name)
            shutil.copy2(src, out)
            made.append(out)
            done[src] = str(out)
            if progress:
                progress(i + 1, len(todo), Path(src).name)
        if cancel is not None and cancel.is_set():
            raise Cancelled("Копирование отменено")
    except BaseException:
        for p in made:
            try:
                p.unlink()
            except OSError:
                pass
        raise
    new = remap(look, done)
    new.copied = done                    # что куда скопировано — заменить и в оформлении, которое успели поправить
    return new


def remap(look: Look, moves: dict[str, str]) -> Look:
    """Копия оформления, где пути из moves (старый → копия в программе) заменены на новые; остальное — как было."""
    new = copy.deepcopy(look)
    if not moves:
        return new
    for attr, prefix in (("background", "image:"), ("break_background", "image:"), ("font", "file:")):
        v = getattr(new, attr) or ""
        if v.startswith(prefix) and v[len(prefix):] in moves:
            setattr(new, attr, prefix + moves[v[len(prefix):]])
    for e in new.exercises:
        if e.path in moves:
            e.path = moves[e.path]
    return new
