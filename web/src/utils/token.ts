/**
 * token 内存态：axios 拦截器读它，Pinia store 写它。
 * 单独抽一个模块，避免 request.ts ↔ store 的循环依赖。
 */
const STORAGE_KEY = 'classfee.token'
/**
 * 用户信息缓存（第十六轮新增）。
 *
 * 之前用户信息**只存内存**，`/auth/me` 回来前 `user` 是 null，于是每次刷新页面：
 *   - 顶栏先闪一下「同学 / 未登录」
 *   - 更糟的是 `isStaff` 暂时为 false —— 班主任在那一瞬会看到**普通成员的侧栏**
 *     （少一半入口），再跳回完整菜单
 * 这里把用户信息与 token 一起持久化，store 初始化时**同步**读出来，
 * 首屏即可用正确身份渲染；`/auth/me` 仍会在路由守卫里后台刷新，保证数据新鲜。
 */
const USER_KEY = 'classfee.user'

let token = ''

export function getToken(): string {
  if (!token) {
    token = localStorage.getItem(STORAGE_KEY) ?? ''
  }
  return token
}

export function setToken(value: string): void {
  token = value
  if (value) {
    localStorage.setItem(STORAGE_KEY, value)
  } else {
    localStorage.removeItem(STORAGE_KEY)
  }
}

export function getCachedUser<T>(): T | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    // 缓存被外部改坏（手改、手清）时按「没有缓存」处理，交给 /auth/me 兜底
    return null
  }
}

export function setCachedUser(value: unknown): void {
  try {
    if (value) {
      localStorage.setItem(USER_KEY, JSON.stringify(value))
    } else {
      localStorage.removeItem(USER_KEY)
    }
  } catch {
    // 隐私模式 / 配额满：缓存写不进去不影响功能，只是刷新会再闪一下
  }
}
