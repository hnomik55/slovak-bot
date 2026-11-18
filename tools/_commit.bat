@echo off
cd /d "%~dp0"
set "G=C:\Program Files\Git\cmd\git.exe"
"%G%" add -A
"%G%" commit -m "feat: licenzii - odnorazovyy klyuch dostupa i podpiski"
"%G%" log --oneline -3
