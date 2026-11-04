<script setup lang="ts">
/**
 * 任务总览（第三十二轮）。
 *
 * 放在「学院 › 任务」下面——回答的是「现在什么状况」，而不是「有哪些任务」：
 * 多少条、还开着几条、回收率多少、哪个班交得最齐、谁发的。
 *
 * ## 统计范围
 *
 * 只有**院长**能看这一页（侧栏、路由、后端三道门都堵着），
 * 所以统计范围是**全校**。
 *
 * ## 样式
 *
 * 卡片、表格、进度条都跟「学院任务」页**同一套写法**
 * （`.glass-card` + `.roster` 表 + `el-progress`）——
 * 这一页和那一页是同一个模块的两个入口，长得不一样会让人以为是两个系统。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { exportTaskDetail, exportTaskOverview, fetchTaskOverview } from '@/api/tasks'
import { fetchCollegeFields } from '@/api/college'
import { getErrorMessage } from '@/api/request'
import { useUserStore } from '@/stores/user'
import { progressUnit } from '@/utils/taskStatus'
import type { CollegeClassChoice, Task, TaskOverviewPayload } from '@/types'

const userStore = useUserStore()

/** 筛选班级（第六十轮）：只给院长，看他关心的那个班。全部班级 = null */
const classFilter = ref<number | null>(null)
const allClasses = ref<CollegeClassChoice[]>([])

async function loadClasses() {
  try {
    const f = await fetchCollegeFields()
    allClasses.value = f.classes
  } catch {
    // 下拉空着也不影响看全院数据，不弹错误
    allClasses.value = []
  }
}

/**
 * 纯院长（第三十轮）：只管学院，不参与班级事务——
 * 他不是任何任务的应答对象，所以「去班级任务里填」这个入口对他是死路。
 */
const isPureDean = computed(
  () => userStore.user?.role === 'DEAN' && userStore.user.deanOnly === true,
)

const loading = ref(true)
const error = ref('')
const data = ref<TaskOverviewPayload | null>(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await fetchTaskOverview(classFilter.value)
  } catch (e) {
    data.value = null
    error.value = getErrorMessage(e, '任务统计加载失败')
  } finally {
    loading.value = false
  }
}

/** 回收率：已答 / 应答对象。分母为 0 时显示「—」（不假装是 0%） */
function rateText(rate: number | null | undefined): string {
  return rate === null || rate === undefined ? '—' : `${rate}%`
}

/** 进度条百分比（0-100）。分母为 0 时给 0——没有应答对象时「100%」是假的 */
function ratePercent(rate: number | null | undefined): number {
  if (rate === null || rate === undefined) return 0
  return Math.max(0, Math.min(100, rate))
}

const cards = computed(() => {
  const d = data.value
  if (!d) return []
  return [
    { key: 'total', label: '任务总数', value: String(d.total), hint: `其中 ${d.classTasks} 条班级任务` },
    { key: 'open', label: '还在收答案', value: String(d.open), hint: d.closed ? `${d.closed} 条已关闭` : '没有已关闭的' },
    // 两种任务的单位不同（人 / 班），**不能合成一个数**——分开两张卡，
    // 否则「已答 15 / 应答 22」谁也说不清 22 是人还是班。
    {
      key: 'collegeRate',
      label: '学院任务回收率',
      value: rateText(d.collegeRate),
      hint: `已填 ${d.collegeAnswered} / 共 ${d.collegeBase} 个班`,
    },
    {
      key: 'classRate',
      label: '班级任务回收率',
      value: rateText(d.classRate),
      hint: `已答 ${d.classAnswered} / 共 ${d.classBase} 人`,
    },
    { key: 'college', label: '学院任务', value: String(d.collegeTasks), hint: '院长发到全学院的' },
  ]
})

const byClass = computed(() => data.value?.byClass ?? [])
const byPublisher = computed(() => data.value?.byPublisher ?? [])
const recent = computed<Task[]>(() => data.value?.recent ?? [])

function fmtTime(value: string | null | undefined): string {
  return value ? value.slice(0, 16) : '—'
}

/** 一条任务是学院任务还是班级任务 */
function scopeText(t: Task): string {
  return t.scope === 'COLLEGE' ? '学院任务' : t.className || '班级任务'
}

/** 导出这一条任务的全部回答（谁填了什么、谁还没填） */
async function onExport(t: Task) {
  try {
    await exportTaskDetail(t.id)
    ElMessage.success('已导出')
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '导出失败'))
  }
}

/** 导出整个任务总览（所有任务一览 + 回收情况） */
const exporting = ref(false)
async function onExportOverview() {
  exporting.value = true
  try {
    await exportTaskOverview(classFilter.value)
    ElMessage.success('已导出任务总览')
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '导出失败'))
  } finally {
    exporting.value = false
  }
}

onMounted(async () => {
  // 班级下拉不依赖主数据；先拿到它就能筛，但**不阻塞**主加载
  void loadClasses()
  await load()
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>任务总览</h2>
        <p>
          现在任务是什么状况：多少条、还开着几条、回收了多少。统计范围可在这里按班级切换。
          <router-link v-if="!isPureDean" to="/tasks" class="link">去班级任务里填 →</router-link>
        </p>
      </div>
      <div style="display: flex; gap: 8px">
        <el-select
          v-model="classFilter"
          placeholder="全部班级（全学院）"
          clearable
          style="width: 180px"
          aria-label="按班级筛选"
          @change="load"
        >
          <el-option
            v-for="c in allClasses"
            :key="c.id"
            :label="(c.grade ? c.grade + ' · ' : '') + c.className"
            :value="c.id"
          />
        </el-select>
        <el-button :loading="exporting" @click="onExportOverview">导出总览</el-button>
        <el-button @click="load">刷新</el-button>
      </div>
    </div>

    <p v-if="error" class="glass-card error-note" role="alert">{{ error }}</p>

    <div v-loading="loading" class="cards">
      <article v-for="c in cards" :key="c.key" class="glass-card card">
        <div class="card-label">{{ c.label }}</div>
        <div class="card-value">{{ c.value }}</div>
        <div class="card-hint">{{ c.hint }}</div>
      </article>
    </div>

    <section
      v-if="data && (data.classBase > 0 || data.collegeBase > 0)"
      class="glass-card rate-card"
    >
      <!-- 两种任务的应答对象不是同一个单位：班级任务数**人**、学院任务数**班**。
           合成一个「总体回收率」会得到一个单位不明的数，所以这里并列两条。 -->
      <div class="rate-head">
        <span>回收率</span>
      </div>

      <div class="rate-row">
        <div class="rate-row-head">
          <span><strong>班级任务</strong>（按人）</span>
          <strong class="num">{{ rateText(data.classRate) }}</strong>
        </div>
        <el-progress
          :percentage="ratePercent(data.classRate)"
          :stroke-width="8"
          :show-text="false"
          color="var(--color-accent-text)"
          aria-hidden="true"
        />
        <p class="filter-hint">
          已答 {{ data.classAnswered }} 份，应答对象共 {{ data.classBase }} 人。
          <strong>班级任务</strong>由本班同学应答；班主任及以上不算，发布人自己也不算。
        </p>
      </div>

      <div class="rate-row">
        <div class="rate-row-head">
          <span><strong>学院任务</strong>（按班）</span>
          <strong class="num">{{ rateText(data.collegeRate) }}</strong>
        </div>
        <el-progress
          :percentage="ratePercent(data.collegeRate)"
          :stroke-width="8"
          :show-text="false"
          color="var(--color-accent-text)"
          aria-hidden="true"
        />
        <p class="filter-hint">
          已填 {{ data.collegeAnswered }} 个班，<strong>学院任务</strong>由各班班主任应答：
          分母是<strong>班主任名册</strong>里已登记班主任的班（一班一个名额，兼班主任的院长也算），
          班里学生<strong>全部点完名</strong>才算已填。
        </p>
      </div>
    </section>

    <section class="glass-card" aria-label="各班情况">
      <div class="table-wrap">
        <table class="roster">
          <thead>
            <tr>
              <th scope="col">班级</th>
              <th scope="col">任务数</th>
              <th scope="col">开放中</th>
              <th scope="col">回收进度</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in byClass" :key="c.classId">
              <td>{{ c.className || '未分班' }}</td>
              <td class="num">{{ c.total }}</td>
              <td class="num">{{ c.open }}</td>
              <td class="progress-cell">
                <el-progress
                  :percentage="ratePercent(c.rate)"
                  :stroke-width="8"
                  :show-text="false"
                  color="var(--color-accent-text)"
                  aria-hidden="true"
                />
                <span class="progress-text num">
                  已答 {{ c.answered }} / 共 {{ c.base }} {{ progressUnit(c.scope) }}
                </span>
              </td>
            </tr>
            <tr v-if="byClass.length === 0">
              <td colspan="4" class="empty">还没有任务</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="glass-card" aria-label="谁发布的">
      <div class="table-wrap">
        <table class="roster">
          <thead>
            <tr>
              <th scope="col">发布人</th>
              <th scope="col">任务数</th>
              <th scope="col">开放中</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in byPublisher" :key="p.userId">
              <td>{{ p.name }}</td>
              <td class="num">{{ p.total }}</td>
              <td class="num">{{ p.open }}</td>
            </tr>
            <tr v-if="byPublisher.length === 0">
              <td colspan="3" class="empty">还没有任务</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="glass-card" aria-label="最近的任务">
      <div class="table-wrap">
        <table class="roster">
          <thead>
            <tr>
              <th scope="col">标题</th>
              <th scope="col">范围</th>
              <th scope="col">回收进度</th>
              <th scope="col">状态</th>
              <th scope="col">发布时间</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in recent" :key="t.id">
              <td>
                {{ t.title }}
                <el-tag v-if="t.pinned" size="small" type="warning" effect="plain">置顶</el-tag>
              </td>
              <td>{{ scopeText(t) }}</td>
              <td class="progress-cell">
                <el-progress
                  :percentage="ratePercent(
                    t.summary.total > 0
                      ? Math.round((t.summary.answered / t.summary.total) * 100)
                      : 0,
                  )"
                  :stroke-width="8"
                  :show-text="false"
                  color="var(--color-accent-text)"
                  aria-hidden="true"
                />
                <span class="progress-text num">
                  已答 {{ t.summary.answered }} / 共 {{ t.summary.total }}
                  {{ progressUnit(t.scope) }}
                </span>
              </td>
              <td>
                <el-tag size="small" effect="plain" :type="t.open ? 'success' : 'info'">
                  {{ t.open ? '开放中' : '已关闭' }}
                </el-tag>
              </td>
              <td class="num">{{ fmtTime(t.createdAt) }}</td>
              <td>
                <el-button
                  v-if="t.canSeeDetail"
                  size="small"
                  link
                  type="primary"
                  @click="onExport(t)"
                >
                  导出
                </el-button>
                <span v-else style="color: var(--color-muted-fg)">—</span>
              </td>
            </tr>
            <tr v-if="recent.length === 0">
              <td colspan="6" class="empty">还没有任务</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
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
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.link {
  color: var(--el-color-primary);
}

.error-note {
  margin: 0;
  padding: 12px 14px;
  font-size: 13px;
  color: var(--color-destructive-text);
}

/* 统计卡片：和「学院任务」页的卡片一样是 var(--space-md) 内边距 */
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--space-md);
}

.card {
  padding: var(--space-md);
}

.card-label {
  font-size: 13px;
  color: var(--color-muted-fg);
}

.card-value {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.3;
}

.card-hint {
  font-size: 12px;
  color: var(--color-muted-fg);
}

.rate-card {
  padding: var(--space-md);
}

.rate-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 8px;
}

.rate-head strong {
  font-size: 18px;
}

/* 两条回收率并列（单位不同，不能合成一个数） */
.rate-row + .rate-row {
  margin-top: var(--space-md);
  padding-top: var(--space-md);
  border-top: 1px solid var(--color-border);
}

.rate-row-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
  font-size: 13px;
}

.rate-row-head .num {
  font-size: 16px;
}

.filter-hint {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--color-muted-fg);
}

/* 表格：与「学院任务」页同一套 */
.table-wrap {
  overflow-x: auto;
}

.roster {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.roster th,
.roster td {
  padding: 9px 12px;
  border-bottom: 1px solid var(--color-border);
  text-align: left;
  vertical-align: top;
}

.roster thead th {
  background: var(--color-surface, #fff);
  font-weight: 600;
  color: var(--color-foreground);
  white-space: nowrap;
}

.progress-cell {
  min-width: 160px;
}

.progress-text {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: var(--color-muted-fg);
}

.empty {
  color: var(--color-muted-fg);
  text-align: center;
  padding: 18px 12px;
}
</style>
