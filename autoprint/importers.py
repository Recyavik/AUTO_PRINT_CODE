"""Импорт образцов из Jupyter-тетрадок (.ipynb), Markdown (.md) и Python-файлов (.py).

Файл забирается целиком, как есть: каждая ячейка — отдельный блок
в исходном порядке (пустые ячейки пропускаются).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .storage import BLOCK_CODE, BLOCK_MARKDOWN, Block, Template


def _cell_text(cell: dict) -> str:
    src = cell.get("source", "")
    text = "".join(src) if isinstance(src, list) else str(src)
    return text.replace("\r\n", "\n").rstrip("\n")


def _build(title: str, cells: list[tuple], lang: str) -> Template:
    """cells: [(kind, text)] где kind = 'markdown' | 'code'. Одна ячейка = один блок, порядок как в файле."""
    blocks = []
    for kind, text, *meta in cells:
        if not text.strip():
            continue
        m = meta[0] if meta else {}
        blocks.append(Block(BLOCK_MARKDOWN if kind == "markdown" else BLOCK_CODE, text, lang=lang,
                            role=m.get("role", "text"), title=m.get("title", "")))
    return Template(title=title, blocks=blocks)


def _guess_lang(nb: dict) -> str:
    meta = nb.get("metadata", {})
    name = (meta.get("language_info", {}).get("name")
            or meta.get("kernelspec", {}).get("language") or "python")
    return str(name).lower()


def import_ipynb(path: str) -> Template:
    nb = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if "cells" not in nb:
        raise ValueError("Это не тетрадка Jupyter (нет поля cells). Поддерживается формат nbformat 4.")
    lang = _guess_lang(nb)
    cells = []
    for c in nb["cells"]:
        kind = c.get("cell_type")
        if kind in ("markdown", "code"):
            cells.append((kind, _cell_text(c), c.get("metadata", {}).get("autoprintcode", {})))
        elif kind == "raw":
            cells.append(("markdown", "```\n" + _cell_text(c) + "\n```"))
    return _build(Path(path).stem, cells, lang)


_FENCE = re.compile(r"^```[ \t]*([\w+#.-]*)[^\n]*\n(.*?)^```[ \t]*$", re.M | re.S)


def import_markdown(path: str) -> Template:
    text = Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    cells: list[tuple] = []
    pos = 0
    langs = []
    for m in _FENCE.finditer(text):
        cells.append(("markdown", text[pos:m.start()].strip("\n")))
        cells.append(("code", m.group(2).rstrip("\n")))
        langs.append(m.group(1).lower() or "text")
        pos = m.end()
    cells.append(("markdown", text[pos:].strip("\n")))
    t = _build(Path(path).stem, cells, "python")
    # проставить язык каждому блоку кода по его ```-метке
    code_blocks = t.code_blocks()
    nonempty_langs = [lang for (kind, txt), lang in zip([c for c in cells if c[0] == "code"], langs) if txt.strip()]
    for b, lang in zip(code_blocks, nonempty_langs):
        b.lang = lang
    return t


_PY_CELL = re.compile(r"^#[ \t]*%%(.*)$")
_PY_MD_TAG = re.compile(r"\[\s*(markdown|md)\s*\]", re.I)


def _uncomment(lines: list[str]) -> str:
    out = []
    for ln in lines:
        s = ln.lstrip()
        out.append(s[2:] if s.startswith("# ") else s[1:] if s.startswith("#") else ln)
    return "\n".join(out).strip("\n")


def import_python(path: str) -> Template:
    """Python-файл. Есть разметка ячеек «# %%» (VS Code, Spyder, Jupytext) — по ячейке на блок,
    «# %% [markdown]» — блок-пояснение без «# ». Иначе весь файл — один блок кода, как есть."""
    text = Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    lines = text.split("\n")
    marks = [i for i, ln in enumerate(lines) if _PY_CELL.match(ln)]
    if not marks:
        return _build(Path(path).stem, [("code", text.strip("\n"))], "python")
    cells: list[tuple] = [("code", "\n".join(lines[:marks[0]]).strip("\n"))]
    for n, i in enumerate(marks):
        body = lines[i + 1:marks[n + 1] if n + 1 < len(marks) else len(lines)]
        header = _PY_CELL.match(lines[i]).group(1)
        if _PY_MD_TAG.search(header):
            cells.append(("markdown", _uncomment(body)))
        else:
            title = header.strip()
            cells.append(("code", "\n".join(body).strip("\n"), {"title": title} if title else {}))
    return _build(Path(path).stem, cells, "python")


def export_ipynb(t: Template, path: str) -> None:
    """Образец → тетрадка: условие → markdown-ячейка, блок кода → code-ячейка."""
    def src(text: str) -> list[str]:
        lines = text.split("\n")
        return [ln + "\n" for ln in lines[:-1]] + [lines[-1]]

    cells = []
    lang = "python"
    for b in t.blocks:
        if b.type == BLOCK_MARKDOWN:
            cells.append({"cell_type": "markdown", "source": src(b.text),
                          "metadata": {"autoprintcode": {"role": b.role, "title": b.title}}})
        else:
            lang = b.lang or lang
            cells.append({"cell_type": "code", "metadata": {"autoprintcode": {"title": b.title}},
                          "execution_count": None,
                          "outputs": [], "source": src(b.text)})
    nb = {"cells": cells, "nbformat": 4, "nbformat_minor": 5,
          "metadata": {"language_info": {"name": lang}}}
    Path(path).write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
