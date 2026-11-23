"""Окно «Импорт занятия» и ⚙ → Нейросеть — как пользуется человек: вставка, промпт, ответ нейросети,
«Разобрать нейросетью» на подставном сервере, проверка связи. Тихий режим: на экран ничего не выводится.

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
from autoprint.ui.main_window import MainWindow  # noqa: E402
from autoprint.ui.theme import theme  # noqa: E402

failed: list[str] = []


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


CODE = "grades = [5, 4, 3, 5]\naverage = sum(grades) / len(grades)\nprint(average)"


def main() -> int:
    s = Settings()
    s.sound_enabled = False
    s.update_auto_check = False
    theme.setup(app, "dark")
    win = MainWindow(s, TemplateStore())
    win.resize(1240, 800)
    win.show()
    pump()

    # --- «Вставить»: просто код JavaScript
    n0 = len(win.store.templates)
    win.import_files()
    d = win._import_dlg
    pump()
    check("окно импорта открылось на «Из файла»", d.isVisible() and d.tabs.value() == "file")
    d.grab().save(str(SHOTS / "import-file.png"))
    d.tabs.set_value("paste")
    d._show_tab("paste")
    d.paste_edit.setPlainText("function double(a) {\n  return a * 2;\n}")
    wait_for(lambda: "Распознано" in d.status.text(), 3)
    check("вставка: распознан код JavaScript", "javascript" in d.status.text() and d.add_btn.isEnabled(),
          d.status.text())
    d.grab().save(str(SHOTS / "import-paste.png"))
    d.add_btn.click()
    pump()
    check("вставка: урок добавлен и открыт на экране урока", len(win.store.templates) == n0 + 1
          and win.printer.focus().code_blocks()[0].lang == "javascript" and not d.isVisible())

    # --- «С помощью нейросети» без подключения: промпт и ответ своего чата
    win.import_files("ai")
    d = win._import_dlg
    pump()
    d.material.setPlainText(CODE)
    pump(0.2)
    check("без подключения: «Разобрать» недоступно, «Скопировать промпт» — да, подсказка «Подключить»",
          not d.ask_btn.isEnabled() and d.copy_btn.isEnabled() and "Подключить" in d.ai_info.text())
    d.style_seg.set_value(L.STYLE_STEPS)
    d._style_changed(L.STYLE_STEPS)
    d.copy_btn.click()
    clip = QGuiApplication.clipboard().text()
    check("промпт скопирован: материал, формат, разбор по шагам", CODE in clip and L.FORMAT in clip
          and "ПОШАГОВОЙ" in clip)
    d.grab().save(str(SHOTS / "import-ai-empty.png"))
    d.answer_edit.setPlainText("Вот занятие:\n```json\n" + L._EXAMPLES[L.STYLE_STEPS] + "\n```")
    wait_for(lambda: d.add_btn.isEnabled(), 3)
    check("ответ своего чата разобран — видно, что получится", "шагов: 3" in d.answer_info.text(),
          d.answer_info.text()[:120])
    d.grab().save(str(SHOTS / "import-ai-answer.png"))
    win.settings.print_mode, win.settings.strip_comments = "block", False
    win._apply_settings()
    d.add_btn.click()
    pump()
    t = win.printer.focus()
    check("занятие по шагам добавлено, включены «По шагам» и «Без комментариев»",
          t.title == "Оценки" and win.settings.print_mode == "steps" and win.settings.strip_comments
          and any(len(set(b.steps)) > 1 for b in t.code_blocks()), f"{win.settings.print_mode}")
    check("выбор разбора запомнен в настройках", win.settings.lesson_style == L.STYLE_STEPS)

    # --- большой код: нейросеть только размечает строки, код берётся из материала
    win.import_files("ai")
    d = win._import_dlg
    pump()
    big = "\n".join(f"value_{i} = compute({i})" for i in range(L.BIG_LINES + 30))
    d.material.setPlainText(big)
    d._update_ai_buttons()
    d.copy_btn.click()
    clip = QGuiApplication.clipboard().text()
    check("большой код: подсказка «разметит строки», промпт — разметкой с номерами строк",
          "разметит" in d.ai_info.text() and "1| value_0" in clip and "НЕ ПЕРЕПИСЫВАЙ" in clip, d.ai_info.text()[:90])
    d.answer_edit.setPlainText('{"mode": "marks", "title": "Большой", "lang": "python", "marks": ['
                               '{"from": 1, "to": 60, "step": 1, "say": "Первая половина"},'
                               '{"from": 61, "to": 150, "step": 2, "say": "Вторая половина"}]}')
    wait_for(lambda: d.add_btn.isEnabled(), 3)
    check("разметка собрана в занятие: код целиком, 2 шага, замечаний нет",
          "шагов: 2" in d.answer_info.text() and "Внимание" not in d.answer_info.text()
          and d._ai_parsed.template.code_blocks()[0].text.count("\n") + 1 == L.BIG_LINES + 30 + 2,
          d.answer_info.text()[:120])
    d.close()
    pump()

    # --- подключённая нейросеть (подставной сервер): «Разобрать нейросетью»
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    s.ai_provider = "custom"
    s.ai_urls["custom"] = f"http://127.0.0.1:{srv.server_address[1]}"
    s.ai_models["custom"] = "teacher-7b"
    win.import_files("ai")
    d = win._import_dlg
    pump()
    d.material.setPlainText(CODE)
    d._update_ai_buttons()
    check("подключено: «Разобрать нейросетью» доступно, видно, кто ответит",
          d.ask_btn.isEnabled() and "Своё" in d.ai_info.text(), d.ai_info.text()[:100])
    d.ask_btn.click()
    ok = wait_for(lambda: d.add_btn.isEnabled(), 15)
    check("нейросеть ответила — ответ в поле и разобран", ok and L.FORMAT in d.answer_edit.toPlainText()
          and "ответил" in d.answer_info.text(), d.answer_info.text()[:120])
    d.close()
    pump()

    # --- ⚙ → Нейросеть
    win.open_settings("ai")
    sw = win.settings_win
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
