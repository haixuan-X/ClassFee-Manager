<script setup lang="ts">
/**
 * 任务发布 / 修改对话框（第三十二轮抽成组件）。
 *
 * 原来只有「班级任务」页有它，第三十二轮加了**学院任务**（院长发到全学院的，
 * 各班班主任应答）——发布入口有两个地方，对话框也就该共用一份，
 * 不然两处表单会慢慢漂移（题型选项、校验口径、提示文案各写一遍）。
 *
 * - `scope='CLASS'`：班级任务（同学应答）
 * - `scope='COLLEGE'`：学院任务（各班班主任应答）
 */
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { getErrorMessage } from '@/api/request'
import { useCloseGuard } from '@/composables/useCloseGuard'
import { publishTask, updateTask, TASK_QTYPES } from '@/api/tasks'
import { disablePastDates, isPastDateTime } from '@/utils/date'
import dayjs from 'dayjs'
import type { Task, TaskCreatePayload, TaskQType, TaskScope } from '@/types'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    /** 发布哪一类任务 */
    scope?: TaskScope
    /**
     * 传了就进「修改」模式（题型和候选项不给改）。
     * 只要带这几项即可——学院任务列表的行类型不必是完整的 `Task`。
     */
    task?: Pick<Task, 'id' | 'title' | 'question' | 'qtype' | 'options' | 'allowText' | 'deadline'> | null
  }>(),
  { scope: 'CLASS', task: null },
)

const emit = defineEmits<{
  'update:modelValue': [boolean]
  /** 发布/保存成功后通知父页刷新 */
  saved: []
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const loading = ref(false)
const formRef = ref<FormInstance>()

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

/** 修改模式下任务原本的截止时间；没改就允许保留（它可能已经过期） */
const originalDeadline = ref<string | null>(null)

const editing = computed(() => props.task !== null)
const isCollege = computed(() => props.scope === 'COLLEGE')

/**
 * 后端的截止时间有两种口径，都要能吃下：
 *
 * - 班级任务列表（`task_service._build_rows`）：`YYYY-MM-DD HH:mm`（不带秒）
 * - 学院任务列表（`college_service.tasks` 的 `fmt_dt`）：`YYYY-MM-DD HH:mm:ss`（带秒）
 *
 * 原来一律 `.replace(' ', 'T') + ':00'`，对带秒的那份会拼出
 * `2026-10-29T23:59:59:00` —— pydantic 直接拒，学院任务的**修改必然 400**。
 *
 * 解析不出来就原样交给后端报错：**绝不能静默变成 null**，
 * 那会把「已经设过的截止时间」悄悄改成「不限时间」。
 */
function toPickerValue(raw: string): string {
  const parsed = dayjs(raw.replace(' ', 'T'))
  return parsed.isValid() ? parsed.format('YYYY-MM-DDTHH:mm:ss') : raw
}

/** 打开时按 scope / 任务重置表单 */
watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    if (props.task) {
      const deadline = props.task.deadline ? toPickerValue(props.task.deadline) : null
      originalDeadline.value = deadline
      Object.assign(form, {
        title: props.task.title,
        question: props.task.question,
        qtype: props.task.qtype,
        options: props.task.options.length ? [...props.task.options] : ['', ''],
        allowText: props.task.allowText,
        deadline,
      })
    } else {
      originalDeadline.value = null
      Object.assign(form, blank())
    }
    // 存一份快照，供「有未保存改动就不让随手关」比对
    baseline.value = snapshot()
  },
)

/** 表单当前状态的快照（字符串化，直接比对） */
function snapshot(): string {
  return JSON.stringify({
    title: form.title,
    question: form.question,
    qtype: form.qtype,
    options: form.options,
    allowText: form.allowText,
    deadline: form.deadline,
  })
}

/** 打开那一刻的表单状态 */
const baseline = ref('')

/** 有没有未保存的改动（点了遮罩 / ✕ / Esc 时用） */
const isDirty = computed(() => snapshot() !== baseline.value)

/**
 * 关闭拦截：填了内容就不让随手关。
 *
 * 三条关闭路径（点遮罩 / 点 ✕ / Esc）都汇到 `before-close`，拦这一处就够。
 */
const { onBeforeClose } = useCloseGuard(
  visible,
  isDirty,
  () => '填了内容还没保存，关闭会丢掉这些改动。确定关闭？',
)

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
  deadline: [
    {
      validator: (_rule, value: string | null, callback) => {
        // 留空 = 不限时间
        if (!value) return callback()
        // 改一条已经过期的任务时，没动截止时间就放行；
        // 否则连改标题都会被「原截止时间在过去」卡住
        if (editing.value && value === originalDeadline.value) return callback()
        if (isPastDateTime(value)) return callback(new Error('截止时间要晚于现在'))
        callback()
      },
      trigger: 'change',
    },
  ],
}

/** 选日期时默认落到当天 23:59，避免「今天」默认 00:00 一选就过期 */
const deadlineDefaultTime = new Date(2000, 0, 1, 23, 59, 59)

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

async function submit() {
  const formEl = formRef.value
  if (!formEl || loading.value) return
  // 先上锁，再校验：`await validate()` 期间按钮还是可点的状态，
  // 连点两下就会发布出**两条**任务（同个人信息页那个坑）
  loading.value = true
  try {
    const ok = await formEl.validate().catch(() => false)
    if (!ok) return

    const payload: TaskCreatePayload = {
      title: form.title.trim(),
      question: form.question.trim(),
      qtype: form.qtype,
      allowText: form.allowText,
      deadline: form.deadline,
      scope: props.scope,
    }
    if (needsOptions.value) payload.options = cleanOptions.value

    if (!editing.value) {
      await publishTask(payload)
      ElMessage.success(isCollege.value ? '学院任务已发布' : '任务已发布')
    } else if (props.task) {
      await updateTask(props.task.id, payload)
      ElMessage.success('任务已修改')
    }
    visible.value = false
    emit('saved')
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '发布失败'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="editing ? '修改任务' : isCollege ? '发布学院任务' : '发布任务'"
    width="560px"
    :close-on-click-modal="true"
    :before-close="onBeforeClose"
  >
    <!-- 学院任务：说清楚「谁来答」，发错了要返工 -->
    <el-alert
      v-if="isCollege"
      type="info"
      :closable="false"
      show-icon
      title="学院任务：全学院都看得见，由各班班主任应答"
      description="每个班的班主任交一份代表他那个班的答案（比如「本班同学都返校了吗」）。发布后各班班主任在「班级任务」里就能填。"
      style="margin-bottom: 14px"
    />
    <el-form ref="formRef" :model="form" :rules="formRules" label-width="88px" @submit.prevent>
      <el-form-item label="任务标题" prop="title">
        <el-input v-model="form.title" placeholder="如「返校统计」" maxlength="60" show-word-limit />
        <div class="form-tip">列表里显示的短标题，一句话说清是干什么的</div>
      </el-form-item>

      <el-form-item label="题目" prop="question">
        <el-input
          v-model="form.question"
          :placeholder="isCollege ? '如「本班同学都返校了吗？」' : '如「你已经返校了吗？」'"
          maxlength="255"
          show-word-limit
        />
        <div class="form-tip">真正被回答的那句话，回答的人看到的就是它</div>
      </el-form-item>

      <el-form-item label="题型" prop="qtype">
        <el-radio-group v-model="form.qtype" :disabled="editing">
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

      <el-form-item label="截止时间" prop="deadline">
        <el-date-picker
          v-model="form.deadline"
          type="datetime"
          placeholder="留空 = 不限时间"
          format="YYYY-MM-DD HH:mm"
          value-format="YYYY-MM-DDTHH:mm:ss"
          :disabled-date="disablePastDates"
          :default-time="deadlineDefaultTime"
          style="width: 100%"
        />
        <div class="form-tip">
          只能选现在之后；过了这个时间就不再收答案，已填的照常保留
        </div>
      </el-form-item>

      <el-alert
        v-if="editing"
        type="info"
        show-icon
        :closable="false"
        title="题型和候选项改不了"
        description="换题型会让已经收回的答案对不上题。要换请删掉这个任务重新发一个。"
      />
    </el-form>
    <template #footer>
      <el-button @click="onBeforeClose">取消</el-button>
      <el-button type="primary" :loading="loading" @click="submit">
        {{ editing ? '保存' : '发布' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.options {
  width: 100%;
}

.opt-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.form-tip {
  font-size: 12px;
  color: var(--color-muted-fg);
  line-height: 1.6;
}
</style>
