"""Поля «Настроек», которые меняет страница окна: тип и пределы — как в прежнем окне настроек.

Страница шлёт {key, value}; значение проверяется здесь (числа приводятся к пределам, выбор — из списка). Ключи
нейросети сюда не входят: они шифруются отдельно и в страницу не возвращаются (app_cmd.call_ai_set).
"""
from __future__ import annotations

from .storage import PROFILES

HOTKEY_TITLES = [
    ("hotkey_toggle", "Старт / пауза / продолжить"),
    ("hotkey_restart", "Начать сначала"),
    ("hotkey_stop", "Остановить"),
    ("hotkey_next_block", "Следующий блок кода"),
    ("hotkey_prev_block", "Предыдущий блок кода"),
    ("hotkey_next_tab", "Следующий урок"),
    ("hotkey_step_back", "Шаг назад без печати (режим «По шагам»)"),
]

B = ("bool",)
FIELDS: dict[str, tuple] = {
    # вид
    "theme": ("choice", ("system", "dark", "light")),
    "page_zoom": ("int", 80, 200), "page_zoom_auto": B,
    "page_plan": ("choice", ("side", "top", "hidden")),
    "page_width": ("width",),               # вариант или своя ширина в пикселях (ручки по краям текста урока)
    "page_past": ("choice", ("dim", "collapse")),
    "page_stage_timer": B,
    # урок
    "start_screen": B, "start_compact": B, "copy_media": B, "exercise_pick": ("choice", ("next", "random", "ask")),
    "exercise_start": ("choice", ("click", "auto")),
    # пульт (1.3)
    "deck_on": B, "deck_prepare": ("urls",), "deck_prepare_screen": B, "deck_style": ("choice", ("tiles", "outline")),
    # набор кода
    "print_mode": ("choice", ("block", "lines", "steps")),
    "step_nav": ("choice", ("arrows", "home")),
    "cpm": ("int", 30, 3000), "jitter": ("int", 0, 90),
    "newline_pause_ms": ("int", 0, 3000), "punct_pause_ms": ("int", 0, 1000),
    "fast_indent": B, "indent_with_tab": B, "tab_width": ("int", 1, 8), "selection_whole_lines": B,
    "strip_comments": B, "profile": ("choice", tuple(PROFILES)), "esc_before_enter": B, "key_gap_ms": ("int", 5, 200),
    "human_typing": B, "typos_per_100": ("float", 0, 10), "think_pause_s": ("float", 0, 10), "minimize_on_type": B,
    # звук
    "sound_enabled": B, "sound_style": ("str",), "sound_volume": ("int", 0, 100),
    # поведение
    "hotkey_start_delay_ms": ("int", 0, 3000), "button_countdown_s": ("int", 0, 10),
    "autopause_on_focus_change": B, "guard_enabled": B, "close_to_tray": B, "pin_tray_icon": B, "autostart": B,
    # нейросеть (без ключей)
    "ai_backup_enabled": B, "ai_timeout_s": ("int", 0, 3600),
    # обновления
    "update_auto_check": B, "update_interval_h": ("choice", (0, 24, 168)),
    "update_mode": ("choice", ("notify", "download", "auto")), "update_prerelease": B, "update_skip_version": ("str",),
}


WIDTHS = ("narrow", "normal", "wide", "full")
WIDTH_PX = (480, 4000)


def clean_width(value) -> str:
    """Ширина текста урока: вариант из WIDTHS или число пикселей в пределах WIDTH_PX (строкой)."""
    v = str(value if value is not None else "").strip()
    if v in WIDTHS:
        return v
    if v.isdigit() and WIDTH_PX[0] <= int(v) <= WIDTH_PX[1]:
        return str(int(v))
    raise ValueError("нет такой ширины")


URLS_MAX = 20


def clean_urls(value) -> list[str]:
    """Список адресов (строкой по адресу или списком): только http(s), без повторов, не больше URLS_MAX.
    «example.com» — https://example.com. Не адрес — ValueError с этой строкой."""
    import re
    rows = value if isinstance(value, list) else str(value or "").splitlines()
    out: list[str] = []
    for raw in rows:
        u = str(raw or "").strip()
        if not u:
            continue
        scheme = re.match(r"([a-z][a-z0-9+.-]*):(?!\d)", u, re.I)     # «javascript:…», «file:…» — не сайт
        if scheme and scheme.group(1).lower() not in ("http", "https"):
            raise ValueError(f"это не адрес сайта: {u[:60]}")
        if not scheme:
            u = "https://" + u
        if not re.fullmatch(r"https?://[^\s<>\"']+", u, re.I) or len(u) > 2000:
            raise ValueError(f"это не адрес сайта: {str(raw).strip()[:60]}")
        if u not in out:
            out.append(u)
    if len(out) > URLS_MAX:
        raise ValueError(f"не больше {URLS_MAX} вкладок")
    return out


def clean(key: str, value):
    """Значение поля key после проверки. ValueError — такого поля нет или значение не подходит."""
    spec = FIELDS.get(key)
    if spec is None:
        raise ValueError(f"нет такой настройки: {key}")
    kind = spec[0]
    if kind == "width":
        return clean_width(value)
    if kind == "bool":
        return bool(value)
    if kind in ("int", "float"):
        try:
            v = float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            raise ValueError("нужно число") from None
        v = max(spec[1], min(spec[2], v))
        return int(round(v)) if kind == "int" else round(v * 2) / 2        # дробные — шагом 0,5
    if kind == "urls":
        return clean_urls(value)
    if kind == "choice":
        for c in spec[1]:
            if str(c) == str(value):
                return c
        raise ValueError("нет такого варианта")
    return str(value or "").strip()[:200]
