"""Обновление с GitHub: проверка релизов, загрузка, установка.

Источник версий — GitHub Releases репозитория (тег vX.Y.Z). Если релизов ещё нет, берутся теги.
Папка data/ никогда не трогается.
- Программа скачана git clone → обновление через git (fetch тега + перемотка вперёд), git-история не ломается.
- Скачана архивом → архив исходников релиза распаковывается поверх; если замена сорвётся,
  старые файлы возвращаются из временной копии.
- Собранный AutoPrintCode.exe → из релиза скачивается сборка AutoPrintCode-X.Y.Z-win64.zip, сверяется
  с AutoPrintCode-X.Y.Z-win64.zip.sha256 и распаковывается в data/updates. Работающий .exe и его библиотеки
  заблокированы, поэтому файлы заменяет вспомогательный скрипт %TEMP%\\AutoPrintCode-update.cmd: он ждёт
  выхода программы, откладывает старые файлы, копирует новые (data\\ не трогает), при ошибке возвращает
  старые и запускает программу снова. Журнал скрипта — data/updates/apply.log.
  Если в релизе нет сборки, остаётся только ссылка на страницу релиза.
- Собранная программа, установленная в Program Files (для всех пользователей), свою папку менять не может:
  из релиза скачивается установщик AutoPrintCode-X.Y.Z-Setup.exe, сверяется с .sha256 и после выхода
  запускается с запросом прав администратора (/SILENT /RELAUNCH=1 — поставит и запустит программу снова).

Модуль без Qt: функции блокирующие, вызываются из фонового потока (см. ui/updates.py).
"""
from __future__ import annotations

import atexit
import hashlib
import http.client
import json
import logging
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import APP_NAME, __version__
from .storage import DATA_DIR, _in_program_files, app_dir

log = logging.getLogger("autoprint.update")

# Виктор (Recyavik) ушёл из проекта — обновления только из этого репозитория, его версии не подтягиваются
REPO = "DanT2000/AUTO_PRINT_CODE"
API = f"https://api.github.com/repos/{REPO}"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
GIT_URL = f"https://github.com/{REPO}.git"

UPDATES_DIR = DATA_DIR / "updates"
BACKUP_DIR = UPDATES_DIR / "backup"
LAST_UPDATE_FILE = UPDATES_DIR / "last_update.json"
APPLY_LOG = UPDATES_DIR / "apply.log"          # журнал скрипта, который ставит сборку .exe

# что из архива не копируется в папку программы
SKIP_TOP = {"data", ".git", ".github", ".venv", "venv", "env", "build", "dist"}

MODE_SOURCE = "source"   # исходники, скачанные архивом — замена файлов
MODE_GIT = "git"         # git-клон — обновление через git
MODE_FROZEN = "frozen"   # собранный .exe — сборка из релиза, файлы заменяет скрипт после выхода

# собранная программа (PyInstaller, onedir): AutoPrintCode.exe + папка библиотек _internal
EXE_NAME = f"{APP_NAME}.exe"
INTERNAL_DIR = "_internal"
WINDOW_DIR = "window"                       # с 1.2: окно программы (Electron) — window\AutoPrintCodeWindow.exe
WINDOW_EXE = "AutoPrintCodeWindow.exe"
HELPER_NAME = f"{APP_NAME}-update.cmd"
PID_WAIT_S = 30          # сколько скрипт ждёт выхода программы
_EXE_ZIP_RE = re.compile(rf"^{re.escape(APP_NAME)}-(.+)-win64\.zip$", re.IGNORECASE)
# запись установщика (installer/AutoPrintCode.iss, AppId) в «Приложениях» Windows — у установки для пользователя
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{BC0222C7-A45D-4D77-A7C6-1EB7F2C4FB28}_is1"

NO_BUILD_TEXT = "В этом выпуске нет готовой сборки для Windows — скачайте новую версию со страницы релиза."
NO_SETUP_TEXT = "В этом выпуске нет установщика — скачайте новую версию со страницы релиза."
NO_SHA_TEXT = ("В выпуске нет файла контрольной суммы (.sha256), поэтому установить его автоматически "
               "нельзя — скачайте новую версию со страницы релиза.")


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

def _request(url: str, timeout: float = 15, accept: str = "application/vnd.github+json"):
    req = urllib.request.Request(url, headers={
        "User-Agent": f"{APP_NAME}/{__version__}",
        "Accept": accept,
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
class Asset:
    """Файл, приложенный к релизу на GitHub."""
    name: str
    url: str            # browser_download_url
    size: int = 0


def exe_asset_name(version: str) -> str:
    """Имя архива сборки для Windows в релизе: AutoPrintCode-0.5.0-win64.zip (рядом — тот же + .sha256)."""
    return f"{APP_NAME}-{version}-win64.zip"


@dataclass
class Release:
    version: str        # '0.3.8'
    tag: str            # 'v0.3.8'
    name: str
    notes: str          # описание релиза (Markdown)
    page_url: str
    zip_url: str        # архив исходников
    published: str      # '2026-10-07'
    prerelease: bool = False
    assets: list[Asset] = field(default_factory=list)   # приложенные файлы (сборка .exe и т.п.)

    def asset(self, name: str) -> Asset | None:
        low = name.lower()
        return next((a for a in self.assets if a.name.lower() == low), None)

    @property
    def exe_zip(self) -> Asset | None:
        """Архив сборки для Windows. Если имя не совпало с версией из тега (v0.5 и 0.5.0) —
        единственный архив вида AutoPrintCode-*-win64.zip."""
        a = self.asset(exe_asset_name(self.version))
        if a is None:
            found = [x for x in self.assets if _EXE_ZIP_RE.match(x.name)]
            a = found[0] if len(found) == 1 else None
        return a

    @property
    def exe_sha(self) -> Asset | None:
        """Контрольная сумма архива сборки: <архив>.sha256."""
        z = self.exe_zip
        return self.asset(z.name + ".sha256") if z else None

    @property
    def setup_exe(self) -> Asset | None:
        """Установщик (необязателен): AutoPrintCode-0.5.0-Setup.exe."""
        return self.asset(f"{APP_NAME}-{self.version}-Setup.exe")

    @property
    def setup_sha(self) -> Asset | None:
        """Контрольная сумма установщика: <установщик>.sha256."""
        z = self.setup_exe
        return self.asset(z.name + ".sha256") if z else None


def _assets(r: dict) -> list[Asset]:
    out = []
    for a in r.get("assets") or ():
        if not isinstance(a, dict):
            continue
        name, url = str(a.get("name") or ""), str(a.get("browser_download_url") or "")
        if not name or not url.startswith("https://"):
            continue
        try:
            size = int(a.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        out.append(Asset(name=name, url=url, size=size))
    return out


def parse_releases(data, include_prerelease: bool = False) -> list[Release]:
    """Релизы из ответа GitHub API /releases. Черновики, неподходящие теги и (без флага) бета пропускаются."""
    rels = []
    for r in data or ():
        if not isinstance(r, dict) or r.get("draft") or (r.get("prerelease") and not include_prerelease):
            continue
        tag = str(r.get("tag_name") or "")
        if parse_version(tag) is None:
            continue
        rels.append(Release(
            version=tag.lstrip("vV"), tag=tag, name=r.get("name") or tag, notes=r.get("body") or "",
            page_url=r.get("html_url") or f"{RELEASES_PAGE}/tag/{tag}",
            zip_url=f"https://github.com/{REPO}/archive/refs/tags/{tag}.zip",
            published=(r.get("published_at") or "")[:10], prerelease=bool(r.get("prerelease")),
            assets=_assets(r)))
    return rels


def newest(rels: list[Release]) -> Release | None:
    return max(rels, key=lambda r: parse_version(r.tag), default=None)


def fetch_latest(include_prerelease: bool = False) -> Release | None:
    """Самый новый релиз (или тег, если релизов нет). None — на GitHub нет ни одной версии."""
    rels = parse_releases(_get_json(f"{API}/releases?per_page=30"), include_prerelease)
    if not rels:
        for t in _get_json(f"{API}/tags?per_page=50"):
            tag = t.get("name", "")
            key = parse_version(tag)
            if key is None or (key[1][0] == 0 and not include_prerelease):   # key[1][0] == 0 — бета
                continue
            rels.append(Release(
                version=tag.lstrip("vV"), tag=tag, name=tag, notes="", page_url=f"https://github.com/{REPO}/tree/{tag}",
                zip_url=f"https://github.com/{REPO}/archive/refs/tags/{tag}.zip", published=""))
    return newest(rels)


def _fetch(url: str, dest: Path, progress: Callable[[int, int], None] | None,
           cancelled: Callable[[], bool], accept: str = "application/vnd.github+json", size: int = 0) -> Path:
    """Скачивает url в dest через временный .part. progress(получено, всего|0)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    got = 0
    with _request(url, timeout=30, accept=accept) as r, open(part, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0) or size
        try:
            while chunk := r.read(64 * 1024):
                if cancelled():
                    f.close()
                    part.unlink(missing_ok=True)
                    raise Cancelled("Загрузка отменена.")
                f.write(chunk)
                got += len(chunk)
                if progress:
                    progress(got, total)
        except (OSError, http.client.HTTPException) as e:
            raise UpdateError(f"Загрузка прервалась ({e}). Проверьте интернет и попробуйте ещё раз.") from e
    if size and got != size:
        part.unlink(missing_ok=True)
        raise UpdateError("Файл обновления скачался не полностью. Попробуйте ещё раз.")
    os.replace(part, dest)
    return dest


def download(rel: Release, progress: Callable[[int, int], None] | None = None,
             cancelled: Callable[[], bool] = lambda: False) -> Path:
    """Скачивает архив исходников релиза в data/updates/. progress(получено, всего|0)."""
    dest = _fetch(rel.zip_url, UPDATES_DIR / f"{APP_NAME}-{rel.version}.zip", progress, cancelled)
    log.info("Скачано обновление %s: %d байт, sha256 %s", rel.version, dest.stat().st_size, _sha256(dest)[:16])
    return dest


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_SHA_RE = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])")


def parse_sha256(text: str) -> str | None:
    """Хеш из файла .sha256 (формат sha256sum: «<64 hex>  <имя файла>»). None — хеша в тексте нет."""
    m = _SHA_RE.search(text or "")
    return m.group(0).lower() if m else None


def verify_sha256(path: Path, expected: str | None) -> None:
    """Сверяет SHA-256 файла. Не совпало — файл удаляется, UpdateError."""
    if not expected:
        raise UpdateError(NO_SHA_TEXT)
    actual = _sha256(path)
    if actual != expected.strip().lower():
        log.error("SHA-256 не совпал: %s — %s, в релизе %s", path.name, actual, expected)
        path.unlink(missing_ok=True)
        raise UpdateError("Контрольная сумма скачанного архива не совпала с указанной в релизе — файл повреждён "
                          "или подменён. Обновление отменено, попробуйте позже.")


def download_exe(rel: Release, progress: Callable[[int, int], None] | None = None,
                 cancelled: Callable[[], bool] = lambda: False) -> Path:
    """Скачивает сборку для Windows (AutoPrintCode-X.Y.Z-win64.zip) и сверяет её SHA-256 с файлом .sha256
    из того же релиза. Без .sha256 не скачивает вовсе."""
    reason = release_block_reason(rel)
    if reason:
        raise UpdateError(reason)
    z, sha = (rel.setup_exe, rel.setup_sha) if via_installer() else (rel.exe_zip, rel.exe_sha)
    with _request(sha.url, accept="application/octet-stream") as r:
        expected = parse_sha256(r.read(4096).decode("utf-8", "replace"))
    if not expected:
        raise UpdateError("Файл контрольной суммы в релизе испорчен — обновление отменено. "
                          "Скачайте новую версию со страницы релиза.")
    dest = _fetch(z.url, UPDATES_DIR / Path(z.name).name, progress, cancelled,
                  accept="application/octet-stream", size=z.size)
    verify_sha256(dest, expected)
    log.info("Скачана сборка %s: %d байт, sha256 совпал (%s…)", rel.version, dest.stat().st_size, expected[:16])
    return dest


# ---------------------------------------------------------------- подготовка

def read_version(root: Path) -> str:
    m = re.search(r"""__version__\s*=\s*["']([^"']+)""",
                  (root / "autoprint" / "__init__.py").read_text(encoding="utf-8"))
    return m.group(1) if m else ""


def _extract(zip_path: Path, staging: Path, test: bool = True) -> Path:
    """Распаковывает архив в staging. Возвращает корень: единственную папку внутри архива или сам staging."""
    shutil.rmtree(staging, ignore_errors=True)
    try:
        with zipfile.ZipFile(zip_path) as z:
            if test and z.testzip() is not None:
                raise UpdateError("Архив обновления повреждён. Попробуйте ещё раз.")
            for name in z.namelist():   # защита от путей вида ../../
                if name.startswith(("/", "\\")) or ".." in Path(name).parts:
                    raise UpdateError("В архиве обновления недопустимые пути.")
            z.extractall(staging)
    except zipfile.BadZipFile as e:
        raise UpdateError("Скачанный файл — не архив. Попробуйте ещё раз.") from e
    # GitHub кладёт всё в одну папку «AUTO_PRINT_CODE-0.3.8/», сборка — в «AutoPrintCode/»
    tops = list(staging.iterdir()) if staging.is_dir() else []
    return tops[0] if len(tops) == 1 and tops[0].is_dir() else staging


def stage(zip_path: Path, rel: Release) -> Path:
    """Распаковывает архив во временную папку и проверяет, что внутри нужная версия программы."""
    root = _extract(zip_path, UPDATES_DIR / f"staging-{rel.version}")
    if not (root / "app.py").is_file() or not (root / "autoprint" / "__init__.py").is_file():
        raise UpdateError("В архиве нет файлов программы.")
    found = read_version(root)
    if parse_version(found) != parse_version(rel.version):
        raise UpdateError(f"В релизе {rel.tag} лежит версия {found or '?'} — "
                          "автор, видимо, забыл поднять номер версии. Обновление отменено.")
    return root


def exe_version(path: Path) -> str:
    """Версия из ресурса версии .exe: ProductVersion, иначе FileVersion. '' — ресурса нет."""
    if sys.platform != "win32":
        return ""
    import ctypes
    from ctypes import wintypes
    try:
        ver = ctypes.WinDLL("version")
    except OSError:
        return ""
    ver.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    ver.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    ver.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    ver.GetFileVersionInfoW.restype = wintypes.BOOL
    ver.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
                                   ctypes.POINTER(wintypes.UINT)]
    ver.VerQueryValueW.restype = wintypes.BOOL
    size = ver.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return ""
    buf = ctypes.create_string_buffer(size)
    if not ver.GetFileVersionInfoW(str(path), 0, size, buf):
        return ""
    ptr, n = ctypes.c_void_p(), wintypes.UINT()
    if ver.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(n)) and n.value >= 4:
        lang, cp = struct.unpack("<HH", ctypes.string_at(ptr.value, 4))
        key = f"\\StringFileInfo\\{lang:04x}{cp:04x}\\ProductVersion"
        if ver.VerQueryValueW(buf, key, ctypes.byref(ptr), ctypes.byref(n)) and n.value:
            s = ctypes.wstring_at(ptr.value, n.value).split("\0", 1)[0].strip()
            if s:
                return s
    if ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(n)) and n.value >= 16:
        ms, ls = struct.unpack("<II", ctypes.string_at(ptr.value + 8, 8))   # VS_FIXEDFILEINFO.dwFileVersion*
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    return ""


def stage_exe(zip_path: Path, rel: Release) -> Path:
    """Распаковывает сборку во временную папку и проверяет: есть AutoPrintCode.exe и _internal, версия та.
    Установщик (…-Setup.exe) не распаковывается — только сверяется его версия."""
    if zip_path.suffix.lower() == ".exe":
        found = exe_version(zip_path)
        key, want = parse_version(found) if found else None, parse_version(rel.version)
        if key is not None and want is not None and key[:3] != want[:3]:
            raise UpdateError(f"В релизе {rel.tag} лежит установщик версии {found} — обновление отменено.")
        return zip_path
    # целостность уже проверена по SHA-256, повторно читать весь архив (testzip) незачем
    root = _extract(zip_path, UPDATES_DIR / f"staging-{rel.version}", test=False)
    if not (root / EXE_NAME).is_file() or not (root / INTERNAL_DIR).is_dir():
        raise UpdateError(f"В архиве нет файлов программы ({EXE_NAME} и папки {INTERNAL_DIR}).")
    ver = parse_version(rel.version)
    if ver is not None and ver[0][:3] >= (1, 2, 0) and not (root / WINDOW_DIR / WINDOW_EXE).is_file():
        raise UpdateError(f"В архиве нет окна программы ({WINDOW_DIR}\\{WINDOW_EXE}) — обновление отменено.")
    found = exe_version(root / EXE_NAME)
    key, want = parse_version(found) if found else None, parse_version(rel.version)
    if key is not None and want is not None and key[:3] != want[:3]:
        raise UpdateError(f"В релизе {rel.tag} лежит сборка версии {found} — "
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


# ---------------------------------------------------------------- собранная программа (.exe)

def _dir_writable(d: Path) -> bool:
    probe = d / f".{APP_NAME}-write-test-{os.getpid()}"
    try:
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def _installed_for_all_users() -> bool:
    """Программа поставлена установщиком для всех пользователей (запись в HKLM указывает на эту папку)."""
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY, 0,
                            winreg.KEY_QUERY_VALUE | winreg.KEY_WOW64_64KEY) as k:
            where, _t = winreg.QueryValueEx(k, "InstallLocation")
    except OSError:
        return False
    return os.path.normcase(os.path.normpath(str(where))) == os.path.normcase(str(app_dir()))


def via_installer() -> bool:
    """Обновлять установщиком (с правами администратора): сборка в Program Files, файлы менять самой нельзя."""
    if not getattr(sys, "frozen", False):
        return False
    d = app_dir()
    return (_in_program_files(d) or not _dir_writable(d)) and _installed_for_all_users()


def frozen_layout_reason() -> str | None:
    """Почему собранная программа не может заменить свои файлы сама (None — может)."""
    d = app_dir()
    if Path(sys.executable).name.lower() != EXE_NAME.lower() or not (d / INTERNAL_DIR).is_dir():
        return "Эта сборка программы не умеет обновляться сама — скачайте новую версию со страницы релиза."
    if not _dir_writable(d) and not via_installer():
        return ("Нет прав на запись в папку программы — скачайте новую версию со страницы релиза "
                "и установите её.")
    return None


def release_block_reason(rel: Release) -> str | None:
    """Почему этот релиз нельзя поставить в собранную программу автоматически (None — можно)."""
    if via_installer():
        if rel.setup_exe is None:
            return NO_SETUP_TEXT
        if rel.setup_sha is None:
            return NO_SHA_TEXT
        return None
    if rel.exe_zip is None:
        return NO_BUILD_TEXT
    if rel.exe_sha is None:
        return NO_SHA_TEXT
    return None


def frozen_block_reason(rel: Release | None = None) -> str | None:
    """Почему собранная программа не может сама поставить rel (None — может)."""
    return frozen_layout_reason() or (release_block_reason(rel) if rel is not None else None)


def can_self_update() -> bool:
    """Умеет ли эта установка обновляться сама. Git-клон и исходники — да; собранный .exe — если это сборка
    AutoPrintCode.exe + _internal и в её папку можно писать (а в релизе будет сборка с .sha256)."""
    if install_mode() != MODE_FROZEN:
        return True
    return frozen_layout_reason() is None


_HELPER = r"""@echo off
"%SystemRoot%\System32\chcp.com" 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
rem {app_name}: установка обновления {old} → {new}. Скрипт создан программой и удаляет себя сам.
rem Ждёт выхода программы, откладывает старые файлы, копирует новые (папку data не трогает),
rem при ошибке возвращает прежнюю версию. Аргумент restart — потом запустить программу.
set "PID={pid}"
set "APP={app}"
set "EXE={exe}"
set "SRC={src}"
set "BAK={bak}"
set "LOG={log}"
set "WAIT={wait}"
set "RETRIES={retries}"
set "OLDNAME={internal}.old"
set "WOLD={window}.old"
set "SYS=%SystemRoot%\System32"
set "MODE=%~1"
set "OK="
call :log "=== Обновление {old} → {new}, режим %MODE%: ждём выхода программы (PID %PID%)"

set /a N=0
:wait
"%SYS%\tasklist.exe" /FI "PID eq %PID%" /NH 2>nul | "%SYS%\find.exe" " %PID% " >nul || goto closed
set /a N+=1
if %N% geq %WAIT% goto timeout
"%SYS%\PING.EXE" -n 2 127.0.0.1 >nul
goto wait

:timeout
call :log "Программа не закрылась за %WAIT% с — обновление не установлено"
goto done

:closed
rem копия файлов из корня папки программы, которые заменит обновление
if exist "%BAK%" rmdir /s /q "%BAK%"
mkdir "%BAK%" 2>nul
if not exist "%BAK%" (call :log "Не удалось создать папку для копии — обновление отменено" & goto finish)
set "ERR="
for %%F in ("%SRC%\*") do if exist "%APP%\%%~nxF" copy /y "%APP%\%%~nxF" "%BAK%\" >nul || set "ERR=1"
if defined ERR (call :log "Не удалось сохранить копию файлов программы — обновление отменено" & goto finish)

rem старые библиотеки — в сторону; переименование ждёт, пока система отпустит файлы
if exist "%APP%\%OLDNAME%" rmdir /s /q "%APP%\%OLDNAME%"
if exist "%APP%\%OLDNAME%" set "OLDNAME=%OLDNAME%-%RANDOM%"
set /a N=0
:rename
ren "%APP%\{internal}" "%OLDNAME%" 2>nul && goto renamed
set /a N+=1
if %N% geq 15 (call :log "Папка {internal} занята — обновление отменено" & goto finish)
"%SYS%\PING.EXE" -n 2 127.0.0.1 >nul
goto rename

:renamed
rem окно программы (с 1.2) — тоже в сторону: при ошибке вернётся целиком, а не наполовину новым
if not exist "%APP%\{window}" goto wrenamed
if exist "%APP%\%WOLD%" rmdir /s /q "%APP%\%WOLD%"
if exist "%APP%\%WOLD%" set "WOLD=%WOLD%-%RANDOM%"
set /a N=0
:wrename
ren "%APP%\{window}" "%WOLD%" 2>nul && goto wrenamed
set /a N+=1
if %N% geq 15 (call :log "Папка {window} занята — обновление отменено" & goto restore)
"%SYS%\PING.EXE" -n 2 127.0.0.1 >nul
goto wrename

:wrenamed
call :log "Прежние библиотеки отложены в %OLDNAME%, копируем новые файлы"
"%SYS%\Robocopy.exe" "%SRC%" "%APP%" /E /XD "%SRC%\data" /R:%RETRIES% /W:1 /NP /NDL /NFL /NJH >>"%LOG%" 2>&1
if errorlevel 8 (call :log "Ошибка копирования (robocopy %ERRORLEVEL%) — возвращаем прежнюю версию" & goto restore)
call :log "Готово: установлена версия {new}"
set "OK=1"
goto finish

:restore
if exist "%APP%\{internal}" rmdir /s /q "%APP%\{internal}"
ren "%APP%\%OLDNAME%" "{internal}" || call :log "ОШИБКА: не удалось вернуть папку {internal} из %OLDNAME%"
if not exist "%APP%\%WOLD%" goto restore_files
if exist "%APP%\{window}" rmdir /s /q "%APP%\{window}"
ren "%APP%\%WOLD%" "{window}" || call :log "ОШИБКА: не удалось вернуть папку {window} из %WOLD%"
:restore_files
"%SYS%\Robocopy.exe" "%BAK%" "%APP%" /R:%RETRIES% /W:1 /NP /NDL /NFL /NJH >>"%LOG%" 2>&1
if errorlevel 8 (call :log "ОШИБКА: не удалось вернуть файлы из копии") else call :log "Прежняя версия возвращена"
goto finish

:finish
if /i "%MODE%"=="restart" (
  call :log "Запуск программы"
  start "" /d "%APP%" "%APP%\%EXE%" --updated
)
if defined OK (
  rmdir /s /q "%APP%\%OLDNAME%" 2>nul
  rmdir /s /q "%APP%\%WOLD%" 2>nul
  rmdir /s /q "%BAK%" 2>nul
)

:done
call :log "Скрипт обновления завершён"
(goto) 2>nul & del "%~f0"
exit /b 0

:log
set "MSG=%~1"
setlocal EnableDelayedExpansion
>>"%LOG%" echo(%DATE% %TIME% !MSG!
endlocal
exit /b 0
"""


def _bat_value(p) -> str:
    """Путь для строки set "X=..." в .cmd: % удваивается, у корня диска («E:\\») — «E:\\.»,
    иначе кавычка после обратной косой черты ломает разбор аргументов robocopy."""
    s = str(p)
    if s.endswith("\\"):
        s += "."
    return s.replace("%", "%%")


def write_update_helper(src: Path, app: Path, pid: int, new_version: str, *, old_version: str = __version__,
                        script: Path | None = None, log_file: Path | None = None, backup: Path | None = None,
                        wait_s: int = PID_WAIT_S, retries: int = 5) -> Path:
    """Пишет скрипт, который после выхода процесса pid заменит файлы в app файлами из src.
    Возвращает путь к скрипту (по умолчанию %TEMP%\\AutoPrintCode-update.cmd)."""
    script = script or Path(tempfile.gettempdir()) / HELPER_NAME
    log_file = log_file or APPLY_LOG
    backup = backup or BACKUP_DIR
    log_file.parent.mkdir(parents=True, exist_ok=True)
    text = _HELPER.format(
        app_name=APP_NAME, old=old_version, new=new_version, pid=int(pid), app=_bat_value(app), exe=EXE_NAME,
        src=_bat_value(src), bak=_bat_value(backup), log=_bat_value(log_file), wait=int(wait_s),
        retries=int(retries), internal=INTERNAL_DIR, window=WINDOW_DIR)
    script.parent.mkdir(parents=True, exist_ok=True)
    # UTF-8 без BOM: первой строкой скрипт сам переключает консоль на UTF-8 (chcp 65001)
    with open(script, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(text)
    return script


def _child_env() -> dict[str, str]:
    """Окружение для процессов, запускаемых собранной программой: без служебных переменных
    загрузчика PyInstaller и путей к _internal, которые добавил его runtime-хук."""
    env = dict(os.environ)
    if not getattr(sys, "frozen", False):
        return env
    meipass = os.path.normcase(os.path.normpath(getattr(sys, "_MEIPASS", "") or str(app_dir() / INTERNAL_DIR)))
    for k in list(env):
        if k.upper().startswith(("_PYI_", "_MEIPASS")):
            del env[k]
        elif k.upper() in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH") and \
                os.path.normcase(os.path.normpath(env[k])).startswith(meipass):
            del env[k]
    for k in env:
        if k.upper() == "PATH":
            env[k] = os.pathsep.join(p for p in env[k].split(os.pathsep)
                                     if p and os.path.normcase(os.path.normpath(p)) != meipass)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"   # новый экземпляр — независимый
    return env


def run_update_helper(script: Path, restart: bool) -> subprocess.Popen:
    """Запускает скрипт обновления скрытым независимым процессом: он переживёт выход программы."""
    comspec = os.environ.get("COMSPEC") or os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                                        "System32", "cmd.exe")
    # /s: cmd снимает только внешние кавычки — путь к скрипту с пробелами и скобками не ломается
    cmd = f'"{comspec}" /d /s /c ""{script}" {"restart" if restart else "exit"}"'
    # CREATE_NO_WINDOW — скрытая консоль, её наследуют robocopy и tasklist (с DETACHED_PROCESS у каждой
    # из них открылось бы своё окно); CREATE_NEW_PROCESS_GROUP — Ctrl+C родителя скрипт не касается
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    kw = dict(cwd=str(script.parent), env=_child_env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
              stderr=subprocess.DEVNULL, close_fds=True)
    try:   # и не погибнет вместе с заданием (job), в котором запущена программа, если оно это разрешает
        return subprocess.Popen(cmd, creationflags=flags | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0), **kw)
    except OSError:
        return subprocess.Popen(cmd, creationflags=flags, **kw)


_pending_helper: Path | None = None   # подготовленный скрипт установки сборки — запустится при выходе
_atexit_set = False


def prepare_exe_update(root: Path, new_version: str) -> Path:
    """Готовит установку скачанной сборки из root: пишет скрипт обновления. Файлы заменяются после
    выхода из программы: relaunch() запустит скрипт с перезапуском, обычный выход — без него (atexit)."""
    global _pending_helper, _atexit_set
    if not getattr(sys, "frozen", False):
        raise UpdateError("Сборку .exe можно установить только из собранной программы.")
    reason = frozen_layout_reason()
    if reason:
        raise UpdateError(reason)
    if root.suffix.lower() == ".exe":
        # установщик: запустится после выхода с запросом прав администратора
        if not root.is_file():
            raise UpdateError("Скачанный установщик не найден — скачайте обновление заново.")
        script = root
    elif not (root / EXE_NAME).is_file() or not (root / INTERNAL_DIR).is_dir():
        raise UpdateError("Скачанное обновление не найдено или повреждено — скачайте его заново.")
    else:
        script = write_update_helper(root, app_dir(), os.getpid(), new_version)
    _write_last_update({"from": __version__, "to": new_version, "time": time.time(), "shown": False,
                        "frozen": True})
    _pending_helper = script
    if not _atexit_set:
        atexit.register(_run_pending_helper_at_exit)
        _atexit_set = True
    log.info("Подготовлена установка сборки %s → %s: %s", __version__, new_version, script)
    return script


def exe_update_pending() -> bool:
    """Подготовлена установка сборки, которая начнётся при выходе из программы."""
    return _pending_helper is not None


def _run_pending_helper_at_exit() -> None:
    """«Установить при выходе»: программа закрывается без перезапуска — скрипт ставит обновление
    и не запускает её; новая версия откроется при следующем запуске."""
    global _pending_helper
    if _pending_helper is None:
        return
    script, _pending_helper = _pending_helper, None
    try:
        if script.suffix.lower() == ".exe":
            run_setup(script, restart=False)
        else:
            run_update_helper(script, restart=False)
        log.info("Запущена установка обновления при выходе: %s", script)
    except OSError:
        log.exception("Не удалось запустить установку обновления")


SETUP_ARGS = "/SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS"


def run_setup(setup: Path, restart: bool) -> None:
    """Установщик — с запросом прав администратора (UAC). /SILENT — без вопросов, видно только ход
    установки; /RELAUNCH=1 — установщик сам запустит программу (от имени пользователя, не администратора).
    OSError — не запустился (например, отказались дать права)."""
    import ctypes
    args = SETUP_ARGS + (" /RELAUNCH=1" if restart else "")
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(setup), args, str(setup.parent), 1)
    if r <= 32:
        raise OSError(f"установщик не запустился (код {r}; возможно, не дали права администратора)")


def cleanup() -> None:
    """Удаляет скачанные архивы, распакованные папки и временную копию старых файлов."""
    if getattr(sys, "frozen", False):   # отложенные скриптом библиотеки прежней сборки
        for p in [*app_dir().glob(INTERNAL_DIR + ".old*"), *app_dir().glob(WINDOW_DIR + ".old*")]:
            shutil.rmtree(p, ignore_errors=True)
    if not UPDATES_DIR.is_dir():
        return
    for p in UPDATES_DIR.iterdir():
        if p.name.startswith("staging-"):
            shutil.rmtree(p, ignore_errors=True)
        elif p.suffix in (".zip", ".part", ".exe"):   # .exe — скачанный установщик
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
    if d.get("frozen"):
        # сборку ставил скрипт после выхода: удалось ли — видно по версии, которая сейчас запущена
        cleanup()
        if parse_version(str(d.get("to") or "")) != parse_version(__version__):
            log.warning("Обновление до %s не установлено, работает %s — подробности в %s",
                        d.get("to"), __version__, APPLY_LOG)
            return None
        _sync_uninstall_entry()
    return d


def _sync_uninstall_entry() -> None:
    """Программа поставлена установщиком и обновилась сама — номер версии в «Приложениях» Windows тоже новый."""
    if sys.platform != "win32":
        return
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0,
                            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as k:
            where, _t = winreg.QueryValueEx(k, "InstallLocation")
            if os.path.normcase(os.path.normpath(str(where))) != os.path.normcase(str(app_dir())):
                return   # это другая копия программы (например, распакованная из zip)
            winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, __version__)
    except OSError:
        pass


def relaunch() -> None:
    """Запускает программу заново (вызывать после выхода из цикла событий и снятия блокировки).
    Если подготовлена установка сборки .exe — вместо этого запускает скрипт обновления: он дождётся
    выхода программы, заменит файлы и сам запустит новую версию с --updated."""
    global _pending_helper
    if _pending_helper is not None:
        script, _pending_helper = _pending_helper, None
        try:
            if script.suffix.lower() == ".exe":
                run_setup(script, restart=True)
            else:
                run_update_helper(script, restart=True)
            log.info("Перезапуск через установку обновления: %s", script)
            return
        except OSError as e:
            log.error("Не удалось запустить установку обновления (%s) — перезапуск прежней версии", e)
    frozen = getattr(sys, "frozen", False)
    if frozen:
        cmd = [sys.executable]
    else:
        cmd = [_python_exe(gui=True), str(app_dir() / "app.py")]
    cmd.append("--updated")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    log.info("Перезапуск: %s", cmd)
    subprocess.Popen(cmd, cwd=str(app_dir()), creationflags=flags, close_fds=True,
                     env=_child_env() if frozen else None)
