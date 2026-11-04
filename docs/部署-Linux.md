# 学生信息管理系统 · 部署指南（Linux）

> 目标形态（单机即可跑通）：
>
> ```
> 浏览器 ──▶ nginx (:80)
>              ├─ 静态文件（web/dist 构建产物）
>              └─ /api 反代 ──▶ FastAPI 后端 (127.0.0.1:8080) ──▶ MariaDB (localhost:3306)
> ```

前端 axios 用相对路径 `/api`，经 nginx 同源转发，**无需处理跨域**；路由为 history 模式，nginx 必须配 SPA 回退。

**两条路线，选一条**：

| 路线 | 章节 | 服务器要装什么 | 适合 |
|------|------|--------------|------|
| **A. 手动部署** | §1–§5 | Python 3.13、Node、MariaDB、nginx | 要自定义、反代已有站点 |
| **B. Docker Compose** | §6 | Docker + compose | **最省事** |

---

## 1. 构建产物（在 Windows 本机构建，推荐）

服务器上只需运行时环境，构建放本机做：

```powershell
# 后端无需构建（Python 源码直接运行），仅需安装依赖
cd D:\bj\server-py
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 前端静态文件
cd D:\bj\web
npm run type-check && npm run build
```

得到两个产物：

| 产物 | 路径 |
|------|------|
| 后端 | `server-py/` 源码目录（上传后服务器内装依赖运行） |
| 前端 | `web/dist/`（整个目录） |

> 服务器上从零准备也可以，但**版本必须 ≥3.13**（`Dockerfile` 用 `python:3.13-slim`；
> Ubuntu 22.04 自带 3.10、Debian 12 自带 3.11，均偏低——要么自行装 3.13，
> 要么干脆走 §6 Docker）。

---

## 2. 服务器初始化（Ubuntu/Debian 示例）

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx mariadb-server

# 2.1 建库建账号（'%' 表示允许容器/外部网段连入；只要同机用则 'localhost' 即可）
sudo mysql <<'SQL'
CREATE DATABASE classfee DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'classfee'@'%' IDENTIFIED BY '你的强密码';
GRANT ALL PRIVILEGES ON classfee.* TO 'classfee'@'%';
FLUSH PRIVILEGES;
SQL
```

表结构（`schema.sql`，`IF NOT EXISTS` 幂等）与演示种子（默认类别、班级脚手架）由后端启动时自动执行，**不用手动导库**；重复启动安全。

### 2.2 上传产物归位

```powershell
# Windows 侧
scp -r D:\bj\server-py user@your-server:/tmp/server-py
scp -r D:\bj\web\dist   user@your-server:/tmp/dist
```

```bash
sudo mkdir -p /opt/classfee /var/www/classfee
sudo mv /tmp/server-py /opt/classfee/ && sudo mv /tmp/dist/* /var/www/classfee/
sudo chown -R www-data:www-data /var/www/classfee
cd /opt/classfee/server-py && sudo -u www-data python3 -m venv .venv \
  && sudo -u www-data .venv/bin/pip install -r requirements.txt
```

---

## 3. systemd 单元

`/etc/systemd/system/classfee.service`：

```ini
[Unit]
Description=ClassFee (FastAPI)
After=network.target mysql.service mariadb.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/classfee/server-py
Environment=TZ=Asia/Shanghai
Environment=CLASSFEE_DB_URL=mysql+pymysql://localhost:3306/classfee?charset=utf8mb4
Environment=CLASSFEE_DB_USERNAME=classfee
Environment=CLASSFEE_DB_PASSWORD=你的强密码
Environment=CLASSFEE_JWT_SECRET=openssl rand -hex 32 生成的随机串
# Environment=CLASSFEE_TEACHER_USERNAME=test
# Environment=CLASSFEE_TEACHER_PASSWORD=换成强口令
# Environment=CLASSFEE_COLLEGE_NAME=智能汽车学院
ExecStart=/opt/classfee/server-py/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now classfee
systemctl status classfee          # active (running)
journalctl -u classfee -f          # 看日志
```

> `uvicorn` 路径不一致就用 `ls /opt/classfee/server-py/.venv/bin/` 确认后替换。
> **`.env` 不会自动进环境变量**：`run.py` 只读 `CLASSFEE_COLLEGE_NAME`；
> 数据库账号 / JWT 密钥 / 班主任账号都要 `Environment=` 注入，
> 或 systemd 里 `EnvironmentFile=/opt/classfee/.env`（`.env` 不要入库）。

---

## 4. nginx 站点配置

`/etc/nginx/sites-available/classfee`（Debian 系；CentOS 放 `/etc/nginx/conf.d/classfee.conf`）：

```nginx
server {
    listen 80;
    server_name your-domain.com;     # 或 _ 表示默认站点

    root /var/www/classfee;
    index index.html;

    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;

    # 运行日志落到仓库 log/frontend/（见 §7）
    access_log /opt/classfee/log/frontend/access.log;
    error_log  /opt/classfee/log/frontend/error.log warn;

    # 前端路由 history 回退：刷新深层路径不 404
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API 反代；client_max_body_size 默认 1m 会让 5MB 小票 413
    location /api/ {
        client_max_body_size 6m;
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/classfee /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

> ⚠ `nginx.docker.conf` 之类的配置文件**必须 UTF-8 无 BOM**——
> BOM 会让 nginx 报 `unknown directive " server"`。
> （代码里 `test_a00_encoding_guards` 回归用例会扫描全仓库查 BOM。）

---

## 5. 验证（逐条打勾）

```bash
# 1) 后端活着（未带 token 应 401）
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/api/auth/me      # 期望 401

# 2) 登录能拿到 token（账号换成 .env 里声明的班主任）
curl -s -X POST http://127.0.0.1:8080/api/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"test","password":"你的口令"}' | head -c 120

# 3) nginx 转发正常（首页 HTML）
curl -sI http://127.0.0.1/ | head -1

# 4) SPA 深链接不 404
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1/records              # 期望 200
```

浏览器访问 `http://your-domain.com`，登录后**立即在「个人信息」页改密码**；其余账号在「成员管理」中创建。

---

## 6. Docker Compose（最省事）

无需在服务器装 Python / Node / nginx，只要 **Docker + compose 插件**（Docker 20.10+ / compose v2）。架构：`db`（MariaDB 11.4，healthcheck）→ `backend`（健康后幂等建表 + 建账号）→ `frontend`（nginx）。

```bash
scp -r D:\bj user@your-server:/opt/classfee-src    # 或只传构建必需文件，见下
cd /opt/classfee-src
cp .env.example .env        # 必填：CLASSFEE_JWT_SECRET / CLASSFEE_TEACHER_* / DB_ROOT_PASSWORD
docker compose up -d --build
docker compose ps            # db → healthy，backend → healthy，frontend → running
```

必填 `.env` 项：

```
CLASSFEE_JWT_SECRET=<openssl rand -hex 32>
CLASSFEE_TEACHER_USERNAME=test
CLASSFEE_TEACHER_PASSWORD=换成强口令
DB_ROOT_PASSWORD=强密码
```

| 文件 | 作用 |
|------|------|
| `docker-compose.yml` | db + backend + frontend，healthcheck 与数据卷（`db-data` / `classfee_uploads`）齐全 |
| `docker-compose.use-existing-db.yml` | **复用服务器已有库**（仅 backend + frontend 两容器） |
| `web/nginx.docker.conf` | SPA 回退 + `/api` 反代；**必须无 BOM** |
| `.env.example` | 全部变量的中文注释模板 |

**服务器上已有 MySQL/MariaDB** 时用 use-existing-db 变体（不另起库容器）：

```bash
# 1) 建库建账号（'%' 允许容器网段连入；localhost 会被容器连不上）
sudo mysql -e "CREATE DATABASE classfee; CREATE USER 'classfee'@'%' IDENTIFIED BY '你的强密码'; GRANT ALL ON classfee.* TO 'classfee'@'%';"
# 2) 确认 bind-address=0.0.0.0（默认常是 127.0.0.1），3306 对容器网段放行
# 3) .env 填 DB_HOST/DB_PORT/DB_NAME/DB_USERNAME/DB_PASSWORD（不是 DB_ROOT_PASSWORD）
docker compose -f docker-compose.use-existing-db.yml up -d --build
```

| 报错 | 原因 | 处理 |
|------|------|------|
| `Access denied for user 'classfee'@'172.17.x.x'` | 账号只授权给 localhost | 补 `'%'` 主机 + GRANT |
| `Can't connect to MySQL server on '127.0.0.1'` | 容器里 `127.0.0.1` 指容器自己 | 同机填宿主内网 IP 或 `host.docker.internal` |
| `unknown directive " server"` | `nginx.docker.conf` 带 BOM | `sed -i '1s/^\xEF\xBB\xBF//' web/nginx.docker.conf` 后重新 `up -d --build` |

常用操作：

```bash
docker compose logs -f backend        # 后端日志（db / frontend 同理）
docker compose up -d --build          # 发版（**只重启不生效**）
docker compose down                   # 停止（卷保留）
docker compose down -v                # 停止并删库（慎用）

# 备份数据库
docker compose exec db sh -c 'exec mysqldump -uroot -p"$MARIADB_ROOT_PASSWORD" classfee' > backup_$(date +%F).sql

# 备份小票（小票不在数据库里，在磁盘卷）
docker run --rm -v classfee_uploads:/data -v "$PWD":/backup alpine \
  tar czf /backup/uploads_$(date +%F).tgz -C /data .
```

---

## 7. 运行日志（`log/`）

仓库根下的 `log/` 按**后端 / 前端 / 数据库**三类分离，**除 `README.md` 与 `.gitkeep` 外不入库**（日志含姓名学号痕迹）：

| 目录 | 内容 | 怎么开 |
|------|------|--------|
| `log/backend/` | 后端应用 + uvicorn 访问/错误日志 | **自动**（5MB×6 份；`CLASSFEE_LOG_DIR` 可改路径） |
| `log/frontend/` | nginx access/error；本地 `npm run dev:log` 的 vite 输出 | docker：compose 已挂载 `./log/frontend → /var/log/classfee`；直跑：nginx 配两行；本地 `npm run dev:log` |
| `log/database/` | MariaDB 错误日志 | docker：compose db 已带 `--log-error=/var/log/mysql/error.log` + 挂载（先 `chmod 0777 log/database`，UID 999）；外部库：本机配 `log_error` 后重启 |

```bash
# docker 首次：给 MariaDB 容器建可写的日志目录
mkdir -p log/backend log/frontend log/database && chmod 0777 log/database
docker compose up -d --build
```

**不开慢查询日志**——SQLAlchemy/PyMySQL 拼出的 SQL 会带姓名/学号字面量。
日志查完即删，不外发、不提交。详见 `log/README.md`。

---

## 8. 排错与运维速查

| 症状 | 大概率原因 | 处理 |
|------|------|------|
| backend 容器一直 `starting` | 数据库连不上 | `docker compose logs backend`；多为 `CLASSFEE_DB_*` 不匹配 |
| frontend 起不来、`unknown directive " server"` | nginx.docker.conf 带 BOM | 见 §6 表格去 BOM 后重建 |
| 小票上传 413 | nginx `client_max_body_size` 默认 1m | 改成 6m 并 reload nginx |
| 登录 401 | 账号错/已停用 | 看 `menu_account` 是否停用；班主任在 `.env` 声明 |
| 改 `CLASSFEE_JWT_SECRET` 后全员掉线 | 密钥换了签发内容 | 正常行为——通知成员重新登录 |
| 小票「文件不存在」 | 上传目录权限/路径与部署方式不一致 | 直跑看 `CLASSFEE_UPLOAD_DIR`；docker 看卷 `classfee_uploads` |
| 日志里一堆 401 | 正常（监控脚本健康检查） | 非故障 |
| 备份 | `mysqldump` + uploads 目录，务必两手抓 | 见 §6 末两行 |

**升级**：Windows 侧构建后替换源码与 dist，`docker compose up -d --build`（直跑则 `systemctl restart classfee && systemctl reload nginx`）。**上传的文件里 `.env` 绝不参与提交**（已 gitignore）。

---

## 9. 常用命令速查

```bash
# 直跑
sudo systemctl {start|stop|restart|status} classfee
sudo systemctl {start|stop|restart} nginx
journalctl -u classfee -f
sudo tail -f /var/log/classfee/backend/backend.log

# docker
docker compose ps
docker compose logs -f backend
docker compose up -d --build

# 备份
mysqldump -u classfee -p classfee > backup_$(date +%F).sql
```
