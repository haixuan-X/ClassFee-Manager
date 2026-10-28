<script setup lang="ts">
/**
 * 学院学生信息 —— **照班级「学生信息」那一套做**（第三十一轮重做）。
 *
 * ## 为什么整页推翻
 *
 * 这一页原来是一张 **Handsontable 电子表格**：框选、复制粘贴、冻结列、
 * 右击列头菜单、快捷键面板……功能确实全，但**太重**：
 *
 * - 一上来是一片「Excel 的界面」，要先理解「什么是列菜单」才能改一个格子；
 * - 页头常年挂着十几个按钮、右侧一块筛选区，一眼看不到「这张表是干什么的」；
 * - 改一格要走「双击 → 输入 → 回车 → 等请求」，和班级页那种「点一下就改」
 *   完全不是一个手感。
 *
 * 用户口径是「**按班级学生信息界面那样做**」。所以这里不是"加功能"，
 * 而是**换一种做法**：手写 `<table>`，点格子就改、回车就存，
 * 列名点一下能改名，交互 / 文案 / 样式全部对齐班级页。
 *
 * 学院版只多四件事：
 *
 * 1. **多一个「班级」列**（只读——转班是另一个操作，不能当成改一格）
 * 2. **跨班级筛选**（关键字 / 班级 / 年级）
 * 3. **分页**（全校几千人，一次全渲染会卡）
 * 4. **列的操作对所有班生效**（学院只有一份表）
 *
 * ## 「年级」这一列为什么特殊
 *
 * 表格里的年级显示的是**有效年级**：学生自己填的 `grade` 字段值优先，
 * 没填才回退到**班级**的年级（和年级筛选同一个口径）。
 *
 * 所以它**不是**一个普通的字段列：
 * - 显示值可能和 `grade` 字段的值不一样（没填的学生显示的是班级年级）
 * - 因此不能拿字段列那套「改名 / 改类型 / 停用」套上去
 * - 而 `grade` 字段本身**不再单独出列**——两列都叫「年级」比少一个管理入口更糟
 *
 * 编辑年级 = 写 `grade` 字段的值（后端在那个班还没有这一列时会就地补建）。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, Delete } from '@element-plus/icons-vue'
import {
  applyCollegeFieldRetype,
  createCollegeField,
  deleteCollegeField,
  deleteCollegeStudents,
  downloadCollegeStudentTemplate,
  exportCollegeStudents,
  fetchCollegeDisabledFields,
  fetchCollegeStudents,
  importCollegeStudents,
  previewCollegeFieldRetype,
  purgeCollegeField,
  restoreCollegeField,
  updateCollegeCell,
  updateCollegeField,
} from '@/api/college'
import { getErrorMessage } from '@/api/request'
import type {
  CollegeClassChoice,
  CollegeRetypePreview,
  CollegeStudentColumn,
  CollegeStudentList,
  CollegeStudentRow,
  StudentFieldType,
} from '@/types'

/** 学生「年级」字段的机器名 */
const GRADE_FIELD_KEY = 'grade'

// ==================== 数据 ====================

const loading = ref(true)
const importing = ref(false)
const list = ref<CollegeStudentList | null>(null)

const rows = computed<CollegeStudentRow[]>(() => list.value?.rows ?? [])
/** 库里定义的列（各班按 field_key 合并成一份） */
const allColumns = computed<CollegeStudentColumn[]>(() => list.value?.columns ?? [])
const total = computed(() => list.value?.total ?? 0)
/** 总页数（PageUp / PageDown 翻页用） */
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / size.value)))
const classes = computed<CollegeClassChoice[]>(() => list.value?.classes ?? [])

/**
 * 筛选下拉里只列**有学生**的班。
 *
 * 一个班一个人都没有（名单还没导进去）时，选下去必然是 0 人——
 * 那不是「筛选坏了」，是「这里本来就没东西」。这种班不占筛选的位置。
 *
 * ⚠ 导入时的「进哪个班」选择器**列全部班**（那里恰恰要选一个空班）。
 */
const classesWithStudents = computed(() =>
  classes.value.filter((c) => (c.students ?? 0) > 0),
)
const grades = computed<string[]>(() => list.value?.grades ?? [])

// ==================== 筛选 ====================

const keyword = ref('')
const classId = ref<number | null>(null)
const grade = ref('')
const page = ref(1)
const size = ref(50)

/** 已经生效的筛选条件 */
const applied = ref<{ keyword: string; classId: number | null; grade: string }>({
  keyword: '',
  classId: null,
  grade: '',
})

/** 界面上现在有筛选（用来区分「库里没人」和「筛完没人」） */
const hasFilter = computed(
  () =>
    !!applied.value.keyword ||
    applied.value.classId !== null ||
    !!applied.value.grade,
)

function search() {
  applied.value = {
    keyword: keyword.value.trim(),
    classId: classId.value,
    grade: grade.value,
  }
  page.value = 1
  void load()
}

function reset() {
  keyword.value = ''
  classId.value = null
  grade.value = ''
  applied.value = { keyword: '', classId: null, grade: '' }
  page.value = 1
  void load()
}

async function load() {
  loading.value = true
  try {
    const data = await fetchCollegeStudents({
      keyword: applied.value.keyword,
      classId: applied.value.classId,
      grade: applied.value.grade,
      page: page.value,
      size: size.value,
    })
    list.value = data
    // 刷新后清掉已经不存在的勾选（翻页/筛选后原来选的人可能不在这一页了）
    const alive = new Set(data.rows.map((r) => r.id))
    selectedIds.value = selectedIds.value.filter((id) => alive.has(id))
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '读取学生名册失败'))
    list.value = null
  } finally {
    loading.value = false
  }
}

watch([page, size], () => void load())

onMounted(() => {
  // 全局快捷键（撤销/重做）：挂在 window 上，焦点在哪儿都能用
  window.addEventListener('keydown', onGlobalKeydown, true)
  void load()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onGlobalKeydown, true)
})

// ==================== 列 ====================

/**
 * 表格里的一列。
 *
 * `field` 表示它是**真的字段**（能改名 / 改类型 / 停用 / 插列）；
 * 固定列（学号 / 姓名 / 班级 / 年级）不是字段。
 */
interface CollegeCol {
  /** 表格里的列标识。固定列是 `__no__` / `__name__` / `__class__` / `__grade__` */
  key: string
  label: string
  type: StudentFieldType
  /** 是不是真的字段 */
  field: boolean
  /** 只读（班级） */
  readonly?: boolean
}

/**
 * 库里定义的列（**去掉 grade**——它由固定的「年级」列代表，
 * 否则表里会有两列都叫「年级」）。
 */
const fieldColumns = computed<CollegeStudentColumn[]>(
  () => allColumns.value.filter((c) => c.key !== GRADE_FIELD_KEY),
)

/**
 * 这一批学生里**有数据**的列（后端按**整个筛选结果**算，不是当前页，
 * 所以翻页时列不会忽多忽少）。
 *
 * 只用在**导出对话框**里（默认不勾没数据的列——导出的表里一片空白列没人要）。
 * 表格本身**照常显示全部列**：少一列就多一份「我记忆里明明有这一列」的困惑，
 * 而空列一眼就看得出是空的（显示「—」），不占多少地方。
 */
const populatedKeys = computed(() => new Set(list.value?.populatedKeys ?? []))

/**
 * 表格的列序 = **学号 | 姓名 | 班级 | 年级 | 各字段列**。
 */
const columns = computed<CollegeCol[]>(() => {
  const gradeCol = allColumns.value.find((c) => c.key === GRADE_FIELD_KEY)
  const out: CollegeCol[] = [
    { key: '__no__', label: '学号', type: 'TEXT', field: false },
    { key: '__name__', label: '姓名', type: 'TEXT', field: false },
    { key: '__class__', label: '班级', type: 'TEXT', field: false, readonly: true },
    { key: '__grade__', label: '年级', type: gradeCol?.type ?? 'TEXT', field: false },
  ]
  for (const c of fieldColumns.value) {
    out.push({ key: c.key, label: c.label, type: c.type, field: true })
  }
  return out
})

/**
 * 这一列能不能进编辑态。
 *
 * 「班级」**能**改（点开是选班的下拉，选中即改）。
 * 但它不能用 Delete 清空——班级不能是空的（见 `clearCell`）。
 */
function isEditableCol(_k: string): boolean {
  return true
}

// ==================== 就地编辑 ====================

/** 正在编辑的格子：key = `${recordId}:${columnKey}` */
const editKey = ref<string | null>(null)
/** 正在保存的格子（转圈指示） */
const savingKey = ref<string | null>(null)
/** 最近一次保存的时间戳，用于闪一下「已存」 */
const savedKey = ref<string | null>(null)
const savedAt = ref(0)

const ckey = (recordId: number, colKey: string) => `${recordId}:${colKey}`

/**
 * 正在编辑的那格的输入框（用来自动聚焦）。
 *
 * ## 为什么必须自己聚焦
 *
 * `<el-input autofocus>` **不管用**：`autofocus` 会作为**普通属性**落到
 * el-input 的根元素（那个 wrapper div）上，而不是里面的原生 `<input>`；
 * 而且原生 autofocus 只在「元素插入文档时」生效一次，对动态插入的编辑框
 * 更是指望不上。
 *
 * 后果很直接：点一下格子，输入框出来了，但**焦点还在 body 上**——
 * 用户接着打字，什么都没进去。「点一下怎么编辑不了」就是这么来的。
 */
const editorRef = ref<{ focus?: () => void } | null>(null)

/** 编辑框挂上来就聚焦（否则用户还得再点一次才能打字） */
function bindEditor(el: unknown, id: number, k: string) {
  if (!el || !isEditing(id, k)) return
  editorRef.value = el as { focus?: () => void }
  void nextTick(() => editorRef.value?.focus?.())
}

/** 编辑态里输入框绑的值。每次进入编辑态由 startEdit 复位 */
const draftVal = ref('')
/**
 * 进入编辑态时的**原值**。
 *
 * 用来判断「用户在这个输入框里敲过字没有」——
 * 决定 Ctrl+Z 是「撤销刚敲的字」（原生）还是「撤销上一步保存」（我们的）。
 */
const editStartVal = ref('')

const isEditing = (id: number, k: string) => editKey.value === ckey(id, k)
const isSaving = (id: number, k: string) => savingKey.value === ckey(id, k)
const justSaved = (id: number, k: string) =>
  savedKey.value === ckey(id, k) && Date.now() - savedAt.value < 1600

/** 这一格的显示值。固定列的值不在 `values` 里，得单独取。 */
function cellValue(row: CollegeStudentRow, k: string): string {
  if (k === '__no__') return row.studentNo ?? ''
  if (k === '__name__') return row.name ?? ''
  if (k === '__class__') return row.className ?? ''
  if (k === '__grade__') return row.grade ?? ''
  return row.values?.[k] ?? ''
}

function startEdit(id: number, k: string) {
  // 已经在编辑这一格就直接返回：td 的 click 会冒泡，输入框里点一下挪光标
  // 也会触发，不挡住的话 draftVal 会被重置回旧值，用户刚敲的字就没了。
  if (editKey.value === ckey(id, k)) return
  if (!isEditableCol(k)) return
  const row = rows.value.find((r) => r.id === id)
  if (!row) return
  draftVal.value = cellValue(row, k)
  editStartVal.value = draftVal.value
  editKey.value = ckey(id, k)
}

/**
 * 点格子的统一入口。
 *
 * 每一列都是同一个手感：**点一下 → 出一个输入框 → 打字 → 回车保存**。
 * 班级那一列也不例外（输入的是**班级名**，回车后转到那个班；
 * 库里没这个班就自动建一个）。
 */
function onCellClick(row: CollegeStudentRow, col: CollegeCol) {
  startEdit(row.id, col.key)
}

/**
 * 在格间移动编辑位置（Excel 手感的关键部分）。
 *
 * `dr` / `dc` 是**行/列**的位移：`(0,1)` 右移一格、`(1,0)` 下移一行、
 * `(-1,0)` 上移一行、`(0,-1)` 左移一格。
 *
 * 到头就**退出编辑态**（而不是绕回第一格）——Excel 也是这样，
 * 绕回去会让人以为「怎么又回到第一格了」。
 */
function moveEdit(id: number, k: string, dr: number, dc: number) {
  const rowIdx = rows.value.findIndex((r) => r.id === id)
  if (rowIdx < 0) return
  const colIdx = columns.value.findIndex((c) => c.key === k)
  if (colIdx < 0) return
  const nr = rowIdx + dr
  const nc = colIdx + dc
  if (nr < 0 || nr >= rows.value.length || nc < 0 || nc >= columns.value.length) {
    editKey.value = null
    return
  }
  const row = rows.value[nr]
  const nk = columns.value[nc].key
  draftVal.value = cellValue(row, nk)
  editStartVal.value = draftVal.value
  editKey.value = ckey(row.id, nk)
}

/**
 * 把一个值写进去（**真正落库**的那一步）。
 *
 * 「提交」和「撤销」都要用它——区别只是撤销时**不再记一条撤销记录**。
 */
async function applyValue(
  row: CollegeStudentRow,
  k: string,
  value: string,
): Promise<boolean> {
  if (k === '__name__') {
    await updateCollegeCell(row.id, {}, { name: value })
    row.name = value
  } else if (k === '__no__') {
    await updateCollegeCell(row.id, {}, { studentNo: value })
    row.studentNo = value
  } else if (k === '__class__') {
    // 班级：按名字改。后端会把他那些值**按列名搬到新班**（一个不丢），
    // 库里没这个班就自动建一个（和导入一个规矩）。
    const r = await updateCollegeCell(row.id, {}, { className: value })
    row.className = r.className || row.className
    await load()
  } else if (k === '__grade__') {
    await updateCollegeCell(row.id, { [GRADE_FIELD_KEY]: value })
    row.values = { ...row.values, [GRADE_FIELD_KEY]: value }
    // 「年级」这一列显示的是**有效年级**：填了值就以填的为准
    row.grade = value
  } else {
    await updateCollegeCell(row.id, { [k]: value })
    row.values = { ...row.values, [k]: value }
  }
  return true
}

/** 这一列在界面上叫什么（撤销提示里用） */
function columnTitle(k: string): string {
  return columns.value.find((c) => c.key === k)?.label ?? k
}

/**
 * 提交一格。
 *
 * 四个固定列落在**四个不同的地方**：
 *
 * | 列 | 落在哪 | 怎么传 |
 * |----|--------|--------|
 * | 学号 | `student_record.student_no` | `studentNo`（同班不能撞号） |
 * | 姓名 | `student_record.name` | `name` |
 * | 班级 | 学生的**归属** | `className`（按名字；没有就自动建班） |
 * | 年级 | `grade` 字段的值 | `values['grade']` |
 * | 其它 | 该班对应字段的值 | `values[字段标识]` |
 *
 * `undoable=false` 是**撤销/重做**自己用的：它们要写回去，但**不能再记一条
 * 撤销记录**（否则按一次 Ctrl+Z 会又攒出一条新的，撤销就永远停不下来）。
 */
async function commit(
  id: number,
  k: string,
  raw: string | null,
  undoable = true,
): Promise<boolean> {
  const row = rows.value.find((r) => r.id === id)
  if (!row) return false
  // 只在「关的就是当前这一格」时才退出编辑态。
  const ck = ckey(id, k)
  if (editKey.value === ck) editKey.value = null
  const before = cellValue(row, k)
  if ((raw ?? '') === before) return true // 没改就不发请求
  savingKey.value = ck
  try {
    await applyValue(row, k, raw ?? '')
    if (undoable) {
      undoStack.value.push({
        recordId: id,
        key: k,
        before,
        after: raw ?? '',
        label: `改${columnTitle(k)}`,
      })
      if (undoStack.value.length > UNDO_LIMIT) undoStack.value.shift()
      redoStack.value = [] // 有了新操作，重做栈就作废了
    }
    if (k === '__class__') {
      ElMessage.success(`已转到「${row.className}」`)
    }
    savedKey.value = ck
    savedAt.value = Date.now()
    setTimeout(() => {
      if (savedKey.value === ck) savedKey.value = null
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

// ==================== 撤销 / 重做 ====================

/** 一次撤销/重做记的内容 */
interface UndoStep {
  recordId: number
  /** 哪一列 */
  key: string
  /** 改之前的值 */
  before: string
  /** 改之后的值 */
  after: string
  /** 提示语（「改姓名」「改班级」…） */
  label: string
}

/** 撤销栈最多留多少步（多了内存白占，界面也用不上） */
const UNDO_LIMIT = 50

const undoStack = ref<UndoStep[]>([])
const redoStack = ref<UndoStep[]>([])

/**
 * 撤销一步。
 *
 * 做法是**把旧值再写回去**（不是回滚数据库）——所以撤销本身也是一次普通的
 * 改动，同样会走校验（比如学号在原班撞号了就会失败）。
 * 失败了就把它放回栈里，不吞掉用户的操作。
 */
async function undo() {
  const step = undoStack.value.pop()
  if (!step) {
    ElMessage.info('没有可撤销的操作')
    return
  }
  const row = rows.value.find((r) => r.id === step.recordId)
  if (!row) {
    // 那一行已经不在当前筛选/页里了，撤不了
    undoStack.value.push(step)
    ElMessage.warning('这一行已经不在当前列表里，撤不了')
    return
  }
  try {
    await applyValue(row, step.key, step.before)
    redoStack.value.push(step)
    ElMessage.success(`已撤销：${step.label}`)
  } catch (e) {
    undoStack.value.push(step)
    ElMessage.error(getErrorMessage(e, '撤销失败'))
  }
}

/** 重做：把刚才撤销的改动再做一遍。 */
async function redo() {
  const step = redoStack.value.pop()
  if (!step) {
    ElMessage.info('没有可重做的操作')
    return
  }
  const row = rows.value.find((r) => r.id === step.recordId)
  if (!row) {
    redoStack.value.push(step)
    ElMessage.warning('这一行已经不在当前列表里，重做不了')
    return
  }
  try {
    await applyValue(row, step.key, step.after)
    undoStack.value.push(step)
    ElMessage.success(`已重做：${step.label}`)
  } catch (e) {
    redoStack.value.push(step)
    ElMessage.error(getErrorMessage(e, '重做失败'))
  }
}

/**
 * 全局快捷键：Ctrl+Z 撤销 / Ctrl+Y（Ctrl+Shift+Z）重做。
 *
 * ## 编辑中要不要抢？
 *
 * 用户在输入框里敲了字，Ctrl+Z 的原生行为是「撤销我刚敲的字」——
 * 那是用户此刻真正想要的，抢过来反而丢东西。
 *
 * 但有一种情况**必须抢**：刚按回车提交完，光标已经跳到下一格（输入框里是
 * 那一格的旧值，**一个字都没敲**）。这时用户按 Ctrl+Z，想的是「撤销我刚才
 * 那次保存」，而原生撤销在那个输入框里什么也撤不掉（撤销栈是空的）——
 * 表现就是「Ctrl+Z 没反应」。
 *
 * 判据就是**这个输入框里有没有刚敲的字**：
 * `draftVal !== editStartVal` = 敲过 → 交给原生；相等 = 没敲 → 抢过来撤销保存。
 */
function onGlobalKeydown(e: KeyboardEvent) {
  if (!(e.ctrlKey || e.metaKey)) return
  const k = e.key.toLowerCase()
  const isUndo = k === 'z' && !e.shiftKey
  const isRedo = k === 'y' || (k === 'z' && e.shiftKey)
  if (!isUndo && !isRedo) return
  // 编辑中且**刚敲了字** → 让输入框自己撤销
  if (editKey.value && draftVal.value !== editStartVal.value) return
  e.preventDefault()
  if (isUndo) void undo()
  else void redo()
}

/**
 * Tab = 右移一格，顺带把当前这格存了。
 *
 * 必须拦 **keydown** 而不是 keyup —— 浏览器在 keydown 阶段就把焦点移走，
 * blur 先触发、输入框被卸载，keyup.tab 压根不会派发到它身上。
 */
/**
 * Tab = 右移一格，顺带把当前这格存了。
 *
 * 两条容易踩的：
 * ① 必须拦 **keydown** 而不是 keyup —— 浏览器在 keydown 阶段就把焦点移走，
 *    blur 先触发、输入框被卸载，keyup.tab 压根不会派发到它身上。
 * ② 先移再存，不等网络。raw 已经取值，commit 里改 draftVal 也影响不到它。
 */
function onTab(id: number, k: string, dc = 1) {
  const raw = draftVal.value
  moveEdit(id, k, 0, dc)
  void commit(id, k, raw)
}

/**
 * Enter = 存下并**往下**移一格（到底了往右）。
 *
 * Excel 的手感：改完一行按回车，接着改下一行同一个字段——这是填表最快的路径。
 */
function onEnter(id: number, k: string) {
  const raw = draftVal.value
  const rowIdx = rows.value.findIndex((r) => r.id === id)
  const atLastRow = rowIdx >= rows.value.length - 1
  moveEdit(id, k, atLastRow ? 0 : 1, atLastRow ? 1 : 0)
  void commit(id, k, raw)
}

/** 方向键 = 存下并移动到相邻格（继续编辑）。 */
function onArrow(id: number, k: string, dr: number, dc: number) {
  const raw = draftVal.value
  moveEdit(id, k, dr, dc)
  void commit(id, k, raw)
}

/**
 * 「清空这一格」——Excel 里 Delete 键的效果。
 *
 * 班级**不能清空**（没有「不属于任何班」这种状态）。
 */
async function clearCell(row: CollegeStudentRow, k: string) {
  if (k === '__class__') return
  await commit(row.id, k, null)
}

/**
 * 焦点离开这一格 = 提交（Excel 里点别处就生效）。
 *
 * 挂在 td 的 `focusout` 而不是 el-input 的 `blur`：blur 不冒泡，
 * 且**输入框被卸载时不派发**——而点另一格正是"当前输入框被卸载"。
 *
 * ## ⚠ 必须区分「焦点跳到本格的编辑框」和「用户真的走了」
 *
 * 点一下格子 → 输入框挂上来 → 它抢走焦点 → td 触发 `focusout`。
 * 这时候**编辑框还开着**，用户正在里面打字呢！
 * 不区分就会：焦点一进编辑框就提交 + 关闭 → 用户看着「点进去又弹出来」。
 *
 * 判据是 `relatedTarget`（焦点接下来去了哪儿）：落在**同一个 td 里**
 * 就是「还在本格」，不提交也不关闭。
 */
function onCellFocusOut(e: FocusEvent, row: CollegeStudentRow, k: string) {
  // 只有「正是在编辑这一格」才提交：Tab 移走后输入框卸载也会冒泡上来，
  // 那时 editKey 已经指向新格子，再提交一次等于把旧值盖回去。
  if (editKey.value !== ckey(row.id, k)) return
  const to = e.relatedTarget as Node | null
  const cell = e.currentTarget as HTMLElement | null
  // 焦点只是跳进了本格的编辑框 → 还在本格，别管
  if (to && cell && cell.contains(to)) return
  void commit(row.id, k, draftVal.value)
}

/**
 * 单元格上的键盘处理，**所有编辑器类型统一走这里**。
 *
 * 用 `.capture`（捕获阶段）：el-select 内部对 Escape 会 stopPropagation，
 * 冒泡阶段根本轮不到这里的 handler，Esc 就废了。
 *
 * ## 两套快捷键
 *
 * **编辑态**（输入框里）：
 *
 * | 键 | 作用 |
 * |----|------|
 * | Enter | 存下并**往下**移一格（到底往右） |
 * | Tab / Shift+Tab | 存下并右移 / 左移一格 |
 * | ↑ ↓ ← → | 存下并移动到相邻格（继续编辑） |
 * | Esc | 取消，不保存 |
 *
 * **非编辑态**（焦点在格子上，没在输入）：
 *
 * | 键 | 作用 |
 * |----|------|
 * | Enter / F2 | 进入编辑 |
 * | Delete | 清空这一格 |
 * | ↑ ↓ ← → | 移到相邻格（不进入编辑） |
 * | Home / End | 本行第一个 / 最后一个格子 |
 * | PageUp / PageDown | 上一页 / 下一页 |
 *
 * ⚠ **编辑态里不抢** Home/End（那是输入框里移动光标的位置）。
 */
function onCellKeydown(e: KeyboardEvent, row: CollegeStudentRow, k: string) {
  const editing = editKey.value === ckey(row.id, k)
  const inInput =
    e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement
  // el-select / el-date-picker 的面板里，方向键和 Enter 是它们自己的
  const inPanel = !inInput && e.target !== e.currentTarget

  if (!editing) {
    // ---- 非编辑态 ----
    if (e.key === 'Delete') {
      if (!isEditableCol(k)) return
      e.preventDefault()
      void clearCell(row, k)
      return
    }
    if (e.key === 'Enter' || e.key === 'F2') {
      e.preventDefault()
      startEdit(row.id, k)
      return
    }
    if (e.key === 'Home' || e.key === 'End') {
      e.preventDefault()
      focusCellAt(row.id, k, e.key === 'Home' ? 0 : columns.value.length - 1)
      return
    }
    if (e.key === 'PageUp' || e.key === 'PageDown') {
      e.preventDefault()
      const step = e.key === 'PageUp' ? -1 : 1
      const next = Math.min(Math.max(page.value + step, 1), pageCount.value)
      if (next !== page.value) {
        page.value = next
        void load()
      }
      return
    }
    if (ARROWS[e.key]) {
      e.preventDefault()
      const [dr, dc] = ARROWS[e.key]
      focusCellBy(row.id, k, dr, dc)
      return
    }
    return
  }

  // ---- 编辑态 ----
  if (e.key === 'Escape') {
    editKey.value = null // 不保存直接关（Excel 里 Esc 的语义）
    return
  }
  if (e.key === 'Tab') {
    e.preventDefault()
    onTab(row.id, k, e.shiftKey ? -1 : 1)
    return
  }
  if (inPanel) return // 面板里交给它自己
  if (e.key === 'Enter') {
    e.preventDefault()
    onEnter(row.id, k)
    return
  }
  if (ARROWS[e.key]) {
    e.preventDefault()
    const [dr, dc] = ARROWS[e.key]
    onArrow(row.id, k, dr, dc)
  }
}

/** 方向键 → 位移 */
const ARROWS: Record<string, [number, number]> = {
  ArrowUp: [-1, 0],
  ArrowDown: [1, 0],
  ArrowLeft: [0, -1],
  ArrowRight: [0, 1],
}

/**
 * 把焦点挪到**同一行的某一列**（Home / End）。
 *
 * 焦点是给键盘用户的：格子本身是 `tabindex=0`，能接住焦点。
 */
function focusCellAt(id: number, _k: string, colIdx: number) {
  const rowIdx = rows.value.findIndex((r) => r.id === id)
  if (rowIdx < 0) return
  const col = columns.value[Math.min(Math.max(colIdx, 0), columns.value.length - 1)]
  if (!col) return
  const el = document.querySelector<HTMLElement>(
    `.cell[data-r="${rowIdx}"][data-c="${col.key}"]`,
  )
  el?.focus()
}

/** 把焦点挪到**相邻格**（方向键）。 */
function focusCellBy(id: number, k: string, dr: number, dc: number) {
  const rowIdx = rows.value.findIndex((r) => r.id === id)
  const colIdx = columns.value.findIndex((c) => c.key === k)
  if (rowIdx < 0 || colIdx < 0) return
  const nr = rowIdx + dr
  const nc = colIdx + dc
  if (nr < 0 || nr >= rows.value.length || nc < 0 || nc >= columns.value.length) return
  const col = columns.value[nc]
  const el = document.querySelector<HTMLElement>(`.cell[data-r="${nr}"][data-c="${col.key}"]`)
  el?.focus()
}

// ==================== 列名（就地改） ====================

/**
 * 点列名改名。**不另开对话框**——和班级页一个手感：
 * 点一下变成输入框，回车就存。
 */
const renamingKey = ref<string | null>(null)
const renameDraft = ref('')

function startRename(col: CollegeCol) {
  if (!col.field) return
  if (renamingKey.value === col.key) return
  renameDraft.value = col.label
  renamingKey.value = col.key
}

async function submitRename(col: CollegeCol) {
  if (renamingKey.value !== col.key) return
  const label = renameDraft.value.trim()
  renamingKey.value = null
  if (!label || label === col.label) return
  try {
    await updateCollegeField(col.key, { label })
    ElMessage.success(`已改名为「${label}」`)
    await load()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '改名失败'))
  }
}

// ==================== 改列类型（先预览，再确认） ====================

const retypeOpen = ref(false)
const retypeCol = ref<CollegeCol | null>(null)
const retypeTo = ref<StudentFieldType>('TEXT')
const retypePreview = ref<CollegeRetypePreview | null>(null)
const retypeLoading = ref(false)
const retypeApplying = ref(false)
/** 转不了的值要不要清空。默认保留原文本——改错了还能改回来 */
const retypeClearBad = ref(false)

const retypeChanged = computed(
  () => retypePreview.value !== null && retypePreview.value.fromType !== retypeTo.value,
)
/** 只有可转换数为 0、转不了的也一堆时，「清空」才是唯一出路 */
const retypeNeedChoice = computed(() => (retypePreview.value?.unconvertibleCount ?? 0) > 0)

async function openRetype(col: CollegeCol) {
  if (!col.field) return
  retypeCol.value = col
  retypeTo.value = col.type
  retypePreview.value = null
  retypeClearBad.value = false
  retypeOpen.value = true
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
    retypePreview.value = await previewCollegeFieldRetype(col.key, retypeTo.value)
    if (retypePreview.value.unconvertibleCount > 0) retypeClearBad.value = false
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '读取转换预览失败'))
    retypePreview.value = null
  } finally {
    retypeLoading.value = false
  }
}

const TYPE_OPTIONS: { value: StudentFieldType; label: string }[] = [
  { value: 'TEXT', label: '文本' },
  { value: 'NUMBER', label: '数字' },
  { value: 'DATE', label: '日期' },
  { value: 'BOOL', label: '是/否' },
]

/** 表头上那行小字。只标**非文本**的类型——默认就是文本、真没什么可提示的。 */
const TYPE_BADGE: Record<StudentFieldType, string> = {
  TEXT: '',
  NUMBER: '数字',
  DATE: '日期',
  BOOL: '是/否',
}

async function submitRetype() {
  const col = retypeCol.value
  if (!col || !retypeChanged.value) return
  retypeApplying.value = true
  try {
    const r = await applyCollegeFieldRetype(col.key, retypeTo.value, retypeClearBad.value)
    retypeOpen.value = false
    const parts = [`已把「${col.label}」改成${typeText(r.toType)}类型`]
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

function typeText(t: string): string {
  return TYPE_OPTIONS.find((o) => o.value === t)?.label ?? t
}

// ==================== 新增列（可在任意位置插入） ====================

/**
 * 「在某一列前面插一个列」。表头上每个 `＋` 都调它。
 *
 * 学院版插的是**所有班各建一份、key 相同**的列——学院只有一份表。
 */
const insertOpen = ref(false)
const insertLabel = ref('')
const insertType = ref<StudentFieldType>('TEXT')
const insertAnchor = ref<string | null>(null)
const insertAnchorLabel = ref('')
const inserting = ref(false)

function openInsert(col: CollegeCol) {
  insertAnchor.value = col.key
  insertAnchorLabel.value = col.label
  insertLabel.value = ''
  insertType.value = 'TEXT'
  insertOpen.value = true
}

async function submitInsert() {
  const label = insertLabel.value.trim()
  if (!label) {
    ElMessage.warning('请填写列名')
    return
  }
  inserting.value = true
  try {
    const r = await createCollegeField({
      label,
      type: insertType.value,
      anchorKey: insertAnchor.value,
      side: 'before',
    })
    insertOpen.value = false
    ElMessage.success(`已在「${insertAnchorLabel.value}」前面插入「${label}」（${r.classCount} 个班）`)
    await load()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '新增列失败'))
  } finally {
    inserting.value = false
  }
}

async function removeColumn(col: CollegeCol) {
  // 确认框里必须说清"值还在"：用户看到列消失，第一反应是"数据没了"。
  try {
    await ElMessageBox.confirm(
      `确定停用「${col.label}」这一列吗？\n\n` +
        `· 它会从表格、导出和后续导入中消失\n` +
        `· 这一列已填的值仍保留在数据库里，误删可在「已停用列」中恢复\n` +
        `· 所有班一起停用`,
      '确认停用该列？',
      { type: 'warning', confirmButtonText: '确认停用', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const r = await deleteCollegeField(col.key)
    ElMessage.success(`「${col.label}」已停用，可在「已停用列」里恢复（${r.classCount} 个班）`)
    await load()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '停用失败'))
  }
}

// ==================== 已停用列（恢复） ====================

const trashOpen = ref(false)
const trashLoading = ref(false)
const disabledColumns = ref<CollegeStudentColumn[]>([])

/**
 * 已停用的列。
 *
 * 停用是软删（`status=0`），值一行没动——所以必须给一条找回的路，
 * 否则"误删一列填了几十条数据的列"就等于真丢了。
 */
async function openTrash() {
  trashOpen.value = true
  trashLoading.value = true
  try {
    const r = await fetchCollegeDisabledFields()
    disabledColumns.value = r.columns ?? []
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '读取已停用列失败'))
    disabledColumns.value = []
  } finally {
    trashLoading.value = false
  }
}

async function restoreColumn(c: CollegeStudentColumn) {
  try {
    await restoreCollegeField(c.key)
    ElMessage.success(`「${c.label}」已恢复`)
    await Promise.all([openTrash(), load()])
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '恢复失败'))
  }
}

/**
 * 彻底删除已停用的列（所有班一起删）。确认框必须把三件事说清：
 * **所有班**、**连同已填的值**、**不可恢复**——学院列是跨班共用的，
 * 这一删的影响面比班级页大得多，宁可比班级页更啰嗦一点。
 */
async function purgeColumn(c: CollegeStudentColumn) {
  const classCount = c.classCount
  try {
    await ElMessageBox.confirm(
      `将把「${c.label}」这一列从所有班` +
        (classCount ? `（共 ${classCount} 个班）` : '') +
        `里彻底删除，连同已填的所有值。\n\n` +
        '删除后不能恢复，请确认这些数据不再需要。',
      '彻底删除该列？',
      { type: 'error', confirmButtonText: '彻底删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const r = await purgeCollegeField(c.key)
    ElMessage.success(
      `「${c.label}」已从 ${r.classCount} 个班彻底删除` +
        (r.deletedValues ? `（连同 ${r.deletedValues} 个值）` : ''),
    )
    await Promise.all([openTrash(), load()])
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '删除失败'))
  }
}

// ==================== 勾选 + 导出 ====================

const selectedIds = ref<number[]>([])

const allSelected = computed(
  () => rows.value.length > 0 && selectedIds.value.length === rows.value.length,
)
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

/**
 * 删掉勾中的学生（**不可撤销**）。
 *
 * 确认框里必须把两件事说清楚，否则用户会以为删掉的是账号：
 * 1. 删的是**名册行 + 他填过的所有信息**；
 * 2. **登录账号还在**，要停用/销号得去「成员管理」。
 *
 * 批量删一半失败比全删成功更糟，所以后端对「已经不存在的 id」是跳过的，
 * 提示按**真正删掉的数量**说（`deleted`），不说「已删除 3 名」而实际只删了 2 个。
 */
const deleting = ref(false)

async function deleteSelected() {
  const ids = [...selectedIds.value]
  if (!ids.length || deleting.value) return
  try {
    await ElMessageBox.confirm(
      `将从名册里删除 ${ids.length} 名学生，连同他们在表格里填过的所有信息。\n` +
        '登录账号不会被删除（要停用账号请去「成员管理」）。删除后不能撤销。',
      '删除学生',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    return // 用户取消
  }
  deleting.value = true
  try {
    const r = await deleteCollegeStudents(ids)
    ElMessage.success(`已删除 ${r.deleted} 名学生`)
    selectedIds.value = []
    await load()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '删除失败'))
  } finally {
    deleting.value = false
  }
}

const exporting = ref(false)
const exportOpen = ref(false)
const exportRowScope = ref<'selected' | 'all' | 'range'>('all')
/** 「指定行区间」导出用的起止行号（相对当前筛选结果，1 起） */
const exportRowFrom = ref(1)
const exportRowTo = ref(10)
const exportFields = ref<string[]>([])
const exportFieldFilter = ref('')

/** 可以取消勾选的列：班级和年级之外的全是字段列。 */
const optionalExportColumns = computed(() => allColumns.value.filter((c) => c.key !== GRADE_FIELD_KEY))

/** 学号/姓名必选；班级/年级听勾选。 */
const requiredExportColumns = computed(() => [
  { key: '__no__', label: '学号' },
  { key: '__name__', label: '姓名' },
  { key: '__class__', label: '班级' },
  { key: '__grade__', label: '年级' },
])

/** 真正会导出的列标识（学号/姓名必选，其余听勾选）。 */
const exportColumnKeys = computed(() => {
  const keys: string[] = ['__no__', '__name__']
  if (exportFields.value.includes('__class__')) keys.push('__class__')
  if (exportFields.value.includes('__grade__')) keys.push('__grade__')
  for (const c of optionalExportColumns.value) {
    if (exportFields.value.includes(c.key)) keys.push(c.key)
  }
  return keys
})

const exportFieldSearch = computed(() => {
  const q = exportFieldFilter.value.trim().toLowerCase()
  const base = [
    { key: '__class__', label: '班级' },
    { key: '__grade__', label: '年级' },
    ...optionalExportColumns.value,
  ]
  if (!q) return base
  return base.filter((c) => c.label.toLowerCase().includes(q))
})

/** 导出行数：已勾选 = 勾了几行；全部 = 当前筛选下多少人。 */
const exportRowCount = computed(() => {
  if (exportRowScope.value === 'selected') return selectedIds.value.length
  if (exportRowScope.value === 'range') {
    const from = Math.max(1, Math.floor(exportRowFrom.value || 1))
    const to = Math.min(total.value, Math.floor(exportRowTo.value || 0))
    return Math.max(0, to - from + 1)
  }
  return total.value
})

function openExport() {
  exportRowScope.value = selectedIds.value.length ? 'selected' : 'all'
  // 默认勾上**有数据的**列：导出的表里一片空白列没人要。
  // 没数据的列仍然列在下面（要导就手动勾——比如给别人一个带表头的空模板）。
  exportFields.value = [
    '__class__',
    '__grade__',
    ...optionalExportColumns.value
      .filter((c) => populatedKeys.value.has(c.key))
      .map((c) => c.key),
  ]
  exportFieldFilter.value = ''
  exportOpen.value = true
}

function toggleExportField(key: string) {
  const i = exportFields.value.indexOf(key)
  if (i >= 0) exportFields.value.splice(i, 1)
  else exportFields.value.push(key)
}

async function submitExport() {
  exporting.value = true
  try {
    // 「指定行区间」：按当前筛选结果的顺序，取第 from 到 to 条
    const range =
      exportRowScope.value === 'range'
        ? {
            offset: Math.max(1, Math.floor(exportRowFrom.value || 1)) - 1,
            limit: Math.max(1, exportRowCount.value),
          }
        : {}
    await exportCollegeStudents({
      columns: exportColumnKeys.value,
      ids: exportRowScope.value === 'selected' ? [...selectedIds.value] : undefined,
      keyword: applied.value.keyword,
      classId: applied.value.classId,
      grade: applied.value.grade,
      ...range,
    })
    exportOpen.value = false
    ElMessage.success(`已导出 ${exportRowCount.value} 名学生 × ${exportColumnKeys.value.length} 列`)
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '导出失败'))
  } finally {
    exporting.value = false
  }
}

// ==================== 导入 ====================

/**
 * 真按钮 + 编程式唤起文件选择器。
 *
 * ⚠ **不能**用「`<label>` 包着 `<input type=file>` 再塞个按钮」的写法：
 * 按 HTML 规范，label 的激活行为在**点击目标是交互元素**（button）时
 * **不执行**——所以点那个看得见的「导入 Excel」按钮，文件选择器根本不弹。
 * 现在是：按钮 click → `fileInput.click()` → 浏览器弹出文件选择器。
 */
const fileInput = ref<HTMLInputElement>()
/** 文件里没有「班级」列时，这些行进哪个班 */
const importClassId = ref<number | null>(null)
/** 后退一步再问一次的场景：文件没有「班级」列，得先知道进哪个班 */
const needClassOpen = ref(false)
const pendingFile = ref<File | null>(null)

function pickFile() {
  fileInput.value?.click()
}

/**
 * 下载学院名册的导入模板。
 *
 * 列 = 所有启用班级的字段合并（另加「班级」列）。每次下载都由后端现读字段，
 * 所以学院里新增一列之后，重新下载就是新列。有模板再导入，
 * 就不会有人拿自己随手编的表导进来——那种表往往列名对不上。
 */
const templateLoading = ref(false)

async function onDownloadTemplate() {
  templateLoading.value = true
  try {
    await downloadCollegeStudentTemplate()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '下载模板失败'))
  } finally {
    templateLoading.value = false
  }
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  input.value = ''
  if (f) void onImport(f)
}

async function onImport(file: File) {
  importing.value = true
  try {
    const r = await importCollegeStudents(file, importClassId.value)
    ElMessage.success(`导入完成：新增 ${r.created} 人，更新 ${r.updated} 人`)
    if (r.newFields.length) {
      const detail = r.newFields.map((f) => `${f.label}（${f.typeText}）`).join('、')
      ElMessageBox.alert(
        `表格里有 ${r.newFields.length} 列之前没有，已自动建为列并导入：\n${detail}\n\n` +
          '所有班都加上了这一列。',
        '已自动新增列',
        { confirmButtonText: '知道了' },
      )
    }
    if (r.unmatchedColumns.length) {
      ElMessage.warning(
        `表格里有 ${r.unmatchedColumns.length} 列没有对应字段，未导入：${r.unmatchedColumns.join('、')}`,
      )
    }
    if (r.duplicateRows > 0) {
      ElMessage.warning(
        `表格里有 ${r.duplicateRows} 行学号重复，已按后出现的覆盖前面的。` +
          '如果这不是你要的，请检查表格里有没有复制粘贴残留的空行。',
      )
    }
    if (r.errors?.length) {
      ElMessage.warning(`有 ${r.errors.length} 行没能导入：${r.errors.slice(0, 3).join('；')}`)
    }
    await load()
  } catch (e) {
    const msg = getErrorMessage(e, '导入失败')
    // 文件里没有「班级」列 → 后端不知道该进哪个班。
    // 别只甩一句报错：把同一个文件留下来，问一句进哪个班，然后接着导。
    if (msg.includes('班级') && (msg.includes('没有') || msg.includes('选择'))) {
      pendingFile.value = file
      needClassOpen.value = true
      return
    }
    ElMessage.error(msg)
  } finally {
    importing.value = false
  }
}

/** 选好班级后，用**同一个文件**再导一次。 */
async function submitImportClass() {
  if (!importClassId.value) {
    ElMessage.warning('请选择要导入到哪个班')
    return
  }
  const f = pendingFile.value
  needClassOpen.value = false
  pendingFile.value = null
  if (f) await onImport(f)
}

// ==================== 更多 ====================

function onMore(cmd: string) {
  if (cmd === 'trash') void openTrash()
}
</script>

<template>
  <div class="page">
    <header class="head">
      <div>
        <h2>学院学生信息</h2>
        <p class="sub">
          <template v-if="hasFilter">
            当前筛选下 <strong>{{ total }}</strong> 人
          </template>
          <template v-else>
            <strong>全部班级</strong>共 {{ total }} 人<template v-if="total"> · 点任意格子即可修改，回车保存</template>
          </template>
        </p>
      </div>
      <div class="actions">
        <!--
          导入 Excel 是这一页的**起点**，所以它是唯一的主按钮。
          导出和「更多」收在后面，不跟主行动抢视线。
        -->
        <el-button type="primary" :loading="importing" @click="pickFile">
          导入 Excel
        </el-button>
        <!--
          导出模板：下载一张空白模板，列 = 各班字段合并 + 「班级」列。
          用户填好后再用「导入 Excel」上传，能挡掉「自己随便编一张表导进来」——列名不对等于白导一遍。
        -->
        <el-button
          :loading="templateLoading"
          title="下载一张空白模板（按各班字段生成），填好后用「导入 Excel」上传"
          @click="onDownloadTemplate"
        >
          导出模板
        </el-button>
        <!-- 撤销 / 重做只有快捷键（Ctrl+Z / Ctrl+Y），页头不放按钮 -->
        <el-button @click="openExport">
          导出<span v-if="selectedIds.length">选中（{{ selectedIds.length }}）</span>
        </el-button>
        <!--
          删除**只在勾了人之后才出现**：没选中时它是一个永远点不动的死按钮，
          摆在那里只会让人以为「删不了」。
        -->
        <el-button
          v-if="selectedIds.length"
          type="danger"
          plain
          :loading="deleting"
          @click="deleteSelected"
        >
          删除选中（{{ selectedIds.length }}）
        </el-button>
        <el-dropdown trigger="click" @command="onMore">
          <el-button aria-label="更多操作">
            更多<el-icon class="more-caret"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="trash">
                <el-icon><Delete /></el-icon>已停用列
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <!-- 真藏起来的 file input：仍然可被脚本 .click() 唤起 -->
        <input
          ref="fileInput"
          class="file-input"
          type="file"
          accept=".xlsx,.xlsm"
          @change="onFileChange"
        />
      </div>
    </header>

    <!-- 筛选：全校几千人，没有筛选没法用 -->
    <section class="filters">
      <el-input
        v-model="keyword"
        class="f-keyword"
        placeholder="学号 / 姓名 / 任意文本字段（回车搜索）"
        clearable
        @keyup.enter="search"
      />
      <!--
        班级/年级**选了立刻筛**。
        之前要再点一次「搜索」才生效——用户选了之后看表格没变，
        直接就判成「筛选不了」。筛选器本来就该即时反馈。
        关键字那边要按回车，是因为逐字输就逐字发请求（每敲一个字一次）。
      -->
      <el-select
        v-model="classId"
        class="f-select"
        placeholder="全部班级"
        clearable
        @change="search"
      >
        <el-option
          v-for="c in classesWithStudents"
          :key="c.id"
          :label="c.className"
          :value="c.id"
        />
      </el-select>
      <el-select
        v-model="grade"
        class="f-select"
        placeholder="全部年级"
        clearable
        @change="search"
      >
        <el-option v-for="g in grades" :key="g" :label="g" :value="g" />
      </el-select>
      <el-button type="primary" @click="search">搜索</el-button>
      <el-button @click="reset">重置</el-button>
    </section>

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
                  固定列（学号/姓名/班级/年级）不是字段，不给这些操作。
                -->
                <el-input
                  v-if="renamingKey === col.key"
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
                  :class="{ editable: col.field }"
                  :title="
                    col.field
                      ? `${col.label}（${typeText(col.type)}）——点击可改名`
                      : col.key === '__class__'
                        ? '班级是学生的归属，不能在这里改（转班请在班级页操作）'
                        : col.key === '__grade__'
                          ? '学生的年级：自己填的值为准，没填才用班级的年级'
                          : col.key === '__no__'
                            ? '学号是导入名单时的匹配依据，改动后再导同一份名单会重复插入'
                            : col.label
                  "
                  @click="startRename(col)"
                >
                  {{ col.label }}
                </span>
                <span
                  v-if="col.field && TYPE_BADGE[col.type]"
                  class="col-type editable"
                  title="点击可改这一列的类型"
                  @click="openRetype(col)"
                >
                  {{ TYPE_BADGE[col.type] }}
                </span>
                <span class="col-ops">
                  <!--
                    固定列不给 ＋/✕：它们不是字段（学号姓名在 student_record 上，
                    班级是归属，年级代表 grade 字段），插列/停用对它们没有意义。
                  -->
                  <button
                    v-if="col.field"
                    class="mini"
                    :aria-label="`在「${col.label}」前面插入新列`"
                    :title="`在「${col.label}」前面插入新列`"
                    @click="openInsert(col)"
                  >
                    ＋
                  </button>
                  <button
                    v-if="col.field"
                    class="mini danger"
                    :aria-label="`停用「${col.label}」这一列`"
                    :title="`停用「${col.label}」这一列`"
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
                transferable: col.key === '__class__',
                saved: justSaved(row.id, col.key),
              }"
              :data-r="ri"
              :data-c="col.key"
              :title="col.key === '__class__' ? '改成别的班级名，回车即可（没有这个班会自动建）' : undefined"
              tabindex="0"
              @click="onCellClick(row, col)"
              @keydown.capture="onCellKeydown($event, row, col.key)"
              @focusout="onCellFocusOut($event, row, col.key)"
            >
              <!-- 编辑态：按字段类型给对应控件 -->
              <el-select
                v-if="isEditing(row.id, col.key) && col.type === 'BOOL'"
                :ref="(el: unknown) => bindEditor(el, row.id, col.key)"
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
                :ref="(el: unknown) => bindEditor(el, row.id, col.key)"
                v-model="draftVal"
                type="date"
                size="small"
                value-format="YYYY-MM-DD"
                clearable
                @change="commit(row.id, col.key, draftVal)"
              />

              <!-- 键盘事件（Esc / Tab / Delete / Enter / 方向键）统一由 td 冒泡处理 -->
              <el-input
                v-else-if="isEditing(row.id, col.key)"
                :ref="(el: unknown) => bindEditor(el, row.id, col.key)"
                v-model="draftVal"
                size="small"
              />

              <!-- 显示态 -->
              <template v-else>
                <span class="txt" :class="{ empty: !cellValue(row, col.key) }">
                  {{ cellValue(row, col.key) || (col.key === '__class__' ? '未分班' : '—') }}
                </span>
                <el-icon v-if="isSaving(row.id, col.key)" class="spin"><Loading /></el-icon>
                <span v-else-if="justSaved(row.id, col.key)" class="ok-mark">已存</span>
              </template>
            </td>
          </tr>
          <tr v-if="!rows.length && !loading">
            <td class="empty-row" :colspan="columns.length + 2">
              <template v-if="hasFilter">
                当前筛选下没有学生。换个班级或年级试试，或者点<strong>「重置」</strong>看全部。
              </template>
              <template v-else>
                还没有学生。可以点右上角<strong>「导入 Excel」</strong>一次导入全校名单
                （表格里有<strong>「班级」列</strong>就会按班级自动分发到各个班）。
              </template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p class="foot">
      <span class="foot-line">单击格子修改，回车或移开自动保存 · Esc 取消 · Delete 清空该格</span>
      <span class="foot-line">
        快捷键：Enter 存下并往下移一格 · ↑↓←→ 存下并移动 · Tab 下一格 ·
        F2 进入编辑 · Home/End 行首行尾 · PageUp/PageDown 翻页 · Ctrl+Z 撤销 · Ctrl+Y 重做
      </span>
      <span class="foot-tip">
        · 点列名可改名，点类型小标签可改类型；鼠标移到列名上会出现 ＋ 和 ✕，
        ＋ 在这一列前面插入新列，✕ 停用该列
      </span>
    </p>

    <div v-if="total > size" class="pager">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="size"
        :total="total"
        :page-sizes="[50, 100, 200]"
        layout="total, sizes, prev, pager, next"
        background
      />
    </div>

    <!-- 文件里没有「班级」列：问一句进哪个班，然后用同一个文件接着导 -->
    <el-dialog
      v-model="needClassOpen"
      title="这份名单没有「班级」列"
      width="420px"
      append-to-body
    >
      <p class="add-hint">
        表格里没有<strong>「班级」列</strong>，没法按班分发。请选一个班，
        名单里的所有人都会进这个班。
      </p>
      <el-form label-width="64px" style="margin-top: 12px">
        <el-form-item label="进哪个班">
          <el-select v-model="importClassId" placeholder="选择班级" style="width: 100%">
            <el-option
              v-for="c in classes"
              :key="c.id"
              :label="`${c.className}（${c.students} 人）`"
              :value="c.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="needClassOpen = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="submitImportClass">
          导入
        </el-button>
      </template>
    </el-dialog>

    <!-- 新增列：就地小浮层，不是另开一个抽屉 -->
    <el-dialog
      v-model="insertOpen"
      :title="`在「${insertAnchorLabel}」前面插入列`"
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
      <p class="add-hint">
        新列会加到<b>所有班</b>——学院只有一份表，各班的列名要一样才对得上。
      </p>
      <template #footer>
        <el-button @click="insertOpen = false">取消</el-button>
        <el-button type="primary" :loading="inserting" @click="submitInsert">
          插入
        </el-button>
      </template>
    </el-dialog>

    <!-- 导出：行范围 + 选列 -->
    <el-dialog v-model="exportOpen" title="导出学院学生信息" width="620px" append-to-body>
      <el-form label-width="64px">
        <el-form-item label="行">
          <el-radio-group v-model="exportRowScope">
            <el-radio value="all">当前筛选下全部（{{ total }} 人）</el-radio>
            <el-radio value="selected" :disabled="!selectedIds.length">
              已勾选（{{ selectedIds.length }} 人）
            </el-radio>
            <el-radio value="range">指定行区间</el-radio>
          </el-radio-group>
          <div
            v-if="exportRowScope === 'range'"
            style="margin-top: 8px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap"
          >
            第
            <el-input-number
              v-model="exportRowFrom"
              :min="1"
              :max="Math.max(1, total)"
              size="small"
              controls-position="right"
              style="width: 110px"
            />
            到第
            <el-input-number
              v-model="exportRowTo"
              :min="1"
              :max="Math.max(1, total)"
              size="small"
              controls-position="right"
              style="width: 110px"
            />
            条（共 {{ total }} 人，按当前筛选后的顺序）
          </div>
        </el-form-item>

        <el-form-item label="列">
          <div class="col-picker">
            <div class="col-picker-bar">
              <el-input
                v-model="exportFieldFilter"
                size="small"
                placeholder="搜索列名"
                clearable
              />
              <el-button size="small" @click="exportFields = exportFieldSearch.map((c) => c.key)">
                全选
              </el-button>
              <el-button size="small" @click="exportFields = []">清空</el-button>
            </div>
            <!-- 学号/姓名是**必选**（一份没有学号的表没法说明每一行是谁） -->
            <el-checkbox
              v-for="c in requiredExportColumns.slice(0, 2)"
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
              没有叫「{{ exportFieldFilter }}」的列
            </p>
          </div>
        </el-form-item>
      </el-form>

      <p class="export-preview">
        将导出 <strong>{{ exportRowCount }}</strong> 名学生 ×
        <strong>{{ exportColumnKeys.length }}</strong> 列
        （学号、姓名必选，已计入）
      </p>

      <template #footer>
        <el-button @click="exportOpen = false">取消</el-button>
        <el-button
          type="primary"
          :loading="exporting"
          :disabled="exportColumnKeys.length < 2 || exportRowCount < 1"
          @click="submitExport"
        >
          导出
        </el-button>
      </template>
    </el-dialog>

    <!-- 改列类型：先看预览（会动已存的值），再确认 -->
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
          当前类型：<strong>{{ typeText(retypeCol.type) }}</strong>
          <span v-if="retypeChanged" class="retype-arrow">→</span>
          <strong v-if="retypeChanged" class="retype-new">{{ typeText(retypeTo) }}</strong>
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
            这一列共有 {{ retypePreview.total }} 个值（跨所有班汇总），
            改类型后会同步转换已填的内容：
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

    <!-- 已停用列：软删的值还在这里，可以一键恢复 -->
    <el-dialog v-model="trashOpen" title="已停用的列" width="560px" append-to-body>
      <p class="trash-hint">
        停用只是把这一列从表格和导出里收起来，<strong>已填的值一行都没删</strong>。
        点「恢复」放回表格，数据原样还在；确认不要了，点「删除」把这一列连同数据一起彻底清除。
      </p>
      <el-table v-loading="trashLoading" :data="disabledColumns" size="small">
        <el-table-column prop="label" label="列名" />
        <el-table-column label="类型" width="90">
          <template #default="{ row }">{{ typeText(row.type) }}</template>
        </el-table-column>
        <el-table-column label="来源" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="row.system ? 'info' : 'success'" disable-transitions>
              {{ row.system ? '模板预置' : '自定义' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" align="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="restoreColumn(row)">恢复</el-button>
            <el-button link type="danger" @click="purgeColumn(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <p class="trash-empty">没有被停用的列</p>
        </template>
      </el-table>
      <template #footer>
        <el-button @click="trashOpen = false">关闭</el-button>
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

.more-caret {
  margin-left: 2px;
}

/* 真藏起来的 file input：仍然可被脚本 .click() 唤起 */
.file-input {
  display: none;
}

/* ---------- 筛选 ---------- */
.filters {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  padding: 10px 12px;
  border: 1px solid var(--color-border);
  border-radius: 10px;
  background: var(--color-card);
}

.f-keyword {
  width: 240px;
}

.f-select {
  width: 190px;
}

/* ---------- 表格 ---------- */
.grid-wrap {
  border: 1px solid var(--color-border);
  border-radius: 10px;
  overflow: auto;
  max-height: calc(100vh - 330px);
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

/* 勾选列并进行号列：单独加一列会把表格整体右移，白白多一列宽度。 */
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
  /* 悬停当前列才显示。表格列名一行几十个，按钮常驻会把「列名 / 类型」冲得七零八落。 */
  opacity: 0;
}

.col-head:hover .col-ops {
  opacity: 1;
}

/* 键盘可达性：Tab 聚焦到某列时也得显出来 */
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

/* 列名 / 类型小标签：能改的时候给出可点的暗示。 */
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
  color: var(--color-muted-fg);
  background: #fafbfd;
}

/*
 * 「班级」那一格：点开是**转班**，不是改文本。
 * 给一个可点的样子（手型 + 悬停描边），别让它看着像改不了的死格。
 */
.cell.transferable {
  cursor: pointer;
}

.cell.transferable:hover {
  box-shadow: inset 0 0 0 1px var(--el-color-primary-light-5);
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

.foot-tip {
  display: block;
  margin-top: 2px;
}

.foot-line {
  display: block;
}

.pager {
  display: flex;
  justify-content: flex-end;
}

/* ---------- 对话框 ---------- */
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

.trash-empty {
  margin: 12px 0;
  text-align: center;
  color: var(--color-muted-fg);
  font-size: 13px;
}
</style>
