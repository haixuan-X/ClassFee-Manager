@echo off
rem FastAPI backend (server-py) on http://localhost:8080
cd /d D:\bj\server-py
if not exist ".venv" (
  echo [setup] First run: creating venv and installing dependencies...
  python -m venv .venv
  .venv\Scripts\pip.exe install -r requirements.txt
)
rem 载入项目根目录 .env 里的「学院名」（显示在侧栏顶部）。
rem 只取这一个键：.env 是**给 compose 用的**（里面的上传目录是容器里的 /app/uploads），
rem 整个文件都灌进来会让本地开发把图片写到 D:\app\uploads 去。
for /f "usebackq tokens=1,* delims==" %%A in ("D:\bj\.env") do (
  if "%%A"=="CLASSFEE_COLLEGE_NAME" set "%%A=%%B"
)
rem Bind loopback only. 0.0.0.0 would expose the unauthenticated dev API to the whole LAN.
rem Docker keeps 0.0.0.0 inside the container network (see docker-compose*.yml) - unchanged.
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080
pause
