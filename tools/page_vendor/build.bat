@echo off
rem CodeMirror 6 для экрана урока: собрать autoprintfir\pageendor\cm6.js (нужен Node.js)
cd /d "%~dp0"
call npm install --no-audit --no-fund || exit /b 1
call npm run build
