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

# Особые правила разбора:
#   ws    — «#» начинает комментарий только в начале строки или после пробела (bash: ${#arr[@]}, ${p##*/})
#   regex — «/…/» после оператора или «(» — регулярное выражение, а не начало комментария (JS: /https?:\/\//)
#   attr  — «#[» — атрибут PHP 8, а не комментарий
_JS_FLAGS = frozenset({"regex"})

# язык → (маркеры строчных комментариев, пары блочных комментариев, кавычки, особые правила)
_LANGS: dict[str, tuple[tuple, tuple, tuple, frozenset]] = {}
for _names, _spec in (
    ("python py python3 ipython", (_HASH, (), ('"""', "'''", '"', "'"), frozenset())),
    ("bash sh shell zsh yaml yml toml r ruby rb perl makefile dockerfile",
     (_HASH, (), ('"', "'"), frozenset({"ws"}))),
    ("powershell ps1", (_HASH, (("<#", "#>"),), ('"', "'"), frozenset({"ws"}))),
    ("javascript js jsx typescript ts tsx", (_SLASH, _C_BLOCK, ('"', "'", "`"), _JS_FLAGS)),
    ("java kotlin kt scala dart go rust rs swift c cpp c++ cs csharp objective-c json5",
     (_SLASH, _C_BLOCK, ('"', "'", "`"), frozenset())),
    ("php", (_SLASH + _HASH, _C_BLOCK, ('"', "'"), frozenset({"attr"}))),
    ("css scss less", ((), _C_BLOCK, ('"', "'"), frozenset())),
    ("sql", (("--",), _C_BLOCK, ('"', "'"), frozenset())),
    ("lua", (("--",), (("--[[", "]]"),), ('"', "'"), frozenset())),
    ("haskell hs", (("--",), (("{-", "-}"),), ('"',), frozenset())),
    ("html xml svg vue", ((), (("<!--", "-->"),), (), frozenset())),
):
    for _n in _names.split():
        _LANGS[_n] = _spec

_KEEP_HEAD = re.compile(r"^#!|^#.*coding[:=]")
_REGEX_BEFORE = set("(,=:[!&|?{};+-*%<>~^")   # после этих символов «/» открывает регулярное выражение


def lang_spec(lang: str) -> tuple[tuple, tuple, tuple, frozenset] | None:
    """→ (маркеры строчных комментариев, пары блочных, кавычки, особые правила) или None."""
    return _LANGS.get((lang or "").lower())


def _regex_end(text: str, i: int) -> int:
    """Если в позиции i («/») начинается регулярное выражение JS — позиция после него, иначе -1."""
    j = i - 1
    while j >= 0 and text[j] in " \t":
        j -= 1
    if j >= 0 and text[j] not in _REGEX_BEFORE and text[j] != "\n" and not text[:j + 1].endswith("return"):
        return -1                       # после значения «/» — это деление
    k, in_class = i + 1, False
    while k < len(text) and text[k] != "\n":
        c = text[k]
        if c == "\\":
            k += 2
            continue
        if c == "[":
            in_class = True
        elif c == "]":
            in_class = False
        elif c == "/" and not in_class:
            return k + 1
        k += 1
    return -1


def _comment_spans(text: str, line_marks: tuple, blocks: tuple, quotes: tuple,
                   flags: frozenset = frozenset()) -> list[tuple[int, int]]:
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
        if "regex" in flags and text[i] == "/" and not text.startswith(("//", "/*"), i):
            end = _regex_end(text, i)
            if end > 0:
                i = end
                continue
        m = next((m for m in line_marks if text.startswith(m, i)), None)
        if m and not ("ws" in flags and m == "#" and i > 0 and not text[i - 1].isspace()) \
                and not ("attr" in flags and text.startswith("#[", i)):
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
