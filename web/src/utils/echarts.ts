import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ComposeOption } from 'echarts/core'
import type { BarSeriesOption, LineSeriesOption, PieSeriesOption } from 'echarts/charts'
import type {
  GridComponentOption,
  LegendComponentOption,
  TooltipComponentOption,
} from 'echarts/components'

/**
 * 按需注册 ECharts 模块：全量引入会让首包多出 ~600KB。
 *
 * BarChart 是给「学生情况总览」的当月入校柱状图用的（第二十九轮）。
 * 只注册实际用到的三种——`type: 'bar'` 没注册的话不会静默降级，
 * 而是直接抛 `Type '"bar"' is not assignable to type '"line" | "pie"'`（TS 层）或
 * 渲染出空白图（运行时）。
 */
echarts.use([
  LineChart,
  PieChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  CanvasRenderer,
])

export type ECOption = ComposeOption<
  | LineSeriesOption
  | PieSeriesOption
  | BarSeriesOption
  | GridComponentOption
  | TooltipComponentOption
  | LegendComponentOption
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
  /** 主强调色：人数类图表（学生总览）的柱/线用它，和「收入绿」区分开 */
  accent: string
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
    accent: cssVar('--color-accent'),
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
