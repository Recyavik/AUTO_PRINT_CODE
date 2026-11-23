"""0.10 — один экран урока: модель, печать только кода, окно-список, правки со страницы, «Эфир».
Всё без окон на экране.

    python tests/test_v10.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import quiet  # noqa: E402,F401  — до PySide6: offscreen, своя папка данных

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
quiet.patch()
from autoprint.ui.theme import theme  # noqa: E402
theme.setup(app, "dark")

from autoprint import storage  # noqa: E402
from autoprint.storage import (BLOCK_CODE, BLOCK_IMAGE, BLOCK_MARKDOWN, BLOCK_STAGE, Block,  # noqa: E402
                               Settings, Template, TemplateStore)

TMP = Path(tempfile.mkdtemp(prefix="v10-test-"))


def pump(ms: int = 50) -> None:
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def note(text: str = "заметка", role: str = "say", **kw) -> Block:
    return Block(BLOCK_MARKDOWN, text, role=role, **kw)


def code(text: str = "print(1)", **kw) -> Block:
    return Block(BLOCK_CODE, text, **kw)


def stage(title: str = "Этап", minutes: int = 5, **kw) -> Block:
    return Block(BLOCK_STAGE, "", title=title, minutes=minutes, **kw)


# ================================================================ Task 1: роли, урок, миграции

class RolesTest(unittest.TestCase):
    def test_new_roles(self):
        from autoprint.storage import ROLE_HINTS, ROLE_MORE, ROLE_ORDER, ROLES
        self.assertIn("term", ROLES)
        self.assertIn("output", ROLES)
        self.assertEqual(ROLES["task"][1], "Задание")
        self.assertEqual(ROLES["text"][1], "Заметка")
        self.assertEqual(ROLES["term"][1], "Термин")
        self.assertEqual(ROLES["output"][1], "Вывод")
        self.assertEqual(set(ROLE_ORDER + ROLE_MORE), set(ROLES))
        self.assertEqual(len(ROLE_ORDER + ROLE_MORE), len(ROLES))
        self.assertEqual(ROLE_ORDER[0], "say")
        self.assertEqual(set(ROLE_HINTS), set(ROLES))
        self.assertIn("дословно", ROLE_HINTS["say"])
        self.assertIn("своими словами", ROLE_HINTS["tell"])

    def test_new_lesson_shape(self):
        t = TemplateStore().add("X")
        self.assertEqual([(b.type, b.title, b.minutes) for b in t.blocks[:1]], [(BLOCK_STAGE, "Начало", 5)])
        self.assertEqual(len(t.blocks), 2)
        self.assertEqual((t.blocks[1].type, t.blocks[1].role, t.blocks[1].text), (BLOCK_MARKDOWN, "say", ""))

    def test_look_field_roundtrip(self):
        t = Template("L", [note()], look="abc")
        d = storage.asdict(t)
        self.assertEqual(storage._template_from(d).look, "abc")

    def test_settings_new_fields(self):
        names = set(Settings.__dataclass_fields__)
        for new in ("lesson_look", "page_open", "page_lesson"):
            self.assertIn(new, names)


class NextCodeTest(unittest.TestCase):
    def test_next_code(self):
        a, b = code("a = 1", id="A"), code("b = 2", id="B")
        t = Template("T", [note(), a, Block(BLOCK_IMAGE, "x.png"), code("  \n", id="E"), b])
        self.assertIs(t.next_code(), a)
        self.assertIs(t.next_code("A"), b)
        self.assertIsNone(t.next_code("B"))
        self.assertIs(t.next_code("B", back=True), a)
        self.assertIsNone(t.next_code("A", back=True))

    def test_is_printable(self):
        from autoprint.storage import is_printable
        self.assertTrue(is_printable(code("x")))
        self.assertFalse(is_printable(code("   ")))
        self.assertFalse(is_printable(note("x")))
        self.assertFalse(is_printable(Block(BLOCK_IMAGE, "x.png")))


class MigrationTest(unittest.TestCase):
    def setUp(self):
        storage.TEMPLATES_FILE.unlink(missing_ok=True)
        storage.TEMPLATES_FILE.with_suffix(".json.bak").unlink(missing_ok=True)
        (storage.DATA_DIR / "templates.before-0.10.json").unlink(missing_ok=True)

    def make_store(self):
        store = TemplateStore()
        n = note(id="n1")
        store.templates = [Template("С кодом", [n, code(id="c1")], active_block="n1"),
                           Template("Без кода", [note(id="n2")], active_block="n2"),
                           Template("Код активен", [code(id="c2")], active_block="c2")]
        store.save()
        return store

    def test_active_note_reset(self):
        from autoprint import migrations
        store = self.make_store()
        s = Settings()
        self.assertTrue(migrations.apply(s, store))
        self.assertEqual([t.active_block for t in store.templates], ["c1", "", "c2"])
        self.assertIn("roles_v10", s.migrations)
        self.assertFalse(migrations.apply(s, store))

    def test_backup_once(self):
        from autoprint import migrations
        store = self.make_store()
        before = storage.TEMPLATES_FILE.read_text(encoding="utf-8")
        migrations.apply(Settings(), store)
        bak = storage.DATA_DIR / "templates.before-0.10.json"
        self.assertTrue(bak.exists())
        self.assertEqual(bak.read_text(encoding="utf-8"), before)
        store.templates[0].title = "другое"
        store.save()
        migrations.apply(Settings(), store)
        self.assertEqual(bak.read_text(encoding="utf-8"), before)

    def test_tray_migration_moved(self):
        from autoprint import migrations
        s = Settings()
        s.close_to_tray = False
        migrations.apply(s, self.make_store())
        self.assertTrue(s.close_to_tray)
        self.assertIn("tray_v1", s.migrations)


if __name__ == "__main__":
    unittest.main(verbosity=2)
