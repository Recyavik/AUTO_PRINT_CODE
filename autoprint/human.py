"""Имитация ручного набора: живой ритм, паузы на обдумывание, опечатки с исправлением.

Работает поверх готовых единиц печати (build_units) и только добавляет к ним:
  * k     — множитель задержки после символа (быстрые знакомые слова, медленный Shift…);
  * pause — пауза перед символом (обдумывание новой строки, заминка между словами);
  * опечатки — лишние «char»-единицы и «back» (Backspace). У них src_end не растёт,
    поэтому шкала прогресса и пауза/продолжение работают как обычно.

Безопасность для IDE: опечатка — только буква внутри слова из букв, и всё, что
набрано до исправления, тоже буквы этого слова. Скобки, кавычки, отступы и Enter
никогда не участвуют, поэтому автоскобки и автодополнение редактора не задеваются.
"""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .storage import Settings
    from .typer import Unit

# слова, которые программист набирает «на автомате» — быстрее остальных
FAMILIAR = set("""
print return def self import from for in if else elif while True False None and or not range len
class input int str float list dict set append pass break continue with as try except lambda
const let var function console log new this null true false
""".split())
# слова, перед которыми человек задумывается (начало нового смыслового куска)
THINK_BEFORE = set("def class for while if elif else try except with return import from function".split())

SHIFTED = set('~!@#$%^&*()_+{}|:"<>?')

_ROWS = (
    ("1234567890-=", "qwertyuiop[]", "asdfghjkl;'", "zxcvbnm,./"),
    ("1234567890-=", "йцукенгшщзхъ", "фывапролджэ", "ячсмитьбю."),
)


def _neighbors() -> dict[str, str]:
    near: dict[str, str] = {}
    for rows in _ROWS:
        for r, row in enumerate(rows):
            for i, ch in enumerate(row):
                if not ch.isalpha():
                    continue
                cand = [row[j] for j in (i - 1, i + 1) if 0 <= j < len(row)]
                for rr in (r - 1, r + 1):
                    if 0 <= rr < len(rows) and i < len(rows[rr]):
                        cand.append(rows[rr][i])
                near[ch] = "".join(c for c in cand if c.isalpha())
    return near


NEIGHBORS = _neighbors()


def _is_letter(u: "Unit") -> bool:
    return u.kind == "char" and len(u.text) == 1 and u.text.isalpha()


def _wrong_key(ch: str, rng: random.Random) -> str | None:
    near = NEIGHBORS.get(ch.lower())
    if not near:
        return None
    c = rng.choice(near)
    return c.upper() if ch.isupper() else c


def humanize(units: list["Unit"], settings: "Settings", rng: random.Random | None = None) -> list["Unit"]:
    from .typer import Unit

    rng = rng or random.Random()
    think = max(0.0, settings.think_pause_s)
    typo_p = max(0, settings.typo_per_100_words) / 100   # вероятность опечатки в слове

    # слова: непрерывные отрезки букв/цифр/_ в единицах «char»
    n = len(units)
    word_of = [None] * n
    i = 0
    while i < n:
        if units[i].kind == "char" and (units[i].text.isalnum() or units[i].text == "_"):
            j = i
            while j < n and units[j].kind == "char" and (units[j].text.isalnum() or units[j].text == "_"):
                j += 1
            for k in range(i, j):
                word_of[k] = (i, j)
            i = j
        else:
            i += 1

    def word(span) -> str:
        return "".join(units[k].text for k in range(*span))

    # --- проход 1: ритм (k) и паузы (pause) для каждого символа
    line_start = True        # следующий печатный символ — первый на строке
    prev_blank = True        # предыдущая строка пустая (или начало текста)
    line_has_text = False
    drift_phase = rng.uniform(0, 2 * math.pi)
    prev_ch = ""
    for idx, u in enumerate(units):
        if u.kind == "newline":
            prev_blank = not line_has_text
            line_start, line_has_text, prev_ch = True, False, ""
            continue
        if u.kind != "char" or (line_start and not u.text.strip()):
            continue        # отступы и служебные единицы — без изменений
        span = word_of[idx]
        w = word(span) if span else ""
        at_word_start = bool(span) and span[0] == idx

        if line_start and think:
            pause = rng.uniform(0.15, 0.45) * think
            if prev_blank:
                pause += rng.uniform(0.3, 0.7) * think           # новый смысловой кусок
            if w in THINK_BEFORE:
                pause += rng.uniform(0.1, 0.4) * think
            u.pause = pause
        elif at_word_start and think and rng.random() < 0.04:
            u.pause = rng.uniform(0.1, 0.4) * think              # заминка посреди строки
        line_start, line_has_text = False, True

        ch = u.text
        k = 1.0
        if w in FAMILIAR:
            k *= 0.65
        elif at_word_start:
            k *= 1.3
        if ch in SHIFTED or ch.isupper():
            k *= 1.35
        elif ch.isdigit():
            k *= 1.15
        elif not ch.isalnum() and ch not in " _":
            k *= 1.2
        if ch == prev_ch:
            k *= 0.8
        k *= 1 + 0.1 * math.sin(drift_phase + idx / 60)        # плавный дрейф темпа
        u.k, prev_ch = k, ch

    # --- проход 2: опечатки — решается один раз на слово из букв
    out: list[Unit] = []
    i = 0
    while i < n:
        span = word_of[i]
        if (span and span[0] == i and typo_p and span[1] - span[0] >= 3 and rng.random() < typo_p
                and all(_is_letter(units[t]) for t in range(*span))):
            out.extend(_typo(units, span, rng, Unit))
            i = span[1]
            continue
        out.append(units[i])
        i += 1
    return out


def _typo(units, span, rng: random.Random, Unit) -> list:
    """Слово с опечаткой: ошибка → (0–2 верных буквы) → заметил → Backspace → правильно."""
    a, b = span
    letters = [units[t] for t in range(a, b)]
    pos = rng.randrange(1, len(letters))           # первая буква — без ошибок
    kind = rng.choice(("near", "near", "near", "swap", "double"))
    if kind == "swap" and pos + 1 >= len(letters):
        kind = "near"
    good = pos                                     # столько букв набрано верно до ошибки
    if kind == "near":
        wrong = _wrong_key(letters[pos].text, rng)
        if not wrong:
            return letters
        typed_wrong = [wrong]
        after = pos + 1
    elif kind == "swap":
        typed_wrong = [letters[pos + 1].text, letters[pos].text]
        after = pos + 2
    else:   # double: буква набрана верно, но дважды — стереть надо только лишнюю
        good = pos + 1
        typed_wrong = [letters[pos].text]
        after = pos + 1
    extra = min(rng.choice((0, 0, 1, 1, 2)), len(letters) - after)   # успел набрать дальше

    out = list(letters[:good])
    src_before = letters[good - 1].src_end
    for c in typed_wrong:
        out.append(Unit("char", c, src_before, k=1.0))
    for t in range(after, after + extra):
        out.append(Unit("char", letters[t].text, src_before, k=letters[t].k))
    for i in range(len(typed_wrong) + extra):      # заметил ошибку: пауза, затем Backspace
        out.append(Unit("back", "", src_before, k=0.6, pause=rng.uniform(0.25, 0.7) if i == 0 else 0.0))
    out.extend(letters[good:])
    return out
