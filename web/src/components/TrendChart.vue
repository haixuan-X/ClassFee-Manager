<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import echarts, { chartColors, prefersReducedMotion, type ECOption } from '@/utils/echarts'
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

function resize() {
  chart?.resize()
}

onMounted(() => {
  if (!el.value) return
  chart = echarts.init(el.value)
  render()
  window.addEventListener('resize', resize)
})

watch(() => props.points, render, { deep: true })

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div>
    <div
      v-show="hasData"
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
