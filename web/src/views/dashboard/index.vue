<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'
import { fetchCategoryPie, fetchSummary, fetchTrend } from '@/api/dashboard'
import { useUserStore } from '@/stores/user'
import TrendChart from '@/components/TrendChart.vue'
import CategoryPie from '@/components/CategoryPie.vue'
import type { DashboardSummary, Notice, PieItem, TrendPoint } from '@/types'
import { CHANNEL_TEXT, ROLE_TEXT } from '@/types'

const userStore = useUserStore()
const router = useRouter()

const summary = ref<DashboardSummary | null>(null)
const trend = ref<TrendPoint[]>([])
const pie = ref<PieItem[]>([])
const loading = ref(true)

interface StatItem {
  label: string
  value: string
  hint: string
  tone: '' | 'in' | 'out'
  /** 缴费完成率（0-100），有值时卡片内画进度条；其余卡片无此项 */
  progress?: number
}

const stats = computed<StatItem[]>(() => {
  const s = summary.value
  const rate = s?.completionRate != null ? Number(s.completionRate) : null
  return [
    {
      label: '当前余额',
      value: s ? Number(s.balance).toFixed(2) : '--',
      hint: balanceHint.value,
      tone: '',
    },
    {
      label: '本月收入',
      value: s ? Number(s.monthIncome).toFixed(2) : '--',
      hint: s ? `共 ${s.monthCount} 笔流水` : '加载中',
      tone: 'in',
    },
    {
      label: '本月支出',
      value: s ? Number(s.monthExpense).toFixed(2) : '--',
      hint: s ? '不含已作废流水' : '加载中',
      tone: 'out',
    },
    {
      label: '缴费完成率',
      value: rate != null ? `${rate.toFixed(1)}%` : '--',
      hint:
        rate != null
          ? userStore.isStaff
            ? '最近收费批次'
            : '最近收费批次 · 点下面看我的'
          : '暂无收费批次',
      tone: '',
      progress: rate != null ? rate : undefined,
    },
  ]
})

/** 冗余余额与流水求和应当一致，不一致时直接亮出来 */
const balanceHint = computed(() => {
  const s = summary.value
  if (!s) return '加载中'
  const diff = Number(s.balance) - Number(s.realBalance)
  if (Math.abs(diff) < 0.005) return '与流水对账一致'
  return `与流水相差 ${diff.toFixed(2)} 元，请核对`
})

const isReconciled = computed(() => {
  const s = summary.value
  if (!s) return true
  return Math.abs(Number(s.balance) - Number(s.realBalance)) < 0.005
})

/** 置顶公告（后端只返回已发布且置顶的最多 3 条） */
const pinnedNotices = computed<Notice[]>(() => summary.value?.pinnedNotices ?? [])

function fmtTime(value: string | null | undefined) {
  return value ? dayjs(value).format('MM-DD HH:mm') : '—'
}

onMounted(async () => {
  try {
    const [s, t, p] = await Promise.all([fetchSummary(), fetchTrend(6), fetchCategoryPie(6)])
    summary.value = s
    trend.value = t
    pie.value = p
  } catch {
    /* 拦截器已统一提示；summary 缺失时卡片显示占位文案 */
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="dashboard">
    <div class="page-head">
      <div>
        <h2>班级账目总览</h2>
        <p>
          欢迎回来，{{ userStore.displayName }} ·
          {{ userStore.user?.className ?? '未加入班级' }}
        </p>
      </div>
      <span class="role-tag">{{ userStore.user ? ROLE_TEXT[userStore.user.role] : '' }}</span>
    </div>

    <!-- 统计卡 -->
    <section class="stats" aria-label="关键指标" :aria-busy="loading">
      <article
        v-for="item in stats"
        :key="item.label"
        class="glass-card stat"
        :class="{ 'stat-link': item.label === '缴费完成率' }"
      >
        <div class="stat-label">{{ item.label }}</div>
        <div class="stat-value num" :class="item.tone === 'in' ? 'value-in' : item.tone === 'out' ? 'value-out' : ''">
          {{ item.value }}
        </div>
        <div class="stat-hint" :class="{ warn: item.label === '当前余额' && !isReconciled }">
          {{ item.hint }}
        </div>
        <!-- 第十八轮：给这张卡一个去处 —— 运营角色进「成员缴费」，
             普通成员进「我的缴费」（否则只能看到一个百分比却无处可去） -->
        <button
          v-if="item.label === '缴费完成率'"
          type="button"
          class="stat-jump"
          :aria-label="userStore.isStaff ? '查看成员缴费' : '查看我的缴费'"
          @click="router.push(userStore.isStaff ? '/members' : '/my-fees')"
        >
          {{ userStore.isStaff ? '查看缴费名单' : '查看我的缴费' }} →
        </button>
        <!-- 完成率图表：进度条纯视觉，语义由上方数值与 hint 承担 -->
        <el-progress
          v-if="item.progress !== undefined"
          class="stat-progress"
          :percentage="item.progress"
          :stroke-width="8"
          :show-text="false"
          color="var(--color-accent-text)"
          aria-hidden="true"
        />
      </article>
    </section>

    <section class="grid-2">
      <article class="glass-card panel">
        <div class="panel-head">
          <h3>近 6 月收支趋势</h3>
          <span class="hint">收入实线 · 支出虚线</span>
        </div>
        <TrendChart :points="trend" />
      </article>

      <article class="glass-card panel">
        <div class="panel-head">
          <h3>支出分类占比</h3>
          <span class="hint">近 6 月</span>
        </div>
        <CategoryPie :items="pie" />
      </article>
    </section>

    <section class="grid-2">
      <article class="glass-card panel">
        <div class="panel-head">
          <h3>最新流水</h3>
          <span class="hint">含作废记录</span>
        </div>
        <ul class="latest">
          <li v-for="row in summary?.latestRecords ?? []" :key="row.id" :class="{ voided: row.status === 'VOID' }">
            <span class="dot" :class="row.type === 'INCOME' ? 'dot-in' : 'dot-out'" aria-hidden="true" />
            <div class="latest-main">
              <div class="latest-title">{{ row.title }}</div>
              <div class="latest-meta">
                {{ row.categoryName }} · {{ CHANNEL_TEXT[row.channel] }} · {{ fmtTime(row.occurredAt) }}
              </div>
            </div>
            <span
              class="num latest-amount"
              :class="row.type === 'INCOME' ? 'amount-in' : 'amount-out'"
            >
              {{ row.type === 'INCOME' ? '+' : '−' }}{{ Number(row.amount).toFixed(2) }}
            </span>
          </li>
        </ul>
        <el-empty
          v-if="!loading && (summary?.latestRecords?.length ?? 0) === 0"
          description="还没有流水，去「收入登记 / 支出登记」记第一笔"
          :image-size="72"
        />
      </article>

      <article class="glass-card panel">
        <div class="panel-head">
          <h3>置顶公告</h3>
          <router-link to="/notices" class="panel-link">查看全部</router-link>
        </div>
        <ul v-if="pinnedNotices.length > 0" class="notice-list">
          <li v-for="n in pinnedNotices" :key="n.id" class="notice-item">
            <div class="notice-title">{{ n.title }}</div>
            <div class="notice-meta">
              {{ n.createdByName ?? '—' }} · {{ fmtTime(n.publishedAt ?? n.createdAt) }}
            </div>
            <p class="notice-content">{{ n.content }}</p>
          </li>
        </ul>
        <el-empty
          v-else
          description="暂无置顶公告，班级通知会显示在这里"
          :image-size="72"
        />
      </article>
    </section>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-end;
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

.role-tag {
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
  background: rgba(34, 197, 94, 0.14);
  color: var(--color-income);
}

.stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-md);
}

.stat {
  padding: var(--space-md);
}

.stat-label {
  font-size: 13px;
  color: var(--color-muted-fg);
}

.stat-value {
  font-size: 32px;
  font-weight: 600;
  line-height: 1.25;
  margin: 6px 0 4px;
  letter-spacing: -0.5px;
  color: var(--color-foreground);
}

/* 金额方向：符号 + 颜色双重编码（卡片数值不带 +/-，用色 + 文案表达） */
.value-in {
  color: var(--color-income);
}

.value-out {
  color: var(--color-expense);
}

.stat-hint {
  font-size: 12px;
  color: var(--color-muted-fg);
}

.stat-hint.warn {
  color: var(--color-destructive-text);
  font-weight: 600;
}

.stat-progress {
  margin-top: 8px;
}

/* 第十八轮：完成率卡片的去处（运营看名单 / 同学看自己） */
.stat-jump {
  display: inline-block;
  margin-top: 8px;
  padding: 2px 0;
  border: 0;
  background: none;
  font: inherit;
  font-size: 12px;
  color: var(--color-accent-text);
  text-decoration: underline;
  cursor: pointer;
  min-height: 24px;
}

.stat-jump:hover {
  text-decoration: none;
}

.stat-jump:focus-visible {
  outline: 2px solid var(--color-accent-text);
  outline-offset: 2px;
  border-radius: 4px;
}

.stat-link {
  cursor: default;
}

.grid-2 {
  display: grid;
  grid-template-columns: 1.5fr 1fr;
  gap: var(--space-md);
}

.panel {
  padding: var(--space-md);
}

.panel-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 14px;
}

.panel-head h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}

.hint {
  font-size: 12px;
  color: var(--color-muted-fg);
}

/* 面板内的「查看全部」入口（亮绿对白底仅 2.3:1，文字必须用深绿变体；
   padding 撑出 ≥32px 的点击区，负 margin 抵消，视觉位置不变） */
.panel-link {
  margin-left: auto;
  margin-top: -7px;
  margin-bottom: -7px;
  padding: 7px 6px;
  font-size: 12px;
  color: var(--color-accent-text);
  text-decoration: none;
  border-radius: var(--el-border-radius-small);
}

.panel-link:hover {
  text-decoration: underline;
  background: var(--color-muted);
}

/* 置顶公告 */
.notice-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.notice-item {
  padding: 10px 0;
  border-bottom: 1px dashed var(--color-border);
}

.notice-item:last-child {
  border-bottom: 0;
}

.notice-title {
  font-size: 14px;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.notice-meta {
  font-size: 12px;
  color: var(--color-muted-fg);
  margin-top: 2px;
}

.notice-content {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--color-foreground);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  /* 仪表盘只做速览：正文最多 2 行，完整内容去公告页看 */
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 最新流水 */
.latest {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.latest li {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px dashed var(--color-border);
}

.latest li:last-child {
  border-bottom: 0;
}

.latest li.voided .latest-title,
.latest li.voided .latest-amount {
  text-decoration: line-through;
  color: var(--color-muted-fg);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
}

.dot-in {
  background: var(--chart-income);
}

.dot-out {
  background: var(--chart-expense);
}

.latest-main {
  flex: 1;
  min-width: 0;
}

.latest-title {
  font-size: 14px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.latest-meta {
  font-size: 12px;
  color: var(--color-muted-fg);
}

.latest-amount {
  font-size: 15px;
  font-weight: 600;
}

/* 建设进度 */
@media (max-width: 1180px) {
  .stats {
    grid-template-columns: repeat(2, 1fr);
  }

  .grid-2 {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .page-head h2 {
    font-size: 20px;
  }

  .stat-value {
    font-size: 24px;
  }
}

@media (max-width: 375px) {
  .stats {
    grid-template-columns: 1fr;
  }
}
</style>
