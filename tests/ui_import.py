"""⚙ → Нейросеть — как пользуется человек: провайдер, ключ (зашифрован), «Проверить» на подставном сервере,
модели Claude Code и Codex. Тихий режим: на экран ничего не выводится. («Импорт урока» с 1.0 — «Новый урок» в окне:
tests/test_app_wizard.py и tests/test_wizard_core.py.)

    python tests/ui_import.py [папка для снимков]
"""
from __future__ import annotations

import http.server
import json
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import quiet  # noqa: E402 — окна в памяти, своя папка данных

from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
quiet.patch()
SHOTS = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="autoprint-import-shots-"))
SHOTS.mkdir(parents=True, exist_ok=True)
errors: list[str] = []
def _hook(t, v, tb) -> None:
    errors.append("".join(traceback.format_exception(t, v, tb)))
    print(errors[-1], file=sys.stderr)


sys.excepthook = _hook

from autoprint import ai, lesson_ai as L  # noqa: E402
from autoprint.storage import Settings, TemplateStore  # noqa: E402
from autoprint.app_core import App  # noqa: E402
from autoprint.ui.theme import theme  # noqa: E402

failed: list[str] = []


def open_settings_window(win, page: str):
    """Прежнее окно настроек (до «Настроек» в окне, Task 14)."""
    from autoprint.ui.settings_window import SettingsWindow
    w = SettingsWindow(win.settings, win.window)
    w.changed.connect(win.on_setting_changed)
    w.reload()
    w.show_page(page)
    w.show()
    return w


def check(name: str, ok: bool, extra: str = "") -> None:
    print(f"[{'OK' if ok else 'FAIL'}] {name}{' — ' + extra if extra else ''}")
    if not ok:
        failed.append(name)


def pump(sec: float = 0.4) -> None:
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def wait_for(pred, timeout: float = 10) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.02)
    return False


class Fake(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a) -> None:
        pass

    def _send(self, obj) -> None:
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._send({"data": [{"id": "teacher-7b"}]})

    def do_POST(self) -> None:
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        short = "одним словом" in req["messages"][0]["content"]
        self._send({"choices": [{"message": {"content": "готово" if short else L._EXAMPLES[L.STYLE_STEPS]}}]})


def main() -> int:
    s = Settings()
    s.sound_enabled = False
    s.update_auto_check = False
    theme.setup(app, "dark")
    win = App(s, TemplateStore(), web=False)
    win.window.resize(1240, 800)
    win.window.show()
    pump()

    # --- подключённая нейросеть (подставной сервер) — для «Проверить»
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    s.ai_provider = "custom"
    s.ai_urls["custom"] = f"http://127.0.0.1:{srv.server_address[1]}"
    s.ai_models["custom"] = "teacher-7b"
    # --- ⚙ → Нейросеть
    sw = open_settings_window(win, "ai")
    pump()
    box = sw.ai_main
    check("страница «Нейросеть»: выбран подключённый провайдер и его адрес",
          box.pid() == "custom" and box.url.text().startswith("http://127.0.0.1"))
    box.combo.setCurrentIndex(box.combo.findData("openai"))
    pump(0.1)
    check("ChatGPT (API): строки адреса и ключа видны, без ключа — подсказка",
          box.row_key.isVisibleTo(sw) and "ключ" in box.check_info.text().lower(), box.check_info.text())
    box.key.setText("sk-test-123")
    box._save_key()
    check("ключ сохранён зашифрованным", s.ai_keys.get("openai", "").startswith("dpapi:")
          and "sk-test-123" not in json.dumps(s.ai_keys))
    box.combo.setCurrentIndex(box.combo.findData("custom"))
    pump(0.1)
    box._check()
    ok = wait_for(lambda: box.check_btn.isEnabled() and box.pill.text() not in ("", "проверяю…"), 10)
    check("«Проверить»: время ответа и сам ответ", ok and "мс" in box.pill.text()
          and "готово" in box.check_info.text(), f"{box.pill.text()} {box.check_info.text()[:60]}")
    box.combo.setCurrentIndex(box.combo.findData("claudeCli"))
    pump(0.1)
    check("Claude по подписке: без адреса и ключа, список моделей с подписями, по умолчанию sonnet",
          not box.row_key.isVisibleTo(sw) and box.model.count() == 4 and not box.model.isEditable()
          and box.model.currentData() == "sonnet" and "Sonnet" in box.model.currentText())
    box.combo.setCurrentIndex(box.combo.findData("codexCli"))
    pump(0.1)
    i = box.model.findData("gpt-5.6-terra")
    box.model.setCurrentIndex(i)
    pump(0.1)
    check("ChatGPT по подписке (Codex): модель выбирается и сохраняется",
          i >= 0 and s.ai_models.get("codexCli") == "gpt-5.6-terra" and box.model.itemText(0) == "Как в Codex",
          repr(s.ai_models.get("codexCli")))
    box.model.setCurrentIndex(0)
    pump(0.1)
    check("«Как в Codex» — модель не передаётся", s.ai_models.get("codexCli") == ""
          and ai.config(s, "codexCli").model == "")
    box.combo.setCurrentIndex(box.combo.findData("claudeCli"))
    pump(0.1)
    sw.show_page("ai")
    pump(0.2)
    sw.grab().save(str(SHOTS / "settings-ai.png"))
    from autoprint import report
    snap = report._settings_snapshot(s)
    check("в отчёт об ошибке ключи не попадают", "sk-test-123" not in json.dumps(snap, ensure_ascii=False)
          and "dpapi:" not in json.dumps(snap))
    sw.close()
    srv.shutdown()

    win._quitting = True
    win.close()
    pump()
    check("без исключений", not errors, errors[0].strip().splitlines()[-1][:200] if errors else "")
    for e in errors[:3]:
        print(e, file=sys.stderr)
    print("снимки:", SHOTS)
    print("OK" if not failed else f"FAIL: {failed}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
