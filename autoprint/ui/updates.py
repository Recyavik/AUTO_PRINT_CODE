"""Обновления: фоновая проверка и загрузка (лист «Доступно обновление» — в окне программы, sheets.js).

Собранная программа (.exe) ставит сборку из релиза: скачивание, проверка SHA-256 и распаковка — здесь,
в фоне; замену файлов делает скрипт после выхода программы (см. updater.prepare_exe_update / relaunch).
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .. import __version__, updater
from ..storage import Settings
from ..updater import MODE_FROZEN, MODE_GIT, Release, UpdateError

log = logging.getLogger("autoprint.update")

MODE_NOTIFY, MODE_DOWNLOAD, MODE_AUTO = "notify", "download", "auto"
UPDATE_MODES = {
    MODE_NOTIFY: "Только сообщить",
    MODE_DOWNLOAD: "Скачать и предложить перезапуск",
    MODE_AUTO: "Скачать и установить при выходе",
}
INTERVALS = {0: "При каждом запуске", 24: "Раз в день", 168: "Раз в неделю"}

FROZEN_NOTE = "Скачайте новую версию со страницы релиза."


class UpdateManager(QObject):
    """Проверка → загрузка → подготовка идут в фоновом потоке; установка — в GUI-потоке, она быстрая."""
    checked = Signal(object, bool)      # (Release | None, вручную)
    check_failed = Signal(str, bool)    # (текст, вручную)
    progress = Signal(str, int, int)    # (этап, получено, всего; 0 — неизвестно)
    ready = Signal(object)              # Release скачан, проверен и готов к установке
    download_failed = Signal(str)

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.mode = updater.install_mode()
        self.latest: Release | None = None
        self.staged: tuple[Release, Path] | None = None
        self.checking = False
        self.downloading = False
        self.applied = False
        self._cancel = False

    @property
    def can_install(self) -> bool:
        """Можно ли поставить найденную версию (self.latest) самой программой, без браузера."""
        if self.mode != MODE_FROZEN:
            return True
        if self.latest is None:
            return updater.can_self_update()
        return self.installable(self.latest)

    def installable(self, rel: Release) -> bool:
        """Собранной программе нужна сборка .exe с .sha256 в релизе и право записи в свою папку."""
        return self.mode != MODE_FROZEN or updater.frozen_block_reason(rel) is None

    def block_reason(self, rel: Release) -> str:
        """Почему rel придётся скачать вручную ('' — не придётся)."""
        if self.mode != MODE_FROZEN:
            return ""
        return updater.frozen_block_reason(rel) or ""

    # ---- проверка
    def check_due(self) -> bool:
        s = self.settings
        if not s.update_auto_check:
            return False
        if s.update_interval_h <= 0:
            return True
        return time.time() - s.update_last_check >= s.update_interval_h * 3600

    def check(self, manual: bool = False) -> None:
        if self.checking:
            return
        self.checking = True
        threading.Thread(target=self._check, args=(manual, self.settings.update_prerelease),
                         name="update-check", daemon=True).start()

    def _check(self, manual: bool, prerelease: bool) -> None:
        try:
            rel = updater.fetch_latest(prerelease)
        except UpdateError as e:
            log.warning("Проверка обновлений: %s", e)
            self.checking = False
            self.check_failed.emit(str(e), manual)
            return
        except Exception as e:  # неожиданный ответ GitHub не должен ронять программу
            log.exception("Проверка обновлений")
            self.checking = False
            self.check_failed.emit(f"Не удалось проверить обновления: {e}", manual)
            return
        self.checking = False
        log.info("Проверка обновлений: на GitHub %s, установлена %s", rel.tag if rel else "—", __version__)
        newer = rel if rel and updater.is_newer(rel.version) else None
        self.latest = newer
        self.checked.emit(newer, manual)

    def is_skipped(self, rel: Release) -> bool:
        return rel.version == self.settings.update_skip_version

    # ---- загрузка
    def download(self, rel: Release) -> None:
        if self.downloading or not self.installable(rel):
            return
        if self.staged and self.staged[0].version == rel.version:
            self.ready.emit(rel)
            return
        self.downloading = True
        self._cancel = False
        threading.Thread(target=self._download, args=(rel,), name="update-download", daemon=True).start()

    def cancel(self) -> None:
        self._cancel = True

    def _download(self, rel: Release) -> None:
        try:
            if self.mode == MODE_FROZEN:
                # сборка .exe: скачать, сверить SHA-256 с .sha256 из релиза, распаковать и проверить
                z = updater.download_exe(rel, lambda got, total: self.progress.emit("Загрузка", got, total),
                                         lambda: self._cancel)
                self.progress.emit("Распаковка", 0, 0)
                root = updater.stage_exe(z, rel)
            elif self.mode == MODE_GIT:
                self.progress.emit("Загрузка", 0, 0)
                root = updater.git_stage(rel)
            else:
                z = updater.download(rel, lambda got, total: self.progress.emit("Загрузка", got, total),
                                     lambda: self._cancel)
                self.progress.emit("Проверка архива", 0, 0)
                root = updater.stage(z, rel)
            if self.mode != MODE_FROZEN and updater.requirements_changed(root):
                self.progress.emit("Установка библиотек (pip)", 0, 0)
                updater.install_requirements(root)
        except UpdateError as e:
            self.downloading = False
            self.download_failed.emit(str(e))
            return
        except Exception as e:
            log.exception("Загрузка обновления")
            self.downloading = False
            self.download_failed.emit(f"Не удалось подготовить обновление: {e}")
            return
        self.downloading = False
        self.staged = (rel, root)
        self.ready.emit(rel)

    # ---- установка
    def apply_staged(self) -> str:
        """Ставит скачанное обновление. Возвращает новую версию. UpdateError — если не вышло.
        Собранная программа здесь только готовит скрипт: файлы он заменит после выхода из программы
        (updater.relaunch() — с перезапуском, обычный выход — без него)."""
        if not self.staged:
            raise UpdateError("Обновление ещё не скачано.")
        if self.applied:
            return self.staged[0].version
        rel, root = self.staged
        if self.mode == MODE_FROZEN:
            updater.prepare_exe_update(root, rel.version)
        elif self.mode == MODE_GIT:
            updater.git_apply(rel)
        else:
            updater.apply(root, rel.version)
        self.applied = True
        return rel.version
