# 0.11 — урок по событиям: план работ

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** экран урока — единственный пульт: ничего не делает сам, один план, экран учеников и слайды
отсюда, правка как в Word, урок из презентации.

**Architecture:** страница `/lesson` (ES-модули) + LessonController/EfirController в Qt. Настройки
страницы — поля Settings, команда `prefs`. Слайд — блок-картинка с `slide=N`, экран учеников — режим
`slide`. Редактор заметок — `contenteditable` с переводом HTML ↔ Markdown на странице.

**Tech Stack:** Python 3.14, PySide6 6.11 (QtPdf), plain JS, CodeMirror 6 bundle, headless Edge (CDP).

**Spec:** docs/superpowers/specs/2026-11-24-v011-urok-po-sobytiyam-design.md

## Общие ограничения

- Тесты невидимы: `tests/quiet.py`, Edge `--headless=new` со своим профилем. PowerPoint в тестах не
  запускать — подменять `slides.export_pdf`.
- Каждая задача: тест сначала (RED), потом код, потом `tests/test_v11.py` (Python) и/или
  `tests/test_page.py` (страница).
- Тексты интерфейса — по-русски, как в спеке.
- Старые settings.json и templates.json читаются; новые поля — со значениями по умолчанию.

## Что проверить отдельно (Review Focus)

1. Смена этапа по часам не меняет раскрытое и не двигает ленту, пока учитель читает. Тест — задача 2.
2. Правка с панелью → Markdown → снова в редактор — то же оформление; вставка из Word не тащит стили.
   Тест — задача 5.
3. Кликер ◀ ▶ во время правки заметки не листает слайды. Тест — задача 8.
4. PPTX со скрытым слайдом: заметки не сдвигаются молча. Тест — задача 9.
5. Экран учеников со слайдом переживает перезапуск программы. Тест — задача 8.

---

## Заход A — урок по событиям

### Task 1: «Мои настройки», масштаб

**Файлы:** `autoprint/storage.py`, `autoprint/ui/lesson_control.py`, `autoprint/scenario.py`,
`autoprint/efir/page/lesson/app.js`, `lesson.html`, `state.js`.

**Produces:**
- Settings: `page_zoom: int = 100`, `page_plan: str = "strip"` (strip | side | hidden),
  `page_past: str = "dim"` (dim | collapse), `page_stage_timer: bool = True`, `start_timer: bool = False`,
  `start_screen: bool = False`.
- State: `prefs` — эти поля.
- Команда `{"cmd": "prefs", "key": …, "value": …}` с проверкой значений.

- [ ] Тест `PrefsTest.test_prefs_command`: команда меняет поле, неверное значение игнорируется, state
  содержит `prefs`.
- [ ] Тест страницы `test_zoom_keys`: Ctrl+= → `page_zoom` 110, `--zoom` на `<html>`.
- [ ] Кнопка «Аа» → меню «Мои настройки».
- [ ] Ctrl+= / Ctrl+− / Ctrl+0, Ctrl+колесо.

### Task 2: «Урок» не сворачивает и не прокручивает

**Файлы:** `app.js`, `lesson.html`.

- [ ] Тест страницы `test_no_auto_collapse`: урок идёт, якорь сдвинут так, что текущим стал следующий
  этап. Проверить:
  - `collapsed` ни у одного этапа;
  - `scrollY` не изменился;
  - плашка «↓ Идёт» видна, если этап вне экрана.
- [ ] Тест `test_collapse_buttons`: «Свернуть всё» / «Развернуть всё» в шапке плана; `page_past=collapse`
  сворачивает пройденные.
- [ ] Убрать «Следующий · через»; «осталось» — только при `page_stage_timer`.
- [ ] Подписи этапов — 14 px.

### Task 3: план строкой

**Файлы:** `app.js`, `render.js`, `lesson.html`.

- [ ] Тест страницы `test_plan_strip`: в «Уроке» при `page_plan=strip`:
  - `#plan` скрыт;
  - `#strip` показывает текущий, следующий и «конец ЧЧ:ММ»;
  - «▾» открывает план поверх ленты.

  В «Подготовке» план сбоку всегда.
- [ ] «+N мин» при сдвиге: `live.shift` (мин) из LessonController — разница якоря с первым якорем урока.

### Task 4: экран учеников с экрана урока, таймер, оформление

**Файлы:** `lesson_control.py`, `efir_control.py`, `efir_timer.py`, `app.js`, `scenario.py`.

- [ ] Тест `EfirPageTest.test_start_no_timer`: `command start` → `timer_window is None`; `start_timer=True`
  → окно есть.
- [ ] Тест `test_break_default`: `command break` без stage → `break_min` оформления.
- [ ] Тест `test_screen_state`: в state `efir`:
  - `mode`, `tab`;
  - `break_ends`;
  - `slide` (задача 8);
  - `exercises`.
- [ ] Тест `test_look_edit_command`:
  - `cmd look_edit` → `ctl.edit_look` вызван с id оформления урока;
  - `look_new` → новый Look в store, урок выбирает его.
- [ ] Тест `TimerBreakTest.test_popup_buttons`: в попапе «Перерыв» кнопки 5/10/15/20 и плановые минуты;
  у спинбокса нет фокуса; щелчок по кнопке начинает перерыв.
- [ ] Страница: «У учеников: …», Фон, Перерыв ▾, Зарядка, «Открыть экран учеников».
- [ ] Переименования: «Начать этот этап сейчас», «Разложить по этапам».

## Заход B — правка как в Word

### Task 5: редактор заметки без разметки

**Файлы:** `edit.js`, новый `richtext.js` (HTML ↔ Markdown, санитайзер вставки), `lesson.html`,
`tests/test_page.py`.

**Produces:** `richtext.js`:
- `toMarkdown(root: Element) -> string`;
- `cleanPaste(html: string) -> string` — разрешены b/strong, i/em, code, a[href^=http], ul/ol/li, p, br,
  h1–h6 (как жирный абзац).

- [ ] Тест страницы `test_rich_bold`: правка заметки, выделить слово, кнопка «Ж» → текст блока содержит
  `**слово**`; в редакторе нет `*`.
- [ ] Тест `test_rich_roundtrip`: заметка `**a** *b* \`c\` [d](https://x.ru)\n- e\n- f` → открыть и
  закрыть без правки → текст не изменился.
- [ ] Тест `test_paste_word`: вставка `<p style="…"><b>Жир</b> <span style="color:red">текст</span></p><ul><li>раз</li></ul>`
  → `**Жир** текст\n\n- раз`.
- [ ] Старые тесты, опиравшиеся на TEXTAREA, — на `.rich[contenteditable]`.

### Task 6: поля «Спроси» и «Термин»

- [ ] Тест страницы `test_ask_fields`: у «Спроси» поле вопроса и строки ответов; «+ ответ», ввод →
  `вопрос\n→ ответ 1\n→ ответ 2`.
- [ ] Тест `test_term_fields`: «Термин» + «Определение» → `Термин\nопределение`.

### Task 7: роли и палитра

**Файлы:** `storage.py`, `lesson_ai.py`, `importers.py` (тетрадка учеников), `edit.js`, `render.js`.

- [ ] Тест `RolesV11Test`:
  - ROLES: `trap` «Типичные ошибки», `output` «Результат кода», `hint` «Если застрял», `homework`
    «Домашнее задание», `goal` «Цель урока»;
  - ROLE_ORDER по группам;
  - ROLE_GROUPS в state.
- [ ] Тест `test_students_notebook_homework`: домашнее задание попадает в тетрадку учеников.
- [ ] Тест страницы `test_palette_groups`: заголовки групп; «Код» — последний в «Материалах»; урок без кода —
  нет «Печать».
- [ ] Подпись «· дословно» и т. п. на плашке.

## Заход C — презентации

### Task 8: слайд и экран учеников

**Файлы:** `storage.py` (Block.slide), `lesson_md.py`, `lesson_edit.py`, `scenario.py`,
`efir_control.py`, `efir/store.py`, `screen.html`, `render.js`, `app.js`.

**Produces:**
- `EfirController.show_slide(url: str, n: int, bid: str)` — режим `slide`, хранится как brk
  (`store.set_slide`);
- page `cmd slide {block}`, `cmd slide_step {d}`.

- [ ] Тест `SlideTest.test_show_slide`: состояние экрана `{"mode": "slide", "src": …}`; `show_background`
  снимает.
- [ ] Тест `test_slide_survives_restart`.
- [ ] Тест `test_md_slide_roundtrip`: lesson_md пишет и читает `slide:N`.
- [ ] Тест страницы `test_clicker_keys`: в «Уроке» ArrowRight → cmd slide следующего слайда; при правке
  заметки — нет.
- [ ] screen.html: режим `slide`, предзагрузка следующего.

### Task 9: импорт PDF и PPTX

**Файлы:** новый `autoprint/slides.py`, `importers.py`, `materials.py`, `main_window.py`, `import_dialog.py`.

**Produces:**
- `slides.from_pdf(path, title) -> Template`;
- `slides.from_pptx(path, pdf: str | None = None) -> tuple[Template, list[str]]` — урок и замечания;
- `slides.export_pdf(pptx) -> str | None` — PowerShell COM;
- `slides.pptx_info(path) -> (order, sections, notes)`.

- [ ] Тест `PresentationTest.test_pdf`: 3 страницы (QPdfWriter) → 3 слайда с картинками, этап
  «Презентация».
- [ ] Тест `test_pptx_order_sections_notes`: pptx в тесте:
  - порядок по presentation.xml;
  - 2 раздела → 2 этапа;
  - пометки → роли.
- [ ] Тест `test_hidden_slide_mismatch`: 3 слайда, PDF на 2 страницы → замечание, третий слайд без
  картинки.
- [ ] Тест `test_export_pdf_mocked`: команда PowerShell без окна (`CREATE_NO_WINDOW`), путь вывода.
- [ ] «Новый урок → Из презентации…»; Импорт принимает .pdf/.pptx как урок по слайдам.

### Task 10: нейросеть в своём чате

**Файлы:** `lesson_ai.py`, `import_dialog.py`, `lesson_control.py`, `app.js`.

- [ ] Тест `ChatPromptTest.test_copy_without_material`: `chat_prompt("", opt)` — «приложен к сообщению»,
  «```markdown», пример `![Слайд 1](slide:1)`.
- [ ] Тест `test_slides_prompt`: урок с 3 слайдами → текст слайдов, «с 1 по 3».
- [ ] Тест `test_apply_answer`:
  - ответ .md со `slide:2` → копия урока, слайд 2 — тот же файл;
  - замечания: «слайда 5 нет», «сумма минут 40 из 45».
- [ ] Кнопка «Скопировать промпт» активна без материала.
- [ ] «⋯ → Промпт для слайдов», «⋯ → Вставить ответ нейросети».

## Заход D — печать, шаблоны, образец, выпуск

### Task 11: печать

- [ ] Тест страницы `test_print_options`: окно печати ставит на `<body>` классы:
  - `print-size-large`;
  - `print-no-answers`;
  - `print-no-code`;
  - `print-slides-thumbs`.

  `window.print` подменён.
- [ ] `print-color-adjust: exact`.

### Task 12: новый урок по шаблону структуры

- [ ] Тест `StructureTest`: `store.add_from_structure("school45")` → этапы с минутами по спеке; команда
  страницы `new_lesson {structure}`.
- [ ] Меню «Новый урок ▾» в окне программы и в списке уроков на странице.

### Task 13: образцовый урок v3

- [ ] Тест `SampleV3Test`:
  - есть «Цель урока», «Домашнее задание», рефлексия;
  - «Спроси» после теории;
  - нет «Как читать».
- [ ] Миграция `samples_v11`: неизменённая копия образца v2 удаляется, добавляется v3.

### Task 14: README, версия 0.11.0, снимки

### Task 15: тестировщик и методист

- [ ] Агент-тестировщик: ищет ошибки на готовой ветке, только без окон.
- [ ] Агент-методист: перепроверка.
- [ ] Исправления — RED → GREEN.

### Task 16: итоговое ревью, сборка, установка

- [ ] Итоговое ревью ветки свежим проверяющим.
- [ ] Сборка.
- [ ] Установка — с разрешения владельца, после проверки, что эфир не идёт.
- [ ] Обновить память, отправить ветку в форк.
