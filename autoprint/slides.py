"""Урок из презентации: PDF или PowerPoint (.pptx) → этапы и слайды-картинки, под каждым — заметки докладчика.

- PDF: каждая страница — слайд (картинка шириной 1600 px), подпись — первая строка текста страницы, один этап
  «Презентация».
- PPTX: порядок слайдов — из ppt/presentation.xml (имена slideN.xml могут идти не по порядку), разделы
  PowerPoint — этапы, заметки докладчика — плашки по пометкам («Скажи:», «Спроси:» и «→», «Сделай:», «Термин:»,
  «Важно:», «Задание:»; без пометки — «Расскажи»). Картинки слайдов берутся из PDF той же презентации: файл
  рядом с тем же именем, иначе сохраняем в PDF через PowerPoint (тихо, без окна), иначе просим выбрать PDF.
  Скрытые слайды PowerPoint в PDF не сохраняет — их пропускаем и говорим об этом.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from . import materials
from .storage import (BLOCK_IMAGE, BLOCK_MARKDOWN, BLOCK_STAGE, DATA_DIR, MEDIA_FOLDER, Block, Template,
                      media_ref)

log = logging.getLogger(__name__)

P_NS = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
P14_NS = "{http://schemas.microsoft.com/office/powerpoint/2010/main}"
DEFAULT_MINUTES = 45
SLIDE_WIDTH = 1600
CREATE_NO_WINDOW = 0x08000000


# ---------------------------------------------------------------- PDF

def _first_line(text: str, limit: int = 80) -> str:
    for ln in (text or "").replace("\r", "\n").replace(" ", "\n").split("\n"):
        ln = ln.strip()
        if ln:
            return ln if len(ln) <= limit else ln[:limit - 1].rstrip() + "…"
    return ""


def pdf_pages(pdf: str) -> list[tuple[str, str]]:
    """Страницы PDF → [(ссылка на картинку, первая строка текста)]."""
    doc = materials._open_pdf(pdf)
    try:
        texts = [doc.getAllText(i).text() for i in range(doc.pageCount())]
    finally:
        doc.close()
    out = []
    for i, text in enumerate(texts, start=1):
        img = materials.render_page(pdf, i, DATA_DIR / MEDIA_FOLDER, width=SLIDE_WIDTH)
        out.append((media_ref(img) if img else "", _first_line(text)))
    return out


def from_pdf(path: str, title: str = "", minutes: int = DEFAULT_MINUTES) -> Template:
    pages = pdf_pages(path)
    blocks = [Block(BLOCK_STAGE, "", title="Презентация", minutes=minutes)]
    for n, (ref, cap) in enumerate(pages, start=1):
        blocks.append(Block(BLOCK_IMAGE, ref, title=cap, slide=n))
    return Template(title or Path(path).stem, blocks)


# ---------------------------------------------------------------- PPTX: порядок, разделы, заметки

def _xml(z: zipfile.ZipFile, name: str):
    try:
        return ET.fromstring(z.read(name))
    except (KeyError, ET.ParseError):
        return None


def _rels(z: zipfile.ZipFile, name: str) -> dict[str, str]:
    root = _xml(z, name)
    return {r.get("Id"): r.get("Target", "") for r in root.iter(REL_NS + "Relationship")} if root is not None else {}


def _shapes_text(root, skip=("sldNum", "sldImg", "hdr", "ftr", "dt")) -> tuple[str, str]:
    """(заголовок, весь текст) фигур; служебные поля (номер слайда, картинка в заметках) — мимо."""
    title, parts = "", []
    for sp in root.iter(P_NS + "sp"):
        ph = sp.find(f"{P_NS}nvSpPr/{P_NS}nvPr/{P_NS}ph")
        kind = ph.get("type", "") if ph is not None else ""
        if kind in skip:
            continue
        lines = ["".join(t.text or "" for t in p.iter(A_NS + "t")).strip() for p in sp.iter(A_NS + "p")]
        text = "\n".join(lines).strip("\n")
        if kind in ("title", "ctrTitle") and not title:
            title = " ".join(x for x in lines if x)
        if text:
            parts.append(text)
    return title, "\n".join(parts)


def pptx_info(path: str) -> tuple[list[dict], list[tuple[str, list[int]]]]:
    """Слайды по порядку показа [{n, title, text, notes, hidden}] и разделы [(название, [номера слайдов])]."""
    with zipfile.ZipFile(path) as z:
        pres = _xml(z, "ppt/presentation.xml")
        rels = _rels(z, "ppt/_rels/presentation.xml.rels")
        order: list[tuple[str, str]] = []           # (id слайда, файл)
        if pres is not None:
            for s in pres.iter(P_NS + "sldId"):
                target = rels.get(s.get(R_NS + "id"), "")
                if target:
                    order.append((s.get("id", ""), "ppt/" + target.lstrip("/").removeprefix("ppt/")))
        if not order:                                # нет presentation.xml — по номерам файлов
            names = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                           key=materials._slide_no)
            order = [("", n) for n in names]
        slides = []
        for k, (sid, name) in enumerate(order, start=1):
            root = _xml(z, name)
            if root is None:
                continue
            title, text = _shapes_text(root)
            notes = ""
            srels = _rels(z, name.replace("slides/", "slides/_rels/") + ".rels")
            for target in srels.values():
                m = re.search(r"notesSlides/(notesSlide\d+\.xml)$", target)
                if m:
                    nroot = _xml(z, "ppt/notesSlides/" + m.group(1))
                    if nroot is not None:
                        notes = _shapes_text(nroot)[1]
            slides.append({"n": k, "id": sid, "title": title or _first_line(text), "text": text, "notes": notes,
                           "hidden": root.get("show") == "0"})
        sections = []
        if pres is not None:
            pos = {s["id"]: s["n"] for s in slides if s["id"]}
            for sec in pres.iter(P14_NS + "section"):
                nums = [pos[x.get("id")] for x in sec.iter(P14_NS + "sldId") if x.get("id") in pos]
                sections.append((sec.get("name") or "Раздел", nums))
    return slides, sections


# пометки в заметках докладчика → роли
_MARKS = [(re.compile(r"^(скажи|говоришь|говорю|дословно)\s*:\s*", re.I), "say"),
          (re.compile(r"^(спроси|вопрос)\s*:\s*", re.I), "ask"),
          (re.compile(r"^(сделай|делаешь|действие)\s*:\s*", re.I), "do"),
          (re.compile(r"^термин\s*:\s*", re.I), "term"),
          (re.compile(r"^(важно!?)\s*:?\s+", re.I), "important"),
          (re.compile(r"^(задание|задача)\s*:\s*", re.I), "task"),
          (re.compile(r"^(расскажи|своими словами)\s*:\s*", re.I), "tell"),
          (re.compile(r"^(покажи|показываешь)\s*:\s*", re.I), "show")]
_ANSWER = re.compile(r"^\s*(→|->)\s*")


def notes_blocks(text: str) -> list[Block]:
    """Заметки докладчика → плашки. Пустая строка заканчивает плашку; строки «→» — ответы к «Спроси»."""
    out: list[Block] = []
    role, lines = "", []

    def flush() -> None:
        nonlocal role, lines
        body = "\n".join(lines).strip()
        if body:
            r = role or "tell"
            if r == "term":
                head, sep, rest = body.partition("\n")
                m = re.match(r"^(.+?)\s+[—–-]\s+(.+)$", head)
                if m and not sep:
                    body = m.group(1).strip() + "\n" + m.group(2).strip()
                elif m:
                    body = m.group(1).strip() + "\n" + m.group(2).strip() + "\n" + rest
            out.append(Block(BLOCK_MARKDOWN, body, role=r))
        role, lines = "", []

    for raw in (text or "").replace("\r", "\n").split("\n"):
        ln = raw.strip()
        if not ln:
            flush()
            continue
        if _ANSWER.match(ln) and role == "ask":
            lines.append("→ " + _ANSWER.sub("", ln))
            continue
        for rx, r in _MARKS:
            m = rx.match(ln)
            if m:
                flush()
                role = r
                rest = ln[m.end():].strip()
                if rest:
                    lines.append(rest)
                break
        else:
            if role in ("say", "ask", "do", "important", "task", "show") and lines:
                flush()                   # без пометки после помеченной строки — уже своими словами (у термина — определение)
            lines.append(ln)
    flush()
    return out


def _split_minutes(total: int, weights: list[int]) -> list[int]:
    s = sum(weights) or 1
    mins = [max(1, round(total * w / s)) for w in weights]
    mins[-1] += total - sum(mins)
    if mins[-1] < 1:
        mins[-1] = 1
    return mins


def from_pptx(path: str, pdf: str | None = None, minutes: int = DEFAULT_MINUTES,
              export: bool = True) -> tuple[Template, list[str], bool]:
    """PPTX → (урок, замечания, нужен ли PDF). PDF: указанный, иначе рядом с тем же именем, иначе — сохранить
    через PowerPoint (export); не вышло — слайды без картинок и need_pdf=True."""
    slides, sections = pptx_info(path)
    warns: list[str] = []
    if pdf is None:
        near = Path(path).with_suffix(".pdf")
        if near.is_file():
            pdf = str(near)
        elif export:
            pdf = export_pdf(path)
    need_pdf = pdf is None
    pages = pdf_pages(pdf) if pdf else []
    visible = [s for s in slides if not s["hidden"]]
    hidden = [s for s in slides if s["hidden"]]
    images: dict[int, str] = {}
    if pages:
        if len(pages) == len(visible):
            images = {s["n"]: pages[i][0] for i, s in enumerate(visible)}
            if hidden:
                warns.append("Скрытые слайды " + ", ".join(str(s["n"]) for s in hidden) + " пропущены — их нет в PDF.")
        else:
            images = {s["n"]: pages[i][0] for i, s in enumerate(slides) if i < len(pages)}
            warns.append(f"Страниц в PDF: {len(pages)}, слайдов в презентации: {len(slides)} — картинки разложены по "
                         "порядку; проверьте последние слайды.")
            hidden = []
    use = [s for s in slides if s not in hidden]
    # этапы: разделы PowerPoint, иначе один «Презентация»
    groups = [(name, [s for s in use if s["n"] in nums]) for name, nums in sections] if sections else []
    groups = [(n, g) for n, g in groups if g] or [("Презентация", use)]
    mins = _split_minutes(minutes, [len(g) for _n, g in groups])
    blocks: list[Block] = []
    for (name, group), m in zip(groups, mins):
        blocks.append(Block(BLOCK_STAGE, "", title=name, minutes=m))
        for s in group:
            blocks.append(Block(BLOCK_IMAGE, images.get(s["n"], ""), title=s["title"], slide=s["n"]))
            blocks += notes_blocks(s["notes"])
    if need_pdf:
        warns.append("Картинок слайдов нет: сохраните презентацию как PDF (Файл → Сохранить как → PDF) и выберите "
                     "оба файла — заметки возьмём из PPTX.")
    return Template(Path(path).stem, blocks), warns, need_pdf


# ---------------------------------------------------------------- PowerPoint → PDF (без окна)

def powerpoint_installed() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"PowerPoint.Application\CurVer"):
            return True
    except OSError:
        return False


_PS_EXPORT = r"""
$ErrorActionPreference = 'Stop'
$was = @(Get-Process POWERPNT -ErrorAction SilentlyContinue).Count -gt 0
$pp = New-Object -ComObject PowerPoint.Application
try {
  $p = $pp.Presentations.Open($env:AP_SRC, -1, 0, 0)
  $p.SaveAs($env:AP_OUT, 32)
  $p.Close()
} finally {
  if (-not $was) { $pp.Quit() }
}
"""


def export_pdf(pptx: str) -> str | None:
    """Сохранить .pptx в PDF через PowerPoint (COM из PowerShell, без окна). Если PowerPoint был открыт у
    учителя (идёт показ) — его не закрываем. None — PowerPoint нет или не получилось."""
    if os.name != "nt" or not powerpoint_installed() or not shutil.which("powershell"):
        return None
    src = Path(pptx).resolve()
    st = src.stat()
    key = hashlib.sha1(f"{src}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()[:12]
    out_dir = DATA_DIR / "slides"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{key}.pdf"
    if out.is_file():
        return str(out)
    env = dict(os.environ, AP_SRC=str(src), AP_OUT=str(out))
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                            _PS_EXPORT], env=env, capture_output=True, text=True, timeout=180,
                           creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("PowerPoint → PDF не вышло: %s", e)
        return None
    if r.returncode != 0 or not out.is_file():
        log.warning("PowerPoint → PDF не вышло (код %s): %s", r.returncode, (r.stderr or "")[-300:])
        return None
    log.info("Презентация %s сохранена в PDF через PowerPoint", src.name)
    return str(out)
