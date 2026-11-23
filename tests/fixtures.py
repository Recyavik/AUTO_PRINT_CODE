"""Общие данные тестов: урок с печатью по шагам (раньше — встроенный пример «Пример: пошаговый урок»).
Шаг 3 возвращается наверх (import), шаг 4 — вставка в середину; комментарии — «Скажи: …» на экране урока."""
from __future__ import annotations

STEPS_CODE = '''import statistics

# Оценки учеников
grades = [5, 4, 3, 5, 4]
grades.append(5)  # пришла ещё одна оценка — вернулись наверх и дописали
print("Оценки:", grades)

# Средний балл
average = sum(grades) / len(grades)
print("Средний:", round(average, 2))

# Медиана — возьмём готовую функцию из модуля statistics
median = statistics.median(grades)
print("Медиана:", median)'''
STEPS = [3, 3, 1, 1, 4, 1, 2, 2, 2, 2, 3, 3, 3, 3]
STEPS_TITLE = "Пример: пошаговый урок"


def steps_template():
    from autoprint.storage import BLOCK_CODE, BLOCK_MARKDOWN, Block, Template
    return Template(title=STEPS_TITLE,
                    blocks=[Block(BLOCK_MARKDOWN, "Пошаговый урок: оценки учеников", role="explain"),
                            Block(BLOCK_CODE, STEPS_CODE, steps=list(STEPS))])
