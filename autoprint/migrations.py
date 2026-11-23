"""Разовые переделки данных при обновлении. Каждая — один раз (имя в settings.migrations).

Перед первой переделкой 0.10 кладётся копия базы уроков и шаблонов «Эфира» — на случай отката на 0.9:
templates.before-0.10.json и efir/webinars.before-0.10.json рядом с оригиналами.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from . import storage

log = logging.getLogger(__name__)


def backup_before_v10(data_dir: Path) -> None:
    """Копии базы до переделок 0.10 — только если их ещё нет (вторая копия затёрла бы настоящую старую)."""
    for src, dst in ((data_dir / "templates.json", data_dir / "templates.before-0.10.json"),
                     (data_dir / "efir" / "webinars.json", data_dir / "efir" / "webinars.before-0.10.json")):
        if src.exists() and not dst.exists():
            try:
                shutil.copy2(src, dst)
            except OSError as e:
                log.warning("Копия %s не сделана: %s", src.name, e)


def _roles_v10(store) -> None:
    """0.10: печатается только код — указатель «следующим», стоящий на заметке или картинке, переносится
    на первый блок кода урока (или снимается)."""
    for t in store.templates:
        b = t.find_block(t.active_block) if t.active_block else None
        if b is not None and not storage.is_printable(b):
            first = t.next_code()
            t.active_block = first.id if first else ""


def apply(settings, store=None) -> bool:
    """Все переделки по порядку. True — что-то поменялось (настройки и базу нужно сохранить)."""
    done = settings.migrations
    changed = False
    if "tray_v1" not in done:
        # 0.9: «закрыть» прячет в трей — иначе вместе с окном пропадали суфлёр и экран эфира
        settings.close_to_tray = True
        done.append("tray_v1")
        changed = True
    if "window_v10" not in done:
        # 0.10: окно программы — маленький список уроков; размер большого окна с редактором не возвращаем
        settings.window_geometry = ""
        done.append("window_v10")
        changed = True
    if store is None:
        return changed
    if "roles_v10" not in done:
        backup_before_v10(storage.DATA_DIR)
        _roles_v10(store)
        store.save()
        done.append("roles_v10")
        changed = True
    return changed
