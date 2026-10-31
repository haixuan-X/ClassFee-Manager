# 交接文档 · HANDOFF

> **给下一个 AI 会话**：读完这一份就能接着干活，不必从头摸索。
> 由上一个会话写于 **2026-10-30**，它当时刚完成「学院任务详情仪表盘」与「按状态筛选导出」两件事。
> 编码按本项目规定存为 **UTF-8 带 BOM**（人读的 markdown 无 BOM 在中文 Windows 上是乱码，见 README「编码规则」）。

---

## 0. 阅读顺序与文档时效

| 先读 | 用途 | 时效 |
|------|------|------|
| 本文件 | 本地环境、当前未提交状态、权限与任务模块的实操要点、用户约定 | **最新**（2026-10-30） |
| `README.md` | 产品定位、快速开始、编码规则、运维要点 | 较新，但**有滞后**（见下） |
| `docs/系统设计文档.md` | 权限矩阵、DDL、全部接口、**第 1–22 轮**交付记录（含踩坑） | 权威设计文档，但只写到第 22 轮 |
| `docs/部署-Linux.md` | 手动部署 / Docker / 故障排查 | 部署用 |

### ⚠ 已知滞后（别被 README 志骗了）

README 与设计文档写的是**历史数字**，以下以代码为准：

| README 说 | 实际（本机核实） |
|-----------|------------------|
| 「7 张表」 | **15 张**（新增学生信息 6 张 + 任务 3 张） |
| 「288 项断言」 | **1121 passed / 0 failed**（`server-py/tests/api_regression.py`） |
| 「36 个 REST 端点 / 11 个页面」 | 更多，见 §4 |
| 没有「任务 / 学院」模块 | 已有完整的**任务（点名/统计）**与**学院（院长）**层 |
| 版本 | **1.2.0** |

**第 23–49 轮的交付记录没有写进 `docs/系统设计文档.md`**，只存在于代码注释、回归用例名（`test_a24`…`test_a39`）与本文件 §6、§7。

---

## 1. 项目 30 秒

**学生信息管理系统**（原名「班费系统」，仓库内仍有 `classfee` 痕迹：包名 `classfee-web`、库名 `classfee`、env 前缀 `CLASSFEE_`）。

四块业务叠在一起：

1. **班费账本**：收支流水、作废红冲、收费批次逐人缴费、小票图片、公告。
2. **学生信息名册**：自定义字段、Excel 导入导出、就地改一格（电子表格交互）、字段改类型。
3. **任务 / 点名**：发布一个**单问题**任务（是/否、单选、多选、日期），逐人填答、看明细、导出。
4. **学院层（院长）**：跨班学生名册、班主任名册、**学院任务**（发给各班班主任逐个点名）。

技术栈：`Vue 3 + Vite + Element Plus + ECharts` ｜ `FastAPI + SQLAlchemy 2.0（Python 3.13）` ｜ `MySQL 8 / MariaDB`。

**本项目是 Vibe Coding 产物**：AI 写码、人拍板需求与验收，已进行 **49 轮**。

---

## 2. 当前状态快照（2026-10-30）

- **版本** `1.2.0`。真相源 **`server-py/app/version.py` 里 `VERSION = "1.2.0"` 一行**；`web/package.json` 同步写 1.2.0，回归 `test_a19_version` 专门盯两处漂移。
- **分支** `main`，最近提交 `93daf83 修复前端代码的 TypeScript 类型校验不通过`。
- **⚠ 大量改动未提交**（**用户自己 commit，AI 永远不要替他提交**）：
  - 26 个文件已修改，**+1935 / −92**
  - 5 个新文件未跟踪：`web/src/components/TaskDetailDashboard.vue`、`web/src/components/TaskRollcallDrawer.vue`、`web/src/composables/useCloseGuard.ts`、`web/src/utils/rafThrottle.ts`、`web/src/utils/taskStatus.ts`
- **回归**：`1121 passed / 0 failed`（原 1099 + 新增 `test_a39` 20 条 + `test_a24` 白名单 2 条）。
- **type-check / build 均 0 错**。
- **数据现状**（本机 MariaDB，跑完回归会自动清探针）：
  - 班：`id=1` `云计算2502`，**35 个学生**，班主任字段 `test-ls`
  - 账号：只剩 **`dean`（DEAN, id=3310）** 与 **`test`（TEACHER/班主任, id=14）**，密码都是 `123456`；回归的 `KEEP_ACCOUNTS = ["dean"]` 与「账号回到基线」断言依赖这个状态
  - 任务：**`2935` = 用户自建的 `test`（BOOLEAN 是/否 + 备注，35 人已全答）—— 不要删、不要改**
  - 临时验证任务 `3054`（TEMP返校验证-待删）**已删除**

---

## 3. 本地怎么跑（照抄能用）

### 3.1 起服务

```powershell
# 后端 :8080 —— 用项目 venv，cwd 必须是 server-py
Start-Process -FilePath "D:\bj\server-py\.venv\Scripts\python.exe" `
  -ArgumentList "-u","run.py" -WorkingDirectory "D:\bj\server-py" -WindowStyle Hidden

# 前端 :5173（/api 已代理到 :8080）
cd D:\bj\web; npm run dev
```

- `server-py/run.py` 是**专门给 PyCharm 右键运行**的入口（会 `chdir` 到 `server-py`、只读 `.env` 里的 `CLASSFEE_COLLEGE_NAME`、Debug 模式自动关 reload）。
- `run.py` 默认 `CLASSFEE_RELOAD=1` → uvicorn **父 + 子两进程**。
- 接口文档：`http://127.0.0.1:8080/docs`；`GET /api/version` 可探活。

### 3.2 ⚠ 改了 `.py` 之后必须这样重启（最容易踩的坑）

**热重载对「新增路由」不可靠**，症状是新接口 **405**（旧内存里没有这条路由）。而且杀父进程会留**孤儿攥着 8080**，重启失败或起的是旧代码。必须**父子 + 孤儿一起杀**：

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'run\.py|spawn_main' } |
  ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -EA Stop; "已停 $($_.ProcessId)" } catch {} }
Start-Sleep -Seconds 3
Start-Process -FilePath "D:\bj\server-py\.venv\Scripts\python.exe" `
  -ArgumentList "-u","run.py" -WorkingDirectory "D:\bj\server-py" -WindowStyle Hidden
Start-Sleep -Seconds 7
Get-NetTCPConnection -LocalPort 8080 -State Listen -EA SilentlyContinue   # 确认 LISTENING
```

重启后**先打 `GET /api/version` 确认起来了**，再跑回归。

### 3.3 回归（本项目唯一常驻的自动化闸门）

```powershell
cd D:\bj\server-py
& ".\.venv\Scripts\python.exe" -X utf8 tests\api_regression.py
```

- **必须先有 8080 在跑**（它打的是真 HTTP）。
- `-X utf8` 是为了控制台中文不乱码。
- `test_*` 命名，也可被 pytest 收集；`ALL_TESTS` 列表定义执行顺序（`test_a15_cleanup` 固定在**末尾**，负责清探针/回到基线）。
- 收尾会打印 `RESULT: N passed, M failed` 与「账号回到基线（跑之前有哪些，跑完还是哪些）」。
- 根目录的 `api-regression.ps1` 是**老的 PowerShell 版**（288 断言时代），已被上面这个取代，别再改它。

### 3.4 前端检查

```powershell
cd D:\bj\web
npm run type-check    # vue-tsc --noEmit
npm run build         # vite build
```

两者都必须 0 错才能交。

### 3.5 浏览器端到端验证（本会话的通道）

本会话用 **playwright 浏览器工具**（不是 in-app browser）做的视觉/网络验证，要点：

- 工具签名用 `target` 不是 `ref`：`browser_type({element, target, text})`、`browser_click({element, target})`、`browser_snapshot({depth, target})`
- **refs 每次 snapshot 后重新生成**（形如 `f2e203`），旧 ref 点击报 not found → 先 `browser_find` / 重新 snapshot 再操作
- 网络：`browser_network_requests({static:false, filter:"regex"})`、`browser_network_request({index, part:"request-body"})`
- 截图：`browser_take_screenshot({scale:"css", filename})` —— `scale` 是**必填**
- ⚠ 工具会在仓库根生成 **`.playwright-mcp/`**（快照 + 下载的 xlsx），**提交前删掉**，它是工具缓存不是代码
- 登录页/侧栏页脚会显示 `v1.2.0`，可当版本探针

---

## 4. 代码地图

### 4.1 后端分层

```
server-py/
├─ run.py                PyCharm 运行入口
├─ db/schema.sql         15 张表 DDL，启动时幂等执行（必须 UTF-8 无 BOM！）
├─ app/
│  ├─ main.py            app 装配、异常处理、启动迁移
│  ├─ config.py          环境变量 → settings（DB URL、学院名、上传目录）
│  ├─ db.py              engine / SessionLocal / get_db
│  ├─ models.py          15 个 ORM 模型（每个类的 docstring 是最佳文档）
│  ├─ schemas.py         Pydantic 请求体（校验层）
│  ├─ security.py        ★ JWT + 三道权限闸（§5）
│  ├─ seed.py            幂等建表 + **幂等 ALTER 迁移**（改列必须同步这里）
│  ├─ errors.py          BizException（bad_request / forbidden …）
│  ├─ responses.py       统一 R<T> 包装 {code, message, data}
│  ├─ routers/           HTTP 层：只做参数校验与响应包装
│  │   auth · users · members · records · batches · categories
│  │   notices?(在别处) · class_info · students · college · tasks
│  │   dashboard · files · meta(版本) · auth
│  └─ services/          业务规则与事务（权限真正的闸门常在这层）
│      task_service · task_excel · record · batch · user · student
│      export · dashboard · auth · file · notice · class · category
└─ tests/api_regression.py   契约回归 1121 项
```

**分层铁律**：routers 只做参数校验与包装；**业务规则与权限判断在 service 层**；「谁能做什么」还要过 `security.py` 的中间件。

### 4.2 数据表（15 张，`schema.sql` 与 `models.py` 必须一致）

| 类别 | 表 |
|------|----|
| 班费 | `cls_class`（含冗余 `balance`）、`fee_category`、`fee_record`、`fee_batch`、`fee_payment` |
| 账号 | `sys_user`（含 `role` ENUM、`dean_only`、`guest_scopes`、`status`）、`sys_user_class`（多班关系） |
| 学生信息 | `student_field`、`student_record`、`student_record_value`、`student_access_request`、`student_grant` |
| 任务 | `cls_task`、`cls_task_answer`、`cls_task_student_answer` |

> **改列定义必须同步两处**：`db/schema.sql`（新库）+ `app/seed.py` 的幂等 `ALTER`（既有库）。
> 漏第 2 步 = 已有库不变；给 ENUM 加值漏了会直接 500（`DataError 1265`）。
> 全库**不建外键**，级联删除一律在 service 里显式做。

### 4.3 前端

```
web/src/
├─ api/          按域拆分（request.ts 是 axios 实例 + 拦截器）
│  ├─ request.ts ★ 拦截器会给**所有**请求补 ?classId=1（既有行为，FastAPI 忽略未知 query）
│  ├─ tasks.ts   任务相关 + exportTaskDetail(id, filter?)  ← 本轮改过
│  ├─ students/college/records/batches/users/…
│  └─ download.ts 的 downloadXlsx / exportFailure 被各处导出共用
├─ views/        页面（路由见 router/index.ts）
│  dashboard · records(收入/支出同组件) · my-fees · student-info
│  tasks(班级任务 + overview) · members · batches · member-manage
│  class-info · college/{students,advisers,tasks} · profile · login · error
├─ components/   TaskDetailDashboard.vue(★本轮) · TaskRollcallDrawer.vue
│                TaskPublishDialog.vue · 图表组件 …
├─ composables/  useCloseGuard.ts（三处弹层关闭拦截的公共实现）
├─ utils/        taskStatus.ts(★分桶唯一真相源) · download.ts · rafThrottle.ts
├─ stores/       pinia 登录态
└─ router/       路由守卫（只隐藏入口，**不构成安全边界**）
```

**页面 → 角色**（`meta.roles`，`STAFF_ROLES` 共用）：

- 全员：`dashboard`、`records`(只读)、`profile`、`class-info`、`student-info`、`tasks`
- 运营 `STAFF_ROLES={ADMIN,MONITOR,TEACHER,DEAN}`：`income`、`expense`、`members`、`batches`、`member-manage`、`tasks/overview`（实际 DEAN 用）
- 仅 `DEAN`：`tasks/overview`、`college/students`、`college/advisers`、`college/tasks`、`college/class-tasks`
- `roles: ['ADMIN','MONITOR','MEMBER']`：`my-fees`（**班主任不参与缴费**）

---

## 5. 权限模型（最容易改错的地方，动之前先读 `app/security.py` 的注释）

### 5.1 角色与等级

```python
ROLE_LEVEL = {"MEMBER":0, "GUEST":0, "ADMIN":1, "MONITOR":2, "TEACHER":3, "DEAN":4}
STAFF_ROLES = {"ADMIN", "MONITOR", "TEACHER", "DEAN"}   # 记账/成员管理等运营权限四者同权
```

- 中文名：MEMBER 普通成员 / ADMIN 生活委员 / MONITOR 班长 / TEACHER 班主任 / DEAN 院长 / GUEST 访客
- **角色是身份，等级才是权限**：账号管理的护栏一律比 `ROLE_LEVEL`，别写 `!= "TEACHER"`（会出现院长管不了、班主任反而能管的倒挂）。
- GUEST 访客：纯只读，靠 `sys_user.guest_scopes` 勾选范围（`DASHBOARD/RECORDS/STUDENTS/TASKS`）。
- DEAN 有两种：**兼班主任**（`dean_only=0`，班级事务都能管）与**纯院长**（`dean_only=1`，只能碰学院层）。

### 5.2 三道闸（顺序）

1. **`PUBLIC_ROUTES`**（`security.py:96`）：免登录白名单（登录、版本、静态）。
2. **`_STAFF_ROUTES`**（`security.py:354`）：中间件强制，**表内路径只有 STAFF_ROLES 能过**。
   ⚠ **故意不含任何 `/api/tasks` 条目** —— 填答案是全员动作，拦在中间件会导致「同学连任务都答不了」。
3. **`_PURE_DEAN_ALLOWED`**（`security.py:426`）：**纯院长白名单**（默认方向是「关」）。
   加新接口时**必须确认是否要加进来**，否则纯院长 403。
   - 已确认：`("POST", r"^/api/tasks")` 是**前缀匹配（无 `$`）**，所以 `POST /api/tasks/{id}/export` 直接命中，**无需新增条目**。
   - `("GET", r"^/api/class/choices$")` 这类带 `$` 的才需要逐条点名。

4. **service 层**：真正的业务权限（任务的「仅发布人/班主任可看明细」「纯院长限于学院任务」等）。

**加一个新接口时的检查清单**：
① 要不要进 `_STAFF_ROUTES`（运营才有）？ ② 纯院长要不要？→ 看 `_PURE_DEAN_ALLOWED` 是否命中；
③ service 层有没有归属权/范围判断？ ④ 回归里补断言（白名单漏条目在 a24 列表里点名，端到端在对应 `test_aNN` 里验）。

> 历史教训（写在 `security.py` 注释里）：**用白名单而不是黑名单**。黑名单漏一个 = 静默放行（不可发现）；白名单漏一个是 403（可发现、可补）。访客范围那道闸门曾因「没命中 = 放行」吃过亏。

---

## 6. 任务模块专题（第 25、32、45、48、49 轮，最近两轮的工作全在这）

### 6.1 概念

- **一个任务 = 一个问题**（刻意不做成多问题问卷）。题型 `BOOLEAN / SINGLE / MULTI / DATE`，`allow_text` 独立开关（可再补一句说明）。
- **`scope`**：
  - `CLASS`（默认）：班主任/班长发给**本班**，**同学**应答 → 答案进 `cls_task_answer`（键 `user_id`）
  - `COLLEGE`：院长发到**全学院**，**各班班主任**逐个点名 → 答案进 `cls_task_student_answer`（键 **`record_id`** = `student_record.id`，因为名册学生**不一定有账号**；另有冗余 `class_id`）
- **答案存原文不存选项下标**（发布人可以改选项）。
- 关闭：`status=1/0`；过 `deadline` 也停收（不另存状态）；`pinned` 置顶出现在全员仪表盘。

### 6.2 关键端点（`app/routers/tasks.py`）

| 方法/路径 | 用途 |
|-----------|------|
| `GET /api/tasks` | 全员列表（**只到汇总，不含别人答案**） |
| `GET /api/tasks/pinned` · `/overview` · `/overview/export` | 置顶 / 任务总览 / 总览导出 |
| `POST /api/tasks` | 发布（scope 由 body 定） |
| `GET /api/tasks/{id}/detail` | **明细（唯一出现别人答案的出口）**，仅发布人与班主任/院长 |
| `GET /api/tasks/{id}/export` | 全量导出 xlsx |
| **`POST /api/tasks/{id}/export`** | **按状态筛选导出（第 49 轮新增）** |
| `GET /api/tasks/{id}/rollcall` · `PUT …/rollcall` · `GET …/rollcall/export` | 点名页（班主任视角）/ 批量存 / 点名导出 |
| `PUT /{id}` · `POST /close|reopen|pin|unpin` · `DELETE /{id}` | 仅发布人自己 |
| `PUT /{id}/answer` | 全员填答（班主任与访客除外） |

学院侧另有 `GET /api/college/tasks`（学院任务一览）。学生名册侧的导出惯例是 **`GET /students/export` 全量、`POST /students/export` 子集**。

### 6.3 「未返校」的口径 —— **唯一真相源在前端**

`web/src/utils/taskStatus.ts`：

| 桶 | 包含 |
|----|------|
| `absent` 未返校 | 填了否定状态（否/未到/缺席…）**+ 还没填的** |
| `excused` 请假 | 请假/病假/事假 —— **不算未返校**（用户明确定的口径） |
| `returned` 已返校 | 是/到校/已返校/正常… |
| `other` 其它状态 | **认不出的文案单列一栏**，绝不硬塞 |

- **判定顺序固定：请假 → 未返校 → 已返校**（「未到校」同时含「未到」和「到校」，先判否定词才归得对）。
- `null`/空串 = 还没填 = 按口径算未返校。
- 导出时 `statusLabel()` 让图例/列表/卡片三处叫法一致（空值统一显示「未填」）。

> **后端绝不重写一份这个关键词表**。这是设计约束：屏幕上的分桶和导出的文件必须来自同一份代码。

### 6.4 详情仪表盘（`web/src/components/TaskDetailDashboard.vue`，第 48 轮）

- 由 `web/src/views/college/tasks/index.vue` 的「详情」按钮打开（el-dialog）。
- 复用 `GET /tasks/{id}/detail`，**后端零改动**，统计全由前端从学生行现算。
- 顶部大数字卡片**同时是筛选 tab**：真 `<button>` + `aria-pressed`，点中态有描边 + 「（筛选中）」文字（不只靠颜色）；点「学校总人数」复位。
- 分组顺序固定 **请假 → 未返校 → 已返校**（截图里是 `未返校 / 请假` 分段标题）；`other` 单列。
- 班级卡片：命中筛选时**没有人的班整段不出现**；标题随筛选变「未返校 · 各班名单」。
- 页脚按钮：`导出全部（N 人）` / `导出（未返校 30 人）`，筛选态 0 人禁用。

### 6.5 筛选导出的契约（第 49 轮，**改这块前必读**）

```
前端：按 taskStatus.ts 算出当前筛选的 recordIds
      → POST /api/tasks/{id}/export  {recordIds:[...], label:"未返校"}
后端：只做**集合过滤**，不认任何状态语义
      → 文件内容 = 屏幕上那些行
```

- **为什么传 id 不传「状态=未返校」**：判定写两份必然漂，会出现「屏幕 6 人、文件 8 人」且没人查得出来。传 id 列表则**结构上不可能对不上**。
- `recordIds` 上限 500；全量请走 `GET /export`。
- **空 `recordIds` 或一个都没命中 → 400**（不发只有表头的空文件）。
- 命中 0 人的班**整段不出现**；班标题改成「筛选出 N 人」；副标题加「筛选：label（N 人）」（无 label 时写「所选行」）；文件名加 `-label`。
- 权限与 `GET` 完全同闸（都走 `get_detail`）。
- 学院任务行键 `recordId`，班级任务行键 `userId`，按各自有的键匹配。

### 6.6 相关文件

| 文件 | 内容 |
|------|------|
| `web/src/utils/taskStatus.ts` | 分桶唯一真相源 |
| `web/src/components/TaskDetailDashboard.vue` | 仪表盘（筛选 tab + 页脚导出） |
| `web/src/api/tasks.ts` | `exportTaskDetail(id, filter?)`、`TaskExportFilter` |
| `server-py/app/services/task_excel.py` | `export_detail(..., only_ids, label)` |
| `server-py/app/routers/tasks.py` | `POST /{id}/export` |
| `server-py/app/schemas.py` | `TaskExportRequest` |
| `server-py/tests/api_regression.py` | `test_a39_task_export_filter`（20 条）+ `test_a24` 白名单条目 |

---

## 7. 未提交改动 & 服务器同步清单

**AI 不要 commit —— 用户自己提交代码。** 下面是这几轮动过的文件。

### 第 49 轮（按状态筛选导出）

- `server-py/app/schemas.py` — `TaskExportRequest`
- `server-py/app/routers/tasks.py` — `POST /{task_id}/export`
- `server-py/app/services/task_excel.py` — `only_ids` / `label`
- `server-py/tests/api_regression.py` — `test_a39` + a24 白名单 2 条
- `web/src/api/tasks.ts` — `exportTaskDetail(id, filter?)`
- `web/src/components/TaskDetailDashboard.vue`

### 此前几轮（一并同步）

- `server-py/app/version.py`（1.2.0 真相源）
- `web/package.json` + `web/package-lock.json`（1.2.0 锚点）
- `server-py/db/schema.sql` — **⚠ 服务器要建 `cls_task_student_answer` 表**
- `server-py/app/security.py` — 纯院长白名单 / 访客范围
- `server-py/app/models.py`、`app/services/task_service.py`、`app/routers/users.py`、`app/services/user_service.py`、`app/schemas.py`
- `web/src/utils/taskStatus.ts`、`web/src/composables/useCloseGuard.ts`、`web/src/utils/rafThrottle.ts`
- `web/src/components/TaskRollcallDrawer.vue`、`TaskPublishDialog.vue`
- `web/src/views/college/tasks/index.vue`、`web/src/views/tasks/index.vue`、`web/src/views/member-manage/index.vue`、`web/src/views/records/index.vue`、`web/src/views/login/index.vue`
- `web/src/layout/SideNav.vue`、`web/src/api/users.ts`、`web/src/types/index.ts`
- 图表：`web/src/components/{CategoryPie,StudentTrendChart,TrendChart}.vue`

> 部署提醒：Docker 场景**只重启不生效**（配置是 COPY 进镜像的），要 `up -d --build`。

---

## 8. 用户的工作约定（照着来，别自作主张）

1. **不要 commit / push**。改完把清单交给用户，他自己提交。
2. **演示数据要清干净**：临时账号、临时任务、探针必须自己删掉；回归跑完账号要回到基线（`['dean','test']`）。
3. **页面文案要自明**：按钮/标题带上对象与数量（「导出（未返校 30 人）」），不让人靠猜。
4. **权限按等级推导**（`ROLE_LEVEL`），不写角色名硬比较。
5. **金额全链路 `Decimal` + `HALF_UP`，禁止 float**；DB 是 `DECIMAL(10,2)`。
6. **快捷键写进页脚**。
7. **不只靠颜色传达信息**：正负要带 `+/−`、选中态要描边、状态要文字。
8. **导出惯例**：`GET = 全量`、`POST = 子集`。
9. **改完要真跑**：type-check + build + 回归三样都绿才算完；能用浏览器实测就实测。
10. **单一事实源**：同一份口径只写一处（版本号、分桶关键词、缴费角色口径都是）。
11. 文案是中文，注释也是中文，且**注释常写「为什么」与踩坑教训** —— 新注释请保持这个密度与风格。
12. 弹层要有三条关闭路径（Esc / × / 遮罩），公共实现抽到 `composables/useCloseGuard.ts`。

---

## 9. 踩坑记录（本机 / 本项目特有）

| 坑 | 症状 | 解法 |
|----|------|------|
| 改 `.py` 后没真重启 | 新路由 **405**，或跑的是旧内存状态 | 见 §3.2，父子 + 孤儿一起杀再起 |
| `schema.sql` / `nginx.docker.conf` 带 BOM | 新库**静默少一张表** / frontend 容器起不来 | 存为 UTF-8 **无 BOM**；回归 `test_a00_encoding_guards` 会扫 |
| playwright ref 复用 | 点击报 `Ref not found` | 每次 snapshot 后 ref 变了，重新 find/snapshot |
| 全局 axios 拦截器 | 所有请求带 `?classId=1` | 既有行为，FastAPI 忽略未知 query，别当成 bug 改 |
| 循环变量覆盖函数参数 | 第 49 轮真抓到：表头循环 `for i, label in …` 覆盖了筛选名参数 → 文件名变 `…-提交时间-回答.xlsx` | 循环变量改名 `col_title`；**e2e 能抓住这类错，别只靠看** |
| `.playwright-mcp/` 出现在仓库根 | `git status` 多出一堆 | 浏览器工具缓存，提交前删 |
| PS 5.1 按 ANSI 读文件 | 中文断言乱码 | 跑 python 回归时加 `-X utf8`；`.ps1` 里只放 ASCII 字面量 |
| 服务起不来 | 8080 被孤儿占用 | 先 `Get-NetTCPConnection -LocalPort 8080` 看 pid 再杀 |
| 截图/下载文件落在仓库根 | 污染 `git status` | 验证完挪到 temp 或删除 |

**跑 e2e 真 API + openpyxl 真解析**是本项目很有效的验证方式（第 49 轮的 `export_e2e.py` 34 条断言就是它抓出了上面那个真 bug）。临时脚本放在
`C:\Users\29913\AppData\Local\Temp\opencode\tscheck\`（**会随 temp 被清理，重要逻辑请固化进 `tests/api_regression.py`**）。

---

## 10. 常见操作速查

| 想做什么 | 怎么做 |
|----------|--------|
| 起后端/前端 | §3.1 |
| 改了后端代码 | §3.2 重启 → 跑回归 |
| 跑全量回归 | `cd server-py; .\.venv\Scripts\python.exe -X utf8 tests\api_regression.py` |
| 前端检查 | `cd web; npm run type-check; npm run build` |
| 看版本真相源 | `server-py/app/version.py`（改版本只改那一行 + 同步 package.json） |
| 加新接口 | 过 §5.2 检查清单 → 回归补断言 → 必要时 bump MINOR |
| 改表结构 | `db/schema.sql` + `app/seed.py` 幂等 ALTER **两处都改** |
| 加纯院长可访问的接口 | 确认 `_PURE_DEAN_ALLOWED` 命中 + a24 列表点名 |
| 查「未返校」口径 | `web/src/utils/taskStatus.ts`（**唯一**） |
| 改任务导出 | `task_excel.export_detail` + `tasks.py` 的 POST 路由 + `TaskDetailDashboard.vue` 的 `onExport` |
| 清浏览器工具缓存 | 删仓库根 `.playwright-mcp/` |

---

**给下一个会话的最后一句**：这个项目的注释与文档**刻意写得很密**（记录为什么这么选、踩过什么坑）。动手前先在你要改的那个文件里读注释 —— 大概率答案已经在里面了。
