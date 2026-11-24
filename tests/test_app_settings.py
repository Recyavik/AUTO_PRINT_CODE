"""«Настройки» в окне программы: разделы, пределы чисел, тема сразу, запись хоткеев (правила, конфликт, хоткеи сняты на
время записи), нейросеть (ключ шифруется и в страницу не уходит, «Проверить», модели агентов), обновления, о программе,
автозапуск, «маленький режим при начале урока».

    .venv\\Scripts\\python.exe tests\\test_app_settings.py
"""
from __future__ import annotations

import json
import unittest

from apphelp import AppPage, note, pump, stage  # noqa: F401

from autoprint import ai, app_state, system
from autoprint.storage import Template

SECTIONS = ["view", "lesson", "typing", "sound", "hotkeys", "behavior", "ai", "updates", "about"]


def lessons() -> list[Template]:
    return [Template("Урок", [stage("Начало", 5, id="s1"), note("x", id="n1")], id="L")]


class SettingsTest(AppPage):
    port = 18962
    templates = staticmethod(lessons)
    route = "#/settings"

    def setUp(self):
        app_state._CLI = {"claude": True, "codex": False}
        self.app.publish_now()
        self.go("#/settings/view", "settings")
        self.assertTrue(self.wait_js("!!document.querySelector('#setnav')"))

    def tearDown(self):
        app_state._CLI = None
        self.js("document.querySelectorAll('.hk.capturing').forEach(b => b.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})))")
        super().tearDown()

    def patch(self, obj, name, fn):
        old = getattr(obj, name)
        setattr(obj, name, fn)
        self.addCleanup(setattr, obj, name, old)

    def section(self, sec):
        self.go(f"#/settings/{sec}", "settings")
        self.assertTrue(self.wait_js(f"document.querySelector('#setnav [data-sec={sec}]').getAttribute('aria-current') === 'page'"))

    def set_value(self, sel, value, ev="change"):
        self.js(f"{{ const e = document.querySelector({sel!r}); e.value = {value!r}; e.dispatchEvent(new Event({ev!r}, {{bubbles: true}})); }}")

    def toast_text(self):
        return self.js("(document.getElementById('toasts') || {}).textContent || ''")

    def key(self, sel, key, code="", ctrl=False, alt=False, shift=False):
        self.js(f"document.querySelector({sel!r}).dispatchEvent(new KeyboardEvent('keydown', {{key: {key!r}, code: {code!r}, "
                f"ctrlKey: {str(ctrl).lower()}, altKey: {str(alt).lower()}, shiftKey: {str(shift).lower()}, bubbles: true, cancelable: true}}))")

    # ---------------------------------------------------------------- разделы
    def test_sections_present(self):
        self.assertEqual(self.js("[...document.querySelectorAll('#setnav [data-sec]')].map(b => b.dataset.sec)"), SECTIONS)
        texts = []
        for sec in SECTIONS:
            self.section(sec)
            texts.append(self.js("document.querySelector('#setbody').textContent"))
        whole = " ".join(texts)
        self.assertNotIn("Окно поверх остальных", whole)
        self.assertNotIn("Размер интерфейса", whole)
        self.assertIn("Тема", texts[0])
        self.assertIn("Копировать картинки и видео в программу", texts[1])
        self.assertIn("Сворачивать окно при наборе", texts[2])

    def test_number_limits_clamped(self):
        self.section("typing")
        self.set_value("#f-cpm", "99999")
        self.assertTrue(self.wait_py(lambda: self.app.settings.cpm == 3000))
        self.assertTrue(self.wait_js("document.querySelector('#f-cpm').value === '3000'"))
        self.set_value("#f-typos_per_100", "2.5")
        self.assertTrue(self.wait_py(lambda: self.app.settings.typos_per_100 == 2.5))
        self.app.settings.cpm = 320

    def test_theme_switch_live(self):
        self.click("#f-theme button[data-value=light]")
        self.assertTrue(self.wait_py(lambda: self.app.settings.theme == "light"))
        self.assertTrue(self.wait_js("document.documentElement.classList.contains('light')"))
        self.click("#f-theme button[data-value=dark]")
        self.assertTrue(self.wait_js("!document.documentElement.classList.contains('light')"))

    def test_start_compact(self):
        self.section("lesson")
        self.click("#f-start_compact")
        self.assertTrue(self.wait_py(lambda: self.app.settings.start_compact))
        self.app.printer.set_focus("L")
        self.app.lesson.command({"cmd": "start"})
        try:
            self.assertTrue(self.wait_py(lambda: self.app.window.compact))
        finally:
            self.app.lesson.command({"cmd": "stop"})
            self.app.set_compact(False)
            self.app.settings.start_compact = False

    # ---------------------------------------------------------------- хоткеи
    def test_hotkey_capture_rules(self):
        s = self.app.settings
        self.section("hotkeys")
        f = ".hk[data-key=hotkey_stop]"
        before = s.hotkey_stop
        self.click(f)
        self.assertTrue(self.wait_js(f"document.querySelector('{f}').classList.contains('capturing')"))
        self.key(f, "a", "KeyA")
        self.assertTrue(self.wait_js(f"document.querySelector('{f}').textContent.includes('нужен Ctrl, Alt или Win')"))
        self.assertEqual(s.hotkey_stop, before)
        self.click(f)
        self.key(f, "F5", "F5")                                         # F-клавиша — можно и без Ctrl
        self.assertTrue(self.wait_py(lambda: s.hotkey_stop == "F5"))
        self.click(f)
        self.key(f, "F9", "F9", ctrl=True)                              # уже у «Старт / пауза»
        self.assertTrue(self.wait_js("(document.getElementById('toasts') || {}).textContent.includes('уже назначен')"))
        self.assertEqual(s.hotkey_stop, "F5")
        self.click(f)
        self.key(f, "Backspace", "Backspace")                           # без хоткея
        self.assertTrue(self.wait_py(lambda: s.hotkey_stop == ""))
        t = ".hk[data-key=hotkey_toggle]"
        self.click(t)
        self.key(t, "Delete", "Delete")
        self.assertTrue(self.wait_js("(document.getElementById('toasts') || {}).textContent.includes('нужен всегда')"))
        self.assertEqual(s.hotkey_toggle, "Ctrl+F9")
        s.hotkey_stop = before
        self.app.on_setting_changed("hotkeys")

    def test_hotkeys_suspended_while_capturing(self):
        self.section("hotkeys")
        self.assertTrue(self.app.hotkeys._bindings)
        f = ".hk[data-key=hotkey_restart]"
        self.click(f)
        self.assertTrue(self.wait_py(lambda: self.app.hotkeys._bindings == {}))
        self.key(f, "Escape", "Escape")
        self.assertTrue(self.wait_py(lambda: bool(self.app.hotkeys._bindings)))
        self.assertTrue(self.wait_js(f"!document.querySelector('{f}').classList.contains('capturing')"))

    # ---------------------------------------------------------------- нейросеть
    def test_ai_key_not_in_state(self):
        s = self.app.settings
        self.section("ai")
        self.set_value("#aiProvMain", "openai")
        self.assertTrue(self.wait_py(lambda: s.ai_provider == "openai"))
        self.assertTrue(self.wait_js("!!document.querySelector('#aiKeyMain') && !document.querySelector('#aiKeyMain').closest('.field').hidden"))
        self.set_value("#aiKeyMain", "sk-secret-123")
        self.assertTrue(self.wait_py(lambda: s.ai_keys.get("openai", "").startswith("dpapi:")))
        self.app.publish_now()
        pump(300)
        self.assertTrue(self.wait_js("S.settings.ai.main.key_set === true"))
        whole = self.js("JSON.stringify(window.S)")
        self.assertNotIn("sk-secret-123", whole)
        self.assertNotIn("dpapi:", whole)
        self.assertEqual(self.js("document.querySelector('#aiKeyMain').value"), "")          # поле после сохранения пустое
        from autoprint import report
        snap = json.dumps(report._settings_snapshot(s), ensure_ascii=False)                 # и в отчёт об ошибке не попадает
        self.assertNotIn("sk-secret-123", snap)
        self.assertNotIn("dpapi:", snap)
        s.ai_provider, s.ai_keys = "", {}
        self.app.publish_now()

    def test_ai_check_result_pill(self):
        s = self.app.settings
        s.ai_provider, s.ai_urls["custom"], s.ai_models["custom"] = "custom", "http://127.0.0.1:9", "m"
        self.app.publish_now()
        self.patch(ai, "check", lambda c, timeout=60: (123, "готово"))
        self.section("ai")
        self.assertTrue(self.wait_js("!!document.querySelector('#aiCheckMain')"))
        self.click("#aiCheckMain")
        self.assertTrue(self.wait_js("document.querySelector('#aiPillMain').textContent === '123 мс'"))
        self.assertIn("готово", self.js("document.querySelector('#aiInfoMain').textContent"))
        s.ai_provider = ""
        self.app.publish_now()

    def test_ai_agents_models(self):
        """Claude по подписке: без адреса и ключа, модели с подписями, по умолчанию sonnet; Codex: «Как в Codex» — пусто."""
        s = self.app.settings
        self.section("ai")
        self.set_value("#aiProvMain", "claudeCli")
        self.assertTrue(self.wait_py(lambda: s.ai_provider == "claudeCli"))
        self.assertTrue(self.wait_js("document.querySelector('#aiKeyMain').closest('.field').hidden"))
        opts = self.js("[...document.querySelectorAll('#aiModelMain option')].map(o => o.value)")
        self.assertEqual(len(opts), 4)
        self.assertEqual(self.js("document.querySelector('#aiModelMain').value"), "sonnet")
        self.assertIn("установлен", self.js("[...document.querySelectorAll('#aiProvMain option')].find(o => o.value === 'claudeCli').textContent"))
        self.set_value("#aiProvMain", "codexCli")
        self.assertTrue(self.wait_js("[...document.querySelectorAll('#aiModelMain option')].some(o => o.value === 'gpt-5.6-terra')"))
        self.set_value("#aiModelMain", "gpt-5.6-terra")
        self.assertTrue(self.wait_py(lambda: s.ai_models.get("codexCli") == "gpt-5.6-terra"))
        self.assertEqual(self.js("document.querySelector('#aiModelMain option').textContent"), "Как в Codex")
        self.set_value("#aiModelMain", "")
        self.assertTrue(self.wait_py(lambda: s.ai_models.get("codexCli") == ""))
        s.ai_provider = ""
        self.app.publish_now()

    def test_ai_backup_rows(self):
        s = self.app.settings
        self.section("ai")
        self.assertTrue(self.js("document.querySelector('#aiBackup').hidden"))
        self.click("#f-ai_backup_enabled")
        self.assertTrue(self.wait_py(lambda: s.ai_backup_enabled))
        self.assertTrue(self.wait_js("!document.querySelector('#aiBackup').hidden"))
        self.set_value("#f-ai_timeout_min", "5")
        self.assertTrue(self.wait_py(lambda: s.ai_timeout_s == 300))
        s.ai_backup_enabled, s.ai_timeout_s = False, 0
        self.app.publish_now()

    # ---------------------------------------------------------------- обновления, о программе, поведение
    def test_updates_rows_disabled_when_auto_off(self):
        s = self.app.settings
        s.update_auto_check = False
        self.app.publish_now()
        self.section("updates")
        self.assertTrue(self.wait_js("document.querySelector('#f-update_interval_h').disabled && document.querySelector('#f-update_mode').disabled"))
        self.click("#f-update_auto_check")
        self.assertTrue(self.wait_py(lambda: s.update_auto_check))
        self.assertTrue(self.wait_js("!document.querySelector('#f-update_interval_h').disabled"))
        s.update_auto_check = False
        self.assertIn("Установлена версия", self.js("document.querySelector('#setbody').textContent"))

    def test_about_buttons(self):
        import os
        from autoprint.logs import LOG_FILE
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not LOG_FILE.exists():
            LOG_FILE.write_text("журнал\n", encoding="utf-8")
        opened = []
        self.patch(os, "startfile", lambda p, *a: opened.append(str(p)))
        self.section("about")
        self.click("#openLog")
        self.assertTrue(self.wait_py(lambda: opened == [str(LOG_FILE)]))
        self.assertIn(self.app.settings.hotkey_toggle, self.js("document.querySelector('#setbody').textContent"))

    def test_autostart_failure_reverts(self):
        s = self.app.settings
        self.patch(system, "set_autostart", lambda on: False)
        self.patch(system, "autostart_enabled", lambda: False)
        self.section("behavior")
        self.click("#f-autostart")
        self.assertTrue(self.wait_js("(document.getElementById('toasts') || {}).textContent.includes('автозапуск')"))
        self.assertFalse(s.autostart)
        self.assertTrue(self.wait_js("document.querySelector('#f-autostart').checked === false"))


class OldSettingsRemovedTest(unittest.TestCase):
    def test_old_windows_removed(self):
        from pathlib import Path
        from autoprint import storage
        ui = Path(storage.__file__).parent / "ui"
        for name in ("settings_window.py", "ai_settings.py"):
            self.assertFalse((ui / name).exists(), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
