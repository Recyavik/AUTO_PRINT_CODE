# Решения по ходу и итоговый разбор — AutoPrintCode 1.0 «одним окном»

Журнал исполнения плана [2026-11-25-v1-odno-okno.md](2026-11-25-v1-odno-okno.md): что сделано по задачам, решения (`Ruling:`), итоговый разбор, отложенные мелочи.

```text
# SDD ledger — plan: docs/superpowers/plans/2026-11-25-v1-odno-okno.md

Spec: docs/superpowers/specs/2026-11-25-v1-odno-okno-design.md (reachable).

## Pre-flight
| Tasks | Produces → consumes | Found |
|---|---|---|
| 1 → 2 | AppWindow(app, web) needs app.settings, app.efir.server | App provides both — ok |
| 2 → 3 | App.changed(str), App.navigate(str) | ok |
| 3 → 4,5 | core.js send/call/on/go | ok |
| 4 → 5,6… | ui.js menu/ask/sheet/popover | ok (menu is in ui.js, plan T6 cites T5 — same module set) |
| 2 → 10 | App.export_template(t, fmt, path) vs LessonController cmd "export" calls export_template(t, fmt) | conflict |
| 11 → 13 | Jobs.start/cancel | ok |
| 8 → 12 | screenctl, #typingBar | ok |
| 13 → 14 | copy_all_media | ok |

Pre-flight: Ruling: App.export_template(t, fmt, path: str | None = None) — path None opens native QFileDialog itself (T2); page sheet passes the path from T10 on — keeps old "export" command working between tasks — cost if wrong: none, signature is a superset.

## Tasks
Task 1: complete (commits 1388483..fa863dd, tests: .venv/Scripts/python.exe tests/test_app_shell.py → OK)
Task 1: Ruling: tools/build_exe.py got --out DIR (trial builds outside dist\) — the released 0.12.0 installer in dist\ must not be overwritten by a half-done build — cost if wrong: none.
Task 1: Ruling: Settings.compact / compact_geometry added in T1 (plan put them in T17) — AppWindow.set_compact needs storage now — cost: none.
Task 1: Ruling: --selftest code in app.py is committed with Task 2 (app.py also switches to App there) — cost: T1 commit alone lacks the CLI flag, the build check used the working tree.
Task 1: note: trial build 0.12.0+WebEngine: folder 398.7 MB, zip 163 MB, Setup 112.9 MB, --selftest passed. PySide6/qml (23.8 MB) and QtOpenGL.pyd (8.3 MB) look unneeded — try dropping in Task 18 with --selftest.
Task 2: complete (commits fa863dd..54b16b7, tests: .venv/Scripts/python.exe /d/Project/Auto_Rpint/.superpowers/sdd/2026-11-25-v1-odno-okno/run.py test_app_core test_v09 test_v10 test_v11 test_v12 test_lesson test_page test_engine ui_regress ui_import → ALL OK)
Task 2: Ruling: App was written before its tests (during the T1 build wait) — verified the tests bite by removing navigate.emit: 2 tests failed, restored — cost: none beyond process.
Task 2: Ruling: снято по замыслу — test_v09.PrompterWinTest (6), test_v10 test_page_window_pid_registered, test_v12 OneWindowTest.test_page_window_not_launched_twice — окно Edge-суфлёра удалено — cost: none.
Task 2: Ruling: перенесено в T6 — test_v10 test_library_meta («15 мин · 2 этапа · 2 кода», «без кода»), test_v12 LibraryTest (группы «Планы/Уроки», meta плана «План · 1 ч 5 мин · 4 этапа · уроков: 1», поиск прячет пустую группу, меню плана/урока), OneWindowTest.test_double_click_opens_lesson_once — список уроков теперь страница.
Task 2: Ruling: перенесено в T8 — test_v10 test_print_bar_resume_counts_down (resume = (0.0, 3) отсчёт) и test_print_bar_pause_stays_paused (pressed→автопауза, click не продолжает) — строка печати теперь полоса набора страницы.
Task 2: Ruling: снято по замыслу — test_v09 test_title_logo_is_brand (знак рисует страница, T5), test_efir_token (плашки «Эфир» нет), test_v11 «Новый урок ▾» меню (вместо меню — шаги, T11), test_v12 test_library_button_opens_lesson_tab (кнопки «Из методички» нет, T11).
Task 2: Ruling: test_v10 test_session_page больше не проверяет page_open (урок всегда в окне; сессия экрана — T17 last_view).
Task 2: Ruling: tests/ui_smoke.py, ui_sweep.py удалены — снимки и обход окон Qt; снимки нового окна — T18 tools/screens.py, «одно окно, нет лишних окон» — ui_regress (StraySpy теперь ждёт только AppWindow) — cost: обход старых диалогов (настройки, эфир) до их замены не проверяется.
Task 2: Ruling: ui_import открывает старые ImportDialog/SettingsWindow прямо из теста (helpers open_import/open_settings_window) до T11/T14 — App не держит временный код старых окон.
Task 2: Ruling: open_lesson(ask=True) при идущем другом уроке не спрашивает QMessageBox, а шлёт notice с action {"cmd":"open","lesson":id,"force":true}; страница переспрашивает — cost: до T5 вопрос виден только в старой странице /lesson тостом.
Task 2: Ruling: ui_scale больше не ставит QT_SCALE_FACTOR (масштаб — страница); миграция значения — T17.
Task 3: complete (commits 54b16b7..8c59abf, tests: .venv/Scripts/python.exe /d/Project/Auto_Rpint/.superpowers/sdd/2026-11-25-v1-odno-okno/run.py test_app_core test_app_page test_app_shell → ALL OK)
Task 4: Ruling: шрифты — вариативные woff2 (по два файла на шрифт: cyrillic + latin, с unicode-range) вместо Onest-{400..700} и JetBrainsMono-{400,600} — меньше файлов, любые начертания; лицензии OFL-Onest.txt, OFL-JetBrainsMono.txt — cost: none.
Task 4: Ruling: tools/screens.py создан в T4 (план — T18), чтобы смотреть вид по ходу — cost: none.
Task 4: Ruling: точка входа страницы — page/app/main.js (views, тема, масштаб, уведомления); витрина #/dev/ui — page/app/devui.js — cost: none.
Task 4: complete (commits 8c59abf..387292c, tests: .venv/Scripts/python.exe /d/Project/Auto_Rpint/.superpowers/sdd/2026-11-25-v1-odno-okno/run.py test_app_page test_app_shell test_app_core → ALL OK)
Task 5: Ruling: меню разделов скрыто и в «Новом уроке» (не только в уроке и маленьком режиме) — так на макете NewStep; шаги во всю ширину — cost: меньше переходов из мастера.
Task 5: Ruling: временные экраны (page/app/placeholders.js) для «Уроков», «Нового урока», «Эфира», «Настроек» до их задач; сборка до конца плана не ставится — cost: none.
Task 5: Ruling: масштаб для областей окна страница считает сама (innerWidth / ширина <html> в getBoundingClientRect) — разные Chromium по-разному учитывают CSS zoom — cost: none.
Task 5: Ruling: «Аа» в шапке — размер и «План урока: Сбоку / Сверху / Скрыть» (не отдельные значки в заголовке плана — они добавятся в T7 рядом с планом).
Task 5: complete (commits 387292c..a15a11f, tests: .venv/Scripts/python.exe /d/Project/Auto_Rpint/.superpowers/sdd/2026-11-25-v1-odno-okno/run.py test_app_page test_app_shell test_app_core → ALL OK)
Task 6: Ruling: урок в списке открывается одним щелчком (строки — как ссылки на макете) или Enter; двойной щелчок не открывает дважды (защита 700 мс) — план говорил «двойной щелчок или Enter» — cost: случайный щелчок открывает урок (безопасно: идущий урок спрашивает).
Task 6: Ruling: «Продолжить» — последний открытый урок, иначе урок в фокусе (не план) — cost: none.
Task 6: Ruling: найдена и исправлена потеря сообщений — несколько notify за 150 мс показывали только последнее; теперь state.notices (последние 6) и notice_action ищет по seq (test_notice_toast_with_action поймал) — cost: none.
Task 6: note: коммит 6c6b58c ушёл при красном test_app_page (цепочка команд не проверила результат); исправлено в следующем коммите.
Task 6: complete (commits a15a11f..d9a464c, tests: .venv/Scripts/python.exe /d/Project/Auto_Rpint/.superpowers/sdd/2026-11-25-v1-odno-okno/run.py test_app_library test_app_page test_app_core test_app_shell → ALL OK)
Task 7: Ruling: при плане «Сверху» или «Скрыть» правка минут — в заголовке этапа (кнопка минут), план сбоку не навязывается; «Поставьте этапам минуты» ставит курсор туда — cost: none.
Task 7: Ruling: значение page_plan "top" добавлено в PREFS lesson_control (старое "strip" принимается и показывается как «Сверху» до миграции T17).
Task 7: Ruling: найдено и исправлено зацикливание «экран урока просит open → программа navigate → снова open» (30 открытий); экран просит открыть урок один раз, go() с тем же адресом ничего не делает, open_lesson публикует урок сразу — cost: none.
Task 7: Ruling: время начала не назначено — в полосе только кнопка «Начать в… ▾» (без подписи «Начало в»), назначено — «Начало в» + «18:00 ▾» — cost: none.
Task 7: complete (commits d9a464c..8da9dfc, tests: .venv/Scripts/python.exe /d/Project/Auto_Rpint/.superpowers/sdd/2026-11-25-v1-odno-okno/run.py test_app_lesson test_app_library test_app_page test_app_core test_page → ALL OK)
Task 8: Ruling: полоса набора шлёт отдельные команды typing pause|resume|next|stop вместо toggle(pressed=True)+remember_press при активации окна — щелчок по окну сам ставит набор на паузу, отдельная «Пауза» никогда не продолжает набор — цена ошибки: нет известной; трей по-прежнему через remember_press.
Task 8: Ruling: .pulse держится (анимация 4 раза, потом ровный цвет) до щелчка по значку, смены экрана или этапа — бриф «один раз»; ровная подсказка не теряется — цена: лёгкий визуальный шум.
Task 8: Ruling: render.js получил хук decor.code; старая .armbtn остаётся для старой страницы /lesson до Task 9.
Task 8: Ruling: «Слайд» нажатый — щелчок возвращает фон (как B); перерыв: 5/10/15/20 показываются всегда (как в брифе), даже если совпадают с «По плану».
Task 8: Ruling: переключатель minimize_on_type в интерфейсе — в Настройках (Task 14); поле и поведение есть уже сейчас. В состояние урока добавлены break_left, ex_paused, screen_bg, button_countdown.
Task 8: Ruling: тест test_status_not_started_with_start_at ждал старый текст — ждёт «Начало в» (гонка теста, не кода).
Task 8: complete (commits 8da9dfc..dbb8315, tests: .venv/Scripts/python.exe .superpowers/sdd/2026-11-25-v1-odno-okno/run.py test_app_lesson test_app_core test_page test_v10 → ALL OK)
Task 9: Ruling: тесты правки — в отдельном tests/test_app_edit.py (бриф: test_app_lesson.py) — файл урока и так большой; ScreenImageTest переехал в test_app_lesson.py — цена: нет.
Task 9: Ruling: id полосы плана оставлен #planbanner (бриф #planBanner) — так он назван в Task 7 — цена: нет.
Task 9: Ruling: меню правки (state.js menu, body > .menu) оставлены, оформлены как меню окна (Task 7) — не переписаны на ui.js — цена: два кода меню до финальной полировки.
Task 9: Ruling: не перенесены тесты убранного: план строкой «План ▾», «Закрепить сбоку», «Аа», старый чип статуса, «Печать ⚙» (заменён «▾» набора, Task 8), заголовок «только для вас»; печать, ответ нейросети, «Свернуть этапы» — в Task 10 (меню урока); Ctrl+= — Task 5.
Task 9: Ruling: урок завершили (тот же урок) — правка снова включается; «Выбрать файл…» — app call place_image (файл читает программа); ссылка «по плану ↗» под названием убрана — у урока по плану «Изменить план» внизу плана и тост с «Изменить план» на минутах/названии этапа.
Task 9: complete (commits dbb8315..3afefbc, tests: .venv/Scripts/python.exe .superpowers/sdd/2026-11-25-v1-odno-okno/run.py test_app_edit test_app_lesson test_lesson test_v09 test_v10 → ALL OK)
Task 10: Ruling: тесты листов написаны до кода, но не запущены красными до реализации (отступление от TDD) — после реализации зелёные; настоящий printToPdf проверен отдельным невидимым процессом (PdfRealTest, %PDF-) — цена: тест мог бы пройти и без кода, частично закрыто ручной сверкой текстов.
Task 10: Ruling: «Открыть» (и «Новый урок по плану» у плана) — только в меню «Уроков» (lessonMenuItems o.open); в шапке урока — список из брифа; «План урока…» у самого плана не показывается.
Task 10: Ruling: «Печать или PDF» из «Уроков» сначала открывает урок (печатается экран урока); «Подставить слайды» — pick_files + call slides_fill (старый _fill_slides с QFileDialog(App) удалён — был сломан); команда export экрана урока удалена, chat_prompt/apply_answer оставлены для старых тестов.
Task 10: Ruling: найдена гонка Task 6 (двойной щелчок открывал урок дважды: экран урока просил открыть до прихода канала урока) — focusWanted учитывает S.focus_id; run.py сохраняет журнал упавшего набора (fail-<имя>.log). Один раз test_app_sheets упал в общем прогоне и не воспроизвёлся за 7 прогонов.
Task 10: complete (commits 3afefbc..5054f52, tests: .venv/Scripts/python.exe .superpowers/sdd/2026-11-25-v1-odno-okno/run.py test_app_sheets test_app_library test_app_lesson test_v12 → ALL OK)
Task 11: Ruling: Claude Code с файлами — «--tools Read --allowedTools Read» (allowedTools сверх спецификации: без него печатный режим может ждать разрешения) — цена: очень старый Claude Code без --allowedTools не запустится.
Task 11: Ruling: агенту уходят как есть только файлы, которые он читает (pdf, txt, md, код, картинки); .docx/.pptx — всегда текстом (materials.extract) — цена: картинки внутри Word агент не увидит.
Task 11: Ruling: «Скопировать задание» в карточке нейросети — под «Спросить свой чат вместо этого» (раскрывается), ответ, вставленный туда, собирает урок без нейросети программы; задание без материала с темой: «материал может быть приложен, иначе — по теме» (source attached_or_topic).
Task 11: Ruling: удачная фоновая работа исчезает через 6 с, ошибка — до «Закрыть»; выбор плана сбрасывается к последнему выбранному при каждом новом входе в «Новый урок», остальные поля мастера живут до закрытия программы.
Task 11: Ruling: ui_import.py сокращён до «⚙ → Нейросеть» (переедет в Task 14); тесты окна импорта из test_lesson / test_v10 / test_v11 / test_v12 перенесены на wizard.py и App.import_paths / add_new_lesson.
Task 11: complete (commits 5054f52..3b4ba98, tests: .venv/Scripts/python.exe .superpowers/sdd/2026-11-25-v1-odno-okno/run.py test_wizard_core test_app_wizard test_lesson test_v11 test_v12 ui_import → ALL OK)
Task 12: Ruling: в маленьком режиме шапка окна скрыта, на табло только «Большой режим» (без свернуть/закрыть) — места мало; закрыть можно из трея — цена: привычного «×» нет.
Task 12: Ruling: экран учеников на табло — свои простые меню (перерыв: по плану / 5–20 / +5 +1 −1 / пауза / убрать; зарядка: список, пауза, сначала), а не меню полосы урока — табло работает и без открытого экрана урока; у вебинара без урока в фокусе значки не показываются.
Task 12: Ruling: «Следующий этап» — команда live_next (efir.start_now), одна для урока и вебинара; до начала — «Начать сейчас»; найдено: sendRegions пропускал fixed-элементы (offsetParent) — видимость по getClientRects.
Task 12: complete (commits 3b4ba98..d03871f, tests: .venv/Scripts/python.exe .superpowers/sdd/2026-11-25-v1-odno-okno/run.py test_app_compact test_app_shell → ALL OK)
Task 13: Ruling: тесты media_copy написаны первыми, но модуль появился сразу следом без отдельного красного прогона (кроме отсутствия модуля); страница «Эфир» — тесты до кода, красный прогон пропущен ради объёма — цена: как у Task 10.
Task 13: Ruling: старые Qt-тесты окон эфира (StartPicker, EditorWindow, TimerWindow, EfirWindow) удалены, их смысл перенесён: test_app_efir (страница), test_efir/test_v09/test_v10 (контроллер: put_webinar/put_look/delete_look/force), test_app_compact (табло вместо таймера); agenda_slice/list_fit/board_mode — без замены (раскладки табло проверяет test_compact_sizes).
Task 13: Ruling: замена идущего эфира — флаг force (страница спрашивает листом), EfirController.confirm_replace удалён; launch() теперь возвращает bool; «Мини-таймер» (cmd timer) → маленький режим окна; настройка start_timer больше ничего не открывает (решит Task 14).
Task 13: Ruling: экран учеников у вебинара без урока — команды efir_screen (перерыв 5–20, ±, пауза, зарядка, фон) прямо в EfirController; уход с несохранённой правкой — общий canLeave в main.js (адрес возвращается replaceState, лист «Уйти без сохранения»); фон из галереи браузера приходит на страницу через app_state.efir.picked.
Task 13: Ruling: test_app_page.test_cmd_reaches_window — гонка с собственной отправкой областей страницей; тест шлёт, пока не дойдёт.
Task 13: complete (commits d03871f..9cd3352, tests: .venv/Scripts/python.exe .superpowers/sdd/2026-11-25-v1-odno-okno/run.py test_media_copy test_app_efir test_efir test_lesson test_v09 test_v10 test_v11 test_v12 → ALL OK)
Task 14: Ruling: TDD — settings.js написан до красного прогона (тесты уже были; красный прогон — до регистрации экрана: 14/14 упали на #setnav), дальше зелёный.
Task 14: Ruling: tests/ui_import.py удалён (Qt-окно «Нейросеть» больше нет): провайдер/строки ключа, шифрование, «Проверить», модели Claude Code и Codex, ключи не в отчёте — в test_app_settings (ai.check подменён вместо подставного HTTP-сервера); проверка HotkeyField из ui_regress — в test_hotkey_capture_rules; test_v10.test_ui_texts_current читает settings.js.
Task 14: Ruling: quiet.FakeHotkeys запоминает _bindings, как настоящий HotkeyManager — иначе «хоткеи сняты на время записи» не проверить.
Task 14: Ruling: «Записать звук клавиатуры…» пока открывает прежний RecordDialog (лист записи — Task 15); «маленький режим при начале урока» = start_timer → set_compact(True) в lesson_control._launch.
Task 14: Ruling: раздел перерисовывается при смене данных (нейросеть, звуки, обновления), но не пока печатают в поле; фокус списка/кнопки возвращается на то же место.
Task 14: complete (commits 9cd3352..1f0bad5, tests: .venv/Scripts/python.exe .superpowers/sdd/2026-11-25-v1-odno-okno/run.py test_app_settings test_app_shell test_app_core test_app_page test_app_lesson test_app_compact test_app_efir ui_regress test_v10 test_v11 test_v12 test_lesson → ALL OK)
Task 15: Ruling: листы окна — отдельный модуль page/app/winsheets.js (+ winsheets.css), а не sheets.js: sheets.js — листы урока из его меню; программа просит лист через app_state.sheet {seq,name,text,t} (core.js → событие sheet; при первом подключении — только просьба моложе 8 с).
Task 15: Ruling: сбой до загрузки страницы — QMessageBox с «Сохранить отчёт на Рабочий стол» (report.save_zip), а не «Сообщить об ошибке…»: Qt-окна отчёта больше нет; после загрузки — лист «Внутренняя ошибка: …».
Task 15: Ruling: «Обновить и перезапустить» — скачать и перезапустить, как только скачается (App._update_restart), как было в UpdateDialog; ход загрузки и ошибка — app.update_progress / update_error в state.release.
Task 15: Ruling: ui.sheet получил beforeClose/tryClose (Esc и щелчок по фону спрашивают «Закрыть без сохранения?» у листа записи); во время записи клавиши ловятся на window (до Esc листа) и гасятся.
Task 15: Ruling: Qt-проверки ReportDialog из test_report.py и ui_regress.py перенесены в test_app_sheets.WindowSheetsTest (предпросмотр, без настроек, строка ошибки, zip, GitHub, копирование); ui_regress проверяет open_report без лишних окон.
Task 15: complete (commits 1f0bad5..1293f4e, tests: .venv/Scripts/python.exe .superpowers/sdd/2026-11-25-v1-odno-okno/run.py test_record_flow test_app_sheets test_report ui_regress test_app_settings test_app_shell test_app_core test_app_page test_updater test_sounds test_app_compact → ALL OK)
Task 16: Перенос проверок: ui_regress → test_app_core.RegressTest (фокус — урок, а не план; смена темы без ошибок; без лишних окон при отчёте и обновлении; пауза в отсчёте; \r\n в образце); ui_import → test_app_settings (Task 14); ReportDialog → test_app_sheets.WindowSheetsTest (Task 15). Сняты по замыслу: test_v09 WheelTest/RealWheelTest (колёсико Qt-виджетов — виджетов нет, у полей страницы своя защита ui.numberField), ui_smoke/ui_sweep (удалены раньше), StraySpy-класс ui_regress (теперь в RegressTest).
Task 16: Ruling: найдено и исправлено две ошибки по ходу (с тестами RED→GREEN): (1) класс .sel — и у <select>, и «выбранный блок» урока: выбранная заметка схлопывалась до 40 px — стиль списков теперь select.sel (test_app_edit.test_selected_block_keeps_its_height); (2) при запуске фокус мог встать на план (первый шаблон) — теперь первый урок (test_app_core.RegressTest.test_focus_is_lesson_not_plan).
Task 16: Ruling: theme.py сокращён до темы, цветов рамки и простого QSS для меню трея, подсказок, кнопок заставки окна и QMessageBox (цвета — как у страницы); ui/icons.py удалён вместе с widgets.py (больше никем не использовался); FramelessWindow без своего заголовка (client_hit по умолчанию — HTCLIENT, окно спрашивает страницу).
Task 16: Ruling: tools/make_readme_shots.py переписан на страницу /app (снимки сняты, старые картинки удалены, logo-256.png оставлен — фирменный); README переписан под одно окно (это частично работа Task 18 «снимки» — в 18 снимки пересниму после полировки).
Task 16: Ruling: tools/check.py — всё зелёное, кроме «Веб: типы» и «Веб: тесты» (нет npm-пакетов web/, как и до ветки) — совпадает с Expected брифа.
Task 16: Ruling: test_app_page.test_cmd_requires_header падал разрывом (WinError 10053): сервер на 403 закрывал сокет, не дочитав тело, — Windows шлёт RST. Теперь тело дочитывается (в пределах DRAIN_LIMIT) — test_forbidden_post_answers_cleanly RED (60 запросов по 200 КБ) → GREEN.
Task 16: complete (commits 1293f4e..596fef0, tests: .venv/Scripts/python.exe .superpowers/sdd/2026-11-25-v1-odno-okno/run.py test_app_core test_app_edit test_v09 test_v10 test_app_page test_app_shell test_app_settings test_app_sheets → ALL OK)
Task 17: Ruling: start_timer переименован в start_compact (миграция v1 копирует значение); поле start_timer оставлено в Settings только для чтения миграцией; «Мои настройки» (prefs) и «Настройки → Урок» — start_compact; page_plan "strip" больше не принимается (миграция → "top").
Task 17: Ruling: последний экран запоминает страница (core.js шлёт {cmd:"view"} через 0,4 с после смены адреса; адрес берётся в момент отправки); «Новый урок» (#/new…) и #/dev не запоминаются; несуществующий урок → «Уроки». Урок в эфире важнее последнего экрана.
Task 17: Ruling: installer/* не правился — версия установщика приходит из __version__ (tools/build_exe.py передаёт /DAppVersion); --tray — App.start(tray) вместо win.show() в app.py.
Task 17: Ruling: test_migration_v1_once до реализации проходил (проверяет, что второй прогон ничего не меняет — без v1 он тоже ничего не менял); остальные 6 тестов были красными.
Task 17: complete (commits 596fef0..4234adb, tests: .venv/Scripts/python.exe .superpowers/sdd/2026-11-25-v1-odno-okno/run.py test_app_core test_app_settings test_v11 test_app_page → ALL OK)
Task 18: Ruling: снимки (tools/screens.py, 83 шт., обе темы + 150 %) просмотрел отдельный агент (свежий взгляд), исправлено: правка расписания на всю ширину (без прокрутки вбок, поля не обрезаны), «Завершить эфир» в одной строке, полоса маленького режима — только целые ячейки + «N ›», раскладка маленького режима по пикселям страницы (с масштабом) и прокрутка табло, лист отчёта не выше окна (одна прокрутка, строки переносятся), листы — под заголовком окна, темнее подложка в светлой теме, шапка урока — правая группа с главной кнопкой справа, шапка этапа сеткой («осталось» справа), заголовок «Уроков» группой, плашки плана сверху — до 2 строк, «↓ Идёт» по центру текста урока, панель форматирования внутри карточки, scrollbar-gutter, единицы чисел одной ширины, выбранное в сегментах заметнее, роли в «О программе» своим цветом, короче подпись «Не подключена — свой чат». Тесты: test_app_compact.test_size_counts_zoom, test_strip_cells_fit_whole, test_nothing_hidden_when_low (RED→GREEN).
Task 18: Ruling: не правил (minor/спорное): текст удаления с путём data/templates.json.bak (его требует test_app_library — решение прошлой задачи), пустое место в compact-tall (по спецификации), сноски «8 мин» на новой строке в части мест (text-wrap: pretty только в шапке этапа), выравнивание правых краёв в редакторе оформления, «Что нового» дважды в листе обновления (заголовок из текста выпуска).
Task 18: Ruling: сборка — исключены папка PySide6/qml, QtOpenGL.pyd и 100 библиотек Qt, нужных только QML (по таблицам импорта .pyd, плагинов и QtWebEngineProcess.exe они недостижимы): установщик 107,2 → 93,3 МБ, папка 366,8 → 309,7 МБ; --selftest зелёный. Риск: --selftest проверяет только загрузку окна; печать в PDF, QtPdf и звук — на своих (оставленных) библиотеках.
Task 18: сборка 1.0.0 в dist\: установщик 93,3 МБ, zip 129,9 МБ, папка 309,7 МБ; --selftest зелёный; tools/check.py — всё зелёное, кроме «Веб: …» (test_app_library после возврата текста удаления — зелёный отдельно).
Task 18: complete (commits 4234adb..63a5a51, tests: .venv/Scripts/python.exe .superpowers/sdd/2026-11-25-v1-odno-okno/run.py test_app_compact test_app_library test_app_lesson test_app_efir test_app_sheets test_app_settings test_v10 → ALL OK)
Final review: opus, 1388483..63a5a51 — «With fixes», Critical нет, Important 8.
Final: fixed позиция маленького окна теряется при выходе в маленьком режиме — test_app_core.SessionTest.test_compact_position_survives_restart RED→GREEN
Final: fixed --tray при маленьком режиме и развёрнутом большом окне показывал окно — SessionTest.test_tray_start_in_compact_stays_hidden RED→GREEN (AppWindow._set_maximized не показывает скрытое окно)
Final: fixed запасная нейросеть не получала материал, когда основная (Claude Code / Codex) читала файлы — test_wizard_core.LessonTaskTest.test_backup_gets_file_text_when_agent_fails RED→GREEN (ai.ask(as_text=…))
Final: fixed «Скопировать в программу» затирало правки оформления / редактор возвращал старые пути — test_app_efir.LooksTest.test_copy_does_not_lose_edits RED→GREEN (карта путей app.media_moves, remap текущего оформления)
Final: fixed нагрузка на окно при записи звука и на публикациях — test_record_flow.test_state_is_cheap_with_long_recordings (93 мс → <15), test_app_core.test_publish_does_not_search_path_or_decrypt_each_time, test_publish_does_not_stat_look_files_each_time RED→GREEN (кэш итогов записи, cli_path раз в минуту, расшифровка ключей, статусы файлов оформлений раз в 10 с, can_self_update раз за запуск)
Final: fixed «Идёт урок — завершить и открыть?» тостом с разрушительной кнопкой — теперь лист с явной кнопкой: test_app_sheets.test_open_other_while_live_sheet, test_app_core/test_v10 переписаны RED→GREEN
Final: fixed большое видео для оформления копировалось на UI-потоке и плодило дубли — test_media_copy.test_take_same_file_twice_no_duplicate, test_app_efir.test_big_file_copies_in_background RED→GREEN
Final: fixed белое окно после загрузки (сбой отрисовки, не запустились скрипты) — test_app_shell.test_renderer_gone_shows_message_and_reloads, test_page_not_ready_shows_message RED→GREEN
Final: fixed (повышено из Minor по эффекту — первое, что увидит владелец после обновления) первое окно больше экрана — SessionTest.test_first_window_fits_screen RED→GREEN (place_default)
Final: minor (deferred): процесс агента может пережить «Выход» на ~0,2 с, папка req-* не убирается при быстром выходе
Final: minor (deferred): внешняя вкладка /app в браузере может перебить области перетаскивания настоящего окна
Final: minor (deferred): /app/call — защита в глубину: CSP на app.html, nosniff/sandbox на /media, список расширений в efir_take_file, токены вместо путей
Final: minor (deferred): предпросмотр вставки заново рисует слайды и запускает экспорт PowerPoint на UI-потоке
Final: minor (deferred): при сбое «скопировать все оформления» уже скопированные файлы остаются в data/media
Final: minor (deferred): готовый урок нейросети сам открывается и поднимает окно (даже во время вебинара) — мягче был бы тост «Открыть»
Final: minor (deferred): DevTools по --debug нет (в спецификации было)
Final: minor (deferred): мёртвый код (_take_import, _new_from_menu, import_files(tab), new_from_presentation, chat_prompt/apply_answer для старых тестов, oldArmSlot), BOM в tools/check.py
Final: minor (deferred): AppCommands.handle ловит только TypeError/ValueError/KeyError — OSError команды страницы уходит на лист сбоя
Final: minor (deferred): тест «поздний результат после отмены не добавляется»
Final: Ruling: внешний вид против макета не оценен ревьюером — его смотрел отдельный агент в Task 18 по 83 снимкам; стоит — cost: мелкие визуальные огрехи найдёт владелец
Final: Ruling: перетаскивание окна через WM_NCHITTEST, прилипание, мониторы с разным DPI, window/move — не проверяются невидимо; оставлено на ручную проверку при установке — cost: если перетаскивание сломано, окно не подвинуть (есть Win+стрелки)
Final: Ruling: сборка без ~100 DLL Qt проверена только --selftest; печать/PDF/QtPdf — на оставленных библиотеках; ручная проверка при установке — cost: печать в PDF может не работать в exe
Final: Ruling: агент читает файлы материала инструментом Read без ограничения папкой — так задумано спецификацией (Read-only), риск подсказок из чужого материала принят — cost: агент может прочитать соседние файлы по указанию материала
Final: Ruling: web/ (веб-версия Виктора) вне задачи; повторно используемые модули урока — вне диффа; ruling T6 и T12 ревьюер принял
Final: fix pass — tools/check.py зелёный, кроме «Веб: …» (31 шаг); коммит b35821c.
```
