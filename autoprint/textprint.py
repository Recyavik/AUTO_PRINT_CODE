"""Печать текстовых (Markdown) блоков: условие задачи, пояснение, подсказка.

Три вида:
  * markdown — исходник как есть (markdown-ячейка Jupyter, .md-файл);
  * plain    — без разметки: «## Заголовок», **жирный**, `код`, [ссылка](url) → просто текст
               (Блокнот, Word, чат);
  * comment  — простой текст, каждая строка закомментирована по языку ближайшего блока кода
               (условие в начале файла с решением).
"""
from __future__ import annotations

import re

from .comments import lang_spec

PRINT_MARKDOWN, PRINT_PLAIN, PRINT_COMMENT = "markdown", "plain", "comment"
PRINT_MODES = {
    PRINT_MARKDOWN: "как Markdown",
    PRINT_PLAIN: "простым текстом",
    PRINT_COMMENT: "комментарием в коде",
}

_FENCE = re.compile(r"^\s{0,3}(```|~~~)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}(?:\s+|$)(.*?)(?:\s+#+)?\s*$")
_SETEXT = re.compile(r"^\s{0,3}(=+|-+)\s*$")
_QUOTE = re.compile(r"^\s{0,3}>\s?")
_RULE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_BULLET = re.compile(r"^(\s*)[*+](\s+)")
_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!>~|])")
_CODE = re.compile(r"(`+)(.+?)\1")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_ITALIC = re.compile(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])|(?<!\w)_(?=\S)(.+?)(?<=\S)_(?!\w)")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_HARD_BREAK = re.compile(r"(\\| {2,})$")
_PRIVATE = 0xE000   # экранированные символы на время разбора прячутся в область частного использования


def _emphasis(s: str) -> str:
    s = _IMAGE.sub(r"\1", s)
    s = _LINK.sub(r"\1", s)
    s = _STRIKE.sub(r"\1", s)
    s = _BOLD.sub(r"\2", s)
    return _ITALIC.sub(lambda m: m.group(1) or m.group(2), s)


def _inline(s: str) -> str:
    s = _ESCAPE.sub(lambda m: chr(_PRIVATE + ord(m.group(1))), s)
    out, last = [], 0
    for m in _CODE.finditer(s):
        out.append(_emphasis(s[last:m.start()]))
        code = m.group(2)
        if len(code) > 2 and code[0] == code[-1] == " ":
            code = code[1:-1]
        out.append(code)
        last = m.end()
    out.append(_emphasis(s[last:]))
    return "".join(chr(ord(c) - _PRIVATE) if _PRIVATE <= ord(c) < _PRIVATE + 128 else c for c in "".join(out))


def markdown_to_plain(text: str) -> str:
    lines: list[str] = []
    fence = ""
    para = False                            # предыдущая строка — текст абзаца (не код, не пустая)
    for line in text.split("\n"):
        m = _FENCE.match(line)
        if fence:
            if m and m.group(1) == fence:
                fence = ""
            else:
                lines.append(line)          # код внутри ``` — как есть
            continue
        if m:
            fence, para = m.group(1), False
            continue
        if para and _SETEXT.match(line):
            para = False
            continue                        # подчёркивание заголовка «===» / «---»
        para = bool(line.strip())
        if _RULE.match(line):
            lines.append("")
            para = False
            continue
        line = _QUOTE.sub("", line)
        h = _HEADING.match(line)
        if h:
            line = h.group(1)
        line = _BULLET.sub(r"\1-\2", line)
        line = _HARD_BREAK.sub("", line)
        lines.append(_inline(line).rstrip())
    out: list[str] = []
    for line in lines:                      # не больше одной пустой строки подряд
        if line or (out and out[-1]):
            out.append(line)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


def as_comment(text: str, lang: str) -> str:
    """Простой текст, закомментированный для языка lang (неизвестный язык → «#»)."""
    lines = markdown_to_plain(text).split("\n")
    marks, blocks, _quotes = lang_spec(lang) or (("#",), (), ())
    if marks:
        m = marks[0]
        return "\n".join(f"{m} {line}" if line else m for line in lines)
    if blocks:
        a, b = blocks[0]
        return "\n".join([a, *lines, b])
    return "\n".join(f"# {line}" if line else "#" for line in lines)


def printable(text: str, mode: str, lang: str = "python") -> str:
    """Что печатать для текстового блока в выбранном виде."""
    if mode == PRINT_PLAIN:
        return markdown_to_plain(text)
    if mode == PRINT_COMMENT:
        return as_comment(text, lang)
    return text.strip("\n")


def _fence_at(text: str, pos: int) -> str:
    """Открывающая строка ```-блока, внутри которого стоит позиция pos ('' — не внутри)."""
    fence, opener = "", ""
    for line in text[:pos].split("\n")[:-1]:
        m = _FENCE.match(line)
        if fence:
            if m and m.group(1) == fence:
                fence = opener = ""
        elif m:
            fence, opener = m.group(1), line
    return opener


def selection_text(source: str, part: str, base: int, mode: str, lang: str = "python") -> str:
    """Печатаемый текст выделенного куска part (начинается в source с позиции base).
    Кусок из середины ```-блока остаётся кодом и в простом тексте."""
    if mode != PRINT_MARKDOWN:
        opener = _fence_at(source, base)
        if opener:
            return printable(opener + "\n" + part + "\n" + opener.strip()[:3], mode, lang)
    return printable(part, mode, lang)


# ---------------------------------------------------------------- выделение в отрисованном тексте

_LIST_MARK = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?")
_VIEW_BULLET = re.compile(r"^\s*[•◦▪▫·‣○●■□]\s*")   # маркеры, которые просмотр может добавить к выделению


def _rendered_lines(source: str) -> list[str]:
    """Каждая строка исходника — так, как её видно в отрисованном Markdown (без ##, **, маркеров списка)."""
    out = []
    fence = ""
    para = False
    for line in source.split("\n"):
        m = _FENCE.match(line)
        if fence:
            if m and m.group(1) == fence:
                fence = ""
                out.append("")
            else:
                out.append(line)
            continue
        if m:
            fence, para = m.group(1), False
            out.append("")
            continue
        if (para and _SETEXT.match(line)) or _RULE.match(line):
            para = False
            out.append("")
            continue
        para = bool(line.strip())
        line = _QUOTE.sub("", line)
        h = _HEADING.match(line)
        if h:
            line = h.group(1)
        line = _LIST_MARK.sub("", line)
        out.append(_inline(_HARD_BREAK.sub("", line)))
    return out


def _squash(text: str) -> tuple[str, list[int]]:
    """Схлопывает пробельные символы в один пробел → (строка, индекс исходного символа для каждого)."""
    out, idx = [], []
    for i, ch in enumerate(text):
        if ch.isspace():
            if out and out[-1] != " ":
                out.append(" ")
                idx.append(i)
        else:
            out.append(ch)
            idx.append(i)
    return "".join(out), idx


def find_selection(source: str, selected: str, hint: float = 0.0) -> list[int]:
    """Выделение в отрисованном тексте → [начало, конец] целых строк исходника; [] — не нашлось.

    selected — выделенный текст, как его отдаёт просмотр; hint — где примерно началось выделение
    (0…1 от длины отрисованного текста): если такой же кусок встречается несколько раз."""
    lines = _rendered_lines(source)
    flat, line_of = "", []
    for j, line in enumerate(lines):
        flat += line + "\n"
        line_of += [j] * (len(line) + 1)
    hay, hay_idx = _squash(flat)
    selected = "\n".join(_VIEW_BULLET.sub("", x) for x in selected.splitlines())
    need = _squash(selected)[0].strip()
    if not need:
        return []

    def occurrences(s: str, start: int = 0) -> list[int]:
        found, i = [], hay.find(s, start)
        while i >= 0:
            found.append(i)
            i = hay.find(s, i + 1)
        return found

    def nearest(found: list[int]) -> int:
        return min(found, key=lambda i: abs(i / max(1, len(hay)) - hint))

    found = occurrences(need)
    if found:
        a = nearest(found)
        b = a + len(need) - 1
    else:
        # просмотр мог добавить или убрать символы (маркеры списков, таблицы) — ищем первую и последнюю строку
        parts = [p for p in (_squash(x)[0].strip() for x in selected.splitlines()) if p]
        first = occurrences(parts[0])
        if not first:
            return []
        a = nearest(first)
        last = occurrences(parts[-1], a)
        b = (last[0] + len(parts[-1]) - 1) if last else a + len(parts[0]) - 1
    ja, jb = line_of[hay_idx[a]], line_of[hay_idx[b]]
    starts = [0]
    for line in source.split("\n"):
        starts.append(starts[-1] + len(line) + 1)
    return [starts[ja], starts[jb + 1] - 1]
