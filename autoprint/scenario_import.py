"""Сценарная тетрадка (как «Занятие 6»: заголовки «⏱ 00:00–00:03 · Название», «🗣 **Говоришь:**» с цитатой,
«✅ **Ожидаемый вывод:**») → урок с этапами и плашками ролей. Исходный урок не меняется — получается копия.

    ⏱ ЧЧ:ММ–ЧЧ:ММ · Название   → этап; минуты — конец − начало; «перерыв» → перерыв; «заряд», «глаз», 🧘 → зарядка
    ✍️ в заголовке этапа         → пометка этапа «задание»
    # 🟦 ПЕРВАЯ ПОЛОВИНА — 45 минут (заголовок без ⏱) → раздел «Первая половина» для следующих этапов
    🗣 **Говоришь…:** + «> …»   → «Говоришь» (уточнение после «Говоришь» — заголовок плашки)
    ✅ **Ожидаемый вывод:** …    → «Вывод»
    **Решение — …:**            → «Делаешь»
    ⚠️ / ❗ → «Важно», ℹ️ → «Заметка», ❓ → «Спроси», 👀 → «Показываешь», ⌨️ и ⏱ (не заголовок) → «Делаешь»,
    остальное — «Заметка»
    ---                         → выбрасывается
"""
from __future__ import annotations

import re

from .storage import BLOCK_CODE, BLOCK_MARKDOWN, BLOCK_STAGE, Block, Template, new_id

_TIME = re.compile(r"⏱\s*(\d{1,2}):(\d{2})\s*[–—-]\s*(\d{1,2}):(\d{2})\s*[·•.:—-]?\s*(.*)$")
_HEAD = re.compile(r"^\s*(#{1,6})\s+(.*?)\s*$")
_RULE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
_SAY = re.compile(r"^\s*🗣\s*\*\*\s*Говоришь\s*([^*:]*?)\s*:?\s*\*\*\s*:?\s*(.*)$", re.I)
_OUT = re.compile(r"^\s*✅\s*\*\*\s*Ожидаемый вывод\s*:?\s*\*\*\s*:?\s*(.*)$", re.I)
_DO = re.compile(r"^\s*\*\*\s*(Решение[^*]*?)\s*:?\s*\*\*\s*:?\s*(.*)$", re.I)
_MARKS = (("⚠", "important"), ("❗", "important"), ("ℹ", "text"), ("❓", "ask"), ("👀", "show"), ("⌨", "do"),
          ("⏱", "do"))
_EMOJI = re.compile(r"[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]+")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", _EMOJI.sub("", s)).strip(" ·—-:")


def _sentence(s: str) -> str:
    """«ПЕРЕРЫВ 10 МИНУТ» → «Перерыв 10 минут» (заголовки в тетрадке часто капсом)."""
    if s.isupper():
        s = s.lower()
    return s[:1].upper() + s[1:]


def looks_like_scenario(blocks: list[Block]) -> bool:
    """Тетрадка-сценарий: хотя бы два заголовка с ⏱ и временем «от–до»."""
    n = 0
    for b in blocks:
        if b.type != BLOCK_MARKDOWN:
            continue
        for ln in b.text.split("\n"):
            m = _HEAD.match(ln)
            if m and _TIME.search(m.group(2)):
                n += 1
    return n >= 2


def _stage(line: str, part: str) -> Block | None:
    m = _TIME.search(line)
    if not m:
        return None
    h1, m1, h2, m2, rest = m.groups()
    minutes = max(0, (int(h2) * 60 + int(m2)) - (int(h1) * 60 + int(m1)))
    title = _sentence(_clean(rest)) or "Этап"
    low = title.lower()
    kind = "break" if "перерыв" in low else ("exercise" if ("заряд" in low or "глаз" in low or "🧘" in line) else "")
    note = "задание" if "✍" in line else ""
    return Block(BLOCK_STAGE, note, title=title, minutes=minutes, stage_kind=kind, part=part)


class _Notes:
    """Куски текста одной ячейки → заметки с ролями."""

    def __init__(self, out: list[Block]) -> None:
        self.out = out
        self.role, self.title, self.lines = "", "", []

    def start(self, role: str, title: str = "", first: str = "") -> None:
        self.flush()
        self.role, self.title, self.lines = role, title, ([first] if first else [])

    def add(self, line: str) -> None:
        if not self.role:
            self.role = "text"
        self.lines.append(line)

    def flush(self) -> None:
        if self.role:
            text = "\n".join(self.lines).strip("\n")
            if self.role in ("say", "tell"):
                text = "\n".join(re.sub(r"^\s*>\s?", "", ln) for ln in text.split("\n"))
            if self.role == "output":
                text = _output(text)
            text = text.strip()
            if text:
                self.out.append(Block(BLOCK_MARKDOWN, text, role=self.role, title=self.title))
        self.role, self.title, self.lines = "", "", []


def _output(text: str) -> str:
    """«`1`, `0`, `0`» → строки вывода; блок ``` — как есть."""
    t = text.strip()
    if "```" in t:
        return t
    parts = re.findall(r"`([^`]+)`", t)
    return "\n".join(parts) if parts else t


def recognize(t: Template) -> Template:
    """Копия урока: заголовки с ⏱ — этапы, метки 🗣 ✅ … — плашки ролей. Исходный урок не меняется."""
    out: list[Block] = []
    part = ""
    for b in t.blocks:
        if b.type != BLOCK_MARKDOWN:
            nb = Block(b.type, b.text, lang=b.lang, title=b.title, steps=list(b.steps), profile=b.profile,
                       minutes=b.minutes, stage_kind=b.stage_kind, part=b.part, role=b.role)
            out.append(nb)
            continue
        notes = _Notes(out)
        for ln in b.text.split("\n"):
            if _RULE.match(ln):
                continue
            h = _HEAD.match(ln)
            if h and _TIME.search(h.group(2)):
                notes.flush()
                st = _stage(h.group(2), part)
                if st is not None:
                    out.append(st)
                continue
            if h and len(h.group(1)) == 1 and re.search(r"половин|часть|раздел", h.group(2), re.I):
                notes.flush()
                part = _sentence(re.sub(r"\s*[—-]\s*\d+\s*мин\w*\s*$", "", _clean(h.group(2)), flags=re.I))
                continue
            m = _SAY.match(ln)
            if m:
                notes.start("say", _clean(m.group(1)).lstrip(",").strip(), m.group(2).strip())
                continue
            m = _OUT.match(ln)
            if m:
                notes.start("output", "", m.group(1).strip())
                continue
            m = _DO.match(ln)
            if m:
                first = _clean(m.group(1)) + ((" " + m.group(2).strip()) if m.group(2).strip() else "")
                notes.start("do", "", first)
                continue
            mark = next(((sym, role) for sym, role in _MARKS if ln.lstrip().startswith(sym)), None)
            if mark:
                notes.start(mark[1], "", ln.lstrip()[len(mark[0]):].lstrip("\ufe0f ").strip())
                continue
            if notes.role == "say" and notes.lines and ln.strip() and not ln.lstrip().startswith(">"):
                notes.start("text", "", ln)               # текст после цитаты «Говоришь» — уже не реплика
                continue
            notes.add(ln)
        notes.flush()
    for x in out:
        x.id = new_id()
    r = Template(title=f"{t.title} (сценарий)", blocks=out)
    return r
