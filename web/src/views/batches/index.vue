<script setup lang="ts">
import { nextTick, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import dayjs from 'dayjs'
import { closeBatch, createBatch, deleteBatch, fetchBatchDetail, fetchBatches } from '@/api/batches'
import { getErrorMessage } from '@/api/request'
import { useModal } from '@/composables/useModal'
import { useUserStore } from '@/stores/user'
import BatchPayDialog from '@/components/BatchPayDialog.vue'
import type { Batch, BatchDetail, Channel, PaymentRow, PayStatus, Role } from '@/types'
import {
  BATCH_STATUS_TEXT,
  CHANNEL_TEXT,
  PAY_STATUS_TEXT,
  ROLE_TEXT,
} from '@/types'

/**
 * 收费批次（M3）：建批次 → 展开逐人明细 → 标记已交（同事务生成流水）→ 关闭批次。
 * 仅运营角色可见（ADMIN/MONITOR/TEACHER；路由 meta.roles + 后端 _STAFF_ROUTES 双重限制）。
 */
const router = useRouter()

/**
 * 第十七轮归属权（A 方案）：**关闭 / 删除批次只对创建人开放**。
 * 后端 `require_ownership` 是硬边界，这里只负责不让人点了才吃 403。
 * 「标记已交」刻意不受此限 —— 收款是协作动作，闸门加在缴费上会把账卡死。
 */
const isMine = (b: Batch) => b.createdBy === userStore.user?.id

const userStore = useUserStore()

const loading = ref(true)
const batches = ref<Batch[]>([])

/** 同一时刻只展开一个批次的明细（明细请求也只有一路） */
const expandedId = ref<number | null>(null)
const detailLoading = ref(false)
const detail = ref<BatchDetail | null>(null)

/* ============================ 新建批次 ============================ */

const createVisible = ref(false)
/** Esc 关闭兜底（EP select 吞 Escape）+ 关闭后焦点还原 */
const { restoreFocus: restoreCreateFocus } = useModal(createVisible)

const formRef = ref<FormInstance>()
const creating = ref(false)
/** 提交失败的错误摘要（role=alert，键盘/读屏可发现） */
const alertMessage = ref('')
const alertRef = ref<HTMLElement>()

const form = reactive({
  name: '',
  amount: undefined as number | undefined,
  deadline: null as string | null,
  remark: '',
})

const rules: FormRules = {
  name: [
    { required: true, message: '请填写批次名称', trigger: 'blur' },
    { max: 60, message: '批次名称最多 60 字', trigger: 'blur' },
  ],
  amount: [
    { required: true, message: '请输入每人应收金额', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (typeof value === 'number' && value > 0) callback()
        else callback(new Error('金额必须大于 0'))
      },
      trigger: 'blur',
    },
  ],
  deadline: [
    {
      validator: (_rule, value: string | null, callback) => {
        if (!value || !dayjs(value).isBefore(dayjs(), 'day')) callback()
        else callback(new Error('截止日不能早于今天'))
      },
      trigger: 'change',
    },
  ],
}

/* ============================ 标记缴费 ============================ */

const payVisible = ref(false)
const payMember = ref<
  { userId: number; realName: string; studentNo?: string | null; batch: Batch } | null
>(null)

/* ============================ 数据 ============================ */

/** 列表加载失败标记：区分「真的没有批次」与「接口出错」两种空态 */
const loadError = ref(false)

/** showLoading：首屏全量加载用骨架；标记缴费/关闭后的刷新保持页面不闪 */
async function load(showLoading = true) {
  if (showLoading) loading.value = true
  try {
    batches.value = await fetchBatches()
    loadError.value = false
  } catch {
    loadError.value = true
    // 拦截器已统一提示，这里只避免未处理的 rejection
  } finally {
    if (showLoading) loading.value = false
  }
}

/** 明细请求序号：快速切换展开时丢弃过期响应，防止明细与卡片/弹窗错配 */
let detailSeq = 0

async function loadDetail(id: number, keep = false) {
  const seq = ++detailSeq
  detailLoading.value = true
  if (!keep) detail.value = null
  try {
    const data = await fetchBatchDetail(id)
    if (seq !== detailSeq || expandedId.value !== id) return
    detail.value = data
  } catch {
    if (seq !== detailSeq) return
    expandedId.value = null
    detail.value = null
  } finally {
    if (seq === detailSeq) detailLoading.value = false
  }
}

function toggleDetail(batch: Batch) {
  if (expandedId.value === batch.id) {
    detailSeq++ // 收起时作废在途请求，避免晚到的响应重新写入
    expandedId.value = null
    detail.value = null
    detailLoading.value = false
    return
  }
  expandedId.value = batch.id
  loadDetail(batch.id)
}

/* ============================ 交互 ============================ */

function openCreate() {
  alertMessage.value = ''
  form.name = ''
  form.amount = undefined
  form.deadline = null
  form.remark = ''
  formRef.value?.clearValidate()
  createVisible.value = true
}

async function onCreate() {
  if (!formRef.value || creating.value) return

  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) {
    alertMessage.value = '表单有未填写或格式不正确的项，请按下方提示修改'
    await nextTick()
    alertRef.value?.focus()
    return
  }

  creating.value = true
  alertMessage.value = ''
  try {
    const created = await createBatch({
      name: form.name.trim(),
      amount: form.amount!,
      deadline: form.deadline || undefined,
      remark: form.remark.trim() || undefined,
    })
    ElMessage.success(`批次「${created.name}」已创建，已为 ${created.total} 名成员生成未缴费记录`)
    createVisible.value = false
    await load(false)
    // 自动展开新批次，直接进入逐人标记
    expandedId.value = created.id
    loadDetail(created.id)
  } catch (error) {
    alertMessage.value = getErrorMessage(error, '创建失败，请稍后重试')
    await nextTick()
    alertRef.value?.focus()
  } finally {
    creating.value = false
  }
}

async function onCloseBatch(batch: Batch) {
  try {
    await ElMessageBox.confirm(
      `关闭「${batch.name}」后不能再标记缴费（已收流水与余额不受影响）。确定关闭？`,
      '关闭批次',
      { type: 'warning', confirmButtonText: '确认关闭', cancelButtonText: '再想想' },
    )
  } catch {
    return // 用户取消
  }
  try {
    await closeBatch(batch.id)
    ElMessage.success('批次已关闭')
  } catch (error) {
    ElMessage.error(getErrorMessage(error, '关闭失败，请稍后重试'))
    return
  }
  await load(false)
  if (expandedId.value === batch.id) await loadDetail(batch.id, true)
}

async function onDeleteBatch(batch: Batch) {
  try {
    await ElMessageBox.confirm(
      `删除「${batch.name}」将级联清除该批次的全部缴费状态与流水（正常流水余额同步回滚），不可恢复。确定删除？`,
      '删除批次',
      { type: 'error', confirmButtonText: '确认删除', cancelButtonText: '再想想' },
    )
  } catch {
    return // 用户取消
  }
  try {
    await deleteBatch(batch.id)
  } catch {
    return // 拦截器已统一提示（400/403），这里兜住未处理的 rejection
  }
  ElMessage.success('批次及关联数据已删除')
  // 正在展开的就是被删批次 → 先收起，避免明细区悬空
  if (expandedId.value === batch.id) {
    detailSeq++
    expandedId.value = null
    detail.value = null
    detailLoading.value = false
  }
  await load(false)
}

function openPay(row: PaymentRow) {
  // 快照批次信息：即使明细随后被切换/刷新，弹窗文案与提交目标也不会错配
  const batch = detail.value?.batch
  if (!batch) return
  payMember.value = {
    userId: row.userId,
    realName: row.realName ?? '该成员',
    studentNo: row.studentNo,
    batch,
  }
  payVisible.value = true
}

async function onPaySaved() {
  if (expandedId.value != null) await loadDetail(expandedId.value, true)
  await load(false)
}

/** 查看这笔缴费生成的流水（账本页首屏精确命中一次） */
function gotoRecord(row: PaymentRow) {
  if (!row.recordId) return
  router.push({ path: '/records', query: { id: String(row.recordId) } })
}

/* ============================ 文案 ============================ */

const payTagType = (status: PayStatus): 'success' | 'warning' | 'info' =>
  status === 'PAID' ? 'success' : status === 'REFUNDED' ? 'warning' : 'info'

const channelText = (channel: Channel | null) => (channel ? CHANNEL_TEXT[channel] : '—')
const roleText = (role: Role | null) => (role ? ROLE_TEXT[role] : '')
/** 模板里 el-table 的 slot 参数是宽松类型，统一走这里的强类型取文案（同 records 页） */
const statusText = (row: PaymentRow) => PAY_STATUS_TEXT[row.status]

onMounted(() => load())
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>收费批次</h2>
        <p>建批次 → 逐人标记缴费 → 自动生成收入流水 → 关闭批次，全程不改账</p>
      </div>
      <el-button type="primary" @click="openCreate">新建批次</el-button>
    </div>

    <!-- 首屏加载态（MASTER §8：加载态预留空间，避免内容弹出的 CLS） -->
    <section
      v-if="loading"
      class="glass-card list-loading"
      aria-label="批次加载中"
      aria-busy="true"
      v-loading="true"
    />

    <!-- 空态：加载失败与真的没有数据分开，避免误导用户去创建重复批次 -->
    <div v-else-if="loadError" class="glass-card empty-state">
      <el-empty description="批次列表加载失败，请检查网络后重试">
        <el-button type="primary" @click="load()">重新加载</el-button>
      </el-empty>
    </div>

    <!-- 空态：给出明确的下一步 -->
    <div v-else-if="batches.length === 0" class="glass-card empty-state">
      <el-empty description="还没有收费批次">
        <el-button type="primary" @click="openCreate">创建第一个批次</el-button>
      </el-empty>
    </div>

    <ul v-else class="batch-list" aria-label="收费批次列表">
      <li v-for="b in batches" :key="b.id" class="glass-card batch">
        <div class="batch-top">
          <div class="batch-name">
            <h3>{{ b.name }}</h3>
            <el-tag :type="b.status === 'OPEN' ? 'primary' : 'info'" size="small" effect="light">
              {{ BATCH_STATUS_TEXT[b.status] }}
            </el-tag>
          </div>
          <span class="muted created">创建于 {{ dayjs(b.createdAt).format('YYYY-MM-DD') }}</span>
        </div>

        <div class="batch-meta">
          <span>
            每人应收 <b class="num">¥{{ Number(b.amount).toFixed(2) }}</b>
          </span>
          <span>合计应收 <b class="num">¥{{ (Number(b.amount) * b.total).toFixed(2) }}</b></span>
          <span>截止 {{ b.deadline ?? '不限' }}</span>
          <span v-if="b.remark" class="remark">{{ b.remark }}</span>
        </div>

        <div class="progress">
          <el-progress
            class="bar"
            :percentage="Number(b.rate)"
            :stroke-width="10"
            :show-text="false"
            color="var(--color-accent-text)"
            aria-hidden="true"
          />
          <span class="progress-text">
            已缴 <b class="num">{{ b.paidCount }}/{{ b.total }}</b> 人 ·
            <b class="num">{{ b.rate }}%</b>
          </span>
        </div>

        <div class="batch-actions">
          <el-button
            size="small"
            :aria-expanded="expandedId === b.id"
            :aria-controls="`batch-detail-${b.id}`"
            @click="toggleDetail(b)"
          >
            {{ expandedId === b.id ? '收起明细' : `查看明细（${b.total} 人）` }}
          </el-button>
          <!-- 第十七轮归属权（A 方案）：关闭/删除只对**创建人**开放。
               后端 require_ownership 是硬边界，这里隐藏按钮是为了不让人点了才吃 403。
               注意「标记已交」**不**受此限制 —— 收款是协作动作，闸门加在缴费上会把账卡死。 -->
          <el-button
            v-if="b.status === 'OPEN' && isMine(b)"
            size="small"
            type="danger"
            plain
            @click="onCloseBatch(b)"
          >
            关闭批次
          </el-button>
          <el-button v-if="isMine(b)" size="small" type="danger" plain @click="onDeleteBatch(b)">
            删除批次
          </el-button>
          <span v-if="!isMine(b)" class="muted closed-hint">
            由 {{ b.createdByName ?? '他人' }} 创建，仅创建人可关闭或删除
          </span>
          <span v-if="b.status !== 'OPEN'" class="muted closed-hint">
            已关闭<span v-if="b.closedByName"> · 由 {{ b.closedByName }} 关闭</span> ·
            {{ b.paidCount }}/{{ b.total }} 人已缴
          </span>
        </div>

        <!-- 逐人明细：同一时刻只展开一个批次 -->
        <div v-if="expandedId === b.id" :id="`batch-detail-${b.id}`" class="detail">
          <div
            class="detail-inner"
            :class="{ 'is-loading': detailLoading }"
            :aria-busy="detailLoading"
            v-loading="detailLoading"
          >
            <template v-if="detail && detail.payments.length > 0">
              <!-- 桌面：表格 -->
              <el-table class="detail-table desktop-only" :data="detail.payments">
                <el-table-column label="成员" min-width="170">
                  <template #default="{ row }">
                    <div class="who">
                      <b>{{ row.realName }}</b>
                      <el-tag
                        v-if="row.role && row.role !== 'MEMBER'"
                        size="small"
                        type="info"
                        effect="plain"
                      >
                        {{ roleText(row.role) }}
                      </el-tag>
                    </div>
                    <span class="muted sn">{{ row.studentNo ?? '—' }}</span>
                  </template>
                </el-table-column>

                <el-table-column label="状态" width="96">
                  <template #default="{ row }">
                    <el-tag :type="payTagType(row.status)" size="small" effect="light">
                      {{ statusText(row) }}
                    </el-tag>
                  </template>
                </el-table-column>

                <el-table-column label="实缴" width="124" align="right">
                  <template #default="{ row }">
                    <template v-if="row.status === 'PAID'">
                      <div class="num paid-amount">¥{{ Number(row.amount).toFixed(2) }}</div>
                      <span class="muted ch">{{ channelText(row.channel) }}</span>
                    </template>
                    <span v-else class="muted">—</span>
                  </template>
                </el-table-column>

                <el-table-column label="缴费时间" width="156">
                  <template #default="{ row }">
                    <span class="muted">{{ row.paidAt ?? '—' }}</span>
                  </template>
                </el-table-column>

                <el-table-column label="操作" width="116" align="right">
                  <template #default="{ row }">
                    <el-button
                      v-if="row.status === 'UNPAID' && b.status === 'OPEN'"
                      size="small"
                      type="primary"
                      plain
                      @click="openPay(row)"
                    >
                      标记已交
                    </el-button>
                    <el-button
                      v-else-if="row.status === 'PAID' && row.recordId"
                      size="small"
                      link
                      type="primary"
                      @click="gotoRecord(row)"
                    >
                      查看流水
                    </el-button>
                    <span v-else class="muted">—</span>
                  </template>
                </el-table-column>
              </el-table>

              <!-- 移动端：卡片（不横向滚动，MASTER §4） -->
              <ul class="detail-cards mobile-only" aria-label="成员缴费明细">
                <li v-for="p in detail.payments" :key="p.id" class="dcard">
                  <div class="dcard-top">
                    <div class="who">
                      <b>{{ p.realName }}</b>
                      <el-tag
                        v-if="p.role && p.role !== 'MEMBER'"
                        size="small"
                        type="info"
                        effect="plain"
                      >
                        {{ roleText(p.role) }}
                      </el-tag>
                      <span class="muted sn">{{ p.studentNo ?? '—' }}</span>
                    </div>
                    <el-tag :type="payTagType(p.status)" size="small" effect="light">
                      {{ PAY_STATUS_TEXT[p.status] }}
                    </el-tag>
                  </div>
                  <div class="dcard-mid">
                    <template v-if="p.status === 'PAID'">
                      <span class="num paid-amount">¥{{ Number(p.amount).toFixed(2) }}</span>
                      <span class="muted">{{ channelText(p.channel) }} · {{ p.paidAt }}</span>
                    </template>
                    <span v-else class="muted">尚未缴费</span>
                  </div>
                  <div class="dcard-actions">
                    <el-button
                      v-if="p.status === 'UNPAID' && b.status === 'OPEN'"
                      size="small"
                      type="primary"
                      plain
                      @click="openPay(p)"
                    >
                      标记已交
                    </el-button>
                    <el-button
                      v-else-if="p.status === 'PAID' && p.recordId"
                      size="small"
                      link
                      type="primary"
                      @click="gotoRecord(p)"
                    >
                      查看流水
                    </el-button>
                  </div>
                </li>
              </ul>
            </template>

            <p v-else-if="detail && detail.payments.length === 0" class="muted">
              该批次没有成员记录（成员是在创建批次时生成的）。
            </p>
            <p v-else-if="!detailLoading" class="muted">明细加载失败，请收起后重新展开。</p>
          </div>
        </div>
      </li>
    </ul>

    <!-- 新建批次 -->
    <el-dialog
      v-model="createVisible"
      title="新建收费批次"
      width="min(560px, 92vw)"
      @closed="restoreCreateFocus"
    >
      <div v-if="alertMessage" ref="alertRef" class="error-summary" role="alert" tabindex="-1">
        <b>无法创建：</b>{{ alertMessage }}
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent>
        <el-form-item label="批次名称" prop="name">
          <el-input
            v-model.trim="form.name"
            aria-label="批次名称"
            maxlength="60"
            show-word-limit
            placeholder="如：2026 春季班费"
          />
        </el-form-item>

        <div class="row-2">
          <el-form-item label="每人应收（元）" prop="amount" class="grow">
            <el-input-number
              v-model="form.amount"
              class="full"
              aria-label="每人应收（元）"
              :controls="false"
              inputmode="decimal"
              :min="0.01"
              :max="99999999.99"
              :precision="2"
              :step="1"
              placeholder="0.00"
            />
          </el-form-item>

          <el-form-item label="截止日（选填）" prop="deadline" class="grow">
            <el-date-picker
              v-model="form.deadline"
              class="full"
              aria-label="截止日"
              type="date"
              placeholder="选择截止日"
              value-format="YYYY-MM-DD"
            />
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
            placeholder="如：用于春游物资与打印资料"
          />
        </el-form-item>
      </el-form>

      <p class="form-hint">
        创建后自动为全班成员生成「未缴费」记录；逐人标记后会在同一事务里生成收入流水并更新余额。
      </p>

      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="onCreate">创建批次</el-button>
      </template>
    </el-dialog>

    <!-- 代为登记 / 标记已交（与成员缴费页共用） -->
    <BatchPayDialog
      v-model="payVisible"
      :batch="payMember?.batch ?? null"
      :member="payMember"
      @saved="onPaySaved"
    />
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}

.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.page-head h2 {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
  line-height: 1.3;
}

.page-head p {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--color-muted-fg);
}

.list-loading {
  min-height: 240px;
}

.empty-state {
  padding: var(--space-lg) var(--space-md);
}

.batch-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}

.batch {
  padding: var(--space-md);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.batch-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.batch-name {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.batch-name h3 {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
}

.created {
  font-size: 12px;
}

.batch-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  font-size: 13px;
  color: var(--color-muted-fg);
}

.batch-meta b {
  color: var(--color-foreground);
}

.remark {
  color: var(--color-muted-fg);
}

/* 完成率图表：进度条为视觉呈现，数值由旁边的文字承担语义 */
.progress {
  display: flex;
  align-items: center;
  gap: 12px;
}

.progress .bar {
  flex: 1;
  min-width: 120px;
}

.progress-text {
  font-size: 13px;
  color: var(--color-muted-fg);
  white-space: nowrap;
}

.progress-text b {
  color: var(--color-foreground);
}

.batch-actions {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  flex-wrap: wrap;
}

.closed-hint {
  font-size: 13px;
  margin-left: auto;
}

.detail {
  border-top: 1px solid var(--color-border);
  padding-top: 14px;
}

.detail-inner {
  min-height: 60px;
}

.detail-inner.is-loading {
  min-height: 150px;
}

.who {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.sn {
  display: block;
  font-size: 12px;
}

.ch {
  font-size: 12px;
}

.paid-amount {
  font-weight: 600;
}

.muted {
  color: var(--color-muted-fg);
}

/* 移动端明细卡片 */
.detail-cards {
  display: none;
  list-style: none;
  margin: 0;
  padding: 0;
  flex-direction: column;
  gap: var(--space-sm);
}

.dcard {
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-surface);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dcard-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.dcard-mid {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 13px;
}

.dcard-mid .paid-amount {
  font-size: 16px;
}

.dcard-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-sm);
}

/* 新建弹窗 */
.error-summary {
  border: 1px solid rgba(220, 38, 38, 0.35);
  background: rgba(220, 38, 38, 0.06);
  color: var(--color-destructive-text);
  border-radius: var(--radius);
  padding: 11px 13px;
  margin-bottom: 16px;
  font-size: 13px;
}

.form-hint {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--color-muted-fg);
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

/* 1024px 视口的内容区 ~706px：明细表格六列共 ~656px 可放下；
   ≤1023 整体切卡片列表（卡片携带全部字段），不出现横向滚动 */
@media (max-width: 1023px) {
  .desktop-only {
    display: none;
  }

  .detail-cards {
    display: flex;
  }
}

@media (max-width: 768px) {
  .page-head h2 {
    font-size: 20px;
  }

  .closed-hint {
    margin-left: 0;
  }

  .progress {
    flex-direction: column;
    align-items: stretch;
    gap: 6px;
  }
}
</style>
