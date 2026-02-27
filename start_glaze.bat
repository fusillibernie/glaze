@echo off
title Glaze - Ceramic Glaze Formulator
cd /d C:\Users\pwong\projects\glaze
call .venv\Scripts\activate
echo.
echo ========================================
echo   Glaze - Ceramic Glaze Formulator
echo ========================================
echo.
echo Starting server at http://localhost:8000
echo Web UI at http://localhost:8000
echo API docs at http://localhost:8000/docs
echo.
echo Press Ctrl+C to stop the server
echo.

REM Open browser after delay (in background)
start /b cmd /c "timeout /t 4 /nobreak >nul && start http://localhost:8000"

REM Start the server (this keeps the window open)
.venv\Scripts\uvicorn.exe api.main:app --reload --port 8000
