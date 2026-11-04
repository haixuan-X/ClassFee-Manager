/**
 * 小票图片的本地压缩（提交时用）。
 *
 * 为什么需要（线上实测）：手机拍的收据原图动辄 3–8MB，
 * 共享 axios 实例的 10s 超时 + 普通网络，上传经常被客户端中断——
 * 班主任点「确认缴费」看到「网络异常」，其实文件可能已经被后端收下
 * （留下盘上的孤儿文件），重试一次反而成功。
 *
 * 提交前等比缩到最长边 1600px、JPEG q=0.8：收据/截图场景
 * 体积通常会压到 200–800KB，上传不再是瓶颈。
 *
 * 退路都是「原样用原图」，绝不阻断提交流程：
 * - GIF：canvas 会丢动画，原样上传
 * - 原图已很小（长边 ≤1600 且 <1MB）：不重编码，免得把清晰的 PNG 截图转成 JPEG 糊掉
 * - 解码失败 / canvas 编码失败 / 压了反而更大：都用原图
 */
export const RECEIPT_MAX_EDGE = 1600
export const RECEIPT_JPEG_QUALITY = 0.8
/** 压缩前的原图上限：手机原图常见 3–9MB，放宽到 20MB；后端仍只收 5MB（压缩后） */
export const RECEIPT_ORIGINAL_MAX_BYTES = 20 * 1024 * 1024

export async function compressReceiptImage(file: File): Promise<File> {
  if (/^image\/gif/i.test(file.type)) return file
  try {
    const bitmap = await createImageBitmap(file)
    const { width, height } = bitmap
    const scale = Math.min(1, RECEIPT_MAX_EDGE / Math.max(width, height))
    if (scale >= 1 && file.size <= 1024 * 1024) {
      bitmap.close()
      return file
    }
    const w = Math.max(1, Math.round(width * scale))
    const h = Math.max(1, Math.round(height * scale))
    const canvas = document.createElement('canvas')
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      bitmap.close()
      return file
    }
    // 白底：透明 PNG → JPEG 会变黑底
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, w, h)
    ctx.drawImage(bitmap, 0, 0, w, h)
    bitmap.close()
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, 'image/jpeg', RECEIPT_JPEG_QUALITY),
    )
    if (!blob || blob.size >= file.size) return file
    const baseName = file.name.replace(/\.[^.]+$/, '') || 'receipt'
    return new File([blob], `${baseName}.jpg`, { type: 'image/jpeg', lastModified: Date.now() })
  } catch {
    return file
  }
}
