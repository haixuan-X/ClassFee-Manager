<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules, type UploadFile } from 'element-plus'
import dayjs from 'dayjs'
import { createRecord, fetchCategories } from '@/api/records'
import { MAX_RECEIPT_BYTES, RECEIPT_ACCEPT, uploadReceipt } from '@/api/files'
import { getErrorMessage } from '@/api/request'
import { useModal } from '@/composables/useModal'
import CategoryManagerDialog from '@/components/CategoryManagerDialog.vue'
import type { Category, Channel, RecordRequest, RecordType } from '@/types'
import { CHANNEL_TEXT, TYPE_TEXT } from '@/types'

const props = defineProps<{ type: RecordType }>()
const visible = defineModel<boolean>({ required: true })
const emit = defineEmits<{ saved: [] }>()

const formRef = ref<FormInstance>()
const loading = ref(false)
/** 提交失败的错误摘要（role=alert，键盘/读屏可发现） */
const alertMessage = ref('')
const alertRef = ref<HTMLElement>()

const categories = ref<Category[]>([])
const channels = Object.entries(CHANNEL_TEXT) as [Channel, string][]

/** 类别字典维护弹窗（与表单共用 kind，改动后联动刷新下拉） */
const catMgrVisible = ref(false)

/** 小票只出现在支出登记（设计文档 M4：报销/采购票据） */
const showReceipt = computed(() => props.type === 'EXPENSE')

const uploadRef = ref()
const receiptFile = ref<File | null>(null)
/** 本地 objectURL 预览（提交成功前不落服务器，关抽屉即释放） */
const receiptPreview = ref('')
/** 选图时的就地错误（role=alert，读屏可感知） */
const receiptError = ref('')

/** 校验通过后记下文件；真正上传发生在提交时（取消登记不留孤儿文件） */
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
  categoryId: undefined as number | undefined,
  amount: undefined as number | undefined,
  title: '',
  occurredAt: dayjs().format('YYYY-MM-DD HH:mm:ss'),
  channel: 'CASH' as Channel,
  remark: '',
})

const rules: FormRules = {
  categoryId: [{ required: true, type: 'number', message: '请选择类别', trigger: 'change' }],
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
  title: [
    { required: true, message: '请填写摘要', trigger: 'blur' },
    { max: 60, message: '摘要最多 60 字', trigger: 'blur' },
  ],
  occurredAt: [{ required: true, message: '请选择发生时间', trigger: 'change' }],
}

/** Esc 关闭兜底（EP select 吞 Escape）+ 关闭后焦点还原；root 指向抽屉内容以判定嵌套层级 */
const { restoreFocus } = useModal(visible, formRef)

watch(visible, async (open) => {
  // 无论开关都先清小票：关=释放 objectURL，开=避免上次输入残留
  clearReceipt()
  receiptError.value = ''
  if (!open) return
  alertMessage.value = ''
  // 每次打开重置，避免上次输入残留
  form.categoryId = undefined
  form.amount = undefined
  form.title = ''
  form.remark = ''
  form.channel = 'CASH'
  form.occurredAt = dayjs().format('YYYY-MM-DD HH:mm:ss')
  formRef.value?.clearValidate()

  // 类别按收支方向分开取。/income 与 /expense 路由**复用同一个抽屉组件实例**，
  // 切页时 props.type 会变而组件不重建 —— 所以不能只判「是否为空」，
  // 必须校验缓存里的类别是否属于当前方向，否则支出抽屉会带出收入类别。
  if (categories.value.length === 0 || categories.value[0].kind !== props.type) {
    categories.value = await fetchCategories(props.type)
  }
  await nextTick()
  // 焦点移到抽屉里第一个输入框（限定在本抽屉的 form 内，不命中其他抽屉）
  const formEl = formRef.value?.$el as HTMLElement | undefined
  formEl?.querySelector<HTMLElement>('input, textarea')?.focus()
})

/** 类别弹窗新增/删除后：按**当前方向**刷新下拉，正被表单选中的类别已删则清掉选择 */
async function onCategoriesChanged() {
  try {
    categories.value = await fetchCategories(props.type)
  } catch {
    /* 拦截器已提示；下拉保持旧值也不影响后续重新打开时加载 */
  }
  if (form.categoryId && !categories.value.some((c) => c.id === form.categoryId)) {
    form.categoryId = undefined
  }
}

async function onSubmit() {
  if (!formRef.value) return
  if (loading.value) return

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
    // 先传小票拿相对路径，再随流水一起落库（上传失败=整单失败，不产生半截流水）
    let receiptUrl: string | undefined
    if (receiptFile.value) {
      receiptUrl = (await uploadReceipt(receiptFile.value)).path
    }
    const payload: RecordRequest = {
      type: props.type,
      categoryId: form.categoryId!,
      amount: form.amount!,
      title: form.title.trim(),
      occurredAt: form.occurredAt,
      channel: form.channel,
      remark: form.remark.trim() || undefined,
      receiptUrl,
    }
    await createRecord(payload)
    ElMessage.success(`已记入${TYPE_TEXT[props.type]}流水，余额同步更新`)
    visible.value = false
    emit('saved')
  } catch (error) {
    alertMessage.value = getErrorMessage(error, '保存失败，请稍后重试')
    await nextTick()
    alertRef.value?.focus()
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <!-- Esc 由 useModal 统一接管（捕获阶段 + 最上层判定）；禁用 EP 原生 close-on-press-escape：
       它挂在 document 冒泡，焦点在弹层外时会绕过层级判定把下层弹层一起关掉 -->
  <el-drawer
    v-model="visible"
    :title="`登记${TYPE_TEXT[type]}`"
    size="min(440px, 100vw)"
    :close-on-press-escape="false"
    @closed="restoreFocus"
  >
    <div
      v-if="alertMessage"
      ref="alertRef"
      class="error-summary"
      role="alert"
      tabindex="-1"
    >
      <b>无法保存：</b>{{ alertMessage }}
    </div>

    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent>
      <el-form-item label="类别" prop="categoryId">
        <el-select
          v-model="form.categoryId"
          class="full"
          aria-label="类别"
          placeholder="请选择类别"
          :loading="categories.length === 0"
        >
          <el-option
            v-for="cat in categories"
            :key="cat.id"
            :label="cat.name"
            :value="cat.id"
          />
        </el-select>
      </el-form-item>

      <div class="cat-manage">
        <el-button link type="primary" size="small" @click="catMgrVisible = true">
          管理类别（新增 / 改名 / 删除）
        </el-button>
      </div>

      <el-form-item label="金额（元）" prop="amount">
        <el-input-number
          v-model="form.amount"
          class="full"
          aria-label="金额（元）"
          :controls="false"
          inputmode="decimal"
          :min="0.01"
          :max="99999999.99"
          :precision="2"
          :step="1"
          placeholder="0.00"
        />
      </el-form-item>

      <el-form-item label="摘要" prop="title">
        <el-input
          v-model.trim="form.title"
          aria-label="摘要"
          maxlength="60"
          show-word-limit
          placeholder="如：收取9月班费 / 购买活动矿泉水"
        />
      </el-form-item>

      <div class="row-2">
        <el-form-item label="发生时间" prop="occurredAt" class="grow">
          <el-date-picker
            v-model="form.occurredAt"
            class="full"
            aria-label="发生时间"
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
        />
      </el-form-item>

      <!-- 小票（仅支出）：本地预览，提交时才上传；错误就地 role=alert -->
      <el-form-item v-if="showReceipt" label="小票图片（选填）">
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

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="loading" @click="onSubmit">保存流水</el-button>
    </template>
  </el-drawer>

  <!-- 类别字典维护：与本抽屉同方向（收入/支出各自维护） -->
  <CategoryManagerDialog v-model="catMgrVisible" :kind="type" @changed="onCategoriesChanged" />
</template>

<style scoped>
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

.cat-manage {
  margin-top: -12px;
  margin-bottom: 4px;
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
</style>
