@echo off
rem FastAPI backend (server-py) on http://localhost:8080
cd /d D:\bj\server-py
if not exist ".venv" (
  echo [setup] First run: creating venv and installing dependencies...
  python -m venv .venv
  .venv\Scripts\pip.exe install -r requirements.txt
)
rem Load college name from root .env for the sidebar header (CLASSFEE_COLLEGE_NAME only).
rem This .env is for compose; only take this one key so dev does not write uploads to /app/uploads.
rem .env is UTF-8: switch the console to UTF-8 first, or cmd (GBK) mangles the Chinese value.
chcp 65001 >nul
for /f "usebackq tokens=1,* delims==" %%A in ("D:\bj\.env") do (
  if "%%A"=="CLASSFEE_COLLEGE_NAME" set "%%A=%%B"
)
rem Loopback only. --reload restarts the server automatically when backend code changes (dev only).
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
pause
