"""Обновление с GitHub: проверка релизов, загрузка, установка.

Источник версий — GitHub Releases репозитория (тег vX.Y.Z). Если релизов ещё нет, берутся теги.
Папка data/ никогда не трогается.
- Программа скачана git clone → обновление через git (fetch тега + перемотка вперёд), git-история не ломается.
- Скачана архивом → архив исходников релиза распаковывается поверх; если замена сорвётся,
  старые файлы возвращаются из временной копии.

Модуль без Qt: функции блокирующие, вызываются из фонового потока (см. ui/updates.py).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import APP_NAME, __version__
from .storage import DATA_DIR, app_dir

log = logging.getLogger("autoprint.update")

REPO = "Recyavik/AUTO_PRINT_CODE"
API = f"https://api.github.com/repos/{REPO}"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
GIT_URL = f"https://github.com/{REPO}.git"

UPDATES_DIR = DATA_DIR / "updates"
BACKUP_DIR = UPDATES_DIR / "backup"
LAST_UPDATE_FILE = UPDATES_DIR / "last_update.json"

# что из архива не копируется в папку программы
SKIP_TOP = {"data", ".git", ".github", ".venv", "venv", "env", "build", "dist"}

MODE_SOURCE = "source"   # исходники, скачанные архивом — замена файлов
MODE_GIT = "git"         # git-клон — обновление через git
MODE_FROZEN = "frozen"   # собранный .exe: только ссылка на страницу релиза


class UpdateError(Exception):
    """Понятная пользователю ошибка обновления."""


class Cancelled(UpdateError):
    pass


# ---------------------------------------------------------------- версии

_VER_RE = re.compile(r"^v?(\d+(?:\.\d+)*)(?:[-.]?([a-zA-Z]+)\.?(\d*))?$")


def parse_version(s: str) -> tuple | None:
    """'v0.4.0' → ключ сравнения; бета ('0.4.0-beta.2', '0.4.0rc1') младше финальной 0.4.0."""
    m = _VER_RE.match(s.strip())
    if not m:
        return None
    nums = tuple(int(x) for x in m.group(1).split("."))
    nums = (nums + (0,) * 6)[:max(6, len(nums))]   # одна длина: 0.4.2 = 0.4.2.0, сравнение без TypeError
    pre, pre_n = (m.group(2) or "").lower(), int(m.group(3) or 0)
    return nums, ((1, "", 0) if not pre else (0, pre, pre_n))


def is_newer(candidate: str, current: str = __version__) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    return a is not None and b is not None and a > b


def install_mode() -> str:
    if getattr(sys, "frozen", False):
        return MODE_FROZEN
    if (app_dir() / ".git").exists() and shutil.which("git"):
        return MODE_GIT
    return MODE_SOURCE


# ---------------------------------------------------------------- git-клон

def _git(*args: str, timeout: float = 120) -> str:
    try:
        p = subprocess.run(["git", *args], cwd=str(app_dir()), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        raise UpdateError(f"Не удалось запустить git: {e}") from e
    if p.returncode != 0:
        log.warning("git %s: %s", " ".join(args), (p.stderr or p.stdout).strip()[-2000:])
        raise UpdateError("git: " + ((p.stderr or p.stdout).strip().splitlines() or ["ошибка"])[-1])
    return p.stdout


def _git_local_changes() -> bool:
    return bool(_git("status", "--porcelain", "--untracked-files=no").strip())


def git_stage(rel: Release) -> Path:
    """Скачивает тег релиза и проверяет его. Рабочие файлы пока не меняются."""
    ref = f"refs/tags/{rel.tag}"
    _git("fetch", "--quiet", "--no-tags", GIT_URL, f"+{ref}:{ref}", timeout=300)
    init = _git("show", f"{ref}:autoprint/__init__.py")
    m = re.search(r"""__version__\s*=\s*["']([^"']+)""", init)
    found = m.group(1) if m else ""
    if parse_version(found) != parse_version(rel.version):
        raise UpdateError(f"В релизе {rel.tag} лежит версия {found or '?'} — "
                          "автор, видимо, забыл поднять номер версии. Обновление отменено.")
    # requirements.txt новой версии — для сравнения и pip
    root = UPDATES_DIR / f"staging-{rel.version}"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    try:
        req = _git("show", f"{ref}:requirements.txt")
    except UpdateError:
        req = ""
    (root / "requirements.txt").write_text(req, encoding="utf-8")
    return root


def git_apply(rel: Release) -> None:
    """Перематывает клон вперёд до тега релиза. Свои правки и коммиты не теряются: если они мешают — ошибка."""
    if _git_local_changes():
        raise UpdateError("В папке программы изменены файлы — обновление не установлено, чтобы их не потерять. "
                          "Верните файлы как были (или сохраните свои правки) и повторите.")
    try:
        _git("merge", "--ff-only", "--quiet", f"refs/tags/{rel.tag}")
    except UpdateError as e:
        raise UpdateError("Не удалось обновиться: в папке программы есть свои изменения, "
                          "несовместимые с новой версией. Подробности — в журнале.") from e
    _write_last_update({"from": __version__, "to": rel.version, "time": time.time(), "shown": False})
    log.info("Установлено обновление через git %s → %s", __version__, rel.version)
    cleanup()


# ---------------------------------------------------------------- сеть

def _request(url: str, timeout: float = 15):
    req = urllib.request.Request(url, headers={
        "User-Agent": f"{APP_NAME}/{__version__}",
        "Accept": "application/vnd.github+json",
    })
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code == 403 and e.headers.get("X-RateLimit-Remaining") == "0":
            raise UpdateError("GitHub временно ограничил число запросов. Попробуйте через час.") from e
        if e.code == 404:
            raise UpdateError(f"Не найдено на GitHub: {url}") from e
        raise UpdateError(f"GitHub ответил ошибкой {e.code}.") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise UpdateError(f"Нет связи с GitHub ({reason}). Проверьте интернет.") from e


def _get_json(url: str):
    with _request(url) as r:
        return json.loads(r.read().decode("utf-8"))


@dataclass
class Release:
    version: str        # '0.3.8'
    tag: str            # 'v0.3.8'
    name: str
    notes: str          # описание релиза (Markdown)
    page_url: str
    zip_url: str
    published: str      # '2026-10-07'
    prerelease: bool = False


def fetch_latest(include_prerelease: bool = False) -> Release | None:
    """Самый новый релиз (или тег, если релизов нет). None — на GitHub нет ни одной версии."""
    rels = []
    for r in _get_json(f"{API}/releases?per_page=30"):
        if r.get("draft") or (r.get("prerelease") and not include_prerelease):
            continue
        tag = r.get("tag_name", "")
        if parse_version(tag) is None:
            continue
        rels.append(Release(
            version=tag.lstrip("vV"), tag=tag, name=r.get("name") or tag, notes=r.get("body") or "",
            page_url=r.get("html_url") or f"{RELEASES_PAGE}/tag/{tag}",
            zip_url=f"https://github.com/{REPO}/archive/refs/tags/{tag}.zip",
            published=(r.get("published_at") or "")[:10], prerelease=bool(r.get("prerelease"))))
    if not rels:
        for t in _get_json(f"{API}/tags?per_page=50"):
            tag = t.get("name", "")
            key = parse_version(tag)
            if key is None or (key[1][0] == 0 and not include_prerelease):   # key[1][0] == 0 — бета
                continue
            rels.append(Release(
                version=tag.lstrip("vV"), tag=tag, name=tag, notes="", page_url=f"https://github.com/{REPO}/tree/{tag}",
                zip_url=f"https://github.com/{REPO}/archive/refs/tags/{tag}.zip", published=""))
    return max(rels, key=lambda r: parse_version(r.tag), default=None)


def download(rel: Release, progress: Callable[[int, int], None] | None = None,
             cancelled: Callable[[], bool] = lambda: False) -> Path:
    """Скачивает архив релиза в data/updates/. progress(получено, всего|0)."""
    UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPDATES_DIR / f"{APP_NAME}-{rel.version}.zip"
    part = dest.with_suffix(".zip.part")
    with _request(rel.zip_url, timeout=30) as r, open(part, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while chunk := r.read(64 * 1024):
            if cancelled():
                f.close()
                part.unlink(missing_ok=True)
                raise Cancelled("Загрузка отменена.")
            f.write(chunk)
            got += len(chunk)
            if progress:
                progress(got, total)
    os.replace(part, dest)
    log.info("Скачано обновление %s: %d байт, sha256 %s", rel.version, dest.stat().st_size, _sha256(dest)[:16])
    return dest


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- подготовка

def read_version(root: Path) -> str:
    m = re.search(r"""__version__\s*=\s*["']([^"']+)""",
                  (root / "autoprint" / "__init__.py").read_text(encoding="utf-8"))
    return m.group(1) if m else ""


def stage(zip_path: Path, rel: Release) -> Path:
    """Распаковывает архив во временную папку и проверяет, что внутри нужная версия программы."""
    staging = UPDATES_DIR / f"staging-{rel.version}"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        with zipfile.ZipFile(zip_path) as z:
            if z.testzip() is not None:
                raise UpdateError("Архив обновления повреждён. Попробуйте ещё раз.")
            for name in z.namelist():   # защита от путей вида ../../
                if name.startswith(("/", "\\")) or ".." in Path(name).parts:
                    raise UpdateError("В архиве обновления недопустимые пути.")
            z.extractall(staging)
    except zipfile.BadZipFile as e:
        raise UpdateError("Скачанный файл — не архив. Попробуйте ещё раз.") from e
    # GitHub кладёт всё в одну папку «AUTO_PRINT_CODE-0.3.8/»
    tops = [p for p in staging.iterdir()]
    root = tops[0] if len(tops) == 1 and tops[0].is_dir() else staging
    if not (root / "app.py").is_file() or not (root / "autoprint" / "__init__.py").is_file():
        raise UpdateError("В архиве нет файлов программы.")
    found = read_version(root)
    if parse_version(found) != parse_version(rel.version):
        raise UpdateError(f"В релизе {rel.tag} лежит версия {found or '?'} — "
                          "автор, видимо, забыл поднять номер версии. Обновление отменено.")
    return root


def requirements_changed(root: Path) -> bool:
    def read(p: Path) -> set[str]:
        try:
            return {ln.strip() for ln in p.read_text(encoding="utf-8").splitlines()
                    if ln.strip() and not ln.lstrip().startswith("#")}
        except OSError:
            return set()
    return read(root / "requirements.txt") != read(app_dir() / "requirements.txt")


def _python_exe(gui: bool) -> str:
    exe = Path(sys.executable)
    want = "pythonw.exe" if gui else "python.exe"
    alt = exe.with_name(want)
    return str(alt if alt.exists() else exe)


def install_requirements(root: Path) -> None:
    """pip install -r requirements.txt новой версии. Без консольного окна."""
    cmd = [_python_exe(gui=False), "-m", "pip", "install", "--disable-pip-version-check",
           "-r", str(root / "requirements.txt")]
    log.info("Установка зависимостей: %s", " ".join(cmd))
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=900,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        raise UpdateError(f"Не удалось запустить pip: {e}") from e
    if p.returncode != 0:
        log.error("pip: %s", (p.stderr or p.stdout)[-3000:])
        raise UpdateError("Не удалось установить библиотеки для новой версии (подробности в журнале). "
                          "Закройте программу и выполните: pip install -r requirements.txt")


# ---------------------------------------------------------------- установка

def _files(root: Path) -> set[str]:
    out = set()
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if p.is_file() and rel.parts[0] not in SKIP_TOP and "__pycache__" not in rel.parts:
            out.add(rel.as_posix())
    return out


def apply(root: Path, new_version: str) -> None:
    """Заменяет файлы программы файлами из root. При ошибке всё возвращается как было."""
    target = app_dir()
    new = _files(root)
    # только модули программы: обходить всю папку (.git, web/node_modules) незачем
    old_code = {p.relative_to(target).as_posix() for p in (target / "autoprint").rglob("*.py")
                if "__pycache__" not in p.parts}
    replaced = {f for f in new if (target / f).is_file()}
    removed = old_code - new           # модули, которых в новой версии нет
    added = new - replaced

    shutil.rmtree(BACKUP_DIR, ignore_errors=True)
    files_dir = BACKUP_DIR / "files"
    try:
        for f in replaced | removed:
            dst = files_dir / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target / f, dst)
    except OSError as e:   # программа ещё не тронута — просто не ставим
        raise UpdateError(f"Не удалось сделать резервную копию перед обновлением ({e}). "
                          "Проверьте место на диске; программа не изменена.") from e

    try:
        for f in sorted(new):
            dst = target / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / f, dst)
        for f in removed:
            (target / f).unlink(missing_ok=True)
    except OSError as e:
        log.exception("Ошибка установки, возвращаем старые файлы")
        _restore(added)
        raise UpdateError(f"Не удалось заменить файлы программы ({e}). Всё возвращено как было.") from e

    _write_last_update({"from": __version__, "to": new_version, "time": time.time(), "shown": False})
    log.info("Установлено обновление %s → %s: заменено %d, добавлено %d, удалено %d",
             __version__, new_version, len(replaced), len(added), len(removed))
    cleanup()


def _restore(added: set[str]) -> None:
    target = app_dir()
    for f in added:
        (target / f).unlink(missing_ok=True)
    files_dir = BACKUP_DIR / "files"
    for p in files_dir.rglob("*"):
        if p.is_file():
            dst = target / p.relative_to(files_dir)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)


def cleanup() -> None:
    """Удаляет скачанные архивы, распакованные папки и временную копию старых файлов."""
    if not UPDATES_DIR.is_dir():
        return
    for p in UPDATES_DIR.iterdir():
        if p.name.startswith("staging-"):
            shutil.rmtree(p, ignore_errors=True)
        elif p.suffix in (".zip", ".part"):
            p.unlink(missing_ok=True)
        elif p == BACKUP_DIR:
            shutil.rmtree(p, ignore_errors=True)


def _write_last_update(d: dict) -> None:
    UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    LAST_UPDATE_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def pop_last_update() -> dict | None:
    """Сведения о только что прошедшем обновлении (один раз после перезапуска)."""
    try:
        d = json.loads(LAST_UPDATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if d.get("shown"):
        return None
    d["shown"] = True
    _write_last_update(d)
    return d


def relaunch() -> None:
    """Запускает программу заново (вызывать после выхода из цикла событий и снятия блокировки)."""
    if getattr(sys, "frozen", False):
        cmd = [sys.executable]
    else:
        cmd = [_python_exe(gui=True), str(app_dir() / "app.py")]
    cmd.append("--updated")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    log.info("Перезапуск: %s", cmd)
    subprocess.Popen(cmd, cwd=str(app_dir()), creationflags=flags, close_fds=True)
