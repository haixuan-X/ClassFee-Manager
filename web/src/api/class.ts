import { request } from '@/api/request'
import type { ClassInfo, ClassInfoRequest } from '@/types'

/** 班级信息（全员可读） */
export function fetchClassInfo() {
  return request<ClassInfo>({ url: '/class', method: 'get' })
}

/**
 * 所有**启用**的班（第三十二轮）。
 *
 * 给「个人信息 → 我带的班」用：老师要能选**所有**班（不限于已经能管的），
 * 否则「我带另一个班」根本没法表达。只给运营角色以上。
 */
export function fetchClassChoices() {
  return request<{ classes: { id: number; className: string; grade: string }[] }>({
    url: '/class/choices',
    method: 'get',
  })
}

/** 编辑班级名称 / 年级 / 班主任（仅运营角色 ADMIN/MONITOR/TEACHER；balance 为流水冗余列，不开放手改） */
export function updateClassInfo(data: ClassInfoRequest) {
  return request<ClassInfo>({ url: '/class', method: 'put', data })
}
