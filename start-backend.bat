@echo off
rem FastAPI backend (server-py) on http://localhost:8080
cd /d D:\bj\server-py
if not exist ".venv" (
  echo [setup] First run: creating venv and installing dependencies...
  python -m venv .venv
  .venv\Scripts\pip install -r requirements.txt
)
rem Bind loopback only. 0.0.0.0 would expose the unauthenticated dev API to the whole LAN.
rem Docker keeps 0.0.0.0 inside the container network (see docker-compose*.yml) - unchanged.
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080
pause
