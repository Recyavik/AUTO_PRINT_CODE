"""Суфлёр урока: страница в браузере (http://127.0.0.1:8791/lesson) и её связь с программой.

Контроллер собирает состояние страницы (урок по этапам, идёт ли он, какой код печатается следующим) и отдаёт
его серверу «Эфира» на канал lesson; команды со страницы (начать урок, начать с этапа, печатать этот блок,
перерыв, зарядка…) приходят сюда. Показывается урок, идущий в «Эфире», иначе — открытый в программе.
Время урока — эфир по его этапам (EfirController.launch_lesson): таймер, плашка «Эфир», перерыв, зарядка.
"""
from __future__ import annotations

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

    def __init__(self, main) -> None:
        super().__init__(main)
        self.main = main
        self.efir = main.efir
        self.efir.server.on_command = self._cmd.emit
        self._cmd.connect(self.command)
        self._timer = QTimer(self, singleShot=True, interval=300, timeout=self.publish)
        self._last = ""          # что ушло на страницу в последний раз: то же самое второй раз не шлём
        for sig in (self.efir.live_changed, self.efir.screen_changed, self.efir.tab_changed,
                    self.efir.webinars_changed, theme.changed):
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
        lid = self.efir.live_lesson_id()
        t = self.main.store.get(lid) if lid else None
        if t is not None:
            return t
        v = self.main.current_view()
        return v.template if v is not None else None

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
        preset = self.efir.lesson_preset(t) if t is not None else None
        state = scenario.lesson_state(
            t, live_anchor_ms=anchor, armed=t.active_block if t is not None else "",
            media_url=self.efir.server.media_url, presets=[(w.id, w.title) for w in self.efir.store.visible()],
            preset=preset.id if preset is not None else "", dark=theme.dark, efir_mode=self.efir.mode,
            tab=self.efir.tab_status()[0], hotkey=self.main.settings.hotkey_toggle)
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
            elif cmd == "exercise" and t is not None:
                self._ensure_screen(t)
                self.efir.start_exercise(int(d.get("index") or 0))
            elif cmd == "background":
                self.efir.show_background()
            elif cmd == "preset" and t is not None:
                self._set_preset(t, str(d.get("id") or ""))
            elif cmd == "set_start" and t is not None:
                self._set_start(t, str(d.get("start") or "").strip())
        except (TypeError, ValueError) as e:
            log.warning("Команда суфлёра %r не выполнена: %s", d, e)
        self.schedule_publish()

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
        if not t.find_block(bid):
            return
        v = self.main.open_template(t.id)
        if v is not None:
            v.go_to_block(bid)
            self.main._update_armed_label()

    def _ensure_screen(self, t: Template) -> None:
        """Перерыв или зарядка до «Начать урок»: оформление экрана — из пресета урока."""
        if self.efir.webinar is None:
            self.efir.webinar = scenario.webinar_for(t, self.efir.lesson_preset(t))

    def _set_start(self, t: Template, start: str) -> None:
        """Начало урока «ЧЧ:ММ»: идёт урок — его время сдвигается; не идёт — запоминается для «Начать в…»."""
        if start and not parse_hhmm(start):
            return
        start = norm_hhmm(start)
        t.start = start
        self.main._save_timer.start()
        if self.efir.live_lesson_id() == t.id and start:
            self.efir.set_start(start)

    def _set_preset(self, t: Template, wid: str) -> None:
        w = self.efir.store.get(wid)
        if w is None or w.lesson_id:
            return
        t.preset = wid
        self.main.settings.lesson_preset = wid
        self.main._settings_timer.start()
        self.main._save_timer.start()
        if self.efir.live_lesson_id() == t.id:
            self.efir.launch_lesson(t, show=False)      # оформление идущего урока — сразу
