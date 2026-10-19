import { request } from '@/api/request'
import type { AppVersion } from '@/types'

/**
 * 读取当前后端的版本号。
 *
 * **免鉴权端点**（后端加在 `PUBLIC_ROUTES` 里），所以登录页未登录时也能调用——
 * 这正是它放在这里而不是塞进 `/auth/me` 的原因：出问题时人还没登录，
 * 看到版本号才能第一时间判断「是不是版本不对」。
 *
 * ⚠ 界面上显示的版本号**只以这个接口为准**，不读 `package.json`：
 * 浏览器可能缓存着上一版的 bundle，读本地字段会显示一个根本没在跑的版本。
 */
export function fetchVersion() {
  return request<AppVersion>({ url: '/version', method: 'get' })
}