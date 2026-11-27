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
    # файл на миг держит антивирус или индексатор Windows («Отказано в доступе») — подождать и повторить
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == REPLACE_TRIES - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


REPLACE_TRIES = 6           # подмена файла: до 6 попыток, всего около 0,75 с


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
    if not ref or _SCHEME.match(ref) or ref.startswith(("\\\\", "//")):
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
    typos_per_100: float = 1.5         # опечаток на 100 символов текста (исправляются Backspace)
    think_pause_s: float = 1.5         # пауза на обдумывание перед новой строкой (до …, с)

    print_mode: str = "block"          # block — блок целиком | lines — по строкам | steps — по шагам
    # «Эфир» (autoprint/efir, ui/efir_*.py): шаблоны вебинаров — в data/efir/webinars.json
    efir_port: int = 8791              # адрес вкладки эфира: http://127.0.0.1:<порт>/ (занят — следующие)
    efir_pinned: bool = True           # окно таймера поверх всех окон
    efir_timer_geometry: str = ""      # окно таймера: место и размер
    efir_window_geometry: str = ""     # окно «Эфир» (шаблоны)
    efir_editor_geometry: str = ""     # редактор шаблона вебинара
    lesson_preset: str = ""            # до 0.10: шаблон «Эфира» (оформление) — последний выбранный
    lesson_look: str = ""              # оформление эфира урока — последнее выбранное (efir/looks.json)
    page_open: bool = False            # экран урока был открыт при выходе — открыть снова при запуске
    page_lesson: str = ""              # какой урок был на экране урока
    # «Мои настройки» экрана урока
    page_zoom: int = 100               # размер текста страницы, % (80…200)
    page_zoom_auto: bool = False       # 1.1.1: масштаб под размер окна (шире — крупнее, 90…150 %)
    page_plan: str = "side"            # план в «Уроке»: side — сбоку, top — строкой сверху, hidden — скрыт
    page_past: str = "dim"             # пройденные этапы: dim — приглушать, collapse — сворачивать
    page_stage_timer: bool = True      # «осталось» на текущем этапе
    page_width: str = "normal"         # ширина текста урока: narrow · normal · wide · full (во всё окно)
    exercise_pick: str = "next"        # какое видео зарядки включает щелчок: next — по очереди, random — случайное,
                                       # ask — меню видео (до 1.2.1 по умолчанию ask, migrations exercise_v121)
    exercise_last: str = ""            # название прошлого показанного видео зарядки — «по очереди» продолжает с него
    exercise_start: str = "click"      # 1.2.4: click — видео встаёт на первый кадр и ждёт щелчка по вкладке учеников
                                       # (звук всегда есть; щелчок по идущей — пауза), auto — начинается сразу
    deck_on: bool = False              # 1.3: пульт — команды /api/<команда>?key=… (Macro Deck, Stream Deck) и файлы
                                       # deck\*.txt со временем и этапами для кнопок
    deck_key: str = ""                 # 1.3: ключ пульта (появляется при включении; «Новый ключ» — старые ссылки не работают)
    deck_prepare: list = field(default_factory=list)   # 1.3: «Подготовка» — какие вкладки открыть (адреса http(s))
    deck_prepare_screen: bool = True   # 1.3: «Подготовка» открывает и вкладку экрана учеников
    md_token: str = ""                 # 1.3: ключ Macro Deck (Настройки → AI clients) — зашифрован Windows, «dpapi:…»
    md_profile: str = ""               # 1.3: профиль «AutoPrintCode», который программа собрала в Macro Deck
    md_folder: str = ""                # 1.3: его главная страница (там кнопки программы)
    md_widgets: dict = field(default_factory=dict)   # 1.3: кнопки программы в Macro Deck: ключ → id
    md_layout: int = 0                 # 1.3: устройство страницы, с которым она собрана (другое — пересобрать само)
    deck_style: str = "glass"          # 1.3: вид кнопок на телефоне — glass («Стекло») | tiles («Плитки») | outline («Контур»)
    start_timer: bool = False          # до 1.0: «Начать урок» открывал мини-таймер (migrations v1 → start_compact)
    start_compact: bool = False        # 1.0: «Начать урок» — окно в маленький режим поверх всех
    start_screen: bool = False         # «Начать урок» открывает экран учеников (вкладку)
    step_nav: str = "arrows"           # шаги: arrows — стрелками от курсора (код — продолжение файла)
                                       #       | home — от начала документа (Ctrl+Home)

    profile: str = PROFILE_IDE
    esc_before_enter: bool = False     # закрывать подсказки Esc перед Enter (не для Jupyter!)

    sound_enabled: bool = True
    sound_volume: int = 35             # 0..100
    sound_style: str = "office"        # office | brown | red | cream | blue (sounds.STYLES) | my_<…> — свой звук

    hotkey_start_delay_ms: int = 150   # пауза перед стартом по хоткею
    button_countdown_s: int = 3        # отсчёт при старте кнопкой в окне
    minimize_on_type: bool = False     # окно сворачивается на время набора и разворачивается после
    copy_media: bool = True            # файлы, выбранные в оформлении эфира (фон, видео, шрифт), — копией в data/media
    autopause_on_focus_change: bool = True
    guard_enabled: bool = True         # пауза при нажатии клавиши / клике во время печати
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
    lesson_plan: str = ""              # «Урок через нейросеть»: последний выбранный план ("" — без плана)
    lesson_class: str = ""             # «Урок через нейросеть»: класс / возраст учеников

    current_tab: str = ""
    window_geometry: str = ""
    compact: bool = False              # 1.0: окно было в маленьком режиме
    compact_geometry: str = ""         # 1.0: геометрия маленького режима (base64)
    last_view: str = ""                # 1.0: экран окна при выходе (#/lessons, #/lesson/<id>, #/settings/…)

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

# Роли заметок: ключ → (значок, название, цвет полоски). Заметки — для преподавателя: печатается только код
ROLES = {
    "text": ("📝", "Заметка", "#8b949e"),
    "task": ("📋", "Задание", "#3b82f6"),
    "explain": ("💡", "Пояснение", "#d29922"),
    "hint": ("🛟", "Если застрял", "#a855f7"),     # наводящий вопрос, подсказка тем, кто не справляется
    "say": ("🎙", "Говоришь", "#7fb4ff"),          # почти дословно
    "tell": ("💬", "Расскажи", "#6fd382"),         # своими словами
    "ask": ("❓", "Спроси", "#e9a72c"),            # вопрос; строки «→ …» — ожидаемый ответ
    "do": ("👉", "Делаешь", "#a6a6b2"),            # действие, вслух не читать
    "important": ("⚠", "Важно", "#f2686c"),
    "show": ("🖥", "Показываешь", "#b28cff"),      # что видят ученики
    "trap": ("🪤", "Типичные ошибки", "#f2686c"),  # на чём ошибаются, что режет проверка
    "extra": ("⚡", "Для быстрых", "#b28cff"),     # дополнительное задание
    "term": ("📖", "Термин", "#5fc9b8"),           # обязательный термин: первая строка — термин, дальше определение
    "output": ("✅", "Результат кода", "#6fd382"),  # что выведет код после запуска
    "homework": ("🏠", "Домашнее задание", "#e9a72c"),  # в тетрадку учеников; «Скопировать для чата»
    "goal": ("🎯", "Цель урока", "#7fb4ff"),      # чему научатся; в начале урока
}
# палитра «+» и меню роли — по группам; «Ещё» — старые роли (показываются, новых с ними не создаём)
ROLE_GROUPS = [("Урок", ["goal"]), ("Речь", ["say", "tell", "term", "ask"]), ("Ученикам", ["task", "hint", "extra", "homework"]),
               ("Действия", ["do", "show"]), ("Для себя", ["important", "trap", "text"]), ("Материалы", ["output"])]
ROLE_ORDER = [k for _g, keys in ROLE_GROUPS for k in keys]
ROLE_MORE = ["explain"]
# как читать — рядом с названием на плашке
ROLE_HOW = {"say": "дословно", "term": "дословно", "tell": "своими словами", "ask": "ответы учеников"}
# одна строка в «Обозначениях»: как обращаться с заметкой этой роли
ROLE_HINTS = {
    "say": "обязательно, дословно", "term": "обязательный термин — дословно",
    "tell": "своими словами, можно дополнять", "ask": "вопрос и ответы учеников", "do": "вслух не читать",
    "show": "что видят ученики", "output": "что выведет код", "important": "нельзя пропустить",
    "trap": "на чём ошибаются", "extra": "тем, кто закончил раньше", "task": "что делают ученики",
    "text": "заметка", "explain": "пояснение", "hint": "наводящий вопрос тем, кто застрял",
    "homework": "что сделать дома — попадёт в тетрадку учеников", "goal": "чему научатся на уроке",
}
STAGE_KINDS = {"": "Обычный", "break": "Перерыв", "exercise": "Зарядка"}
KIND_PLAN = "plan"         # Template.kind: план урока
# «Новый урок» по шаблону структуры: ключ → (название, [(этап, минуты[, вид])])
STRUCTURES = {
    "empty": ("Пустой урок", []),
    "school45": ("Школа, 45 мин", [("Оргмомент", 2), ("Цель и мотивация", 3), ("Актуализация знаний", 5),
                                    ("Новый материал", 15), ("Закрепление", 12), ("Домашнее задание", 3), ("Рефлексия", 5)]),
    "online90": ("Онлайн-занятие, 90 мин", [("Приветствие", 5), ("Разминка", 5), ("Теория", 15), ("Практика", 20),
                                             ("Перерыв", 10, "break"), ("Практика", 20), ("Итоги и рефлексия", 10),
                                             ("Домашнее задание", 5)]),
    "pair90": ("Пара, 2×45", [("Первая половина", 45), ("Перерыв", 10, "break"), ("Вторая половина", 45)]),
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
    steps: list[int] = field(default_factory=list)   # шаг каждой строки кода (режим «По шагам»); пусто — все 1
    print_as: str = "markdown"   # как печатать Markdown-блок: markdown | plain | comment (см. textprint)
    profile: str = ""            # окно для этого блока: plain | ide | terminal; пусто — как в настройках
    # этап урока (type == stage): title — название, text — пометка («теория · на платформе»)
    minutes: int = 0
    stage_kind: str = ""         # "" — обычный, break — перерыв, exercise — зарядка (см. STAGE_KINDS)
    part: str = ""               # раздел — группа этапов в плане урока («Тёмная тема»)
    slide: int = 0               # картинка — слайд презентации с этим номером («На экран», ◀ ▶); 0 — обычная
    link: str = ""               # этап урока по плану: id этапа плана, который он повторяет (plans.py);
                                 # заметка-разделитель «Из этапа «X»…» — id убранного этапа плана
    exercise: str = ""           # этап-зарядка: название видео зарядки из оформления ("" — первое)

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
    preset: str = ""     # до 0.10: шаблон «Эфира» с оформлением (остаётся для отката на 0.9)
    look: str = ""       # оформление экрана эфира (efir/looks.json); пусто — последнее выбранное
    kind: str = ""       # "" — урок, "plan" — план урока: этапы и минуты для уроков по нему (plans.py)
    plan_id: str = ""    # урок по плану: id плана, этапы урока повторяют его этапы

    def find_block(self, block_id: str) -> Block | None:
        return next((b for b in self.blocks if b.id == block_id), None)

    def code_blocks(self) -> list[Block]:
        return [b for b in self.blocks if b.type == BLOCK_CODE]

    def next_code(self, after_id: str = "", back: bool = False) -> "Block | None":
        """Следующий (back — предыдущий) непустой блок кода после блока after_id; без него — первый."""
        items = list(reversed(self.blocks)) if back else list(self.blocks)
        ids = [b.id for b in items]
        start = ids.index(after_id) + 1 if after_id in ids else (len(ids) if after_id else 0)
        return next((b for b in items[start:] if is_printable(b)), None)

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


def is_printable(b: Block) -> bool:
    """По Ctrl+F9 печатается только непустой код; заметки и картинки — для преподавателя."""
    return b.type == BLOCK_CODE and bool(b.text.strip())


def sample_template() -> Template:
    """Урок для новой базы — образцовый урок (autoprint/samples/lesson-example.md)."""
    from .samples_lesson import lesson_sample
    return lesson_sample()


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
    try:
        b.slide = max(0, min(9999, int(b.slide)))
    except (TypeError, ValueError):
        b.slide = 0
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
    kind = "plan" if d.get("kind") == KIND_PLAN else ""
    return Template(title=d.get("title", "Без названия"), blocks=blocks, active_block=d.get("active_block", ""),
                    id=d.get("id") or new_id(), updated=d.get("updated", time.time()),
                    start=str(d.get("start") or ""), preset=str(d.get("preset") or ""),
                    look=str(d.get("look") or ""), kind=kind,
                    plan_id="" if kind else str(d.get("plan_id") or ""))


def _fresh_ids(t: Template) -> Template:
    """Свои id блоков и урока (копия, импорт). Связь с планом не трогает: копия урока остаётся по тому же плану."""
    for b in t.blocks:
        b.id = new_id()
    t.id, t.active_block = new_id(), ""
    return t


def without_plan(t: Template) -> Template:
    """Урок без связи с планом: импорт из файла и вставка всегда дают обычный урок (план остаётся планом)."""
    t.plan_id = ""
    for b in t.blocks:
        b.link = ""
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
        if self.drop_dangling_links():
            log.warning("Уроки ссылались на удалённый план — связь снята, этапы остались")

    def plans(self) -> list[Template]:
        return [t for t in self.templates if t.kind == KIND_PLAN]

    def topics_of(self, plan_id: str) -> list[Template]:
        """Уроки по плану plan_id — в порядке списка."""
        return [t for t in self.templates if plan_id and t.kind != KIND_PLAN and t.plan_id == plan_id]

    def drop_dangling_links(self) -> int:
        """Связь с несуществующим планом (базу правили руками, сбой между сохранениями) снимается: этапы урока
        остаются, их снова можно править. → сколько уроков отвязано."""
        ids = {t.id for t in self.plans()}
        n = 0
        for t in self.templates:
            if t.kind == KIND_PLAN:
                t.plan_id = ""
                for b in t.blocks:
                    b.link = ""
            elif t.plan_id and t.plan_id not in ids or not t.plan_id and any(b.link for b in t.blocks
                                                                               if b.type == BLOCK_STAGE):
                without_plan(t)
                n += 1
        return n

    def add_plan_from_structure(self, key: str, title: str = "") -> Template:
        """Новый план урока по шаблону структуры (STRUCTURES): только этапы с минутами; пустой — этап «Начало»."""
        name, stages = STRUCTURES.get(key, STRUCTURES["empty"])
        if not stages:
            name, stages = "Новый план", [("Начало", 5)]
        blocks = [Block(BLOCK_STAGE, "", title=s, minutes=m, stage_kind=k[0] if k else "") for s, m, *k in stages]
        t = Template(title=title or f"План: {name}", blocks=blocks, kind=KIND_PLAN)
        self.templates.append(t)
        return t

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

    def add_from_structure(self, key: str, title: str = "Новый урок") -> Template:
        """Новый урок по шаблону структуры (STRUCTURES): этапы с минутами, цель урока в начале; у рефлексии —
        вопрос, у домашнего задания — плашка «Домашнее задание»."""
        stages = STRUCTURES.get(key, STRUCTURES["empty"])[1]
        if not stages:
            return self.add(title)
        blocks = [Block(BLOCK_MARKDOWN, "", role="goal")]
        for name, minutes, *kind in stages:
            blocks.append(Block(BLOCK_STAGE, "", title=name, minutes=minutes, stage_kind=kind[0] if kind else ""))
            if kind and kind[0] == "break":
                continue
            role = "homework" if name == "Домашнее задание" else "ask" if name == "Рефлексия" else "say"
            blocks.append(Block(BLOCK_MARKDOWN, "", role=role))
        t = Template(title=title, blocks=blocks)
        self.templates.append(t)
        return t

    def add(self, title: str) -> Template:
        t = Template(title=title, blocks=[Block(BLOCK_STAGE, "", title="Начало", minutes=5),
                                          Block(BLOCK_MARKDOWN, "", role="say")])
        self.templates.append(t)
        return t

    def insert(self, t: Template) -> Template:
        self.templates.append(t)
        return t

    def duplicate(self, t: Template) -> Template:
        """Копия рядом: копия урока — по тому же плану; копия плана — новый план без уроков."""
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
        return without_plan(_fresh_ids(_template_from(raw.get("autoprintcode_template", raw))))
