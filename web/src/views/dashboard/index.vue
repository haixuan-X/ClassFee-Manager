<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'
import {
  fetchCategoryPie,
  fetchStudentDashboard,
  fetchSummary,
  fetchTrend,
} from '@/api/dashboard'
import { fetchPinnedTasks } from '@/api/tasks'
import { useUserStore } from '@/stores/user'
import TrendChart from '@/components/TrendChart.vue'
import CategoryPie from '@/components/CategoryPie.vue'
import StudentTrendChart from '@/components/StudentTrendChart.vue'
import PinnedTasksPanel from '@/components/PinnedTasksPanel.vue'
import SliderTabs from '@/components/SliderTabs.vue'
import type { DashboardSummary, PieItem, StudentDashboard, Task, TrendPoint } from '@/types'
import { CHANNEL_TEXT, ROLE_TEXT } from '@/types'

const userStore = useUserStore()
const router = useRouter()

/**
 * 顶部滑动切换器：两个总览互斥。默认先看「班级账目总览」——老用户第一眼要的还是余额。
 *
 * ## 「学生情况总览」**仅院长可见**
 *
 * 非院长时整条切换器都不渲染，只剩一个总览——切换器要给两个以上选项才有意义，
 * 一个选项的切换器是纯噪音。
 *
 * ⚠ 这里**不渲染**，而不是渲染了再在加载时报 403。后端 `require_min_level`
 * 也拦了一道，两边都要：只做后端的话班主任会看到一个点进去就报「无权」的标签；
 * 只做前端的话手输接口照样拿得到数据。
 */
const isDean = computed(() => userStore.user?.role === 'DEAN')
const view = ref<'fee' | 'student'>('fee')
const VIEWS = computed(() =>
  isDean.value
    ? [
        { value: 'fee', label: '班级账目总览' },
        { value: 'student', label: '学生情况总览' },
      ]
    : [{ value: 'fee', label: '班级账目总览' }],
)

const summary = ref<DashboardSummary | null>(null)
const trend = ref<TrendPoint[]>([])
const pie = ref<PieItem[]>([])
/** 置顶任务（第二十五轮）。只含置顶且还开放着的，最多 3 条。两个总览共用。 */
const pinnedTasks = ref<Task[]>([])
/** 学生情况总览的聚合数据 */
const stu = ref<StudentDashboard | null>(null)
const loading = ref(true)
const stuLoading = ref(false)
/** 学生总览的加载失败：面板要如实说「没数据」，不能画一张空图装作正常 */
const stuError = ref('')

/**
 * 学生总览的统计卡。三张对应用户提的三个指标。
 *
 * 第三张「学籍变化」目前是**壳**：`changeTotal` 后端恒给 `null`，
 * 界面上写「暂无异动记录」而不是画一条全零折线——零会被读成「本年零异动」，
 * 那是撒谎。真接上异动表之后，这里换成真数字即可。
 */
const stuStats = computed(() => {
  const d = stu.value
  const notRegistered = d ? d.studentTotal - d.registeredTotal : 0
  return [
    {
      key: 'total',
      label: '学生数量',
      value: d ? String(d.studentTotal) : '--',
      hint: d
        ? d.canViewAll
          ? `本班全部登记学生${d.classGrade ? ` · ${d.classGrade}` : ''}`
          : '你只能看到自己有权限的那几行，不代表全班'
        : '加载中',
      tone: '' as '' | 'out',
    },
    {
      key: 'registered',
      label: '年级学籍注册人数',
      value: d ? String(d.registeredTotal) : '--',
      // ⚠ 0 人时说「全部在籍」是误导——那等于宣称「在读率 100%」，
      // 而真相是「一个人都没有」。分母为 0 时不给比例类结论。
      hint: d
        ? d.studentTotal === 0
          ? '还没有学生记录'
          : notRegistered > 0
            ? `${notRegistered} 人不在籍（休学/退学等）`
            : '全部在籍'
        : '加载中',
      tone: '' as '' | 'out',
    },
    {
      key: 'change',
      label: '学籍变化',
      // 没有数据源就明说，不给一个会被读成「零异动」的 0
      value: d ? (d.changeTotal == null ? '--' : String(d.changeTotal)) : '--',
      hint: d
        ? d.changeSupported
          ? '本学期异动人次'
          : '暂无异动记录'
        : '加载中',
      tone: '' as '' | 'out',
    },
  ]
})

/** 趋势图下方跟着当前选中的统计卡走（「点击字段显示该字段趋势」） */
const stuTrendEmpty = computed(() => {
  const d = stu.value
  if (!d) return '正在加载学生数据'
  if (!d.canViewAll) return '你只能看到自己有权限的那几行，暂无趋势'
  if (d.studentTotal === 0) return '还没有学生记录，去「学生信息」导入名单'
  return '还没有填过入校日期的记录'
})

/**
 * 空态文案按「谁看不见」分两种。
 *
 * 都写「还没有学生记录」是**误导**：普通同学看不到全班数据，
 * 「还没有」会被理解成「班里一个人都没录」，而真相是「你没权限看」。
 */
const stuEmptyText = computed(() => {
  const d = stu.value
  if (!d) return '正在加载'
  return d.canViewAll ? '还没有学生记录' : '没有你有权限查看的学生记录'
})

const regStatusTagType = (status: string | null, registered: boolean) => {
  if (!status) return 'info' as const
  return registered ? ('success' as const) : ('warning' as const)
}

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

function fmtTime(value: string | null | undefined) {
  return value ? dayjs(value).format('MM-DD HH:mm') : '—'
}

/**
 * 学生总览的数据**懒加载**：第一次切过去才拉。
 *
 * 不是为了省流量——这接口很轻——而是为了不让它拖累首屏：老用户可能整个
 * 学期都只看余额，学生总览的接口失败也不该影响他看得到账目。
 */
async function loadStudentPanel() {
  if (stu.value || stuLoading.value) return
  stuLoading.value = true
  stuError.value = ''
  try {
    stu.value = await fetchStudentDashboard()
  } catch {
    stuError.value = '学生数据加载失败，稍后再试'
  } finally {
    stuLoading.value = false
  }
}

function switchView(v: string) {
  // 双保险：切换器本来就只给院长渲染，这里再挡一次——
  // 组件有值不代表调用方就有权用（将来可能从别处调它）
  if (v === 'student' && !isDean.value) return
  view.value = v as 'fee' | 'student'
  if (v === 'student') void loadStudentPanel()
}

onMounted(async () => {
  try {
    // 置顶任务单独兜住：它挂掉不该让账目总览整块变成占位符
    const [s, t, p, pinned] = await Promise.all([
      fetchSummary(),
      fetchTrend(6),
      fetchCategoryPie(6),
      fetchPinnedTasks()
        .then((r) => r.rows)
        .catch(() => [] as Task[]),
    ])
    summary.value = s
    trend.value = t
    pie.value = p
    pinnedTasks.value = pinned
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
        <h2>{{ view === 'fee' ? '班级账目总览' : '学生情况总览' }}</h2>
        <p>
          欢迎回来，{{ userStore.displayName }} ·
          {{ userStore.user?.className ?? '未加入班级' }}
        </p>
      </div>
      <div class="head-tools">
        <span class="role-tag">{{ userStore.user ? ROLE_TEXT[userStore.user.role] : '' }}</span>
        <!-- 一个选项时切换器没有意义（纯噪音），整条不渲染 -->
        <SliderTabs
          v-if="VIEWS.length > 1"
          :model-value="view"
          :items="VIEWS"
          @update:model-value="switchView"
        />
      </div>
    </div>

    <!-- ============ 总览一：班级账目（内容与改造前完全一致） ============ -->
    <template v-if="view === 'fee'">

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

      <!-- 置顶任务（第二十五轮）。抽成组件后与「学生情况总览」共用同一份 -->
      <PinnedTasksPanel :tasks="pinnedTasks" :loading="loading" />
    </section>
    </template>

    <!--
      总览二：学生情况（第二十九轮新增，第二十九轮末收紧为**仅院长**）

      条件里除了 `view === 'student'` 还要 `isDean`：登录态可能在页面停留期间
      变掉（令牌过期后换成别人登录、被降级），此时 `view` 会停在 'student'，
      光判 view 会让一个已无权限的人继续看着管理看板。
    -->
    <template v-else-if="isDean">
      <!-- 顶部三张指标卡 -->
      <section class="stats stats-3" aria-label="学生关键指标" :aria-busy="stuLoading">
        <article
          v-for="item in stuStats"
          :key="item.key"
          class="glass-card stat"
        >
          <div class="stat-label">{{ item.label }}</div>
          <div class="stat-value num">{{ item.value }}</div>
          <div class="stat-hint">{{ item.hint }}</div>
        </article>
      </section>

      <p v-if="stuError" class="stu-error" role="alert">{{ stuError }}</p>

      <!--
        没权限看全班的同学，必须把这件事说在前面：
        「学生数量 1」不说清楚，会被读成「班里只有 1 个人」。
      -->
      <p v-else-if="stu && !stu.canViewAll" class="scope-note" role="note">
        你目前只能查看自己的学生信息，所以下面的数字<span class="nowrap">不代表全班</span>。
        需要查看全部请到「学生信息」页面申请授权。
      </p>

      <section class="grid-2">
        <article class="glass-card panel">
          <div class="panel-head">
            <h3>学籍变化趋势</h3>
            <span class="hint">按入校月份统计</span>
          </div>
          <StudentTrendChart :points="stu?.enrollTrend ?? []" :empty-text="stuTrendEmpty" />
        </article>

        <article class="glass-card panel">
          <div class="panel-head">
            <h3>注册状态分布</h3>
            <span class="hint">按人数</span>
          </div>
          <ul v-if="(stu?.statusBreakdown ?? []).length > 0" class="breakdown">
            <li v-for="s in stu?.statusBreakdown ?? []" :key="s.status">
              <span class="bd-name">{{ s.status }}</span>
              <span class="bd-bar" aria-hidden="true">
                <span
                  class="bd-fill"
                  :style="{
                    width: `${stu && stu.studentTotal ? (s.count / stu.studentTotal) * 100 : 0}%`,
                  }"
                />
              </span>
              <span class="bd-count num">{{ s.count }}</span>
            </li>
          </ul>
          <el-empty
            v-else-if="!stuLoading"
            :description="stuEmptyText"
            :image-size="72"
          />
        </article>
      </section>

      <section class="grid-2">
        <!-- 最新学籍信息 -->
        <article class="glass-card panel">
          <div class="panel-head">
            <h3>最新学籍信息</h3>
            <router-link to="/student-info" class="panel-link">查看全部</router-link>
          </div>
          <ul v-if="(stu?.latest ?? []).length > 0" class="latest">
            <li v-for="row in stu?.latest ?? []" :key="row.id">
              <div class="latest-main">
                <div class="latest-title">{{ row.name }}</div>
                <div class="latest-meta">
                  学号 {{ row.studentNo }}
                  <span v-if="row.majorName"> · {{ row.majorName }}</span>
                  <span v-if="row.enrollDate"> · 入校 {{ row.enrollDate }}</span>
                </div>
              </div>
              <el-tag
                size="small"
                effect="plain"
                :type="regStatusTagType(row.regStatus, row.registered)"
              >
                {{ row.regStatus || '未填写' }}
              </el-tag>
            </li>
          </ul>
          <el-empty
            v-else-if="!stuLoading"
            :description="stu?.canViewAll ? '还没有学生记录，去「学生信息」导入名单' : stuEmptyText"
            :image-size="72"
          />
        </article>

        <PinnedTasksPanel :tasks="pinnedTasks" :loading="loading" />
      </section>
    </template>
  </div>
</template>

<style scoped>
/* 页头右侧：角色标签 + 推拉切换器并排 */
.head-tools {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-left: auto;
}

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

/* 学生总览只有三张卡 */
.stats-3 {
  grid-template-columns: repeat(3, 1fr);
}

/* 可见范围不足时的说明。不能只靠卡片里的 hint——数字是整排并排的，
   「1」和「68」摆在一起更容易被扫读成同一个量级 */
.scope-note {
  margin: 0 0 var(--space-md);
  padding: 10px 14px;
  border-radius: var(--el-border-radius-base, 8px);
  border: 1px solid rgba(230, 162, 60, 0.4);
  background: rgba(230, 162, 60, 0.1);
  font-size: 13px;
  color: var(--color-foreground);
}

.nowrap {
  white-space: nowrap;
}

.stu-error {
  margin: 0 0 var(--space-md);
  padding: 10px 14px;
  border-radius: var(--el-border-radius-base, 8px);
  border: 1px solid var(--color-destructive-text);
  color: var(--color-destructive-text);
  font-size: 13px;
}

/* 注册状态分布：名称 / 条 / 人数三列 */
.breakdown {
  list-style: none;
  margin: 0;
  padding: 0;
}

.breakdown li {
  display: grid;
  grid-template-columns: 5.5em 1fr 3em;
  align-items: center;
  gap: 10px;
  padding: 9px 0;
  border-bottom: 1px dashed var(--color-border);
}

.breakdown li:last-child {
  border-bottom: 0;
}

.bd-name {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bd-bar {
  height: 8px;
  border-radius: 999px;
  background: var(--color-muted);
  overflow: hidden;
}

.bd-fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: var(--color-accent);
}

.bd-count {
  text-align: right;
  font-size: 14px;
  font-weight: 600;
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

/* 最新流水 */
.latest {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

/* 置顶任务。虚线分隔、字号层级都跟着 .latest 那一套走，
   免得同一片面板区里两种列表看起来像两个模块 */
.task-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.task-item {
  padding: 10px 0;
  border-bottom: 1px dashed var(--color-border);
}

.task-item:last-child {
  border-bottom: 0;
}

.task-title {
  font-size: 14px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}

.task-q {
  margin: 4px 0 0;
  font-size: 13px;
}

.task-meta {
  margin-top: 4px;
  font-size: 12px;
  color: var(--color-muted-fg);
}

/* 「我还欠着」的入口。做成按钮而不是纯文字：置顶的全部意义就是催人交，
   这一行是面板里唯一可点的东西，值得有个可点的样子 */
.task-act {
  margin-top: 8px;
}

.task-jump {
  border: 0;
  background: none;
  padding: 0;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-accent-text);
}

.task-jump:hover {
  text-decoration: underline;
}

.task-mine {
  margin-top: 6px;
  font-size: 12px;
  color: var(--color-muted-fg);
}

/* 「N 道待填」：唯一需要强调的一行，所以给它颜色；
   淡到不刺眼，和「缴费完成率」那类提示区分得开 */
.hint.pending {
  color: var(--color-expense);
  font-weight: 600;
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

  .stats-3 {
    grid-template-columns: repeat(3, 1fr);
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

  .stats-3 {
    grid-template-columns: 1fr;
  }
}
</style>
