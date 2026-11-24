"""Снимки экранов окна программы (headless Edge, без окон на экране): build/screens/<имя>-<тема>.png.

    .venv\\Scripts\\python.exe tools\\screens.py [hash ...] [--size 1280x860] [--out папка]

Без аргументов — все экраны из SCREENS. Данные — временные (образцы программы), рабочая data/ не трогается.
"""
from __future__ import annotations

import base64
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("AUTOPRINT_DATA", tempfile.mkdtemp(prefix="autoprint-screens-"))

SCREENS = ["#/dev/ui"]


def main() -> int:
    args = [a for a in sys.argv[1:]]
    size = (1280, 860)
    out = ROOT / "build" / "screens"
    if "--size" in args:
        i = args.index("--size")
        w, h = args[i + 1].lower().split("x")
        size = (int(w), int(h))
        del args[i:i + 2]
    if "--out" in args:
        i = args.index("--out")
        out = Path(args[i + 1])
        del args[i:i + 2]
    hashes = args or SCREENS
    out.mkdir(parents=True, exist_ok=True)

    import quiet  # noqa: F401
    from PySide6.QtWidgets import QApplication
    qa = QApplication.instance() or QApplication(sys.argv[:1])
    quiet.patch()
    from autoprint.app_core import App
    from autoprint.storage import Settings, TemplateStore
    from autoprint.ui.theme import theme
    from cdp import Edge

    s = Settings()
    s.update_auto_check = False
    s.sound_enabled = False
    s.efir_port = 18999
    app = App(s, TemplateStore(), web=False)
    app.efir.ensure_server()
    app.publish_now()
    edge = Edge.start(f"http://127.0.0.1:{app.efir.server.port}/app{hashes[0]}", pump=qa.processEvents,
                      width=size[0], height=size[1])
    edge.wait("window.__ready === true", 15)
    saved = []
    try:
        for mode in ("dark", "light"):
            theme.set_mode(mode)
            app.publish_now()
            for hsh in hashes:
                edge.eval(f"location.hash = {hsh!r}")
                end = time.time() + 1.2
                while time.time() < end:
                    qa.processEvents()
                    time.sleep(0.02)
                edge.eval("document.fonts.ready.then(() => true)")
                shot = edge.call("Page.captureScreenshot", {"format": "png"})
                name = hsh.strip("#/").replace("/", "-") or "home"
                p = out / f"{name}-{mode}.png"
                p.write_bytes(base64.b64decode(shot["data"]))
                saved.append(p)
    finally:
        edge.close()
        app._quitting = True
        app.shutdown()
    for p in saved:
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
