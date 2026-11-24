"""Команды страницы окна программы: POST /app/cmd (без ответа) и POST /app/call (с ответом).

Приходят в потоке сервера; выполняются в потоке интерфейса (уроки, окно и настройки меняет только он). /app/call
ждёт результата — окно выбора файла может быть открыто, пока человек выбирает (до 10 минут).
"""
from __future__ import annotations

import concurrent.futures
import logging
from pathlib import Path

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
        elif op == "compact":                      # маленький режим — и пункт трея меняется
            arg = d.get("arg")
            self.app.set_compact(not self.app.window.compact if arg is None else bool(arg))
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

    # ------------------------------------------------------------ уроки
    def _t(self, d: dict, key: str = "id"):
        t = self.app.store.get(str(d.get(key) or ""))
        if t is None:
            raise ValueError("урок не найден")
        return t

    def cmd_open(self, d: dict) -> None:
        self.app.open_lesson(str(d.get("lesson") or d.get("id") or ""), ask=not d.get("force"))

    def cmd_duplicate(self, d: dict) -> None:
        self.app.duplicate(self._t(d))

    def cmd_delete(self, d: dict) -> None:
        """Удалить урок или план — страница уже спросила."""
        self.app.delete_lesson(self._t(d))

    def cmd_new_topic(self, d: dict) -> None:
        self.app.new_topic(str(d.get("plan") or ""))

    def cmd_recognize(self, d: dict) -> None:
        self.app.recognize_lesson(self._t(d))

    def cmd_new_lesson(self, d: dict) -> None:
        self.app.new_template(str(d.get("structure") or "empty"))

    def cmd_notice_action(self, d: dict) -> None:
        """Кнопка в тосте: повторить команду из уведомления (например, «Завершить и открыть»)."""
        seq = int(d.get("seq") or -1)
        n = next((x for x in getattr(self.app, "notices", [self.app.notice]) if x.get("seq") == seq), None)
        act = (n or {}).get("action") or {}
        inner = act.get("cmd") if isinstance(act, dict) else None
        if isinstance(inner, dict):
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

    def call_rename(self, d: dict) -> bool:
        return self.app.rename(self._t(d), str(d.get("title") or ""))

    def call_import_paths(self, d: dict) -> dict:
        paths = d.get("paths")
        if not isinstance(paths, list):
            raise ValueError("нет файлов")
        return self.app.import_paths([str(p) for p in paths][:50])

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

    # ------------------------------------------------------------ «Новый урок» (Task 11)
    def _wizard_plan(self, d: dict):
        """План шага 1: id плана или "none" / "" — без плана."""
        from .storage import KIND_PLAN
        pid = str(d.get("plan") or "")
        p = self.app.store.get(pid) if pid and pid != "none" else None
        return p if p is not None and p.kind == KIND_PLAN else None

    def _remember_wizard(self, d: dict, plan) -> None:
        s = self.app.settings
        s.lesson_plan = plan.id if plan is not None else ""
        if "cls" in d:
            s.lesson_class = str(d.get("cls") or "").strip()
        for key, field, lo, hi in (("minutes", "lesson_minutes", 10, 600), ("brk", "lesson_break", 0, 60)):
            if d.get(key) not in (None, ""):
                try:
                    setattr(s, field, max(lo, min(hi, int(d[key]))))
                except (TypeError, ValueError):
                    pass
        code = d.get("code") or {}
        if code:
            from . import wizard
            o = wizard.code_options(code)
            s.lesson_style, s.lesson_task, s.lesson_explain = o.style, o.task, o.explain
            s.lesson_keep_code, s.lesson_detail = o.keep_code, o.detail
        self.app._settings_timer.start()

    def _lesson_options(self, d: dict, plan):
        from . import lesson_ai as L
        s = self.app.settings
        return L.Options(style=L.STYLE_SCENARIO, minutes=s.lesson_minutes, break_min=s.lesson_break,
                         cls=str(d.get("cls") or "").strip(), topic=str(d.get("topic") or "").strip(), marks=False)

    def call_plan_create(self, d: dict) -> dict:
        """«Новый план» → план в списке навсегда и сразу выбран в «Новом уроке»."""
        from . import wizard
        p = wizard.plan_from_spec(str(d.get("title") or ""), list(d.get("stages") or []))
        self.app.store.insert(p)
        self.app.touch(p)
        self.app.settings.lesson_plan = p.id
        self.app._settings_timer.start()
        self.app.publish_now()
        return {"id": p.id}

    def call_use_cli(self, d: dict) -> dict:
        """«Использовать Claude Code / Codex (по подписке)» — нейросеть подключается одним щелчком."""
        from . import ai
        pid = {"claude": "claudeCli", "codex": "codexCli"}.get(str(d.get("which") or ""))
        p = ai.provider(pid) if pid else None
        if p is None or ai.cli_path(p) is None:
            raise ValueError("Эта программа не найдена на компьютере")
        self.app.settings.ai_provider = pid
        self.app.save_settings()
        self.app.publish_now()
        return {"provider": p.name}

    def call_copy_prompt(self, d: dict) -> bool:
        """«Скопировать задание»: урок (план, тема, класс, видео зарядок) или разбор кода — в буфер обмена."""
        from PySide6.QtGui import QGuiApplication
        from . import wizard
        plan = self._wizard_plan(d)
        self._remember_wizard(d, plan)
        material = str(d.get("material") or "")
        if d.get("what") == "code":
            text = wizard.copy_prompt("code", wizard.code_options(d.get("code") or {}, material), material=material)
        else:
            text = wizard.copy_prompt("lesson", self._lesson_options(d, plan), material=material, plan=plan,
                                      exercises=self.app.exercise_titles(plan))
        QGuiApplication.clipboard().setText(text)
        self.app._notify("Задание скопировано: вставьте его в свой чат (ChatGPT, GigaChat, DeepSeek…) вместе с "
                         "методичкой, а ответ — в поле ниже.", quiet=True)
        return True

    def call_paste_preview(self, d: dict) -> dict:
        """Что получится из вставленного: одна строка итога и замечания."""
        from . import wizard
        plan = self._wizard_plan(d)
        try:
            r = wizard.paste_parse(str(d.get("text") or ""), str(d.get("lang") or ""), plan=plan,
                                   slide=wizard.slide_maker(self._slides_pdf(d)))
        except ValueError as e:
            return {"ok": False, "summary": str(e)}
        empty = any(b.type == "image" and b.slide and not (b.text or "").strip() for b in r.template.blocks)
        return {"ok": True, "kind": r.kind, "summary": r.summary, "notes": r.notes, "slides_empty": empty}

    def _slides_pdf(self, d: dict) -> str:
        """Презентация для мест «Слайд N» (pdf; pptx — PowerPoint сохраняет PDF)."""
        path = str(d.get("slides") or "")
        if not path:
            return ""
        if path.lower().endswith(".pptx"):
            from . import slides
            return slides.export_pdf(path) or ""
        return path

    def call_clipboard_text(self, _d: dict) -> str:
        from PySide6.QtGui import QGuiApplication
        return QGuiApplication.clipboard().text()

    def call_wizard_create(self, d: dict) -> dict:
        """«Создать урок»: source manual | paste | ai. → {lesson} (урок открыт) или {job} (работа идёт)."""
        from . import ai, plans, wizard
        plan = self._wizard_plan(d)
        self._remember_wizard(d, plan)
        topic = str(d.get("topic") or "").strip()
        source = str(d.get("source") or "manual")
        if source == "manual":
            if plan is not None:
                t = self.app.store.insert(plans.new_topic(plan, topic or "Новый урок"))
            else:
                t = self.app.store.add(topic or "Новый урок")
            self.app.touch(t)
            self.app.open_lesson(t.id, ask=False)
            return {"lesson": t.id}
        if source == "paste":
            r = wizard.paste_parse(str(d.get("text") or ""), str(d.get("lang") or ""), plan=plan,
                                   slide=wizard.slide_maker(self._slides_pdf(d)))
            if topic and r.kind == "ответ нейросети":
                r.template.title = topic
            style = (wizard.code_options(d.get("code") or {}).style if d.get("what") == "code" else r.style)
            job = self.app.add_new_lesson(r.template, r.notes, style)
            return {"job": job} if job else {"lesson": r.template.id}
        if source != "ai":
            raise ValueError("неизвестный способ")
        if not ai.configured(self.app.settings):
            raise ValueError("Нейросеть не подключена — подключите её или «Скопировать задание» для своего чата")
        c = ai.config(self.app.settings)
        what = "code" if d.get("what") == "code" else "lesson"
        m = wizard.gather(list(d.get("files") or []), str(d.get("material") or ""),
                          agent=c is not None and c.provider.kind == "cli" and what == "lesson")
        if what == "code":
            if not m.text.strip():
                raise ValueError("Вставьте код или выберите файл с кодом")
            opt = wizard.code_options(d.get("code") or {}, m.text)
            fn = wizard.lesson_task(self.app.settings, opt, material=m.text, what="code")
            title = "Разбор кода" + (f" «{topic}»" if topic else "")
        else:
            opt = self._lesson_options(d, plan)
            fn = wizard.lesson_task(self.app.settings, opt, plan=plan, exercises=self.app.exercise_titles(plan),
                                    material=m.text, files=m.files, pdf=m.pdf)
            title = f"Урок «{topic}»" if topic else "Новый урок"
        notes = list(m.notes)

        def done(res: dict) -> None:
            t = res["template"]
            if what == "code" and topic:
                t.title = topic
            self.app.add_new_lesson(t, notes + list(res.get("notes") or []), res.get("style") or "")
        return {"job": self.app.jobs.start("ai", fn, done, title)}

    def cmd_live_next(self, _d: dict) -> None:
        """Маленький режим, «Следующий этап»: следующий этап урока или блок вебинара — с этой минуты (до начала —
        первый)."""
        ef = self.app.efir
        if ef.live_webinar() is None:
            return
        ag = ef.agenda()
        if ag.phase == "after":
            return
        nxt = ag.index + 1 if ag.phase == "live" else 0
        if nxt < len(ef.segments()):
            ef.start_now(nxt)
            self.app.lesson.schedule_publish()

    def cmd_job_cancel(self, d: dict) -> None:
        self.app.jobs.cancel(str(d.get("id") or ""))

    def cmd_job_skip(self, d: dict) -> None:
        self.app.jobs.skip(str(d.get("id") or ""))

    def cmd_job_dismiss(self, d: dict) -> None:
        self.app.jobs.dismiss(str(d.get("id") or ""))

    # ------------------------------------------------------------ листы урока (Task 10)
    def _many(self, d: dict) -> list:
        """Уроки листа: all — все, ids / id — эти."""
        if d.get("all"):
            return list(self.app.store.templates)
        ids = d.get("ids") or ([d["id"]] if d.get("id") else [])
        ts = [t for t in (self.app.store.get(str(i)) for i in ids) if t is not None]
        if not ts:
            raise ValueError("урок не найден")
        return ts

    def call_export_sizes(self, d: dict) -> dict:
        """«Экспорт» .autoprint: сколько весят картинки урока и оформление экрана учеников, есть ли план."""
        from .storage import KIND_PLAN
        ts = self._many(d)
        base = self.app.package_media_size(ts, include_looks=False)
        full = self.app.package_media_size(ts, include_looks=True)
        return {"pics": base, "looks": max(0, full - base), "linked": any(t.plan_id or t.kind == KIND_PLAN for t in ts)}

    def call_export(self, d: dict) -> dict:
        """Сохранить урок (или все) в path: package | md | ipynb | students | json."""
        ts = self._many(d)
        fmt, path = str(d.get("fmt") or "package"), str(d.get("path") or "")
        if not path:
            raise ValueError("не выбран файл")
        if fmt == "package":
            s = self.app._package_to(ts, path, bool(d.get("plans", True)), bool(d.get("looks", True)))
            if s is None:
                raise ValueError("файл не сохранился")
            return s
        if fmt not in ("md", "ipynb", "students", "json") or len(ts) != 1:
            raise ValueError("неизвестный формат")
        if not self.app.export_template(ts[0], fmt, path):
            raise ValueError("файл не сохранился")
        return {"path": path}

    def call_print_pdf(self, d: dict) -> dict:
        path = str(d.get("path") or "")
        if not path or not self.app.window.print_pdf(path):
            raise ValueError("PDF не сохранился")
        self.app._notify(f"PDF сохранён: {path}", quiet=True)
        return {"path": path}

    def call_print(self, _d: dict) -> bool:
        return bool(self.app.window.print_dialog())

    def call_plan_link(self, d: dict) -> dict:
        """«План урока…»: link (plan) | unlink | make."""
        t = self._t(d)
        op = str(d.get("op") or "")
        if op == "link":
            notes = self.app.link_plan(t, str(d.get("plan") or ""))
            return {"plan": t.plan_id, "notes": notes or []}
        if op == "unlink":
            self.app.unlink_plan(t)
            return {"plan": ""}
        if op == "make":
            p = self.app.make_plan(t)
            if p is None:
                raise ValueError("из этого урока план не сделать")
            return {"plan": p.id}
        raise ValueError("неизвестное действие")

    def call_prompt(self, d: dict) -> bool:
        """«Скопировать задание» для своего чата (урок со слайдами — по слайдам)."""
        self.app.lesson.chat_prompt(self._t(d))
        return True

    def call_answer(self, d: dict) -> bool:
        text = str(d.get("text") or "").strip()
        if not text:
            raise ValueError("Вставьте ответ нейросети")
        self.app.lesson._apply_answer(self._t(d), text)
        return True

    def call_slides_fill(self, d: dict) -> bool:
        return bool(self.app.lesson.fill_slides_from(self._t(d), str(d.get("path") or "")))

    def call_place_image(self, d: dict) -> dict:
        """Картинка с диска в урок (место «Нужна картинка», «Выбрать файл…», файл на окне): копия в data/media,
        блок-картинка после after. Как вставка со страницы, только файл читает программа."""
        from .efir.server import UPLOAD_LIMIT
        p = Path(str(d.get("path") or ""))
        ext = p.suffix.lower()
        if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            raise ValueError("Это не картинка: подойдут PNG, JPG, GIF или WebP")
        if not p.is_file():
            raise ValueError(f"Файла нет: {p}")
        if p.stat().st_size > UPLOAD_LIMIT:
            raise ValueError("Картинка слишком большая")
        return self.app.lesson.add_image({"lesson": str(d.get("lesson") or ""), "after": str(d.get("after") or ""),
                                          "id": str(d.get("id") or ""), "ext": ".jpg" if ext == ".jpeg" else ext,
                                          "data": p.read_bytes()})

    def call_pick_save(self, d: dict) -> str:
        """Куда сохранить: системное окно → путь или "" (передумали)."""
        name = "".join(c for c in str(d.get("name") or "") if c not in '\\/:*?"<>|').strip()
        path, _ = QFileDialog.getSaveFileName(self.app.window, str(d.get("title") or "Сохранить"), name,
                                              str(d.get("filter") or "Все файлы (*.*)"))
        return str(path or "")
