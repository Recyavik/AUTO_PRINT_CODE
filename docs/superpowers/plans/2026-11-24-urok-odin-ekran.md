# AutoPrintCode 0.10 — один экран урока: план работ

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Цель:** экран урока в браузере становится единственным местом, где урок готовят и ведут. Печатается
только код урока, который идёт. Окно программы — список уроков. «Эфир»: оформление отдельно от
расписаний. Образцовый урок.

**Устройство:**
- Логика печати выносится из `MainWindow` в `PrintController` (без виджетов); он работает с данными урока,
  а не с вкладками Qt.
- Страница `/lesson` получает плоский список блоков с версиями, правит урок через `POST /lesson/edit`
  и перерисовывает только изменённые блоки.
- Редактор кода на странице — CodeMirror 6, собранный в один файл.
- «Эфир» хранит оформления (`looks.json`) и расписания (`schedules.json`). Экран и таймер работают
  с прежним объектом `Webinar`, собранным из двух частей.

**Технологии:** Python 3.14, PySide6 6.11, pygments; страница на чистом JS (ES-модули), CodeMirror 6
(esbuild); тесты — сценарии `tests/*.py` (offscreen) и headless Edge через CDP.

**Проект:** docs/superpowers/specs/2026-11-24-urok-odin-ekran-design.md

## Общие ограничения

- Новых зависимостей Python нет. Страница работает без интернета: все JS и CSS отдаёт сервер программы.
- POST — только с `X-Suflor: 1` и своего Origin.
  - Правки и команды — до 2 МБ, картинка — до 25 МБ.
  - Картинка — только png, jpg, gif или webp; тип проверяется по первым байтам.
- Тесты невидимы.
  - `import quiet` первой строкой; `QT_QPA_PLATFORM=offscreen`.
  - Своя папка `AUTOPRINT_DATA`; порт не 8791 (берём 8890–8899).
  - Edge — только `--headless=new` со своим временным профилем.
- Колёсико мыши не меняет значения на странице: минуты — `<input inputmode="numeric">`, не `type=number`.
- Тексты интерфейса — по-русски, коротко.
- Каждая задача — коммит в `redesign-pastetalk-ui`, в конце сообщения
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Проверка перед сдачей задачи: тесты задачи, затем `.venv/Scripts/python.exe tools/check.py`. Шаги
  «Веб: …» падают без `web/node_modules` — так было и до этой работы, это не ошибка.
- Процессы пользователя (msedge, chrome, explorer) не завершаем. Окно суфлёра закрываем только своё,
  по pid.

## Порядок (отличается от проекта)

Решение: редактор блоков Qt удаляется в первом заходе, а не в третьем. Иначе первую очередь пришлось бы
встраивать в редактор, который потом выбрасываем. Между заходами 1 и 2 урок нельзя править в программе
(только импортом); пользователь эту промежуточную версию не получает.

1. **Заход A** (задачи 1–5): модель, `PrintController`, компактное окно, удаление пульта, суфлёров и
   редактора Qt.
2. **Заход B** (задачи 6–11): экран урока — состояние, правки, «Подготовка», «Урок», «Печать ⚙», CodeMirror.
3. **Заход C** (задачи 12–15): «Эфир».
4. **Заход D** (задачи 16–20): образцовый урок, примеры, распознавание сценария, нейросеть, .md, чистка,
   версия, сборка, установка.

## Что проверить отдельно (Review Focus)

1. Состояние пришло, пока человек печатает в заметке: текст, курсор и выделение в поле не меняются.
   Тест — задача 9.
2. Нет связи, программу перезапустили: несохранённые правки уходят один раз. Новый блок не задваивается:
   `id` вставляемого блока придумывает страница, повтор с тем же `id` ничего не добавляет. Тест — задачи 7 и 9.
3. Блок или урок, из которого идёт печать, удалили или урок сменили: печать останавливается, ошибок нет.
   Тест — задача 2.
4. Правка этапов идущего урока: начало текущего этапа на тех же часах, в том числе когда удалили этап
   перед ним или сам текущий этап. Тест — задача 13.
5. Большой урок (90 блоков): страница открывается быстрее 300 мс, ввод в заметку не перерисовывает ленту.
   Тест — задача 11.

---

## Заход A — модель и печать

### Задача 1: роли, поля урока, миграции 0.10

**Файлы:**
- Изменить: `autoprint/storage.py` — ROLES, Settings, Template.
- Создать: `autoprint/migrations.py`.
- Тест: `tests/test_v10.py` — новый сценарий, добавить в `SCRIPT_TESTS` в `tools/check.py`.

**Интерфейсы (выдаёт):**
- `ROLES`:
  - добавить `"term": ("📖", "Термин", "#5fc9b8")` и `"output": ("✅", "Вывод", "#6fd382")`;
  - переименовать `task` → «Задание», `text` → «Заметка».
- `ROLE_ORDER: list[str] = ["say", "term", "tell", "ask", "do", "show", "output", "important", "trap", "extra", "task", "text"]`
  и `ROLE_MORE = ["explain", "hint"]`.
- `ROLE_HINTS: dict[str, str]` — строка обозначений:
  - say «обязательно, дословно»;
  - term «обязательный термин — дословно»;
  - tell «своими словами, можно дополнять»;
  - ask «вопрос и ответы учеников»;
  - do «вслух не читать»;
  - show «что видят ученики»;
  - output «что выведет код»;
  - important «нельзя пропустить»;
  - trap «на чём ошибаются»;
  - extra «тем, кто закончил раньше»;
  - task «что делают ученики»;
  - text «заметка»;
  - explain «пояснение»;
  - hint «подсказка».
- `Template.look: str = ""` — новое поле; `preset` остаётся.
- `Template.next_code(after_id: str = "", back: bool = False) -> Block | None` — следующий/предыдущий
  непустой блок кода. Без `after_id` — первый.
- `is_printable(b: Block) -> bool` — `b.type == BLOCK_CODE and b.text.strip()`.
- `TemplateStore.add(title)` создаёт этап «Начало» (5 мин) и пустую заметку `say` (вместо «Задача 1» и кода).
- `Settings`:
  - убрать `typo_per_100_words`, `splitter_state`, `open_tabs`, `show_prompter`, `prompter_window`,
    `prompter_mode`, `prompter_font`, `prompter_geometry`, `auto_advance`;
  - добавить `lesson_look: str = ""`, `page_open: bool = False` (экран урока был открыт), `page_lesson: str = ""`.
- `migrations.backup_before_v10(data_dir: Path) -> None` — копия `templates.json` →
  `templates.before-0.10.json` и `efir/webinars.json` → `efir/webinars.before-0.10.json`.
  Только если копии ещё нет.
- `migrations.apply(settings, store) -> bool`:
  - один раз зовёт `backup_before_v10`;
  - `roles_v10`: у каждого урока, где `active_block` указывает не на код, ставит `active_block` первого
    кода или `""`;
  - `tray_v1` переезжает сюда из `main_window.apply_migrations`.

- [ ] Тест `RolesTest.test_new_roles`: `"term" in ROLES and "output" in ROLES`;
  `ROLES["task"][1] == "Задание"`; `ROLES["text"][1] == "Заметка"`; `set(ROLE_ORDER + ROLE_MORE) == set(ROLES)`.
- [ ] Тест `RolesTest.test_new_lesson_shape`: `TemplateStore().add("X").blocks` → `[stage("Начало", minutes=5),
  markdown(role="say", text="")]`.
- [ ] Тест `MigrationTest.test_active_note_reset`: урок, где `active_block` — заметка, а дальше код с id
  `c1` → после `apply` `active_block == "c1"`. Урок без кода → `""`. Второй `apply` ничего не меняет
  (вернул False).
- [ ] Тест `MigrationTest.test_backup_once`: после `apply` есть `templates.before-0.10.json`, равный исходному.
  Запись базы и повтор `apply` копию не трогают.
- [ ] Тест `NextCodeTest`: в уроке [заметка, код A, картинка, код пустой, код B] — `next_code()` → A,
  `next_code("A")` → B, `next_code("B")` → None, `next_code("B", back=True)` → A.
- [ ] Прогнать (`FAIL`), сделать, прогнать (`OK`). Коммит «Модель 0.10: роли «Термин» и «Вывод»,
  «Задание», новый урок с этапа, миграции с копией базы».

### Задача 2: `PrintController` — печать урока в фокусе

**Файлы:**
- Создать: `autoprint/ui/print_control.py` — перенос из `main_window.py` строк 976–1606: печать, шаги,
  задания, сигналы движка.
- Создать: `autoprint/printing.py` — без Qt: `typing_slice`, взятый из `blocks.py`.
- Изменить: `autoprint/ui/main_window.py` (отдаёт печать контроллеру), `autoprint/ui/lesson_control.py`.
- Тест: `tests/test_v10.py`.

**Интерфейсы (выдаёт):**
- `class PrintController(QObject)`:
  - `__init__(self, settings, store, owner)`. Владеет `engine`, `player`, `guard`, `job`, `step_next`.
  - Сигналы: `changed = Signal()` (состояние печати или указатель изменились), `notify = Signal(str, bool)`.
  - `focus_id: str` — урок в фокусе; `focus() -> Template | None`.
  - `live_id: Callable[[], str]` — ставит `MainWindow`: `efir.live_lesson_id`. Если урок идёт,
    `focus()` возвращает его, иначе `store.get(focus_id)`.
  - `set_focus(tid: str) -> None`.
  - Команды: `arm(bid: str) -> bool` (только код, иначе False), `toggle(from_tray: bool = False)`,
    `restart()`, `stop()`, `step(d: int)` (Ctrl+F12 / Ctrl+Shift+F12), `step_back()`,
    `on_hotkey(action: str)`.
  - `snapshot() -> dict` для страницы:
    - `mode`, `cpm`, `human`, `sound`, `strip`, `hotkey`;
    - `state` ∈ idle | countdown | running | paused | line_wait | finished;
    - `block`, `progress` (0..1), `step: {i, n} | None`, `line: {i, n} | None`;
    - `next_lines: list[int]` — номера строк (с 1) следующего шага или строки у указателя;
    - `say: list[str]` — что сказать перед следующим шагом или строкой;
    - `last: str` — id последнего напечатанного блока.
  - `set_option(key: str, value)` для `mode`, `cpm`, `human`, `sound`, `strip` — меняет `Settings`, как
    раньше пульт: `rebuild`, сброс задания, сохранение настроек.
- **Правила.**
  - По окончании блока (в «по шагам» — после последнего шага) указатель переходит на
    `focus().next_code(bid)`, `last = bid`.
  - Ctrl+F10 во время печати или на паузе — этот блок заново; иначе `arm(last)` и сообщение
    «Ещё раз: <название> — Ctrl+F9».
  - Указателя нет и следующего кода нет — «Весь код урока напечатан».
  - **E13.** Перед стартом `toggle`: окно впереди наше (`winapi.is_own_window`) или окно Edge экрана урока
    (pid окна равен pid `lesson_control.prompter_window().proc`, либо заголовок окна кончается на
    « — AutoPrintCode») → не печатать, `notify("Поставьте курсор в Jupyter (или другой редактор) и
    нажмите Ctrl+F9 там.", True)`.
  - Вставка картинок, печать заметок и `textprint` (markdown / plain / comment) удаляются.
    `_paste_image_block` удаляется.
  - **Блок пропал.** Блок печатаемого задания удалили или фокус сменился на другой урок во время печати →
    `stop()`. Проверка — в `on_store_changed()`, его зовёт `MainWindow._touch` и правки со страницы.

- [ ] Тест `PrintTest.test_note_never_armed`: `arm(id заметки)` → False, `active_block` не изменился.
  `toggle()` при указателе на картинку из старой базы → движок не запускался (`engine.load` не вызван,
  подменить заглушкой).
- [ ] Тест `PrintTest.test_focus_is_live`: `live_id` возвращает урок L, `focus_id` — урок M → `focus()` это L,
  `toggle()` грузит задание из кода L.
- [ ] Тест `PrintTest.test_auto_advance`: после `engine.finished` по коду A указатель стоит на B, `last == A`.
  `restart()` в простое → указатель A и сообщение «Ещё раз: …».
- [ ] Тест `PrintTest.test_refuse_own_window`: подменить `winapi.foreground_window` и `is_own_window` → True;
  `toggle()` не стартует, сообщение с «Поставьте курсор в Jupyter».
- [ ] Тест `PrintTest.test_deleted_block_stops`: идёт печать (заглушка состояния RUNNING), блок удалён,
  `on_store_changed()` → `stop` вызван.
- [ ] Перенести и прогнать тесты печати из `tests/test_ui.py`, `test_steps.py`, `ui_regress.py`, которые
  проверяют шаги, строки и Ctrl+F12 через `MainWindow.cmd_*`: теперь через `win.printer.*`.
  Тесты вставки картинок (`PasteTest`, `ImageArmTest`) удалить.
- [ ] Коммит «Печать — отдельный контроллер: только код идущего урока, автопереход, Ctrl+F10 — ещё раз,
  не печатать в своё окно».

### Задача 3: окно программы — список уроков

**Файлы:**
- Изменить: `autoprint/ui/main_window.py` (тело окна), `autoprint/ui/library.py` (строка с подписью).
- Удалить: `autoprint/ui/control_strip.py`, `prompter.py`, `prompter_window.py`, `prompter_control.py`,
  `template_view.py`, `blocks.py`, `code_editor.py`, `autoprint/textprint.py` (если пусто).
- `MenuButton` перенести в `autoprint/ui/widgets.py`; `efir_editor` берёт его оттуда.
- Тесты, где удалённые классы: `tests/test_ui.py`, `ui_smoke.py`, `ui_sweep.py`, `ui_regress.py`,
  `test_v09.py` (`ThemeTest`, `EditorBlocksTest`, `PrompterWinTest` — то, что про окно Edge, остаётся),
  `ui_import.py`.

**Интерфейсы:**
- `MainWindow`:
  - тело — `LibraryPanel` во всю ширину;
  - под списком кнопки «Открыть» (главная), «Новый урок», «Импорт…», «Урок из методички (нейросеть)…»;
  - внизу `PrintBar` — строка печати: «Печатается: <блок> · NN% · [Пауза] [Стоп]», видна только при
    печати, строится на `printer.changed`;
  - по умолчанию 520×720, минимум 420×480.
- `MainWindow.open_lesson(tid: str) -> None`:
  - урок идёт и это другой → вопрос «Идёт урок «X». Завершить его и открыть «Y»?»;
  - да или урок не идёт → `printer.set_focus(tid)`, `settings.page_lesson = tid`, `lesson.open_page()`.
  - Двойной щелчок и Enter в списке — то же самое.
- Строка списка: название; ниже мелко «1 ч 30 мин · 12 этапов · 5 кодов». Идущий урок — красная точка.
  Данные — `ROLE_META` («подпись»), рисует `LibraryDelegate` в две строки, высота строки 48.
- Меню урока (правый щелчок): Открыть, Переименовать, Дублировать, Экспорт ▸ (.md / .ipynb / тетрадка
  учеников / .json), Распознать сценарий (задача 18; до неё пункта нет), Удалить.
- Меню логотипа без пунктов: «Добавить пример…» ×3, «Суфлёр в отдельном окне», «Все блоки — обычный
  размер». Есть «Экран урока».
- В трее нет «Суфлёр в отдельном окне». «Суфлёр урока» → «Экран урока».
- `QShortcut`: Ctrl+N, Ctrl+O, Ctrl+Q, Ctrl+, и F1 остаются; масштаб блоков и Alt+↑/↓ убрать.
- **Сессия.**
  - При выходе `settings.page_open = lesson.page_alive()`.
  - При запуске, если `page_open` и урок `page_lesson` есть, — `open_lesson(page_lesson)` через 800 мс.
    Без вопроса: урок не идёт, или идёт этот же.
- **«Настройки → Печать».**
  - Убрать «Суфлёр» (`show_prompter`).
  - В «Как печатать блок» — описание без «на пульте».
  - «Скорость» — описание без «на пульте».
  - «Не печатать комментарии» — без «на пульте».

- [ ] Тест `WindowTest.test_compact`: окно открыто offscreen; нет детей `ControlStrip`, `TemplateView`;
  есть `LibraryPanel` и `PrintBar` (скрыт); размер по умолчанию 520×720.
- [ ] Тест `WindowTest.test_open_lesson_sets_focus`: `open_lesson(t.id)` → `printer.focus_id == t.id`,
  `lesson.open_page` вызван (заглушка).
- [ ] Тест `WindowTest.test_open_other_while_live_asks`: идёт урок L. `QMessageBox.question` → No:
  фокус и урок не меняются. → Yes: `efir.stop_live` вызван, фокус M.
- [ ] Тест `WindowTest.test_library_meta`: у урока с этапами 5+10 мин и 2 кодами подпись строки
  «15 мин · 2 этапа · 2 кода».
- [ ] Прогнать `tools/check.py`, коммит «Окно программы — список уроков: без пульта, суфлёров и
  редактора блоков».

### Задача 4: экспорт и импорт под новую модель

**Файлы:** `autoprint/importers.py`, `autoprint/lesson_md.py`.

- `export_ipynb(t, path, students=True)` — только ячейки кода.
- `TEACHER_ROLES` удалить: для учеников заметок нет вообще.
- `lesson_md`:
  - `[!term]` и `[!output]` читаются и пишутся (идут через `ROLES`, как остальные);
  - русские имена «Термин» и «Вывод» тоже читаются (`_ROLE_BY_NAME` строится из `ROLES`).
- [ ] Тест `ExportTest.test_students_code_only`: урок [этап, заметка say, картинка, код] → в тетрадке одна
  ячейка, `cell_type == "code"`.
- [ ] Тест `ExportTest.test_md_term_output_roundtrip`: урок с `term` и `output` → `to_md` → `parse` →
  роли и тексты те же.
- [ ] Коммит «Экспорт: тетрадка учеников — только код; .md знает «Термин» и «Вывод»».

### Задача 5: `LessonController` — урок страницы и печать

**Файлы:** `autoprint/ui/lesson_control.py`, `autoprint/ui/main_window.py`.

- `LessonController.current()` = `printer.focus()`. Больше не `main.current_view()`.
- `LessonController.page_alive() -> bool` — `prompter_window().alive()`.
- Команда `arm` со страницы → `printer.arm(bid)`.
- `printer.changed` → `schedule_publish`.
- Команда `open {lesson}` со страницы → `main.open_lesson(lesson)`.
- [ ] Тест `LessonCtlTest.test_current_is_focus`: `printer.set_focus(M)` → `lesson.current().id == M`.
  Идёт урок L → `current().id == L`.
- [ ] Тест `LessonCtlTest.test_cmd_arm_note_ignored`: `command({"cmd": "arm", "block": id_заметки})` →
  `active_block` не изменился.
- [ ] Коммит «Экран урока показывает урок в фокусе; «Следующим» — только у кода».

## Заход B — экран урока

### Задача 6: состояние страницы — плоский список блоков с версиями

**Файлы:** `autoprint/scenario.py` (`lesson_state`), `autoprint/ui/lesson_control.py`.

**Интерфейсы:**
- `scenario.block_version(b: Block) -> int` — `zlib.crc32` от `json.dumps(asdict(b), sort_keys=True)`.
- `scenario.item_state(b: Block, media_url) -> dict` — каждый блок, пустые тоже. Поля:
  - всегда: `id`, `type`, `v`, `text`, `title`;
  - заметка: `role`, `html` (+ `answers` у `ask`; у `term`: `term` — первая строка, `html` — остальное);
  - код: `lang`, `label`, `icon`, `html`, `steps`, `sel`, `profile`;
  - картинка: `url`, `missing`, `name`;
  - этап: `minutes`, `kind`, `part`, `note`.
- `lesson_state(...)` получает параметр `printer: dict`; `armed` берётся из него.
  Поле `lesson` — словарь:
  - `id`, `title`, `rev` (crc32 от версий всех блоков), `total`, `has_stages`, `start`;
  - `items` — все блоки по порядку;
  - `stages` — `{i, id, title, minutes, kind, part, note, start, end}`, без блоков;
  - `look`, `looks` (до задачи 12 — `preset`, `presets`).
- Новые поля верхнего уровня:
  - `lessons` — `{id, title, total, stages, codes, updated}` всех уроков;
  - `print` — `printer.snapshot()`;
  - `roles` — `[{key, name, hint}]` в порядке `ROLE_ORDER + ROLE_MORE`; страница берёт названия
    только отсюда;
  - `exercises` — у оформления есть видео зарядки (E7).
- `intro` и `stages[].blocks` удаляются.

- [ ] Тест `StateTest.test_items_flat`: в уроке [заметка, этап, код, картинка] `items` — 4 штуки по порядку,
  у кода есть `text`, `lang`, `v`. Изменили текст кода — `v` другой, у заметки `v` прежний.
- [ ] Тест `StateTest.test_term`: `term` «Функция\nименованный блок…» → `term == "Функция"`, в `html` есть
  «именованный».
- [ ] Тест `StateTest.test_print_in_state`: `printer.arm(код)` → `state["print"]["block"] == id`.
- [ ] Коммит «Состояние экрана урока: все блоки с версиями, печать, список уроков».

### Задача 7: правки урока — `POST /lesson/edit` и `/lesson/upload`

**Файлы:**
- `autoprint/efir/server.py` — маршруты, лимиты, статика `/static/lesson/*.js` и `/static/vendor/*.js`.
- Создать: `autoprint/lesson_edit.py` — применение действий к `Template`, без Qt.
- `autoprint/ui/lesson_control.py` — поток интерфейса.

**Интерфейсы:**
- `lesson_edit.apply(t: Template, ops: list[dict]) -> list[str]` — меняет урок, возвращает id затронутых
  блоков. Ошибка → `ValueError`, урок не изменён: сначала проверка всех действий, потом применение.
  Действия:
  - `{"op":"set","block":id,"fields":{…}}` — разрешены `text`, `title`, `role` (только из `ROLES`), `lang`,
    `profile`, `steps` (список int), `sel` ([a, b] или []), `minutes` (0..600), `stage_kind`, `part`;
  - `{"op":"insert","after":id|"" ,"block":{"id":…,"type":…,"role":…,"text":…,…}}` — `id` от страницы,
    только `[0-9a-f]{12}`. Если блок с таким `id` уже есть — ничего не делать (повтор);
  - `{"op":"delete","block":id}`. Удаление этапа: его блоки остаются на месте и переходят к предыдущему
    этапу сами (так устроен `stages()`);
  - `{"op":"move","block":id,"after":id|""}`;
  - `{"op":"move_stage","stage":id,"after_stage":id|""}` — этап вместе с его блоками;
  - `{"op":"restore","block":{…все поля…},"after":id|""}`;
  - `{"op":"set_lesson","title":…}`.
- `BroadcastServer(on_edit=…, on_upload=…)`:
  - `on_edit(data: dict) -> dict` и `on_upload(lesson, after, body: bytes, ctype) -> dict` выполняются
    в потоке сервера;
  - `LessonController` передаёт работу в поток интерфейса через `concurrent.futures.Future` и сигнал
    с QueuedConnection, ждёт `future.result(timeout=3)`. Не успел → 503 `{"ok": false, "retry": true}`.
- **Ответ `/lesson/edit`:** `{"ok":true,"rev":…,"items":{id:item_state…}}`, удалённые — `null`. После
  применения: `printer.on_store_changed()`, `main._touch()` (сохранение через 700 мс), `schedule_publish()`.
- **`/lesson/upload?lesson=…&after=…`:**
  - тело ≤ 25 МБ;
  - магия: `\x89PNG`, `\xff\xd8\xff`, `GIF8`, `RIFF....WEBP`, иначе 415;
  - временный файл → `storage.import_media` → блок-картинка после `after`;
  - ответ — `{"ok":true,"item":…}`.
- **Статика:** `/static/lesson/<имя>.js` и `/static/vendor/<имя>.js` по `[a-z0-9-]+\.js`, из
  `efir/page/lesson/` и `efir/page/vendor/`; `Content-Type: text/javascript`.
- Лимит тела POST: команды и правки — 2 МБ (было 64 КБ).

- [ ] Тест `EditTest.test_ops` (без Qt), по одному утверждению на действие:
  - `set` текста;
  - `set` роли `zzz` → ValueError, урок не изменён;
  - `insert` с тем же `id` дважды → один блок;
  - `delete` этапа — блоки остались;
  - `move`;
  - `move_stage` переносит этап и его блоки за следующий этап;
  - `restore` возвращает удалённый блок на место.
- [ ] Тест `EditServerTest.test_edit_roundtrip`: сервер на 8891, `MainWindow` offscreen. POST с
  `X-Suflor` → 200, в ответе `items[id].html`, урок в `store` изменён. Без заголовка → 403. Чужой
  Origin → 403. Тело 3 МБ → 413.
- [ ] Тест `EditServerTest.test_upload`: PNG 1×1 → блок-картинка после `after`, файл в `data/media`.
  Тело «hello» с `Content-Type: image/png` → 415.
- [ ] Тест `EditServerTest.test_static`: `/static/lesson/app.js` → 200 `text/javascript`;
  `/static/lesson/../server.py` → 404.
- [ ] Коммит «Правки урока со страницы: протокол действий, загрузка картинок, статика страницы».

### Задача 8: CodeMirror 6 — сборка в один файл

**Файлы:**
- Создать: `tools/page_vendor/` (`package.json`, `cm6-entry.js`, `build.bat`).
- Результат: `autoprint/efir/page/vendor/cm6.js` (в репозитории) и `autoprint/efir/page/vendor/LICENSES.txt`.
- `cm6-entry.js` экспортирует:
  - `EditorView`, `EditorState`, `keymap`, `lineNumbers`, `gutter`, `GutterMarker`, `history`,
    `defaultKeymap`, `historyKeymap`, `indentWithTab`, `syntaxHighlighting`, `HighlightStyle`, `tags`,
    `StateField`, `StateEffect`, `RangeSetBuilder`, `Decoration`;
  - языки: `python()`, `javascript()`, `html()`, `css()`, `java()`, `cpp()`, `sql()`, `json()`.
- Сборка: `esbuild cm6-entry.js --bundle --format=esm --minify --outfile=../../autoprint/efir/page/vendor/cm6.js`.
  Пакеты ставятся `npm install` в `tools/page_vendor`; `node_modules` в .gitignore.
- [ ] Проверка: файл < 900 КБ; `node -e "import('…/cm6.js').then(m => console.log(typeof m.EditorView))"`
  → `function`.
- [ ] Коммит «CodeMirror 6 для экрана урока — один файл, без интернета».

### Задача 9: страница — лента, «Подготовка», правка на месте

**Файлы:**
- `autoprint/efir/page/lesson.html` — разметка и стили.
- Создать модули в `autoprint/efir/page/lesson/`:
  - `app.js` — связь, состояние, режимы;
  - `render.js` — блоки и этапы, обновление по версиям;
  - `edit.js` — правка заметок, этапов, плана, «+», перенос, удаление, отмена, вставка картинок;
  - `code.js` — CodeMirror;
  - `queue.js` — очередь правок и `localStorage`.
- Создать: `tests/cdp.py` — headless Edge и клиент WebSocket на stdlib.
- Создать: `tests/test_page.py` (в `SCRIPT_TESTS`).

**Поведение — по проекту, раздел 3.** Решения сверх него:
- **Обновление по версиям.** Узел блока — `<div class="blk" data-id data-v>`. Пришло состояние: узлы с
  тем же `v` не трогаются; новые вставляются; удалённые убираются; порядок выравнивается перестановкой.
  Блок, который правят (`data-editing`), не перерисовывается.
- **Правка заметки** — `<textarea class="c">` с теми же CSS-переменными шрифта, что у `.c` роли, и
  `field-sizing: content` (запасной вариант — подгонка `scrollHeight`).
  - Сохранение: через 400 мс тишины и на `blur`.
  - После ответа — `innerHTML` из `items[id].html`.
- **Режим** («Подготовка» / «Урок») — в `localStorage` `suflor.mode`. Если урок идёт — «Урок».
- **Очередь правок** (`queue.js`) — каждое действие с `seq`; хранится в `localStorage`
  `suflor.pending.<lesson>`, пока нет `ok`; отправляется по одному. Ошибка сети или 503 → повтор через
  1, 2, 4 с (до 30 с). В шапке «Нет связи — правки ждут».
- **Заголовок документа:** `<урок> — Урок · AutoPrintCode` (для E13 — кончается на « — AutoPrintCode»).

- [ ] `tests/cdp.py`:
  - `class Edge` — `start(url) -> Edge`, `eval(js) -> value`, `wait(js, timeout=5)`, `key(text)`,
    `close()`;
  - запуск: `msedge --headless=new --remote-debugging-port=0 --user-data-dir=<tmp> --no-first-run about:blank`;
  - порт — из `<tmp>/DevToolsActivePort`;
  - WebSocket — `socket` + рукопожатие + кадры с маской;
  - нет Edge → `unittest.SkipTest`.
- [ ] Тест `PageEditTest.test_click_edit_same_height`: щелчок (`el.click()` через JS, не мышь) по заметке
  → есть `textarea`; |высота поля − высота показа| ≤ 2 px.
- [ ] Тест `PageEditTest.test_type_saves`: ввод «привет» (`Input.insertText`) → через ≤ 2 с текст блока в
  `store` содержит «привет». `blur` → `textarea` нет, в HTML «привет».
- [ ] Тест `PageEditTest.test_echo_keeps_caret`: во время правки программа публикует состояние (другой
  блок изменён) → `textarea` то же (тот же узел), `selectionStart` тот же.
- [ ] Тест `PageEditTest.test_other_nodes_kept`: пометить узлы всех блоков JS-свойством; изменить один
  блок в программе → у остальных пометка сохранилась.
- [ ] Тест `PageEditTest.test_plus_inserts_role`: «+» после блока → палитра → «Спроси» → в `store` новый
  блок `role == "ask"` после него.
- [ ] Тест `PageEditTest.test_minutes_in_plan`: в поле минут плана «12» и Enter → `stage.minutes == 12`,
  итог в плане пересчитан. Событие `wheel` над полем значение не меняет.
- [ ] Тест `PageEditTest.test_move_keys`: фокус на блоке, Alt+↓ → в `store` блок стоит после следующего.
  Перетаскивание строки плана (`move_stage`) — в том же тесте, через вызов функции переноса на странице.
- [ ] Тест `PageEditTest.test_delete_undo`: удалить блок → «Вернуть» → блок снова на месте с тем же `id`.
- [ ] Тест `PageEditTest.test_offline_queue`: остановить сервер, ввести текст, запустить сервер → правка
  дошла один раз. Вставка блока в офлайне → в `store` ровно один новый блок.
- [ ] Тест `PageEditTest.test_paste_image`: `ClipboardEvent('paste')` с PNG в `DataTransfer` → в `store`
  блок-картинка.
- [ ] Коммит «Экран урока: «Подготовка» — правка на месте, «+», перенос, удаление с «Вернуть», картинки
  через Ctrl+V».

### Задача 10: страница — код, «Урок», «Печать ⚙», шапка

**Файлы:** `autoprint/efir/page/lesson/code.js`, `app.js`, `render.js`, `lesson.html`; команды —
`autoprint/ui/lesson_control.py`.

- **Код.**
  - Щелчок в «Подготовке» — `EditorView` на месте `<pre>`: шрифт и `line-height` те же, `lineNumbers`,
    полоса шагов.
  - Полоса шагов: номер шага, цвет `hsl(step*47, 60%, 55%)`.
  - Alt+1…9 — шаг выделенным строкам, Alt+0 — новый шаг.
  - Выделение → `sel` через 400 мс.
  - Уход из поля — `destroy`, показ HTML.
  - Одновременно жив один редактор.
- **«Урок».**
  - Блок у указателя: «▶ Следующим · Ctrl+F9».
  - Во время печати — полоска хода и «Печатается · NN% · Ctrl+F9 — пауза».
  - По строкам и по шагам: `print.next_lines` подсвечены; `print.say` — плашка «Скажи: …» над кодом.
  - Последняя минута этапа — класс `.ending` (янтарный).
  - Щелчок по заметке ничего не делает.
- **Шапка.**
  - Список уроков (`lessons`) с поиском, «Новый урок».
  - «Подготовка | Урок».
  - «Печать ⚙» — режим, скорость (ползунок 60–1200), «Как человек», «Звук клавиш», «Комментарии:
    печатать / читать вслух», «Все настройки печати…».
  - ⋯ — Обозначения (из `roles`), Распечатать, Экспорт ▸, Оформление эфира, Распознать сценарий
    (с задачи 18), Удалить урок.
  - Значок сохранения.
- **Новые команды `/lesson/cmd`:**
  - `print_settings {key, value}` → `printer.set_option`;
  - `new_lesson` → `store.add("Новый урок")`, фокус, ответ через состояние;
  - `delete_lesson` (с подтверждением на странице) → удалить; фокус на первый урок;
  - `export {fmt}` — окно сохранения в Qt;
  - `settings {page}` — окно настроек;
  - `recognize`.
- **Начало урока.**
  - «Начать урок ▾» → «Сейчас» / поле ЧЧ:ММ.
  - Во время урока: «Начало ЧЧ:ММ», «Этап заново с этой минуты» (прежний `shift_now`), «Завершить».
  - Кнопка зарядки — только если `exercises`.

- [ ] Тест `PageLessonTest.test_arm_code_only`: в «Уроке» щелчок по заметке → `active_block` прежний.
  «Следующим» у кода → `active_block` этот код.
- [ ] Тест `PageLessonTest.test_print_popover`: «По шагам» в «Печать ⚙» → `settings.print_mode == "steps"`.
- [ ] Тест `PageLessonTest.test_code_edit`: щелчок по коду → есть `.cm-editor`; `Input.insertText("x=1")`
  → в `store` текст содержит `x=1`; второй щелчок по другому коду → `.cm-editor` один.
- [ ] Тест `PageLessonTest.test_no_exercise_button_without_video`: оформление без видео → кнопки
  «Включить зарядку» нет.
- [ ] Коммит «Экран урока: редактор кода, «Урок» со следующим к печати и ходом печати, «Печать ⚙»,
  список уроков».

### Задача 11: скорость и последняя проверка страницы

- [ ] Тест `PagePerfTest.test_big_lesson`: урок на 90 блоков (30 кодов по 15 строк, 50 заметок, 10 этапов)
  → от `apply(state)` до конца отрисовки < 300 мс (`performance.now()` вокруг `apply` на странице).
- [ ] Тест `PagePerfTest.test_typing_no_rerender`: 20 нажатий в заметку → число узлов `.blk`, созданных
  заново, — 0. Счётчик в `render.js` доступен как `window.__renders`.
- [ ] Коммит «Экран урока: быстрая отрисовка большого урока».

## Заход C — «Эфир»

### Задача 12: оформление отдельно от расписаний

**Файлы:** `autoprint/efir/model.py`, `autoprint/efir/store.py`, `autoprint/migrations.py`,
`autoprint/scenario.py` (`webinar_for`), `autoprint/ui/efir_control.py`.

**Интерфейсы:**
- `@dataclass Look`: `id`, `title`, `background`, `caption`, `exercises`, `break_countdown`,
  `break_background`, `break_title`, `break_show_title`, `break_done`, `font`, `text_color`.
  Есть `look_from_dict(d) -> Look` и `to_dict()`.
- `@dataclass Schedule`: `id`, `title`, `start`, `schedule: list[Activity]`, `look: str`, `break_min: int = 10`,
  `lesson_id: str`. Есть `schedule_from_dict(d)`.
- `compose(s: Schedule, look: Look | None) -> Webinar` — `Webinar` прежний: экран и таймер не меняются.
  У `Webinar` новое поле `look_id`.
- `split(w: Webinar) -> tuple[Schedule, Look]`.
- `EfirStore` (вместо `WebinarStore`; старое имя остаётся псевдонимом):
  - файлы `efir/looks.json` и `efir/schedules.json` (там же `live` и `brk`, см. задачу 13);
  - методы: `looks`, `schedules`, `look(id)`, `schedule(id)`, `put_look`, `put_schedule`, `remove_look`,
    `remove_schedule`, `visible() -> list[Schedule]` (без уроков), `get(id) -> Webinar | None`
    (собранный), `set_live`, `live`.
  - `webinars.json` читается только миграцией `looks_v10`, не пишется.
- `looks_v10` (в `migrations.apply`):
  - из каждого шаблона — `split`;
  - одинаковые `Look` (по полям без `id` и `title`) сливаются;
  - название — «Оформление · <название шаблона>»; служебные эфиры уроков (`lesson_id`) не переносятся;
  - `Template.look` и `settings.lesson_look` — по `preset` и `lesson_preset`;
  - `live` переносится, если его шаблон перенесён.
- `webinar_for(t, look)`: оформление — `look`; `break_min` — первый этап-перерыв, иначе 10.
- `EfirController.lesson_look(t) -> Look | None` вместо `lesson_preset`: `t.look` → `settings.lesson_look`
  → первое оформление.
- **Импорт и экспорт JSON расписаний:** `parse_webinars` возвращает `Webinar`; при импорте `split`:
  оформление создаётся, только если в JSON есть поля вида и они отличаются от стандартных.

- [ ] Тест `LooksTest.test_split_compose`: `compose(*split(w))` по `to_dict` без `id` и `look_id` равен `w`.
- [ ] Тест `LooksTest.test_migration`: `webinars.json` из двух шаблонов с одинаковым фоном и одного
  урочного → 1 оформление, 2 расписания. `webinars.json` не изменён. Урок с `preset` = id шаблона →
  `look` = id оформления. Повтор `apply` ничего не меняет.
- [ ] Тест `LooksTest.test_lesson_webinar`: урок с этапом-перерывом 15 мин → `webinar_for(t, look).break_min == 15`,
  фон из `look`.
- [ ] Коммит «Эфир: оформление отдельно от расписаний (looks.json, schedules.json), перенос из webinars.json».

### Задача 13: ошибки E4–E12, D1–D6

**Файлы:** `autoprint/efir/model.py`, `autoprint/ui/efir_control.py`, `autoprint/ui/efir_timer.py`,
`autoprint/ui/lesson_control.py`, `autoprint/efir/server.py`, `autoprint/efir/page/screen.html`,
`autoprint/ui/efir_window.py`, редакторы.

- **E8.** `anchor_at(hhmm, now)`: время в пределах последних 6 часов → сегодня; иначе ближайшее
  будущее (сегодня или завтра).
- **E5.** `LessonController._sync_live(t)`:
  - запомнить id блока текущего этапа и его начало по часам (`anchor + start_min`) до изменения;
  - после изменения — `anchor = начало − new_start_min(id)`;
  - если этапа больше нет — якорь прежний.
- **E6.**
  - `EfirController.start_break(minutes, ends_at: float | None = None)`.
  - Команда страницы `break {stage}`: этап идёт сейчас → `ends_at = anchor + end_min`; иначе — его минуты.
  - Без этапа — `webinar.break_min`.
  - На экране: `brk.done_hold_s = 60`. `screen.html` через 60 с после конца сама показывает фон.
  - Контроллер по таймеру (раз в 5 с) переводит `mode` в `idle`, если `now > brk_ends + 60`.
- **E7.** Кнопки зарядки нет, если у оформления нет `exercises`: страница и таймер (`_exercise_clicked`
  скрыт).
- **E9.** `EfirController.launch*` — если идёт другой эфир, `confirm_replace(cur_title, new_title) -> bool`
  через `QMessageBox`, на странице — `confirm()` перед командой. Отказ — ничего.
- **E4.** `Board.mouseDoubleClickEvent` и `row_activated` удалить; подсказку «Двойной щелчок…» убрать.
  В «⋯» таймера «Начать с блока…» — с вопросом.
- **E11.** `EditorWindow.closeEvent` / «Отмена» при `_changed()` — `QMessageBox` «Сохранить изменения?»
  (Сохранить / Не сохранять / Отмена).
- **E12.**
  - В `schedules.json` хранится `brk: {ends_at, total, seq}`, пока идёт перерыв. `restore()` возвращает
    `mode = break`, если `ends_at + 60 > now`.
  - Сервер стартует с `_states["screen"] = {"mode": "wait"}`; `screen.html` на `wait` ничего не меняет
    (остаётся прежний кадр).
  - `restore()` публикует настоящее состояние.
- **D1.** «Сдвинуть расписание» и «Сдвинуть на сейчас» → «Этап заново с этой минуты» (таймер, страница).
- **D2.** «Начать урок» — только на странице. В окне «Эфир» уроков нет (как сейчас).
- **D3.** Таймер: последняя минута — цвет `live` уже есть; на странице `.ending`.
- **D4.** `refresh_live`: `mode = idle` только если `mode == exercise` и номер вне списка.
- **D5.** Плашка «Эфир»: `mode == break` и `break_left() <= 0` → прежний текст урока.
- **D6.** `_states` получает `"preview": {}`. Мёртвые `anchor_for`, `next_in_s`, `lesson_clients`,
  `last_report` удалить.

- [ ] Тест `FixTest.test_anchor_rule`:
  - сейчас 07:00, «20:00» → сегодня 20:00;
  - сейчас 20:20, «20:00» → сегодня 20:00;
  - сейчас 23:50, «00:10» → завтра;
  - сейчас 03:00, «23:50» → вчера (в пределах 6 ч).
- [ ] Тест `FixTest.test_live_edit_keeps_stage`: урок 3 этапа по 10 мин, идёт 15-я минута (этап 2).
  Минуты этапа 1 → 20 → начало этапа 2 по часам прежнее. Удалили этап 2 → якорь прежний.
- [ ] Тест `FixTest.test_break_until_stage_end`: этап-перерыв 10 мин идёт с 3-й минуты →
  `brk_ends ≈ start + 10 мин`. Перерыв вне плана → `break_min`.
- [ ] Тест `FixTest.test_break_auto_background`: `brk_ends` 61 с назад → после `tick` `mode == "idle"`.
- [ ] Тест `FixTest.test_replace_asks`: идёт A, `launch(B)` при `confirm_replace` → False — идёт A.
- [ ] Тест `FixTest.test_restart_keeps_break`: `start_break(10)`, новый контроллер на той же папке →
  `restore()` → `mode == "break"`. До `restore` `server.snapshot("screen")["mode"] == "wait"`.
- [ ] Тест `FixTest.test_stale_exercise_keeps_break`: перерыв, у оформления убрали видео → `refresh_live`
  → `mode == "break"`.
- [ ] Тест `FixTest.test_editor_cancel_asks`: правка фона и «Отмена» → вопрос показан (заглушка).
- [ ] Коммит «Эфир: ошибки разбора — начало в 20:00, правка этапов не сбивает время, перерыв по плану
  и сам уходит, вопрос при замене эфира, перезапуск не виден ученикам».

### Задача 14: таймер — столько строк, сколько влезает

**Файлы:** `autoprint/ui/efir_timer.py`, `tests/test_v09.py` (`TimerTest`).

**Интерфейсы:**
- `agenda_slice(n: int, cur: int, fit: int) -> tuple[int, int]`:
  - `fit >= n` → `(0, n)`;
  - иначе одна строка до текущей (если `cur > 0`), дальше будущие: `a = max(0, min(cur - 1, n - fit))`,
    `b = a + fit`.
  - `agenda_window` удалить.
- `list_fit(height: float, n: int, scale: float = 1.0) -> int` — сколько строк по 24·scale влезает,
  с учётом строк «ещё N», если всё не влезло.
- `board_mode(w, h)`:
  - `hero`, если `h < 160` или `w < 260`;
  - `strip`, если `w >= 640 and h < 230 and w >= 2.6*h`;
  - `side`, если `w >= 560 and h >= 230`;
  - иначе `below`.
  - В `below` высота «сейчас» — `clamp(h*0.45, 110, 320)`.
- `_draw_list`: высота строки `clamp(avail/fit, 24, 56)`, без центрирования, сверху.
- `_draw_strip`: клеток `max(1, int((w + gap) // (120 + gap)))`, правило то же.

- [ ] Переписать `TimerTest.test_agenda_window` → `test_agenda_slice`:
  - `agenda_slice(13, 5, 20) == (0, 13)`;
  - `agenda_slice(13, 5, 4) == (4, 8)`;
  - `agenda_slice(13, 0, 4) == (0, 4)`;
  - `agenda_slice(13, 12, 4) == (9, 13)`.
- [ ] Тест `TimerTest.test_default_window_has_list`: `board_mode(440, 270) == "below"`; при высоте списка
  этого окна `list_fit` ≥ 3.
- [ ] Тест `TimerTest.test_tall_shows_all`: `list_fit(700, 13) == 13`.
- [ ] Коммит «Таймер: столько строк, сколько влезает; в окне по умолчанию — список».

### Задача 15: окно «Эфир» — «Расписания» и «Оформления», два редактора

**Файлы:**
- `autoprint/ui/efir_window.py` — две вкладки; карточки оформлений: фон, число зарядок, «Изменить»,
  «Дублировать», «Удалить» (нельзя, если на него ссылается расписание — сообщение).
- `autoprint/ui/efir_editor.py` → `ScheduleEditor`:
  - название, строки, «Оформление: [выбор]», «Перерыв по умолчанию N мин»;
  - JSON, нейросеть.
- `autoprint/ui/efir_editor.py` → `LookEditor`: фон, надпись, зарядки, перерыв (кроме минут), шрифт, цвет,
  предпросмотр.
- `EfirController.edit_live()`: урок → `LookEditor(lesson_look)`; вебинар → `ScheduleEditor`.

- [ ] Тест `EfirWindowTest.test_tabs`: две вкладки; в «Оформлениях» — карточки из `looks`.
- [ ] Тест `EfirWindowTest.test_look_editor_saves`: смена фона в `LookEditor` и «Сохранить» →
  `store.look(id).background` новый, расписания не тронуты.
- [ ] Тест `EfirWindowTest.test_cant_delete_used_look`: удаление оформления, на которое ссылается расписание,
  → оформление на месте.
- [ ] Перенести тесты `EfirEditorTest` в `test_v09.py` на новые классы (строки → `ScheduleEditor`,
  перерыв и фон → `LookEditor`).
- [ ] Коммит «Окно «Эфир»: расписания и оформления — отдельно».

## Заход D — содержимое, чистка, выпуск

### Задача 16: образцовый урок

**Файлы:**
- Создать: `autoprint/samples/lesson-example.md` и картинки рядом:
  - `lesson-example_files/func-scheme.png`;
  - `password-rules.png`;
  - `output-check.png`.
- `tools/make_sample_images.py` — рисует эти три (Qt offscreen, 1280×720, тёмные, крупный текст).
- Изменить: `autoprint/samples_lesson.py` — `lesson_sample() -> Template` читает .md через
  `lesson_md.parse`; `LESSON_SAMPLE_ID = "lesson_v2"`; `LESSON_TITLE = "Пример урока: функции и надёжный
  пароль"`.
- Удалить: `autoprint/samples.py`, пример шагов в `storage.py` (`STEPS_SAMPLE_*`, `steps_sample_template`),
  старые картинки `dark-*.png`. Перед удалением снять отпечатки (задача 17).

**Содержание** (Python, 90 мин; части «Первая половина» и «Вторая половина»):

| Этап | Мин | Что внутри |
|---|---|---|
| 1. Приветствие и цель | 4 | Говоришь, Задание (цель) |
| 2. Разминка: 3 вопроса | 5 | Спроси ×3 с ответами |
| 3. Теория: что такое функция | 8 | Термин «Функция», Термин «Аргумент», Расказ-история про повторяющийся код, картинка схемы |
| 4. Разбор 1: длина пароля | 8 | Говоришь, код `is_long`, Вывод, Ловушки |
| 5. Разбор 2: цифры и буквы | 8 | Расскажи, код `has_digit`/`has_letter`, Вывод, Делаешь |
| 6. Мини-задание 1 | 6 | Задание, Показываешь, Для быстрых |
| 7. Зарядка для глаз | 5 | вид «зарядка», Говоришь |
| 8. Перерыв | 10 | вид «перерыв», Говоришь |
| 9. Разбор 3: return и несколько проверок | 10 | Термин «return», код `check_password`, Вывод, Важно, картинка правил |
| 10. Разбор 4: подсказки пользователю | 10 | Расскажи, код `password_hints`, Вывод (картинка вывода) |
| 11. Мини-задание 2 | 10 | Задание, Ловушки, Для быстрых |
| 12. Итоги и домашнее задание | 6 | Спроси, Говоришь, Задание |

Итого 90 мин. Каждая роль хотя бы раз. Реплики — живая речь, как в «Занятии 6»; код рабочий.

- [ ] Тест `SampleTest.test_example` (переписать в `test_v09.py` → `test_v10.py`):
  - `total_minutes == 90`;
  - этапов 12; 1 перерыв, 1 зарядка;
  - все роли из `ROLE_ORDER` есть;
  - кодов ≥ 5, у каждого кода следующий блок — `output`;
  - картинок 3, все файлы есть;
  - весь код этапов 4, 5, 9, 10 выполняется `exec` без ошибок, печать перехвачена;
  - выводы в блоках `output` совпадают с напечатанным (`strip()`).
- [ ] Коммит «Образцовый урок: функции и надёжный пароль».

### Задача 17: примеры в базе — `samples_v10`

**Файлы:** `autoprint/migrations.py`, `autoprint/ui/main_window.py` (`_ensure_samples`).

- `SAMPLE_FINGERPRINTS: frozenset[str]` — sha1 от
  `json.dumps([(b.type, b.role, b.text, b.lang, b.title, b.minutes, b.stage_kind, b.part) for b in t.blocks])`
  для `tour_template()`, `steps_sample_template()` и старого `lesson_sample()` из 0.9. Снять скриптом
  до удаления генераторов, записать константой.
- `samples_v10`: удалить уроки с отпечатком из множества. `_ensure_samples` добавляет только `lesson_v2`
  (наверх), один раз.
- [ ] Тест `SamplesMigrationTest`:
  - база с точной копией старого примера, изменённой копией (одна заметка другая) и своим уроком →
    после `apply` остались изменённая копия, свой урок и новый образец;
  - повтор `apply` ничего не меняет.
- [ ] Коммит «Встроенные примеры: один образцовый урок; точные копии старых примеров убираются».

### Задача 18: распознавание сценарных тетрадок

**Файлы:**
- Создать: `autoprint/scenario_import.py`, `tests/data/scenario-sample.ipynb` — обезличенный фрагмент
  в формате «Занятия 6», 4 этапа.
- Изменить: `autoprint/importers.py` (`notebook`, `markdown_text`), `MainWindow`, страница.

**Интерфейсы:**
- `looks_like_scenario(blocks: list[Block]) -> bool` — ≥ 2 заголовков с ⏱.
- `recognize(t: Template) -> Template` — новый урок «<название> (сценарий)» по таблицам раздела 7 проекта.
  Исходный урок не меняется.
- Импорт .ipynb и .md → если `looks_like_scenario`, сразу `recognize`, название без «(сценарий)».
- «Распознать сценарий» в меню окна и в ⋯ страницы → копия рядом и открыть её.

- [ ] Тест `ScenarioTest.test_stages`:
  - 4 этапа с минутами из ⏱ (3, 5, 5, 10);
  - «ЗАРЯДКА ДЛЯ ГЛАЗ» → `exercise`;
  - «ПЕРЕРЫВ 10 МИНУТ» → `break`;
  - «Разминка, 5 вопросов» → обычный;
  - раздел «Первая половина» у первых этапов.
- [ ] Тест `ScenarioTest.test_roles`:
  - «🗣 **Говоришь, показывая на код:**» + цитата → `say` с `title == "показывая на код"`, без `> `;
  - «✅ **Ожидаемый вывод:** `1`» → `output` «1»;
  - «**Решение — показываешь через 4 минуты:**» → `do`;
  - ячейки кода остались кодом по порядку.
- [ ] Тест `ScenarioTest.test_copy`: `recognize(t)` → исходный `t.blocks` не изменились.
- [ ] Коммит «Сценарные тетрадки (⏱, 🗣, ✅) → урок с этапами и плашками».

### Задача 19: нейросеть, чистка, версия

**Файлы:** `autoprint/lesson_ai.py`, `autoprint/storage.py`, `autoprint/efir/model.py`, `autoprint/__init__.py`,
`README.md`, `installer/*.iss`.

- Подсказка сценария:
  - роли `term` и `output`;
  - `say` — «обязательно и дословно: определения, тезисы»;
  - `tell` — «своими словами»;
  - `task` — «Задание»;
  - фраза «печатается только код; всё остальное — подсказки преподавателю».
  - `_TYPE_ROLE` знает «термин», «вывод».
- Удалить `store_image_file`, второй `_code_number`, повторные `MODE_*`.
  `grep -rn "auto_advance\|show_prompter\|prompter_\|print_as\|PRINT_MARKDOWN" autoprint` → пусто, кроме
  поля `print_as` в `Block`.
- `__version__ = "0.10.0"`; версия в установщике; README — раздел «Как вести урок» под новый экран.
- [ ] Тест `AiTest.test_prompt_roles`: в подсказке есть «Термин», «Вывод», «печатается только код», нет «Условие».
- [ ] `tools/check.py` — всё зелёное, кроме «Веб: …» (нет `node_modules`).
- [ ] Коммит «0.10.0: подсказка нейросети под новые роли, чистка, версия».

### Задача 20: проверка всего, сборка, установка

- [ ] Финальное ревью ветки: свежий проверяющий на самой сильной модели. Пакет —
  `review-package <plan> <merge-base> HEAD`. Исправить Critical и Important (каждое — тест RED→GREEN).
- [ ] Скриншоты страницы в headless Edge: «Подготовка», «Урок», «Печать ⚙» — светлая и тёмная тема.
  Посмотреть самому; ничего на экран пользователя.
- [ ] Сборка: `build_exe.bat` → установщик `dist/…0.10.0….exe`.
- [ ] Установка у пользователя (разрешено: «установи сразу»):
  1. Проверить, что эфир не идёт: `%LOCALAPPDATA%\Programs\AutoPrintCode\data\efir\webinars.json` → `live`
     пусто или его конец в прошлом. Идёт — не ставить, сказать пользователю.
  2. Копия: `data\templates.json`, `data\media`, `data\efir`, `data\settings.json` →
     `%LOCALAPPDATA%\Programs\AutoPrintCode-backup-2026-11-24-v090`.
  3. Тихая установка `/VERYSILENT /CURRENTUSER`, код выхода 0.
  4. Удалить все уроки пользователя из установленной базы: программа закрыта; `templates.json` →
     `{"templates": []}` в формате файла. При запуске программа добавит образец, потому что
     `lesson_v2` ещё не в `samples_seen`.
  5. Запустить программу (окно программы — разрешено: «посмотрим»); проверить журнал: миграции прошли,
     в базе один урок.
- [ ] Обновить память: `v010-odin-ekran.md` — что сделано, где копия.
- [ ] Отправить ветку в форк.
