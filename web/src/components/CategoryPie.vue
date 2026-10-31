<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import echarts, { chartColors, cssVar, prefersReducedMotion, type ECOption } from '@/utils/echarts'
import { rafThrottle } from '@/utils/rafThrottle'
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

/** 同 TrendChart：拖窗口每帧触发，用 rafThrottle 对齐到下一帧，只画一次 */
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
  () => props.items,
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
