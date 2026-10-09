"""Эталоны для тестов веб-версии: результаты Python-модулей на тех же входных данных.

Веб-версия — порт autoprint/*.py; тесты web/tests/*.test.ts сравнивают её с эталонами
в web/tests/fixtures/. Входные данные (тексты, настройки, выделения) хранятся в самих
файлах эталонов, скрипт пересчитывает только результаты.

    python tools/make_web_fixtures.py          — пересчитать эталоны
    python tools/make_web_fixtures.py --check  — только проверить, что эталоны актуальны (код 1 — нет)

Новый случай: добавьте вход в нужный файл эталона (результат — любой) и запустите без --check.
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoprint.comments import strip_comments  # noqa: E402
from autoprint.storage import Settings  # noqa: E402
from autoprint.textprint import find_selection, printable, selection_text  # noqa: E402
from autoprint.typer import build_units  # noqa: E402
from autoprint.ui.blocks import typing_slice  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "web" / "tests" / "fixtures"


def python_reference(d: dict) -> dict:
    for c in d["units"]:
        s = replace(Settings(), **c["settings"])
        c["units"] = [[u.kind, u.text, u.src_end] for u in build_units(c["text"], s)]
    for c in d["strip"]:
        c["out"], c["map"] = strip_comments(c["text"], c["lang"])
    for c in d["slices"]:
        c["out"] = list(typing_slice(c["text"], c["sel"], c["whole"]))
    return d


def textprint_reference(cases: list) -> list:
    for c in cases:
        c["out"] = printable(c["text"], c["mode"], c["lang"])
    return cases


def textselect_reference(d: dict) -> dict:
    src = d["source"]
    for c in d["cases"]:
        c["sel"] = find_selection(src, c["selected"], c["hint"])
        c["out"] = {}
        if c["sel"]:
            part, base = typing_slice(src, c["sel"], True)
            for mode in ("markdown", "plain", "comment"):
                c["out"][mode] = selection_text(src, part, base, mode, "javascript")
    return d


BUILDERS = {
    "python-reference.json": python_reference,
    "textprint-reference.json": textprint_reference,
    "textselect-reference.json": textselect_reference,
}


def main() -> int:
    check = "--check" in sys.argv
    stale = []
    for name, build in BUILDERS.items():
        path = FIXTURES / name
        old = json.loads(path.read_text(encoding="utf-8"))
        new = build(json.loads(json.dumps(old)))
        if new == old:
            continue
        stale.append(name)
        if not check:
            path.write_text(json.dumps(new, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if stale:
        print(("Устарели: " if check else "Обновлены: ") + ", ".join(stale))
    else:
        print("Эталоны актуальны.")
    return 1 if check and stale else 0


if __name__ == "__main__":
    sys.exit(main())
