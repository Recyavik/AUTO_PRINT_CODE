"""Проверка обновлений без сети: разбор релизов GitHub, SHA-256, распаковка сборки .exe,
скрипт установки сборки (и его прогон на поддельной папке программы).

    python tests/test_updater.py

Рабочая папка data/ не используется (AUTOPRINT_DATA → временная папка). Скрипт установки запускается
только на поддельной «папке программы» во временной папке — папку репозитория он не трогает.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="autoprint-upd-"))
os.environ["AUTOPRINT_DATA"] = str(TMP / "data")

from autoprint import __version__, updater  # noqa: E402
from autoprint.updater import Asset, Release, UpdateError  # noqa: E402

for _stream in (sys.stdout, sys.stderr):   # вывод в канал с кодировкой cp1251 не должен падать на «→»
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
logging.basicConfig(level=logging.CRITICAL)   # ожидаемые ошибки обновления (SHA и т.п.) не засоряют вывод

fails = 0


def check(name: str, cond, detail: str = "") -> None:
    global fails
    print(("OK   " if cond else "FAIL ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        fails += 1


def error_of(fn, *args, **kw) -> str | None:
    """Текст UpdateError, которую бросила fn; None — не бросила."""
    try:
        fn(*args, **kw)
    except UpdateError as e:
        return str(e)
    return None


def make_zip(path: Path, files: dict[str, bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


def write_tree(root: Path, files: dict[str, bytes]) -> None:
    for name, data in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


# ---------------------------------------------------------------- релизы

def test_releases() -> None:
    base = "https://github.com/Recyavik/AUTO_PRINT_CODE/releases/download/v0.5.0/"
    data = [
        {"tag_name": "v0.5.0", "name": "Версия 0.5.0", "body": "что нового", "draft": False, "prerelease": False,
         "html_url": "https://github.com/Recyavik/AUTO_PRINT_CODE/releases/tag/v0.5.0",
         "published_at": "2026-10-08T10:00:00Z",
         "assets": [
             {"name": "AutoPrintCode-0.5.0-win64.zip", "browser_download_url": base + "AutoPrintCode-0.5.0-win64.zip",
              "size": 123456},
             {"name": "AutoPrintCode-0.5.0-win64.zip.sha256",
              "browser_download_url": base + "AutoPrintCode-0.5.0-win64.zip.sha256", "size": 96},
             {"name": "AutoPrintCode-0.5.0-Setup.exe", "browser_download_url": base + "AutoPrintCode-0.5.0-Setup.exe",
              "size": 50_000_000},
             {"name": "evil.zip", "browser_download_url": "http://example.com/evil.zip"},   # не https — мимо
         ]},
        {"tag_name": "v0.6.0-beta.1", "prerelease": True, "assets": []},
        {"tag_name": "v0.4.9", "name": "0.4.9", "body": ""},            # только исходники, без assets
        {"tag_name": "v9.9.9", "draft": True},
        {"tag_name": "nightly"},
        "мусор",
    ]
    rels = updater.parse_releases(data)
    check("релизы: черновик, бета и чужие теги пропущены", [r.tag for r in rels] == ["v0.5.0", "v0.4.9"],
          str([r.tag for r in rels]))
    latest = updater.newest(rels)
    check("релизы: самый новый — v0.5.0", latest is not None and latest.version == "0.5.0")
    check("релизы: поля как раньше", latest.name == "Версия 0.5.0" and latest.notes == "что нового"
          and latest.published == "2026-10-08" and latest.zip_url.endswith("/v0.5.0.zip"))
    check("релизы: файлы релиза разобраны (http-ссылка отброшена)", len(latest.assets) == 3,
          str(latest.assets))
    z = latest.exe_zip
    check("релизы: архив сборки найден", z is not None and z.name == "AutoPrintCode-0.5.0-win64.zip"
          and z.size == 123456 and z.url.startswith("https://"))
    check("релизы: .sha256 найден", latest.exe_sha is not None
          and latest.exe_sha.name == "AutoPrintCode-0.5.0-win64.zip.sha256")
    check("релизы: установщик найден", latest.setup_exe is not None and latest.setup_exe.size == 50_000_000)
    check("релизы: сборку можно ставить", updater.release_block_reason(latest) is None)

    src_only = rels[1]
    check("без assets: список пуст, сборки нет", src_only.assets == [] and src_only.exe_zip is None
          and src_only.exe_sha is None)
    check("без assets: причина — нет сборки", updater.release_block_reason(src_only) == updater.NO_BUILD_TEXT)

    beta = updater.newest(updater.parse_releases(data, include_prerelease=True))
    check("бета: с флагом самый новый — v0.6.0-beta.1", beta is not None and beta.tag == "v0.6.0-beta.1")

    no_sha = Release("0.5.0", "v0.5.0", "n", "", "page", "zip", "",
                     assets=[Asset("AutoPrintCode-0.5.0-win64.zip", "https://x/a.zip", 1)])
    check("без .sha256: причина понятна", updater.release_block_reason(no_sha) == updater.NO_SHA_TEXT)

    odd = Release("0.5", "v0.5", "n", "", "page", "zip", "",
                  assets=[Asset("AutoPrintCode-0.5.0-win64.zip", "https://x/a.zip"),
                          Asset("autoprintcode-0.5.0-win64.zip.SHA256", "https://x/a.sha")])
    check("тег v0.5 при сборке 0.5.0: архив и .sha256 всё равно найдены",
          odd.exe_zip is not None and odd.exe_sha is not None)

    old_style = Release("0.3.8", "v0.3.8", "n", "", "page", "zip", "2026-10-07", False)
    check("Release без assets создаётся как раньше", old_style.assets == [] and old_style.exe_zip is None)


# ---------------------------------------------------------------- SHA-256

def test_sha() -> None:
    f = TMP / "sha" / "AutoPrintCode-0.5.0-win64.zip"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"payload " * 1000)
    good = updater._sha256(f)
    check("sha256: разбор «hex  имя»", updater.parse_sha256(f"{good.upper()}  {f.name}\n") == good)
    check("sha256: разбор «hex *имя»", updater.parse_sha256(f"{good} *{f.name}") == good)
    check("sha256: мусор не принимается", updater.parse_sha256("not a hash 1234") is None
          and updater.parse_sha256("a" * 65) is None)

    check("sha256: совпал — без ошибки", error_of(updater.verify_sha256, f, good) is None)
    err = error_of(updater.verify_sha256, f, "0" * 64)
    check("sha256: не совпал — ошибка", err is not None and "Контрольная сумма" in err, str(err))
    check("sha256: испорченный файл удалён", not f.exists())
    f.write_bytes(b"x")
    err = error_of(updater.verify_sha256, f, None)
    check("sha256: нет суммы — понятная ошибка", err == updater.NO_SHA_TEXT, str(err))

    # без .sha256 в релизе не скачивается вовсе (сеть не трогаем)
    real_request = updater._request

    def no_network(*a, **kw):
        raise AssertionError("сеть не должна понадобиться")
    updater._request = no_network
    try:
        rel = Release("0.5.0", "v0.5.0", "n", "", "page", "zip", "",
                      assets=[Asset("AutoPrintCode-0.5.0-win64.zip", "https://x/a.zip", 10)])
        err = error_of(updater.download_exe, rel)
        check("download_exe без .sha256: ошибка до загрузки", err == updater.NO_SHA_TEXT, str(err))
        rel.assets = []
        err = error_of(updater.download_exe, rel)
        check("download_exe без сборки: ошибка до загрузки", err == updater.NO_BUILD_TEXT, str(err))
    finally:
        updater._request = real_request


# ---------------------------------------------------------------- распаковка сборки

def test_stage_exe() -> None:
    rel = Release("0.5.0", "v0.5.0", "n", "", "page", "zip", "")
    z = make_zip(TMP / "zips" / "ok.zip", {"AutoPrintCode/AutoPrintCode.exe": b"MZ fake exe",
                                           "AutoPrintCode/_internal/dummy.txt": b"dummy"})
    root = updater.stage_exe(z, rel)
    check("сборка: распакована в data/updates/staging-0.5.0/AutoPrintCode",
          root == updater.UPDATES_DIR / "staging-0.5.0" / "AutoPrintCode", str(root))
    check("сборка: exe и _internal на месте", (root / "AutoPrintCode.exe").is_file()
          and (root / "_internal" / "dummy.txt").read_bytes() == b"dummy")

    flat = make_zip(TMP / "zips" / "flat.zip", {"AutoPrintCode.exe": b"MZ", "_internal/a.txt": b"a",
                                                "README.txt": b"r"})
    root = updater.stage_exe(flat, rel)
    check("сборка без общей папки: корень — staging", root == updater.UPDATES_DIR / "staging-0.5.0")

    rel12 = Release("1.2.0", "v1.2.0", "n", "", "page", "zip", "")      # с 1.2 в сборке — окно программы (Electron)
    no_win = make_zip(TMP / "zips" / "no_window.zip", {"AutoPrintCode/AutoPrintCode.exe": b"MZ",
                                                       "AutoPrintCode/_internal/a": b"a"})
    err = error_of(updater.stage_exe, no_win, rel12)
    check("сборка 1.2 без окна программы: ошибка", err is not None and "окна программы" in err, str(err))
    with_win = make_zip(TMP / "zips" / "with_window.zip", {"AutoPrintCode/AutoPrintCode.exe": b"MZ",
                                                           "AutoPrintCode/_internal/a": b"a",
                                                           "AutoPrintCode/window/AutoPrintCodeWindow.exe": b"MZ"})
    check("сборка 1.2 с окном: распакована", (updater.stage_exe(with_win, rel12) / "window").is_dir())

    bad = make_zip(TMP / "zips" / "no_internal.zip", {"AutoPrintCode/AutoPrintCode.exe": b"MZ"})
    err = error_of(updater.stage_exe, bad, rel)
    check("сборка без _internal: ошибка", err is not None and "_internal" in err, str(err))

    evil = make_zip(TMP / "zips" / "evil.zip", {"AutoPrintCode.exe": b"MZ", "_internal/a": b"a",
                                                "../evil.txt": b"evil"})
    err = error_of(updater.stage_exe, evil, rel)
    check("сборка с путём ../: ошибка", err is not None and "недопустимые" in err, str(err))
    check("сборка с путём ../: наружу ничего не записано", not (updater.UPDATES_DIR / "evil.txt").exists())

    junk = TMP / "zips" / "junk.zip"
    junk.write_bytes(b"not a zip at all")
    check("не архив: ошибка", error_of(updater.stage_exe, junk, rel) is not None)

    v = updater.exe_version(Path(sys.executable))
    want = ".".join(map(str, sys.version_info[:3]))
    check("версия .exe читается из ресурса (python.exe)", v.startswith(want), repr(v))
    check("версия .exe: нет ресурса — пусто", updater.exe_version(root / "AutoPrintCode.exe") == "")
    other = make_zip(TMP / "zips" / "wrong_version.zip",
                     {"AutoPrintCode/AutoPrintCode.exe": Path(sys.executable).read_bytes(),
                      "AutoPrintCode/_internal/a": b"a"})
    err = error_of(updater.stage_exe, other, rel)
    check("сборка другой версии: ошибка", err is not None and "забыл поднять" in err, str(err))


# ---------------------------------------------------------------- защита от запуска не из сборки

def test_guards() -> None:
    check("исходники/git обновляются сами", updater.can_self_update() is True)
    check("не сборка: у сборки есть причина отказа", isinstance(updater.frozen_layout_reason(), str))
    root = TMP / "fake-stage"
    write_tree(root, {"AutoPrintCode.exe": b"MZ", "_internal/a": b"a"})
    err = error_of(updater.prepare_exe_update, root, "0.5.0")
    check("prepare_exe_update не из сборки: отказ", err is not None, str(err))
    check("prepare_exe_update не из сборки: скрипт не запланирован", not updater.exe_update_pending())


def test_last_update() -> None:
    f = updater.LAST_UPDATE_FILE
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"from": "0.1.0", "to": __version__, "shown": False, "frozen": True}), encoding="utf-8")
    d = updater.pop_last_update()
    check("сборка обновилась: «было → стало» показывается", d is not None and d["to"] == __version__)
    check("…и только один раз", updater.pop_last_update() is None)

    f.write_text(json.dumps({"from": __version__, "to": "99.0.0", "shown": False, "frozen": True}),
                 encoding="utf-8")
    check("сборка не обновилась (откат): сообщения «обновлён» нет", updater.pop_last_update() is None)
    check("…и запись помечена показанной", json.loads(f.read_text(encoding="utf-8"))["shown"] is True)

    f.write_text(json.dumps({"from": "0.1.0", "to": "99.0.0", "shown": False}), encoding="utf-8")
    d = updater.pop_last_update()
    check("исходники: поведение прежнее", d is not None and d["to"] == "99.0.0")


def test_manager() -> None:
    """UpdateManager в режиме сборки: ставить можно только релиз со сборкой и .sha256."""
    from autoprint.storage import Settings
    from autoprint.ui.updates import UpdateManager
    real = updater.frozen_layout_reason
    updater.frozen_layout_reason = lambda: None   # как будто запущена настоящая сборка с правом записи
    try:
        m = UpdateManager(Settings())
        m.mode = updater.MODE_FROZEN
        full = Release("0.5.0", "v0.5.0", "n", "", "page", "zip", "",
                       assets=[Asset("AutoPrintCode-0.5.0-win64.zip", "https://x/a.zip"),
                               Asset("AutoPrintCode-0.5.0-win64.zip.sha256", "https://x/a.sha")])
        bare = Release("0.5.0", "v0.5.0", "n", "", "page", "zip", "")
        m.latest = full
        check("менеджер: релиз со сборкой — можно ставить", m.can_install and m.installable(full)
              and m.block_reason(full) == "")
        m.latest = bare
        check("менеджер: релиз без сборки — только страница релиза", not m.can_install
              and m.block_reason(bare) == updater.NO_BUILD_TEXT)
        m.download(bare)
        check("менеджер: релиз без сборки не скачивается", not m.downloading)
    finally:
        updater.frozen_layout_reason = real


def test_program_files() -> None:
    """Установка в Program Files: обновление — установщиком (Setup.exe + .sha256), данные — в профиле."""
    import contextlib
    import io
    from autoprint import storage
    real = updater.via_installer
    updater.via_installer = lambda: True
    real_request, real_fetch = updater._request, updater._fetch
    try:
        setup = Asset("AutoPrintCode-0.5.0-Setup.exe", "https://x/setup.exe", 7)
        sha = Asset("AutoPrintCode-0.5.0-Setup.exe.sha256", "https://x/setup.sha")
        zip_only = [Asset("AutoPrintCode-0.5.0-win64.zip", "https://x/a.zip"),
                    Asset("AutoPrintCode-0.5.0-win64.zip.sha256", "https://x/a.sha")]
        rel = Release("0.5.0", "v0.5.0", "n", "", "page", "zip", "", assets=zip_only + [setup, sha])
        check("Program Files: релиз с установщиком и .sha256 — можно ставить", updater.release_block_reason(rel) is None)
        check("Program Files: без установщика — только страница релиза",
              updater.release_block_reason(Release("0.5.0", "v0.5.0", "n", "", "p", "z", "", assets=zip_only))
              == updater.NO_SETUP_TEXT)
        check("Program Files: установщик без .sha256 — не ставится",
              updater.release_block_reason(Release("0.5.0", "v0.5.0", "n", "", "p", "z", "", assets=[setup]))
              == updater.NO_SHA_TEXT)
        body = b"MZsetup"
        good = hashlib.sha256(body).hexdigest()
        updater._request = lambda url, **kw: contextlib.nullcontext(io.BytesIO(f"{good}  x\n".encode()))

        def fake_fetch(url, dest, progress, cancelled, accept="", size=0):
            check("Program Files: скачивается установщик, а не архив", url == setup.url, url)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
            return dest
        updater._fetch = fake_fetch
        got = updater.download_exe(rel)
        check("Program Files: установщик скачан и сверен по SHA-256", got.name == setup.name and got.read_bytes() == body)
        check("Program Files: установщик не распаковывается", updater.stage_exe(got, rel) == got)
        wrong = got.with_name("other-Setup.exe")
        wrong.write_bytes(Path(sys.executable).read_bytes())
        err = error_of(updater.stage_exe, wrong, rel)
        check("Program Files: установщик другой версии — отказ", err is not None and "версии" in err, str(err))
    finally:
        updater.via_installer = real
        updater._request, updater._fetch = real_request, real_fetch

    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    check("папка в Program Files распознаётся", storage._in_program_files(Path(pf) / "AutoPrintCode")
          and not storage._in_program_files(Path(pf + "X") / "AutoPrintCode")
          and not storage._in_program_files(TMP))
    # перенос данных прежней установки «только для меня»
    old = TMP / "pf" / "Local" / "Programs" / "AutoPrintCode" / "data"
    write_tree(old, {"settings.json": b'{"cpm": 500}', "templates.json": b'{"templates": []}',
                     "sounds/a.wav": b"RIFF", "updates/junk.zip": b"z"})
    new = TMP / "pf" / "Roaming" / "AutoPrintCode"
    (old.parent / "AutoPrintCode.exe").write_bytes(b"MZ")
    check("прежняя копия ещё установлена — её данные не забираем", not storage.migrate_legacy_data(new, old)
          and not new.exists() and (old / "settings.json").exists())
    (old.parent / "AutoPrintCode.exe").unlink()   # прежнюю копию удалили — данные «осиротели»
    moved = storage.migrate_legacy_data(new, old)
    check("данные прежней установки перенесены (без updates), старая папка убрана",
          moved and (new / "settings.json").read_bytes() == b'{"cpm": 500}' and (new / "sounds" / "a.wav").is_file()
          and not (new / "updates").exists() and not old.exists() and not old.parent.exists())
    write_tree(old, {"settings.json": b'{"cpm": 1}'})
    check("свои данные уже есть — перенос не трогает их", not storage.migrate_legacy_data(new, old)
          and (new / "settings.json").read_bytes() == b'{"cpm": 500}' and old.exists())


# ---------------------------------------------------------------- скрипт установки сборки

OLD_APP = {"AutoPrintCode.exe": b"old exe 0.4.0", "_internal/old.dll": b"old dll",
           "_internal/common.txt": b"old common", "_internal/sub/x.pyd": b"old pyd",
           "window/AutoPrintCodeWindow.exe": b"old window", "window/locales/de.pak": b"old locale",
           "data/settings.json": b'{"keep": true}', "data/templates.json": b"[]", "unins000.exe": b"uninstaller"}
NEW_BUILD = {"AutoPrintCode.exe": b"NEW EXE 0.5.0 -- longer", "_internal/common.txt": b"new common!!",
             "_internal/new.dll": b"new dll", "_internal/sub/x.pyd": b"new pyd 0.5.0",
             "window/AutoPrintCodeWindow.exe": b"new window 0.5.0", "window/resources/app.asar": b"asar",
             "data/evil.json": b"must not be copied"}


def fresh(case: str) -> tuple[Path, Path, Path, Path, Path]:
    """Поддельная папка программы (с пробелами, скобками, & и кириллицей в пути) и распакованная сборка."""
    base = TMP / f"run-{case}"
    app = base / "Мои программы (x86) & тест" / "AutoPrintCode"
    src = base / "data" / "updates" / "staging-0.5.0" / "AutoPrintCode"
    write_tree(app, OLD_APP)
    write_tree(src, NEW_BUILD)
    return app, src, base / "data" / "updates" / "backup", base / "data" / "updates" / "apply.log", \
        base / "скрипт обновления (тест).cmd"


def dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def run_helper(script: Path) -> int:
    p = updater.run_update_helper(script, restart=False)
    return p.wait(timeout=120)


def old_untouched(app: Path) -> bool:
    return all((app / k).read_bytes() == v for k, v in OLD_APP.items()) and \
        not (app / "_internal" / "new.dll").exists()


def test_helper_text() -> None:
    app, src, bak, logf, script = fresh("text")
    pct = TMP / "100% путь"
    s = updater.write_update_helper(src, app, 4321, "0.5.0", script=script, log_file=logf, backup=pct)
    raw = s.read_bytes()
    text = raw.decode("utf-8")
    check("скрипт: записан в UTF-8 без BOM, строки CRLF", not raw.startswith(b"\xef\xbb\xbf")
          and b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""))
    check("скрипт: переключает консоль на UTF-8", "chcp.com\" 65001" in text)
    check("скрипт: ждёт выхода процесса", 'set "PID=4321"' in text and 'tasklist.exe" /FI "PID eq %PID%"' in text
          and f'set "WAIT={updater.PID_WAIT_S}"' in text)
    check("скрипт: пути программы и сборки", f'set "APP={app}"' in text and f'set "SRC={src}"' in text)
    check("скрипт: % в пути удвоен", 'set "BAK=' + str(pct).replace("%", "%%") + '"' in text)
    check("скрипт: папка data не копируется", '/XD "%SRC%\\data"' in text)
    check("скрипт: robocopy — ошибка от 8", "if errorlevel 8" in text and "goto restore" in text)
    check("скрипт: при ошибке возвращает прежнюю версию", ":restore" in text
          and 'ren "%APP%\\%OLDNAME%" "_internal"' in text and 'Robocopy.exe" "%BAK%" "%APP%"' in text)
    check("скрипт: перезапуск с --updated", '"%APP%\\%EXE%" --updated' in text and 'set "EXE=AutoPrintCode.exe"' in text)
    check("скрипт: журнал", f'set "LOG={logf}"' in text)
    allowed = ('"%BAK%"', '"%APP%\\%OLDNAME%"', '"%APP%\\_internal"', '"%APP%\\%WOLD%"', '"%APP%\\window"',
               '"%~f0"')
    deletes = [ln.strip() for ln in text.splitlines() if ln.lstrip().startswith(("rmdir", "del ", "(goto)"))
               or " rmdir " in ln]
    check("скрипт: удаляет только копию, отложенные и новые библиотеки (не data)",
          deletes and all(any(a in ln for a in allowed) for ln in deletes), "\n".join(deletes))
    s.unlink()


def test_helper_run() -> None:
    if sys.platform != "win32":
        print("SKIP прогон скрипта — только Windows")
        return

    # 1. успешная установка
    app, src, bak, logf, script = fresh("ok")
    updater.write_update_helper(src, app, dead_pid(), "0.5.0", script=script, log_file=logf, backup=bak, retries=1)
    t = time.monotonic()
    code = run_helper(script)
    log_text = logf.read_text(encoding="utf-8", errors="replace") if logf.exists() else ""
    check("прогон: скрипт завершился", code == 0, f"код {code}")
    check("прогон: exe заменён", (app / "AutoPrintCode.exe").read_bytes() == NEW_BUILD["AutoPrintCode.exe"])
    check("прогон: _internal новой версии", (app / "_internal/common.txt").read_bytes() == b"new common!!"
          and (app / "_internal/new.dll").exists()
          and (app / "_internal/sub/x.pyd").read_bytes() == NEW_BUILD["_internal/sub/x.pyd"])
    check("прогон: устаревшие библиотеки убраны", not (app / "_internal/old.dll").exists())
    check("прогон: окно программы новое целиком", (app / "window/AutoPrintCodeWindow.exe").read_bytes()
          == NEW_BUILD["window/AutoPrintCodeWindow.exe"] and (app / "window/resources/app.asar").exists()
          and not (app / "window/locales/de.pak").exists())
    check("прогон: отложенное окно удалено", not list(app.glob("window.old*")))
    check("прогон: data программы не тронута", (app / "data/settings.json").read_bytes() == b'{"keep": true}'
          and (app / "data/templates.json").read_bytes() == b"[]")
    check("прогон: data из сборки не скопирована", not (app / "data/evil.json").exists())
    check("прогон: чужие файлы в папке программы на месте", (app / "unins000.exe").read_bytes() == b"uninstaller")
    check("прогон: отложенные библиотеки и копия удалены", not list(app.glob("_internal.old*")) and not bak.exists())
    check("прогон: журнал на русском, без кракозябр", "Готово: установлена версия 0.5.0" in log_text, log_text[-500:])
    check("прогон: скрипт удалил себя", not script.exists())
    print(f"     (успешная установка: {time.monotonic() - t:.1f} с)")

    # 2. новый exe не записать (занят) → откат
    app, src, bak, logf, script = fresh("fail")
    updater.write_update_helper(src, app, dead_pid(), "0.5.0", script=script, log_file=logf, backup=bak, retries=1)
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k32.CreateFileW.restype = wintypes.HANDLE
    # читать можно (копия создаётся), писать нельзя (как у запущенного файла)
    h = k32.CreateFileW(str(app / "AutoPrintCode.exe"), 0x80000000, 0x1, None, 3, 0x80, None)
    check("откат: файл занят для теста", h not in (None, wintypes.HANDLE(-1).value))
    try:
        code = run_helper(script)
    finally:
        k32.CloseHandle(h)
    log_text = logf.read_text(encoding="utf-8", errors="replace") if logf.exists() else ""
    check("откат: скрипт завершился", code == 0, f"код {code}")
    check("откат: прежняя версия на месте (exe, _internal, data)", old_untouched(app),
          str(sorted(p.relative_to(app).as_posix() for p in app.rglob("*"))))
    check("откат: отложенная папка возвращена", not list(app.glob("_internal.old*")))
    check("откат: окно программы — прежнее целиком", not (app / "window/resources/app.asar").exists()
          and not list(app.glob("window.old*")))
    check("откат: в журнале", "возвращаем прежнюю версию" in log_text and "Прежняя версия возвращена" in log_text,
          log_text[-800:])

    # 3. программа не закрылась → ничего не меняется
    app, src, bak, logf, script = fresh("timeout")
    updater.write_update_helper(src, app, os.getpid(), "0.5.0", script=script, log_file=logf, backup=bak,
                                wait_s=2, retries=1)
    code = run_helper(script)
    log_text = logf.read_text(encoding="utf-8", errors="replace") if logf.exists() else ""
    check("ожидание: не дождавшись выхода, ничего не меняет", code == 0 and old_untouched(app) and not bak.exists())
    check("ожидание: в журнале", "не закрылась за 2 с" in log_text, log_text[-500:])


def main() -> int:
    check("данные теста — во временной папке", str(updater.UPDATES_DIR).startswith(str(TMP)))
    for t in (test_releases, test_sha, test_stage_exe, test_guards, test_last_update, test_manager,
              test_program_files, test_helper_text, test_helper_run):
        try:
            t()
        except Exception as e:   # упавший тест не должен скрыть остальные
            import traceback
            traceback.print_exc()
            check(f"{t.__name__}: без исключений", False, repr(e))
    shutil.rmtree(TMP, ignore_errors=True)
    print("ИТОГ:", "всё в порядке" if not fails else f"ошибок: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
