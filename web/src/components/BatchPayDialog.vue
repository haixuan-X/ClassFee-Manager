<script setup lang="ts">
import { nextTick, reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import dayjs from 'dayjs'
import { payBatchMember } from '@/api/batches'
import { getErrorMessage } from '@/api/request'
import { useModal } from '@/composables/useModal'
import type { Batch, Channel } from '@/types'
import { CHANNEL_TEXT } from '@/types'

const props = defineProps<{
  /** 当前批次（用于默认应收金额与标题） */
  batch: Batch | null
  /** 被登记的成员 */
  member: { userId: number; realName: string; studentNo?: string | null } | null
}>()
const visible = defineModel<boolean>({ required: true })
const emit = defineEmits<{ saved: [] }>()

/** Esc 关闭兜底（EP select 吞 Escape）+ 关闭后焦点还原 */
const { restoreFocus } = useModal(visible)

const formRef = ref<FormInstance>()
/** 弹窗内容根节点：焦点只在本弹窗内查找，避免命中页面上其他已打开过的 el-dialog */
const contentRef = ref<HTMLElement>()
const loading = ref(false)
/** 提交失败的错误摘要（role=alert，键盘/读屏可发现） */
const alertMessage = ref('')
const alertRef = ref<HTMLElement>()

const channels = Object.entries(CHANNEL_TEXT) as [Channel, string][]

const form = reactive({
  amount: undefined as number | undefined,
  channel: 'CASH' as Channel,
  occurredAt: dayjs().format('YYYY-MM-DD HH:mm:ss'),
  remark: '',
})

const rules: FormRules = {
  amount: [
    { required: true, message: '请输入金额', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (typeof value === 'number' && value > 0) callback()
        else callback(new Error('金额必须大于 0'))
      },
      trigger: 'blur',
    },
  ],
  occurredAt: [{ required: true, message: '请选择缴费时间', trigger: 'change' }],
}

watch(visible, async (open) => {
  if (!open) return
  alertMessage.value = ''
  // 默认批次应收 / 现在 / 现金，可改（补录历史缴费时改时间即可）
  form.amount = props.batch?.amount ?? undefined
  form.channel = 'CASH'
  form.occurredAt = dayjs().format('YYYY-MM-DD HH:mm:ss')
  form.remark = ''
  formRef.value?.clearValidate()
  await nextTick()
  // 焦点移进弹窗首个输入框（el-form 未暴露 focus 方法，走 DOM）
  contentRef.value?.querySelector<HTMLElement>('input')?.focus()
})

async function onSubmit() {
  if (!formRef.value || loading.value) return
  if (!props.batch || !props.member) {
    // 明细被并发刷新清空等极端情况：必须给出可读反馈，不能静默吞掉点击
    ElMessage.warning('批次或成员信息已失效，请关闭弹窗后重试')
    return
  }

  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) {
    alertMessage.value = '表单有未填写或格式不正确的项，请按下方提示修改'
    await nextTick()
    alertRef.value?.focus()
    return
  }

  loading.value = true
  alertMessage.value = ''
  try {
    await payBatchMember(props.batch.id, {
      userId: props.member.userId,
      amount: form.amount!,
      channel: form.channel,
      occurredAt: form.occurredAt,
      remark: form.remark.trim() || undefined,
    })
    ElMessage.success(
      `${props.member.realName} 已标记缴费，收入流水与余额已同步更新`,
    )
    visible.value = false
    emit('saved')
  } catch (error) {
    alertMessage.value = getErrorMessage(error, '登记失败，请稍后重试')
    await nextTick()
    alertRef.value?.focus()
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="`代为登记 · ${member?.realName ?? ''}`"
    width="min(560px, 92vw)"
    @closed="restoreFocus"
  >
    <div ref="contentRef">
      <p v-if="batch" class="batch-hint">
        批次「{{ batch.name }}」每人应收 <b class="num">¥{{ Number(batch.amount).toFixed(2) }}</b
        >，实收可多可少（如减免、补差额）。
      </p>

    <div
      v-if="alertMessage"
      ref="alertRef"
      class="error-summary"
      role="alert"
      tabindex="-1"
    >
      <b>无法登记：</b>{{ alertMessage }}
    </div>

    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent>
      <el-form-item label="实收金额（元）" prop="amount">
        <el-input-number
          v-model="form.amount"
          class="full"
          aria-label="实收金额（元）"
          :controls="false"
          inputmode="decimal"
          :min="0.01"
          :max="99999999.99"
          :precision="2"
          :step="1"
          placeholder="0.00"
        />
      </el-form-item>

      <div class="row-2">
        <el-form-item label="缴费时间" prop="occurredAt" class="grow">
          <el-date-picker
            v-model="form.occurredAt"
            class="full"
            aria-label="缴费时间"
            type="datetime"
            placeholder="选择日期时间"
            value-format="YYYY-MM-DD HH:mm:ss"
            :clearable="false"
          />
        </el-form-item>

        <el-form-item label="支付方式" class="grow">
          <el-select v-model="form.channel" class="full" aria-label="支付方式">
            <el-option
              v-for="[value, label] in channels"
              :key="value"
              :label="label"
              :value="value"
            />
          </el-select>
        </el-form-item>
      </div>

      <el-form-item label="备注（选填）">
        <el-input
          v-model="form.remark"
          aria-label="备注"
          type="textarea"
          :rows="3"
          maxlength="255"
          show-word-limit
          placeholder="如：现金已收 / 微信转账截图已存档"
        />
      </el-form-item>
      </el-form>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="loading" @click="onSubmit">确认缴费</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.batch-hint {
  margin: 0 0 16px;
  font-size: 13px;
  color: var(--color-muted-fg);
}

.batch-hint b {
  color: var(--color-foreground);
}

.error-summary {
  border: 1px solid rgba(220, 38, 38, 0.35);
  background: rgba(220, 38, 38, 0.06);
  color: var(--color-destructive-text);
  border-radius: var(--radius);
  padding: 11px 13px;
  margin-bottom: 16px;
  font-size: 13px;
}

.full {
  width: 100%;
}

.row-2 {
  display: flex;
  gap: 12px;
}

.grow {
  flex: 1;
  min-width: 0;
}

@media (max-width: 560px) {
  .row-2 {
    flex-direction: column;
    gap: 0;
  }
}
</style>
