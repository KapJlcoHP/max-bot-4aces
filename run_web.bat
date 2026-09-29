@echo off
rem Dev-сервер мини-апа (Vite): http://localhost:5173 — проксирует /api на :8000.
rem Сначала запустите run_api.bat!
cd /d "%~dp0web"
call npm run dev

pause
