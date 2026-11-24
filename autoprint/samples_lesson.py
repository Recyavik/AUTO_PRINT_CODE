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
