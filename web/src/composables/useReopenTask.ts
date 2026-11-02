import { ElMessage, ElMessageBox } from 'element-plus'
import { getErrorMessage } from '@/api/request'
import { setTaskOpen } from '@/api/tasks'

/** 截止时间格式：`YYYY-MM-DD HH:mm`（和后端 `_parse_deadline` 同一份口径） */
const PATTERN = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/

/** 今天 23:59 —— 「重开并延长」的默认值：当天还能收，不用想 */
function tonight(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} 23:59`
}

/** 本地时间里这个截止是不是已经过了（列表上的「已关闭」也按这个判） */
function isExpired(deadline: string | null): boolean {
  if (!deadline) return false
  return new Date(deadline.replace(' ', 'T')).getTime() < Date.now()
}

/**
 * 关闭 / 重开一个任务（两个任务列表页共用这一份逻辑）。
 *
 * ## 为什么重开时要问截止时间（第五十七轮）
 *
 * 「能不能答题」是**两个闸门**：`status`（人手动开的）**和** `deadline`
 * （到点自动关）。截止已过的任务只把 status 打开，`is_open` 仍然是 False——
 * 列表照样显示「已关闭」，班主任照样填不了，而提示说「已重新开放」，
 * 用户只会觉得点了没反应。
 *
 * 所以截止已过时，重开弹一个框把新截止一起给（默认今天 23:59），
 * 一次请求把两个闸门都打开。没过期就直接重开，不多问一句。
 */
export async function toggleTaskOpen(row: {
  id: number
  open: boolean
  deadline: string | null
}): Promise<void> {
  try {
    if (row.open) {
      await setTaskOpen(row.id, false)
      ElMessage.success('任务已关闭')
      return
    }
    if (isExpired(row.deadline)) {
      let deadline = ''
      try {
        const r = await ElMessageBox.prompt(
          `截止时间 ${row.deadline} 已过，重开后仍不能答题。\n` +
            '把截止时间延到下面这个时间，才真的能收：',
          '重开并延长截止时间',
          {
            inputValue: tonight(),
            inputPattern: PATTERN,
            inputErrorMessage: '格式应为 YYYY-MM-DD HH:mm',
            confirmButtonText: '重开并延长',
            cancelButtonText: '取消',
          },
        )
        deadline = String(r.value).trim()
      } catch {
        return // 用户取消
      }
      await setTaskOpen(row.id, true, deadline)
      ElMessage.success(`任务已重新开放，截止时间延到 ${deadline}`)
      return
    }
    await setTaskOpen(row.id, true)
    ElMessage.success('任务已重新开放')
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '操作失败'))
  }
}
