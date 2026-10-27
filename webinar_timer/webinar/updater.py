"""Обновления «Таймера вебинара» из GitHub Releases.

Релиз таймера — тег «webinar-v1.3.0» в репозитории; к нему приложен лёгкий установщик
«webinar-timer-update-1.3.0.exe» (программа без видео, фона и шрифта: они у пользователя уже стоят).
Теги AutoPrintCode («v0.6.3») сюда не попадают, а его программа обновлений не видит теги таймера.

Проверка и скачивание — в фоновом потоке (CheckThread, DownloadThread), окно не подвисает;
поток переживает закрытие окна настроек и не держит выход из программы.
Установка — тихим запуском установщика: он закрывает таймер, ставит новую версию (шаблоны и настройки
пользователя не трогает) и запускает таймер снова. Обновляется только установленная версия (exe);
из исходников — git pull.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import __version__

log = logging.getLogger(__name__)

REPO = "Recyavik/AUTO_PRINT_CODE"
API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
TAG_PREFIX = "webinar-v"
ASSET_RE = re.compile(r"^webinar-timer-update-(\d+(?:\.\d+)*)\.exe$", re.IGNORECASE)
TIMEOUT = 15


@dataclass
class Release:
    version: str
    notes: str
    asset_url: str
    size: int


def version_key(v: str) -> tuple[int, ...] | None:
    """«1.2.0» → (1, 2, 0, 0, 0, 0) — одной длины, чтобы «1.2» == «1.2.0»; не версия — None."""
    # опечатки в имени тега при создании релиза: «webinar-v.1.3.2», «v-1.3.2» — номер тот же
    v = v.strip().lstrip("vV").lstrip(".-_ ")
    if not re.fullmatch(r"\d+(\.\d+){0,5}", v):
        return None
    nums = tuple(int(x) for x in v.split("."))
    return nums + (0,) * (6 - len(nums))


def is_newer(v: str, current: str = __version__) -> bool:
    new, cur = version_key(v), version_key(current)
    return new is not None and cur is not None and new > cur


def pick_latest(releases: list[dict]) -> Release | None:
    """Самый новый релиз таймера с лёгким установщиком (черновики и пре-релизы — мимо).
    Версия — из тега «webinar-v1.3.0», а если релиз выложили под другим тегом — из имени установщика
    «webinar-timer-update-1.3.0.exe» (так релиз не потеряется из-за ошибки в теге)."""
    best: Release | None = None
    for r in releases:
        if r.get("draft") or r.get("prerelease"):
            continue
        m = None
        asset = None
        for a in r.get("assets", []):
            m = ASSET_RE.match(str(a.get("name", "")))
            if m:
                asset = a
                break
        if asset is None:
            continue
        tag = str(r.get("tag_name", ""))
        ver = tag[len(TAG_PREFIX):] if tag.startswith(TAG_PREFIX) else m.group(1)
        if version_key(ver) is None:
            continue
        if best is None or version_key(ver) > version_key(best.version):
            best = Release(ver, str(r.get("body") or ""), str(asset.get("browser_download_url", "")),
                           int(asset.get("size") or 0))
    return best


def fetch_latest() -> Release | None:
    req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"webinar-timer/{__version__}"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return pick_latest(json.loads(resp.read().decode("utf-8")))


def can_update() -> bool:
    """Обновляется только установленная версия (exe), не запуск из исходников."""
    return bool(getattr(sys, "frozen", False))


def install(setup: Path) -> None:
    """Тихая установка: установщик сам закроет таймер, поставит новую версию и запустит её."""
    log.info("Установка обновления: %s", setup.name)
    subprocess.Popen([str(setup), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     close_fds=True)


class _Background(QObject):
    """Сетевая работа в обычном фоновом потоке Python, а не в QThread с родителем-окном.
    QThread, удалённый вместе с окном настроек посреди запроса (до 15 с), аварийно роняет всю программу
    («QThread: Destroyed while thread is still running») — хоть посреди эфира. Фоновый поток переживает
    закрытие окна и не держит выход из программы; сигналы приходят в окно, пока оно живо."""
    finished = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__()          # без родителя: окно может уйти раньше, чем закончится запрос
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._main, name=type(self).__name__, daemon=True)
        self._thread.start()

    def isRunning(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _main(self) -> None:
        try:
            self.run()
        finally:
            try:
                self.finished.emit()
            except RuntimeError:     # программа уже закрывается
                pass

    def run(self) -> None:
        raise NotImplementedError


class CheckThread(_Background):
    """Проверить, есть ли версия новее. found(Release | None) — None, если обновлений нет."""
    found = Signal(object)
    failed = Signal(str)

    def run(self) -> None:
        try:
            r = fetch_latest()
        except Exception as e:      # сеть, GitHub, разбор ответа — для пользователя одно: «не удалось»
            log.warning("Проверка обновлений: %s", e)
            self.failed.emit(str(e))
            return
        self.found.emit(r if r is not None and is_newer(r.version) else None)


class DownloadThread(_Background):
    """Скачать установщик обновления во временную папку. progress(0…100), done(путь)."""
    progress = Signal(int)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, release: Release, parent=None) -> None:
        super().__init__(parent)
        self.release = release

    def run(self) -> None:
        dest = Path(tempfile.gettempdir()) / f"webinar-timer-update-{self.release.version}.exe"
        try:
            req = urllib.request.Request(self.release.asset_url,
                                         headers={"User-Agent": f"webinar-timer/{__version__}"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp, open(dest, "wb") as f:
                total = int(resp.headers.get("Content-Length") or self.release.size or 0)
                got = 0
                while chunk := resp.read(1 << 16):
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        self.progress.emit(min(100, got * 100 // total))
            # обрыв связи на середине: urllib просто вернёт конец данных — недокачанный установщик не запускать
            if total and got != total:
                raise OSError(f"скачано {got} из {total} байт — связь оборвалась")
        except Exception as e:
            dest.unlink(missing_ok=True)
            log.warning("Скачивание обновления: %s", e)
            self.failed.emit(str(e))
            return
        self.done.emit(dest)
