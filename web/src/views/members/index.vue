<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { fetchBatches, fetchMembers } from '@/api/batches'
import BatchPayDialog from '@/components/BatchPayDialog.vue'
import type { Batch, Channel, MemberRow, PayStatus, Role } from '@/types'
import {
  BATCH_STATUS_TEXT,
  CHANNEL_TEXT,
  PAY_STATUS_TEXT,
  ROLE_TEXT,
} from '@/types'

/**
 * 成员缴费（M6/M7 汇总视图）：选批次 → 看全班缴费状态与进度 → 代为登记。
 * 仅运营角色可见（ADMIN/MONITOR/TEACHER；路由 meta.roles + 后端 _STAFF_ROUTES 双重限制）。
 */
const router = useRouter()

const loading = ref(true)
const batches = ref<Batch[]>([])
const members = ref<MemberRow[]>([])
const selectedBatchId = ref<number | null>(null)

const filters = reactive({
  keyword: '',
  payStatus: '' as PayStatus | '',
})

const currentBatch = computed(
  () => batches.value.find((b) => b.id === selectedBatchId.value) ?? null,
)

const emptyText = computed(() => {
  if (membersError.value) return '成员列表加载失败，请点击查询重试'
  if (batches.value.length === 0) return '还没有收费批次，缴费状态暂不可用'
  if (filters.keyword.trim() || filters.payStatus) return '没有匹配的成员'
  return '暂无成员'
})

/** 批次列表加载失败标记：避免把网络错误显示成「去创建批次」 */
const batchesError = ref(false)

const payVisible = ref(false)
const payMember = ref<{ userId: number; realName: string; studentNo?: string | null } | null>(null)

async function loadBatches() {
  try {
    batches.value = await fetchBatches()
    batchesError.value = false
  } catch {
    batchesError.value = true
    // 拦截器已统一提示
  }
  if (batches.value.length === 0) {
    selectedBatchId.value = null
    return
  }
  // 默认选中：最新进行中 > 最新创建；已失效的选中项也在这里兜底
  const stillExists = batches.value.some((b) => b.id === selectedBatchId.value)
  if (!stillExists) {
    const open = batches.value.find((b) => b.status === 'OPEN')
    selectedBatchId.value = (open ?? batches.value[0]).id
  }
}

/** 列表加载失败标记：区分「真的没有成员」与「接口出错」 */
const membersError = ref(false)
/** 列表刷新 loading（切换批次/筛选时给出反馈，不整页闪骨架） */
const listLoading = ref(false)
/** 请求序号：切换批次/筛选连点时丢弃过期响应，避免数据与选择器错配 */
let memberSeq = 0

async function loadMembers() {
  const seq = ++memberSeq
  listLoading.value = true
  try {
    const data = await fetchMembers({
      keyword: filters.keyword.trim() || undefined,
      payStatus: filters.payStatus || undefined,
      batchId: selectedBatchId.value ?? undefined,
    })
    if (seq !== memberSeq) return
    members.value = data
    membersError.value = false
  } catch {
    if (seq !== memberSeq) return
    members.value = []
    membersError.value = true
  } finally {
    if (seq === memberSeq) listLoading.value = false
  }
}

function applyFilters() {
  loadMembers()
}

function resetFilters() {
  filters.keyword = ''
  filters.payStatus = ''
  loadMembers()
}

function goCreate() {
  router.push('/batches')
}

/** 批次列表加载失败后的重试：批次与成员一起重取，保证口径一致 */
async function retryBatches() {
  await loadBatches()
  await loadMembers()
}

function openPay(member: MemberRow) {
  payMember.value = {
    userId: member.userId,
    realName: member.realName,
    studentNo: member.studentNo,
  }
  payVisible.value = true
}

async function onPaySaved() {
  await loadMembers()
  await loadBatches() // 完成率/已缴人数随之变化
}

/** 查看这笔缴费生成的流水（账本页首屏精确命中一次） */
function gotoRecord(member: MemberRow) {
  if (!member.recordId) return
  router.push({ path: '/records', query: { id: String(member.recordId) } })
}

/* ============================ 文案 ============================ */

const payTagType = (status: PayStatus | null): 'success' | 'warning' | 'info' => {
  if (status === 'PAID') return 'success'
  if (status === 'REFUNDED') return 'warning'
  return 'info'
}

const payText = (status: PayStatus | null) => (status ? PAY_STATUS_TEXT[status] : '—')
const channelText = (channel: Channel | null) => (channel ? CHANNEL_TEXT[channel] : '—')
const roleText = (role: Role) => ROLE_TEXT[role]

/** 可代为登记：未缴 + 批次进行中 */
function canPay(member: MemberRow): boolean {
  return (
    member.payStatus === 'UNPAID' && currentBatch.value?.status === 'OPEN'
  )
}

/** 已缴且有对应流水，可跳转查看 */
function hasRecord(member: MemberRow): boolean {
  return member.payStatus === 'PAID' && !!member.recordId
}

onMounted(async () => {
  loading.value = true
  try {
    await loadBatches()
    await loadMembers()
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>成员缴费</h2>
        <p>按批次查看全班缴费状态，可为未缴费成员代为登记（同步生成收入流水）</p>
      </div>
      <el-button v-if="batches.length > 0" @click="goCreate">管理收费批次</el-button>
    </div>

    <!-- 还没有批次的引导（加载失败单独给重试，避免误导去重复建批次） -->
    <div v-if="!loading && batchesError" class="glass-card notice" role="alert">
      <span>批次列表加载失败，请检查网络后重试。</span>
      <el-button type="primary" size="small" @click="retryBatches">重新加载</el-button>
    </div>
    <div v-else-if="!loading && batches.length === 0" class="glass-card notice" role="status">
      <span>还没有收费批次，缴费状态不可用。创建批次后即可逐人标记缴费。</span>
      <el-button type="primary" size="small" @click="goCreate">去创建批次</el-button>
    </div>

    <!-- 批次选择 + 完成率进度 -->
    <section v-if="batches.length > 0" class="glass-card batch-panel" aria-label="批次进度">
      <div class="panel-row">
        <el-select
          v-model="selectedBatchId"
          class="batch-select"
          aria-label="选择收费批次"
          @change="loadMembers"
        >
          <el-option
            v-for="b in batches"
            :key="b.id"
            :label="`${b.name}（${BATCH_STATUS_TEXT[b.status]}）`"
            :value="b.id"
          />
        </el-select>
        <el-tag
          v-if="currentBatch"
          :type="currentBatch.status === 'OPEN' ? 'primary' : 'info'"
          size="small"
          effect="light"
        >
          {{ BATCH_STATUS_TEXT[currentBatch.status] }}
        </el-tag>
      </div>

      <template v-if="currentBatch">
        <div class="progress">
          <el-progress
            class="bar"
            :percentage="Number(currentBatch.rate)"
            :stroke-width="10"
            :show-text="false"
            color="var(--color-accent-text)"
            aria-hidden="true"
          />
          <span class="progress-text">
            已缴 <b class="num">{{ currentBatch.paidCount }}/{{ currentBatch.total }}</b> 人 ·
            <b class="num">{{ currentBatch.rate }}%</b>
          </span>
        </div>
        <div class="panel-meta">
          <span>每人应收 <b class="num">¥{{ Number(currentBatch.amount).toFixed(2) }}</b></span>
          <span>截止 {{ currentBatch.deadline ?? '不限' }}</span>
          <span class="muted">未缴 {{ currentBatch.unpaidCount }} 人</span>
        </div>
      </template>
    </section>

    <!-- 筛选栏 -->
    <section class="glass-card filters" aria-label="筛选条件">
      <el-input
        v-model="filters.keyword"
        class="f-keyword"
        placeholder="搜索姓名 / 学号 / 登录名"
        clearable
        aria-label="关键字"
        @keyup.enter="applyFilters"
        @clear="applyFilters"
      />
      <el-select
        v-model="filters.payStatus"
        class="f-status"
        placeholder="全部缴费状态"
        clearable
        aria-label="缴费状态"
        @change="applyFilters"
      >
        <el-option label="已缴费" value="PAID" />
        <el-option label="未缴费" value="UNPAID" />
      </el-select>
      <el-button type="primary" plain @click="applyFilters">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
    </section>

    <!-- 桌面：表格 -->
    <section
      class="glass-card table-wrap desktop-only"
      aria-label="成员缴费列表"
      :aria-busy="loading || listLoading"
      v-loading="loading || listLoading"
    >
      <el-table :data="members" :empty-text="emptyText">
        <el-table-column label="成员" min-width="180">
          <template #default="{ row }">
            <div class="who">
              <b>{{ row.realName }}</b>
              <el-tag
                v-if="row.role !== 'MEMBER'"
                size="small"
                type="info"
                effect="plain"
              >
                {{ roleText(row.role) }}
              </el-tag>
            </div>
            <span class="muted sn">{{ row.studentNo ?? row.username }}</span>
          </template>
        </el-table-column>

        <el-table-column label="缴费状态" width="96">
          <template #default="{ row }">
            <el-tag :type="payTagType(row.payStatus)" size="small" effect="light">
              {{ payText(row.payStatus) }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="实缴" width="110" align="right">
          <template #default="{ row }">
            <template v-if="row.payStatus === 'PAID'">
              <div class="num paid-amount">¥{{ Number(row.amount).toFixed(2) }}</div>
              <span class="muted ch">{{ channelText(row.channel) }}</span>
            </template>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>

        <el-table-column label="缴费时间" width="148">
          <template #default="{ row }">
            <span class="muted">{{ row.paidAt ?? '—' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="104" align="right">
          <template #default="{ row }">
            <el-button
              v-if="canPay(row)"
              size="small"
              type="primary"
              plain
              @click="openPay(row)"
            >
              代为登记
            </el-button>
            <el-button
              v-else-if="hasRecord(row)"
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
    </section>

    <!-- 移动端：卡片（不横向滚动，MASTER §4） -->
    <div
      class="cards mobile-only"
      :class="{ 'is-loading': loading || listLoading }"
      aria-label="成员缴费列表"
      :aria-busy="loading || listLoading"
      v-loading="loading || listLoading"
    >
      <div v-for="m in members" :key="m.userId" class="glass-card card">
        <div class="card-top">
          <div class="who">
            <b>{{ m.realName }}</b>
            <el-tag v-if="m.role !== 'MEMBER'" size="small" type="info" effect="plain">
              {{ roleText(m.role) }}
            </el-tag>
          </div>
          <el-tag :type="payTagType(m.payStatus)" size="small" effect="light">
            {{ payText(m.payStatus) }}
          </el-tag>
        </div>
        <span class="muted sn">{{ m.studentNo ?? m.username }}</span>
        <div class="card-mid">
          <template v-if="m.payStatus === 'PAID'">
            <span class="num paid-amount">¥{{ Number(m.amount).toFixed(2) }}</span>
            <span class="muted">{{ channelText(m.channel) }} · {{ m.paidAt }}</span>
          </template>
          <span v-else class="muted">{{ m.payStatus ? '尚未缴费' : '暂无批次' }}</span>
        </div>
        <div class="card-actions">
          <el-button v-if="canPay(m)" size="small" type="primary" plain @click="openPay(m)">
            代为登记
          </el-button>
          <el-button
            v-else-if="hasRecord(m)"
            size="small"
            link
            type="primary"
            @click="gotoRecord(m)"
          >
            查看流水
          </el-button>
        </div>
      </div>

      <div v-if="members.length === 0 && !loading" class="glass-card card empty-card">
        <p class="muted">{{ emptyText }}</p>
      </div>
    </div>

    <!-- 代为登记（与收费批次页共用） -->
    <BatchPayDialog
      v-model="payVisible"
      :batch="currentBatch"
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

.notice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-sm);
  flex-wrap: wrap;
  padding: var(--space-md);
  font-size: 13px;
  color: var(--color-muted-fg);
}

/* 批次进度面板 */
.batch-panel {
  padding: var(--space-md);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.panel-row {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  flex-wrap: wrap;
}

.batch-select {
  width: min(320px, 100%);
}

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

.panel-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  font-size: 13px;
  color: var(--color-muted-fg);
}

.panel-meta b {
  color: var(--color-foreground);
}

/* 筛选栏 */
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-sm);
  padding: var(--space-md);
  align-items: center;
}

.f-keyword {
  width: 240px;
}

.f-status {
  width: 160px;
}

.table-wrap {
  padding: var(--space-md);
  min-height: 360px;
  overflow: hidden;
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

/* 移动端卡片 */
.cards {
  display: none;
  flex-direction: column;
  gap: var(--space-sm);
}

.cards.is-loading {
  min-height: 360px;
}

.card {
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.card-mid {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 13px;
}

.card-mid .paid-amount {
  font-size: 17px;
}

.card-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-sm);
  margin-top: 4px;
}

.empty-card {
  padding: var(--space-md);
  text-align: center;
}

.empty-card p {
  margin: 0;
  font-size: 13px;
}

/* 1024px 视口的内容区 ~706px：五列共 ~638px 可放下；
   ≤1023 整体切卡片列表（卡片携带全部字段），不出现横向滚动 */
@media (max-width: 1023px) {
  .desktop-only {
    display: none;
  }

  .cards {
    display: flex;
  }
}

@media (max-width: 768px) {
  .page-head h2 {
    font-size: 20px;
  }

  .f-keyword,
  .f-status {
    width: 100%;
    max-width: none;
  }

  .progress {
    flex-direction: column;
    align-items: stretch;
    gap: 6px;
  }
}
</style>
