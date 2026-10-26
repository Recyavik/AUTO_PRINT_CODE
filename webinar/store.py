"""Хранилище: шаблоны вебинаров (plans.json) и настройки (settings.json) в data/webinar/.

Запись — как у AutoPrintCode: через временный файл с fsync и резервной копией plans.json.bak.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from autoprint.storage import DATA_DIR as APP_DATA_DIR

from .model import Plan, default_plan, plan_from, plan_to

# WEBINAR_DATA — другая папка (для тестов, чтобы не трогать рабочие шаблоны)
DATA_DIR = Path(os.environ.get("WEBINAR_DATA") or APP_DATA_DIR / "webinar")
PLANS_FILE = DATA_DIR / "plans.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

log = logging.getLogger(__name__)


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
    break_image: str = ""          # фон заставки перерыва; пусто — встроенный фон
    eyes_media: str = ""           # видео/картинка для «Зарядки для глаз», если у блока нет своего файла
    heads_up_min: int = 1          # предупреждать за N минут до активности (0 — не предупреждать)
    note_pos: str = ""             # куда перетащили напоминания: «x,y» от угла монитора управления; пусто — справа вверху
    sound: bool = True             # звук уведомления
    windows_toast: bool = False    # дублировать всплывающим уведомлением Windows (оно на основном мониторе!)
    current_plan: str = ""
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
        _atomic_write(SETTINGS_FILE, asdict(self))


class PlanStore:
    def __init__(self) -> None:
        self.plans: list[Plan] = []
        self.warning = ""
        self.load()

    def load(self) -> None:
        for path in (PLANS_FILE, PLANS_FILE.with_suffix(".json.bak")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8-sig"))
                self.plans = [plan_from(p) for p in raw.get("plans", [])]
            except FileNotFoundError:
                continue
            except (OSError, ValueError, AttributeError, TypeError) as e:
                self.warning = f"{path.name} не читается ({e})"
                log.warning(self.warning)
                continue
            if path != PLANS_FILE:
                self.warning = (self.warning or f"{PLANS_FILE.name} не найден") + \
                    ". Шаблоны восстановлены из резервной копии."
            if self.plans:
                return
        self.plans = [default_plan()]
        if not self.warning:
            self.save()

    def save(self) -> None:
        _atomic_write(PLANS_FILE, {"version": 1, "saved": time.time(), "plans": [plan_to(p) for p in self.plans]},
                      backup=True)

    def get(self, pid: str) -> Plan | None:
        return next((p for p in self.plans if p.id == pid), None)
