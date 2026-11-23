# Суфлёр урока — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Урок = занятие AutoPrintCode с этапами, ролями-подсказками и картинками; живая страница-суфлёр в
браузере по часам «Эфира»; нейросеть раскладывает в этот формат методичку или презентацию.

**Architecture:** Формат — расширение `storage.Block/Template`. Чистая логика (план этапов, Markdown → HTML,
код → HTML, состояние страницы) — `autoprint/scenario.py`. Страница `efir/page/lesson.html` на сервере «Эфира»
(новый канал SSE `lesson`, команды `POST /lesson/cmd`). `ui/lesson_control.py` связывает главное окно,
«Эфир» и страницу. Время — скрытый шаблон «Эфира» из этапов урока.

**Tech Stack:** Python 3.14, PySide6 6.11 (QtPdf для PDF), Pygments, http.server, ванильный JS.

**Spec:** `docs/superpowers/specs/2026-11-23-suflor-uroka-design.md`

## Global Constraints

- Все тексты интерфейса — по-русски. Старые `templates.json` читаются без потерь (новые поля — по умолчанию).
- Сервер слушает только 127.0.0.1; весь пользовательский текст на странице экранируется; ссылки — только
  http(s), `target=_blank rel=noopener`.
- Команды страницы принимаются только с заголовком `X-Suflor: 1` и своим Host/Origin.
- Тесты невидимы: `tests/quiet.py`, offscreen, временный AUTOPRINT_DATA; никаких окон, трея, браузеров.
- Версия 0.8.0. Значки языков — SVG devicon (MIT), лежат в `autoprint/efir/page/lang/`.

## Review Focus

- Старое занятие без этапов: страница показывает блоки без времени, «Начать урок» скрыт, ничего не падает.
- Этап с 0 минут или урок, где сумма минут 0: деления на ноль нет, этап считается мгновенным.
- Текст с `<script>`, `"`/`'`, `javascript:`-ссылкой в Markdown: на странице — текст, не код и не ссылка.
- Картинка, файла которой больше нет: на странице — подпись «нет файла», а не битая ссылка/ошибка сервера.
- Ответ нейросети без кода, но с этапами — принимается; без этапов и без кода — понятная ошибка.

---

### Task 1: Формат урока и план этапов

**Files:**
- Modify: `autoprint/storage.py` (ROLES, Block, Template, `_template_from`)
- Create: `autoprint/scenario.py`
- Test: `tests/test_lesson.py` (новый; добавить в `tools/check.py`)

**Interfaces:**
- Produces: `BLOCK_STAGE = "stage"`, `BLOCK_IMAGE = "image"`; `Block.minutes: int = 0`,
  `Block.stage_kind: str = ""`, `Block.part: str = ""`; `Template.start: str = ""`, `Template.preset: str = ""`;
  ROLES += `say tell ask do important show trap extra` (значок, название, цвет);
  `scenario.STAGE_KINDS`, `scenario.Stage(index, block, start_min, end_min, blocks)`,
  `scenario.stages(t) -> tuple[list[Block], list[Stage]]` (блоки до первого этапа, этапы),
  `scenario.has_stages(t) -> bool`, `scenario.total_minutes(t) -> int`.

- [ ] **Step 1: тесты** `ModelTest.test_old_json_loads` (блок без новых полей → minutes 0, stage_kind ""),
  `test_roundtrip_new_fields` (stage/image/роль say через `asdict` → `_template_from`),
  `test_stages_split` (intro, 3 этапа 2+8+10 → start/end 0/2, 2/10, 10/20; блоки по этапам),
  `test_zero_minutes` (этапы 0 и 5 → total 5, без исключений).
- [ ] **Step 2:** запустить `python -m unittest tests.test_lesson -v` — падают (нет модуля).
- [ ] **Step 3:** поля и роли в storage; `scenario.stages/has_stages/total_minutes`.
- [ ] **Step 4:** тесты проходят.

### Task 2: Markdown и код → HTML, значки языков

**Files:** Modify `autoprint/scenario.py`; Create `autoprint/efir/page/lang/*.svg`; Test `tests/test_lesson.py`

**Interfaces:**
- Produces: `scenario.md_html(text: str) -> str` (заголовки, абзацы, списки -/1., **жирный**, *курсив*,
  `код`, ```-блоки, [текст](http…), голые http(s)-адреса; всё прочее экранировано);
  `scenario.ask_parts(text) -> tuple[str, list[str]]` (вопрос, строки «→ …»);
  `scenario.code_html(code, lang) -> str` (Pygments → `<span class="t-k">` и т.п.);
  `scenario.lang_info(lang) -> tuple[str, str]` (подпись, имя файла значка или "").

- [ ] **Step 1: тесты** `HtmlTest.test_escape` (`<script>` → `&lt;script&gt;`), `test_js_link_not_link`
  (`[x](javascript:alert(1))` → нет `href="javascript`), `test_links` (голый `https://a.b/c` и
  `[a](https://x.y)` → `<a href="https://…" target="_blank" rel="noopener">`), `test_lists_bold_code`,
  `test_ask_parts` («Вопрос?\n→ ответ» → ("Вопрос?", ["ответ"])), `test_code_html_classes`
  (`def f(): pass`, python → есть `t-k`, текст не потерян), `test_lang_info` (python → ("Python","python.svg");
  "brainfuck" → ("brainfuck", "")).
- [ ] **Step 2–4:** реализовать, скачать SVG devicon v2.16.0 (python, javascript, typescript, html5, css3,
  java, kotlin, csharp, cplusplus, c, go, rust, php, bash, powershell, sqlite→sql нет — текстом, json, yaml,
  markdown, swift, dart, ruby, lua), проверить содержимое (без `<script>`), тесты зелёные.

### Task 3: Материалы — PDF, DOCX, PPTX, текст

**Files:** Create `autoprint/materials.py`; Test `tests/test_lesson.py`

**Interfaces:**
- Produces: `materials.Material(text: str, pdf: str | None, pages: int)`;
  `materials.extract(path: str) -> Material` (PDF — «=== Страница N ===» перед текстом каждой страницы,
  PPTX — «=== Слайд N ===», DOCX — абзацы, прочее — текст utf-8/cp1251);
  `materials.render_page(pdf: str, page: int, out_dir: Path, width: int = 1280) -> Path | None`.
- [ ] **Step 1: тесты** `MaterialsTest.test_docx` (docx собран zipfile'ом из двух абзацев → оба в тексте),
  `test_pptx` (2 слайда → «=== Слайд 2 ===» и текст), `test_pdf_text_and_render` (PDF из QPdfWriter с
  «Привет» на 2 страницах → текст, pages == 2, render_page(…, 2) → PNG существует), `test_txt_cp1251`.
- [ ] **Step 2–4:** реализовать (DOCX/PPTX — `zipfile` + `xml.etree`, PDF — `QPdfDocument.getAllText`,
  `render`), тесты зелёные.

### Task 4: Нейросеть — «Сценарий урока»

**Files:** Modify `autoprint/lesson_ai.py`; Test `tests/test_lesson.py`

**Interfaces:**
- Consumes: Task 1 поля, `materials.render_page`.
- Produces: `STYLE_SCENARIO = "scenario"` (в STYLES как «Сценарий урока»); `Options.minutes: int = 90`,
  `Options.break_min: int = 0`; `instruction(opt)` для сценария (типы блоков, правила, пример из «Тёмной
  темы»); `parse_lesson(text, …, slide=None)` где `slide: Callable[[int], str | None]` даёт путь картинки
  слайда; версия 2: `stage` (`min`/`minutes`, `kind`, `part`, `note`), роли, `ask.answer` → «→ » строки,
  `image` (`slide` | `url` | `path`, `caption`); код не обязателен, если есть этапы.
- [ ] **Step 1: тесты** `ScenarioAiTest.test_prompt_mentions_blocks` (в промпте `"stage"`, `"say"`, `"ask"`,
  90 минут), `test_parse_scenario` (2 этапа, say, ask+answer, code css, image slide 3 → slide-функция вызвана с 3,
  блок image с её путём; `active_block` — первый код), `test_parse_no_code_ok`, `test_parse_nothing_error`
  (ни этапов, ни кода → LessonError), `test_unknown_type_warns`.
- [ ] **Step 2–4:** реализовать, тесты зелёные; старые тесты `tests/test_lesson_ai.py` зелёные.

### Task 5: Сервер — каналы, статика, команды

**Files:** Modify `autoprint/efir/server.py`; Test `tests/test_lesson.py`

**Interfaces:**
- Produces: `BroadcastServer.publish(state, channel="screen")`, `snapshot(channel="screen")`,
  `wait_change(rev, timeout, channel="screen")`; `GET /lesson` → `page/lesson.html`; `GET /events?ch=lesson`;
  `GET /static/lang/<имя>.svg` (только `[a-z0-9+#-]+\.svg` из папки lang); `POST /lesson/cmd` → `on_command(dict)`
  только при `X-Suflor: 1` и Origin своём или пустом (иначе 403).
- [ ] **Step 1: тесты** `ServerTest.test_lesson_channel` (publish lesson не меняет screen; SSE `?ch=lesson`
  отдаёт lesson), `test_static_lang` (python.svg → 200 image/svg+xml; `../server.py` → 404),
  `test_cmd_requires_header` (без заголовка → 403, с ним → on_command получил dict),
  `test_cmd_foreign_origin` (Origin http://evil → 403).
- [ ] **Step 2–4:** реализовать, тесты зелёные; `tests/test_efir.py` зелёные.

### Task 6: «Эфир» по этапам урока

**Files:** Modify `autoprint/efir/model.py` (Webinar.lesson_id), `autoprint/efir/store.py` (`visible()`),
`autoprint/ui/efir_window.py` (список без уроков), `autoprint/ui/efir_control.py`; Test `tests/test_lesson.py`

**Interfaces:**
- Produces: `Webinar.lesson_id: str = ""`; `WebinarStore.visible() -> list[Webinar]`;
  `scenario.webinar_for(t, preset: Webinar | None) -> Webinar` (id `"lesson-" + t.id`, schedule из этапов,
  оформление из preset); `EfirController.launch_lesson(t, start_now: bool)`; `EfirController.live_lesson_id() -> str`.
- [ ] **Step 1: тесты** `EfirLessonTest.test_webinar_for` (этапы 2/8/10 break → schedule с kind break, фон
  пресета), `test_hidden_in_list` (store.visible() без lesson_id), `test_launch_lesson` (live.webinar_id ==
  "lesson-…", anchor ≈ сейчас).
- [ ] **Step 2–4:** реализовать, тесты зелёные.

### Task 7: Состояние страницы и сама страница

**Files:** Modify `autoprint/scenario.py`; Create `autoprint/efir/page/lesson.html`; Test `tests/test_lesson.py`

**Interfaces:**
- Produces: `scenario.lesson_state(t, *, live_anchor_ms: int | None, armed: str, media_url, presets,
  preset: str, dark: bool, efir_mode: str, tab: str) -> dict` —
  `{"lesson": {"id","title","total","start","has_stages","intro":[blk],"stages":[{"i","title","minutes",
  "kind","part","note","start","end","blocks":[blk]}],"presets":[{"id","title"}],"preset"},
  "live": {"anchor": ms} | None, "armed", "dark", "efir": {"mode","tab"}}`;
  блок `{"id","role","html"}` | `{"id","role":"code","lang","label","icon","html"}` |
  `{"id","role":"image","url","caption","missing"}`.
- Страница: вёрстка макета v3 (значки ролей, «Обозначения», план слева, свёртка этапов по времени, «осталось»,
  код со значком языка и отметкой «Печатается следующим», картинка — крупно по щелчку, кнопки «Начать урок»,
  «Сдвинуть на сейчас», «Завершить», «Включить перерыв/зарядку», «Распечатать»; светлая и тёмная тема; печать).
- [ ] **Step 1: тесты** `StateTest.test_state_stages` (времена этапов, роли блоков, armed), `test_state_no_stages`
  (has_stages False, всё в intro), `test_state_missing_image` (missing True, url ""), `test_state_escapes`.
- [ ] **Step 2–4:** реализовать, тесты зелёные; headless Edge (свой профиль) — снимки страницы до урока,
  во время, печать; проверить глазами.

### Task 8: Контроллер урока и главное окно

**Files:** Create `autoprint/ui/lesson_control.py`; Modify `autoprint/ui/main_window.py`,
`autoprint/ui/template_view.py` (кнопка «Суфлёр урока»); Test `tests/test_lesson.py`

**Interfaces:**
- Consumes: Tasks 5–7.
- Produces: `LessonController(main)`: `current() -> Template | None` (урок в эфире, иначе открытый),
  `publish()`, `schedule_publish()` (через 300 мс), `open_page()` (Edge `--app`, иначе браузер),
  `command(d: dict)` (start, stop, shift_now, start_at i, arm bid, break min, exercise i, background,
  set start/preset), `url`; сигнал `TemplateView.suflor_requested`.
- [ ] **Step 1: тесты** `ControllerTest.test_publish_current` (MainWindow offscreen, открытый урок → состояние
  на канале lesson), `test_cmd_arm` (arm → active_block), `test_cmd_start_stop` (start → эфир с lesson_id;
  stop → нет эфира), `test_edit_republishes`.
- [ ] **Step 2–4:** реализовать, тесты зелёные.

### Task 9: Редактор — этапы, картинки, роли

**Files:** Modify `autoprint/ui/blocks.py`, `autoprint/ui/template_view.py`, `autoprint/ui/theme.py`,
`autoprint/ui/icons.py`, `autoprint/ui/prompter_control.py` (`_intro` — только markdown),
`autoprint/importers.py` (export_ipynb: этап → `## …`, картинка → `![подпись](путь)`, `students=True` — без
подсказок учителя), `autoprint/ui/main_window.py` (меню «Экспорт тетрадки для учеников»); Test `tests/test_lesson.py`
- Produces: `StageBlockWidget`, `ImageBlockWidget`; `make_block_widget` для четырёх типов; кнопки
  «Текст · Код · Этап · Картинка»; время этапа в шапке «0:10–0:20».
- [ ] **Step 1: тесты** `EditorTest.test_view_builds_all_types`, `test_stage_minutes_edit` (спин → block.minutes,
  changed), `test_image_from_file` (копия в data/media), `test_change_type_to_stage`, `test_export_students`
  (say/ask/do нет, код и условие есть).
- [ ] **Step 2–4:** реализовать, тесты зелёные; `tests/ui_sweep.py`, `ui_regress.py`, `ui_smoke.py` зелёные.

### Task 10: Импорт — «Сценарий урока»

**Files:** Modify `autoprint/ui/import_dialog.py`; Test `tests/test_lesson.py`
- Produces: в «С помощью нейросети» вид «Сценарий урока» (длительность, перерыв; прочие опции скрыты),
  «Из файла…» понимает PDF/DOCX/PPTX (материал + слайды PDF для `slide: N`).
- [ ] **Step 1: тесты** `ImportTest.test_scenario_options` (минуты/перерыв в Options), `test_answer_parsed`
  (вставленный ответ v2 → `_ai_parsed` с этапами).
- [ ] **Step 2–4:** реализовать, тесты зелёные.

### Task 11: Выпуск

- [ ] `__version__ = "0.8.0"`; README — раздел «Суфлёр урока»; `tools/build_exe.py` — `page/*.html`,
  `page/lang/*.svg` в datas и REQUIRED; `tools/check.py` — `test_lesson`.
- [ ] Полный прогон: `python tools/check.py` — всё зелёное.
- [ ] Сборка exe и установщика, offscreen-проверка собранного exe.
- [ ] Коммит в `redesign-pastetalk-ui`, push в `fork`.
