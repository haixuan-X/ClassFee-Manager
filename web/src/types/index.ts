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
  /**
   * 是不是**纯院长**（第三十轮）。只有院长会有 true。
   *
   * 院长有两种：① 兼班主任（本班的账目、任务、成员他都管）；
   * ② 纯院长（只管学院那一层，班级事务一概不参与）。
   *
   * 纯院长的侧栏**不出现**「账目」和「班级」两组，仪表盘也只有
   * 「学生情况总览」——但那只是**入口**层面的过滤，
   * 真正的边界在后端（`security` 中间件的纯院长白名单），手输 URL 也绕不过去。
   */
  deanOnly?: boolean
  classId: number
  className: string | null
  /**
   * 这个人**能管哪些班**（第三十二轮）。
   *
   * 一个班主任常带好几个班（云计算2502 + 云计算2501）。侧栏顶上据此
   * 渲染「班级切换器」，切换后所有请求都带上 `classId`。
   */
  classIds?: number[]
  /** 与 `classIds` 一一对应的班级名 */
  classNames?: string[]
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
  /** 班级年级，来自 `cls_class.grade`；没填时为空串。学院口径下为空串 */
  classGrade: string
  /** 统计范围里的班级数 */
  classCount: number
  /**
   * true = **全校口径**（院长的看板统计所有启用班）。
   *
   * 这个总览只有院长能看，看板的身份是「校级看板」——给院长看
   * 「我这一班」的学生情况，等于把班级的学生信息表换个皮摆给他。
   */
  collegeScope: boolean
  /** 可见范围内的学生记录数 */
  studentTotal: number
  /** 其中「在籍」的人数（毕业/入伍/休学/退学等不计入，空值算在籍） */
  registeredTotal: number
  /**
   * 学籍状态分布，按**固定顺序**排：在籍 / 毕业 / 入伍 / 休学 / 退学 /
   * 其他 / 未填写（只给有人的那几档）。不按人数排序——每次打开都该在
   * 同一个位置，才找得到。
   *
   * 原始文本是自由填写的，后端按关键词**归类**：`已毕业`→毕业、
   * `参军入伍`→入伍、`在藉`（错字）→其他。归类之外的写法留在 `samples` 里。
   */
  statusBreakdown: {
    /** 归类后的档位名 */
    status: string
    count: number
    /** 这一档算不算「在籍」（在籍、未填写算；毕业/入伍/休学/退学/其他不算） */
    registered: boolean
    /** 这一档下出现过的原始写法（最多 3 种），只对「写法不等于档名」的有值 */
    samples: string[]
  }[]
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
    /** 归类后的档位名（配色/分组用；展示仍用 `regStatus` 原文） */
    regStatusCanon: string
    grade: string | null
    majorName: string | null
    enrollDate: string | null
    registered: boolean
    /** 学院口径下这一行是哪个班的 */
    className?: string
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

/**
 * 角色等级（与后端 `security.ROLE_LEVEL` 同口径）。
 *
 * 第二十九轮从 `member-manage/index.vue` 提到这里：仪表盘也要判「是不是院长」，
 * 而**两张手写等级表必然漂**——加角色时只改一边，界面上就会出现
 * 「成员管理里能管、仪表盘里看不见」这种自相矛盾。收成唯一一份之后，
 * 回归只需盯住它和后端一致（`test_a20_dean_role`）。
 *
 * ⚠ 权限判断一律用 `roleLevel()` 比较，**不要写 `role === 'DEAN'`**：
 * 写死角色名等于把「院长之上再加一档」这件事变成一次静默降权，
 * 症状是「新角色登录后该看的东西全看不见」，且不报错。
 */
export const ROLE_LEVEL: Record<Role, number> = {
  MEMBER: 0,
  GUEST: 0, // 访客（只读，给领导看）
  ADMIN: 1, // 生活委员
  MONITOR: 2, // 班长
  TEACHER: 3, // 班主任
  DEAN: 4, // 院长（系统管理员，等级最高）
}

/** 取等级；未知角色按最低档处理（**不抛错**，界面降级总比白屏好）。 */
export function roleLevel(role: Role | null | undefined): number {
  return role ? (ROLE_LEVEL[role] ?? 0) : 0
}

/** 「班主任及以上」= 够格管理访客 / 建访客 / 按学生建号的最低档。 */
export const TEACHER_MIN_LEVEL = ROLE_LEVEL.TEACHER

/** 「院长及以上」= 管理级看板（如仪表盘的「学生情况总览」）的最低档。 */
export const DEAN_MIN_LEVEL = ROLE_LEVEL.DEAN

/* ============================ 学院（第三十轮） ============================ */

/**
 * 学院 = **全部班级**的聚合视图，**仅院长可见**。
 *
 * 库里没有「学院」这一层（数据模型是 class → 学生/账号/任务/字段），
 * 学院视角就是院长的权限范围。见 `server-py/app/services/college_service.py`。
 */

/** 学院筛选用的班级选项 */
export interface CollegeClassChoice {
  id: number
  className: string
  grade: string
  /** 这个班有几个人（0 = 名单还没导进去） */
  students: number
}

/** 学生名册的一列。`key` 是字段机器名，跨班一致 */
export interface CollegeStudentColumn {
  key: string
  label: string
  type: 'TEXT' | 'NUMBER' | 'DATE' | 'BOOL'
  system: boolean
  /** 该列存在于多少个班（仅「已停用列」面板返回） */
  classCount?: number
}

/** 学院名册的一行：跨班级的同一个学生 */
export interface CollegeStudentRow {
  id: number
  classId: number
  className: string
  grade: string
  studentNo: string
  name: string
  values: Record<string, string | null>
}

/** 学院学生名册（含搜索筛选所需的选项） */
export interface CollegeStudentList {
  columns: CollegeStudentColumn[]
  /**
   * 筛选结果里**至少有一行有值**的字段 key。
   *
   * 只显示这些列——模板有 34 个字段，全摆出来是一屏空格子。
   * ⚠ 按**整个筛选结果**算，不是当前页，所以翻页时列不会增减。
   */
  populatedKeys: string[]
  rows: CollegeStudentRow[]
  total: number
  page: number
  size: number
  classes: CollegeClassChoice[]
  grades: string[]
}

/** 班主任账号 */
export interface CollegeTeacher {
  id: number
  username: string
  realName: string
  phone: string
  /** 1=启用 0=停用 */
  status: number
  lastLoginAt: string | null
}

/**
 * 名册的一行 = **一个班主任账号**。
 *
 * ⚠ 不是「一班一行」：有的班有**两个**班主任（班主任本人 + 兼班主任的院长）。
 * 一班一行就得把两个账号塞进一格，「账号状态」那列只能渲染两个「启用」，
 * 看不出哪个配哪个；手机号、最近登录这类属于某个账号的属性也只能取第一个
 * ——第二个人的手机号就永远不显示。
 *
 * 一人一行：每行一个账号、一个状态、一个手机号。一个班有几个人就占几行
 * （班级那列重复），这是名册的正常样子。
 *
 * 还没建班主任账号的班**也占一行**（`teacherId` 为 null）——
 * 「哪个班还没人管」是这份名册最该被看见的信息。
 */
export interface CollegeAdviserRow {
  classId: number
  className: string
  grade: string
  /** 班级信息里登记的班主任姓名（可能与账号不一致，两边都给出） */
  headTeacher: string
  /** null = 这个班还没有班主任账号 */
  teacherId: number | null
  username: string
  realName: string
  phone: string
  /** null = 没有账号；1=启用 0=停用 */
  status: number | null
  lastLoginAt: string | null
}

/** 班主任（导员）名册 */
export interface CollegeAdviserList {
  rows: CollegeAdviserRow[]
  total: number
}

/** 学院任务一览的一行 */
export interface CollegeTaskRow {
  id: number
  /** `COLLEGE`=学院任务（院长发的）；`CLASS`=班主任发的班级任务 */
  scope: TaskScope
  /** 发布人姓名（学院任务看不出是谁发的，这行必须有名字） */
  publisher: string
  classId: number
  className: string
  grade: string
  title: string
  question: string
  qtype: TaskQType
  options: string[]
  allowText: boolean
  /** 1=开放 0=已关闭（过了截止时间也算关） */
  open: boolean
  pinned: boolean
  /** 是不是我发的——决定显示不显示编辑/置顶/关闭/删除 */
  canEdit: boolean
  /**
   * 能不能看明细 / 导出。
   *
   * 和 `canEdit` 是**两个**权限：纯院长能管学院任务，却看不到别人班级任务的
   * 明细（后端 `task_service.can_see_detail`）。按钮必须各按各的显示，
   * 共用一个 v-if 会出现「关闭能用、导出 403」。
   */
  canSeeDetail: boolean
  /** 和 canEdit 同义，给需要区分「改内容」与「管状态」的地方用 */
  canManage: boolean
  deadline: string | null
  createdAt: string | null
  /** 已答人数 */
  answered: number
  /**
   * 应答总人数。
   *
   * 班级任务 = **该任务自己那个班**的应答人数；
   * 学院任务 = **全校班主任**的人数（一人代表一个班）。
   */
  total: number
  unanswered: number
}

/** 学院任务一览 */
export interface CollegeTaskList {
  rows: CollegeTaskRow[]
  total: number
  classes: CollegeClassChoice[]
}

/**
 * 改一列的类型之前，先看会发生什么（**不写库**）。
 *
 * 跨**所有班**汇总：这一列在每个班各有一份定义、各有各的存量值，
 * 只报一个班的数会骗人。
 */
export interface CollegeRetypePreview {
  key: string
  label: string
  fromType: string
  fromTypeText: string
  toType: string
  toTypeText: string
  /** 这一列在几个班里各有一份定义 */
  classCount: number
  /** 这一列共有多少个值（跨所有班汇总） */
  total: number
  /** 能转换的值的条数 */
  convertibleCount: number
  /** 能转换的样例：改前 → 改后 */
  convertibleSamples: { before: string; after: string }[]
  /** 样例之外还有多少个能转换的 */
  convertibleTruncated: number
  /** 转不了的（比如把「待缴」转成日期） */
  unconvertibleCount: number
  unconvertibleSamples: { before: string }[]
  unconvertibleTruncated: number
  /** 空值（未填就是未填，不用管） */
  emptyCount: number
}

/** 学院列定义（各班的字段按 field_key 合并成一份） */
export interface CollegeFieldList {
  columns: CollegeStudentColumn[]
  classes: CollegeClassChoice[]
}

/**
 * 导入学院学生信息的结果。
 *
 * `newFields` 是**自动新建**的列（文件里有、库里没有的列名）——
 * 和班级版一样：用户不必先去界面上手工加一遍列。
 */
export interface CollegeImportResult {
  created: number
  updated: number
  rows: number
  skippedEmptyCells: number
  newFields: { label: string; type: string; typeText: string }[]
  duplicateRows: number
  unmatchedColumns: string[]
  errors: string[]
  errorCount: number
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
  /**
   * 职务范围（第三十二轮）：true = 纯院长（只管学院）、false = 院长 + 班主任。
   *
   * 只有**院长本人**能改（别的角色这一位没有意义，后端会忽略）。
   */
  deanOnly?: boolean
  /**
   * **我带的班**（第三十二轮）。
   *
   * 班主任是**班**的归属（多对多）：一个老师可以带好几个班。
   * 传了就重写「我带的班」（**直接生效**）；不传 = 不改。
   * 只有运营角色以上能改（普通同学不是班主任）。
   */
  classIds?: number[]
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
  /**
   * 学院名（部署时在 `.env` 里声明 `CLASSFEE_COLLEGE_NAME`）。
   *
   * 侧栏顶部那行显示的是「你这个人的管辖范围」：对院长来说是**学院**，
   * 不是某个班。没配置就是空串，界面上退回写「学院」两个字。
   */
  collegeName: string
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
  /** 是不是纯院长（只管学院，不参与班级事务）。非院长恒为 false。 */
  deanOnly?: boolean
  classId: number
  /**
   * 这个账号**能管哪些班**（第三十二轮）。
   *
   * 一个班主任常带好几个班（云计算2502 + 云计算2501），这里列出全部。
   */
  managedClassIds?: number[]
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
  /**
   * 是不是纯院长（第三十轮）。**只有 `role='DEAN'` 时有意义**，
   * 其他角色传了会被后端忽略。
   *
   * 不传 = 兼班主任（与第二十八轮的行为完全一致）。
   */
  deanOnly?: boolean
  /**
   * 这个账号**能管哪些班**（第三十二轮）。
   *
   * 不传 = 只有当前班。只能给**你自己也管的班**（后端会过滤掉别的）。
   */
  classIds?: number[]
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
  /**
   * 是不是纯院长（第三十轮）。传了就改、**不传=不改**；只有院长有效。
   * 改完**立刻生效**（后端中间件每个请求都重读这一列）。
   */
  deanOnly?: boolean
  /**
   * 改成「这个账号能管哪些班」（第三十二轮）。不传=不改。
   * 只能给**你自己也管的班**（后端会过滤掉别的）。
   */
  classIds?: number[]
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

/** 任务的范围（第三十二轮）。与后端 	ask_service.SCOPES 一一对应 */
export type TaskScope = 'CLASS' | 'COLLEGE'

/** 任务列表看哪一块（第三十二轮）。与后端 	ask_service.VIEWS 一一对应 */
export type TaskView = 'mine' | 'college' | 'other'

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
  /**
   * 这条是**班级任务**还是**学院任务**（第三十二轮）。
   *
   * - CLASS：班主任/班长发给自己班的，**同学**应答
   * - COLLEGE：院长发到全学院的，**各班班主任**应答
   */
  scope: TaskScope
  /** 「班级任务」/「学院任务」 */
  scopeText: string
  /** 任务属于哪个班（学院任务是发布人的班） */
  classId: number
  /** 班级名（界面上要显示「谁发的」） */
  className: string
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
  /** 我能不能发**学院任务**（只有院长，第三十二轮） */
  canPublishCollege: boolean
  /** 这次看的是哪一块 */
  view: TaskView
}

/** 任务总览（第三十二轮，GET /api/tasks/overview） */
export interface TaskOverviewPayload {
  /** 能不能看到**其他班**的任务（运营角色） */
  canSeeAll: boolean
  /** 任务总数 */
  total: number
  /** 还在收答案的 */
  open: number
  /** 已关闭的 */
  closed: number
  /** 班级任务数 */
  classTasks: number
  /** 学院任务数 */
  collegeTasks: number
  /** 已答份数 */
  answered: number
  /** 应答对象总数（分母为 0 的任务不算） */
  base: number
  /** 回收率（百分数）；分母为 0 时为 null */
  rate: number | null
  /** 按班分布 */
  byClass: {
    classId: number
    className: string
    total: number
    open: number
    answered: number
    base: number
    rate: number | null
  }[]
  /** 按发布人分布 */
  byPublisher: { userId: number; name: string; total: number; open: number }[]
  /** 最近的任务（与任务列表同一形状） */
  recent: Task[]
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
  /**
   * CLASS（默认）= 班级任务；COLLEGE = **学院任务**（第三十二轮）。
   *
   * 学院任务全学院可见、由**各班班主任**应答，只有院长能发（后端会 403）。
   */
  scope?: TaskScope
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
