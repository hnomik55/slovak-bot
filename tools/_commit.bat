@echo off
cd /d "%~dp0"
set "G=C:\Program Files\Git\cmd\git.exe"
"%G%" add -A
"%G%" commit -m "feat: Mini App - prilozhenie vnutri Telegram"
"%G%" log --oneline -3
"%G%" status --short
