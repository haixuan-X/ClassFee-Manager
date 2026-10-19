<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import echarts, { chartColors, prefersReducedMotion, type ECOption } from '@/utils/echarts'
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
    color: [colors.accent, colors.income],
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
        itemStyle: { color: colors.accent },
        data: props.points.map((p) => p.added),
      },
      {
        name: '累计在校',
        type: 'line',
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2 },
        areaStyle: { opacity: 0.14 },
        data: props.points.map((p) => p.cumulative),
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