import type { AxiosResponse } from 'axios'
import { ElMessage } from 'element-plus'
import { request } from '@/api/request'
import service from '@/api/request'
import type {
  StudentAccessRequest,
  StudentField,
  StudentFieldRequest,
  StudentGrant,
  StudentImportResult,
  StudentRetypePreview,
  StudentRetypeResult,
  StudentScope,
  StudentSheet,
  StudentFieldType,
} from '@/types'

/**
 * 学生信息（第二十三轮）。
 *
 * **行级权限**：每个人默认只看得到自己那一行，且**只能看、不能改**。
 * 要看别人 / 要改都必须先申请，班主任审批通过后才生效。
 * 后端返回的行**已经裁剪过**，没权限的人根本拿不到别人的学号，
 * 所以这里不需要（也不应该）再在前端做一遍过滤。
 */

/** 学生信息表（含权限快照） */
export function fetchStudents(keyword?: string) {
  return request<StudentSheet>({
    url: '/students',
    method: 'get',
    params: keyword ? { keyword } : undefined,
  })
}

/**
 * 手工新增一行（不靠 Excel）。
 *
 * 只要**学号 + 姓名**就能建行——这两列是锚点，缺了就没法定位"这是谁的行"。
 * 其余字段留空是常态：先把人加进来，细节在表格里逐格填（像 Excel 插一行）。
 *
 * **不会创建登录账号**：加一个学生 ≠ 给这个人开权限。账号仍由班主任在
 * 「成员管理」单独建，行级可见性仍走申请/审批。
 */
export function createStudent(
  studentNo: string,
  name: string,
  values?: Record<string, string | null>,
) {
  return request<{ id: number; studentNo: string; name: string }>({
    url: '/students',
    method: 'post',
    data: { studentNo, name, values: values ?? {} },
  })
}

/**
 * 就地编辑一格（表格编辑模式）。
 *
 * 三种写法，不要混用：
 * - 改普通字段：`updateStudent(id, { gender: '男' })`
 * - 改姓名：    `updateStudent(id, {}, { name: '张三' })`
 * - 改学号：    `updateStudent(id, {}, { studentNo: '20230001' })`
 *
 * 锚点两列不在字段表里，走独立字段；班内撞号由后端拒绝。
 */
export function updateStudent(
  id: number,
  values: Record<string, string | null>,
  anchor?: { name?: string; studentNo?: string },
) {
  return request<{ ok: boolean }>({
    url: `/students/${id}`,
    method: 'put',
    data: { values, ...(anchor ?? {}) },
  })
}

/**
 * 字段定义列表。`includeDisabled=true` 时带上已停用的（恢复面板用）。
 *
 * 默认只给启用的——表格、导出、导入匹配都按"用户看得见的列"走。
 */
export function fetchStudentFields(includeDisabled = false) {
  return request<StudentField[]>({
    url: '/students/fields',
    method: 'get',
    params: includeDisabled ? { includeDisabled: true } : undefined,
  })
}

/**
 * 新增字段（班主任 / 班长）。
 *
 * `beforeKey` = 插在哪一列**之前**，对应表头上那个 `＋` 的字面意思。
 * 不传 = 追加到末尾。表格没有单独的"末尾新增"按钮——加了会在最后一行后面
 * 多出一截空白，而"插在最后一列前面"本来就等于追加到末尾。
 */
export function createStudentField(
  data: StudentFieldRequest,
  beforeKey?: string | null,
) {
  return request<StudentField>({
    url: '/students/fields',
    method: 'post',
    params: beforeKey ? { beforeKey } : undefined,
    data,
  })
}

/**
 * 改字段的显示名 / 类型 / 排序。**按字段标识 key 定位**（模板字段也能改）。
 */
export function updateStudentField(key: string, data: StudentFieldRequest) {
  return request<StudentField>({
    url: `/students/fields/${encodeURIComponent(key)}`,
    method: 'put',
    data,
  })
}

/**
 * 停用字段（软删，值保留）。**模板字段也允许停用**。
 *
 * 传的是**字段标识 key** 而不是 id —— 表格里每列的增删按钮拿到的是 key，
 * 让前端为了删一列去反查 id 是没必要的绕路，后端按 key 定位即可。
 */
export function deleteStudentField(key: string) {
  return request<void>({ url: `/students/fields/${encodeURIComponent(key)}`, method: 'delete' })
}

/**
 * 改类型前的预览：**不写库**，只算一遍存量值会变成什么。
 *
 * 改类型要同步转换已填的值，而有的值转不了（"待定"没法变日期）。
 * 先把这笔账摊开给用户看，确认了再调 apply，别让转换静默毁数据。
 */
export function previewStudentFieldRetype(key: string, toType: StudentFieldType) {
  return request<StudentRetypePreview>({
    url: `/students/fields/${encodeURIComponent(key)}/retype-preview`,
    method: 'get',
    params: { toType },
  })
}

/**
 * 确认改类型。
 *
 * `clearUnconvertible=false`（默认）——转不了的值**保留原文本**，
 * 改错了还能改回来。设 true 则置空。
 */
export function applyStudentFieldRetype(
  key: string,
  toType: StudentFieldType,
  clearUnconvertible = false,
) {
  return request<StudentRetypeResult>({
    url: `/students/fields/${encodeURIComponent(key)}/retype`,
    method: 'post',
    data: { toType, clearUnconvertible },
  })
}

/** 把停用的字段重新启用。软删保住了值，这是误删的退路。 */
export function restoreStudentField(key: string) {
  return request<StudentField>({
    url: `/students/fields/${encodeURIComponent(key)}/restore`,
    method: 'post',
  })
}

/**
 * 导入 xlsx 名单。
 *
 * 学号是 upsert 键；**空单元格不覆盖**旧值。
 * 导入**不创建登录账号**——账号仍由班主任在「成员管理」单独建。
 */
export function importStudents(file: File) {
  const form = new FormData()
  form.append('file', file)
  return request<StudentImportResult>({
    url: '/students/import',
    method: 'post',
    data: form,
  })
}

/**
 * 导出（内容 = 当前用户的可见范围；看不到的行不会出现在文件里）。
 *
 * 直接用 axios 实例而不是 `request()`：后者要解 `{code,message,data}` 信封，
 * 而这里是 xlsx 二进制，没有 `code` 字段会被误判成失败。
 */
export async function exportStudents(): Promise<void> {
  await downloadXlsx(
    service.get<Blob>('/students/export', { responseType: 'blob' }),
  )
}

/**
 * **勾选导出**（第二十四轮）：行和列都可以只导一部分。
 *
 * 走 POST 而不是 `GET /export?ids=1,2,3`：勾几十个人时 URL 放不下，
 * 而且 id 列表放 URL 里会被浏览历史、代理日志记下来。
 *
 * 服务端会把不在可见范围内的 id 过滤掉，所以这**不是**绕过可见性的口子。
 * 学号/姓名是锚点列，传不传 `fieldKeys` 都会保留。
 */
export async function exportSelectedStudents(
  opts: { recordIds?: number[]; fieldKeys?: string[] } = {},
): Promise<void> {
  const recordIds = opts.recordIds ?? []
  const fieldKeys = opts.fieldKeys ?? []
  if (!recordIds.length && !fieldKeys.length) {
    ElMessage.warning('请先勾选要导出的学生或字段')
    return
  }
  await downloadXlsx(
    service.post<Blob>('/students/export', { recordIds, fieldKeys }, { responseType: 'blob' }),
  )
}

/** 把 xlsx 响应变成浏览器下载。中文文件名走 RFC 5987 的 filename* */
async function downloadXlsx(req: Promise<AxiosResponse<Blob>>): Promise<void> {
  const res = await req
  const blob = new Blob([res.data], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
  // axios 的 headers 类型是 AxiosResponseHeaders，值可能是 string[] / undefined，
  // 所以只能按 unknown 取——原代码就是 `res.headers['content-disposition'] ?? ''`，
  // 这次只是把整体类型标成 AxiosResponse，别收紧到 Record<string,string>。
  const disposition = String(res.headers?.['content-disposition'] ?? '')
  const matched = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  const filename = matched ? decodeURIComponent(matched[1]) : '学生信息.xlsx'
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

/** 我提交的申请（mine=true） */
export function fetchMyRequests() {
  return request<StudentAccessRequest[]>({
    url: '/students/requests',
    method: 'get',
    params: { mine: true },
  })
}

/** 待审批收件箱（仅班主任） */
export function fetchPendingRequests() {
  return request<StudentAccessRequest[]>({ url: '/students/requests', method: 'get' })
}

/** 提交申请 */
export function createStudentRequest(scope: StudentScope, reason?: string) {
  return request<{ id: number }>({
    url: '/students/requests',
    method: 'post',
    data: { scope, reason },
  })
}

/** 审批（仅班主任）。approve=false 即拒绝。 */
export function handleStudentRequest(
  id: number,
  approve: boolean,
  reply?: string,
) {
  return request<{ ok: boolean }>({
    url: `/students/requests/${id}/handle`,
    method: 'post',
    data: { approve, reply },
  })
}

/** 已生效的授权清单（仅班主任） */
export function fetchStudentGrants() {
  return request<StudentGrant[]>({ url: '/students/grants', method: 'get' })
}

/** 撤销授权（仅班主任） */
export function revokeStudentGrant(userId: number, scope: StudentScope) {
  return request<void>({
    url: `/students/grants/${userId}/${scope}`,
    method: 'delete',
  })
}

/** 顶栏红点：待审批条数（非班主任恒为 0） */
export function fetchStudentPendingCount() {
  return request<{ count: number }>({
    url: '/students/pending-count',
    method: 'get',
  })
}