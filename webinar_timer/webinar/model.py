"""Шаблоны вебинаров и расчёт повестки строго по часам.

Формат JSON совместим со страницей «Повестка эфира» (Таймер-с-настройками.html) и её config.json:
    {"start": "11:00", "schedule": [{"name": "Приветствие", "demo": "on", "min": 1}, ...]}
Дополнительные поля активности (необязательные): "remind" — напоминать о начале, "break" — перерыв
(заставка на экран демонстрации), "media" — картинка или видео на экран демонстрации (гимнастика для глаз,
фон перерыва). Если их нет, remind и break выводятся из названия и демонстрации.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

DEMO_ON, DEMO_OFF, DEMO_NONE = "on", "off", "none"
DEMO_TEXT = {DEMO_ON: "Демонстрация ВКЛ", DEMO_OFF: "Демонстрация ВЫКЛ", DEMO_NONE: ""}
_BREAK_RE = re.compile(r"перерыв", re.I)
_EYES_RE = re.compile(r"глаз|заряд", re.I)
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Activity:
    name: str
    demo: str = DEMO_OFF
    min: int = 5
    remind: bool | None = None      # None — по умолчанию: напоминать обо всём, что идёт без демонстрации
    is_break: bool | None = None    # None — по названию («перерыв»)
    media: str = ""                 # картинка или видео на экран демонстрации («Далее» в напоминании)

    @property
    def breaks(self) -> bool:
        return bool(_BREAK_RE.search(self.name)) if self.is_break is None else self.is_break

    @property
    def reminds(self) -> bool:
        """Напоминать о начале. Презентация (демонстрация ВКЛ) идёт сама — о ней не напоминаем."""
        if self.remind is not None:
            return self.remind
        return self.breaks or self.demo != DEMO_ON

    @property
    def kind(self) -> str:
        """Для оформления: break — перерыв, eyes — зарядка, "" — обычный блок."""
        if self.breaks:
            return "break"
        return "eyes" if _EYES_RE.search(self.name) else ""


@dataclass
class Plan:
    title: str
    start: str = "11:00"
    schedule: list[Activity] = field(default_factory=list)
    id: str = field(default_factory=new_id)
    part_min: int = 45      # действующий предел урока (до перерыва, между перерывами, после); 0 — без предела
    lesson_min: int | None = None   # своя продолжительность урока у шаблона; None — как в настройках
    lesson_names: list[str] = field(default_factory=list)   # названия уроков по порядку; пусто — «Урок N»

    def lesson_name(self, i: int) -> str:
        """Название урока i (с 0); пусто, если не задано."""
        return self.lesson_names[i] if 0 <= i < len(self.lesson_names) else ""

    @property
    def total_min(self) -> int:
        return sum(a.min for a in self.schedule)

    def parts(self) -> list[list[int]]:
        """Части занятия, разделённые перерывами: индексы блоков (сами перерывы не входят)."""
        out: list[list[int]] = [[]]
        for i, a in enumerate(self.schedule):
            if a.breaks:
                out.append([])
            else:
                out[-1].append(i)
        return [p for p in out if p]

    def part_total(self, part: list[int]) -> int:
        return sum(self.schedule[i].min for i in part)

    def part_of(self, index: int) -> list[int]:
        return next((p for p in self.parts() if index in p), [])

    def room(self, index: int) -> int | None:
        """Сколько минут ещё можно добавить блоку, не превысив предел части; None — без предела."""
        if not self.part_min or self.schedule[index].breaks:
            return None
        return self.part_min - self.part_total(self.part_of(index))

    def over_limit(self) -> list[tuple[int, int]]:
        """Части, превысившие предел: [(номер части с 1, минут)]."""
        if not self.part_min:
            return []
        return [(n, t) for n, p in enumerate(self.parts(), 1) if (t := self.part_total(p)) > self.part_min]


DEFAULT_SCHEDULE = [
    ("Приветствие", DEMO_ON, 1), ("Целеполагание", DEMO_OFF, 5), ("ПРЕЗЕНТАЦИЯ", DEMO_ON, 14),
    ("Зарядка для глаз", DEMO_OFF, 5), ("ПРЕЗЕНТАЦИЯ", DEMO_ON, 15), ("Выводы", DEMO_OFF, 5),
    ("ПЕРЕРЫВ", DEMO_NONE, 10), ("Приветствие", DEMO_OFF, 2), ("ПРЕЗЕНТАЦИЯ", DEMO_ON, 20),
    ("Зарядка для глаз", DEMO_OFF, 5), ("ПРЕЗЕНТАЦИЯ", DEMO_ON, 10), ("Выводы", DEMO_OFF, 8),
]


def default_plan() -> Plan:
    return Plan("Вебинар 1Т (пример)", "11:00", [Activity(n, d, m) for n, d, m in DEFAULT_SCHEDULE])


# ---------------------------------------------------------------- JSON

def parse_time(text: str) -> tuple[int, int]:
    m = _TIME_RE.match((text or "").strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError(f"Некорректное время старта: «{text}» (нужно ЧЧ:ММ)")
    return int(m.group(1)), int(m.group(2))


def activity_from(d: dict, i: int) -> Activity:
    if not isinstance(d, dict):
        raise ValueError(f"Блок {i + 1}: ожидается объект")
    name = str(d.get("name") if d.get("name") is not None else "").strip()
    if not name:
        raise ValueError(f"Блок {i + 1}: пустое название")
    try:
        minutes = float(d.get("min"))
    except (TypeError, ValueError):
        minutes = 0
    if not minutes > 0:
        raise ValueError(f"Блок «{name}»: минуты должны быть больше нуля")
    demo = d.get("demo") if d.get("demo") in (DEMO_ON, DEMO_OFF, DEMO_NONE) else DEMO_OFF
    remind = d.get("remind") if isinstance(d.get("remind"), bool) else None
    is_break = d.get("break") if isinstance(d.get("break"), bool) else None
    media = str(d.get("media") or "").strip()
    return Activity(name, demo, max(1, round(minutes)), remind, is_break, media)


def plan_from(d: dict, title: str = "Вебинар") -> Plan:
    """Из JSON (страница «Повестка эфира», её config.json или наш файл). ValueError — с понятным текстом."""
    if not isinstance(d, dict):
        raise ValueError("Ожидается объект JSON")
    start = str(d.get("start") or "11:00")
    h, m = parse_time(start)
    if not isinstance(d.get("schedule"), list):
        raise ValueError("Поле schedule должно быть списком")
    schedule = [activity_from(a, i) for i, a in enumerate(d["schedule"])]
    if not schedule:
        raise ValueError("Расписание пустое")
    def minutes(v) -> int | None:
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None

    part_min = minutes(d.get("part_min"))
    names = d.get("lessons")
    names = [str(n).strip() for n in names] if isinstance(names, list) else []
    return Plan(str(d.get("title") or title).strip() or title, f"{h:02d}:{m:02d}", schedule,
                str(d.get("id") or new_id()), 45 if part_min is None else part_min, minutes(d.get("lesson_min")),
                names)


def activity_to(a: Activity) -> dict:
    d = {"name": a.name, "demo": a.demo, "min": a.min}
    if a.remind is not None:
        d["remind"] = a.remind
    if a.is_break is not None:
        d["break"] = a.is_break
    if a.media:
        d["media"] = a.media
    return d


def plan_to(p: Plan) -> dict:
    d = {"id": p.id, "title": p.title, "start": p.start, "part_min": p.part_min,
         "schedule": [activity_to(a) for a in p.schedule]}
    if p.lesson_min is not None:
        d["lesson_min"] = p.lesson_min
    names = list(p.lesson_names)
    while names and not names[-1]:
        names.pop()
    if names:
        d["lessons"] = names
    return d


# ---------------------------------------------------------------- расчёт повестки

@dataclass
class Segment:
    index: int
    activity: Activity
    start: datetime
    end: datetime


@dataclass
class State:
    phase: str                       # before | running | after
    index: int                       # текущий блок (-1 — вне эфира)
    remaining: timedelta             # до конца блока (before — до начала эфира)
    progress: float                  # доля текущего блока (0…1)


def segments(plan: Plan, day: date) -> list[Segment]:
    h, m = parse_time(plan.start)
    t = datetime.combine(day, datetime.min.time()).replace(hour=h, minute=m)
    out = []
    for i, a in enumerate(plan.schedule):
        end = t + timedelta(minutes=a.min)
        out.append(Segment(i, a, t, end))
        t = end
    return out


def split_lessons(schedule: list[Activity]) -> tuple[list[list[Activity]], list[list[Activity]]]:
    """Расписание → (уроки, перерывы вокруг них). Перерывов на один набор больше: до первого урока,
    между уроками и после последнего (наборы бывают пустыми)."""
    groups: list[list[Activity]] = []
    seps: list[list[Activity]] = [[]]
    cur: list[Activity] | None = None
    for a in schedule:
        if a.breaks:
            if cur is not None:
                groups.append(cur)
                cur = None
                seps.append([])
            seps[-1].append(a)
        else:
            if cur is None:
                cur = []
            cur.append(a)
    if cur is not None:
        groups.append(cur)
        seps.append([])
    return groups, seps


def reorder_lessons(schedule: list[Activity], order: list[int]) -> list[Activity]:
    """Уроки целиком (все их блоки) в новом порядке order; перерывы остаются на своих местах."""
    groups, seps = split_lessons(schedule)
    if sorted(order) != list(range(len(groups))):
        raise ValueError("Порядок уроков: нужна перестановка всех уроков")
    out = list(seps[0])
    for k, i in enumerate(order):
        out += groups[i] + seps[k + 1]
    return out


def lessons(segs: list[Segment]) -> list[list[Segment]]:
    """Уроки: подряд идущие блоки между перерывами (сами перерывы не входят)."""
    out: list[list[Segment]] = [[]]
    for s in segs:
        if s.activity.breaks:
            out.append([])
        else:
            out[-1].append(s)
    return [x for x in out if x]


def state_at(segs: list[Segment], now: datetime) -> State:
    if not segs:
        return State("after", -1, timedelta(0), 0.0)
    if now < segs[0].start:
        return State("before", -1, segs[0].start - now, 0.0)
    for s in segs:
        if s.start <= now < s.end:
            return State("running", s.index, s.end - now, (now - s.start) / (s.end - s.start))
    return State("after", -1, timedelta(0), 1.0)


def fmt_left(td: timedelta) -> str:
    """Оставшееся время: «мм:сс» или «ч:мм:сс». Секунды округляются вверх — 00:00 только в самом конце."""
    s = max(0, int(-(-td.total_seconds() // 1)))
    h, rest = divmod(s, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
