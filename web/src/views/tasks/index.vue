<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { getErrorMessage } from '@/api/request'
import {
  deleteTask,
  exportTaskDetail,
  fetchTaskDetail,
  fetchTasks,
  publishTask,
  setTaskOpen,
  setTaskPinned,
  submitTaskAnswer,
  TASK_QTYPES,
  updateTask,
} from '@/api/tasks'
import { useModal } from '@/composables/useModal'
import type { Task, TaskCreatePayload, TaskDetail, TaskQType } from '@/types'

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

async function load() {
  loading.value = true
  try {
    const data = await fetchTasks()
    rows.value = data.rows
    canPublish.value = data.canPublish
  } catch {
    rows.value = []
  } finally {
    loading.value = false
  }
}

/* ============================ 题型说明 ============================ */

const qtypeLabel = (t: TaskQType) => TASK_QTYPES.find((x) => x.value === t)?.label ?? t

/** 汇总条的总份数，用来画进度条；分母 0（没有应答对象）时按 0 处理，不除零。 */
const percent = (answered: number, total: number) =>
  total > 0 ? Math.round((answered / total) * 100) : 0

/* ============================ 发布 / 修改 ============================ */

const formVisible = ref(false)
const formLoading = ref(false)
const formRef = ref<FormInstance>()
const editingId = ref<number | null>(null)
const { restoreFocus: restoreFormFocus } = useModal(formVisible)

const blank = () => ({
  title: '',
  question: '',
  qtype: 'BOOLEAN' as TaskQType,
  /** 候选项：数组编辑器，每项一个输入框 */
  options: ['', ''] as string[],
  allowText: false,
  /** el-date-picker 的 `YYYY-MM-DDTHH:mm:ss` 字符串，null = 不限 */
  deadline: null as string | null,
})
const form = reactive(blank())

const needsOptions = computed(() => form.qtype === 'SINGLE' || form.qtype === 'MULTI')
/** 去掉首尾空白和空串，发布前归一（用户很容易在候选项里敲进一个空格） */
const cleanOptions = computed(() => form.options.map((o) => o.trim()).filter(Boolean))

const formRules: FormRules = {
  title: [
    { required: true, message: '请输入任务标题', trigger: 'blur' },
    { max: 60, message: '任务标题最多 60 字', trigger: 'blur' },
  ],
  question: [
    { required: true, message: '请输入题目', trigger: 'blur' },
    { max: 255, message: '题目最多 255 字', trigger: 'blur' },
  ],
}

function openCreate() {
  editingId.value = null
  Object.assign(form, blank())
  formVisible.value = true
}

/** 改任务。**题型和候选项不给改**——换题型会让已收回的答案对不上题。 */
function openEdit(row: Task) {
  editingId.value = row.id
  Object.assign(form, {
    title: row.title,
    question: row.question,
    qtype: row.qtype,
    options: row.options.length ? [...row.options] : ['', ''],
    allowText: row.allowText,
    deadline: row.deadline ? row.deadline.replace(' ', 'T') + ':00' : null,
  })
  formVisible.value = true
}

function addOption() {
  if (form.options.length >= 12) return
  form.options.push('')
}

function removeOption(i: number) {
  // 少于 2 项时全删光，编辑器会变成空白，用户会以为出 bug 了——
  // 所以始终留住 2 个空位（后端也会拒少于 2 项）
  if (form.options.length <= 2) return
  form.options.splice(i, 1)
}

async function submitForm() {
  const formEl = formRef.value
  if (!formEl) return
  const ok = await formEl.validate().catch(() => false)
  if (!ok) return

  const payload: TaskCreatePayload = {
    title: form.title.trim(),
    question: form.question.trim(),
    qtype: form.qtype,
    allowText: form.allowText,
    deadline: form.deadline,
  }
  if (needsOptions.value) payload.options = cleanOptions.value

  formLoading.value = true
  try {
    if (editingId.value === null) {
      await publishTask(payload)
      ElMessage.success('任务已发布')
    } else {
      await updateTask(editingId.value, payload)
      ElMessage.success('任务已修改')
    }
    formVisible.value = false
    await load()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '发布失败'))
  } finally {
    formLoading.value = false
  }
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
}

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
  if (!task) return
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
        `已经收回的 ${row.summary.answered} 份回答会**一起删除**，不可恢复。`,
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

/* ============================ 杂项 ============================ */

const ROLE_TEXT: Record<string, string> = {
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
          班主任或班长发一个题，全班在这里填；只公布「多少人是、多少否」，具体谁填了什么只有发布人和班主任看得到
        </p>
      </div>
      <el-button v-if="canPublish" type="primary" @click="openCreate">发布任务</el-button>
    </div>

    <p ref="alertRef" class="sr-alert" role="alert">{{ alertMessage }}</p>

    <div v-loading="loading" class="task-list" aria-label="任务列表">
      <p v-if="!loading && rows.length === 0" class="glass-card empty">{{ emptyText }}</p>

      <section v-for="row in rows" :key="row.id" class="glass-card task" :aria-label="row.title">
        <header class="task-head">
          <div class="head-left">
            <h3>
              {{ row.title }}
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
    <el-dialog
      v-model="formVisible"
      :title="editingId === null ? '发布任务' : '修改任务'"
      width="560px"
      :close-on-click-modal="false"
      @closed="restoreFormFocus"
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="88px" @submit.prevent>
        <el-form-item label="任务标题" prop="title">
          <el-input v-model="form.title" placeholder="如「返校统计」" maxlength="60" show-word-limit />
          <div class="form-tip">列表里显示的短标题，一句话说清是干什么的</div>
        </el-form-item>

        <el-form-item label="题目" prop="question">
          <el-input
            v-model="form.question"
            placeholder="如「你已经返校了吗？」"
            maxlength="255"
            show-word-limit
          />
          <div class="form-tip">真正被回答的那句话，同学看到的就是它</div>
        </el-form-item>

        <el-form-item label="题型" prop="qtype">
          <el-radio-group v-model="form.qtype" :disabled="editingId !== null">
            <el-radio-button v-for="t in TASK_QTYPES" :key="t.value" :value="t.value">
              {{ t.label }}
            </el-radio-button>
          </el-radio-group>
          <div class="form-tip">
            {{ TASK_QTYPES.find((t) => t.value === form.qtype)?.hint }}
          </div>
        </el-form-item>

        <el-form-item v-if="needsOptions" label="候选项">
          <div class="options">
            <div v-for="(_, i) in form.options" :key="i" class="opt-row">
              <el-input
                v-model="form.options[i]"
                :placeholder="`选项 ${i + 1}`"
                maxlength="30"
                aria-label="候选项"
              />
              <el-button
                :disabled="form.options.length <= 2"
                size="small"
                link
                type="danger"
                :aria-label="`删除选项 ${i + 1}`"
                @click="removeOption(i)"
              >
                删除
              </el-button>
            </div>
            <el-button size="small" :disabled="form.options.length >= 12" @click="addOption">
              加一项
            </el-button>
            <div class="form-tip">
              已填 {{ cleanOptions.length }} 项（至少 2 项，最多 12 项，每项 30 字内）
            </div>
          </div>
        </el-form-item>

        <el-form-item label="补充说明">
          <el-switch v-model="form.allowText" active-text="允许" inactive-text="不允许" />
          <div class="form-tip">
            打开后，答完还能再写一句话（如没返校的原因）。不打开则只记答案本身。
          </div>
        </el-form-item>

        <el-form-item label="截止时间">
          <el-date-picker
            v-model="form.deadline"
            type="datetime"
            placeholder="留空 = 不限时间"
            format="YYYY-MM-DD HH:mm"
            value-format="YYYY-MM-DDTHH:mm:ss"
            style="width: 100%"
          />
          <div class="form-tip">过了这个时间就不再收答案，已填的照常保留</div>
        </el-form-item>

        <el-alert
          v-if="editingId !== null"
          type="info"
          show-icon
          :closable="false"
          title="题型和候选项改不了"
          description="换题型会让已经收回的答案对不上题。要换请删掉这个任务重新发一个。"
        />
      </el-form>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" :loading="formLoading" @click="submitForm">
          {{ editingId === null ? '发布' : '保存' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- ============================ 答题 ============================ -->
    <el-dialog
      v-model="answerVisible"
      :title="current?.title ?? '填写答案'"
      width="480px"
      :close-on-click-modal="false"
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
        <el-button @click="answerVisible = false">取消</el-button>
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
          <el-table :data="detail.rows" size="small" max-height="420">
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