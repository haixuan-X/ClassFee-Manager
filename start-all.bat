@echo off
rem Double-click: opens backend (8080) and frontend (5173) in two windows.
rem Stop: close the windows or press Ctrl+C inside them.

start "ClassFee Backend (8080)" cmd /k D:\bj\start-backend.bat
timeout /t 2 >nul
start "ClassFee Frontend (5173)" cmd /k D:\bj\start-frontend.bat

echo Started. Wait a few seconds, then open http://localhost:5173
timeout /t 5
