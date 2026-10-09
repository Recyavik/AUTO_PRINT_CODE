"""Хранилище: настройки (settings.json) и база образцов (templates.json).

Обе лежат в папке data/ рядом с приложением — их легко забэкапить или перенести.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


# AUTOPRINT_DATA — другая папка данных (для тестов, чтобы не трогать рабочую базу)
DATA_DIR = Path(os.environ.get("AUTOPRINT_DATA") or app_dir() / "data")
SETTINGS_FILE = DATA_DIR / "settings.json"
TEMPLATES_FILE = DATA_DIR / "templates.json"


def _atomic_write(path: Path, data: dict, backup: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if backup and path.exists():
        os.replace(path, path.with_suffix(path.suffix + ".bak"))
    os.replace(tmp, path)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------- настройки

PROFILE_PLAIN = "plain"
PROFILE_IDE = "ide"
PROFILES = {
    PROFILE_PLAIN: "Блокнот / простое поле",
    PROFILE_IDE: "IDE: VS Code, веб-IDE, Jupyter",
}


# звуки до v0.3.8 были синтезированы; теперь — записи настоящих клавиатур
LEGACY_SOUND_STYLES = {"soft": "office", "mechanical": "brown", "typewriter": "blue"}


@dataclass
class Settings:
    hotkey_toggle: str = "Ctrl+F9"     # старт / пауза / продолжить
    hotkey_restart: str = "Ctrl+F10"   # начать сначала
    hotkey_stop: str = "Ctrl+F11"      # остановить
    hotkey_next_block: str = "Ctrl+F12"        # следующий блок кода
    hotkey_prev_block: str = "Ctrl+Shift+F12"  # предыдущий блок кода
    hotkey_next_tab: str = ""                  # следующая вкладка-образец

    cpm: int = 320                     # скорость, символов в минуту
    jitter: int = 35                   # разброс задержки, %
    newline_pause_ms: int = 220        # доп. пауза после Enter
    punct_pause_ms: int = 50           # доп. пауза после , ; : ) и т.п.
    fast_indent: bool = True           # отступы печатаются быстро
    indent_with_tab: bool = False      # отступ — нажатиями Tab (по одному на tab_width пробелов)
    key_gap_ms: int = 30               # мин. интервал между нажатиями (надёжность ввода)
    tab_width: int = 4                 # табы в коде заменяются пробелами
    selection_whole_lines: bool = True # выделение в образце расширяется до целых строк
    strip_comments: bool = False       # не печатать комментарии из кода
    human_typing: bool = False         # имитация ручного ввода: живой ритм, обдумывание, опечатки
    typo_per_100_words: int = 3        # опечаток на 100 слов (исправляются Backspace)
    think_pause_s: float = 1.5         # пауза на обдумывание перед новой строкой (до …, с)

    profile: str = PROFILE_IDE
    esc_before_enter: bool = False     # закрывать подсказки Esc перед Enter (не для Jupyter!)

    sound_enabled: bool = True
    sound_volume: int = 35             # 0..100
    sound_style: str = "office"        # office | brown | red | cream | blue (см. sounds.STYLES)

    hotkey_start_delay_ms: int = 150   # пауза перед стартом по хоткею
    button_countdown_s: int = 3        # отсчёт при старте кнопкой в окне
    minimize_on_button_start: bool = True
    autopause_on_focus_change: bool = True
    guard_enabled: bool = True         # пауза при нажатии клавиши / клике во время печати
    auto_advance: bool = False         # по окончании выбрать следующий блок кода
    always_on_top: bool = False

    update_auto_check: bool = True     # проверять обновления на GitHub сам
    update_interval_h: int = 24        # как часто: 0 — при каждом запуске, 24 — раз в день, 168 — раз в неделю
    update_mode: str = "download"      # notify — сообщить | download — скачать и предложить | auto — ставить при выходе
    update_prerelease: bool = False    # предлагать бета-версии
    update_skip_version: str = ""      # «пропустить эту версию»
    update_last_check: float = 0.0

    open_tabs: list = field(default_factory=list)
    current_tab: str = ""
    window_geometry: str = ""
    splitter_state: str = ""

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        try:
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return s
        known = {f.name: f.type for f in fields(cls)}
        for k, v in raw.items():
            if k in known and type(v) is type(getattr(s, k)):
                setattr(s, k, v)
        s.sound_style = LEGACY_SOUND_STYLES.get(s.sound_style, s.sound_style)
        return s

    def save(self) -> None:
        _atomic_write(SETTINGS_FILE, asdict(self))


# ---------------------------------------------------------------- образцы

BLOCK_MARKDOWN = "markdown"
BLOCK_CODE = "code"

# Типы Markdown-блоков: ключ → (значок, название, цвет полоски)
ROLES = {
    "text": ("📝", "Текст", "#8b949e"),
    "task": ("📋", "Условие", "#3b82f6"),
    "explain": ("💡", "Пояснение", "#d29922"),
    "hint": ("🔎", "Подсказка", "#a855f7"),
}


@dataclass
class Block:
    type: str
    text: str = ""
    lang: str = "python"
    sel: list[int] = field(default_factory=list)  # [start, end] — выделение в блоке кода
    id: str = field(default_factory=new_id)
    role: str = "text"   # для Markdown-блока: text | task | explain | hint (см. ROLES)
    title: str = ""      # свой заголовок блока; пусто → название по типу
    zoom: int = 100      # масштаб содержимого блока, % (Ctrl/Shift + колёсико)
    print_as: str = "markdown"   # как печатать Markdown-блок: markdown | plain | comment (см. textprint)

    def display_title(self, code_number: int = 0) -> str:
        if self.title.strip():
            return self.title.strip()
        if self.type == BLOCK_CODE:
            return f"Код {code_number}" if code_number else "Код"
        return ROLES.get(self.role, ROLES["text"])[1]


@dataclass
class Template:
    """Образец (например, одно занятие) — список блоков: условия, пояснения и код вперемешку."""
    title: str
    blocks: list[Block] = field(default_factory=list)
    active_block: str = ""
    id: str = field(default_factory=new_id)
    updated: float = field(default_factory=time.time)

    def find_block(self, block_id: str) -> Block | None:
        return next((b for b in self.blocks if b.id == block_id), None)

    def code_blocks(self) -> list[Block]:
        return [b for b in self.blocks if b.type == BLOCK_CODE]

    def nav_blocks(self) -> list[Block]:
        """Переходы по хоткею «следующий блок»: блоки кода и активный текстовый блок, если печатается он —
        так из условия задачи попадаем в код под ним."""
        return [b for b in self.blocks if b.type == BLOCK_CODE or b.id == self.active_block]

    def code_number(self, block: Block) -> int:
        """Номер блока кода (1, 2, …) для заголовка «Код N»; 0 — для текстового блока."""
        ids = [b.id for b in self.code_blocks()]
        return ids.index(block.id) + 1 if block.id in ids else 0

    def lang_near(self, block: Block) -> str:
        """Язык ближайшего блока кода — сначала ниже (условие стоит над решением), затем выше."""
        i = self.blocks.index(block)
        for b in self.blocks[i + 1:] + self.blocks[:i][::-1]:
            if b.type == BLOCK_CODE:
                return b.lang
        return "python"


SAMPLE_TASKS = [
    ("## Задача 1. Сумма чисел\n\nНапишите функцию `total(nums)`, которая возвращает сумму "
     "чисел списка.\n\n- без встроенной `sum()`\n- пустой список → `0`",
     "def total(nums):\n    result = 0\n    for n in nums:\n        result += n\n    return result\n"
     "\n\nprint(total([1, 2, 3]))  # 6\nprint(\"Готово!\")"),
    ("## Задача 2. Чётные числа\n\nВыведите все чётные числа от 0 до 10.",
     "for i in range(0, 11, 2):\n    print(i)"),
]


def sample_template() -> Template:
    return Template(title="Пример занятия",
                    blocks=[b for md, code in SAMPLE_TASKS
                            for b in (Block(BLOCK_MARKDOWN, md, role="task"), Block(BLOCK_CODE, code))])


def _block_from(d: dict) -> Block:
    return Block(**{k: v for k, v in d.items() if k in Block.__dataclass_fields__})


def _flatten_tasks(tasks: list[dict]) -> list[Block]:
    """Старый формат (до v0.3): образец → задачи → блоки. Задачи сливаются в один список блоков.
    Если задач несколько, название задачи, которого нет в её тексте, становится заголовком перед её блоками."""
    blocks = []
    for t in tasks:
        tb = [_block_from(b) for b in t.get("blocks", [])]
        title = str(t.get("title", "")).strip()
        if len(tasks) > 1 and title and not any(b.type == BLOCK_MARKDOWN and title in b.text for b in tb):
            blocks.append(Block(BLOCK_MARKDOWN, f"## {title}"))
        blocks += tb
    return blocks


def _template_from(d: dict) -> Template:
    if "tasks" in d:
        blocks = _flatten_tasks(d["tasks"])
    else:
        blocks = [_block_from(b) for b in d.get("blocks", [])]
    return Template(title=d.get("title", "Без названия"), blocks=blocks, active_block=d.get("active_block", ""),
                    id=d.get("id") or new_id(), updated=d.get("updated", time.time()))


def _fresh_ids(t: Template) -> Template:
    for b in t.blocks:
        b.id = new_id()
    t.id, t.active_block = new_id(), ""
    return t


class TemplateStore:
    def __init__(self) -> None:
        self.templates: list[Template] = []
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(TEMPLATES_FILE.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.templates = [sample_template()]
            self.save()
            return
        except (OSError, ValueError) as e:
            raise RuntimeError(f"Не удалось прочитать {TEMPLATES_FILE}: {e}") from e
        if raw.get("version", 1) < 3:
            # одноразовая копия базы в старом формате (с задачами) — на случай отката
            old = TEMPLATES_FILE.with_suffix(".v2.json")
            if not old.exists():
                old.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        self.templates = [_template_from(t) for t in raw.get("templates", [])]

    def save(self) -> None:
        _atomic_write(TEMPLATES_FILE, {"version": 3, "templates": [asdict(t) for t in self.templates]},
                      backup=True)

    def get(self, tid: str) -> Template | None:
        return next((t for t in self.templates if t.id == tid), None)

    def add(self, title: str) -> Template:
        t = Template(title=title, blocks=[Block(BLOCK_MARKDOWN, "## Задача 1\n\n", role="task"),
                                          Block(BLOCK_CODE, "")])
        self.templates.append(t)
        return t

    def insert(self, t: Template) -> Template:
        self.templates.append(t)
        return t

    def duplicate(self, t: Template) -> Template:
        copy = _fresh_ids(_template_from(asdict(t)))
        copy.title = t.title + " (копия)"
        self.templates.insert(self.templates.index(t) + 1, copy)
        return copy

    def remove(self, t: Template) -> None:
        self.templates.remove(t)

    # --- обмен одним образцом (.json) ---
    @staticmethod
    def export_template(t: Template, path: str) -> None:
        Path(path).write_text(json.dumps({"autoprintcode_template": asdict(t)}, ensure_ascii=False, indent=2),
                              encoding="utf-8")

    @staticmethod
    def read_template_file(path: str) -> Template:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return _fresh_ids(_template_from(raw.get("autoprintcode_template", raw)))
