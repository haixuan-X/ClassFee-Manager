import { request } from '@/api/request'
import type { UserAccount, UserCreateRequest, UserUpdateRequest } from '@/types'

/** 账号列表（运营角色 ADMIN/MONITOR/TEACHER；含停用账号，按登录名排序） */
export function fetchUsers(keyword?: string) {
  return request<UserAccount[]>({
    url: '/users',
    method: 'get',
    params: { keyword: keyword || undefined },
  })
}

/** 新建账号（老师建班；默认初始密码 123456、角色 MEMBER，建号后即可登录） */
export function createUser(data: UserCreateRequest) {
  return request<UserAccount>({ url: '/users', method: 'post', data })
}

/** 编辑账号 / 重置密码 / 停用启用（同一带 PATCH 语义的 PUT） */
export function updateUser(id: number, data: UserUpdateRequest) {
  return request<UserAccount>({ url: `/users/${id}`, method: 'put', data })
}

/**
 * 删除账号：仅「零引用」的账号可删（无流水 / 缴费记录 / 公告 / 批次关联）。
 * 有历史引用时后端 400 拒绝，提示改用停用。
 */
export function deleteUser(id: number) {
  return request<void>({ url: `/users/${id}`, method: 'delete' })
}
