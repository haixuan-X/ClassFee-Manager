/** 后端统一响应体：{ code, message, data } */
export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T
}

/** 角色 */
export type Role = 'ADMIN' | 'MEMBER' | 'GUEST' | 'MONITOR' | 'TEACHER' | 'DEAN'

/** 当前用户信息（后端 UserVO） */
export interface UserInfo {
  id: number
  username: string
  realName: string
  role: Role
  /**
   * 访客的可见范围（第二十六轮），非访客为 `null`。
   * 侧栏和路由守卫都按它过滤——但它只是**入口**层面的过滤，
   * 真正的边界在后端（`security` 中间件），手输 URL 也绕不过去。
   */
  guestScopes?: GuestScope[] | null
  classId: number
  className: string | null
}

/** 登录返回 */
export interface LoginResult {
  token: string
  user: UserInfo
}

/** 登录入参 */
export interface LoginRequest {
  username: string
  password: string
}

/** 修改密码入参 */
export interface PasswordRequest {
  oldPassword: string
  newPassword: string
}

/** 校验错误项（后端 400 时 data 为该数组） */
export interface FieldError {
  field: string
  message: string
}

/* ============================ M2 记账 ============================ */

/** 收支类型 */
export type RecordType = 'INCOME' | 'EXPENSE'

/** NORMAL 正常 / VOID 已作废（红冲） */
export type RecordStatus = 'NORMAL' | 'VOID'

/** 支付方式 */
export type Channel = 'CASH' | 'WECHAT' | 'ALIPAY' | 'BANK' | 'OTHER'

export const TYPE_TEXT: Record<RecordType, string> = {
  INCOME: '收入',
  EXPENSE: '支出',
}

export const CHANNEL_TEXT: Record<Channel, string> = {
  CASH: '现金',
  WECHAT: '微信',
  ALIPAY: '支付宝',
  BANK: '银行卡',
  OTHER: '其他',
}

export const STATUS_TEXT: Record<RecordStatus, string> = {
  NORMAL: '正常',
  VOID: '已作废',
}

/** 收支类别（后端 FeeCategory） */
export interface Category {
  id: number
  classId: number
  name: string
  kind: RecordType
  icon: string | null
  sort: number
  status: number
}

/** 新增流水入参 */
export interface RecordRequest {
  type: RecordType
  categoryId: number
  amount: number
  title: string
  /** yyyy-MM-dd HH:mm:ss */
  occurredAt: string
  channel?: Channel
  remark?: string
  /** 小票图片相对路径（POST /api/files 上传返回；仅支出流水可传） */
  receiptUrl?: string
}

/** 流水（后端 RecordVO，amount 为两位小数） */
export interface FeeRecord {
  id: number
  type: RecordType
  categoryId: number
  categoryName: string | null
  amount: number
  title: string
  occurredAt: string
  channel: Channel
  remark: string | null
  /** 小票图片相对路径，null=未上传 */
  receiptUrl: string | null
  status: RecordStatus
  createdBy: number
  createdByName: string | null
  createdAt: string
  /** 第十九轮审计：作废留痕（谁、何时）。删除是硬删无痕，所以「作废」是可追的唯一路径 */
  voidedBy: number | null
  voidedByName: string | null
  voidedAt: string | null
}

/** 流水查询条件 */
export interface RecordQuery {
  page: number
  size: number
  /** 精确查某条流水（批次明细「查看流水」跳转用，只生效一次） */
  id?: number
  type?: RecordType
  categoryId?: number
  keyword?: string
  status?: RecordStatus
  /** yyyy-MM-dd */
  start?: string
  end?: string
}

/** 后端 PageResult */
export interface PageInfo<T> {
  records: T[]
  total: number
  page: number
  size: number
}

/** 仪表盘汇总 */
export interface DashboardSummary {
  balance: number
  realBalance: number
  monthIncome: number
  monthExpense: number
  monthCount: number
  /** 最新收费批次完成率 0-100；还没有批次时为 null */
  completionRate: number | null
  latestRecords: FeeRecord[]
}

/**
 * 仪表盘「学生情况总览」的聚合数据（后端 `student_service.dashboard_stats`）。
 *
 * ⚠ 全部字段都**受可见范围限制**：普通同学默认只看得到自己那一行，
 * 所以 `studentTotal` 可能是 1 而不是全班人数。这是**有意**的：
 * 人数本身也是信息，仪表盘不该成为绕过学生信息权限的后门。
 * 界面必须靠 `canViewAll` 决定怎么措辞。
 */
export interface StudentDashboard {
  /** false = 只统计到「你有权看的那几行」，数字不代表全班 */
  canViewAll: boolean
  /** 班级年级，来自 `cls_class.grade`；没填时为空串 */
  classGrade: string
  /** 可见范围内的学生记录数 */
  studentTotal: number
  /** 其中「在籍」的人数（休学/退学/毕业等不计入，空值算在籍） */
  registeredTotal: number
  /** 注册状态分布，按人数降序；未填写归到「未填写」一项 */
  statusBreakdown: { status: string; count: number }[]
  /** 按入校月份的新增与累计人数——**唯一有真实时间轴的序列** */
  enrollTrend: { ym: string; added: number; cumulative: number }[]
  months: number
  /** 最近有改动的学生行 */
  latest: {
    id: number
    studentNo: string
    name: string
    updatedAt: string | null
    regStatus: string | null
    grade: string | null
    majorName: string | null
    enrollDate: string | null
    registered: boolean
  }[]
  /**
   * 学籍异动人次。**目前恒为 `null`**——库里没有异动表、没有历史快照，
   * 画一条全零折线会被读成「本年零异动」，那是撒谎。`null` 才如实表达
   * 「这个功能还没有数据源」。配套的 `changeSupported` 让界面能显式
   * 说明原因，而不是画个空图。
   */
  changeTotal: number | null
  changeSupported: boolean
}

/** 月度趋势点 */
export interface TrendPoint {
  ym: string
  income: number
  expense: number
}

/** 支出分类占比项 */
export interface PieItem {
  name: string
  value: number
}

/**
 * 角色中文名：普通成员(只读) / 访客(只读·给领导看) / 生活委员 / 班长 / 班主任 / 院长
 * （后四者为运营角色 `STAFF_ROLES`；院长是系统管理员，等级最高）。
 *
 * ⚠ 必须与后端 `security.ROLE_LEVEL` 的键**完全一致**：多一个少一个，
 * 界面上就会出现「后端认识但前端显示 undefined」的角色名。
 */
export const ROLE_TEXT: Record<Role, string> = {
  ADMIN: '生活委员',
  MEMBER: '普通成员',
  GUEST: '访客',
  MONITOR: '班长',
  TEACHER: '班主任',
  DEAN: '院长',
}

/**
 * 运营角色（与后端 `security.STAFF_ROLES` 同口径）。
 *
 * ⚠ 这份列表在**三个地方**都要用：侧栏入口过滤、路由 `meta.roles`、成员管理
 * 的操作按钮。原先它们各写一份字面量，于是加「院长」时只改一处就会出问题——
 * 实测过的两种表现：① 侧栏少了 5 个入口；② `/member-manage` 被路由守卫弹回
 * 仪表盘（页面看着像坏了，其实只是没授权）。
 * 收成一份共享常量后，「加角色漏改」最多只剩「忘了往这个常量里加」一处。
 *
 * 回归里有断言盯着它与后端一致（`test_a20_dean_role`）。
 */
export const STAFF_ROLES: Role[] = ['ADMIN', 'MONITOR', 'TEACHER', 'DEAN']

/* ============================ M4 班级信息 ============================ */

/* 第二十四轮：班级公告已整体移除，`Notice` / `NoticeRequest` / `NoticeQuery`
   三个类型连同页面、路由、侧栏入口、后端接口与 sys_notice 表一并删掉。
   `DashboardSummary.pinnedNotices` 也已从摘要里去掉。 */

/** 班级信息（balance 是流水事务同步的冗余列，只读） */
export interface ClassInfo {
  id: number
  className: string
  grade: string | null
  headTeacher: string | null
  balance: number
  status: number
}

/** 班级信息入参：className 必填；grade/headTeacher 空串=清空 */
export interface ClassInfoRequest {
  className: string
  grade?: string
  headTeacher?: string
}

/* ============================ M3 收费批次 ============================ */

/** 批次状态：进行中 / 已关闭 */
export type BatchStatus = 'OPEN' | 'CLOSED'

/** 缴费状态：未缴 / 已缴 / 已退款 */
export type PayStatus = 'UNPAID' | 'PAID' | 'REFUNDED'

export const BATCH_STATUS_TEXT: Record<BatchStatus, string> = {
  OPEN: '进行中',
  CLOSED: '已关闭',
}

export const PAY_STATUS_TEXT: Record<PayStatus, string> = {
  UNPAID: '未缴费',
  PAID: '已缴费',
  REFUNDED: '已退款',
}

/** 收费批次（后端 BatchVO，rate 为 0-100 百分比） */
export interface Batch {
  id: number
  name: string
  /** 每人应收 */
  amount: number
  /** yyyy-MM-dd */
  deadline: string | null
  remark: string | null
  status: BatchStatus
  createdAt: string
  /** 创建人 id：第十七轮归属权（A 方案）——关闭/删除只对创建人开放 */
  createdBy: number
  /** 创建人姓名（可为 null：账号已被删除） */
  createdByName: string | null
  /** 第十九轮审计：关闭留痕（谁、何时关的）。删除是硬删无痕 */
  closedBy: number | null
  closedByName: string | null
  closedAt: string | null
  /** 应缴人数 */
  total: number
  paidCount: number
  unpaidCount: number
  rate: number
}

/**
 * 第十八轮：普通成员视角的批次（「我的缴费」页）。
 *
 * 与 `Batch` 的差别：不含 `createdBy`（内部字段），多了**自己**的缴费状态。
 * 缴费名单（`PaymentRow` / `MemberRow`）对普通成员仍然不可见。
 */
export interface MyBatch {
  id: number
  name: string
  amount: number
  /** yyyy-MM-dd */
  deadline: string | null
  status: BatchStatus
  total: number
  paidCount: number
  unpaidCount: number
  /** null = 不在这个批次的缴费名单里（通常���建批次之后才入班） */
  myStatus: PayStatus | null
  myAmount: number | null
  myPaidAt: string | null
  /** 流水被作废、缴费状态退回未缴，等人重新登记 */
  myAmountDue: boolean
}

/** 新建批次入参 */
export interface BatchRequest {
  name: string
  amount: number
  /** yyyy-MM-dd */
  deadline?: string
  remark?: string
}

/** 标记缴费入参（金额/时间/方式缺省时后端取批次默认值） */
export interface PayRequest {
  userId: number
  amount?: number
  channel?: Channel
  occurredAt?: string
  remark?: string
}

/** 批次明细行 */
export interface PaymentRow {
  id: number
  userId: number
  realName: string | null
  studentNo: string | null
  role: Role | null
  status: PayStatus
  amount: number
  channel: Channel | null
  paidAt: string | null
  recordId: number | null
  remark: string | null
}

/** 批次详情 */
export interface BatchDetail {
  batch: Batch
  payments: PaymentRow[]
}

/** 成员缴费列表行（后端 MemberVO） */
export interface MemberRow {
  userId: number
  username: string
  realName: string
  studentNo: string | null
  role: Role
  status: number
  /** 当前查看批次；无批次时为 null */
  batchId: number | null
  /** 无批次时为 null */
  payStatus: PayStatus | null
  amount: number | null
  channel: Channel | null
  paidAt: string | null
  recordId: number | null
}

/** 成员查询条件 */
export interface MemberQuery {
  keyword?: string
  payStatus?: PayStatus
  batchId?: number
}

/* ============================ 第十五轮 个人信息（本人自助） ============================ */

/**
 * 修改本人资料入参（`PUT /api/auth/profile`）。
 *
 * 只有这三类字段：角色、启用状态、登录名、班级**都不在范围内**
 * （分别只能由运营走 `/users/{id}`、改密走 `/auth/password`）。
 * 请求体不接受 id —— 改谁由登录令牌决定。
 */
export interface ProfileUpdateRequest {
  /** 姓名（传了就不能为空） */
  realName?: string
  /** 学号（空串=清空、不传=不改，同班唯一） */
  studentNo?: string
  /** 手机号（空串=清空、不传=不改） */
  phone?: string
}

/**
 * 个人信息页展示的账号详情。
 *
 * 直接复用 `UserAccount`（含学号/手机号/状态/时间戳）——不另立类型，
 * 避免同一份数据在两处各写一遍字段。`/auth/me` 不返回学号与手机号，
 * 需要这两项时由页面读 `GET /api/users` 里的自己那一行。
 */
export type MyProfile = UserAccount

/* ============================ 语义化版本 ============================ */

/**
 * `GET /api/version` 的返回（第二十七轮）。
 *
 * **唯一真相源在后端** `server-py/app/version.py` 的 `VERSION` 常量，
 * 前端只是把它显示出来——不要在前端另写一份版本号，两处手写迟早漂。
 *
 * `web/package.json` 的 `version` 同步改，但只作为**漂移检测的锚**：
 * 回归里有一条断言盯着它和后端一致（`test_a19_version`）。
 *
 * 字段与后端 `version_info()` 逐一对应。
 */
export interface AppVersion {
  /** 应用名。与版本号一起显示——光一个 "1.1.0" 看不出是什么的版本 */
  appName: string
  /** 完整版本号，形如 `1.1.0` / `1.2.0-rc.1` */
  version: string
  major: number
  minor: number
  patch: number
  /** 预发布标记（`1.2.0-rc.1` 里的 `rc.1`）；正式版为 null */
  preRelease: string | null
  /** 构建后缀（`1.2.0+20261019` 里的日期）；一般没用 */
  build: string | null
}

/* ============================ 第七轮 账号管理（老师建班） ============================ */

/** 账号（后端 GET/POST /api/users 行；含停用账号） */
/**
 * 访客的可见范围（第二十六轮）。**只有访客用得上**，其他角色一律 `null`。
 *
 * 与后端 `security.GUEST_SCOPE_KEYS` 一一对应，改一处必须同时改另一处。
 * 这四项就是访客本来就能进的全部页面；「个人信息」不在其中——
 * 他自己的账号，没什么可限制的。
 *
 * ⚠ 这里是**范围**，不是**页面**：一个范围可能盖住不止一条接口。
 * 「账本明细」除了流水和缴费，还管收费批次（`/api/batches`）——那里面有
 * 金额和截止时间，是账目信息，所以第二十六轮把它从 `_STAFF_ROUTES` 挪进来。
 */
export type GuestScope = 'DASHBOARD' | 'RECORDS' | 'STUDENTS' | 'TASKS'

/** 范围项的中文名与说明。与后端 `GUEST_SCOPE_LABELS` 保持一致。 */
export const GUEST_SCOPE_OPTIONS: { value: GuestScope; label: string; hint: string }[] = [
  { value: 'DASHBOARD', label: '仪表盘', hint: '班级余额、收支趋势和最新流水' },
  {
    value: 'RECORDS',
    label: '账本明细',
    hint: '全部记账流水、缴费记录，以及收费批次（要收多少钱、什么时候截止）',
  },
  { value: 'STUDENTS', label: '学生信息', hint: '全班学生的登记信息，可勾选导出' },
  { value: 'TASKS', label: '班级任务', hint: '任务题目和填写情况（只有汇总，不含谁填了什么）' },
]

export interface UserAccount {
  id: number
  username: string
  realName: string
  studentNo: string | null
  phone: string | null
  role: Role
  /**
   * 访客能看的页面范围。非访客恒为 `null`。
   * **不传 / 传空数组 = 全部可见**（后端 `dump_guest_scopes` 归一成 NULL），
   * 这样第二十四轮那批访客账号不需要任何数据迁移，行为保持原样。
   */
  guestScopes?: GuestScope[] | null
  classId: number
  /** 1 启用 / 0 停用 */
  status: number
  /** yyyy-MM-dd HH:mm:ss */
  lastLoginAt: string | null
  createdAt: string | null
}

/** 新建账号入参（password 缺省 123456；role 缺省 MEMBER；studentNo 留空默认取登录名） */
export interface UserCreateRequest {
  username: string
  realName: string
  /** 学号（可与登录名不同，同班唯一，≤20 字） */
  studentNo?: string
  password?: string
  phone?: string
  role?: Role
  /**
   * 访客的可见范围（第二十六轮）。**只有 `role='GUEST'` 时有意义**，
   * 其他角色传了会被后端忽略。
   *
   * 勾选框的状态就是真实权限：四项全传 = 全部可见，**传 `[]` = 一个页面都进不去**
   * （只剩自己的「个人信息」）。不传 = 全部可见。
   */
  guestScopes?: GuestScope[]
}

/** 编辑账号入参（字段均可选；password=重置密码；phone/studentNo 传空串=清空） */
export interface UserUpdateRequest {
  realName?: string
  /** 学号（空串=清空、不传=不改，同班唯一） */
  studentNo?: string
  phone?: string
  status?: 0 | 1
  password?: string
  /**
   * 访客的可见范围。第二十六轮：传了就改、**不传=不改**。
   * 传 `[]` = 什么都看不到；四项全传 = 全部可见。
   * 改完**立刻生效**，访客不用重新登录（后端中间件每个请求都重读这一列）。
   */
  guestScopes?: GuestScope[]
}

// ==================== 第二十三轮：学生信息 ====================

/** 字段类型：决定录入控件与导出时的格式化方式 */
export type StudentFieldType = 'TEXT' | 'NUMBER' | 'DATE' | 'BOOL'

/**
 * 申请/授权的三种范围。
 *
 * - `EDIT_OWN`：能改**自己那一行**（不含看别人）
 * - `VIEW_ALL`：能看所有人的行（不含改）
 * - `EDIT_ALL`：能改所有人的行，**蕴含** `VIEW_ALL`
 */
export type StudentScope = 'EDIT_OWN' | 'VIEW_ALL' | 'EDIT_ALL'

/** 学生信息字段定义（一列 = 一条） */
export interface StudentField {
  id: number
  /** 机器名，稳定不变；改显示名不影响历史数据 */
  key: string
  /** 表头显示名 */
  label: string
  type: StudentFieldType
  typeText: string
  /** 模板预置字段。**照样可以停用**（停用是软删，可恢复） */
  isSystem: boolean
  sort: number
  /** 1=启用 0=已停用。只有 `includeDisabled=true` 的列表里才会出现 0 */
  status?: number
  /** 当前角色不能改这个字段（如生活委员没有字段管理权） */
  locked: boolean
}

/**
 * 改字段类型前的预览结果（后端算的，不写库）。
 *
 * 之所以要预览这一步：改类型要同步转换已填的值，而有的值转不了
 * （"待定"没法变日期）。不先摊开这笔账就改，等于静默毁数据。
 */
export interface StudentRetypePreview {
  key: string
  label: string
  fromType: StudentFieldType
  fromTypeText: string
  toType: StudentFieldType
  toTypeText: string
  /** 这一列一共多少个值（含空的） */
  total: number
  /** 能转换的个数（会被改写成新格式） */
  convertibleCount: number
  convertibleSamples: { before: string; after: string }[]
  /** 样本之外的还有多少条 */
  convertibleTruncated: number
  /** 转不了的个数（「待定」这种） */
  unconvertibleCount: number
  unconvertibleSamples: { before: string }[]
  unconvertibleTruncated: number
  /** 空值（未填），不用管 */
  emptyCount: number
}

/** 改类型的结果 */
export interface StudentRetypeResult {
  key: string
  label: string
  fromType: StudentFieldType
  toType: StudentFieldType
  convertedCount: number
  /** 转不了但保留原样的个数（`clearUnconvertible=false` 时） */
  keptUnconvertibleCount: number
  /** 被清空的个数（`clearUnconvertible=true` 时） */
  clearedCount: number
}

/** 表格一列的展示配置：前两列是锚点（学号/姓名），其余来自字段定义 */
export interface StudentColumn {
  key: string
  label: string
  type: StudentFieldType
  system: boolean
  writable: boolean
}

/** 一行学生数据 */
export interface StudentRow {
  id: number
  studentNo: string
  name: string
  /** 是否是自己那一行 */
  isMine: boolean
  /** 当前角色能否编辑这一行 */
  editable: boolean
  linkedUserId: number | null
  /** 字段标识 → 值 */
  values: Record<string, string | null>
}

/**
 * 权限快照。
 *
 * 后端已按可见范围裁剪过行，前端只是据此决定「锁图标 / 申请按钮」的显隐——
 * **真正的闸门在后端**，这里拿到 false 也只是界面不给出入口。
 */
export interface StudentPermission {
  scopes: StudentScope[]
  isTeacher: boolean
  /** 访客（领导）：能看全部、只能看，主用途是勾选导出 */
  isGuest?: boolean
  canViewAll: boolean
  canEditAll: boolean
  canEditOwn: boolean
  /** 班主任 / 班长可加字段 */
  canAddField: boolean
  myRecordId: number | null
  myStudentNo: string | null
  /** 账号没填学号 → 匹配不到自己那行，提示去「个人信息」补 */
  accountHasNoStudentNo: boolean
  /** 班级一条记录都还没有 → 提示找班主任导入 */
  classHasNoRecords: boolean
}

export interface StudentSheet {
  columns: StudentColumn[]
  rows: StudentRow[]
  permission: StudentPermission
}

/** 新增/修改字段 */
export interface StudentFieldRequest {
  key?: string
  label?: string
  type?: StudentFieldType
  sort?: number
}

/**
 * 「按学生信息一键建账号」的结果（`GET .../preview` 与 `POST .../accounts` 共用）。
 *
 * 预演和执行**同一个形状**：唯一区别是 `executed`。
 * 用户口径：一次建全部可建的、密码统一 123456、已有账号顺便挂接、仅班主任。
 */
export interface StudentAccountPlan {
  /** false = 预演（什么都没写）；true = 真建过了 */
  executed: boolean
  /** 一共多少行学生记录 */
  total: number
  /** 将/已新建的账号数 */
  toCreate: number
  /** 将/已挂接到已有账号的行数 */
  toLink: number
  /** 将/已跳过的行数 */
  toSkip: number
  /**
   * 将要建的那些（预演时就有）。
   * 只给个数字的话老师没法在点之前核对「到底是哪几个」；有这个列表，
   * 「预演说建哪些、执行就建哪些」也才可被验证。
   */
  toCreateList: { studentNo: string; name: string }[]
  /** `executed=true` 时才有内容：新建出来的账号 */
  created: { id: number; username: string; realName: string }[]
  /** 挂接详情。`backfilled` = 顺手把这个账号空着的学号补上了 */
  linked: {
    userId: number
    studentNo: string
    name: string
    username: string
    backfilled: boolean
  }[]
  /** 跳过的行 + **具体原因**（不给原因的话用户没法处理） */
  skipped: { studentNo: string; name: string; reason: string }[]
  /** 初始密码，界面上要原样告诉班主任（否则学生登不进去） */
  initialPassword: string
}

export type StudentRequestStatus = 'PENDING' | 'APPROVED' | 'REJECTED'

/** 一条访问申请（我提交的 / 收件箱里的，同一结构） */
export interface StudentAccessRequest {
  id: number
  scope: StudentScope
  scopeText: string
  status: StudentRequestStatus
  reason: string | null
  reply: string | null
  createdAt: string | null
  handledAt: string | null
  /** 收件箱专用：申请人 */
  userId?: number
  userName?: string
  role?: Role
}

/** 一条已生效的授权 */
export interface StudentGrant {
  id: number
  userId: number
  userName: string
  role: Role
  scope: StudentScope
  scopeText: string
  grantedByName: string
  grantedAt: string | null
}

/** 导入结果 */
export interface StudentImportResult {
  created: number
  updated: number
  rows: number
  skippedEmptyCells: number
  /** 本次导入**自动新建**的字段（表格里有、系统里还没有的列） */
  newFields: { label: string; type: string; typeText: string }[]
  /** 表内学号重复的行数（后一行覆盖前一行，不中止导入） */
  duplicateRows: number
  /** 有字段权限的人导入后这里恒为空；留着是为了无权限者导入时能看到"哪些列没进去" */
  unmatchedColumns: string[]
  errors: string[]
  errorCount: number
}

/* ==================== 第二十五轮：班级任务 ==================== */
/**
 * 任务和被删掉的班级公告的**唯一区别**：任务发出去之后还要有人回来填答案。
 * 因此这一组类型里最要紧的是**可见性三态**——canSeeDetail（谁填了什么）、
 * canAnswer（我能不能填）、summary（只有分布、没有具体是谁）。
 */

/** 四种题型。与后端 	ask_service.QTYPES 一一对应，改一处必须同时改另一处 */
export type TaskQType = 'BOOLEAN' | 'SINGLE' | 'MULTI' | 'DATE'

/** 汇总：**只给分布，不含具体是谁**——这是用户明确要的口径 */
export interface TaskSummary {
  /** 应答对象总数（全部启用账号减去发布人自己） */
  total: number
  answered: number
  unanswered: number
  /** BOOLEAN/SINGLE/MULTI 才有；DATE 为空数组 */
  options: { label: string; count: number }[]
}

/** 我提交的那一条回答 */
export interface TaskAnswer {
  /** 存进库里时的原始值（BOOLEAN 是 true/false，MULTI 是 JSON 数组字符串） */
  value: string
  raw: string
  note: string | null
  submittedAt: string | null
}

/** 任务列表里的一条 */
export interface Task {
  id: number
  title: string
  question: string
  qtype: TaskQType
  qtypeText: string
  /** SINGLE/MULTI 的候选项；BOOLEAN/DATE 为空数组 */
  options: string[]
  /** 答完能不能再补一段文字说明 */
  allowText: boolean
  deadline: string | null
  /** 是否还在收答案（status 开关 + deadline 时间闸门，两个都过才算开） */
  open: boolean
  canAnswer: boolean
  createdBy: number
  /** 是不是我发的 */
  isMine: boolean
  /** 能不能看「谁填了什么」——只有发布人和班主任为 true */
  canSeeDetail: boolean
  /** 能不能改/关/删这条任务——只有发布人自己为 true */
  canEdit: boolean
  /** 是否置顶：置顶的、还在开放的任务会出现在所有人仪表盘的「置顶任务」里 */
  pinned: boolean
  createdAt: string | null
  myAnswer: TaskAnswer | null
  summary: TaskSummary
}

export interface TaskListPayload {
  rows: Task[]
  /** 我能不能发任务（TEACHER / MONITOR） */
  canPublish: boolean
}

/**
 * 仪表盘「置顶任务」面板的数据（`GET /api/tasks/pinned`）。
 *
 * 和任务列表**同一个 `Task` 类型**、同一套可见性口径（后端都走 `_build_rows`）：
 * 访客看得到置顶任务，但拿不到「我的答案」、`canAnswer` 恒为 false，
 * 明细在这里根本不存在。
 *
 * 只含**置顶且还在开放**的，最多 3 条，快到期的排前面。
 */
export interface TaskPinnedPayload {
  rows: Task[]
}

/** 明细里的一行：一个人在这条任务上的回答状态 */
export interface TaskDetailRow {
  userId: number
  name: string
  username: string
  role: Role
  answered: boolean
  value: string | null
  raw: string | null
  note: string | null
  submittedAt: string | null
}

/** 明细。**非发布人 / 非班主任拿不到**（后端 403） */
export interface TaskDetail {
  taskId: number
  title: string
  question: string
  qtype: TaskQType
  qtypeText: string
  allowText: boolean
  deadline: string | null
  open: boolean
  /** 未填的人排在前面（后端已排序） */
  rows: TaskDetailRow[]
  answered: number
  unanswered: number
  noteCount: number
  summary: TaskSummary
}

/**
 * 发布任务的入参。
 * qtype 决定 options 要不要给：BOOLEAN / DATE 忽略它，
 * SINGLE / MULTI 必填且至少 2 项（后端校验）。
 */
export interface TaskCreatePayload {
  title: string
  question: string
  qtype: TaskQType
  options?: string[]
  allowText?: boolean
  /** YYYY-MM-DDTHH:mm:ss；不填=不限 */
  deadline?: string | null
}

/**
 * 改任务的入参。
 * **刻意没有 qtype 和 options** —— 换题型会让已收回的答案对不上题，
 * 要换只能删了重发（与后端 TaskUpdateRequest 保持一致）。
 */
export interface TaskUpdatePayload {
  title: string
  question: string
  deadline?: string | null
  status?: number
  allowText?: boolean
}
