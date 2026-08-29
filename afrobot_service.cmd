@echo off
setlocal
cd /d "%~dp0"
set PY=C:\Users\emman\AppData\Local\Python\pythoncore-3.14-64\python.exe
set LOG=%~dp0afrobot.log

:loop
rem rotate log if it grows past ~5 MB
if exist "%LOG%" for %%F in ("%LOG%") do if %%~zF GTR 5000000 move /y "%LOG%" "%LOG%.old" >nul 2>&1
echo [%date% %time%] starting afrobot >> "%LOG%"
"%PY%" news_bot.py >> "%LOG%" 2>&1
echo [%date% %time%] afrobot exited, restarting in 15s >> "%LOG%"
timeout /t 15 /nobreak >nul
goto loop
