"""Урок одним файлом (.autoprint): уроки, их планы, оформление экрана учеников с видео зарядок — и все картинки
внутри. Отдал человеку один файл — он открыл его в «Импорт…», и у него всё как у вас.

Внутри — обычный zip (можно переименовать в .zip и открыть):
    manifest.json                — что это и что внутри
    lessons/<id>.json, plans/<id>.json   — уроки и планы в формате программы (картинки — «media/<файл>»)
    looks/<id>.json              — оформления экрана учеников (файлы — «looks_media/<файл>»)
    media/…, looks_media/…       — картинки уроков; фон, заставка перерыва, видео зарядок, шрифт
    <название урока>.md          — тот же урок для людей: открывается в любом редакторе, картинки — из media/

Архив без manifest.json (например, от нейросети: урок .md и картинки рядом) тоже читается — как урок .md, но
картинки берутся только из самого архива: ни файлов с компьютера, ни путей «наружу».
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

from . import __version__, storage
from .storage import BLOCK_IMAGE, BLOCK_STAGE, KIND_PLAN, Template, _template_from, new_id

EXT = ".autoprint"
FORMAT = "autoprintcode-package"
MAX_FILES = 5000
# уже сжатое (картинки, видео, звук, шрифты) кладётся как есть: пережимать — долго и без толку
STORED = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v",
          ".mp3", ".m4a", ".ogg", ".opus", ".aac", ".woff", ".woff2", ".zip", ".7z", ".rar", ".gz"}


class Cancelled(Exception):
    """Запись файла отменили (progress бросил это) — недописанный файл удалён."""


@dataclass
class Package:
    lessons: list[Template] = field(default_factory=list)
    plans: list[Template] = field(default_factory=list)
    looks: list = field(default_factory=list)        # efir.model.Look
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- запись

def _safe_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip(" .") or "file"


class _Files:
    """Файлы в архиве: одно имя на один исходный файл, без совпадений."""

    def __init__(self, z: zipfile.ZipFile, folder: str, done=None) -> None:
        self.z, self.folder, self.by_src, self.used, self.bytes = z, folder, {}, set(), 0
        self.done = done                         # done(байт) — после каждого файла (ход записи)

    def add(self, src: Path) -> str:
        key = str(src.resolve())
        if key in self.by_src:
            return self.by_src[key]
        base = _safe_name(src.name)
        name, n = base, 1
        while name.lower() in self.used:
            n += 1
            name = f"{Path(base).stem}-{n}{Path(base).suffix}"
        self.used.add(name.lower())
        arc = f"{self.folder}/{name}"
        kind = zipfile.ZIP_STORED if src.suffix.lower() in STORED else zipfile.ZIP_DEFLATED
        self.z.write(src, arc, compress_type=kind)
        size = src.stat().st_size
        self.bytes += size
        self.by_src[key] = arc
        if self.done is not None:
            self.done(size)
        return arc


def look_files(look) -> list[Path]:
    """Файлы оформления, которые есть на этом компьютере: фон, заставка перерыва, видео зарядок, шрифт."""
    out = []
    for spec in (look.background, look.break_background):
        if spec.startswith("image:") and Path(spec[6:]).is_file():
            out.append(Path(spec[6:]))
    out += [Path(e.path) for e in look.exercises if e.path and Path(e.path).is_file()]
    if look.font.startswith("file:") and Path(look.font[5:]).is_file():
        out.append(Path(look.font[5:]))
    return out


def lesson_files(t: Template) -> list[Path]:
    return [p for b in t.blocks if b.type == BLOCK_IMAGE and (p := storage.media_path(b.text)) is not None and p.is_file()]


def _sizes(lessons, plans, looks, media: bool) -> int:
    files = {p.resolve() for t in (list(lessons) + list(plans)) for p in lesson_files(t)} if media else set()
    files |= {p.resolve() for lk in looks for p in look_files(lk)}
    return sum(p.stat().st_size for p in files if p.is_file())


def export_package(path, lessons=(), plans=(), looks=(), media: bool = True, progress=None) -> dict:
    """Записать файл .autoprint. → {"lessons", "plans", "looks", "files", "bytes"}.

    media=False — без картинок уроков: места картинок остаются пустыми (у слайда — его номер), их потом подставят.
    progress(записано, всего) — в байтах файлов, после каждого файла; бросил Cancelled — запись брошена, файла нет."""
    from .lesson_md import to_md
    path = Path(path)
    tmp = path.with_name(path.name + ".part")
    total = _sizes(lessons, plans, looks, media)
    state = {"done": 0}

    def done(n: int) -> None:
        state["done"] += n
        if progress is not None:
            progress(state["done"], total)

    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
            files, lmedia = _Files(z, "media", done), _Files(z, "looks_media", done)
            manifest = {"format": FORMAT, "version": 1, "app": __version__, "lessons": [], "plans": [], "looks": []}
            md_names: set[str] = set()
            for folder, items, key in (("plans", plans, "plans"), ("lessons", lessons, "lessons")):
                for t in items:
                    d = asdict(t)
                    arcs: dict[str, str] = {}
                    for b, bd in zip(t.blocks, d["blocks"]):
                        if b.type != BLOCK_IMAGE:
                            continue
                        if not media:
                            bd["text"] = ""              # место картинки остаётся: название и номер слайда — в уроке
                            continue
                        p = storage.media_path(b.text)
                        if p is not None and p.is_file():
                            arcs[b.id] = bd["text"] = files.add(p)
                    z.writestr(f"{folder}/{t.id}.json", json.dumps(d, ensure_ascii=False, indent=1))
                    manifest[key].append(t.id)
                    name = _safe_name(t.title) + ".md"
                    while name.lower() in md_names:
                        name = Path(name).stem + "-2.md"
                    md_names.add(name.lower())
                    md_t = t if media else _template_from(d)     # без картинок — и в .md места, а не пути
                    z.writestr(name, to_md(md_t, "media", copy_image=lambda b, a=arcs: a.get(b.id)))
            for look in looks:
                d = look.to_dict()
                for k in ("background", "break_background"):
                    if d[k].startswith("image:") and Path(d[k][6:]).is_file():
                        d[k] = "image:" + lmedia.add(Path(d[k][6:]))
                for e in d["exercises"]:
                    if e.get("path") and Path(e["path"]).is_file():
                        e["path"] = lmedia.add(Path(e["path"]))
                if d["font"].startswith("file:") and Path(d["font"][5:]).is_file():
                    d["font"] = "file:" + lmedia.add(Path(d["font"][5:]))
                z.writestr(f"looks/{look.id}.json", json.dumps(d, ensure_ascii=False, indent=1))
                manifest["looks"].append(look.id)
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
        if progress is not None:
            progress(total, total)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)            # отменили или не записалось — недописанного файла не оставляем
        raise
    return {"lessons": len(lessons), "plans": len(plans), "looks": len(looks),
            "files": len(files.by_src) + len(lmedia.by_src), "bytes": files.bytes + lmedia.bytes}


# ---------------------------------------------------------------- чтение

def _check_names(z: zipfile.ZipFile) -> None:
    names = z.namelist()
    if len(names) > MAX_FILES:
        raise ValueError("В архиве слишком много файлов")
    for n in names:
        p = PurePosixPath(n.replace("\\", "/"))
        if p.is_absolute() or ".." in p.parts or re.match(r"^[A-Za-z]:", n):
            raise ValueError(f"В архиве недопустимый путь: {n}")


def _extract(z: zipfile.ZipFile, arc: str, out_dir: Path) -> Path | None:
    try:
        info = z.getinfo(arc)
    except KeyError:
        return None
    dst = out_dir / _safe_name(PurePosixPath(arc).name)
    n = 1
    while dst.exists():
        n += 1
        dst = out_dir / f"{Path(_safe_name(PurePosixPath(arc).name)).stem}-{n}{PurePosixPath(arc).suffix}"
    with z.open(info) as src, open(dst, "wb") as f:
        shutil.copyfileobj(src, f)
    return dst


def read_package(path, look_media_dir: Path | None = None) -> Package:
    """Прочитать .autoprint (или .zip). Картинки уроков — в data/media, файлы оформлений — в look_media_dir
    (по умолчанию data/efir/media). Уроки и планы — со своими id; связь урока с планом сохраняется."""
    path = Path(path)
    look_media_dir = Path(look_media_dir or storage.DATA_DIR / "efir" / "media")
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        raise ValueError(f"{path.name}: это не файл урока AutoPrint и не zip-архив") from e
    with z:
        _check_names(z)
        names = set(z.namelist())
        if "manifest.json" not in names:
            return _read_plain_zip(z, path)
        manifest = json.loads(z.read("manifest.json").decode("utf-8-sig"))
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
            raise ValueError(f"{path.name}: незнакомый формат файла")
        pkg = Package()
        with tempfile.TemporaryDirectory() as tmp:
            tmpd = Path(tmp)

            def media_ref(arc: str) -> str:
                f = _extract(z, arc, tmpd) if arc in names else None
                return storage.import_media(f) if f is not None else ""

            stage_map: dict[str, str] = {}
            plan_map: dict[str, str] = {}
            for folder, key in (("plans", "plans"), ("lessons", "lessons")):
                for tid in manifest.get(key, []):
                    arc = f"{folder}/{tid}.json"
                    if arc not in names:
                        continue
                    t = _template_from(json.loads(z.read(arc).decode("utf-8-sig")))
                    old_id = t.id
                    t.id = new_id()
                    for b in t.blocks:
                        old_b = b.id
                        b.id = new_id()
                        if t.kind == KIND_PLAN and b.type == BLOCK_STAGE:
                            stage_map[old_b] = b.id
                        if b.type == BLOCK_IMAGE and b.text.startswith("media/"):
                            b.text = media_ref(b.text)
                    t.active_block = ""
                    if t.kind == KIND_PLAN:
                        plan_map[old_id] = t.id
                        pkg.plans.append(t)
                    else:
                        if t.plan_id in plan_map:
                            t.plan_id = plan_map[t.plan_id]
                            for b in t.blocks:
                                b.link = stage_map.get(b.link, "") if b.link else ""
                        else:
                            storage.without_plan(t)       # план не в файле — урок обычный
                        pkg.lessons.append(t)
            from .efir.model import look_from_dict
            look_media_dir.mkdir(parents=True, exist_ok=True)
            for lid in manifest.get("looks", []):
                arc = f"looks/{lid}.json"
                if arc not in names:
                    continue
                d = json.loads(z.read(arc).decode("utf-8-sig"))

                def place(a: str) -> str:
                    f = _extract(z, a, look_media_dir) if a in names else None
                    return str(f) if f is not None else ""
                for k in ("background", "break_background"):
                    v = str(d.get(k) or "")
                    if v.startswith("image:looks_media/"):
                        f = place(v[6:])
                        d[k] = "image:" + f if f else ""
                for e in d.get("exercises") or []:
                    if isinstance(e, dict) and str(e.get("path") or "").startswith("looks_media/"):
                        e["path"] = place(e["path"])
                v = str(d.get("font") or "")
                if v.startswith("file:looks_media/"):
                    d["font"] = "file:" + place(v[5:])
                pkg.looks.append(look_from_dict(d))
        return pkg


def _read_plain_zip(z: zipfile.ZipFile, path: Path) -> Package:
    """Архив без manifest.json — урок .md и картинки рядом (так может прислать нейросеть)."""
    from . import lesson_md
    mds = [n for n in z.namelist() if n.lower().endswith(".md")]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        z.extractall(root)                              # имена уже проверены (_check_names)
        for n in mds:
            text = (root / n).read_text(encoding="utf-8-sig")
            if lesson_md.looks_like_lesson(text):
                t = lesson_md.parse(text, (root / n).parent, Path(n).stem, root=root)
                return Package(lessons=[t])
    raise ValueError(f"{path.name}: в архиве нет урока (.md с этапами или подсказками)")
