"""Правки урока с экрана урока: действия над блоками (без Qt).

apply(t, ops) применяет все действия или ни одного: сначала — на копии блоков (проверка), при ошибке
ValueError урок не меняется. Действия, которые повторяет страница после обрыва связи (вставка с её id,
удаление уже удалённого), повторно ничего не меняют.

    {"op": "set", "block": id, "fields": {...}}          поля блока (по его типу)
    {"op": "insert", "after": id | "", "block": {...}}    новый блок (id придумывает страница) после after
    {"op": "delete", "block": id}
    {"op": "move", "block": id, "after": id | ""}
    {"op": "move_stage", "stage": id, "after_stage": id | ""}   этап со своими блоками
    {"op": "restore", "block": {...все поля...}, "after": id | ""}   «Вернуть» удалённое
    {"op": "set_lesson", "title": "…"}
"""
from __future__ import annotations

import copy
import re

from .storage import (BLOCK_CODE, BLOCK_IMAGE, BLOCK_MARKDOWN, BLOCK_STAGE, PROFILES, ROLES, STAGE_KINDS, Block,
                      Template, _block_from, is_printable)

TYPES = (BLOCK_MARKDOWN, BLOCK_CODE, BLOCK_STAGE, BLOCK_IMAGE)
MAX_TEXT = 200_000
MAX_MINUTES = 600
_ID = re.compile(r"[0-9A-Za-z_-]{1,40}")   # страница придумывает 12 hex; у старых блоков бывают другие
_LANG = re.compile(r"[\w+#.-]{1,30}")
# какие поля можно менять у блока какого типа
_FIELDS = {
    BLOCK_MARKDOWN: {"text", "title", "role"},
    BLOCK_CODE: {"text", "title", "lang", "profile", "steps", "sel"},
    BLOCK_STAGE: {"text", "title", "minutes", "stage_kind", "part", "exercise"},
    BLOCK_IMAGE: {"text", "title", "slide"},
}


def _str(v, name: str, limit: int = MAX_TEXT) -> str:
    if not isinstance(v, str):
        raise ValueError(f"{name}: нужен текст")
    if len(v) > limit:
        raise ValueError(f"{name}: слишком длинный текст")
    return v.replace("\r\n", "\n").replace("\r", "\n")


def _field(b: Block, key: str, v):
    """Проверенное значение поля key для блока b (ValueError — нельзя)."""
    if key not in _FIELDS.get(b.type, ()):
        raise ValueError(f"У блока «{b.type}» нет поля {key}")
    if key == "text":
        return _str(v, "text")
    if key in ("title", "part"):
        return _str(v, key, 300)
    if key == "exercise":                       # название видео зарядки из оформления
        return _str(v, key, 200)
    if key == "role":
        if v not in ROLES:
            raise ValueError(f"Нет роли {v!r}")
        return v
    if key == "lang":
        if not isinstance(v, str) or not _LANG.fullmatch(v):
            raise ValueError("Неверный язык")
        return v.lower()
    if key == "profile":
        if v not in PROFILES and v != "":
            raise ValueError("Неверное окно")
        return v
    if key == "slide":
        if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 9999:
            raise ValueError("Неверный номер слайда")
        return v
    if key == "steps":
        if not isinstance(v, list) or len(v) > 10_000 or not all(isinstance(x, int) and 1 <= x <= 99 for x in v):
            raise ValueError("Неверные шаги")
        return list(v)
    if key == "sel":
        if v in ([], None):
            return []
        if (not isinstance(v, list) or len(v) != 2 or not all(isinstance(x, int) and x >= 0 for x in v)
                or v[0] > v[1]):
            raise ValueError("Неверное выделение")
        return list(v)
    if key == "minutes":
        if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= MAX_MINUTES:
            raise ValueError(f"Минуты этапа — от 0 до {MAX_MINUTES}")
        return v
    if key == "stage_kind":
        if v not in STAGE_KINDS:
            raise ValueError("Неверный вид этапа")
        return v
    raise ValueError(f"Поле {key} не меняется")


def _index(blocks: list[Block], bid: str) -> int:
    return next((i for i, b in enumerate(blocks) if b.id == bid), -1)


def _after_index(blocks: list[Block], after: str) -> int:
    """Куда вставить «после after»: "" — в начало; неизвестный блок — ошибка."""
    if not after:
        return 0
    i = _index(blocks, after)
    if i < 0:
        raise ValueError("Блок, после которого вставлять, не найден")
    return i + 1


def _new_block(d) -> Block:
    if not isinstance(d, dict):
        raise ValueError("Нет блока")
    bid = d.get("id")
    if not isinstance(bid, str) or not _ID.fullmatch(bid):
        raise ValueError("Неверный id блока")
    if d.get("type") not in TYPES:
        raise ValueError("Неверный тип блока")
    b = _block_from({k: v for k, v in d.items() if k in Block.__dataclass_fields__})
    # поля, которые задаёт страница, — с той же проверкой, что и при правке
    for key in ("text", "title", "role", "lang", "profile", "minutes", "stage_kind", "part", "steps", "sel", "slide",
                "exercise"):
        if key in d and key in _FIELDS[b.type]:
            setattr(b, key, _field(b, key, d[key]))
    if b.type == BLOCK_MARKDOWN and b.role not in ROLES:
        b.role = "say"
    if b.type == BLOCK_STAGE and "minutes" not in d:
        b.minutes = 5
    return b


def _group_end(blocks: list[Block], i: int) -> int:
    """Конец группы этапа, начинающегося с i: до следующего этапа (не включая)."""
    j = i + 1
    while j < len(blocks) and blocks[j].type != BLOCK_STAGE:
        j += 1
    return j


def _apply_one(t: Template, blocks: list[Block], op: dict, touched: list[str]) -> None:
    if not isinstance(op, dict):
        raise ValueError("Неверное действие")
    kind = op.get("op")
    if kind == "set":
        i = _index(blocks, str(op.get("block") or ""))
        if i < 0:
            raise ValueError("Блок не найден")
        fields = op.get("fields")
        if not isinstance(fields, dict) or not fields:
            raise ValueError("Нет полей")
        b = blocks[i]
        new = {k: _field(b, k, v) for k, v in fields.items()}
        for k, v in new.items():
            setattr(b, k, v)
        if "text" in new and b.type == BLOCK_CODE and b.sel and b.sel[1] > len(b.text):
            b.sel = []                       # выделение было в прежнем тексте
        touched.append(b.id)
    elif kind in ("insert", "restore"):
        b = _new_block(op.get("block"))
        if _index(blocks, b.id) >= 0:
            return                           # повтор после обрыва связи
        blocks.insert(_after_index(blocks, str(op.get("after") or "")), b)
        touched.append(b.id)
    elif kind == "delete":
        bid = str(op.get("block") or "")
        i = _index(blocks, bid)
        if i >= 0:
            del blocks[i]
        touched.append(bid)
    elif kind == "move":
        bid, after = str(op.get("block") or ""), str(op.get("after") or "")
        i = _index(blocks, bid)
        if i < 0 or bid == after:
            return
        b = blocks.pop(i)
        blocks.insert(_after_index(blocks, after), b)
        touched.append(bid)
    elif kind == "move_stage":
        sid, after = str(op.get("stage") or ""), str(op.get("after_stage") or "")
        i = _index(blocks, sid)
        if i < 0 or blocks[i].type != BLOCK_STAGE or sid == after:
            return
        group = blocks[i:_group_end(blocks, i)]
        del blocks[i:i + len(group)]
        if after:
            k = _index(blocks, after)
            if k < 0 or blocks[k].type != BLOCK_STAGE:
                raise ValueError("Этап, после которого переносить, не найден")
            at = _group_end(blocks, k)
        else:
            at = next((k for k, b in enumerate(blocks) if b.type == BLOCK_STAGE), len(blocks))
        blocks[at:at] = group
        touched.extend(b.id for b in group)
    elif kind == "set_lesson":
        title = _str(op.get("title"), "title", 300).strip()
        if not title:
            raise ValueError("Пустое название урока")
        t.title = title
    else:
        raise ValueError(f"Неизвестное действие {kind!r}")


def _keep_pointer(t: Template, old: list[Block]) -> None:
    """Удалили код, который печатается следующим, — следующим становится код после него (или никакой):
    иначе Ctrl+F9 сказал бы «весь код напечатан», хотя впереди ещё код."""
    alive = {b.id: b for b in t.blocks}
    if not t.active_block or t.active_block in alive:
        return
    ids = [b.id for b in old]
    i = ids.index(t.active_block) + 1 if t.active_block in ids else len(ids)
    nxt = next((alive[b.id] for b in old[i:] if b.id in alive and is_printable(alive[b.id])), None)
    t.active_block = nxt.id if nxt is not None else ""


def _touches_stage(blocks: list[Block], op) -> bool:
    """Действие меняет этапы: их поля, состав или порядок."""
    if not isinstance(op, dict):
        return False
    kind = op.get("op")
    if kind == "move_stage":
        return True
    if kind in ("insert", "restore"):
        return isinstance(op.get("block"), dict) and op["block"].get("type") == BLOCK_STAGE
    if kind in ("set", "delete"):
        i = _index(blocks, str(op.get("block") or ""))
        return i >= 0 and blocks[i].type == BLOCK_STAGE
    return False


def apply(t: Template, ops: list, fixed_stages: str = "", keep_one_stage: bool = False) -> list[str]:
    """Применить действия к уроку — все или ни одного. → id затронутых блоков (удалённые тоже).
    fixed_stages — название плана урока: этапы задаёт план, их правка — ValueError. keep_one_stage — это план:
    последний этап не удаляется."""
    if not isinstance(ops, list):
        raise ValueError("Нет списка действий")
    title = t.title
    old = list(t.blocks)
    blocks = copy.deepcopy(t.blocks)
    touched: list[str] = []
    try:
        for op in ops:
            if fixed_stages and _touches_stage(blocks, op):
                raise ValueError(f"Этапы этого урока задаёт план «{fixed_stages}» — меняйте их в плане")
            _apply_one(t, blocks, op, touched)
        if keep_one_stage and any(b.type == BLOCK_STAGE for b in old) and not any(b.type == BLOCK_STAGE for b in blocks):
            raise ValueError("В плане должен остаться хотя бы один этап")
    except ValueError:
        t.title = title
        raise
    t.blocks[:] = blocks
    _keep_pointer(t, old)
    seen: set[str] = set()
    return [x for x in touched if not (x in seen or seen.add(x))]
