"""«Эфир»: что сейчас на экране эфира (вкладке браузера) и команды к нему.

Экран — три состояния: фон (он же занавес), зарядка (видео), перерыв (заставка с отсчётом). Контроллер держит
состояние, отдаёт его странице через BroadcastServer и получает от страницы отчёты (подключилась, звук
разрешён, ход видео, видео кончилось). Окна — EfirWindow (шаблоны), TimerWindow (таймер эфира), редактор.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QMessageBox, QWidget

from ..efir import legacy
from ..efir.model import Webinar, agenda_at, anchor_at, anchor_to_start_at, norm_hhmm, parse_hhmm, segments
from ..efir.server import DEFAULT_PORT, BroadcastServer
from ..efir.store import WebinarStore

log = logging.getLogger(__name__)

MODE_IDLE, MODE_EXERCISE, MODE_BREAK, MODE_SLIDE = "idle", "exercise", "break", "slide"
KEEP_LIVE_AFTER_END = timedelta(minutes=30)    # после конца повестки эфир ещё восстанавливается при запуске
BREAK_HOLD_S = 60          # «когда время вышло» на экране — столько секунд, потом экран сам возвращается к фону
TAB_REOPEN_S = 30          # сами открыли вкладку экрана учеников — столько секунд ждём, пока она подключится


class EfirController(QObject):
    screen_changed = Signal()       # что на экране эфира (режим, перерыв, ход видео)
    tab_changed = Signal()          # вкладка эфира: подключена ли, разрешён ли звук
    live_changed = Signal()         # эфир начат / завершён / сдвинут
    webinars_changed = Signal()
    picked = Signal(str)            # фон выбран в галерее
    message = Signal(str, bool)     # текст, предупреждение
    screen_key = Signal(str)        # кликер нажали на вкладке учеников (◀ ▶, PageUp / PageDown, B) — уроку
    _report = Signal(dict)          # из потока сервера → в поток интерфейса
    _pick = Signal(dict)

    def __init__(self, main) -> None:
        super().__init__(main)
        self.main = main
        self.store = WebinarStore()
        self.settings = getattr(main, "settings", None)
        port = getattr(self.settings, "efir_port", DEFAULT_PORT)
        self.server = BroadcastServer(port or DEFAULT_PORT, on_report=self._report.emit, on_pick=self._pick.emit)
        self._report.connect(self._on_report)
        self._pick.connect(lambda d: self.picked.emit(str(d.get("background", ""))))
        self.mode = MODE_IDLE
        self.webinar: Webinar | None = None
        # зарядка
        self.ex_index = -1
        self.ex_seq = 0
        self.ex_restart = 0
        self.ex_paused = False
        self.video_pos = 0.0
        self.video_dur = 0.0
        self.video_error = ""
        # перерыв (время — time.time(), секунды)
        self.brk_seq = 0
        self.brk_ends = 0.0
        self.slide: dict | None = None     # слайд у учеников: {"ref", "next", "n", "bid"}
        self.brk_left_paused: float | None = None
        self.brk_total = 600.0
        # вкладка
        self.clients = 0
        self._tab_opened_at = -1e9       # когда сами открыли вкладку экрана учеников (ensure_tab)
        self.unlocked = False
        self.blocked = False
        self.timer_window = None
        self.window = None
        self.editors: list = []
        self._ticker = QTimer(self)
        self._ticker.setInterval(5000)
        self._ticker.timeout.connect(self._tick)
        self._ticker.start()

    # ================================================================ сервер и вкладка
    def ensure_server(self) -> bool:
        if self.server.running:
            return True
        ok = self.server.start()
        if not ok:
            self.message.emit("Экран эфира не запустился: порты 8791–8799 заняты другой программой", True)
        return ok

    @property
    def url(self) -> str:
        return self.server.url or f"http://127.0.0.1:{self.server.want_port}/"

    def open_tab(self) -> None:
        if self.ensure_server():
            QDesktopServices.openUrl(QUrl(self.server.url))

    def ensure_tab(self) -> bool:
        """Перерыв, зарядка или слайд ученикам, а вкладки экрана учеников нигде нет — открыть её самим (не говорить
        «не открыта»). Только что открыли (вкладка ещё подключается) — второй раз не открываем. → открыли сейчас."""
        if self.clients > 0 or time.monotonic() - self._tab_opened_at < TAB_REOPEN_S:
            return False
        self._tab_opened_at = time.monotonic()
        self.open_tab()
        self.message.emit("Вкладка экрана учеников не была открыта — открыл её в браузере. Покажите её ученикам "
                          "(демонстрация этой вкладки).", False)
        return True

    def copy_url(self) -> None:
        if self.ensure_server():
            QGuiApplication.clipboard().setText(self.server.url)
            self.message.emit(f"Адрес вкладки эфира скопирован: {self.server.url}", False)

    def open_gallery(self, current: str = "") -> None:
        if self.ensure_server():
            QDesktopServices.openUrl(QUrl(self.server.url + "gallery?select=" + quote(current)))

    def tab_status(self) -> tuple[str, str]:
        """(текст, цвет-токен) состояния вкладки эфира."""
        if not self.server.running:
            return "Экран эфира выключен", "faint"
        if self.clients <= 0:
            return "Вкладка эфира не открыта", "faint"
        if self.blocked or not self.unlocked:
            return "Щёлкните по вкладке эфира один раз — для звука", "accent"
        return "Вкладка эфира на связи", "ok"

    def _on_report(self, d: dict) -> None:
        kind = d.get("type")
        if kind == "key":
            self.screen_key.emit(str(d.get("key") or "")[:20])
            return
        if kind == "clients":
            self.clients = int(d.get("count") or 0)
            if self.clients == 0:
                self.unlocked = False
            self.tab_changed.emit()
        elif kind == "hello":
            self.unlocked = bool(d.get("unlocked"))
            self.tab_changed.emit()
        elif kind == "unlock":
            self.unlocked, self.blocked = True, False
            self.tab_changed.emit()
        elif kind == "blocked":
            self.blocked = True
            self.tab_changed.emit()
            self.message.emit("Браузер не дал включить звук: щёлкните один раз по вкладке эфира — звук появится", True)
        elif kind == "video" and d.get("seq") == self.ex_seq and self.mode == MODE_EXERCISE:
            try:
                self.video_pos = float(d.get("pos") or 0)
                self.video_dur = float(d.get("dur") or 0)
            except (TypeError, ValueError):
                pass
            if not d.get("muted"):
                self.blocked = False
            self.screen_changed.emit()
        elif kind == "ended" and d.get("seq") == self.ex_seq and self.mode == MODE_EXERCISE:
            self.show_background()           # зарядка доиграла — снова фон
        elif kind == "video_error" and d.get("seq") == self.ex_seq:
            self.video_error = str(d.get("message") or "ошибка")
            self.message.emit(f"Видео зарядки не играет: {self.video_error}", True)
            self.screen_changed.emit()

    # ================================================================ состояние экрана → страница
    def _bg(self, spec: str) -> dict | None:
        if not spec:
            return None
        kind, _, value = spec.partition(":")
        if kind == "image":
            p = Path(value)
            if not p.is_file():
                return {"kind": "color", "value": "#000000"}
            return {"kind": "image", "value": p.name, "url": self.server.media_url(p)}
        if kind in ("color", "anim") and value:
            return {"kind": kind, "value": value}
        return {"kind": "color", "value": "#000000"}

    def _font(self, w: Webinar) -> dict:
        if w.font.startswith("file:"):
            p = Path(w.font[5:])
            if p.is_file():
                return {"family": p.stem, "url": self.server.media_url(p)}
            return {"family": "Montserrat"}
        return {"family": w.font}

    def state(self) -> dict:
        w = self.webinar
        if w is None:
            return {"mode": MODE_IDLE, "bg": {"kind": "color", "value": "#000000"}, "caption": ""}
        st = {"mode": self.mode, "bg": self._bg(w.background), "caption": w.caption, "font": self._font(w),
              "color": w.text_color}
        if self.mode == MODE_EXERCISE and 0 <= self.ex_index < len(w.exercises):
            ex = w.exercises[self.ex_index]
            st["exercise"] = {"seq": self.ex_seq, "restart": self.ex_restart, "paused": self.ex_paused,
                              "title": ex.title, "url": self.server.media_url(ex.path), "volume": 1.0}
        if self.mode == MODE_SLIDE and self.slide:
            st["slide"] = {"src": self._media(self.slide["ref"]), "next": self._media(self.slide.get("next", "")),
                           "n": self.slide.get("n", 0)}
        if self.mode == MODE_BREAK:
            st["brk"] = {"seq": self.brk_seq, "ends_at": int(self.brk_ends * 1000),
                         "paused_left": None if self.brk_left_paused is None else int(self.brk_left_paused * 1000),
                         "total": int(self.brk_total * 1000), "countdown": w.break_countdown,
                         "title": w.break_title if w.break_show_title else "", "done": w.break_done,
                         "bg": self._bg(w.break_background), "hold": BREAK_HOLD_S}
        return st

    def _media(self, ref: str) -> str:
        from ..storage import media_path
        if not ref:
            return ""
        if re.match(r"https?://", ref, re.I):
            return ref
        p = media_path(ref)
        return self.server.media_url(str(p)) if p is not None else ""

    def preview_break(self, w: Webinar) -> str:
        """Предпросмотр перерыва с настройками из редактора (ещё не сохранёнными) — отдельной вкладкой, на канале
        preview: настоящий экран эфира у учеников не меняется. Возвращает адрес вкладки."""
        if not self.ensure_server():
            return ""
        total = max(1, int(w.break_min)) * 60.0
        st = {"mode": MODE_BREAK, "bg": self._bg(w.background), "caption": "", "font": self._font(w),
              "color": w.text_color,
              "brk": {"seq": int(time.time()), "ends_at": int((time.time() + total) * 1000), "paused_left": None,
                      "total": int(total * 1000), "countdown": w.break_countdown,
                      "title": w.break_title if w.break_show_title else "", "done": w.break_done,
                      "bg": self._bg(w.break_background)}}
        self.server.publish(st, channel="preview")
        url = self.server.url + "?ch=preview"
        QDesktopServices.openUrl(QUrl(url))
        return url

    def publish(self) -> None:
        if self.server.running:
            self.server.publish(self.state())
        self.screen_changed.emit()

    # ================================================================ эфир (повестка)
    def live_webinar(self) -> Webinar | None:
        live = self.store.live
        return self.store.get(live.webinar_id) if live else None

    def segments(self):
        w, live = self.live_webinar(), self.store.live
        return segments(w, live.anchor) if w and live else []

    def agenda(self, now: datetime | None = None):
        return agenda_at(self.segments(), now or datetime.now())

    def confirm_replace(self, current: str, new: str) -> bool:
        """E9: идёт другой эфир — заменить его только с согласия."""
        r = QMessageBox.question(self._owner(), "Идёт эфир", f"Сейчас идёт «{current}». Завершить его и начать «{new}»?")
        return r == QMessageBox.StandardButton.Yes

    def _may_replace(self, new_id: str, new_title: str) -> bool:
        cur = self.live_webinar()
        if cur is None or cur.id == new_id:
            return True
        return self.confirm_replace(cur.title, new_title)

    def launch(self, wid: str, start: str | None = None) -> None:
        """Запустить эфир по шаблону. start: "" — сейчас, "ЧЧ:ММ" — в это время (запоминается в шаблоне как
        прошлое время старта), None — идущий эфир не трогать (иначе — сейчас)."""
        w = self.store.get(wid)
        if not w or not self._may_replace(w.id, w.title):
            return
        live = self.store.live
        now = datetime.now().replace(microsecond=0)
        if start is None and live and live.webinar_id == wid:
            anchor = live.anchor                                  # тот же эфир — не сбиваем «сдвинуть на сейчас»
        elif start and parse_hhmm(start):
            anchor = anchor_at(start, now)
            w.start = norm_hhmm(start)
            self.store.put(w)
        else:
            anchor = now
        self.store.set_live(wid, anchor)
        self.webinar = w
        self.ensure_server()
        self.publish()
        self.live_changed.emit()
        self.show_timer()

    def lesson_look(self, t):
        """Оформление эфира урока: своё (Template.look), иначе — оформление шаблона, выбранного в 0.9
        (Template.preset), иначе последнее выбранное, иначе первое."""
        st = self.store
        for lid in (getattr(t, "look", ""), getattr(self.settings, "lesson_look", "")):
            if lid and st.look(lid) is not None:
                return st.look(lid)
        for wid in (getattr(t, "preset", ""), getattr(self.settings, "lesson_preset", "")):
            w = st.get(wid) if wid else None
            if w is not None and st.look(w.look_id) is not None:
                return st.look(w.look_id)
        return st.looks[0] if st.looks else None

    lesson_preset = lesson_look

    def launch_lesson(self, t, start: str | None = None, show: bool = True, force: bool = False) -> bool:
        """Эфир по этапам урока из суфлёра. start: "" — сейчас, "ЧЧ:ММ" — в это время, None — тот же урок уже
        идёт — время не сбивается, только расписание обновляется (иначе — сейчас). False — нет этапов с минутами.
        force — замену идущего эфира уже подтвердили (на странице урока)."""
        from ..scenario import webinar_for
        w = webinar_for(t, self.lesson_look(t))
        if not w.schedule:
            self.message.emit("У урока нет этапов с минутами — эфир по нему не начать", True)
            return False
        if not force and not self._may_replace(w.id, w.title):
            return False
        live = self.store.live
        now = datetime.now().replace(microsecond=0)
        if start is None and live and live.webinar_id == w.id:
            anchor = live.anchor
        elif start and parse_hhmm(start):
            anchor = anchor_at(start, now)
        else:
            anchor = now
        w.start = anchor.strftime("%H:%M")
        self.store.drop_lesson_schedules(keep=w.id)      # служебные эфиры прошлых уроков больше не нужны
        w = self.store.put(w)
        self.store.set_live(w.id, anchor)
        self.webinar = w
        self.ensure_server()
        self.publish()
        self.live_changed.emit()
        if show:
            self.show_timer()
        return True

    def live_lesson_id(self) -> str:
        w = self.live_webinar()
        return w.lesson_id if w else ""

    def edit_live(self) -> None:
        """«Изменить…» в таймере. Идёт урок — правится его оформление (расписание урока — его этапы, их правят на
        экране урока); идёт вебинар — его расписание."""
        w = self.live_webinar()
        if w is None:
            return
        if not w.lesson_id:
            self.edit(w.id)
            return
        if not w.look_id or self.store.look(w.look_id) is None:
            self.message.emit("У урока нет оформления экрана эфира — создайте его в «Эфир → Оформления»", True)
            self.show_window()
            return
        self.edit_look(w.look_id)

    def refresh_live(self) -> None:
        """Шаблон идущего эфира поправили в редакторе — подхватить фон, зарядки, перерыв."""
        w = self.live_webinar()
        if w:
            self.webinar = w
            if self.mode == MODE_EXERCISE and self.ex_index >= len(w.exercises):
                self.mode = MODE_IDLE          # зарядку убрали из оформления; перерыв не трогаем (D4)
            self.publish()
            self.live_changed.emit()

    def stop_live(self) -> None:
        self.store.set_live(None)
        self.mode = MODE_IDLE
        self.publish()
        self.live_changed.emit()
        if self.timer_window is not None:
            tw, self.timer_window = self.timer_window, None
            tw.close_silently()

    def start_now(self, index: int | None = None) -> None:
        """«Этап заново с этой минуты»: блок index (по умолчанию — текущий, до начала — первый) начинается сейчас,
        следующие сдвигаются."""
        segs = self.segments()
        if not segs:
            return
        now = datetime.now()
        if index is None:
            ag = agenda_at(segs, now)
            index = ag.index if ag.phase == "live" else 0
        self.store.set_live(self.store.live.webinar_id, anchor_to_start_at(segs, index, now).replace(microsecond=0))
        self.live_changed.emit()

    def set_start(self, hhmm: str) -> None:
        """«Изменить начало…» идущего эфира: "" — с первого блока с этой минуты, "ЧЧ:ММ" — с этого времени."""
        w = self.live_webinar()
        if w is None or (hhmm and not parse_hhmm(hhmm)):
            return
        now = datetime.now().replace(microsecond=0)
        anchor = anchor_at(hhmm, now) if hhmm else now
        if hhmm:
            w.start = norm_hhmm(hhmm)
            self.store.put(w)
        self.store.set_live(w.id, anchor)
        self.live_changed.emit()

    def restore(self) -> None:
        """При запуске программы: эфир шёл (программу перезапустили) — вернуть таймер."""
        live, w = self.store.live, self.live_webinar()
        if not (live and w):
            if self.server.running:
                self.publish()               # эфира нет — фон вместо «ждать»
            return
        end = live.anchor + timedelta(minutes=w.total_min)
        if datetime.now() > end + KEEP_LIVE_AFTER_END or live.anchor.date() < datetime.now().date():
            self.store.set_live(None)
            return
        self.webinar = w
        self.ensure_server()
        brk = self.store.brk
        if brk and brk["ends_at"] + BREAK_HOLD_S > time.time():     # перерыв шёл — продолжить (E12)
            self.mode = MODE_BREAK
            self.brk_ends, self.brk_total, self.brk_seq = brk["ends_at"], brk["total"], brk["seq"] + 1
            self.brk_left_paused = None
        elif self.store.slide:                                      # слайд был у учеников — снова он
            self.mode, self.slide = MODE_SLIDE, dict(self.store.slide)
        self.publish()
        if not w.lesson_id or getattr(self.settings, "start_timer", True):
            self.show_timer()                       # урок ведут с экрана урока — мини-таймер только по настройке

    def _tick(self) -> None:
        """Раз в 5 с: «время вышло» перерыва постояло BREAK_HOLD_S — экран сам возвращается к фону (E6)."""
        if self.mode == MODE_BREAK and self.brk_left_paused is None and time.time() > self.brk_ends + BREAK_HOLD_S:
            self.show_background()

    def _forget_break(self) -> None:
        if self.store.brk is not None:
            self.store.set_break(None)
        if self.store.slide is not None:          # что угодно другое у учеников — слайда больше нет
            self.store.set_slide(None)
        self.slide = None

    def show_slide(self, ref: str, n: int, bid: str, next_ref: str = "") -> None:
        """Слайд презентации ученикам (по действию учителя: «На экран», ◀ ▶ кликера)."""
        if not (self.webinar or self.live_webinar()):
            return
        self.webinar = self.webinar or self.live_webinar()
        self.ensure_server()
        if self.mode == MODE_BREAK and self.store.brk is not None:
            self.store.set_break(None)
        self.slide = {"ref": ref, "next": next_ref, "n": n, "bid": bid}
        self.mode = MODE_SLIDE
        self.ex_paused = False
        if self.store.live is not None:
            self.store.set_slide(dict(self.slide))
        self.publish()

    # ================================================================ команды экрана
    def show_background(self) -> None:
        self.mode = MODE_IDLE
        self.ex_paused = False
        self._forget_break()
        self.publish()

    def start_exercise(self, index: int) -> None:
        w = self.webinar or self.live_webinar()
        if not w or not 0 <= index < len(w.exercises):
            return
        self.webinar = w
        if not Path(w.exercises[index].path).is_file():
            self.message.emit(f"Нет файла зарядки: {w.exercises[index].path}", True)
            return
        self.ensure_server()
        self.ex_index = index
        self.ex_seq += 1
        self.ex_paused = False
        self.video_pos = self.video_dur = 0.0
        self.video_error = ""
        self.mode = MODE_EXERCISE
        self._forget_break()
        self.publish()
        self.ensure_tab()

    def exercise_pause(self) -> None:
        if self.mode == MODE_EXERCISE:
            self.ex_paused = not self.ex_paused
            self.publish()

    def exercise_restart(self) -> None:
        if self.mode == MODE_EXERCISE:
            self.ex_restart += 1
            self.ex_paused = False
            self.publish()

    def exercise_left(self) -> float:
        return max(0.0, self.video_dur - self.video_pos) if self.video_dur else 0.0

    def start_break(self, minutes: int, ends_at: float | None = None) -> None:
        """Перерыв на экран эфира: minutes минут, а если задан конец (ends_at, time.time()) — до него (перерыв
        по плану урока кончается вместе с этапом)."""
        w = self.webinar or self.live_webinar()
        if not w:
            return
        self.webinar = w
        self.ensure_server()
        now = time.time()
        if ends_at is not None and ends_at > now + 30:
            self.brk_ends = ends_at
            self.brk_total = ends_at - now
        else:
            self.brk_total = max(1, int(minutes)) * 60.0
            self.brk_ends = now + self.brk_total
        self.brk_left_paused = None
        self.brk_seq += 1
        self.mode = MODE_BREAK
        if self.store.live:
            if self.store.slide is not None:
                self.store.slide = None
            self.slide = None
            self.store.set_break({"ends_at": self.brk_ends, "total": self.brk_total, "seq": self.brk_seq})
        self.publish()
        self.ensure_tab()

    def break_left(self) -> float:
        if self.brk_left_paused is not None:
            return self.brk_left_paused
        return self.brk_ends - time.time()

    def break_adjust(self, seconds: float) -> None:
        if self.mode != MODE_BREAK:
            return
        if self.brk_left_paused is not None:
            self.brk_left_paused = max(0.0, self.brk_left_paused + seconds)
        else:
            left = self.brk_ends - time.time()
            if left <= 0 and seconds > 0:
                self.brk_ends = time.time() + seconds     # время вышло, «+1 мин» — снова отсчёт
            else:
                self.brk_ends = max(time.time(), self.brk_ends + seconds)
        self.brk_total = max(60.0, self.brk_total + seconds)
        self.publish()

    def break_pause(self) -> None:
        if self.mode != MODE_BREAK:
            return
        if self.brk_left_paused is None:
            self.brk_left_paused = max(0.0, self.brk_ends - time.time())
        else:
            self.brk_ends = time.time() + self.brk_left_paused
            self.brk_left_paused = None
        self.publish()

    def break_restart(self) -> None:
        if self.mode == MODE_BREAK:
            self.brk_ends = time.time() + self.brk_total
            self.brk_left_paused = None
            self.publish()

    # ================================================================ окна
    def show_window(self) -> None:
        from .efir_window import EfirWindow
        if self.window is None:
            self.window = EfirWindow(self, self._owner())
        self.window.show_and_raise()

    def _owner(self) -> QWidget | None:
        """Окно-владелец для «Эфира» и редактора — главное окно (своей кнопки на панели задач у них нет)."""
        return self.main if isinstance(self.main, QWidget) else None

    def show_timer(self) -> None:
        from .efir_timer import TimerWindow
        if self.timer_window is None:
            self.timer_window = TimerWindow(self)
        self.timer_window.show_and_raise()

    def edit_look(self, lid: str | None = None) -> None:
        from .efir_editor import EditorWindow
        look = self.store.look(lid) if lid else None
        ed = EditorWindow(self, look, self.window if self.window is not None else self._owner(), mode="look")
        self.editors.append(ed)
        ed.closed.connect(lambda e=ed: self.editors.remove(e) if e in self.editors else None)
        ed.show_and_raise()

    def save_look(self, look) -> None:
        self.store.put_look(look)
        self.webinars_changed.emit()
        live = self.live_webinar()
        if live is not None and live.look_id == look.id:
            self.refresh_live()

    def edit(self, wid: str | None = None, parent=None) -> None:
        from .efir_editor import EditorWindow
        w = self.store.get(wid) if wid else None
        ed = EditorWindow(self, w, self.window if self.window is not None else self._owner())
        self.editors.append(ed)
        ed.closed.connect(lambda e=ed: self.editors.remove(e) if e in self.editors else None)
        ed.show_and_raise()

    def save_webinar(self, w: Webinar) -> None:
        self.store.put(w)
        self.webinars_changed.emit()
        live = self.store.live
        if live and live.webinar_id == w.id:
            self.refresh_live()

    def legacy_folder(self) -> Path | None:
        return legacy.find()

    def import_legacy(self, quiet: bool = False) -> int:
        root = legacy.find()
        if not root:
            if not quiet:
                self.message.emit("«Таймер вебинара» не найден на этом компьютере", True)
            return 0
        items = legacy.import_from(root)
        if not items:
            if not quiet:
                self.message.emit("В «Таймере вебинара» нет шаблонов", True)
            return 0
        known = {w.title for w in self.store.visible()}
        fresh = [w for w in items if w.title not in known] if quiet else items
        self.store.imported_legacy = True
        added = self.store.add(fresh) if fresh else []
        if not fresh:
            self.store.save()
        self.webinars_changed.emit()
        if not quiet or added:
            self.message.emit(f"Из «Таймера вебинара» перенесено шаблонов: {len(added)}", False)
        return len(added)

    def auto_import_legacy(self) -> None:
        """Первое открытие «Эфира»: шаблонов нет, а «Таймер вебинара» есть — перенести его шаблоны сами."""
        if self.store.visible() or self.store.imported_legacy:
            return
        if legacy.find():
            self.import_legacy(quiet=True)

    def shutdown(self) -> None:
        for ed in list(self.editors):
            ed.close()
        for w in (self.timer_window, self.window):
            if w is not None:
                w.save_geometry()
        self.server.stop()

