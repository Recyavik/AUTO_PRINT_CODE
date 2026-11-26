"""Отчёт об ошибке: версии, система, обезличенные настройки и журнал — для сообщения автору.

Без виджетов: лист «Сообщить об ошибке» — в окне программы (sheets.js, app_cmd.call_report*). Qt используется, только если уже есть QGuiApplication
(экраны, звуковые устройства); без него отчёт собирается тоже.

Приватность. В отчёт НЕ попадают:
- текст образцов и то, что печатается (из образцов берутся только количества);
- путь к папке пользователя и его имя — заменяются на «%USERPROFILE%» и «<user>» везде: в журнале,
  в путях, в описании; имя компьютера — на «<pc>», адреса почты — на «<email>»;
- заголовки чужих окон из журнала («Code.exe «секрет.py - Visual Studio Code»») — остаётся только
  программа: «Code.exe «… - Visual Studio Code»»;
- положение окна, открытые вкладки и прочее из настроек, что описывает работу пользователя.
Строки журнала, совпавшие со строкой какого-нибудь образца (например, в тексте исключения), скрываются.

    collect()        → dict отчёта
    to_markdown()    → текст для GitHub / буфера обмена
    save_zip()       → report.md + журналы целиком (обезличенные) в .zip
    issue_url()      → ссылка «новое сообщение» на GitHub с кратким текстом (полный — в .zip)
"""
from __future__ import annotations

import ctypes
import getpass
import json
import locale
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlencode

from . import APP_NAME, __version__, updater
from .storage import PROFILES, TEMPLATES_FILE, Settings, app_dir

LOG_TAIL_LINES = 400        # столько последних строк журнала идёт в сам отчёт (в .zip — журнал целиком)
MAX_CRASHES = 5             # разных необработанных исключений в отчёте
MAX_LINE = 600              # длиннее — строка журнала обрезается
URL_LIMIT = 5800            # GitHub не открывает ссылки длиннее ~6000 знаков (кириллица — 6 знаков на букву)
CRASH_MARK = "Необработанное исключение"   # logs.setup_logging → log.critical(...)

USER_PROFILE = "%USERPROFILE%"
USER = "<user>"
PC = "<pc>"
HIDDEN_TEXT = "<текст занятия скрыт>"

# что из настроек не нужно для разбора ошибки и описывает работу пользователя
_DROP_SETTINGS = {"window_geometry", "splitter_state", "open_tabs", "current_tab"}
_CUSTOM_SOUND = "my_"       # sounds.CUSTOM_PREFIX: свой звук — имя набора придумал пользователь

INSTALL_MODES = {updater.MODE_GIT: "git-клон", updater.MODE_SOURCE: "исходники (архив)",
                 updater.MODE_FROZEN: "сборка .exe"}
PRINT_MODES = {"block": "Целиком", "lines": "По строкам", "steps": "По шагам"}

_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3} (\w+)\b")
# заголовок — до ПОСЛЕДНЕЙ «»» в строке: в нём самом бывают кавычки («Договор «Ромашка» - Word»).
# Начало имени exe — только с начала слова: иначе на длинной строке без пробелов поиск квадратичный
_TITLE_RE = re.compile(r"(?P<exe>(?<![^\s«»(])[^\s«»]+?\.exe|\?|pid \d+) «(?P<t>[^\n]*)»", re.IGNORECASE)
_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# строка в кавычках, в том числе repr() с экранированием (\t, \', \")
_QUOTED_RE = re.compile(r"'((?:[^'\\\n]|\\.){8,})'|\"((?:[^\"\\\n]|\\.){8,})\"")
_FILE_EXT_RE = re.compile(r"\.\w{1,6}$")
_PRECUT = MAX_LINE * 20     # совсем длинную строку журнала укоротить ДО замен — регулярные выражения не тормозят


def _safe(fn, default=None):
    """Сбор сведений не должен ронять отчёт: что не удалось узнать — то пропускаем."""
    try:
        return fn()
    except Exception:
        return default


# ---------------------------------------------------------------- обезличивание

def _short_path(p: str) -> str:
    """Короткое имя 8.3 (C:\\Users\\IVANPE~1): так путь к профилю иногда попадает в трассировки."""
    if sys.platform != "win32" or not p:
        return ""
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(p, buf, len(buf))
    return buf.value if 0 < n < len(buf) else ""


@lru_cache(maxsize=1)
def _identity_patterns() -> tuple[re.Pattern | None, re.Pattern | None, re.Pattern | None]:
    """(путь к профилю, имя пользователя, имя компьютера) — регулярные выражения для замены."""
    homes = {os.environ.get("USERPROFILE", ""), os.environ.get("HOME", ""), _safe(lambda: str(Path.home()), "")}
    homes |= {_safe(lambda h=h: _short_path(h), "") for h in list(homes)}
    paths = set()
    for h in homes:
        h = (h or "").rstrip("\\/")
        if len(h) < 4:          # «C:» или пусто — заменять нечего
            continue
        paths |= {h, h.replace("\\", "/"), h.replace("/", "\\"), h.replace("\\", "\\\\")}
        # путь внутри ссылки (file:///C%3A%5CUsers%5C…): там граница имени — не «\», и имя пользователя
        # отдельно не нашлось бы
        paths |= {quote(h.replace("/", "\\"), safe=""), quote(h.replace("\\", "/"), safe=""),
                  quote(h.replace("\\", "/"), safe="/:")}
    profile = (re.compile("|".join(re.escape(p) for p in sorted(paths, key=len, reverse=True)), re.IGNORECASE)
               if paths else None)

    def words(names: set[str]) -> re.Pattern | None:
        names = {n.strip() for n in names if n and len(n.strip()) >= 2}
        if not names:
            return None
        alt = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
        # граница — не буква и не цифра: «Admin» в «Admin_old» заменяется, в «Administrator» — нет
        return re.compile(rf"(?<![^\W_])(?:{alt})(?![^\W_])", re.IGNORECASE)

    users = {os.environ.get("USERNAME", ""), _safe(getpass.getuser, ""),
             Path(os.environ.get("USERPROFILE", "")).name}
    pcs = {os.environ.get("COMPUTERNAME", ""), _safe(platform.node, "")}
    domain = os.environ.get("USERDOMAIN", "")
    if domain and domain.upper() not in ("WORKGROUP", "NT AUTHORITY"):
        pcs.add(domain)
    return profile, words(users), words(pcs - users)


def _mask_title(m: re.Match) -> str:
    """Заголовок чужого окна → только название программы (последняя часть «… - Visual Studio Code»)."""
    exe, t = m.group("exe"), m.group("t")
    if not t:
        return m.group(0)
    if t.startswith(APP_NAME):    # своё окно: «AutoPrintCode — Пауза · <название блока>…»
        return f"{exe} «{APP_NAME}{' — …' if len(t) > len(APP_NAME) else ''}»"
    for sep in (" - ", " — ", " – "):
        if sep in t:
            last = t.rsplit(sep, 1)[1].strip().rstrip("…").strip()
            last = last.rsplit(":", 1)[-1].strip()   # Edge: «Иван: Microsoft Edge» — имя профиля не нужно
            # последняя часть — обычно название программы; у JetBrains («проект – файл.py») — имя файла
            if 0 < len(last) <= 40 and not _FILE_EXT_RE.search(last) and "«" not in last and "»" not in last:
                return f"{exe} «…{sep}{last}»"
    return f"{exe} «…»"


_ESCAPES = {"t": "\t", "'": "'", '"': '"', "\\": "\\"}


def _unescape(s: str) -> str:
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(0)), s)


def _hide_template_text(line: str, private: set[str]) -> str:
    if not private:
        return line
    s = line.strip()
    if s in private:
        return line[:len(line) - len(line.lstrip())] + HIDDEN_TEXT

    def quoted(m: re.Match) -> str:
        body = m.group(1) if m.group(1) is not None else m.group(2)
        parts = re.split(r"\\r\\n|\\n|\n", body)
        # repr() строки образца: «\t», «\'», «\"», «\\» — сравниваем с исходным текстом строки
        parts += [_unescape(p) for p in parts]
        if any(p.strip() in private for p in parts) or body.strip() in private:
            q = m.group(0)[0]
            return f"{q}{HIDDEN_TEXT}{q}"
        return m.group(0)
    return _QUOTED_RE.sub(quoted, line)


def sanitize(text: str, private: set[str] | None = None) -> str:
    """Убрать из текста путь к профилю, имя пользователя и компьютера, почту, заголовки чужих окон
    и строки образцов (private — набор строк образцов, см. template_lines())."""
    if not text:
        return text or ""
    profile, user, pc = _identity_patterns()
    out = []
    for line in text.split("\n"):
        if len(line) > _PRECUT:
            line = line[:_PRECUT]
        line = _hide_template_text(line, private or set())
        if profile is not None:
            line = profile.sub(lambda _m: USER_PROFILE, line)
        line = _EMAIL_RE.sub("<email>", line)
        if user is not None:
            line = user.sub(USER, line)
        if pc is not None:
            line = pc.sub(PC, line)
        line = _TITLE_RE.sub(_mask_title, line)
        if len(line) > MAX_LINE:
            line = line[:MAX_LINE] + "…"
        out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------- образцы: только количества

def _template_blocks(t: dict) -> list[dict]:
    if isinstance(t.get("blocks"), list):
        return [b for b in t["blocks"] if isinstance(b, dict)]
    # формат до v0.3: образец → задачи → блоки
    return [b for task in t.get("tasks") or [] if isinstance(task, dict)
            for b in task.get("blocks") or [] if isinstance(b, dict)]


def _read_templates() -> list[dict]:
    try:
        raw = json.loads(TEMPLATES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = raw.get("templates") if isinstance(raw, dict) else None
    return [t for t in items or [] if isinstance(t, dict)]


def template_lines() -> set[str]:
    """Строки всех образцов (без отступов, от 8 знаков) — чтобы скрыть их, если попали в журнал.
    В сам отчёт этот набор не кладётся."""
    out: set[str] = set()
    for t in _read_templates():
        for s in (str(t.get("title") or ""),):
            if len(s.strip()) >= 8:
                out.add(s.strip())
        for b in _template_blocks(t):
            for s in [str(b.get("title") or "")] + str(b.get("text") or "").splitlines():
                s = s.strip()
                if len(s) >= 8:
                    out.add(s)
    return out


def _template_stats() -> dict:
    templates = _read_templates()
    stats = {"templates": len(templates), "blocks": 0, "code_blocks": 0, "markdown_blocks": 0,
             "code_lines": 0, "step_blocks": 0, "langs": {}}
    for t in templates:
        for b in _template_blocks(t):
            stats["blocks"] += 1
            if b.get("type") == "code":
                stats["code_blocks"] += 1
                stats["code_lines"] += len(str(b.get("text") or "").splitlines())
                lang = str(b.get("lang") or "?")[:20]
                stats["langs"][lang] = stats["langs"].get(lang, 0) + 1
                steps = b.get("steps")
                if isinstance(steps, list) and any(s != 1 for s in steps):
                    stats["step_blocks"] += 1
            else:
                stats["markdown_blocks"] += 1
    return stats


# ---------------------------------------------------------------- журнал

def log_files() -> list[Path]:
    """Файлы журнала от старого к новому: autoprint.log.3, .2, .1, autoprint.log."""
    from .logs import LOG_DIR, LOG_FILE
    if not LOG_DIR.is_dir():
        return []
    backups = []
    for p in LOG_DIR.glob(LOG_FILE.name + ".*"):
        suffix = p.name[len(LOG_FILE.name) + 1:]
        if suffix.isdigit():
            backups.append((int(suffix), p))
    files = [p for _n, p in sorted(backups, reverse=True)]
    if LOG_FILE.is_file():
        files.append(LOG_FILE)
    return files


def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _crashes(lines: list[str]) -> list[dict]:
    """Необработанные исключения из журнала — новые первыми, одинаковые склеены (count)."""
    found: dict[str, dict] = {}
    cur: dict | None = None
    for ln in lines + ["0000-00-00 00:00:00,000 END"]:   # последняя запись тоже закрывается
        m = _TS_RE.match(ln)
        if m:
            if cur is not None:
                text = "\n".join(cur["body"]).strip("\n") or cur["head"]
                prev = found.pop(text, None)
                found[text] = {"time": cur["time"], "text": text, "count": (prev["count"] if prev else 0) + 1}
            cur = {"time": m.group(1), "head": ln[m.end():].strip(), "body": []} if CRASH_MARK in ln else None
        elif cur is not None:
            cur["body"].append(ln.rstrip())
    return list(reversed(found.values()))[:MAX_CRASHES]


# ---------------------------------------------------------------- система

def _windows() -> dict:
    if sys.platform != "win32":
        return {"name": f"{platform.system()} {platform.release()}", "build": platform.version()}
    v = sys.getwindowsversion()
    info = {"name": f"Windows {'11' if v.build >= 22000 else platform.release()}", "build": str(v.build),
            "edition": _safe(platform.win32_edition, "") or ""}

    def reg() -> None:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as k:
            for name, key in (("DisplayVersion", "release"), ("UBR", "ubr")):
                info[key] = str(_safe(lambda n=name: winreg.QueryValueEx(k, n)[0], "") or "")
    _safe(reg)
    if info.get("ubr"):
        info["build"] += "." + info.pop("ubr")
    info.pop("ubr", None)
    return info


def _keyboard_layouts() -> list[str]:
    """Раскладки клавиатуры («ru_RU 04190419»): от них зависит, как печатаются символы."""
    if sys.platform != "win32":
        return []
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32")
    user32.GetKeyboardLayoutList.argtypes = [ctypes.c_int, ctypes.POINTER(wintypes.HKL)]
    user32.GetKeyboardLayoutList.restype = ctypes.c_int
    n = user32.GetKeyboardLayoutList(0, None)
    if n <= 0:
        return []
    buf = (wintypes.HKL * n)()
    n = user32.GetKeyboardLayoutList(n, buf)
    out = []
    for h in buf[:n]:
        hkl = (h or 0) & 0xFFFFFFFF
        lang = locale.windows_locale.get(hkl & 0xFFFF, f"0x{hkl & 0xFFFF:04x}")
        out.append(f"{lang} {hkl:08x}")
    return out


def _locale() -> dict:
    d = {"encoding": _safe(lambda: locale.getpreferredencoding(False), "") or ""}
    loc = _safe(lambda: locale.getlocale()[0], None)
    if loc:
        d["python"] = loc
    try:
        from PySide6.QtCore import QLocale
        d["qt"] = QLocale.system().name()
    except Exception:
        pass
    return d


def _qt_versions() -> dict:
    d = {}
    try:
        import PySide6
        from PySide6 import QtCore
        d = {"pyside": PySide6.__version__, "qt": QtCore.qVersion()}
    except Exception:
        pass
    return d


def _gui() -> dict | None:
    """Экраны и масштаб — только если окно программы уже есть (QGuiApplication создан)."""
    try:
        from PySide6.QtGui import QGuiApplication
    except Exception:
        return None
    app = QGuiApplication.instance()
    if app is None:
        return None
    primary = QGuiApplication.primaryScreen()
    screens = []
    for s in QGuiApplication.screens():
        g = s.geometry()
        screens.append({"size": f"{g.width()}×{g.height()}", "scale": round(s.devicePixelRatio() * 100),
                        "dpi": round(s.logicalDotsPerInch()), "hz": round(s.refreshRate()),
                        "primary": s == primary})
    return {"platform": QGuiApplication.platformName(), "screens": screens}


def _audio_devices() -> dict | None:
    """Звуковые устройства (названия) — необязательно: только при живом QGuiApplication."""
    try:
        from PySide6.QtGui import QGuiApplication
        if QGuiApplication.instance() is None:
            return None
        from PySide6.QtMultimedia import QMediaDevices
    except Exception:
        return None

    def names(devs) -> list[str]:
        return [sanitize(d.description()) + (" (по умолчанию)" if d.isDefault() else "") for d in devs]
    return {"outputs": names(QMediaDevices.audioOutputs()), "inputs": names(QMediaDevices.audioInputs())}


def _git_commit() -> str:
    """Коммит git-клона («a1b2c3d» или «a1b2c3d, есть правки»)."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def git(*args: str) -> str:
        p = subprocess.run(["git", *args], cwd=str(app_dir()), capture_output=True, text=True, timeout=3,
                           encoding="utf-8", errors="replace", creationflags=flags)
        return p.stdout.strip() if p.returncode == 0 else ""
    head = git("rev-parse", "--short", "HEAD")
    if head and git("status", "--porcelain", "--untracked-files=no"):
        head += ", есть правки"
    return head


def _settings_snapshot(s: Settings) -> dict:
    d = asdict(s)
    for k in _DROP_SETTINGS:
        d.pop(k, None)
    if str(d.get("sound_style", "")).startswith(_CUSTOM_SOUND):
        d["sound_style"] = _CUSTOM_SOUND + "… (свой звук)"
    # ключи нейросети — только «задан», сами ключи в отчёт не попадают (даже зашифрованными)
    d["ai_keys"] = {k: "задан" for k, v in (d.get("ai_keys") or {}).items() if v}
    last = d.get("update_last_check") or 0
    d["update_last_check"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(last)) if last else "—"
    return d


# ---------------------------------------------------------------- отчёт

def collect(description: str = "", include_settings: bool = True, settings: Settings | None = None) -> dict:
    """Собрать отчёт. settings — текущие настройки программы (по умолчанию читаются из settings.json).
    include_settings=False — без настроек и звуковых устройств."""
    private = _safe(template_lines, set()) or set()
    s = settings if settings is not None else _safe(Settings.load, None) or Settings()
    mode = _safe(updater.install_mode, "?")
    app = {"name": APP_NAME, "version": __version__, "frozen": bool(getattr(sys, "frozen", False)),
           "install_mode": mode, "app_dir": sanitize(str(app_dir())),
           "executable": sanitize(sys.executable)}
    if mode == updater.MODE_GIT:
        app["commit"] = _safe(_git_commit, "") or ""
    system = {"windows": _safe(_windows, {}) or {}, "python": platform.python_version(),
              "arch": platform.machine(), **_qt_versions(), "locale": _safe(_locale, {}) or {},
              "keyboard_layouts": _safe(_keyboard_layouts, []) or []}
    gui = _safe(_gui, None)
    if gui:
        system["gui"] = gui
    lines = []
    for f in log_files():
        lines += sanitize(_read_text(f), private).splitlines()
    tail = lines[-LOG_TAIL_LINES:]
    report = {
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        # описание пишет сам пользователь и видит его в предпросмотре: строки образцов в нём не скрываются
        "description": sanitize(description.strip()),
        "app": app,
        "system": system,
        "usage": {"print_mode": s.print_mode, "profile": s.profile, "human_typing": s.human_typing,
                  "strip_comments": s.strip_comments, "theme": s.theme},
        "templates": _safe(_template_stats, {}) or {},
        "include_settings": include_settings,
        "settings": _safe(lambda: _settings_snapshot(s), {}) if include_settings else None,
        "audio": _safe(_audio_devices, None) if include_settings else None,
        "crashes": _safe(lambda: _crashes(lines), []) or [],
        "log_tail": "\n".join(tail),
        "log_lines": len(tail),
    }
    return report


def open_log_folder() -> None:
    """Открыть папку с журналом работы (data/logs) в Проводнике."""
    from .logs import LOG_DIR
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    os.startfile(LOG_DIR)


def last_crash(report: dict) -> str | None:
    """Трассировка последнего необработанного исключения из журнала (None — не было)."""
    crashes = report.get("crashes") or []
    return crashes[0]["text"] if crashes else None


def crash_summary(text: str) -> str:
    """Строка исключения из трассировки («ValueError: …»): последняя строка без отступа."""
    lines = [ln for ln in (text or "").strip().splitlines() if ln.strip()]
    for ln in reversed(lines):
        if not ln[:1].isspace() and not ln.startswith("Traceback"):
            return ln.strip()
    return lines[-1].strip() if lines else ""


def default_title(report: dict) -> str:
    """Заголовок сообщения: первая строка описания, иначе последняя ошибка."""
    desc = (report.get("description") or "").strip()
    if desc:
        return _clip(desc.splitlines()[0].strip(), 90)
    crash = last_crash(report)
    if crash:
        return _clip("Ошибка: " + crash_summary(crash), 90)
    return "Сообщение об ошибке"


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[:max(0, n - 1)].rstrip() + "…"


def _clip_tail_lines(text: str, n: int) -> str:
    """Конец текста не длиннее n знаков, по целым строкам (в трассировке важнее всего конец)."""
    if len(text) <= n:
        return text
    if n <= 0:
        return ""
    out, size = [], 2
    for ln in reversed(text.splitlines()):
        if size + len(ln) + 1 > n:
            break
        out.append(ln)
        size += len(ln) + 1
    if not out:   # одна очень длинная строка
        return "…" + text[-(n - 1):]
    return "…\n" + "\n".join(reversed(out))


def _fence(text: str, lang: str = "") -> str:
    """Блок кода Markdown; ограда длиннее любой цепочки ` внутри текста."""
    longest = max((len(m) for m in re.findall(r"`{3,}", text)), default=0)
    f = "`" * max(3, longest + 1)
    return f"{f}{lang}\n{text}\n{f}"


def _windows_line(report: dict) -> str:
    w = report.get("system", {}).get("windows") or {}
    parts = [w.get("name", ""), w.get("edition", ""), w.get("release", "")]
    s = " ".join(p for p in parts if p)
    return f"{s} (сборка {w['build']})" if w.get("build") else s


def _versions_line(report: dict) -> str:
    a, s = report.get("app", {}), report.get("system", {})
    mode = INSTALL_MODES.get(a.get("install_mode"), a.get("install_mode", "?"))
    if a.get("commit"):
        mode += f" {a['commit']}"
    out = f"{a.get('name', APP_NAME)} {a.get('version', '?')} ({mode}) · {_windows_line(report)}"
    out += f" · Python {s.get('python', '?')} · PySide6 {s.get('pyside', '?')}"
    if s.get("qt") and s.get("qt") != s.get("pyside"):
        out += f" · Qt {s['qt']}"
    return out


def _usage_line(report: dict) -> str:
    u = report.get("usage") or {}
    out = (f"Режим печати: {PRINT_MODES.get(u.get('print_mode'), u.get('print_mode', '?'))} · "
           f"профиль: {PROFILES.get(u.get('profile'), u.get('profile', '?'))}")
    if u.get("human_typing"):
        out += " · «как человек»"
    if u.get("strip_comments"):
        out += " · без комментариев"
    return out


def to_markdown(report: dict) -> str:
    """Отчёт целиком: для буфера обмена, файла report.md и предпросмотра."""
    a, s = report.get("app", {}), report.get("system", {})
    out = [f"# Отчёт об ошибке — {a.get('name', APP_NAME)} {a.get('version', '?')}",
           "", f"Создан: {report.get('created', '')}", "", "## Что случилось", "",
           report.get("description") or "_(не описано)_", "", "## Программа", ""]
    out.append(f"- {_versions_line(report)}")
    out.append(f"- {_usage_line(report)}")
    out.append(f"- Папка программы: `{a.get('app_dir', '?')}`")
    out.append(f"- Python: `{a.get('executable', '?')}`" + (f" · {s['arch']}" if s.get("arch") else ""))

    out += ["", "## Система", ""]
    loc = s.get("locale") or {}
    lang = " · ".join(x for x in (loc.get("qt"), loc.get("python"), loc.get("encoding")) if x)
    out.append(f"- Язык: {lang or '?'}")
    if s.get("keyboard_layouts"):
        out.append(f"- Раскладки: {', '.join(s['keyboard_layouts'])}")
    gui = s.get("gui")
    if gui:
        scr = [f"{x['size']} @{x['scale']} %, {x['hz']} Гц" + (" (основной)" if x.get("primary") else "")
               for x in gui.get("screens", [])]
        out.append(f"- Экраны ({gui.get('platform', '?')}): {'; '.join(scr) or '—'}")
    audio = report.get("audio")
    if audio:
        out.append(f"- Звук, вывод: {'; '.join(audio.get('outputs') or []) or '—'}")
        out.append(f"- Звук, ввод: {'; '.join(audio.get('inputs') or []) or '—'}")

    t = report.get("templates") or {}
    if t:
        langs = ", ".join(f"{k} {v}" for k, v in sorted(t.get("langs", {}).items(), key=lambda kv: -kv[1]))
        out += ["", "## Занятия (только количество)", "",
                f"- Занятий: {t.get('templates', 0)} · блоков: {t.get('blocks', 0)} "
                f"(код: {t.get('code_blocks', 0)}, текст: {t.get('markdown_blocks', 0)})",
                f"- Строк кода: {t.get('code_lines', 0)} · блоков с разметкой шагов: {t.get('step_blocks', 0)}"
                + (f" · языки: {langs}" if langs else "")]

    st = report.get("settings")
    if st:
        width = max(len(k) for k in st)
        body = "\n".join(f"{k.ljust(width)} = {json.dumps(v, ensure_ascii=False)}" for k, v in st.items())
        out += ["", "## Настройки", "", _fence(body, "ini")]
    elif not report.get("include_settings", True):
        out += ["", "## Настройки", "", "_(не приложены)_"]

    crashes = report.get("crashes") or []
    if crashes:
        c = crashes[0]
        times = f", повторялась {c['count']} раз" if c.get("count", 1) > 1 else ""
        out += ["", "## Ошибки из журнала", "", f"Последняя — {c['time']}{times}:", "",
                _fence(_clip_tail_lines(c["text"], 6000))]
        for c in crashes[1:]:
            last = crash_summary(c["text"]) or "?"
            out.append(f"- {c['time']}: `{_clip(last, 160)}`" + (f" ×{c['count']}" if c.get("count", 1) > 1 else ""))

    out += ["", f"## Журнал (последние {report.get('log_lines', 0)} строк)", ""]
    out.append(_fence(report.get("log_tail") or "(журнал пуст)"))
    return "\n".join(out) + "\n"


def default_zip_name() -> str:
    return f"{APP_NAME}-report-{time.strftime('%Y-%m-%d_%H-%M')}.zip"


def save_zip(report: dict, path) -> Path:
    """Архив для вложения: report.md и журналы целиком (обезличенные), журнал установки обновлений."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    private = _safe(template_lines, set()) or set()
    fd, tmp = tempfile.mkstemp(prefix=path.stem + "-", suffix=".part", dir=str(path.parent))
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("report.md", to_markdown(report))
            for f in log_files():
                z.writestr(f"logs/{f.name}", sanitize(_read_text(f), private))
            if updater.APPLY_LOG.is_file():
                z.writestr(f"logs/{updater.APPLY_LOG.name}", sanitize(_read_text(updater.APPLY_LOG), private))
            from .logs import LOG_DIR
            window_log = LOG_DIR / "window.log"           # сообщения окна программы (Electron, Chromium) — с 1.2
            if window_log.is_file():
                z.writestr("logs/window.log", sanitize(_read_text(window_log)[-200_000:], private))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def _issue_body(report: dict, desc: str, crash: str, attachment: str) -> str:
    out = ["### Что случилось", "", desc or "_(не описано)_", "", "### Версия", "",
           _versions_line(report), _usage_line(report)]
    c = (report.get("crashes") or [None])[0]
    if crash and c:
        out += ["", f"### Последняя ошибка ({c['time']})", "", _fence(crash)]
    name = f"`{attachment}`" if attachment else "(кнопка «Сохранить отчёт…» в окне «Сообщить об ошибке»)"
    out += ["", "---", f"**Приложите файл отчёта** {name} — перетащите его в это поле. В нём сведения о системе "
                       "и журнал работы, без текста занятий и личных данных."]
    return "\n".join(out)


def issue_url(report: dict, title: str = "", attachment: str | os.PathLike | None = None) -> str:
    """Ссылка «новое сообщение» на GitHub с заголовком и кратким текстом (версии, последняя ошибка).
    Длина — не больше URL_LIMIT: при необходимости описание и трассировка укорачиваются."""
    base = f"https://github.com/{updater.REPO}/issues/new?"
    title = _clip(" ".join((title or default_title(report)).split()), 120)
    att = Path(attachment).name if attachment else ""
    desc = (report.get("description") or "").strip()
    crash = (last_crash(report) or "").strip()
    d_lim, c_lim = 1500, 2500
    while True:
        short = _clip(desc, d_lim) if d_lim else ("… (полностью — в файле отчёта)" if desc else "")
        body = _issue_body(report, short, _clip_tail_lines(crash, c_lim), att)
        url = base + urlencode({"title": title, "body": body}, quote_via=quote)
        if len(url) <= URL_LIMIT or (d_lim == 0 and c_lim == 0):
            break
        if c_lim >= d_lim:
            c_lim = c_lim * 2 // 3 if c_lim > 150 else 0
        else:
            d_lim = d_lim * 2 // 3 if d_lim > 150 else 0
    return url
