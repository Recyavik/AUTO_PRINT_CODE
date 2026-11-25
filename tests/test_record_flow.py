"""Запись своей клавиатуры без окна (record_flow.RecordFlow): удары и цели по шагам, сохранение набора, пропуск пробела
и Enter. Микрофон подменён: «запись» — синтетический шум со щелчками.

    .venv\\Scripts\\python.exe tests\\test_record_flow.py
"""
from __future__ import annotations

import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import quiet  # noqa: E402,F401 — своя папка данных

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autoprint import record_flow, sounds  # noqa: E402
from autoprint.recorder import RATE  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)


def clicks(n: int, seed: int = 1) -> list[float]:
    """n ударов (затухающие всплески шума) с паузами ~0,45 с на тихом шуме."""
    rnd = random.Random(seed)
    gap, lead = int(RATE * 0.45), int(RATE * 0.4)
    buf = [rnd.gauss(0, 0.002) for _ in range(lead + gap * n + int(RATE * 0.5))]
    for k in range(n):
        at, amp, tau = lead + k * gap, rnd.uniform(0.35, 0.6), RATE * 0.006
        s = [rnd.uniform(-1, 1) * math.exp(-i / tau) for i in range(int(RATE * 0.04))]
        pk = max(abs(x) for x in s)
        for i, x in enumerate(s):
            buf[at + i] += x * amp / pk
    return buf


class FakeRecorder(QObject):
    """Вместо микрофона: start() — «слушаем», stop() — отдаёт заготовленную запись."""
    level = Signal(float)
    error = Signal(str)
    next_samples: list[float] = []

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._on = False
        self.keep = True
        self.starts: list[tuple] = []

    @staticmethod
    def devices() -> list[tuple[str, str]]:
        return [("mic1", "Микрофон у клавиатуры"), ("mic2", "Гарнитура")]

    @staticmethod
    def default_device() -> str:
        return "mic1"

    @property
    def recording(self) -> bool:
        return self._on

    def start(self, device_id=None, keep=True) -> bool:
        self._on, self.keep = True, keep
        self.starts.append((device_id, keep))
        return True

    def stop(self) -> list[float]:
        was, self._on = self._on, False
        return list(FakeRecorder.next_samples) if was and self.keep else []


class RecordFlowTest(unittest.TestCase):
    def setUp(self):
        self.f = record_flow.RecordFlow(volume=50, recorder=FakeRecorder())
        self.made: list[str] = []

    def tearDown(self):
        self.f.close()
        for k in self.made:
            sounds.delete_custom(k)

    def record(self, kind: str, n: int) -> None:
        FakeRecorder.next_samples = clicks(n, seed=n)
        self.assertTrue(self.f.start(kind))
        self.assertEqual(self.f.recording, kind)
        self.f.stop()
        self.assertEqual(self.f.recording, "")

    def test_devices_and_monitor(self):
        devs = self.f.devices()
        self.assertEqual([d[0] for d in devs], ["mic1", "mic2"])
        self.assertTrue(devs[0][2])                         # по умолчанию
        self.assertTrue(self.f.monitor("mic2"))
        self.assertEqual(self.f.rec.starts[-1], ("mic2", False))   # уровень — без записи
        self.f.rec.level.emit(0.5)
        self.assertGreater(self.f.level, 0.5)               # шкала −60…0 дБ: 0.5 → ≈0.9

    def test_hits_and_targets(self):
        self.record("key", 10)
        self.assertEqual(self.f.hits("key"), 10)
        self.assertEqual(self.f.tone("key"), "ok")
        self.assertIn("хорошо", self.f.status("key"))
        self.assertTrue(self.f.can_next("key"))
        self.record("space", 2)
        self.assertEqual(self.f.hits("space"), 2)
        self.assertIn("маловато", self.f.status("space"))
        self.assertEqual(self.f.tone("space"), "live")
        w = self.f.wave("key")
        self.assertTrue(0 < len(w) <= 600)
        self.assertTrue(all(0 <= x <= 1 for x in w))
        self.assertEqual(len(self.f.marks("key")), 10)
        st = self.f.state()
        self.assertEqual(st["kinds"]["key"]["hits"], 10)
        self.assertEqual(st["max_s"], record_flow.MAX_RECORD_S)

    def test_too_few_keys_block_next(self):
        self.record("key", record_flow.MIN_KEY_HITS - 1)
        self.assertFalse(self.f.can_next("key"))
        with self.assertRaises(ValueError):
            self.f.save("Мало")

    def test_save_creates_style(self):
        self.record("key", 9)
        self.record("space", 5)
        self.record("enter", 5)
        self.assertTrue(self.f.dirty)
        key = self.f.save("Моя клава")
        self.made.append(key)
        self.assertTrue(key.startswith("my_"))
        self.assertIn(key, sounds.available_styles())
        self.assertFalse(self.f.dirty)

    def test_skip_space_uses_keys(self):
        self.record("key", 8)
        self.f.skip("space")
        self.f.skip("enter")
        self.assertIn("Пропущено", self.f.status("space"))
        self.assertTrue(self.f.can_next("space"))
        key = self.f.save("")                               # пустое имя — «Моя клавиатура»
        self.made.append(key)
        self.assertEqual(sounds.available_styles()[key], "Своя: " + record_flow.DEFAULT_NAME)
        files = {p.name for p in sounds.custom_dir(key).iterdir()}
        self.assertFalse(any(n.startswith("space_") for n in files))   # пробел — из обычных клавиш при сборке

    def test_auto_stop_after_max(self):
        FakeRecorder.next_samples = clicks(4)
        self.f.start("key")
        self.f._started -= record_flow.MAX_RECORD_S + 1
        self.f._on_tick()
        self.assertEqual(self.f.recording, "")
        self.assertEqual(self.f.hits("key"), 4)

    def test_state_is_cheap_with_long_recordings(self):
        """Лист обновляется ~10 раз в секунду: состояние с длинными записями — без пересчёта волны каждый раз."""
        import time
        FakeRecorder.next_samples = clicks(80, seed=3)                     # ~36 с записи
        self.f.start("key")
        self.f.stop()
        FakeRecorder.next_samples = clicks(30, seed=4)
        self.f.start("space")
        self.f.stop()
        self.f.start("enter")                                              # идёт запись третьей
        self.f.state()
        t0 = time.perf_counter()
        for _ in range(5):
            self.f.state()
        per = (time.perf_counter() - t0) / 5
        self.f.stop()
        self.assertLess(per, 0.015, f"{per * 1000:.0f} мс на состояние")

    def test_preview_uses_player(self):
        played = []
        self.f.player.play = lambda clips, gap: played.append((len(clips), gap))
        self.record("key", 8)
        self.f.preview("key")
        self.f.preview("all")
        self.assertEqual(played[0][0], 8)
        self.assertEqual(played[1][0], 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
