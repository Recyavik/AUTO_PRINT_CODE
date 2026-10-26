"""Экран демонстрации: заставка перерыва и файл активности (видео гимнастики для глаз, картинка).

Заставка перерыва — на весь монитор, поверх всего, что там показано: фон (картинка, растянутая
с обрезкой краёв, или встроенный фиолетовый), название («ПЕРЕРЫВ») и крупный обратный отсчёт
шрифтом Furore — как на слайдах 1Т. Когда время вышло — «ПРОДОЛЖАЕМ»; заставка остаётся, пока её
не уберут (кнопкой в напоминании, щелчком по ней или Esc), чтобы не исчезнуть посреди фразы ведущего.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QLinearGradient, QPainter, QPixmap, QRadialGradient, QScreen
from PySide6.QtWidgets import QLabel, QStackedLayout, QWidget

from ..model import fmt_left
from . import style

TITLE_FONT = "Furore"          # шрифт заголовков 1Т; если не установлен — Segoe UI Black
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".m4v"}


def title_font(px: float) -> QFont:
    """Шрифт в пикселях экрана — одинаковый размер на мониторах с разным масштабом."""
    family = TITLE_FONT if TITLE_FONT in QFontDatabase.families() else "Segoe UI"
    f = QFont(family)
    if family != TITLE_FONT:
        f.setWeight(QFont.Weight.Black)
    f.setPixelSize(max(18, int(px)))
    return f


def is_video(path: str) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXT


class _ScreenWindow(QWidget):
    """Окно на весь монитор демонстрации поверх всего. Щелчок или Esc — убрать."""
    closed = Signal()

    def __init__(self, screen: QScreen) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CursorShape.BlankCursor)

    def mousePressEvent(self, _e) -> None:
        self.close()

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.close()

    def closeEvent(self, e) -> None:
        self.closed.emit()
        super().closeEvent(e)


class BreakOverlay(_ScreenWindow):
    def __init__(self, screen: QScreen, end: datetime, clock: Callable[[], datetime], image: str = "",
                 title: str = "ПЕРЕРЫВ") -> None:
        super().__init__(screen)
        self.end, self.clock, self.title = end, clock, (title or "ПЕРЕРЫВ").upper()
        self.pixmap = QPixmap(image) if image else QPixmap()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(250)

    def left_text(self) -> str:
        left = self.end - self.clock()
        return fmt_left(left) if left.total_seconds() > 0 else "ПРОДОЛЖАЕМ"

    def closeEvent(self, e) -> None:
        self._timer.stop()
        super().closeEvent(e)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect())
        w, h = r.width(), r.height()
        if not self.pixmap.isNull():
            scaled = self.pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                        Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(int((w - scaled.width()) / 2), int((h - scaled.height()) / 2), scaled)
        else:
            g = QLinearGradient(0, 0, w, h)
            g.setColorAt(0, QColor("#0B0A3A"))
            g.setColorAt(1, QColor("#3A0F5E"))
            p.fillRect(r, g)
            glow = QRadialGradient(w * 0.8, h * 0.1, w * 0.6)
            glow.setColorAt(0, QColor(142, 77, 255, 90))
            glow.setColorAt(1, QColor(142, 77, 255, 0))
            p.fillRect(r, glow)

        # как на слайде «ПЕРЕРЫВ / 10 МИН»: белые надписи по центру, лёгкая тень для читаемости на любом фоне
        def text(rect: QRectF, s: str, px: float) -> None:
            p.setFont(title_font(px))
            p.setPen(QColor(0, 0, 0, 120))
            p.drawText(rect.translated(px * 0.04, px * 0.05), Qt.AlignmentFlag.AlignCenter, s)
            p.setPen(QColor(style.INK))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, s)

        text(QRectF(0, h * 0.30, w, h * 0.16), self.title, h * 0.075)
        left = self.left_text()
        text(QRectF(0, h * 0.50, w, h * 0.22), left, h * (0.13 if ":" in left else 0.075))


class MediaOverlay(_ScreenWindow):
    """Файл активности на весь монитор демонстрации: видео (со звуком, само закрывается в конце) или картинка."""

    def __init__(self, screen: QScreen, path: str) -> None:
        super().__init__(screen)
        self.path = path
        self.setStyleSheet("background: black;")
        lay = QStackedLayout(self)
        self.player = None
        if is_video(path):
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            from PySide6.QtMultimediaWidgets import QVideoWidget
            video = QVideoWidget(self)
            video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
            lay.addWidget(video)
            self.audio = QAudioOutput(self)
            self.player = QMediaPlayer(self)
            self.player.setAudioOutput(self.audio)
            self.player.setVideoOutput(video)
            self.player.setSource(QUrl.fromLocalFile(str(Path(path).resolve())))
            self.player.mediaStatusChanged.connect(self._on_status)
        else:
            label = QLabel(self)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pm = QPixmap(path)
            if not pm.isNull():
                label.setPixmap(pm.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))
            lay.addWidget(label)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if self.player is not None:
            self.player.play()

    def _on_status(self, status) -> None:
        from PySide6.QtMultimedia import QMediaPlayer
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.close()            # видео кончилось — экран демонстрации снова виден

    def closeEvent(self, e) -> None:
        if self.player is not None:
            self.player.stop()
        super().closeEvent(e)
