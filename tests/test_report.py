"""Проверка отчёта об ошибке: сбор сведений, обезличивание, .zip, ссылка на GitHub, окно.

    python tests/test_report.py [папка для снимков]

Рабочая папка data/ не используется (AUTOPRINT_DATA → временная папка). Журнал — поддельный: с трассировкой,
путями к профилю настоящего пользователя, заголовками окон и строкой образца в тексте исключения.
Окно собирается без показа на экране (WA_DontShowOnScreen) и снимается в тёмной и светлой теме.
Браузер не открывается, буфер обмена не трогается.
"""
from __future__ import annotations

import getpass
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="autoprint-report-"))
os.environ["AUTOPRINT_DATA"] = str(TMP / "data")
import quiet  # noqa: E402,F401 — окна только в памяти, без трея и уведомлений

from autoprint import __version__, report, updater  # noqa: E402
from autoprint.logs import LOG_DIR, LOG_FILE  # noqa: E402
from autoprint.storage import SETTINGS_FILE, TEMPLATES_FILE  # noqa: E402

for _stream in (sys.stdout, sys.stderr):   # вывод в канал с кодировкой cp1251 не должен падать на «→»
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

fails = 0


def check(name: str, cond, detail: str = "") -> None:
    global fails
    print(("OK   " if cond else "FAIL ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        fails += 1


PROFILE = os.environ.get("USERPROFILE") or str(Path.home())
USERNAME = os.environ.get("USERNAME") or getpass.getuser()
SECRET_CODE = "secret_salary = compute_bonus(ivan_petrov)"
SECRET_MD = "Пароль от Wi-Fi: hunter2hunter2"
EMAIL = "ivan.petrov@example.com"


def name_re(name: str) -> re.Pattern:
    return re.compile(rf"(?<![^\W_]){re.escape(name)}(?![^\W_])", re.IGNORECASE)


def leaks(text: str) -> list[str]:
    """Что личного осталось в тексте."""
    found = []
    for p in {PROFILE, PROFILE.replace("\\", "/"), PROFILE.replace("\\", "\\\\")}:
        if p.lower() in text.lower():
            found.append(f"путь профиля {p!r}")
    if name_re(USERNAME).search(text):
        found.append(f"имя пользователя {USERNAME!r}")
    for s in (SECRET_CODE, "hunter2hunter2", "secret_project", "Иван", EMAIL, "my_ivan_keyboard",
              "AdnQywADAAAAAAC", "73bf6847855e"):
        if s in text:
            found.append(repr(s))
    return found


# ---------------------------------------------------------------- поддельные данные

def write_fake_data() -> None:
    TEMPLATES_FILE.parent.mkdir(parents=True, exist_ok=True)
    TEMPLATES_FILE.write_text(json.dumps({"version": 3, "templates": [
        {"title": "Зарплаты Ивана Петрова", "id": "73bf6847855e", "blocks": [
            {"type": "markdown", "text": f"## Секрет\n\n{SECRET_MD}", "role": "task"},
            {"type": "code", "lang": "python", "text": f"import os\n{SECRET_CODE}\nprint(secret_salary)",
             "steps": [1, 2, 2]},
        ]},
        {"title": "Второй", "blocks": [{"type": "code", "lang": "javascript", "text": "console.log(1)"}]},
    ]}, ensure_ascii=False), encoding="utf-8")
    SETTINGS_FILE.write_text(json.dumps({
        "cpm": 222, "print_mode": "steps", "profile": "plain", "sound_style": "my_ivan_keyboard",
        "window_geometry": "AdnQywADAAAAAAC", "splitter_state": "AAAA", "open_tabs": ["73bf6847855e"],
        "current_tab": "73bf6847855e"}, ensure_ascii=False), encoding="utf-8")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    esc = PROFILE.replace("\\", "\\\\")
    old = [
        "2026-10-07 10:00:00,000 INFO    MainThread autoprint: ==== AutoPrintCode 0.3.8 запущен",
        f"2026-10-07 10:00:05,000 INFO    MainThread autoprint.import: Импорт {PROFILE}\\Documents\\урок.ipynb",
        "2026-10-07 10:01:00,000 CRITICAL MainThread autoprint: Необработанное исключение",
        "Traceback (most recent call last):",
        f'  File "{PROFILE}\\AppData\\Local\\AutoPrintCode\\autoprint\\sounds.py", line 12, in play',
        "    effect.play()",
        "OSError: старая ошибка звука",
    ]
    crash = [
        "Traceback (most recent call last):",
        f'  File "{PROFILE}\\AppData\\Local\\Programs\\AutoPrintCode\\_internal\\autoprint\\ui\\main_window.py",'
        " line 42, in _on_click",
        "    self.engine.start(job)",
        f'  File "{PROFILE.replace(chr(92), "/").lower()}/projects/autoprint/typer.py", line 10, in start',
        "    raise ValueError(text)",
        f"ValueError: не удалось открыть '{esc}\\\\Documents\\\\урок.ipynb': '{SECRET_MD}'",
        f"    {SECRET_CODE}",
    ]
    new = [
        "2026-10-08 12:00:00,000 INFO    MainThread autoprint: ==== AutoPrintCode 0.4.0 запущен",
        "2026-10-08 12:00:10,000 INFO    Thread-1 (_worker) autoprint.typer: Печать начата с 0/50 → "
        "Code.exe «secret_project.py - Visual Studio Code» · профиль=ide · 200 симв/мин",
        "2026-10-08 12:00:20,000 INFO    Thread-1 (_worker) autoprint.typer: Пауза (сменилось окно → "
        "msedge.exe «Почта — Иван: Microsoft Edge») на 10/50",
        "2026-10-08 12:00:21,000 INFO    MainThread autoprint.typer: Пауза (сменилось окно → "
        "pythonw.exe «AutoPrintCode — Пауза · Задача Ивана») на 10/50",
        f"2026-10-08 12:00:30,000 WARNING MainThread autoprint: вход {USERNAME} ({EMAIL}), "
        f"папка {PROFILE.lower()}\\Desktop",
        "2026-10-08 12:01:00,000 CRITICAL MainThread autoprint: Необработанное исключение", *crash,
        "2026-10-08 12:02:00,000 CRITICAL MainThread autoprint: Необработанное исключение", *crash,
        "2026-10-08 12:03:00,000 INFO    MainThread autoprint.typer: Стоп на 10/50",
    ]
    LOG_FILE.with_name(LOG_FILE.name + ".1").write_text("\n".join(old) + "\n", encoding="utf-8")
    LOG_FILE.write_text("\n".join(new) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- без окна

def test_collect_plain() -> dict:
    from PySide6.QtGui import QGuiApplication
    check("QApplication ещё нет", QGuiApplication.instance() is None)
    rep = report.collect(f"Не печатает. Файл {PROFILE}\\Desktop\\a.py, пользователь {USERNAME}")
    check("версия программы", rep["app"]["version"] == __version__)
    check("способ установки", rep["app"]["install_mode"] in report.INSTALL_MODES)
    check("версии Python/PySide6/Qt", rep["system"].get("python") and rep["system"].get("pyside")
          and rep["system"].get("qt"))
    check("Windows и сборка", rep["system"]["windows"].get("name", "").startswith("Windows")
          and rep["system"]["windows"].get("build"))
    check("без QApplication — без экранов и звука", "gui" not in rep["system"] and rep["audio"] is None)
    check("последние строки журнала из всех файлов по порядку",
          rep["log_tail"].index("0.3.8 запущен") < rep["log_tail"].index("0.4.0 запущен"))
    t = rep["templates"]
    check("образцы — только количества", (t["templates"], t["blocks"], t["code_blocks"], t["markdown_blocks"],
                                           t["code_lines"], t["step_blocks"]) == (2, 3, 2, 1, 4, 1), str(t))
    st = rep["settings"]
    check("настройки приложены", st and st["cpm"] == 222 and st["hotkey_toggle"] == "Ctrl+F9")
    check("из настроек убраны окно и вкладки",
          not {"window_geometry", "splitter_state", "open_tabs", "current_tab"} & set(st))
    check("свой звук без имени", "ivan" not in st["sound_style"])
    check("режим печати и профиль", rep["usage"]["print_mode"] == "steps" and rep["usage"]["profile"] == "plain")

    md = report.to_markdown(rep)
    check("в отчёте нет личного (путь, имя, почта, образцы, заголовки окон)", not leaks(md), ", ".join(leaks(md)))
    check("путь заменён на %USERPROFILE%", "%USERPROFILE%\\Desktop" in md and "%USERPROFILE%\\AppData" in md)
    check("имя заменено на <user>", f"вход {report.USER}" in md and f"пользователь {report.USER}" in md)
    check("строка образца в исключении скрыта", report.HIDDEN_TEXT in md)
    check("от заголовка окна осталась программа",
          "Code.exe «… - Visual Studio Code»" in md and "msedge.exe «… — Microsoft Edge»" in md
          and "pythonw.exe «AutoPrintCode — …»" in md)
    check("в отчёте раздел журнала и настроек", "## Журнал" in md and "## Настройки" in md and "cpm" in md)

    crash = report.last_crash(rep)
    check("last_crash нашёл трассировку", crash is not None and crash.startswith("Traceback")
          and "ValueError: не удалось открыть" in crash, repr(crash))
    check("одинаковые ошибки склеены", rep["crashes"][0]["count"] == 2 and rep["crashes"][0]["time"]
          == "2026-10-08 12:02:00", str(rep["crashes"][:1]))
    check("старая ошибка из прошлого файла журнала", len(rep["crashes"]) == 2
          and "OSError: старая ошибка звука" in rep["crashes"][1]["text"])
    check("трассировка обезличена", not leaks(crash or ""), ", ".join(leaks(crash or "")))
    check("без ошибок в журнале — None", report.last_crash({"crashes": []}) is None)
    check("crash_summary — строка исключения, а не хвост трассировки",
          report.crash_summary(crash or "").startswith("ValueError: не удалось открыть"))
    check("заголовок без описания — по ошибке",
          report.default_title({**rep, "description": ""}).startswith("Ошибка: ValueError"))

    off = report.collect("", include_settings=False)
    md_off = report.to_markdown(off)
    check("без настроек — их нет в отчёте", off["settings"] is None and "hotkey_toggle" not in md_off)
    return rep


def test_zip(rep: dict) -> None:
    path = report.save_zip(rep, TMP / "out" / report.default_zip_name())
    check("zip сохранён", path.is_file() and path.name.startswith("AutoPrintCode-report-"))
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        check("в zip report.md и журналы", {"report.md", "logs/autoprint.log", "logs/autoprint.log.1"} <= names,
              str(names))
        texts = {n: z.read(n).decode("utf-8") for n in names}
    bad = {n: leaks(t) for n, t in texts.items() if leaks(t)}
    check("в zip нет личного", not bad, str(bad))
    check("журнал в zip целиком", "0.3.8 запущен" in texts["logs/autoprint.log.1"]
          and "Стоп на 10/50" in texts["logs/autoprint.log"])
    check("временный файл убран", not list(path.parent.glob("*.part")))


def test_issue_url(rep: dict) -> None:
    url = report.issue_url(rep, report.default_title(rep), "AutoPrintCode-report-x.zip")
    parts = urlsplit(url)
    q = parse_qs(parts.query)
    check("ссылка на новое сообщение в репозитории",
          url.startswith(f"https://github.com/{updater.REPO}/issues/new?") and parts.path.endswith("/issues/new"))
    check("ссылка короче 6000 знаков", len(url) < 6000, str(len(url)))
    check("ссылка только из ASCII", url.isascii())
    body = q.get("body", [""])[0]
    check("заголовок и текст на месте", q.get("title", [""])[0].startswith("Не печатает") and body)
    check("в тексте версия, ошибка и имя файла", __version__ in body and "ValueError" in body
          and "AutoPrintCode-report-x.zip" in body, body[:300])
    check("в тексте ссылки нет личного", not leaks(body), ", ".join(leaks(body)))

    big = dict(rep)
    big["description"] = "Очень длинное описание ошибки. " * 400
    big["crashes"] = [{"time": "2026-10-08 12:00:00", "count": 1, "text": "Traceback (most recent call last):\n"
                       + "\n".join(f'  File "модуль{i}.py", line {i}, in функция{i}' for i in range(600))
                       + "\nRuntimeError: конец трассировки"}]
    url = report.issue_url(big, "Т" * 500)
    body = parse_qs(urlsplit(url).query)["body"][0]
    check("длинные описание и трассировка укорочены до лимита", len(url) < 6000, str(len(url)))
    check("от трассировки остался конец", "RuntimeError: конец трассировки" in body)
    check("без имени файла — подсказка, как сохранить", "Сохранить отчёт" in body)


def test_with_app() -> None:
    from PySide6.QtWidgets import QApplication
    QApplication(sys.argv)
    quiet.patch()
    rep = report.collect("с окном")
    gui = rep["system"].get("gui")
    check("с QApplication — экраны и масштаб", gui and gui["screens"] and gui["screens"][0]["scale"] > 0, str(gui))
    check("звуковые устройства (необязательно) — списки",
          rep["audio"] is None or (isinstance(rep["audio"]["outputs"], list)
                                   and isinstance(rep["audio"]["inputs"], list)))
    check("и с окном в отчёте нет личного", not leaks(report.to_markdown(rep)))

    # окно «Сообщить об ошибке» — с 1.0 лист в окне программы: tests/test_app_sheets.py (WindowSheetsTest)


def main() -> int:
    write_fake_data()
    rep = test_collect_plain()
    test_zip(rep)
    test_issue_url(rep)
    test_with_app()
    shutil.rmtree(TMP, ignore_errors=True)
    print("\nВсё в порядке." if not fails else f"\nОшибок: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
