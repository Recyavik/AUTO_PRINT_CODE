"""Картинки для встроенного примера урока (autoprint/samples/*.png): сайт в светлой и тёмной теме и слайд
«Правила тёмной темы». Снимки делает Edge без окна (headless) — на экране ничего не появляется.

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
OUT = ROOT / "autoprint" / "samples"

SITE = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><style>
* { box-sizing: border-box; } body { margin: 0; font: 18px/1.5 "Segoe UI", sans-serif; background: #FFF8EE; color: #2B2118; }
header { display: flex; align-items: center; gap: 28px; padding: 22px 56px; background: #F3D9B1; }
.logo { font: 800 28px "Segoe UI"; color: #8A4B12; } nav a { margin-right: 22px; color: #8A4B12; text-decoration: none; font-weight: 600; }
button { margin-left: auto; font: 600 16px "Segoe UI"; padding: 10px 18px; border-radius: 10px; border: 2px solid #8A4B12;
  background: #FFF8EE; color: #8A4B12; }
main { padding: 48px 56px; } h1 { font-size: 46px; margin: 0 0 12px; } p { max-width: 760px; color: #5A4636; }
.cards { display: flex; gap: 24px; margin-top: 34px; } .card { flex: 1; padding: 22px; border-radius: 16px; background: #FFFFFF;
  box-shadow: 0 6px 20px rgba(90,60,20,.12); } .card b { display: block; font-size: 22px; margin-bottom: 6px; }
body.darkTheme { background: #121212; color: #FFFFFF; } body.darkTheme header { background: #1F1F1F; }
body.darkTheme .logo, body.darkTheme nav a { color: #FAC981; } body.darkTheme button { background: #FAC981; color: #121212; border-color: #FAC981; }
body.darkTheme p { color: #C9C2BA; } body.darkTheme .card { background: #1E1E1E; box-shadow: none; border: 1px solid #2C2C2C; }
</style></head><body class="%THEME%"><header><div class="logo">☕ Кафе «Луна»</div><nav><a href="#">Меню</a><a href="#">Доставка</a>
<a href="#">Контакты</a></nav><button>%BTN%</button></header><main><h1>Кофе, который ждёт вас</h1>
<p>Свежая обжарка каждое утро, десерты по рецептам бабушки и тихий зал для работы. Заходите — первый капучино за наш счёт.</p>
<div class="cards"><div class="card"><b>Эспрессо</b>Плотный, с карамельной ноткой</div><div class="card"><b>Чизкейк</b>
Нежный, по-нью-йоркски</div><div class="card"><b>Какао</b>С маршмеллоу и корицей</div></div></main></body></html>"""

SLIDE = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><style>
body { margin: 0; height: 100vh; display: flex; flex-direction: column; justify-content: center; padding: 0 90px;
  background: linear-gradient(135deg, #1B2238, #2B1B38); color: #fff; font: 26px/1.45 "Segoe UI", sans-serif; }
h1 { font-size: 54px; margin: 0 0 34px; } .r { display: flex; gap: 22px; align-items: baseline; margin: 16px 0; }
.n { flex: none; width: 54px; height: 54px; border-radius: 14px; background: #E9A72C; color: #1B1B1F; font-weight: 800;
  display: flex; align-items: center; justify-content: center; } small { display: block; color: #B9B4D0; font-size: 21px; }
</style></head><body><h1>Правила тёмной темы</h1>
<div class="r"><div class="n">1</div><div>Не берите чистый чёрный <b>#000</b><small>фон — тёмно-серый, например #121212</small></div></div>
<div class="r"><div class="n">2</div><div>Снижайте насыщенность цветов<small>яркие цвета на тёмном «режут» глаза</small></div></div>
<div class="r"><div class="n">3</div><div>Чем «ближе» элемент — тем он светлее<small>шапка и карточки светлее фона</small></div></div>
</body></html>"""


def edge() -> str:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            p = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if p.is_file():
                return str(p)
    sys.exit("Нет Microsoft Edge")


def shot(html: str, out: Path, tmp: Path) -> None:
    page = tmp / (out.stem + ".html")
    page.write_text(html, encoding="utf-8")
    subprocess.run([edge(), "--headless=new", "--disable-gpu", f"--user-data-dir={tmp / 'profile'}", "--no-first-run",
                    "--hide-scrollbars", "--window-size=1280,720", f"--screenshot={out}", page.as_uri()],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    print(out, out.stat().st_size // 1024, "КБ")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sample-images-") as d:
        tmp = Path(d)
        shot(SITE.replace("%THEME%", "").replace("%BTN%", "🌙 Тёмная тема"), OUT / "dark-site-light.png", tmp)
        shot(SITE.replace("%THEME%", "darkTheme").replace("%BTN%", "☀ Светлая тема"), OUT / "dark-site-dark.png", tmp)
        shot(SLIDE, OUT / "dark-rules-slide.png", tmp)


if __name__ == "__main__":
    main()
