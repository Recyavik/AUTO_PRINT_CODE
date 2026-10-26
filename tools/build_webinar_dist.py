"""Дистрибутив «Таймера вебинара» для коллег: самораспаковывающийся архив в INSTALL/.

    python tools/build_webinar_dist.py

Python на компьютере коллеги не нужен: PyInstaller собирает «Таймер вебинара.exe» вместе с Python и PySide6
(окна, видео, звук). Рядом с exe — media/ (фон, видео гимнастики, шрифт), templates/, data/ (шаблоны и
настройки без привязки к этому компьютеру: мониторы и места окон у коллеги свои) и «Создать ярлык на рабочем
столе.bat». Всё упаковывается 7-Zip в самораспаковывающийся .exe: коллега запускает его, выбирает папку —
и запускает таймер.

Для сборки нужны Python 3.10–3.13 (обычный, не «t» без GIL) и 7-Zip. Окружение сборки (PySide6, PyInstaller)
создаётся само в build/webinar/venv и переиспользуется.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "webinar_timer"
BUILD = ROOT / "build" / "webinar"
VENV = BUILD / "venv"
OUT = ROOT / "INSTALL"
NAME = "Таймер вебинара"

# у коллеги — свои мониторы и окна
MACHINE_SETTINGS = {"demo_screen": "", "control_screen": "", "window_geometry": "", "note_pos": "",
                    "player_pos": ""}
# ярлык без кириллицы в командной строке: имя ярлыка — по имени exe, путь — из %~dp0
SHORTCUT_BAT = """@echo off
set "APPDIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$exe = Get-ChildItem -LiteralPath $env:APPDIR -Filter '*.exe' | Select-Object -First 1;" ^
  "$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) ($exe.BaseName + '.lnk');" ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk);" ^
  "$s.TargetPath = $exe.FullName; $s.WorkingDirectory = $env:APPDIR; $s.IconLocation = $exe.FullName; $s.Save()"
if errorlevel 1 (echo Не получилось создать ярлык & pause & exit /b 1)
echo Ярлык создан на рабочем столе.
timeout /t 3 >nul
"""


def run(cmd: list, **kw) -> None:
    print("  >", " ".join(str(c) for c in cmd[:4]), "…" if len(cmd) > 4 else "")
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def find_7z() -> Path:
    for p in (shutil.which("7z"), r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if p and Path(p).is_file():
            return Path(p)
    raise SystemExit("Не найден 7-Zip (7z.exe) — установите его с https://www.7-zip.org/")


def version() -> str:
    for line in (APP / "webinar" / "__init__.py").read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("Не найдена версия в webinar/__init__.py")


def venv_python() -> Path:
    """Окружение сборки: Python с PySide6 и PyInstaller (создаётся один раз)."""
    py = VENV / "Scripts" / "python.exe"
    if not py.exists():
        check = "import sys, sysconfig; sys.exit(sys.version_info < (3, 10) or bool(sysconfig.get_config_var('Py_GIL_DISABLED')))"
        base = next(([*c] for c in (["py", "-3.13"], ["py", "-3.12"], ["py", "-3.11"], [sys.executable])
                     if subprocess.run([*c, "-c", check], capture_output=True).returncode == 0), None)
        if base is None:
            raise SystemExit("Нужен Python 3.10–3.13 (обычный) для сборки")
        run([*base, "-m", "venv", VENV])
    run([py, "-m", "pip", "install", "-q", "--disable-pip-version-check", "-r", APP / "requirements.txt",
         "pyinstaller"])
    return py


def _rmtree(path: Path) -> None:
    """Удалить папку прошлой сборки, в том числе файлы «только чтение» (шрифт копируется из Windows таким)."""
    def unlock(func, p, _exc) -> None:
        os.chmod(p, stat.S_IWRITE)
        func(p)
    if path.exists():
        shutil.rmtree(path, onexc=unlock)


def build_exe(py: Path) -> Path:
    """«Таймер вебинара.exe» с папкой _internal (Python, Qt) — в build/webinar/dist/."""
    ico = APP / "webinar.ico"
    run([py, "-c", "import sys; sys.path.insert(0, '.'); from webinar.install import make_icon_file; make_icon_file()"],
        cwd=APP)
    dist = BUILD / "dist"
    _rmtree(dist / NAME)
    run([py, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", NAME, "--icon", ico,
         "--add-data", f"{APP / 'webinar' / 'ui' / '*.svg'};webinar/ui",
         "--hidden-import", "PySide6.QtMultimedia", "--hidden-import", "PySide6.QtMultimediaWidgets",
         "--distpath", dist, "--workpath", BUILD / "work", "--specpath", BUILD, APP / "webinar.py"], cwd=APP)
    return dist / NAME


def stage(app_dir: Path) -> None:
    """Рядом с exe — медиа, шаблоны, данные и ярлык."""
    for name in ("media", "templates"):
        # без атрибутов исходника: «только чтение» мешал бы пересборке и распаковке поверх
        shutil.copytree(APP / name, app_dir / name, dirs_exist_ok=True, copy_function=shutil.copyfile)
    data = app_dir / "data"
    data.mkdir(exist_ok=True)
    if (APP / "data" / "plans.json").is_file():
        shutil.copy2(APP / "data" / "plans.json", data / "plans.json")
    settings_file = APP / "data" / "settings.json"
    if settings_file.is_file():
        s = json.loads(settings_file.read_text(encoding="utf-8-sig"))
        s.update({k: v for k, v in MACHINE_SETTINGS.items() if k in s})
        (data / "settings.json").write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    # cmd читает .bat в кодировке консоли (cp866) — так русские сообщения видны без chcp
    (app_dir / "Создать ярлык на рабочем столе.bat").write_bytes(
        SHORTCUT_BAT.replace("\n", "\r\n").encode("cp866"))


def pack(app_dir: Path) -> Path:
    seven = find_7z()
    sfx = seven.parent / "7z.sfx"
    if not sfx.is_file():
        raise SystemExit(f"Нет модуля самораспаковки {sfx}")
    OUT.mkdir(exist_ok=True)
    exe = OUT / f"{NAME} {version()}.exe"
    with tempfile.TemporaryDirectory(prefix="webinar-dist-") as tmp:
        archive = Path(tmp) / "app.7z"
        # видео уже сжато — сильное сжатие не поможет, только замедлит
        run([seven, "a", "-t7z", "-mx=5", "-bso0", "-bsp0", archive, app_dir.name], cwd=app_dir.parent)
        with open(Path(tmp) / "out.exe", "wb") as out:
            for part in (sfx, archive):
                with open(part, "rb") as f:
                    shutil.copyfileobj(f, out)
        shutil.move(Path(tmp) / "out.exe", exe)        # временная папка может быть на другом диске
    return exe


def main() -> None:
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    print("1/4 Окружение сборки")
    py = venv_python()
    print("2/4 Сборка exe (PyInstaller)")
    app_dir = build_exe(py)
    print("3/4 Медиа, шаблоны, данные, ярлык")
    stage(app_dir)
    print("4/4 Самораспаковывающийся архив")
    exe = pack(app_dir)
    files = sum(1 for p in app_dir.rglob("*") if p.is_file())
    print(f"Готово: {exe} ({exe.stat().st_size / 2**20:.0f} МБ, файлов внутри: {files})")


if __name__ == "__main__":
    main()
