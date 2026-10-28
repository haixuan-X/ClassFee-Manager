/** xlsx 的 MIME，下载和 Blob 构造都要它 */
const XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

/** axios 二进制响应的最小形状（只用得到 data 和 headers） */
type BlobResponse = { data: Blob; headers?: unknown }

/**
 * 把 xlsx 二进制触发成一次浏览器下载。
 *
 * 中文文件名走 RFC 5987 的 `filename*`（后端统一按这个格式发），
 * 拿不到就用 `fallback`——否则下载出来的文件叫「blob」，用户不知道是什么。
 */
export function downloadXlsx(res: BlobResponse, fallback: string): void {
  const blob = new Blob([res.data], { type: XLSX_MIME })
  const headers = res.headers as Record<string, string> | undefined
  const disposition = String(headers?.['content-disposition'] ?? '')
  const matched = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  const filename = matched ? decodeURIComponent(matched[1]) : fallback
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

/**
 * xlsx 下载失败时抛一条**中文**错误给调用方提示。
 *
 * 这里**不能**直接用 axios 那句 `err.message`：
 * `responseType: 'blob'` 时 `error.response.data` 是个 Blob，后端的中文 message
 * 一个字都读不到，axios 只会说「Request failed with status code 400」——
 * 用户看到的就是英文技术文案。所以只认**能读出来的后端 message**，
 * 读不到就用统一的中文兜底（调用方再原样弹出来）。
 */
export function exportFailure(error: unknown): never {
  const data = (error as { response?: { data?: unknown } } | null)?.response?.data
  let backendMessage: string | undefined
  if (typeof data === 'string') {
    // 有些代理/网关会把 JSON 错误体当文本塞回来
    try {
      backendMessage = (JSON.parse(data) as { message?: string }).message
    } catch {
      /* 不是 JSON，当没有 message */
    }
  } else if (data && typeof data === 'object' && !(data instanceof Blob)) {
    backendMessage = (data as { message?: string }).message
  }
  throw new Error(backendMessage || '导出失败，请检查网络后重试')
}
