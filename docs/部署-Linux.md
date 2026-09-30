# 班费收支系统 · Linux 部署指南

> 目标形态（单机即可跑通）：
>
> ```
> 浏览器 ──▶ nginx (:80)
>              ├─ 静态文件  /var/www/classfee   （web/dist 构建产物）
>              └─ /api 反代 ──▶ FastAPI 后端 (127.0.0.1:8080) ──▶ MariaDB (localhost:3306)
> ```

前端 axios 使用相对路径 `baseURL: '/api'`，经 nginx 同源转发，**无需处理跨域**；路由为 history 模式，nginx 必须配置 SPA 回退。

**两条路线，选一条**：

| 路线 | 章节 | 服务器要装什么 | 适合 |
|------|------|--------------|------|
| **A. 手动部署** | §1–§8 | Python 3.13、Node、MariaDB、nginx | 要自定义、反代已有站点 |
| **B. Docker Compose** | §9 | Docker + compose | **最省事**，不用装上面任何东西 |

> 💡 不想折腾就跳到 **§9 Docker 一键部署**。

---

## 1. 构建产物（在 Windows 本机构建，推荐）

服务器上只需运行时环境，构建放在本机做：

```powershell
# 后端无需构建（Python 源码直接运行），仅需安装依赖：
cd D:\bj\server-py
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 前端静态文件
cd D:\bj\web
npm run build
```

得到两个产物：

| 产物 | 路径 |
|------|------|
| 后端 | `server-py/` 源码目录（上传后服务器内装依赖运行） |
| 前端 | `web/dist/`（整个目录） |

> 也可以在服务器上从零准备：装 `python3.12+`（含 venv）、`nodejs 22` 后执行同样命令。

> ⚠️ **版本一致性**：本项目开发与 Docker 镜像统一用 **Python 3.13**（`Dockerfile` 为 `python:3.13-slim`）。Ubuntu 22.04 自带 3.10，Debian 12 自带 3.11，**均低于开发版本**——若要复现与本地一致的行为，请自行安装 3.13（deadsnakes PPA / pyenv / 源码编译），否则按 §9 走 Docker 更省事。

## 2. 服务器初始化（Ubuntu/Debian 示例）

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx mariadb-server

python3 --version   # 需 3.10+（推荐 3.12/3.13）
```

- **CentOS/Rocky**：`sudo dnf install -y python3 python3-pip nginx mariadb-server`，防火墙用 `firewall-cmd --permanent --add-service=http && firewall-cmd --reload`。
- 数据库是 MariaDB 或 MySQL 8 均可（默认配置按 MariaDB 的 JDBC 驱动连，MySQL 8 见 §7 改法）。

### 2.1 创建数据库与账号

```bash
sudo mysql <<'SQL'
CREATE DATABASE classfee CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'classfee'@'localhost' IDENTIFIED BY 'classfee123';
GRANT ALL PRIVILEGES ON classfee.* TO 'classfee'@'localhost';
FLUSH PRIVILEGES;
SQL
```

表结构（`schema.sql`，`IF NOT EXISTS` 幂等）与演示数据（管理员、默认类别、13 名成员）由**后端启动时自动创建**（启动 lifespan 幂等执行 `server-py/db/schema.sql` + 种子补齐），不用手动导库；种子逻辑只在空库时补数据，重复启动安全。

## 3. 上传产物

在 Windows PowerShell：

```powershell
scp -r D:\bj\server-py user@your-server:/tmp/server-py
scp -r D:\bj\web\dist user@your-server:/tmp/dist
```

服务器上归位：

```bash
sudo mkdir -p /opt/classfee /var/www/classfee
sudo mv /tmp/server-py /opt/classfee/
sudo mv /tmp/dist/* /var/www/classfee/
sudo chown -R www-data:www-data /var/www/classfee

# 后端依赖装进虚拟环境
cd /opt/classfee/server-py
sudo -u www-data python3 -m venv .venv
sudo -u www-data .venv/bin/pip install -r requirements.txt
```

## 4. 后端 systemd 服务

`/etc/systemd/system/classfee.service`：

```ini
[Unit]
Description=ClassFee Manager (FastAPI)
After=network.target mysql.service mariadb.service
Wants=mysql.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/classfee/server-py
Environment=TZ=Asia/Shanghai
Environment=CLASSFEE_DB_URL=mysql+pymysql://localhost:3306/classfee?charset=utf8mb4
Environment=CLASSFEE_DB_USERNAME=classfee
Environment=CLASSFEE_DB_PASSWORD=classfee123
# 旧变量名 SPRING_DATASOURCE_* 仍兼容（沿用 Java 版命名），但不再推荐
# 生产必须换掉开发密钥（见 §7）：Python 后端 config.py 读取，用于签发/校验登录令牌
# 生成：openssl rand -hex 32
Environment=CLASSFEE_JWT_SECRET=换成随机64位十六进制串
# 班主任（运营）账号：在 .env 或系统环境变量里「声明即生效」，仅在库中不存在时创建
# 用户名与密码必须同时填写（代码里没有默认口令）；已存在则跳过，不覆盖库里改过的密码/角色
# Environment=CLASSFEE_TEACHER_USERNAME=test
# Environment=CLASSFEE_TEACHER_PASSWORD=换成强口令
# Environment=CLASSFEE_TEACHER_NAME=测试班主任
# Environment=CLASSFEE_TEACHER_ROLE=TEACHER   # ADMIN | TEACHER，默认 TEACHER
# 其余学生/管理员账号：班主任登录后在「成员管理」中创建
# 小票图片目录（默认 /opt/classfee/server-py/uploads；需 www-data 可写，
# 备份时连同该目录一起备）
# Environment=CLASSFEE_UPLOAD_DIR=/opt/classfee/server-py/uploads
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

> `uvicorn` 路径若不同用 `ls /opt/classfee/server-py/.venv/bin/` 确认后替换 `ExecStart`。

## 5. nginx 站点配置

`/etc/nginx/sites-available/classfee`（Debian 系；CentOS 放 `/etc/nginx/conf.d/classfee.conf`）：

```nginx
server {
    listen 80;
    server_name your-domain.com;     # 或 _ 表示默认站点

    root /var/www/classfee;
    index index.html;

    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;

    # 前端路由 history 回退：刷新深层路径不 404
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API 反代到后端
    location /api/ {
        # 小票图片上传上限 5MB（后端同值校验），留 1MB 余量给 multipart 边界
        # 缺省会用 nginx 默认 1m，登记小票时直接 413
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
sudo ln -s /etc/nginx/sites-available/classfee /etc/nginx/sites-enabled/   # Debian/Ubuntu
sudo nginx -t && sudo systemctl reload nginx
```

**防火墙**：`sudo ufw allow 'Nginx Full'`（或 `sudo ufw allow 80`）。

## 6. 验证

```bash
# 后端直连（把下面的账号/口令换成你在 .env 里声明的班主任账号）
curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"test","password":"你的口令"}' | head -c 200

# 经 nginx（应返回 index.html，接口返回 JSON）
curl -sI http://127.0.0.1/ | head -1
curl -s -X POST http://127.0.0.1/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"test","password":"你的口令"}' | head -c 200
```

浏览器访问 `http://your-domain.com`，用 `.env` 里声明的账号登录（**首次登录后立刻在「个人中心」改密码**；库里已有该账号时启动不会覆盖你改过的密码），其余成员账号在「成员管理」中创建。

**部署后自检清单**（逐条打勾，全过才算部署完成）：

```bash
# 1) 后端活着且返回统一响应结构（未带 token 应 401）
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/api/auth/me      # 期望 401

# 2) 登录能拿到 token
curl -s -X POST http://127.0.0.1:8080/api/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"test","password":"你的口令"}' | head -c 120

# 3) nginx 转发正常（首页 HTML + 接口 JSON）
curl -sI http://127.0.0.1/ | head -1

# 4) SPA 深链接回退生效（直接访问子路由应返回 index.html 而非 404）
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1/member-manage       # 期望 200

# 5) 小票上传体积限制已放开（默认 1m 会让 5MB 小票 413）
grep client_max_body_size /etc/nginx/sites-available/classfee
```

浏览器侧再确认：登录后侧栏能看到全部运营入口、能建号、账本页点「导出 Excel」能下到 xlsx。

## 7. 生产环境注意事项

| 项 | 说明 |
|----|------|
| **JWT 密钥** | `config.py` 里是开发占位串，生产用 `CLASSFEE_JWT_SECRET` 环境变量注入随机串（`openssl rand -hex 32`）。这个变量是**当前 Python 后端**在用（config.py 读取 → security.py 签发/校验登录令牌），不是 Java 版遗留；改它会让所有已登录会话立即失效，需重新登录。systemd 单元已预留位置，改完 `sudo systemctl restart classfee` 生效 |
| **班主任账号** | **账号不写死在代码里，也没有注册页**。在 compose 的 `.env`（或 systemd 环境变量）声明 `CLASSFEE_TEACHER_USERNAME` + `CLASSFEE_TEACHER_PASSWORD`（可选 `CLASSFEE_TEACHER_NAME`、`CLASSFEE_TEACHER_ROLE=ADMIN\|TEACHER`）即生效：启动时库中无此用户名则创建，**已存在则跳过且不覆盖**（自助改密不会被改回）。两项都为空则不创建任何账号，启动日志会提示；其余成员账号由运营角色登录后在「成员管理」中创建并授权（角色四选一：普通成员/生活委员/班长/班主任） |
| **从旧版升级** | 旧版的 `CLASSFEE_INIT_ENABLED/USERNAME/PASSWORD/ROLE` 已废弃（不再读取）。若此前已用旧引导建好账号，把**同名用户名**写进 `CLASSFEE_TEACHER_USERNAME` 即可（存在即跳过，密码/角色不受影响）；若从未建过账号，升级后必须补齐 `CLASSFEE_TEACHER_USERNAME`/`PASSWORD` 并重启，否则无人可登录。`sys_user.role` 枚举新增 `'MONITOR'`（班长）由启动时的 `migrate_role_enum()` **幂等自动升级**（查 `INFORMATION_SCHEMA`，缺了才 `ALTER`），无需手工改表 |
| **MySQL 8 替代 MariaDB** | 连接串**不用改**——用的是 SQLAlchemy 原生写法 `mysql+pymysql://`，PyMySQL 同时支持 MariaDB 与 MySQL 8。想换库名/端口就改 URL 里的主机与库名部分。旧 Java 版留下的 `jdbc:mariadb://` / `jdbc:mysql://` 写法**仍兼容**（`config.py` 会自动归一化，但那些 `useUnicode`/`serverTimezone` 是 Java 驱动专有参数，会被丢弃）；旧变量名 `SPRING_DATASOURCE_URL` 也仍兼容 |
| **HTTPS** | `sudo certbot --nginx -d your-domain.com` 一键加证书并改写 80→443 |
| **时区** | 应用内已固定 `Asia/Shanghai`（systemd/compose 均已设 `TZ`），服务器系统时区不必改 |
| **数据库备份** | `mysqldump -u classfee -p classfee > backup_$(date +%F).sql`，建议 cron 每日执行 |
| **小票图片** | 支出小票落磁盘（默认 `server-py/uploads/`，`CLASSFEE_UPLOAD_DIR` 可改），**不在数据库里**：备份除 mysqldump 外还要备该目录（`tar czf uploads_$(date +%F).tgz -C server-py uploads`）；nginx 需放开 `client_max_body_size 6m`（默认 1m 会让 5MB 小票 413） |
| **更新发布** | 替换 `server-py/` 源码与 `dist` 后 `sudo systemctl restart classfee && sudo systemctl reload nginx`；前端静态文件建议同时改 `index.html` 的引用 hash（Vite 已自带指纹，用户强刷即更新） |

## 8. 快速命令速查

```bash
# 启停
sudo systemctl {start|stop|restart|status} classfee
sudo systemctl {start|stop|restart} nginx

# 日志
journalctl -u classfee -f
sudo tail -f /var/log/nginx/access.log /var/log/nginx/error.log

# 发布新版本（Windows 侧构建后）
# scp -r 新的 server-py/* 到 /opt/classfee/server-py/、scp dist/* 到 /var/www/classfee/，然后：
sudo systemctl restart classfee && sudo systemctl reload nginx
```

---

## 9. Docker 一键部署（最省事）

> ⚠️ **本机未整体实测**：开发机没有 Docker，无法执行 `docker compose up --build`。已做的核对：
> - **实测通过**：compose YAML 可解析（3 服务 / 2 卷）；数据库连接串归一化对**五种写法**（原生 `mysql+pymysql://`、`mariadb+pymysql://`、老 `jdbc:mariadb://`、老 `jdbc:mysql://`、带空格的值）都正确，且**用项目真实 engine 连本机 MariaDB 成功**（12.3.2 / utf8mb4 / 中文存取正常）；后端健康检查脚本**双向验证**（后端在跑→退出码 0，端口不通→1）；`package-lock.json` 存在（`npm ci` 不会失败）；`.env` 不会被 `COPY` 进镜像；`.dockerignore` 已排除 `.env`/`uploads`/`node_modules`；全量接口回归 156 项通过。
> - **未能验证**：镜像能否构建成功、首次启动的建表与账号创建、nginx 反代联通——这三项**只能在有 Docker 的机器上验证**。首次部署请对照 §9.3 逐条自检。

无需在服务器安装 Python/Node/nginx，只要 **Docker + compose 插件**（Docker 20.10+ / compose v2）。后端直接以 `python:3.13-slim` 跑源码（pip 装依赖），前端为多阶段构建（容器内跑 npm），由 nginx 镜像托管并内置 `/api` 反代。相关文件：

| 文件 | 作用 |
|------|------|
| `docker-compose.yml` | 编排 db（MariaDB 11.4）+ backend + frontend，含健康检查与数据卷 |
| `server-py/Dockerfile` | `python:3.13-slim` → pip 装依赖（**装完立即 import 冒烟**）→ **非 root 运行** → `uvicorn app.main:app` |
| `web/Dockerfile` | 多阶段：`node:22` 构建（先 `type-check` 再 `build`）→ `nginx:1.27-alpine` 托管 + 健康检查 |
| `web/nginx.docker.conf` | SPA 回退 + `/api` → `backend:8080` 反代，`client_max_body_size 6m`（小票 5MB） |
| `.env.example` | 账号 / JWT 密钥 / root 密码 / 对外端口，复制为 `.env` 修改（内含部署后自检清单） |

**架构与启动顺序**：`db`（MariaDB，带官方 healthcheck）→ 健康后启 `backend`（启动时幂等建表 + 按 `.env` 声明创建账号；另有自检 healthcheck）→ 健康后启 `frontend`（nginx）。

### 9.1 准备

上传**整个项目源码目录**（与手动方式不同 —— Docker 构建发生在目标机）：

```powershell
scp -r D:\bj user@your-server:/opt/classfee-src
```

目标机安装 Docker（Ubuntu/Debian）：

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER && newgrp docker    # 免 sudo 使用 docker
```

> 上传前建议**先清掉不该进仓库的东西**（`scp -r` 会把 `.venv`/`node_modules`/`dist` 一起拷过去，几十上百 MB 白费带宽）。在本地 `D:\bj` 执行：
>
> ```powershell
> # 只传构建必需的文件（下面这份清单就是 docker compose build 用到的全部内容）
> scp -r server-py web docker-compose.yml .env.example .gitignore `
>       README.md user@your-server:/opt/classfee-src
> ```
>
> 若整目录传，传完在目标机删掉无用目录：`rm -rf /opt/classfee-src/server-py/.venv /opt/classfee-src/web/node_modules /opt/classfee-src/web/dist`
>
> 本机装了 **Docker Desktop** 也可以在 `D:\bj` 下直接执行，先 `docker login` 推镜像或在目标机 `docker save/load` 传输，适合服务器构建资源不足的场景。

### 9.2 配置

```bash
cd /opt/classfee-src
cp .env.example .env        # 模板在仓库根目录，逐项都有中文说明
# 编辑 .env（docker compose 自动读取同目录该文件）：
#   CLASSFEE_JWT_SECRET=<openssl rand -hex 32 的输出>   # Python 后端签发/校验登录令牌用
#   DB_ROOT_PASSWORD=强密码
#   CLASSFEE_TEACHER_USERNAME=test       # 班主任账号：声明即生效（两项必填，无默认口令）
#   CLASSFEE_TEACHER_PASSWORD=换成强口令
#   CLASSFEE_TEACHER_NAME=测试班主任
#   CLASSFEE_TEACHER_ROLE=TEACHER
#   HTTP_PORT / CLASSFEE_UPLOAD_DIR 按需调整
```

> `.env` 含真实口令，已加入仓库根目录的 `.gitignore`，**不要提交或外传**；对外分享时只给 `.env.example`。

> **服务器上已经有在跑的 MySQL/MariaDB？不要用本节的 `DB_ROOT_PASSWORD` 路线。**
> 本节默认 compose 自己起一个 MariaDB 容器。你要复用现有数据库的话，配置文件换成
> `docker-compose.use-existing-db.yml`、`.env` 里填 `DB_HOST/DB_PORT/DB_NAME/DB_USERNAME/DB_PASSWORD`
> 而不是 `DB_ROOT_PASSWORD` —— 完整步骤见 **[§9.6](#96-复用服务器上已有的-mysqlmariadb不新建数据库容器)**。

### 9.3 启动与验证

```bash
docker compose up -d --build
docker compose ps        # 期望：db → healthy，backend → healthy，frontend → running/healthy
```

| 服务 | 对外端口 | 说明 |
|------|----------|------|
| db | 无（仅容器网络） | 数据卷 `db-data` 持久化；首启自动建表 + 班级/类别种子，班主任账号按 `.env` 声明创建 |
| backend | 无（调试可放开 compose 内注释的 `8080:8080`） | 连 `db:3306`，JWT 密钥走环境变量；小票图片写 `classfee_uploads` 卷（`/app/uploads`）；**非 root 运行** |
| frontend | `${HTTP_PORT:-80}:80` | SPA 回退 + `/api` 反代到 `backend:8080` |

**frontend 起不来、日志报 `unknown directive " server" in /etc/nginx/conf.d/default.conf:1`？**

这是 `web/nginx.docker.conf` 带了 **UTF-8 BOM**（`EF BB BF`）。nginx 按字节读配置，把 BOM 和
`server` 解析成同一个 token，于是 `server` 指令「不存在」——报错里引号内那个空格就是 BOM 被
终端渲染出来的样子。中文注释完全没问题，**只有 BOM 有害**。

```bash
# 检查（无输出 = 正常）
head -c 3 web/nginx.docker.conf | xxd | grep -i 'efbbbf' && echo ">>> 有 BOM"

# 去掉 BOM
sed -i '1s/^\xEF\xBB\xBF//' web/nginx.docker.conf
head -c 12 web/nginx.docker.conf    # 期望 73 65 72 76 65 72 … 即 "server {"

# 必须重新构建镜像（BOM 是 COPY 进去的，只重启不生效）
docker compose -f docker-compose.use-existing-db.yml up -d --build
```

同一条规则还适用于 `server-py/Dockerfile`、`server-py/db/schema.sql`、两个 compose 文件、
`.env.example` 等**所有被程序读取的配置文件**（`*.conf` / `*.sh` / `Dockerfile*` / `*.sql` /
`*.json` / `*.yml`）——它们**都必须无 BOM**。

反之，`docs/*.md` / `README.md` 这类**给人读**的文档**必须保留 BOM**，否则中文 Windows 的
GBK 工具打开是乱码。分界线是「**谁来读这个文件**」，不是文件类型。**中文注释在「无 BOM」
那一侧完全没问题**，坏的只有 BOM 本身。

**编辑方式**：保存为 UTF-8 无 BOM。**不要用 Windows 记事本**——它默认写 GBK，部分版本还会
对已有文件追加 BOM。VS Code 右下角能直接看到当前是 `UTF-8` 还是 `UTF-8 with BOM`，保存前扫一眼。

本地跑 `server-py/tests/api_regression.py` 的**第一个用例就是这条编码闸门**，会扫描全仓库并逐个
指名道姓地报出带 BOM 的文件。

**逐条自检**（对应 `.env.example` 末尾那份清单）：

```bash
# 1) 三个服务的状态
docker compose ps

# 2) 后端活着（退出码 0 = 健康；拿到 401 说明服务已就绪，未带 token 本来就该 401）
docker compose exec backend python -c \
  "import urllib.request,urllib.error as e;urllib.request.urlopen('http://127.0.0.1:8080/api/auth/me')"
echo "exit=$?"     # 期望 0

# 3) 首页返回 HTML
curl -sI http://127.0.0.1/ | head -1        # 期望 HTTP/1.1 200 OK

# 4) SPA 深链接不 404（验证 nginx history 回退）
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1/member-manage    # 期望 200

# 5) 登录接口通（账号口令换成 .env 里声明的班主任账号）
curl -s -X POST http://127.0.0.1/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"test","password":"你的口令"}' | head -c 120
# 期望 {"code":200,...} 后跟一段 token
```

浏览器打开 `http://<服务器IP>`，用 `.env` 里声明的账号登录后**立即在「个人信息」页改密码**（库里已有该账号时启动不会覆盖），学生账号在「成员管理」中创建。

**首次启动会慢一点**（要装依赖 + 跑前端构建，约 2–5 分钟，取决于服务器）。构建期若失败，`docker compose build` 的报错会直接指出是哪个阶段：

| 报错关键字 | 原因 | 处理 |
|------------|------|------|
| `deps ok` 没打出来就失败 | pip 装依赖失败（多为网络/镜像源） | 配置 pip 镜像源后重试 |
| `npm ci` 报错 | `package-lock.json` 与 `package.json` 不同步 | 本地 `npm install` 更新锁文件后再传 |
| `type-check` 阶段报类型错 | 前端代码有类型错误 | 本地 `npx vue-tsc --noEmit` 先修好 |
| backend 一直 `starting` | 数据库连不上 | `docker compose logs backend` 看报错，多为 `CLASSFEE_DB_*` 不匹配 |

### 9.4 日常操作

```bash
docker compose logs -f backend        # 后端日志（db / frontend 同理）
docker compose up -d --build          # 发版：替换源码后重新构建启动
docker compose down                   # 停止（数据卷保留，重起数据还在）
docker compose down -v                # 停止并删库（**连小票图片卷一起删**，慎用）
docker compose exec backend python --version   # 进容器排查

# 备份数据库
docker compose exec db sh -c 'exec mysqldump -uroot -p"$MARIADB_ROOT_PASSWORD" classfee' > backup_$(date +%F).sql

# 备份小票图片（小票在磁盘卷里，不在数据库中）
docker run --rm -v classfee_uploads:/data -v "$PWD":/backup alpine \
  tar czf /backup/uploads_$(date +%F).tgz -C /data .
```

### 9.5 两种方式怎么选

| | 手动（§2-§8） | Docker（本节） |
|---|---|---|
| 服务器依赖 | Python 3.12+ + nginx + MariaDB | 仅 Docker |
| 上传内容 | `server-py/` 源码 + dist | 全部源码（构建在目标机） |
| 升级 | 替换源码与 dist + restart | `docker compose up -d --build` |
| 数据库 | 用系统 MariaDB 服务 | 容器 + 数据卷（备份走 mysqldump 容器内执行） |
| 小票图片 | `server-py/uploads/` 目录（**要单独备份**） | `classfee_uploads` 卷（**要单独备份**） |
| 适用 | 小机器、已有数据库环境 | 想要干净隔离、快速起停、多环境迁移 |

> 上表只比了「手动 vs Docker」。**Docker 这一列内部还分两种**：服务器上已有在跑的
> MySQL/MariaDB 时，用 `docker-compose.use-existing-db.yml` 复用它（不另起库容器、
> 你的数据完全不受 `docker compose down` 影响），见 [§9.6](#96-复用服务器上已有的-mysqlmariadb不新建数据库容器)。

### 9.6 复用服务器上已有的 MySQL/MariaDB（不新建数据库容器）

服务器上已经有在跑的数据库时，用 **`docker-compose.use-existing-db.yml`**——它与主 compose 的命令完全一样，只是**没有 `db` 服务**，backend 直接连你的现有数据库。

**第一步：在数据库里建库和账号**（用你现有的管理账号登录，如 root）

```sql
CREATE DATABASE classfee DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_general_ci;
-- 关键：'%' 表示允许从 Docker 容器网段（172.17.x.x）连进来；只写 'localhost' 容器连不上
CREATE USER 'classfee'@'%' IDENTIFIED BY '你的强密码';
GRANT ALL PRIVILEGES ON classfee.* TO 'classfee'@'%';
FLUSH PRIVILEGES;
```

> 已经有 `classfee` 账号的话，只需确认它授权的主机是 `%` 而不是 `localhost`：
> `SELECT user, host FROM mysql.user;`

**第二步：确认数据库不是只监听本机**

```bash
# bind-address 若是 127.0.0.1，只接受本机连接，容器连不上
grep -E '^\s*(bind-address|skip-networking)' /etc/mysql/mariadb.conf.d/*.cnf /etc/my.cnf
# 需要 3306 对容器网段可达，且防火墙放行
sudo ufw allow from 172.16.0.0/12 to any port 3306 proto tcp   # 仅当启用了 ufw
```

**第三步：填 `.env`**

```bash
cd /opt/classfee
cp .env.example .env
# DB_* 这 5 行（DB_PASSWORD 必填）
DB_HOST=127.0.0.1        # 数据库与本应用同机 → 127.0.0.1；不同机 → 那台的内网 IP
DB_PORT=3306
DB_NAME=classfee
DB_USERNAME=classfee
DB_PASSWORD=你的强密码
# 另外这两个也必填
CLASSFEE_JWT_SECRET=<openssl rand -hex 32 的输出>
CLASSFEE_TEACHER_USERNAME=你的账号
CLASSFEE_TEACHER_PASSWORD=你的口令
```

**第四步：启动**（唯一区别是 `-f` 指定文件，其余命令一致）

```bash
docker compose -f docker-compose.use-existing-db.yml up -d --build
docker compose -f docker-compose.use-existing-db.yml ps      # backend → healthy
```

**与主 compose 的差异**

| | `docker-compose.yml` | `docker-compose.use-existing-db.yml` |
|---|---|---|
| 数据库 | compose 起 MariaDB 11.4 容器 | **用你服务器上已有的** |
| 启几个容器 | 3（db / backend / frontend） | **2**（backend / frontend） |
| 数据在哪 | `db-data` 卷 | 你的数据库（`down` 不影响） |
| `down -v` | 会删库 | 只删小票卷，**数据库不受影响** |
| 备份命令 | `docker compose exec db …` | 用服务器自己的 `mysqldump` |

> 建表与种子数据仍由后端启动时**幂等执行**（`schema.sql` + `seed.py`），首次启动会自动在你选定的库里建好 7 张表并按 `.env` 创建班主任账号；已有表不会被覆盖。

**排查**：`docker compose -f docker-compose.use-existing-db.yml logs backend`，最常见的报错：

| 报错 | 原因 | 处理 |
|------|------|------|
| `Access denied for user 'classfee'@'172.17.x.x'` | 账号只授权给 `localhost` | 补 `CREATE USER 'classfee'@'%' …` + `GRANT` |
| `Can't connect to MySQL server on '127.0.0.1'` | 容器里 `127.0.0.1` 指容器自己 | 数据库在不同机就填它的内网 IP |
| `(2003) Can't connect` / `Connection refused` | 数据库没监听外部地址 | 改 `bind-address = 0.0.0.0` 并重启数据库 |
