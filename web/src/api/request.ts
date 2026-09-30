import axios, { type AxiosError, type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'
import { getToken } from '@/utils/token'
import { useUserStore } from '@/stores/user'
import type { ApiResponse, FieldError } from '@/types'

/** 统一请求实例：BaseURL 走 Vite 代理到后端 */
const service = axios.create({
  baseURL: '/api',
  timeout: 10000,
})

service.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

/** HTTP 层错误处理：401 回登录页，其余就地提示 */
service.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiResponse>) => {
    const status = error.response?.status
    const message = error.response?.data?.message

    if (status === 401) {
      // 必须清 Pinia 里的登录态：只清 localStorage 会让路由守卫仍认为“已登录”，
      // 把 /login 又弹回受保护页，形成卡死循环
      useUserStore().clear()
      const isOnLogin = router.currentRoute.value.path === '/login'
      if (!isOnLogin) {
        ElMessage.warning(message || '登录已过期，请重新登录')
        router.replace({
          path: '/login',
          query: { redirect: router.currentRoute.value.fullPath },
        })
      }
      // 登录页的 401 = 账号密码错误，由页面顶部的 role="alert" 摘要展示，不重复弹提示
    } else if (status === 403) {
      ElMessage.error(message || '当前角色无权执行该操作')
    } else if (status === 400) {
      // 后端把逐字段校验错误放在 data 里
      const items = error.response?.data?.data
      const first = Array.isArray(items) ? (items as FieldError[])[0]?.message : undefined
      ElMessage.error(first || message || '请求参数不合法')
    } else {
      // 404 也要提示：接口缺失时静默失败会让页面“点了没反应”，比报错更难排查
      ElMessage.error(message || '网络异常，请稍后重试')
    }

    return Promise.reject(error)
  },
)

/**
 * 发起请求并解包：成功返回 data，失败（业务 code ≠ 200）提示并 reject。
 */
export function request<T>(config: AxiosRequestConfig): Promise<T> {
  return service.request<ApiResponse<T>>(config).then(({ data }) => {
    if (data.code !== 200) {
      ElMessage.error(data.message || '操作失败')
      return Promise.reject(new Error(data.message))
    }
    return data.data
  })
}

/** 从拦截器捕获的错误里取用户可读的提示文案 */
export function getErrorMessage(error: unknown, fallback = '操作失败'): string {
  const err = error as AxiosError<ApiResponse>
  return err?.response?.data?.message || err?.message || fallback
}

export default service
