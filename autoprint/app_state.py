"""Состояние окна программы (канал app): что показывает страница кроме самого урока.

Урок, открытый на экране урока, идёт своим каналом lesson (scenario.lesson_state). Здесь — список уроков и
планов, идёт ли урок или эфир, набор кода, обновление, нейросеть, уведомления, окно, переход на экран.
Без ключей нейросети и личных путей сверх нужного странице.
"""
from __future__ import annotations

from . import __version__, scenario
from .storage import BLOCK_STAGE, KIND_PLAN

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
                "end_ms": int(ag.end.timestamp() * 1000) if ag.end else 0}
    win = app.window
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
        "efir": {},
        "settings": {},
    }
