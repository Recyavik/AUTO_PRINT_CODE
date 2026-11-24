"""Материал для нейросети: текст из методички, презентации или расшифровки — PDF, DOCX, PPTX, текст.

PDF и PPTX размечаются по страницам/слайдам («=== Страница 3 ===»), чтобы нейросеть могла сослаться на
слайд, а программа — вставить его картинкой (render_page, только PDF). В DOCX выделенный цветом текст
(в методичках так отмечают речь преподавателя) обрамляется ⟦…⟧.
"""
from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
MARK_NOTE = ("(Текст в ⟦…⟧ в исходном документе выделен цветом — часто так отмечают то, что преподаватель "
             "говорит почти дословно.)")
TEXT_EXTS = {".txt", ".md", ".markdown", ".py", ".js", ".ts", ".html", ".htm", ".css", ".json", ".kt", ".java",
             ".cs", ".cpp", ".c", ".sql", ".csv", ".ipynb", ".xml", ".yaml", ".yml"}


@dataclass
class Material:
    text: str
    pdf: str | None = None     # путь к PDF — из него можно вставлять слайды картинками
    pages: int = 0


def extract(path: str) -> Material:
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".pdf":
        return _pdf(p)
    if ext in (".docx", ".pptx"):
        try:
            if ext == ".docx":
                return Material(_docx(p))
            text, n = _pptx(p)
            return Material(text, pages=n)
        except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:   # не тот файл или повреждён
            raise ValueError(f"Файл {p.name} не открылся как документ {ext[1:].upper()} — возможно, он повреждён "
                             f"или это другой формат ({e.__class__.__name__}). Сохраните его заново или в PDF.") from e
    if ext in (".doc", ".ppt"):
        raise ValueError(f"Старый формат {ext}: сохраните файл как .{ext[1:]}x (Word/PowerPoint → «Сохранить как») "
                         "или в PDF.")
    return Material(_read_text(p))


def _read_text(p: Path) -> str:
    raw = p.read_bytes()
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- DOCX

def _colored(run) -> bool:
    rpr = run.find(W_NS + "rPr")
    if rpr is None:
        return False
    c = rpr.find(W_NS + "color")
    if c is not None and (c.get(W_NS + "val") or "").lower() not in ("", "auto", "000000"):
        return True
    h = rpr.find(W_NS + "highlight")
    if h is not None and (h.get(W_NS + "val") or "").lower() not in ("", "none"):
        return True
    s = rpr.find(W_NS + "shd")
    return s is not None and (s.get(W_NS + "fill") or "").lower() not in ("", "auto", "ffffff")


def _docx(p: Path) -> str:
    with zipfile.ZipFile(p) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    lines, marked_any = [], False
    for para in root.iter(W_NS + "p"):
        parts: list[str] = []
        open_mark = False
        for run in para.iter(W_NS + "r"):
            text = "".join(t.text or "" for t in run.iter(W_NS + "t"))
            if run.find(W_NS + "tab") is not None:
                text = "\t" + text
            if not text:
                continue
            mark = _colored(run) and bool(text.strip())
            if mark and not open_mark:
                parts.append("⟦")
                marked_any = True
            elif not mark and open_mark:
                parts.append("⟧")
            open_mark = mark
            parts.append(text)
        if open_mark:
            parts.append("⟧")
        lines.append("".join(parts).rstrip())
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return (MARK_NOTE + "\n\n" + text) if marked_any else text


# ---------------------------------------------------------------- PPTX

def _slide_no(name: str) -> int:
    m = re.search(r"(\d+)\.xml$", name)
    return int(m.group(1)) if m else 0


def _shape_text(xml: bytes) -> str:
    root = ET.fromstring(xml)
    out = []
    for para in root.iter(A_NS + "p"):
        line = "".join(t.text or "" for t in para.iter(A_NS + "t")).strip()
        if line:
            out.append(line)
    return "\n".join(out)


def _pptx(p: Path) -> tuple[str, int]:
    """Текст слайдов и заметок докладчика — в порядке показа (ppt/presentation.xml), номера — как в PowerPoint."""
    from .slides import pptx_info
    try:
        slides, _sections = pptx_info(str(p))
    except (KeyError, ET.ParseError):
        slides = []
    if slides:
        out = []
        for s in slides:
            out.append(f"=== Слайд {s['n']} ===" + (" (скрытый)" if s["hidden"] else "") + f"\n{s['text']}")
            if s["notes"]:
                out.append(f"Заметки к слайду {s['n']}:\n{s['notes']}")
        return "\n\n".join(out).strip(), len(slides)
    with zipfile.ZipFile(p) as z:
        names = set(z.namelist())
        slides = sorted((n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=_slide_no)
        out = []
        for n in slides:
            k = _slide_no(n)
            out.append(f"=== Слайд {k} ===\n{_shape_text(z.read(n))}")
            rels = f"ppt/slides/_rels/slide{k}.xml.rels"
            if rels in names:      # заметки докладчика — часто там и есть текст для преподавателя
                for target in re.findall(rb'Target="\.\./notesSlides/(notesSlide\d+\.xml)"', z.read(rels)):
                    note = f"ppt/notesSlides/{target.decode()}"
                    if note in names:
                        text = _shape_text(z.read(note))
                        if text:
                            out.append(f"Заметки к слайду {k}:\n{text}")
    return "\n\n".join(out).strip(), len(slides)


# ---------------------------------------------------------------- PDF (QtPdf)

def _open_pdf(path: str):
    from PySide6.QtPdf import QPdfDocument
    doc = QPdfDocument(None)
    err = doc.load(path)
    if err != QPdfDocument.Error.None_:
        raise ValueError(f"PDF не открылся: {err.name}")
    return doc


def _pdf(p: Path) -> Material:
    doc = _open_pdf(str(p))
    try:
        n = doc.pageCount()
        out = []
        for i in range(n):
            text = doc.getAllText(i).text().replace("\r\n", "\n").replace("\r", "\n").replace(" ", "\n")
            out.append(f"=== Страница {i + 1} ===\n{text.strip()}")
        return Material("\n\n".join(out).strip(), pdf=str(p), pages=n)
    finally:
        doc.close()


def render_page(pdf: str, page: int, out_dir: Path, width: int = 1280) -> Path | None:
    """Страница PDF (с 1) → PNG в out_dir. None — такой страницы нет или PDF не открылся."""
    from PySide6.QtCore import QSize
    try:
        doc = _open_pdf(pdf)
    except ValueError:
        return None
    try:
        if not 1 <= page <= doc.pageCount():
            return None
        size = doc.pagePointSize(page - 1)
        if size.width() <= 0:
            return None
        h = max(1, round(width * size.height() / size.width()))
        img = doc.render(page - 1, QSize(width, h))
        if img.isNull():
            return None
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        st = Path(pdf).stat()
        key = hashlib.sha1(f"{Path(pdf).resolve()}|{st.st_mtime_ns}|{width}".encode()).hexdigest()[:10]
        out = out_dir / f"slide-{key}-{page}.png"
        return out if img.save(str(out), "PNG") else None
    finally:
        doc.close()
