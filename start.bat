@echo off
rem ============================================================
rem   Slovencina - Telegram bot for learning Slovak
rem   Keep this window open while you study.
rem ============================================================
cd /d "%~dp0"
title Slovencina bot

rem --- find a python that has aiogram ---
set "PY="
for %%i in ("python" "%LOCALAPPDATA%\WindowsApps\PythonSoftwareFoundation.Python.3.9_qbz5n2kfra8p0\python.exe" "%LOCALAPPDATA%\Python\bin\python.exe") do (
    if not defined PY (
        %%~i -c "import aiogram" >nul 2>&1
        if not errorlevel 1 set "PY=%%~i"
    )
)

if not defined PY (
    echo.
    echo   ERROR: aiogram is not installed for any known Python.
    echo   Run this once in PowerShell:
    echo.
    echo     python -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo   Python: %PY%

if not exist ".env" (
    echo   Creating .env from .env.example ...
    copy ".env.example" ".env" >nul
)

findstr /C:"XXXXTOKENXXXX" ".env" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo   BOT_TOKEN is not set. Opening .env in Notepad ...
    echo   Paste the token from BotFather after BOT_TOKEN=
    echo   Save with Ctrl+S, close Notepad, run start.bat again.
    echo.
    notepad ".env"
    pause
    exit /b 1
)

if not exist "data\content.json" (
    echo   Building content from D:\Slovakia ...
    "%PY%" tools\build_content.py
    echo.
)

echo   Starting bot. Keep this window open.
echo   Open your bot in Telegram and press /start
echo.
"%PY%" bot.py

echo.
echo   Bot stopped.
pause
