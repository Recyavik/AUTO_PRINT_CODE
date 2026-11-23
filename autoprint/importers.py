"""Импорт образцов из Jupyter-тетрадок (.ipynb), Markdown (.md) и Python-файлов (.py).

Файл забирается целиком, как есть: каждая ячейка — отдельный блок
в исходном порядке (пустые ячейки пропускаются).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .storage import BLOCK_CODE, BLOCK_IMAGE, BLOCK_MARKDOWN, BLOCK_STAGE, Block, Template

# подсказки преподавателю — в тетрадку для учеников не попадают (суфлёр урока)


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
        try:   # шаги строк (печать по шагам) — из нашей же тетрадки, если её экспортировали отсюда
            steps = [max(1, int(s)) for s in m.get("steps") or []]
        except (TypeError, ValueError):
            steps = []
        if kind == "markdown" and m.get("type") == BLOCK_STAGE:      # этап урока из нашей же тетрадки
            try:
                minutes = max(0, int(m.get("minutes") or 0))
            except (TypeError, ValueError):
                minutes = 0
            blocks.append(Block(BLOCK_STAGE, str(m.get("note") or ""), title=str(m.get("title") or ""),
                                minutes=minutes, stage_kind=str(m.get("stage_kind") or ""),
                                part=str(m.get("part") or "")))
            continue
        if kind == "markdown" and m.get("type") == BLOCK_IMAGE and m.get("src"):
            src = str(m["src"])
            from .storage import media_path
            if media_path(src) is None and m.get("_attachment"):
                src = _attachment_media(m["_attachment"]) or src
            blocks.append(Block(BLOCK_IMAGE, src, title=str(m.get("title") or "")))
            continue
        blocks.append(Block(BLOCK_MARKDOWN if kind == "markdown" else BLOCK_CODE, text, lang=lang,
                            role=m.get("role", "text"), title=m.get("title", ""), steps=steps))
    return Template(title=title, blocks=blocks)


def _guess_lang(nb: dict) -> str:
    meta = nb.get("metadata", {})
    name = (meta.get("language_info", {}).get("name")
            or meta.get("kernelspec", {}).get("language") or "python")
    return str(name).lower()


def _attachment_media(item) -> str:
    """Вложение ячейки Jupyter (имя, {mime: base64}) → копия в data/media. "" — не вышло."""
    import base64
    import tempfile
    from .storage import import_media
    try:
        name, data = item
        mime, b64 = next((k, v) for k, v in data.items() if str(k).startswith("image/"))
        raw = base64.b64decode("".join(b64) if isinstance(b64, list) else b64)
        ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp",
               "image/svg+xml": ".svg"}.get(mime, Path(str(name)).suffix or ".png")
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / f"attachment{ext}"
            f.write_bytes(raw)
            return import_media(f)
    except (StopIteration, ValueError, TypeError, OSError):
        return ""


def import_ipynb(path: str) -> Template:
    return notebook(json.loads(Path(path).read_text(encoding="utf-8-sig")), Path(path).stem)   # -sig: с BOM


def notebook(nb: dict, title: str) -> Template:
    if "cells" not in nb:
        raise ValueError("Это не тетрадка Jupyter (нет поля cells). Поддерживается формат nbformat 4.")
    lang = _guess_lang(nb)
    cells = []
    for c in nb["cells"]:
        kind = c.get("cell_type")
        if kind in ("markdown", "code"):
            meta = dict(c.get("metadata", {}).get("autoprintcode", {}))
            att = c.get("attachments")
            if isinstance(att, dict) and att:
                meta["_attachment"] = next(iter(att.items()))
            cells.append((kind, _cell_text(c), meta))
        elif kind == "raw":
            cells.append(("markdown", "```\n" + _cell_text(c) + "\n```"))
    return _build(title, cells, lang)


_FENCE = re.compile(r"^```[ \t]*([\w+#.-]*)[^\n]*\n(.*?)^```[ \t]*$", re.M | re.S)


def import_markdown(path: str) -> Template:
    return markdown_text(Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n"), Path(path).stem)


def markdown_text(text: str, title: str) -> Template:
    """Markdown: текст между ```-блоками — пояснения, сами блоки — код (язык по метке ```python)."""
    cells: list[tuple] = []
    pos = 0
    langs = []
    for m in _FENCE.finditer(text):
        cells.append(("markdown", text[pos:m.start()].strip("\n")))
        cells.append(("code", m.group(2).rstrip("\n")))
        langs.append(m.group(1).lower() or "text")
        pos = m.end()
    cells.append(("markdown", text[pos:].strip("\n")))
    t = _build(title, cells, "python")
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
    return python_text(Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n"), Path(path).stem)


def python_text(text: str, title: str) -> Template:
    lines = text.split("\n")
    marks = [i for i, ln in enumerate(lines) if _PY_CELL.match(ln)]
    if not marks:
        return _build(title, [("code", text.strip("\n"))], "python")
    cells: list[tuple] = [("code", "\n".join(lines[:marks[0]]).strip("\n"))]
    for n, i in enumerate(marks):
        body = lines[i + 1:marks[n + 1] if n + 1 < len(marks) else len(lines)]
        header = _PY_CELL.match(lines[i]).group(1)
        if _PY_MD_TAG.search(header):
            cells.append(("markdown", _uncomment(body)))
        else:
            head = header.strip()
            cells.append(("code", "\n".join(body).strip("\n"), {"title": head} if head else {}))
    return _build(title, cells, "python")


FILE_FILTER = ("Тетрадки и занятия (*.ipynb *.md *.py *.pyw *.json);;Jupyter (*.ipynb);;Markdown (*.md);;"
               "Python (*.py *.pyw);;JSON (*.json)")
FILE_EXTS = (".ipynb", ".md", ".py", ".pyw", ".json")


def load_file(path: str) -> Template:
    """Занятие из файла: .ipynb, .md, .py, .json (наш экспорт или ответ нейросети)."""
    from .storage import TemplateStore
    ext = Path(path).suffix.lower()
    if ext == ".ipynb":
        return import_ipynb(path)
    if ext == ".md":
        from . import lesson_md
        text = Path(path).read_text(encoding="utf-8-sig")
        if lesson_md.looks_like_lesson(text):          # урок: этапы, подсказки, картинки рядом с файлом
            return lesson_md.parse(text, Path(path).parent, Path(path).stem)
        return import_markdown(path)
    if ext in (".py", ".pyw"):
        return import_python(path)
    text = Path(path).read_text(encoding="utf-8-sig")
    try:
        return TemplateStore.read_template_file(path)
    except (ValueError, KeyError, TypeError):
        from .lesson_ai import parse_lesson
        return parse_lesson(text, Path(path).stem).template


# ---------------------------------------------------------------- «Вставить»: текст из буфера

def guess_lang(code: str) -> str:
    """Язык кода по виду — для вставленного без пояснений кода (ошибся — поправят в шапке блока)."""
    s = code
    if re.search(r"#include|std::|\bint main\s*\(", s):
        return "cpp"
    if re.search(r"public static void main|System\.out\.", s):
        return "java"
    if re.search(r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE TABLE)\b", s, re.I | re.M):
        return "sql"
    if re.search(r"<(html|div|body|head|p|span)\b", s, re.I):
        return "html"
    if re.search(r"^\s*(def |class \w+.*:|import \w|from \S+ import |print\()", s, re.M):
        return "python"
    if re.search(r"\b(function|const|let|var)\b|=>|console\.log", s):
        return "javascript"
    if re.search(r"^\s*(using System|namespace \w)", s, re.M):
        return "csharp"
    return "python"


def parse_pasted(text: str, lang: str = "") -> tuple[Template, str]:
    """Вставленный текст → (занятие, что распознано). Понимает: ответ нейросети и наш .json, тетрадку
    Jupyter (JSON), Markdown с ```-блоками, Python с ячейками «# %%», просто код (lang — язык; "" — угадать)."""
    from .lesson_ai import extract_json, parse_lesson
    from .storage import _fresh_ids, _template_from
    src = text.replace("\r\n", "\n").strip("\n")
    if not src.strip():
        raise ValueError("Вставьте текст: код, Markdown или ответ нейросети.")
    data = extract_json(src) if src.lstrip()[:1] in "{`" or "```json" in src else None
    if isinstance(data, dict):
        if isinstance(data.get("autoprintcode_template"), dict):
            return _fresh_ids(_template_from(data["autoprintcode_template"])), "занятие AutoPrintCode (.json)"
        if isinstance(data.get("cells"), list):
            return notebook(data, "Тетрадка Jupyter"), "тетрадка Jupyter"
        if isinstance(data.get("blocks"), list):
            return parse_lesson(src).template, "занятие от нейросети"
    from . import lesson_md
    if lesson_md.looks_like_lesson(src):
        return lesson_md.parse(src, None, "Вставленный урок"), "урок в Markdown"
    if _FENCE.search(src):
        t = markdown_text(src, "Вставленное занятие")
        return t, "Markdown с блоками кода"
    if any(_PY_CELL.match(ln) for ln in src.split("\n")):
        return python_text(src, "Вставленный код"), "Python с ячейками # %%"
    code_lang = lang or guess_lang(src)
    t = _build("Вставленный код", [("code", src)], code_lang)
    return t, f"код ({code_lang})"


def export_ipynb(t: Template, path: str, students: bool = False) -> None:
    """Образец → тетрадка: условие → markdown-ячейка, блок кода → code-ячейка. Этап урока — заголовком,
    картинка — ссылкой на файл (обратно в программу они возвращаются этапом и картинкой).
    students=True — тетрадка для учеников: только ячейки кода (заметки, этапы и картинки — для преподавателя)."""
    def src(text: str) -> list[str]:
        lines = text.split("\n")
        return [ln + "\n" for ln in lines[:-1]] + [lines[-1]]

    cells = []
    lang = "python"
    for b in t.blocks:
        if students and b.type != BLOCK_CODE:
            continue
        if b.type == BLOCK_STAGE:
            head = f"## {b.title or 'Этап'}"
            if not students:
                info = " · ".join(x for x in (f"{b.minutes} мин" if b.minutes else "", b.text.strip()) if x)
                head += f"\n*{info}*" if info else ""
            meta = {} if students else {"autoprintcode": {"type": BLOCK_STAGE, "title": b.title, "minutes": b.minutes,
                                                          "stage_kind": b.stage_kind, "part": b.part,
                                                          "note": b.text}}
            cells.append({"cell_type": "markdown", "source": src(head), "metadata": meta})
        elif b.type == BLOCK_IMAGE:
            if not b.text.strip():
                continue
            from .storage import media_path
            local = media_path(b.text)
            cell = {"cell_type": "markdown", "source": src(f"![{b.title}]({b.text})"),
                    "metadata": {"autoprintcode": {"type": BLOCK_IMAGE, "src": b.text, "title": b.title}}}
            mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
                    ".webp": "image/webp", ".svg": "image/svg+xml"}.get(local.suffix.lower()) if local else None
            if local is not None and mime:
                import base64
                name = local.name
                cell["source"] = src(f"![{b.title}](attachment:{name})")
                cell["attachments"] = {name: {mime: base64.b64encode(local.read_bytes()).decode("ascii")}}
            cells.append(cell)
        elif b.type == BLOCK_MARKDOWN:
            cells.append({"cell_type": "markdown", "source": src(b.text),
                          "metadata": {"autoprintcode": {"role": b.role, "title": b.title}}})
        else:
            lang = b.lang or lang
            meta = {"title": b.title}
            if b.steps:   # разметка шагов переживает экспорт и импорт обратно
                meta["steps"] = list(b.steps)
            cells.append({"cell_type": "code", "metadata": {"autoprintcode": meta},
                          "execution_count": None,
                          "outputs": [], "source": src(b.text)})
    nb = {"cells": cells, "nbformat": 4, "nbformat_minor": 5,
          "metadata": {"language_info": {"name": lang}}}
    Path(path).write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
