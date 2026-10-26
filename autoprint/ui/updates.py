"""Обновления в интерфейсе: фоновая проверка и загрузка, окно «Доступно обновление»."""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextBrowser, QVBoxLayout

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
        return True     # исходники — git или архив; собранная версия — установщиком из релиза

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
        if self.downloading or not self.can_install:
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
                root = updater.download_installer(rel, lambda got, total: self.progress.emit("Загрузка", got, total),
                                                  lambda: self._cancel)
                self.downloading = False
                self.staged = (rel, root)
                self.ready.emit(rel)
                return
            if self.mode == MODE_GIT:
                self.progress.emit("Загрузка", 0, 0)
                root = updater.git_stage(rel)
            else:
                z = updater.download(rel, lambda got, total: self.progress.emit("Загрузка", got, total),
                                     lambda: self._cancel)
                self.progress.emit("Проверка архива", 0, 0)
                root = updater.stage(z, rel)
            if updater.requirements_changed(root):
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
    def apply_staged(self, relaunch: bool = True) -> str:
        """Ставит скачанное обновление. Возвращает новую версию. UpdateError — если не вышло.
        Собранная версия: запускает установщик (он закроет программу и, если relaunch, запустит новую)."""
        if not self.staged:
            raise UpdateError("Обновление ещё не скачано.")
        if self.applied:
            return self.staged[0].version
        rel, root = self.staged
        if self.mode == MODE_FROZEN:
            updater.run_installer(root, rel.version, relaunch)
        elif self.mode == MODE_GIT:
            updater.git_apply(rel)
        else:
            updater.apply(root, rel.version)
        self.applied = True
        return rel.version


def _fmt_size(n: int) -> str:
    return f"{n / 1_048_576:.1f} МБ" if n >= 1_048_576 else f"{n // 1024} КБ"


class UpdateDialog(QDialog):
    """Что нового + «Обновить и перезапустить» / «Пропустить эту версию» / «Позже»."""
    restart_requested = Signal()

    def __init__(self, manager: UpdateManager, rel: Release, parent=None) -> None:
        super().__init__(parent)
        self.m, self.rel = manager, rel
        self.setWindowTitle("Доступно обновление")
        self.setMinimumSize(560, 420)

        head = QLabel(f"<h3>{rel.name}</h3>Установлена версия <b>{__version__}</b>, "
                      f"доступна <b>{rel.version}</b>"
                      + (f" от {rel.published}" if rel.published else "")
                      + (" <span style='color:#d29922'>(бета)</span>" if rel.prerelease else "") + ".")
        head.setTextFormat(Qt.TextFormat.RichText)
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(rel.notes.strip() or "_Автор не добавил описание к этой версии._")

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.RichText)
        self.bar = QProgressBar()
        self.bar.hide()
        self._want_restart = False

        self.btn_install = QPushButton()
        self.btn_install.setDefault(True)
        self.btn_install.clicked.connect(self._install)
        skip = QPushButton("Пропустить эту версию")
        skip.clicked.connect(self._skip)
        later = QPushButton("Позже")
        later.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(skip)
        row.addWidget(later)
        row.addWidget(self.btn_install)

        lay = QVBoxLayout(self)
        lay.addWidget(head)
        lay.addWidget(QLabel("Что нового:"))
        lay.addWidget(notes, 1)
        lay.addWidget(self.status)
        lay.addWidget(self.bar)
        lay.addLayout(row)

        manager.progress.connect(self._on_progress)
        manager.ready.connect(self._on_ready)
        manager.download_failed.connect(self._on_failed)
        self._refresh()

    def _refresh(self) -> None:
        m = self.m
        if m.staged and m.staged[0].version == self.rel.version:
            self.btn_install.setText("Перезапустить и обновить")
            self.status.setText("Обновление скачано и проверено. Ваши образцы и настройки не изменятся.")
        elif m.downloading:
            self.btn_install.setText("Отменить загрузку")
            self.bar.show()
        else:
            self.btn_install.setText("Обновить и перезапустить")
            self.status.setText("Ваши образцы и настройки не изменятся.")

    def _install(self) -> None:
        m = self.m
        if m.downloading:
            m.cancel()
        elif m.staged and m.staged[0].version == self.rel.version:
            self.accept()
            self.restart_requested.emit()
        else:
            self._want_restart = True
            m.download(self.rel)
            self._refresh()

    def _skip(self) -> None:
        self.m.settings.update_skip_version = self.rel.version
        self.m.settings.save()
        self.reject()

    def _on_progress(self, stage: str, got: int, total: int) -> None:
        self.bar.show()
        self.bar.setMaximum(total or 0)   # 0 — «бегущая» полоса
        self.bar.setValue(got if total else 0)
        size = f": {_fmt_size(got)}" + (f" из {_fmt_size(total)}" if total else "") if got else "…"
        self.status.setText(stage + size)

    def _on_ready(self, rel: Release) -> None:
        if rel.version != self.rel.version:
            return
        self.bar.hide()
        self._refresh()
        if self._want_restart:
            self.accept()
            self.restart_requested.emit()

    def _on_failed(self, text: str) -> None:
        self.bar.hide()
        self._want_restart = False
        self._refresh()
        self.status.setText(f"<span style='color:#e5534b'>{text}</span>")

    def done(self, r: int) -> None:
        for sig, slot in ((self.m.progress, self._on_progress), (self.m.ready, self._on_ready),
                          (self.m.download_failed, self._on_failed)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        super().done(r)
