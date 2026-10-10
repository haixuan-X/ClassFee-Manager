/** 后端统一响应体：{ code, message, data } */
export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T
}

/** 角色 */
export type Role = 'ADMIN' | 'MEMBER' | 'GUEST' | 'MONITOR' | 'TEACHER'

/** 当前用户信息（后端 UserVO） */
export interface UserInfo {
  id: number
  username: string
  realName: string
  role: Role
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

/** 角色中文名：普通成员(只读) / 访客(只读·给领导看) / 生活委员 / 班长 / 班主任（后三者为运营角色） */
export const ROLE_TEXT: Record<Role, string> = {
  ADMIN: '生活委员',
  MEMBER: '普通成员',
  GUEST: '访客',
  MONITOR: '班长',
  TEACHER: '班主任',
}

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

/* ============================ 第七轮 账号管理（老师建班） ============================ */

/** 账号（后端 GET/POST /api/users 行；含停用账号） */
export interface UserAccount {
  id: number
  username: string
  realName: string
  studentNo: string | null
  phone: string | null
  role: Role
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
}

/** 编辑账号入参（字段均可选；password=重置密码；phone/studentNo 传空串=清空） */
export interface UserUpdateRequest {
  realName?: string
  /** 学号（空串=清空、不传=不改，同班唯一） */
  studentNo?: string
  phone?: string
  status?: 0 | 1
  password?: string
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
