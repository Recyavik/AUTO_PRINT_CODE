"""Перенос из «Таймера вебинара» (отдельная программа Виктора): шаблоны, видео гимнастики, фон перерыва, шрифт.

Где искать: установленный таймер (запись в «Приложениях» или %LOCALAPPDATA%\\Programs\\Таймер вебинара) и копия
его папок в data/efir/webinar-timer (её делает установщик AutoPrintCode перед удалением таймера).
Видео и картинки копируются в data/efir/media — после удаления таймера они остаются у нас.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import winreg
from pathlib import Path

from .model import DEFAULT_FONT, Exercise, Webinar, webinar_from_dict
from .store import efir_dir, media_dir

log = logging.getLogger(__name__)

TIMER_APP_ID = "{E4F5E0C0-61A9-4003-8571-50BDDAAC123E}_is1"
TIMER_FOLDER = "Таймер вебинара"


def _registry_location() -> Path | None:
    key = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{TIMER_APP_ID}"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, key) as k:
                loc, _ = winreg.QueryValueEx(k, "InstallLocation")
                if loc:
                    return Path(loc)
        except OSError:
            continue
    return None


def candidates() -> list[Path]:
    out = [efir_dir() / "webinar-timer"]
    reg = _registry_location()
    if reg:
        out.append(reg)
    base = os.environ.get("LOCALAPPDATA")
    if base:
        out.append(Path(base) / "Programs" / TIMER_FOLDER)
    for pf in ("ProgramFiles", "ProgramW6432"):
        if os.environ.get(pf):
            out.append(Path(os.environ[pf]) / TIMER_FOLDER)
    seen, res = set(), []
    for p in out:
        key = os.path.normcase(str(p))
        if key not in seen:
            seen.add(key)
            res.append(p)
    return res


def find() -> Path | None:
    """Папка «Таймера вебинара» с шаблонами (data/plans.json или templates/*.json)."""
    for p in candidates():
        if (p / "data" / "plans.json").is_file() or any((p / "templates").glob("*.json")):
            return p
    return None


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        log.warning("Не прочитан %s: %s", path, e)
        return None


def _copy_media(src: Path) -> Path | None:
    """Файл таймера → data/efir/media (если там уже такой же — не копируем)."""
    if not src.is_file():
        return None
    try:
        src.resolve().relative_to(efir_dir().resolve())
        return src          # копия таймера, сделанная установщиком, уже в наших данных — второй раз не копируем
    except ValueError:
        pass
    dst = media_dir() / src.name
    try:
        if not (dst.is_file() and dst.stat().st_size == src.stat().st_size):
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        return dst
    except OSError as e:
        log.warning("Не скопирован %s: %s", src, e)
        return src if src.is_file() else None


def _resolve(root: Path, rel: str) -> Path | None:
    if not rel:
        return None
    p = Path(rel)
    return p if p.is_absolute() else root / p


def import_from(root: Path) -> list[Webinar]:
    """Шаблоны «Таймера вебинара» как шаблоны Эфира. Зарядка — видео гимнастики из его настроек,
    фон перерыва — его картинка, шрифт — Furore (если есть). Основной фон — нейтральный чёрный."""
    settings = _read_json(root / "data" / "settings.json") or {}
    plans = (_read_json(root / "data" / "plans.json") or {}).get("plans")
    if not isinstance(plans, list) or not plans:
        plans = [d for f in sorted((root / "templates").glob("*.json")) if isinstance(d := _read_json(f), dict)]
    eyes = _resolve(root, str(settings.get("eyes_media") or "media/Гимнастика для глаз.mp4"))
    brk = _resolve(root, str(settings.get("break_image") or "media/Фон.jpg"))
    font = root / "media" / "Furore.otf"
    eyes_c = _copy_media(eyes) if eyes else None
    brk_c = _copy_media(brk) if brk else None
    font_c = _copy_media(font)
    try:
        break_min = int(settings.get("manual_break_min") or 10)
    except (TypeError, ValueError):
        break_min = 10
    color = str(settings.get("break_text_color") or "#FFFFFF")
    out = []
    for d in plans:
        try:
            w = webinar_from_dict(d)
        except ValueError as e:
            log.warning("Шаблон таймера пропущен: %s", e)
            continue
        if eyes_c:
            w.exercises = [Exercise("Гимнастика для глаз", str(eyes_c))]
        # свои ролики у блоков (media в плане) — тоже зарядки
        for a in d.get("schedule", []) if isinstance(d.get("schedule"), list) else []:
            m = _resolve(root, str(a.get("media") or "")) if isinstance(a, dict) else None
            if m and m.suffix.lower() in (".mp4", ".webm", ".mov", ".m4v") and m.is_file():
                c = _copy_media(m)
                if c and all(e.path != str(c) for e in w.exercises):
                    w.exercises.append(Exercise(str(a.get("name") or m.stem), str(c)))
        if brk_c:
            w.break_background = f"image:{brk_c}"
        w.font = f"file:{font_c}" if font_c else DEFAULT_FONT
        w.text_color = color if color.startswith("#") and len(color) == 7 else "#FFFFFF"
        w.break_min = max(1, min(180, break_min))
        w.caption = ""
        out.append(w)
    return out
