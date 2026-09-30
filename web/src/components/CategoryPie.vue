<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import echarts, { chartColors, cssVar, prefersReducedMotion, type ECOption } from '@/utils/echarts'
import type { ECharts } from 'echarts/core'
import type { PieItem } from '@/types'

/**
 * 支出分类环形图（MASTER §1.2）：
 * 切片 ≤6 直接标百分比，>6 的部分合并为「其他」；配可排序数据表兜底。
 */
const props = defineProps<{ items: PieItem[] }>()

const el = ref<HTMLDivElement>()
let chart: ECharts | null = null

/** 排序方向：默认金额从高到低 */
const sortDesc = ref(true)

const hasData = computed(() => props.items.length > 0)

const total = computed(() =>
  props.items.reduce((sum, item) => sum + Number(item.value), 0),
)

/** 合并超出 6 类的部分为「其他」 */
const displayItems = computed<PieItem[]>(() => {
  if (props.items.length <= 6) return props.items
  const head = props.items.slice(0, 5)
  const rest = props.items.slice(5).reduce((sum, i) => sum + Number(i.value), 0)
  return [...head, { name: '其他', value: rest }]
})

const sortedItems = computed(() =>
  [...props.items].sort((a, b) =>
    sortDesc.value ? Number(b.value) - Number(a.value) : Number(a.value) - Number(b.value),
  ),
)

const ariaLabel = computed(
  () =>
    `近半年支出分类环形图，共 ${props.items.length} 类合计 ${total.value.toFixed(2)} 元，详细占比见下方数据表。`,
)

function toggleSort() {
  sortDesc.value = !sortDesc.value
}

function render() {
  if (!chart || !hasData.value) return
  const colors = chartColors()
  const showLabels = displayItems.value.length <= 6

  const option: ECOption = {
    color: colors.slices,
    tooltip: {
      trigger: 'item',
      valueFormatter: (value) => `${Number(value).toFixed(2)} 元`,
    },
    legend: {
      bottom: 0,
      type: 'scroll',
      textStyle: { color: colors.axis },
    },
    series: [
      {
        name: '支出分类',
        type: 'pie',
        radius: ['54%', '74%'],
        center: ['50%', '44%'],
        // 每片直接标百分比（>6 类时靠图例 + 数据表）
        label: {
          show: showLabels,
          formatter: '{b} {d}%',
          fontSize: 11,
          color: colors.axis,
        },
        labelLine: { show: showLabels },
        itemStyle: { borderColor: cssVar('--color-surface'), borderWidth: 2 },
        data: displayItems.value.map((i) => ({ name: i.name, value: Number(i.value) })),
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

watch(() => props.items, render, { deep: true })

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
      description="近半年还没有支出记录"
      :image-size="72"
    />

    <!-- 可排序数据表兜底：与图形等价，键盘可操作 -->
    <table v-if="hasData" class="data-table">
      <caption class="sr-only">支出分类占比数据表</caption>
      <thead>
        <tr>
          <th scope="col">
            <button class="sort-btn" type="button" @click="toggleSort">
              类别
              <span aria-hidden="true">{{ sortDesc ? '▼' : '▲' }}</span>
              <span class="sr-only">{{ sortDesc ? '当前按金额从高到低排序' : '当前按金额从低到高排序' }}</span>
            </button>
          </th>
          <th scope="col" class="right">金额（元）</th>
          <th scope="col" class="right">占比</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in sortedItems" :key="item.name">
          <th scope="row">{{ item.name }}</th>
          <td class="right num">{{ Number(item.value).toFixed(2) }}</td>
          <td class="right num">{{ ((Number(item.value) / total) * 100).toFixed(1) }}%</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.chart {
  width: 100%;
  height: 260px;
}

.empty {
  height: 260px;
  margin: 0;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 8px;
  font-size: 12.5px;
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
  padding-top: 0;
}

.right {
  text-align: right;
}

.sort-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 40px;
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}

.sort-btn:hover {
  color: var(--color-info);
}
</style>
