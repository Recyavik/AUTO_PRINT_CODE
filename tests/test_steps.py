"""Печать по шагам: после каждого шага в редакторе — ровно строки шагов 1…k (без комментариев, если включено).

    python tests/test_steps.py

Редактор эмулируется: документ, курсор, клавиши Ctrl+Home/End, ↑/↓, End, Enter. Профиль «Блокнот»
(без автоотступов), чтобы проверялась именно логика шагов и переходов.
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["AUTOPRINT_DATA"] = tempfile.mkdtemp(prefix="autoprint-steps-")

from autoprint import steps as S  # noqa: E402
from autoprint.comments import strip_comments  # noqa: E402
from autoprint.storage import PROFILE_PLAIN, Settings  # noqa: E402
from autoprint.typer import build_units  # noqa: E402

failed: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {name}{' — ' + extra if extra else ''}")
    if not ok:
        failed.append(name)


class Editor:
    """Документ + курсор; клавиши как в простом редакторе без переноса строк."""

    def __init__(self) -> None:
        self.lines, self.r, self.c = [""], 0, 0

    def insert(self, s: str) -> None:
        for ch in s:
            if ch == "\n":
                self.enter()
            else:
                ln = self.lines[self.r]
                self.lines[self.r] = ln[:self.c] + ch + ln[self.c:]
                self.c += 1

    def enter(self) -> None:
        ln = self.lines[self.r]
        self.lines[self.r:self.r + 1] = [ln[:self.c], ln[self.c:]]
        self.r, self.c = self.r + 1, 0

    def back(self) -> None:
        if self.c:
            ln = self.lines[self.r]
            self.lines[self.r] = ln[:self.c - 1] + ln[self.c:]
            self.c -= 1
        elif self.r:
            prev = self.lines[self.r - 1]
            self.lines[self.r - 1:self.r + 1] = [prev + self.lines[self.r]]
            self.r, self.c = self.r - 1, len(prev)

    def key(self, name: str) -> None:
        if name == "ctrl_home":
            self.r, self.c = 0, 0
        elif name == "ctrl_end":
            self.r = len(self.lines) - 1
            self.c = len(self.lines[self.r])
        elif name == "down":
            self.r = min(len(self.lines) - 1, self.r + 1)
            self.c = min(self.c, len(self.lines[self.r]))
        elif name == "up":
            self.r = max(0, self.r - 1)
            self.c = min(self.c, len(self.lines[self.r]))
        elif name == "end":
            self.c = len(self.lines[self.r])
        elif name == "home":
            # «умный» Home как в VS Code: сначала к началу текста строки, повторно — в столбец 0
            ln = self.lines[self.r]
            first = len(ln) - len(ln.lstrip(" \t"))
            self.c = first if self.c != first else 0
        elif name == "enter_raw":
            self.enter()
        else:
            raise ValueError(name)

    def run(self, units) -> None:
        for u in units:
            if u.kind in ("char", "fast"):
                self.insert(u.text)
            elif u.kind == "newline":
                self.enter()
            elif u.kind == "back":
                self.back()
            elif u.kind == "nav":
                self.key(u.text)
            elif u.kind == "tab":
                self.insert("    ")
            elif u.kind == "cleanup":
                pass
            else:
                raise ValueError(u.kind)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def settings(human: bool = False) -> Settings:
    s = Settings()
    s.profile = PROFILE_PLAIN
    s.human_typing = human
    s.typos_per_100 = 3.0
    return s


def expected(text: str, steps: list[int], k: int, lang: str, strip: bool) -> str:
    lines = S.analyze(text, steps, lang, strip)
    return "\n".join(sl.typed for sl in lines if sl.typed is not None and sl.step <= k)


def play(text: str, steps: list[int], lang: str = "python", strip: bool = False, human: bool = False,
         name: str = "", nav: str = "home", before: list[str] | None = None,
         after: list[str] | None = None) -> bool:
    """Печать всех шагов. before/after — код, который уже был в файле выше/ниже места печати
    (урок — продолжение файла); курсор ставится в начало пустой строки между ними."""
    s = settings(human)
    lines = S.analyze(text, steps, lang, strip)
    ed = Editor()
    before, after = before or [], after or []
    ed.lines = before + [""] + after
    ed.r, ed.c = len(before), 0
    ok = True
    for k in S.step_numbers(steps, len(text.split("\n"))):
        ed.run(S.build_step_units(lines, k, s, nav))
        exp = "\n".join(before + [expected(text, steps, k, lang, strip)] + after)
        if ed.text != exp:
            print(f"   [{name}] шаг {k}:\n   GOT {ed.text!r}\n   EXP {exp!r}")
            ok = False
            break
    return ok


LESSON = '''import statistics

# Оценки учеников
grades = [5, 4, 3, 5, 4]
grades.append(5)  # пришла ещё одна оценка
print("Оценки:", grades)

# Средний балл
average = sum(grades) / len(grades)
print("Средний:", round(average, 2))

# Медиана — из модуля statistics
median = statistics.median(grades)
print("Медиана:", median)'''
LESSON_STEPS = [3, 3, 1, 1, 4, 1, 2, 2, 2, 2, 3, 3, 3, 3]


def main() -> int:
    check("урок: шаги с возвратом наверх", play(LESSON, LESSON_STEPS, name="урок"))
    check("урок без комментариев", play(LESSON, LESSON_STEPS, strip=True, name="урок/strip"))
    check("урок «как человек» (опечатки исправляются)", play(LESSON, LESSON_STEPS, human=True, name="урок/human"))

    # итог без комментариев совпадает с обычным удалением комментариев
    lines = S.analyze(LESSON, LESSON_STEPS, "python", True)
    full = "\n".join(sl.typed for sl in lines if sl.typed is not None)
    check("без комментариев: итог = strip_comments", full == strip_comments(LESSON, "python")[0])

    # суфлёр: комментарии шага
    nar = S.narration(LESSON, S.analyze(LESSON, LESSON_STEPS, "python", True), 2, "python")
    check("суфлёр шага 2", nar == ["Средний балл"], repr(nar))
    nar4 = S.narration(LESSON, S.analyze(LESSON, LESSON_STEPS, "python", True), 4, "python")
    check("суфлёр: хвостовой комментарий тоже", nar4 == ["пришла ещё одна оценка"], repr(nar4))

    # первый шаг — без переходов (печать там, где курсор)
    u1 = S.build_step_units(S.analyze(LESSON, LESSON_STEPS, "python", False), 1, settings())
    check("первый шаг без переходов", not any(u.kind == "nav" for u in u1))

    # src_end — позиции в тексте блока, растут внутри куска и не выходят за текст
    u3 = S.build_step_units(S.analyze(LESSON, LESSON_STEPS, "python", False), 3, settings())
    ends = [u.src_end for u in u3 if u.kind == "char"]
    check("src_end в пределах текста", all(0 < e <= len(LESSON) for e in ends))

    # автоматическая разметка
    by_c = S.auto_by_comments(LESSON, "python")
    # код до первого комментария (import) — свой шаг, дальше каждый комментарий открывает шаг
    check("разметка по комментариям", by_c == [1, 2, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4], repr(by_c))
    by_b = S.auto_by_blank_lines(LESSON)
    check("разметка по пустым строкам: 4 шага", max(by_b) == 4, repr(by_b))
    check("пустая строка — со следующим куском", by_b[1] == by_b[2], repr(by_b))

    # шаги с пропусками в нумерации и «пустые» шаги (только комментарии)
    t = "# только слова\nx = 1\n# ещё слова\ny = 2"
    check("шаг из одних комментариев", play(t, [1, 2, 3, 3], strip=True, name="comments-only"))
    check("нумерация с пропусками", play("a = 1\nb = 2\nc = 3", [2, 5, 2], name="gaps"))

    # случайные разметки: всегда точный итог
    rnd = random.Random(7)
    bad = 0
    for trial in range(400):
        n = rnd.randint(1, 14)
        src = []
        for i in range(n):
            kind = rnd.random()
            if kind < 0.15:
                src.append("")
            elif kind < 0.3:
                src.append("    " * rnd.randint(0, 2) + f"# заметка {i}")
            else:
                src.append("    " * rnd.randint(0, 2) + f"v{i} = {i}" + ("  # хвост" if rnd.random() < 0.2 else ""))
        text = "\n".join(src)
        st = [rnd.randint(1, 5) for _ in range(n)]
        for strip in (False, True):
            if not play(text, st, strip=strip, name=f"random#{trial}/{strip}"):
                bad += 1
            # стрелками от курсора — и как продолжение файла: код выше и ниже не задевается
            if not play(text, st, strip=strip, nav="arrows", name=f"random#{trial}/{strip}/arrows"):
                bad += 1
            if not play(text, st, strip=strip, nav="arrows", before=["import os", "", "x = 1"],
                        after=["", "# конец файла"], name=f"random#{trial}/{strip}/continue"):
                bad += 1
    check("400 случайных разметок × 2 режима × 3 способа перехода", bad == 0, f"ошибок: {bad}")

    # урок как продолжение уже написанного кода: стрелки не уходят в начало и конец файла
    existing = ["# уже было в файле", "def hello():", "    print('привет')", ""]
    check("урок — продолжение файла (стрелками)",
          play(LESSON, LESSON_STEPS, strip=True, nav="arrows", before=existing, after=["", "hello()"],
               name="continue"))
    # вставка над первой строкой блока, когда она с отступом (Home дважды)
    check("вставка над строкой с отступом",
          play("    b = 2\n    c = 3", [2, 1], nav="arrows", before=["def f():"], name="indent-top"))

    # обычная печать не изменилась: построчный режим помечает ожидание только после непустых строк
    units = build_units("a\n\nb\nc", settings(), line_wait=True)
    waits = [u.wait for u in units if u.kind == "newline"]
    check("по строкам: ждём после непустых строк", waits == [True, False, True], repr(waits))

    # разметка шагов переживает экспорт в .ipynb и импорт обратно
    from autoprint.importers import export_ipynb, import_ipynb
    from fixtures import steps_template
    nb = Path(os.environ["AUTOPRINT_DATA"]) / "урок.ipynb"
    src_t = steps_template()
    export_ipynb(src_t, str(nb))
    back = import_ipynb(str(nb))
    check("шаги: экспорт в .ipynb и импорт обратно", [b.steps for b in back.blocks] == [b.steps for b in src_t.blocks],
          repr([b.steps for b in back.blocks]))

    print("ГОТОВО" if not failed else f"ОШИБКИ: {failed}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
