import { request } from '@/api/request'
import type { DashboardSummary, PieItem, TrendPoint } from '@/types'

/** 余额 / 本月收支 / 最新 5 笔 */
export function fetchSummary() {
  return request<DashboardSummary>({ url: '/dashboard/summary', method: 'get' })
}

/** 近 N 月收支趋势 */
export function fetchTrend(months = 6) {
  return request<TrendPoint[]>({ url: '/dashboard/trend', method: 'get', params: { months } })
}

/** 近 N 月支出分类占比 */
export function fetchCategoryPie(months = 6) {
  return request<PieItem[]>({ url: '/dashboard/category-pie', method: 'get', params: { months } })
}
