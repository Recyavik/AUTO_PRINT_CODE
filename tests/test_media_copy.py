"""Файлы оформлений экрана учеников: где лежат (в программе, снаружи, нет файла) и копия в программу.

    .venv\\Scripts\\python.exe tests\\test_media_copy.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import quiet  # noqa: E402,F401  — своя папка данных

from autoprint import media_copy, storage  # noqa: E402
from autoprint.efir.model import Exercise, Look  # noqa: E402

OUT = Path(tempfile.mkdtemp(prefix="autoprint-outside-"))


def outside_look() -> Look:
    (OUT / "bg.png").write_bytes(b"\x89PNG" + b"0" * 100)
    (OUT / "brk.jpg").write_bytes(b"J" * 50)
    (OUT / "eyes.mp4").write_bytes(b"V" * 400)
    (OUT / "font.ttf").write_bytes(b"F" * 30)
    return Look(title="Снаружи", background="image:" + str(OUT / "bg.png"), break_background="image:" + str(OUT / "brk.jpg"),
                exercises=[Exercise("Глаза", str(OUT / "eyes.mp4"))], font="file:" + str(OUT / "font.ttf"))


class MediaCopyTest(unittest.TestCase):
    def test_file_status_missing_outside_ok(self):
        inside = storage.DATA_DIR / storage.MEDIA_FOLDER / "x-status.png"
        inside.parent.mkdir(parents=True, exist_ok=True)
        inside.write_bytes(b"1")
        (OUT / "y.png").write_bytes(b"1")
        self.assertEqual(media_copy.file_status(str(inside)), "ok")
        self.assertEqual(media_copy.file_status(str(OUT / "y.png")), "outside")
        self.assertEqual(media_copy.file_status(str(OUT / "нет.png")), "missing")
        self.assertEqual(media_copy.file_status(""), "missing")

    def test_outside_size(self):
        lk = outside_look()
        self.assertEqual(media_copy.outside_size(lk), 104 + 50 + 400 + 30)
        files = media_copy.look_files(lk)
        self.assertEqual(len(files), 4)

    def test_copy_look_files_rewrites_paths(self):
        lk = outside_look()
        dest = storage.DATA_DIR / storage.MEDIA_FOLDER
        seen = []
        new = media_copy.copy_look_files(lk, dest, progress=lambda i, n, name: seen.append((i, n)))
        self.assertIsNot(new, lk)
        self.assertEqual(lk.background, "image:" + str(OUT / "bg.png"))            # исходный не тронут
        for p in media_copy.look_files(new):
            self.assertEqual(Path(p).parent, dest)
            self.assertTrue(Path(p).is_file())
        self.assertTrue(new.background.startswith("image:"))
        self.assertTrue(new.font.startswith("file:"))
        self.assertEqual(new.exercises[0].title, "Глаза")
        self.assertEqual(media_copy.outside_size(new), 0)
        self.assertEqual(seen[-1], (4, 4))

    def test_copy_failure_keeps_paths(self):
        lk = outside_look()
        dest = Path(tempfile.mkdtemp(prefix="autoprint-dest-"))
        orig, calls = shutil.copy2, []

        def broken(src, dst, *a, **k):
            calls.append(dst)
            if len(calls) == 2:
                raise OSError("нет места на диске")
            return orig(src, dst, *a, **k)
        shutil.copy2 = broken
        try:
            with self.assertRaises(OSError):
                media_copy.copy_look_files(lk, dest)
        finally:
            shutil.copy2 = orig
        self.assertEqual(lk.background, "image:" + str(OUT / "bg.png"))
        self.assertEqual(list(dest.iterdir()), [])                                # начатое убрано

    def test_copy_cancel(self):
        lk = outside_look()
        ev = threading.Event()
        ev.set()
        with self.assertRaises(media_copy.Cancelled):
            media_copy.copy_look_files(lk, Path(tempfile.mkdtemp()), cancel=ev)

    def test_take_file_copies_into_program(self):
        (OUT / "new-bg.png").write_bytes(b"N" * 10)
        p = media_copy.take_file(str(OUT / "new-bg.png"))
        self.assertEqual(Path(p).parent, storage.DATA_DIR / storage.MEDIA_FOLDER)
        self.assertEqual(Path(p).read_bytes(), b"N" * 10)
        self.assertEqual(media_copy.take_file(p), p)                               # уже в программе — тот же


if __name__ == "__main__":
    unittest.main(verbosity=2)
