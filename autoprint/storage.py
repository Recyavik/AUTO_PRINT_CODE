"""Хранилище: настройки (settings.json) и база образцов (templates.json).

Обе лежат в папке data/ рядом с приложением — их легко забэкапить или перенести. Кроме установки
в Program Files (для всех пользователей): туда программа писать не может, и данные каждого пользователя —
в %APPDATA%\\AutoPrintCode (туда же при первом запуске переносятся данные прежней установки «только для
меня» из %LOCALAPPDATA%\\Programs\\AutoPrintCode\\data — см. migrate_legacy_data).
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


APP_FOLDER = "AutoPrintCode"


def _writable(d: Path) -> bool:
    probe = d / f".write-test-{os.getpid()}"
    try:
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def _in_program_files(d: Path) -> bool:
    roots = [os.environ.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")]
    p = os.path.normcase(str(d))
    return any(r and p.startswith(os.path.normcase(r.rstrip("\\")) + "\\") for r in roots)


def user_data_dir() -> Path:
    """Папка данных пользователя для установки в Program Files."""
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_FOLDER


def _data_dir() -> Path:
    # AUTOPRINT_DATA — другая папка данных (для тестов, чтобы не трогать рабочую базу)
    if os.environ.get("AUTOPRINT_DATA"):
        return Path(os.environ["AUTOPRINT_DATA"])
    base = app_dir()
    # собранная программа в Program Files (или в папке без права записи) — данные в профиле пользователя.
    # Даже если её запустили «от администратора»: иначе данные разошлись бы по двум местам
    if getattr(sys, "frozen", False) and (_in_program_files(base) or not _writable(base)):
        return user_data_dir()
    return base / "data"


DATA_DIR = _data_dir()
SETTINGS_FILE = DATA_DIR / "settings.json"
TEMPLATES_FILE = DATA_DIR / "templates.json"


BACKUP_EVERY_S = 600   # резервная копия обновляется не чаще раза в 10 минут — есть куда откатиться

log = logging.getLogger(__name__)


def legacy_data_dir() -> Path:
    """data/ прежней установки «только для меня» (до установки в Program Files)."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Programs" / APP_FOLDER / "data"


def migrate_legacy_data(target: Path = None, legacy: Path = None) -> bool:
    """Первый запуск установки в Program Files: занятия, настройки и звуки прежней установки
    «только для меня» переносятся в папку данных пользователя. True — перенесли."""
    target = target or DATA_DIR
    legacy = legacy or legacy_data_dir()
    if target == legacy or not legacy.is_dir():
        return False
    if (legacy.parent / f"{APP_FOLDER}.exe").exists():
        return False     # прежняя копия ещё установлена и работает со своими данными — не забираем их
    if (target / "settings.json").exists() or (target / "templates.json").exists():
        return False     # здесь уже свои данные — не трогаем
    if not ((legacy / "templates.json").exists() or (legacy / "settings.json").exists()):
        return False
    try:
        shutil.copytree(legacy, target, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("updates", ".lock", "*.tmp"))
    except OSError as e:
        log.warning("Данные прежней установки не перенесены: %s", e)
        return False
    try:   # перенесли — прежнюю копию убираем, чтобы не путаться (если удаление не выйдет, ничего страшного)
        shutil.rmtree(legacy)
        legacy.parent.rmdir()   # пустая папка прежней установки
    except OSError:
        pass
    return True


def _atomic_write(path: Path, data: dict, backup: bool = False) -> None:
    """Запись через временный файл: при сбое на диске остаётся либо старая, либо новая версия.
    backup — перед записью скопировать текущий файл в .bak (если копия старше BACKUP_EVERY_S)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))
        f.flush()
        os.fsync(f.fileno())     # иначе после сбоя питания файл может оказаться пустым
    if backup and path.exists():
        bak = path.with_suffix(path.suffix + ".bak")
        try:
            if not bak.exists() or time.time() - bak.stat().st_mtime > BACKUP_EVERY_S:
                shutil.copy2(path, bak)   # копия, а не переименование: основной файл не исчезает ни на миг
        except OSError as e:
            log.warning("Резервная копия %s не обновлена: %s", bak, e)
    os.replace(tmp, path)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------- картинки уроков (data/media)

MEDIA_FOLDER = "media"
_SCHEME = re.compile(r"[a-z][a-z0-9+.-]+:(?![\\/])", re.I)     # http:, javascript:… (но не диск «C:\»)


def import_media(src) -> str:
    """Копия картинки в data/media (имя — по содержимому: тот же файл — та же копия) → ссылка относительно
    папки данных. Так кладут картинки и пример урока, и импорт урока из .md."""
    import hashlib
    import shutil
    src = Path(src)
    data = src.read_bytes()
    out = DATA_DIR / "media" / f"img-{hashlib.sha1(data).hexdigest()[:16]}{src.suffix.lower() or '.png'}"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, out)
    return media_ref(out)


def media_ref(path) -> str:
    """Как записать картинку в блок: файл в папке данных — относительно неё («media/…»), чтобы урок пережил
    переезд данных (установка в Program Files, другой компьютер); иначе — путь как есть."""
    p = Path(path)
    try:
        return p.resolve().relative_to(DATA_DIR.resolve()).as_posix()
    except (ValueError, OSError):
        return str(p)


def media_path(ref: str) -> Path | None:
    """Файл картинки блока. Относительный путь — от папки данных; абсолютный, которого больше нет (урок из
    прежней папки данных), — ищется по имени в data/media. None — адрес в интернете или файла нет."""
    ref = (ref or "").strip()
    if not ref or _SCHEME.match(ref):
        return None
    p = Path(ref)
    cand = p if p.is_absolute() else DATA_DIR / p
    try:
        if cand.is_file():
            return cand
        alt = DATA_DIR / MEDIA_FOLDER / p.name
        return alt if p.name and alt.is_file() else None
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- настройки

PROFILE_PLAIN = "plain"
PROFILE_IDE = "ide"
PROFILE_TERMINAL = "terminal"
PROFILES = {
    PROFILE_PLAIN: "Блокнот / простое поле",
    PROFILE_IDE: "IDE: VS Code, веб-IDE, Jupyter",
    PROFILE_TERMINAL: "Терминал: Git Bash, PowerShell, cmd",
}
PROFILE_SHORT = {PROFILE_PLAIN: "Блокнот", PROFILE_IDE: "IDE", PROFILE_TERMINAL: "Терминал"}


# звуки до v0.3.8 были синтезированы; теперь — записи настоящих клавиатур
LEGACY_SOUND_STYLES = {"soft": "office", "mechanical": "brown", "typewriter": "blue"}


@dataclass
class Settings:
    hotkey_toggle: str = "Ctrl+F9"     # старт / пауза / продолжить
    hotkey_restart: str = "Ctrl+F10"   # начать сначала
    hotkey_stop: str = "Ctrl+F11"      # остановить
    hotkey_next_block: str = "Ctrl+F12"        # следующий блок кода
    hotkey_prev_block: str = "Ctrl+Shift+F12"  # предыдущий блок кода
    hotkey_next_tab: str = ""                  # следующий образец
    hotkey_step_back: str = ""                 # шаг назад без печати (режим «По шагам»)

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
    typo_per_100_words: int = 3        # устарело (до 0.5): опечатки на 100 слов — см. typos_per_100
    typos_per_100: float = 1.5         # опечаток на 100 символов текста (исправляются Backspace)
    think_pause_s: float = 1.5         # пауза на обдумывание перед новой строкой (до …, с)

    print_mode: str = "block"          # block — блок целиком | lines — по строкам | steps — по шагам
    show_prompter: bool = True         # суфлёр: что дальше и что сказать (комментарии шага)
    prompter_window: bool = False      # суфлёр в отдельном окне (открыт)
    prompter_mode: str = "auto"        # окно суфлёра: auto — печатает программа, self — набираю сам
    prompter_font: int = 20            # окно суфлёра: размер текста «что сказать»
    prompter_geometry: str = ""        # окно суфлёра: место и размер
    # «Эфир» (autoprint/efir, ui/efir_*.py): шаблоны вебинаров — в data/efir/webinars.json
    efir_port: int = 8791              # адрес вкладки эфира: http://127.0.0.1:<порт>/ (занят — следующие)
    efir_pinned: bool = True           # окно таймера поверх всех окон
    efir_timer_geometry: str = ""      # окно таймера: место и размер
    efir_window_geometry: str = ""     # окно «Эфир» (шаблоны)
    efir_editor_geometry: str = ""     # редактор шаблона вебинара
    lesson_preset: str = ""            # суфлёр урока: шаблон «Эфира» (оформление) — последний выбранный
    step_nav: str = "arrows"           # шаги: arrows — стрелками от курсора (код — продолжение файла)
                                       #       | home — от начала документа (Ctrl+Home)

    profile: str = PROFILE_IDE
    esc_before_enter: bool = False     # закрывать подсказки Esc перед Enter (не для Jupyter!)

    sound_enabled: bool = True
    sound_volume: int = 35             # 0..100
    sound_style: str = "office"        # office | brown | red | cream | blue (sounds.STYLES) | my_<…> — свой звук

    hotkey_start_delay_ms: int = 150   # пауза перед стартом по хоткею
    button_countdown_s: int = 3        # отсчёт при старте кнопкой в окне
    minimize_on_button_start: bool = True
    autopause_on_focus_change: bool = True
    guard_enabled: bool = True         # пауза при нажатии клавиши / клике во время печати
    auto_advance: bool = False         # по окончании выбрать следующий блок кода
    always_on_top: bool = False
    theme: str = "system"              # system — как в Windows | dark | light
    ui_scale: int = 100                # размер интерфейса, % (100 / 125 / 150 / 175) — после перезапуска

    close_to_tray: bool = True         # «закрыть» прячет окно в трей, выход — из меню (суфлёр не теряет связь)
    pin_tray_icon: bool = False        # значок всегда виден у часов (не в «скрытых значках»)
    autostart: bool = False            # запускать вместе с Windows (сразу в трей)
    samples_seen: list = field(default_factory=list)   # какие примеры уже добавлялись в базу
    migrations: list = field(default_factory=list)     # разовые переделки настроек при обновлении

    update_auto_check: bool = True     # проверять обновления на GitHub сам
    update_interval_h: int = 24        # как часто: 0 — при каждом запуске, 24 — раз в день, 168 — раз в неделю
    update_mode: str = "download"      # notify — сообщить | download — скачать и предложить | auto — ставить при выходе
    update_prerelease: bool = False    # предлагать бета-версии
    update_skip_version: str = ""      # «пропустить эту версию»
    update_last_check: float = 0.0

    # нейросеть (⚙ → Нейросеть; autoprint/ai.py): разбор кода в занятие. Ключи — зашифрованы Windows (DPAPI)
    ai_provider: str = ""              # "" — не подключена (остаётся «Скопировать промпт»)
    ai_urls: dict = field(default_factory=dict)     # адрес сервера по провайдеру
    ai_keys: dict = field(default_factory=dict)     # ключ по провайдеру: "dpapi:…" (base64)
    ai_models: dict = field(default_factory=dict)   # модель по провайдеру
    ai_backup_enabled: bool = False    # пробовать запасного, если основной не ответил
    ai_backup_provider: str = ""
    ai_timeout_s: int = 0              # 0 — по длине материала
    # последний выбор в «Импорт → С помощью нейросети»
    lesson_style: str = "steps"        # comments | steps | parts
    lesson_task: bool = True
    lesson_explain: bool = True
    lesson_keep_code: bool = True
    lesson_detail: str = "short"
    lesson_minutes: int = 90           # «Сценарий урока»: длительность урока
    lesson_break: int = 0              # «Сценарий урока»: перерыв, мин (0 — только если он есть в материале)

    open_tabs: list = field(default_factory=list)
    current_tab: str = ""
    window_geometry: str = ""
    splitter_state: str = ""

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        try:
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return s
        if not isinstance(raw, dict):
            return s
        known = {f.name for f in fields(cls)}
        for k, v in raw.items():
            if k not in known:
                continue
            default = getattr(s, k)
            if type(v) is int and type(default) is float:
                v = float(v)                 # «think_pause_s: 2» — тоже число
            if type(v) is type(default):
                setattr(s, k, v)
        s.sound_style = LEGACY_SOUND_STYLES.get(s.sound_style, s.sound_style)
        return s

    def save(self) -> None:
        _atomic_write(SETTINGS_FILE, asdict(self))


# ---------------------------------------------------------------- образцы

BLOCK_MARKDOWN = "markdown"
BLOCK_CODE = "code"
BLOCK_STAGE = "stage"     # этап урока: название, минуты, вид (обычный / перерыв / зарядка) — суфлёр урока
BLOCK_IMAGE = "image"     # картинка: слайд, скриншот (text — путь к копии в data/media или адрес http(s))

# Типы Markdown-блоков: ключ → (значок, название, цвет полоски). Первые четыре — подсказки ученику и
# преподавателю у кода; остальные — суфлёр урока (что сказать, спросить, сделать, показать)
ROLES = {
    "text": ("📝", "Текст", "#8b949e"),
    "task": ("📋", "Условие", "#3b82f6"),
    "explain": ("💡", "Пояснение", "#d29922"),
    "hint": ("🔎", "Подсказка", "#a855f7"),
    "say": ("🎙", "Говоришь", "#7fb4ff"),          # почти дословно
    "tell": ("💬", "Расскажи", "#6fd382"),         # своими словами
    "ask": ("❓", "Спроси", "#e9a72c"),            # вопрос; строки «→ …» — ожидаемый ответ
    "do": ("👉", "Делаешь", "#a6a6b2"),            # действие, вслух не читать
    "important": ("⚠", "Важно", "#f2686c"),
    "show": ("🖥", "Показываешь", "#b28cff"),      # что видят ученики
    "trap": ("🪤", "Ловушки", "#f2686c"),          # на чём ошибаются, что режет проверка
    "extra": ("⚡", "Для быстрых", "#b28cff"),     # дополнительное задание
}
STAGE_KINDS = {"": "Обычный", "break": "Перерыв", "exercise": "Зарядка"}


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
    steps: list[int] = field(default_factory=list)   # шаг каждой строки кода (режим «По шагам»); пусто — все 1
    print_as: str = "markdown"   # как печатать Markdown-блок: markdown | plain | comment (см. textprint)
    profile: str = ""            # окно для этого блока: plain | ide | terminal; пусто — как в настройках
    # этап урока (type == stage): title — название, text — пометка («теория · на платформе»)
    minutes: int = 0
    stage_kind: str = ""         # "" — обычный, break — перерыв, exercise — зарядка (см. STAGE_KINDS)
    part: str = ""               # раздел — группа этапов в плане урока («Тёмная тема»)

    def display_title(self, code_number: int = 0) -> str:
        if self.title.strip():
            return self.title.strip()
        if self.type == BLOCK_CODE:
            return f"Код {code_number}" if code_number else "Код"
        if self.type == BLOCK_STAGE:
            return "Этап"
        if self.type == BLOCK_IMAGE:
            return "Картинка"
        return ROLES.get(self.role, ROLES["text"])[1]


@dataclass
class Template:
    """Образец (например, одно занятие) — список блоков: условия, пояснения и код вперемешку."""
    title: str
    blocks: list[Block] = field(default_factory=list)
    active_block: str = ""
    id: str = field(default_factory=new_id)
    updated: float = field(default_factory=time.time)
    start: str = ""      # плановое начало урока «ЧЧ:ММ» (суфлёр урока); пусто — с момента «Начать урок»
    preset: str = ""     # шаблон «Эфира», откуда брать фон, зарядки и перерыв; пусто — последний выбранный

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


def sample_template() -> Template:
    """Образец для новой базы — экскурсия по всем возможностям (autoprint/samples.py)."""
    from .samples import tour_template
    return tour_template()


# Пример печати по шагам: шаг 3 возвращается наверх (import), шаг 4 — вставка в середину.
# Комментарии — текст для суфлёра: с «Без комментариев» они не печатаются, а читаются вслух.
STEPS_SAMPLE_ID = "steps_v1"
STEPS_SAMPLE_INTRO = """## Пошаговый урок: оценки учеников

Так записывают урок, где код растёт частями и иногда приходится вернуться наверх.

1. На пульте: режим **«По шагам»** и **«Без комментариев»**.
2. Откройте пустой файл в VS Code (или новую ячейку Jupyter) и поставьте туда курсор.
3. Над лентой — **суфлёр**: что сказать перед шагом (это комментарии шага — они не печатаются).
   Сказали — нажали **Ctrl+F9**: программа напечатает шаг сама.
4. Шаг 3 вернётся наверх и допишет `import`, шаг 4 вставит строку в середину.

Шаг строки — цветной номер слева от номера строки: правый щелчок по строке, **Alt+1…9**
или кнопка «Шаги» в шапке блока (там же — разметка по комментариям одним щелчком)."""
STEPS_SAMPLE_CODE = '''import statistics

# Оценки учеников
grades = [5, 4, 3, 5, 4]
grades.append(5)  # пришла ещё одна оценка — вернулись наверх и дописали
print("Оценки:", grades)

# Средний балл
average = sum(grades) / len(grades)
print("Средний:", round(average, 2))

# Медиана — возьмём готовую функцию из модуля statistics
median = statistics.median(grades)
print("Медиана:", median)'''
STEPS_SAMPLE_STEPS = [3, 3, 1, 1, 4, 1, 2, 2, 2, 2, 3, 3, 3, 3]


def steps_sample_template() -> Template:
    return Template(title="Пример: пошаговый урок",
                    blocks=[Block(BLOCK_MARKDOWN, STEPS_SAMPLE_INTRO, role="explain"),
                            Block(BLOCK_CODE, STEPS_SAMPLE_CODE, steps=list(STEPS_SAMPLE_STEPS))])


def _block_from(d: dict) -> Block:
    b = Block(**{k: v for k, v in d.items() if k in Block.__dataclass_fields__})
    # образец могли поправить руками или прислать из другой программы: переводы строк Windows (редактор
    # их убирает, а печать по строкам и по шагам набрала бы «\r») и шаги не числами
    b.text = str(b.text).replace("\r\n", "\n").replace("\r", "\n")
    try:
        b.steps = [max(1, int(s)) for s in b.steps] if isinstance(b.steps, list) else []
    except (TypeError, ValueError):
        b.steps = []
    try:
        b.minutes = max(0, min(24 * 60, int(b.minutes)))
    except (TypeError, ValueError):
        b.minutes = 0
    if b.stage_kind not in STAGE_KINDS:
        b.stage_kind = ""
    return b


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
                    id=d.get("id") or new_id(), updated=d.get("updated", time.time()),
                    start=str(d.get("start") or ""), preset=str(d.get("preset") or ""))


def _fresh_ids(t: Template) -> Template:
    for b in t.blocks:
        b.id = new_id()
    t.id, t.active_block = new_id(), ""
    return t


def _read_templates(path: Path) -> tuple[dict, list[Template]]:
    """→ (исходный JSON, образцы). ValueError — файл повреждён или не того формата."""
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    try:
        return raw, [_template_from(t) for t in raw.get("templates", [])]
    except (AttributeError, TypeError, KeyError) as e:
        raise ValueError(f"неверная структура: {e}") from e


class TemplateStore:
    def __init__(self) -> None:
        self.templates: list[Template] = []
        self.created_fresh = False   # базы не было — создана с образцом-экскурсией (второй раз его не добавлять)
        self.warning = ""     # что пошло не так при загрузке (показать пользователю)
        self.load()

    def load(self) -> None:
        bak = TEMPLATES_FILE.with_suffix(TEMPLATES_FILE.suffix + ".bak")
        try:
            raw, self.templates = _read_templates(TEMPLATES_FILE)
        except FileNotFoundError:
            if not bak.exists():
                self.templates = [sample_template()]
                self.created_fresh = True
                self.save()
                return
            raw, self.templates = self._recover(bak, f"{TEMPLATES_FILE.name} не найден")
        except (OSError, ValueError) as e:
            if not bak.exists():
                raise RuntimeError(f"Не удалось прочитать {TEMPLATES_FILE}: {e}") from e
            raw, self.templates = self._recover(bak, f"{TEMPLATES_FILE.name} повреждён ({e})")
        if raw.get("version", 1) < 3:
            # одноразовая копия базы в старом формате (с задачами) — на случай отката
            old = TEMPLATES_FILE.with_suffix(".v2.json")
            if not old.exists():
                old.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    def _recover(self, bak: Path, why: str) -> tuple[dict, list[Template]]:
        """Основной файл не читается — берём резервную копию, испорченный файл откладываем."""
        try:
            raw, templates = _read_templates(bak)
        except (OSError, ValueError) as e:
            raise RuntimeError(f"{why}, резервная копия {bak.name} тоже не читается: {e}") from e
        if TEMPLATES_FILE.exists():
            stamp, n = time.strftime("%Y%m%d-%H%M%S"), 1
            broken = TEMPLATES_FILE.with_name(f"templates.broken-{stamp}.json")
            while broken.exists():
                n += 1
                broken = TEMPLATES_FILE.with_name(f"templates.broken-{stamp}-{n}.json")
            os.replace(TEMPLATES_FILE, broken)
            why += f"; он сохранён как {broken.name}"
        shutil.copy2(bak, TEMPLATES_FILE)
        self.warning = f"{why}. Образцы восстановлены из резервной копии {bak.name}."
        log.warning(self.warning)
        return raw, templates

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
        raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return _fresh_ids(_template_from(raw.get("autoprintcode_template", raw)))
