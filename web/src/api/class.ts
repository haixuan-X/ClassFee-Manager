import { request } from '@/api/request'
import type { ClassInfo, ClassInfoRequest } from '@/types'

/** 班级信息（全员可读） */
export function fetchClassInfo() {
  return request<ClassInfo>({ url: '/class', method: 'get' })
}

/** 编辑班级名称 / 年级 / 班主任（仅运营角色 ADMIN/MONITOR/TEACHER；balance 为流水冗余列，不开放手改） */
export function updateClassInfo(data: ClassInfoRequest) {
  return request<ClassInfo>({ url: '/class', method: 'put', data })
}
