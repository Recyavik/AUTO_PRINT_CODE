"""Шаблоны вебинаров и идущий эфир: data/efir/webinars.json (запись — атомарная, с резервной копией)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .. import storage
from .model import Webinar, webinar_from_dict

log = logging.getLogger(__name__)


def efir_dir() -> Path:
    return storage.DATA_DIR / "efir"


def media_dir() -> Path:
    """Файлы, перенесённые из «Таймера вебинара» (видео, фон, шрифт)."""
    return efir_dir() / "media"


@dataclass
class Live:
    """Идущий эфир: какой шаблон и когда старт (с учётом «сдвинуть на сейчас»)."""
    webinar_id: str
    anchor: datetime


class WebinarStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or efir_dir() / "webinars.json"
        self.webinars: list[Webinar] = []
        self.live: Live | None = None
        self.imported_legacy = False      # перенос из «Таймера вебинара» уже был (второй раз не предлагать)
        self.load()

    def load(self) -> None:
        self.webinars, self.live = [], None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            log.warning("Шаблоны вебинаров не прочитаны (%s): %s", self.path, e)
            bak = self.path.with_suffix(self.path.suffix + ".bak")
            try:
                raw = json.loads(bak.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                return
        if not isinstance(raw, dict):
            return
        for d in raw.get("webinars", []):
            try:
                self.webinars.append(webinar_from_dict(d))
            except ValueError as e:
                log.warning("Шаблон пропущен: %s", e)
        self.imported_legacy = bool(raw.get("imported_legacy"))
        live = raw.get("live")
        if isinstance(live, dict) and self.get(str(live.get("id", ""))):
            try:
                self.live = Live(str(live["id"]), datetime.fromisoformat(str(live["anchor"])))
            except (KeyError, ValueError):
                self.live = None

    def save(self) -> None:
        data = {"version": 1, "imported_legacy": self.imported_legacy,
                "webinars": [w.to_dict() for w in self.webinars],
                "live": ({"id": self.live.webinar_id, "anchor": self.live.anchor.isoformat(timespec="seconds")}
                         if self.live else None)}
        storage._atomic_write(self.path, data, backup=True)

    # ------------------------------------------------------------ шаблоны
    def get(self, wid: str) -> Webinar | None:
        return next((w for w in self.webinars if w.id == wid), None)

    def visible(self) -> list[Webinar]:
        """Шаблоны для списка «Эфира» — без служебных эфиров уроков из суфлёра."""
        return [w for w in self.webinars if not w.lesson_id]

    def put(self, w: Webinar) -> None:
        for i, old in enumerate(self.webinars):
            if old.id == w.id:
                self.webinars[i] = w
                break
        else:
            self.webinars.append(w)
        self.save()

    def add(self, items: list[Webinar]) -> list[Webinar]:
        """Добавить (импорт): одинаковые id получают новые, одинаковые названия — пометку «(2)»."""
        ids = {w.id for w in self.webinars}
        titles = {w.title for w in self.webinars}
        added = []
        for w in items:
            w = w.copy() if w.id in ids else w
            base, n = w.title, 2
            while w.title in titles:
                w.title = f"{base} ({n})"
                n += 1
            ids.add(w.id)
            titles.add(w.title)
            self.webinars.append(w)
            added.append(w)
        self.save()
        return added

    def remove(self, wid: str) -> None:
        self.webinars = [w for w in self.webinars if w.id != wid]
        if self.live and self.live.webinar_id == wid:
            self.live = None
        self.save()

    def move(self, wid: str, delta: int) -> None:
        i = next((k for k, w in enumerate(self.webinars) if w.id == wid), -1)
        j = i + delta
        if i < 0 or not 0 <= j < len(self.webinars):
            return
        self.webinars[i], self.webinars[j] = self.webinars[j], self.webinars[i]
        self.save()

    # ------------------------------------------------------------ эфир
    def set_live(self, wid: str | None, anchor: datetime | None = None) -> None:
        self.live = Live(wid, anchor or datetime.now()) if wid else None
        self.save()
