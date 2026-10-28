"""在 PyCharm 里直接运行后端（等价于 start-backend.bat）。

右键本文件 → Run 'run'，或点右上角绿色三角即可。默认地址：

    http://127.0.0.1:8080
    接口文档 http://127.0.0.1:8080/docs

普通 Run 会开后端热重载（改完代码自动重启）；用 Debug 运行时自动关掉，
否则断点会落在 uvicorn 重载出来的子进程里。

只起后端。前端另开一个终端：

    cd web
    npm run dev
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
REPO_DIR = SERVER_DIR.parent


def _load_college_name() -> None:
    """从仓库根 .env 只取 CLASSFEE_COLLEGE_NAME。

    .env 是给 compose 用的（上传目录写的是容器里的 /app/uploads），
    整个灌进环境变量会让本地把图片写到 D:\\app\\uploads。
    和 start-backend.bat 同一个口径：只取学院名。
    """
    if os.environ.get("CLASSFEE_COLLEGE_NAME"):
        return
    env_file = REPO_DIR / ".env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() != "CLASSFEE_COLLEGE_NAME":
            continue
        value = value.strip().strip("\"'")
        if value:
            os.environ["CLASSFEE_COLLEGE_NAME"] = value
        return


def main() -> None:
    # PyCharm 的工作目录可能是项目根，也可能是 server-py；
    # 统一切到 server-py，uploads / app 包 / 相对路径才不会找错。
    os.chdir(SERVER_DIR)
    if str(SERVER_DIR) not in sys.path:
        sys.path.insert(0, str(SERVER_DIR))
    _load_college_name()

    try:
        import uvicorn
    except ModuleNotFoundError:
        raise SystemExit(
            "没找到 uvicorn。请把 PyCharm 解释器选成 "
            "server-py\\.venv\\Scripts\\python.exe，或先执行：\n"
            "  .venv\\Scripts\\pip install -r requirements.txt"
        ) from None

    host = os.environ.get("CLASSFEE_HOST", "127.0.0.1")
    port = int(os.environ.get("CLASSFEE_PORT", "8080"))
    reload = os.environ.get("CLASSFEE_RELOAD", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    # PyCharm 的 Debug 和 reload 不能共存：断点会落在子进程里，主进程也停不住
    if sys.gettrace() is not None:
        reload = False

    college = os.environ.get("CLASSFEE_COLLEGE_NAME") or "（未配置学院名）"
    print(f"backend  http://{host}:{port}")
    print(f"docs     http://{host}:{port}/docs")
    print(f"college  {college}")
    print(f"reload   {'on' if reload else 'off'}")
    print("frontend cd web && npm run dev    （另开一个终端）")
    print()

    # reload 必须传 import string：重载器要在子进程里重新 import
    uvicorn.run("app.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
