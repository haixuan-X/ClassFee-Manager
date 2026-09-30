import { request } from '@/api/request'
import type {
  LoginRequest,
  LoginResult,
  PasswordRequest,
  ProfileUpdateRequest,
  UserAccount,
  UserInfo,
} from '@/types'

/** 登录 */
export function login(data: LoginRequest) {
  return request<LoginResult>({ url: '/auth/login', method: 'post', data })
}

/** 当前登录用户 */
export function fetchMe() {
  return request<UserInfo>({ url: '/auth/me', method: 'get' })
}

/** 修改密码 */
export function changePassword(data: PasswordRequest) {
  return request<void>({ url: '/auth/password', method: 'put', data })
}

/**
 * 第十五轮：修改本人资料（姓名 / 学号 / 手机号）。
 *
 * 全员可用（含普通成员），**不进 STAFF_ROUTES**。改谁由登录令牌决定，
 * 入参里没有 id —— 结构上改不到别人。返回 `UserInfo`（同 `/auth/me` 结构），
 * 保存后可直接写回 store 让顶栏姓名/班级同步刷新，不用二次请求。
 */
export function updateProfile(data: ProfileUpdateRequest) {
  return request<UserInfo>({ url: '/auth/profile', method: 'put', data })
}

/**
 * 第十五轮：读取本人完整资料（含学号 / 手机号 / 状态 / 时间戳）。
 *
 * 不走 `GET /api/users` 找自己那行——那是运营角色的成员管理列表，
 * 普通成员读会 403，页面就填不出自己的学号。本端点只认登录令牌，**只能读自己**。
 */
export function fetchMyProfile() {
  return request<UserAccount>({ url: '/auth/profile', method: 'get' })
}
