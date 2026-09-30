import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { getCachedUser, getToken, setCachedUser, setToken } from '@/utils/token'
import type { LoginResult, UserInfo } from '@/types'

/**
 * 登录态：token 与用户信息都持久化到 localStorage。
 *
 * 第十六轮改：用户信息原本**只在内存**，`/auth/me` 返回前 `user` 为 null，导致
 * 每次刷新都会先闪一下「同学 / 未登录」，而且 `isStaff` 短暂为 false ——
 * 班主任会先看到**普通成员的侧栏**再跳回完整菜单。现在启动即从缓存同步恢复，
 * `/auth/me` 仍在路由守卫里后台刷新（缓存只用于首屏，不代表信任其权限：
 * 真正的边界永远在后端）。
 */
export const useUserStore = defineStore('user', () => {
  const token = ref<string>(getToken())
  // 同步从缓存恢复：首屏就有正确身份，避免闪烁与侧栏跳变
  const user = ref<UserInfo | null>(getCachedUser<UserInfo>())

  const isLogin = computed(() => token.value.length > 0)
  const isAdmin = computed(() => user.value?.role === 'ADMIN')
  /** 运营角色（生活委员/班长/班主任 = ADMIN/MONITOR/TEACHER）：财务操作与成员账号管理，后端 _STAFF_ROUTES 同口径 */
  const isStaff = computed(
    () =>
      user.value?.role === 'ADMIN' ||
      user.value?.role === 'MONITOR' ||
      user.value?.role === 'TEACHER',
  )
  const displayName = computed(() => user.value?.realName || user.value?.username || '同学')

  /** 登录成功后写入会话 */
  function setSession(result: LoginResult) {
    token.value = result.token
    setToken(result.token)
    user.value = result.user
    setCachedUser(result.user)
  }

  function setUser(info: UserInfo) {
    user.value = info
    setCachedUser(info)
  }

  /** 清除本地会话（退出登录 / 401） */
  function clear() {
    token.value = ''
    setToken('')
    user.value = null
    setCachedUser(null)
  }

  return { token, user, isLogin, isAdmin, isStaff, displayName, setSession, setUser, clear }
})
