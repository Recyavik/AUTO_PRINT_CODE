"""Шаблон вебинара и повестка строго по часам.

Шаблон — это и расписание, и «пресет» экрана эфира: фон, зарядки, перерыв. Формат JSON совместим со страницей
«Повестка эфира» (Таймер-с-настройками.html) и с «Таймером вебинара»:
    {"start": "11:00", "schedule": [{"name": "Приветствие", "demo": "on", "min": 1}, ...]}
Остальные поля необязательны — без них берутся значения по умолчанию.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

KIND_NORMAL, KIND_BREAK, KIND_EXERCISE = "", "break", "exercise"
KINDS = [(KIND_NORMAL, "Обычный"), (KIND_BREAK, "Перерыв"), (KIND_EXERCISE, "Зарядка")]
DEMO_ON, DEMO_OFF, DEMO_NONE = "on", "off", "none"
DEMOS = [(DEMO_ON, "Демонстрация ВКЛ"), (DEMO_OFF, "Демонстрация ВЫКЛ"), (DEMO_NONE, "—")]

_BREAK_RE = re.compile(r"перерыв|break", re.I)
_EXERCISE_RE = re.compile(r"заряд|глаз|гимнаст|физкульт|разминк", re.I)
_TIME_RE = re.compile(r"^\s*(\d{1,2})[:.](\d{2})\s*$")

# Фон экрана эфира: "color:#RRGGBB" | "anim:<имя>" | "image:<путь>"
BG_BLACK = "color:#000000"
ANIMATIONS = [
    ("gradient", "Градиент"),
    ("aurora", "Сияние"),
    ("lights", "Огоньки"),
    ("bubbles", "Пузыри"),
    ("cube", "Куб"),
    ("stars", "Звёзды"),
    ("pipes", "Трубы"),
]
ANIMATION_NAMES = dict(ANIMATIONS)

# Шрифт надписей перерыва и занавеса. Веб-шрифты грузятся из Google Fonts (кириллица есть у всех),
# без интернета — запасной системный. "file:<путь>" — свой файл шрифта (.otf/.ttf/.woff2)
FONTS = [
    ("Montserrat", "Montserrat"),
    ("Unbounded", "Unbounded"),
    ("Russo One", "Russo One"),
    ("Oswald", "Oswald"),
    ("Rubik Mono One", "Rubik Mono One"),
    ("Bahnschrift", "Bahnschrift (есть в Windows)"),
    ("Segoe UI", "Segoe UI (есть в Windows)"),
]
DEFAULT_FONT = "Montserrat"


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def parse_hhmm(text: str) -> tuple[int, int] | None:
    m = _TIME_RE.match(str(text or ""))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return h, mi


def guess_kind(name: str) -> str:
    if _BREAK_RE.search(name or ""):
        return KIND_BREAK
    if _EXERCISE_RE.search(name or ""):
        return KIND_EXERCISE
    return KIND_NORMAL


@dataclass
class Activity:
    name: str
    min: int = 5
    kind: str = KIND_NORMAL          # "" — обычный блок, break — перерыв, exercise — зарядка
    demo: str = DEMO_ON              # демонстрация экрана в этом блоке (подсказка ведущему)


@dataclass
class Exercise:
    title: str
    path: str                        # видеофайл (или картинка) на этом компьютере


@dataclass
class Webinar:
    title: str = "Новый вебинар"
    start: str = "11:00"
    schedule: list[Activity] = field(default_factory=list)
    background: str = BG_BLACK       # фон экрана эфира (он же занавес)
    caption: str = ""                # надпись на фоне (пусто — без надписи)
    exercises: list[Exercise] = field(default_factory=list)   # нет зарядок — нет кнопки «Зарядка»
    break_min: int = 10
    break_countdown: bool = True     # показывать обратный отсчёт
    break_background: str = ""       # "" — как основной фон
    break_title: str = "ПЕРЕРЫВ"
    break_show_title: bool = True    # показывать надпись перерыва (выкл — только фон и, если включён, отсчёт)
    break_done: str = "ПРОДОЛЖАЕМ"   # когда время перерыва вышло
    font: str = DEFAULT_FONT         # шрифт надписей (перерыв, занавес): имя или "file:<путь>"
    text_color: str = "#FFFFFF"
    id: str = field(default_factory=new_id)
    lesson_id: str = ""              # эфир урока из суфлёра (расписание — его этапы); в списке шаблонов не виден

    @property
    def total_min(self) -> int:
        return sum(a.min for a in self.schedule)

    def to_dict(self) -> dict:
        return asdict(self)

    def copy(self, title: str = "") -> "Webinar":
        w = webinar_from_dict(self.to_dict())
        w.id = new_id()
        if title:
            w.title = title
        return w


# ---------------------------------------------------------------- JSON

def _int(v, default: int, lo: int = 0, hi: int = 24 * 60) -> int:
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _str(v, default: str = "") -> str:
    return v.strip() if isinstance(v, str) else default


def _bg(v, default: str) -> str:
    v = _str(v)
    if v.startswith("color:") and re.fullmatch(r"color:#[0-9A-Fa-f]{6}", v):
        return v
    if v.startswith("anim:") and v[5:] in ANIMATION_NAMES:
        return v
    if v.startswith("image:") and len(v) > 6:
        return v
    return default


def activity_from_dict(d: dict) -> Activity | None:
    if not isinstance(d, dict):
        return None
    name = _str(d.get("name"))
    if not name:
        return None
    kind = d.get("kind")
    if kind not in (KIND_NORMAL, KIND_BREAK, KIND_EXERCISE):
        brk = d.get("break")             # «Таймер вебинара»: break — true/false/нет
        if brk is True:
            kind = KIND_BREAK
        elif brk is False:
            kind = KIND_EXERCISE if _EXERCISE_RE.search(name) else KIND_NORMAL
        else:
            kind = guess_kind(name)
    demo = d.get("demo") if d.get("demo") in (DEMO_ON, DEMO_OFF, DEMO_NONE) else DEMO_ON
    return Activity(name=name, min=_int(d.get("min", d.get("minutes", 5)), 5, 1), kind=kind, demo=demo)


def webinar_from_dict(d: dict) -> Webinar:
    """Шаблон из словаря: свой формат, «Повестка эфира» (start + schedule) или план «Таймера вебинара»."""
    if not isinstance(d, dict):
        raise ValueError("Ожидается объект JSON с расписанием")
    raw = d.get("schedule", d.get("blocks", d.get("activities")))
    if not isinstance(raw, list):
        raise ValueError("Нет списка schedule (блоки расписания)")
    schedule = [a for a in (activity_from_dict(x) for x in raw) if a]
    if not schedule:
        raise ValueError("Расписание пустое: у блоков нужны name и min")
    w = Webinar()
    w.title = _str(d.get("title", d.get("name")), "") or "Вебинар"
    start = _str(d.get("start"))
    w.start = start if parse_hhmm(start) else "11:00"
    w.schedule = schedule
    w.background = _bg(d.get("background"), BG_BLACK)
    w.caption = _str(d.get("caption"))
    ex = d.get("exercises")
    if isinstance(ex, list):
        for e in ex:
            if isinstance(e, dict) and _str(e.get("path")):
                w.exercises.append(Exercise(_str(e.get("title")) or "Зарядка", _str(e.get("path"))))
            elif isinstance(e, str) and e.strip():
                w.exercises.append(Exercise("Зарядка", e.strip()))
    w.break_min = _int(d.get("break_min"), 10, 1, 180)
    w.break_countdown = d.get("break_countdown") if isinstance(d.get("break_countdown"), bool) else True
    w.break_background = _bg(d.get("break_background"), "")
    w.break_title = _str(d.get("break_title"), "ПЕРЕРЫВ") or "ПЕРЕРЫВ"
    w.break_show_title = d.get("break_show_title") if isinstance(d.get("break_show_title"), bool) else True
    w.break_done = _str(d.get("break_done"), "ПРОДОЛЖАЕМ")
    font = _str(d.get("font"))
    w.font = font if font in dict(FONTS) or font.startswith("file:") else DEFAULT_FONT
    color = _str(d.get("text_color"))
    w.text_color = color if re.fullmatch(r"#[0-9A-Fa-f]{6}", color) else "#FFFFFF"
    if _str(d.get("id")) and re.fullmatch(r"[0-9a-zA-Z_-]{4,40}", d["id"]):
        w.id = d["id"]
    w.lesson_id = _str(d.get("lesson_id"))
    return w


def _json_candidates(text: str):
    """Куски текста, похожие на JSON: весь текст, блоки ```json```, первый {...} / [...] по балансу скобок."""
    text = (text or "").strip().lstrip("﻿")
    yield text
    for m in re.finditer(r"```(?:json)?\s*(.*?)```", text, re.S):
        yield m.group(1)
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        while start != -1:
            depth, in_str, esc = 0, False, False
            for i in range(start, len(text)):
                ch = text[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                elif ch == '"':
                    in_str = True
                elif ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        yield text[start:i + 1]
                        break
            start = text.find(opener, start + 1)


def parse_webinars(text: str) -> list[Webinar]:
    """Шаблоны из текста: файл экспорта, JSON «Повестки эфира», plans.json «Таймера вебинара» или ответ
    нейросети (JSON может быть обёрнут пояснениями и ```json```). Ошибка — ValueError с понятным текстом."""
    default_error = "В тексте не найден JSON с расписанием"
    last_error = default_error
    for chunk in _json_candidates(text):
        try:
            data = json.loads(chunk)
        except ValueError:
            continue
        items: list = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            for key in ("webinars", "plans", "templates"):
                if isinstance(data.get(key), list):
                    items = data[key]
                    break
            else:
                items = [data]
        out = []
        for it in items:
            try:
                out.append(webinar_from_dict(it))
            except ValueError as e:
                if last_error == default_error:      # первая ошибка — по самому большому куску, она понятнее
                    last_error = str(e)
        if out:
            return out
    raise ValueError(last_error)


def export_json(webinars: list[Webinar]) -> str:
    if len(webinars) == 1:
        return json.dumps(webinars[0].to_dict(), ensure_ascii=False, indent=2)
    return json.dumps({"webinars": [w.to_dict() for w in webinars]}, ensure_ascii=False, indent=2)


def ai_prompt(example: Webinar | None = None) -> str:
    """Промпт для нейросети: формат и пример. Ответ (JSON) вставляется «Импорт → Из буфера»."""
    ex = example.copy() if example else sample_webinar()
    ex.exercises = []                 # пути к файлам — только этого компьютера
    ex.background = BG_BLACK if ex.background.startswith("image:") else ex.background
    ex.break_background = "" if ex.break_background.startswith("image:") else ex.break_background
    ex.font = DEFAULT_FONT if ex.font.startswith("file:") else ex.font
    sample = {"title": ex.title, "start": ex.start, "break_min": ex.break_min,
              "schedule": [{"name": a.name, "min": a.min, "kind": a.kind, "demo": a.demo} for a in ex.schedule]}
    return (
        "Составь расписание вебинара в формате JSON для программы AutoPrintCode (раздел «Эфир»).\n\n"
        "Формат:\n"
        "- title — название шаблона (например, «Вебинар 1Т — первая пара»);\n"
        "- start — время начала «ЧЧ:ММ»;\n"
        "- break_min — длительность перерыва по умолчанию, минут;\n"
        "- schedule — блоки по порядку: name — название, min — минуты (целое > 0),\n"
        "  kind — \"\" обычный блок, \"break\" перерыв, \"exercise\" зарядка (например, для глаз),\n"
        "  demo — \"on\" демонстрация экрана включена, \"off\" выключена, \"none\" не важно.\n\n"
        "Ответь только JSON, без пояснений. Пример:\n"
        + json.dumps(sample, ensure_ascii=False, indent=2)
        + "\n\nМоё расписание (опиши своими словами: что, сколько минут, где перерыв и зарядки):\n"
    )


def sample_webinar() -> Webinar:
    """Шаблон по умолчанию — как «Повестка эфира» из HTML."""
    rows = [("Приветствие", 1, DEMO_ON), ("Целеполагание", 5, DEMO_OFF), ("Теория", 14, DEMO_ON),
            ("Зарядка для глаз", 5, DEMO_OFF), ("Теория", 15, DEMO_ON), ("Выводы", 5, DEMO_OFF),
            ("Перерыв", 10, DEMO_NONE), ("Приветствие", 2, DEMO_OFF), ("Практика", 20, DEMO_ON),
            ("Зарядка для глаз", 5, DEMO_OFF), ("Практика", 10, DEMO_ON), ("Выводы", 8, DEMO_OFF)]
    return Webinar(title="Вебинар", start="11:00",
                   schedule=[Activity(n, m, guess_kind(n), d) for n, m, d in rows])


# ---------------------------------------------------------------- повестка по часам

@dataclass
class Segment:
    index: int
    activity: Activity
    start: datetime
    end: datetime


@dataclass
class Agenda:
    """Что идёт сейчас. phase: before — эфир ещё не начался, live — идёт, after — закончился."""
    phase: str
    index: int = -1                   # текущий блок (live), иначе -1
    current: Segment | None = None
    next: Segment | None = None
    left_s: float = 0.0               # live — до конца блока, before — до начала эфира
    next_in_s: float = 0.0            # до начала следующего блока
    frac: float = 0.0                 # прошло от текущего блока, 0..1
    total_frac: float = 0.0           # прошло от всего эфира, 0..1
    start: datetime | None = None
    end: datetime | None = None


def anchor_for(start: str, day: date | None = None) -> datetime:
    hm = parse_hhmm(start) or (11, 0)
    d = day or date.today()
    return datetime(d.year, d.month, d.day, hm[0], hm[1])


def anchor_at(hhmm: str, now: datetime) -> datetime:
    """Начало эфира «в ЧЧ:ММ»: из вчера, сегодня и завтра — ближайшее к now. Опоздали на 20 минут — сегодня
    (эфир уже идёт); 23:50 → «00:10» — завтра; 00:05 → «23:50» — вчера. Пусто или неверно — now."""
    hm = parse_hhmm(hhmm)
    if not hm:
        return now
    base = now.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
    return min((base + timedelta(days=d) for d in (-1, 0, 1)), key=lambda t: abs((t - now).total_seconds()))


def norm_hhmm(hhmm: str) -> str:
    hm = parse_hhmm(hhmm)
    return f"{hm[0]:02d}:{hm[1]:02d}" if hm else ""


def segments(w: Webinar, anchor: datetime) -> list[Segment]:
    out, t = [], anchor
    for i, a in enumerate(w.schedule):
        end = t + timedelta(minutes=a.min)
        out.append(Segment(i, a, t, end))
        t = end
    return out


def agenda_at(segs: list[Segment], now: datetime) -> Agenda:
    if not segs:
        return Agenda("after")
    start, end = segs[0].start, segs[-1].end
    total = max(1.0, (end - start).total_seconds())
    if now < start:
        return Agenda("before", next=segs[0], left_s=(start - now).total_seconds(),
                      next_in_s=(start - now).total_seconds(), start=start, end=end)
    if now >= end:
        return Agenda("after", total_frac=1.0, start=start, end=end)
    for s in segs:
        if s.start <= now < s.end:
            nxt = segs[s.index + 1] if s.index + 1 < len(segs) else None
            dur = max(1.0, (s.end - s.start).total_seconds())
            return Agenda("live", s.index, s, nxt, left_s=(s.end - now).total_seconds(),
                          next_in_s=(s.end - now).total_seconds() if nxt else 0.0,
                          frac=(now - s.start).total_seconds() / dur,
                          total_frac=(now - start).total_seconds() / total, start=start, end=end)
    return Agenda("after", total_frac=1.0, start=start, end=end)


def anchor_to_start_at(segs: list[Segment], index: int, now: datetime) -> datetime:
    """Старт эфира, при котором блок index начинается сейчас («начать с этого блока», «сдвинуть на сейчас»)."""
    if not segs:
        return now
    index = max(0, min(index, len(segs) - 1))
    return now - (segs[index].start - segs[0].start)


def fmt_left(seconds: float) -> str:
    """12:05 или 1:02:05 (секунды вниз не округляем, чтобы «00:00» не висело целую секунду до конца)."""
    s = max(0, int(seconds + 0.999))
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def fmt_minutes(n: int) -> str:
    h, m = divmod(max(0, int(n)), 60)
    if h and m:
        return f"{h} ч {m} мин"
    return f"{h} ч" if h else f"{m} мин"
