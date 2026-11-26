"""Все автоматические проверки перед выпуском — одной командой.

    python tools/check.py          — тесты Python, эталоны, типы и тесты веб-версии
    python tools/check.py --ui     — плюс сквозной тест страницы в Chrome/Edge без окна (npm run test:ui)

Печать в настоящие окна сюда не входит — она захватывает клавиатуру и фокус. Её запускают вручную,
ничего не трогая во время прогона: python tests/run_editors.py и node web/tests/e2e-editors.ts tk notepad.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
NPM = "npm.cmd" if os.name == "nt" else "npm"
# тихие тесты-сценарии: окна — только в памяти, без трея, уведомлений и настоящих нажатий
SCRIPT_TESTS = ["test_steps", "test_engine", "test_human", "test_lesson_ai", "test_report", "test_sounds", "test_v10", "test_v11", "test_v12",
                "test_v121", "test_updater", "test_efir", "test_lesson", "test_v09",
                "test_app_shell", "test_app_core", "test_app_page", "test_app_library", "test_app_lesson", "test_app_edit", "test_app_sheets", "test_wizard_core", "test_app_wizard", "test_app_compact", "test_media_copy", "test_app_efir", "test_app_settings", "test_record_flow", "test_thumbs"]


def run(title: str, cmd: list[str], cwd: Path = ROOT) -> bool:
    print(f"\n=== {title}", flush=True)
    t = time.time()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "QT_QPA_PLATFORM": "offscreen"}
    ok = subprocess.run(cmd, cwd=cwd, env=env).returncode == 0
    print(f"--- {'OK' if ok else 'ОШИБКА'} ({time.time() - t:.0f} с)", flush=True)
    return ok


def main() -> int:
    if not sys.stdout.isatty():   # вывод в файл или конвейер — UTF-8, как у вложенных команд
        sys.stdout.reconfigure(encoding="utf-8")
    py = sys.executable
    steps = [
        ("Python: тесты ядра и интерфейса (unittest)", [py, "-m", "unittest", "tests.test_core"], ROOT),
        # остальные тесты — сценарии со своим main(): каждый в своём процессе (свои заглушки и папка данных)
        *[(f"Python: {name}", [py, f"tests/{name}.py"], ROOT) for name in SCRIPT_TESTS],
        ("Окно программы (Electron): места окна на экране", ["node", "--test", "window/tests/geometry.test.js"], ROOT),
        ("Эталоны веб-версии совпадают с Python", [sys.executable, "tools/make_web_fixtures.py", "--check"], ROOT),
        ("Веб: типы", [NPM, "run", "typecheck"], WEB),
        ("Веб: тесты (паритет с Python, движок, текстовые блоки)", [NPM, "test"], WEB),
    ]
    if "--ui" in sys.argv:
        steps.append(("Веб: сквозной тест страницы", [NPM, "run", "test:ui"], WEB))
    failed = [title for title, cmd, cwd in steps if not run(title, cmd, cwd)]
    print("\nИтог:", "всё в порядке." if not failed else "не прошло — " + "; ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
