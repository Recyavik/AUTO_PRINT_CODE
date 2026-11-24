"""Урок в Markdown: файл, который открывается в любом редакторе (VS Code, Obsidian, GitHub) — с картинками.

    ---
    title: Тёмная тема на сайте
    ---

    Вступление до первого этапа — обычный Markdown.

    # Тёмная тема                         ← раздел (часть урока) для следующих этапов

    ## Приветствие · 5 мин                 ← этап: название · минуты [· перерыв | · зарядка]
    *без экрана*                           ← пометка этапа: строка курсивом сразу под заголовком

    > [!say] Повторение                    ← подсказка ведущему: [!роль] и необязательный заголовок
    > Здравствуйте! На прошлом занятии…

    ```css title="Фон и текст"            ← блок кода (заголовок и шаги — необязательно)
    .darkTheme { color: #fff; }
    ```

    ![Сайт после](Урок_files/img-ab12.png) ← картинка: подпись и путь рядом с файлом

Роли в [!…] — по-английски (say, tell, ask, do, important, show, trap, extra, task, explain, hint, text) или
по-русски (говоришь, расскажи, спроси…). Незнакомое — обычный текст, без ошибок. Картинки при сохранении
кладутся в папку «<имя>_files» рядом с файлом, при открытии копируются в данные программы.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from urllib.parse import unquote

from . import storage
from .storage import BLOCK_CODE, BLOCK_IMAGE, BLOCK_MARKDOWN, BLOCK_STAGE, ROLES, Block, Template

KIND_WORDS = {"break": "перерыв", "exercise": "зарядка"}
_KIND_BY_WORD = {"перерыв": "break", "зарядка": "exercise", "break": "break", "exercise": "exercise"}
_ROLE_BY_NAME = {**{k: k for k in ROLES}, **{v[1].lower(): k for k, v in ROLES.items()},
                 "расскажи про": "tell", "важно!": "important", "ловушка": "trap", "показываешь на экране": "show",
                 # названия до 0.11
                 "ловушки": "trap", "вывод": "output", "подсказка": "hint", "домашка": "homework", "цель": "goal"}

_STAGE = re.compile(r"^##\s+(.+?)\s*$")
# «· 10 мин», «(10 мин)», «— 10 минут» [«· перерыв» | «· зарядка» | «· зарядка: Гимнастика для глаз»]
_STAGE_TAIL = re.compile(r"\s*(?:[·—–-]\s*|\()(\d+)\s*мин(?:ут[аы]?|\.)?\)?(?:\s*·\s*([^\s:·]+)(?:\s*:\s*([^·]+?))?)?\s*$",
                         re.I)
PHOTO_SRC = {"фото", "photo", "?", ""}      # ![что на картинке](фото) — место: «Нужна картинка: …»
_SLIDE_SRC = re.compile(r"^slide:\s*(\d{1,4})$", re.I)
_PART = re.compile(r"^#\s+(.+?)\s*$")
_CALLOUT = re.compile(r"^\[!([^\]]+)\]\s*(.*)$")
_FENCE = re.compile(r"^(`{3,}|~{3,})\s*([^\s`]*)\s*(.*)$")
_SLIDE_CAP = re.compile(r"^Слайд\s+(\d{1,4})(?:\s*[·—:-]\s*(.*))?$", re.I)
_IMAGE = re.compile(r"^!\[((?:[^\]\\]|\\.)*)\]\((<[^>]+>|[^)\s]*)\)\s*$")
_NOTE = re.compile(r"^(\*|_)([^*_].*?)\1\s*$")
_ATTR = re.compile(r'(\w+)="([^"]*)"')


# ---------------------------------------------------------------- запись

def _fence_for(code: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", code)), default=0)
    return "`" * max(3, longest + 1)


def _quote(text: str) -> str:
    return "\n".join("> " + ln if ln else ">" for ln in text.split("\n"))


def _image_path(rel: str) -> str:
    return f"<{rel}>" if re.search(r"[\s()<>]", rel) else rel


def stage_line(b: Block) -> str:
    """Строка этапа: «## Зарядка · 3 мин · зарядка: Гимнастика для глаз» (тот же вид — в промпте нейросети)."""
    head = f"## {(b.title or 'Этап').strip()} · {b.minutes} мин"
    if b.stage_kind in KIND_WORDS:
        head += f" · {KIND_WORDS[b.stage_kind]}"
        if b.stage_kind == "exercise" and b.exercise.strip():
            head += f": {b.exercise.strip()}"
    return head


def to_md(t: Template, media_prefix: str, copy_image=None) -> str:
    """Урок → текст .md. copy_image(block) → путь картинки для файла (None — оставить как есть)."""
    out = ["---", f"title: {t.title}"]
    if t.kind == storage.KIND_PLAN:
        out.append(f"kind: {storage.KIND_PLAN}")
    if t.start:
        out.append(f"start: {t.start}")
    out += ["---", ""]
    part = ""
    for b in t.blocks:
        if b.type == BLOCK_STAGE:
            if b.part and b.part != part:
                out += [f"# {b.part}", ""]
                part = b.part
            out.append(stage_line(b))
            if b.text.strip():
                out.append(f"*{b.text.strip()}*")
            out.append("")
        elif b.type == BLOCK_CODE:
            fence = _fence_for(b.text)
            attrs = []
            if b.title:
                attrs.append(f'title="{b.title.replace(chr(34), chr(39))}"')
            if b.steps:
                attrs.append(f'steps="{",".join(str(x) for x in b.steps)}"')
            out += [f"{fence}{b.lang or 'text'}" + (" " + " ".join(attrs) if attrs else ""), b.text, fence, ""]
        elif b.type == BLOCK_IMAGE:
            src = (b.text or "").strip()
            cap = (b.title or "").replace("]", "\\]")
            if b.slide:                     # слайд презентации: номер — в подписи («Слайд 3 · План»)
                cap = f"Слайд {b.slide}" + (f" · {cap}" if cap else "")
            if not src:                     # место: слайда ещё нет — slide:N, картинки нет — «фото»
                out += [f"![{cap}](slide:{b.slide})" if b.slide else f"![{cap}](фото)", ""]
                continue
            rel = copy_image(b) if copy_image else None
            out += [f"![{cap}]({_image_path(rel or src)})", ""]
        else:
            role = b.role if b.role in ROLES else "text"
            text = b.text.strip("\n")
            if role == "text" and not b.title and not re.search(r"^\s*(```|~~~|>|#|!\[)", text, re.M):
                out += [text, ""]           # простой текст — как есть (с разметкой внутри — плашкой [!text])
            else:
                out += [_quote(f"[!{role}]" + (f" {b.title}" if b.title else "") + "\n" + text), ""]
    return "\n".join(out).rstrip("\n") + "\n"


def export_md(t: Template, path: Path) -> Path:
    """Сохранить урок в .md; картинки — копиями в папку «<имя>_files» рядом."""
    path = Path(path)
    folder = path.parent / f"{path.stem}_files"

    def copy_image(b: Block) -> str | None:
        local = storage.media_path(b.text)
        if local is None:
            return None
        folder.mkdir(parents=True, exist_ok=True)
        dst = folder / local.name
        if not dst.exists():
            shutil.copyfile(local, dst)
        return f"{folder.name}/{local.name}"

    path.write_text(to_md(t, folder.name, copy_image), encoding="utf-8")
    return path


# ---------------------------------------------------------------- чтение

def looks_like_lesson(text: str) -> bool:
    """Это урок (этапы с минутами или подсказки [!роль]), а не просто заметки с кодом."""
    for ln in text.replace("\r\n", "\n").split("\n"):
        m = _STAGE.match(ln)
        if m and _STAGE_TAIL.search(m.group(1)):
            return True
        if ln.startswith(">"):
            c = _CALLOUT.match(ln[1:].strip())
            if c and _role(c.group(1)) != "":
                return True
    return False


_GITHUB_ALERTS = {"NOTE", "TIP", "IMPORTANT", "WARNING", "CAUTION"}


def _role(name: str) -> str:
    """Роль по имени из [!…]; "" — не наша (обычный текст). [!IMPORTANT] и др. заглавными — это выноски GitHub
    в обычных заметках, а не подсказки урока (мы пишем роли строчными)."""
    n = name.strip()
    if n in _GITHUB_ALERTS:
        return ""
    return _ROLE_BY_NAME.get(n.lower(), "")


def _resolve_image(src: str, base: Path | None, local: bool = True) -> str:
    if src.startswith("<") and src.endswith(">"):
        src = src[1:-1]
    if re.match(r"https?://", src, re.I) or not local:
        return src                   # local=False — текст не из файла урока (ответ чата): файлов с компьютера не берём
    if src.startswith(("\\\\", "//")):
        return src                   # сетевой путь — не открываем (Windows пошла бы по SMB)
    rel = unquote(src)
    for cand in ([base / rel] if base is not None else []) + [Path(rel)]:
        try:
            if cand.is_file():
                return storage.import_media(cand)
        except OSError:
            continue
    return rel                       # файла нет — блок останется, суфлёр покажет «нет файла»


def parse(text: str, base: Path | None, title: str, local_images: bool = True) -> Template:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    t = Template(title=title)
    i = 0
    if lines and lines[0].strip() == "---":          # шапка: title, start
        for j in range(1, len(lines)):
            if lines[j].strip() == "---":
                for ln in lines[1:j]:
                    k, _, v = ln.partition(":")
                    if k.strip() == "title" and v.strip():
                        t.title = v.strip()
                    elif k.strip() == "start":
                        t.start = v.strip()
                    elif k.strip() == "kind" and v.strip() == storage.KIND_PLAN:
                        t.kind = storage.KIND_PLAN
                i = j + 1
                break
    blocks: list[Block] = []
    para: list[str] = []
    part = ""
    heading: tuple[str, int] | None = None

    def keep_heading() -> None:
        nonlocal heading
        if heading is not None:
            blocks.insert(heading[1], Block(BLOCK_MARKDOWN, heading[0].strip(), role="text"))
            heading = None

    def flush() -> None:
        txt = "\n".join(para).strip("\n")
        if txt.strip():
            blocks.append(Block(BLOCK_MARKDOWN, txt, role="text"))
        para.clear()

    n = len(lines)
    while i < n:
        ln = lines[i]
        fm = _FENCE.match(ln)
        if fm:
            flush()
            fence, lang, rest = fm.group(1), fm.group(2), fm.group(3)
            attrs = dict(_ATTR.findall(rest))
            body = []
            i += 1
            close = re.compile(re.escape(fence[0]) + "{%d,}" % len(fence))
            while i < n and not close.fullmatch(lines[i].strip()):
                body.append(lines[i])
                i += 1
            steps = [int(x) for x in re.findall(r"\d+", attrs.get("steps", ""))]
            blocks.append(Block(BLOCK_CODE, "\n".join(body), lang=(lang or "text").lower(),
                                title=attrs.get("title", ""), steps=steps))
            i += 1
            continue
        if ln.startswith(">"):
            flush()
            quote = []
            while i < n and lines[i].startswith(">"):
                q = lines[i][1:]
                quote.append(q[1:] if q.startswith(" ") else q)
                i += 1
            c = _CALLOUT.match(quote[0].strip()) if quote else None
            if c:
                role = _role(c.group(1)) or "text"
                blocks.append(Block(BLOCK_MARKDOWN, "\n".join(quote[1:]).strip("\n"), role=role,
                                    title=c.group(2).strip()))
            else:
                blocks.append(Block(BLOCK_MARKDOWN, "\n".join("> " + q for q in quote), role="text"))
            continue
        sm = _STAGE.match(ln)
        if sm:
            flush()
            head = sm.group(1)
            minutes, kind, video = 0, "", ""
            tail = _STAGE_TAIL.search(head)
            if tail:
                minutes = int(tail.group(1))
                kind = _KIND_BY_WORD.get((tail.group(2) or "").lower(), "")
                video = (tail.group(3) or "").strip() if kind == "exercise" else ""
                head = head[:tail.start()]
            note = ""
            j = i + 1
            if j < n and _NOTE.match(lines[j].strip()):
                note = _NOTE.match(lines[j].strip()).group(2).strip()
                j += 1
            heading = None
            blocks.append(Block(BLOCK_STAGE, note, title=head.strip(), minutes=min(minutes, 1440),
                                stage_kind=kind, part=part, exercise=video[:200]))
            i = j
            continue
        pm = _PART.match(ln)
        if pm:
            flush()
            keep_heading()
            part = pm.group(1).strip()
            heading = (ln, len(blocks))           # станет разделом этапов; этапа после него нет — останется текстом
            i += 1
            continue
        im = _IMAGE.match(ln.strip())
        if im:
            flush()
            cap = im.group(1).replace("\\]", "]")
            sm = _SLIDE_CAP.match(cap)
            slide_no = int(sm.group(1)) if sm else 0
            if sm:
                cap = sm.group(2) or ""
            src = im.group(2)
            src = src[1:-1] if src.startswith("<") and src.endswith(">") else src
            ss = _SLIDE_SRC.match(src.strip())
            if ss:                              # ![Слайд 4](slide:4) — место слайда: картинку подставят из презентации
                blocks.append(Block(BLOCK_IMAGE, "", title=cap, slide=int(ss.group(1))))
            elif src.strip().casefold() in PHOTO_SRC:     # ![Кот у ноутбука](фото) — место: «Нужна картинка»
                blocks.append(Block(BLOCK_IMAGE, "", title=cap, slide=slide_no))
            else:
                blocks.append(Block(BLOCK_IMAGE, _resolve_image(im.group(2), base, local_images), title=cap,
                                    slide=slide_no))
            i += 1
            continue
        para.append(ln)
        i += 1
        if not ln.strip() and para and not any(x.strip() for x in para):
            para.clear()
    flush()
    keep_heading()
    t.blocks = blocks
    code = next((b for b in blocks if b.type == BLOCK_CODE), None)
    if code is not None:
        t.active_block = code.id
    return t
