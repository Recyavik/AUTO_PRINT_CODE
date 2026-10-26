@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Установка: Таймер вебинара
echo.
echo   Установка «Таймера вебинара» — нужна один раз на каждом компьютере.
echo   Папка программы: %CD%
echo.

rem ---- 1. Python 3.9+ с PySide6-совместимой сборкой (не «t» без GIL): py-лаунчер, PATH, обычные папки
set "PY="
set "CHECK=import sys, sysconfig; sys.exit(sys.version_info < (3, 9) or bool(sysconfig.get_config_var('Py_GIL_DISABLED')))"
for %%V in (3.13 3.12 3.14 3.11 3.10 3) do if not defined PY py -%%V -c "%CHECK%" >nul 2>&1 && set "PY=py -%%V"
if not defined PY python -c "%CHECK%" >nul 2>&1 && set "PY=python"
if not defined PY for %%V in (313 312 311 310) do if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
if not defined PY (
  echo   Python не найден — устанавливаю Python 3.12 через winget (для текущего пользователя, без прав администратора^)...
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PY (
  echo.
  echo   Не удалось найти или установить Python.
  echo   Установите Python 3.12 с https://www.python.org/downloads/ ^(галочка «Add python.exe to PATH»^)
  echo   и снова запустите «Установка.bat».
  goto fail
)
echo   Python: %PY%

rem ---- 2. Окружение .venv внутри папки. Скопированное с другого компьютера не работает — пересоздаём
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "%CHECK%" >nul 2>&1 || (
    echo   Окружение не подходит ^(скопировано с другого компьютера?^) — создаю заново...
    rmdir /s /q ".venv"
  )
)
if not exist ".venv\Scripts\python.exe" (
  echo   Создаю окружение .venv...
  %PY% -m venv .venv || goto fail
)

rem ---- 3. Библиотеки (PySide6 — окна, видео, трей)
echo   Устанавливаю библиотеки (первый раз — несколько минут)...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto fail

rem ---- 4. Значок и ярлык на рабочем столе
".venv\Scripts\python.exe" -m webinar.install || goto fail

echo.
echo   Готово! Запуск — ярлык «Таймер вебинара» на рабочем столе или «Таймер вебинара.bat» в этой папке.
echo.
if not defined WEBINAR_SETUP_NOPAUSE pause
exit /b 0

:fail
echo.
echo   Установка не удалась — сообщение об ошибке выше.
echo.
if not defined WEBINAR_SETUP_NOPAUSE pause
exit /b 1
