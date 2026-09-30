import * as echarts from 'echarts/core'
import { LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ComposeOption } from 'echarts/core'
import type { LineSeriesOption, PieSeriesOption } from 'echarts/charts'
import type {
  GridComponentOption,
  LegendComponentOption,
  TooltipComponentOption,
} from 'echarts/components'

/**
 * 按需注册 ECharts 模块：全量引入会让首包多出 ~600KB。
 */
echarts.use([LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

export type ECOption = ComposeOption<
  LineSeriesOption | PieSeriesOption | GridComponentOption | TooltipComponentOption | LegendComponentOption
>

/**
 * 读设计 token（tokens.css），图表颜色同样不写裸 hex —— 唯一视觉真相在 MASTER.md。
 */
export function cssVar(name: string): string {
  if (typeof document === 'undefined') return ''
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

export interface ChartColors {
  income: string
  expense: string
  slices: string[]
  axis: string
  splitLine: string
  tooltipBg: string
}

/** 渲染前调用一次，拿到当前主题下的图表配色 */
export function chartColors(): ChartColors {
  return {
    income: cssVar('--chart-income'),
    expense: cssVar('--chart-expense'),
    slices: [1, 2, 3, 4, 5, 6].map((i) => cssVar(`--chart-slice-${i}`)),
    axis: cssVar('--color-muted-fg'),
    splitLine: cssVar('--color-border'),
    tooltipBg: cssVar('--color-foreground'),
  }
}

/** 用户要求减少动效时，图表也不做入场动画（MASTER §6） */
export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export default echarts
