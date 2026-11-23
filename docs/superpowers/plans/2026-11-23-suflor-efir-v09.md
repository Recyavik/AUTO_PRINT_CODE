# Суфлёр и «Эфир» 0.9 — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Суфлёр, «Эфир» и редактор занятий без логических ловушек: тема без зависаний, колёсико не меняет
значения, начало эфира задаётся при запуске, суфлёр читается как PDF-пилот, пример урока, урок в Markdown.

**Architecture:** Правки по месту в существующих модулях; новое — `autoprint/lesson_md.py` (формат .md),
`autoprint/samples_lesson.py` + `autoprint/samples/*.png` (пример урока), `WheelGuard` в `ui/widgets.py`,
`StartPicker` в `ui/efir_start.py`. Тесты — `tests/test_v09.py` (в `tools/check.py`).

**Tech Stack:** Python 3.14, PySide6 6.11, http.server, ванильный JS.

**Spec:** `docs/superpowers/specs/2026-11-23-suflor-efir-v09-design.md`

## Global Constraints

- Тексты интерфейса — по-русски. Старые `templates.json`, `webinars.json`, `settings.json` читаются без потерь.
- Тесты невидимы: `tests/quiet.py`, offscreen, временный AUTOPRINT_DATA; без окон, трея, браузеров, кликов.
- Данные и установленную копию пользователя не трогать; GUI не запускать.
- Версия 0.9.0.

## Review Focus

- Смена темы, когда печать идёт из вкладки, которую выгружают из памяти: печать не обрывается, вид этой вкладки
  не удаляется, пока идёт печать.
- «Начать в ЧЧ:ММ», когда это время сегодня уже прошло (ведущий опоздал) или около полуночи (23:50 → 00:10):
  якорь — ближайшее разумное время (прошедшее сегодня — сегодня; если до него > 12 ч назад — завтра).
- .md: пробелы и кириллица в имени папки картинок, CRLF, картинки нет, неизвестная роль, ```-блок внутри
  цитаты — без исключений, неизвестное — обычный текст.
- Колёсико над редактором кода/текста в ленте: прокрутка ленты работает; в счётчике с фокусом колёсико меняет
  значение (как и раньше).
- Окно суфлёра закрыли руками → следующее «Суфлёр урока» открывает заново; Edge нет → браузер по умолчанию.

---

### Task 1: Колёсико не меняет значения без фокуса

**Files:** Modify `autoprint/ui/widgets.py` (+`WheelGuard`), `autoprint/ui/main_window.py` (установка на
приложение), `app.py` при необходимости; Create `tests/test_v09.py`; Modify `tools/check.py`.

**Interfaces:** Produces `widgets.WheelGuard(QObject)`; `widgets.install_wheel_guard(app) -> WheelGuard`
(идемпотентно). Счётчики/списки/ползунки получают `FocusPolicy.StrongFocus`.

- [ ] Тесты `WheelTest.test_unfocused_spin_scrolls_page` (QSpinBox в QScrollArea без фокуса, колесо вниз →
  value тот же, полоса прокрутки сдвинулась), `test_focused_spin_changes` (setFocus → value меняется),
  `test_unfocused_combo_unchanged`, `test_text_editor_wheel_not_blocked` (QPlainTextEdit — колесо доходит).
- [ ] RED → реализовать (фильтр событий приложения; колесо отдаётся полосе прокрутки ближайшей QAbstractScrollArea
  и событие съедается) → GREEN.

### Task 2: Тема без зависаний — лёгкая шапка блока, вкладки в памяти по требованию

**Files:** Modify `autoprint/ui/blocks.py` (шапка: `RoleChip` вместо `IconCombo`, меню по требованию вместо
`QComboBox` «окно»/«как печатать»/язык и вместо постоянных меню вставки), `autoprint/ui/main_window.py`
(`MAX_VIEWS = 2`, выгрузка вкладок, пересборка при смене темы), `autoprint/ui/theme.py`
(`about_to_change` перед `setStyleSheet`).

**Interfaces:**
- Produces `theme.about_to_change: Signal`; `MainWindow._evict_views(keep: str)`; `MainWindow._rebuild_views()`;
  `blocks.RoleChip(QToolButton)` с `set_role(key)`; `BlockWidget.type_requested` прежний.
- Consumes: TemplateView API (`block_widget`, `go_to_block`, полоса прокрутки).

- [ ] Тесты `ThemeTest.test_block_widget_count` (Markdown- и Code-блок ≤ 32 дочерних QWidget),
  `test_views_lru` (открыть 4 занятия → живых видов ≤ 2, текущий среди них), `test_running_job_view_kept`
  (job на вкладке A, открыть B, C → вид A жив), `test_theme_rebuild_keeps_place` (занятие 120 блоков, активный
  блок и прокрутка сохраняются, вид — новый объект), `test_theme_switch_fast` (120 блоков: смена темы < 3 с),
  `test_role_chip_menu` (действие меню → `type_requested(widget, "say")`).
- [ ] RED → реализовать → GREEN; повторить замер `repro_theme` на копии данных пользователя (ожидание ≤ 2,5 с
  для «Занятие 6», было 5–20 с).

### Task 3: Трей по умолчанию, одно окно суфлёра, логотип

**Files:** Modify `autoprint/storage.py` (`Settings.close_to_tray=True`, `Settings.migrations: list[str]`),
`autoprint/ui/main_window.py` (миграция `tray_v1`; закрытие окна суфлёра при выходе; логотип в шапке —
`logo.APP`), `autoprint/ui/lesson_control.py` (`PrompterWindow`: Popen со своим `--user-data-dir`
в `DATA_DIR/edge-suflor`, поднять живое окно, `close()`), `autoprint/efir/server.py` (`/favicon.svg`),
`autoprint/efir/page/lesson.html`, `screen.html` (`<link rel=icon>`, знак в шапке).

**Interfaces:** Produces `lesson_control.PrompterWindow(launch=subprocess.Popen)` с `open(url) -> bool`,
`alive() -> bool`, `close()`; `LessonController.shutdown()`; `logo.svg_mark() -> str`.

- [ ] Тесты `TrayTest.test_migration_turns_tray_on_once`, `PrompterWinTest.test_single_window`
  (поддельный Popen: второй `open` при живом процессе не запускает новый), `test_relaunch_after_closed`,
  `test_profile_dir_own`, `test_closed_on_shutdown`, `test_no_edge_falls_back`, `FaviconTest.test_favicon_served`.
- [ ] RED → реализовать → GREEN.

### Task 4: Начало эфира задаётся при запуске

**Files:** Create `autoprint/ui/efir_start.py` (`StartPicker` — всплывающее окно: «Сейчас», 2 ближайших :00/:30,
поле ЧЧ:ММ с прошлым временем); Modify `autoprint/efir/model.py` (`anchor_at(hhmm, now) -> datetime`),
`autoprint/ui/efir_control.py` (`launch(wid, start="")`, `set_start(hhmm)`, `launch_lesson(t, start="")`),
`efir_window.py` («Запустить» → StartPicker), `efir_timer.py` («Изменить начало…», убрать «Время по плану»),
`efir_editor.py` (без поля «Старт»), `lesson_control.py` + `lesson.html` («Начать сейчас» / «в ЧЧ:ММ»).

**Interfaces:** `model.anchor_at(hhmm: str, now: datetime) -> datetime` (прошедшее сегодня ≤ 12 ч — сегодня,
иначе завтра; ""/плохое → now); `EfirController.launch(wid: str, start: str = "") -> None` (start пусто — сейчас;
запоминает `w.start`, если задано); `EfirController.set_start(hhmm: str)`; `efir_start.quick_times(now) -> list[str]`.

- [ ] Тесты `StartTest.test_anchor_at_future_today`, `test_anchor_at_passed_today`, `test_anchor_at_midnight`
  (23:50 → «00:10» завтра), `test_launch_now`, `test_launch_at_remembers_start`, `test_set_start_moves_anchor`,
  `test_editor_has_no_start_field`, `test_quick_times` (17:12 → ["17:30","18:00"]), `test_lesson_start_at_cmd`
  (команда `{"cmd":"start","at":"18:00"}` → якорь 18:00).
- [ ] RED → реализовать → GREEN.

### Task 5: Редактор шаблона «Эфира»

**Files:** Modify `autoprint/efir/model.py` (`Webinar.break_show_title=True`, чтение/запись),
`autoprint/ui/efir_editor.py` (итог сверху, время от начала, кнопки-значки вида и демонстрации, несколько
зарядок, раздел «Перерыв» + «Надпись», «Предпросмотр», «Галерея фонов»), `autoprint/ui/efir_control.py`
(`preview_break(w)` → канал `preview`), `autoprint/efir/server.py` (канал `preview`),
`autoprint/efir/page/screen.html` (`?ch=`).

**Interfaces:** `EfirController.preview_break(w: Webinar) -> None`; `server.CHANNELS` += "preview".

- [ ] Тесты `EditorTest.test_total_on_top` («Всего 1 ч 30 мин · блоков: 12»), `test_row_times_relative`
  («0:00», «0:01», «0:06»…), `test_kind_button_sets_kind`, `test_demo_button_sets_demo`,
  `test_add_several_exercises`, `test_break_show_title_roundtrip`, `test_state_hides_title`
  (break_show_title False → `brk.title == ""`), `test_preview_published` (канал preview получил состояние перерыва).
- [ ] RED → реализовать → GREEN.

### Task 6: Таймер, кнопка «Эфир» в шапке, экран без подсказки

**Files:** Modify `autoprint/ui/efir_timer.py` (`agenda_window`, `board_mode`, полоса для широкого окна,
кнопка «Открыть вкладку»), `autoprint/ui/main_window.py` (плоская кнопка «Эфир», цвет по состоянию),
`autoprint/efir/page/screen.html` (без `#hint`).

**Interfaces:** `efir_timer.agenda_window(n: int, cur: int, k: int = 2) -> tuple[int, int]` (срез [a, b));
`efir_timer.board_mode(w: float, h: float) -> str` ("hero" | "side" | "below" | "strip");
`main_window.efir_token(phase: str, mode: str) -> str`.

- [ ] Тесты `TimerTest.test_agenda_window` (n=13,cur=0 → (0,3); cur=6 → (4,9); cur=12 → (10,13); n=3 → всё),
  `test_board_mode` (900×160 → strip; 700×400 → side; 300×500 → below; 200×80 → hero),
  `test_open_tab_button` (клиентов 0 → кнопка видна; 1 → скрыта), `test_efir_token`
  (нет эфира → "dim"; before → "accent"; live → "live"; live+break → "accent"), `test_screen_no_hint`.
- [ ] RED → реализовать → GREEN; снимки таймера 900×160, 700×420 (offscreen grab) — посмотреть глазами.

### Task 7: Суфлёр как PDF — плашки ролей

**Files:** Modify `autoprint/efir/page/lesson.html` (CSS ролей: фон-оттенок, полоса, подпись капителью со
значком и заголовком блока; «Говоришь» крупнее, «Делаешь» мельче/серее, «Для быстрых» пунктир; этап: плашка
времени, «ЭТАП N», значки вида; часть — плашка «ЧАСТЬ»), `autoprint/scenario.py` (в состоянии блока —
`title`, `label`).

- [ ] Тесты `PageTest.test_block_state_has_label_title` (роль say + заголовок «Повторение» → label «Говоришь»,
  title «Повторение»), `test_page_role_styles` (в lesson.html правила `.row.r-say` с background и `.lbl`).
- [ ] RED → реализовать → GREEN; снимок headless Edge (тёмная и светлая) — сравнить с PDF глазами.

### Task 8: Редактор занятий — картинка во всю ширину, цвет ролей

**Files:** Modify `autoprint/ui/blocks.py` (ImageBlockWidget: масштаб по ширине, до 520 px высоты, щелчок —
`ImageViewer`; без RoleChip у картинки и этапа; фон блока подкрашен ролью).

**Interfaces:** `blocks.ImageViewer(QDialog)`; `ImageBlockWidget.preview_size() -> QSize`.

- [ ] Тесты `EditorBlocksTest.test_image_fits_width` (картинка 3840×2160, блок 900 px → ширина превью ≥ 800),
  `test_image_height_capped`, `test_image_click_opens_viewer`, `test_no_role_chip_on_image_and_stage`.
- [ ] RED → реализовать → GREEN; снимок редактора с примером урока.

### Task 9: Пример урока с картинками

**Files:** Create `autoprint/samples_lesson.py`, `autoprint/samples/dark-site-light.png`, `dark-site-dark.png`,
`toggle-dialog.png` (рисуются `tools/make_sample_images.py`, коммитятся); Modify `main_window._ensure_samples`
(`LESSON_SAMPLE_ID = "lesson_v1"`), `tools/build_exe.py` (картинки в сборку и REQUIRED).

**Interfaces:** `samples_lesson.lesson_sample() -> Template` (картинки копируются в data/media через
`storage.media_ref`).

- [ ] Тесты `SampleTest.test_has_everything` (этапов ≥ 6, есть перерыв и зарядка, все 8 ролей суфлёра, код css/js/html,
  ≥ 3 картинки и файлы существуют), `test_added_once`, `test_sample_page_state` (lesson_state без ошибок, картинки
  с url).
- [ ] RED → реализовать → GREEN.

### Task 10: Урок в Markdown; картинки внутри .ipynb

**Files:** Create `autoprint/lesson_md.py`; Modify `autoprint/importers.py` (`.md` с разметкой урока →
`lesson_md.parse`; `export_ipynb` — картинки вложениями), `autoprint/ui/main_window.py` (экспорт «Урок в
Markdown (.md)…»).

**Interfaces:** `lesson_md.export_md(t: Template, path: Path) -> Path` (папка `<имя>_files` рядом);
`lesson_md.to_md(t, media_prefix: str) -> str`; `lesson_md.parse(text: str, base: Path | None, title: str) -> Template`;
`lesson_md.looks_like_lesson(text: str) -> bool`.

- [ ] Тесты `MdTest.test_roundtrip_sample` (пример урока → .md → разбор: те же типы, роли, минуты, виды,
  разделы, код и язык, подписи картинок), `test_images_copied_back`, `test_plain_md_unchanged` (обычный .md —
  как раньше), `test_unknown_role_text`, `test_russian_role_names`, `test_crlf_and_spaces`, `test_missing_image`,
  `IpynbTest.test_image_attachment` (ячейка с `attachments` и `![…](attachment:…)`).
- [ ] RED → реализовать → GREEN.

### Task 11: Картинка печатается в Jupyter (вставкой)

**Files:** Modify `autoprint/ui/main_window.py` (`_job_for_armed`: картинка → `{"kind": "image"}`; запуск —
буфер обмена + Ctrl+V после отпускания клавиш, не в своё окно).

**Interfaces:** `MainWindow._paste_image(path: Path) -> bool`.

- [ ] Тесты `PasteTest.test_image_job` (активный блок-картинка → job kind image), `test_paste_sends_ctrl_v`
  (поддельные `winapi.tap`/`foreground_window` → картинка в буфере, нажат Ctrl+V), `test_no_paste_into_self`.
- [ ] RED → реализовать → GREEN.

### Task 12: Версия, README, сборка

**Files:** `autoprint/__init__.py` (0.9.0), `README.md`, `tools/build_exe.py`.

- [ ] `python tools/check.py` — Python-этапы зелёные; сборка установщика; состав сборки проверен.
