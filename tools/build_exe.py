"""Сборка AutoPrintCode.exe (PyInstaller, onedir) и файлов для GitHub Releases.

    .venv\\Scripts\\python.exe tools\\build_exe.py       (или build_exe.bat)

Что получается в dist\\:
    AutoPrintCode\\                          — программа: AutoPrintCode.exe + _internal\\
    AutoPrintCode-<версия>-win64.zip         — этот архив и .sha256 к нему прикладываются к релизу,
    AutoPrintCode-<версия>-win64.zip.sha256    по ним собранная программа обновляется сама
    AutoPrintCode-<версия>-Setup.exe (+ .sha256) — установщик, если найден Inno Setup 6 (ISCC.exe)

Номер версии — __version__ из autoprint/__init__.py. Значок рисуется autoprint.ui.logo.save_ico.
Нужен PyInstaller: pip install -r requirements-dev.txt
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"
NAME = "AutoPrintCode"
APP_DIST = DIST / NAME
ISS = ROOT / "installer" / f"{NAME}.iss"

# Модули Python, которые программе не нужны (tkinter — только тестовое окно в tests/)
EXCLUDES = [
    "tkinter", "_tkinter", "turtle", "turtledemo", "idlelib", "unittest", "doctest", "pydoc", "pydoc_data",
    "lib2to3", "test", "ensurepip", "venv", "distutils", "setuptools", "pkg_resources", "pip",
    "PyInstaller", "sqlite3", "_sqlite3", "xmlrpc", "curses",
    "PySide6.QtMultimediaWidgets",   # хук QtMultimedia добавляет его «на всякий случай»
]
# Нужны обязательно: QtMultimedia (QSoundEffect), QtSvg (значки), QtNetwork (QLocalServer —
# второй запуск активирует уже открытое окно)
HIDDEN = ["PySide6.QtMultimedia", "PySide6.QtSvg", "PySide6.QtNetwork", "PySide6.QtPdf"]   # QtPdf — материал урока из PDF

# Лишние двоичные файлы Qt (имена в сборке, без учёта регистра), всего ~60 МБ:
# - FFmpeg и его плагин (~20 МБ): QSoundEffect играет WAV через windowsmediaplugin — проверено;
# - opengl32sw.dll (~20 МБ): программный OpenGL, программе на виджетах он не нужен;
# - экранная клавиатура (platforminputcontexts) — только она тянет Qt Quick/QML/OpenGL (~16 МБ);
# - OpenSSL для Qt (*-x64.dll и qopensslbackend): QtNetwork нужен лишь для QLocalServer, а HTTPS
#   у обновлений идёт через ssl самого Python (libssl-3.dll — остаётся);
# - платформы qdirect2d/qminimal, networkinformation, тач-плагин TUIO, imageformats/qpdf (Qt6Pdf остаётся:
#   суфлёр урока читает методички в PDF);
# - переводы Qt, кроме русских (их можно подключить QTranslator'ом), и справка Qt Help.
DROP_PATTERNS = [
    r"(^|/)opengl32sw\.dll$",
    r"(^|/)(avcodec|avformat|avutil|avdevice|avfilter|swresample|swscale)-\d+\.dll$",
    r"/plugins/multimedia/ffmpegmediaplugin\.dll$",
    r"/plugins/platforminputcontexts/",
    r"(^|/)qt6(virtualkeyboard|quick|qml|qmlmeta|qmlmodels|qmlworkerscript|opengl)\.dll$",
    r"(^|/)lib(ssl|crypto)-3-x64\.dll$",
    r"/plugins/tls/qopensslbackend\.dll$",
    r"/plugins/platforms/(qdirect2d|qminimal)\.dll$",
    r"/plugins/networkinformation/",
    r"/plugins/generic/qtuiotouchplugin\.dll$",
    r"/plugins/imageformats/qpdf\.dll$",
    r"/translations/(?!.*_ru\.qm$)[^/]+\.qm$",
    r"/translations/qt_help_[^/]+\.qm$",
]
# Это в сборке должно быть обязательно — проверяется после PyInstaller
REQUIRED = [
    f"{NAME}.exe", "_internal/PySide6/Qt6Multimedia.dll", "_internal/PySide6/Qt6Network.dll",
    "_internal/PySide6/Qt6Svg.dll", "_internal/PySide6/plugins/multimedia/windowsmediaplugin.dll",
    "_internal/PySide6/plugins/platforms/qwindows.dll", "_internal/PySide6/plugins/imageformats/qsvg.dll",
    "_internal/PySide6/plugins/iconengines/qsvgicon.dll", "_internal/autoprint/sounds/SOURCES.md", "_internal/autoprint/efir/page/screen.html",
    "_internal/autoprint/efir/page/lesson.html", "_internal/autoprint/efir/page/favicon.svg",
    "_internal/autoprint/samples/lesson-example.md", "_internal/autoprint/samples/lesson-example_files/func-scheme.png",
    "_internal/autoprint/efir/page/lang/python.svg",
    "_internal/autoprint/efir/page/lesson/app.js",
    "_internal/PySide6/Qt6Pdf.dll",
]

SPEC = '''# -*- mode: python ; coding: utf-8 -*-
# Создано tools/build_exe.py при сборке — правьте там, а не здесь.
import re

DROP = [re.compile(p, re.IGNORECASE) for p in {drop!r}]


def _keep(entry):
    name = entry[0].replace("\\\\", "/")
    return not any(p.search(name) for p in DROP)


a = Analysis(
    [{script!r}],
    pathex=[{root!r}],
    binaries=[],
    datas={datas!r},
    hiddenimports={hidden!r},
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes={excludes!r},
    noarchive=False,
    optimize=0,
)
a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name={name!r},
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=[{icon!r}],
    version={version_file!r},
    contents_directory="_internal",
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name={name!r})
'''

VERSION_INFO = '''# -*- coding: utf-8 -*-
# Создано tools/build_exe.py: ресурс версии AutoPrintCode.exe
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={nums!r},
    prodvers={nums!r},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('041904B0', [
        StringStruct('CompanyName', {name!r}),
        StringStruct('FileDescription', {name!r}),
        StringStruct('FileVersion', {version!r}),
        StringStruct('InternalName', {name!r}),
        StringStruct('OriginalFilename', {exe!r}),
        StringStruct('ProductName', {name!r}),
        StringStruct('ProductVersion', {version!r}),
        StringStruct('Comments', {comments!r}),
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [0x0419, 1200])])
  ]
)
'''


def say(text: str) -> None:
    print(f"[build] {text}", flush=True)


def read_version() -> str:
    text = (ROOT / "autoprint" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r"""__version__\s*=\s*["']([^"']+)""", text)
    if not m:
        sys.exit("Не найден __version__ в autoprint/__init__.py")
    return m.group(1)


def numeric_version(version: str) -> tuple[int, int, int, int]:
    """'0.5.0-beta.1' → (0, 5, 0, 0): для ресурса версии Windows нужны только числа."""
    nums = [int(x) for x in re.findall(r"\d+", version.split("-")[0].split("+")[0])][:4]
    return tuple((nums + [0, 0, 0, 0])[:4])


def make_icon(path: Path) -> None:
    """Значок программы — тот же, что рисует сама программа (autoprint.ui.logo)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(ROOT))
    from PySide6.QtGui import QGuiApplication
    from autoprint.ui import logo
    app = QGuiApplication.instance() or QGuiApplication([sys.argv[0]])  # noqa: F841 — нужен для QPixmap
    path.parent.mkdir(parents=True, exist_ok=True)
    if not logo.save_ico(path):
        sys.exit(f"Не удалось сохранить значок {path}")


def collect_datas() -> list[tuple[str, str]]:
    sounds = ROOT / "autoprint" / "sounds"
    datas = [(str(p), p.parent.relative_to(ROOT).as_posix()) for p in sorted(sounds.rglob("*.wav"))]
    if not datas:
        sys.exit("Нет звуков в autoprint/sounds — сборка без них была бы немой")
    datas.append((str(sounds / "SOURCES.md"), "autoprint/sounds"))
    page = ROOT / "autoprint" / "efir" / "page"          # страница экрана эфира (вкладка браузера)
    datas += [(str(f), "autoprint/efir/page") for f in sorted(page.glob("*.html")) + [page / "favicon.svg"]]
    samples = ROOT / "autoprint" / "samples"              # образцовый урок (.md) и его картинки
    datas.append((str(samples / "lesson-example.md"), "autoprint/samples"))
    datas += [(str(f), "autoprint/samples/lesson-example_files")
              for f in sorted((samples / "lesson-example_files").glob("*.png"))]
    lang = page / "lang"                                  # значки языков для кода на странице суфлёра урока
    datas += [(str(f), "autoprint/efir/page/lang") for f in sorted(lang.glob("*.svg"))]
    datas.append((str(lang / "LICENSE-devicon.txt"), "autoprint/efir/page/lang"))
    for sub in ("lesson", "vendor"):                      # скрипты экрана урока и CodeMirror
        d = page / sub
        datas += [(str(f), f"autoprint/efir/page/{sub}") for f in sorted(d.glob("*")) if f.suffix in (".js", ".css", ".txt")]
    return datas


def run_pyinstaller(version: str, icon: Path) -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("PyInstaller не установлен. Выполните: .venv\\Scripts\\python.exe -m pip install -r requirements-dev.txt")
    version_file = BUILD / "version_info.txt"
    version_file.write_text(VERSION_INFO.format(
        nums=numeric_version(version), version=version, name=NAME, exe=f"{NAME}.exe",
        comments="Печатает заготовленный код в любое окно — https://github.com/DanT2000/AUTO_PRINT_CODE"),
        encoding="utf-8")
    spec = BUILD / f"{NAME}.spec"
    spec.write_text(SPEC.format(
        drop=DROP_PATTERNS, script=str(ROOT / "app.py"), root=str(ROOT), datas=collect_datas(), hidden=HIDDEN,
        excludes=EXCLUDES, name=NAME, icon=str(icon), version_file=str(version_file)), encoding="utf-8")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--log-level", "WARN",
           "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller"), str(spec)]
    say("PyInstaller: " + " ".join(cmd[3:]))
    if subprocess.run(cmd, cwd=str(ROOT)).returncode != 0:
        sys.exit("PyInstaller завершился с ошибкой")


def check_dist() -> None:
    missing = [r for r in REQUIRED if not (APP_DIST / r).exists()]
    if missing:
        sys.exit("В сборке нет обязательных файлов:\n  " + "\n  ".join(missing))
    wavs = list((APP_DIST / "_internal" / "autoprint" / "sounds").rglob("*.wav"))
    dropped = [p for p in APP_DIST.rglob("*")
               if any(re.search(d, p.relative_to(APP_DIST).as_posix(), re.IGNORECASE) for d in DROP_PATTERNS)]
    if dropped:
        sys.exit("В сборку попали исключённые файлы:\n  " + "\n  ".join(map(str, dropped)))
    if (APP_DIST / "data").exists():
        sys.exit(f"В {APP_DIST} есть папка data — это чьи-то образцы и настройки, в релиз их класть нельзя")
    say(f"Сборка проверена: {len(wavs)} звуков, Qt Multimedia/Network/Svg на месте")


def dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def mb(n: int) -> str:
    return f"{n / 1_048_576:.1f} МБ"


def write_sha256(path: Path) -> Path:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    out = path.with_name(path.name + ".sha256")
    # формат sha256sum: «<hex>  <имя файла>»
    out.write_text(f"{h.hexdigest()}  {path.name}\n", encoding="ascii", newline="\n")
    return out


def make_zip(version: str) -> Path:
    """Архив для релиза: внутри папка AutoPrintCode\\ (exe + _internal), без data\\."""
    dest = DIST / f"{NAME}-{version}-win64.zip"
    dest.unlink(missing_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(APP_DIST.rglob("*")):
            rel = p.relative_to(APP_DIST)
            if rel.parts[0].lower() == "data":
                continue
            arc = (Path(NAME) / rel).as_posix()
            if p.is_dir():
                continue
            z.write(p, arc)
    return dest


def find_iscc() -> Path | None:
    for name in ("ISCC.exe", "iscc"):
        found = shutil.which(name)
        if found:
            return Path(found)
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        if base:
            for ver in ("Inno Setup 6", "Inno Setup 7"):
                p = Path(base) / ver / "ISCC.exe"
                if p.is_file():
                    return p
    return None


def make_setup(version: str, icon: Path) -> Path | None:
    iscc = find_iscc()
    if iscc is None:
        say("Inno Setup (ISCC.exe) не найден — установщик не собран. Он необязателен: для автообновления "
            "достаточно zip и .sha256. Чтобы собирать и установщик, поставьте Inno Setup 6 (jrsoftware.org).")
        return None
    num = ".".join(map(str, numeric_version(version)))
    cmd = [str(iscc), "/Q", f"/DAppVersion={version}", f"/DAppNumVersion={num}", f"/DSourceDir={APP_DIST}",
           f"/DOutputDir={DIST}", f"/DIconFile={icon}", str(ISS)]
    say("Inno Setup: " + " ".join(cmd[1:]))
    if subprocess.run(cmd, cwd=str(ISS.parent)).returncode != 0:
        sys.exit("Inno Setup завершился с ошибкой")
    setup = DIST / f"{NAME}-{version}-Setup.exe"
    if not setup.is_file():
        sys.exit(f"Inno Setup не создал {setup}")
    return setup


def main() -> int:
    t0 = time.monotonic()
    version = read_version()
    say(f"{NAME} {version}")
    BUILD.mkdir(exist_ok=True)
    DIST.mkdir(exist_ok=True)
    icon = BUILD / "icon.ico"
    make_icon(icon)
    run_pyinstaller(version, icon)
    check_dist()

    for old in DIST.glob(f"{NAME}-*"):   # архивы и установщики прошлых сборок
        if old.is_file():
            old.unlink()
    zip_path = make_zip(version)
    outputs = [zip_path, write_sha256(zip_path)]
    setup = make_setup(version, icon)
    if setup:
        outputs += [setup, write_sha256(setup)]

    say(f"Готово за {time.monotonic() - t0:.0f} с. Папка программы {APP_DIST}: {mb(dir_size(APP_DIST))}")
    for p in outputs:
        say(f"  {p.name}: {mb(p.stat().st_size) if p.stat().st_size > 1024 else str(p.stat().st_size) + ' Б'}")
    say(f"Приложите к релизу v{version} на GitHub файлы из {DIST}: " + ", ".join(p.name for p in outputs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
