"""Занятие от нейросети: промпт, формат ответа (JSON) и разбор ответа в занятие.

Путей два, результат один:
- «Скопировать промпт» → вставить в свой чат (ChatGPT, Claude, DeepSeek…) → ответ вставить обратно в «Импорт»;
- подключённая нейросеть (⚙ → Нейросеть) — тот же промпт уходит по API, ответ разбирается сам.

Как разложить материал (STYLES):
- «С комментариями» — код целиком, в нём комментарии для преподавателя: что сказать перед каждым куском;
- «По шагам» — то же, плюс номер шага у каждой строки (печать по шагам, с возвратом наверх);
- «По частям» — несколько блоков кода, между ними пояснения.

Формат ответа (FORMAT):
{
  "format": "autoprintcode-lesson", "version": 1,
  "title": "Название занятия",
  "blocks": [
    {"type": "task" | "explain" | "hint" | "text", "text": "Markdown"},
    {"type": "code", "lang": "python", "code": "код с комментариями"},
    {"type": "code", "lang": "python", "lines": [[1, "строка"], [1, "строка"], [3, "import …"], …]}
  ]
}
"lines" — строки итогового файла по порядку, у каждой номер шага, на котором она появляется: шаг может
дописать строки выше уже напечатанных (import в начало). Так число строк и шагов не может разойтись.

Большой код (is_big) — «разметка» (Options.marks): переписывать сотни строк нейросеть будет долго и упрётся
в предел длины ответа. Поэтому строки материала нумеруются, а нейросеть отвечает только разметкой —
какие строки на каком шаге и что сказать перед ними; код программа берёт из материала, он остаётся точно
вашим:
{"format": "autoprintcode-lesson", "version": 1, "mode": "marks", "title": "…", "lang": "python",
 "intro": [{"type": "task", "text": "…"}],
 "marks": [{"from": 1, "to": 12, "step": 1, "say": "что сказать перед этими строками"}, …]}
"""
from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from typing import Callable

from .comments import comment_line, comment_spans, strip_comments, supported
from .importers import guess_lang
from .storage import BLOCK_CODE, BLOCK_IMAGE, BLOCK_MARKDOWN, BLOCK_STAGE, ROLES, Block, Template

FORMAT = "autoprintcode-lesson"

STYLE_COMMENTS, STYLE_STEPS, STYLE_PARTS, STYLE_SCENARIO = "comments", "steps", "parts", "scenario"
STYLES = {
    STYLE_COMMENTS: "С комментариями",
    STYLE_STEPS: "По шагам",
    STYLE_PARTS: "По частям",
    STYLE_SCENARIO: "Сценарий урока",   # суфлёр урока: этапы со временем, что сказать / спросить / показать
}
DETAIL_SHORT, DETAIL_FULL = "short", "full"

# код больше — разбор «разметкой»: нейросеть не переписывает код, а размечает строки
BIG_LINES = 120
BIG_CHARS = 6000


@dataclass
class Options:
    style: str = STYLE_STEPS
    task: bool = True            # краткое условие задачи в начале занятия
    explain: bool = True         # пояснения для учеников (отдельные текстовые блоки)
    keep_code: bool = True       # код не менять — только комментарии и разметка
    detail: str = DETAIL_SHORT   # комментарии: коротко | подробно
    lang: str = ""               # язык кода, если известен ("" — пусть определит нейросеть)
    marks: bool = False          # большой код: ответ — разметка строк, код берётся из материала
    minutes: int = 90            # сценарий урока: длительность урока
    break_min: int = 0           # сценарий урока: перерыв (0 — только если он есть в материале)
    cls: str = ""                 # сценарий урока: класс / возраст учеников
    topic: str = ""               # сценарий урока: тема (без материала нейросеть составляет урок по ней)


def source_lines(material: str) -> list[str]:
    """Строки материала так, как они пронумерованы для нейросети (с 1)."""
    text = material.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    return [ln.rstrip() for ln in text.split("\n")]


def is_big(material: str) -> bool:
    """Код такой длины разбирать «разметкой»."""
    src = source_lines(material)
    return len(src) > BIG_LINES or sum(len(x) for x in src) > BIG_CHARS


# ---------------------------------------------------------------- промпт

_STYLE_RULES = {
    STYLE_COMMENTS: """\
Разложи в ОДИН блок кода ("type": "code" с полем "code").
В коде перед каждым смысловым куском — строка-комментарий для преподавателя: что сказать ученикам
перед тем, как этот кусок появится. Хвостовые комментарии (после кода на той же строке) — только
если очень коротко поясняют неочевидное место.""",
    STYLE_STEPS: """\
Разложи в ОДИН блок кода с ПОШАГОВОЙ разметкой ("type": "code" с полем "lines").
"lines" — все строки итогового файла по порядку, у каждой номер шага: [номер_шага, "текст строки"].
Шаги — как преподаватель пишет программу у доски: сначала простое и данные, потом обработка, потом
вывод. Шаг может дописывать строки ВЫШЕ уже написанного: например, import, который понадобился на
шаге 3, стоит первой строкой файла, но с номером 3. Шагов обычно 3–8, в шаге 1–6 строк кода.
Каждый шаг начинается со строки-комментария для преподавателя — что сказать перед этим шагом
(у неё тот же номер шага). Пустые строки — с номером шага соседнего кода.""",
    STYLE_PARTS: """\
Разложи на ЧАСТИ: чередуй блоки "explain" (что делаем в этой части, 1–3 предложения для учеников)
и "code" (кусок программы с полем "code"). Части по порядку дают всю программу целиком.
Обычно 2–6 частей. В коде каждой части — строки-комментарии для преподавателя: что сказать.""",
}


def build_prompt(material: str, opt: Options) -> str:
    """Промпт целиком для «Скопировать промпт»: правила, формат, пример — и материал пользователя в конце."""
    return instruction(opt) + material_for(material, opt)


def material_for(material: str, opt: Options) -> str:
    """Материал отдельным сообщением — в том виде, что нужен разбору (сценарий, разметка, обычный)."""
    if opt.style == STYLE_SCENARIO:
        return f"\nМАТЕРИАЛ (методичка, презентация или расшифровка урока):\n<<<\n{material.strip()}\n>>>\n"
    return material_message(material, opt.marks)


def material_message(material: str, numbered: bool = False) -> str:
    if numbered:
        body = "\n".join(f"{i}| {ln}" for i, ln in enumerate(source_lines(material), 1))
        return (f"\nМАТЕРИАЛ — строки пронумерованы («номер| текст»; номер и «| » — не часть кода):\n"
                f"<<<\n{body}\n>>>\n")
    return f"\nМАТЕРИАЛ (код или задание с решением):\n<<<\n{material.strip()}\n>>>\n"


def instruction(opt: Options) -> str:
    """Правила, формат и пример — без материала (по API это системное сообщение, материал — отдельным)."""
    if opt.style == STYLE_SCENARIO:
        return lesson_instruction(opt, source="next")
    if opt.marks:
        return _marks_instruction(opt)
    keep = ("Код НЕ МЕНЯЙ: ни имён, ни логики, ни ПОРЯДКА строк, ни форматирования — только добавь комментарии "
            "(и разметку шагов/частей). Строки кода в ответе идут ровно в том порядке, что и в исходном файле; "
            "в разборе по шагам порядок итогового файла тоже исходный — меняются только номера шагов "
            "(например, import стоит первой строкой, но с номером позднего шага). Если в материале есть "
            "условие задачи — его не переписывай в код."
            if opt.keep_code else
            "Код можно поправить, если в нём ошибка или он явно неудобен для объяснения новичкам, — но "
            "без лишнего усложнения.")
    detail = ("Комментарии короткие: одна строка, по сути, разговорным языком."
              if opt.detail == DETAIL_SHORT else
              "Комментарии подробные: 1–3 строки, объясняй «зачем», а не только «что», разговорным языком.")
    extra = []
    if opt.task:
        extra.append('Первым блоком — краткое условие задачи ("type": "task", Markdown: заголовок «## …» и '
                     '1–4 строки). Если условия в материале нет — сформулируй его по коду.')
    if opt.explain and opt.style != STYLE_PARTS:
        extra.append('Перед кодом — блок "explain": 1–3 предложения для учеников, что будем делать.')
    if not opt.explain and opt.style != STYLE_PARTS:
        extra.append('Блоков "explain" не добавляй.')
    lang = f'Язык кода: {opt.lang}.' if opt.lang else 'Язык кода определи сам ("lang": python, javascript, …).'
    example = _EXAMPLES[opt.style]
    return f"""{_INTRO}

{_STYLE_RULES[opt.style]}

{keep}
{detail}
{lang}
{chr(10).join(extra)}

ОТВЕТ — ТОЛЬКО JSON, без пояснений до и после, по формату:
{{
  "format": "{FORMAT}", "version": 1,
  "title": "короткое название занятия",
  "blocks": [ ... ]
}}
Типы блоков: "task" (условие), "explain" (пояснение), "hint" (подсказка), "text" (просто текст) — с полем
"text" (Markdown); "code" — с полем "lang" и либо "code" (строка), либо "lines" (пошаговая разметка).
Внутри строк JSON экранируй кавычки и переводы строк как положено (\\" и \\n).

Пример ответа (по смыслу, не копируй):
{example}
"""


_INTRO = """Ты помогаешь преподавателю программирования подготовить занятие для программы AutoPrintCode.
Программа сама «печатает» код в редактор во время урока, а преподаватель в это время объясняет.
Комментарии в коде — это подсказки преподавателю: программа может не печатать их, а показывать
на суфлёре — что сказать перед следующим куском. Пиши комментарии на русском, как живую речь
преподавателя, обращаясь к ученикам («сейчас заведём…», «обратите внимание…»). Не начинай комментарии
со слов «Шаг 1:», «Часть 2:» — программа сама показывает номер шага."""

_MARKS_RULES = {
    STYLE_COMMENTS: """\
"marks" — смысловые куски кода по порядку (функция, цикл, подготовка данных — обычно 3–20 строк):
"from" и "to" — номера первой и последней строки куска, "say" — комментарий для преподавателя, что
сказать перед этим куском (программа вставит его строкой-комментарием над куском). "step" не нужен.""",
    STYLE_STEPS: """\
"marks" — разбор ПО ШАГАМ, как преподаватель пишет программу у доски: сначала простое и данные, потом
обработка, потом вывод. Каждая метка — диапазон строк "from"–"to" и номер шага "step", на котором эти
строки появляются. Шаг может дописывать строки ВЫШЕ уже написанного: например, import в строке 1
понадобился на шаге 3 — метка {"from": 1, "to": 1, "step": 3}. У шага может быть несколько меток
(одинаковый "step"). "say" — что сказать перед шагом (у первой метки шага; у остальных — "").
Для большого кода шагов обычно 6–25, в шаге — 3–30 строк.""",
    STYLE_PARTS: """\
"marks" — ЧАСТИ программы по порядку (обычно 4–12): "from"–"to" — строки части, "say" — пояснение
для учеников, что делаем в этой части (1–3 предложения). Программа сделает из каждой части пояснение
и блок кода.""",
}

_MARKS_EXAMPLES = {
    STYLE_COMMENTS: """{"format": "autoprintcode-lesson", "version": 1, "mode": "marks", "title": "Оценки", "lang": "python",
 "intro": [{"type": "task", "text": "## Средний балл\\nПосчитать средний балл и медиану."}],
 "marks": [
  {"from": 1, "to": 2, "say": "Подключаем модуль statistics — в нём есть медиана"},
  {"from": 3, "to": 3, "say": "Заводим список оценок"},
  {"from": 4, "to": 5, "say": "Средний балл и медиана"}
 ]}""",
    STYLE_STEPS: """{"format": "autoprintcode-lesson", "version": 1, "mode": "marks", "title": "Оценки", "lang": "python",
 "intro": [{"type": "explain", "text": "Посчитаем средний балл и медиану."}],
 "marks": [
  {"from": 3, "to": 3, "step": 1, "say": "Сначала — сами оценки"},
  {"from": 4, "to": 4, "step": 2, "say": "Средний балл: сумму делим на количество"},
  {"from": 1, "to": 2, "step": 3, "say": "Медиану возьмём из модуля statistics — допишем import наверх"},
  {"from": 5, "to": 5, "step": 3, "say": ""}
 ]}""",
    STYLE_PARTS: """{"format": "autoprintcode-lesson", "version": 1, "mode": "marks", "title": "Оценки", "lang": "python",
 "intro": [],
 "marks": [
  {"from": 1, "to": 3, "say": "Подключим модуль и заведём список оценок."},
  {"from": 4, "to": 5, "say": "Посчитаем средний балл и медиану."}
 ]}""",
}


def _marks_instruction(opt: Options) -> str:
    """Промпт «разметки» для большого кода: код не переписывать — только номера строк, шаги и комментарии."""
    detail = ('Комментарии ("say") короткие: одна строка, по сути, разговорным языком.'
              if opt.detail == DETAIL_SHORT else
              'Комментарии ("say") подробные: 1–3 предложения, объясняй «зачем», а не только «что».')
    intro = []
    if opt.task:
        intro.append('"intro" начинается с краткого условия задачи ("type": "task", Markdown: заголовок «## …» '
                     'и 1–4 строки). Если условия в материале нет — сформулируй его по коду.')
    if opt.explain and opt.style != STYLE_PARTS:
        intro.append('В "intro" — блок "explain": 1–3 предложения для учеников, что будем делать.')
    if not intro:
        intro.append('"intro" — пустой список.')
    lang = f'Язык кода: {opt.lang}.' if opt.lang else 'Язык кода определи сам ("lang": python, javascript, …).'
    return f"""{_INTRO}

Код большой, поэтому НЕ ПЕРЕПИСЫВАЙ его в ответ — программа возьмёт его из материала сама, без изменений.
Строки материала пронумерованы. Ответь РАЗМЕТКОЙ: какие строки куда относятся и что сказать перед ними.

{_MARKS_RULES[opt.style]}

Метки не пересекаются и вместе покрывают весь код — с первой строки кода до последней, включая
docstring, комментарии, импорты и пустые строки. Не включай только то, что не код: условие задачи или
пояснения, если они есть в материале отдельным текстом. Номера — ровно те, что стоят в материале слева.
{detail}
{lang}
{chr(10).join(intro)}

ОТВЕТ — ТОЛЬКО JSON, без пояснений до и после, по формату:
{{
  "format": "{FORMAT}", "version": 1, "mode": "marks",
  "title": "короткое название занятия", "lang": "язык кода",
  "intro": [ {{"type": "task" | "explain", "text": "Markdown"}} ],
  "marks": [ {{"from": номер, "to": номер, "step": номер_шага, "say": "что сказать"}}, … ]
}}

Пример ответа (по смыслу, не копируй; материал примера — 5 строк: import, пустая, список оценок,
средний балл, медиана):
{_MARKS_EXAMPLES[opt.style]}
"""




_EXAMPLES = {
    STYLE_COMMENTS: """{"format": "autoprintcode-lesson", "version": 1, "title": "Сумма списка",
 "blocks": [
  {"type": "task", "text": "## Сумма чисел\\nНапишите функцию total(nums) без sum()."},
  {"type": "code", "lang": "python", "code": "# Заводим функцию, которая принимает список\\ndef total(nums):\\n    # Копим сумму в переменной, начинаем с нуля\\n    result = 0\\n    for n in nums:\\n        result += n\\n    return result"}
 ]}""",
    STYLE_STEPS: """{"format": "autoprintcode-lesson", "version": 1, "title": "Оценки",
 "blocks": [
  {"type": "explain", "text": "Посчитаем средний балл и медиану."},
  {"type": "code", "lang": "python", "lines": [
    [3, "import statistics"], [3, ""],
    [1, "# Сначала — сами оценки"], [1, "grades = [5, 4, 3, 5]"],
    [2, "# Средний балл: сумму делим на количество"], [2, "average = sum(grades) / len(grades)"],
    [3, "# Медиану возьмём из модуля statistics — допишем import наверх"],
    [3, "median = statistics.median(grades)"]
  ]}
 ]}""",
    STYLE_PARTS: """{"format": "autoprintcode-lesson", "version": 1, "title": "Чётные числа",
 "blocks": [
  {"type": "explain", "text": "Сначала заведём список чисел."},
  {"type": "code", "lang": "python", "code": "# Список, с которым будем работать\\nnums = [1, 2, 3, 4]"},
  {"type": "explain", "text": "Теперь отберём чётные."},
  {"type": "code", "lang": "python", "code": "# Остаток от деления на 2 равен нулю — число чётное\\nevens = [n for n in nums if n % 2 == 0]"}
 ]}""",
}


# ---------------------------------------------------------------- разбор ответа

class LessonError(ValueError):
    """Понятная пользователю ошибка разбора ответа."""


@dataclass
class Parsed:
    template: Template
    warnings: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        t = self.template
        codes = t.code_blocks()
        steps = sum(len(set(b.steps)) for b in codes if b.steps and len(set(b.steps)) > 1)
        parts = [f"блоков: {len(t.blocks)}", f"кода: {len(codes)}"]
        stages = [b for b in t.blocks if b.type == BLOCK_STAGE]
        if stages:
            parts.insert(0, f"этапов: {len(stages)} · {sum(b.minutes for b in stages)} мин")
        if steps:
            parts.append(f"шагов: {steps}")
        return " · ".join(parts)


_TYPE_ROLE = {"task": "task", "explain": "explain", "hint": "hint", "text": "text", "markdown": "text",
              "условие": "task", "пояснение": "explain", "подсказка": "hint",
              # суфлёр урока
              "say": "say", "tell": "tell", "ask": "ask", "do": "do", "important": "important", "show": "show",
              "trap": "trap", "traps": "trap", "extra": "extra", "question": "ask", "action": "do",
              "говоришь": "say", "расскажи": "tell", "спроси": "ask", "делаешь": "do", "важно": "important",
              "показываешь": "show", "ловушки": "trap", "для быстрых": "extra",
              "term": "term", "термин": "term", "output": "output", "вывод": "output", "задание": "task",
              "заметка": "text", "homework": "homework", "домашнее задание": "homework", "домашка": "homework",
              "goal": "goal", "цель": "goal", "цель урока": "goal", "если застрял": "hint",
              "типичные ошибки": "trap", "результат кода": "output"}
_STAGE_TYPES = {"stage", "этап"}
_IMAGE_TYPES = {"image", "picture", "slide", "картинка", "слайд"}
_STAGE_KINDS = {"break": "break", "перерыв": "break", "exercise": "exercise", "зарядка": "exercise",
                "гимнастика": "exercise", "normal": "", "": ""}


def _stage_block(raw: dict, n: int) -> Block:
    from .efir.model import KIND_BREAK, KIND_EXERCISE, guess_kind
    title = str(raw.get("title") or raw.get("name") or "").strip() or f"Этап {n}"
    try:
        minutes = max(0, min(24 * 60, int(raw.get("min", raw.get("minutes", raw.get("duration"))) or 0)))
    except (TypeError, ValueError):
        minutes = 0
    kind = _STAGE_KINDS.get(str(raw.get("kind") or "").strip().lower())
    if kind is None:     # «practice», «теория» — не вид этапа: смотрим на название (Перерыв, Гимнастика для глаз)
        kind = ""
    if not kind:
        g = guess_kind(title)
        kind = "break" if g == KIND_BREAK else "exercise" if g == KIND_EXERCISE else ""
    note = str(raw.get("note") or raw.get("text") or "").strip()
    return Block(BLOCK_STAGE, note, title=title[:120], minutes=minutes, stage_kind=kind,
                 part=str(raw.get("part") or "").strip()[:120])


def _answers(raw) -> list[str]:
    if isinstance(raw, list):
        items = [str(x) for x in raw]
    else:
        items = str(raw or "").split("\n")
    return [re.sub(r"^\s*(→|->)\s*", "", x).strip() for x in items if str(x).strip()]


def extract_json(text: str):
    """JSON из ответа нейросети: без ```-ограды и пояснений вокруг. None — JSON нет."""
    s = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", s, re.S)
    if fence:
        s = fence.group(1)
    a, b = s.find("{"), s.rfind("}")
    if a < 0 or b <= a:
        return None
    body = s[a:b + 1]
    for candidate in (body, re.sub(r",\s*([}\]])", r"\1", body)):   # лишние запятые перед } и ]
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    return None


def is_lesson_json(text: str) -> bool:
    data = extract_json(text)
    return isinstance(data, dict) and (data.get("format") == FORMAT or isinstance(data.get("blocks"), list)
                                       or isinstance(data.get("marks"), list))


def _compact_steps(steps: list[int]) -> list[int]:
    """Номера шагов подряд с 1, порядок сохраняется (3, 7, 7, 9 → 1, 2, 2, 3)."""
    order = {s: i + 1 for i, s in enumerate(sorted(set(steps)))}
    return [order[s] for s in steps]


def _lines(raw, n_block: int, warnings: list[str]) -> tuple[str, list[int]]:
    texts, steps = [], []
    for item in raw:
        if isinstance(item, dict):
            st, tx = item.get("step", item.get("s", 1)), item.get("text", item.get("t", ""))
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            st, tx = item
        else:
            raise LessonError(f"Блок кода {n_block}: строка разметки шагов не в формате [шаг, \"текст\"].")
        try:
            st = max(1, int(st))
        except (TypeError, ValueError):
            st = steps[-1] if steps else 1
        texts.append(str(tx).replace("\r", "").replace("\n", " "))
        steps.append(st)
    if not texts:
        raise LessonError(f"Блок кода {n_block}: пустая разметка шагов.")
    compact = _compact_steps(steps)
    if compact != steps:
        warnings.append(f"Блок кода {n_block}: номера шагов выровнены по порядку (1, 2, 3…).")
    return "\n".join(texts), compact


def parse_lesson(text: str, title: str = "", material: str = "", style: str = "",
                 slide: Callable[[int], str | None] | None = None) -> Parsed:
    """Ответ нейросети (или наш JSON) → занятие. LessonError — если разобрать нельзя.
    material и style нужны «разметке» большого кода: код берётся из материала.
    slide(N) — путь к картинке слайда N материала (PDF) для блоков {"type": "image", "slide": N}."""
    # ответ своего чата — урок в Markdown (блок ~~~markdown или .md с шапкой «---»), а не JSON
    looks_md = any(_MD_OPEN.match(x) for x in text.split("\n")) or text.lstrip().startswith("---")
    md = md_answer(text) if looks_md else None
    if md is not None:
        return _parse_md_answer(md, title, slide)
    data = extract_json(text)
    if data is None:
        raise LessonError("В ответе не нашёлся JSON. Попросите нейросеть ответить строго в формате из промпта "
                          "(без пояснений), или вставьте код во вкладке «Вставить».")
    if isinstance(data, dict) and isinstance(data.get("autoprintcode_template"), dict):
        data = data["autoprintcode_template"]          # наш экспорт занятия в .json
    if isinstance(data, dict) and (data.get("mode") == "marks" or isinstance(data.get("marks"), list)):
        return _parse_marks(data, material, style, title)
    if not isinstance(data, dict) or not isinstance(data.get("blocks"), list):
        raise LessonError("В JSON нет списка блоков (\"blocks\").")
    warnings: list[str] = []
    blocks: list[Block] = []
    n_code = 0
    for i, raw in enumerate(data["blocks"], 1):
        if not isinstance(raw, dict):
            warnings.append(f"Блок {i} пропущен: это не объект.")
            continue
        kind = str(raw.get("type", "")).strip().lower()
        if kind in _STAGE_TYPES:
            blocks.append(_stage_block(raw, sum(b.type == BLOCK_STAGE for b in blocks) + 1))
            continue
        if kind in _IMAGE_TYPES:
            n = _int(raw.get("slide", raw.get("page")))
            url = str(raw.get("url") or raw.get("src") or "").strip()
            path = slide(n) if n and slide else None
            if not path and re.match(r"https?://", url, re.I):
                path = url
            caption = str(raw.get("caption") or raw.get("title") or raw.get("text") or "").strip()
            if path:
                blocks.append(Block(BLOCK_IMAGE, path, title=caption[:200]))
            elif n:
                warnings.append(f"Блок {i}: картинку «слайд {n}» не вставить — нет PDF с таким слайдом.")
            else:
                warnings.append(f"Блок {i}: картинка без файла и адреса — пропущена.")
            continue
        if kind == "code" or "code" in raw or "lines" in raw:
            n_code += 1
            lang = str(raw.get("lang") or "python").lower()
            if isinstance(raw.get("lines"), list):
                code, steps = _lines(raw["lines"], n_code, warnings)
            else:
                code = str(raw.get("code") or raw.get("text") or "").replace("\r\n", "\n").strip("\n")
                steps = []
                if isinstance(raw.get("steps"), list):
                    try:
                        steps = [max(1, int(s)) for s in raw["steps"]]
                    except (TypeError, ValueError):
                        steps = []
            if not code.strip():
                warnings.append(f"Блок кода {n_code} пустой — пропущен.")
                continue
            blocks.append(Block(BLOCK_CODE, code, lang=lang, steps=steps, title=str(raw.get("title") or "")))
        else:
            role = _TYPE_ROLE.get(kind, "text")
            if kind and kind not in _TYPE_ROLE:
                warnings.append(f"Блок {i}: неизвестный тип «{kind}» — стал обычным текстом.")
            body = str(raw.get("text") or "").replace("\r\n", "\n").strip()
            if role == "ask" and raw.get("answer"):
                body = "\n".join([body] + [f"→ {a}" for a in _answers(raw["answer"])]).strip()
            if body:
                blocks.append(Block(BLOCK_MARKDOWN, body, role=role if role in ROLES else "text"))
    has_code = any(b.type == BLOCK_CODE for b in blocks)
    if not has_code and not any(b.type == BLOCK_STAGE for b in blocks):
        raise LessonError("В ответе нет ни этапов урока, ни блоков кода.")
    name = str(data.get("title") or title or "Новое занятие").strip()[:120]
    t = Template(title=name, blocks=blocks)
    t.active_block = next((b.id for b in blocks if b.type == BLOCK_CODE), "")
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", str(data.get("start") or ""))
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        t.start = f"{int(m.group(1)):02d}:{m.group(2)}"       # плановое начало урока, если оно есть в материале
    return Parsed(t, warnings)


# ---------------------------------------------------------------- разметка большого кода

_FENCE = re.compile(r"^\s*```")
_SKIP = -1
# начало строки, с которого начинается код, а не текст задачи
_CODE_HEAD = re.compile(r'("""|\'\'\'|#|//|/\*|--|<|@|import\b|from\s+\S+\s+import\b|def\b|class\b|package\b|using\b|'
                        r'const\b|let\b|var\b|function\b|public\b|int\b|void\b|fn\b|func\b|[\w.]+\s*=[^=]|\w+\()')


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _text_blocks(raw_list) -> list[Block]:
    out = []
    for raw in raw_list or []:
        if isinstance(raw, str):
            raw = {"type": "text", "text": raw}
        if not isinstance(raw, dict):
            continue
        role = _TYPE_ROLE.get(str(raw.get("type", "")).lower(), "text")
        body = str(raw.get("text") or "").replace("\r\n", "\n").strip()
        if body:
            out.append(Block(BLOCK_MARKDOWN, body, role=role if role in ROLES else "text"))
    return out


def _read_marks(raw_marks: list, n: int, warnings: list[str]) -> list[dict]:
    marks, bad = [], 0
    for m in raw_marks:
        if not isinstance(m, dict):
            bad += 1
            continue
        a = _int(m.get("from", m.get("start", m.get("line"))))
        b = _int(m.get("to", m.get("end")))
        if isinstance(m.get("lines"), list) and len(m["lines"]) == 2:
            a, b = _int(m["lines"][0]), _int(m["lines"][1])
        if a is None:
            bad += 1
            continue
        b = a if b is None else b
        if b < a:
            a, b = b, a
        if b < 1 or a > n:
            bad += 1
            continue
        say = m.get("say", m.get("comment", m.get("text", "")))
        marks.append({"from": max(1, a), "to": min(n, b), "step": _int(m.get("step")),
                      "say": str(say or "").replace("\r", "").strip()})
    if bad:
        warnings.append(f"Меток не разобрано: {bad} (нет номеров строк или они вне кода).")
    return sorted(marks, key=lambda m: (m["from"], m["to"]))


def _drop_broken_comments(lines: list[tuple[int, str, bool]], lang: str,
                          warnings: list[str]) -> list[tuple[int, str, bool]]:
    """Вставленный комментарий должен остаться комментарием: метка, начатая внутри многострочной строки
    (docstring, шаблон), испортила бы её — такой комментарий убираем."""
    if not supported(lang):
        return lines   # язык без разбора комментариев — проверить нечем
    text = "\n".join(tx for _st, tx, _c in lines)
    starts, pos = [], 0
    for _st, tx, _c in lines:
        starts.append(pos)
        pos += len(tx) + 1
    spans = {a for a, _b in comment_spans(text, lang)}
    keep, bad = [], 0
    for (st, tx, ins), at in zip(lines, starts):
        if ins and at + len(tx) - len(tx.lstrip()) not in spans:
            bad += 1
            continue
        keep.append((st, tx, ins))
    if bad:
        warnings.append(f"Комментариев убрано: {bad} — они попали бы внутрь многострочной строки кода.")
    return keep


def _parse_marks(data: dict, material: str, style: str, title: str) -> Parsed:
    """«Разметка» большого кода → занятие: код — из материала, от нейросети только шаги и комментарии."""
    src = source_lines(material) if material.strip() else []
    if not src:
        raise LessonError("Это разметка без кода (ответ для большого кода): разбирать её нужно вместе с кодом — "
                          "вставьте ответ во вкладке «С помощью нейросети», где вставлен ваш код.")
    if not isinstance(data.get("marks"), list) or not data["marks"]:
        raise LessonError('В разметке нет меток ("marks") — попросите нейросеть ответить по формату из промпта.')
    warnings: list[str] = []
    n = len(src)
    marks = _read_marks(data["marks"], n, warnings)
    if not marks:
        raise LessonError("В разметке нет ни одной метки с номерами строк.")
    if not style:
        style = STYLE_STEPS if any(m["step"] for m in marks) else STYLE_COMMENTS
    # чья каждая строка: первой метки, что её покрывает; строки между метками и после — соседней сверху
    owner: list[int | None] = [None] * (n + 1)
    for i, m in enumerate(marks):
        for ln in range(m["from"], m["to"] + 1):
            if owner[ln] is None:
                owner[ln] = i
    first = marks[0]["from"]
    unmarked = 0
    for ln in range(1, n + 1):
        if _FENCE.match(src[ln - 1]):
            owner[ln] = _SKIP     # ``` из Markdown — не код
        elif owner[ln] is None and ln > first:
            owner[ln] = next((owner[k] for k in range(ln - 1, 0, -1) if owner[k] not in (None, _SKIP)), None)
            if src[ln - 1].strip():
                unmarked += 1
    lead = [x.strip() for x in src[:first - 1] if x.strip() and not _FENCE.match(x)]
    if lead and _CODE_HEAD.match(lead[0]):
        # нейросеть не разметила начало файла (docstring, комментарий, import) — это код: к первой метке
        for ln in range(1, first):
            if owner[ln] is None:
                owner[ln] = owner[first]
                unmarked += 1 if src[ln - 1].strip() else 0
    elif lead:
        warnings.append(f"Строки 1–{first - 1} не вошли в код — похоже на условие задачи: «{lead[0][:60]}»…")
    if unmarked:
        warnings.append(f"Строк без разметки: {unmarked} — добавлены к соседнему куску.")
    last = 1
    for m in marks:   # шаг не указан — как у предыдущей метки
        m["step"] = max(1, m["step"]) if m["step"] else last
        last = m["step"]
    lang = str(data.get("lang") or "").lower().strip() or guess_lang("\n".join(src))
    blocks = _text_blocks(data.get("intro"))
    if style == STYLE_PARTS:
        parts: list[tuple[int, list[str]]] = []
        for ln in range(1, n + 1):
            o = owner[ln]
            if o is None or o == _SKIP:
                continue
            if not parts or parts[-1][0] != o:
                parts.append((o, []))
            parts[-1][1].append(src[ln - 1])
        for o, rows in parts:
            while rows and not rows[0].strip():
                rows.pop(0)
            while rows and not rows[-1].strip():
                rows.pop()
            if rows:
                if marks[o]["say"]:
                    blocks.append(Block(BLOCK_MARKDOWN, marks[o]["say"], role="explain"))
                blocks.append(Block(BLOCK_CODE, "\n".join(rows), lang=lang))
    else:
        lines: list[tuple[int, str, bool]] = []      # (шаг, строка, это вставленный комментарий)
        said: set[int] = set()
        for ln in range(1, n + 1):
            o = owner[ln]
            if o is None or o == _SKIP:
                continue
            m, line = marks[o], src[ln - 1]
            if o not in said and line.strip():
                # комментарий-подсказка — строкой над первой строкой куска, с её отступом
                said.add(o)
                indent = line[:len(line) - len(line.lstrip())]
                for part in m["say"].split("\n"):
                    if part.strip():
                        lines.append((m["step"], indent + comment_line(part.strip(), lang), True))
            lines.append((m["step"], line, False))
        lines = _drop_broken_comments(lines, lang, warnings)
        while lines and not lines[-1][1].strip():
            lines.pop()
        while lines and not lines[0][1].strip():
            lines.pop(0)
        if lines:
            steps = _compact_steps([st for st, _tx, _c in lines]) if style == STYLE_STEPS else []
            blocks.append(Block(BLOCK_CODE, "\n".join(tx for _st, tx, _c in lines), lang=lang, steps=steps))
    if not any(b.type == BLOCK_CODE for b in blocks):
        raise LessonError("По разметке не набралось ни одной строки кода.")
    name = str(data.get("title") or title or "Новое занятие").strip()[:120]
    t = Template(title=name, blocks=blocks)
    t.active_block = next(b.id for b in blocks if b.type == BLOCK_CODE)
    return Parsed(t, warnings)


def _norm_code(text: str, lang: str) -> list[str]:
    """Код без комментариев и пустых строк, без хвостовых пробелов — для сравнения «код не меняли»."""
    bare = strip_comments(text, lang)[0]
    return [ln.rstrip() for ln in bare.split("\n") if ln.strip()]


def code_changes(original: str, parsed: Parsed) -> list[str]:
    """Чем код занятия отличается от исходного (без учёта комментариев и пустых строк). [] — не менялся."""
    codes = parsed.template.code_blocks()
    if not codes or not original.strip():
        return []
    lang = codes[0].lang
    got = [ln for b in codes for ln in _norm_code(b.text, b.lang)]
    want = _norm_code(original, lang)
    if got == want or _subsequence(got, want):
        return []   # в материале могло быть ещё условие задачи — его строк в коде нет, порядок кода тот же
    if sorted(got) == sorted(want) or (set(got) <= set(want) and len(got) == len(set(got))):
        # те же строки в другом порядке: переставленные — те, что не входят в общую последовательность
        sm = difflib.SequenceMatcher(a=want, b=got, autojunk=False)
        kept = {i for blk in sm.get_matching_blocks() for i in range(blk.b, blk.b + blk.size)}
        moved = [got[i] for i in range(len(got)) if i not in kept]
        return [f"строка переставлена: {ln.strip()}" for ln in moved[:6]]
    diff = [ln for ln in difflib.unified_diff(want, got, lineterm="", n=0) if ln[:1] in "+-"
            and not ln.startswith(("+++", "---"))]
    return diff[:12]


def _subsequence(small: list[str], big: list[str]) -> bool:
    """Все строки small встречаются в big в том же порядке (между ними могут быть лишние)."""
    it = iter(big)
    return all(any(x == y for y in it) for x in small)


# ---------------------------------------------------------------- урок: свой чат и встроенная нейросеть
# Один промпт урока: ответ — наш формат .md (а не JSON) — его можно прочитать и поправить прямо в чате, кавычки не
# ломаются. Свой чат: «Скопировать промпт» → ChatGPT, GigaChat, Алиса, DeepSeek → ответ в «Урок через нейросеть»
# или «Вставить». Встроенная нейросеть: тот же текст системным сообщением, материал — следующим.

CHAT_FORMAT = """ФОРМАТ ОТВЕТА — урок в Markdown:

---
title: Название урока
---

> [!goal]
> Цель урока: что ученики будут уметь после него (до первого этапа).

# Раздел урока (необязательно: «Первая половина», «Практика»)

## Название этапа · 10 мин

Строка этапа строго: «## Название · 10 мин» (точка посередине, число и «мин»). Перерыв и зарядка — отдельными этапами: «## Перерыв · 10 мин · перерыв», «## Гимнастика для глаз · 3 мин · зарядка».
Под этапом — плашки, по порядку урока. Плашка — цитата, первая строка [!роль]:

> [!say]
> Говоришь — обязательно и дословно: только то, что учитель произносит слово в слово — определение, главный тезис (1–3 предложения). Если в материале речь выделена (цветом, кавычками, репликой с «—») — переноси её сюда.

> [!tell]
> - Расскажи — объяснения своими словами, пунктами

> [!term]
> Термин
> Определение — дословно.

> [!ask]
> Вопрос классу?
> → верный ответ
> → частая ошибка — и что на неё сказать

Другие роли — так же: [!do] Делаешь (вслух не читается), [!show] Показываешь (что видят ученики — общими словами),
[!important] Важно, [!task] Задание ученикам, [!hint] Если застрял (наводящий вопрос), [!extra] Для быстрых,
[!trap] Типичные ошибки, [!homework] Домашнее задание, [!text] заметка для себя. В плашках — Markdown: списки «- »,
**жирный**, `код`, ссылки [текст](адрес); ссылки из материала сохраняй.

Программа печатает только код; всё остальное — подсказки учителю на экране, ученики их не видят. Код, который пишут
вместе с учениками (его программа набирает в редакторе), — блоком ```язык (код из материала — без изменений), а сразу
под ним, если известно, что он выведет:

> [!output]
> что напечатает код

В конце урока:

> [!homework]
> Домашнее задание — что сделать дома.
"""

CHAT_EXAMPLE = """Пример ответа на два слайда (по смыслу, не копируй):
~~~markdown
---
title: Функции в Python
---

> [!goal]
> Ученики пишут функцию с параметром и вызывают её для разных данных.

## Что такое функция · 8 мин

![Слайд 1](slide:1)

> [!say]
> Функция — именованный блок кода, который выполняет одну задачу.

![Слайд 2](slide:2)

> [!ask]
> Где вы уже вызывали функции?
> → print()
> → len()
~~~
"""

_PICTURES = ("КАРТИНКИ:\n"
             "- слайд или страница материала — «![Слайд N](slide:N)» там, где этот слайд стоит держать перед глазами;\n"
             "- фото из интернета — «![что на фото](https://…)», только если знаешь точный прямой адрес картинки "
             "(.jpg, .png, .webp);\n"
             "- картинка нужна, но адреса нет — «![что должно быть на картинке](фото)»: учитель вставит её сам.\n")


def _plan_lines(plan: Template) -> list[str]:
    from .lesson_md import stage_line
    return [stage_line(b) for b in plan.blocks if b.type == BLOCK_STAGE]


def lesson_instruction(opt: Options, *, plan: Template | None = None, exercises=(), slides=None,
                       source: str = "attached") -> str:
    """Промпт урока без материала. source: "attached" — материал приложен к сообщению в чате; "below" — он в конце
    промпта; "next" — придёт следующим сообщением (встроенная нейросеть). plan — план урока: этапы строго по нему.
    exercises — названия видео зарядок у учителя. slides — [(номер, заголовок[, заметки])] слайдов урока."""
    head = ("Ты помогаешь учителю подготовить урок для программы AutoPrintCode — суфлёра урока: на экране учителя "
            "по этапам видно, что сказать, что спросить, что показать. Твой ответ учитель загрузит в программу, "
            "поэтому формат строгий. Пиши по-русски, коротко и конкретно.\n\n")
    stages = [b for b in plan.blocks if b.type == BLOCK_STAGE] if plan is not None else []
    if stages:
        minutes = sum(max(0, int(b.minutes or 0)) for b in stages)
        head += f"УРОК: {minutes} мин. Сумма минут всех этапов — ровно {minutes}.\n"
    else:
        minutes = max(5, int(opt.minutes or 90))
        brk = f", перерыв {opt.break_min} мин отдельным этапом в середине" if opt.break_min else ""
        head += f"УРОК: {minutes} мин{brk}. Сумма минут всех этапов — ровно {minutes}.\n"
    cls = (opt.cls or "").strip()
    topic = (opt.topic or "").strip()
    if topic:
        head += f"ТЕМА УРОКА: {topic}.\n"
    head += f"Класс / возраст учеников: {cls or '___ (если не указан — определи по материалу)'}.\n"
    if source == "below":
        head += "Опирайся только на материал ниже; не выдумывай фактов, которых в нём нет.\n\n"
    elif source == "topic":
        head += ("Материала нет: составь урок по теме, плану и классу сам — только надёжные факты из школьной программы "
                 "и учебников; в чём не уверен — не пиши.\n\n")
    elif source == "attached_or_topic":
        head += ("Материал урока (методичка, презентация) может быть приложен к сообщению — тогда опирайся только на "
                 "него. Если материала нет — составь урок по теме, плану и классу сам: только надёжные факты из школьной "
                 "программы; в чём не уверен — не пиши.\n\n")
    elif source == "files":
        head += ("Материал урока — файлы в текущей папке (их имена — в сообщении). Прочитай их целиком, вместе с "
                 "картинками слайдов; опирайся только на них; не выдумывай фактов, которых в них нет. Страницы и слайды "
                 "называй по их номерам в файле.\n\n")
    elif source == "next":
        head += ("Материал урока пришлю следующим сообщением: страницы и слайды в нём помечены «=== Страница N ===» и "
                 "«=== Слайд N ===». Опирайся только на него; не выдумывай фактов, которых в нём нет.\n\n")
    else:
        head += ("Материал урока (методичка, презентация, план) приложен к сообщению — опирайся только на него; "
                 "не выдумывай фактов, которых в нём нет.\n\n")
    if stages:
        head += ("ЭТАПЫ — строго по плану учителя: эти, в этом порядке, с этими минутами; не добавляй, не убирай и не "
                 "переименовывай:\n" + "\n".join(_plan_lines(plan)) + "\nПод каждым этапом — плашки для этой темы.\n\n")
    if slides:
        n = len(slides)
        head += (f"СЛАЙДЫ: в презентации {n} слайдов. Для КАЖДОГО слайда с 1 по {n}, по порядку и без пропусков, — "
                 "строка «![Слайд N](slide:N)», а под ней плашки: что учитель говорит, спрашивает и делает на этом "
                 "слайде. Заметки докладчика (ниже) сохрани почти дословно — разметь их ролями и добавь только "
                 "недостающее. Слайды объединяй в этапы по смыслу (не этап на каждый слайд).\nСлайды:\n")
        for sl in slides:
            k, title, notes = (tuple(sl) + ("",))[:3]
            head += f"{k}. {title or '—'}" + (f"\n   Заметки: {notes.strip()}" if notes and notes.strip() else "") + "\n"
        head += "\n"
    head += _PICTURES + "\n"
    names = [x.strip() for x in exercises if x and x.strip()]
    if names:
        # 1.1: только пометка «зарядка» — какое видео, учитель выберет на уроке (или программа — случайное)
        head += ("ЗАРЯДКА: у учителя есть видео зарядок. Этап-зарядку пометь словом «зарядка», без названия видео: "
                 "«## Зарядка · 3 мин · зарядка» — видео учитель выберет на уроке; под этапом — [!say], как объявить "
                 "зарядку.")
    else:
        head += ("ЗАРЯДКА: видео зарядок у учителя нет — на этапе-зарядке распиши упражнения в [!say]: что делать и "
                 "сколько раз.")
    if not stages and minutes >= 60:
        head += " Добавь зарядку 3–5 минут отдельным этапом."
    head += "\n\n"
    detail = ("Пиши коротко: реплики «Говоришь» — 1–3 предложения, тезисы — по одной строке."
              if opt.detail == DETAIL_SHORT else
              "Можно подробнее: реплики «Говоришь» — до 5 предложений, тезисы — с пояснением «зачем».")
    tail = ("\nОБЯЗАТЕЛЬНО: цель — что ученики смогут (объяснят, решат, сравнят); после каждого нового понятия — "
            "[!ask] на понимание; в практике — [!task], [!hint] (если застрял) и [!extra]; в конце — рефлексия по цели "
            "([!ask]) и [!homework].\n" + detail + "\n"
            "\nПРАВИЛА: Начни ответ строкой ~~~markdown и закончи строкой ~~~ — тильдами, не ```: внутри бывают блоки "
            "кода (у такого блока в чате есть кнопка «Копировать»). Без пояснений до и после. Если урок не про "
            "программирование — блоков кода нет. Пустые плашки не добавляй.\n\n" + CHAT_EXAMPLE)
    return head + CHAT_FORMAT + tail


def lesson_prompt(opt: Options, *, material: str = "", plan: Template | None = None, exercises=(), slides=None) -> str:
    """Промпт урока целиком — для «Скопировать промпт». Нет материала — его прикладывают в чате."""
    body = lesson_instruction(opt, plan=plan, exercises=exercises, slides=slides,
                              source="below" if material.strip() else ("attached_or_topic" if (opt.topic or "").strip()
                                                                       and slides is None else "attached"))
    if material.strip():
        body += "\nМАТЕРИАЛ:\n<<<\n" + material.strip() + "\n>>>\n"
    return body


def chat_prompt(material: str, opt: Options, slides: list[tuple[int, str]] | None = None) -> str:
    """Промпт для своего чата (до 0.12 — без плана и зарядок): то же, что lesson_prompt."""
    return lesson_prompt(opt, material=material, slides=slides)


def slides_prompt(t: Template, minutes: int = 0, plan: Template | None = None, exercises=()) -> str:
    """«⋯ → Промпт для слайдов»: урок из презентации → промпт, по которому чат подготовит заметки к каждому слайду."""
    total = minutes or sum(b.minutes for b in t.blocks if b.type == BLOCK_STAGE) or 45
    slides: list[tuple[int, str, str]] = []
    for i, b in enumerate(t.blocks):                 # заметки под слайдом — до следующего слайда или этапа
        if b.type != BLOCK_IMAGE or not b.slide:
            continue
        notes = []
        for x in t.blocks[i + 1:]:
            if x.type in (BLOCK_IMAGE, BLOCK_STAGE):
                break
            if x.type == BLOCK_MARKDOWN and x.text.strip():
                notes.append(x.text.strip().replace("\n", " / "))
        slides.append((b.slide, b.title, " | ".join(notes)))
    return lesson_prompt(Options(style=STYLE_SCENARIO, minutes=total, break_min=0), plan=plan, exercises=exercises,
                         slides=slides)


_MD_OPEN = re.compile(r"^\s*(~{3,}|`{3,})\s*(markdown|md)\s*$", re.I)


def md_answer(text: str) -> str | None:
    """Урок в Markdown из ответа чата: внутри блока ~~~markdown / ```markdown (до последней такой же черты —
    внутри могут быть блоки кода) или весь текст, если это урок. None — это не урок в Markdown."""
    from . import lesson_md
    text = re.sub(r"\(\s*slide:\s*(\d+)\s*\)", r"(slide:\1)", text.replace("\r\n", "\n"))   # «slide: 2» — тоже слайд
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        m = _MD_OPEN.match(ln)
        if m:
            fence = m.group(1)
            ch, depth, close = fence[0], 0, len(lines)
            for j in range(i + 1, len(lines)):     # конец блока — та же черта не внутри вложенного кода
                s = lines[j].strip()
                if re.fullmatch(re.escape(ch) + "{%d,}" % len(fence), s):
                    if depth:
                        depth -= 1
                        continue
                    close = j
                    break
                if ch == "`" and re.match(r"^`{3,}\S", s):
                    depth += 1
            return "\n".join(lines[i + 1:close])
    src = text.strip()
    return src if lesson_md.looks_like_lesson(src) or src.startswith("---\ntitle:") else None


def _parse_md_answer(md: str, title: str, slide) -> Parsed:
    """Ответ своего чата — урок в Markdown: слайды «slide:N» — картинками из PDF материала (slide(N))."""
    from . import lesson_md
    t = lesson_md.parse(md, None, title or "Урок от нейросети", local_images=False)
    warnings: list[str] = []
    keep = []
    no_pic: list[int] = []
    for b in t.blocks:
        if b.type == BLOCK_IMAGE and not (b.text or "").strip():
            if b.slide:                   # место слайда: есть PDF материала — картинка страницы, нет — место остаётся
                path = slide(b.slide) if slide else None
                if path:
                    b.text = path
                else:
                    no_pic.append(b.slide)
            keep.append(b)                # «Нужна картинка: …» — место, учитель вставит сам
            continue
        if b.type == BLOCK_IMAGE and not re.match(r"https?://", (b.text or "").strip(), re.I):
            warnings.append("Картинка с путём к файлу пропущена — вставьте её сами.")
            continue
        keep.append(b)
    if no_pic:
        nums = ", ".join(str(n) for n in dict.fromkeys(no_pic))
        warnings.append(f"Слайд {nums}: картинки пока нет — подставьте слайды из презентации." if len(no_pic) == 1 else
                        f"Слайды {nums}: картинок пока нет — подставьте слайды из презентации.")
    t.blocks = keep
    if not t.blocks:
        raise LessonError("В ответе нет ни этапов, ни плашек — попросите нейросеть ответить по формату из промпта.")
    return Parsed(t, warnings)
