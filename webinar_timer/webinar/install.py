"""Завершение установки (запускает «Установка.bat» из окружения .venv): значок и ярлык на рабочем столе.

    .venv\\Scripts\\python.exe -m webinar.install

Ярлык запускает таймер без окна консоли (pythonw) из папки приложения — где бы она ни лежала.
WEBINAR_DESKTOP — другая папка для ярлыка (для проверки установки, чтобы не трогать рабочий стол).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
ICON = APP_DIR / "webinar.ico"
SHORTCUT_NAME = "Таймер вебинара.lnk"


def make_icon_file() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # без окон: только нарисовать значок
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from webinar.ui.main_window import make_icon
    if not make_icon().pixmap(256).save(str(ICON), "ICO"):
        raise SystemExit("Не удалось сохранить значок")
    del app


def desktop_dir() -> Path:
    if os.environ.get("WEBINAR_DESKTOP"):
        return Path(os.environ["WEBINAR_DESKTOP"])
    out = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                         capture_output=True, text=True, encoding="utf-8", check=True)
    return Path(out.stdout.strip())     # рабочий стол может быть в OneDrive — спрашиваем Windows


def make_shortcut() -> Path:
    link = desktop_dir() / SHORTCUT_NAME
    pythonw = APP_DIR / ".venv" / "Scripts" / "pythonw.exe"
    # пути — через переменные окружения: так кириллица и пробелы не ломают командную строку PowerShell
    env = {**os.environ, "APC_LINK": str(link), "APC_TARGET": str(pythonw), "APC_DIR": str(APP_DIR),
           "APC_ICON": str(ICON)}
    script = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:APC_LINK);"
              "$s.TargetPath = $env:APC_TARGET; $s.Arguments = '\"webinar.py\"';"
              "$s.WorkingDirectory = $env:APC_DIR; $s.IconLocation = $env:APC_ICON;"
              "$s.Description = 'Таймер вебинара'; $s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", script], env=env, check=True)
    return link


def main() -> int:
    sys.path.insert(0, str(APP_DIR))
    make_icon_file()
    link = make_shortcut()
    print(f"Ярлык на рабочем столе: {link}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
