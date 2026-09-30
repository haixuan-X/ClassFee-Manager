# ---- 班费收支系统 · Python 后端（FastAPI，对应原 Java 服务，契约一致）----
FROM python:3.13-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    PIP_DISABLE_PIP_VERSION_CHECK=1
# 依赖先装（层缓存）：全部为 manylinux wheel，无需编译工具链
COPY requirements.txt .
# 装完立刻 import 一次做冒烟：依赖解析问题会在**构建期**暴露，而不是等到服务器上启动才 500
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "import fastapi, sqlalchemy, pymysql, jwt, bcrypt, pydantic, openpyxl, multipart; print('deps ok')"
# app/ 业务代码 + db/schema.sql（启动时幂等执行建表与种子数据）
COPY app ./app
COPY db ./db
# 非 root 运行；uploads 目录预建好，named volume 挂载时属主自动继承
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/uploads \
    && chown -R appuser:appuser /app
USER appuser
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
