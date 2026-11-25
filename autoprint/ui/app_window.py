"""Окно программы: своя рамка (FramelessWindow) и внутри — одна страница во встроенном браузере (QtWebEngine).

Страница — http://127.0.0.1:<порт>/app с локального сервера эфира. Заголовок окна рисует она сама и сообщает,
где «ручки» для перетаскивания (ui/regions.py). Кнопки окна, маленький режим, «поверх всех окон» — команды
страницы (window_cmd). Пока движок браузера стартует (~2 с), поверх — заставка со знаком программы; не удалось
загрузить страницу — понятное сообщение с «Повторить» и «Журнал работы», а не белый экран.

web=False — без встроенного браузера (тесты оболочки): всё, кроме самой страницы.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QByteArray, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QStackedLayout, QVBoxLayout, QWidget

from .. import APP_NAME
from .frameless import FramelessWindow
from .regions import Regions, hit_code
from .theme import theme

log = logging.getLogger(__name__)

BIG_SIZE = QSize(1280, 860)
BIG_MIN = QSize(720, 480)
COMPACT_SIZE = QSize(360, 600)
COMPACT_MIN = QSize(150, 70)
FAIL_PREFIX = "Не удалось запустить окно программы"
LOCAL_HOSTS = ("127.0.0.1", "localhost")


def _bg() -> str:
    return "#161A22" if theme.dark else "#EEF0F3"


def _make_page_class():
    """Класс страницы создаётся лениво: без web QtWebEngine не импортируется вовсе."""
    from PySide6.QtWebEngineCore import QWebEnginePage

    class Page(QWebEnginePage):
        """Ссылки наружу (не наш сервер) открываются в браузере человека, а не внутри окна программы."""

        def acceptNavigationRequest(self, url, nav_type, is_main_frame) -> bool:
            if url.scheme() in ("http", "https") and url.host() not in LOCAL_HOSTS:
                QDesktopServices.openUrl(url)
                return False
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)

        def createWindow(self, _type):
            # target=_blank и window.open: адрес узнаём на первом переходе и отдаём браузеру человека
            helper = Page(self.profile(), self)
            helper.urlChanged.connect(lambda u, h=helper: (QDesktopServices.openUrl(u), h.deleteLater()))
            return helper

        def javaScriptConsoleMessage(self, level, message, line, source) -> None:
            if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
                log.warning("Страница окна: %s (%s:%s)", message, source.rsplit("/", 1)[-1], line)

    return Page


class AppWindow(FramelessWindow):
    ready = Signal()            # страница загрузилась
    page_failed = Signal(str)   # не загрузилась — текст для человека

    def __init__(self, app, web: bool = True) -> None:
        super().__init__(APP_NAME, minimize=True, maximize=True)
        self.app = app
        self.web = web
        self.regions = Regions()
        self.compact = False
        self._big_geometry: QByteArray | None = None
        self._big_maximized = False
        self.resize(BIG_SIZE)
        self.setMinimumSize(BIG_MIN)

        self.stack = QStackedLayout(self.body)
        self.stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self.view = None
        if web:
            from PySide6.QtWebEngineCore import QWebEngineProfile
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from ..storage import DATA_DIR
            self.profile = QWebEngineProfile("autoprint", self)
            web_dir = DATA_DIR / "web"
            self.profile.setPersistentStoragePath(str(web_dir / "storage"))
            self.profile.setCachePath(str(web_dir / "cache"))
            self.view = QWebEngineView(self)
            page = _make_page_class()(self.profile, self.view)
            page.setBackgroundColor(QColor(_bg()))
            self.view.setPage(page)
            self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
            self.view.loadFinished.connect(self._on_loaded)
            page.renderProcessTerminated.connect(self.on_render_gone)   # сбой отрисовки — не белое окно
            self.stack.addWidget(self.view)
        self.splash = self._make_splash()
        self.stack.addWidget(self.splash)
        self.fail = self._make_fail()
        self.stack.addWidget(self.fail)
        self.fail.hide()
        self.splash.raise_()
        self._loaded = False
        self.apply_pin()

    # ------------------------------------------------------------ заставка и сообщение
    def _make_splash(self) -> QWidget:
        from . import logo
        w = QWidget()
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        w.setStyleSheet(f"background:{_bg()};")
        lay = QVBoxLayout(w)
        mark = QLabel()
        mark.setPixmap(logo.make_icon(logo.APP).pixmap(72, 72))
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(mark)
        return w

    def _make_fail(self) -> QWidget:
        w = QWidget()
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        text = "#E9EDF3" if theme.dark else "#181C24"
        w.setStyleSheet(f"background:{_bg()}; color:{text}; font-size:15px;")
        lay = QVBoxLayout(w)
        lay.addStretch(1)
        self._fail_label = QLabel()
        self._fail_label.setWordWrap(True)
        self._fail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fail_label.setMaximumWidth(560)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._fail_label)
        row.addStretch(1)
        lay.addLayout(row)
        btns = QHBoxLayout()
        btns.addStretch(1)
        retry = QPushButton("Повторить")
        retry.clicked.connect(self.retry)
        logs = QPushButton("Журнал работы")
        logs.clicked.connect(self._open_log)
        btns.addWidget(retry)
        btns.addWidget(logs)
        btns.addStretch(1)
        lay.addLayout(btns)
        lay.addStretch(1)
        return w

    def message_text(self) -> str:
        return self._fail_label.text()

    def show_failure(self, why: str) -> None:
        text = f"{FAIL_PREFIX}: {why}"
        log.warning(text)
        self._fail_label.setText(text + "\nПодробности — в журнале работы.")
        self.splash.hide()
        self.fail.show()
        self.fail.raise_()
        self.page_failed.emit(text)

    @staticmethod
    def _open_log() -> None:
        from ..logs import LOG_FILE
        if LOG_FILE.exists():
            os.startfile(LOG_FILE)

    # ------------------------------------------------------------ загрузка
    def page_url(self) -> str:
        server = self.app.efir.server
        return server.url + "app" if server.running and server.url else ""

    def load(self) -> None:
        url = self.page_url()
        if not url:
            ensure = getattr(self.app.efir, "ensure_server", None)
            if callable(ensure) and ensure():
                url = self.page_url()
        if not url:
            self.show_failure("сервер окна не запустился (порты 8791–8799 заняты?).")
            return
        self.fail.hide()
        if self.view is None:
            return
        self.splash.show()
        self.splash.raise_()
        self.view.load(QUrl(url))

    def retry(self) -> None:
        self.load()

    def _on_loaded(self, ok: bool) -> None:
        if not ok:
            self.show_failure("страница окна не загрузилась.")
            return
        self._loaded = True
        self.fail.hide()
        self.splash.hide()
        self._watch_drops()
        self.ready.emit()
        # загрузилась, но скрипты страницы могли не запуститься (ошибка в модуле) — проверить через несколько секунд
        if self.view is not None:
            QTimer.singleShot(6000, lambda: self.view is not None and self.view.page().runJavaScript(
                "window.__ready === true", 0, lambda ok: self.on_ready_checked(bool(ok))))

    def on_ready_checked(self, ok: bool) -> None:
        if not ok and not self._failure_shown():
            self.show_failure("страница окна не запустилась.")

    def _failure_shown(self) -> bool:
        return not self.fail.isHidden()          # сообщение уже показано — второе не нужно

    def on_render_gone(self, status, code) -> None:
        """Процесс отрисовки страницы упал (видеодрайвер, нехватка памяти): сообщение и перезагрузка сама."""
        log.warning("Страница окна: процесс отрисовки завершился (%s, код %s)", status, code)
        self._loaded = False
        self.show_failure("страница окна перестала отвечать — перезагружаю.")
        QTimer.singleShot(1500, self.retry)

    # ------------------------------------------------------------ файлы, перетащенные в окно
    def _watch_drops(self) -> None:
        """Файлы ловит окно, а не браузер: у программы — настоящие пути (видео в сотни МБ не копируются через
        страницу), а страница не уходит на file://. Текст и картинки из браузера — как обычно, странице."""
        for w in (self.view, self.view.focusProxy() if self.view is not None else None):
            if w is not None and not w.property("apc_drops"):
                w.setProperty("apc_drops", True)
                w.installEventFilter(self)

    @staticmethod
    def _local_files(mime) -> list[str]:
        if mime is None or not mime.hasUrls():
            return []
        urls = mime.urls()
        if not urls or not all(u.isLocalFile() for u in urls):
            return []
        return [u.toLocalFile() for u in urls]

    def eventFilter(self, obj, ev) -> bool:
        from PySide6.QtCore import QEvent
        t = ev.type()
        if t in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if self._local_files(ev.mimeData()):
                ev.acceptProposedAction()
                return True
        elif t == QEvent.Type.Drop:
            paths = self._local_files(ev.mimeData())
            if paths:
                ev.acceptProposedAction()
                drop = getattr(self.app, "drop", None)
                if callable(drop):
                    drop(paths)
                return True
        return super().eventFilter(obj, ev)

    def run_js(self, code: str, callback=None) -> None:
        if self.view is None:
            return
        if callback is None:
            self.view.page().runJavaScript(code)
        else:
            self.view.page().runJavaScript(code, 0, callback)

    # ------------------------------------------------------------ печать урока
    def _wait(self, signal, start, timeout_ms: int) -> bool:
        """Запустить start() и дождаться signal(…, ok) — страница ждёт ответа (классы печати на ней до конца)."""
        from PySide6.QtCore import QEventLoop
        loop = QEventLoop()
        res = {"ok": False}

        def done(*args) -> None:
            res["ok"] = bool(args[-1]) if args else False
            loop.quit()
        signal.connect(done)
        try:
            start()
            QTimer.singleShot(timeout_ms, loop.quit)
            loop.exec()
        finally:
            signal.disconnect(done)
        return res["ok"]

    def print_pdf(self, path: str, open_after: bool = True) -> bool:
        """«Сохранить PDF…»: страница урока как при печати (@media print), A4; потом файл открывается."""
        if self.view is None:
            return False
        from PySide6.QtCore import QMarginsF
        from PySide6.QtGui import QPageLayout, QPageSize
        page = self.view.page()
        layout = QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                             QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)
        with self._paper():
            ok = self._wait(page.pdfPrintingFinished, lambda: page.printToPdf(str(path), layout), 120_000)
        if ok and open_after:
            try:
                os.startfile(str(path))
            except OSError as e:
                log.warning("PDF не открылся: %s", e)
        return ok

    def print_dialog(self) -> bool:
        """«Печать…»: системный выбор принтера, печать страницы урока. False — передумали или не напечаталось."""
        if self.view is None:
            return False
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle("Печать урока")
        if dlg.exec() != QPrintDialog.DialogCode.Accepted:
            return False
        with self._paper():
            return self._wait(self.view.printFinished, lambda: self.view.print(printer), 300_000)

    @contextmanager
    def _paper(self):
        """На время печати фон под страницей — белый: Chromium закрашивает им поля листа, а в тёмной теме окна
        это был #161A22 — чёрная рамка вокруг урока в PDF и на бумаге."""
        page = self.view.page()
        page.setBackgroundColor(QColor("#FFFFFF"))
        try:
            yield
        finally:
            page.setBackgroundColor(QColor(_bg()))

    # ------------------------------------------------------------ области и кнопки окна
    def set_regions(self, data: dict) -> None:
        self.regions = Regions.from_data(data)

    def client_hit(self, lx: float, ly: float) -> int:
        return hit_code(lx, ly, self.regions)

    @property
    def pinned(self) -> bool:
        s = self.app.settings
        return bool(s.efir_pinned if self.compact else s.always_on_top)

    def on_top(self) -> bool:
        h = self.windowHandle()
        if h is not None:
            return bool(h.flags() & Qt.WindowType.WindowStaysOnTopHint)
        return bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

    def apply_pin(self) -> None:
        """Поверх всех окон — без пересоздания окна (иначе оно мигает и теряет кнопку на панели задач)."""
        on = self.pinned
        h = self.windowHandle()
        if h is not None:
            h.setFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        else:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)

    def window_cmd(self, op: str, arg=None) -> None:
        s = self.app.settings
        if op == "min":
            self.showMinimized()
        elif op == "max":
            self.showMaximized()
        elif op == "restore":
            self.showNormal()
        elif op == "toggle_max":
            self.showNormal() if self.isMaximized() else self.showMaximized()
        elif op == "close":
            self.close()
        elif op == "pin":
            if self.compact:
                s.efir_pinned = not s.efir_pinned
            else:
                s.always_on_top = not s.always_on_top
            self.apply_pin()
        elif op == "compact":
            self.set_compact(not self.compact if arg is None else bool(arg))
        elif op == "compact_size":
            self.compact_size(arg)
        elif op == "move":
            h = self.windowHandle()
            if h is not None and QGuiApplication.mouseButtons() & Qt.MouseButton.LeftButton:
                h.startSystemMove()

    # ------------------------------------------------------------ закрытие и панель задач
    close_handler = None          # App.on_window_close: в трей или выход

    def closeEvent(self, e) -> None:
        if self.close_handler is not None:
            self.close_handler(e)
            if not e.isAccepted():
                return
        super().closeEvent(e)

    def set_taskbar_icon(self, icon_path: str) -> None:
        """Своя иконка и имя на панели задач (иначе Windows покажет «Python»)."""
        self._taskbar_icon = icon_path
        self._apply_taskbar()

    def _apply_taskbar(self) -> None:
        path = getattr(self, "_taskbar_icon", "")
        if path:
            from .. import taskbar
            taskbar.apply_to_window(int(self.winId()), path, APP_NAME)

    def event(self, e) -> bool:
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.Type.WinIdChange:
            QTimer.singleShot(0, self._apply_taskbar)
        return super().event(e)

    # ------------------------------------------------------------ маленький режим
    def _set_maximized(self, on: bool) -> None:
        """Развернуть или вернуть; скрытое окно (запуск в трей) при этом не показывается."""
        if self.isVisible():
            self.showMaximized() if on else self.showNormal()
            return
        st = self.windowState()
        self.setWindowState(st | Qt.WindowState.WindowMaximized if on else st & ~Qt.WindowState.WindowMaximized)

    def place_default(self) -> None:
        """Первый запуск (размера ещё нет): большое окно — не больше рабочей области экрана и по центру."""
        scr = self.screen() or QGuiApplication.primaryScreen()
        if scr is None:
            return
        av = scr.availableGeometry()
        w = max(min(BIG_SIZE.width(), av.width() - 40), min(BIG_MIN.width(), av.width()))
        h = max(min(BIG_SIZE.height(), av.height() - 40), min(BIG_MIN.height(), av.height()))
        self.setGeometry(av.x() + (av.width() - w) // 2, av.y() + (av.height() - h) // 2, w, h)

    def compact_rect(self) -> QRect:
        """Где стоит маленькое окно: запомненное место, иначе 360×600 у правого края экрана по середине."""
        scr = self.screen() or QGuiApplication.primaryScreen()
        avail = scr.availableGeometry() if scr is not None else QRect(0, 0, 1280, 800)
        size = QSize(min(COMPACT_SIZE.width(), avail.width()), min(COMPACT_SIZE.height(), avail.height()))
        x = avail.right() - size.width() - 16
        y = avail.top() + max(0, (avail.height() - size.height()) // 2)
        return QRect(max(avail.left(), x), y, size.width(), size.height())

    def compact_size(self, arg) -> None:
        """Вид маленького режима из меню страницы: {w, h} в пикселях страницы (× масштаб окна). Правый верхний угол
        остаётся на месте (окно обычно у правого края), окно — в пределах экрана."""
        if not self.compact or not isinstance(arg, dict):
            return
        try:
            cw, ch = int(arg.get("w")), int(arg.get("h"))
        except (TypeError, ValueError):
            return
        if not (100 <= cw <= 4000 and 50 <= ch <= 3000):
            return
        k = max(80, min(200, int(self.app.settings.page_zoom or 100))) / 100
        g = self.geometry()
        scr = self.screen() or QGuiApplication.primaryScreen()
        av = scr.availableGeometry() if scr is not None else QRect(0, 0, 1280, 800)
        w = max(COMPACT_MIN.width(), min(round(cw * k), av.width()))
        h = max(COMPACT_MIN.height(), min(round(ch * k), av.height()))
        x = max(av.left(), min(g.right() + 1 - w, av.right() + 1 - w))
        y = max(av.top(), min(g.top(), av.bottom() + 1 - h))
        self.setGeometry(x, y, w, h)

    def set_compact(self, on: bool) -> None:
        if on == self.compact:
            return
        s = self.app.settings
        if on:
            self._big_geometry = self.saveGeometry()
            self._big_maximized = self.isMaximized()
            if self._big_maximized:
                self._set_maximized(False)
            self.compact = True
            self.setMinimumSize(COMPACT_MIN)
            if s.compact_geometry:
                self.restoreGeometry(QByteArray.fromBase64(s.compact_geometry.encode()))
            else:
                self.setGeometry(self.compact_rect())
        else:
            s.compact_geometry = bytes(self.saveGeometry().toBase64()).decode()
            self.compact = False
            self.setMinimumSize(BIG_MIN)
            if self._big_geometry is not None:
                self.restoreGeometry(self._big_geometry)
            if self._big_maximized:
                self._set_maximized(True)
        s.compact = self.compact
        self.apply_pin()


def selftest(timeout_s: float = 30.0) -> int:
    """`AutoPrintCode.exe --selftest`: невидимо (offscreen) загрузить окно программы. 0 — страница загрузилась."""
    import sys
    import tempfile
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("AUTOPRINT_DATA", tempfile.mkdtemp(prefix="autoprint-selftest-"))
    import PySide6.QtWebEngineWidgets  # noqa: F401  — до QApplication
    from PySide6.QtWidgets import QApplication
    from ..efir.server import BroadcastServer
    from ..storage import Settings

    class _App:
        def __init__(self) -> None:
            self.settings = Settings()
            self.server = BroadcastServer()

            class _E:
                pass
            self.efir = _E()
            self.efir.server = self.server

    qa = QApplication.instance() or QApplication(sys.argv[:1])
    fake = _App()
    fake.server.start()
    w = AppWindow(fake, web=True)
    result = {"code": 1}

    def done() -> None:
        result["code"] = 0
        qa.quit()

    w.ready.connect(done)
    w.page_failed.connect(lambda _t: qa.quit())
    QTimer.singleShot(int(timeout_s * 1000), qa.quit)
    w.load()
    qa.exec()
    fake.server.stop()
    print("selftest:", "ok" if result["code"] == 0 else "fail", flush=True)
    return result["code"]
