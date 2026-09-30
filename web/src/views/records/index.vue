<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import { deleteRecord, exportRecords, fetchCategories, fetchRecords, voidRecord } from '@/api/records'
import { fetchReceipt } from '@/api/files'
import { useUserStore } from '@/stores/user'
import { useModal } from '@/composables/useModal'
import RecordFormDrawer from '@/components/RecordFormDrawer.vue'
import type { Category, FeeRecord, RecordQuery, RecordStatus, RecordType } from '@/types'
import { CHANNEL_TEXT, STATUS_TEXT, TYPE_TEXT } from '@/types'

/**
 * 账本明细（/records）、收入登记（/income）、支出登记（/expense）共用一个页面：
 * 由路由 meta.type 决定是否固定方向，登记页多一个「新增」入口。
 */
const route = useRoute()
const userStore = useUserStore()

const fixedType = computed(() => route.meta.type as RecordType | undefined)
const pageTitle = computed(() => (route.meta.title as string) || '账本明细')

/**
 * 页面副标题：按角色给不同说明。
 * 第十六轮：原文案对所有角色统一说「记错可「作废」红冲或删除」，但普通成员只读、
 * 点不到这两个按钮 —— 属于「承诺了做不到的事」。这里改成：登记页/运营角色才提作废删除，
 * 普通成员只说明可筛选。
 */
const pageHint = computed(() => {
  if (fixedType.value) {
    return `只显示${TYPE_TEXT[fixedType.value]}流水，可按类别、时间与关键字筛选`
  }
  return userStore.isStaff
    ? '记错可「作废」红冲或删除；已作废默认隐藏，可切换状态查看'
    : '账本为只读视图；如需更正请联系生活委员、班长或班主任'
})

const loading = ref(false)
const rows = ref<FeeRecord[]>([])
const total = ref(0)
const categories = ref<Category[]>([])
const drawerVisible = ref(false)

const filters = reactive<{
  type: RecordType | ''
  keyword: string
  categoryId?: number
  status?: RecordStatus | ''
  range: [string, string] | null
}>({
  type: '',
  keyword: '',
  categoryId: undefined,
  // 默认只看正常流水：已作废默认隐藏（需要时用状态筛选查看），作废记录不再占满列表
  status: 'NORMAL',
  range: null,
})

const page = reactive({ num: 1, size: 20 })
const PAGE_SIZES = [10, 20, 50]

/**
 * 批次明细「查看流水」跳转（/records?id=123）：只在首次加载精确命中一次，
 * 之后用户改任何筛选都不再带 id，避免列表被一个看不见的条件锁死。
 */
let pendingJumpId =
  typeof route.query.id === 'string' && /^\d+$/.test(route.query.id)
    ? Number(route.query.id)
    : undefined

// 精确跳转的目标可能是已作废流水：放开默认的状态过滤，保证能命中
if (pendingJumpId !== undefined) {
  filters.status = ''
}

const canWrite = computed(() => userStore.isStaff)

/**
 * 第十七轮归属权（A 方案）：**作废 / 删除只对自己记的流水开放**。
 * 后端 `require_ownership` 是硬边界，这里只负责不让人点了才吃 403。
 * 他人记的流水在列表里照常显示（账是公开的），只是不给改的入口。
 */
const isMine = (row: FeeRecord) => row.createdBy === userStore.user?.id

/**
 * 表格列的响应式取舍：
 * - 视口 ≥1280px（内容区 ≥980px）：十列全显（含小票列，固定宽合计 942px）；
 * - 1024–1279px（内容区仅 ~706px）：「支付方式 / 录入人」并入摘要列的次要行，
 *   小票入口也并入摘要列（独立列合计会超宽），避免表格内层横向滚动把「金额」等关键列藏起来。
 */
const showDetailColumns = ref(
  typeof window !== 'undefined' ? window.matchMedia('(min-width: 1280px)').matches : true,
)
let detailMq: MediaQueryList | null = null

function syncDetailColumns() {
  showDetailColumns.value = detailMq?.matches ?? true
}

onMounted(() => {
  detailMq = window.matchMedia('(min-width: 1280px)')
  syncDetailColumns()
  detailMq.addEventListener('change', syncDetailColumns)
})

onUnmounted(() => detailMq?.removeEventListener('change', syncDetailColumns))

/** 筛选栏的类别下拉：登记页只显示同方向类别 */
const filterCategories = computed(() =>
  fixedType.value ? categories.value.filter((c) => c.kind === fixedType.value) : categories.value,
)

/** 加载失败标记：区分「没有数据」与「接口出错」的空态 */
const loadError = ref(false)

async function load() {
  loading.value = true
  try {
    const result = await fetchRecords({ ...currentQuery(), id: pendingJumpId })
    rows.value = result.records
    total.value = result.total
    if (pendingJumpId !== undefined) {
      // 精确跳转却 0 命中（权限外 / 条件不匹配）时必须给出可读反馈
      if (result.total === 0) {
        ElMessage.info(`未找到流水 #${pendingJumpId}，可能不属于本班或与当前筛选不匹配`)
      }
      pendingJumpId = undefined // 只生效一次
    }
    loadError.value = false
  } catch {
    loadError.value = true // 拦截器已统一提示，这里只避免未处理的 rejection
  } finally {
    loading.value = false
  }
}

/** 筛选条件变化 → 回到第一页再查 */
function applyFilters() {
  page.num = 1
  load()
}

/** 当前生效的查询条件（列表与导出共用，保证「导出=所见」） */
function currentQuery(): RecordQuery {
  return {
    page: page.num,
    size: page.size,
    type: fixedType.value ?? (filters.type || undefined),
    categoryId: filters.categoryId,
    keyword: filters.keyword.trim() || undefined,
    status: filters.status || undefined,
    start: filters.range?.[0],
    end: filters.range?.[1],
  }
}

/** 导出 Excel（仅运营角色）：带当前筛选条件，文件流直接交给浏览器下载 */
const exporting = ref(false)

async function onExport() {
  if (exporting.value) return
  exporting.value = true
  try {
    // 精确跳转（?id=）也带上：导出的就是这一笔
    await exportRecords({ ...currentQuery(), id: pendingJumpId })
    ElMessage.success('已开始下载账本 Excel')
  } catch {
    /* 拦截器已提示（403 无权限 / 网络异常） */
  } finally {
    exporting.value = false
  }
}

function resetFilters() {
  filters.type = ''
  filters.keyword = ''
  filters.categoryId = undefined
  filters.status = 'NORMAL' // 重置 = 回到默认视图（隐藏已作废）
  filters.range = null
  applyFilters()
}

function onPageChange(p: number) {
  page.num = p
  load()
}

function onSizeChange(size: number) {
  page.size = size
  applyFilters()
}

async function onVoid(row: FeeRecord) {
  try {
    await ElMessageBox.confirm(
      `确认作废「${row.title}」（${TYPE_TEXT[row.type]} ${row.amount.toFixed(2)} 元）？作废后余额会同步回滚，流水保留可查。`,
      '作废确认',
      { type: 'warning', confirmButtonText: '确认作废', cancelButtonText: '再想想' },
    )
  } catch {
    return // 用户取消
  }
  try {
    await voidRecord(row.id)
  } catch {
    return // 拦截器已统一提示，这里兜住未处理的 rejection
  }
  ElMessage.success('已作废，余额已回滚')
  load()
}

async function onDelete(row: FeeRecord) {
  try {
    await ElMessageBox.confirm(
      row.status === 'VOID'
        ? `确认删除已作废的「${row.title}」？记录将彻底移除，不可恢复。`
        : `确认删除「${row.title}」（${TYPE_TEXT[row.type]} ${row.amount.toFixed(2)} 元）？余额会同步回滚，删除不可恢复；仅记错建议优先用「作废」留痕。`,
      '删除确认',
      { type: 'error', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
  } catch {
    return // 用户取消
  }
  try {
    await deleteRecord(row.id)
  } catch {
    return // 拦截器已统一提示，这里兜住未处理的 rejection
  }
  ElMessage.success(row.status === 'VOID' ? '已删除该流水' : '已删除，余额已回滚')
  load()
}

onMounted(async () => {
  try {
    categories.value = await fetchCategories()
  } catch {
    /* 拦截器已提示；类别下拉为空不阻塞列表主流程 */
  }
  await load()
})

// 同一组页面在 /records ↔ /income ↔ /expense 间切换时复用组件，需跟随路由重新取数
watch(
  () => route.path,
  () => {
    filters.categoryId = undefined
    page.num = 1
    load()
  },
)

// 停留在记录页时 query 变化（浏览器前进/后退带 ?id=）：path 不变，单独监听生效精确跳转
watch(
  () => route.query.id,
  (value) => {
    if (typeof value === 'string' && /^\d+$/.test(value)) {
      pendingJumpId = Number(value)
      filters.status = '' // 跳转目标可能是已作废流水，放开默认状态过滤
      page.num = 1
      load()
    }
  },
)

/** 模板里 el-table 的 slot 参数是宽松类型，统一走这里的强类型取文案 */
const typeText = (row: FeeRecord) => TYPE_TEXT[row.type]
const channelText = (row: FeeRecord) => CHANNEL_TEXT[row.channel]
const statusText = (row: FeeRecord) => STATUS_TEXT[row.status]

// ---------------- 小票查看 ----------------
// /api/files/* 要 Authorization，<img src> 带不了头：先带 token 取 Blob 转
// objectURL，再按路径缓存（同图不重复请求），组件卸载时统一释放。
const receiptVisible = ref(false)
const receiptLoading = ref(false)
const receiptFailed = ref(false)
const receiptSrc = ref('')
const receiptPath = ref('')
const receiptTitle = ref('')
const receiptCache = new Map<string, string>()

/** 弹层内根元素：供 useModal 判定本对话框是否处于最上层（Esc 归谁消费） */
const dialogRef = ref<HTMLElement>()
const { restoreFocus } = useModal(receiptVisible, dialogRef)

async function loadReceipt(path: string) {
  receiptSrc.value = ''
  receiptFailed.value = false
  receiptLoading.value = true
  try {
    const url = URL.createObjectURL(await fetchReceipt(path))
    receiptCache.set(path, url)
    receiptSrc.value = url
  } catch {
    receiptFailed.value = true // 拦截器已提示；弹窗内保留重试入口
  } finally {
    receiptLoading.value = false
  }
}

async function viewReceipt(row: FeeRecord) {
  const path = row.receiptUrl
  if (!path) return
  receiptPath.value = path
  receiptTitle.value = row.title
  receiptVisible.value = true
  const cached = receiptCache.get(path)
  if (cached) {
    receiptSrc.value = cached
    receiptFailed.value = false
    receiptLoading.value = false
    return
  }
  await loadReceipt(path)
}

function retryReceipt() {
  if (receiptPath.value) loadReceipt(receiptPath.value)
}

onUnmounted(() => {
  receiptCache.forEach((url) => URL.revokeObjectURL(url))
  receiptCache.clear()
})

const datePickOptions = {
  valueFormat: 'YYYY-MM-DD',
  shortcuts: [
    { text: '本月', value: [dayjs().startOf('month').toDate(), dayjs().endOf('month').toDate()] },
    { text: '近 30 天', value: [dayjs().subtract(30, 'day').toDate(), dayjs().toDate()] },
  ],
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>{{ pageTitle }}</h2>
        <p>
          <!-- 第十六轮：原文案对所有角色都说「记错可作废或删除」，但普通成员根本不能改流水，
               属于承诺了做不到的事。改成按角色给不同说明。 -->
          {{ pageHint }}
        </p>
      </div>
      <div class="head-actions">
        <el-tooltip content="按当前筛选条件导出 Excel" placement="bottom">
          <el-button v-if="canWrite" :loading="exporting" @click="onExport">
            导出 Excel
          </el-button>
        </el-tooltip>
        <el-button
          v-if="fixedType && canWrite"
          type="primary"
          @click="drawerVisible = true"
        >
          新增{{ TYPE_TEXT[fixedType] }}
        </el-button>
      </div>
    </div>

    <!-- 筛选栏 -->
    <section class="glass-card filters" aria-label="筛选条件">
      <el-input
        v-model="filters.keyword"
        class="f-keyword"
        placeholder="搜索摘要 / 备注"
        clearable
        aria-label="关键字"
        @keyup.enter="applyFilters"
        @clear="applyFilters"
      />

      <el-select
        v-if="!fixedType"
        v-model="filters.type"
        class="f-type"
        placeholder="全部方向"
        clearable
        aria-label="收支方向"
        @change="applyFilters"
      >
        <el-option label="收入" value="INCOME" />
        <el-option label="支出" value="EXPENSE" />
      </el-select>

      <el-select
        v-model="filters.categoryId"
        class="f-cat"
        placeholder="全部类别"
        clearable
        aria-label="类别"
        @change="applyFilters"
      >
        <el-option
          v-for="cat in filterCategories"
          :key="cat.id"
          :label="cat.name"
          :value="cat.id"
        />
      </el-select>

      <el-select
        v-model="filters.status"
        class="f-status"
        placeholder="全部状态"
        clearable
        aria-label="状态"
        @change="applyFilters"
      >
        <el-option label="正常" value="NORMAL" />
        <el-option label="已作废" value="VOID" />
      </el-select>

      <el-date-picker
        v-model="filters.range"
        class="f-range"
        type="daterange"
        range-separator="至"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        :shortcuts="datePickOptions.shortcuts"
        :clearable="true"
        aria-label="发生日期区间"
        @change="applyFilters"
      />

      <el-button class="f-search" type="primary" plain @click="applyFilters">查询</el-button>
      <el-button class="f-reset" @click="resetFilters">重置</el-button>
    </section>

    <!-- 桌面：表格 -->
    <section class="glass-card table-wrap desktop-only" aria-label="流水列表" :aria-busy="loading">
      <el-table v-loading="loading" :data="rows" style="width: 100%">
        <el-table-column label="发生时间" width="136">
          <template #default="{ row }">
            <span class="num">{{ row.occurredAt }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="categoryName" label="类别" width="84" />
        <el-table-column label="摘要" min-width="96">
          <template #default="{ row }">
            <span :class="{ voided: row.status === 'VOID' }">{{ row.title }}</span>
            <span v-if="row.remark" class="remark">{{ row.remark }}</span>
            <!-- 窄桌面放不下独立列时，支付方式/录入人并入此列 -->
            <span v-if="!showDetailColumns" class="meta">
              {{ channelText(row) }} · {{ row.createdByName ?? '—' }}
            </span>
            <!-- 小票同理：窄桌面不占 64px 列，改为摘要列内的入口（桌面表格不内层横滚） -->
            <span v-if="!showDetailColumns && row.receiptUrl" class="meta">
              <el-button
                link
                type="primary"
                size="small"
                :aria-label="`查看小票：${row.title}`"
                @click="viewReceipt(row)"
              >
                查看小票
              </el-button>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="方向" width="80">
          <template #default="{ row }">
            <el-tag :type="row.type === 'INCOME' ? 'success' : 'danger'" size="small" effect="light">
              {{ row.type === 'INCOME' ? '+' : '−' }}{{ typeText(row) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="金额（元）" width="110" align="right">
          <template #default="{ row }">
            <span
              class="num amount"
              :class="row.type === 'INCOME' ? 'amount-in' : 'amount-out'"
            >
              {{ row.type === 'INCOME' ? '+' : '−' }}{{ row.amount.toFixed(2) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column v-if="showDetailColumns" label="支付方式" width="84">
          <template #default="{ row }">{{ channelText(row) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="150">
          <template #default="{ row }">
            <div class="status-cell">
              <el-tag
                :type="row.status === 'NORMAL' ? 'info' : 'warning'"
                size="small"
                effect="plain"
              >
                {{ statusText(row) }}
              </el-tag>
              <!-- 第十九轮审计：作废留痕。删除是硬删无痕，所以「作废」是账去哪了的唯一线索 -->
              <el-tooltip
                v-if="row.status === 'VOID' && row.voidedByName"
                :content="`由 ${row.voidedByName} 于 ${row.voidedAt ?? '—'} 作废`"
                placement="top"
              >
                <span class="voided-by">谁作废</span>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
        <el-table-column v-if="showDetailColumns" prop="createdByName" label="录入人" width="100" />
        <!-- 小票列（仅宽桌面；窄桌面入口在摘要列，收入页不显示） -->
        <el-table-column v-if="showDetailColumns && fixedType !== 'INCOME'" label="小票" width="64">
          <template #default="{ row }">
            <el-button
              v-if="row.receiptUrl"
              link
              type="primary"
              size="small"
              :aria-label="`查看小票：${row.title}`"
              @click="viewReceipt(row)"
            >
              查看
            </el-button>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <!-- 操作列 108px：作废 + 删除两个 link 按钮并排，摘要列 min-width 同步收窄保持总宽 -->
        <el-table-column v-if="canWrite" label="操作" width="108" fixed="right">
          <template #default="{ row }">
            <!-- 第十七轮归属权：他人记的流水不给作废/删除入口 -->
            <template v-if="isMine(row)">
              <el-button
                v-if="row.status === 'NORMAL'"
                link
                type="danger"
                size="small"
                @click="onVoid(row)"
              >
                作废
              </el-button>
              <el-button link type="danger" size="small" @click="onDelete(row)">删除</el-button>
            </template>
            <span v-else class="muted other-author">{{ row.createdByName ?? '他人' }} 记的</span>
          </template>
        </el-table-column>
      </el-table>

      <el-empty
        v-if="!loading && rows.length === 0"
        :description="loadError ? '流水加载失败，请检查网络后重试' : '暂无符合条件的流水'"
        :image-size="80"
      >
        <el-button v-if="loadError" type="primary" @click="load()">重新加载</el-button>
      </el-empty>
    </section>

    <!-- 移动端：卡片列表 -->
    <section
      class="cards mobile-only"
      aria-label="流水列表"
      :aria-busy="loading"
      v-loading="loading"
      :class="{ 'is-loading': loading }"
    >
      <article v-for="row in rows" :key="row.id" class="glass-card card">
        <div class="card-top">
          <span class="cat">{{ row.categoryName }}</span>
          <span class="num time">{{ row.occurredAt }}</span>
        </div>
        <div class="card-title" :class="{ voided: row.status === 'VOID' }">{{ row.title }}</div>
        <div class="card-bottom">
          <span
            class="num amount"
            :class="row.type === 'INCOME' ? 'amount-in' : 'amount-out'"
          >
            {{ row.type === 'INCOME' ? '+' : '−' }}{{ row.amount.toFixed(2) }}
          </span>
          <span class="muted">{{ channelText(row) }} · {{ row.createdByName ?? '—' }}</span>
          <el-tag
            v-if="row.status === 'VOID'"
            type="warning"
            size="small"
            effect="plain"
          >
            已作废
          </el-tag>
          <!-- 第十九轮审计：作废留痕（谁、何时）。删除是硬删无痕，这里是唯一线索 -->
          <el-tooltip
            v-if="row.status === 'VOID' && row.voidedByName"
            :content="`由 ${row.voidedByName} 于 ${row.voidedAt ?? '—'} 作废`"
            placement="top"
          >
            <span class="voided-by">谁作废</span>
          </el-tooltip>
          <template v-if="row.receiptUrl">
            <el-button link type="primary" size="small" @click="viewReceipt(row)">小票</el-button>
          </template>
          <template v-if="canWrite && isMine(row)">
            <el-button
              v-if="row.status === 'NORMAL'"
              link
              type="danger"
              size="small"
              @click="onVoid(row)"
            >
              作废
            </el-button>
            <el-button link type="danger" size="small" @click="onDelete(row)">删除</el-button>
          </template>
        </div>
      </article>

      <el-empty
        v-if="!loading && rows.length === 0"
        :description="loadError ? '流水加载失败，请检查网络后重试' : '暂无符合条件的流水'"
        :image-size="80"
      >
        <el-button v-if="loadError" type="primary" @click="load()">重新加载</el-button>
      </el-empty>
    </section>

    <!-- 分页：EP 内置 sizes 选择框没有无障碍名称（axe label 失败），改为自带 aria-label 的选择框 -->
    <div v-if="total > 0" class="pager">
      <el-select
        v-model="page.size"
        class="pager-size"
        aria-label="每页条数"
        @change="onSizeChange"
      >
        <el-option
          v-for="size in PAGE_SIZES"
          :key="size"
          :value="size"
          :label="`${size}条/页`"
        />
      </el-select>
      <el-pagination
        background
        layout="total, prev, pager, next"
        :total="total"
        :current-page="page.num"
        :page-size="page.size"
        @current-change="onPageChange"
      />
    </div>

    <RecordFormDrawer
      v-if="fixedType"
      v-model="drawerVisible"
      :type="fixedType"
      @saved="load"
    />

    <!-- 小票查看：Esc 由 useModal 统一接管（捕获阶段 + 最上层判定），见类别弹窗同款说明 -->
    <el-dialog
      v-model="receiptVisible"
      :title="`小票 · ${receiptTitle}`"
      width="min(560px, 92vw)"
      :close-on-press-escape="false"
      @closed="restoreFocus"
    >
      <div ref="dialogRef" v-loading="receiptLoading" class="receipt-body">
        <img
          v-if="receiptSrc"
          :src="receiptSrc"
          :alt="`「${receiptTitle}」的小票图片`"
          class="receipt-img"
        />
        <div v-else-if="receiptFailed && !receiptLoading" class="receipt-fail" role="alert">
          <p>小票加载失败，可能是文件已被删除</p>
          <el-button type="primary" plain size="small" @click="retryReceipt">重试</el-button>
        </div>
      </div>
    </el-dialog>
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

/* 页头右侧：导出 + 主操作（窄屏自动换行） */
.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-sm);
  padding: var(--space-md);
  align-items: center;
}

.f-keyword {
  width: 220px;
}

.f-cat,
.f-status,
.f-type {
  width: 140px;
}

.f-range {
  max-width: 260px;
}

.table-wrap {
  padding: var(--space-md);
  min-height: 360px;
  overflow: hidden;
}

.amount {
  font-weight: 600;
}

.remark {
  margin-left: 8px;
  font-size: 12px;
  color: var(--color-muted-fg);
}

/* 窄桌面下并入摘要列的「支付方式 · 录入人」次要行 */
.meta {
  display: block;
  font-size: 12px;
  color: var(--color-muted-fg);
}

.voided {
  text-decoration: line-through;
  color: var(--color-muted-fg);
}

/* 小票弹窗：加载态预留高度，避免图片到达后把弹窗撑高（CLS） */
.receipt-body {
  min-height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.receipt-img {
  max-width: 100%;
  max-height: 60vh;
  border-radius: var(--radius);
  border: 1px solid var(--color-border);
}

.receipt-fail {
  text-align: center;
  color: var(--color-muted-fg);
  font-size: 13px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.receipt-fail p {
  margin: 0;
  color: var(--color-destructive-text);
}

.muted {
  color: var(--color-muted-fg);
}

/* 第十七轮归属权：他人记的流水，操作列显示「谁记的」而不是空白 */
.other-author {
  font-size: 12px;
  white-space: nowrap;
}

/* 第十九轮审计：已作废流水的「谁作废」角标 */
.status-cell {
  display: flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}

.voided-by {
  padding: 0 4px;
  border: 1px dashed var(--color-border);
  border-radius: 4px;
  font-size: 11px;
  line-height: 18px;
  color: var(--color-muted-fg);
  cursor: help;
  white-space: nowrap;
}

.pager {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-sm);
  flex-wrap: wrap;
}

.pager-size {
  width: 108px;
  flex: none;
}

/* 移动端卡片 */
.cards {
  display: none;
  flex-direction: column;
  gap: var(--space-sm);
}

/* 加载态预留高度（MASTER §8：加载态预留空间，避免内容弹出的 CLS） */
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
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  color: var(--color-muted-fg);
}

.card-title {
  font-size: 14px;
  font-weight: 600;
}

.card-bottom {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap; /* 小票入口加入后，窄屏换行而不是溢出横滚 */
  font-size: 12px;
}

.card-bottom .amount {
  font-size: 18px;
  margin-right: auto;
}

/* 1024px 视口的内容区仅 ~706px，表格九列需要 870px：
   ≤1023 整体切卡片列表（卡片携带全部字段），1024–1279 由脚本隐藏两列并入摘要 */
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
  .f-cat,
  .f-status,
  .f-type,
  .f-range {
    width: 100%;
    max-width: none;
  }
}
</style>
