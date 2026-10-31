<script setup lang="ts">
/**
 * 学院任务的点名页（第四十五轮）。
 *
 * 班主任打开一个学院任务 → 看到**自己班的学生名册** → 逐个标记状态。
 *
 * 和「回答明细」弹窗是两套东西：那个是院长看结果（只读汇总），
 * 这个是班主任填表（要能改、要随时存）。刻意不复用——
 * 一个组件同时管「看结果」和「填表」，状态和按钮会缠成一团。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getErrorMessage } from '@/api/request'
import { useCloseGuard } from '@/composables/useCloseGuard'
import {
  exportTaskRollcall,
  fetchTaskRollcall,
  saveStudentAnswer,
  saveStudentAnswers,
  type TaskRollcall,
  type TaskRollcallRow,
} from '@/api/tasks'

const props = defineProps<{ taskId: number | null }>()
const visible = defineModel<boolean>({ required: true })
const emit = defineEmits<{ saved: [] }>()

const loading = ref(true)
const loadError = ref('')
const detail = ref<TaskRollcall | null>(null)

/** 当前看的班（班主任带多个班时可切） */
const classId = ref<number | null>(null)

/** 乐观更新：每个学生正在保存的状态（recordId），用于行内 loading */
const savingIds = ref<Set<number>>(new Set())
/** 「保存全部」进行中：整批一个请求，挡住重复点 */
const savingAll = ref(false)
/** 未保存的草稿：recordId -> { value, note }。随时存，但改完没存的要有标记 */
const drafts = reactive<Record<number, { value: string | null; note: string }>>({})

/**
 * BOOLEAN 题型的三个固定选项（SINGLE 用候选项）。
 *
 * 「请假」是第五十五轮加的：只有是/否两档时，「没到但请假了」只能选否，
 * 于是院长看板里的「请假」那一栏永远是 0——做了那一栏却没法填。
 * 后端 `_dump_value` 同步放行这个词（只放行它，BOOLEAN 仍不是自由填空）。
 */
const booleanOptions = ['是', '否', '请假']

/**
 * 把草稿里的显示值翻成**提交给后端的值**。
 *
 * 只有 BOOLEAN 需要转换：草稿里存的是给老师看的「是/否」，
 * 而后端 `_dump_value` 对 BOOLEAN 只认 `true`/`false`——
 * 直接把中文传过去会 400「这一题只能回答「是」或「否」」。
 * SINGLE / MULTI / DATE 的值就是候选项原文，原样传。
 */
function toPayload(value: string | null | undefined): unknown {
  if (value === null || value === undefined) return null
  if (!isBoolean.value) return value
  if (value === '是') return true
  if (value === '否') return false
  return value
}

const rows = computed(() => detail.value?.rows ?? [])
const isSingle = computed(() => detail.value?.qtype === 'SINGLE')
const isBoolean = computed(() => detail.value?.qtype === 'BOOLEAN')

/**
 * 关闭拦截：没存的改动不让随手关。
 *
 * 三条关闭路径（点遮罩 / 点 ✕ / Esc）都汇到 `before-close`，拦这一处就够。
 */
const { onBeforeClose } = useCloseGuard(
  visible,
  computed(() => dirtyCount.value > 0),
  () => `还有 ${dirtyCount.value} 名学生的状态没保存，关闭会丢掉这些改动。确定关闭？`,
)

/** 已填 / 未填的计数（实时算，因为草稿会改） */
const answeredCount = computed(() => rows.value.filter((r) => r.value !== null).length)

/**
 * 「全设为 X」能给的选项。
 *
 * SINGLE 用候选项；BOOLEAN 是固定的「是 / 否」。
 * 其它题型（MULTI / DATE）逐人点名不适用，这里给空数组 → 按钮整组不渲染。
 */
const bulkOptions = computed<string[]>(() => {
  if (isSingle.value) return detail.value?.options ?? []
  if (isBoolean.value) return booleanOptions
  return []
})

/**
 * 勾选中的学生（recordId）。批量操作**只作用于这些行**。
 *
 * 和「全填没填的」那种无差别操作不同：勾谁改谁，是老师自己圈的范围。
 * 搜索时勾选框跟着筛选结果走，但已勾的**不因为被搜掉就丢**——
 * 他搜「李」勾了几个，再搜「王」时那几个李还留在已选里，
 * 回头清空搜索一次性改掉，比「搜一次清一次」符合直觉。
 */
const selectedIds = ref<Set<number>>(new Set())

/** 当前勾选中的完整行（按 rows 取，不受搜索影响） */
const selectedRows = computed(() =>
  rows.value.filter((r) => selectedIds.value.has(r.recordId)),
)

/** 表头全选框的半选/全选态：只看**当前筛选出来的**那批行 */
const allSelected = computed(
  () =>
    filteredRows.value.length > 0 &&
    filteredRows.value.every((r) => selectedIds.value.has(r.recordId)),
)

/** 勾了一部分（不是全勾）：表头显示半选态的三横线 */
const someSelected = computed(
  () => filteredRows.value.some((r) => selectedIds.value.has(r.recordId)),
)

function toggleSelect(id: number) {
  const next = new Set(selectedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedIds.value = next
}

/** 表头勾选框：当前筛选结果全选 / 全不选（不影响筛选外已勾的行） */
function toggleSelectAll() {
  const next = new Set(selectedIds.value)
  if (allSelected.value) {
    for (const r of filteredRows.value) next.delete(r.recordId)
  } else {
    for (const r of filteredRows.value) next.add(r.recordId)
  }
  selectedIds.value = next
}

function clearSelection() {
  selectedIds.value = new Set()
}

/** 改了但还没提交的人数（「保存全部」提交的就是这部分） */
const dirtyCount = computed(
  () => filteredRows.value.filter((r) => isDirty(r) && drafts[r.recordId]?.value !== null).length,
)

/** 搜索：按姓名或学号过滤，方便在几十上百个学生里找人 */
const keyword = ref('')
const filteredRows = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return rows.value
  return rows.value.filter(
    (r) => r.name.toLowerCase().includes(kw) || r.studentNo.toLowerCase().includes(kw),
  )
})

/** 某一行当前显示的值（草稿优先，没草稿就用服务端的） */
function displayValue(row: TaskRollcallRow): string | null {
  const d = drafts[row.recordId]
  return d ? d.value : row.value
}

function displayNote(row: TaskRollcallRow): string {
  const d = drafts[row.recordId]
  return d ? d.note : (row.note ?? '')
}

/** 这一行有没有未保存的改动 */
function isDirty(row: TaskRollcallRow): boolean {
  const d = drafts[row.recordId]
  if (!d) return false
  return d.value !== row.value || d.note !== (row.note ?? '')
}

async function load() {
  if (!props.taskId) return
  loading.value = true
  loadError.value = ''
  try {
    detail.value = await fetchTaskRollcall(props.taskId, classId.value ?? undefined)
    classId.value = detail.value.classId
    // 清空草稿与勾选：换班或重新加载时，它们不能跨班留着
    // （recordId 是全局唯一，但「上个班勾的那几个人」换个班就没意义了）
    for (const k of Object.keys(drafts)) delete drafts[Number(k)]
    selectedIds.value = new Set()
  } catch (e) {
    detail.value = null
    loadError.value = getErrorMessage(e, '打不开点名页')
  } finally {
    loading.value = false
  }
}

/** 换班 */
async function onClassChange(cid: number) {
  classId.value = cid
  await load()
}

/** 选一个状态（还没存，进草稿） */
function pick(row: TaskRollcallRow, value: string) {
  const cur = drafts[row.recordId]
  const nextVal = cur?.value === value ? null : value  // 再点一次 = 取消
  if (!cur) {
    drafts[row.recordId] = { value: nextVal, note: row.note ?? '' }
  } else {
    cur.value = nextVal
  }
}

/** 改这个学生的备注（进草稿，失焦时存） */
function onNoteInput(row: TaskRollcallRow, note: string) {
  const cur = drafts[row.recordId]
  if (cur) {
    cur.note = note
  } else {
    drafts[row.recordId] = { value: row.value, note }
  }
}

/**
 * 把**勾选中的学生**统一标成某个状态。
 *
 * 只进草稿不发请求，统一由「保存全部」一次提交——
 * 勾 30 个人不该变成 30 个网络请求。
 *
 * ⚠ 勾谁改谁，**包括已经填过的**。勾选框圈出来的就是老师要动的范围，
 * 这时还替他跳过「已填的」反而诡异（他明明勾了，点了却没反应）。
 * 要「只补空」的场景是「先全标成到校、再改例外」，那时候例外还没填，
 * 走的本来就是没填那批。
 */
function setSelected(value: string) {
  const targets = selectedRows.value
  if (!targets.length) return
  for (const row of targets) {
    const cur = drafts[row.recordId]
    if (cur) {
      cur.value = value
    } else {
      drafts[row.recordId] = { value, note: row.note ?? '' }
    }
  }
  ElMessage.success(`已把勾选的 ${targets.length} 人标为「${value}」，点「保存全部」提交`)
}

/**
 * 存一个学生。
 *
 * 一次只存一个人：班主任点一个存一个，不用等全班标完再交。
 * 失败时把草稿留着（不清），让他改完再存——清掉才是灾难。
 */
async function saveOne(row: TaskRollcallRow) {
  const d = drafts[row.recordId]
  if (!d || d.value === null) {
    ElMessage.warning(`请先给「${row.name}」选一个状态`)
    return
  }
  if (savingIds.value.has(row.recordId)) return
  savingIds.value.add(row.recordId)
  try {
    const res = await saveStudentAnswer(
      props.taskId!,
      row.recordId,
      toPayload(d.value),
      d.note || undefined,
    )
    // 服务端回执覆盖本地草稿（value 可能被后端归一化过）
    row.value = res.value
    row.raw = res.raw
    row.note = res.note
    row.submittedAt = res.submittedAt
    delete drafts[row.recordId]
    emit('saved')
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '保存失败'))
  } finally {
    savingIds.value.delete(row.recordId)
  }
}

/**
 * 全部保存：把有草稿的**一次请求**提交给后端。
 *
 * 一个班几十人，逐个 PUT 是几十次往返（也是一份几十行的网络日志）；
 * 后端 `save_student_answers` 一次事务写完，中途任何一条不合法整批拒绝。
 * 所以这里失败时**草稿一条都不清**——整批没存进去，界面就不该显示成已存。
 */
async function saveAll() {
  const dirty = rows.value.filter((r) => isDirty(r) && drafts[r.recordId]?.value !== null)
  if (!dirty.length) {
    ElMessage.info('没有需要保存的改动')
    return
  }
  savingAll.value = true
  try {
    const res = await saveStudentAnswers(
      props.taskId!,
      dirty.map((r) => ({
        recordId: r.recordId,
        value: toPayload(drafts[r.recordId]!.value),
        note: drafts[r.recordId]!.note || undefined,
      })),
    )
    // 后端回执只给条数；逐行按本地草稿回填（值已被后端校验过，能走到这里就是合法的）
    for (const row of dirty) {
      const d = drafts[row.recordId]!
      row.value = d.value
      row.note = d.note || null
      row.submittedAt = new Date().toISOString().slice(0, 16).replace('T', ' ')
      delete drafts[row.recordId]
    }
    ElMessage.success(`已保存 ${res.saved} 人`)
    emit('saved')
  } catch (e) {
    // 整批失败：草稿全留着，改完可以直接再点一次
    ElMessage.error(getErrorMessage(e, '保存失败'))
  } finally {
    savingAll.value = false
  }
}

watch(visible, (open) => {
  if (open) void load()
})

onMounted(() => {
  if (visible.value) void load()
})

/** 导出中状态（防连点） */
const exporting = ref(false)

async function onExport() {
  if (!props.taskId) return
  exporting.value = true
  try {
    await exportTaskRollcall(props.taskId, detail.value?.classId)
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '导出失败'))
  } finally {
    exporting.value = false
  }
}

/** 供模板判断：qtype 是 BOOLEAN 时显示 是/否 两个按钮 */
</script>

<template>
  <el-drawer
    v-model="visible"
    :title="detail ? `点名 · ${detail.title}` : '点名'"
    size="min(720px, 96vw)"
    :close-on-click-modal="true"
    :before-close="onBeforeClose"
  >
    <div v-loading="loading" class="rollcall">
      <el-alert
        v-if="loadError"
        type="error"
        :title="loadError"
        show-icon
        :closable="false"
        class="err"
      />

      <template v-if="detail">
        <div class="head">
          <p class="q">
            {{ detail.question }}
            <span class="qtype">{{ detail.qtypeText }}</span>
          </p>
          <p class="meta">
            共 {{ detail.total }} 人，已填 {{ answeredCount }}，未填 {{ detail.total - answeredCount }}
            <template v-if="detail.deadline">，截止 {{ detail.deadline }}</template>
          </p>
        </div>

        <!-- 多个班时给切换器 -->
        <div v-if="detail.classes.length > 1" class="class-switch">
          <span>班级：</span>
          <el-radio-group
            :model-value="detail.classId"
            size="small"
            @update:model-value="onClassChange"
          >
            <el-radio-button
              v-for="c in detail.classes"
              :key="c.classId"
              :value="c.classId"
            >
              {{ c.className }}
            </el-radio-button>
          </el-radio-group>
        </div>

        <!-- 批量条：勾中人才出现。和搜索框分开一行，
             因为「对人动手」的代价比查询高得多，混在一起容易误点 -->
        <div v-if="selectedIds.size" class="batch-bar" role="group" aria-label="批量操作">
          <span>已选 <strong>{{ selectedIds.size }}</strong> 人</span>
          <el-button
            v-for="opt in bulkOptions"
            :key="opt"
            size="small"
            @click="setSelected(opt)"
          >
            全设为「{{ opt }}」
          </el-button>
          <el-button size="small" text @click="clearSelection">取消选择</el-button>
        </div>

        <div class="toolbar">
          <el-input
            v-model="keyword"
            placeholder="搜索姓名 / 学号"
            clearable
            class="search"
            aria-label="搜索学生"
          />
          <div class="spacer" />
          <el-button
            type="primary"
            :loading="savingAll"
            :disabled="dirtyCount === 0"
            @click="saveAll"
          >
            保存全部{{ dirtyCount ? `（${dirtyCount}）` : '' }}
          </el-button>
          <el-button :loading="exporting" @click="onExport">导出</el-button>
        </div>

        <div class="table-wrap">
          <table class="roll-table">
            <thead>
              <tr>
                <th scope="col" class="check-col">
                  <el-checkbox
                    :model-value="allSelected"
                    :indeterminate="someSelected && !allSelected"
                    aria-label="全选当前列表"
                    @change="toggleSelectAll"
                  />
                </th>
                <th scope="col">学号</th>
                <th scope="col">姓名</th>
                <th scope="col">状态</th>
                <th v-if="detail.allowText" scope="col">备注</th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in filteredRows"
                :key="row.recordId"
                :class="{ dirty: isDirty(row), selected: selectedIds.has(row.recordId) }"
              >
                <td class="check-col">
                  <el-checkbox
                    :model-value="selectedIds.has(row.recordId)"
                    :aria-label="`选择 ${row.name}`"
                    @change="toggleSelect(row.recordId)"
                  />
                </td>
                <td class="num">{{ row.studentNo }}</td>
                <td>
                  <b>{{ row.name }}</b>
                  <span v-if="row.submittedAt && !isDirty(row)" class="ts">
                    {{ row.submittedAt }}
                  </span>
                </td>
                <td>
                  <!-- SINGLE：候选项按钮；BOOLEAN：是/否 -->
                  <div class="opts">
                    <template v-if="isSingle">
                      <el-button
                        v-for="o in detail.options"
                        :key="o"
                        size="small"
                        :type="displayValue(row) === o ? 'primary' : 'default'"
                        @click="pick(row, o)"
                      >
                        {{ o }}
                      </el-button>
                    </template>
                    <template v-else-if="isBoolean">
                      <el-button
                        v-for="o in booleanOptions"
                        :key="o"
                        size="small"
                        :type="displayValue(row) === o ? 'primary' : 'default'"
                        @click="pick(row, o)"
                      >
                        {{ o }}
                      </el-button>
                    </template>
                    <span v-else class="muted">题型 {{ detail.qtypeText }} 暂不支持逐人点名</span>
                  </div>
                </td>
                <td v-if="detail.allowText">
                  <el-input
                    :model-value="displayNote(row)"
                    size="small"
                    maxlength="255"
                    placeholder="选填"
                    @update:model-value="(v: string) => onNoteInput(row, v)"
                  />
                </td>
                <td>
                  <el-button
                    size="small"
                    type="primary"
                    :loading="savingIds.has(row.recordId)"
                    :disabled="!isDirty(row) && displayValue(row) === null"
                    @click="saveOne(row)"
                  >
                    保存
                  </el-button>
                </td>
              </tr>
            </tbody>
          </table>

          <el-empty
            v-if="!filteredRows.length"
            :description="keyword ? '没有匹配的学生' : '这个班还没有学生名册'"
            :image-size="80"
          />
        </div>

        <p class="tip">
          点一个状态就存一个人，不用等全班标完；改过的行会标黄，点「保存」才生效。
        </p>
      </template>
    </div>
  </el-drawer>
</template>

<style scoped>
.rollcall {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  min-height: 200px;
}

.err {
  margin-bottom: var(--space-sm);
}

.head .q {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}

.qtype {
  margin-left: 6px;
  font-size: 12px;
  font-weight: 400;
  color: var(--color-muted-fg);
}

.head .meta {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--color-muted-fg);
}

.class-switch {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.toolbar {
  display: flex;
  gap: var(--space-sm);
  align-items: center;
}

/* 撑开右侧：让「保存全部 / 导出」贴到右边，不和搜索框挤在一起 */
.spacer {
  flex: 1;
}

/* 批量条：勾中人才出现，用浅底色和工具栏分开
   （这是「对人动手」的一排按钮，不该长得和搜索条一样） */
.batch-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-sm) var(--space-md);
  background: var(--el-fill-color-light);
  border-radius: var(--radius);
  font-size: 13px;
}

.check-col {
  width: 36px;
  padding-left: 6px !important;
  padding-right: 0 !important;
}

.search {
  flex: 1;
  max-width: 240px;
}

.table-wrap {
  overflow-x: auto;
}

.roll-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.roll-table th,
.roll-table td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--color-border);
  text-align: left;
  vertical-align: middle;
}

.roll-table thead th {
  background: var(--color-surface, #fff);
  font-weight: 600;
  color: var(--color-foreground);
  white-space: nowrap;
}

.roll-table tbody tr.dirty {
  background: var(--el-color-warning-light-9);
}

/* 选中行：浅蓝底。和「未保存」的黄底分开——
   一个是「我圈了这批要动」，一个是「改了还没存」，两件事不该混一个颜色 */
.roll-table tbody tr.selected {
  background: var(--el-color-primary-light-9);
}

.roll-table tbody tr.dirty.selected {
  background: var(--el-color-primary-light-8);
}

.ts {
  display: block;
  font-size: 11px;
  color: var(--color-muted-fg);
}

.opts {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.muted {
  color: var(--color-muted-fg);
}

.tip {
  margin: 0;
  font-size: 12px;
  color: var(--color-muted-fg);
}
</style>
