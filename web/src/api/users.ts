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

/** 批量动作。只放「同一个值套到 N 个人身上」的操作。 */
export type UserBatchAction = 'disable' | 'enable' | 'delete' | 'resetPassword'

export interface UserBatchResult {
  action: UserBatchAction
  /** 动作的中文名，后端给的，前端不再抄一份措辞 */
  actionText: string
  /** 勾了几个人 */
  requested: number
  /** 真正处理成功的条数 */
  changed: number
  /** 被跳过的（自己 / 权限不够 / 有历史引用），逐条带原因 */
  skipped: { userId: number; reason: string }[]
  /** 只有重置密码时才有值，其它动作是 null */
  password: string | null
}

/**
 * 批量停用 / 启用 / 删除 / 重置密码（第四十四轮）。
 *
 * 规则与单条完全同口径：目标须在**我能管的班**里、不能动自己、
 * 操作者等级须**严格高于**目标、删除只对**零引用**账号生效。
 *
 * 「能做就做，做不了的跳过并说明」——不会因为一条删不掉就整批不动
 * （那在用户看来就是「点了没反应」）。所以**返回值里有 skipped**，
 * 调用方必须把它读出来告诉用户，别只弹一个「成功」。
 */
export function batchUsers(
  action: UserBatchAction,
  userIds: number[],
  password?: string,
) {
  return request<UserBatchResult>({
    url: '/users/batch',
    method: 'post',
    data: { action, userIds, password: password || undefined },
  })
}
