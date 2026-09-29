@echo off
rem Чат-бот «МедМаршрут» (long polling). ВАЖНО: экземпляр должен быть один!
cd /d "%~dp0"
.venv\Scripts\python.exe run_bot.py

pause
