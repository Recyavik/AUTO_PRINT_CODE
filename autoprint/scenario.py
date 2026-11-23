"""Суфлёр урока: урок по этапам — план с минутами, блоки этапов, HTML для страницы суфлёра.

Урок — обычное занятие AutoPrintCode (ленту блоков), в котором есть блоки-«Этапы». Блоки после этапа
принадлежат ему до следующего этапа; блоки до первого этапа — «перед уроком». Урок без этапов — прежнее
занятие: страница показывает его блоки без времени.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

from .storage import BLOCK_STAGE, Block, Template


@dataclass
class Stage:
    index: int
    block: Block                      # сам блок-этап: название, минуты, вид, раздел, пометка
    start_min: int                    # с какой минуты урока
    end_min: int                      # по какую
    blocks: list[Block] = field(default_factory=list)


def stages(t: Template) -> tuple[list[Block], list[Stage]]:
    """→ (блоки до первого этапа, этапы с их блоками и минутами от начала урока)."""
    intro: list[Block] = []
    out: list[Stage] = []
    at = 0
    for b in t.blocks:
        if b.type == BLOCK_STAGE:
            m = max(0, int(b.minutes or 0))
            out.append(Stage(len(out), b, at, at + m))
            at += m
        elif out:
            out[-1].blocks.append(b)
        else:
            intro.append(b)
    return intro, out


def has_stages(t: Template) -> bool:
    return any(b.type == BLOCK_STAGE for b in t.blocks)


def total_minutes(t: Template) -> int:
    return sum(max(0, int(b.minutes or 0)) for b in t.blocks if b.type == BLOCK_STAGE)


def webinar_for(t: Template, preset=None):
    """Эфир урока: расписание — этапы урока (этапы на 0 минут — мгновенные, в таймер не идут), оформление
    экрана (фон, зарядки, перерыв, шрифт) — из шаблона «Эфира» preset. Пресет не меняется."""
    from .efir.model import (DEMO_NONE, KIND_BREAK, KIND_EXERCISE, KIND_NORMAL, Activity, Webinar,
                             webinar_from_dict)
    kinds = {"break": KIND_BREAK, "exercise": KIND_EXERCISE}
    schedule = [Activity(name=s.block.title or "Этап", min=s.end_min - s.start_min,
                         kind=kinds.get(s.block.stage_kind, KIND_NORMAL), demo=DEMO_NONE)
                for s in stages(t)[1] if s.end_min > s.start_min]
    if preset is not None:
        d = preset.to_dict()
        d["schedule"] = [{"name": "x", "min": 1}]        # заменим ниже; разбор требует непустое расписание
        w = webinar_from_dict(d)
    else:
        w = Webinar()
    w.schedule = schedule
    w.id, w.lesson_id, w.title = "lesson-" + t.id, t.id, t.title
    w.start = t.start or w.start
    brk = next((a.min for a in schedule if a.kind == KIND_BREAK), 0)
    if brk:
        w.break_min = brk
    return w


# ---------------------------------------------------------------- Markdown → HTML (для страницы суфлёра)
# Свой маленький разбор: заголовки, абзацы, списки, **жирный**, *курсив*, `код`, ```-блоки, ссылки. Сначала
# всё экранируется — на страницу не попадёт ни тег, ни скрипт; ссылки — только http(s).

_INLINE = re.compile(r"(`[^`\n]+`)|\[([^\]\n]+)\]\(([^)\s]+)\)|(https?://[^\s<>\"'`]+)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")     # без __…__: в тексте про Python это __init__, а не жирный
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])")
_UL = re.compile(r"^\s*[-*•]\s+(.*)$")
_OL = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_HEAD = re.compile(r"^(#{1,6})\s+(.*)$")
_FENCE = re.compile(r"^\s*```")


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def _emph(escaped: str) -> str:
    s = _BOLD.sub(r"<b>\1</b>", escaped)
    return _ITALIC.sub(r"<i>\1</i>", s)


def _link(url: str, inner: str) -> str:
    return f'<a href="{_esc(url)}" target="_blank" rel="noopener">{inner}</a>'


def _inline(text: str) -> str:
    out, pos = [], 0
    for m in _INLINE.finditer(text):
        out.append(_emph(_esc(text[pos:m.start()])))
        code, label, url, bare = m.groups()
        if code:
            out.append(f"<code>{_esc(code[1:-1])}</code>")
        elif label is not None:
            inner = _emph(_esc(label))
            out.append(_link(url, inner) if re.match(r"https?://", url, re.I) else inner)
        else:
            tail = ""
            while bare and bare[-1] in ".,;:!?)»":
                if bare[-1] == ")" and bare.count("(") >= bare.count(")"):
                    break
                tail = bare[-1] + tail
                bare = bare[:-1]
            out.append(_link(bare, _esc(bare)) + _esc(tail))
        pos = m.end()
    out.append(_emph(_esc(text[pos:])))
    return "".join(out)


def md_html(text: str) -> str:
    """Markdown блока → безопасный HTML для страницы суфлёра."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    para: list[str] = []
    items: list[str] = []
    kind = ""                                          # "ul" | "ol" — открытый список

    def flush_para() -> None:
        if para:
            out.append("<p>" + "<br>".join(_inline(x) for x in para) + "</p>")
            para.clear()

    def flush_list() -> None:
        nonlocal kind
        if items:
            out.append(f"<{kind}>" + "".join(f"<li>{_inline(x)}</li>" for x in items) + f"</{kind}>")
            items.clear()
        kind = ""

    i = 0
    while i < len(lines):
        ln = lines[i]
        if _FENCE.match(ln):
            flush_para()
            flush_list()
            body = []
            i += 1
            while i < len(lines) and not _FENCE.match(lines[i]):
                body.append(lines[i])
                i += 1
            out.append("<pre>" + _esc("\n".join(body)) + "</pre>")
            i += 1
            continue
        if not ln.strip():
            flush_para()
            flush_list()
        elif _HEAD.match(ln):
            flush_para()
            flush_list()
            level, body = _HEAD.match(ln).groups()
            h = min(6, len(level) + 1)
            out.append(f"<h{h}>{_inline(body.strip())}</h{h}>")
        elif _UL.match(ln) or _OL.match(ln):
            flush_para()
            k = "ul" if _UL.match(ln) else "ol"
            if kind and kind != k:
                flush_list()
            kind = k
            items.append((_UL.match(ln) or _OL.match(ln)).group(1).strip())
        elif items and ln[:1] in " \t":
            items[-1] += " " + ln.strip()           # продолжение пункта списка
        else:
            flush_list()
            para.append(ln.strip())
        i += 1
    flush_para()
    flush_list()
    return "".join(out)


_ANSWER = re.compile(r"^\s*(→|->)\s*")


def ask_parts(text: str) -> tuple[str, list[str]]:
    """Блок «Спроси»: (вопрос, ожидаемые ответы — строки «→ …»)."""
    question, answers = [], []
    for ln in (text or "").split("\n"):
        if _ANSWER.match(ln):
            answers.append(_ANSWER.sub("", ln).strip())
        else:
            question.append(ln)
    return "\n".join(question).strip(), [a for a in answers if a]


# ---------------------------------------------------------------- код → HTML

_TOKEN_CLASSES = None


def _token_classes():
    global _TOKEN_CLASSES
    if _TOKEN_CLASSES is None:
        from pygments.token import Comment, Keyword, Name, Number, Operator, String
        _TOKEN_CLASSES = [(Comment, "t-c"), (Keyword, "t-k"), (Name.Builtin, "t-b"), (Name.Function, "t-f"),
                          (Name.Class, "t-cl"), (Name.Decorator, "t-d"), (Name.Tag, "t-t"),
                          (Name.Attribute, "t-a"), (String, "t-s"), (Number, "t-n"), (Operator, "t-o")]
    return _TOKEN_CLASSES


def _class_for(ttype) -> str:
    from pygments.token import Token
    while ttype is not Token:
        for tt, cls in _token_classes():
            if ttype is tt:
                return cls
        ttype = ttype.parent
    return ""


def code_html(code: str, lang: str) -> str:
    """Код с подсветкой (Pygments, как в редакторе программы) → HTML со span-классами t-*."""
    try:
        from pygments import lex
        from pygments.lexers import get_lexer_by_name
        lexer = get_lexer_by_name((lang or "text").lower(), stripnl=False, ensurenl=False)
    except Exception:
        return _esc(code)
    out = []
    for ttype, value in lex(code, lexer):
        cls = _class_for(ttype)
        out.append(f'<span class="{cls}">{_esc(value)}</span>' if cls and value.strip() else _esc(value))
    return "".join(out)


# язык блока кода → (подпись, файл значка в efir/page/lang; "" — значка нет, подпись текстом)
_LANGS = {
    "python": ("Python", "python.svg"), "py": ("Python", "python.svg"),
    "javascript": ("JavaScript", "javascript.svg"), "js": ("JavaScript", "javascript.svg"),
    "typescript": ("TypeScript", "typescript.svg"), "ts": ("TypeScript", "typescript.svg"),
    "html": ("HTML", "html.svg"), "html5": ("HTML", "html.svg"), "css": ("CSS", "css.svg"),
    "java": ("Java", "java.svg"), "kotlin": ("Kotlin", "kotlin.svg"), "kt": ("Kotlin", "kotlin.svg"),
    "csharp": ("C#", "csharp.svg"), "cs": ("C#", "csharp.svg"), "c#": ("C#", "csharp.svg"),
    "cpp": ("C++", "cpp.svg"), "c++": ("C++", "cpp.svg"), "c": ("C", "c.svg"), "go": ("Go", "go.svg"),
    "rust": ("Rust", "rust.svg"), "php": ("PHP", "php.svg"),
    "bash": ("Bash", "bash.svg"), "sh": ("Bash", "bash.svg"), "shell": ("Bash", "bash.svg"),
    "powershell": ("PowerShell", "powershell.svg"), "ps1": ("PowerShell", "powershell.svg"),
    "json": ("JSON", "json.svg"), "yaml": ("YAML", "yaml.svg"), "yml": ("YAML", "yaml.svg"),
    "markdown": ("Markdown", "markdown.svg"), "md": ("Markdown", "markdown.svg"),
    "swift": ("Swift", "swift.svg"), "dart": ("Dart", "dart.svg"), "ruby": ("Ruby", "ruby.svg"),
    "rb": ("Ruby", "ruby.svg"), "lua": ("Lua", "lua.svg"), "sql": ("SQL", ""), "text": ("Текст", ""),
}


def lang_info(lang: str) -> tuple[str, str]:
    key = (lang or "").strip().lower()
    return _LANGS.get(key, (lang or "", ""))
