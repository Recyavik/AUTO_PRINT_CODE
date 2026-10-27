"""Хранилище: шаблоны вебинаров (plans.json) и настройки (settings.json) — в папке приложения.

Папка webinar_timer самодостаточна — её можно скопировать целиком:
    data/   шаблоны, настройки, журнал
    media/  фон перерыва, видео гимнастики, шрифт Furore
    templates/  шаблоны в JSON (экспорт) — их получает новая установка, пока своих шаблонов нет
Пути к файлам из media/ хранятся относительно папки приложения («media/Фон.jpg»).
Запись — через временный файл с fsync и резервной копией plans.json.bak.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .model import Plan, default_plan, plan_from, plan_to

# папка программы: рядом с «Таймер вебинара.exe» (собранная версия) или webinar_timer/ (из исходников)
APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
MEDIA_DIR = APP_DIR / "media"
TEMPLATES_DIR = APP_DIR / "templates"                  # шаблоны для коллег: с них начинается новая установка
# WEBINAR_DATA — другая папка (для тестов, чтобы не трогать рабочие шаблоны)
DATA_DIR = Path(os.environ.get("WEBINAR_DATA") or APP_DIR / "data")
PLANS_FILE = DATA_DIR / "plans.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

log = logging.getLogger(__name__)


def resolve(path: str) -> str:
    """Путь из настроек или шаблона → полный (относительные — от папки приложения). Пусто — пусто."""
    if not path:
        return ""
    p = Path(path)
    return str(p if p.is_absolute() else APP_DIR / p)


def portable(path: str) -> str:
    """Файл внутри папки приложения — относительным путём («media/Фон.jpg»): папку можно перенести."""
    if not path:
        return ""
    try:
        return Path(path).resolve().relative_to(APP_DIR).as_posix()
    except ValueError:
        return path


def existing(path: str) -> str:
    """Полный путь, если файл есть; иначе пусто (нет файла — встроенный фон, видео не показывается)."""
    full = resolve(path)
    return full if full and Path(full).is_file() else ""


def _quarantine(path: Path) -> str:
    """Нечитаемый файл — в сторону (plans.json.broken-ДАТА): иначе следующее сохранение затёрло бы им копию .bak."""
    keep = path.with_name(f"{path.name}.broken-{time.strftime('%Y%m%d-%H%M%S')}")
    try:
        path.replace(keep)
    except OSError as e:
        log.warning("Не удалось отложить %s: %s", path, e)
        return ""
    return f"; он сохранён как {keep.name}"


def _atomic_write(path: Path, data: dict, backup: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))
        f.flush()
        os.fsync(f.fileno())
    if backup and path.exists():
        try:
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        except OSError as e:
            log.warning("Резервная копия %s не обновлена: %s", path, e)
    os.replace(tmp, path)


@dataclass
class Settings:
    demo_screen: str = ""          # монитор демонстрации (имя QScreen); пусто — основной
    control_screen: str = ""       # монитор управления — сюда уведомления; пусто — не основной, если есть
    break_image: str = "media/Фон.jpg"                 # фон заставки перерыва; нет файла — встроенный фон
    eyes_media: str = "media/Гимнастика для глаз.mp4"  # видео/картинка «Зарядки для глаз» (если у блока нет своего)
    heads_up_min: int = 1          # предупреждать за N минут до активности (0 — не предупреждать)
    lesson_min: int = 45           # продолжительность урока — предел части до перерыва и после (0 — без предела)
    manual_break_min: int = 10     # «Перерыв сейчас» — длительность по умолчанию
    note_pos: str = ""             # куда перетащили напоминания: «x,y» от угла монитора управления; пусто — справа вверху
    player_pos: str = ""           # куда перетащили пульты (видео и перерыва): «x,y» от угла монитора управления;
                                   # пусто — внизу по центру
    sound: bool = True             # звук напоминания (мягкий колокольчик, webinar/chime.py)
    sound_volume: int = 40         # его громкость, 0–100
    windows_toast: bool = False    # дублировать всплывающим уведомлением Windows (оно на основном мониторе!)
    auto_update_check: bool = True # сам проверять обновления и сообщать о новой версии (ставит пользователь)
    theme: str = "dark"            # тема окна таймера: dark | light (экран демонстрации от неё не зависит)
    current_plan: str = ""
    live: str = ""                 # идущий эфир «id шаблона|ЧЧ:ММ старта|ГГГГ-ММ-ДД» — продолжить после перезапуска
    window_geometry: str = ""

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        try:
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return s
        if not isinstance(raw, dict):
            return s
        for f in fields(cls):
            v = raw.get(f.name)
            if v is not None and type(v) is type(getattr(s, f.name)):
                setattr(s, f.name, v)
        return s

    def save(self) -> None:
        try:
            _atomic_write(SETTINGS_FILE, asdict(self))
        except OSError as e:          # настройки (место окна, мониторы) — не повод прерывать эфир
            log.error("Настройки не сохранены: %s", e)


def starter_plans() -> list[Plan]:
    """Шаблоны из папки templates/ (по алфавиту) — для первого запуска на новом компьютере."""
    plans: list[Plan] = []
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        try:
            p = plan_from(json.loads(path.read_text(encoding="utf-8-sig")), path.stem)
        except (OSError, ValueError, AttributeError, TypeError) as e:
            log.warning("Шаблон %s не читается: %s", path.name, e)
            continue
        if all(p.id != q.id for q in plans):
            plans.append(p)
    return plans


class PlanStore:
    def __init__(self) -> None:
        self.plans: list[Plan] = []
        self.warning = ""
        self.load()

    def load(self) -> None:
        problem = ""
        for path in (PLANS_FILE, PLANS_FILE.with_suffix(".json.bak")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8-sig"))
                self.plans = [plan_from(p) for p in raw.get("plans", [])]
            except FileNotFoundError:
                problem = problem or f"{path.name} не найден"
                continue
            except (OSError, ValueError, AttributeError, TypeError) as e:
                problem = problem or f"{path.name} не читается ({e}){_quarantine(path)}"
                log.warning(problem)
                continue
            if not self.plans:
                problem = problem or f"в {path.name} нет шаблонов"
                continue
            if path != PLANS_FILE:
                self.warning = f"{problem}. Шаблоны восстановлены из резервной копии."
            return
        if problem.startswith(PLANS_FILE.name + " не найден") or problem.startswith(f"в {PLANS_FILE.name}"):
            problem = ""             # первый запуск — это не ошибка
        self.warning = problem
        self.plans = starter_plans() or [default_plan()]
        if not self.warning:
            self.save()

    def save(self) -> None:
        _atomic_write(PLANS_FILE, {"version": 1, "saved": time.time(), "plans": [plan_to(p) for p in self.plans]},
                      backup=True)

    def get(self, pid: str) -> Plan | None:
        return next((p for p in self.plans if p.id == pid), None)
