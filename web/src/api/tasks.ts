import { request } from '@/api/request'
import service from '@/api/request'
import type {
  TaskAnswer,
  TaskCreatePayload,
  TaskDetail,
  TaskListPayload,
  TaskQType,
  TaskUpdatePayload,
} from '@/types'

/**
 * 班级任务（第二十五轮）。
 *
 * 和第二十四轮删掉的班级公告的**唯一区别**：任务发出去之后还要有人回来填答案。
 * 所以这一层要处理三种不同的"看"：
 *
 * | 端点 | 谁能看到 |
 * |------|---------|
 * | `fetchTasks` | 全员（含访客），但**只到汇总为止** |
 * | `fetchTaskDetail` | 仅发布人和班主任 —— 唯一出现别人答案的地方 |
 * | `submitTaskAnswer` | 全员；访客被后端 403 |
 *
 * 列表页对所有人一律只到汇总，所以这里不需要（也不应该）再在前端过滤一遍：
 * 后端已经把非发布人看不到的东西裁掉了，前端再滤一遍只会让人以为"只是没渲染"。
 */

/** 任务列表（含发布权限标记）。每条自带我的答案和汇总。 */
export function fetchTasks() {
  return request<TaskListPayload>({ url: '/tasks', method: 'get' })
}

/** 谁能发这个任务：`TEACHER` / `MONITOR`。非发布人调 `createTask` 会被后端 403。 */
export function publishTask(payload: TaskCreatePayload) {
  return request<{ id: number; title: string }>({
    url: '/tasks',
    method: 'post',
    data: payload,
  })
}

/**
 * 改任务。**刻意不含题型和候选项** —— 换题型会让已收回的答案对不上题，
 * 要换只能删了重发（后端 `TaskUpdateRequest` 同样不收这两个字段）。
 */
export function updateTask(id: number, payload: TaskUpdatePayload) {
  return request<{ id: number; open: boolean }>({
    url: `/tasks/${id}`,
    method: 'put',
    data: payload,
  })
}

/** 关闭 / 重新开放。已收回的回答保留，重新开放后还在。 */
export function setTaskOpen(id: number, open: boolean) {
  return request<{ id: number; open: boolean }>({
    url: `/tasks/${id}/${open ? 'reopen' : 'close'}`,
    method: 'post',
  })
}

/** 删除任务（连带回答）。仅发布人自己。 */
export function deleteTask(id: number) {
  return request<null>({ url: `/tasks/${id}`, method: 'delete' })
}

/**
 * 提交或修改**自己**的答案。一人一任务一条，重复提交是"改"而不是"多一行"。
 *
 * `value` 的形状按题型不同，所以这里是 `unknown`：BOOLEAN 要布尔、SINGLE 要选项**原文**、
 * MULTI 要字符串数组、DATE 要 `YYYY-MM-DD`。传错由后端给中文提示。
 */
export function submitTaskAnswer(id: number, value: unknown, note?: string | null) {
  return request<TaskAnswer>({
    url: `/tasks/${id}/answer`,
    method: 'put',
    data: { value, note: note ?? null },
  })
}

/** 明细：谁填了什么、谁还没填。**非发布人 / 非班主任会拿到 403。** */
export function fetchTaskDetail(id: number) {
  return request<TaskDetail>({ url: `/tasks/${id}/detail`, method: 'get' })
}

/**
 * 导出全班回答（xlsx）。
 *
 * 直接用 axios 实例而不是 `request()`：后者要解 `{code,message,data}` 信封，
 * 而这里是 xlsx 二进制，没有 `code` 字段会被误判成失败。
 */
export async function exportTaskDetail(id: number): Promise<void> {
  const res = await service.get<Blob>(`/tasks/${id}/export`, { responseType: 'blob' })
  const blob = new Blob([res.data], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
  const disposition = String(res.headers?.['content-disposition'] ?? '')
  const matched = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  const filename = matched ? decodeURIComponent(matched[1]) : '任务回答.xlsx'
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

/** 题型枚举。与后端 `task_service.QTYPES` 一一对应。 */
export const TASK_QTYPES: { value: TaskQType; label: string; hint: string }[] = [
  { value: 'BOOLEAN', label: '是 / 否', hint: '点名、统计是否，如「你已经返校了吗？」' },
  { value: 'SINGLE', label: '单选', hint: '从若干候选项里挑一个，如「住校 / 走读 / 请假」' },
  { value: 'MULTI', label: '多选', hint: '可以多选，如返校方式勾「飞机 + 中转」' },
  { value: 'DATE', label: '日期', hint: '填一个具体日期，如「你预计哪天到校？」' },
]