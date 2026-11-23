"""Суфлёр урока: урок по этапам — план с минутами, блоки этапов, HTML для страницы суфлёра.

Урок — обычное занятие AutoPrintCode (ленту блоков), в котором есть блоки-«Этапы». Блоки после этапа
принадлежат ему до следующего этапа; блоки до первого этапа — «перед уроком». Урок без этапов — прежнее
занятие: страница показывает его блоки без времени.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .storage import BLOCK_STAGE, Block, Template


@dataclass
class Stage:
    index: int
    block: Block                      # сам блок-этап: название, минуты, вид, раздел, пометка
    start_min: int                    # с какой минуты урока
    end_min: int                      # по какую
    blocks: list[Block] = field(default_factory=list)


def stages(t: Template) -> tuple[list[Block], list[Stage]]:
    """→ (блоки до первого этапа, этапы с их блоками и минутами от начала урока)."""
    intro: list[Block] = []
    out: list[Stage] = []
    at = 0
    for b in t.blocks:
        if b.type == BLOCK_STAGE:
            m = max(0, int(b.minutes or 0))
            out.append(Stage(len(out), b, at, at + m))
            at += m
        elif out:
            out[-1].blocks.append(b)
        else:
            intro.append(b)
    return intro, out


def has_stages(t: Template) -> bool:
    return any(b.type == BLOCK_STAGE for b in t.blocks)


def total_minutes(t: Template) -> int:
    return sum(max(0, int(b.minutes or 0)) for b in t.blocks if b.type == BLOCK_STAGE)
