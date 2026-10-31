<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import echarts, { chartColors, prefersReducedMotion, type ECOption } from '@/utils/echarts'
import { rafThrottle } from '@/utils/rafThrottle'
import type { ECharts } from 'echarts/core'
import type { TrendPoint } from '@/types'

/** 近 N 月收支趋势折线图（MASTER §1.2：收入实线、支出虚线、填充 ≤20%） */
const props = defineProps<{ points: TrendPoint[] }>()

const el = ref<HTMLDivElement>()
const details = ref<HTMLDetailsElement>()
let chart: ECharts | null = null

const hasData = computed(() =>
  props.points.some((p) => Number(p.income) > 0 || Number(p.expense) > 0),
)

const totalIncome = computed(() =>
  props.points.reduce((sum, p) => sum + Number(p.income), 0),
)
const totalExpense = computed(() =>
  props.points.reduce((sum, p) => sum + Number(p.expense), 0),
)

const ariaLabel = computed(() =>
  `近 ${props.points.length} 个月收支趋势折线图，收入合计 ${totalIncome.value.toFixed(2)} 元，支出合计 ${totalExpense.value.toFixed(2)} 元，详细数值见下方数据表。`,
)

function render() {
  if (!chart || !hasData.value) return
  const colors = chartColors()
  const option: ECOption = {
    color: [colors.income, colors.expense],
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value) => Number(value).toFixed(2),
    },
    legend: {
      data: ['收入', '支出'],
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
      axisLabel: { color: colors.axis },
      splitLine: { lineStyle: { color: colors.splitLine } },
    },
    series: [
      {
        name: '收入',
        type: 'line',
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2 },
        // 填充不透明度 ≤20%（MASTER §1.2）
        areaStyle: { opacity: 0.14 },
        data: props.points.map((p) => Number(p.income)),
      },
      {
        name: '支出',
        type: 'line',
        smooth: true,
        showSymbol: false,
        // 支出用虚线：不依赖颜色也能区分两条线
        lineStyle: { width: 2, type: [6, 4] },
        areaStyle: { opacity: 0.14 },
        data: props.points.map((p) => Number(p.expense)),
      },
    ],
    animation: !prefersReducedMotion(),
  }
  chart.setOption(option)
}

/**
 * 拖窗口时每帧都会触发 resize，`chart.resize()` 会整块重画图表。
 * 用 `rafThrottle` 把重画对齐到下一帧——一帧内拖多少次都只画一次。
 * 组件卸载时会 `removeEventListener`，之后这个函数不会再被调用。
 */
const resize = rafThrottle(() => {
  chart?.resize()
})

/**
 * 需要时创建 ECharts 实例（幂等）。
 *
 * ⚠ 为什么不能只写在 `onMounted` 里：图表容器用 `v-if`（有数据才存在），
 * 组件挂载那一刻数据还没到，容器**根本不存在**，`el.value` 是 null。
 * 而 `v-if` 从 false 变 true 时组件**不会重新挂载**，`onMounted` 不会再跑——
 * 所以建实例必须做成幂等的，两处都调，否则图表永远画不出来。
 *
 * 另一头：容器用 `v-show`（隐藏但存在）时，ECharts 在 `display:none`
 * 的容器上 init 量到的宽度是 0，画布会退化成 100px 挤在左边
 * （实测复现），且 `resize()` 救不回来——ECharts 不会重新量一个隐藏元素的尺寸。
 * 所以容器必须是 `v-if`：有数据才存在，挂载那一刻就是可见且有真实宽度的。
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
    <!-- v-if 而非 v-show：容器必须在**可见时**才存在，理由见 ensureChart 的注释 -->
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
      description="近几个月还没有收支记录，记一笔就能看到趋势"
      :image-size="72"
    />

    <!-- 数据表兜底：默认折叠，键盘与读屏始终可读 -->
    <details v-if="hasData" ref="details" class="data-table">
      <summary>查看数据表</summary>
      <table>
        <caption class="sr-only">近 {{ props.points.length }} 个月收支数据</caption>
        <thead>
          <tr>
            <th scope="col">月份</th>
            <th scope="col" class="right">收入（元）</th>
            <th scope="col" class="right">支出（元）</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in props.points" :key="p.ym">
            <th scope="row">{{ p.ym }}</th>
            <td class="right num">{{ Number(p.income).toFixed(2) }}</td>
            <td class="right num">{{ Number(p.expense).toFixed(2) }}</td>
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
