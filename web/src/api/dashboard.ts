import { request } from '@/api/request'
import type { DashboardSummary, PieItem, StudentDashboard, TrendPoint } from '@/types'

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

/**
 * 学生情况总览（仪表盘第二个总览）。
 *
 * ⚠ 返回的行数**受可见范围限制**：普通同学默认只看得见自己那一行，
 * 仪表盘不是绕过学生信息权限的后门。所以界面必须说清 `canViewAll=false`，
 * 否则「学生数量 1」会被读成「班里只有 1 个人」。
 */
export function fetchStudentDashboard(months = 12) {
  return request<StudentDashboard>({
    url: '/dashboard/students',
    method: 'get',
    params: { months },
  })
}
