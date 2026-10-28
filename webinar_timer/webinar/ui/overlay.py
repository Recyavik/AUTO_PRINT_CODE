"""Экран демонстрации: заставка перерыва и файл активности (видео гимнастики для глаз, картинка).

Заставка перерыва — на весь монитор, поверх всего, что там показано: фон (картинка, растянутая
с обрезкой краёв, или встроенный фиолетовый), название («ПЕРЕРЫВ») и крупный обратный отсчёт
шрифтом Furore — как на слайдах 1Т. Когда время вышло — «ПРОДОЛЖАЕМ», ниже «ПЕРЕРЫВ ЗАВЕРШЁН»; заставка остаётся, пока её
не уберут кнопкой «■ Убрать» на пульте, чтобы не исчезнуть посреди фразы ведущего.
Заставка и видео — «занавес»: пока они на экране, ведущий спокойно готовит слайды за ними; зрители этого не видят.
Экстренный занавес (CurtainOverlay) — тот же фон и своя надпись (по умолчанию «СЕЙЧАС ПРОДОЛЖИМ»), без отсчёта: быстро закрыть то, что не для зрителей.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QImage, QLinearGradient, QPainter, QPixmap, QRadialGradient, QScreen
from PySide6.QtWidgets import QWidget

from ..model import fmt_left

log = logging.getLogger(__name__)

TITLE_FONT = "Furore"          # шрифт заголовков 1Т; если не установлен — Segoe UI Black
WRAP_CENTER = Qt.AlignmentFlag.AlignCenter.value | Qt.TextFlag.TextWordWrap.value   # по центру, с переносом слов
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".m4v"}


_fonts_loaded = False


def _load_media_fonts() -> None:
    """Шрифт из папки media (Furore.otf) — если он не установлен в Windows: папку можно перенести на другой ПК."""
    global _fonts_loaded
    if _fonts_loaded:
        return
    _fonts_loaded = True
    from ..store import MEDIA_DIR
    for f in list(MEDIA_DIR.glob("*.otf")) + list(MEDIA_DIR.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(f))


def title_font(px: float) -> QFont:
    """Шрифт в пикселях экрана — одинаковый размер на мониторах с разным масштабом."""
    if TITLE_FONT not in QFontDatabase.families():
        _load_media_fonts()
    family = TITLE_FONT if TITLE_FONT in QFontDatabase.families() else "Segoe UI"
    f = QFont(family)
    if family != TITLE_FONT:
        f.setWeight(QFont.Weight.Black)
    f.setPixelSize(max(18, int(px)))
    return f


def is_video(path: str) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXT


class _ScreenWindow(QWidget):
    """Окно на весь монитор демонстрации поверх всего. Убирается только кнопкой на пульте (не случайным щелчком)."""
    closed = Signal()

    def __init__(self, screen: QScreen) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CursorShape.BlankCursor)

    def closeEvent(self, e) -> None:
        self.closed.emit()
        super().closeEvent(e)


def paint_backdrop(p: QPainter, w: float, h: float, pixmap: QPixmap) -> None:
    """Фон заставки: картинка, растянутая с обрезкой краёв, или встроенный фиолетовый 1Т."""
    if not pixmap.isNull():
        scaled = pixmap.scaled(int(w), int(h), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               Qt.TransformationMode.SmoothTransformation)
        p.drawPixmap(int((w - scaled.width()) / 2), int((h - scaled.height()) / 2), scaled)
        return
    r = QRectF(0, 0, w, h)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0, QColor("#0B0A3A"))
    g.setColorAt(1, QColor("#3A0F5E"))
    p.fillRect(r, g)
    glow = QRadialGradient(w * 0.8, h * 0.1, w * 0.6)
    glow.setColorAt(0, QColor(142, 77, 255, 90))
    glow.setColorAt(1, QColor(142, 77, 255, 0))
    p.fillRect(r, glow)


def paint_title(p: QPainter, rect: QRectF, s: str, px: float, color: QColor, wrap: bool = False) -> None:
    """Надпись как на слайдах 1Т: по центру, с лёгкой тенью для читаемости на любом фоне."""
    flags = WRAP_CENTER if wrap else Qt.AlignmentFlag.AlignCenter.value
    p.setFont(title_font(px))
    p.setPen(QColor(0, 0, 0, 120))
    p.drawText(rect.translated(px * 0.04, px * 0.05), flags, s)
    p.setPen(color)
    p.drawText(rect, flags, s)


def fit_px(rect: QRectF, s: str, px: float) -> float:
    """Кегль, при котором надпись (с переносом по словам) помещается в rect: длинный текст — мельче."""
    flags = WRAP_CENTER
    while px > 18:
        box = QFontMetricsF(title_font(px)).boundingRect(rect, flags, s)
        if box.width() <= rect.width() and box.height() <= rect.height():
            break
        px *= 0.92
    return px


class CurtainOverlay(_ScreenWindow):
    """Экстренный занавес: фон заставки и надпись из настроек — без отсчёта, пока ведущий не уберёт."""
    DEFAULT_TEXT = "Сейчас продолжим"

    def __init__(self, screen: QScreen, image: str = "", text_color: str = "#FFFFFF", text: str = "") -> None:
        super().__init__(screen)
        self.text = (text.strip() or self.DEFAULT_TEXT).upper()
        self.text_color = QColor(text_color) if QColor.isValidColorName(text_color) else QColor("#FFFFFF")
        self.pixmap = QPixmap(image) if image else QPixmap()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        paint_backdrop(p, w, h, self.pixmap)
        rect = QRectF(w * 0.06, h * 0.25, w * 0.88, h * 0.5)
        paint_title(p, rect, self.text, fit_px(rect, self.text, h * 0.09), self.text_color, wrap=True)


class BreakOverlay(_ScreenWindow):
    def __init__(self, screen: QScreen, end: datetime, clock: Callable[[], datetime], image: str = "",
                 title: str = "ПЕРЕРЫВ", text_color: str = "#FFFFFF") -> None:
        super().__init__(screen)
        self.text_color = QColor(text_color) if QColor.isValidColorName(text_color) else QColor("#FFFFFF")
        self.end, self.clock, self.title = end, clock, (title or "ПЕРЕРЫВ").upper()
        self.total = max(timedelta(0), end - clock())     # длительность — для «Заново» и полосы на пульте
        self._paused_left: timedelta | None = None        # отсчёт на паузе: сколько оставалось
        self.pixmap = QPixmap(image) if image else QPixmap()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(250)

    # ---- управление с пульта (расписание эфира при этом не сдвигается)
    @property
    def paused(self) -> bool:
        return self._paused_left is not None

    def left(self) -> timedelta:
        return self._paused_left if self._paused_left is not None else self.end - self.clock()

    def pause(self) -> None:
        if self._paused_left is None:
            self._paused_left = max(timedelta(0), self.end - self.clock())
            self.update()

    def resume(self) -> None:
        if self._paused_left is not None:
            self.end, self._paused_left = self.clock() + self._paused_left, None
            self.update()

    def add(self, delta: timedelta) -> None:
        """±минута: перерыв длиннее или короче; после «ПРОДОЛЖАЕМ» +1 мин снова включает отсчёт."""
        if self._paused_left is not None:
            self._paused_left = max(timedelta(0), self._paused_left + delta)
        else:
            now = self.clock()
            self.end = max(now, max(self.end, now) + delta if delta > timedelta(0) else self.end + delta)
        self.total = max(timedelta(0), self.total + delta)
        self.update()

    def seek(self, passed: timedelta) -> None:
        """Перемотка с пульта: отсчёт — как будто от перерыва прошло passed (0 … вся длительность).
        На паузе остаётся на паузе; расписание эфира не сдвигается."""
        left = max(timedelta(0), min(self.total, self.total - passed))
        if self._paused_left is not None:
            self._paused_left = left
        else:
            self.end = self.clock() + left
        self.update()

    def restart(self) -> None:
        self.end = self.clock() + self.total
        if self._paused_left is not None:
            self._paused_left = self.total
        self.update()

    def left_text(self) -> str:
        left = self.left()
        return fmt_left(left) if left.total_seconds() > 0 else "ПРОДОЛЖАЕМ"

    def closeEvent(self, e) -> None:
        self._timer.stop()
        super().closeEvent(e)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        paint_backdrop(p, w, h, self.pixmap)

        # как на слайде «ПЕРЕРЫВ / 10 МИН»; цвет — из настроек заставки, не из темы окна таймера
        def text(rect: QRectF, s: str, px: float) -> None:
            paint_title(p, rect, s, px, self.text_color)

        if self.left().total_seconds() > 0:
            text(QRectF(0, h * 0.30, w, h * 0.16), self.title, h * 0.075)
            text(QRectF(0, h * 0.50, w, h * 0.22), self.left_text(), h * 0.13)
        else:
            # время вышло: главное — «ПРОДОЛЖАЕМ», ниже мельче — что закончилось
            text(QRectF(0, h * 0.32, w, h * 0.18), "ПРОДОЛЖАЕМ", h * 0.11)
            text(QRectF(0, h * 0.53, w, h * 0.12), "ПЕРЕРЫВ ЗАВЕРШЁН", h * 0.055)


class MediaOverlay(_ScreenWindow):
    """Файл активности на весь монитор демонстрации: видео (со звуком; в конце — стоп-кадр) или картинка.

    Кадры видео рисуются в самом окне (QVideoSink → QPainter), как заставка перерыва, а не через QVideoWidget:
    тот выводит через Direct3D, Windows считает такое окно на весь монитор полноэкранной игрой и при переходе
    в другое окно с панели задач переключает режим вывода — экран у зрителей моргал."""

    def __init__(self, screen: QScreen, path: str) -> None:
        super().__init__(screen)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.player = None
        self.frame = QImage()                      # последний кадр видео (в конце видео он и остаётся)
        self.pixmap = QPixmap()                    # картинка вместо видео
        if is_video(path):
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
            self.audio = QAudioOutput(self)
            self.player = QMediaPlayer(self)
            self.player.setAudioOutput(self.audio)
            self.sink = QVideoSink(self)
            self.sink.videoFrameChanged.connect(self._on_frame)
            self.player.setVideoOutput(self.sink)
            self.player.setSource(QUrl.fromLocalFile(str(Path(path).resolve())))
            self.player.mediaStatusChanged.connect(self._on_status)
            self.player.errorOccurred.connect(lambda _e, msg: log.warning("Видео %s: %s", Path(path).name, msg))
        else:
            self.pixmap = QPixmap(path)

    def _on_frame(self, frame) -> None:
        if frame.isValid():
            image = frame.toImage()
            if not image.isNull():
                self.frame = image
                self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("black"))
        src = self.frame if not self.frame.isNull() else self.pixmap
        if src.isNull():
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        size = src.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        target = QRectF((self.width() - size.width()) / 2, (self.height() - size.height()) / 2,
                        size.width(), size.height())
        if isinstance(src, QImage):
            p.drawImage(target, src)
        else:
            p.drawPixmap(target, src, QRectF(src.rect()))

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if self.player is not None:
            self.player.play()

    def _on_status(self, status) -> None:
        from PySide6.QtMultimedia import QMediaPlayer
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            log.warning("Видео не открылось: %s", self.player.errorString())
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            log.info("Видео закончилось (%d с)", self.player.position() // 1000)
            # экран не открывается сам: последний кадр стоит, пока ведущий не уберёт видео кнопкой на пульте
            self.player.setPosition(max(0, self.player.duration() - 100))
            self.player.pause()

    def closeEvent(self, e) -> None:
        if self.player is not None:
            self.player.stop()
        super().closeEvent(e)
