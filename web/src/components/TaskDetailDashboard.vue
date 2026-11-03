<script setup lang="ts">
/**
 * 学院任务的「返校情况」仪表盘（第四十八轮）。
 *
 * 院长在「学院任务」列表点 **详情** 打开：
 *
 * - **上面一排大数字**：学校总人数 / 已返校 / 未返校 / 请假（认不出的状态再多一张）
 * - **中间一条状态图例**：每个状态实际多少人、各归到哪个桶——归类是关键词猜的，
 *   必须让院长**看得见**它把谁算了未返校，否则那个数字没法信
 * - **下面按班**：每班一行，列出**没返校的学生**和他们的**补充说明**（备注），
 *   有请假的也单列一份，认得清「没到校但请假了」和「无故没到」
 *
 * ## 数据从哪来
 *
 * 复用 `GET /tasks/{id}/detail`（后端 `_college_detail`），一行 = 一个学生，
 * 带 `value`（状态原文）和 `note`（补充说明）。**后端不用改**——
 * 这里要的数字全是从学生行现算的，算的口径在 `utils/taskStatus.ts`。
 *
 * ## 和「回答明细」的关系
 *
 * 那个（`views/tasks/index.vue`）是**全量表**：每班一张表，把所有人都列出来，
 * 用来逐行核对。这个是**仪表盘**：只突出没返校的那几个，给院长一眼看全局。
 * 两者读同一份 `/detail`，所以数字对得上，不会一个说 4 个一个说 5 个。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getErrorMessage } from '@/api/request'
import { exportTaskDetail, fetchTaskDetail } from '@/api/tasks'
import { useModal } from '@/composables/useModal'
import { BUCKET_META, classifyStatus, statusLabel, type ReturnBucket } from '@/utils/taskStatus'
import type { TaskDetail, TaskDetailClass, TaskDetailStudentRow } from '@/types'

const props = defineProps<{ taskId: number | null }>()
const visible = defineModel<boolean>({ required: true })

const loading = ref(true)
const loadError = ref('')
const detail = ref<TaskDetail | null>(null)

const { restoreFocus } = useModal(visible)

/* ==================== 分组口径（第六十四轮） ====================
 *
 * 这个看板原来只服务「返校统计」：所有答案都往固定四个桶
 * （已返校 / 未返校 / 请假 / 其它）里塞。
 *
 * 单选题的答案是**发布人自定义的选项**，套那四个桶是错的——用户实测：
 * 「单选测试」的详情里显示成「未返校 9 人」，跟选项毫无关系。
 *
 * 现在按题型分流，两套口径共用同一份「筛选 / 班级过滤 / 导出」逻辑：
 * - 是/否、日期 → 返校桶（原样保留，返校统计是它的主场）
 * - 单选、多选 → 按**选项**分组（选项原文 + 「未填」）
 */

/** 「未填」的分组键。用哨兵而不是中文，免得和用户自己起的选项名撞车 */
const UNFILLED = '__unfilled__'

/** 当前任务按**选项**展示（单选/多选），还是按**返校桶**（是/否、日期） */
const optionMode = computed(() => {
  const q = detail.value?.qtype
  return q === 'SINGLE' || q === 'MULTI'
})

/** 一个答案归到哪一组 */
function groupKeyOf(value: string | null | undefined): string {
  if (optionMode.value) return (value ?? '').trim() || UNFILLED
  return classifyStatus(value ?? null)
}

/** 组的显示名 */
function groupLabel(key: string): string {
  if (optionMode.value) return key === UNFILLED ? '未填' : key
  return BUCKET_META[key as ReturnBucket].label
}

/** 组的色调（拼成 `tone-xxx`） */
function groupTone(key: string): string {
  if (optionMode.value) return key === UNFILLED ? 'muted' : 'opt'
  return BUCKET_META[key as ReturnBucket].tone
}

/** 一行学生的状态标签文字（选项模式 = 选项原文；返校模式 = 归类后的标准名） */
function rowLabel(value: string | null | undefined): string {
  return optionMode.value
    ? (value ?? '').trim() || '未填'
    : statusLabel(value ?? null)
}

/**
 * 一个班分组后的样子：`byKey` = 分组键 → 该组的学生行。
 *
 * 不再写死 returned/absent/excused/other 四个字段——组是动态的
 * （选项模式最多 4 个选项 + 未填），写死字段就只能在两种模式里二选一。
 * `cls.rows` 后端已按学号排过，分组只做 filter，保序。
 */
interface ClassView {
  cls: TaskDetailClass
  byKey: Map<string, TaskDetailStudentRow[]>
}

function toClassView(cls: TaskDetailClass): ClassView {
  const byKey = new Map<string, TaskDetailStudentRow[]>()
  for (const r of cls.rows) {
    const k = groupKeyOf(r.value)
    const arr = byKey.get(k)
    if (arr) arr.push(r)
    else byKey.set(k, [r])
  }
  return { cls, byKey }
}

/** 未填/未返校多的班排前面——院长先看最需要催的那个班 */
const classViews = computed<ClassView[]>(() =>
  (detail.value?.classes ?? [])
    .map(toClassView)
    .sort((a, b) => {
      const key = optionMode.value ? UNFILLED : 'absent'
      const na = a.byKey.get(key)?.length ?? 0
      const nb = b.byKey.get(key)?.length ?? 0
      return nb - na || a.cls.className.localeCompare(b.cls.className)
    }),
)

/** 班级筛选范围内的全部学生行——图例、卡片、名单都从这一份算，口径只有一处 */
const allRows = computed<TaskDetailStudentRow[]>(() =>
  scopedViews.value.flatMap((v) => v.cls.rows),
)

const stats = computed(() => {
  const rows = allRows.value
  const count = (b: ReturnBucket) => rows.filter((r) => classifyStatus(r.value) === b).length
  return {
    total: rows.length,
    classes: classViews.value.length,
    returned: count('returned'),
    absent: count('absent'),
    excused: count('excused'),
    other: count('other'),
    /** 还没点名的（**已含在未返校里**，这里只为在卡片提示上说清楚） */
    unanswered: rows.filter((r) => !r.value?.trim()).length,
  }
})

/**
 * 选项模式的卡片（第六十四轮）：按**发布时的选项顺序**排，**含 0 人的选项**
 * （「选项C 0 人」正是发布人要看的），「未填」有才出现。
 * 库里存在但已不在选项表里的旧答案追加在最后，不静默丢掉。
 */
const optionCards = computed<{ key: string; label: string; count: number }[]>(() => {
  const counts = new Map<string, number>()
  for (const r of allRows.value) {
    const k = groupKeyOf(r.value)
    counts.set(k, (counts.get(k) ?? 0) + 1)
  }
  const opts = detail.value?.options ?? []
  const out = opts.map((o) => ({ key: o, label: o, count: counts.get(o) ?? 0 }))
  for (const [k, n] of counts) {
    if (k === UNFILLED || opts.includes(k)) continue
    out.push({ key: k, label: k, count: n })
  }
  const unfilled = counts.get(UNFILLED) ?? 0
  if (unfilled > 0) out.push({ key: UNFILLED, label: '未填', count: unfilled })
  return out
})

/* ==================== 筛选 + 导出（第四十九轮） ====================
 *
 * 顶部那排卡片**同时是筛选器**：点「未返校」下面只列未返校的学生，
 * 再点一次复位（点「学校总人数」= 回到全部）。底部的导出按钮跟着筛选走——
 * 点着已返校导出的文件里就只有已返校的人。
 *
 * 为什么导出传 **recordIds** 而不是「状态=未返校」：
 * 「哪些值算未返校」的关键词表只在 `utils/taskStatus.ts` 一份。
 * 若后端也判一遍，改了关键词忘了改后端就会出现「屏幕 6 人、文件 8 人」。
 * 传 id 列表 = 文件内容就是屏幕上那些行，结构上不可能对不上。
 */

/**
 * 当前筛选。`null` = 全部（不筛）。
 *
 * 存**分组键**（字符串）而不是 `ReturnBucket`：选项模式下键就是选项原文，
 * 两套口径共用一个筛选变量，模板不用分叉。
 */
const filter = ref<string | null>(null)

function toggleFilter(key: string): void {
  filter.value = filter.value === key ? null : key
}

/* ==================== 按班级筛选（第五十四轮） ====================
 *
 * 用户口径：名单一长就得一屏一屏往下翻。点左边的「班级」按钮弹出班级框，
 * 选中哪个班，下面（和上方四张卡片）就只算那个班；再点同一个班 = 复位。
 *
 * 两个筛选**正交**：班级筛选（看哪个班）× 状态筛选（看哪一栏）。
 * 导出跟着两者一起走——文件里的行就是屏幕上那些行。
 */

const classFilter = ref<number | null>(null)
const classPickerOpen = ref(false)

/** 班级框里的选项：全部 + 每个班（带人数） */
const classChoices = computed(() =>
  classViews.value.map((v) => ({
    id: v.cls.classId,
    name: v.cls.className,
    total: v.cls.total,
  })),
)

function pickClass(id: number | null): void {
  // 再点一次同一个班 = 取消筛选（和顶部卡片同一套「再点一次复位」的约定）
  classFilter.value = classFilter.value === id ? null : id
  classPickerOpen.value = false
}

const classFilterName = computed(
  () => classChoices.value.find((c) => c.id === classFilter.value)?.name ?? '',
)

/** 班级筛选之后的班（状态筛选不在这里做，交给 `visibleViews`） */
const scopedViews = computed<ClassView[]>(() =>
  classFilter.value === null
    ? classViews.value
    : classViews.value.filter((v) => v.cls.classId === classFilter.value),
)

/** 当前筛选命中的学生行（不筛时 = 全部行）——导出的 recordIds 就从这来 */
const filteredRows = computed<TaskDetailStudentRow[]>(() => {
  const k = filter.value
  return k === null
    ? allRows.value
    : allRows.value.filter((r) => groupKeyOf(r.value) === k)
})

/**
 * 下面要展示的班：**先套班级筛选**，再按状态筛选掉「没命中学生的班」
 * （一排空表会像漏了人）。
 *
 * ⚠ 必须基于 `scopedViews` 而不是 `classViews`：上面卡片的数字走 `allRows`
 * （= `scopedViews` 摊平），这里若用 `classViews` 就会「上面只剩一个班、
 * 下面还是全列出来」——用户实测踩到的就是这个（选了机电一体化2601，
 * 下面照样列云计算/大数据）。
 */
const visibleViews = computed<ClassView[]>(() => {
  const k = filter.value
  return k === null
    ? scopedViews.value
    : scopedViews.value.filter((v) => (v.byKey.get(k)?.length ?? 0) > 0)
})

interface GroupView {
  key: string
  title: string
  tone: string
  rows: TaskDetailStudentRow[]
}

/** 一个班在当前筛选下要渲染的分组 */
function groupsOf(v: ClassView): GroupView[] {
  const k = filter.value
  if (k !== null) {
    const rows = v.byKey.get(k) ?? []
    return rows.length
      ? [{ key: k, title: `${groupLabel(k)} ${rows.length} 人`, tone: groupTone(k), rows }]
      : []
  }
  // 不筛时：
  // - 返校模式只列「未返校 / 请假 / 其它」（已返校是正常态，铺满屏反而找不到人）
  // - 选项模式**每个有人的选项都列**——这就是「按选项展示」本身
  const out: GroupView[] = []
  const keys: string[] = optionMode.value
    ? optionCards.value.map((c) => c.key)
    : ['absent', 'excused', 'other']
  for (const key of keys) {
    const rows = v.byKey.get(key) ?? []
    if (!rows.length) continue
    // 返校模式保留原本那几句更具体的说明（「不算未返校」这类提示有用）
    const title = optionMode.value
      ? `${groupLabel(key)} ${rows.length} 人`
      : key === 'absent'
        ? `未返校 ${rows.length} 人`
        : key === 'excused'
          ? `请假 ${rows.length} 人（不算未返校）`
          : `其它状态 ${rows.length} 人`
    out.push({ key, title, tone: groupTone(key), rows })
  }
  return out
}

/** 各桶对应的标签色。显式标 `Record<ReturnBucket, ...>`——
    写成对象字面量再下标取值会被拓宽成 `string`，过不了 el-tag 的类型 */
const TAG_TYPES: Record<ReturnBucket, 'success' | 'danger' | 'warning' | 'info'> = {
  returned: 'success',
  absent: 'danger',
  excused: 'warning',
  other: 'info',
}

/** 行上状态标签的颜色：选项模式只区分「填了/没填」，返校模式按桶上色 */
function tagType(
  key: string,
  value: string | null | undefined,
): 'primary' | 'success' | 'danger' | 'warning' | 'info' {
  if (optionMode.value) return key === UNFILLED ? 'info' : 'primary'
  if (!value?.trim()) return 'info'
  return TAG_TYPES[key as ReturnBucket]
}

/* ------------------------- 导出 ------------------------- */

const exporting = ref(false)

/** 按钮文案带上**当前导出的是谁、多少人**——点了才知道会得到什么文件 */
const exportLabel = computed(() => {
  const k = filter.value
  return k === null
    ? `导出全部（${filteredRows.value.length} 人）`
    : `导出（${groupLabel(k)} ${filteredRows.value.length} 人）`
})

async function onExport(): Promise<void> {
  if (props.taskId === null || exporting.value) return
  const k = filter.value
  const rows = filteredRows.value
  // 一个都没筛中就别发请求：后端会 400，按钮此时也是 disabled，这里是双保险
  if (k !== null && !rows.length) return
  exporting.value = true
  try {
    await exportTaskDetail(
      props.taskId,
      k === null
        ? undefined
        : { recordIds: rows.map((r) => r.recordId), label: groupLabel(k) },
    )
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '导出失败'))
  } finally {
    exporting.value = false
  }
}

/**
 * 状态图例：每个状态实际多少人、归到哪个桶。
 *
 * 归类靠关键词，认不出的会落进「其它状态」。这张表就是**对账用的**——
 * 院长扫一眼就知道「哦，我填的『未到校』被算进未返校了」，数字才可信。
 *
 * 选项模式不需要它：答案是发布人自己定的选项，卡片上就是分布，
 * 不存在「被归到别的桶」这回事。
 */
const legend = computed(() => {
  if (optionMode.value) return []
  const map = new Map<string, { label: string; count: number; bucket: ReturnBucket }>()
  for (const r of allRows.value) {
    const label = statusLabel(r.value)
    const bucket = classifyStatus(r.value)
    // 同一个状态文字（含「未填」）只算一条
    const hit = map.get(label)
    if (hit) hit.count += 1
    else map.set(label, { label, count: 1, bucket })
  }
  return [...map.values()].sort((a, b) => b.count - a.count)
})

/** 百分比。分母为 0（空任务）不除零 */
function pct(n: number, d: number = stats.value.total): string {
  if (!d) return '—'
  return `${((n / d) * 100).toFixed(1)}%`
}

/** 每次打开都重新拉，不然上一条任务的数字会留在屏幕上 */
watch(visible, (open) => {
  if (!open) return
  load()
})

async function load() {
  if (props.taskId === null) return
  loading.value = true
  loadError.value = ''
  detail.value = null
  filter.value = null // 换一条任务就回到「全部」，不把上一条的筛选带到这条来
  try {
    detail.value = await fetchTaskDetail(props.taskId)
  } catch (e) {
    // 没权限（403）也走这里：班主任点不进详情，按钮本来就按 canSeeDetail 隐藏，
    // 这里是兜底，提示得说人话
    loadError.value = getErrorMessage(e, '打不开详情')
    ElMessage.error(loadError.value)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="
      detail
        ? `${optionMode ? '答题情况' : '返校情况'} · ${detail.title}`
        : optionMode
          ? '答题情况'
          : '返校情况'
    "
    width="940px"
    class="dash-dialog"
    @closed="restoreFocus"
  >
    <div v-loading="loading" class="dash">
      <el-alert
        v-if="loadError"
        type="error"
        :title="loadError"
        show-icon
        :closable="false"
        class="err"
      />

      <template v-if="detail && !loadError">
        <p class="head-q">
          {{ detail.question }}
          <span class="qtype">{{ detail.qtypeText }}</span>
        </p>
        <p class="head-meta muted">
          共 {{ stats.classes }} 个班
          <template v-if="detail.allowText"> · 含补充说明</template>
          <template v-if="detail.deadline"> · 截止 {{ detail.deadline }}</template>
          <template v-if="!detail.open"> · 任务已关闭</template>
        </p>

        <!-- ============================ 顶部大数字 = 筛选 tab ============================
             点一张卡 = 下面只看那一栏，再点一次复位；点第一张卡 = 回到全部。
             用真 <button>：可 Tab、可回车、有 aria-pressed，读屏也说得清「筛选中」。

             第六十四轮按题型分叉：是/否、日期走「返校」四桶（原样保留）；
             单选/多选的答案是发布人自定义的选项，卡片就按选项列（含 0 人的）。 -->
        <div v-if="!optionMode" class="cards" role="group" aria-label="按状态筛选">
          <button
            type="button"
            class="card tone-total"
            :class="{ on: !filter }"
            :aria-pressed="filter === null"
            title="看全部学生"
            @click="filter = null"
          >
            <div class="card-label">学校总人数</div>
            <div class="card-value num">{{ stats.total }}</div>
            <div class="card-hint">{{ stats.classes }} 个班</div>
          </button>

          <button
            type="button"
            class="card tone-ok"
            :class="{ on: filter === 'returned' }"
            :aria-pressed="filter === 'returned'"
            title="只看已返校的学生"
            @click="toggleFilter('returned')"
          >
            <div class="card-label">已返校</div>
            <div class="card-value num">{{ stats.returned }}</div>
            <div class="card-hint">占 {{ pct(stats.returned) }}</div>
          </button>

          <button
            type="button"
            class="card tone-bad"
            :class="{ on: filter === 'absent' }"
            :aria-pressed="filter === 'absent'"
            title="只看未返校的学生（含还没点名的）"
            @click="toggleFilter('absent')"
          >
            <div class="card-label">未返校</div>
            <div class="card-value num">{{ stats.absent }}</div>
            <div class="card-hint">
              {{ stats.unanswered ? `含 ${stats.unanswered} 人还没点名` : '已全部点名' }}
            </div>
          </button>

          <button
            type="button"
            class="card tone-warn"
            :class="{ on: filter === 'excused' }"
            :aria-pressed="filter === 'excused'"
            title="只看请假的学生"
            @click="toggleFilter('excused')"
          >
            <div class="card-label">请假</div>
            <div class="card-value num">{{ stats.excused }}</div>
            <div class="card-hint">{{ stats.excused ? '没到校，不算未返校' : '无' }}</div>
          </button>

          <!-- 认不出的状态**单列**，不塞进上面任何一栏（见 taskStatus.ts 的说明） -->
          <button
            v-if="stats.other"
            type="button"
            class="card tone-muted"
            :class="{ on: filter === 'other' }"
            :aria-pressed="filter === 'other'"
            title="只看归类认不出的状态"
            @click="toggleFilter('other')"
          >
            <div class="card-label">其它状态</div>
            <div class="card-value num">{{ stats.other }}</div>
            <div class="card-hint">归类认不出，见下方图例</div>
          </button>
        </div>

        <!-- 选项模式：一个选项一张卡（含 0 人的），点开只看选了它的人 -->
        <div v-else class="cards" role="group" aria-label="按选项筛选">
          <button
            type="button"
            class="card tone-total"
            :class="{ on: !filter }"
            :aria-pressed="filter === null"
            title="看全部学生"
            @click="filter = null"
          >
            <div class="card-label">全部学生</div>
            <div class="card-value num">{{ stats.total }}</div>
            <div class="card-hint">{{ stats.classes }} 个班</div>
          </button>

          <button
            v-for="c in optionCards"
            :key="c.key"
            type="button"
            class="card"
            :class="[`tone-${c.key === UNFILLED ? 'muted' : 'opt'}`, { on: filter === c.key }]"
            :aria-pressed="filter === c.key"
            :title="`只看「${c.label}」的学生`"
            @click="toggleFilter(c.key)"
          >
            <div class="card-label">{{ c.label }}</div>
            <div class="card-value num">{{ c.count }}</div>
            <div class="card-hint">占 {{ pct(c.count) }}</div>
          </button>
        </div>

        <!-- 状态图例：把「哪个状态算哪一栏」摊开给人看（选项模式不需要） -->
        <p v-if="!optionMode" class="legend">
          <span
            v-for="l in legend"
            :key="l.label"
            class="legend-chip"
            :class="`tone-${BUCKET_META[l.bucket].tone}`"
          >
            {{ l.label }}<b class="num">{{ l.count }}</b>
            <i>{{ BUCKET_META[l.bucket].label }}</i>
          </span>
          <span class="legend-note muted">「未填」也计入未返校；底色对应上方卡片。</span>
        </p>

        <!-- ============================ 每班名单 ============================ -->
        <!-- 标题跟着筛选走：筛着「未返校」时标题还写「各班未返校情况」是对的，
             但筛「已返校」就必须改口，否则文件名和屏幕各说各话 -->
        <div class="sec-head">
          <div class="sec-head-left">
            <!-- 班级筛选：点一下弹出班级框，选中哪个班下面就只列那个班（再点一次复位） -->
            <el-popover
              v-model:visible="classPickerOpen"
              placement="bottom-start"
              :width="240"
              trigger="click"
            >
              <template #reference>
                <el-button :type="classFilter === null ? 'default' : 'primary'">
                  {{ classFilter === null ? '按班级筛选' : `班级：${classFilterName}` }}
                </el-button>
              </template>
              <div class="cls-picker" role="listbox" aria-label="按班级筛选">
                <button
                  type="button"
                  class="cls-opt"
                  :class="{ on: classFilter === null }"
                  :aria-selected="classFilter === null"
                  @click="pickClass(null)"
                >
                  全部班级<b class="num">{{ classChoices.length }}</b>
                </button>
                <button
                  v-for="c in classChoices"
                  :key="c.id"
                  type="button"
                  class="cls-opt"
                  :class="{ on: classFilter === c.id }"
                  :aria-selected="classFilter === c.id"
                  @click="pickClass(c.id)"
                >
                  {{ c.name }}<b class="num">{{ c.total }}</b>
                </button>
              </div>
            </el-popover>

            <h4 class="sec-title">
              {{
                filter
                  ? `${groupLabel(filter)} · 各班名单`
                  : optionMode
                    ? '各选项分布 · 按班'
                    : '各班未返校情况'
              }}
            </h4>
          </div>

          <!-- 导出放在标题行右侧（用户口径：名单太长还得翻到底部才能导，太麻烦）。
               跟着**班级筛选 + 状态筛选**一起走；筛出 0 人时禁用，别让人吃 400。 -->
          <el-button
            type="primary"
            :loading="exporting"
            :disabled="filter !== null && !filteredRows.length"
            @click="onExport"
          >
            {{ exportLabel }}
          </el-button>
        </div>

        <p v-if="!visibleViews.length" class="all-good">
          ✓ 没有{{ filter ? groupLabel(filter) : '' }}的学生
        </p>

        <section
          v-for="v in visibleViews"
          :key="v.cls.classId"
          class="glass-card cls-card"
        >
          <header class="cls-head">
            <div class="cls-title">
              <strong class="cls-name">{{ v.cls.className }}</strong>
              <span v-if="v.cls.teachers.length" class="muted cls-teacher">
                班主任 {{ v.cls.teachers.join('、') }}
              </span>
            </div>
            <div class="badges">
              <template v-if="optionMode">
                <el-tag type="success" size="small">已填 {{ v.cls.answered }}</el-tag>
                <el-tag
                  v-if="v.cls.total > v.cls.answered"
                  type="info"
                  size="small"
                >
                  未填 {{ v.cls.total - v.cls.answered }}
                </el-tag>
              </template>
              <template v-else>
                <el-tag
                  :type="(v.byKey.get('absent')?.length ?? 0) ? 'danger' : 'success'"
                  size="small"
                >
                  未返校 {{ v.byKey.get('absent')?.length ?? 0 }}
                </el-tag>
                <el-tag v-if="v.byKey.get('excused')?.length" type="warning" size="small">
                  请假 {{ v.byKey.get('excused')?.length }}
                </el-tag>
                <el-tag type="success" size="small">
                  已返校 {{ v.byKey.get('returned')?.length ?? 0 }}
                </el-tag>
              </template>
            </div>
          </header>

          <p class="cls-stat muted">
            共 {{ v.cls.total }} 人 · 已点名 {{ v.cls.answered }} 人 ·
            {{ optionMode ? '填写率' : '返校率' }}
            {{
              pct(
                optionMode ? v.cls.answered : (v.byKey.get('returned')?.length ?? 0),
                v.cls.total,
              )
            }}
          </p>

          <p v-if="!groupsOf(v).length" class="all-good">
            ✓
            {{
              optionMode
                ? '全班都还没填'
                : '全班已到齐，没有未返校和请假的学生'
            }}
          </p>

          <template v-else>
            <template v-for="g in groupsOf(v)" :key="g.key">
              <h5 class="grp" :class="`tone-${g.tone}`">{{ g.title }}</h5>
              <ul class="stu-list">
                <li v-for="s in g.rows" :key="s.recordId" class="stu">
                  <span class="stu-name">{{ s.name }}</span>
                  <span class="stu-no num">{{ s.studentNo }}</span>
                  <!-- 没点名的（info）和「确认没到」（danger）要分得开：
                       前者可能只是班主任还没轮到，不该被当成已确认缺席 -->
                  <el-tag size="small" :type="tagType(g.key, s.value)">
                    {{ rowLabel(s.value) }}
                  </el-tag>
                  <span
                    v-if="detail.allowText"
                    class="stu-note"
                    :class="{ empty: !s.note }"
                  >
                    备注：{{ s.note || '—' }}
                  </span>
                </li>
              </ul>
            </template>
          </template>
        </section>
      </template>
    </div>

    <!-- 底部不再放按钮：导出挪到名单标题那一行（数据一长就得翻到底部才能导，太麻烦），
         关闭用弹窗右上角的 × 就够了。 -->
  </el-dialog>
</template>

<style scoped>
/* 四个桶的色基调。⚠ 文字一律用「暗一档」的值：亮色（#f59e0b / #ef4444）
   对白底只有 2~3:1，达不到 §8 的 4.5:1。同 tokens.css 里 accent 的处理。 */
.dash {
  --tone-ok: #166534;
  --tone-ok-bg: #ecfdf5;
  --tone-bad: #b91c1c;
  --tone-bad-bg: #fef2f2;
  --tone-warn: #b45309;
  --tone-warn-bg: #fffbeb;
  --tone-muted: #5a6779;
  --tone-muted-bg: var(--color-muted);
  --tone-total: #2563eb;
  --tone-total-bg: #eff6ff;
  /* 选项模式的「一个选项」：靛蓝，和「全部」的总人数蓝区分开 */
  --tone-opt: #4338ca;
  --tone-opt-bg: #eef2ff;
}

.dash-dialog :deep(.el-dialog) {
  /* 属性只吃纯长度，min() 放这里更稳；小屏不撑破视口 */
  width: min(940px, 96vw);
}

.dash-dialog :deep(.el-dialog__body) {
  max-height: min(74vh, 780px);
  overflow-y: auto;
  padding-top: var(--space-sm);
}

.err {
  margin-bottom: var(--space-md);
}

.muted {
  color: var(--color-muted-fg);
}

/* --------------------------- 头部 --------------------------- */

.head-q {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}

.qtype {
  margin-left: var(--space-sm);
  padding: 1px 6px;
  border-radius: var(--radius);
  background: var(--color-muted);
  color: var(--color-muted-fg);
  font-size: 12px;
  font-weight: 400;
}

.head-meta {
  margin: var(--space-xs) 0 0;
  font-size: 13px;
}

/* --------------------------- 顶部大数字 --------------------------- */

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: var(--space-md);
  margin-top: var(--space-md);
}

.card {
  padding: var(--space-md);
  border: 1px solid var(--color-border);
  border-left: 4px solid var(--t, var(--tone-total));
  border-radius: var(--radius-lg);
  background: var(--bg, var(--tone-total-bg));
  /* 卡片是 <button>（既是统计又是筛选器）：抹掉按钮默认外观，文字靠左 */
  display: block;
  width: 100%;
  margin: 0;
  font: inherit;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: box-shadow var(--duration) var(--ease);
}

.card:hover {
  box-shadow: var(--shadow-md);
}

.card:focus-visible {
  outline: 2px solid var(--color-info);
  outline-offset: 2px;
}

/* 筛选中：按各自的色调描一圈实边。选中态不能只靠底色深浅那点差别——
   色弱用户看不出 #eff6ff 和白的分别，描边是形状信息 */
.card.on {
  box-shadow: 0 0 0 2px var(--t, var(--tone-total));
}

.card-label {
  font-size: 13px;
  color: var(--color-muted-fg);
}

/* 「筛选中」写成字，不让人靠猜。总人数卡是「全部」，不标这个 */
.card:not(.tone-total).on .card-label::after {
  content: '（筛选中）';
}

.card-value {
  margin-top: var(--space-xs);
  font-size: 32px;
  font-weight: 700;
  line-height: 1.1;
  color: var(--tone-total);
}

.card-hint {
  margin-top: var(--space-xs);
  font-size: 12px;
  color: var(--color-muted-fg);
}

.tone-ok {
  --t: var(--tone-ok);
  --bg: var(--tone-ok-bg);
  border-left-color: var(--tone-ok);
  background: var(--tone-ok-bg);
}
.tone-ok .card-value { color: var(--tone-ok); }

.tone-bad {
  --t: var(--tone-bad);
  --bg: var(--tone-bad-bg);
  border-left-color: var(--tone-bad);
  background: var(--tone-bad-bg);
}
.tone-bad .card-value { color: var(--tone-bad); }

.tone-warn {
  --t: var(--tone-warn);
  --bg: var(--tone-warn-bg);
  border-left-color: var(--tone-warn);
  background: var(--tone-warn-bg);
}
.tone-warn .card-value { color: var(--tone-warn); }

.tone-muted {
  --t: var(--tone-muted);
  --bg: var(--tone-muted-bg);
  border-left-color: var(--tone-muted);
  background: var(--tone-muted-bg);
}
.tone-muted .card-value { color: var(--tone-muted); }

/* 选项模式的卡片（第六十四轮）：中性蓝，不走「好/坏」语义——
   选项没有对错，颜色只是分组锚点 */
.tone-opt {
  --t: var(--tone-opt);
  --bg: var(--tone-opt-bg);
  border-left-color: var(--tone-opt);
  background: var(--tone-opt-bg);
}
.tone-opt .card-value { color: var(--tone-opt); }

/* 总人数卡（全部）：描边用蓝色，和「筛选中」的那几张区分开 */
.tone-total {
  --t: var(--tone-total);
  --bg: var(--tone-total-bg);
}

/* --------------------------- 状态图例 --------------------------- */

.legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-sm);
  margin: var(--space-md) 0 0;
  font-size: 12px;
}

.legend-chip {
  padding: 3px 8px;
  border: 1px solid currentcolor;
  border-radius: 999px;
  font-weight: 600;
}

.legend-chip b {
  margin-left: 5px;
  font-weight: 700;
}

/* 归到哪个桶：小字标在胶囊里，不用颜色单独传信息 */
.legend-chip i {
  margin-left: 5px;
  font-style: normal;
  font-weight: 400;
  opacity: 0.85;
}

.legend-chip.tone-ok { color: var(--tone-ok); background: var(--tone-ok-bg); }
.legend-chip.tone-bad { color: var(--tone-bad); background: var(--tone-bad-bg); }
.legend-chip.tone-warn { color: var(--tone-warn); background: var(--tone-warn-bg); }
.legend-chip.tone-muted { color: var(--tone-muted); background: var(--tone-muted-bg); }

.legend-note {
  font-weight: 400;
}

/* --------------------------- 每班卡片 --------------------------- */

.sec-title {
  margin: var(--space-lg) 0 var(--space-sm);
  font-size: 14px;
}

.cls-card {
  padding: var(--space-md);
  margin-bottom: var(--space-md);
}

.cls-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-sm);
}

.cls-name {
  font-size: 15px;
}

.cls-teacher {
  margin-left: var(--space-sm);
  font-size: 12px;
}

.badges {
  display: flex;
  gap: var(--space-xs);
}

.cls-stat {
  margin: var(--space-xs) 0 0;
  font-size: 12px;
}

.all-good {
  margin: var(--space-sm) 0 0;
  padding: var(--space-sm) var(--space-md);
  border-radius: var(--radius);
  background: var(--tone-ok-bg);
  color: var(--tone-ok);
  font-size: 13px;
}

/* 名单标题那一行：左边「班级筛选 + 标题」，右边导出。
   `sticky` + 高 z-index：名单再长，导出按钮也一直钉在顶部，不用往回滚。 */
.sec-head {
  position: sticky;
  top: 0;
  z-index: 3;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-sm);
  flex-wrap: wrap;
  margin: var(--space-lg) 0 var(--space-sm);
  padding: var(--space-sm) 0;
  background: var(--color-bg);
}

.sec-head-left {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  flex-wrap: wrap;
}

/* 班级筛选弹层：一个班一行，右边是这个班的人数 */
.cls-picker {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 260px;
  overflow-y: auto;
}

.cls-opt {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 6px 8px;
  border: 0;
  border-radius: var(--radius);
  background: transparent;
  color: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}

.cls-opt:hover {
  background: var(--color-muted);
}

.cls-opt.on {
  background: var(--color-muted);
  font-weight: 600;
}

/* 标题原本的 margin 由 .sec-head 接管了，这里只留字号 */
.sec-head .sec-title {
  margin: 0;
  font-size: 14px;
}

.grp {
  margin: var(--space-md) 0 var(--space-xs);
  font-size: 13px;
}
.grp.tone-bad { color: var(--tone-bad); }
.grp.tone-warn { color: var(--tone-warn); }
.grp.tone-muted { color: var(--tone-muted); }

.stu-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.stu {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-sm) var(--space-sm);
  border-bottom: 1px dashed var(--color-border);
  font-size: 13px;
}

.stu:last-child {
  border-bottom: 0;
}

.stu-name {
  min-width: 5em;
  font-weight: 600;
}

.stu-no {
  color: var(--color-muted-fg);
  font-size: 12px;
}

.stu-note {
  color: var(--color-card-foreground);
  word-break: break-all;
}

.stu-note.empty {
  color: var(--color-muted-fg);
}
</style>
