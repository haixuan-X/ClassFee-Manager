import { request, service } from '@/api/request'
import { downloadXlsx, exportFailure } from '@/utils/download'
import type {
  TaskAnswer,
  TaskCreatePayload,
  TaskDetail,
  TaskListPayload,
  TaskOverviewPayload,
  TaskPinnedPayload,
  TaskQType,
  TaskUpdatePayload,
  TaskView,
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

/**
 * 任务列表（含发布权限标记）。每条自带我的答案和汇总。
 *
 * iew 决定看哪一块（第三十二轮）：
 * - mine（默认）：**本班**的任务 + **学院**的任务
 * - college：只看学院任务
 * - other：**其他班**班主任发出来的（只读）
 */
export function fetchTasks(view: TaskView = 'mine') {
  return request<TaskListPayload>({ url: '/tasks', method: 'get', params: { view } })
}

/**
 * 任务总览（第三十二轮）：统计「现在什么状况」——
 * 多少条、还开着几条、回收率、按班/按发布人的分布、最近任务。
 */
export function fetchTaskOverview() {
  return request<TaskOverviewPayload>({ url: '/tasks/overview', method: 'get' })
}

/**
 * 仪表盘「置顶任务」面板的数据源。
 *
 * 形状与可见性口径都和 `fetchTasks` **完全一致**（后端两个端点共用同一个
 * `_build_rows`），所以这里不要在前端再做一遍过滤。
 *
 * 只含**置顶且还在开放**的，最多 3 条，快到期的排前面；关闭掉的任务会
 * 自动从面板消失——置顶是为了催人填，填完了就不该继续占着仪表盘。
 */
export function fetchPinnedTasks() {
  return request<TaskPinnedPayload>({ url: '/tasks/pinned', method: 'get' })
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

/**
 * 置顶 / 取消置顶：出现在**所有人**仪表盘的「置顶任务」里。**仅发布人自己**。
 *
 * 占用的是全班人的仪表盘，所以权限跟改标题、关闭是同一档，不能只按
 * 「能不能发布任务」放行。
 */
export function setTaskPinned(id: number, pinned: boolean) {
  return request<{ id: number; pinned: boolean }>({
    url: `/tasks/${id}/${pinned ? 'pin' : 'unpin'}`,
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
 * xlsx 下载的两个小工具（触发下载 / 把失败翻成中文错误）共用一份，
 * 放在 `utils/download.ts`——学生名册、账本、学院名册的导出也在用。
 *
 * 不带 `filter` 走 GET（全量，和以前一样）；带 `filter` 走 POST（**按状态筛选**，
 * 第四十九轮）——照 `/students/export` 的既有惯例：GET=全量、POST=子集。
 * `recordIds` 是前端按状态算好的行 id，后端只做集合过滤、不认语义。
 */
export interface TaskExportFilter {
  /** 只导这些行（仪表盘里当前筛选命中的学生） */
  recordIds: number[]
  /** 筛选名（「未返校」），只用于文件名和表内副标题 */
  label: string
}

export async function exportTaskDetail(id: number, filter?: TaskExportFilter): Promise<void> {
  try {
    const res = filter
      ? await service.post<Blob>(`/tasks/${id}/export`, filter, { responseType: 'blob' })
      : await service.get<Blob>(`/tasks/${id}/export`, { responseType: 'blob' })
    downloadXlsx(res, filter ? `任务回答-${filter.label}.xlsx` : '任务回答.xlsx')
  } catch (error) {
    exportFailure(error)
  }
}

/** 导出**任务总览**（所有任务一览 + 回收情况），仅院长。 */
export async function exportTaskOverview(): Promise<void> {
  try {
    const res = await service.get<Blob>('/tasks/overview/export', { responseType: 'blob' })
    downloadXlsx(res, '任务总览.xlsx')
  } catch (error) {
    exportFailure(error)
  }
}

/** 导出**自己班**的点名结果（班主任专用，第四十五轮）。 */
export async function exportTaskRollcall(id: number, classId?: number): Promise<void> {
  try {
    const res = await service.get<Blob>(`/tasks/${id}/rollcall/export`, {
      responseType: 'blob',
      params: { classId: classId ?? undefined },
    })
    downloadXlsx(res, '点名结果.xlsx')
  } catch (error) {
    exportFailure(error)
  }
}

/** 点名页的一个学生行（第四十五轮：学院任务按学生逐个标记） */
export interface TaskRollcallRow {
  recordId: number
  studentNo: string
  name: string
  /** 这个学生当前的状态（未填 = null） */
  value: string | null
  raw: string | null
  note: string | null
  submittedAt: string | null
}

/** 点名页：一个班的学生名册 + 当前状态 */
export interface TaskRollcall {
  taskId: number
  title: string
  question: string
  qtype: TaskQType
  qtypeText: string
  allowText: boolean
  deadline: string | null
  open: boolean
  /** SINGLE/MULTI 的候选项（BOOLEAN/DATE 为空数组） */
  options: string[]
  classId: number
  className: string
  /** 我能管的、有学生的班（多个时前端给切换器） */
  classes: { classId: number; className: string }[]
  rows: TaskRollcallRow[]
  total: number
  answered: number
  unanswered: number
}

/** 打开点名页（班主任视角）。`classId` 不传就取第一个有学生的班。 */
export function fetchTaskRollcall(id: number, classId?: number) {
  return request<TaskRollcall>({
    url: `/tasks/${id}/rollcall`,
    method: 'get',
    params: { classId: classId ?? undefined },
  })
}

/**
 * 给**一个学生**打状态。一次一个人，标几个存几个，下次接着标。
 *
 * 重复提交是「改」（后端 `uk_task_record`），所以前端可以放心乐观更新。
 */
export function saveStudentAnswer(
  taskId: number,
  recordId: number,
  value: unknown,
  note?: string,
) {
  return request<{
    taskId: number
    recordId: number
    value: string
    raw: string | null
    note: string | null
    submittedAt: string
  }>({
    url: `/tasks/${taskId}/rollcall/${recordId}`,
    method: 'put',
    data: { value, note: note ?? null },
  })
}

/**
 * **批量**保存点名结果：一次请求存多个学生（第四十六轮）。
 *
 * 一个班几十人，逐个 PUT 是几十次往返；点名页的「保存全部」走这条。
 *
 * ⚠ 后端是**整批要么全成要么全不动**——任何一条不合法就 400，一条都不写。
 * 所以调用方失败时**不能清本地草稿**，否则界面显示成已存、实际一个字没存。
 */
export function saveStudentAnswers(
  taskId: number,
  items: { recordId: number; value: unknown; note?: string }[],
) {
  return request<{ taskId: number; saved: number }>({
    url: `/tasks/${taskId}/rollcall`,
    method: 'put',
    data: { items: items.map((it) => ({ recordId: it.recordId, value: it.value, note: it.note ?? null })) },
  })
}

/** 题型枚举。与后端 `task_service.QTYPES` 一一对应。 */
export const TASK_QTYPES: { value: TaskQType; label: string; hint: string }[] = [
  { value: 'BOOLEAN', label: '是 / 否', hint: '点名、统计是否，如「你已经返校了吗？」' },
  { value: 'SINGLE', label: '单选', hint: '从若干候选项里挑一个，如「住校 / 走读 / 请假」' },
  { value: 'MULTI', label: '多选', hint: '可以多选，如返校方式勾「飞机 + 中转」' },
  { value: 'DATE', label: '日期', hint: '填一个具体日期，如「你预计哪天到校？」' },
]