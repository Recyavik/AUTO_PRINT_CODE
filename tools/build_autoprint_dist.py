"""Дистрибутив AutoPrintCode (настольная версия): мастер установки в INSTALL/ и установщик обновления.

    python tools/build_autoprint_dist.py

Python у пользователя не нужен: PyInstaller собирает «AutoPrintCode.exe» вместе с Python, PySide6 и Pygments;
звуки клавиш и значки интерфейса — внутри. Inno Setup (tools/autoprint_setup.iss) делает:
  INSTALL/Установка — AutoPrintCode <версия>.exe   — для первой установки;
  build/autoprint/autoprintcode-update-<версия>.exe — для обновления: приложить к релизу GitHub с тегом v<версия>,
      установленная программа найдёт его сама (Справка → Проверить обновления).
Папки data/ в установщике нет: обновление не трогает образцы и настройки. Окружение сборки и проверки — общее
с «Таймером вебинара» (tools/build_webinar_dist.py): тесты прогоняются на тех же версиях, что войдут в exe.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_webinar_dist as common  # noqa: E402 — окружение сборки, PyInstaller, Inno Setup, тесты

ROOT = common.ROOT
BUILD = ROOT / "build" / "autoprint"
OUT = common.OUT
NAME = "AutoPrintCode"
ISS = ROOT / "tools" / "autoprint_setup.iss"


def version() -> str:
    for line in (ROOT / "autoprint" / "__init__.py").read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("Не найдена версия в autoprint/__init__.py")


def build_exe(py: Path) -> Path:
    """«AutoPrintCode.exe» с папкой _internal — в build/autoprint/dist/."""
    BUILD.mkdir(parents=True, exist_ok=True)
    ico = BUILD / "autoprintcode.ico"
    common.run([py, "-c", "import sys; from pathlib import Path; sys.path.insert(0, '.');"
                "from PySide6.QtWidgets import QApplication; app = QApplication([]);"
                "from autoprint.typer import IDLE; from autoprint.ui.main_window import STATE_COLORS, save_ico;"
                f"sys.exit(0 if save_ico(STATE_COLORS[IDLE], Path(r'{ico}')) else 1)"],
               cwd=ROOT, env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    dist = BUILD / "dist"
    common._rmtree(dist / NAME)
    common.run([py, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", NAME, "--icon", ico,
                "--add-data", f"{ROOT / 'autoprint' / 'sounds'};autoprint/sounds",
                "--add-data", f"{ROOT / 'autoprint' / 'ui' / '*.svg'};autoprint/ui",
                "--collect-submodules", "pygments.lexers", "--collect-submodules", "pygments.formatters",
                "--distpath", dist, "--workpath", BUILD / "work", "--specpath", BUILD, ROOT / "app.py"], cwd=ROOT)
    return dist / NAME


def pack(app_dir: Path, update: bool = False) -> Path:
    ver = version()
    out = BUILD if update else OUT
    common.run([common.find_iscc(), "/Q", f"/DAppVersion={ver}", f"/DSourceDir={app_dir}", f"/DOutDir={out}",
                f"/DIcon={BUILD / 'autoprintcode.ico'}", *(["/DUpdate=1"] if update else []), ISS])
    return out / (f"autoprintcode-update-{ver}.exe" if update else f"Установка — {NAME} {ver}.exe")


def main() -> None:
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    print("1/4 Окружение сборки")
    py = common.venv_python()
    common.run([py, "-m", "pip", "install", "-q", "--disable-pip-version-check", "-r", ROOT / "requirements.txt"])
    print("2/4 Тесты — на тех же версиях Python и PySide6, что войдут в exe")
    common.run_tests(py, ROOT / "tests")
    print("3/4 Сборка exe (PyInstaller)")
    app_dir = build_exe(py)
    print("4/4 Мастер установки и установщик обновления (Inno Setup)")
    OUT.mkdir(exist_ok=True)
    exe, upd = pack(app_dir), pack(app_dir, update=True)
    print(f"Готово: {exe} ({exe.stat().st_size / 2**20:.0f} МБ)")
    print(f"Обновление: {upd} ({upd.stat().st_size / 2**20:.0f} МБ) — приложить к релизу GitHub с тегом v{version()}")


if __name__ == "__main__":
    main()
