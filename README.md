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

---

## 功能

### 班级层（班主任 / 班长 / 生活委员 / 普通成员）

| 模块 | 说明 | 谁能用 |
|------|------|--------|
| 登录 / 会话 | 账号密码登录，JWT（HS256 / 2h），改密码 | 全部 |
| 仪表盘 | 余额、本月收支、缴费完成率、近 6 月趋势、支出分类占比、最新流水、学籍变化、置顶公告、置顶任务 | 全部 |
| 收入登记 | 班费 / 义卖 / 捐款 / 退款 | 运营 |
| 支出登记 | 报销 / 采购，**可挂小票图片** | 运营 |
| 账本明细 | 多条件筛选、分页、**按当前筛选导出 Excel**、作废红冲、删除、**查看小票** | 运营看全部；成员只读 |
| 我的缴费 | 我有没有班费要交 / 交没交 / 什么时候截止 | 成员（运营角色不参与缴费） |
| 成员缴费 | 缴费名单、按人补录缴费（**代缴可挂小票**）、缴清筛选 | 运营 |
| 收费批次 | 建批次 → 逐人标记缴费 → 自动生成流水 → 关闭 / 删除 | 运营 |
| 班级公告 | 发布 / 编辑 / 置顶 / 下架（可恢复）/ 彻底删除 | 运营写，全员读 |
| 成员管理 | 建号（四档角色）、编辑资料与学号、重置密码、停用启用、删除 | 运营 |
| 学生信息 | 班级名册：字段设计、批量导入（xlsx）、导出；删/改学生记录 | 运营写，成员按授权读 |
| 班级任务 | 发班级任务（是/否、单选、多选、日期）、答题统计、置顶到仪表盘 | 全员 |
| 班级信息 | 班级名称 / 年级 / 班主任（余额只读） | 运营写，全员读 |
| 个人信息 | 改密码、改姓名 / 学号 / 手机号 / 登录名、改「我带的班」 | 全部 |

### 学院层（院长）

| 模块 | 说明 |
|------|------|
| 学院任务 | 院长发全学院任务（是/否、单选），各班班主任逐人接龙回收；任务明细按题型分流展示（是/否/日期→返校四桶；单选/多选→按选项）；置顶到全员仪表盘 |
| 学院名册 | 各班班主任名册（一人一行）：查看在管/空缺班级、登记/改安排班主任 |
| 任务总览 | 全学院任务统计：总数 / 开放中 / 按班回收率 / 按发布人分布 / 最近任务，可按班筛选、导出 |
| 院长账号 | 院长账号管理：新增纯院长 / 兼班主任院长，指派管辖班 |
| 班级管理 | 学院视角建班、停用、批量删除、改班主任安排 |

### 角色与权限

| 界面名 | 标识 | 等级 | 权限 | 缴费对象 |
|--------|------|------|------|---------|
| 普通成员 | `MEMBER` | 0 | 只读（含自己的缴费/任务） | ✅ 交班费 |
| 访客 | `GUEST` | 0 | 只读**受限范围**（班主任逐项指定） | ✅ |
| 生活委员 | `ADMIN` | 1 | 运营 | ✅ 交班费 |
| 班长 | `MONITOR` | 2 | 运营 | ✅ 交班费 |
| 班主任 | `TEACHER` | 3 | 运营 + 本班管理 | ❌ 不参与 |
| 院长 | `DEAN` | 4 | **系统管理员**（学院层全权） | ❌ 不参与 |

- **运营权限三者一致**（班主任之下的 ADMIN/MONITOR/TEACHER 记账/作废/小票/成员管理/批次/公告同权），差别在两处：
  - **等级护栏**：不能创建或操作比自己等级高的账号（`院长 > 班主任 > 班长 > 生活委员 > 成员`），判定一律看 `ROLE_LEVEL` 等级，不写角色名；
  - **管辖范围**：班主任管自己的班；院长管整个学院（账号管理、班级管理、学院任务、名册）。
- **院长分两种**：① **兼班主任院长**（院长 + 本班班主任 → 同班主任权限 + 学院权限）；② **纯院长**（`dean_only=1`，只管学院事务，班级事务一概不参与）。
- **权限由后端强制**：`_STAFF_ROUTES` 角色路由表 + 端点级 `require_role` 双闸，
  前端路由守卫只负责隐藏入口，**不构成安全边界**。
- **归属权**：改 / 删 / 作废 / 关闭只能操作**自己创建**的数据。
- 班级信息里的「班主任」是 `cls_class.head_teacher` 独立字段（填姓名），与角色无关。

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

打开 <http://localhost:5173>，用**部署时声明的账号**登录（见「账号体系」）。

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
| `未配置 CLASSFEE_TEACHER_USERNAME / PASSWORD` | 没声明账号，见「账号体系」 |
| `已升级 sys_user.role 枚举：新增 'MONITOR'` | 一次性枚举升级，第二次不再出现 |
| `已补审计列：…` / `已把 N 条缴费行补进进行中的批次` | 一次性迁移/回填，第二次不再出现 |

---

## 账号体系

**没有注册页，只有登录页。** 账号不写死在代码里，也**没有默认口令**。

| 来源 | 账号 | 密码 | 角色 |
|------|------|------|------|
| **部署配置声明** | `CLASSFEE_TEACHER_USERNAME` | `CLASSFEE_TEACHER_PASSWORD` | 班主任（默认）/ 生活委员 |
| 运营在页面创建 | 「成员管理 → 新增成员」时指定 | 运营设定 | 四档任选 |
| 院长在学院页创建 | 「学院 → 院长账号 → 新增」 | 运营设定 | 院长 / 院长+班主任 |

```bash
cp .env.example .env        # 编辑；docker compose 会自动读取仓库根目录的 .env
```

```bash
# 手动部署时等价的环境变量
CLASSFEE_TEACHER_USERNAME=test              # 必填（与 PASSWORD 同时）
CLASSFEE_TEACHER_PASSWORD=换成强口令          # 必填
CLASSFEE_TEACHER_NAME=测试班主任              # 可选，默认同用户名
CLASSFEE_TEACHER_ROLE=TEACHER                # 可选，ADMIN | TEACHER | DEAN
CLASSFEE_DEAN_ONLY=0                         # 仅 ROLE=DEAN 时有意义：0=院长兼班主任（默认） 1=纯院长
CLASSFEE_COLLEGE_NAME=智能汽车学院            # 可选，侧栏顶部显示的学院名
CLASSFEE_JWT_SECRET=<openssl rand -hex 32>   # 令牌签名密钥，生产必填
```

- **仅首次创建**：账号已存在则跳过，**不覆盖**库里改过的密码/角色/停用状态。
- **纯院长**（`CLASSFEE_DEAN_ONLY=1`）：只管学院，看不到班级的账目/任务/成员入口。
- **可管理**：改资料/学号、重置密码、停用（保历史、禁登录）、删除（**仅限零引用**账号）。
- **停用即时生效**：中间件每次请求都查 `sys_user.status`。

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

- **单一事实源**：收支共用一张 `fee_record` 流水表。**记错优先走「作废（红冲）」留痕**，运营也可物理删除（事务内回滚余额并联动缴费状态）。
- **审计留痕**：作废/关闭/编辑都会记下**谁**在**什么时候**动的；删除仍是硬删无痕，界面文案一律引导「记错优先作废」。
- **余额**：`SUM(收入 NORMAL) − SUM(支出 NORMAL)`，`cls_class.balance` 冗余列在**同一事务内原子 UPDATE**，不接受手改。
- **金额**：数据库 `DECIMAL(10,2)`，Python 侧 `Decimal` + `HALF_UP`，**全链路禁止 float**。
- **缴费单一入口**：成员缴费在「收费批次 → 标记缴费」一个事务写入（`fee_record` + `fee_payment.status` + 余额）。
- **小票**：支出可挂票据（`POST /api/files` 上传 → `receiptUrl` 挂账 → 账本点「查看」带 token 取图）。
  前端选图**自动压缩**（最长边 1600px）再上传；服务端 ≤5MB、魔数嗅探、uuid 命名、仅支出可挂、删流水时回收文件。
- **界面不只靠颜色**：收入 `+¥` 绿、支出 `−¥` 红，符号优先于颜色；无障碍对比度 ≥4.5:1。
- **任务口径**：
  - 题型 `BOOLEAN / SINGLE / MULTI / DATE`，发布时只开放「是/否」「单选」；
  - 明细看板按题型分流：**是/否·日期 → 返校四桶；单选/多选 → 按选项**（零人选项也列）；
  - 学院任务 `canAnswer` 恒 false（院长自己不填），「填写」按钮由 `canFill` 控制；
  - 名册回收率 = 学生**全部点完名**的班数 / 分母=已登记班主任的班数（`_adviser_role_condition()` 共用判定）；
  - 学籍变化（仪表盘 `changeTotal`）= **当前不在籍人数**（毕业/入伍/休学/退学/其它），无历史表，给不了「本学期异动人次」。
- **权限判定全链路看 `ROLE_LEVEL`**（`MEMBER=0 … DEAN=4`），不写 `role == "TEACHER"`。
- **学院口径接口不带 `classId`**：`web/src/api/request.ts` 的 `skipClassId` 名单
  （`/college/`、`/dashboard/students`、`/tasks/overview`）+ **新增学院口径接口必须加进去**，否则会被塞「当前班」。

### 数据模型（15 张表）

`schema.sql` 由后端启动时**幂等执行**；改列定义时**必须**同步两处：

1. `server-py/db/schema.sql`（新库）
2. `server-py/app/seed.py` 的幂等 `ALTER`（既有库）

| 表 | 用途 |
|----|------|
| `cls_class` | 班级（含冗余余额列、`head_teacher` 纯文本） |
| `sys_user` / `sys_user_class` | 用户 + 多对多班级关联（`is_adviser=1` = 班主任） |
| `fee_category` | 收支类别字典（启动时按 kind 幂等补齐 11 条） |
| `fee_record` | **核心流水**，作废 = 红冲，审计列 `voided_by/voided_at` |
| `fee_batch` / `fee_payment` | 收费批次 + 逐人缴费状态 |
| `sys_notice` | 班级公告，审计列 `updated_by/updated_at` |
| `student_field` / `student_record` / `student_record_value` | 学籍名册字段设计 + 逐人取值 |
| `student_access_request` / `student_grant` | 跨班数据访问申请与授权 |
| `cls_task` / `cls_task_answer` / `cls_task_student_answer` | 任务 + 本人答案 + 院长视角学生级答案 |

---

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
├─ docs/部署-Linux.md      部署指南（手动 systemd+nginx / Docker Compose）
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
