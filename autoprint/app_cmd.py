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
THREAD_CALLS = {"ai_check", "ai_models"}      # вызовы без окна и настроек Qt — в потоке сервера


def open_url(url: str) -> bool:
    """Открыть ссылку в браузере по умолчанию (тесты подменяют: браузер не открывается)."""
    from PySide6.QtCore import QByteArray, QUrl
    from PySide6.QtGui import QDesktopServices
    return QDesktopServices.openUrl(QUrl.fromEncoded(QByteArray(url.encode("utf-8"))))

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
        if isinstance(d, dict) and d.get("cmd") in THREAD_CALLS:
            # запрос в сеть (проверка нейросети, список моделей) — прямо здесь: окно программы не замирает
            try:
                return 200, self.call(d)
            except Exception as e:  # noqa: BLE001
                return 200, {"ok": False, "error": str(e) or type(e).__name__}
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

    # ------------------------------------------------------------ «Настройки» (Task 14)
    def call_set(self, d: dict) -> dict:
        """Поле настроек: значение проверяется (settings_spec), применяется сразу. → значение, как оно есть теперь
        (автозапуск мог не включиться)."""
        from .settings_spec import clean
        key = str(d.get("key") or "")
        v = clean(key, d.get("value"))
        s = self.app.settings
        if getattr(s, key) != v:
            setattr(s, key, v)
            self.app.on_setting_changed(key)
            if key.startswith("page_") or key in ("start_screen", "start_compact"):
                self.app.lesson.schedule_publish()
        self.app.publish_now()
        return {"value": getattr(s, key)}

    def call_set_hotkey(self, d: dict) -> dict:
        """Хоткей: подходит ли, не занят ли другим, «Старт / пауза» — обязателен. → {ok, error}."""
        from .hotkeys import parse_hotkey
        from .settings_spec import HOTKEY_TITLES
        s = self.app.settings
        key, value = str(d.get("key") or ""), str(d.get("value") or "").strip()
        if key not in dict(HOTKEY_TITLES):
            raise ValueError("нет такого хоткея")
        if key == "hotkey_toggle" and not value:
            return {"ok": False, "error": "Хоткей «Старт / пауза» нужен всегда."}
        if value:
            wanted = parse_hotkey(value)        # сравниваются клавиши, а не текст: «Ctrl++» и «Ctrl+=» — одно
            if wanted is None:
                return {"ok": False, "error": f"«{value}» — не подходит"}
            for k, title in HOTKEY_TITLES:
                if k != key and parse_hotkey(getattr(s, k)) == wanted:
                    return {"ok": False, "error": f"«{value}» уже назначен: «{title}»."}
        if getattr(s, key) != value:
            setattr(s, key, value)
            self.app.on_setting_changed("hotkeys")
        self.app.publish_now()
        return {"ok": True}

    def cmd_view(self, d: dict) -> None:
        """Страница открыла экран (адрес) — запомнить для следующего запуска."""
        self.app.remember_view(str(d.get("hash") or ""))

    def cmd_hotkey_capture(self, d: dict) -> None:
        """Пока страница ждёт сочетание — глобальные хоткеи сняты."""
        self.app.hotkey_capture(bool(d.get("on")))

    def cmd_test_sound(self, _d: dict) -> None:
        s = self.app.settings
        self.app.test_sound(s.sound_style, s.sound_volume)

    def call_sound_delete(self, _d: dict) -> bool:
        from .sounds import DEFAULT_STYLE, delete_custom, is_custom
        s = self.app.settings
        key = s.sound_style
        if not is_custom(key):
            return False
        s.sound_style = DEFAULT_STYLE                 # сначала переключить: файлы набора освободятся
        self.app.on_setting_changed("sound_style")
        delete_custom(key)
        self.app.publish_now()
        return True

    def cmd_record_sound(self, _d: dict) -> None:
        """«Записать звук клавиатуры…» — лист записи (RecordFlow)."""
        self.app.open_record()

    def call_record(self, d: dict):
        """Шаги листа записи: op = monitor | quiet | start | stop | skip | preview | save | close."""
        flow = self.app.record
        op = str(d.get("op") or "")
        if op == "close":
            self.app.close_record()
            return True
        if flow is None:
            raise ValueError("Запись уже закрыта")
        kind = str(d.get("kind") or "")
        device = d.get("device")
        device = str(device) if device is not None else None
        if op == "monitor":
            return flow.monitor(device)
        if op == "quiet":
            flow.quiet()
            return True
        if op == "start":
            return flow.start(kind, device)
        if op == "stop":
            flow.stop()
            return True
        if op == "skip":
            flow.skip(kind)
            return True
        if op == "preview":
            return flow.preview(kind)
        if op == "save":
            key = flow.save(str(d.get("name") or ""))
            s = self.app.settings
            s.sound_style = key
            self.app.close_record()
            self.app.on_setting_changed("sound_style")
            self.app._notify("Свой звук сохранён и выбран. «Послушать» — как он звучит при печати.")
            return key
        raise ValueError("неизвестный шаг записи")

    def cmd_restart(self, _d: dict) -> None:
        self.app.restart_app()

    def cmd_open_log(self, _d: dict) -> None:
        self.app._open_log()

    def cmd_open_data(self, _d: dict) -> None:
        self.app._open_data_dir()

    def cmd_update_check(self, _d: dict) -> None:
        self.app.check_updates(manual=True)

    def cmd_report(self, _d: dict) -> None:
        self.app.open_report()

    # ------------------------------------------------------------ «Сообщить об ошибке» (Task 15)
    def _report(self, d: dict) -> dict:
        from . import report
        inc = bool(d.get("include_settings", True))
        key = inc
        if getattr(self, "_rep_key", None) != key:       # сбор (журнал, система) — не на каждую букву описания
            self._rep, self._rep_key = report.collect(include_settings=inc, settings=self.app.settings), key
        self._rep["description"] = report.sanitize(str(d.get("description") or "").strip())
        return self._rep

    def call_report(self, d: dict) -> dict:
        """Отчёт для предпросмотра: markdown — всё, что уйдёт автору; crash — последняя ошибка из журнала."""
        from . import report
        if d.get("fresh"):
            self._rep_key = None
        r = self._report(d)
        crash = report.last_crash(r)
        return {"markdown": report.to_markdown(r), "log_lines": report.LOG_TAIL_LINES,
                "crash": {"time": r["crashes"][0]["time"], "text": report.crash_summary(crash)[:150]} if crash else None,
                "zip_name": report.default_zip_name(), "desktop": str(_desktop())}

    def call_report_save(self, d: dict) -> dict:
        from . import report
        path = Path(str(d.get("path") or ""))
        if not str(path) or str(path) == ".":
            raise ValueError("Не указано, куда сохранить")
        if path.suffix.lower() != ".zip":
            path = path.with_name(path.name + ".zip")
        try:
            saved = report.save_zip(self._report(d), path)
        except OSError as e:
            raise ValueError(f"Не удалось сохранить отчёт: {e}") from None
        self._rep_saved = saved
        return {"path": str(saved), "name": saved.name, "folder": saved.parent.name}

    def call_report_github(self, d: dict) -> dict:
        """«Открыть на GitHub»: новое сообщение (краткий текст в ссылке, файл .zip — приложить вручную)."""
        from PySide6.QtGui import QGuiApplication
        from . import report
        r = self._report(d)
        saved = getattr(self, "_rep_saved", None)
        if saved is not None and not Path(saved).exists():
            saved = None
        url = report.issue_url(r, report.default_title(r), saved)
        if not open_url(url):
            QGuiApplication.clipboard().setText(url)
            return {"ok": False}
        return {"ok": True, "saved": saved is not None}

    def call_report_copy(self, d: dict) -> bool:
        from PySide6.QtGui import QGuiApplication
        from . import report
        QGuiApplication.clipboard().setText(report.to_markdown(self._report(d)))
        return True

    def cmd_open_log_folder(self, _d: dict) -> None:
        from .report import open_log_folder
        open_log_folder()

    # ------------------------------------------------------------ «Доступно обновление» (Task 15)
    def cmd_update_install(self, _d: dict) -> None:
        self.app.update_install()

    def call_update_skip(self, _d: dict) -> bool:
        rel = self.app.updates.latest
        if rel is None:
            return False
        self.app.settings.update_skip_version = rel.version
        self.app.save_settings()
        self.app.publish_now()
        return True

    def call_ai_set(self, d: dict) -> dict:
        """Нейросеть (which: main | backup): provider, url, key (шифруется DPAPI), model. → {problem}. Ключ назад
        не отдаётся."""
        from . import ai
        s = self.app.settings
        field = "ai_backup_provider" if d.get("which") == "backup" else "ai_provider"
        if "provider" in d:
            pid = str(d.get("provider") or "")
            if pid and ai.provider(pid) is None:
                raise ValueError("нет такой нейросети")
            setattr(s, field, pid)
        pid = getattr(s, field)
        if pid:
            if "url" in d:
                s.ai_urls[pid] = str(d.get("url") or "").strip()
            if "key" in d:
                s.ai_keys[pid] = ai.protect(str(d.get("key") or "").strip())
            if "model" in d:
                s.ai_models[pid] = str(d.get("model") or "").strip()
        self.app.on_setting_changed("ai")
        self.app.publish_now()
        c = ai.config(s, pid) if pid else None
        return {"problem": (ai.problem(c) or "") if c else ""}

    def _ai_config(self, d: dict):
        from . import ai
        s = self.app.settings
        pid = getattr(s, "ai_backup_provider" if d.get("which") == "backup" else "ai_provider")
        c = ai.config(s, pid) if pid else None
        if c is None:
            raise ValueError("Нейросеть не выбрана")
        return c

    def call_ai_models(self, d: dict) -> list:
        """Список моделей сервера (в потоке сервера: окно не замирает)."""
        from . import ai
        try:
            return ai.list_models(self._ai_config(d))
        except ai.AIError as e:
            raise ValueError(f"Список моделей не получен: {e}") from None

    def call_ai_check(self, d: dict) -> dict:
        """«Проверить»: короткий запрос — время и ответ (в потоке сервера)."""
        from . import ai
        c = self._ai_config(d)
        try:
            ms, sample = ai.check(c)
        except ai.AIError as e:
            return {"ok": False, "text": str(e)}
        return {"ok": True, "ms": ms, "text": f"{c.provider.name} ответил: «{sample}»"}

    def call_copy_all_media(self, _d: dict) -> dict:
        """«Скопировать файлы всех оформлений в программу» (Настройки → Урок)."""
        return self.call_efir_copy_files({"all": True})

    # ------------------------------------------------------------ «Эфир» (Task 13)
    @property
    def _ef(self):
        return self.app.efir

    def cmd_efir_opened(self, _d: dict) -> None:
        """Первое открытие «Эфира»: шаблонов нет, а «Таймер вебинара» есть — перенести его шаблоны сами."""
        self._ef.auto_import_legacy()

    def call_efir_launch(self, d: dict) -> dict:
        """«Запустить»: start "" — сейчас, «ЧЧ:ММ» — в это время. Идёт другой эфир — заменить только с force
        (страница спросила). → {ok, other}."""
        ef = self._ef
        cur = ef.live_webinar()
        wid = str(d.get("id") or "")
        if cur is not None and cur.id != wid and not d.get("force"):
            return {"ok": False, "other": cur.title}
        ok = ef.launch(wid, str(d.get("start") or ""), force=True)
        self.app.publish_now()
        return {"ok": bool(ok), "other": ""}

    def cmd_efir_stop(self, _d: dict) -> None:
        self._ef.stop_live()

    def cmd_efir_start_block(self, d: dict) -> None:
        """«Начать этот блок сейчас» (без index — текущий), «Начать с блока…»."""
        idx = d.get("index")
        self._ef.start_now(None if idx is None else int(idx))
        self.app.publish_now()

    def cmd_efir_set_start(self, d: dict) -> None:
        """«Изменить начало…» ("" — с первого блока с этой минуты)."""
        self._ef.set_start(str(d.get("start") or "").strip())
        self.app.publish_now()

    def cmd_efir_screen(self, d: dict) -> None:
        """Экран учеников из табло вебинара (урок не нужен): background | break | exercise | break_adjust |
        break_pause | exercise_pause."""
        ef = self._ef
        op = str(d.get("op") or "")
        if op == "background":
            ef.show_background()
        elif op == "break":
            w = ef.webinar or ef.live_webinar()
            ef.start_break(int(d.get("minutes") or 0) or (w.break_min if w else 10))
        elif op == "exercise":
            ef.start_exercise(int(d.get("index") or 0))
        elif op == "break_adjust":
            ef.break_adjust(max(-3600, min(3600, int(d.get("seconds") or 0))))
        elif op == "break_pause":
            ef.break_pause()
        elif op == "exercise_pause":
            ef.exercise_pause()

    def call_efir_put_webinar(self, d: dict) -> dict:
        w = self._ef.put_webinar(dict(d.get("webinar") or {}))
        self.app.publish_now()
        return {"id": w.id}

    def call_efir_put_look(self, d: dict) -> dict:
        """Сохранить оформление. Редактор мог держать пути, которые уже скопированы в программу, — они заменяются."""
        lk = self._ef.put_look(dict(d.get("look") or {}))
        if self.app.media_moves:
            from .media_copy import remap
            new = remap(lk, self.app.media_moves)
            if new != lk:
                lk = new
                self._ef.save_look(new)
        self.app.lesson.schedule_publish()
        self.app.publish_now()
        return {"id": lk.id}

    def call_efir_delete_webinar(self, d: dict) -> bool:
        self._ef.delete_webinar(str(d.get("id") or ""))
        self.app.publish_now()
        return True

    def call_efir_delete_look(self, d: dict) -> bool:
        lid = str(d.get("id") or "")
        users = self._ef.look_users(lid, self.app.store.templates)
        if users:
            raise ValueError("Оформление используется: " + ", ".join(users[:5]) + " — сначала смените его там")
        if not self._ef.delete_look(lid, self.app.store.templates):
            raise ValueError("Оформление не удалено")
        self.app.publish_now()
        return True

    def call_efir_copy_webinar(self, d: dict) -> dict:
        c = self._ef.copy_webinar(str(d.get("id") or ""))
        self.app.publish_now()
        return {"id": c.id if c else ""}

    def cmd_efir_move(self, d: dict) -> None:
        self._ef.move_webinar(str(d.get("id") or ""), int(d.get("d") or 1))

    def call_efir_new(self, d: dict) -> dict:
        """«Новый эфир»: empty — пустой (по образцу), paste — текст (JSON или ответ нейросети), json — файл, legacy —
        из «Таймера вебинара». → {ids}."""
        from .efir.model import parse_webinars, sample_webinar
        how = str(d.get("how") or "empty")
        ef = self._ef
        if how == "legacy":
            n = ef.import_legacy()
            self.app.publish_now()
            return {"ids": [w.id for w in ef.store.visible()[-n:]] if n else []}
        if how == "empty":
            w = sample_webinar()
            w.title = "Новый эфир"
            items = [w]
        elif how == "json":
            path = Path(str(d.get("path") or ""))
            items = parse_webinars(path.read_text(encoding="utf-8-sig"))
        else:
            items = parse_webinars(str(d.get("text") or ""))
        added = ef.add_webinars(items)
        self.app.publish_now()
        return {"ids": [w.id for w in added]}

    def call_efir_ai(self, d: dict) -> dict:
        """«По описанию — нейросеть»: в фоне; нет нейросети — задание в буфер (страница скажет)."""
        from . import ai
        from .efir.model import ai_prompt, parse_webinars
        text = str(d.get("text") or "").strip()
        if not text:
            raise ValueError("Опишите эфир: что, сколько минут, где перерыв и зарядки")
        if not ai.configured(self.app.settings):
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(ai_prompt() + text)
            return {"copied": True}

        def work(job):
            answer, _who = ai.ask(self.app.settings, ai_prompt(), text, job.cancel_event, on_status=job.status,
                                  on_progress=job.progress)
            return parse_webinars(answer)

        def done(items):
            added = self._ef.add_webinars(items)
            if added:
                self.app.show_view(f"#/efir/{added[0].id}/edit")
        return {"job": self.app.jobs.start("ai", work, done, "Расписание эфира")}

    def call_efir_ai_prompt(self, d: dict) -> bool:
        """«Скопировать для нейросети» / «Скопировать задание с примером»."""
        from PySide6.QtGui import QGuiApplication
        from .efir.model import ai_prompt
        w = self._ef.store.get(str(d.get("id") or "")) if d.get("id") else None
        QGuiApplication.clipboard().setText(ai_prompt(w))
        self.app._notify("Задание для нейросети скопировано: допишите в конце своё расписание.", quiet=True)
        return True

    def call_efir_export(self, d: dict) -> dict:
        from .efir.model import export_json
        ws = [self._ef.store.get(str(d.get("id")))] if d.get("id") else self._ef.store.visible()
        ws = [w for w in ws if w is not None]
        path = str(d.get("path") or "")
        if not ws or not path:
            raise ValueError("нечего сохранять")
        Path(path).write_text(export_json(ws), encoding="utf-8")
        self.app._notify(f"Сохранено: {path}", quiet=True)
        return {"path": path}

    def call_efir_take_file(self, d: dict) -> dict:
        """Выбранный для оформления файл: копия в программу (настройка «Копировать картинки и видео в программу»)."""
        from . import media_copy, storage
        from .media_copy import file_status, take_file
        path = str(d.get("path") or "")
        if not Path(path).is_file():
            raise ValueError(f"Файла нет: {path}")
        job = ""
        if self.app.settings.copy_media and file_status(path) == "outside":
            dest = storage.DATA_DIR / storage.MEDIA_FOLDER
            have = media_copy.existing_copy(Path(path), dest)
            if have is not None or Path(path).stat().st_size <= media_copy.TAKE_SYNC_LIMIT:
                path = str(have) if have is not None else take_file(path)
            else:                           # большое видео — в фоне: окно (и идущий урок) не замирает
                src = path
                ef = self._ef

                def done(out: str) -> None:
                    self.app.media_moves[src] = out
                    for lk in list(ef.store.looks):        # уже сохранили оформление с этим файлом — путь на копию
                        new = media_copy.remap(lk, {src: out})
                        if new != lk:
                            ef.save_look(new)
                    self.app.publish_now()
                job = self.app.jobs.start("copy", lambda _job: take_file(src), done, f"Копирую «{Path(src).name}»")
        return {"path": path, "name": Path(path).name, "size": Path(path).stat().st_size, "status": file_status(path),
                "url": self._ef.server.media_url(path), "job": job}

    def call_efir_copy_files(self, d: dict) -> dict:
        """«Скопировать в программу»: файлы оформления (или всех оформлений — all) — в фоне, с ходом и отменой; ссылки
        меняются только после удачной копии."""
        from . import media_copy, storage
        ef = self._ef
        looks = list(ef.store.looks) if d.get("all") else [ef.store.look(str(d.get("id") or ""))]
        looks = [lk for lk in looks if lk is not None and media_copy.outside_size(lk) > 0]
        if not looks:
            return {"job": ""}
        dest = storage.DATA_DIR / storage.MEDIA_FOLDER

        def work(job):
            out = []
            for k, lk in enumerate(looks):
                out.append(media_copy.copy_look_files(
                    lk, dest, progress=lambda i, n, name, k=k: job.progress("photos", i, f"{name} ({i} из {n})"),
                    cancel=job.cancel_event))
            return out

        def done(new_looks):
            # оформление могли поправить, пока шла копия: берётся текущее, в нём меняются только скопированные пути
            for lk in new_looks:
                moves = getattr(lk, "copied", {}) or {}
                self.app.media_moves.update(moves)
                cur = ef.store.look(lk.id)
                if cur is not None:
                    ef.save_look(media_copy.remap(cur, moves))
            self.app._notify("Файлы оформлений скопированы в программу.", quiet=True)
        title = "Копирую файлы оформлений" if d.get("all") else f"Копирую файлы «{looks[0].title}»"
        return {"job": self.app.jobs.start("copy", work, done, title)}

    def cmd_efir_preview_break(self, d: dict) -> None:
        """«Предпросмотр перерыва»: вкладка браузера с перерывом по несохранённым настройкам (ученикам не видно)."""
        from .efir.model import Webinar, compose, look_from_dict
        lk = look_from_dict(dict(d.get("look") or {}))
        w = compose(Webinar(title="Предпросмотр", break_min=int(d.get("minutes") or 10)), lk)
        self._ef.preview_break(w)

    def cmd_efir_gallery(self, d: dict) -> None:
        self._ef.open_gallery(str(d.get("current") or ""))

    def cmd_efir_open_tab(self, _d: dict) -> None:
        self._ef.open_tab()

    def cmd_efir_copy_url(self, _d: dict) -> None:
        self._ef.copy_url()

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
        if d.get("dir") and name:                         # папка по умолчанию (отчёт — на Рабочий стол)
            name = str(Path(str(d["dir"])) / name)
        path, _ = QFileDialog.getSaveFileName(self.app.window, str(d.get("title") or "Сохранить"), name,
                                              str(d.get("filter") or "Все файлы (*.*)"))
        return str(path or "")


def _desktop() -> Path:
    from PySide6.QtCore import QStandardPaths
    d = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
    return Path(d) if d else Path.home()
