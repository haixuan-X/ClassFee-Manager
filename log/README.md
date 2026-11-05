# log/ 运行日志目录

系统运行时的日志按**前台端 / 后端 / 数据库**三类分离存放，
统一放在仓库根目录的 `log/` 下。**只有本文件和各目录的 `.gitkeep` 入库**，
其它内容一律被 `.gitignore` 忽略——日志里会写操作痕迹（姓名/学号/SQL 片段），**提交仓库前请自觉**。

## 目录结构

| 目录 | 内容 | 写入方式 |
|------|------|----------|
| `backend/`  | 后端应用日志 + uvicorn 访问/错误日志 | 后端启动时自动写 `backend.log`，按 5MB 轮转，保留 5 份 |
| `frontend/` | Nginx 访问日志 / 错误日志；`npm run dev:log` 的 Vite 输出 | 见下「前端」 |
| `database/` | MariaDB 错误日志（容器版） | 见下「数据库」 |

## 后端（本机直接跑 / 服务器直跑 / docker 均生效）

`server-py/app/main.py` 在启动时给根 logger 和 `uvicorn` / `uvicorn.error` / `uvicorn.access`
挂了一个 `RotatingFileHandler`：

- 默认路径 `log/backend/backend.log`（相对仓库根目录的绝对路径解析，**与当前工作目录无关**）
- **目录不存在会自动创建**（`mkdir -p`），不用手动建；docker 部署时 compose
  已把 `./log/backend` 挂进容器（`/app/log/backend`），属主由 `log-init` 服务自动改好
- 可用环境变量 `CLASSFEE_LOG_DIR` 覆盖目录（如服务器上想集中到 `/var/log/classfee/backend`）
- 控制台输出保留：终端里看得到的同时，文件里也有一份
- 轮转：单文件 5MB，`backend.log` + `backend.log.1` … `backend.log.5`
- 写文件失败（如只读文件系统）只告警、不阻断启动

排查后端问题先查这里：`tail -F log/backend/backend.log`

## 前端

**生产（docker compose）**：`web/nginx.docker.conf` 把 access/error 日志指到容器内
`/var/log/classfee/`，compose 把本仓库的 `./log/frontend` 挂载进去，
于是 `log/frontend/access.log`、`log/frontend/error.log` 就是线上日志。
无需 `logrotate`（查完问题手工清空即可，文件不会回写仓库外）。

**生产（systemd + 系统 nginx 直跑）**：在你的 nginx 站点里加

```nginx
access_log /opt/classfee/log/frontend/access.log;
error_log  /opt/classfee/log/frontend/error.log warn;
```

指到本仓库的 `log/frontend/` 即可，布局保持一致。

**开发环境**：`npm run dev` 的输出默认打到终端。要落盘用

```powershell
npm run dev:log    # 追加写到 log/frontend/vite-dev.log（不截断）
```

（代理不通、`/api` 连不上 `:8080`、路由报错这类信息都在这份里。）

## 数据库

**MariaDB（docker compose）**：`db` 服务带 `--log-error=/var/log/mysql/error.log`，
compose 把 `./log/database` 挂载到容器 `/var/log/mysql`。

**目录不用手动建**：compose 里有个一次性的 `log-init` 服务，每次
`docker compose up` 时自动创建 `log/database / log/backend / log/frontend`
并把属主改成对应容器用户（MariaDB=UID 999、后端=UID 10001），跑完即退出——
Linux 服务器上也不再需要手动 `mkdir` / `chmod`。

**不启用慢查询日志**：SQLAlchemy/PyMySQL 是客户端拼 SQL，慢日志会记下
带**姓名/学号字面量**的整条 SQL，属于隐私事故。如确需排查慢查询，
临时加一行（用完即撤）：

```yaml
      - --slow_query_log=1 --slow_query_log_file=/var/log/mysql/slow.log --long_query_time=2
```

且 `slow.log` 不许外发、不许提交。

**错误日志里没有业务数据**（启动/关闭/崩溃信息），可以放心留。

**宿主机直装的 MariaDB**（Ubuntu 等）：在 `/etc/mysql/mariadb.conf.d/` 加

```ini
[mysqld]
log_error = /opt/classfee/log/database/error.log
```

重启后生效。

## 隐私底线

- `log/` 除本文件与 `.gitkeep` 外**一律不会入库**（`.gitignore` 强制），
  也不要手动 `git add log/`。
- `access.log` / `backend.log` 里可能有带关键词的 URL（如 `?keyword=张三`）——
  查完问题把旧文件删掉即可，别发群里、别传工单系统。
- 备份整机时记得日志目录一起备或一起删，别让旧日志跟着全量备份流出去。
