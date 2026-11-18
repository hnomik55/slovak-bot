@echo off
rem Управление ботом: botctl.bat start | stop | restart | status | log
cd /d "%~dp0"
set "CMD=%~1"
if "%CMD%"=="" set "CMD=status"
python tools\botctl.py %CMD%
if /i "%CMD%"=="start" (
    echo.
    echo   Бот работает в фоне. Открой @Slovak_is_easy_bot и нажми /start
    timeout /t 5 >nul
)
