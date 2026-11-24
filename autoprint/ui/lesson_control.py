"""Экран урока: страница в браузере (http://127.0.0.1:8791/lesson) и её связь с программой.

Контроллер собирает состояние страницы (урок по этапам, идёт ли он, какой код печатается следующим) и отдаёт
его серверу «Эфира» на канал lesson; команды со страницы (начать урок, начать с этапа, печатать этот блок,
перерыв, зарядка…) приходят сюда. Показывается урок, идущий в «Эфире», иначе — открытый в программе.
Время урока — эфир по его этапам (EfirController.launch_lesson): таймер, плашка «Эфир», перерыв, зарядка.
"""
from __future__ import annotations

import concurrent.futures
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices

from .. import scenario
from ..efir.model import norm_hhmm, parse_hhmm
from ..storage import KIND_PLAN, STRUCTURES, Template
from .theme import theme

log = logging.getLogger(__name__)

# «Мои настройки» экрана урока: поле Settings → допустимые значения
PREFS = {"page_zoom": "zoom", "page_plan": ("side", "top", "hidden", "strip"), "page_past": ("dim", "collapse"),
         "page_stage_timer": "bool", "start_timer": "bool", "start_screen": "bool"}
ANSWER_FETCH_LIMIT = 90     # «Вставить ответ нейросети»: фото качаются не дольше, потом урок добавляется со ссылками


class LessonController(QObject):
    _cmd = Signal(dict)          # из потока сервера → в поток интерфейса
    _call = Signal(object)       # (функция, Future) — выполнить в потоке интерфейса и вернуть результат
    _fetched = Signal(object)    # (исходный урок, новый урок, замечания): фото из ответа нейросети скачаны

    def __init__(self, main) -> None:
        super().__init__(main)
        self.main = main
        self.efir = main.efir
        self.efir.server.on_command = self._cmd.emit
        self.efir.server.on_edit = self._edit_from_server
        self.efir.server.on_upload = self._upload_from_server
        self.efir.screen_key.connect(self._screen_key)
        self._cmd.connect(self.command)
        self._call.connect(self._do_call)
        self._fetched.connect(lambda x: self._insert_answer(*x))
        from .. import web_images
        self.fetch = web_images.fetch_images     # картинки по ссылкам из ответа нейросети (тесты подменяют)
        self.edits = 0           # сколько правок со страницы применено — страница знает, какие уже в состоянии
        self._plan = None          # (урок, плановое начало) идущего урока — для «конец 19:30 · +5 мин»
        self._last_slide = ""      # последний слайд ученикам: после фона / перерыва кликер продолжает с него
        self._notice = {"seq": 0, "text": "", "warn": False}   # сообщение программы — тостом на экране урока
        self._timeline: dict[str, tuple[int, int]] = {}   # этапы идущего урока: id → (с минуты, по минуту)
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
        """Урок показывает окно программы — оно живёт, пока живёт программа."""
        return True

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
        # идёт другой эфир (вебинар по расписанию): «Начать урок» спросит на странице, заменить ли его (E9)
        other = self.efir.live_webinar()
        other_live = other.title if other is not None and (t is None or self.efir.live_lesson_id() != t.id) else ""
        state = scenario.lesson_state(
            t, live_anchor_ms=anchor, live_shift=self._shift_min(t) if anchor else 0,
            efir_extra={"break_ends": int(self.efir.brk_ends * 1000) if self.efir.mode == "break" else 0,
                        "tab_open": bool(self.efir.server.running and self.efir.clients > 0),
                        "slide_n": (self.efir.slide or {}).get("n", 0) if self.efir.mode == "slide" else 0,
                        "slide_bid": (self.efir.slide or {}).get("bid", "") if self.efir.mode == "slide" else "",
                        "ex_index": self.efir.ex_index if self.efir.mode == "exercise" else -1,
                        "break_paused": self.efir.mode == "break" and self.efir.brk_left_paused is not None,
                        "break_left": int((self.efir.brk_left_paused or 0) * 1000) if self.efir.mode == "break" else 0,
                        "ex_paused": self.efir.mode == "exercise" and self.efir.ex_paused,
                        # фон экрана учеников по оформлению урока — миниатюра в полосе показывает его
                        "screen_bg": self.efir._bg(preset.background) if preset is not None else None,
                        "ex_muted": self.efir.mode == "exercise" and (self.efir.video_muted or self.efir.video_waiting),
                        "ex_waiting": self.efir.mode == "exercise" and self.efir.video_waiting},
            armed=t.active_block if t is not None else "",
            media_url=self.efir.server.media_url, presets=[(lk.id, lk.title) for lk in self.efir.store.looks],
            preset=preset.id if preset is not None else "", dark=theme.dark, efir_mode=self.efir.mode,
            tab=self.efir.tab_status()[0], hotkey=self.main.settings.hotkey_toggle,
            printer=self.main.printer.snapshot(), lessons=scenario.lessons_state(self.main.store.templates),
            exercises=[e.title for e in preset.exercises] if preset is not None else [], edits=self.edits,
            other_live=other_live,
            prefs={k: getattr(self.main.settings, k) for k in PREFS},
            structures=[{"key": k, "title": v[0], "minutes": sum(s[1] for s in v[1])} for k, v in STRUCTURES.items()],
            plan=self.main.store.get(t.plan_id) if t is not None and t.plan_id else None,
            topics=self.main.store.topics_of(t.id) if t is not None and t.kind == KIND_PLAN else (),
            plans=self.main.store.plans())
        state["notice"] = dict(self._notice)
        state["button_countdown"] = self._countdown()      # «Набрать»: через сколько секунд начнётся набор
        # видео зарядок, файлов которых нет (удалили, переместили) — этап-зарядка предупредит заранее
        state["exercises_missing"] = [e.title for e in (preset.exercises if preset is not None else [])
                                      if not Path(e.path).is_file()]
        # во время зарядки экран эфира шлёт ход видео раз в секунду: странице суфлёра от этого ничего не
        # меняется — не перерисовывать её (иначе пересоздаются кнопки и теряются щелчки)
        key = json.dumps(state, ensure_ascii=False, sort_keys=True)
        if key == self._last:
            return
        self._last = key
        self.efir.server.publish(state, channel="lesson")

    def notice(self, text: str, warn: bool = False) -> None:
        """Сообщение программы — тостом и на экране урока (страница показывает каждое новое по seq)."""
        self._notice = {"seq": self._notice["seq"] + 1, "text": str(text)[:600], "warn": bool(warn)}
        self.schedule_publish()

    def _launch(self, t: Template, **kw) -> bool:
        """«Начать урок» со страницы: мини-таймер и экран учеников — только если так в «Моих настройках»."""
        s = self.main.settings
        ok = self.efir.launch_lesson(t, show=s.start_timer, **kw)
        if ok and s.start_screen and self.efir.clients <= 0:
            self.efir.open_tab()
        return ok

    def _chat_prompt(self, t: Template) -> None:
        """«⋯ → Промпт для своего чата»: урок со слайдами — по каждому слайду; иначе — общий, материал прикладывают."""
        from PySide6.QtGui import QGuiApplication
        from .. import lesson_ai as L
        from ..storage import BLOCK_IMAGE, BLOCK_STAGE
        plan = t if t.kind == KIND_PLAN else (self.main.store.get(t.plan_id) if t.plan_id else None)
        exercises = self.main.exercise_titles(t)
        if any(b.type == BLOCK_IMAGE and b.slide and b.text for b in t.blocks):
            text = L.slides_prompt(t, plan=plan, exercises=exercises)
        else:
            total = sum(b.minutes for b in t.blocks if b.type == BLOCK_STAGE) or 45
            text = L.lesson_prompt(L.Options(style=L.STYLE_SCENARIO, minutes=total, cls=self.main.settings.lesson_class),
                                   plan=plan, exercises=exercises)
        QGuiApplication.clipboard().setText(text)
        self.main._notify("Промпт скопирован: вставьте его в ChatGPT, GigaChat, Алису или DeepSeek и приложите файл "
                          "презентации или методички. Ответ — «⋯ → Вставить ответ нейросети».")

    def _apply_answer(self, t: Template, text: str) -> None:
        """«⋯ → Вставить ответ нейросети»: копия урока по ответу (слайды — по номерам), рядом с исходным. Урок по
        плану или сам план — новый урок по этому плану. Фото по ссылкам — скачиваются в фоне, потом урок добавляется."""
        import threading
        from .. import plans, slides
        try:
            new, notes = slides.apply_chat_answer(t, text)
        except ValueError as e:
            self.main._notify(str(e), warn=True)
            return
        plan = t if t.kind == KIND_PLAN else (self.main.store.get(t.plan_id) if t.plan_id else None)
        new.kind = ""
        if t.kind == KIND_PLAN and new.title == t.title:
            new.title = "Новый урок"
        if plan is not None:
            notes = plans.link_topic(new, plan) + notes
        from ..storage import BLOCK_IMAGE
        if not any(b.type == BLOCK_IMAGE and "://" in (b.text or "") for b in new.blocks):
            self._insert_answer(t, new, notes)
            return
        self.main._notify("Урок по ответу нейросети: скачиваю картинки — урок появится в списке через минуту.")
        fetch = self.fetch

        ev = threading.Event()
        timer = threading.Timer(ANSWER_FETCH_LIMIT, ev.set)       # общий срок: дальше — ссылками из интернета
        timer.daemon = True

        def work() -> None:
            try:
                more = fetch(new, cancel=ev) or []
            except Exception as e:   # noqa: BLE001 — урок добавляется и без фото
                more = [f"Картинки не скачались: {e}"]
            finally:
                timer.cancel()
            self._fetched.emit((t, new, notes + list(more)))
        timer.start()
        threading.Thread(target=work, name="lesson-answer-images", daemon=True).start()

    def _insert_answer(self, t: Template, new: Template, notes: list[str]) -> None:
        st = self.main.store
        st.templates.insert(st.templates.index(t) + 1 if t in st.templates else len(st.templates), new)
        self.main.touch(new)
        self.main._fill_library(new.id)
        msg = f"Урок «{new.title}» по ответу нейросети. " + " ".join(notes)
        if self.efir.live_lesson_id():
            self.main._notify(msg + " Идёт урок — откройте копию после него.", tray=True)
            self.schedule_publish()
            return
        self.main._notify(msg, tray=bool(notes))
        self.main.open_lesson(new.id, ask=False)

    def _fill_slides(self, t: Template) -> None:
        """«Подставить слайды из презентации…»: выбрать PDF или PowerPoint — места «Слайд N» получают картинки."""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self.main, "Презентация — для картинок слайдов", "",
                                              "Презентация (*.pdf *.pptx)")
        if path:
            self.fill_slides_from(t, path)

    def fill_slides_from(self, t: Template, path: str) -> bool:
        from .. import slides
        if self.efir.live_webinar() is not None:
            self.main._notify("Идёт эфир — слайды из презентации подставьте после него: сохранение PowerPoint в PDF "
                              "занимает до минуты, и программа на это время занята.", warn=True)
            return False
        pdf = slides.export_pdf(path) if path.lower().endswith(".pptx") else path
        if not pdf:
            self.main._notify("PowerPoint не сохранил презентацию в PDF — выберите PDF этой презентации.", warn=True)
            return False
        before = sum(1 for b in t.blocks if b.type == "image" and b.slide and not b.text)
        notes = slides.fill_slides(t, pdf)
        after = sum(1 for b in t.blocks if b.type == "image" and b.slide and not b.text)
        self.main.touch(t)
        self.edits += 1
        self.schedule_publish()
        self.main._notify(f"Слайды подставлены: {before - after}. " + " ".join(notes), tray=bool(notes))
        return True

    def _find_image(self, t: Template, bid: str) -> None:
        """«Найти в интернете» у места «Нужна картинка: …» — поиск картинок по подписи в обычном браузере."""
        from urllib.parse import quote
        b = t.find_block(bid)
        if b is None:
            return
        QDesktopServices.openUrl(QUrl("https://yandex.ru/images/search?text=" + quote((b.title or "картинка").strip())))

    def _screen_key(self, key: str) -> None:
        """Кликер нажали на вкладке учеников (её могли щёлкнуть мышью) — листаем слайды так же, как с экрана урока."""
        t = self.current()
        if t is None:
            return
        live = self.efir.live_webinar()
        if live is not None and self.efir.live_lesson_id() != t.id:
            return                                  # идёт вебинар, а не этот урок — слайды урока в эфир не выводим
        if key in ("ArrowRight", "PageDown"):
            self._slide_step(t, 1)
        elif key in ("ArrowLeft", "PageUp"):
            self._slide_step(t, -1)
        elif key in ("b", "B", "и", "И", ".", "ю"):
            # как B в PowerPoint: слайд → фон, ещё раз — тот же слайд
            if self.efir.mode != "slide" and self._last_slide and t.find_block(self._last_slide) is not None:
                self._show_slide(t, self._last_slide)
            else:
                self.efir.show_background()

    @staticmethod
    def _slides(t: Template) -> list:
        """Слайды урока по порядку: картинки с номером слайда; нет таких — все картинки урока."""
        from ..storage import BLOCK_IMAGE
        imgs = [b for b in t.blocks if b.type == BLOCK_IMAGE and (b.text or "").strip()]
        marked = [b for b in imgs if b.slide]
        return marked or imgs

    def _show_slide(self, t: Template, bid: str) -> None:
        from ..storage import BLOCK_IMAGE
        b = next((x for x in t.blocks if x.id == bid and x.type == BLOCK_IMAGE and (x.text or "").strip()), None)
        if b is None:
            return                                  # «На экран» — у любой картинки; листают ◀ ▶ — по слайдам
        slides = self._slides(t)
        i = next((k for k, x in enumerate(slides) if x.id == bid), -1)
        nxt = slides[i + 1].text.strip() if 0 <= i < len(slides) - 1 else ""
        self._ensure_screen(t)
        self.efir.show_slide(b.text.strip(), b.slide or (i + 1 if i >= 0 else 0), b.id, nxt)
        self._last_slide = b.id
        self.efir.ensure_tab()            # вкладки экрана учеников нет — открыть самим, а не говорить «не открыта»

    def _slide_step(self, t: Template, d: int) -> None:
        """◀ ▶ кликера: следующий / предыдущий слайд; ничего не показано — первый."""
        slides = self._slides(t)
        if not slides:
            return
        cur = (self.efir.slide or {}).get("bid") if self.efir.mode == "slide" else ""
        if not cur and any(b.id == self._last_slide for b in slides):
            self._show_slide(t, self._last_slide)     # после фона / перерыва / зарядки — тот же слайд, не первый
            return
        i = next((k for k, b in enumerate(slides) if b.id == cur), None)
        j = 0 if i is None else max(0, min(len(slides) - 1, i + d))
        if i is not None and j == i:
            return
        self._show_slide(t, slides[j].id)

    def _look_new(self, t: Template) -> None:
        """«Новое оформление…»: копия оформления урока под новым именем — урок сразу на нём, открыть редактор."""
        import copy
        from ..efir.model import Look, new_id
        base = self.efir.lesson_look(t)
        look = copy.deepcopy(base) if base is not None else Look()
        look.id, look.title = new_id(), "Новое оформление"
        self.efir.save_look(look)
        self._set_preset(t, look.id)
        self.efir.edit_look(look.id)

    def _remember_plan(self, t: Template) -> None:
        """Плановое начало идущего урока: от него — «конец 19:30» и сдвиг «+5 мин» после «Начать этот этап сейчас»."""
        live = self.efir.store.live
        self._plan = (t.id, live.anchor) if live is not None else None

    def _shift_min(self, t: Template) -> int:
        live = self.efir.store.live
        plan = self._plan
        if live is None or plan is None or plan[0] != t.id:
            return 0
        return round((live.anchor - plan[1]).total_seconds() / 60)

    def _set_pref(self, key: str, value) -> None:
        """«Мои настройки» со страницы: только поля из PREFS и только допустимые значения."""
        kind = PREFS.get(key)
        s = self.main.settings
        if kind is None:
            return
        if kind == "zoom":
            try:
                v = max(80, min(200, int(value)))
            except (TypeError, ValueError):
                return
        elif kind == "bool":
            v = bool(value)
        elif value in kind:
            v = value
        else:
            return
        if getattr(s, key) == v:
            return
        setattr(s, key, v)
        self.main._settings_timer.start()
        self.schedule_publish()

    def _sync_live(self, t: Template) -> None:
        """Урок идёт, а его этапы поправили — обновить расписание таймера. Начало текущего этапа (по id блока)
        остаётся на тех же часах: правка минут прошлых этапов не сдвигает «сейчас» (E5). Текущий этап удалили —
        время урока не трогаем."""
        w = self.efir.live_webinar()
        st = scenario.stages(t)[1]
        new = {s.block.id: (s.start_min, s.end_min) for s in st}
        now = [(a.name, a.min, a.kind) for a in w.schedule] if w else []
        want = [(a.name, a.min, a.kind) for a in scenario.webinar_for(t).schedule]
        if want and now != want:
            live = self.efir.store.live
            anchor = live.anchor
            elapsed = (datetime.now() - anchor).total_seconds() / 60
            cur = next((sid for sid, (a, b) in self._timeline.items() if a <= elapsed < b), None)
            if cur is not None and cur in new:
                anchor = anchor + timedelta(minutes=self._timeline[cur][0] - new[cur][0])
            self.efir.launch_lesson(t, show=False)
            if anchor != live.anchor and self.efir.store.live:
                self.efir.store.set_live(self.efir.store.live.webinar_id, anchor)
                self.efir.live_changed.emit()
        self._timeline = new

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
        """Правка со страницы (поток интерфейса): действия над уроком → новые версии и HTML затронутых блоков.
        Урок по плану: этапы правятся только в плане. План: после правки — уроки по нему приводятся к нему."""
        from .. import lesson_edit
        from ..storage import KIND_PLAN
        t = self._lesson_for_edit(data.get("lesson"))
        plan = self.main.store.get(t.plan_id) if t.plan_id else None
        ids = lesson_edit.apply(t, data.get("ops"), fixed_stages=plan.title if plan is not None else "",
                                keep_one_stage=t.kind == KIND_PLAN)
        res = self._after_edit(t, ids)
        if t.kind == KIND_PLAN:
            self.main.plan_changed(t)
        return res

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
        self._timer.stop()

    def open_page(self) -> None:
        """Урок в фокусе — на экран урока в окне программы."""
        if not self.efir.ensure_server():
            return
        self.publish()
        t = self.current()
        self.main.show_view(f"#/lesson/{t.id}" if t is not None else "#/lessons")

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
                    if self._launch(t, start=at, force=bool(d.get("force"))):
                        self._remember_plan(t)
            elif cmd == "stop":
                if self.efir.live_lesson_id():
                    self.efir.stop_live()
            elif cmd == "shift_now" and t is not None:
                self._start_stage_now(t, self._current_stage(t))
            elif cmd == "start_at" and t is not None:
                self._start_stage_now(t, int(d.get("index")))
            elif cmd == "arm" and t is not None:
                self._arm(t, str(d.get("block") or ""))
            elif cmd == "type" and t is not None:
                self._type(str(d.get("block") or ""))
            elif cmd == "typing":
                self._typing(str(d.get("op") or ""))
            elif cmd == "exercise_pause":
                self.efir.exercise_pause()
            elif cmd == "exercise_restart":
                self.efir.exercise_restart()
            elif cmd == "break" and t is not None:
                self._break(t, str(d.get("stage") or ""), d.get("minutes"))
            elif cmd == "print_settings":
                self.main.printer.set_option(str(d.get("key") or ""), d.get("value"))
            elif cmd == "new_lesson":
                self._new_lesson(bool(d.get("force")), str(d.get("structure") or "empty"), str(d.get("plan") or ""))
            elif cmd == "new_plan":
                if self._may_leave_live(bool(d.get("force"))):
                    self.main.new_plan(str(d.get("structure") or "empty"))
            elif cmd == "make_plan" and t is not None:
                self.main.make_plan(t)
            elif cmd == "link_plan" and t is not None:
                self.main.link_plan(t, str(d.get("plan") or ""))
            elif cmd == "unlink_plan" and t is not None:
                self.main.unlink_plan(t)
            elif cmd == "delete_lesson" and t is not None:
                self.main.delete_lesson(t, ask=False)
            elif cmd == "export" and t is not None and d.get("fmt") in ("package", "md", "ipynb", "students", "json"):
                self.main.export_template(t, str(d["fmt"]))
            elif cmd == "slide" and t is not None:
                self._show_slide(t, str(d.get("block") or ""))
            elif cmd == "slide_step" and t is not None:
                self._slide_step(t, 1 if int(d.get("d") or 1) > 0 else -1)
            elif cmd == "chat_prompt" and t is not None:
                self._chat_prompt(t)
            elif cmd == "apply_answer" and t is not None:
                self._apply_answer(t, str(d.get("text") or ""))
            elif cmd == "fill_slides" and t is not None:
                self._fill_slides(t)
            elif cmd == "find_image" and t is not None:
                self._find_image(t, str(d.get("block") or ""))
            elif cmd == "open_tab":
                self.efir.open_tab()
            elif cmd == "copy_url":
                self.efir.copy_url()
            elif cmd == "break_adjust":
                self.efir.break_adjust(max(-3600, min(3600, int(d.get("seconds") or 0))))
            elif cmd == "break_pause":
                self.efir.break_pause()
            elif cmd == "break_restart":
                self.efir.break_restart()
            elif cmd == "restore_anchor" and t is not None:
                self._restore_anchor(t, d.get("ms"))
            elif cmd == "timer":
                if self.efir.live_webinar() is None:
                    self.main._notify("Мини-таймер показывает урок по времени — сначала «Начать урок».")
                else:
                    self.efir.show_timer()
            elif cmd == "look_new" and t is not None:
                self._look_new(t)
            elif cmd == "look_edit" and t is not None:
                look = self.efir.lesson_look(t)
                if look is None:
                    self._look_new(t)
                else:
                    self.efir.edit_look(look.id)
            elif cmd == "prefs":
                self._set_pref(str(d.get("key") or ""), d.get("value"))
            elif cmd == "settings":
                self.main.open_settings(str(d.get("page") or ""))
            elif cmd == "recognize" and t is not None:
                self.main.recognize_lesson(t)
            elif cmd == "exercise" and t is not None:
                self._ensure_screen(t)
                self.efir.start_exercise(self._exercise_index(t, str(d.get("stage") or ""), d.get("index")))
            elif cmd == "background":
                self.efir.show_background()
            elif cmd == "preset" and t is not None:
                self._set_preset(t, str(d.get("id") or ""))
            elif cmd == "set_start" and t is not None:
                self._set_start(t, str(d.get("start") or "").strip())
            elif cmd == "open":
                self.main.open_lesson(str(d.get("lesson") or ""), ask=not d.get("force"))
        except (TypeError, ValueError) as e:
            log.warning("Команда экрана урока %r не выполнена: %s", d, e)
        self.schedule_publish()

    def _may_leave_live(self, force: bool) -> bool:
        """Новый урок или план со страницы: идёт урок — его завершают, только если страница спросила (force)."""
        if self.efir.live_lesson_id():
            if not force:
                return False
            self.efir.stop_live()
        return True

    def _new_lesson(self, force: bool, structure: str = "empty", plan: str = "") -> None:
        """«Новый урок» со страницы (по плану, пустой или по шаблону структуры): идёт урок — его завершают
        (страница спросила)."""
        if not self._may_leave_live(force):
            return
        if plan:
            self.main.new_topic(plan)
            return
        nt = self.main.store.add_from_structure(structure)
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
        if self.efir.live_lesson_id() != t.id and not self._launch(t):
            return
        anchor = datetime.now().replace(microsecond=0) - timedelta(minutes=stages[index].start_min)
        self.efir.store.set_live(self.efir.store.live.webinar_id, anchor)
        self.efir.live_changed.emit()

    def _restore_anchor(self, t: Template, ms) -> None:
        """«Вернуть» после «Начать этот этап сейчас» / «Следующий этап — сейчас»: прежнее начало идущего урока."""
        live = self.efir.store.live
        if live is None or self.efir.live_lesson_id() != t.id:
            return
        try:
            anchor = datetime.fromtimestamp(int(ms) / 1000)
        except (TypeError, ValueError, OverflowError, OSError):
            return
        self.efir.store.set_live(live.webinar_id, anchor)
        self.efir.live_changed.emit()

    def _arm(self, t: Template, bid: str) -> None:
        self.main.printer.arm(bid)       # только код: заметку или картинку печатать нельзя

    def _countdown(self) -> int:
        """Набор кнопкой в окне — с отсчётом: учитель успевает перейти в окно, где курсор (Jupyter, VS Code)."""
        return max(1, int(self.main.settings.button_countdown_s or 0))

    def _type(self, bid: str) -> None:
        """«Набрать» на блоке кода: блок — следующим и сразу набор с отсчётом. Этот блок уже набирается —
        ничего (пауза — кнопкой в полосе набора); стоит на паузе или ждёт Enter — продолжить."""
        p = self.main.printer
        if not p.arm(bid) or p.engine.active:
            return
        p.toggle(countdown=self._countdown())

    def _typing(self, op: str) -> None:
        """Полоса набора: pause | resume | next | stop. Своя команда на каждое действие — щелчок по окну
        (сам он ставит набор на паузу) не превращает «Пауза» в «Продолжить»."""
        from ..typer import LINE_WAIT, PAUSED
        p = self.main.printer
        st = p.engine.state
        if op == "stop":
            p.stop()
        elif op == "pause":
            p.engine.pause()
        elif op == "resume" and st == PAUSED or op == "next" and st == LINE_WAIT:
            p.toggle(countdown=self._countdown())

    def _break(self, t: Template, sid: str, minutes) -> None:
        """Перерыв ученикам (E6): с карточки этапа-перерыва, который идёт сейчас, — до планового конца этапа;
        с другого этапа — его минуты; вне плана — перерыв по умолчанию (break_min эфира урока, обычно 10)."""
        self._ensure_screen(t)
        st = next((s for s in scenario.stages(t)[1] if s.block.id == sid), None)
        live = self.efir.store.live
        if st is not None and live is not None and self.efir.live_lesson_id() == t.id:
            elapsed = (datetime.now() - live.anchor).total_seconds() / 60
            if st.start_min <= elapsed < st.end_min:
                end = live.anchor + timedelta(minutes=st.end_min)
                self.efir.start_break(st.end_min - st.start_min, ends_at=end.timestamp())
                return
        if st is not None and st.end_min > st.start_min:
            self.efir.start_break(st.end_min - st.start_min)
            return
        w = self.efir.webinar or self.efir.live_webinar()
        self.efir.start_break(int(minutes or 0) or (w.break_min if w else 10))

    def _exercise_index(self, t: Template, stage_id: str, index) -> int:
        """Какое видео зарядки включить: этапа — по названию видео (не нашлось — первое), иначе — index."""
        st = t.find_block(stage_id) if stage_id else None
        if st is None:
            return int(index or 0)
        from ..lesson_md import video_key
        w = self.efir.webinar or self.efir.live_webinar()
        titles = [video_key(e.title) for e in (w.exercises if w is not None else [])]
        want = video_key(st.exercise)
        return titles.index(want) if want and want in titles else 0

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
            self._remember_plan(t)          # новое время начала — новый план: сдвига нет

    def _set_preset(self, t: Template, lid: str) -> None:
        """Оформление экрана эфира для урока (Template.look; preset 0.9 не трогаем — откат)."""
        if self.efir.store.look(lid) is None:
            return
        t.look = lid
        self.main.settings.lesson_look = lid
        self.main._settings_timer.start()
        self.main._save_timer.start()
        if t.kind == KIND_PLAN:
            self.main.plan_changed(t)        # оформление плана — и у уроков по нему (видео зарядки находится)
        if self.efir.live_lesson_id() == t.id:
            self.efir.launch_lesson(t, show=False)      # оформление идущего урока — сразу
