"""Что печатать из блока кода — без Qt (общие правила для программы и эталонов веб-версии)."""
from __future__ import annotations


def typing_slice(text: str, sel: list[int], whole_lines: bool) -> tuple[str, int]:
    """Что печатать: выделение (расширенное до целых строк) или весь блок. → (текст, смещение)."""
    if len(sel) != 2 or sel[1] <= sel[0]:
        return text, 0
    a, b = max(0, sel[0]), min(len(text), sel[1])
    if whole_lines:
        a = text.rfind("\n", 0, a) + 1
        if b > a and text[b - 1] == "\n":
            b -= 1
        nl = text.find("\n", b)
        b = len(text) if nl < 0 else nl
    return text[a:b], a
