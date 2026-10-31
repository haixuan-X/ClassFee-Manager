<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getErrorMessage } from '@/api/request'
import {
  deleteTask,
  exportTaskDetail,
  fetchTaskDetail,
  fetchTasks,
  setTaskOpen,
  setTaskPinned,
  submitTaskAnswer,
  TASK_QTYPES,
} from '@/api/tasks'
import TaskPublishDialog from '@/components/TaskPublishDialog.vue'
import TaskRollcallDrawer from '@/components/TaskRollcallDrawer.vue'
import { useModal } from '@/composables/useModal'
import { useCloseGuard } from '@/composables/useCloseGuard'
import type {
  Task,
  TaskDetail,
  TaskQType,
  TaskScope,
  TaskView,
} from '@/types'

/**
 * 班级任务（第二十五轮）。
 *
 * 和第二十四轮删掉的班级公告的**唯一区别**：公告发出去就看，任务发出去之后
 * **还要有人回来填**。所以这页有三个「看」，权限各不相同：
 *
 * | 谁 | 任务列表 | 我填题 | 「谁填了什么」明细 |
 * |----|---------|--------|------------------|
 * | 班主任（发布人） | ✅ 看到汇总 | **❌** | ✅ |
 * | 生活委员 / 同学 | ✅ **只到汇总** | ✅ | ❌ 403 |
 * | 班长（自己发的题除外） | ✅ | ✅ | ❌ 403 |
 * | 访客 | ✅ 只到汇总 | **❌** | ❌ 403 |
 *
 * 列表对所有人一律只到「汇总」这一层——汇总给的是「多少人是、多少否」，
 * 用来催人交；「张伟没返校」这种具体到人的答案只在明细页，而明细只有发布人和
 * 班主任能看。所以这里**不需要**在前端过滤：后端已经把不该给的裁掉了。
 *
 * 注意本文件**不引入 userStore**：能不能填完全由后端下发的 `canAnswer` 决定，
 * 角色判断留在后端一处（`task_service.NON_ANSWER_ROLES`：班主任和访客不算被统计的
 * 同学），前端不再写第二份口径。班主任和访客因此**根本看不到「填写答案」按钮**，
 * 不是按钮禁用——按不了的东西就不该在页面上。
 */

const loading = ref(true)
const rows = ref<Task[]>([])
const canPublish = ref(false)
const canPublishCollege = ref(false)

/**
 * 看哪一块（第三十二轮）。
 *
 * - mine（默认）：**本班**的任务 + **学院**的任务
 * - college：只看学院任务
 * - other：**其他班**班主任发出来的（只读；同学看与自己无关，所以不显示这一档）
 */
const view = ref<TaskView>('mine')

/**
 * 范围切换（第三十三轮：班级数据不互通）。
 *
 * 只保留两档：本班 + 学院、学院任务。
 * **刻意没有「其他班」**——班主任 / 班长 / 生活委员 / 同学都只能看
 * 「自己班 + 院长下发的学院任务」，看别的班属于越界。
 */
const VIEWS: { key: TaskView; label: string; hint: string }[] = [
  { key: 'mine', label: '本班 + 学院', hint: '我自己班的，以及学院发下来的' },
  { key: 'college', label: '学院任务', hint: '院长发到全学院的，各班班主任应答' },
]

const visibleViews = VIEWS

async function load() {
  loading.value = true
  try {
    const data = await fetchTasks(view.value)
    rows.value = data.rows
    canPublish.value = data.canPublish
    canPublishCollege.value = data.canPublishCollege
  } catch {
    rows.value = []
  } finally {
    loading.value = false
  }
}

function switchView(v: TaskView) {
  if (view.value === v) return
  view.value = v
  void load()
}

/* ============================ 题型说明 ============================ */

const qtypeLabel = (t: TaskQType) => TASK_QTYPES.find((x) => x.value === t)?.label ?? t

/** 汇总条的总份数，用来画进度条；分母 0（没有应答对象）时按 0 处理，不除零。 */
const percent = (answered: number, total: number) =>
  total > 0 ? Math.round((answered / total) * 100) : 0

/* ============================ 发布 / 修改 ============================ */

const formVisible = ref(false)
/** 发布哪一类任务（第三十二轮） */
const formScope = ref<TaskScope>('CLASS')
/** 传了就进「修改」模式 */
const editingTask = ref<Task | null>(null)

function openCreate() {
  editingTask.value = null
  formScope.value = 'CLASS'
  formVisible.value = true
}

/**
 * 发布**学院任务**（第三十二轮）：全学院可见，由**各班班主任**应答。
 *
 * 只有一个入口按钮是不够的——「发布任务」和「发布学院任务」的区别
 * 体现在**谁来答**上，界面上必须分开说清楚，不能让人发错了再返工。
 */
function openCreateCollege() {
  editingTask.value = null
  formScope.value = 'COLLEGE'
  formVisible.value = true
}

/** 改任务。**题型和候选项不给改**——换题型会让已收回的答案对不上题。 */
function openEdit(row: Task) {
  editingTask.value = row
  formScope.value = row.scope
  formVisible.value = true
}

/* ============================ 答题 ============================ */

const answerVisible = ref(false)
const answerLoading = ref(false)
const current = ref<Task | null>(null)
/** BOOLEAN 用 boolean|null；SINGLE/MULTI 用 string[]；DATE 用 string */
const answerValue = ref<boolean | string | string[] | null>(null)
const answerNote = ref('')
const { restoreFocus: restoreAnswerFocus } = useModal(answerVisible)

function openAnswer(row: Task) {
  current.value = row
  answerNote.value = row.myAnswer?.note ?? ''
  // 回填时要还原成**题型对应的形状**，不能把展示文字直接塞回去：
  // MULTI 存的是 JSON 数组字符串、SINGLE 存选项原文、BOOLEAN 存 "true"/"false"。
  switch (row.qtype) {
    case 'BOOLEAN':
      answerValue.value =
        row.myAnswer?.raw === 'true' ? true : row.myAnswer?.raw === 'false' ? false : null
      break
    case 'MULTI': {
      try {
        answerValue.value = row.myAnswer?.raw ? JSON.parse(row.myAnswer.raw) : []
      } catch {
        answerValue.value = []
      }
      break
    }
    default:
      answerValue.value = row.myAnswer?.raw ?? null
  }
  answerVisible.value = true
  // 存一份快照，供「有未保存改动就不让随手关」比对
  answerBaseline.value = answerSnapshot()
}

/** 答案 + 备注的快照（字符串化，直接比对） */
function answerSnapshot(): string {
  return JSON.stringify({ v: answerValue.value, n: answerNote.value })
}

/** 打开那一刻的答案状态 */
const answerBaseline = ref('')

/** 答题弹窗有没有未保存的改动 */
const answerDirty = computed(() => answerSnapshot() !== answerBaseline.value)

/**
 * 关闭拦截：答案改过就不让随手关。
 *
 * 三条关闭路径（点遮罩 / 点 ✕ / Esc）都汇到 `before-close`，拦这一处就够。
 */
const { onBeforeClose: onAnswerBeforeClose } = useCloseGuard(
  answerVisible,
  answerDirty,
  () => '答案还没提交，关闭会丢掉这些改动。确定关闭？',
)

/** MULTI 的勾选由 el-checkbox-group 自己管数组，这里只判「有没有至少选一项」 */
const canSubmitAnswer = computed(() => {
  const v = answerValue.value
  if (v === null || v === undefined || v === '') return false
  if (Array.isArray(v)) return v.length > 0
  if (typeof v === 'boolean') return true
  return true
})

async function submitAnswer() {
  const task = current.value
  if (!task || answerLoading.value) return
  if (!canSubmitAnswer.value) {
    ElMessage.warning('请先选择或填写答案')
    return
  }
  answerLoading.value = true
  try {
    await submitTaskAnswer(task.id, answerValue.value, answerNote.value.trim() || null)
    ElMessage.success(task.myAnswer ? '答案已修改' : '已提交')
    answerVisible.value = false
    await load()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '提交失败'))
  } finally {
    answerLoading.value = false
  }
}

/* ============================ 明细 ============================ */

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<TaskDetail | null>(null)
const { restoreFocus: restoreDetailFocus } = useModal(detailVisible)

/** 点名抽屉（第四十五轮）：学院任务按学生逐个标记 */
const rollcallVisible = ref(false)
const rollcallTaskId = ref<number | null>(null)

function openRollcall(row: Task) {
  rollcallTaskId.value = row.id
  rollcallVisible.value = true
}

async function openDetail(row: Task) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await fetchTaskDetail(row.id)
  } catch (e) {
    detailVisible.value = false
    ElMessage.error(getErrorMessage(e, '打不开明细'))
  } finally {
    detailLoading.value = false
  }
}

async function onExport(taskId: number) {
  try {
    await exportTaskDetail(taskId)
    ElMessage.success('已导出')
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '导出失败'))
  }
}

/** 明细弹窗里的「导出」：用当前这条明细的 taskId */
async function onExportDetail() {
  if (!detail.value) return
  await onExport(detail.value.taskId)
}

/* ============================ 关闭 / 重开 / 删除 ============================ */

async function onToggleOpen(row: Task) {
  try {
    await setTaskOpen(row.id, !row.open)
    ElMessage.success(row.open ? '任务已关闭' : '任务已重新开放')
    await load()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '操作失败'))
  }
}

async function onTogglePin(row: Task) {
  try {
    await setTaskPinned(row.id, !row.pinned)
    ElMessage.success(row.pinned ? '已取消置顶' : '已置顶，全班仪表盘都会显示')
    await load()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '操作失败'))
  }
}

async function onDelete(row: Task) {
  try {
    await ElMessageBox.confirm(
      `确认删除任务「${row.title}」？` +
        `已经收回的 ${row.summary.answered} 份回答会一起删除，不可恢复。`,
      '删除任务',
      { type: 'error', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteTask(row.id)
    ElMessage.success('任务已删除')
    await load()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '删除失败'))
  }
}

/** 批量选择：只对「自己能删的」任务显示复选框（发布人自己；院长可管全院） */
const selectedIds = ref<number[]>([])
function toggleSelect(id: number) {
  const i = selectedIds.value.indexOf(id)
  if (i >= 0) selectedIds.value.splice(i, 1)
  else selectedIds.value.push(id)
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
  if (failCount > 0) ElMessage.warning(`已删除 ${okCount} 条，${failCount} 条失败`)
  else ElMessage.success(`已删除 ${okCount} 条任务`)
  await load()
}

/* ============================ 杂项 ============================ */

// 只用于**已知角色**的兜底显示（`ROLE_TEXT[row.role] ?? row.role`）。
// 权威中文名在 `@/types` 的 ROLE_TEXT，这里保持同口径。
const ROLE_TEXT: Record<string, string> = {
  DEAN: '院长',
  TEACHER: '班主任',
  MONITOR: '班长',
  ADMIN: '生活委员',
  MEMBER: '普通成员',
  GUEST: '访客',
}

const emptyText = '还没有任务'

const alertMessage = ref('')
const alertRef = ref<HTMLElement>()
async function showAlert(message: string) {
  alertMessage.value = message
  await nextTick()
  alertRef.value?.focus()
}

onMounted(async () => {
  await load()
  if (!canPublish.value && rows.value.length === 0) {
    await showAlert('还没有任何任务。任务由班主任或班长发布，发布后同学点这里填写。')
  }
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>班级任务</h2>
        <p>
          班主任或班长发一个题，全班在这里填；只公布「多少人是、多少否」，具体谁填了什么只有发布人和班主任看得到。
          <strong>学院任务</strong>是院长发到全学院的，由<strong>各班班主任</strong>应答，也在这里填。
        </p>
      </div>
      <div class="head-tools">
        <el-button v-if="canPublish" type="primary" @click="openCreate">发布任务</el-button>
        <el-button v-if="canPublishCollege" @click="openCreateCollege">发布学院任务</el-button>
      </div>
    </div>

    <!-- 范围切换：第三十二轮 -->
    <div class="view-switch" role="tablist" aria-label="任务范围">
      <button
        v-for="v in visibleViews"
        :key="v.key"
        type="button"
        role="tab"
        class="view-btn"
        :class="{ active: view === v.key }"
        :aria-selected="view === v.key"
        :title="v.hint"
        @click="switchView(v.key)"
      >
        {{ v.label }}
      </button>
    </div>

    <p ref="alertRef" class="sr-alert" role="alert">{{ alertMessage }}</p>

    <div
      v-if="selectedIds.length"
      style="display: flex; align-items: center; gap: 10px; padding: 8px 12px; background: var(--el-fill-color-light); border-radius: 6px"
    >
      <span>已选 <strong>{{ selectedIds.length }}</strong> 条</span>
      <el-button size="small" type="danger" @click="batchRemove">批量删除</el-button>
      <el-button size="small" @click="selectedIds = []">取消选择</el-button>
    </div>

    <div v-loading="loading" class="task-list" aria-label="任务列表">
      <p v-if="!loading && rows.length === 0" class="glass-card empty">{{ emptyText }}</p>

      <section v-for="row in rows" :key="row.id" class="glass-card task" :aria-label="row.title">
        <header class="task-head">
          <el-checkbox
            v-if="row.canEdit"
            :model-value="selectedIds.includes(row.id)"
            :aria-label="`选择 ${row.title}`"
            @change="toggleSelect(row.id)"
          />
          <div class="head-left">
            <h3>
              {{ row.title }}
              <el-tag v-if="row.scope === 'COLLEGE'" size="small" type="primary" effect="plain">
                学院任务
              </el-tag>
              <el-tag v-else-if="row.className" size="small" type="info" effect="plain">
                {{ row.className }}
              </el-tag>
              <el-tag v-if="row.pinned" size="small" type="danger" effect="plain">置顶</el-tag>
              <el-tag v-if="row.isMine" size="small" type="warning" effect="plain">我发布的</el-tag>
              <el-tag v-if="!row.open" size="small" type="info" effect="plain">已关闭</el-tag>
              <el-tag v-else-if="row.deadline" size="small" type="info" effect="plain">
                截止 {{ row.deadline }}
              </el-tag>
            </h3>
            <p class="q">
              {{ row.question }}
              <span class="qtype">{{ row.qtypeText }}</span>
            </p>
          </div>
          <!-- 只渲染**能点**的按钮。原先这里还放了两个 disabled 的：
               「已提交」和访客看到的「不能填写」。按不了就是不该有——
               页面上摆个死元素只会让人反复去点它（用户原话「不能填写就不能填写呗」）。
               状态不用按钮来表达，卡片正文本来就说清楚了：
               - 填过 → 下面「我的答案：X（备注）提交于 …」
               - 填不了 → 标题旁的「已关闭」/「截止 …」标签
               访客看不到答案、也拿不到按钮，只剩汇总数字，意思已经够了。 -->
          <div v-if="row.canAnswer" class="head-right">
            <el-button type="primary" size="small" @click="openAnswer(row)">
              {{ row.myAnswer ? '修改我的答案' : '填写答案' }}
            </el-button>
          </div>
          <!-- 学院任务的点名入口（第四十五轮）。
               canAnswer 对班主任是 true（他是应答对象），但学院任务要走**点名页**
               而不是单选弹窗——所以这里单独判断 scope，不能复用 canAnswer -->
          <div v-if="row.scope === 'COLLEGE' && row.open" class="head-right">
            <el-button type="primary" size="small" @click="openRollcall(row)">
              点名
            </el-button>
          </div>
        </header>

        <!-- 汇总：只有分布，没有具体是谁。所有角色看到的是同一份 -->
        <div class="summary">
          <div class="bar-line">
            <span class="muted">
              已填 <b>{{ row.summary.answered }}</b> / 共 {{ row.summary.total }} 人
              <template v-if="row.summary.unanswered > 0">
                ，还差 {{ row.summary.unanswered }} 人
              </template>
            </span>
            <el-progress
              :percentage="percent(row.summary.answered, row.summary.total)"
              :stroke-width="8"
              :show-text="false"
              class="bar"
            />
          </div>
          <ul v-if="row.summary.options.length" class="dist">
            <li v-for="o in row.summary.options" :key="o.label">
              <span class="lbl">{{ o.label }}</span>
              <span class="cnt">{{ o.count }}</span>
            </li>
          </ul>
        </div>

        <!-- 我的答案 -->
        <p v-if="row.myAnswer" class="mine">
          我的答案：<b>{{ row.myAnswer.value }}</b>
          <span v-if="row.myAnswer.note" class="note">（{{ row.myAnswer.note }}）</span>
          <span class="muted when">提交于 {{ row.myAnswer.submittedAt }}</span>
        </p>

        <!-- 操作：明细/导出发布人和班主任可见；改/关/删只有发布人自己 -->
        <footer class="task-foot">
          <span class="muted">发布于 {{ row.createdAt }}</span>
          <div class="acts">
            <el-button
              v-if="row.canSeeDetail"
              size="small"
              link
              type="primary"
              @click="openDetail(row)"
            >
              查看明细
            </el-button>
            <el-button
              v-if="row.canSeeDetail"
              size="small"
              link
              type="primary"
              @click="onExport(row.id)"
            >
              导出
            </el-button>
            <el-button v-if="row.canEdit" size="small" link @click="openEdit(row)">修改</el-button>
            <el-button
              v-if="row.canEdit"
              size="small"
              link
              :type="row.pinned ? 'danger' : 'warning'"
              @click="onTogglePin(row)"
            >
              {{ row.pinned ? '取消置顶' : '置顶' }}
            </el-button>
            <el-button v-if="row.canEdit" size="small" link @click="onToggleOpen(row)">
              {{ row.open ? '关闭' : '重新开放' }}
            </el-button>
            <el-button v-if="row.canEdit" size="small" link type="danger" @click="onDelete(row)">
              删除
            </el-button>
          </div>
        </footer>
      </section>
    </div>

    <!-- ============================ 发布 / 修改 ============================ -->
    <TaskPublishDialog
      v-model="formVisible"
      :scope="formScope"
      :task="editingTask"
      @saved="load"
    />

    <!-- ============================ 点名（第四十五轮） ============================
         学院任务发给班主任，班主任打开看到自己班的学生名册，逐个标记状态。
         和上面的「答题」弹窗是两套东西：那个是单选一题，这个是逐人点名。 -->
    <TaskRollcallDrawer
      v-model="rollcallVisible"
      :task-id="rollcallTaskId"
    />

    <!-- ============================ 答题 ============================ -->
    <el-dialog
      v-model="answerVisible"
      :title="current?.title ?? '填写答案'"
      width="480px"
      :close-on-click-modal="true"
      :before-close="onAnswerBeforeClose"
      @closed="restoreAnswerFocus"
    >
      <template v-if="current">
        <p class="dialog-q">
          {{ current.question }}
          <span class="qtype">{{ qtypeLabel(current.qtype) }}</span>
        </p>

        <!-- BOOLEAN：是/否两个大按钮，不用下拉也不用单选圆点 -->
        <el-radio-group
          v-if="current.qtype === 'BOOLEAN'"
          v-model="answerValue as boolean"
          class="bool-group"
        >
          <el-radio-button :value="true">是</el-radio-button>
          <el-radio-button :value="false">否</el-radio-button>
        </el-radio-group>

        <!-- SINGLE -->
        <el-radio-group v-else-if="current.qtype === 'SINGLE'" v-model="answerValue as string">
          <el-radio v-for="o in current.options" :key="o" :value="o" class="one-line">
            {{ o }}
          </el-radio>
        </el-radio-group>

        <!-- MULTI -->
        <el-checkbox-group
          v-else-if="current.qtype === 'MULTI'"
          :model-value="(answerValue as string[]) ?? []"
          class="multi-group"
          @update:model-value="(v: any) => (answerValue = v as string[])"
        >
          <el-checkbox v-for="o in current.options" :key="o" :value="o" class="one-line">
            {{ o }}
          </el-checkbox>
        </el-checkbox-group>

        <!-- DATE -->
        <el-date-picker
          v-else
          v-model="answerValue as string"
          type="date"
          placeholder="选一个日期"
          format="YYYY-MM-DD"
          value-format="YYYY-MM-DD"
          style="width: 100%"
        />

        <el-input
          v-if="current.allowText"
          v-model="answerNote"
          class="note-input"
          type="textarea"
          :rows="2"
          maxlength="255"
          show-word-limit
          placeholder="补充说明（选填），如没返校的原因"
          aria-label="补充说明"
        />

        <p class="form-tip">
          提交后还能改，直到任务关闭或过截止时间。别人看不到你填了什么。
        </p>
      </template>
      <template #footer>
        <el-button @click="onAnswerBeforeClose">取消</el-button>
        <el-button type="primary" :loading="answerLoading" @click="submitAnswer">提交</el-button>
      </template>
    </el-dialog>

    <!-- ============================ 明细 ============================ -->
    <el-dialog
      v-model="detailVisible"
      title="回答明细"
      width="720px"
      @closed="restoreDetailFocus"
    >
      <div v-loading="detailLoading">
        <template v-if="detail">
          <p class="dialog-q">
            {{ detail.question }}
            <span class="qtype">{{ detail.qtypeText }}</span>
          </p>
          <p class="muted detail-sum">
            共 {{ detail.answered + detail.unanswered }} 人，已填 {{ detail.answered }}，
            未填 {{ detail.unanswered }}
            <template v-if="detail.allowText">，带补充说明 {{ detail.noteCount }} 条</template>
          </p>

          <!-- 学院任务：按班分组，每组列出学生（第四十五轮） -->
          <template v-if="detail.scope === 'COLLEGE'">
            <div v-for="cls in detail.classes" :key="cls.classId" class="class-group">
              <h4 class="class-head">
                {{ cls.className }}
                <span class="muted">
                  已填 {{ cls.answered }} / 共 {{ cls.total }} 人
                  <template v-if="cls.teachers.length">　班主任 {{ cls.teachers.join('、') }}</template>
                </span>
              </h4>
              <el-table :data="cls.rows" size="small" max-height="280">
                <el-table-column label="学号" width="110">
                  <template #default="{ row }">{{ row.studentNo }}</template>
                </el-table-column>
                <el-table-column label="姓名" width="100">
                  <template #default="{ row }">{{ row.name }}</template>
                </el-table-column>
                <el-table-column label="是否已填" width="90">
                  <template #default="{ row }">
                    <el-tag :type="row.answered ? 'success' : 'info'" size="small" effect="plain">
                      {{ row.answered ? '是' : '未填' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="状态" min-width="110">
                  <template #default="{ row }">{{ row.value || '—' }}</template>
                </el-table-column>
                <el-table-column v-if="detail.allowText" label="补充说明" min-width="140">
                  <template #default="{ row }">{{ row.note || '—' }}</template>
                </el-table-column>
                <el-table-column label="提交时间" width="150">
                  <template #default="{ row }">{{ row.submittedAt || '—' }}</template>
                </el-table-column>
              </el-table>
            </div>
          </template>

          <!-- 班级任务：一人一行（原样） -->
          <el-table v-else :data="detail.rows" size="small" max-height="420">
            <el-table-column label="姓名" width="100">
              <template #default="{ row }">{{ row.name }}</template>
            </el-table-column>
            <el-table-column label="角色" width="90">
              <template #default="{ row }">{{ ROLE_TEXT[row.role] ?? row.role }}</template>
            </el-table-column>
            <el-table-column label="答案" min-width="130">
              <template #default="{ row }">
                <span v-if="row.answered">{{ row.value }}</span>
                <el-tag v-else size="small" type="info" effect="plain">未填</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="补充说明" min-width="150">
              <template #default="{ row }">
                <span v-if="row.note">{{ row.note }}</span>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="提交时间" width="140">
              <template #default="{ row }">
                <span v-if="row.submittedAt">{{ row.submittedAt }}</span>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
          </el-table>
          <p class="form-tip">未填的排在最前面，方便照着名单催。</p>
        </template>
      </div>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button v-if="detail" type="primary" @click="onExportDetail">导出</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* 范围切换（第三十二轮） */
.view-switch {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.view-btn {
  padding: 5px 12px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface, #fff);
  color: var(--color-muted-fg);
  font-size: 12px;
  cursor: pointer;
}

.view-btn.active {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
  font-weight: 600;
}

.head-tools {
  display: flex;
  gap: 8px;
  align-items: center;
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.task {
  padding: 16px 18px;
}
.task-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
/* 复选框 + 标题：让标题区撑满剩余宽度，标题紧跟复选框，
   而不是被 space-between 推到最右边（第三十三轮） */
.task-head .head-left {
  flex: 1;
  min-width: 0;
}
/* 学院任务明细：每个班一组，班头是浅蓝底的小标题 */
.class-group {
  margin-bottom: 14px;
}
.class-head {
  margin: 0 0 6px;
  padding: 6px 10px;
  background: #dbebf7;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #1f4e79;
}
.class-head .muted {
  font-weight: 400;
  font-size: 12px;
}
.task-head h3 {
  margin: 0 0 4px;
  font-size: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.q {
  margin: 0;
  color: #444;
}
.qtype {
  margin-left: 6px;
  font-size: 12px;
  color: #888;
  border: 1px solid #ddd;
  border-radius: 4px;
  padding: 0 5px;
}
.summary {
  margin-top: 12px;
}
.bar-line {
  display: flex;
  align-items: center;
  gap: 12px;
}
.bar {
  flex: 1;
  max-width: 320px;
}
.dist {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
}
.dist li {
  display: flex;
  align-items: center;
  gap: 6px;
}
.dist .lbl {
  font-size: 13px;
  color: #555;
}
.dist .cnt {
  font-weight: 700;
}
.mine {
  margin: 12px 0 0;
  padding: 8px 10px;
  background: rgba(74, 126, 187, 0.08);
  border-radius: 6px;
  font-size: 14px;
}
.mine .when {
  margin-left: 10px;
  font-size: 12px;
}
.task-foot {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid rgba(0, 0, 0, 0.06);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  font-size: 13px;
  flex-wrap: wrap;
}
.empty {
  padding: 32px;
  text-align: center;
  color: #888;
}
.dialog-q {
  margin: 0 0 14px;
  font-size: 15px;
}
.bool-group {
  display: flex;
  width: 100%;
}
.bool-group :deep(.el-radio-button) {
  flex: 1;
}
.bool-group :deep(.el-radio-button__inner) {
  width: 100%;
}
.one-line {
  display: flex;
  margin: 0 0 8px;
}
.multi-group {
  display: flex;
  flex-direction: column;
}
.note-input {
  margin-top: 14px;
}
.detail-sum {
  margin: 0 0 10px;
  font-size: 13px;
}
.form-tip {
  font-size: 12px;
  color: #888;
  line-height: 1.6;
}
.options {
  width: 100%;
}
.opt-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}
</style>