"""«Новый урок» по шагам — без страницы: свой план из списка этапов, разбор вставленного текста, задание для своего
чата и работа нейросети (урок по теме, по файлам материала или разбор кода).

Claude Code и Codex читают сами файлы материала (ai.ask(files=…): копии в папке запроса, только чтение); остальным
нейросетям уходит текст из файла (materials.extract). План выбран — этапы строго по нему, урок связывается с планом
(plans.link_topic). Слайды «![Слайд N](slide:N)» берутся картинками из PDF материала.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import lesson_ai as L
from .storage import BLOCK_CODE, BLOCK_IMAGE, BLOCK_MARKDOWN, BLOCK_STAGE, KIND_PLAN, Block, Template

STAGE_KINDS = ("", "break", "exercise")
CODE_STYLES = (L.STYLE_COMMENTS, L.STYLE_STEPS, L.STYLE_PARTS)
# файлы, которые Claude Code и Codex читают сами; .docx и .pptx — текстом (их агент открыть не может)
AGENT_READS = (".pdf", ".txt", ".md", ".py", ".ipynb", ".html", ".js", ".css", ".json", ".png", ".jpg", ".jpeg",
               ".java", ".kt", ".cs", ".cpp", ".sql")


def _plural(n: int, one: str, few: str, many: str) -> str:
    a, b = abs(n) % 100, abs(n) % 10
    return many if 11 <= a <= 14 else one if b == 1 else few if 2 <= b <= 4 else many


# ---------------------------------------------------------------- свой план
def plan_from_spec(title: str, stages: list[dict]) -> Template:
    """«Новый план»: [{title, minutes, kind, exercise}] → Template(kind=plan). Минуты 0…600, вид — обычный /
    перерыв / зарядка (другое — обычный), у зарядки — название видео. Без этапов — ValueError."""
    blocks = []
    for s in stages or []:
        try:
            minutes = max(0, min(600, int(s.get("minutes") or 0)))
        except (TypeError, ValueError):
            minutes = 0
        kind = str(s.get("kind") or "")
        kind = kind if kind in STAGE_KINDS else ""
        blocks.append(Block(BLOCK_STAGE, "", title=str(s.get("title") or "").strip() or "Этап", minutes=minutes,
                            stage_kind=kind, exercise=str(s.get("exercise") or "").strip() if kind == "exercise" else ""))
    if not blocks:
        raise ValueError("В плане нет этапов — добавьте хотя бы один")
    return Template(title=(title or "").strip() or "Новый план", blocks=blocks, kind=KIND_PLAN)


# ---------------------------------------------------------------- что получится
def summary(t: Template, plan: Template | None = None) -> str:
    """Итог разбора одной строкой: этапы (по плану), заметки, код, слайды, фото, «нужно вставить»."""
    st = sum(1 for b in t.blocks if b.type == BLOCK_STAGE)
    nn = sum(1 for b in t.blocks if b.type == BLOCK_MARKDOWN)
    cc = sum(1 for b in t.blocks if b.type == BLOCK_CODE)
    imgs = [b for b in t.blocks if b.type == BLOCK_IMAGE]
    slides = [b for b in imgs if b.slide]
    web = [b for b in imgs if "://" in (b.text or "")]
    need = [b for b in imgs if not b.text and not b.slide]
    head = f"«{t.title}» — {st} {_plural(st, 'этап', 'этапа', 'этапов')}"
    head += f" по плану «{plan.title}»" if plan is not None else ""
    head += f", {nn} {_plural(nn, 'заметка', 'заметки', 'заметок')}"
    head += f", {cc} {_plural(cc, 'блок', 'блока', 'блоков')} кода." if cc else ", без кода."
    parts = [head]
    if slides:
        empty = sum(1 for b in slides if not b.text)
        parts.append(f"Слайды: {len(slides)}" + (" — подставьте из презентации." if empty else " — из материала."))
    if web:
        parts.append(f"Фото по ссылкам: {len(web)} — скачаются при создании.")
    if need:
        parts.append(f"Нужно вставить: {len(need)}.")
    return " ".join(parts)


def steps_style(t: Template) -> str:
    """Код разложен по шагам — печать «По шагам»."""
    return L.STYLE_STEPS if any(len(set(b.steps)) > 1 for b in t.code_blocks()) else ""


@dataclass
class PasteResult:
    template: Template
    kind: str
    summary: str
    notes: list[str] = field(default_factory=list)
    style: str = ""


def _looks_like_answer(text: str) -> bool:
    return any(L._MD_OPEN.match(x) for x in text.split("\n")) or text.lstrip().startswith("---\ntitle:")


def paste_parse(text: str, lang: str = "", plan: Template | None = None,
                slide: Callable[[int], str | None] | None = None) -> PasteResult:
    """«Вставить текст»: ответ нейросети (~~~markdown или JSON), Markdown с кодом, тетрадка Jupyter, просто код
    (lang — язык или "" — определить). План выбран — урок по нему. ValueError — разобрать нечего."""
    from . import plans
    from .importers import parse_pasted
    src = (text or "").replace("\r\n", "\n")
    if not src.strip():
        raise ValueError("Вставьте текст: ответ нейросети, Markdown, тетрадку Jupyter или код.")
    notes: list[str] = []
    if _looks_like_answer(src) or L.is_lesson_json(src):
        try:
            p = L.parse_lesson(src, style=L.STYLE_SCENARIO, slide=slide)
        except L.LessonError as e:
            raise ValueError(str(e)) from None
        t, kind = p.template, "ответ нейросети"
        notes += list(p.warnings)
        line = summary(t, plan if plan is not None and t.kind != KIND_PLAN else None)
        if L.is_lesson_json(src) and t.code_blocks():
            line = f"«{t.title}» — {p.summary}"
    else:
        try:
            t, kind = parse_pasted(src, lang)
        except L.LessonError as e:
            raise ValueError(str(e)) from None
        codes = t.code_blocks()
        line = f"Распознано: {kind} · блоков: {len(t.blocks)}, из них кода: {len(codes)}"
    t.kind = ""
    if plan is not None and any(b.type == BLOCK_STAGE for b in t.blocks):
        notes = plans.link_topic(t, plan) + notes
    return PasteResult(t, kind, line, notes, steps_style(t))


# ---------------------------------------------------------------- задание
def code_options(d, material: str = "") -> L.Options:
    """Разбор кода: {style, task, explain, keep, detail} (или Settings) → Options; большой код — разметкой строк."""
    get = (lambda k, dflt: d.get(k, dflt)) if isinstance(d, dict) else (lambda k, dflt: getattr(d, {
        "style": "lesson_style", "task": "lesson_task", "explain": "lesson_explain", "keep": "lesson_keep_code",
        "detail": "lesson_detail"}[k], dflt))
    style = get("style", L.STYLE_STEPS)
    style = style if style in CODE_STYLES else L.STYLE_STEPS
    detail = get("detail", L.DETAIL_SHORT)
    return L.Options(style=style, task=bool(get("task", True)), explain=bool(get("explain", True)),
                     keep_code=bool(get("keep", True)), detail=detail if detail in (L.DETAIL_SHORT, L.DETAIL_FULL)
                     else L.DETAIL_SHORT, marks=L.is_big(material))


def copy_prompt(what: str, opt: L.Options, *, material: str = "", plan: Template | None = None, exercises=()) -> str:
    """«Скопировать задание» для своего чата: урок (план, тема, класс, видео зарядок — внутри) или разбор кода."""
    if what == "code":
        return L.build_prompt(material, opt)
    return L.lesson_prompt(opt, material=material, plan=plan, exercises=exercises)


@dataclass
class Material:
    text: str = ""                 # текст для нейросети (и для разбора большого кода)
    files: list[str] = field(default_factory=list)       # файлы, которые Claude Code и Codex прочитают сами
    pdf: str = ""                  # PDF материала — картинки слайдов
    notes: list[str] = field(default_factory=list)


def gather(paths, text: str = "", agent: bool = False, extract=None) -> Material:
    """Материал из файлов и поля. agent — Claude Code / Codex: читаемые им файлы уходят как есть, остальные — текстом.
    Не прочитался файл — замечание, остальное идёт дальше."""
    from . import materials
    extract = extract or materials.extract
    m = Material(text=(text or "").strip())
    chunks = [m.text] if m.text else []
    for p in paths or []:
        path = Path(p)
        ext = path.suffix.lower()
        if agent and ext in AGENT_READS:
            m.files.append(str(path))
            if ext == ".pdf" and not m.pdf:
                m.pdf = str(path)
            continue
        try:
            x = extract(str(path))
        except (OSError, ValueError, KeyError) as e:
            m.notes.append(f"Не прочитать {path.name}: {e}")
            continue
        if x.pdf and not m.pdf:
            m.pdf = x.pdf
        chunks.append(f"=== Файл {path.name} ===\n{x.text}" if len(paths) > 1 else x.text)
    m.text = "\n\n".join(c for c in chunks if c.strip())
    return m


def slide_maker(pdf: str) -> Callable[[int], str | None] | None:
    """Картинка слайда N из PDF материала → ссылка на копию в данных программы (кэшируется)."""
    if not pdf:
        return None
    cache: dict[int, str | None] = {}

    def slide(n: int) -> str | None:
        if n not in cache:
            from . import materials
            from .storage import DATA_DIR, MEDIA_FOLDER, media_ref
            out = materials.render_page(pdf, n, DATA_DIR / MEDIA_FOLDER)
            cache[n] = media_ref(out) if out else None
        return cache[n]
    return slide


def lesson_task(settings, opt: L.Options, *, plan: Template | None = None, exercises=(), material: str = "",
                files=(), pdf: str = "", what: str = "lesson") -> Callable:
    """Работа для Jobs.start: нейросеть составляет урок (what="lesson") или разбирает код (what="code").
    → {"template", "notes", "style", "who"}. План — урок связан с ним; тема учителя — название урока."""
    from . import ai, plans

    def run(job) -> dict:
        if what == "code":
            system, user = L.instruction(opt), L.material_for(material, opt)
            send_files: tuple = ()
        else:
            send_files = tuple(files)
            source = "files" if send_files else ("next" if material.strip() else "topic")
            system = L.lesson_instruction(opt, plan=plan, exercises=exercises, source=source)
            if material.strip():
                user = L.material_for(material, opt)
            else:
                user = "Составь урок" + (f" на тему «{opt.topic.strip()}»." if (opt.topic or "").strip() else ".")
        text, who = ai.ask(settings, system, user, job.cancel_event, on_status=job.status, on_progress=job.progress,
                           files=send_files)
        if job.cancelled:
            raise ai.Cancelled("Отменено.")
        try:
            parsed = L.parse_lesson(text, material=material, style=opt.style, slide=slide_maker(pdf))
        except L.LessonError as e:
            raise ai.AIError(f"Ответ нейросети не разобрать: {e}") from None
        t = copy.deepcopy(parsed.template)
        t.kind = ""
        notes = list(parsed.warnings)
        if what == "code" and opt.keep_code:
            diff = L.code_changes(material, parsed)
            if diff:
                notes.insert(0, "Внимание: нейросеть изменила код: " + "; ".join(diff[:5]))
        if what != "code":
            if (opt.topic or "").strip():
                t.title = opt.topic.strip()
            if plan is not None:
                notes = plans.link_topic(t, plan) + notes
        return {"template": t, "notes": notes, "style": opt.style if what == "code" else "", "who": who}
    return run
