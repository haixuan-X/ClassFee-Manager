import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { getCachedUser, getToken, setCachedUser, setToken } from '@/utils/token'
import type { LoginResult, UserInfo } from '@/types'
import { STAFF_ROLES } from '@/types'

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
  /**
   * 运营角色：财务操作与成员账号管理，与后端 `security.STAFF_ROLES` 同口径。
   *
   * ⚠ **从 `@/types` 的共享常量取，不在本文件里另写一份**。
   * 原来这里手写着 `ADMIN || MONITOR || TEACHER`——**漏了院长**。
   * 后果实测得到过：院长登录后仪表盘的「缴费完成率」卡里那个按钮
   * 走的是「非运营角色」分支，跳到 `/my-fees`；而那个路由的角色白名单
   * 里没有院长，路由守卫又把他弹回仪表盘——**点了像没反应**。
   * 同一个漏字还让院长**看不到**班级信息的编辑入口、看不到
   * 「能写」的账本页。
   *
   * 这已经是本项目第三次因为「同一个角色列表在多个地方各写一份」而翻车
   * （前两次是侧栏少 5 个入口、路由守卫把院长弹回仪表盘）。共享常量
   * 就是为此存在的。
   */
  const isStaff = computed(() => {
    const role = user.value?.role
    return role ? STAFF_ROLES.includes(role) : false
  })
  const displayName = computed(() => user.value?.realName || user.value?.username || '同学')

  /**
   * 是不是**纯院长**（第三十轮）：只管学院，不参与班级事务。
   *
   * 纯院长的侧栏**不出现**「账目」和「班级」两组，仪表盘只有
   * 「学生情况总览」。但那只是**入口**层面的过滤——真正的边界在后端
   * （`security` 中间件的纯院长白名单），手输 URL 也绕不过去。
   *
   * 判据是 `deanOnly` 这个**标志**而不是「角色是不是 DEAN」：
   * 兼班主任的院长（`deanOnly=false`）照样能管班级。
   */
  const isPureDean = computed(
    () => user.value?.role === 'DEAN' && user.value?.deanOnly === true,
  )

  /**
   * **当前班**（第三十二轮）：这个人正在操作哪个班。
   *
   * 一个班主任常带好几个班（云计算2502 + 云计算2501），侧栏顶上能切。
   * 所有请求都由 axios 拦截器统一带上它（见 `api/request.ts`），
   * 后端在鉴权中间件里把它当成「本次操作的班」——
   * 所以各个页面自己不用记这件事。
   *
   * ⚠ 用 **ref** 而不是 computed：它要能被 `setCurrentClass` 改，
   * 而存在 localStorage 里的那个值**不是响应式源**——computed 不会因为
   * localStorage 变了而重算（那样切换器切了但请求还带着旧的班）。
   */
  const currentClassId = ref<number | null>(null)

  /** 按「能管的班」和上次的选择，算出当前班 */
  function initCurrentClass(u: UserInfo | null) {
    if (!u) {
      currentClassId.value = null
      return
    }
    const ids = u.classIds?.length ? u.classIds : [u.classId]
    // 存的班可能已经被移出「可管的班」了（老师被调走）→ 落回默认班
    const saved = Number(localStorage.getItem('classfee.classId') ?? '')
    currentClassId.value = saved && ids.includes(saved) ? saved : u.classId
  }
  initCurrentClass(user.value)

  /** 切到另一个班（只能切自己能管的） */
  function setCurrentClass(id: number) {
    const u = user.value
    if (!u) return
    const ids = u.classIds?.length ? u.classIds : [u.classId]
    if (!ids.includes(id)) return
    currentClassId.value = id
    localStorage.setItem('classfee.classId', String(id))
  }

  /**
   * 能否切班：只有**多班**且**真能管班级事务**时才需要切换器。
   *
   * ⚠ 纯院长（第三十轮）**不参与班级事务**——所有班级级接口对他都是 403。
   * 给他摆一个切换器，切过去什么都干不了，纯属误导。
   */
  const canSwitchClass = computed(
    () => (user.value?.classIds?.length ?? 0) > 1 && !isPureDean.value,
  )

  /** 登录成功后写入会话 */
  function setSession(result: LoginResult) {
    token.value = result.token
    setToken(result.token)
    user.value = result.user
    setCachedUser(result.user)
    initCurrentClass(result.user)
  }

  function setUser(info: UserInfo) {
    user.value = info
    setCachedUser(info)
    initCurrentClass(info)
  }

  /** 清除本地会话（退出登录 / 401） */
  function clear() {
    token.value = ''
    setToken('')
    user.value = null
    setCachedUser(null)
    currentClassId.value = null
  }

  return {
    token,
    user,
    isLogin,
    isAdmin,
    isStaff,
    isPureDean,
    currentClassId,
    canSwitchClass,
    setCurrentClass,
    displayName,
    setSession,
    setUser,
    clear,
  }
})
