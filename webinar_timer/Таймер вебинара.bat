@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem Окружение, которое создаёт «Установка.bat» (работает, только если создано на этом компьютере)
if exist ".venv\Scripts\pythonw.exe" (
  ".venv\Scripts\python.exe" -c "import PySide6" >nul 2>&1 && (
    start "" ".venv\Scripts\pythonw.exe" webinar.py
    exit /b 0
  )
)

rem Без установки — системный Python, если в нём уже есть PySide6
python -c "import PySide6" >nul 2>&1 && (
  start "" pythonw webinar.py
  exit /b 0
)

echo.
echo   Таймер вебинара ещё не установлен на этом компьютере.
echo   Запустите «Установка.bat» в этой папке (один раз), потом снова этот файл.
echo.
pause
exit /b 1
