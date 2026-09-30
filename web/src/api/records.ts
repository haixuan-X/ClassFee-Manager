import service, { request } from '@/api/request'
import type { Category, RecordRequest, RecordType, FeeRecord, PageInfo, RecordQuery } from '@/types'

/** 类别列表，kind=INCOME|EXPENSE 可选 */
export function fetchCategories(kind?: RecordType) {
  return request<Category[]>({ url: '/categories', method: 'get', params: { kind } })
}

/** 分页流水 */
export function fetchRecords(query: RecordQuery) {
  return request<PageInfo<FeeRecord>>({ url: '/records', method: 'get', params: query })
}

/** 记一笔（ADMIN/MONITOR/TEACHER） */
export function createRecord(data: RecordRequest) {
  return request<FeeRecord>({ url: '/records', method: 'post', data })
}

/** 作废（红冲，ADMIN/MONITOR/TEACHER） */
export function voidRecord(id: number) {
  return request<void>({ url: `/records/${id}/void`, method: 'post' })
}

/** 物理删除（ADMIN/MONITOR/TEACHER）：正常流水同事务回滚余额并联动批次缴费状态 */
export function deleteRecord(id: number) {
  return request<void>({ url: `/records/${id}`, method: 'delete' })
}

/** 新建类别（ADMIN/MONITOR/TEACHER） */
export function createCategory(data: { kind: RecordType; name: string; sort?: number }) {
  return request<void>({ url: '/categories', method: 'post', data })
}

/**
 * 改名 / 调整排序（ADMIN/MONITOR/TEACHER）。
 * 字段全部可选、「不传=不修改」；`kind` 只有在**该类别尚未被任何流水引用**时才允许改
 * （改了会让历史流水的收支方向与类别对不上），后端会拒绝并说明原因。
 * 注意：**不要**在 body 里重复传 id —— 路径里已经有了，传了且不一致后端直接 400。
 */
export function updateCategory(
  id: number,
  data: { name?: string; kind?: RecordType; icon?: string; sort?: number },
) {
  return request<void>({ url: `/categories/${id}`, method: 'put', data })
}

/** 删除类别（ADMIN/MONITOR/TEACHER）：未被流水引用转停用，已引用会被后端拒绝 */
export function deleteCategory(id: number) {
  return request<void>({ url: `/categories/${id}`, method: 'delete' })
}

/**
 * 导出账本（ADMIN/MONITOR/TEACHER）：xlsx 二进制，**沿用列表当前筛选条件**（看到什么导出什么）。
 * 直接用 axios 实例（不走 request() 解包）拿 Blob，再触发浏览器下载。
 */
export async function exportRecords(query: RecordQuery): Promise<void> {
  // 导出不按分页，page/size 剔掉（后端虽忽略，也别让下载 URL 里出现误导参数）
  const { id, page: _page, size: _size, ...filters } = query
  const res = await service.get<Blob>('/records/export', {
    params: { ...filters, id },
    responseType: 'blob',
  })
  const blob = new Blob([res.data], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
  // 优先用后端给的 RFC 5987 中文文件名（filename*=UTF-8''...），拿不到就退回默认名
  const disposition = res.headers['content-disposition'] ?? ''
  const matched = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  const filename = matched ? decodeURIComponent(matched[1]) : '班费账本.xlsx'
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  // 立刻 revoke 会让部分浏览器来不及取数据，延后一拍再释放
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
