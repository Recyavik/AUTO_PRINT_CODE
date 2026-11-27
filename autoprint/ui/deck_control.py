"""Пульт (1.3): управление уроком снаружи — Macro Deck на телефоне, Stream Deck, AutoHotkey, curl.

  • Команды: GET или POST http://127.0.0.1:<порт>/api/<команда>?key=<ключ> (ключ можно заголовком X-AutoPrint-Key).
    Только этот компьютер (сервер слушает 127.0.0.1); ключ — чтобы чужой сайт в браузере не нажимал кнопки.
    Ответ любой команды — состояние (state()): этапы, сколько осталось, что у учеников.
  • Файлы для кнопок: <папка данных>\\deck\\*.txt — по файлу на значение (UTF-8 без BOM, без перевода
    строки), state.json — всё вместе. Macro Deck читает их переменными «Read from file»: время на кнопке идёт само.
    Пишутся раз в секунду и сразу после смены экрана, только то, что изменилось.

Кнопки повторяют значки над уроком: «Чёрный» и «Слайд» — переключатели (ещё раз — фон), «Зарядка» идёт — пауза,
«Перерыв» — по плану урока, ◀ ▶ — пока слайд у учеников.
"""
from __future__ import annotations

import concurrent.futures
import hmac
import json
import logging
import os
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger(__name__)

CALL_TIMEOUT_S = 5
COMMANDS = ("state", "background", "black", "exercise", "break", "break_add", "slide", "slide_prev", "slide_next",
            "mic", "mic_off", "mic_on", "sound", "sound_off", "sound_on", "prepare")
# для «Настройки → Пульт»: команда → (кнопка, что делает)
TITLES = {
    "background": ("Фон", "фон ученикам"),
    "black": ("Чёрный", "чёрный экран · ещё раз — фон"),
    "exercise": ("Зарядка", "включить видео · идёт — пауза, ещё раз — дальше"),
    "break": ("Перерыв", "по плану урока, с этой минуты"),
    "break_add": ("+5 мин", "к перерыву; ?min=1 — на минуту"),
    "slide": ("Слайд", "показать слайд · ещё раз — фон"),
    "slide_prev": ("◀", "предыдущий слайд"),
    "slide_next": ("▶", "следующий слайд"),
    "prepare": ("Подготовка", "открыть вкладки из списка ниже"),
    "mic": ("Микрофон", "все микрофоны выключить · ещё раз — включить"),
    "sound": ("Звук", "весь звук компьютера выключить · ещё раз — включить"),
    "mic_off": ("Микрофон выкл.", "все микрофоны — выключить (сколько ни нажимай)"),
    "sound_off": ("Звук выкл.", "весь звук — выключить"),
    "state": ("Что идёт", "этапы, время, экран учеников (JSON)"),
}
# файлы для кнопок: имя → ключ состояния (bool — "true" / "false")
FILES = {
    "prev.txt": "prev", "now.txt": "now", "next.txt": "next", "left.txt": "left", "stage.txt": "stage_text",
    "screen.txt": "screen", "black.txt": "black", "exercise.txt": "exercise", "break.txt": "break",
    "break_left.txt": "break_left", "slide.txt": "slide", "slides.txt": "slides", "slide_n.txt": "slide_text",
    "clock.txt": "clock", "mic_muted.txt": "mic_muted", "sound_muted.txt": "sound_muted",
}


BOOL_KEYS = {"black", "exercise", "break", "slide", "slides", "mic_muted", "sound_muted"}


def deck_folder() -> Path:
    from ..storage import DATA_DIR
    return DATA_DIR / "deck"


def lan_addresses() -> list[str]:
    """Адреса этого компьютера в домашней сети (IPv4, без 127.* и 169.254.*) — для телефона. Первым — тот, через
    который компьютер выходит в сеть (пакет никуда не уходит: UDP connect только выбирает сетевую карту)."""
    import socket
    out: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            out.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            out.append(info[4][0])
    except OSError:
        pass
    seen: list[str] = []
    for ip in out:
        if ip not in seen and not ip.startswith(("127.", "169.254.", "0.")):
            seen.append(ip)
    return seen


class DeckControl(QObject):
    _call = Signal(object)          # (команда, параметры, Future) — из потока сервера в поток интерфейса
    _md_done = Signal(object)       # итог настройки Macro Deck (из её потока) — в поток интерфейса

    def __init__(self, app) -> None:
        super().__init__(app)
        self.app = app
        self.folder = deck_folder()
        self._written: dict[str, str] = {}     # что уже лежит в файлах — то же самое второй раз не пишем
        self._warned = False
        self._audio = None                     # audio.Mute — при первой нужде (тесты подставляют свой)
        self.md_status = ""                    # Macro Deck: что сейчас (для «Настройки → Пульт»)
        self.md_busy = False
        self.md_sync = None                    # macrodeck.Sync — пока пульт включён и Macro Deck подключён
        self._md_done.connect(self._md_finish)
        app.efir.server.on_deck = self._from_server
        self._call.connect(self._do_call)
        self._timer = QTimer(self, interval=1000, timeout=self.write_files)
        self._soon = QTimer(self, singleShot=True, interval=30, timeout=self.write_files)
        for sig in (app.efir.screen_changed, app.efir.live_changed):
            sig.connect(self._changed)
        self.apply()

    @property
    def audio(self):
        if self._audio is None:
            from ..audio import Mute
            self._audio = Mute()
        return self._audio

    @audio.setter
    def audio(self, value) -> None:
        self._audio = value

    # ------------------------------------------------------------ включатель и ключ
    @property
    def on(self) -> bool:
        return bool(getattr(self.app.settings, "deck_on", False))

    def apply(self) -> None:
        """Пульт включили / выключили в настройках: ключ (если его ещё нет) и файлы раз в секунду. Выключили —
        в файлах «выключено», а не последнее время и подсвеченный «Чёрный»."""
        if self.on:
            self.ensure_key()
            if not self._timer.isActive():
                self._timer.start()
            self._md_start_sync()
            self._changed()
        else:
            self._timer.stop()
            self._soon.stop()
            self.write_off()
            self._md_stop_sync()

    def shutdown(self) -> None:
        """Выход из программы: кнопки не должны показывать застывшее время."""
        self._timer.stop()
        self._soon.stop()
        if self.on:
            self.write_off("Программа закрыта")
        if self.md_sync is not None:
            self.md_sync.stop()

    def write_off(self, text: str = "Пульт выключен") -> None:
        """Нейтральные значения в уже созданных файлах (папки нет — пульт и не включали, ничего не создаём) и на
        странице Macro Deck."""
        if self.md_sync is not None:
            from .. import macrodeck
            self.md_sync.push(macrodeck.values({"off": True, "now": text}))
        if not self.folder.is_dir():
            return
        off = {name: ("false" if k in BOOL_KEYS else "") for name, k in FILES.items()}
        off["screen.txt"] = "off"
        off["now.txt"] = text
        off["state.json"] = json.dumps({"ok": False, "off": True, "now": text}, ensure_ascii=False)
        for name, value in off.items():
            if (self.folder / name).exists() and self._write(self.folder / name, value):
                self._written[name] = value

    def ensure_key(self) -> str:
        s = self.app.settings
        if not s.deck_key:
            s.deck_key = secrets.token_urlsafe(18)
            s.save()
        return s.deck_key

    def new_key(self) -> str:
        """«Новый ключ»: старые ссылки перестают работать (страницу Macro Deck — пересобрать с новым)."""
        self.app.settings.deck_key = ""
        key = self.ensure_key()
        self.app.settings.save()
        if self.md_token():
            self.md_setup()
        return key

    # ------------------------------------------------------------ Macro Deck
    def md_token(self) -> str:
        from ..ai import unprotect
        return unprotect(getattr(self.app.settings, "md_token", "") or "")

    def md_base(self) -> str:
        """Ссылка кнопок страницы: постоянный порт (не временный, если 8791 был занят) и ключ пульта."""
        return f"http://127.0.0.1:{self.app.efir.server.want_port}/api/?key={self.ensure_key()}"

    def md_client(self, token: str):
        from .. import macrodeck
        return macrodeck.Client(token)

    def md_connect(self, token: str) -> None:
        """Ключ Macro Deck вставили: проверить, собрать страницу (в своём потоке — Macro Deck может спросить
        разрешение у человека), запомнить ключ зашифрованным."""
        token = (token or "").strip()
        if not token:
            self.md_status = "Вставьте ключ Macro Deck"
            return
        if not self.app.settings.deck_on:
            self.app.settings.deck_on = True
            self.apply()
        self._md_run(token, remember=True)

    def md_setup(self) -> None:
        """«Пересобрать страницу»."""
        token = self.md_token()
        if token:
            self._md_run(token, remember=False)

    def md_forget(self) -> None:
        """«Отключить Macro Deck»: ключ забыть, значения больше не слать (страница в Macro Deck остаётся)."""
        self._md_stop_sync()
        self.app.settings.md_token = ""
        self.app.settings.save()
        self.md_status = "Macro Deck отключён"

    PENDING_WAIT_S = 180

    def _md_run(self, token: str, remember: bool) -> None:
        if self.md_busy:
            return
        from .. import macrodeck
        self.md_busy = True
        self.md_status = "Собираю страницу в Macro Deck…"
        base, profile = self.md_base(), self.app.settings.md_profile
        client = self.md_client(token)
        wait_s = self.PENDING_WAIT_S

        def work():
            res = {"token": token, "remember": remember}
            end = time.monotonic() + wait_s
            while True:
                try:
                    res.update(ok=True, **macrodeck.setup(client, base, profile))
                    break
                except macrodeck.MacroDeckError as e:
                    if "CONFIRMATION_PENDING" in str(e) and time.monotonic() < end:
                        self.md_status = "Разрешите в Macro Deck на компьютере: он спрашивает, можно ли создать кнопки"
                        time.sleep(3)
                        continue
                    res.update(ok=False, error=str(e) if "CONFIRMATION_PENDING" not in str(e)
                               else "Macro Deck не получил разрешения — нажмите «Пересобрать страницу» ещё раз")
                    break
                except Exception as e:      # noqa: BLE001
                    log.exception("Macro Deck: настройка")
                    res.update(ok=False, error=str(e) or type(e).__name__)
                    break
            self._md_done.emit(res)

        threading.Thread(target=work, name="macrodeck-setup", daemon=True).start()

    def _md_finish(self, res: dict) -> None:
        self.md_busy = False
        s = self.app.settings
        if res.get("ok"):
            if res.get("remember"):
                from ..ai import protect
                s.md_token = protect(res["token"])
            if res.get("profile"):
                s.md_profile = res["profile"]
            s.save()
            self.md_status = "Готово: в Macro Deck на телефоне выберите профиль «AutoPrintCode»"
            self._md_stop_sync()
            self._md_start_sync()
            self._changed()
        else:
            self.md_status = res.get("error") or "Macro Deck: не получилось"
        self.app.changed.emit("settings")

    def _md_start_sync(self) -> None:
        if self.md_sync is not None or not self.on:
            return
        token = self.md_token()
        if token:
            from .. import macrodeck
            self.md_sync = macrodeck.Sync(self.md_client(token))

    def _md_stop_sync(self) -> None:
        if self.md_sync is not None:
            self.md_sync.stop()
            self.md_sync = None

    def md_info(self) -> dict:
        sync = self.md_sync
        return {"connected": bool(self.md_token()), "busy": self.md_busy, "status": self.md_status,
                "error": (sync.error if sync is not None else ""), "profile": self.app.settings.md_profile,
                "lan": lan_addresses()}

    def info(self) -> dict:
        """«Настройки → Пульт»: ключ, готовые ссылки для кнопок, папка файлов."""
        key = self.ensure_key() if self.on else self.app.settings.deck_key
        srv = self.app.efir.server
        port = srv.port or srv.want_port
        base = f"http://127.0.0.1:{port}/api/"
        links = [{"cmd": c, "title": TITLES[c][0], "hint": TITLES[c][1], "url": f"{base}{c}?key={key}"}
                 for c in TITLES]
        # порт 8791 был занят при запуске (прежняя копия ещё закрывалась) — ссылки этого запуска временные
        moved = bool(srv.port) and srv.port != srv.want_port
        return {"on": self.on, "key": key, "base": base, "links": links, "folder": str(self.folder),
                "files": list(FILES), "port": port, "want_port": srv.want_port, "port_moved": moved,
                "md": self.md_info(), "prepare": list(getattr(self.app.settings, "deck_prepare", []) or []),
                "prepare_screen": bool(getattr(self.app.settings, "deck_prepare_screen", True))}

    # ------------------------------------------------------------ из потока сервера
    def _from_server(self, cmd: str, params: dict, key: str) -> tuple[int, dict]:
        s = self.app.settings
        if not s.deck_on:
            return 403, {"ok": False, "error": "Пульт выключен: Настройки → Пульт"}
        if not key or not s.deck_key or not hmac.compare_digest(key.encode(), s.deck_key.encode()):
            return 403, {"ok": False, "error": "Неверный ключ пульта: ссылка — в Настройки → Пульт"}
        if cmd not in COMMANDS:
            return 404, {"ok": False, "error": f"Нет такой команды: {cmd[:40]}", "commands": list(COMMANDS)}
        fut: concurrent.futures.Future = concurrent.futures.Future()
        self._call.emit((cmd, params, fut))
        try:
            return 200, fut.result(CALL_TIMEOUT_S)
        except concurrent.futures.TimeoutError:
            if fut.cancel():                # ещё не начали — и не начнём: повтор с пульта не нажмёт дважды
                return 503, {"ok": False, "retry": True, "error": "Программа занята — нажмите ещё раз"}
            return 202, {"ok": True, "late": True, "error": "Программа занята — команда выполняется"}

    def _do_call(self, triple) -> None:
        cmd, params, fut = triple
        if not fut.set_running_or_notify_cancel():
            return
        try:
            fut.set_result(self.run(cmd, params))
        except Exception as e:      # noqa: BLE001 — ответить пульту, а не уронить сервер
            log.exception("Пульт: команда %r", cmd)
            fut.set_result({"ok": False, "error": str(e) or type(e).__name__})

    # ------------------------------------------------------------ команды (поток интерфейса)
    def _lesson(self):
        """Урок, которым управляет пульт: в фокусе (идущий, иначе открытый). Идёт вебинар не этого урока — None:
        экран учеников — эфира, слайдов нет."""
        t = self.app.lesson.current()
        ef = self.app.efir
        if t is not None and ef.live_webinar() is not None and ef.live_lesson_id() != t.id:
            return None
        return t

    def _pick(self) -> str:
        pick = getattr(self.app.settings, "exercise_pick", "next")
        return "next" if pick == "ask" else pick          # на пульте меню нет — «спросить» = по очереди

    def _plan_break(self, t) -> str:
        """Этап-перерыв «по плану» (как в программе): идёт этап-перерыв — он, иначе первый этап-перерыв урока."""
        from .. import scenario
        stages = [s for s in scenario.stages(t)[1] if s.block.stage_kind == "break" and s.end_min > s.start_min]
        if not stages:
            return ""
        L, ef = self.app.lesson, self.app.efir
        if ef.store.live is not None and ef.live_lesson_id() == t.id:
            cur = L._current_stage(t)
            for s in stages:
                if s.index == cur:
                    return s.block.id
        return stages[0].block.id

    def run(self, cmd: str, params: dict | None = None) -> dict:
        from .lesson_control import EX_DOUBLE_S
        params = params or {}
        ef, L = self.app.efir, self.app.lesson
        t = self._lesson()
        mode = ef.mode
        if cmd == "background":
            L.command({"cmd": "background"}) if t is not None else ef.show_background()
        elif cmd == "black":
            if mode == "black":
                L.command({"cmd": "background"}) if t is not None else ef.show_background()
            else:
                L.command({"cmd": "black"}) if t is not None else ef.show_black()
        elif cmd == "exercise":
            if mode == "exercise":
                if time.monotonic() - ef.ex_started >= EX_DOUBLE_S:      # двойное нажатие — не пауза
                    ef.exercise_pause()
            elif t is not None:
                L.command({"cmd": "exercise", "pick": self._pick()})
            else:
                w = ef.webinar or ef.live_webinar()
                if w is not None and w.exercises:
                    ef.start_exercise(L._next_exercise(w.exercises, self._pick()))
        elif cmd == "break":
            if mode != "break":
                if t is not None:
                    L.command({"cmd": "break", "stage": self._plan_break(t)})
                else:
                    w = ef.webinar or ef.live_webinar()
                    ef.start_break(w.break_min if w else 10)
        elif cmd == "break_add":
            if mode == "break":
                raw = params.get("min")
                try:
                    m = 5 if raw is None or str(raw).strip() == "" else int(float(raw))
                except (TypeError, ValueError, OverflowError):
                    m = 5
                if m:
                    ef.break_adjust(max(-60, min(60, m)) * 60)
        elif cmd == "slide":
            if mode == "slide":
                L.command({"cmd": "background"}) if t is not None else ef.show_background()
            elif t is not None:
                L.command({"cmd": "slide_step", "d": 1})
        elif cmd in ("slide_next", "slide_prev"):
            if mode == "slide" and t is not None:
                L.command({"cmd": "slide_step", "d": 1 if cmd == "slide_next" else -1})
        elif cmd == "prepare":
            self.prepare()
        elif cmd in ("mic", "mic_off", "mic_on", "sound", "sound_off", "sound_on"):
            from ..audio import CAPTURE, RENDER
            flow = CAPTURE if cmd.startswith("mic") else RENDER
            if cmd.endswith("_off"):
                self.audio.set(flow, True)
            elif cmd.endswith("_on"):
                self.audio.set(flow, False)
            else:
                self.audio.toggle(flow)
        st = self.state()
        self._changed()
        return st

    def prepare(self) -> int:
        """«Подготовка»: вкладки из настроек — в браузере по умолчанию; и вкладка экрана учеников, если её ещё нет.
        → сколько вкладок открыто."""
        from .. import app_cmd
        s = self.app.settings
        n = 0
        if getattr(s, "deck_prepare_screen", True) and self.app.efir.ensure_server():
            if not self.app.efir.clients:
                self.app.efir.open_tab()
                n += 1
        for url in list(getattr(s, "deck_prepare", []) or [])[:20]:
            if isinstance(url, str) and url.lower().startswith(("http://", "https://")) and app_cmd.open_url(url):
                n += 1
        return n

    # ------------------------------------------------------------ состояние
    def state(self) -> dict:
        from .. import scenario
        from ..efir.model import fmt_left
        from .lesson_control import LessonController
        ef = self.app.efir
        t = self._lesson()
        now = datetime.now()
        segs = ef.segments()
        ag = ef.agenda(now)
        prev = cur = nxt = left = ""
        left_s = 0
        stage = 0
        if not segs:
            phase = "none"
            cur = t.title if t is not None else "Нет урока"
            first = next((s for s in scenario.stages(t)[1] if s.end_min > s.start_min), None) if t is not None else None
            nxt = first.block.title if first is not None else ""
        elif ag.phase == "before":
            phase, cur = "before", "До начала"
            nxt = ag.next.activity.name if ag.next else ""
            left_s = int(ag.left_s + 0.999)
            left = fmt_left(ag.left_s)
        elif ag.phase == "live":
            phase, stage = "live", ag.index + 1
            prev = segs[ag.index - 1].activity.name if ag.index > 0 else ""
            cur = ag.current.activity.name
            nxt = ag.next.activity.name if ag.next else ""
            left_s = int(ag.left_s + 0.999)
            left = fmt_left(ag.left_s)
        else:
            phase, cur = "after", "Урок закончен"
            prev = segs[-1].activity.name
        mode = ef.mode
        brk_left = ""
        if mode == "break":
            sec = ef.brk_left_paused if ef.brk_left_paused is not None else max(0.0, ef.brk_ends - time.time())
            brk_left = fmt_left(sec)
        slides = LessonController._slides(t) if t is not None else []
        # номер — место слайда среди слайдов урока (номера в картинках бывают с пропусками: «5 / 3»)
        n = 0
        if mode == "slide" and ef.slide:
            n = next((i + 1 for i, b in enumerate(slides) if b.id == ef.slide.get("bid")), 0)
        return {
            "ok": True, "lesson": t.title if t is not None else "", "phase": phase,
            "prev": prev, "now": cur, "next": nxt, "left": left, "left_s": left_s,
            "stage": stage, "stages": len(segs), "stage_text": f"{stage} из {len(segs)}" if stage else "",
            "screen": mode, "black": mode == "black",
            "exercise": mode == "exercise", "exercise_paused": mode == "exercise" and bool(ef.ex_paused),
            "break": mode == "break", "break_left": brk_left,
            "break_paused": mode == "break" and ef.brk_left_paused is not None,
            "slide": mode == "slide", "slides": bool(slides), "slide_n": n, "slides_total": len(slides),
            "slide_text": f"{n} / {len(slides)}" if mode == "slide" and n else "",
            "clock": now.strftime("%H:%M"),
            **self._audio_state(),
        }

    def _audio_state(self) -> dict:
        from ..audio import CAPTURE, RENDER
        try:
            mic, snd = self.audio.muted(CAPTURE), self.audio.muted(RENDER)
        except Exception:      # noqa: BLE001 — нет звука в системе — пульт всё равно работает
            log.exception("Пульт: звук")
            mic = snd = None
        return {"mic_muted": bool(mic), "sound_muted": bool(snd), "mic_found": mic is not None,
                "sound_found": snd is not None}

    # ------------------------------------------------------------ файлы для кнопок
    def _changed(self) -> None:
        if self.on and not self._soon.isActive():
            self._soon.start()

    def write_files(self) -> None:
        if not self.on:
            return
        try:
            st = self.state()
        except Exception:      # noqa: BLE001 — пульт не должен ронять программу
            log.exception("Пульт: состояние")
            return
        out = {name: (("true" if st[k] else "false") if isinstance(st[k], bool) else str(st[k]))
               for name, k in FILES.items()}
        out["state.json"] = json.dumps(st, ensure_ascii=False, indent=1)
        if self.md_sync is not None:
            from .. import macrodeck
            self.md_sync.push(macrodeck.values(st))
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        for name, text in out.items():
            if self._written.get(name) == text and (self.folder / name).exists():
                continue
            if self._write(self.folder / name, text):
                self._written[name] = text

    def _write(self, path: Path, text: str) -> bool:
        """Через временный файл: читающий не увидит половину. Подменить не дали (файл держат открытым без права
        удаления) — пишем прямо в него; не вышло и так — в следующий раз (в журнал — один раз)."""
        data = text.encode("utf-8")
        tmp = path.with_name(path.name + ".tmp")
        try:
            tmp.write_bytes(data)
            os.replace(tmp, path)
            return True
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            path.write_bytes(data)
            return True
        except OSError as e:
            if not self._warned:
                self._warned = True
                log.warning("Пульт: файл %s не записан: %s", path.name, e)
            return False
