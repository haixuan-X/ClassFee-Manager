<script setup lang="ts">
/**
 * 学生信息（第二十三轮）—— **表格式就地编辑**。
 *
 * ## 交互按 Excel 来
 *
 * 用户口径：「做成 Excel 表格那样的编辑模式，要加字段直接在后面加，或者在字段之间加」。
 * 落到实现上是四件事：
 *
 * 1. **点格子就改，回车即存**。没有「编辑态 / 保存按钮」那套——Excel 里改完是直接生效的，
 *    这里也一样，改完立刻 PUT 一格。
 * 2. **点列名就改名，点类型小标签就改类型**——改字段跟改信息一个手感，不另开面板。
 * 3. **表头只有两个按钮**：`＋` 在该列之前插入新字段（想在末尾加就点最后一列的 ＋），
 *    `✕` 停用该列。模板字段也允许停用——34 列里大半填班费台账用不到；
 *    停用是软删，值保留，可在页头「已停用字段」里找回。
 * 4. **页头「新增学生」** 手工加一行（不用先准备 Excel）。
 *
 * 3、4 里的按钮**悬停列名才显示**；表格列名一行几十个，常驻会把字段名冲得七零八落。
 *
 * ## 行级权限仍然只作用在「能不能编辑」上
 *
 * 默认每个人只看得到自己那一行、且只能看不能改（改要申请，见页面里的申请条）。
 * 这与「Excel 式编辑」不冲突：能编辑时是表格，不能编辑时是只读表格 + 申请入口。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, Delete, Stamp } from '@element-plus/icons-vue'
import {
  applyStudentFieldRetype,
  createStudent,
  createStudentAccounts,
  createStudentField,
  deleteStudentField,
  exportSelectedStudents,
  fetchMyRequests,
  fetchPendingRequests,
  fetchStudentFields,
  fetchStudents,
  importStudents,
  previewStudentAccounts,
  previewStudentFieldRetype,
  restoreStudentField,
  updateStudent,
  updateStudentField,
} from '@/api/students'
import { getErrorMessage } from '@/api/request'
import StudentApprovalDrawer from '@/components/StudentApprovalDrawer.vue'
import type {
  StudentAccessRequest,
  StudentAccountPlan,
  StudentColumn,
  StudentField,
  StudentFieldType,
  StudentRetypePreview,
  StudentRow,
  StudentScope,
} from '@/types'

const loading = ref(true)
const importing = ref(false)

const columns = ref<StudentColumn[]>([])
const rows = ref<StudentRow[]>([])
const perm = ref<Awaited<ReturnType<typeof fetchStudents>>['permission'] | null>(null)

/** 正在编辑的格子：key = `${recordId}:${columnKey}` */
const editKey = ref<string | null>(null)
/** 正在保存的格子（转圈指示） */
const savingKey = ref<string | null>(null)
/** 最近一次保存的时间戳，用于闪一下「已保存」 */
const savedKey = ref<string | null>(null)
const savedAt = ref(0)

const myRequests = ref<StudentAccessRequest[]>([])

/** 新增字段的插入点：afterKey = 插在哪一列之后，null = 末尾 */
const insertAt = ref<string | null>(null)
const insertOpen = ref(false)
const insertLabel = ref('')
const insertType = ref<StudentFieldType>('TEXT')
const inserting = ref(false)

const TYPE_OPTIONS: { value: StudentFieldType; label: string }[] = [
  { value: 'TEXT', label: '文本' },
  { value: 'NUMBER', label: '数字' },
  { value: 'DATE', label: '日期' },
  { value: 'BOOL', label: '是/否' },
]

/**
 * 表头上那行小字。
 *
 * 原来写的是「文 / 数 / 日 / 是否」这种单字缩写，结果谁也看不懂是什么意思
 * （用户原话：「这个文是什么意思」）——省下的那点宽度远不值这个困惑。
 * 现在只标**非文本**的类型，因为默认就是文本、真没什么可提示的；
 * 文本列就干干净净一个名字。
 */
const TYPE_BADGE: Record<StudentFieldType, string> = {
  TEXT: '',
  NUMBER: '数字',
  DATE: '日期',
  BOOL: '是/否',
}

const ckey = (recordId: number, colKey: string) => `${recordId}:${colKey}`

/** 编辑态里输入框绑的值。每次进入编辑态由 startEdit 复位 */
const draftVal = ref('')

const isEditing = (id: number, k: string) => editKey.value === ckey(id, k)
const isSaving = (id: number, k: string) => savingKey.value === ckey(id, k)
const justSaved = (id: number, k: string) =>
  savedKey.value === ckey(id, k) && Date.now() - savedAt.value < 1600

/** 锚点列：学号与姓名固定在最前（不在字段表里，是「这是谁的行」） */
const isAnchor = (k: string) => k === '__no__' || k === '__name__'

/**
 * 锚点列同样能编辑，只有 `＋` 不给。
 *
 * 学号改起来有代价但可以接受：它是 Excel 导入的 upsert 键，改了之后
 * **再导同一份旧名单会插出一行重复数据**（按新学号匹配不到旧行）。
 * 这一点写在单元格 title 上，真踩到了也知道是怎么回事。
 * 撞号由后端拦（班内唯一），不会静默覆盖别人那一行。
 */

const myPending = computed(() => myRequests.value.find((r) => r.status === 'PENDING'))
const myRejected = computed(() => myRequests.value.find((r) => r.status === 'REJECTED'))
const canEdit = computed(() => perm.value?.canEditAll || perm.value?.canEditOwn)
const canAddField = computed(() => !!perm.value?.canAddField)

/**
 * 「一键创建账号」比「加字段」权限更高，**不能用 canAddField**。
 *
 * 加字段是班主任 + 班长（给个名字列不危险），建账号是"给人开一扇门"，
 * 一次能开几十个。用户口径明确「仅班主任」。这里读 `isTeacher` 而不是
 * 复用 canAddField，就是为了不让这两条权限以后被绑在一起。
 */
const canCreateAccounts = computed(() => !!perm.value?.isTeacher)

/**
 * 班主任的审批入口。
 *
 * 页面改成表格以后，抽屉一度没人引用——审批功能等于**整个从界面上消失了**：
 * 接口还在、回归也绿，但老师根本点不到，只能自己去调 API。
 * 这种"删引用但没人报错"的缺口，靠 tsc 抓不到（未使用的文件不是错误），
 * 所以这里把入口钉在页头上，并挂一个待审批数量角标。
 */
const approvalOpen = ref(false)
/** 待审批条数，给页头按钮打角标；非班主任恒为 0 */
const pendingCount = ref(0)
const isTeacher = computed(() => !!perm.value?.isTeacher)

async function loadPendingCount() {
  if (!isTeacher.value) {
    pendingCount.value = 0
    return
  }
  try {
    pendingCount.value = (await fetchPendingRequests()).length
  } catch {
    pendingCount.value = 0 // 角标失败不该挡住页面，忽略即可
  }
}

/** 审批完一条：角标数和表格数据一起刷新 */
async function onApprovalHandled() {
  await Promise.all([loadPendingCount(), load()])
}

const emptyHint = computed(() => {
  if (!perm.value) return ''
  if (perm.value.accountHasNoStudentNo) return 'no-student-no'
  if (perm.value.classHasNoRecords) return 'no-records'
  return ''
})

async function load() {
  loading.value = true
  try {
    const sheet = await fetchStudents()
    columns.value = sheet.columns
    rows.value = sheet.rows
    // 刷新后清掉已经不存在的勾选（停用了字段、新增了行都会走到这里）。
    // 不清的话 selectedIds 里会攒下看不见的 id，点「导出选中」就导出了用户看不见的行。
    const alive = new Set(sheet.rows.map((r) => r.id))
    selectedIds.value = selectedIds.value.filter((id) => alive.has(id))
    perm.value = sheet.permission
    await loadMyRequests()
    await loadPendingCount()
  } catch {
    columns.value = []
    rows.value = []
  } finally {
    loading.value = false
  }
}

async function loadMyRequests() {
  try {
    myRequests.value = await fetchMyRequests()
  } catch {
    myRequests.value = []
  }
}

onMounted(load)

// ---------------- 就地编辑 ----------------

function startEdit(id: number, k: string) {
  if (!canEdit.value) return
  if (!isEditableCol(k)) return
  // 已经在编辑这一格就直接返回：td 的 click 会冒泡，输入框里点一下挪光标也会触发，
  // 不挡住的话 draftVal 会被重置回旧值，用户刚敲的字就没了。
  if (editKey.value === ckey(id, k)) return
  const row = rows.value.find((r) => r.id === id)
  if (!row || !row.editable) return
  draftVal.value = cellValue(row, k)
  editKey.value = ckey(id, k)
}

/**
 * 这一列能不能进编辑态。学号/姓名都**可以**改了。
 *
 * （保留这个函数而不是散在调用点判断：以后要是再加"某列只读"，
 * 改一处就够，不用满页面找 `readonly`。）
 */
function isEditableCol(_k: string) {
  return true
}

function moveEdit(id: number, k: string, delta: number) {
  // Tab 在格间移动，这是 Excel 手感的关键部分。
  // 必须连 draftVal 一起换：只改 editKey 的话新格子里会显示**上一格**的内容，
  // 用户按两下 Tab 就把上一列的值复制过去了。
  const row = rows.value.find((r) => r.id === id)
  if (!row) return
  const list = columns.value
  let i = list.findIndex((c) => c.key === k)
  // 跳过学号等不可编辑列，别让 Tab 停在那儿
  for (let step = 0; step < list.length; step += 1) {
    i += delta
    if (i < 0 || i >= list.length) {
      editKey.value = null // 到头了就退出编辑态，而不是跳回第一格
      return
    }
    if (isEditableCol(list[i].key)) break
  }
  draftVal.value = cellValue(row, list[i].key)
  editKey.value = ckey(id, list[i].key)
}

function cellValue(row: StudentRow, k: string): string {
  if (k === '__no__') return row.studentNo
  if (k === '__name__') return row.name
  return row.values[k] ?? ''
}

/**
 * 提交一格。返回是否保存成功（Tab 要靠它决定要不要往下一格走）。
 *
 * 注意：这里**先**把 `editKey` 置空再发请求。输入框随即被卸载，
 * 而卸载一个正在聚焦的 DOM 节点不会触发 blur —— 所以所有「结束编辑」的路径
 * 都必须经过这个函数，漏一条就是用户敲的字白打。
 */
async function commit(id: number, k: string, raw: string | null): Promise<boolean> {
  const row = rows.value.find((r) => r.id === id)
  if (!row) return false
  // 只在「关的就是当前这一格」时才退出编辑态。Tab 是先移走再异步存的，
  // 无脑置 null 会把刚落位的下一格的输入框也一起关掉。
  const ck = ckey(id, k)
  if (editKey.value === ck) editKey.value = null
  const before = cellValue(row, k)
  if ((raw ?? '') === before) return true // 没改就不发请求
  savingKey.value = ckey(id, k)
  try {
    if (k === '__name__') await updateStudent(id, {}, { name: raw ?? '' })
    else if (k === '__no__') await updateStudent(id, {}, { studentNo: raw ?? '' })
    else await updateStudent(id, { [k]: raw ?? '' })
    // 乐观更新：先改本地再后台拉，界面不等网络
    if (k === '__name__') row.name = raw ?? ''
    else if (k === '__no__') row.studentNo = raw ?? ''
    else row.values[k] = raw ?? ''
    savedKey.value = ckey(id, k)
    savedAt.value = Date.now()
    setTimeout(() => {
      if (savedKey.value === ckey(id, k)) savedKey.value = null
    }, 1700)
    return true
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '保存失败'))
    await load() // 拉回真实值，避免界面显示没存上的内容
    return false
  } finally {
    savingKey.value = null
  }
}

/**
 * Tab = 右移一格，顺带把当前这格存了。
 *
 * 两条容易踩的：
 * ① 必须拦 **keydown** 而不是 keyup —— 浏览器在 keydown 阶段就把焦点移走，
 *    blur 先触发、输入框被卸载，keyup.tab 压根不会派发到它身上。
 *    `@keydown.tab.prevent()` 同时挡住了焦点移走，于是 blur 也不会触发。
 * ② 先移再存，不等网络。raw 已经取值，commit 里改 draftVal 也影响不到它。
 */
function onTab(id: number, k: string) {
  const raw = draftVal.value
  moveEdit(id, k, 1)
  void commit(id, k, raw)
}

/** 「清空这一格」——Excel 里 Delete 键的效果。
 *  传 null 而不是空串：空串会作为「已填的空文本」存进库，而 null 才是「未填」。 */
async function clearCell(row: StudentRow, k: string) {
  await commit(row.id, k, null)
}

/**
 * 焦点离开这一格 = 提交（Excel 里点别处就生效）。
 *
 * 挂在 td 的 `focusout` 而不是 el-input 的 `blur`，是因为：
 * blur 不冒泡，且**输入框被卸载时不派发**——而点另一格正是"当前输入框被卸载"，
 * 万一 blur 没赶上（焦点没真正移走、或组件把 blur 挂到了外层包装 div 上），
 * 用户敲的字就白打了。focusout 会从内层 input 一路冒泡到 td，稳。
 */
function onCellFocusOut(row: StudentRow, k: string) {
  // 只有「正是在编辑这一格」才提交：Tab 移走后输入框卸载也会冒泡上来，
  // 那时 editKey 已经指向新格子，再提交一次等于把旧值盖回去。
  if (editKey.value !== ckey(row.id, k)) return
  void commit(row.id, k, draftVal.value)
}

/**
 * 单元格上的键盘处理，**所有编辑器类型统一走这里**。
 *
 * 为什么不各挂各的控件：BOOL 是 el-select、DATE 是 el-date-picker，
 * 只给 el-input 挂键盘事件的话这两种格子点开之后既没有 Esc 也没有 Tab——
 * 用户点开不选就走，格子永远停在编辑态；更糟的是 Delete 键要求「不在编辑态」
 * 才生效，于是整列就再也清不掉了。
 * 冒泡到 td 上统一处理，三种编辑器一视同仁。
 *
 * 用 `.capture`（捕获阶段）而不是默认的冒泡：el-select 内部的 onKeydown 对
 * Escape 会 `stopPropagation`，冒泡阶段根本轮不到这里的 handler，Esc 就废了。
 * 捕获阶段先于目标元素触发，抢在组件之前拿到键盘事件。
 * 注意只拦 Esc / Tab / Delete，**不碰 Enter 和方向键**——那两个是 select / date
 * 面板自己用来选中、翻页的，抢过来会让下拉框选不中。
 */
function onCellKeydown(e: KeyboardEvent, row: StudentRow, k: string) {
  // 未编辑状态下按 Delete：清掉该格（Excel 的 Delete 键）
  if (e.key === 'Delete' && !editKey.value) {
    if (!canEdit.value || !row.editable) return
    e.preventDefault()
    void clearCell(row, k)
    return
  }
  if (editKey.value !== ckey(row.id, k)) return

  if (e.key === 'Escape') {
    editKey.value = null // 不保存直接关（Excel 里 Esc 的语义）
    return
  }
  if (e.key === 'Tab') {
    // 必须拦 keydown：浏览器在这一阶段就把焦点移走，输入框随即被卸载
    e.preventDefault()
    onTab(row.id, k)
  }
}

// ---------------- 新增字段（可在任意位置插入） ----------------

/**
 * 「在某一列前面插一个字段」。表头上每个 `＋` 都调它。
 *
 * 注意是**这一列自己**的 key，不是前一列的 key。传"前一列"的话，
 * 点第一列（学号）的 `＋` 会退化成"追加到末尾"，而对话框标题还写着
 * "在学号前面插入"，说的和做的不是一回事。
 */
function openInsert(beforeKey: string, beforeLabel: string) {
  insertAt.value = beforeKey
  insertLabel.value = ''
  insertType.value = 'TEXT'
  insertOpen.value = true
  insertAnchorLabel.value = beforeLabel
}

const insertAnchorLabel = ref('')

async function submitInsert() {
  const label = insertLabel.value.trim()
  if (!label) {
    ElMessage.warning('请填写字段名称')
    return
  }
  inserting.value = true
  try {
    await createStudentField({ label, type: insertType.value }, insertAt.value)
    insertOpen.value = false
    ElMessage.success(`已在「${insertAnchorLabel.value}」前面插入字段`)
    await load()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '新增字段失败'))
  } finally {
    inserting.value = false
  }
}

async function removeColumn(col: StudentColumn) {
  // 确认框里必须说清"值还在"：用户看到列消失，第一反应是"数据没了"。
  // 实际是软删，误删可以从「已停用字段」里找回来。
  const hasTemplate = col.system
  try {
    await ElMessageBox.confirm(
      `确定停用字段「${col.label}」吗？\n\n` +
        `· 它会从表格、导出和后续导入中消失\n` +
        `· 这一列已填的值仍保留在数据库里，误删可在「已停用字段」中恢复` +
        (hasTemplate ? '\n· 这是模板预置字段，停用后本班所有同学都看不到这一列' : ''),
      '确认停用该字段？',
      { type: 'warning', confirmButtonText: '确认停用', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteStudentField(col.key)
    ElMessage.success(`「${col.label}」已停用，可在「已停用字段」里恢复`)
    await load()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '停用失败'))
  }
}

// ---------------- 勾选导出 ----------------

/**
 * 勾选行 id。
 *
 * 访客（领导）的主要用途就是「勾几个人、把他们的信息导出来看」，
 * 之前只能整表导出，40 多列 50 个人全倒出来，没法挑。
 */
const selectedIds = ref<number[]>([])

/** 表头全选框的三个态：全选 / 全不选 / 部分选中 */
const allSelected = computed(() => rows.value.length > 0 && selectedIds.value.length === rows.value.length)
const someSelected = computed(
  () => selectedIds.value.length > 0 && selectedIds.value.length < rows.value.length,
)
const isIndeterminate = computed(() => !allSelected.value && someSelected.value)

function toggleAll() {
  selectedIds.value = allSelected.value ? [] : rows.value.map((r) => r.id)
}

function toggleRow(id: number) {
  const i = selectedIds.value.indexOf(id)
  if (i >= 0) selectedIds.value.splice(i, 1)
  else selectedIds.value.push(id)
}

const exportingSelected = ref(false)

/**
 * 导出对话框：**行范围 + 列**都在这里定。
 *
 * 用户口径「没办法选中目标列进行导出吗」——领导要的多半是
 * 「这 3 个人的学号、姓名、寝室、电话」，36 列全倒出来没人看得下去。
 *
 * 学号/姓名的勾选框是**锁死**的（`disabled`）：它们是锚点列，
 * 没有学号的表格没法说明每一行是谁，导出去也没用。
 * 后端也会无条件保留这两列，两边都堵死。
 */
const exportOpen = ref(false)
const exportRowScope = ref<'selected' | 'all'>('all')
const exportFields = ref<string[]>([])
/** 列搜索框：列名一多，勾选框列表就得能筛 */
const exportFieldFilter = ref('')

const selectableColumns = computed(() =>
  columns.value.filter((c) => !isAnchor(c.key)),
)
const anchorColumns = computed(() => columns.value.filter((c) => isAnchor(c.key)))

/** 学号/姓名 + 用户勾选的列。顺序按表格里的实际列序，别按勾选顺序。 */
const exportColumnKeys = computed(() =>
  columns.value
    .map((c) => c.key)
    .filter((k) => isAnchor(k) || exportFields.value.includes(k)),
)

const exportFieldSearch = computed(() => {
  const q = exportFieldFilter.value.trim().toLowerCase()
  if (!q) return selectableColumns.value
  return selectableColumns.value.filter((c) => c.label.toLowerCase().includes(q))
})

const exportRowCount = computed(() =>
  exportRowScope.value === 'selected' ? selectedIds.value.length : rows.value.length,
)

function openExport() {
  // 默认给「全部列 + 全部行」：多数时候用户只是导一份完整的，
  // 真要挑就在这个对话框里改，改动即时反映在预览上。
  exportRowScope.value = selectedIds.value.length ? 'selected' : 'all'
  exportFields.value = selectableColumns.value.map((c) => c.key)
  exportFieldFilter.value = ''
  exportOpen.value = true
}

function toggleExportField(key: string) {
  const i = exportFields.value.indexOf(key)
  if (i >= 0) exportFields.value.splice(i, 1)
  else exportFields.value.push(key)
}

/**
 * 「更多」下拉的命令分发。
 *
 * 用 `@command` 而不是逐项绑 `@click`：下拉项绑 click 时菜单会先收起、
 * 对话框再弹出，中间那一帧看起来像没点上；走 command 由 Element Plus
 * 统一处理关闭顺序。`openTrash` 是异步的（要先拉停用字段列表），这点尤其明显。
 */
function onMore(cmd: string) {
  if (cmd === 'approval') approvalOpen.value = true
  else if (cmd === 'trash') void openTrash()
}

function selectAllFields() {
  exportFields.value = selectableColumns.value.map((c) => c.key)
}

async function submitExport() {
  exportingSelected.value = true
  try {
    const useRows =
      exportRowScope.value === 'selected' ? [...selectedIds.value] : undefined
    await exportSelectedStudents({
      recordIds: useRows,
      fieldKeys: [...exportColumnKeys.value],
    })
    exportOpen.value = false
    ElMessage.success(
      `已导出 ${exportRowCount.value} 名学生 × ${exportColumnKeys.value.length} 列`,
    )
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '导出失败'))
  } finally {
    exportingSelected.value = false
  }
}

// ---------------- 新增一行（不靠 Excel） ----------------

/**
 * 手工加学生。
 *
 * 只要**学号 + 姓名**——这两列是锚点，缺了系统就没法定位"这是谁的行"，
 * 也就没法把「你只能看见自己那一行」这个规则套上去。
 * 其余字段一律留空，建完直接在表格里点格子填，和 Excel 插一行一个意思。
 *
 * 刻意不做成"一个填 30 多项的大表单"：字段是动态的，表单得跟着字段表重建，
 * 而用户真正要填的往往就两三项。剩下的在表格里逐格填更快。
 */
const addOpen = ref(false)
const addNo = ref('')
const addName = ref('')
const addSaving = ref(false)

/** 本班已占用的学号，用来在输入时就提示，而不是等提交后报 400 */
const usedNos = computed(() => new Set(rows.value.map((r) => r.studentNo)))
const addNoDup = computed(() => addNo.value.trim() !== '' && usedNos.value.has(addNo.value.trim()))

function openAdd() {
  addNo.value = ''
  addName.value = ''
  addOpen.value = true
}

async function submitAdd() {
  const no = addNo.value.trim()
  const nm = addName.value.trim()
  if (!no) {
    ElMessage.warning('请填写学号')
    return
  }
  if (!nm) {
    ElMessage.warning('请填写姓名')
    return
  }
  if (addNoDup.value) {
    ElMessage.warning(`学号 ${no} 已经在表里了`)
    return
  }
  addSaving.value = true
  try {
    await createStudent(no, nm)
    addOpen.value = false
    await load()
    ElMessage.success(`已添加「${nm}」，其余信息可在表格里点格子填写`)
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '新增失败'))
  } finally {
    addSaving.value = false
  }
}

// ---------------- 改列名（就地改，跟改格子一个手感） ----------------

/**
 * 点列名改名。**不另开对话框**——用户口径是「更改像更改信息一样更改」，
 * 也就是跟点格子改内容一样：点一下变成输入框，回车就存。
 */
const renamingKey = ref<string | null>(null)
const renameDraft = ref('')

function startRename(col: StudentColumn) {
  if (!canAddField.value || isAnchor(col.key)) return
  // 已经在改这一列就直接返回，不然点击会重置掉刚敲的字
  if (renamingKey.value === col.key) return
  renameDraft.value = col.label
  renamingKey.value = col.key
}

async function submitRename(col: StudentColumn) {
  if (renamingKey.value !== col.key) return
  const label = renameDraft.value.trim()
  renamingKey.value = null
  if (!label || label === col.label) return
  try {
    await updateStudentField(col.key, { label })
    ElMessage.success(`已改名为「${label}」`)
    await load()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '改名失败'))
  }
}

// ---------------- 改字段类型（两步：先预览，再确认） ----------------

/**
 * 导入时字段类型是**按取值猜**的（整列都是 20250901 才认成日期），
 * 猜错是常态——所以必须给一个改的入口。
 *
 * 关键在于**改类型会动已存的值**：值是按文本存的（EAV），类型只决定
 * 写入时怎么校验、界面怎么显示。TEXT 改成 DATE 之后，库里的 "20250901"
 * 还是老样子，日期选择器认不出来，必须同步把存量值重新归一化。
 *
 * 而有的值转不了（「待定」没法变日期）。所以不能点一下就直接改：
 * 先 preview 把这笔账摊开，用户看清了再 confirm。
 */
const retypeOpen = ref(false)
const retypeCol = ref<StudentColumn | null>(null)
const retypeTo = ref<StudentFieldType>('TEXT')
const retypePreview = ref<StudentRetypePreview | null>(null)
const retypeLoading = ref(false)
const retypeApplying = ref(false)
/** 转不了的值要不要清空。默认保留原文本——改错了还能改回来 */
const retypeClearBad = ref(false)

const retypeChanged = computed(
  () => retypePreview.value !== null && retypePreview.value.fromType !== retypeTo.value,
)

/** 只有可转换数为 0、转不了的也一堆时，「清空」才是唯一出路——反过来不行 */
const retypeNeedChoice = computed(() => (retypePreview.value?.unconvertibleCount ?? 0) > 0)

async function openRetype(col: StudentColumn) {
  if (!canAddField.value || isAnchor(col.key)) return
  retypeCol.value = col
  retypeTo.value = col.type
  retypePreview.value = null
  retypeClearBad.value = false
  retypeOpen.value = true
  // 默认就拉一遍预览，让用户一进来就看得到"改成日期会怎样"
  await loadRetypePreview()
}

async function loadRetypePreview() {
  const col = retypeCol.value
  if (!col || col.type === retypeTo.value) {
    retypePreview.value = null
    return
  }
  retypeLoading.value = true
  try {
    retypePreview.value = await previewStudentFieldRetype(col.key, retypeTo.value)
    // 有转不了的值时，把选择重置成安全的"保留"。
    // 用户上一轮可能选了清空，这一轮目标类型不同，不能沿用。
    if (retypePreview.value.unconvertibleCount > 0) retypeClearBad.value = false
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '读取转换预览失败'))
    retypePreview.value = null
  } finally {
    retypeLoading.value = false
  }
}

async function submitRetype() {
  const col = retypeCol.value
  if (!col || !retypeChanged.value) return
  retypeApplying.value = true
  try {
    const r = await applyStudentFieldRetype(col.key, retypeTo.value, retypeClearBad.value)
    retypeOpen.value = false
    const parts = [`已把「${col.label}」改成${r.toType === 'DATE' ? '日期' : r.toType === 'NUMBER' ? '数字' : r.toType === 'BOOL' ? '是/否' : '文本'}类型`]
    if (r.convertedCount) parts.push(`${r.convertedCount} 个值已转换`)
    if (r.clearedCount) parts.push(`${r.clearedCount} 个值已清空`)
    if (r.keptUnconvertibleCount) {
      parts.push(`${r.keptUnconvertibleCount} 个值转不了、原样保留`)
    }
    ElMessage.success(parts.join('，'))
    await load()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '改类型失败'))
  } finally {
    retypeApplying.value = false
  }
}

// ---------------- 已停用字段（恢复） ----------------

const trashOpen = ref(false)
const trashLoading = ref(false)
const disabledFields = ref<StudentField[]>([])

/**
 * 已停用的字段。
 *
 * 停用是软删（`status=0`），值一行没动——所以必须给一条找回的路，
 * 否则"误删一列填了几十条数据的字段"就等于真丢了。
 */
async function openTrash() {
  trashOpen.value = true
  trashLoading.value = true
  try {
    const all = await fetchStudentFields(true)
    disabledFields.value = all.filter((f) => f.status === 0)
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '读取已停用字段失败'))
    disabledFields.value = []
  } finally {
    trashLoading.value = false
  }
}

async function restoreField(f: StudentField) {
  try {
    await restoreStudentField(f.key)
    ElMessage.success(`「${f.label}」已恢复`)
    await Promise.all([openTrash(), load()])
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '恢复失败'))
  }
}

// ---------------- 申请 ----------------

const NEEDED: { scope: StudentScope; label: string; hint: string }[] = [
  { scope: 'EDIT_OWN', label: '申请修改本人信息', hint: '改自己那一行' },
  { scope: 'VIEW_ALL', label: '申请查看全部', hint: '查看班上所有同学的登记信息' },
  { scope: 'EDIT_ALL', label: '申请编辑全部', hint: '修改班上所有同学的登记信息' },
]

const needApply = computed(() => {
  if (!perm.value) return []
  // 访客直接返回空：他不是班上的人，「申请修改自己的信息 / 申请编辑全班」
  // 对他不成立。而且访客的权限是**角色内建**的（GUEST_SCOPES，只读），
  // 压根不走申请/授权那张表——后端 `create_request` 对他是 403，
  // 页面摆这个按钮等于「放一个点下去必然报错的东西」。
  if (perm.value.isGuest) return []
  const have = new Set(perm.value.scopes)
  return NEEDED.filter((n) => !have.has(n.scope))
})

async function apply(n: { scope: StudentScope; label: string }) {
  try {
    const { value: reason } = await ElMessageBox.prompt(
      '可以写一句申请理由，班主任会看到（可不填）',
      n.label,
      {
        confirmButtonText: '提交申请',
        cancelButtonText: '取消',
        inputPlaceholder: '例如：需要核对全班学号',
        inputValidator: (v: string) => (v.length <= 255 ? true : '最多 255 字'),
      },
    )
    const { createStudentRequest } = await import('@/api/students')
    await createStudentRequest(n.scope, reason || undefined)
    ElMessage.success('已提交，等班主任审批')
    await loadMyRequests()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') {
      ElMessage.error(getErrorMessage(e, '提交失败'))
    }
  }
}

// ---------------- 导入导出 ----------------

async function onImport(file: File) {
  importing.value = true
  try {
    const r = await importStudents(file)
    ElMessage.success(`导入完成：新增 ${r.created} 人，更新 ${r.updated} 人`)

    // 表格里多出来的列已经自动建成字段了（用户口径：合并，不要手工先去加列）。
    // 要专门告诉他"多了什么"，否则他回头一看列变多了会不知道哪来的。
    if (r.newFields.length) {
      const detail = r.newFields.map((f) => `${f.label}（${f.typeText}）`).join('、')
      ElMessageBox.alert(
        `表格里有 ${r.newFields.length} 列之前没有，已自动建为字段并导入：\n${detail}\n\n` +
          '类型是按这一列的取值猜的，如果猜得不对，可以在表格里点该列的字段设置改成别的类型。',
        '已自动新增字段',
        { confirmButtonText: '知道了' },
      )
    }
    if (r.unmatchedColumns.length) {
      ElMessage.warning(
        `表格里有 ${r.unmatchedColumns.length} 列没有对应字段，未导入：${r.unmatchedColumns.join('、')}`,
      )
    }
    // 重复学号不中止导入（后一行覆盖前一行），但必须让人知道表里有重复行
    if (r.duplicateRows > 0) {
      ElMessage.warning(
        `表格里有 ${r.duplicateRows} 行学号重复，已按后出现的覆盖前面的。` +
          '如果这不是你要的，请检查表格里有没有复制粘贴残留的空行。',
      )
    }
    if (r.errorCount > 0) {
      ElMessageBox.alert(`共 ${r.errorCount} 处未写入：\n${r.errors.join('\n')}`, '部分单元格未导入')
    }
    await load()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '导入失败'))
  } finally {
    importing.value = false
  }
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  if (f) void onImport(f)
  input.value = ''
}

// ---------------- 一键创建账号（第二十五轮） ----------------

const accOpen = ref(false)
const accLoading = ref(false)
const accDoing = ref(false)
const accPlan = ref<StudentAccountPlan | null>(null)

/** 打开对话框时先拉预演：建号不可逆，得先看清楚会动多少人 */
async function openAccounts() {
  accOpen.value = true
  accLoading.value = true
  accPlan.value = null
  try {
    accPlan.value = await previewStudentAccounts()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '读不出来'))
    accOpen.value = false
  } finally {
    accLoading.value = false
  }
}

async function submitAccounts() {
  accDoing.value = true
  try {
    const r = await createStudentAccounts()
    accPlan.value = r
    ElMessage.success(
      `已创建 ${r.created.length} 个账号` +
        (r.linked.length ? `，挂接 ${r.linked.length} 个已有账号` : '') +
        (r.skipped.length ? `，跳过 ${r.skipped.length} 行` : ''),
    )
    // 表格里那列「是否已建账号」会变，所以要重载
    await load()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '创建失败'))
  } finally {
    accDoing.value = false
  }
}

/** 没东西可建时禁用主按钮，而不是点了之后弹一句「没有可创建的」 */
const accNothingToDo = computed(() => {
  const p = accPlan.value
  return !!p && p.executed === false && p.toCreate === 0 && p.toLink === 0
})
</script>

<template>
  <div class="page">
    <header class="head">
      <div>
        <h2>学生信息</h2>
        <p class="sub">
          <template v-if="perm?.isGuest">
            共 {{ rows.length }} 人 · 只读，勾选后可导出
          </template>
          <template v-else-if="perm?.canViewAll">
            共 {{ rows.length }} 人 ·
            <template v-if="perm?.canEditAll">点任意格子即可修改，回车保存</template>
            <template v-else>当前只读</template>
          </template>
          <template v-else-if="perm?.myRecordId">
            这里只显示你自己那一行。需要看或改别人的，先向班主任申请。
          </template>
          <template v-else-if="emptyHint === 'no-student-no'">
            你的账号还没填学号，匹配不到自己那一行。请先到「个人信息」补充学号。
          </template>
          <template v-else-if="emptyHint === 'no-records'">
            本班还没有导入学生名单，请找班主任在「学生信息」里导入。
          </template>
        </p>
      </div>
      <div class="actions">
        <!--
          页头按**工作流**排，不按功能分类排：
            导入 Excel    → 把名单放进来（这个页面的起点，唯一的主按钮）
            新增学生      → 没有 Excel 时也能加人
            一键创建账号  → 导入完的下一步
            导出          → 拿出去
          低频的两个（访问授权 / 已停用字段）收进「更多」。

          之前「新增学生」和「导出」**都是 primary**，两个主操作互相抢视线；
          primary 的含义是"这个页面的主行动是它"。老师第一次打开这一页
          要干的是导入名单，所以导入才是唯一的主按钮。
        -->
        <label v-if="canAddField" class="file-btn">
          <input type="file" accept=".xlsx,.xlsm" hidden @change="onFileChange" />
          <el-button :loading="importing" type="primary" tag="span">导入 Excel</el-button>
        </label>
        <!-- 没有 Excel 时也能加人；只要学号+姓名，其余在表格里逐格填 -->
        <el-button v-if="canAddField" @click="openAdd">新增学生</el-button>
        <!-- 一键建账号：导入完名单的**下一步**。权限比「加字段」高，仅班主任 -->
        <el-button v-if="canCreateAccounts" @click="openAccounts">一键创建账号</el-button>
        <!-- 导出：行范围和列都在这个对话框里定 -->
        <el-button @click="openExport">
          导出<span v-if="selectedIds.length">选中（{{ selectedIds.length }}）</span>
        </el-button>

        <!--
          「更多」里装的两个入口都是班主任/班长专属。两者都没有时**整个下拉不渲染**——
          给普通同学留一个空菜单、点开是张白纸，比不给还糟。
        -->
        <el-dropdown v-if="isTeacher || canAddField" trigger="click" @command="onMore">
          <el-button :class="{ 'has-pending': pendingCount > 0 }" aria-label="更多操作">
            更多<el-icon class="more-caret"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <!-- 待审批数量是这个入口最重要的信息，收进菜单也必须还看得见：
                   按钮上的红点 + 菜单项里的数字，两处都标 -->
              <el-dropdown-item v-if="isTeacher" command="approval">
                <el-icon><Stamp /></el-icon>访问授权
                <span v-if="pendingCount > 0" class="pending-count">{{ pendingCount }}</span>
              </el-dropdown-item>
              <!-- 停用是软删，误删要能找回来：这个入口是"已停用字段"的唯一去处 -->
              <el-dropdown-item v-if="canAddField" command="trash">
                <el-icon><Delete /></el-icon>已停用字段
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <section v-if="perm && !perm.isTeacher && needApply.length" class="apply-bar">
      <div class="apply-title">
        <el-icon><Lock /></el-icon>
        <span>这些内容需要班主任授权</span>
      </div>
      <div class="apply-list">
        <button
          v-for="n in needApply"
          :key="n.scope"
          class="apply-btn"
          type="button"
          @click="apply(n)"
        >
          <strong>{{ n.label }}</strong>
          <small>{{ n.hint }}</small>
        </button>
      </div>
    </section>

    <el-alert
      v-if="myPending"
      class="notice"
      type="info"
      :closable="false"
      show-icon
      :title="`「${myPending.scopeText}」已提交，等待班主任审批`"
    />
    <el-alert
      v-if="myRejected"
      class="notice"
      type="warning"
      :closable="false"
      show-icon
      :title="`「${myRejected.scopeText}」申请未通过`"
      :description="myRejected.reply ? `班主任回复：${myRejected.reply}` : '班主任未填写理由'"
    />

    <!-- ============ 表格 ============ -->
    <div v-loading="loading" class="grid-wrap">
      <table class="grid">
        <thead>
          <tr>
            <th class="corner pick">
              <el-checkbox
                :model-value="allSelected"
                :indeterminate="isIndeterminate"
                aria-label="全选 / 取消全选"
                @change="toggleAll"
              />
            </th>
            <th v-for="col in columns" :key="col.key" class="col-head">
              <div class="col-inner">
                <!--
                  列名和类型都能就地改，跟改格子信息一个手感：
                  点列名 → 变输入框 → 回车保存；点类型小标签 → 换类型。
                  所以表头上只留 ＋ 和 ✕ 两个按钮（用户口径：「你直接保留新增和删除就行了」）。
                -->
                <el-input
                  v-if="renamingKey === col.key"
                  ref="renameInput"
                  v-model="renameDraft"
                  size="small"
                  class="col-rename"
                  maxlength="64"
                  @keyup.enter="submitRename(col)"
                  @keyup.esc="renamingKey = null"
                  @blur="submitRename(col)"
                  @keydown.tab.prevent="submitRename(col)"
                />
                <span
                  v-else
                  class="col-label"
                  :class="{ editable: canAddField && !isAnchor(col.key) }"
                  :title="canAddField && !isAnchor(col.key)
                    ? `${col.label}（${TYPE_OPTIONS.find((t) => t.value === col.type)?.label ?? col.type}）——点击可改名`
                    : `${col.label}（${TYPE_OPTIONS.find((t) => t.value === col.type)?.label ?? col.type}）`"
                  @click="startRename(col)"
                >
                  {{ col.label }}
                </span>
                <span
                  v-if="TYPE_BADGE[col.type]"
                  class="col-type"
                  :class="{ editable: canAddField && !isAnchor(col.key) }"
                  :title="canAddField && !isAnchor(col.key) ? '点击可改这一列的类型' : TYPE_BADGE[col.type]"
                  @click="openRetype(col)"
                >
                  {{ TYPE_BADGE[col.type] }}
                </span>
                <span class="col-ops">
                  <!--
                    锚点列（学号/姓名）不给 ＋：它们不在字段表里，是后端固定拼在最前面的。
                    给它按 ＋，对话框会说"在学号前面插入"，可实际根本无处可插——
                    后端找不到锚点就回退到追加末尾，说的和做的正好相反。
                  -->
                  <button
                    v-if="canAddField && !isAnchor(col.key)"
                    class="mini"
                    title="在这一列前面插入新字段"
                    @click="openInsert(col.key, col.label)"
                  >
                    ＋
                  </button>
                  <button
                    v-if="canAddField"
                    class="mini danger"
                    title="停用该字段"
                    @click="removeColumn(col)"
                  >
                    ✕
                  </button>
                </span>
              </div>
            </th>
          </tr>
        </thead>

        <tbody>
          <tr v-for="(row, ri) in rows" :key="row.id" :class="{ picked: selectedIds.includes(row.id) }">
            <td class="row-no pick">
              <el-checkbox
                :model-value="selectedIds.includes(row.id)"
                :aria-label="`选择 ${row.name}`"
                @change="toggleRow(row.id)"
              />
              <span class="row-idx">{{ ri + 1 }}</span>
            </td>
            <td
              v-for="col in columns"
              :key="col.key"
              class="cell"
              :class="{
                editing: isEditing(row.id, col.key),
                readonly: !canEdit || !row.editable,
                saved: justSaved(row.id, col.key),
              }"
              :title="col.key === '__no__' ? '学号是导入名单时的匹配依据，改动后再导同一份名单会重复插入' : undefined"
              tabindex="0"
              @click="startEdit(row.id, col.key)"
              @keydown.capture="onCellKeydown($event, row, col.key)"
              @focusout="onCellFocusOut(row, col.key)"
            >
              <!-- 编辑态：按字段类型给对应控件 -->
              <el-select
                v-if="isEditing(row.id, col.key) && col.type === 'BOOL'"
                v-model="draftVal"
                size="small"
                @change="commit(row.id, col.key, draftVal)"
              >
                <!-- 空选项是必须的：否则填了「是」之后就再也回不到「未填」 -->
                <el-option label="— 未填 —" value="" />
                <el-option label="是" value="是" />
                <el-option label="否" value="否" />
              </el-select>

              <el-date-picker
                v-else-if="isEditing(row.id, col.key) && col.type === 'DATE'"
                v-model="draftVal"
                type="date"
                size="small"
                value-format="YYYY-MM-DD"
                clearable
                @change="commit(row.id, col.key, draftVal)"
              />

              <!-- 键盘事件（Esc / Tab / Delete）统一由 td 冒泡处理，三种编辑器行为一致 -->
              <el-input
                v-else-if="isEditing(row.id, col.key)"
                v-model="draftVal"
                size="small"
                autofocus
                @keyup.enter="commit(row.id, col.key, draftVal)"
              />

              <!-- 显示态 -->
              <template v-else>
                <span class="txt" :class="{ empty: !cellValue(row, col.key) }">
                  {{ cellValue(row, col.key) || '—' }}
                </span>
                <el-icon v-if="isSaving(row.id, col.key)" class="spin"><Loading /></el-icon>
                <span v-else-if="justSaved(row.id, col.key)" class="ok-mark">已存</span>
              </template>
            </td>
          </tr>
          <tr v-if="!rows.length && !loading">
            <td class="empty-row" :colspan="columns.length + 2">
              <template v-if="canAddField">
                还没有学生。可以点右上角<strong>「导入 Excel」</strong>一次导入整份名单，
                也可以点<strong>「新增学生」</strong>逐个添加。
              </template>
              <template v-else>没有可显示的学生信息</template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p class="foot">
      <template v-if="canEdit">
        单击格子修改，回车或移开自动保存 · Tab 跳下一格 · Delete 清空该格 · Esc 取消
      </template>
      <template v-if="canAddField" class="foot-tip">
        · 点列名可改名，点类型小标签可改类型；鼠标移到列名上会出现 ＋ 和 ✕，
        ＋ 在这一列前面插入新字段（想在末尾加就点最后一列的），✕ 停用该字段
      </template>
      <template v-else-if="perm?.isGuest">
        <!-- 访客只看不改，也没有申请渠道（他的只读权限是角色内建的），
             说「找班主任申请」是骗他 -->
        访客只可查看，不可修改
      </template>
      <template v-else>当前为只读，如需修改请向班主任申请</template>
    </p>

    <!-- 新增字段：就地小浮层，不是另开一个抽屉 -->
    <el-dialog
      v-model="insertOpen"
      :title="`在「${insertAnchorLabel}」前面插入字段`"
      width="380px"
      append-to-body
    >
      <el-form label-width="64px" @submit.prevent="submitInsert">
        <el-form-item label="名称">
          <el-input
            v-model="insertLabel"
            placeholder="如「宿舍号」"
            maxlength="64"
            autofocus
            @keyup.enter="submitInsert"
          />
        </el-form-item>
        <el-form-item label="类型">
          <el-radio-group v-model="insertType">
            <el-radio-button
              v-for="t in TYPE_OPTIONS"
              :key="t.value"
              :value="t.value"
            >
              {{ t.label }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="insertOpen = false">取消</el-button>
        <el-button type="primary" :loading="inserting" @click="submitInsert">
          插入
        </el-button>
      </template>
    </el-dialog>

    <!-- 班主任的审批收件箱与授权清单。审批后要刷新表格：被授权的同学可能立刻多出可见行 -->
    <StudentApprovalDrawer v-model="approvalOpen" @handled="onApprovalHandled" />

    <!-- 导出：行范围 + 选列 -->
    <el-dialog v-model="exportOpen" title="导出学生信息" width="620px" append-to-body>
      <el-form label-width="64px">
        <el-form-item label="行">
          <el-radio-group v-model="exportRowScope">
            <el-radio :value="'all'" :disabled="!selectedIds.length">
              全部可见（{{ rows.length }} 人）
            </el-radio>
            <el-radio :value="'selected'" :disabled="!selectedIds.length">
              已勾选（{{ selectedIds.length }} 人）
            </el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="列">
          <div class="col-picker">
            <div class="col-picker-bar">
              <el-input
                v-model="exportFieldFilter"
                size="small"
                placeholder="搜索字段名"
                clearable
              />
              <el-button size="small" @click="selectAllFields">全选</el-button>
              <el-button size="small" @click="exportFields = []">清空</el-button>
            </div>
            <el-checkbox
              v-for="c in anchorColumns"
              :key="c.key"
              :model-value="true"
              disabled
              class="col-item"
            >
              {{ c.label }}<span class="col-lock">必选</span>
            </el-checkbox>
            <el-checkbox
              v-for="c in exportFieldSearch"
              :key="c.key"
              :model-value="exportFields.includes(c.key)"
              class="col-item"
              @change="toggleExportField(c.key)"
            >
              {{ c.label }}
            </el-checkbox>
            <p v-if="!exportFieldSearch.length && exportFieldFilter" class="col-none">
              没有叫「{{ exportFieldFilter }}」的字段
            </p>
          </div>
        </el-form-item>
      </el-form>

      <p class="export-preview">
        将导出 <strong>{{ exportRowCount }}</strong> 名学生 ×
        <strong>{{ exportColumnKeys.length }}</strong> 列
      </p>

      <template #footer>
        <el-button @click="exportOpen = false">取消</el-button>
        <el-button
          type="primary"
          :loading="exportingSelected"
          :disabled="exportColumnKeys.length < 2"
          @click="submitExport"
        >
          导出
        </el-button>
      </template>
    </el-dialog>

    <!-- 新增一行：只要学号 + 姓名 -->
    <el-dialog
      v-model="addOpen"
      title="新增学生"
      width="420px"
      append-to-body
      @closed="addNo = ''; addName = ''"
    >
      <el-form label-width="56px" @submit.prevent="submitAdd">
        <el-form-item label="学号" required :error="addNoDup ? `学号 ${addNo.trim()} 已经在表里了` : ''">
          <el-input
            v-model="addNo"
            placeholder="如 20230105"
            maxlength="32"
            autofocus
            @keyup.enter="submitAdd"
          />
        </el-form-item>
        <el-form-item label="姓名" required>
          <el-input
            v-model="addName"
            placeholder="如 王浩然"
            maxlength="32"
            @keyup.enter="submitAdd"
          />
        </el-form-item>
      </el-form>
      <p class="add-hint">
        学号和姓名必填——它们决定这一行是谁。其余信息加完在表格里点格子填就行。
        <br />
        这里<strong>不会</strong>给对方开登录账号；要让同学登录，需要到「成员管理」单独建账号。
      </p>
      <template #footer>
        <el-button @click="addOpen = false">取消</el-button>
        <el-button type="primary" :loading="addSaving" @click="submitAdd">添加</el-button>
      </template>
    </el-dialog>

    <!-- 改字段类型：先看预览（会动已存的值），再确认 -->
    <el-dialog
      v-model="retypeOpen"
      :title="retypeCol ? `改「${retypeCol.label}」的类型` : '改类型'"
      width="520px"
      append-to-body
      @closed="retypeCol = null"
    >
      <el-form label-width="64px">
        <el-form-item label="改成">
          <el-radio-group v-model="retypeTo" @change="loadRetypePreview">
            <el-radio-button
              v-for="t in TYPE_OPTIONS"
              :key="t.value"
              :value="t.value"
              :disabled="retypeCol?.type === t.value"
            >
              {{ t.label }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>

      <div v-loading="retypeLoading" class="retype-body">
        <p v-if="retypeCol" class="retype-current">
          当前类型：<strong>{{ TYPE_OPTIONS.find((t) => t.value === retypeCol?.type)?.label }}</strong>
          <span v-if="retypeChanged" class="retype-arrow">→</span>
          <strong v-if="retypeChanged" class="retype-new">
            {{ TYPE_OPTIONS.find((t) => t.value === retypeTo)?.label }}
          </strong>
        </p>

        <el-alert
          v-if="!retypeChanged"
          type="info"
          :closable="false"
          show-icon
          title="换个别的类型看看会改动哪些值"
          description="列的类型是导入时按这一列的取值自动判断的。整列都是 20250901 这种才认成日期，只要有一格不是（比如写着「待定」）就按文本处理。猜错了在这里改。"
        />

        <template v-else-if="retypePreview">
          <p class="retype-note">
            这一列共有 {{ retypePreview.total }} 个值，改类型后会同步转换已填的内容：
          </p>

          <div v-if="retypePreview.convertibleCount" class="retype-block">
            <div class="retype-block-head ok">
              {{ retypePreview.convertibleCount }} 个可以转换
            </div>
            <ul class="retype-samples">
              <li v-for="(s, i) in retypePreview.convertibleSamples" :key="'c' + i">
                <span class="s-before">{{ s.before }}</span>
                <span class="s-arrow">→</span>
                <span class="s-after">{{ s.after }}</span>
              </li>
              <li v-if="retypePreview.convertibleTruncated" class="more">
                …另有 {{ retypePreview.convertibleTruncated }} 个
              </li>
            </ul>
          </div>

          <div v-if="retypePreview.unconvertibleCount" class="retype-block">
            <div class="retype-block-head warn">
              {{ retypePreview.unconvertibleCount }} 个转不了
            </div>
            <ul class="retype-samples">
              <li v-for="(s, i) in retypePreview.unconvertibleSamples" :key="'u' + i">
                <span class="s-before">{{ s.before }}</span>
              </li>
              <li v-if="retypePreview.unconvertibleTruncated" class="more">
                …另有 {{ retypePreview.unconvertibleTruncated }} 个
              </li>
            </ul>
            <el-radio-group v-model="retypeClearBad" class="retype-choice">
              <el-radio :value="false">原样保留（改回来时数据还在）</el-radio>
              <el-radio :value="true">清空这些值</el-radio>
            </el-radio-group>
          </div>

          <p v-if="retypePreview.emptyCount" class="retype-empty">
            另有 {{ retypePreview.emptyCount }} 个空值（未填），不受影响。
          </p>
          <p v-else-if="retypeNeedChoice" class="retype-empty">
            没有空值。这一列每一格都填了东西。
          </p>
        </template>
      </div>

      <template #footer>
        <el-button @click="retypeOpen = false">取消</el-button>
        <el-button
          type="primary"
          :loading="retypeApplying"
          :disabled="!retypeChanged || retypeLoading"
          @click="submitRetype"
        >
          确认改类型
        </el-button>
      </template>
    </el-dialog>

    <!-- 已停用字段：软删的值还在这里，可以一键恢复 -->
    <el-dialog v-model="trashOpen" title="已停用的字段" width="560px" append-to-body>
      <p class="trash-hint">
        停用只是把这一列从表格和导出里收起来，<strong>已填的值一行都没删</strong>。
        点「恢复」放回表格，数据原样还在。
      </p>
      <el-table v-loading="trashLoading" :data="disabledFields" size="small">
        <el-table-column prop="label" label="字段名" />
        <el-table-column prop="typeText" label="类型" width="90" />
        <el-table-column label="来源" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="row.isSystem ? 'info' : 'success'" disable-transitions>
              {{ row.isSystem ? '模板预置' : '自定义' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" align="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="restoreField(row)">恢复</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <p class="trash-empty">没有被停用的字段</p>
        </template>
      </el-table>
      <template #footer>
        <el-button @click="trashOpen = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 一键创建账号：先把「会动到谁」摊开给老师看，确认了再动手 -->
    <el-dialog v-model="accOpen" title="按学生信息创建账号" width="640px" append-to-body>
      <div v-loading="accLoading">
        <template v-if="accPlan && !accPlan.executed">
          <p class="acc-lead">
            本班共 <strong>{{ accPlan.total }}</strong> 行学生信息，将
            <strong>{{ accPlan.toCreate }}</strong> 个新建账号、<strong>{{ accPlan.toLink }}</strong> 个
            挂到已有账号上、<strong>{{ accPlan.toSkip }}</strong> 行跳过。
          </p>
          <p class="acc-lead">
            登录名用<strong>学号</strong>，昵称用<strong>姓名</strong>，角色一律
            <strong>普通成员</strong>，初始密码统一
            <strong class="acc-pw">{{ accPlan.initialPassword }}</strong>
            —— 请告诉学生首次登录后去「个人信息」改成自己的密码。
          </p>

          <el-alert
            v-if="accPlan.toLink > 0"
            type="info"
            show-icon
            :closable="false"
            title="这些行已经有账号了，不会重复创建"
            description="会直接把学生信息行挂到那个账号上，学生登录后就能看到自己那一行。"
          />

          <div v-if="accPlan.toCreateList.length" class="acc-skip">
            <p class="acc-skip-title">将要新建（{{ accPlan.toCreateList.length }}）</p>
            <ul>
              <li v-for="c in accPlan.toCreateList" :key="c.studentNo">
                <span class="acc-sno">{{ c.studentNo }}</span>
                <span class="acc-name">{{ c.name }}</span>
              </li>
            </ul>
          </div>

          <div v-if="accPlan.linked.length" class="acc-skip">
            <p class="acc-skip-title">挂接到已有账号（{{ accPlan.linked.length }}）</p>
            <ul>
              <li v-for="l in accPlan.linked" :key="l.userId">
                <span class="acc-sno">{{ l.studentNo }}</span>
                <span class="acc-name">{{ l.name }}</span>
                <span class="acc-why">
                  挂到账号「{{ l.username }}」上{{ l.backfilled ? '，并补上它空着的学号' : '' }}
                </span>
              </li>
            </ul>
          </div>

          <div v-if="accPlan.skipped.length" class="acc-skip">
            <p class="acc-skip-title">跳过的行（{{ accPlan.skipped.length }}）</p>
            <ul>
              <li v-for="(s, i) in accPlan.skipped" :key="i">
                <span class="acc-sno">{{ s.studentNo }}</span>
                <span class="acc-name">{{ s.name }}</span>
                <span class="acc-why">{{ s.reason }}</span>
              </li>
            </ul>
          </div>

          <p v-if="accNothingToDo" class="acc-lead">
            没有需要新建或挂接的行——名单上的账号都已经建好了。
          </p>
        </template>

        <template v-else-if="accPlan && accPlan.executed">
          <p class="acc-lead">
            完成：新建 <strong>{{ accPlan.created.length }}</strong> 个账号<template v-if="accPlan.linked.length">、挂接 {{ accPlan.linked.length }} 个</template
            ><template v-if="accPlan.skipped.length">、跳过 {{ accPlan.skipped.length }} 行</template>。
          </p>
          <div v-if="accPlan.created.length" class="acc-skip">
            <p class="acc-skip-title">新建的账号</p>
            <ul>
              <li v-for="c in accPlan.created" :key="c.id">
                <span class="acc-sno">{{ c.username }}</span>
                <span class="acc-name">{{ c.realName }}</span>
              </li>
            </ul>
          </div>
          <div v-if="accPlan.linked.length" class="acc-skip">
            <p class="acc-skip-title">挂接到已有账号</p>
            <ul>
              <li v-for="l in accPlan.linked" :key="l.userId">
                <span class="acc-sno">{{ l.studentNo }}</span>
                <span class="acc-name">{{ l.name }}</span>
                <span class="acc-why">{{ l.backfilled ? '已挂接，并补上了这个账号空着的学号' : '已挂接' }}</span>
              </li>
            </ul>
          </div>
        </template>
      </div>
      <template #footer>
        <el-button @click="accOpen = false">关闭</el-button>
        <el-button
          v-if="accPlan && !accPlan.executed"
          type="primary"
          :loading="accDoing"
          :disabled="accNothingToDo || accPlan.toCreate + accPlan.toLink === 0"
          @click="submitAccounts"
        >
          创建 {{ accPlan.toCreate + accPlan.toLink }} 个
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

h2 {
  margin: 0;
  font-size: 20px;
}

.sub {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--color-muted-fg);
}

.actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.file-btn {
  display: inline-flex;
}

/* 「更多」按钮上的红点：有待审批时提示「⋯ 里有事要办」。
   不用 el-badge 是因为角标要占位、会把这个按钮顶偏，这里只需要一个点 */
.actions .has-pending {
  position: relative;
}

.actions .has-pending::after {
  content: '';
  position: absolute;
  top: 4px;
  right: 6px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-expense);
  box-shadow: 0 0 0 2px var(--color-bg);
}

.more-caret {
  margin-left: 2px;
}

/* 菜单项右侧的待审批数 */
.pending-count {
  margin-left: 6px;
  padding: 0 6px;
  border-radius: 8px;
  background: var(--color-expense);
  color: #fff;
  font-size: 11px;
  line-height: 16px;
}

/* ---------- 改类型对话框 ---------- */
/* ---------- 导出对话框 ---------- */
.add-hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--color-muted-fg);
}
.col-picker {
  width: 100%;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 10px;
  max-height: 320px;
  overflow: auto;
}

.col-picker-bar {
  display: flex;
  gap: 6px;
  align-items: center;
  margin-bottom: 8px;
}

.col-item {
  margin-right: 0;
  width: 100%;
}

.col-lock {
  margin-left: 6px;
  font-size: 11px;
  color: var(--color-muted-fg);
}

.col-none {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--color-muted-fg);
}

.export-preview {
  margin: 0;
  padding-top: 4px;
  font-size: 13px;
  color: var(--color-muted-fg);
}

.export-preview strong {
  color: var(--el-color-primary);
  font-size: 15px;
}
.retype-body {
  min-height: 60px;
}

.retype-current {
  margin: 0 0 10px;
  font-size: 13px;
}

.retype-arrow {
  margin: 0 6px;
  color: var(--color-muted-fg);
}

.retype-new {
  color: var(--el-color-primary);
}

.retype-note {
  margin: 0 0 10px;
  font-size: 13px;
  color: var(--color-muted-fg);
}

.retype-block {
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 10px;
}

.retype-block-head {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
}

.retype-block-head.ok {
  color: var(--el-color-success);
}

.retype-block-head.warn {
  color: var(--el-color-warning);
}

.retype-samples {
  margin: 0;
  padding: 0 0 0 4px;
  list-style: none;
  font-size: 12px;
  color: var(--color-muted-fg);
  max-height: 150px;
  overflow: auto;
}

.retype-samples li {
  padding: 1px 0;
}

.retype-samples .s-before {
  color: var(--color-text-1);
}

.retype-samples .s-arrow {
  margin: 0 6px;
}

.retype-samples .s-after {
  color: var(--el-color-success);
  font-weight: 600;
}

.retype-samples .more {
  color: var(--color-muted-fg);
  font-style: italic;
}

.retype-choice {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.retype-empty {
  margin: 0;
  font-size: 12px;
  color: var(--color-muted-fg);
}

.trash-hint {
  margin: 0 0 12px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--color-muted-fg);
}

/* 一键建账号对话框 */
.acc-lead {
  margin: 0 0 10px;
  font-size: 13px;
  line-height: 1.7;
}

/* 初始密码要比周围字重一点：老师要照着它告诉学生，不能淹没在段落里 */
.acc-pw {
  font-family: var(--font-mono, monospace);
  font-size: 15px;
  letter-spacing: 0.5px;
}

.acc-skip {
  margin-top: 12px;
  padding: 10px 12px;
  background: rgba(0, 0, 0, 0.03);
  border-radius: 6px;
  max-height: 190px;
  overflow-y: auto;
}

.acc-skip-title {
  margin: 0 0 6px;
  font-size: 12px;
  color: var(--color-muted-fg);
}

.acc-skip ul {
  margin: 0;
  padding: 0;
  list-style: none;
}

.acc-skip li {
  display: flex;
  gap: 10px;
  font-size: 12px;
  line-height: 1.9;
}

.acc-sno {
  flex: none;
  width: 130px;
  font-family: var(--font-mono, monospace);
}

.acc-name {
  flex: none;
  width: 88px;
}

.acc-why {
  flex: 1;
  color: var(--color-muted-fg);
}

.trash-empty {
  margin: 12px 0;
  text-align: center;
  color: var(--color-muted-fg);
  font-size: 13px;
}

.apply-bar {
  border: 1px solid var(--color-border);
  border-radius: 10px;
  padding: 12px 14px;
  background: #f7f9fc;
}

.apply-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
}

.apply-list {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.apply-btn {
  display: flex;
  flex-direction: column;
  gap: 2px;
  align-items: flex-start;
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  text-align: left;
  font: inherit;
}

.apply-btn:hover {
  border-color: var(--el-color-primary);
}

.apply-btn strong {
  font-size: 13px;
}

.apply-btn small {
  font-size: 12px;
  color: var(--color-muted-fg);
}

.notice {
  margin: 0;
}

/* ---------- 表格 ---------- */
.grid-wrap {
  border: 1px solid var(--color-border);
  border-radius: 10px;
  overflow: auto;
  max-height: calc(100vh - 300px);
  background: #fff;
}

.grid {
  border-collapse: separate;
  border-spacing: 0;
  width: max-content;
  min-width: 100%;
  font-size: 13px;
}

.grid th,
.grid td {
  border-right: 1px solid var(--color-border);
  border-bottom: 1px solid var(--color-border);
  padding: 0;
  text-align: left;
  vertical-align: middle;
}

.grid thead th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: #f5f7fa;
  font-weight: 600;
  white-space: nowrap;
}

.corner,
.row-no {
  width: 44px;
  min-width: 44px;
  text-align: center;
  color: var(--color-muted-fg);
  background: #f5f7fa;
  position: sticky;
  left: 0;
  z-index: 1;
}

/* 勾选列并进行号列：单独加一列会把表格整体右移，白白多一列宽度。
   宽度放宽到 64px 容纳「勾选框 + 序号」，序号退成次要信息。 */
.corner.pick,
.row-no.pick {
  width: 64px;
  min-width: 64px;
}

.row-no.pick {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.row-idx {
  font-size: 11px;
}

/* 勾中的行淡蓝底：导出选中的时候得一眼看出要带走哪几行 */
.grid tbody tr.picked td {
  background: var(--el-color-primary-light-9);
}

.corner {
  z-index: 3;
}

.col-head {
  min-width: 140px;
  padding: 0 8px !important;
}

.col-inner {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 0;
}

.col-label {
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.col-type {
  font-size: 10px;
  color: var(--color-muted-fg);
  border: 1px solid var(--color-border);
  border-radius: 3px;
  padding: 0 3px;
  line-height: 15px;
}

.col-ops {
  display: flex;
  gap: 2px;
  margin-left: auto;
  /* 悬停当前列才显示（用户口径）。表格列名一行几十个，
     按钮常驻会把「字段名 / 类型」这层信息冲得七零八落。 */
  opacity: 0;
}

.col-head:hover .col-ops {
  opacity: 1;
}

/* 键盘可达性：Tab 聚焦到某列时也得显出来，不然纯键盘用户永远看不到 ＋ */
.col-head:focus-within .col-ops {
  opacity: 1;
}

.mini {
  border: 1px solid var(--color-border);
  background: #fff;
  border-radius: 4px;
  width: 20px;
  height: 20px;
  line-height: 1;
  cursor: pointer;
  font-size: 12px;
  padding: 0;
}

/* 列名 / 类型小标签：能改的时候给出可点的暗示。
   跟格子的 hover 高亮同一套视觉语言——「这里能点开改」应该长得一样。 */
.col-label.editable,
.col-type.editable {
  cursor: text;
  border-radius: 3px;
  padding: 0 3px;
  margin: 0 -3px;
}

.col-type.editable {
  cursor: pointer;
}

.col-head:hover .col-label.editable,
.col-label.editable:hover,
.col-type.editable:hover {
  background: var(--el-color-primary-light-9);
  box-shadow: inset 0 0 0 1px var(--el-color-primary-light-5);
}

.col-rename {
  width: 100%;
  max-width: 150px;
}

.mini:hover {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
}

.mini.danger:hover {
  border-color: var(--el-color-danger);
  color: var(--el-color-danger);
}

/* ---------- 单元格 ---------- */
.cell {
  padding: 0 8px !important;
  min-width: 140px;
  max-width: 260px;
  height: 34px;
  cursor: cell;
  position: relative;
  /* 单元格要能接住 Delete 键，就得能拿到焦点；outline 用 inset 不影响表格线 */
  outline: none;
}

.cell:focus-visible {
  box-shadow: inset 0 0 0 2px var(--el-color-primary);
}

.cell.readonly {
  cursor: default;
}

.cell:not(.readonly):hover {
  box-shadow: inset 0 0 0 1px var(--el-color-primary-light-5);
}

.cell.editing {
  padding: 3px 4px !important;
  box-shadow: inset 0 0 0 2px var(--el-color-primary);
  background: #fff;
  z-index: 1;
}

.cell.editing :deep(.el-input),
.cell.editing :deep(.el-select),
.cell.editing :deep(.el-date-editor) {
  width: 100%;
}

.txt {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.txt.empty {
  color: #c0c4cc;
}

.ok-mark {
  position: absolute;
  right: 4px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 10px;
  color: var(--el-color-success);
  background: #fff;
  padding: 0 2px;
}

.cell.saved {
  background: #f0f9eb;
}

.spin {
  position: absolute;
  right: 4px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 12px;
  color: var(--el-color-primary);
}

.empty-row {
  padding: 24px !important;
  text-align: center;
  color: var(--color-muted-fg);
}

.foot {
  margin: 0;
  font-size: 12px;
  color: var(--color-muted-fg);
}
</style>