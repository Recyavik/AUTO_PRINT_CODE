"""Встроенный образцовый урок «Пример урока: функции и надёжный пароль» — всё, что умеет экран урока, на одном
уроке: две половины по 45 минут, этапы с минутами, перерыв и зарядка, все роли заметок (цель урока, говоришь,
термин, расскажи, спроси с ответами, делаешь, показываешь, результат кода, важно, типичные ошибки, если застрял,
для быстрых, задание, домашнее задание, заметка), рабочий код Python с выводом после каждого блока и три картинки.

Урок записан файлом autoprint/samples/lesson-example.md (формат урока .md — его можно открыть в любом
редакторе; копия — в examples/). Картинки — рядом, в lesson-example_files (их рисует tools/make_sample_images.py)
и при загрузке копируются в data/media. Добавляется один раз (Settings.samples_seen, LESSON_SAMPLE_ID).
"""
from __future__ import annotations

from pathlib import Path

from .storage import Template

LESSON_SAMPLE_ID = "lesson_v3"         # v3 (0.11): цель урока, проверки понимания, «если застрял», рефлексия, домашнее
LESSON_TITLE = "Пример урока: функции и надёжный пароль"
SAMPLE_MD = Path(__file__).resolve().parent / "samples" / "lesson-example.md"


def lesson_sample() -> Template:
    from . import lesson_md
    t = lesson_md.parse(SAMPLE_MD.read_text(encoding="utf-8"), SAMPLE_MD.parent, LESSON_TITLE)
    t.title = LESSON_TITLE
    return t


# образец плана урока (0.12): этапы и минуты онлайн-урока на 90 минут, заготовки у приветствия, итогов и ДЗ
PLAN_SAMPLE_ID = "plan_v1"
PLAN_TITLE = "Пример плана: онлайн-урок 90 мин"
_PLAN_STAGES = [("Приветствие и проверка связи", 5, ""), ("Повторение", 10, ""), ("Новая тема", 20, ""),
                ("Зарядка для глаз", 3, "exercise"), ("Практика 1", 12, ""), ("Перерыв", 10, "break"),
                ("Практика 2", 20, ""), ("Итоги и рефлексия", 7, ""), ("Домашнее задание", 3, "")]
_PLAN_DRAFTS = {"Приветствие и проверка связи": ("do", "Проверить звук и демонстрацию; отметить, кто пришёл"),
                "Итоги и рефлексия": ("ask", "Что сегодня получилось? Что было трудно?"),
                "Домашнее задание": ("homework", "")}


def plan_sample() -> Template:
    from .storage import BLOCK_MARKDOWN, BLOCK_STAGE, KIND_PLAN, Block
    blocks = []
    for title, minutes, kind in _PLAN_STAGES:
        blocks.append(Block(BLOCK_STAGE, "", title=title, minutes=minutes, stage_kind=kind))
        if title in _PLAN_DRAFTS:
            role, text = _PLAN_DRAFTS[title]
            blocks.append(Block(BLOCK_MARKDOWN, text, role=role))
    return Template(PLAN_TITLE, blocks, kind=KIND_PLAN)
