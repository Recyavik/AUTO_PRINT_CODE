"""Картинки для образцового урока (autoprint/samples/lesson-example_files/*.png): схема функции, слайд «Надёжный
пароль» и вывод программы в Jupyter. Снимки делает Edge без окна (headless) — на экране ничего не появляется.

    python tools/make_sample_images.py

Картинки лежат в репозитории; скрипт нужен, только если их захочется переделать.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "autoprint" / "samples" / "lesson-example_files"

BASE = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><style>
* { box-sizing: border-box; }
body { margin: 0; height: 100vh; padding: 0 84px; display: flex; flex-direction: column; justify-content: center;
  background: #1A2030; color: #F2F4F8; font: 26px/1.45 "Segoe UI", sans-serif; }
h1 { font-size: 50px; margin: 0 0 30px; letter-spacing: -.01em; } small { color: #A9B2C8; }
%CSS%
</style></head><body>%BODY%</body></html>"""

SCHEME_CSS = """
.flow { display: flex; align-items: center; gap: 22px; margin-top: 10px; }
.box { flex: 1; padding: 26px 24px; border-radius: 18px; background: #232B3F; border: 2px solid #34405C; min-height: 190px; }
.box b { display: block; font-size: 22px; color: #A9B2C8; font-weight: 600; margin-bottom: 10px; }
.box code { font: 600 28px "Cascadia Mono", Consolas, monospace; color: #9CD67C; }
.box.f { background: #2E2A1A; border-color: #E9A72C; } .box.f code { color: #F0B54A; }
.arrow { font-size: 54px; color: #E9A72C; flex: none; }
.note { margin-top: 34px; font-size: 24px; color: #A9B2C8; }
"""
SCHEME = """<h1>Функция: вход → проверка → ответ</h1>
<div class="flow">
  <div class="box"><b>Аргумент — что даём</b><code>"Kot!2024ok"</code><br><small>пароль, который проверяем</small></div>
  <div class="arrow">→</div>
  <div class="box f"><b>Функция — что делаем</b><code>check_password()</code><br><small>длина, цифры, буквы</small></div>
  <div class="arrow">→</div>
  <div class="box"><b>return — что получаем</b><code>"надёжный"</code><br><small>результат можно напечатать или сравнить</small></div>
</div>
<div class="note">Одну и ту же функцию вызываем для любого пароля — код проверки пишем один раз.</div>"""

RULES_CSS = """
.r { display: flex; gap: 22px; align-items: baseline; margin: 14px 0; }
.n { flex: none; width: 52px; height: 52px; border-radius: 14px; background: #E9A72C; color: #1B1B1F; font-weight: 800;
  display: flex; align-items: center; justify-content: center; }
small { display: block; font-size: 21px; }
.bad { margin-top: 26px; padding: 14px 20px; border-radius: 14px; background: #3A1F24; color: #FFB3B6; font-size: 22px; }
"""
RULES = """<h1>Надёжный пароль</h1>
<div class="r"><div class="n">1</div><div>Не короче 8 символов<small>каждый символ в разы усложняет перебор</small></div></div>
<div class="r"><div class="n">2</div><div>Есть цифры<small>не только в конце: «Kot2024» хуже, чем «K0t!2o24»</small></div></div>
<div class="r"><div class="n">3</div><div>Заглавные и строчные буквы<small>«kotik» и «Kotik» — разные пароли</small></div></div>
<div class="r"><div class="n">4</div><div>Хотя бы один знак: ! ? # $ %<small>знаки расширяют «алфавит» для перебора</small></div></div>
<div class="bad">Никогда: qwerty, 123456, дата рождения, имя питомца — их проверяют первыми.</div>"""

JUPYTER_CSS = """
body { background: #FFFFFF; color: #1F2328; padding: 0 70px; }
.cell { border: 1px solid #D0D7DE; border-radius: 10px; overflow: hidden; margin-bottom: 18px; }
.in { display: flex; background: #F6F8FA; } .p { width: 92px; flex: none; padding: 16px 12px; color: #2F6FDB;
  font: 20px "Cascadia Mono", Consolas, monospace; text-align: right; }
pre { margin: 0; padding: 16px 18px; font: 21px/1.5 "Cascadia Mono", Consolas, monospace; white-space: pre; }
.k { color: #CF222E; } .s { color: #0A7A3B; } .f { color: #8250DF; }
.out { display: flex; } .out .p { color: #B3261E; } .out pre { color: #1F2328; }
h1 { color: #1F2328; font-size: 40px; margin-bottom: 22px; }
"""
JUPYTER = """<h1>Так это выглядит в Jupyter</h1>
<div class="cell"><div class="in"><div class="p">[5]:</div><pre><span class="k">for</span> tip <span class="k">in</span> <span class="f">password_hints</span>(<span class="s">"kotik"</span>):
    <span class="f">print</span>(<span class="s">"•"</span>, tip)</pre></div>
<div class="out"><div class="p"></div><pre>• сделайте пароль длиннее 8 символов
• добавьте цифру
• добавьте заглавную букву</pre></div></div>"""


def edge() -> str:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            p = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if p.is_file():
                return str(p)
    sys.exit("Нет Microsoft Edge")


def shot(css: str, body: str, out: Path, tmp: Path) -> None:
    page = tmp / (out.stem + ".html")
    page.write_text(BASE.replace("%CSS%", css).replace("%BODY%", body), encoding="utf-8")
    subprocess.run([edge(), "--headless=new", "--disable-gpu", f"--user-data-dir={tmp / 'profile'}", "--no-first-run",
                    "--hide-scrollbars", "--window-size=1280,720", f"--screenshot={out}", page.as_uri()],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    print(out, out.stat().st_size // 1024, "КБ")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sample-images-") as d:
        tmp = Path(d)
        shot(SCHEME_CSS, SCHEME, OUT / "func-scheme.png", tmp)
        shot(RULES_CSS, RULES, OUT / "password-rules.png", tmp)
        shot(JUPYTER_CSS, JUPYTER, OUT / "output-check.png", tmp)


if __name__ == "__main__":
    main()
