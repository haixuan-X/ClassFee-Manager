# 交接文档 · HANDOFF

> **给下一个 AI 智能体**：读完这一份就能接着干活，不必从头摸索。
> 最后更新 **2026-11-03**（代码基线 HEAD `6f069f1`；文档自身的提交不算代码改动。全量回归 **1263 passed / 0 failed**）。
> 编码：本文件按项目约定存为 **UTF-8 带 BOM**（「人读」的 markdown 要带 BOM，否则中文 Windows 的 GBK 工具打开是乱码；
> 而 `schema.sql`、`nginx.conf` 这类**程序读**的文件反过来必须**无** BOM，见 §10 与 `test_a00_encoding_guards`）。

---

## 0. 阅读顺序与文档时效

| 先读 | 用途 | 时效 |
|------|------|------|
| `AGENTS.md` | 硬规则（单智能体、不改历史、三件套） | 最新 |
| **本文件** | 环境、代码地图、权限、**口径清单**、踩坑 | **最新（2026-11-03）** |
| `README.md` | 产品定位、快速开始、编码规则 | 较新，但**数字有滞后** |
| `docs/系统设计文档.md` | 权限矩阵、DDL、全部接口、**第 1–22 轮**交付记录 | 权威，但只写到第 22 轮 |
| `docs/问题.md` | 用户报障 / 需求清单（当前**全部已处理**） | 随用户更新 |
| `docs/测试分工.md` | 四角色手工验收用例（A1–X10） | 可用 |
| `docs/部署-Linux.md` | 部署 / 排障 | 部署用 |

### ⚠ 已知滞后（别被 README 骗）

| README 说 | 实际（本机核实） |
|-----------|------------------|
| 「7 张表」 | **15 张** |
| 「288 项断言」 | **1263 passed / 0 failed** |
| 没有「任务 / 学院」模块 | 已有完整任务（点名/统计）与学院（院长）层 |
| 版本 | **1.5.0**（真相源 `server-py/app/version.py`） |

第 23 轮之后的交付记录**没有写进设计文档**，只存在于代码注释、回归用例名（`test_a23`…`test_a47`）和本文件。

---

## 1. 项目 30 秒

**学生信息管理系统**（原名「班费系统」；包名 `classfee-web`、库名 `classfee`、env 前缀 `CLASSFEE_` 都还是旧名）。

四块业务：

1. **班费账本**：收支流水、作废红冲、收费批次逐人缴费、小票图片、公告。
2. **学生信息名册**：自定义字段、Excel 导入导出、就地改一格（电子表格交互）、字段改类型。
3. **任务 / 点名**：单问题任务（是/否、单选、多选、日期），逐人填答、看明细、导出。
4. **学院层（院长）**：跨班学生名册、班主任名册、**学院任务**（发给各班班主任接龙）。

技术栈：`Vue 3 + Vite + Element Plus + ECharts` ｜ `FastAPI + SQLAlchemy 2.0（Python 3.13）` ｜ `MySQL 8 / MariaDB`。

**Vibe Coding 产物**：AI 写码、人拍板需求与验收。

---

## 2. 当前状态快照（2026-11-03）

- **版本** `1.5.0`。真相源 **`server-py/app/version.py` 的 `VERSION` 一行**；`web/package.json` 同步写 1.5.0，回归 `test_a19_version` 盯两处漂移。
- **分支** `main`，HEAD `6f069f1`，**工作区干净**。
- **回归**：`1263 passed / 0 failed`（`server-py/tests/api_regression.py`，`ALL_TESTS` 共 50 个用例函数）。
- **前端**：`npm run type-check` 0 错。
- **本机数据**（演示库）：16 个启用班、约 100 名在册学生；常见账号 `dean`（院长）、`test`（班主任），密码以 `.env` / 种子配置为准（本地通常是 `123456`）。回归跑完会自己回到开跑时的基线。
- **`docs/问题.md` 的条目已全部处理完**（院长 4 组 + 班主任 3 组）。

---

## 3. 本地怎么跑

### 3.1 起服务

```powershell
# 后端 :8080 —— 用项目 venv，cwd 必须是 server-py
Start-Process -FilePath "D:\bj\server-py\.venv\Scripts\python.exe" `
  -ArgumentList "-u","run.py" -WorkingDirectory "D:\bj\server-py" -WindowStyle Hidden

# 前端 :5173（/api 已代理到 :8080）
cd D:\bj\web; npm run dev
```

- `server-py/run.py` 是给 PyCharm 右键运行的入口（会 `chdir` 到 `server-py`、只读 `.env` 里的 `CLASSFEE_COLLEGE_NAME`、Debug 模式自动关 reload）。
- `run.py` 默认 `CLASSFEE_RELOAD=1` → uvicorn **父 + 子两进程**。

> ⚠ **`.env` 不会自动进环境变量**：`run.py` 只读 `CLASSFEE_COLLEGE_NAME`，
> 数据库账号、JWT 密钥、种子班主任账号全靠**进程环境**。从新开的 PowerShell
> 直接起服务时，先逐行注入再启动：
>
> ```powershell
> Get-Content 'D:\bj\.env' -Encoding UTF8 | ForEach-Object {
>   if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
>     Set-Item -Path "Env:$($matches[1])" -Value $matches[2].Trim()
>   }
> }
> $env:CLASSFEE_RELOAD="0"
> ```
>
> 不注入的后果：本地退回 `config.py` 的默认库账号（能连上就碰运气），
> 更麻烦的是**空库不会自动建 `test` 账号**——回归第 1 步就 `SystemExit`（见 §14）。
- 接口文档 `http://127.0.0.1:8080/docs`；`GET /api/version` 探活。

### 3.2 ⚠ 改了 `.py` 之后必须这样重启（本项目第一坑）

**热重载基本不可靠**（2026-11-03 一整轮里 `WatchFiles` 只真正触发过两次，改完 `security.py` / `schemas.py` 都没反应，表现为「接口还是旧行为」或新路由 **405**）。
而且杀父进程会留**孤儿攥着 8080**，重启会失败或起成旧代码。必须**父子 + 孤儿一起杀**：

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

重启后**先打 `GET /api/version`** 确认起来了（或 `GET /openapi.json` 看新字段在不在），再跑回归。
> 判断「改动有没有生效」的笨办法但最可靠：查 `/openapi.json` 里有没有新字段 / 新路由。

### 3.3 回归（唯一的自动化闸门）

```powershell
cd D:\bj\server-py
.\.venv\Scripts\python.exe tests\api_regression.py
```

- **必须先有 8080 在跑**（它打真 HTTP）。
- 控制台中文乱码时加 `-X utf8` 或设 `$env:PYTHONIOENCODING='utf-8'`。
- `test_*` 命名，可被 pytest 收集；`ALL_TESTS` 列表定义执行顺序（`test_a15_cleanup` 固定在**末尾**）。
- 收尾打印 `RESULT: N passed, M failed` 与「账号回到基线」。**任何 FAIL 都要当成真 bug 查，不要改断言迁就实现**。
- 根目录 `api-regression.ps1` 是 **288 断言时代的老脚本**，已被取代，别再改它。

### 3.4 前端检查

```powershell
cd D:\bj\web
npm run type-check    # vue-tsc --noEmit
npm run build         # vite build
```

### 3.5 浏览器端到端验证

- 可用的浏览器工具：in-app `browser.*`（`browser.tabs.open` → `browser.preview`）或 playwright MCP。
- playwright 要点：工具签名用 `target` 不是 `ref`；**refs 每次 snapshot 后重新生成**；`browser_take_screenshot({scale:"css"})` 的 `scale` 必填。
- ⚠ 工具会在仓库根生成 **`.playwright-mcp/`**（快照 + 下载的 xlsx）——**提交前删掉**。

---

## 4. 代码地图

### 4.1 后端分层

```
server-py/
├─ run.py                PyCharm / 终端运行入口
├─ db/schema.sql         15 张表 DDL，启动时幂等执行（必须 UTF-8 无 BOM！）
├─ app/
│  ├─ main.py            app 装配：中间件（CORS → 鉴权）→ 异常处理 → 路由
│  ├─ config.py          环境变量 → settings（DB URL、学院名、上传目录）
│  ├─ db.py              engine / SessionLocal / get_db
│  ├─ models.py          15 个 ORM 模型（每个类 docstring 是最佳文档）
│  ├─ schemas.py         Pydantic 请求体（校验层）
│  ├─ security.py        ★ JWT + 三道权限闸（§5）
│  ├─ seed.py            幂等建表 + **幂等 ALTER 迁移**（改列必须同步这里）
│  ├─ errors.py          BizException（bad_request / forbidden / unauthorized…）
│  ├─ responses.py       统一 R<T> 包装 {code, message, data}
│  ├─ routers/           只做参数校验与响应包装
│  │   auth · users · members · records · batches · categories
│  │   class_info · students · college · tasks · dashboard · files · meta
│  └─ services/          业务规则与事务（权限真正的闸门常在这层）
│      task_service · task_excel · college_service · college_excel
│      user_service · student_service · student_excel
│      record_service · batch_service · category_service
│      export_service · dashboard_service · auth_service
│      class_service · file_service
└─ tests/api_regression.py   契约回归 1263 项
```

**分层铁律**：routers 只做参数校验与包装；**业务规则与权限判断在 service 层**；「谁能做什么」还要过 `security.py` 中间件。

### 4.2 数据表（15 张，`schema.sql` 与 `models.py` 必须一致）

| 类别 | 表 |
|------|----|
| 班费 | `cls_class`（含冗余 `balance`）、`fee_category`、`fee_record`、`fee_batch`、`fee_payment` |
| 账号 | `sys_user`（`role` ENUM、`dean_only`、`guest_scopes`、`status`）、`sys_user_class`（多班关系 + `is_adviser`） |
| 学生信息 | `student_field`、`student_record`、`student_record_value`、`student_access_request`、`student_grant` |
| 任务 | `cls_task`、`cls_task_answer`、`cls_task_student_answer` |

> **改列定义必须同步两处**：`db/schema.sql`（新库）+ `app/seed.py` 的幂等 `ALTER`（既有库）。
> 漏第二步 = 已有库不变；给 ENUM 加值漏了会直接 500（`DataError 1265`）。
> **全库不建外键**，级联删除一律在 service 里显式做。

### 4.3 前端

```
web/src/
├─ api/          按域拆分（request.ts 是 axios 实例 + 拦截器）
│  ├─ request.ts ★ 给非学院口径请求补 ?classId=<当前班>
│  └─ auth/records/batches/users/students/college/tasks/files/meta/dashboard
├─ views/        dashboard · records(收入/支出同组件) · my-fees · student-info
│               tasks(index + overview) · members · batches · member-manage
│               class-info · college/{students,advisers,tasks} · profile · login
├─ components/   RecordFormDrawer · BatchPayDialog · TaskPublishDialog
│               TaskRollcallDrawer · TaskDetailDashboard · PinnedTasksPanel …
├─ composables/  useModal · useCloseGuard · useReopenTask
├─ utils/        taskStatus.ts(★分桶 + 进度单位) · date.ts · download.ts …
├─ stores/       pinia 登录态
└─ router/       路由守卫（只隐藏入口，**不构成安全边界**）
```

**页面 → 角色**（`meta.roles`）：

- 全员：`dashboard`、`records`(只读)、`profile`、`class-info`、`student-info`、`tasks`
- 运营 `STAFF_ROLES={ADMIN,MONITOR,TEACHER,DEAN}`：`income`、`expense`、`members`、`batches`、`member-manage`
- 仅 `DEAN`：`tasks/overview`、`college/students`、`college/advisers`、`college/tasks`、`college/class-tasks`
- `{ADMIN,MONITOR,MEMBER}`：`my-fees`（**班主任不参与缴费**）

---

## 5. 权限模型（最容易改错的地方，动之前先读 `app/security.py` 的注释）

### 5.1 角色与等级

```python
ROLE_LEVEL = {"MEMBER":0, "GUEST":0, "ADMIN":1, "MONITOR":2, "TEACHER":3, "DEAN":4}
STAFF_ROLES = {"ADMIN", "MONITOR", "TEACHER", "DEAN"}
```

- MEMBER 普通成员 / ADMIN 生活委员 / MONITOR 班长 / TEACHER 班主任 / DEAN 院长 / GUEST 访客。
- **角色是身份，等级才是权限**：账号管理护栏一律比 `ROLE_LEVEL`，别写 `!= "TEACHER"`（会出现院长管不了、班主任反而能管的倒挂）。
- GUEST：纯只读，靠 `sys_user.guest_scopes` 勾选 `DASHBOARD/RECORDS/STUDENTS/TASKS`。
- DEAN 两种：**兼班主任**（`dean_only=0`，占一个班主任名额、班级事务都能管）与**纯院长**（`dean_only=1`，只能碰学院层）。

### 5.2 四道闸（顺序）

1. **`PUBLIC_ROUTES`**：免登录白名单（登录、版本、静态）。
2. **`_STAFF_ROUTES`**：中间件强制，表内路径只有 `STAFF_ROLES` 能过。
   ⚠ **故意不含任何 `/api/tasks` 条目**——填答案是全员动作。
3. **`_PURE_DEAN_ALLOWED`**：纯院长白名单（默认方向是「关」）。加新接口必须确认是否命中，否则纯院长 403。
4. **service 层**：真正的业务权限（明细可见性、归属权、纯院长限学院任务…）。

**加新接口的检查清单**：
① 要不要进 `_STAFF_ROUTES`？ ② 纯院长要不要 → 看 `_PURE_DEAN_ALLOWED`？
③ service 有没有归属权/范围判断？ ④ 回归补断言（`test_a24` 白名单 + 对应 `test_aNN`）。

> 历史教训：**用白名单不用黑名单**。黑名单漏一个 = 静默放行（不可发现）；白名单漏一个 = 403（可发现、可补）。

### 5.3 归属权（A 方案）

改 / 删 / 作废 / 关批次 只允许**创建人自己**（`security.require_ownership`），院长也不行。报错会带上创建人，便于协作。

---

## 6. ★ 口径清单（单一事实源）

**同一个口径只能有一处实现。** 要改下面任何一条，先找到它的真相源，别在旁边再写一份。

| 口径 | 真相源 |
|---|---|
| 版本号 | `server-py/app/version.py` 的 `VERSION`（+ `web/package.json` 同步） |
| 角色等级 / 运营角色 | `server-py/app/security.py` 的 `ROLE_LEVEL` / `STAFF_ROLES`（前端 `types/index.ts` 有镜像，回归比对） |
| 谁能占「班主任」位 | `user_service._adviser_role_condition()`（TEACHER，或 `DEAN` 且 `dean_only=0`） |
| 一个班一位班主任 / 撞车文案 | `user_service._class_teacher_conflict()` + `_teacher_conflict_msg(hint=...)` |
| 班级任务应答对象 | `task_service.is_answer_target()` |
| 学院任务应答对象 | `task_service.is_college_answer_target()`（排除纯院长、访客） |
| **学院任务回收进度** | `task_service.college_recovery()`（见 §7.3） |
| 任务进度的单位文案 | 前端 `utils/taskStatus.ts` 的 `progressUnit(scope)`：`COLLEGE → 班`，其余 `→ 人` |
| 「未返校」分桶 | 前端 `utils/taskStatus.ts`（**唯一**，后端不许重写关键词表） |
| 默认收支类别 | `services/category_service.ensure_default_categories()` + `INCOME/EXPENSE_CATEGORIES` |
| 缴费对象 | `members`/`PAYABLE_ROLES` 口径（**班主任不是缴费对象**） |
| 日期字符串格式 | 后端 `helpers` 只认 `yyyy-MM-dd`；前端日期框**必须**写 `value-format` |
| 导出惯例 | `GET` = 全量、`POST` = 子集（传 id 列表而不是状态语义） |
| 学籍变化（`changeTotal`） | `student_service.dashboard_stats`：**当前不在籍人数**（毕业/入伍/休学/退学/其他）。没有历史表，给不了「本学期异动人次」，别再把它当时间口径 |
| 任务详情看板展示口径 | `TaskDetailDashboard.vue`：`BOOLEAN/DATE → 返校四桶`（`utils/taskStatus.ts`）；`SINGLE/MULTI → 按选项`（`detail.options` 含 0 人项 + 未填）。两种口径共用一套筛选/导出 |
| 候选项上限 | `task_service.MAX_OPTIONS = 4`（前端 `TaskPublishDialog` 的 `MAX_OPTIONS` 同值）。只挡新建，编辑不改候选项 |
| 学院口径接口不带 `classId` | `web/src/api/request.ts` 的 `skipClassId` 名单：`/college/`、`/dashboard/students`、`/tasks/overview`。**新增学院口径接口必须加进去**，否则会被塞「当前班」（漏一次 = 任务总览 0 条） |

---

## 7. 任务模块专题

### 7.1 概念

- **一个任务 = 一个问题**（不是问卷）。题型 `BOOLEAN / SINGLE / MULTI / DATE`；`allow_text` 独立开关。
  - ⚠ **发布时只给「是/否」「单选」**（`TASK_QTYPES_PUBLISHABLE`）——用户要求把「多选」「日期」隐藏；编辑老任务时仍能看到原题型。
- **`scope`**：
  - `CLASS`（默认）：班主任/班长发**本班**，**同学**应答 → `cls_task_answer`（键 `user_id`）
  - `COLLEGE`：院长发**全学院**，**各班班主任**逐人接龙 → `cls_task_student_answer`（键 `record_id`，因为名册学生不一定有账号）
- 答案存**原文**不存选项下标（发布人可改选项）。
- 关闭 = `status=0`；过 `deadline` 也停收；`pinned` 出现在仪表盘。

### 7.2 关键端点（`app/routers/tasks.py`）

| 方法/路径 | 用途 |
|-----------|------|
| `GET /api/tasks?view=mine\|college\|other` | 全员列表（只到汇总，不含别人答案） |
| `GET /api/tasks/pinned` · `/overview` · `/overview/export` | 置顶 / 总览 / 总览导出 |
| `POST /api/tasks` | 发布（scope 由 body 定） |
| `GET /api/tasks/{id}/detail` | **明细（唯一出现别人答案的出口）** |
| `GET /api/tasks/{id}/export` | 全量导出 xlsx |
| `POST /api/tasks/{id}/export` | 按状态筛选导出（传 `recordIds`） |
| `GET/PUT /api/tasks/{id}/rollcall`、`GET …/rollcall/export` | 学院任务接龙页（班主任视角） |
| `PUT /{id}` · `POST /close\|reopen\|pin\|unpin` · `DELETE /{id}` | 仅发布人（院长可管学院任务） |
| `PUT /{id}/answer` | 填答（班主任/访客除外；**学院任务不接受本人作答**） |

### 7.3 学院任务回收进度（2026-11-03 改过，**别再改回学生口径**）

`task_service.college_recovery(db, task_ids) -> (分母, {task_id: 已填班数})`

- **分母** = 班主任名册里**已登记班主任**（`sys_user_class.is_adviser=1` 且角色合格）、**且有学生**的启用班数。
  - 一班一个名额；**两个班同一个班主任算两个**（他要切班各答一次）；**兼班主任的院长也占一位**。
  - **空班不占名额**：没学生就点不了名，算进分母会让进度永远到不了 100%。
- **分子** = 这些班里**学生已全部点完名**的班数（「没有填完的就不算在已填里面」）。
- 三个出口共用它：`college_service.tasks`（学院任务列表）、`task_service._build_rows`（班级任务/总览/置顶）、`task_excel.export_overview`。
- 总览的「回收率」按 scope 拆成两套（人 / 班），**不要把两个单位加成「总体回收率」**。

### 7.4 「未返校」口径（前端唯一）

`web/src/utils/taskStatus.ts`：

| 桶 | 包含 |
|----|------|
| `absent` 未返校 | 填了否定状态（否/未到/缺席…）**+ 还没填的** |
| `excused` 请假 | 请假/病假/事假 —— **不算未返校** |
| `returned` 已返校 | 是/到校/已返校/正常… |
| `other` 其它状态 | **认不出的文案单列**，绝不硬塞 |

- 判定顺序固定 **请假 → 未返校 → 已返校**（「未到校」同时含「未到」和「到校」）。
- `null`/空串 = 还没填 = 未返校。
- 导出用 id 列表做集合过滤，**结构上保证「屏幕 = 文件」**。

### 7.5 列表页的两个坑

- `views/tasks/index.vue` 的「班级任务」页签是**前端本地过滤** `scope !== 'COLLEGE'`（复用 `view=mine` 的请求）。过滤放在 `load()` 里而不是模板里——`rows` 还喂给计数和批量选择，只滤渲染会让「全选」勾到看不见的学院任务。
- `/records`、`/income`、`/expense` **共用 `records/index.vue` 同一个实例**（路由复用，`onMounted` 不重跑）：筛选状态会带过去，改这里要小心。

---

## 8. 2026-11-03 这一轮改了什么

| commit | 内容 | 关键点 |
|---|---|---|
| `caf4352` | 学院任务回收进度改按**班主任名册**统计 | 见 §7.3；`college_recovery` 是唯一口径 |
| `13d3f7f` | 回归脚本：`e.read()` 也走连接层重试 | 见 §10「401 RST」 |
| `4353576` | 鉴权中间件拒绝前**先读掉请求体** | 消掉匿名带 body 请求的 RST |
| `df4db3b` | 账目 3 条：日期框补 `value-format`、起止日期不能早于今天、类别空态 | 见 §9 取舍 |
| `f5147e5` | 班级 2 条：删/作废流水清 `paid_at`、新建班自动下发默认类别 | 序列化层再加一道兜底 |
| `0a58b2b` | 班级任务页签、代人缴费可挂小票 | 小票只开「代为登记」这条路 |
| `df463ea` | 改「我带的班」撞车文案 → 「联系院长」 | 只改本人路径，运营/院长仍指路名册 |

同期另一个会话的提交（`38a94fa`、`54f133d`、`6f069f1`、`73f29af`）：学籍变化名单筛选、任务详情按选项展示 / 候选项上限 4、任务总览 classId、任务详情按班筛选。

---

## 9. 已知取舍（想改先问用户）

1. **起止日期不能早于今天**（用户明确要求，和发布任务截止时间同一条规则）。
   - 因此删掉了「本月 / 近 30 天」快捷项——它们会直接填进过去的日期。
   - ⚠ 副作用：**账本明细再也筛不了历史区间**。如果用户以后想「看历史账」，正确改法是**只把限制加在登记表单的发生时间上**，筛选器放开。
2. **回收进度空班不占名额**（否则永远到不了 100%）。
3. **小票只允许挂在「代为登记」生成的收入流水上**；手动「收入登记」仍然不允许挂小票（回归里有断言 `income with receipt -> 400`）。
4. **班级任务页签是前端过滤**，没有新增后端 `view`——避免多一处服务端可见性口径。
5. `docs/问题.md` 已全部处理完；用户新增问题时往那里记，别直接改代码猜需求。

---

## 10. 踩坑记录（本机 / 本项目特有）

| 坑 | 症状 | 解法 |
|----|------|------|
| **热重载不可靠** | 改完 `.py` 行为没变 / 新路由 **405** | §3.2：父子 + 孤儿一起杀再起；用 `/openapi.json` 验证 |
| **匿名带 body 的请求 401 丢响应** | 客户端拿到 `ConnectionResetError` 而不是 401（表现为「token 过期后报网络错误」） | 已修：`security._discard_body` 在拒绝前读掉 body |
| **日期框漏 `value-format`** | 后端 400「日期格式应为 yyyy-MM-dd」（v-model 是 Date 对象，axios 序列化成 ISO） | 每个 `<el-date-picker>` 都要写；回归 `test_a47` 做源码扫描 |
| **新建班级没有类别** | 登记页空的、代人缴费 400「缺少可用的收入类别」 | `ensure_default_categories()`；启动时给所有启用班补齐 |
| **删缴费后缴费时间残留** | 成员缴费页「未缴费 + 有缴费时间」 | 删/作废流水时清 `paid_at`；序列化层再兜一道 |
| `schema.sql` / `nginx.docker.conf` 带 BOM | 新库**静默少一张表** / 前端容器起不来 | 存为 UTF-8 **无 BOM**；回归 `test_a00` 会扫 |
| PS 5.1 按 ANSI 读文件 | 中文断言乱码 | 跑回归加 `-X utf8` / `PYTHONIOENCODING=utf-8`；`.ps1` 里只放 ASCII |
| 全局 axios 拦截器 | 所有请求带 `?classId=` | 既有行为；学院口径路径故意不注入，别当 bug |
| 路由复用同一组件 | 切页后筛选/状态还留着 | `watch(() => props.scope)` 或路由变化时重载 |
| playwright ref 复用 | 点击报 `Ref not found` | 每次 snapshot 后 ref 变了，重新 find/snapshot |
| `.playwright-mcp/` 出现在仓库根 | `git status` 多一堆 | 工具缓存，提交前删 |
| 8080 被孤儿占用 | 服务起不来 / 起了个旧代码 | 先 `Get-NetTCPConnection -LocalPort 8080` 看 pid 再杀 |
| PowerShell `Set-Content -Encoding UTF8` 带 BOM | `package.json` / PostCSS 解析报 `Unexpected token '\uFEFF'`，`npm run build` 直接挂 | **别用 PowerShell 改 UTF-8 程序文件**；用编辑器工具，或 Python 按字节写、写完检查前 3 字节 |
| Python 给 CRLF 文件做字符串替换 | `raw.find("...\n...")` 返回 `-1`，`raw[:-1] + new + raw[len(old)-1:]` 仍照写 → **整个文件重复一段**（本仓库真实发生过） | 替换前**断言 `i >= 0`**；优先用编辑器工具；跨行匹配注意 `\r\n` |
| `git add -A` 扫进别人的改动 | 提交信息只写「个人信息页」，实际带了 10 个无关文件 | 只 `git add <具体路径>`；即使单智能体也建议如此 |
| 浏览器工具点登录/按钮 | `browser.click` 报 `UnknownVizError`；登录框没有 a11y ref | 在 `evaluate` 里用原生 `value` setter 赋值 + `element.click()`；`el-select` 要点 `.el-select__wrapper` 的 `mousedown`；下拉项在 portal 里（`.el-select-dropdown__item`）；Vue 重渲染后**元素引用会失效，每次重新查** |
| 截图失败 `Screenshot needs a visible tab` | 浏览器工具报错 | 先 `browser.tabs.focus`，且窗口要可见；拿不到就退回 DOM 断言，别卡住 |
| Vite 只监听 `localhost`（IPv6） | `127.0.0.1:5173` 连不上 | 统一用 `http://localhost:5173` |

---

## 11. 常见操作速查

| 想做什么 | 怎么做 |
|----------|--------|
| 起后端 / 前端 | §3.1 |
| 改了后端代码 | §3.2 重启 → 跑回归 |
| 跑全量回归 | `cd server-py; .\.venv\Scripts\python.exe tests\api_regression.py` |
| 前端检查 | `cd web; npm run type-check; npm run build` |
| 看版本真相源 | `server-py/app/version.py`（改版本只改那一行 + 同步 package.json） |
| 加新接口 | 过 §5.2 检查清单 → 回归补断言 → 必要时 bump MINOR |
| 改表结构 | `db/schema.sql` + `app/seed.py` 幂等 ALTER **两处都改** |
| 加纯院长可访问的接口 | 确认 `_PURE_DEAN_ALLOWED` 命中 + `test_a24` 列表点名 |
| 查「未返校」口径 | `web/src/utils/taskStatus.ts`（**唯一**） |
| 查回收进度口径 | `task_service.college_recovery()`（**唯一**） |
| 改任务导出 | `task_excel.export_detail` + `tasks.py` 的 POST 路由 + `TaskDetailDashboard.vue` |
| 清浏览器工具缓存 | 删仓库根 `.playwright-mcp/` |

---

## 12. 给下一个智能体的最后几句

1. **先把 `AGENTS.md` 的三件套跑一遍**，确认基线是绿的再动手。
2. **先读你要改的那个文件的注释**——这个项目的注释刻意写得很密，为什么这么选、踩过什么坑，大概率已经在里面。
3. **改口径类的东西（§6）之前，先全局搜一遍**：同一个概念往往在「后端 service + 前端 util + 导出 + 回归断言」四处出现，只改一处必然漂。
4. **单个智能体干活**。两个会话并行会把对方的 commit 用 `git reset` 冲掉（本仓库真实发生过三次，内容靠工作区幸存才没丢）。
5. 拿不准需求时**问用户**，别猜：这个用户的报障写得具体，但「应该怎样」只有他能拍板（例如 §9 的日期限制）。

---

## 13. 需求 → 实现对照（`docs/问题.md` 全量）

> 这张表的用途：**别重复劳动**。标「早已实现」的是核对过代码/接口确认能用的，不是猜的。

### 院长

| 问题 | 结论 | 落点 |
|---|---|---|
| 仪表盘·学籍变化不同步（卡片 `--`，分布却有数） | **早已实现**（v1.5.0 接上数据源） | `student_service` 的 `changeTotal` / `statusBreakdown` 同源；实测 `changeTotal=8`、`changeSupported=True` |
| 仪表盘·没有置顶任务（右下角空白） | **早已实现**（纯院长视图也渲染） | `dashboard/index.vue` 两处 `PinnedTasksPanel`；`GET /tasks/pinned` 纯院长走 `scope=COLLEGE & pinned=1`。**当前库里没有置顶任务，所以是空态，不是 bug** |
| 学院·学生名册 Delete / Ctrl+Z 没反应 | **早已实现** | `college/students/index.vue`：Delete 清格、Ctrl+Z 撤销、Ctrl+Y 重做（注释里就是这两条报障原话） |
| 学院·建院长账号时选「院长 + 班主任」 | **早已实现** | `user_service.create_dean`（`deanOnly` + `classIds`）+ `college/deans/index.vue` 单选/勾班 |
| 学院·像成员管理那样操作班主任 | **早已实现** | `college/advisers`：新增 / 导入 / 批量删除 / 改安排（`PUT /college/classes/{id}/teachers`） |
| 任务·发布时隐藏「多选」「日期」 | **早已实现** | `web/src/api/tasks.ts` 的 `TASK_QTYPES_PUBLISHABLE`（只有是/否 + 单选）；编辑老任务仍显示原题型 |
| 任务·班主任「填写答案 / 修改我的答案」没用 | **早已实现** | 学院任务 `canAnswer` 恒 `False` → 按钮不渲染；`canFill` 给「填写」按钮 |
| 任务·普通成员能看见学院任务 | **早已实现** | `task_service.can_see_college_tasks` + `_visible_task_query` + 前端 `canSeeCollege` |
| 任务·回收进度按班主任名册统计 | **本轮修** `caf4352` | `task_service.college_recovery()`，见 §7.3 |
| 任务·总览按班级筛选 / 班级任务显示发布人 | **早已实现** | `overview(db, user, class_id=…)`；`_build_rows` 的 `publisherName` |
| 个人信息·描述出错 / 改登录名 / 改密码 | **早已实现** | `957351c`；`PUT /auth/profile` + 右上头像菜单的改密码 |

### 班主任

| 问题 | 结论 | 落点 |
|---|---|---|
| 账本明细筛选时间报错（`日期格式应为 yyyy-MM-dd`） | **本轮修** `df4db3b` | `records/index.vue` 的 daterange 补 `value-format="YYYY-MM-DD"` |
| 起止日期能选到过去 | **本轮修** `df4db3b` | 同一处加 `:disabled-date="disablePastDates"`，见 §9 取舍 1 |
| 收入/支出登记没类别时一直「加载中」 | **本轮修** `df4db3b` | `RecordFormDrawer.vue`：`catsLoading` + `no-data-text="暂无类别，请添加"` + 空态提示 |
| 删缴费后成员缴费还留着缴费时间 | **本轮修** `f5147e5` | `record_service.delete_record/void_record` 清 `paid_at`；`serializers` 再兜一道 |
| 登记必须先手动建类别 | **本轮修** `f5147e5` | `category_service.ensure_default_categories()` + 启动时全量补齐 |
| 班级任务加「班级任务」筛选 | **本轮修** `0a58b2b` | `tasks/index.vue` 第三个页签（前端过滤，见 §7.5） |
| 代人登记可选上传小票 | **本轮修** `0a58b2b` | `BatchPayDialog.vue` + `BatchPayRequest.receiptUrl` + `batch_service.pay` |
| 改「我带的班」撞车文案 | **本轮修** `df463ea` | `_teacher_conflict_msg(hint="如需更换请联系院长")` |

---

## 14. 回归测试基建（要加断言时看这里）

- 单文件：`server-py/tests/api_regression.py`，**打真 HTTP**，不 mock。
- `ALL_TESTS` 是执行顺序表（50 个函数）；`test_a15_cleanup` **必须最后**。
- 常用 helper：

| helper | 用途 |
|---|---|
| `call(method, path, body=None, token=None)` | 发请求 → `(status, parsed)`；**连接层错误自动重试一次**（含 `HTTPError` 的 `e.read()`） |
| `data_of(j)` / `msg_of(j)` / `code_of(resp)` | 拆统一响应 `{code,message,data}` |
| `login(username, password=None)` | 拿 token |
| `_insert_dean_probe(name)` | 直写库造院长探针（API 建号会被护栏拦） |
| `_post_multipart(path, field, filename, content, token)` | 手拼 multipart；**后端按魔数嗅探图片**，所以传 PNG 字节时 content-type 头写 xlsx 也能过 `/files` |
| `_fixture_class(name)` / `_purge_fixture_class(name)` | 测试自建自删的班级夹具 |
| `_purge_user(username)` / `_purge_students_prefix(prefix)` | 清探针账号 / 学生 |
| `check(name, cond, detail)` | 断言（名称写中文，失败时能直接看懂） |

- **基线不变量**（跑完必须回到开跑时）：账号集合、批次条数、余额、完成率；每个用例结束后还有守卫检查 `test` 账号的班级关联没被改坏（`root_class_links()`）。
- **写新用例的套路**：`test_aNN_xxx()` → 加进 `ALL_TESTS` → 自己造数据自己清 → 断言用中文名。
- ⚠ **用例中途抛异常会跳过自己的清理**，留下脏数据让下一轮红一片（踩过：`回归新建班`、`dean_probe_xls`）。写完全量跑一遍确认能跑到 `RESULT:`。
- ⚠ **`ROOT_U/ROOT_P` 是硬编码的 `test` / `123456`**（文件第 37 行）：库里没有这个账号时脚本直接 `SystemExit("无法登录班主任账号")`。空库/清库后先确认 `.env` 的 `CLASSFEE_TEACHER_USERNAME/PASSWORD` 已配置**并注入了进程环境**再重启（§3.1），或手工建号。
- ⚠ **把某字段从「只读」改成「本人可改」时，先全局搜回归**：`test_a06` 有一条 `PUT /auth/profile {"username":"hijack"}` 断言「username 必须被忽略」——字段一旦可改，探针账号会被真改名，后续 54 条连锁 401。改行为前先 `grep` 断言里的旧口径。
- 中途失败的用例会留下夹具（`回归新建班`、`Z90夹具班`、`不存在的班`、`云计算2502` 等），它们会出现在班级下拉里；确认无用后手工清，别让它越滚越多。
- 前端也有「源码扫描」型断言可以照抄：`test_a22`（图表容器写法）、`test_a47`（每个 `<el-date-picker>` 必须有 `value-format`）。

---

## 15. 常用探测（判断「改动到底生效没有」）

```powershell
# 服务活着吗
Invoke-RestMethod http://127.0.0.1:8080/api/version

# 新字段 / 新路由有没有进内存（改完后端最常用，比重启日志可靠）
(Invoke-RestMethod http://127.0.0.1:8080/openapi.json).components.schemas.BatchPayRequest `
  .properties.PSObject.Properties.Name

# 登录拿 token
$lg = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8080/api/auth/login `
  -ContentType 'application/json' -Body (@{username='dean';password='123456'} | ConvertTo-Json)
$H = @{ Authorization = "Bearer $($lg.data.token)" }

# 院长视图：学籍变化 / 置顶任务
(Invoke-RestMethod "http://127.0.0.1:8080/api/dashboard/students?months=12" -Headers $H).data |
  Select-Object changeTotal, changeSupported
(Invoke-RestMethod "http://127.0.0.1:8080/api/tasks/pinned" -Headers $H).data.rows.Count

# 日期格式：前端该发的 vs 旧 bug 的
(Invoke-RestMethod "http://127.0.0.1:8080/api/records?start=2026-11-03&end=2026-12-09" -Headers $H).code
```

---

## 16. 本机环境与数据现状

- **表** 15 张；**启用班** 16 个；**在册学生** 约 100 名。
- **默认类别**：每个班 5 收入 + 6 支出（共 11 条），启动时按 kind 幂等补齐，用户改过的不动。
- **演示账号**：`dean`（纯院长）、`test`（班主任）；本地密码一般是 `123456`（以 `.env` / 种子配置为准）。
- **上传目录** `server-py/uploads/receipts/`（uuid 命名；删流水时回收未被引用的文件）。
- **前端没有常驻 dev server**：验证前先 `cd web; npm run dev`。
- 仓库根 `.playwright-mcp/`、临时 xlsx、截图都可能污染 `git status`，提交前看一眼。

---

## 17. 数据与隐私（动手前必读）

- **`docs/wenti/` 的 16 张截图是用户的真实报障图**，里面是**真实姓名 + 学号**，已经随仓库提交（用户明确要求保留，**别再删**）。仓库是 **public**。
- 因此：**不要再往仓库里加带真实姓名 / 学号 / 手机号的截图或导出文件**；`git add` 前先看 `git status`，别一把 `-A`。
- 本地 `C:\Users\29913\AppData\Local\Temp\opencode\dbclean\` 下有**清库前的全量备份**（含 423 名学生），**不要**挪进仓库目录，也不要提交。
- 数据库是真实数据：回归会自建自删并回到基线，但**不要手工 `DELETE` / `TRUNCATE`**；确实要清库，先问用户、先备份。
- 改任何「导出 / 下载」功能时，注意导出的默认列可能带姓名学号——新加字段先想一句「这列能不能出现在公开文件里」。

