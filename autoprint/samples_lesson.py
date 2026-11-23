"""Встроенный пример урока «Пример урока: тёмная тема на сайте» — всё, что умеет суфлёр, на одном уроке:
части и этапы с минутами, перерыв и зарядка, все подсказки ведущему (говоришь, расскажи, спроси с ответом,
делаешь, важно, показываешь, ловушки, для быстрых), код CSS/JS/HTML и картинки (сайт до и после, слайд).

Добавляется один раз (Settings.samples_seen, LESSON_SAMPLE_ID). Картинки лежат в autoprint/samples/
(их делает tools/make_sample_images.py) и копируются в data/media — как вставленные руками.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from . import storage
from .storage import BLOCK_CODE, BLOCK_IMAGE, BLOCK_MARKDOWN, BLOCK_STAGE, Block, Template

LESSON_SAMPLE_ID = "lesson_v1"
LESSON_TITLE = "Пример урока: тёмная тема на сайте"
IMAGES_DIR = Path(__file__).resolve().parent / "samples"


def _image(name: str) -> str:
    """Картинка примера → копия в data/media (имя — по содержимому) → ссылка относительно папки данных."""
    src = IMAGES_DIR / name
    try:
        data = src.read_bytes()
    except OSError:
        return f"media/{name}"            # картинки нет в сборке — блок покажет «нет файла», урок не ломается
    out = storage.DATA_DIR / "media" / f"img-{hashlib.sha1(data).hexdigest()[:16]}{src.suffix.lower()}"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, out)
    return storage.media_ref(out)


def _md(role: str, text: str, title: str = "") -> Block:
    return Block(BLOCK_MARKDOWN, text, role=role, title=title)


def _stage(title: str, minutes: int, part: str, note: str = "", kind: str = "") -> Block:
    return Block(BLOCK_STAGE, note, title=title, minutes=minutes, part=part, stage_kind=kind)


def _code(text: str, lang: str, title: str = "") -> Block:
    return Block(BLOCK_CODE, text, lang=lang, title=title)


def _img(name: str, caption: str) -> Block:
    return Block(BLOCK_IMAGE, _image(name), title=caption)


_GOAL = """## Тёмная тема на сайте

Это **пример урока** — так выглядит занятие с этапами для суфлёра. Нажмите «Суфлёр урока» вверху: откроется
страница с планом по времени, что говорить, что спросить и что показать. Блоки кода печатаются, как обычно,
по Ctrl+F9.

После урока ребята:
- знают три правила тёмной темы;
- переключают тему кнопкой через `classList.toggle`;
- делают тёмную тему своему сайту."""

_CSS_DARK = """.darkTheme {
    background-color: #121212;
    color: #fff;
}"""

_CSS_HEADER = """.darkTheme header {
    background-color: #1f1f1f;
}

.darkTheme a,
.darkTheme .logo {
    color: #fac981;
}"""

_JS_TOGGLE = """const button = document.querySelector("#theme");

button.addEventListener("click", () => {
    document.body.classList.toggle("darkTheme");
});"""

_HTML_BUTTON = """<header>
    <div class="logo">☕ Кафе «Луна»</div>
    <button id="theme">🌙 Тёмная тема</button>
</header>"""


def lesson_sample() -> Template:
    blocks = [
        _md("task", _GOAL, "Цель урока"),

        _stage("Приветствие", 3, "Летучка", "без экрана"),
        _md("say", "Здравствуйте! Рад всех видеть. Сегодня сделаем сайту тёмную тему — как в Telegram и YouTube, "
                   "одной кнопкой.", "Начало"),
        _md("do", "Отметь присутствующих. Опоздавшим — напиши в чат ссылку на задание."),

        _stage("Повторение", 7, "Летучка", "опрос"),
        _md("ask", "Как в CSS выбрать элемент по классу?\n→ точкой: `.card`\n→ и можно вложенно: `.card p`"),
        _md("tell", "Классы можно добавлять и убирать из JavaScript — на этом и держится переключение темы. "
                    "Напомни про `classList.add` и `classList.remove` своими словами.", "Напомни"),

        _stage("Зачем нужна тёмная тема", 10, "Тёмная тема", "теория"),
        _md("say", "Вечером яркий белый экран режет глаза. Тёмная тема — это не «всё чёрное», у неё есть правила."),
        _md("show", "Слайд «Правила тёмной темы» — демонстрацию экрана включить."),
        _img("dark-rules-slide.png", "Слайд: правила тёмной темы"),
        _md("important", "Чистого чёрного `#000` на сайте нет: фон — тёмно-серый `#121212`, а текст — белый."),
        _md("ask", "Почему шапка в тёмной теме светлее фона?\n→ она «ближе» к нам, как карточка над столом"),

        _stage("Зарядка для глаз", 5, "Тёмная тема", "видео со звуком", kind="exercise"),
        _md("do", "Кнопка «Включить зарядку ученикам» выше запускает видео на экране эфира. Сами в это время — "
                  "тоже отдохните от экрана."),

        _stage("Создаём тёмную тему", 20, "Тёмная тема", "практика вместе"),
        _md("show", "Сайт кафе на платформе — сейчас он в светлой теме."),
        _img("dark-site-light.png", "Сайт до: светлая тема"),
        _md("say", "Создадим класс `darkTheme`: всё, что внутри него, станет тёмным. Начнём с фона и текста."),
        _code(_CSS_DARK, "css", "Фон и текст"),
        _md("say", "Шапка «ближе» к нам — её фон светлее. А ссылки и логотип сделаем тёплыми, неяркими."),
        _code(_CSS_HEADER, "css", "Шапка и ссылки"),
        _md("say", "Осталось научить кнопку переключать класс у `body`."),
        _code(_JS_TOGGLE, "javascript", "Переключатель"),
        _md("trap", "- `classList.toggle(\".darkTheme\")` с точкой — не сработает: точка только в CSS\n"
                    "- скрипт подключили в `<head>` без `defer` — кнопки ещё нет, `querySelector` вернёт `null`"),
        _img("dark-site-dark.png", "Сайт после: тёмная тема"),

        _stage("Перерыв", 10, "Тёмная тема", kind="break"),
        _md("do", "Кнопка «Показать перерыв ученикам» выше — на экране эфира заставка с обратным отсчётом."),

        _stage("Своя тёмная тема", 25, "Практика", "каждый сам"),
        _md("say", "Теперь — ваш сайт. Добавьте кнопку в шапку и сделайте тёмную тему по трём правилам."),
        _code(_HTML_BUTTON, "html", "Кнопка в шапке"),
        _md("do", "Ходи по ребятам в демонстрации их экранов. Кто застрял на `null` — смотри «Ловушки» выше."),
        _md("extra", "Запомнить выбор темы: `localStorage.setItem(\"theme\", \"dark\")` и прочитать его при загрузке."),

        _stage("Итоги", 10, "Итоги", "рефлексия"),
        _md("ask", "Какие три правила тёмной темы мы узнали?\n→ не чистый чёрный\n→ меньше насыщенности\n"
                   "→ ближе — светлее"),
        _md("say", "Отличная работа! Дома — доделайте тёмную тему и пришлите ссылку в чат.", "Прощание"),
    ]
    t = Template(title=LESSON_TITLE, blocks=blocks)
    t.active_block = next(b.id for b in blocks if b.type == BLOCK_CODE)
    return t
