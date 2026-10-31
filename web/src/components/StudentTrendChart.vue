<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import echarts, { chartColors, prefersReducedMotion, type ECOption } from '@/utils/echarts'
import { rafThrottle } from '@/utils/rafThrottle'
import type { ECharts } from 'echarts/core'

/**
 * 学生人数趋势（仪表盘「学生情况总览」）。
 *
 * 为什么单独一个组件而不复用 `TrendChart.vue`：那个组件的 props 写死成
 * `{ym, income, expense}`、图例写死「收入/支出」、数值格式写死金额两位小数。
 * 人数是整数、序列是「新增/累计」，套进去要么谎报格式、要么改成一个
 * 到处 if 的万能组件。两种都比复制一份更难维护。
 *
 * ⚠ 唯一有**真实时间轴**的序列是入校日期（`enroll_date`）。库里没有异动历史，
 * 所以这里画的是入校趋势，不是「学籍异动」——后者目前无数据源。
 */
const props = defineProps<{
  points: { ym: string; added: number; cumulative: number }[]
  /** 无数据时的说明文案，由调用方按场景给（空库 vs 没权限） */
  emptyText?: string
}>()

const el = ref<HTMLDivElement>()
let chart: ECharts | null = null

const hasData = computed(() => props.points.length > 0)
const totalAdded = computed(() => props.points.reduce((s, p) => s + p.added, 0))

const ariaLabel = computed(() =>
  `学生入校人数趋势折线图，共 ${props.points.length} 个月，累计入校 ${totalAdded.value} 人，详细数值见下方数据表。`,
)

function render() {
  if (!chart || !hasData.value) return
  const colors = chartColors()
  const option: ECOption = {
    // ⚠ **每条序列都写死颜色**，不靠 `color: [...]` 调色板分配。
    // 调色板是按「消费顺序」给的：柱子那条带了显式 `itemStyle.color`，
    // 就不占槽位，于是折线把 `color[0]`（本想给柱子的蓝）拿走了——
    // 结果柱和线**画成同一个蓝**。写死就没有这个坑。
    //
    // 蓝=当月入校（离散事件），绿=累计在校（品牌强调色，连续存量）。
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v) => `${v} 人`,
    },
    legend: {
      data: ['当月入校', '累计在校'],
      top: 0,
      right: 0,
      textStyle: { color: colors.axis },
    },
    grid: { left: 8, right: 16, top: 40, bottom: 0, containLabel: true },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: props.points.map((p) => p.ym),
      axisLine: { lineStyle: { color: colors.splitLine } },
      axisLabel: { color: colors.axis },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      name: '人',
      axisLabel: { color: colors.axis },
      splitLine: { lineStyle: { color: colors.splitLine } },
    },
    series: [
      {
        name: '当月入校',
        type: 'bar',
        barMaxWidth: 22,
        // 柱状不填充：新增是「事件数」，面积会让它看起来像存量
        itemStyle: { color: colors.count },
        data: props.points.map((p) => p.added),
      },
      {
        name: '累计在校',
        type: 'line',
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, color: colors.income },
        itemStyle: { color: colors.income },
        areaStyle: { color: colors.income, opacity: 0.14 },
        data: props.points.map((p) => p.cumulative),
      },
    ],
    animation: !prefersReducedMotion(),
  }
  // 渲染前量一次尺寸：`setOption` 只画不量，容器宽度变了得自己告诉它。
  chart.resize()
  chart.setOption(option)
}

/** 同 TrendChart：拖窗口每帧触发，用 rafThrottle 对齐到下一帧，只画一次 */
const resize = rafThrottle(() => {
  chart?.resize()
})

/**
 * 需要时创建 ECharts 实例。
 *
 * ⚠ 容器用 `v-if`（有数据才存在），所以**组件挂载那一刻容器可能还不存在**，
 * `onMounted` 里 `el.value` 是 null。而 `v-if` 从 false 变 true 时
 * **组件并不会重新挂载**，`onMounted` 不会再跑一次——所以建实例这件事
 * 不能只写在 `onMounted` 里，否则数据晚到一步图表就永远画不出来。
 * 这里做成幂等的，两处都调它。
 */
function ensureChart() {
  if (chart || !el.value) return
  chart = echarts.init(el.value)
  window.addEventListener('resize', resize)
  render()
}

onMounted(() => {
  ensureChart()
})

/**
 * 数据到达后重画。
 *
 * `flush: 'post'`：在 DOM 更新之后再跑——`v-if` 刚创建出来的容器，
 * 早于 DOM 更新执行是拿不到 ref 的。
 */
watch(
  () => props.points,
  async () => {
    await nextTick()
    ensureChart()
    render()
  },
  { deep: true, flush: 'post' },
)

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div>
    <!--
      ⚠ 这里用 `v-if` 而不是 `v-show`，是**必需**的：
      图表容器如果一开始是 `display:none`，ECharts 在它上面 init 时量到的
      宽度是 0，画布会退化成 100px 挤在容器左边（实测复现），而且
      之后 `resize()` 也救不回来——ECharts 不会重新量一个隐藏元素的尺寸。
      `v-if` 让容器**只在有数据时存在**，挂载那一刻它就是可见且有真实宽度的。
    -->
    <div
      v-if="hasData"
      ref="el"
      class="chart"
      role="img"
      :aria-label="ariaLabel"
    />

    <el-empty
      v-if="!hasData"
      class="empty"
      :description="emptyText ?? '还没有填过入校日期的记录'"
      :image-size="72"
    />

    <!-- 数据表兜底：默认折叠，键盘与读屏始终可读 -->
    <details v-if="hasData" class="data-table">
      <summary>查看数据表</summary>
      <table>
        <caption class="sr-only">按入校月份的学生人数</caption>
        <thead>
          <tr>
            <th scope="col">月份</th>
            <th scope="col" class="right">当月入校（人）</th>
            <th scope="col" class="right">累计在校（人）</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in props.points" :key="p.ym">
            <th scope="row">{{ p.ym }}</th>
            <td class="right num">{{ p.added }}</td>
            <td class="right num">{{ p.cumulative }}</td>
          </tr>
        </tbody>
      </table>
    </details>
  </div>
</template>

<style scoped>
.chart {
  width: 100%;
  height: 280px;
}

.empty {
  height: 280px;
  margin: 0;
}

.data-table {
  margin-top: 10px;
  font-size: 12.5px;
  color: var(--color-muted-fg);
}

.data-table summary {
  cursor: pointer;
  padding: 6px 0;
}

.data-table table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 4px;
}

.data-table th,
.data-table td {
  padding: 6px 8px;
  border-bottom: 1px dashed var(--color-border);
  text-align: left;
  font-weight: 400;
}

.data-table thead th {
  font-weight: 600;
  color: var(--color-foreground);
}

.right {
  text-align: right;
}
</style>