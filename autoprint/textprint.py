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
