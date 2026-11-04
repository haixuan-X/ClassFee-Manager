import service, { request } from '@/api/request'

/** 单张小票大小上限（与后端 file_service.MAX_RECEIPT_BYTES 一致） */
export const MAX_RECEIPT_BYTES = 5 * 1024 * 1024

/** 允许的小票格式（后端按魔数嗅探，改这里需同步 file_service） */
export const RECEIPT_ACCEPT = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']

/**
 * 上传小票图片（ADMIN/MONITOR/TEACHER），返回服务端相对路径 receipts/<uuid>.<ext>。
 * 走 FormData，axios 自动带边界；路径随后放进 POST /api/records 的 receiptUrl。
 */
export function uploadReceipt(file: File) {
  const form = new FormData()
  form.append('file', file)
  return request<{ path: string }>({
    url: '/files',
    method: 'post',
    data: form,
    headers: { 'Content-Type': 'multipart/form-data' },
    // 线上实测「timeout of 10000ms exceeded」：共享实例 10s 不够原图上传。
    // （提交前还会走 compressReceiptImage 压缩；这里再兜一层。）
    timeout: 60_000,
  })
}

/**
 * 拉取受保护的小票图片为 Blob：/api/files/* 需要 Authorization，
 * <img src> 带不了请求头，统一在这里带 token 取回后转 objectURL 展示。
 */
export async function fetchReceipt(path: string): Promise<Blob> {
  // 查看同样放宽到 60s：5MB 小票慢网络下 10s 拉不完，
  // 会被误报成「小票文件已删除」（同一句文案，两个完全不同的原因）
  const res = await service.get<Blob>(`/files/${path}`, {
    responseType: 'blob',
    timeout: 60_000,
  })
  return res.data
}
