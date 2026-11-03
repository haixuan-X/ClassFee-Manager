<script setup lang="ts">
import { nextTick, reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules, type UploadFile } from 'element-plus'
import dayjs from 'dayjs'
import { payBatchMember } from '@/api/batches'
import { MAX_RECEIPT_BYTES, RECEIPT_ACCEPT, uploadReceipt } from '@/api/files'
import { getErrorMessage } from '@/api/request'
import { useModal } from '@/composables/useModal'
import { disableFutureDates, isFutureDateTime } from '@/utils/date'
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

/* ---------------- 小票（选填，第六十一轮） ----------------
 * 代为登记时把学生交现金的收据 / 转账截图留档。和支出登记同一套做法：
 * 本地 objectURL 预览，**提交时才上传**（取消登记不会留下孤儿文件）。
 */
const uploadRef = ref()
const receiptFile = ref<File | null>(null)
const receiptPreview = ref('')
const receiptError = ref('')

function onReceiptChange(file: UploadFile) {
  const raw = file.raw
  if (!raw) return
  if (!RECEIPT_ACCEPT.includes(raw.type)) {
    receiptError.value = '仅支持 JPG / PNG / WebP / GIF 图片'
    clearReceipt()
    return
  }
  if (raw.size > MAX_RECEIPT_BYTES) {
    receiptError.value = '图片大小不能超过 5MB'
    clearReceipt()
    return
  }
  receiptError.value = ''
  receiptFile.value = raw
  receiptPreview.value = URL.createObjectURL(raw)
}

function onReceiptExceed() {
  receiptError.value = '请先移除已选图片再重新选择'
}

function clearReceipt() {
  if (receiptPreview.value) URL.revokeObjectURL(receiptPreview.value)
  receiptPreview.value = ''
  receiptFile.value = null
  uploadRef.value?.clearFiles()
}

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
  occurredAt: [
    { required: true, message: '请选择缴费时间', trigger: 'change' },
    {
      validator: (_rule, value: string | null, callback) => {
        // 可以补录历史缴费，但不能登记「还没发生」的缴费
        if (value && isFutureDateTime(value)) {
          return callback(new Error('缴费时间不能晚于现在'))
        }
        callback()
      },
      trigger: 'change',
    },
  ],
}

watch(visible, async (open) => {
  // 无论开关都先清小票：关=释放 objectURL，开=避免上次输入残留
  clearReceipt()
  receiptError.value = ''
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

  // 先上锁，再校验（同个人信息页那个坑）：validate 期间的 await 是可点击窗口，
  // 连点两下会**重复登记一笔缴费**（流水和余额都会多算一次）
  loading.value = true
  alertMessage.value = ''
  try {
    const valid = await formRef.value.validate().catch(() => false)
    if (!valid) {
      alertMessage.value = '表单有未填写或格式不正确的项，请按下方提示修改'
      await nextTick()
      alertRef.value?.focus()
      return
    }

    // 先传小票拿相对路径，再随缴费一起落库（上传失败=整单失败，不产生半截缴费）
    let receiptUrl: string | undefined
    if (receiptFile.value) {
      receiptUrl = (await uploadReceipt(receiptFile.value)).path
    }
    await payBatchMember(props.batch.id, {
      userId: props.member.userId,
      amount: form.amount!,
      channel: form.channel,
      occurredAt: form.occurredAt,
      remark: form.remark.trim() || undefined,
      receiptUrl,
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
            :disabled-date="disableFutureDates"
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

      <!-- 小票（选填）：本地预览，提交时才上传；错误就地 role=alert -->
      <el-form-item label="小票图片（选填）">
        <div v-if="receiptPreview" class="receipt-preview">
          <img :src="receiptPreview" alt="已选小票预览" />
          <div class="receipt-meta">
            <span class="receipt-name">{{ receiptFile?.name }}</span>
            <el-button link type="danger" size="small" @click="clearReceipt">移除</el-button>
          </div>
        </div>
        <el-upload
          v-else
          ref="uploadRef"
          :auto-upload="false"
          :show-file-list="false"
          :limit="1"
          accept="image/jpeg,image/png,image/webp,image/gif"
          :on-change="onReceiptChange"
          :on-exceed="onReceiptExceed"
        >
          <el-button>选择图片</el-button>
        </el-upload>
        <p v-if="receiptError" class="receipt-error" role="alert">{{ receiptError }}</p>
        <p class="receipt-hint">支持 JPG / PNG / WebP / GIF，不超过 5MB；保存后可在账本明细查看</p>
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

.receipt-preview {
  display: flex;
  align-items: center;
  gap: 10px;
}

.receipt-preview img {
  width: 72px;
  height: 72px;
  object-fit: cover;
  border-radius: var(--radius);
  border: 1px solid var(--el-border-color);
}

.receipt-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  min-width: 0;
}

.receipt-name {
  font-size: 12px;
  color: var(--color-muted-fg);
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.receipt-error {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--color-destructive-text);
}

.receipt-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--color-muted-fg);
}

@media (max-width: 560px) {
  .row-2 {
    flex-direction: column;
    gap: 0;
  }
}
</style>
