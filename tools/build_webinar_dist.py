"""Дистрибутив «Таймера вебинара» для коллег: мастер установки в INSTALL/.

    python tools/build_webinar_dist.py                              — собрать
    python tools/build_webinar_dist.py --publish --notes "Что нового"  — собрать и выложить обновление на GitHub

Python на компьютере коллеги не нужен: PyInstaller собирает «Таймер вебинара.exe» вместе с Python и PySide6
(окна, видео, звук). Рядом с exe — media/ (фон, видео гимнастики, шрифт) и templates/ (шаблоны для первого
запуска). Inno Setup (tools/webinar_setup.iss) делает из этого мастер установки «Установка — Таймер вебинара
<версия>.exe»: папка, ярлыки в «Пуске» и на рабочем столе, удаление через «Программы и компоненты», без прав
администратора. Папки data/ в установщике нет: обновление поверх не трогает шаблоны и настройки пользователя.
Шаблоны лежат и отдельными файлами в INSTALL/ — для «Импорт JSON» у тех, у кого таймер уже установлен.

Обновления: собирается и лёгкий установщик build/webinar/webinar-timer-update-<версия>.exe (без видео, фона и
шрифта — они у пользователя уже стоят). --publish выкладывает его на GitHub как Release «webinar-v<версия>»;
таймер находит его в ⚙ Настройки → «Обновления» (или сам, если включена автопроверка) и ставит по кнопке.
Нужен GitHub CLI с входом в аккаунт (gh auth login); всё должно быть закоммичено и отправлено.

Для сборки нужны Python 3.10–3.13 (обычный, не «t» без GIL) и Inno Setup 6 (winget install JRSoftware.InnoSetup).
Окружение сборки (PySide6, PyInstaller) создаётся само в build/webinar/venv и переиспользуется. Перед сборкой
в нём прогоняются тесты таймера: версии PySide6 различаются поведением (в 6.12 иначе сжимается поле-счётчик),
проверяем именно то, что войдёт в exe.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "webinar_timer"
BUILD = ROOT / "build" / "webinar"
VENV = BUILD / "venv"
OUT = ROOT / "INSTALL"
NAME = "Таймер вебинара"
ISS = ROOT / "tools" / "webinar_setup.iss"
REPO = "Recyavik/AUTO_PRINT_CODE"

# Тесты в окружении сборки. Итог — сразу, без выгрузки Qt: после десятков окон тестов PySide6 6.12 падает
# или зависает при выходе из Python (сам таймер закрывается чисто, и с видео тоже — проверено).
TEST_RUNNER = """
import ctypes, sys, unittest
r = unittest.main(module=None, exit=False, argv=["t", "discover", "-s", sys.argv[1], "-p", "test_*.py"])
sys.stdout.flush(); sys.stderr.flush()
k = ctypes.windll.kernel32
k.TerminateProcess(k.GetCurrentProcess(), 0 if r.result.wasSuccessful() else 1)
"""


def run(cmd: list, **kw) -> None:
    print("  >", " ".join(str(c) for c in cmd[:4]), "…" if len(cmd) > 4 else "")
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def run_tests(py: Path) -> None:
    """Тесты таймера в окружении сборки. Итог — по их собственному выводу («Ran N tests … OK»): процесс Python
    с PySide6 6.12 иногда падает уже после итога, при выгрузке Qt, — это не провал тестов."""
    r = subprocess.run([str(py), "-c", TEST_RUNNER, str(APP / "tests")], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    lines = (r.stdout + r.stderr).rstrip().splitlines()
    for line in lines[-4:]:
        print("   ", line)
    last = lines[-1] if lines else ""
    if r.returncode != 0 and not (last == "OK" or last.startswith("OK (")):
        for line in lines:
            print("   ", line)
        raise SystemExit("Тесты не прошли — дистрибутив не собран")


def find_iscc() -> Path:
    for p in (shutil.which("ISCC"), Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Inno Setup 6/ISCC.exe",
              r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe", r"C:\Program Files\Inno Setup 6\ISCC.exe"):
        if p and Path(p).is_file():
            return Path(p)
    raise SystemExit("Не найден Inno Setup 6 (ISCC.exe) — winget install JRSoftware.InnoSetup")


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


def ordered_templates() -> list[Path]:
    """Экспорты из templates/ — в том же порядке, что в списке шаблонов у автора (остальные — по алфавиту)."""
    order = {}
    try:
        mine = json.loads((APP / "data" / "plans.json").read_text(encoding="utf-8-sig"))["plans"]
        order = {p.get("id"): i for i, p in enumerate(mine)}
    except (OSError, ValueError, KeyError, TypeError):
        pass

    def key(f: Path) -> tuple:
        pid = json.loads(f.read_text(encoding="utf-8-sig")).get("id")
        return order.get(pid, len(order)), f.name
    return sorted((APP / "templates").glob("*.json"), key=key)


def stage(app_dir: Path) -> None:
    """Рядом с exe — медиа и шаблоны. Папки data нет: обновление поверх не трогает данные пользователя
    (его шаблоны, настройки, журнал). Шаблоны — в templates/ (новая установка берёт их при первом запуске)
    и отдельными файлами в INSTALL/ — для «Импорт JSON» у тех, у кого таймер уже стоит."""
    # без атрибутов исходника: «только чтение» мешал бы пересборке и обновлению
    shutil.copytree(APP / "media", app_dir / "media", dirs_exist_ok=True, copy_function=shutil.copyfile)
    templates = app_dir / "templates"
    templates.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    for n, f in enumerate(ordered_templates(), 1):
        shutil.copyfile(f, templates / f"{n}. {f.name}")    # номер — порядок в списке при первом запуске
        shutil.copyfile(f, OUT / f.name)


def pack(app_dir: Path, update: bool = False) -> Path:
    """Мастер установки (Inno Setup) из папки с exe: полный — в INSTALL/, лёгкий для обновлений — в build/webinar/."""
    ver = version()
    out = BUILD if update else OUT
    run([find_iscc(), "/Q", f"/DAppVersion={ver}", f"/DSourceDir={app_dir}", f"/DOutDir={out}",
         f"/DIcon={APP / 'webinar.ico'}", *(["/DUpdate=1"] if update else []), ISS])
    return out / (f"webinar-timer-update-{ver}.exe" if update else f"Установка — {NAME} {ver}.exe")


def find_gh() -> Path:
    for p in (shutil.which("gh"), r"C:\Program Files\GitHub CLI\gh.exe"):
        if p and Path(p).is_file():
            return Path(p)
    raise SystemExit("Не найден GitHub CLI — winget install GitHub.cli, затем gh auth login")


def publish(asset: Path, notes: str) -> None:
    """Release «webinar-v<версия>» с лёгким установщиком — его найдут таймеры у пользователей."""
    gh, ver = find_gh(), version()
    tag = f"webinar-v{ver}"
    if subprocess.run([str(gh), "auth", "status"], capture_output=True).returncode != 0:
        raise SystemExit("Сначала войдите в GitHub: gh auth login")
    if subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
                      capture_output=True, text=True).stdout.strip():
        raise SystemExit("Есть незакоммиченные изменения — сначала коммит и push, потом публикация")
    if subprocess.run([str(gh), "release", "view", tag, "-R", REPO], capture_output=True).returncode == 0:
        raise SystemExit(f"Release {tag} уже есть — поднимите версию в webinar_timer/webinar/__init__.py")
    run([gh, "release", "create", tag, asset, "-R", REPO, "--target", "main",
         "--title", f"{NAME} {ver}", "--notes", notes or f"Обновление: {NAME} {ver}"])
    print(f"Опубликовано: https://github.com/{REPO}/releases/tag/{tag}")


def main() -> None:
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Дистрибутив «Таймера вебинара»")
    ap.add_argument("--publish", action="store_true", help="выложить обновление на GitHub (Release webinar-v<версия>)")
    ap.add_argument("--notes", default="", help="что нового — текст для Release и окна обновления")
    args = ap.parse_args()
    print("1/5 Окружение сборки")
    py = venv_python()
    print("2/5 Тесты — на тех же версиях Python и PySide6, что войдут в exe")
    run_tests(py)
    print("3/5 Сборка exe (PyInstaller)")
    app_dir = build_exe(py)
    print("4/5 Медиа и шаблоны")
    stage(app_dir)
    print("5/5 Мастер установки (Inno Setup): полный и лёгкий для обновлений")
    exe = pack(app_dir)
    upd = pack(app_dir, update=True)
    files = sum(1 for p in app_dir.rglob("*") if p.is_file())
    print(f"Готово: {exe} ({exe.stat().st_size / 2**20:.0f} МБ, файлов внутри: {files})")
    print(f"Обновление: {upd} ({upd.stat().st_size / 2**20:.0f} МБ)")
    if args.publish:
        publish(upd, args.notes)


if __name__ == "__main__":
    main()
