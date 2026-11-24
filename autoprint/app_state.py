"""Состояние окна программы (канал app): что показывает страница кроме самого урока.

Урок, открытый на экране урока, идёт своим каналом lesson (scenario.lesson_state). Здесь — список уроков и
планов, идёт ли урок или эфир, набор кода, обновление, нейросеть, уведомления, окно, переход на экран.
Без ключей нейросети и личных путей сверх нужного странице.
"""
from __future__ import annotations

from . import __version__, scenario
from .scenario_import import looks_like_scenario
from .storage import BLOCK_IMAGE, BLOCK_STAGE, KIND_PLAN, PROFILES, STRUCTURES

PREF_KEYS = ("page_plan", "page_past", "page_stage_timer", "start_screen", "start_timer")


def _cli_found() -> dict:
    """Установлены ли Claude Code и Codex (ищется один раз за запуск: shutil.which ходит по PATH)."""
    global _CLI
    if _CLI is None:
        from . import ai
        _CLI = {"claude": ai.cli_path(ai.provider("claudeCli")) is not None,
                "codex": ai.cli_path(ai.provider("codexCli")) is not None}
    return _CLI


_CLI: dict | None = None


def ai_state(settings) -> dict:
    from . import ai
    c = ai.config(settings)
    return {"configured": ai.configured(settings), "provider": settings.ai_provider,
            "name": c.provider.name if c is not None else "", "model": c.model if c is not None else "",
            "cli": _cli_found()}


def plan_state(p, topics: int) -> dict:
    stages = [b for b in p.blocks if b.type == BLOCK_STAGE]
    return {"id": p.id, "title": p.title, "total": sum(max(0, int(b.minutes or 0)) for b in stages),
            "stages": [{"title": b.title, "minutes": int(b.minutes or 0), "kind": b.stage_kind or ""} for b in stages],
            "topics": topics}


_LEGACY: bool | None = None


def _legacy_found(ef) -> bool:
    """Найден ли «Таймер вебинара» (ищется один раз за запуск)."""
    global _LEGACY
    if _LEGACY is None:
        try:
            _LEGACY = ef.legacy_folder() is not None
        except OSError:
            _LEGACY = False
    return _LEGACY


def _look_state(lk, ef, lessons) -> dict:
    from .media_copy import file_status, outside_size

    def bg(v: str) -> dict:
        kind, _, val = (v or "").partition(":")
        d = {"value": v or "", "kind": kind if v else ""}
        if kind == "image":
            d.update(status=file_status(val), name=val.replace("\\", "/").rsplit("/", 1)[-1],
                     url=ef.server.media_url(val) if file_status(val) != "missing" else "")
        return d
    ex = []
    for e in lk.exercises:
        st = file_status(e.path)
        size = 0
        if st != "missing":
            from pathlib import Path
            size = Path(e.path).stat().st_size
        ex.append({"title": e.title, "path": e.path, "name": e.path.replace("\\", "/").rsplit("/", 1)[-1], "status": st,
                   "size": size})
    font_status = file_status(lk.font[5:]) if (lk.font or "").startswith("file:") else "ok"
    return {"id": lk.id, "title": lk.title, "background": bg(lk.background), "caption": lk.caption, "exercises": ex,
            "break_countdown": lk.break_countdown, "break_background": bg(lk.break_background),
            "break_title": lk.break_title, "break_show_title": lk.break_show_title, "break_done": lk.break_done,
            "font": lk.font, "font_status": font_status, "text_color": lk.text_color,
            "users": ef.look_users(lk.id, lessons), "outside": outside_size(lk)}


def _provider_state(s, which: str) -> dict:
    """Нейросеть (основная или запасная) для «Настроек»: адрес, модель, есть ли ключ — сам ключ не уходит."""
    from . import ai
    pid = getattr(s, which) or ""
    c = ai.config(s, pid) if pid else None
    return {"id": pid, "url": c.url if c else "", "model": c.model if c else "",
            "key_set": bool(s.ai_keys.get(pid)) if pid else False, "problem": (ai.problem(c) or "") if c else ""}


def settings_state(app) -> dict:
    """«Настройки»: поля экрана (settings_spec.FIELDS), хоткеи, звуки, нейросети, обновления. Без ключей нейросети."""
    from . import __version__ as version, ai, updater
    from .settings_spec import FIELDS, HOTKEY_TITLES
    from .sounds import available_styles, is_custom
    s = app.settings
    d = {k: getattr(s, k) for k in FIELDS}
    cli = _cli_found()
    d.update(
        hotkeys=[{"key": k, "title": t, "value": getattr(s, k)} for k, t in HOTKEY_TITLES],
        sound_styles=[[k, title, is_custom(k)] for k, title in available_styles().items()],
        providers=[{"id": p.id, "name": p.name, "kind": p.kind, "hint": p.hint, "url": p.url, "needs_key": p.needs_key,
                    "models": [list(m) for m in p.models], "model": p.model,
                    "installed": bool(cli.get("claude" if p.id == "claudeCli" else "codex")) if p.kind == "cli" else None}
                   for p in ai.PROVIDERS],
        ai={"main": _provider_state(s, "ai_provider"), "backup": _provider_state(s, "ai_backup_provider")},
        version=version, update_last_check=s.update_last_check, can_self_update=updater.can_self_update(),
        looks_outside=sum(lk.get("outside", 0) for lk in efir_state_cached(app).get("looks", [])),
        profiles=[[k, t] for k, t in PROFILES.items()], releases_url=updater.RELEASES_PAGE,
    )
    return d


def release_state(app) -> dict | None:
    """Лист «Доступно обновление»: найденная версия, что нового и что сейчас можно сделать."""
    m = app.updates
    rel = m.latest
    if rel is None:
        return None
    return {"version": rel.version, "name": rel.name, "notes": rel.notes or "", "published": rel.published,
            "prerelease": bool(rel.prerelease), "current": __version__, "page_url": rel.page_url,
            "installable": bool(m.installable(rel)), "reason": m.block_reason(rel) if not m.installable(rel) else "",
            "staged": bool(m.staged and m.staged[0].version == rel.version), "downloading": bool(m.downloading),
            "frozen": m.mode == "frozen", "progress": app.update_progress, "error": app.update_error,
            "skipped": app.settings.update_skip_version == rel.version}


def efir_state_cached(app) -> dict:
    return getattr(app, "_efir_state_last", None) or efir_state(app)


def efir_state(app) -> dict:
    """Раздел «Эфир»: расписания (без служебных эфиров уроков), оформления с файлами, идёт ли вебинар, экран."""
    from .efir.model import ANIMATIONS, FONTS
    ef = app.efir
    live = ef.store.live
    looks = {lk.id: lk for lk in ef.store.looks}
    webinars = [{"id": w.id, "title": w.title, "start": w.start, "break_min": w.break_min, "look_id": w.look_id,
                 "look": looks[w.look_id].title if w.look_id in looks else "",
                 "schedule": [{"name": a.name, "min": a.min, "kind": a.kind or "", "demo": a.demo} for a in w.schedule],
                 "total": w.total_min, "live": bool(live and live.webinar_id == w.id)} for w in ef.store.visible()]
    return {"webinars": webinars, "looks": [_look_state(lk, ef, app.store.templates) for lk in ef.store.looks],
            "live_id": live.webinar_id if live else "", "mode": ef.mode, "tab": ef.tab_status()[0],
            "tab_open": bool(ef.server.running and ef.clients > 0), "legacy_found": _legacy_found(ef),
            "imported_legacy": bool(ef.store.imported_legacy), "animations": [list(a) for a in ANIMATIONS],
            "fonts": [list(f) for f in FONTS], "picked": dict(getattr(app, "efir_picked", {"seq": 0, "value": ""})),
            "brk_ends": int(ef.brk_ends * 1000) if ef.mode == "break" else 0,
            "break_paused": ef.mode == "break" and ef.brk_left_paused is not None,
            "exercises": [e.title for e in (ef.webinar.exercises if ef.webinar else [])], "copy_media": app.settings.copy_media}


def app_state(app) -> dict:
    from .app_core import lesson_meta
    from .ui.theme import theme
    s = app.settings
    store = app.store
    plan_titles = {t.id: t.title for t in store.templates if t.kind == KIND_PLAN}
    lessons = []
    for x, t in zip(scenario.lessons_state(store.templates), store.templates):
        x["plan_id"] = t.plan_id if t.plan_id in plan_titles else ""
        x["meta"] = lesson_meta(t, plan_title=plan_titles.get(t.plan_id, ""),
                                topics=len(store.topics_of(t.id)) if t.kind == KIND_PLAN else 0)
        # меню урока: «Подставить слайды…» — есть пустые «Слайд N»; «Разложить по этапам» — похоже на сценарий
        x["stages"] = sum(1 for b in t.blocks if b.type == BLOCK_STAGE)
        x["slides_empty"] = any(b.type == BLOCK_IMAGE and b.slide and not (b.text or "").strip() for b in t.blocks)
        x["scenario"] = looks_like_scenario(t.blocks)
        lessons.append(x)
    plans = [plan_state(p, len(store.topics_of(p.id))) for p in store.templates if p.kind == KIND_PLAN]
    w = app.efir.live_webinar()
    live = None
    if w is not None:
        ag = app.efir.agenda()
        segs = app.efir.segments()
        cur = ag.current
        live = {"lesson_id": app.efir.live_lesson_id(), "webinar_id": w.id, "title": w.title, "phase": ag.phase,
                "index": ag.index, "count": len(segs), "name": cur.activity.name if cur is not None else "",
                "ends_ms": int(cur.end.timestamp() * 1000) if cur is not None else 0,
                "start_ms": int(ag.start.timestamp() * 1000) if ag.start else 0,
                "end_ms": int(ag.end.timestamp() * 1000) if ag.end else 0,
                # повестка — для маленького режима (урок и вебинар одинаково): этапы с часами
                "segments": [{"name": sg.activity.name, "kind": sg.activity.kind or "", "demo": sg.activity.demo,
                              "start_ms": int(sg.start.timestamp() * 1000), "end_ms": int(sg.end.timestamp() * 1000)}
                             for sg in segs]}
    win = app.window
    efir = app._efir_state_last = efir_state(app)
    return {
        "version": __version__,
        "dark": bool(theme.dark),
        "zoom": int(s.page_zoom or 100),
        "prefs": {k: getattr(s, k) for k in PREF_KEYS},
        "lessons": lessons,
        "plans": plans,
        "continue_id": next((x for x in (s.page_lesson, app.printer.focus_id)
                             if x and store.get(x) is not None and store.get(x).kind != KIND_PLAN), ""),
        "focus_id": app.printer.focus_id,
        "live": live,
        "print": app.printer.snapshot(),
        "update": app.update_info,
        "ai": ai_state(s),
        "jobs": app.jobs.state() if app.jobs is not None else [],
        "notice": dict(app.notice),
        "notices": [dict(n) for n in getattr(app, "notices", [])],
        "window": {"compact": bool(win.compact), "pinned": bool(win.pinned), "maximized": bool(win.isMaximized())},
        "drop": dict(app.drop_info),
        "nav": dict(app.nav),
        "efir": efir,
        "settings": settings_state(app),
        "release": release_state(app),
        "record": app.record.state() if getattr(app, "record", None) is not None else None,
        "sheet": dict(app.sheet_req),
        # «Новый урок»: что выбрано в прошлый раз, шаблоны «Начать с» для своего плана, видео зарядок
        "wizard": {"plan": s.lesson_plan, "cls": s.lesson_class, "minutes": s.lesson_minutes, "brk": s.lesson_break,
                   "style": s.lesson_style, "task": s.lesson_task, "explain": s.lesson_explain,
                   "keep": s.lesson_keep_code, "detail": s.lesson_detail},
        "structures": [{"key": k, "title": v[0], "stages": [{"title": x[0], "minutes": x[1], "kind": x[2] if len(x) > 2 else ""}
                                                          for x in v[1]]} for k, v in STRUCTURES.items()],
        "exercises": app.exercise_titles(None),
    }
