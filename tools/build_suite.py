"""Общий мастер «1Т — установка инструментов»: галочки «Таймер вебинара», AutoPrintCode, AutoPrintCode Веб.

    python tools/build_suite.py          — собрать мастер из готовых установщиков в INSTALL/
    python tools/build_suite.py --all    — сначала собрать все три приложения, потом мастер

Внутри мастера — полные установщики приложений (последние версии из INSTALL/); он ставит отмеченные тихо, по очереди.
Каждое приложение ставится, обновляется и удаляется само (своя запись в «Приложениях»); мастер не регистрируется.
Результат: INSTALL/Установка — инструменты 1Т <дата>.exe.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_webinar_dist as common  # noqa: E402

ROOT = common.ROOT
OUT = common.OUT
ISS = ROOT / "tools" / "suite_setup.iss"
TOOLS = ROOT / "tools"


def latest(prefix: str) -> Path:
    """Самый новый установщик «<prefix> <версия>.exe» в INSTALL/."""
    found = []
    for f in OUT.glob(f"{prefix} *.exe"):
        m = re.fullmatch(re.escape(prefix) + r" (\d+(?:\.\d+)*)\.exe", f.name)
        if m:
            found.append((tuple(int(x) for x in m.group(1).split(".")), f))
    if not found:
        raise SystemExit(f"Нет установщика «{prefix} <версия>.exe» в {OUT} — соберите его (или запустите с --all)")
    return max(found)[1]


def main() -> None:
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    if "--all" in sys.argv:
        for script in ("build_webinar_dist.py", "build_autoprint_dist.py", "build_autoprint_web_dist.py"):
            print(f"=== {script}")
            subprocess.run([sys.executable, str(TOOLS / script)], check=True)
    timer = latest("Установка — Таймер вебинара")
    autoprint = latest("Установка — AutoPrintCode")
    web = latest("Установка — AutoPrintCode Веб")
    for f in (timer, autoprint, web):
        print(f"  внутри: {f.name}")
    ver = time.strftime("%Y.%m.%d")
    ico = ROOT / "build" / "autoprint" / "autoprintcode.ico"
    common.run([common.find_iscc(), "/Q", f"/DSuiteVersion={ver}", f"/DTimerSetup={timer}",
                f"/DAutoprintSetup={autoprint}", f"/DWebSetup={web}", f"/DOutDir={OUT}", f"/DIcon={ico}", ISS])
    exe = OUT / f"Установка — инструменты 1Т {ver}.exe"
    print(f"Готово: {exe} ({exe.stat().st_size / 2**20:.0f} МБ)")


if __name__ == "__main__":
    main()
