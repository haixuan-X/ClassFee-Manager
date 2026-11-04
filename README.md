<div align="center">

# 学生信息管理系统

**一个智能汽车学院级的班费 + 学籍名册 + 任务协同平台：公开、透明、可追溯。**

记账有据（每笔可挂小票） · 缴费有序（批次逐人标记） · 错账可追（作废留痕而非抹除）

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/Python-3.13-blue.svg)](server-py/)
[![Vue 3](https://img.shields.io/badge/Vue-3.5-42b883.svg)](web/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688.svg)](server-py/)
[![回归 1263](https://img.shields.io/badge/regression-1263%20passed-success.svg)](server-py/tests/api_regression.py)

`Vue 3 + Element Plus` ｜ `FastAPI + SQLAlchemy 2.0` ｜ `MySQL 8 / MariaDB`

**版本：v1.5.0**

</div>

---

## 界面一览

> **截图已移除（脱敏）**：本仓库曾放过界面截图，其中带有真实姓名与学号。
> 为避免个人信息外泄，此处不再内嵌图片。
> 想看效果请在本地跑起来自己点：前后端启动后用 `.env` 声明的账号登录即可。

---

## 这是什么

一个面向**单个学院**（智能汽车学院）的系统，同时管三件事：

- **班费账本**：按班记收入/支出，批次逐人收班费，生成流水，对账可追溯；
- **学生信息名册**：班主任逐人维护学生字段（六字班级名册 + 自填报表），
  学院侧可申请看 / 授权看非管辖班学生数据；
- **学院任务协同**：院长发全学院任务（是/否、单选），各班班主任逐人接龙回收；
  班主任也可给自己班发班级任务（是/否、单选、多选、日期）。

**没有注册页，只有登录页。** 账号由部署方声明或由运营在页面创建，代码里不写死任何默认口令。

适合的场景：一个学院按班推进班费收缴、数据填报与信息核对。
不适合的场景：多学院多租户 SaaS、需要审批流的财务系统。
功能模块与谁能用见 [`docs/账号权限.md`](docs/账号权限.md)。

---

## 快速开始

需要 **Python 3.13+**、**Node 22+**、一个 MySQL 8 / MariaDB 库。

```bash
# 1. 建库（账号/库名按需改）
mysql -uroot -p -e "CREATE DATABASE classfee DEFAULT CHARSET utf8mb4;"

# 2. 后端 :8080 —— 建表与种子数据由启动时幂等执行，无需手动导 SQL
cd server-py
python -m venv .venv
.venv/bin/pip install -r requirements.txt          # Windows：.venv\Scripts\pip
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080

# 3. 前端 :5173（/api 已代理到 :8080）
cd web && npm install && npm run dev
```

打开 <http://localhost:5173>，用**部署时声明的账号**登录（见「[账号与权限](docs/账号权限.md)」）。

> Windows 下也可以直接双击 `start-all.bat`（同时拉起前后端）。

> ⚠️ **`.env` 不会自动进环境变量**：`run.py` 只读 `CLASSFEE_COLLEGE_NAME`，
> 数据库账号、JWT 密钥、种子班主任都必须注入进程环境。从新开的终端起服务时先：
> ```powershell
> Get-Content '.env' -Encoding UTF8 | ForEach-Object {
>   if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
>     Set-Item -Path "Env:$($matches[1])" -Value $matches[2].Trim()
>   }
> }
> ```
> 不注入的后果：库连不上或空库不建 `test` 账号，回归第一步就报错退出。

**首次启动日志里会看到这几类提示，都不是故障**：

| 日志 | 含义 |
|------|------|
| `未配置 CLASSFEE_TEACHER_USERNAME / PASSWORD` | 没声明账号，见「账号与权限」 |
| `已升级 sys_user.role 枚举：新增 'MONITOR'` | 一次性枚举升级，第二次不再出现 |
| `已补审计列：…` / `已把 N 条缴费行补进进行中的批次` | 一次性迁移/回填，第二次不再出现 |

---

## 账号与权限

账号体系与权限模型见 **[`docs/账号权限.md`](docs/账号权限.md)**。最短口径：

- **没有注册页，只有登录页**：账号由部署方声明 `CLASSFEE_TEACHER_*` 创建（仅首次，不覆盖库里改过的东西），或在「成员管理 / 学院 → 院长账号」里创建，代码里不写死任何默认口令。
- **权限按 `ROLE_LEVEL` 六档推导**：成员 0 < 生活委员 1 < 班长 2 < 班主任 3 < 院长 4；后端 `_STAFF_ROUTES` + 端点级 `require_role` 双闸，**判定一律看等级不写角色名**。
- **归属权**：改 / 删 / 作废 / 关闭只能操作**自己创建**的数据；院长分兼班主任院长 / 纯院长（`CLASSFEE_DEAN_ONLY=1`）。

---

## 部署到服务器

部署文档：[`docs/部署-Linux.md`](docs/部署-Linux.md)，覆盖两条路线：

| 路线 | 章节 | 服务器要装什么 | 适合 |
|------|------|--------------|------|
| **A. 手动部署** | §1–§5 | Python 3.13、Node、MariaDB、nginx | 要自定义、反代已有站点 |
| **B. Docker Compose** | §6 | Docker + compose | **最省事**，一键起 |

```bash
# 例：B 路线一键起
scp -r D:\bj user@your-server:/opt/classfee-src
cd /opt/classfee-src && cp .env.example .env   # 必填 JWT 密钥 + 班主任账号 + DB 密码
docker compose up -d --build
```

服务器上已有 MySQL/MariaDB 时用 `docker-compose.use-existing-db.yml`（不另起库容器），详见部署文档 §6。
运行时日志（后端 / 前端 nginx / MariaDB 三类分离）见部署文档 §7；**除 `log/README.md` 与 `.gitkeep` 外一律不入库**。

## 设计要点

钱怎么记、小票怎么挂、任务回收率怎么算、权限怎么判定、15 张表怎么织网——见 **[`docs/设计要点.md`](docs/设计要点.md)**。一句话：

- 收支一种流水（`fee_record`）、作废红冲留痕；余额实时对账，`Decimal(10,2)` 全链路不碰 float；
- 成员缴费只有「批次标记缴费」一条写入路径；
- 任务按题型分流展示，回收率按班主任名册统计；
- 学院口径接口不带「当前班」，权限一律看 `ROLE_LEVEL` 等级。

## 参与开发

```bash
# 前端类型检查 + 构建
cd web && npm run type-check && npm run build

# 契约回归（**需后端在运行**，零依赖，当前 1263 项全绿）
.venv/bin/python server-py/tests/api_regression.py
```

**回归是本项目唯一常驻的自动化闸门**——`test_*` 命名可被 pytest 直接收集，也可当脚本跑。
改后端必须：**真重启后端 → 跑回归** → 浏览器点一遍。

### ⚠️ 编码规则：谁读这个文件，决定它有没有 BOM

| 读者 | 编码 | 范围 |
|------|------|------|
| **程序**（nginx / MySQL / Docker / 任何按字节解析的解析器） | **UTF-8 无 BOM** | `*.conf`、`Dockerfile*`、compose yml、`*.sql`、`*.json`、`*.toml`、`.env*` |
| **人**（编辑器 / GBK 工具） | **UTF-8 带 BOM** | `README.md` |
| 人机都不敏感 | 无所谓 | 全部 `.py` |

**中文注释在「无 BOM」那一侧完全安全，坏的只有 BOM 本身。**
踩过的坑：带 BOM 的 `nginx.docker.conf` 让 frontend 容器起不来；带 BOM 的 `schema.sql` 静默少一张表。
回归用例 `test_a00_encoding_guards` 会扫描全仓库并逐个指名带 BOM 的文件。

---

## 目录结构

```
classfee-manager/
├─ server-py/              后端（FastAPI，:8080）
│  ├─ app/
│  │  ├─ services/         业务规则与事务（record / batch / user / file / notice / college / student / task / ...）
│  │  ├─ routers/          HTTP 层，只做参数校验与响应包装
│  │  └─ main / config / db / models / security / schemas / responses / errors / seed
│  ├─ db/schema.sql        15 张表 DDL（启动时幂等执行）
│  └─ tests/               契约回归（api_regression.py，零依赖，1263 项）
├─ web/                    前端（Vue 3 + Vite，:5173）
│  └─ src/                 api / views（dashboard · college · records · batches · tasks ...）/ components / stores
├─ log/                    运行日志（backend / frontend / database，不入库）
├─ docs/                   入库仅三份：部署指南 · 账号与权限 · 设计要点
├─ docker-compose.yml                 一键部署（自带数据库容器）
├─ docker-compose.use-existing-db.yml 复用服务器上已有的 MySQL/MariaDB
├─ start-*.bat             Windows 一键启动
└─ .env.example            部署变量模板（复制为 .env 填写）
```

**技术规模**：后端 13 个路由模块 / 110 个 REST 端点；前端 17 个页面组件；15 张表。

---

## 文档索引

| 文档 | 内容 | 适合谁 |
|------|------|--------|
| [`log/README.md`](log/README.md) | 运行日志：三类目录、启停、隐私底线 | 查线上问题 |
| [`docs/部署-Linux.md`](docs/部署-Linux.md) | **部署指南**：手动（systemd + nginx）/ Docker Compose（含外部库）、验证清单、排障、日志配置 | 部署运维 |
| [`docs/账号权限.md`](docs/账号权限.md) | **功能与权限**：功能模块总表（班级层/学院层 + 谁能用）、角色六档与 `ROLE_LEVEL`、账号来源与特性、访客可见范围、跨班授权 | 查有什么功能、排权限/建号 |
| [`docs/设计要点.md`](docs/设计要点.md) | **设计口径**：资金单一流水与作废红冲、余额/金额/小票、任务分流与回收率、`skipClassId`、15 张表 DDL | 动数据结构/钱/任务前 |
| [`design-system/classfee-manager/MASTER.md`](design-system/classfee-manager/MASTER.md) | **UI 规范**：色彩 token、间距、组件规格、响应式断点、**交付前检查清单** | 改界面样式 |
| [`server-py/tests/api_regression.py`](server-py/tests/api_regression.py) | **1263 项契约回归**断言，改后端必跑 | 改接口 |
| [`.env.example`](.env.example) | 全部部署变量（含中文注释） | 部署运维 |

---

## 运维要点

| 项 | 说明 |
|----|------|
| **契约回归** | 改后端后跑 `server-py/tests/api_regression.py`（需后端在运行），1263 项 |
| **JWT 密钥** | `CLASSFEE_JWT_SECRET` 生产必须注入随机串；**改它会让所有已登录会话立即失效** |
| **数据库备份** | `mysqldump -u classfee -p classfee > backup_$(date +%F).sql`，建议 cron 每日 |
| **小票文件** | 落磁盘（`server-py/uploads/`，`CLASSFEE_UPLOAD_DIR` 可改；docker 落卷 `classfee_uploads`），**不在数据库里** |
| **时区** | 应用内固定 `Asia/Shanghai`（systemd/compose 均已设 `TZ`） |
| **升级** | 替换源码后 `docker compose -f docker-compose.use-existing-db.yml up -d --build`；**只重启不生效** |

### 已知限制

- **硬删无痕**：`DELETE` 端点是物理删除，**留不下痕迹**；留痕路径是「作废 / 下架」。
- **学籍变化无历史表**：仪表盘 `changeTotal` 是**当前不在籍人数**，给不了「本学期异动人次」。
- **导出无行数上限**：`/records/export` 一次性在内存生成 xlsx（班级量级足够）。
- **Docker 镜像未在开发机实测**：`Dockerfile` 与 compose 只做过静态校对与连通性验证；
  首次部署请对照 [`docs/部署-Linux.md`](docs/部署-Linux.md) §5 逐条自检。

---

## License

[MIT](LICENSE) © 2026 Student Info Manager contributors
