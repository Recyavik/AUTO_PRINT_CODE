"""Суфлёр урока: страница в браузере (http://127.0.0.1:8791/lesson) и её связь с программой.

Контроллер собирает состояние страницы (урок по этапам, идёт ли он, какой код печатается следующим) и отдаёт
его серверу «Эфира» на канал lesson; команды со страницы (начать урок, начать с этапа, печатать этот блок,
перерыв, зарядка…) приходят сюда. Показывается урок, идущий в «Эфире», иначе — открытый в программе.
Время урока — эфир по его этапам (EfirController.launch_lesson): таймер, плашка «Эфир», перерыв, зарядка.
"""
from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices

from .. import scenario
from ..efir.model import norm_hhmm, parse_hhmm
from ..storage import Template
from .theme import theme

log = logging.getLogger(__name__)


def _edge_path() -> str | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            p = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if p.is_file():
                return str(p)
    return None


class PrompterWindow:
    """Окно суфлёра — Edge без вкладок и адресной строки, со своим профилем (не смешивается с браузером
    человека, его не перепутать с вкладкой, которую захватывают в демонстрации). Окно одно: повторное
    «Суфлёр урока» поднимает его; программа завершается — окно закрывается вместе с ней."""

    def __init__(self, profile_dir: Path, popen=subprocess.Popen, edge=_edge_path, find_window=None,
                 raise_window=None) -> None:
        from .. import winapi
        self.profile_dir = Path(profile_dir)
        self._popen, self._edge = popen, edge
        self._find = find_window or winapi.find_process_window
        self._raise = raise_window or winapi.raise_window
        self.proc = None

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def open(self, url: str) -> bool:
        """True — окно показано (поднято или открыто); False — Edge нет, пусть откроется браузер по умолчанию."""
        if self.alive():
            hwnd = self._find(self.proc.pid)
            if hwnd:
                self._raise(hwnd)
                return True
        edge = self._edge()
        if not edge:
            return False
        try:
            proc = self._popen([edge, f"--app={url}", f"--user-data-dir={self.profile_dir}", "--no-first-run",
                                "--no-default-browser-check", "--window-size=1000,1000"], close_fds=True,
                               creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        except OSError as e:
            log.warning("Edge не запустился: %s", e)
            return False
        if not self.alive():
            self.proc = proc          # главный процесс профиля; повторный запуск лишь передаёт ему адрес
            from .. import winapi
            winapi.own_pids.add(proc.pid)    # в окно экрана урока печатать нельзя (E13)
        return True

    def close(self) -> None:
        if self.alive():
            try:
                self.proc.terminate()
            except OSError as e:
                log.warning("Окно суфлёра не закрылось: %s", e)
        self.proc = None


_window: PrompterWindow | None = None


def prompter_window() -> PrompterWindow:
    global _window
    if _window is None:
        from ..storage import DATA_DIR
        _window = PrompterWindow(DATA_DIR / "edge-suflor")
    return _window


def launch_app_window(url: str) -> bool:
    return prompter_window().open(url)


def close_app_window() -> None:
    if _window is not None:
        _window.close()


class LessonController(QObject):
    _cmd = Signal(dict)          # из потока сервера → в поток интерфейса
    _call = Signal(object)       # (функция, Future) — выполнить в потоке интерфейса и вернуть результат

    def __init__(self, main) -> None:
        super().__init__(main)
        self.main = main
        self.efir = main.efir
        self.efir.server.on_command = self._cmd.emit
        self.efir.server.on_edit = self._edit_from_server
        self.efir.server.on_upload = self._upload_from_server
        self._cmd.connect(self.command)
        self._call.connect(self._do_call)
        self.edits = 0           # сколько правок со страницы применено — страница знает, какие уже в состоянии
        self._timer = QTimer(self, singleShot=True, interval=300, timeout=self.publish)
        self._last = ""          # что ушло на страницу в последний раз: то же самое второй раз не шлём
        for sig in (self.efir.live_changed, self.efir.screen_changed, self.efir.tab_changed,
                    self.efir.webinars_changed, theme.changed, main.printer.changed):
            sig.connect(self.schedule_publish)
        self.efir.webinars_changed.connect(self._restyle_live)

    def _restyle_live(self) -> None:
        """Шаблоны «Эфира» поменялись (например, правили оформление урока) — идущий урок берёт его сразу."""
        lid = self.efir.live_lesson_id()
        t = self.main.store.get(lid) if lid else None
        if t is not None:
            self.efir.launch_lesson(t, show=False)

    # ------------------------------------------------------------ что показывать
    @property
    def url(self) -> str:
        return self.efir.url + "lesson"

    def current(self) -> Template | None:
        """Урок экрана урока — урок в фокусе печати: идущий, иначе открытый."""
        return self.main.printer.focus()

    def page_alive(self) -> bool:
        return _window is not None and _window.alive()

    def schedule_publish(self) -> None:
        """Отправить состояние странице не позже чем через 300 мс после первого изменения. Уже ждём — не
        начинать заново: иначе частые сигналы (вкладка, экран, правки) откладывали бы отправку без конца,
        и правка идущего урока доходила бы до таймера с опозданием. Отправляется то, что есть к моменту отправки."""
        if not self._timer.isActive():
            self._timer.start()

    def publish(self) -> None:
        t = self.current()
        live = self.efir.store.live
        anchor = None
        if t is not None and live is not None and self.efir.live_lesson_id() == t.id:
            anchor = int(live.anchor.timestamp() * 1000)
            self._sync_live(t)
        preset = self.efir.lesson_look(t) if t is not None else None
        state = scenario.lesson_state(
            t, live_anchor_ms=anchor, armed=t.active_block if t is not None else "",
            media_url=self.efir.server.media_url, presets=[(lk.id, lk.title) for lk in self.efir.store.looks],
            preset=preset.id if preset is not None else "", dark=theme.dark, efir_mode=self.efir.mode,
            tab=self.efir.tab_status()[0], hotkey=self.main.settings.hotkey_toggle,
            printer=self.main.printer.snapshot(), lessons=scenario.lessons_state(self.main.store.templates),
            exercises=bool(preset is not None and preset.exercises), edits=self.edits)
        # во время зарядки экран эфира шлёт ход видео раз в секунду: странице суфлёра от этого ничего не
        # меняется — не перерисовывать её (иначе пересоздаются кнопки и теряются щелчки)
        key = json.dumps(state, ensure_ascii=False, sort_keys=True)
        if key == self._last:
            return
        self._last = key
        self.efir.server.publish(state, channel="lesson")

    def _sync_live(self, t: Template) -> None:
        """Урок идёт, а его этапы поправили — обновить расписание таймера (время урока не сбивается)."""
        w = self.efir.live_webinar()
        now = [(a.name, a.min, a.kind) for a in w.schedule] if w else []
        want = [(a.name, a.min, a.kind) for a in scenario.webinar_for(t).schedule]
        if want and now != want:
            self.efir.launch_lesson(t, show=False)

    # ------------------------------------------------------------ правки урока со страницы
    def _do_call(self, pair) -> None:
        fn, fut = pair
        if not fut.set_running_or_notify_cancel():
            return
        try:
            fut.set_result(fn())
        except BaseException as e:      # ошибку — в поток сервера, он ответит странице
            fut.set_exception(e)

    def _in_ui(self, fn, timeout: float = 3.0):
        """Из потока сервера: выполнить fn в потоке интерфейса (урок меняет только он) и дождаться результата."""
        fut: concurrent.futures.Future = concurrent.futures.Future()
        self._call.emit((fn, fut))
        return fut.result(timeout)

    def _edit_from_server(self, data: dict) -> tuple[int, dict]:
        try:
            return 200, self._in_ui(lambda: self.apply_edit(data))
        except concurrent.futures.TimeoutError:
            return 503, {"ok": False, "retry": True}
        except ValueError as e:
            return 400, {"ok": False, "error": str(e)}

    def _upload_from_server(self, data: dict) -> tuple[int, dict]:
        try:
            return 200, self._in_ui(lambda: self.add_image(data), timeout=10.0)
        except concurrent.futures.TimeoutError:
            return 503, {"ok": False, "retry": True}
        except ValueError as e:
            return 400, {"ok": False, "error": str(e)}

    def _lesson_for_edit(self, lid: str) -> Template:
        t = self.main.store.get(str(lid or ""))
        if t is None:
            raise ValueError("Урок не найден — его удалили?")
        return t

    def _after_edit(self, t: Template, ids: list[str]) -> dict:
        self.edits += 1
        self.main.printer.on_store_changed()
        self.main.touch(t)
        self.schedule_publish()
        media = self.efir.server.media_url
        items = {}
        for bid in ids:
            b = t.find_block(bid)
            items[bid] = scenario.item_state(b, media) if b is not None else None
        return {"ok": True, "rev": scenario.lesson_rev(t), "items": items, "title": t.title, "edits": self.edits}

    def apply_edit(self, data: dict) -> dict:
        """Правка со страницы (поток интерфейса): действия над уроком → новые версии и HTML затронутых блоков."""
        from .. import lesson_edit
        t = self._lesson_for_edit(data.get("lesson"))
        ids = lesson_edit.apply(t, data.get("ops"))
        return self._after_edit(t, ids)

    def add_image(self, data: dict) -> dict:
        """Картинка со страницы (Ctrl+V, перетаскивание): копия в data/media и блок-картинка после after."""
        import tempfile
        from .. import lesson_edit
        from ..storage import import_media, new_id
        t = self._lesson_for_edit(data.get("lesson"))
        bid = str(data.get("id") or "")
        if bid and t.find_block(bid):
            return self._after_edit(t, [bid])            # повтор после обрыва связи
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / f"paste{data['ext']}"
            src.write_bytes(data["data"])
            ref = import_media(src)
        bid = bid or new_id()
        lesson_edit.apply(t, [{"op": "insert", "after": str(data.get("after") or ""),
                               "block": {"id": bid, "type": "image", "text": ref}}])
        res = self._after_edit(t, [bid])
        res["item"] = res["items"][bid]
        return res

    # ------------------------------------------------------------ страница
    def shutdown(self) -> None:
        close_app_window()

    def open_page(self) -> None:
        if not self.efir.ensure_server():
            return
        self.publish()
        if not launch_app_window(self.url):
            QDesktopServices.openUrl(QUrl(self.url))

    # ------------------------------------------------------------ команды со страницы
    def command(self, d: dict) -> None:
        if not isinstance(d, dict):
            return
        cmd = str(d.get("cmd") or "")
        t = self.current()
        try:
            if cmd == "start" and t is not None:
                at = str(d.get("at") or "").strip()
                if not at or parse_hhmm(at):         # неверное время — ничего не делаем
                    if at:
                        t.start = norm_hhmm(at)          # запомнить — подставится в следующий раз
                        self.main._save_timer.start()
                    self.efir.launch_lesson(t, start=at)
            elif cmd == "stop":
                if self.efir.live_lesson_id():
                    self.efir.stop_live()
            elif cmd == "shift_now" and t is not None:
                self._start_stage_now(t, self._current_stage(t))
            elif cmd == "start_at" and t is not None:
                self._start_stage_now(t, int(d.get("index")))
            elif cmd == "arm" and t is not None:
                self._arm(t, str(d.get("block") or ""))
            elif cmd == "break" and t is not None:
                self._ensure_screen(t)
                self.efir.start_break(int(d.get("minutes") or 10))
            elif cmd == "print_settings":
                self.main.printer.set_option(str(d.get("key") or ""), d.get("value"))
            elif cmd == "new_lesson":
                self._new_lesson(bool(d.get("force")))
            elif cmd == "delete_lesson" and t is not None:
                self.main.delete_lesson(t, ask=False)
            elif cmd == "export" and t is not None and d.get("fmt") in ("md", "ipynb", "students", "json"):
                self.main.export_template(t, str(d["fmt"]))
            elif cmd == "settings":
                self.main.open_settings(str(d.get("page") or ""))
            elif cmd == "exercise" and t is not None:
                self._ensure_screen(t)
                self.efir.start_exercise(int(d.get("index") or 0))
            elif cmd == "background":
                self.efir.show_background()
            elif cmd == "preset" and t is not None:
                self._set_preset(t, str(d.get("id") or ""))
            elif cmd == "set_start" and t is not None:
                self._set_start(t, str(d.get("start") or "").strip())
            elif cmd == "open":
                self.main.open_lesson(str(d.get("lesson") or ""), ask=not d.get("force"))
        except (TypeError, ValueError) as e:
            log.warning("Команда суфлёра %r не выполнена: %s", d, e)
        self.schedule_publish()

    def _new_lesson(self, force: bool) -> None:
        """«Новый урок» со страницы: идёт урок — его завершают (страница уже спросила)."""
        if self.efir.live_lesson_id():
            if not force:
                return
            self.efir.stop_live()
        nt = self.main.store.add("Новый урок")
        self.main.touch(nt)
        self.main._fill_library(nt.id)
        self.main.open_lesson(nt.id, ask=False)

    def _current_stage(self, t: Template) -> int:
        """Номер этапа, который идёт сейчас (до начала — первый, после конца — последний)."""
        live = self.efir.store.live
        stages = scenario.stages(t)[1]
        if not stages or live is None or self.efir.live_lesson_id() != t.id:
            return 0
        elapsed = (datetime.now() - live.anchor).total_seconds() / 60
        for s in stages:
            if s.start_min <= elapsed < s.end_min:
                return s.index
        return 0 if elapsed < 0 else stages[-1].index

    def _start_stage_now(self, t: Template, index: int) -> None:
        stages = scenario.stages(t)[1]
        if not 0 <= index < len(stages):
            return
        if self.efir.live_lesson_id() != t.id and not self.efir.launch_lesson(t):
            return
        anchor = datetime.now().replace(microsecond=0) - timedelta(minutes=stages[index].start_min)
        self.efir.store.set_live(self.efir.store.live.webinar_id, anchor)
        self.efir.live_changed.emit()

    def _arm(self, t: Template, bid: str) -> None:
        self.main.printer.arm(bid)       # только код: заметку или картинку печатать нельзя

    def _ensure_screen(self, t: Template) -> None:
        """Перерыв или зарядка до «Начать урок»: оформление экрана — из пресета урока."""
        if self.efir.webinar is None:
            self.efir.webinar = scenario.webinar_for(t, self.efir.lesson_look(t))

    def _set_start(self, t: Template, start: str) -> None:
        """Начало урока «ЧЧ:ММ»: идёт урок — его время сдвигается; не идёт — запоминается для «Начать в…»."""
        if start and not parse_hhmm(start):
            return
        start = norm_hhmm(start)
        t.start = start
        self.main._save_timer.start()
        if self.efir.live_lesson_id() == t.id and start:
            self.efir.set_start(start)

    def _set_preset(self, t: Template, lid: str) -> None:
        """Оформление экрана эфира для урока (Template.look; preset 0.9 не трогаем — откат)."""
        if self.efir.store.look(lid) is None:
            return
        t.look = lid
        self.main.settings.lesson_look = lid
        self.main._settings_timer.start()
        self.main._save_timer.start()
        if self.efir.live_lesson_id() == t.id:
            self.efir.launch_lesson(t, show=False)      # оформление идущего урока — сразу
