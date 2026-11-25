"""Расписания вебинаров, оформления экрана эфира и идущий эфир (запись — атомарная, с резервной копией).

С 0.10 — два файла в data/efir:
- schedules.json — расписания (название, строки, перерыв по умолчанию, ссылка на оформление) и идущий эфир;
- looks.json — оформления (фон, зарядки, экран перерыва, шрифт).
Прежний webinars.json (0.9: расписание и вид в одном шаблоне) читается один раз — при первом запуске 0.10 — и
больше не пишется: откат на 0.9 увидит «Эфир» таким, каким он был до обновления.

В памяти расписания — «собранные» Webinar (поля вида — копия оформления): их берут экран эфира и таймер.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .. import storage
from .model import Look, Webinar, compose, look_from_dict, schedule_dict, split, webinar_from_dict

log = logging.getLogger(__name__)


def efir_dir() -> Path:
    return storage.DATA_DIR / "efir"


def media_dir() -> Path:
    """Файлы, перенесённые из «Таймера вебинара» (видео, фон, шрифт)."""
    return efir_dir() / "media"


@dataclass
class Live:
    """Идущий эфир: какой шаблон и когда старт (с учётом «этап заново с этой минуты»). plan — плановое начало
    урока: от него «конец 19:30 · +5 мин» и «Вернуть время» после «Следующий этап — сейчас» (1.1: в файле — переживёт
    перезапуск программы)."""
    webinar_id: str
    anchor: datetime
    plan: datetime | None = None


def _read_json(path: Path):
    """JSON файла, при порче — из резервной копии .bak; нет файла — None."""
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        log.warning("Эфир: файл не прочитан (%s): %s", path, e)
        try:
            return json.loads(path.with_suffix(path.suffix + ".bak").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return None


class WebinarStore:
    def __init__(self, path: Path | None = None) -> None:
        self.legacy_path = path or efir_dir() / "webinars.json"     # 0.9 — только для переноса
        folder = self.legacy_path.parent
        self.path = folder / "schedules.json"
        self.looks_path = folder / "looks.json"
        self.webinars: list[Webinar] = []
        self.looks: list[Look] = []
        self.live: Live | None = None
        self.brk: dict | None = None             # идущий перерыв (переживает перезапуск программы)
        self.slide: dict | None = None           # слайд у учеников: {"ref", "next", "n", "bid"} — тоже переживает
        self.imported_legacy = False      # перенос из «Таймера вебинара» уже был (второй раз не предлагать)
        self.load()

    # ------------------------------------------------------------ файлы
    def load(self) -> None:
        self.webinars, self.looks, self.live, self.brk, self.slide = [], [], None, None, None
        raw = _read_json(self.path)
        if raw is None and not self.path.exists():
            self._migrate_legacy()
            return
        if not isinstance(raw, dict):
            return
        looks_raw = _read_json(self.looks_path)
        for d in (looks_raw or {}).get("looks", []) if isinstance(looks_raw, dict) else []:
            try:
                self.looks.append(look_from_dict(d))
            except ValueError as e:
                log.warning("Оформление пропущено: %s", e)
        for d in raw.get("schedules", []):
            try:
                s = webinar_from_dict(d)
            except ValueError as e:
                log.warning("Расписание пропущено: %s", e)
                continue
            self.webinars.append(compose(s, self.look(s.look_id)))
        self.imported_legacy = bool(raw.get("imported_legacy"))
        self._read_live(raw)

    def _read_live(self, raw: dict) -> None:
        live = raw.get("live")
        if isinstance(live, dict) and self.get(str(live.get("id", ""))):
            try:
                plan = datetime.fromisoformat(str(live["plan"])) if live.get("plan") else None
                self.live = Live(str(live["id"]), datetime.fromisoformat(str(live["anchor"])), plan)
            except (KeyError, ValueError):
                self.live = None
        brk = raw.get("brk")
        if self.live and isinstance(brk, dict) and isinstance(brk.get("ends_at"), (int, float)):
            self.brk = {"ends_at": float(brk["ends_at"]), "total": float(brk.get("total") or 600),
                        "seq": int(brk.get("seq") or 0)}
        sl = raw.get("slide")
        if self.live and isinstance(sl, dict) and isinstance(sl.get("ref"), str):
            self.slide = {"ref": sl["ref"], "next": str(sl.get("next") or ""), "n": int(sl.get("n") or 0),
                          "bid": str(sl.get("bid") or "")}

    def _migrate_legacy(self) -> None:
        """0.10 (looks_v10): шаблоны 0.9 → расписания + оформления; одинаковые оформления — одно. Служебные
        эфиры уроков не переносятся (урок создаёт свой при запуске). webinars.json не меняется."""
        raw = _read_json(self.legacy_path)
        if not isinstance(raw, dict):
            return
        for d in raw.get("webinars", []):
            try:
                w = webinar_from_dict(d)
            except ValueError as e:
                log.warning("Шаблон пропущен: %s", e)
                continue
            if w.lesson_id:
                continue
            w.look_id = ""
            self._adopt(w)
        self.imported_legacy = bool(raw.get("imported_legacy"))
        self._read_live(raw)
        if self.webinars or self.imported_legacy:
            self.save()
            log.info("Эфир: шаблоны 0.9 разделены — расписаний %d, оформлений %d", len(self.webinars), len(self.looks))

    def save(self) -> None:
        data = {"version": 2, "imported_legacy": self.imported_legacy,
                "schedules": [schedule_dict(w) for w in self.webinars],
                "live": ({"id": self.live.webinar_id, "anchor": self.live.anchor.isoformat(timespec="seconds"),
                          **({"plan": self.live.plan.isoformat(timespec="seconds")} if self.live.plan else {})}
                         if self.live else None),
                "brk": self.brk if self.live and self.brk else None,
                "slide": self.slide if self.live and self.slide else None}
        storage._atomic_write(self.looks_path, {"version": 1, "looks": [lk.to_dict() for lk in self.looks]},
                              backup=True)
        storage._atomic_write(self.path, data, backup=True)

    # ------------------------------------------------------------ оформления
    def look(self, lid: str) -> Look | None:
        return next((lk for lk in self.looks if lk.id == lid), None) if lid else None

    def _adopt(self, w: Webinar) -> Webinar:
        """Шаблон с полями вида → расписание со ссылкой на оформление (такое же оформление — то же)."""
        sched, look = split(w)
        if not w.look_id or self.look(w.look_id) is None:
            same = next((lk for lk in self.looks if lk.same_look(look)), None)
            if same is None:
                look.id = look.id if not self.look(look.id) else Look().id
                self.looks.append(look)
                same = look
            sched.look_id = same.id
        composed = compose(sched, self.look(sched.look_id))
        for i, old in enumerate(self.webinars):
            if old.id == composed.id:
                self.webinars[i] = composed
                break
        else:
            self.webinars.append(composed)
        return composed

    def put_look(self, look: Look) -> None:
        for i, old in enumerate(self.looks):
            if old.id == look.id:
                self.looks[i] = look
                break
        else:
            self.looks.append(look)
        self.webinars = [compose(w, self.look(w.look_id)) if w.look_id == look.id else w for w in self.webinars]
        self.save()

    def remove_look(self, lid: str) -> bool:
        """Удалить оформление. False — на него ссылается расписание (сначала смените оформление там)."""
        if any(w.look_id == lid and not w.lesson_id for w in self.webinars):
            return False
        self.looks = [lk for lk in self.looks if lk.id != lid]
        self.save()
        return True

    def users_of(self, lid: str) -> list[Webinar]:
        return [w for w in self.webinars if w.look_id == lid and not w.lesson_id]

    # ------------------------------------------------------------ расписания
    def get(self, wid: str) -> Webinar | None:
        return next((w for w in self.webinars if w.id == wid), None)

    def visible(self) -> list[Webinar]:
        """Расписания для списка «Эфира» — без служебных эфиров уроков."""
        return [w for w in self.webinars if not w.lesson_id]

    def put(self, w: Webinar) -> Webinar:
        """Сохранить расписание. Его оформление: по look_id; без него (импорт, новый) — по полям вида."""
        if w.look_id and self.look(w.look_id) is not None:
            composed = compose(split(w)[0], self.look(w.look_id))
            for i, old in enumerate(self.webinars):
                if old.id == w.id:
                    self.webinars[i] = composed
                    break
            else:
                self.webinars.append(composed)
        else:
            composed = self._adopt(w)
        self.save()
        return composed

    def drop_lesson_schedules(self, keep: str = "") -> None:
        """Служебные эфиры прошлых уроков больше не нужны."""
        self.webinars = [w for w in self.webinars if not w.lesson_id or w.id == keep]

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
            added.append(self._adopt(w))
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
        """Эфир wid с началом anchor. Тот же эфир (сдвинули время) — плановое начало сохраняется."""
        plan = self.live.plan if self.live and wid and self.live.webinar_id == wid else None
        self.live = Live(wid, anchor or datetime.now(), plan) if wid else None
        if not self.live:
            self.brk = self.slide = None
        self.save()

    def set_plan(self, plan: datetime | None) -> None:
        """Плановое начало идущего эфира (урок начали; учитель поменял время начала)."""
        if self.live is not None:
            self.live.plan = plan
            self.save()

    def set_break(self, brk: dict | None) -> None:
        self.brk = brk
        self.save()

    def set_slide(self, slide: dict | None) -> None:
        self.slide = slide
        self.save()
