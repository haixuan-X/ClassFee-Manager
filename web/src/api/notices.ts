import { request } from '@/api/request'
import type { Notice, NoticeQuery, NoticeRequest } from '@/types'

/** 公告列表（全员可读；非运营角色只能拿到已发布，status=0/all 由后端按角色降级） */
export function fetchNotices(query: NoticeQuery = {}) {
  return request<Notice[]>({ url: '/notices', method: 'get', params: query })
}

/** 发布公告（ADMIN/MONITOR/TEACHER） */
export function createNotice(data: NoticeRequest) {
  return request<Notice>({ url: '/notices', method: 'post', data })
}

/** 编辑公告 / 切换置顶 / 下架(0) 与恢复(1)（ADMIN/MONITOR/TEACHER） */
export function updateNotice(id: number, data: NoticeRequest) {
  return request<Notice>({ url: `/notices/${id}`, method: 'put', data })
}

/** 彻底删除公告：需先下架，否则后端 400（ADMIN/MONITOR/TEACHER） */
export function deleteNotice(id: number) {
  return request<void>({ url: `/notices/${id}`, method: 'delete' })
}
