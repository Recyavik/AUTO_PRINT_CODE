"""Удаление комментариев из кода перед печатью.

Комментарий целиком на строке — строка убирается вместе с переводом строки;
комментарий в конце строки кода — убирается вместе с пробелами перед ним.
Если из-за удаления рядом оказались две пустые строки, лишняя тоже убирается.
Строковые литералы (в том числе тройные кавычки и docstring) не трогаются.
Shebang «#!» и строка кодировки в начале файла сохраняются.
"""
from __future__ import annotations

import re

_HASH = ("#",)
_SLASH = ("//",)
_C_BLOCK = (("/*", "*/"),)

# язык → (маркеры строчных комментариев, пары блочных комментариев, кавычки)
_LANGS: dict[str, tuple[tuple, tuple, tuple]] = {}
for _names, _spec in (
    ("python py python3 ipython", (_HASH, (), ('"""', "'''", '"', "'"))),
    ("bash sh shell zsh powershell ps1 yaml yml toml r ruby rb perl makefile dockerfile",
     (_HASH, (), ('"', "'"))),
    ("javascript js jsx typescript ts tsx java kotlin kt scala dart go rust rs swift c cpp c++ cs csharp "
     "objective-c json5", (_SLASH, _C_BLOCK, ('"', "'", "`"))),
    ("php", (_SLASH + _HASH, _C_BLOCK, ('"', "'"))),
    ("css scss less", ((), _C_BLOCK, ('"', "'"))),
    ("sql lua haskell hs", (("--",), (("/*", "*/"),), ('"', "'"))),
    ("html xml svg vue", ((), (("<!--", "-->"),), ())),
):
    for _n in _names.split():
        _LANGS[_n] = _spec

_KEEP_HEAD = re.compile(r"^#!|^#.*coding[:=]")


def supported(lang: str) -> bool:
    return (lang or "").lower() in _LANGS


def lang_spec(lang: str) -> tuple[tuple, tuple, tuple] | None:
    """→ (маркеры строчных комментариев, пары блочных, кавычки) или None для неизвестного языка."""
    return _LANGS.get((lang or "").lower())


def _comment_spans(text: str, line_marks: tuple, blocks: tuple, quotes: tuple) -> list[tuple[int, int]]:
    spans = []
    i, n = 0, len(text)
    while i < n:
        q = next((q for q in quotes if text.startswith(q, i)), None)
        if q:
            j = i + len(q)
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text.startswith(q, j):
                    j += len(q)
                    break
                if len(q) == 1 and text[j] == "\n":   # незакрытая строка — до конца строки
                    break
                j += 1
            i = j
            continue
        b = next((b for b in blocks if text.startswith(b[0], i)), None)
        if b:
            end = text.find(b[1], i + len(b[0]))
            end = n if end < 0 else end + len(b[1])
            spans.append((i, end))
            i = end
            continue
        if any(text.startswith(m, i) for m in line_marks):
            end = text.find("\n", i)
            end = n if end < 0 else end
            spans.append((i, end))
            i = end
            continue
        i += 1
    return spans


def strip_comments(text: str, lang: str) -> tuple[str, list[int]]:
    """→ (текст без комментариев, карта: индекс символа результата → индекс в исходном тексте)."""
    spec = _LANGS.get((lang or "").lower())
    spans = _comment_spans(text, *spec) if spec else []
    if not spans:
        return text, list(range(len(text)))
    in_comment = bytearray(len(text))
    for a, b in spans:
        in_comment[a:b] = b"\x01" * (b - a)

    # строки результата: (индексы оставленных символов, индекс исходного «\n» перед строкой, пустая ли)
    lines: list[tuple[list[int], int, bool]] = []
    dropped = False                       # после последней оставленной строки была удалена строка
    trailing_dropped = False
    start = 0
    for li, line in enumerate(text.split("\n")):
        end = start + len(line)
        idx = [k for k in range(start, end) if not in_comment[k]]
        had_comment = len(idx) < len(line)
        if had_comment and li < 2 and _KEEP_HEAD.match(line):
            idx, had_comment = list(range(start, end)), False
        blank = not "".join(text[k] for k in idx).strip()
        if had_comment and blank:
            dropped = trailing_dropped = True          # строка была только комментарием
        elif blank and dropped and (not lines or lines[-1][2]):
            pass                                       # лишняя пустая строка рядом с удалённым комментарием
        else:
            if had_comment:
                while idx and text[idx[-1]] in " \t":
                    idx.pop()
            lines.append((idx, start - 1, blank))
            dropped = False
            if not blank:
                trailing_dropped = False
        start = end + 1
    if trailing_dropped:                               # пустые строки перед удалённым хвостом
        while lines and lines[-1][2]:
            lines.pop()

    out: list[str] = []
    omap: list[int] = []
    for n, (idx, nl_at, _blank) in enumerate(lines):
        if n:
            out.append("\n")
            omap.append(nl_at)
        out.extend(text[k] for k in idx)
        omap.extend(idx)
    return "".join(out), omap
