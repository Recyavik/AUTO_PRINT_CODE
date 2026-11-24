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
    title = ""
    skipped = set()
    for sp in root.iter(P_NS + "sp"):
        ph = sp.find(f"{P_NS}nvSpPr/{P_NS}nvPr/{P_NS}ph")
        kind = ph.get("type", "") if ph is not None else ""
        if kind in skip:
            skipped.add(sp)
        elif kind in ("title", "ctrTitle") and not title:
            title = " ".join(x for x in ("".join(t.text or "" for t in p.iter(A_NS + "t")).strip()
                                         for p in sp.iter(A_NS + "p")) if x)
    parent = {c: p for p in root.iter() for c in p}
    lines = []
    for para in root.iter(A_NS + "p"):           # весь текст слайда: фигуры, таблицы, группы — кроме служебных полей
        node, inside = para, False
        while node is not None:
            if node in skipped:
                inside = True
                break
            node = parent.get(node)
        if not inside:
            lines.append("".join(t.text or "" for t in para.iter(A_NS + "t")).strip())
    return title, "\n".join(lines).strip("\n")


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


# пометки в заметках докладчика → роли (как пишут в конспектах: «Сказать:», «Вопрос классу:», «ДЗ —», «[Покажи]»)
_ROLE_WORDS = {
    "say": ("скажи", "сказать", "говоришь", "говорю", "дословно", "учитель", "реплика"),
    "ask": ("спроси", "спросить", "вопрос", "вопросы", "вопрос классу", "вопрос к классу"),
    "answer": ("ответ", "ответы", "дети", "ученики", "ответ учеников", "ответы учеников"),
    "do": ("сделай", "сделать", "делаешь", "действие"),
    "show": ("покажи", "показать", "показываешь"),
    "tell": ("расскажи", "рассказать", "объясни", "объяснить", "своими словами"),
    "term": ("термин", "определение"),
    "important": ("важно", "важно!"),
    "task": ("задание", "задача", "задание ученикам"),
    "homework": ("дз", "д/з", "домашнее задание", "домашка"),
    "goal": ("цель", "цель урока"),
    "hint": ("подсказка", "если застрял", "если застряли"),
    "extra": ("для быстрых",),
    "trap": ("ошибки", "типичные ошибки", "ловушки"),
    "text": ("для себя", "заметка"),
    "stage": ("этап",),
}
_WORD_ROLE = {w: r for r, ws in _ROLE_WORDS.items() for w in ws}
_MARK = re.compile(r"^\s*(?:[-•*]\s+|\d+[).]\s+)?(?:\[(?P<b>[^\]]{1,30})\]\s*|"
                   r"(?P<w>[А-Яа-яЁёA-Za-z/! ]{2,30}?)(?:\s+\d+)?\s*(?::|—|–|-(?=\s)|(?<=!)(?=\s))\s*)(?P<rest>.*)$")
_BULLET = re.compile(r"^\s*(?:[-•*]|\d+[).])\s+")


def _marker(line: str) -> tuple[str, str] | None:
    """(роль, остаток строки) — если строка начинается с пометки, иначе None."""
    m = _MARK.match(line)
    if not m:
        return None
    word = re.sub(r"\s+", " ", (m.group("b") or m.group("w") or "").strip().lower())
    role = _WORD_ROLE.get(word)
    return (role, m.group("rest").strip()) if role else None


_ANSWER = re.compile(r"^\s*(→|->)\s*")


def notes_blocks(text: str) -> list[Block]:
    """Заметки докладчика → плашки. Пометка действует до следующей пометки или пустой строки (реплику, разбитую
    Enter'ом, не рвём); «Ответ:», «Ученики:», строки «→» и «- …» после «Ответы:» — ответы к вопросу;
    «Этап: Название · 10 мин» — новый этап. Без пометки — «Расскажи»."""
    from .lesson_md import _KIND_BY_WORD, _STAGE_TAIL
    out: list[Block] = []
    role, lines, answers = "", [], False

    def flush() -> None:
        nonlocal role, lines, answers
        body = "\n".join(lines).strip()
        if body:
            r = role or "tell"
            if r == "term":
                head, sep, rest = body.partition("\n")
                m = re.match(r"^(.+?)\s+[—–-]\s+(.+)$", head)
                if m:
                    body = m.group(1).strip() + "\n" + m.group(2).strip() + ("\n" + rest if sep else "")
            out.append(Block(BLOCK_MARKDOWN, body, role=r))
        role, lines, answers = "", [], False

    def answer(a: str) -> None:
        nonlocal role
        if a:
            if role != "ask":                     # «Учитель: …» / «Ученики: …» — реплика становится вопросом
                role = "ask"
            lines.append("→ " + a)

    for raw in (text or "").replace("\r", "\n").split("\n"):
        ln = raw.strip()
        if not ln:
            flush()
            continue
        if _ANSWER.match(ln):
            answer(_ANSWER.sub("", ln).strip())
            continue
        mk = _marker(ln)
        if mk is None:
            if answers and lines:
                answer(_BULLET.sub("", ln).strip())
            else:
                lines.append(ln)
            continue
        r, rest = mk
        if r == "answer":
            if not lines:
                flush()
            answers = True
            answer(rest)
            continue
        flush()
        if r == "stage":
            tail = _STAGE_TAIL.search(rest)
            minutes = int(tail.group(1)) if tail else 0
            kind = _KIND_BY_WORD.get((tail.group(2) or "").lower(), "") if tail else ""
            title = rest[:tail.start()].strip() if tail else rest
            out.append(Block(BLOCK_STAGE, "", title=title or "Этап", minutes=min(minutes, 600), stage_kind=kind))
            continue
        role = r
        if rest:
            lines.append(rest)
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
        if len(pages) == len(slides) and hidden:
            images = {s["n"]: pages[i][0] for i, s in enumerate(slides)}
            hidden = []
        elif len(pages) == len(visible):
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
    marked = 0                                      # минуты этапов из пометок «Этап: … · 10 мин»
    for (name, group), m in zip(groups, mins):
        part: list[Block] = []
        for s in group:
            nb = notes_blocks(s["notes"])
            stages = [b for b in nb if b.type == BLOCK_STAGE]
            marked += sum(b.minutes for b in stages)
            part += stages                          # этап из заметок начинается с этого слайда
            part.append(Block(BLOCK_IMAGE, images.get(s["n"], ""), title=s["title"], slide=s["n"]))
            part += [b for b in nb if b.type != BLOCK_STAGE]
        if not (part and part[0].type == BLOCK_STAGE):
            blocks.append(Block(BLOCK_STAGE, "", title=name, minutes=m))
        blocks += part
    if marked and not sections and blocks and blocks[0].type == BLOCK_STAGE and blocks[0].title == "Презентация":
        blocks[0].minutes = max(5, minutes - marked)
    if need_pdf:
        warns.append("Картинок слайдов нет: сохраните презентацию как PDF (Файл → Сохранить как → PDF) и выберите "
                     "оба файла — заметки возьмём из PPTX.")
    return Template(Path(path).stem, blocks), warns, need_pdf


# ---------------------------------------------------------------- ответ своего чата → урок по слайдам

def apply_chat_answer(t: Template, text: str) -> tuple[Template, list[str]]:
    """«⋯ → Вставить ответ нейросети»: урок в Markdown со строками «![Слайд N](slide:N)» → копия урока t: этапы и
    плашки по ответу, слайды — картинки t с теми же номерами. → (новый урок, замечания)."""
    from . import lesson_md
    from .lesson_ai import md_answer
    md = md_answer(text)
    if md is None:
        raise ValueError("В ответе нет урока в Markdown — попросите нейросеть ответить блоком ~~~markdown, как в промпте.")
    new = lesson_md.parse(md, None, t.title, local_images=False)
    if not any(b.type in (BLOCK_STAGE, BLOCK_MARKDOWN, BLOCK_IMAGE) for b in new.blocks):
        raise ValueError("В ответе нейросети пустой урок — ни этапов, ни заметок. Попросите ответить по промпту ещё раз.")
    have = {b.slide: b for b in t.blocks if b.type == BLOCK_IMAGE and b.slide}
    notes: list[str] = []
    used: list[int] = []
    missing: list[int] = []
    keep: list[Block] = []
    foreign = 0
    for b in new.blocks:
        if b.type == BLOCK_IMAGE:
            src_text = (b.text or "").strip()
            n = b.slide
            if src_text and not re.match(r"https?://", src_text, re.I):
                foreign += 1               # путь к файлу из ответа чата — не открываем
                continue
            if n and not src_text:         # место «Слайд N» — картинка слайда N этого урока
                src = have.get(n)
                if src is None:
                    missing.append(n)      # такого слайда нет — место остаётся
                else:
                    b.text, b.title = src.text, b.title or src.title
                    used.append(n)
        keep.append(b)
    new.blocks = keep
    missing = list(dict.fromkeys(missing))
    if foreign:
        notes.append(f"Картинки из ответа с путями к файлам пропущены ({foreign}) — вставьте их сами.")
    if missing:
        notes.append(", ".join(f"Слайда {n}" if i == 0 else f"слайда {n}" for i, n in enumerate(missing))
                     + " нет в презентации — вместо него место для картинки.")
    skipped = [n for n in sorted(have) if n not in used]
    if skipped:
        notes.append("Нейросеть пропустила: " + ", ".join(map(str, skipped)) + ".")
    bare = []
    for i, b in enumerate(new.blocks):
        if b.type == BLOCK_IMAGE and b.slide:
            nxt = new.blocks[i + 1] if i + 1 < len(new.blocks) else None
            if nxt is None or nxt.type in (BLOCK_IMAGE, BLOCK_STAGE):
                bare.append(b.slide)
    if bare:
        notes.append("Слайды без заметок: " + ", ".join(map(str, bare)) + ".")
    want = sum(b.minutes for b in t.blocks if b.type == BLOCK_STAGE)
    got = sum(b.minutes for b in new.blocks if b.type == BLOCK_STAGE)
    if want and got != want:
        notes.append(f"Сумма минут {got} из {want}.")
    new.look = getattr(t, "look", "")
    return new, notes


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
