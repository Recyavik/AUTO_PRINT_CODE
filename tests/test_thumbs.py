"""Уменьшенные копии картинок для экрана урока: слайды 1920–3840 px распаковывались при прокрутке — подлагивало.

    .venv\\Scripts\\python.exe tests\\test_thumbs.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import quiet  # noqa: E402,F401  — до PySide6: offscreen, своя папка данных

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
quiet.patch()

from autoprint import thumbs  # noqa: E402
from autoprint.efir.server import BroadcastServer  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="thumbs-test-"))


def picture(name: str, w: int, h: int, alpha: bool = False) -> Path:
    img = QImage(w, h, QImage.Format.Format_ARGB32 if alpha else QImage.Format.Format_RGB32)
    img.fill(QColor(30, 90, 160, 120) if alpha else QColor(30, 90, 160))
    p = TMP / name
    assert img.save(str(p))
    return p


class ThumbTest(unittest.TestCase):
    def setUp(self):
        self.cache = Path(tempfile.mkdtemp(prefix="thumbs-cache-", dir=TMP))

    def test_big_slide_gets_smaller_copy(self):
        src = picture("slide.png", 1920, 1080)
        out = thumbs.thumb_for(src, 1280, self.cache)
        self.assertIsNotNone(out)
        img = QImage(str(out))
        self.assertEqual((img.width(), img.height()), (1280, 720))
        self.assertLess(out.stat().st_size, src.stat().st_size)
        self.assertTrue(out.is_relative_to(self.cache))

    def test_same_request_reuses_copy(self):
        src = picture("slide2.png", 1600, 900)
        a = thumbs.thumb_for(src, 960, self.cache)
        t = a.stat().st_mtime_ns
        time.sleep(0.02)
        self.assertEqual(thumbs.thumb_for(src, 960, self.cache), a)
        self.assertEqual(a.stat().st_mtime_ns, t)                    # не пересоздана

    def test_changed_file_gets_new_copy(self):
        src = picture("slide3.png", 1600, 900)
        a = thumbs.thumb_for(src, 960, self.cache)
        img = QImage(1600, 900, QImage.Format.Format_RGB32)
        img.fill(Qt.GlobalColor.red)
        img.save(str(src))
        os.utime(src, ns=(time.time_ns() + 10**9, time.time_ns() + 10**9))
        b = thumbs.thumb_for(src, 960, self.cache)
        self.assertNotEqual(a, b)

    def test_small_picture_stays_original(self):
        self.assertIsNone(thumbs.thumb_for(picture("small.png", 800, 450), 1280, self.cache))

    def test_not_a_picture_or_odd_width(self):
        v = TMP / "clip.mp4"
        v.write_bytes(b"not an image")
        self.assertIsNone(thumbs.thumb_for(v, 960, self.cache))
        broken = TMP / "broken.png"
        broken.write_bytes(b"\x89PNG broken")
        self.assertIsNone(thumbs.thumb_for(broken, 960, self.cache))
        self.assertIsNone(thumbs.thumb_for(picture("odd.png", 1920, 1080), 1234, self.cache))   # только SIZES
        self.assertIsNone(thumbs.thumb_for(TMP / "gone.png", 960, self.cache))

    def test_transparent_picture_keeps_alpha(self):
        out = thumbs.thumb_for(picture("alpha.png", 1920, 1080, alpha=True), 640, self.cache)
        self.assertTrue(QImage(str(out)).hasAlphaChannel())


class ServerThumbTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = BroadcastServer(port=18961)
        cls.srv.start()
        cls.base = f"http://127.0.0.1:{cls.srv.port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def get(self, path):
        return urllib.request.urlopen(self.base + path, timeout=10)

    def test_media_width_param(self):
        src = picture("served.png", 1920, 1080)
        url = self.srv.media_url(src)
        orig = self.get(url).read()
        self.assertEqual(orig, src.read_bytes())                     # без ?w — как было, сам файл
        r = self.get(url + "?w=960")
        small = QImage.fromData(r.read())
        self.assertEqual((small.width(), small.height()), (960, 540))
        self.assertTrue(r.headers["Content-Type"].startswith("image/"))
        self.assertEqual(self.get(url + "?w=abc").read(), orig)       # непонятная ширина — оригинал
        self.assertEqual(self.get(url + "?w=3840").read(), orig)      # картинка уже — оригинал


if __name__ == "__main__":
    unittest.main()
