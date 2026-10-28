<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getErrorMessage } from '@/api/request'
import { deleteTask, exportTaskDetail, setTaskOpen, setTaskPinned } from '@/api/tasks'
import { fetchCollegeTasks } from '@/api/college'
import TaskPublishDialog from '@/components/TaskPublishDialog.vue'
import { useUserStore } from '@/stores/user'
import type { CollegeTaskList, CollegeTaskRow, TaskScope } from '@/types'

/**
 * 学院视角的任务一览（第三十轮 + 第三十二轮）。
 *
 * 同一个页面服务侧栏「学院 > 任务」下面的两个入口，靠路由传入的
 * `scope` 区分看哪一类：
 *
 * | scope | 页面标题 | 看什么 | 谁发的 |
 * |-------|---------|--------|--------|
 * | `COLLEGE` | 学院任务 | 院长发到**全学院**的任务，各班班主任应答 | 院长 |
 * | `CLASS` | 班级任务 | **各班班主任**发给自己班的任务，同学应答 | 班主任 / 班长 |
 *
 * ## 和「班级 → 班级任务」的区别
 *
 * 「班级 > 班级任务」是**本班**的任务页，能发布/关闭/改置顶/答题。
 * 这里的两页都是**跨班级**的**只读**一览：谁发了什么题、回收了多少。
 * 改任务在班级页做——学院视角一旦能改，就会有两个可写入口。
 *
 * ## 「已填 X / 共 Y 人」的分母
 *
 * - 班级任务：**该任务自己那个班**的人数（跨班混算会得出没人看得懂的数）
 * - 学院任务：**全校班主任**的人数（一人代表一个班）
 */
const props = defineProps<{ scope: TaskScope }>()

const userStore = useUserStore()
const isCollege = computed(() => props.scope === 'COLLEGE')

/**
 * 能不能发布学院任务：**只有院长**。
 *
 * 后端 `create_task(scope='COLLEGE')` 也拦（班主任发会 403），
 * 这里是入口层的同一道门——按不了的东西就不该在页面上。
 */
const canPublishCollege = computed(() => userStore.user?.role === 'DEAN')

/** 页面标题与说明：两类任务说清楚「谁发的、谁来答」 */
const title = computed(() => (isCollege.value ? '学院任务' : '班级任务'))
const subtitle = computed(() =>
  isCollege.value
    ? '学院任务由院长发布：全学院都看得见，由各班班主任应答（比如「各班统计一下本班返校情况，交上来」）。班主任在本班任务页里填。'
    : '这里是各班班主任（和班长）发给自己班的任务一览：谁发了什么题、回收了多少。',
)

const list = ref<CollegeTaskList | null>(null)
const loading = ref(true)
const loadError = ref(false)

const keyword = ref('')
const classId = ref<number | null>(null)
const onlyPinned = ref(false)

const applied = ref<{ keyword: string; classId: number | null; onlyPinned: boolean }>({
  keyword: '',
  classId: null,
  onlyPinned: false,
})

async function load() {
  loading.value = true
  try {
    list.value = await fetchCollegeTasks({
      keyword: applied.value.keyword,
      // 学院任务不属于任何班，按班筛它没有意义
      classId: isCollege.value ? null : applied.value.classId,
      onlyPinned: applied.value.onlyPinned,
      scope: props.scope,
    })
    loadError.value = false
  } catch {
    list.value = null
    loadError.value = true
  } finally {
    loading.value = false
  }
}

function search() {
  applied.value = {
    keyword: keyword.value.trim(),
    classId: classId.value,
    onlyPinned: onlyPinned.value,
  }
  void load()
}

function reset() {
  keyword.value = ''
  classId.value = null
  onlyPinned.value = false
  applied.value = { keyword: '', classId: null, onlyPinned: false }
  void load()
}

const rows = computed(() => list.value?.rows ?? [])

/** 发布学院任务的对话框（第三十二轮）——只有学院任务能发 */
const publishVisible = ref(false)

function openCreateCollege() {
  publishVisible.value = true
}

/** 编辑：复用发布对话框的「修改」模式（题型/候选项不给改） */
const editingTask = ref<CollegeTaskRow | null>(null)
const editVisible = ref(false)
function openEdit(row: CollegeTaskRow) {
  editingTask.value = row
  editVisible.value = true
}

/** 批量选择（仅学院任务视图；班级任务一览仍只读） */
const selectedIds = ref<number[]>([])
const allSelected = computed(
  () => rows.value.length > 0 && rows.value.every((r) => selectedIds.value.includes(r.id)),
)
function toggleSelect(id: number) {
  const i = selectedIds.value.indexOf(id)
  if (i >= 0) selectedIds.value.splice(i, 1)
  else selectedIds.value.push(id)
}
function toggleSelectAll() {
  selectedIds.value = allSelected.value ? [] : rows.value.map((r) => r.id)
}

async function toggleOpen(row: CollegeTaskRow) {
  try {
    await setTaskOpen(row.id, !row.open)
    await load()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '操作失败'))
  }
}

async function togglePin(row: CollegeTaskRow) {
  try {
    await setTaskPinned(row.id, !row.pinned)
    await load()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '操作失败'))
  }
}

async function removeTask(row: CollegeTaskRow) {
  try {
    await ElMessageBox.confirm(
      `确定删除任务「${row.title}」吗？连带已收回的答案一起删除，不可恢复。`,
      '删除任务',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteTask(row.id)
    selectedIds.value = selectedIds.value.filter((id) => id !== row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '删除失败'))
  }
}

async function batchRemove() {
  const ids = [...selectedIds.value]
  if (!ids.length) return
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${ids.length} 条任务吗？连带答案一起删除，不可恢复。`,
      '批量删除',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  const results = await Promise.allSettled(ids.map((id) => deleteTask(id)))
  const okCount = results.filter((r) => r.status === 'fulfilled').length
  const failCount = results.length - okCount
  selectedIds.value = []
  if (failCount > 0) {
    ElMessage.warning(`已删除 ${okCount} 条，${failCount} 条失败（可能不是你发布的）`)
  } else {
    ElMessage.success(`已删除 ${okCount} 条任务`)
  }
  await load()
}

/** 导出这一条任务的全部回答（谁填了什么、谁还没填） */
async function onExport(row: CollegeTaskRow) {
  try {
    await exportTaskDetail(row.id)
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '导出失败'))
  }
}

/** 汇总：开放中的、置顶的 */
const openCount = computed(() => rows.value.filter((r) => r.open).length)
const pinnedCount = computed(() => rows.value.filter((r) => r.pinned).length)

function fmtTime(value: string | null | undefined): string {
  return value ? value.slice(0, 16) : '—'
}

/** 回收进度（0-100）。分母为 0 时给 0——没有应答对象时「100%」是假的 */
function rate(row: { answered: number; total: number }): number {
  if (!row.total) return 0
  return Math.round((row.answered / row.total) * 100)
}

/**
 * 「学院任务」和「班级任务」两个路由**共用这一个组件**（只是 `scope` 不同）。
 *
 * ⚠ 共用组件的坑：Vue Router 认为还是同一个组件，**直接复用实例**，
 * `onMounted` 不会再触发一次——从「学院任务」切到「班级任务」时页面还留着
 * 上一个页面的数据（列表看着像串了）。所以 `scope` 一变就必须重新拉。
 */
watch(
  () => props.scope,
  () => {
    void load()
  },
)

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>{{ title }}</h2>
        <p>{{ subtitle }}</p>
      </div>
      <el-button v-if="isCollege && canPublishCollege" type="primary" @click="openCreateCollege">
        发布学院任务
      </el-button>
    </div>

    <TaskPublishDialog
      v-model="publishVisible"
      scope="COLLEGE"
      @saved="load"
    />

    <!-- 编辑：复用发布对话框的「修改」模式（题型/候选项不给改） -->
    <TaskPublishDialog
      v-model="editVisible"
      scope="COLLEGE"
      :task="editingTask"
      @saved="load"
    />

    <section class="glass-card filters" aria-label="搜索筛选">
      <div class="filter-row">
        <el-input
          v-model="keyword"
          class="f-keyword"
          placeholder="搜索任务标题或题目"
          aria-label="搜索任务"
          clearable
          @keyup.enter="search"
          @clear="search"
        />
        <el-select
          v-if="!isCollege"
          v-model="classId"
          class="f-select"
          placeholder="全部班级"
          aria-label="按班级筛选"
          clearable
          @change="search"
        >
          <el-option
            v-for="c in list?.classes ?? []"
            :key="c.id"
            :label="c.grade ? `${c.className}（${c.grade}）` : c.className"
            :value="c.id"
          />
        </el-select>
        <el-checkbox v-model="onlyPinned" @change="search">只看置顶</el-checkbox>
        <el-button type="primary" @click="search">查询</el-button>
        <el-button @click="reset">重置</el-button>
      </div>
      <p class="filter-hint">
        共 {{ rows.length }} 条任务，其中 {{ openCount }} 条开放中、{{ pinnedCount }} 条置顶。
        <template v-if="isCollege">应答对象是<strong>各班班主任</strong>，一人代表一个班。</template>
        <template v-else>「已填 / 共」的分母是<strong>该任务自己那个班</strong>的人数。</template>
      </p>
    </section>

    <div
      v-if="selectedIds.length"
      style="display: flex; align-items: center; gap: 10px; padding: 8px 12px; background: var(--el-fill-color-light); border-radius: 6px"
    >
      <span>已选 <strong>{{ selectedIds.length }}</strong> 条</span>
      <el-button size="small" type="danger" @click="batchRemove">批量删除</el-button>
      <el-button size="small" @click="selectedIds = []">取消选择</el-button>
    </div>

    <section class="glass-card" aria-label="任务一览" :aria-busy="loading">
      <div v-if="rows.length > 0" class="table-wrap">
        <table class="roster">
          <thead>
            <tr>
              <th scope="col">
                <el-checkbox :model-value="allSelected" @change="toggleSelectAll" aria-label="全选" />
              </th>
              <th v-if="!isCollege" scope="col">班级</th>
              <th v-else scope="col">发布人</th>
              <th scope="col">标题</th>
              <th scope="col">题目</th>
              <th scope="col">状态</th>
              <th scope="col">回收进度</th>
              <th scope="col">截止</th>
              <th scope="col">发布时间</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td>
                <el-checkbox
                  :model-value="selectedIds.includes(row.id)"
                  :aria-label="`选择 ${row.title}`"
                  @change="toggleSelect(row.id)"
                />
              </td>
              <td>{{ isCollege ? row.publisher || '—' : row.className }}</td>
              <td>
                {{ row.title }}
                <el-tag v-if="row.pinned" size="small" type="warning" effect="plain">置顶</el-tag>
              </td>
              <td class="q">{{ row.question }}</td>
              <td>
                <el-tag size="small" effect="plain" :type="row.open ? 'success' : 'info'">
                  {{ row.open ? '开放中' : '已关闭' }}
                </el-tag>
              </td>
              <td class="progress-cell">
                <el-progress
                  :percentage="rate(row)"
                  :stroke-width="8"
                  :show-text="false"
                  color="var(--color-accent-text)"
                  aria-hidden="true"
                />
                <span class="progress-text num">已填 {{ row.answered }} / 共 {{ row.total }} 人</span>
              </td>
              <td class="num">{{ fmtTime(row.deadline) }}</td>
              <td class="num">{{ fmtTime(row.createdAt) }}</td>
              <td>
                <el-button size="small" @click="onExport(row)">导出</el-button>
                <template v-if="row.canEdit">
                  <el-button size="small" @click="openEdit(row)">编辑</el-button>
                  <el-button size="small" @click="toggleOpen(row)">
                    {{ row.open ? '关闭' : '重开' }}
                  </el-button>
                  <el-button size="small" @click="togglePin(row)">
                    {{ row.pinned ? '取消置顶' : '置顶' }}
                  </el-button>
                  <el-button size="small" type="danger" @click="removeTask(row)">删除</el-button>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <el-empty
        v-else-if="!loading"
        :description="
          loadError
            ? `${title}加载失败，请检查网络后重试`
            : applied.keyword || applied.classId || applied.onlyPinned
              ? '没有符合条件的任务'
              : isCollege
                ? '还没有发布过学院任务'
                : '还没有班级发布过任务'
        "
        :image-size="80"
      >
        <el-button v-if="loadError" type="primary" @click="load">重新加载</el-button>
      </el-empty>
    </section>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}

.filters {
  padding: var(--space-md);
}

.filter-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
}

.f-keyword {
  flex: 1 1 260px;
  min-width: 200px;
}

.f-select {
  width: 200px;
}

.filter-hint {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--color-muted-fg);
}

.table-wrap {
  overflow-x: auto;
}

.roster {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.roster th,
.roster td {
  padding: 9px 12px;
  border-bottom: 1px solid var(--color-border);
  text-align: left;
  vertical-align: top;
}

.roster thead th {
  background: var(--color-surface, #fff);
  font-weight: 600;
  color: var(--color-foreground);
  white-space: nowrap;
}

.q {
  max-width: 320px;
  white-space: normal;
}

.progress-cell {
  min-width: 160px;
}

.progress-text {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: var(--color-muted-fg);
}
</style>
