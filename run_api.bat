@echo off
rem API-сервер «МедМаршрут» (FastAPI): REST для мини-апа на http://127.0.0.1:8000
cd /d "%~dp0"
.venv\Scripts\python.exe -m uvicorn server.main:app --reload --host 127.0.0.1 --port 8000

pause
