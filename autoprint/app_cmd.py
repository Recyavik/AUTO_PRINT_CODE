"""Команды страницы окна программы: POST /app/cmd (без ответа) и POST /app/call (с ответом).

Приходят в потоке сервера; выполняются в потоке интерфейса (уроки, окно и настройки меняет только он). /app/call
ждёт результата — окно выбора файла может быть открыто, пока человек выбирает (до 10 минут).
"""
from __future__ import annotations

import concurrent.futures
import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QFileDialog

log = logging.getLogger(__name__)

CALL_TIMEOUT_S = 600

# окна выбора файла: назначение → (заголовок, фильтр, несколько файлов)
PICK = {
    "import": ("Импорт урока", None, True),
    "material": ("Материал урока", "Методички, презентации и код (*.pdf *.docx *.pptx *.txt *.md *.py *.ipynb *.html "
                 "*.js *.css *.json);;Все файлы (*.*)", False),
    "image": ("Картинка", "Картинки (*.png *.jpg *.jpeg *.gif *.webp);;Все файлы (*.*)", False),
    "video": ("Видео зарядки", "Видео (*.mp4 *.webm *.mov *.m4v);;Все файлы (*.*)", True),
    "presentation": ("Презентация — для картинок слайдов", "Презентация (*.pdf *.pptx)", False),
    "json": ("Файл JSON", "JSON (*.json);;Все файлы (*.*)", False),
    "font": ("Свой файл шрифта", "Шрифты (*.ttf *.otf *.woff *.woff2)", False),
    "background": ("Картинка для фона", "Картинки (*.png *.jpg *.jpeg *.gif *.webp)", False),
}


class AppCommands(QObject):
    _cmd = Signal(dict)
    _call = Signal(object)        # (данные, Future)

    def __init__(self, app) -> None:
        super().__init__(app)
        self.app = app
        server = app.efir.server
        server.on_app_cmd = self._cmd.emit
        server.on_app_call = self._call_from_server
        self._cmd.connect(self.handle)
        self._call.connect(self._do_call)

    # ------------------------------------------------------------ из потока сервера
    def _call_from_server(self, d: dict) -> tuple[int, dict]:
        fut: concurrent.futures.Future = concurrent.futures.Future()
        self._call.emit((d, fut))
        try:
            return 200, fut.result(CALL_TIMEOUT_S)
        except concurrent.futures.TimeoutError:
            return 503, {"ok": False, "error": "Программа не ответила вовремя"}

    def _do_call(self, pair) -> None:
        d, fut = pair
        if not fut.set_running_or_notify_cancel():
            return
        try:
            fut.set_result(self.call(d))
        except Exception as e:      # noqa: BLE001 — ответить странице, а не уронить сервер
            log.exception("Вызов окна %r", d.get("cmd") if isinstance(d, dict) else d)
            fut.set_result({"ok": False, "error": str(e) or type(e).__name__})

    # ------------------------------------------------------------ команды без ответа
    def handle(self, d: dict) -> None:
        if not isinstance(d, dict):
            return
        cmd = str(d.get("cmd") or "")
        fn = getattr(self, "cmd_" + cmd, None) if cmd.isidentifier() else None
        if fn is None:
            log.warning("Неизвестная команда окна: %r", cmd)
            return
        try:
            fn(d)
        except (TypeError, ValueError, KeyError) as e:
            log.warning("Команда окна %r не выполнена: %s", d, e)

    def cmd_window(self, d: dict) -> None:
        op = str(d.get("op") or "")
        if op == "regions":
            self.app.window.set_regions(d)
        else:
            self.app.window.window_cmd(op, d.get("arg"))
            self.app.changed.emit("window")

    def cmd_prefs(self, d: dict) -> None:
        self.app.lesson._set_pref(str(d.get("key") or ""), d.get("value"))
        self.app.changed.emit("settings")

    def cmd_quit(self, _d: dict) -> None:
        self.app.quit_app()

    def cmd_update_open(self, _d: dict) -> None:
        self.app.open_update_dialog()

    def cmd_notice_action(self, d: dict) -> None:
        """Кнопка в тосте: повторить команду из уведомления (например, «Завершить и открыть»)."""
        act = (self.app.notice or {}).get("action") or {}
        inner = act.get("cmd") if isinstance(act, dict) else None
        if isinstance(inner, dict) and int(d.get("seq") or -1) == self.app.notice.get("seq"):
            if inner.get("cmd") == "open":
                self.app.open_lesson(str(inner.get("lesson") or ""), ask=not inner.get("force"))
            else:
                self.handle(inner)

    # ------------------------------------------------------------ вызовы с ответом
    def call(self, d: dict) -> dict:
        if not isinstance(d, dict):
            return {"ok": False, "error": "Неверный запрос"}
        cmd = str(d.get("cmd") or "")
        fn = getattr(self, "call_" + cmd, None) if cmd.isidentifier() else None
        if fn is None:
            return {"ok": False, "error": f"Неизвестная команда: {cmd}"}
        return {"ok": True, "result": fn(d)}

    def call_ping(self, _d: dict):
        return "pong"

    def call_pick_files(self, d: dict) -> list[str]:
        """Системное окно выбора файлов поверх окна программы → пути (пусто — передумали)."""
        from .importers import FILE_FILTER
        title, flt, multi = PICK.get(str(d.get("purpose") or "import"), PICK["import"])
        flt = str(d.get("filter") or flt or FILE_FILTER)
        if "multi" in d:
            multi = bool(d["multi"])
        if multi:
            paths, _ = QFileDialog.getOpenFileNames(self.app.window, title, str(d.get("dir") or ""), flt)
            return [str(p) for p in paths]
        path, _ = QFileDialog.getOpenFileName(self.app.window, title, str(d.get("dir") or ""), flt)
        return [str(path)] if path else []

    def call_pick_save(self, d: dict) -> str:
        """Куда сохранить: системное окно → путь или "" (передумали)."""
        name = "".join(c for c in str(d.get("name") or "") if c not in '\\/:*?"<>|').strip()
        path, _ = QFileDialog.getSaveFileName(self.app.window, str(d.get("title") or "Сохранить"), name,
                                              str(d.get("filter") or "Все файлы (*.*)"))
        return str(path or "")
