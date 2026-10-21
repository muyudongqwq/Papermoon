@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
where py >nul 2>nul
if errorlevel 1 (
    python -m skilleditor
) else (
    py -3 -m skilleditor
)
if errorlevel 1 pause
