"""Тесты ядра: разбиение на единицы печати, движок печати, текстовые блоки, комментарии, образцы, импорт.

    python -m unittest discover -s tests -v

Нажатия не уходят в Windows: движок печатает в модель редактора (FakeEditor). Модель в режиме IDE
ведёт себя как VS Code/Jupyter — сама закрывает скобки и кавычки, ставит автоотступ, — так проверяется,
что приёмы профиля IDE дают в итоге ровно исходный текст.
"""
from __future__ import annotations

import json
import os
import random
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

_DATA = tempfile.mkdtemp(prefix="autoprint-test-")
os.environ["AUTOPRINT_DATA"] = _DATA          # до импорта storage: рабочая база не трогается
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoprint import typer, winapi as w  # noqa: E402
from autoprint.comments import strip_comments  # noqa: E402
from autoprint.human import humanize  # noqa: E402
from autoprint.importers import export_ipynb, import_ipynb, import_markdown, import_python  # noqa: E402
from autoprint.storage import (BLOCK_CODE, BLOCK_MARKDOWN, PROFILE_IDE, PROFILE_PLAIN, Block, Settings,  # noqa: E402
                               Template, TemplateStore, sample_template)
from autoprint.textprint import find_selection, markdown_to_plain, printable, selection_text  # noqa: E402
from autoprint.typer import FINISHED, IDLE, PAUSED, RUNNING, TypingEngine, build_units  # noqa: E402
from autoprint.ui.blocks import typing_slice  # noqa: E402

CODE = '''def total(nums):
    """Сумма (без sum)."""
    result = {"a": [1, (2, 3)], 'b': `x`}
    for n in nums:
        if n > 0:
            result += n
    return result


print(total([1, 2, 3]))  # 6
\tprint("таб")
'''

PAIRS = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'", "`": "`"}


class FakeEditor:
    """Модель поля ввода: курсор, выделение, клавиши Home/End/Enter/Backspace/Tab/Esc.
    ide=True — автоскобки/автокавычки и автоотступ, как у VS Code."""

    def __init__(self, ide: bool, tab_width: int = 4) -> None:
        self.text, self.cur, self.anchor = "", 0, None
        self.ide, self.tab = ide, " " * tab_width

    def _sel(self) -> tuple[int, int]:
        a = self.cur if self.anchor is None else self.anchor
        return min(a, self.cur), max(a, self.cur)

    def _insert(self, s: str, after: str = "") -> None:
        a, b = self._sel()
        self.text = self.text[:a] + s + after + self.text[b:]
        self.cur, self.anchor = a + len(s), None

    def type_char(self, ch: str) -> None:
        self._insert(ch, PAIRS.get(ch, "") if self.ide and self.anchor is None else "")

    def tap(self, vk: int, *mods: int) -> None:
        shift = w.VK_SHIFT in mods
        line_start = self.text.rfind("\n", 0, self.cur) + 1
        nl = self.text.find("\n", self.cur)
        line_end = len(self.text) if nl < 0 else nl
        if vk in (w.VK_HOME, w.VK_END):
            if shift and self.anchor is None:
                self.anchor = self.cur
            elif not shift:
                self.anchor = None
            self.cur = line_start if vk == w.VK_HOME else line_end
        elif vk == w.VK_BACK:
            a, b = self._sel()
            if a == b and a > 0:
                a -= 1
            self.text, self.cur, self.anchor = self.text[:a] + self.text[b:], a, None
        elif vk == w.VK_RETURN:
            indent = ""
            if self.ide:
                line = self.text[line_start:self.cur]
                indent = line[:len(line) - len(line.lstrip())] + (self.tab if line.rstrip().endswith(":") else "")
            self._insert("\n" + indent)
        elif vk == w.VK_TAB:
            self._insert(self.tab)
        elif vk == w.VK_ESCAPE:
            pass
        else:
            raise AssertionError(f"неожиданная клавиша {vk:#x}")


def fast(**kw) -> Settings:
    """Быстрые настройки для тестов движка: без отсчёта, пауз и звука."""
    base = dict(cpm=20000, jitter=0, newline_pause_ms=0, punct_pause_ms=0, key_gap_ms=0, think_pause_s=0.0,
                autopause_on_focus_change=True, sound_enabled=False)
    base.update(kw)
    return replace(Settings(), **base)


class EngineHarness:
    """Подменяет WinAPI в движке на FakeEditor и «окно в фокусе»."""

    def __init__(self, test: unittest.TestCase, editor: FakeEditor) -> None:
        self.editor, self.foreground = editor, 1
        patches = {"type_char": editor.type_char, "tap": editor.tap, "wait_modifiers_released": lambda *a, **k: True,
                   "foreground_window": lambda: self.foreground, "is_own_window": lambda h: False,
                   "self_elevated": lambda: True, "window_elevated": lambda h: False,
                   "describe_window": lambda h: f"окно {h}"}
        for name, fn in patches.items():
            old = getattr(typer.w, name)
            setattr(typer.w, name, fn)
            test.addCleanup(setattr, typer.w, name, old)


def wait_state(engine: TypingEngine, states: set[str], timeout: float = 20.0) -> str:
    end = time.time() + timeout
    while time.time() < end:
        if engine.state in states:
            return engine.state
        time.sleep(0.005)
    raise AssertionError(f"движок не дошёл до {states}: {engine.state}")


def replay(units) -> str:
    """Что получится в простом поле ввода (без автодополнений)."""
    out = ""
    for u in units:
        if u.kind == "back":
            out = out[:-1]
        elif u.kind in ("char", "fast", "tab", "newline"):
            out += u.text
    return out


# ---------------------------------------------------------------- единицы печати

class BuildUnitsTest(unittest.TestCase):
    def test_text_reconstructed_for_all_indent_modes(self):
        expected = CODE.replace("\t", "    ")
        for profile in (PROFILE_PLAIN, PROFILE_IDE):
            for fast_indent in (False, True):
                for with_tab in (False, True):
                    s = replace(Settings(), profile=profile, fast_indent=fast_indent, indent_with_tab=with_tab)
                    units = build_units(CODE, s)
                    out = replay(units).replace("\t", "    ")
                    self.assertEqual(out, expected, (profile, fast_indent, with_tab))
                    self.assertEqual(units[-1].kind == "cleanup", profile == PROFILE_IDE)

    def test_progress_is_monotonic_and_ends_at_length(self):
        units = build_units(CODE, Settings())
        ends = [u.src_end for u in units]
        self.assertEqual(ends, sorted(ends))
        self.assertEqual(ends[-1], len(CODE))

    def test_humanize_keeps_text_and_makes_typos(self):
        s = replace(Settings(), profile=PROFILE_PLAIN, human_typing=False, typo_per_100_words=40)
        base = build_units(CODE, s)
        for seed in range(30):
            units = humanize([replace(u) for u in base], s, random.Random(seed))
            self.assertEqual(replay(units), replay(base), seed)
        typos = sum(u.kind == "back" for seed in range(30)
                    for u in humanize([replace(u) for u in base], s, random.Random(seed)))
        self.assertGreater(typos, 0)

    def test_typos_never_touch_brackets_quotes_or_newlines(self):
        s = replace(Settings(), typo_per_100_words=100)
        base = build_units(CODE, s)
        units = humanize([replace(u) for u in base], s, random.Random(1))
        for i, u in enumerate(units):
            if u.kind == "back":
                prev = next(x for x in reversed(units[:i]) if x.kind != "back")
                self.assertTrue(prev.text.isalpha(), prev)


# ---------------------------------------------------------------- движок печати

class EngineTest(unittest.TestCase):
    def run_engine(self, text: str, settings: Settings, editor: FakeEditor) -> TypingEngine:
        EngineHarness(self, editor)
        engine = TypingEngine(settings)
        engine.load(text)
        engine.start()
        wait_state(engine, {FINISHED})
        return engine

    def test_plain_profile_types_exact_text(self):
        ed = FakeEditor(ide=False)
        self.run_engine(CODE, fast(profile=PROFILE_PLAIN), ed)
        self.assertEqual(ed.text, CODE.replace("\t", "    "))

    def test_ide_profile_beats_autoclose_and_autoindent(self):
        for with_tab in (False, True):
            ed = FakeEditor(ide=True)
            self.run_engine(CODE, fast(profile=PROFILE_IDE, indent_with_tab=with_tab), ed)
            self.assertEqual(ed.text, CODE.replace("\t", "    "), with_tab)

    def test_ide_profile_with_human_typing(self):
        ed = FakeEditor(ide=True)
        self.run_engine(CODE, fast(profile=PROFILE_IDE, human_typing=True, typo_per_100_words=30), ed)
        self.assertEqual(ed.text, CODE.replace("\t", "    "))

    def test_pause_resume_and_stop(self):
        ed = FakeEditor(ide=False)
        EngineHarness(self, ed)
        engine = TypingEngine(fast(profile=PROFILE_PLAIN, cpm=600))
        text = "abcdefghij" * 5
        engine.load(text)
        engine.start()
        wait_state(engine, {RUNNING})
        time.sleep(0.2)
        engine.pause()
        self.assertEqual(engine.state, PAUSED)
        time.sleep(0.15)
        typed = len(ed.text)
        time.sleep(0.25)
        self.assertEqual(len(ed.text), typed, "на паузе ничего не печатается")
        self.assertLess(typed, len(text))
        engine.start()                      # «старт» на паузе = продолжить
        wait_state(engine, {FINISHED})
        self.assertEqual(ed.text, text, "после продолжения текст не теряется и не дублируется")
        engine.stop()
        self.assertEqual(engine.state, IDLE)

    def test_pause_during_countdown_and_start_delay(self):
        """Пауза во время отсчёта или задержки хоткея: печать не начинается и не «залипает» в RUNNING."""
        for kw in ({"countdown": 2}, {"delay": 1.0}):
            ed = FakeEditor(ide=False)
            EngineHarness(self, ed)
            engine = TypingEngine(fast(profile=PROFILE_PLAIN))
            engine.load("пауза")
            engine.start(**kw)
            time.sleep(0.3)
            self.assertTrue(engine.active, kw)
            engine.pause()
            self.assertEqual(engine.state, PAUSED, kw)
            time.sleep(kw.get("countdown", kw.get("delay")) + 0.5)
            self.assertEqual((engine.state, ed.text), (PAUSED, ""), kw)
            engine.start()                  # продолжить
            wait_state(engine, {FINISHED})
            self.assertEqual(ed.text, "пауза", kw)

    def test_focus_change_pauses(self):
        ed = FakeEditor(ide=False)
        h = EngineHarness(self, ed)
        engine = TypingEngine(fast(profile=PROFILE_PLAIN, cpm=600))
        engine.load("x" * 200)
        engine.start()
        wait_state(engine, {RUNNING})
        h.foreground = 2                    # пользователь переключился в другое окно
        self.assertEqual(wait_state(engine, {PAUSED}), PAUSED)
        n = len(ed.text)
        time.sleep(0.2)
        self.assertEqual(len(ed.text), n)
        engine.stop()

    def test_stop_cancels_worker(self):
        ed = FakeEditor(ide=False)
        EngineHarness(self, ed)
        engine = TypingEngine(fast(profile=PROFILE_PLAIN, cpm=300))
        engine.load("y" * 500)
        engine.start()
        wait_state(engine, {RUNNING})
        engine.stop()
        n = len(ed.text)
        time.sleep(0.3)
        self.assertEqual(len(ed.text), n, "после «Стоп» нажатия прекращаются")
        self.assertEqual(engine.state, IDLE)
        self.assertIsNone(engine._thread, "поток печати завершён и отпущен")


# ---------------------------------------------------------------- текстовые блоки

MD = ("## Задача 1. Сумма\n\nНапишите `total(nums)`, **без** _sum_.\n\n* пункт\n+ ещё\n> цитата [ссылка](http://x)\n\n"
      "```python\nx = **kw  # `не трогать`\n```\nИтог\n===\n")


class TextPrintTest(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(markdown_to_plain(MD),
                         "Задача 1. Сумма\n\nНапишите total(nums), без sum.\n\n- пункт\n- ещё\nцитата ссылка\n\n"
                         "x = **kw  # `не трогать`\nИтог")

    def test_snake_case_and_escapes_survive(self):
        self.assertEqual(markdown_to_plain("snake_case_name 2*3*4 \\*звезда\\*"), "snake_case_name 2*3*4 *звезда*")

    def test_comment_by_language(self):
        self.assertEqual(printable("# A\n\nb", "comment", "python"), "# A\n#\n# b")
        self.assertEqual(printable("A", "comment", "javascript"), "// A")
        self.assertEqual(printable("A", "comment", "sql"), "-- A")
        self.assertEqual(printable("A", "comment", "html"), "<!--\nA\n-->")
        self.assertEqual(printable("A", "comment", "неизвестный"), "# A")

    def test_markdown_mode_trims_outer_blank_lines(self):
        self.assertEqual(printable("\n\n## A\n\n", "markdown"), "## A")

    def test_find_selection_maps_rendered_text_to_source_lines(self):
        sel = find_selection(MD, "total(nums), без sum")
        self.assertEqual(MD[sel[0]:sel[1]], "Напишите `total(nums)`, **без** _sum_.")
        sel = find_selection(MD, "пункт\nещё")
        self.assertEqual(MD[sel[0]:sel[1]], "* пункт\n+ ещё")
        self.assertEqual(find_selection(MD, "нет такого"), [])
        self.assertEqual(find_selection(MD, "   "), [])

    def test_selection_inside_fence_stays_code(self):
        sel = find_selection(MD, "x = **kw")
        part, base = typing_slice(MD, sel, True)
        self.assertEqual(selection_text(MD, part, base, "plain"), "x = **kw  # `не трогать`")
        self.assertEqual(selection_text(MD, part, base, "markdown"), "x = **kw  # `не трогать`")

    def test_repeated_text_uses_hint(self):
        src = "a\nb\na\nb"
        self.assertEqual(find_selection(src, "a", 0.0), [0, 1])
        self.assertEqual(find_selection(src, "a", 0.9), [4, 5])


class CommentsTest(unittest.TestCase):
    def test_strip_python(self):
        src = "#!/usr/bin/env python\n# комментарий\nx = 1  # хвост\ns = '# не комментарий'\n\n\n# в конце\n"
        out, omap = strip_comments(src, "python")
        # пустые строки перед удалённым хвостом-комментарием тоже убираются
        self.assertEqual(out, "#!/usr/bin/env python\nx = 1\ns = '# не комментарий'")
        self.assertEqual("".join(src[i] for i in omap), out)

    def test_strip_c_like(self):
        out, _ = strip_comments('a = "//x"; /* блок\n */ b = 1; // хвост', "javascript")
        self.assertEqual(out, 'a = "//x";\n b = 1;')     # разбиение на строки сохраняется

    def test_unknown_language_untouched(self):
        self.assertEqual(strip_comments("# x", "text")[0], "# x")


# ---------------------------------------------------------------- образцы и импорт

class TemplateTest(unittest.TestCase):
    def test_navigation_and_numbering(self):
        t = Template("t", [Block(BLOCK_CODE, "1", lang="go"), Block(BLOCK_MARKDOWN, "md"), Block(BLOCK_CODE, "2")])
        md = t.blocks[1]
        self.assertEqual([b.text for b in t.nav_blocks()], ["1", "2"])
        t.active_block = md.id
        self.assertEqual([b.text for b in t.nav_blocks()], ["1", "md", "2"])
        self.assertEqual([t.code_number(b) for b in t.blocks], [1, 0, 2])
        self.assertEqual(t.lang_near(md), "python")          # сначала ниже
        t.blocks.pop()
        self.assertEqual(t.lang_near(md), "go")              # затем выше

    def test_store_roundtrip_and_old_format(self):
        store = TemplateStore()
        t = store.add("Новый")
        t.blocks[0].print_as = "plain"
        store.save()
        again = TemplateStore()
        self.assertEqual(again.get(t.id).blocks[0].print_as, "plain")
        # старый формат (до v0.3): задачи сливаются в одну ленту
        old = {"version": 2, "templates": [{"title": "Старый", "tasks": [
            {"title": "Задача А", "blocks": [{"type": "code", "text": "a"}]},
            {"title": "Задача Б", "blocks": [{"type": "markdown", "text": "## Задача Б"}, {"type": "code", "text": "b"}]}]}]}
        Path(_DATA, "templates.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        migrated = TemplateStore().templates[0]
        self.assertEqual([(b.type, b.text) for b in migrated.blocks],
                         [("markdown", "## Задача А"), ("code", "a"), ("markdown", "## Задача Б"), ("code", "b")])
        self.assertEqual(migrated.blocks[0].print_as, "markdown")
        self.assertTrue(Path(_DATA, "templates.v2.json").exists())

    def test_settings_ignore_wrong_types(self):
        Path(_DATA, "settings.json").write_text(json.dumps({"cpm": "быстро", "jitter": 10, "unknown": 1,
                                                            "think_pause_s": 2}), encoding="utf-8")
        s = Settings.load()
        self.assertEqual((s.cpm, s.jitter, s.think_pause_s), (Settings().cpm, 10, 2.0))
        Path(_DATA, "settings.json").write_text("[1, 2]", encoding="utf-8")
        self.assertEqual(Settings.load().cpm, Settings().cpm)

    def test_broken_file_recovered_from_backup(self):
        main, bak = Path(_DATA, "templates.json"), Path(_DATA, "templates.json.bak")
        for f in Path(_DATA).glob("templates*"):
            f.unlink()
        store = TemplateStore()                     # нет файла и копии — пример
        self.assertEqual(store.templates[0].title, sample_template().title)
        store.templates[0].title = "Моё занятие"
        store.save()
        bak.unlink(missing_ok=True)
        store.save()                                # копия появляется при следующем сохранении
        self.assertTrue(bak.exists())
        for broken in ("", "{не json", "[1, 2]", '{"templates": [{"blocks": 5}]}'):
            main.write_text(broken, encoding="utf-8")
            again = TemplateStore()
            self.assertEqual(again.templates[0].title, "Моё занятие", broken)
            self.assertIn("резервной копии", again.warning)
            self.assertEqual(json.loads(main.read_text(encoding="utf-8"))["templates"][0]["title"], "Моё занятие")
        self.assertTrue(list(Path(_DATA).glob("templates.broken-*.json")))
        main.unlink()                               # файл пропал (сбой между записями) — тоже из копии
        self.assertEqual(TemplateStore().templates[0].title, "Моё занятие")
        main.write_text("{не json", encoding="utf-8")
        bak.write_text("{и копия не json", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            TemplateStore()
        for f in Path(_DATA).glob("templates*"):
            f.unlink()


class ImportersTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(dir=_DATA))

    def test_ipynb_roundtrip(self):
        t = sample_template()
        path = self.dir / "t.ipynb"
        export_ipynb(t, str(path))
        back = import_ipynb(str(path))
        self.assertEqual([(b.type, b.text) for b in back.blocks], [(b.type, b.text) for b in t.blocks])

    def test_ipynb_raw_and_unknown_cells(self):
        path = self.dir / "cells.ipynb"
        cells = [{"cell_type": "raw", "source": "x"}, {"cell_type": "heading", "source": "?"},
                 {"cell_type": "code", "source": ["a\n", "b"]}, {"cell_type": "code", "source": "  \n"}]
        path.write_text(json.dumps({"cells": cells, "metadata": {}}), encoding="utf-8")
        blocks = import_ipynb(str(path)).blocks
        # raw-ячейка — блок кода внутри Markdown, неизвестные и пустые — пропускаются
        self.assertEqual([(b.type, b.text) for b in blocks], [(BLOCK_MARKDOWN, "```\nx\n```"), (BLOCK_CODE, "a\nb")])

    def test_markdown_and_python_cells(self):
        md = self.dir / "z.md"
        md.write_text("# Тема\n\nТекст\n\n```python\nprint(1)\n```\n", encoding="utf-8")
        blocks = import_markdown(str(md)).blocks
        self.assertEqual([b.type for b in blocks], [BLOCK_MARKDOWN, BLOCK_CODE])
        self.assertEqual(blocks[1].text, "print(1)")
        py = self.dir / "z.py"
        py.write_text("# %% [markdown]\n# Условие\n\n# %%\nx = 1\n", encoding="utf-8")
        blocks = import_python(str(py)).blocks
        self.assertEqual([(b.type, b.text) for b in blocks], [(BLOCK_MARKDOWN, "Условие"), (BLOCK_CODE, "x = 1")])


if __name__ == "__main__":
    unittest.main()
