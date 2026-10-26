"""Дистрибутив AutoPrintCode Веб: мастер установки в INSTALL/ и установщик обновления.

    python tools/build_autoprint_web_dist.py

Node.js у пользователя не нужен: внутри — своя копия node.exe той же версии, на которой проходят тесты (берётся
с nodejs.org, кэшируется в build/autoprint-web/cache). В папке приложения: server/, shared/, собранная страница
dist/, библиотеки для работы (npm ci --omit=dev), node/node.exe и значок. Inno Setup (tools/autoprint_web_setup.iss):
  INSTALL/Установка — AutoPrintCode Веб <версия>.exe   — для первой установки;
  build/autoprint-web/autoprintcode-web-update-<версия>.exe — для обновления: приложить к релизу GitHub с тегом
      v<версия> (общий с настольной AutoPrintCode); помощник найдёт его сам и покажет «Доступна версия…».
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_webinar_dist as common  # noqa: E402 — Inno Setup, окружение для значка, вспомогательное

ROOT = common.ROOT
WEB = ROOT / "web"
BUILD = ROOT / "build" / "autoprint-web"
APP = BUILD / "app"
OUT = common.OUT
ISS = ROOT / "tools" / "autoprint_web_setup.iss"
NPM = "npm.cmd"


def version() -> str:
    return json.loads((WEB / "package.json").read_text(encoding="utf-8"))["version"]


def node_exe() -> Path:
    """node.exe той же версии, что у сборщика (на ней прошли тесты) — из официального архива nodejs.org."""
    ver = subprocess.run(["node", "--version"], capture_output=True, text=True, check=True).stdout.strip()
    cache = BUILD / "cache"
    exe = cache / f"node-{ver}-win-x64.exe"
    if not exe.exists():
        cache.mkdir(parents=True, exist_ok=True)
        z = cache / f"node-{ver}-win-x64.zip"
        url = f"https://nodejs.org/dist/{ver}/node-{ver}-win-x64.zip"
        print(f"  > скачиваю {url}")
        urllib.request.urlretrieve(url, z)
        with zipfile.ZipFile(z) as zf, zf.open(f"node-{ver}-win-x64/node.exe") as src, open(exe, "wb") as dst:
            shutil.copyfileobj(src, dst)
        z.unlink()
    return exe


def make_icon(py: Path, ico: Path) -> None:
    png = WEB / "client" / "public" / "icons" / "icon-512.png"
    common.run([py, "-c", "import sys; from PySide6.QtGui import QGuiApplication, QImage; app = QGuiApplication([]);"
                f"img = QImage(r'{png}').scaled(256, 256);"
                f"sys.exit(0 if img.save(r'{ico}', 'ICO') else 1)"],
               env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})


def stage(py: Path) -> None:
    """Папка приложения build/autoprint-web/app — то, что ставится пользователю."""
    common._rmtree(APP)
    APP.mkdir(parents=True)
    for d in ("server", "shared", "dist"):
        shutil.copytree(WEB / d, APP / d, copy_function=shutil.copyfile)
    for f in ("package.json", "package-lock.json"):
        shutil.copyfile(WEB / f, APP / f)
    common.run([NPM, "ci", "--omit=dev", "--no-audit", "--no-fund", "--loglevel=error"], cwd=APP)
    (APP / "node").mkdir()
    shutil.copyfile(node_exe(), APP / "node" / "node.exe")
    make_icon(py, APP / "autoprintcode-web.ico")


def pack(update: bool = False) -> Path:
    ver = version()
    out = BUILD if update else OUT
    common.run([common.find_iscc(), "/Q", f"/DAppVersion={ver}", f"/DSourceDir={APP}", f"/DOutDir={out}",
                f"/DIcon={APP / 'autoprintcode-web.ico'}", *(["/DUpdate=1"] if update else []), ISS])
    return out / (f"autoprintcode-web-update-{ver}.exe" if update else f"Установка — AutoPrintCode Веб {ver}.exe")


def main() -> None:
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    print("1/4 Тесты и сборка страницы")
    common.run([NPM, "test", "--silent"], cwd=WEB)
    common.run([NPM, "run", "build", "--silent"], cwd=WEB)
    print("2/4 Папка приложения: сервер, страница, библиотеки, Node.js")
    py = common.venv_python()
    stage(py)
    print("3/4 Проверка: помощник запускается своей копией Node")
    check = subprocess.run([str(APP / "node" / "node.exe"), "-e", "import('./server/update.ts').then(() => console.log('ok'))"],
                           cwd=APP, capture_output=True, text=True)
    if check.stdout.strip() != "ok":
        raise SystemExit(f"Своя копия Node не запускает сервер: {check.stderr.strip()}")
    print("4/4 Мастер установки и установщик обновления (Inno Setup)")
    OUT.mkdir(exist_ok=True)
    exe, upd = pack(), pack(update=True)
    print(f"Готово: {exe} ({exe.stat().st_size / 2**20:.0f} МБ)")
    print(f"Обновление: {upd} ({upd.stat().st_size / 2**20:.0f} МБ) — приложить к релизу GitHub с тегом v{version()}")


if __name__ == "__main__":
    main()
