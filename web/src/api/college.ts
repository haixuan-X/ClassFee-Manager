import { request, service } from '@/api/request'
import { downloadXlsx, exportFailure } from '@/utils/download'
import type {
  CollegeAdviserList,
  CollegeFieldList,
  CollegeImportResult,
  CollegeRetypePreview,
  CollegeStudentColumn,
  CollegeStudentList,
  CollegeTaskList,
  StudentFieldType,
} from '@/types'

/**
 * 学院视角的接口（第三十轮）。**仅院长**——后端 `require_min_level` 硬拦 403。
 *
 * 前端也**不渲染**入口（侧栏的「学院」分组对非院长整个不出现）。
 */

/** 学院学生名册：跨班级，可按关键字/班级/年级筛选 */
export function fetchCollegeStudents(params: {
  keyword?: string
  classId?: number | null
  grade?: string | null
  page?: number
  size?: number
}) {
  return request<CollegeStudentList>({
    url: '/college/students',
    method: 'get',
    params: {
      keyword: params.keyword || undefined,
      classId: params.classId ?? undefined,
      grade: params.grade || undefined,
      page: params.page ?? 1,
      size: params.size ?? 50,
    },
  })
}

/** 班主任（导员）名册：各班一行 */
export function fetchCollegeAdvisers() {
  return request<CollegeAdviserList>({ url: '/college/advisers', method: 'get' })
}

/** 导入班主任账号（Excel）：姓名 / 登录名 / 初始密码 / 手机号 / 带的班 */
export function importCollegeAdvisers(file: File) {
  const fd = new FormData()
  fd.append('file', file)
  return request<{
    created: number
    updated: number
    skipped: number
    errors: string[]
    errorCount: number
  }>({
    url: '/college/advisers/import',
    method: 'post',
    data: fd,
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

/** 下载班主任导入模板（xlsx） */
export async function downloadAdviserTemplate(): Promise<void> {
  try {
    const res = await service.get<Blob>('/college/advisers/template', { responseType: 'blob' })
    downloadXlsx(res, '班主任导入模板.xlsx')
  } catch (error) {
    exportFailure(error)
  }
}

/**
 * 可被选为班主任的账号（第三十二轮）。
 *
 * 「班主任」是**班**的属性：一个人可以带好几个班，一个班也可以有
 * 正、副两个班主任。这在以前「一个账号只能属于一个班」的模型里表达不出来。
 */
export function fetchCollegeTeacherCandidates() {
  return request<{
    teachers: { id: number; username: string; realName: string; role: string }[]
  }>({ url: '/college/teacher-candidates', method: 'get' })
}

/**
 * 设置某个班的班主任（**可以多个**）。
 *
 * 顺带把账号的默认班（`sys_user.class_id`）对齐到这个班——
 * 它是「登录后落在哪个班」，不能和实际安排矛盾。
 */
export function setCollegeClassTeachers(classId: number, teacherIds: number[]) {
  return request<{ classId: number; className: string; teacherIds: number[] }>({
    url: `/college/classes/${classId}/teachers`,
    method: 'put',
    data: { teacherIds },
  })
}

/**
 * 导出学院学生信息（**可选列**）。
 *
 * `columns` 是勾选框选中的字段标识；**学号/姓名无条件保留**
 * （一份没有学号的表没法说明每一行是谁），班级/年级听勾选。
 *
 * `keyword` / `classId` / `grade` **和界面上的筛选一致**——
 * 界面上筛出来的就该是导出来的。
 *
 * 直接用 axios 实例而不是 `request()`：后者要解 `{code,message,data}` 信封，
 * 而这里是 xlsx 二进制，没有 `code` 字段会被误判成失败。
 */
export async function exportCollegeStudents(params: {
  columns: string[]
  ids?: number[]
  keyword?: string
  classId?: number | null
  grade?: string
  /** 按行区间导出：从第 offset 条（0 起）开始，最多 limit 条 */
  offset?: number
  limit?: number
}): Promise<void> {
  try {
    const res = await service.get<Blob>('/college/students/export', {
      responseType: 'blob',
      params: {
        columns: params.columns.join(',') || undefined,
        ids: params.ids?.length ? params.ids.join(',') : undefined,
        keyword: params.keyword || undefined,
        classId: params.classId ?? undefined,
        grade: params.grade || undefined,
        offset: params.offset ?? undefined,
        limit: params.limit ?? undefined,
      },
    })
    downloadXlsx(res, '学院学生信息.xlsx')
  } catch (error) {
    exportFailure(error)
  }
}

/**
 * 下载学院名册的**导入模板**（列 = 所有启用班级的字段合并，另加「班级」列）。
 *
 * 每次下载现读字段，学院里新增一列后重新下载就是新列。
 * 填完直接走 `importCollegeStudents` 传回来：有「班级」列就按行分发到各班。
 */
export async function downloadCollegeStudentTemplate(): Promise<void> {
  try {
    const res = await service.get<Blob>('/college/students/template', {
      responseType: 'blob',
    })
    downloadXlsx(res, '学院学生名册导入模板.xlsx')
  } catch (error) {
    exportFailure(error)
  }
}

/**
 * 导入学院学生信息。
 *
 * 文件里有「班级」列 → 每一行按自己的班级走；没有 → 全进 `classId` 指定的班。
 * 某行的班级名在库里找不到 → 那一行跳过并报错（**不静默塞进别的班**：
 * 塞错班比不导更糟，人就找不到了）。
 */
export function importCollegeStudents(file: File, classId?: number | null) {
  const form = new FormData()
  form.append('file', file)
  if (classId) form.append('classId', String(classId))
  return request<CollegeImportResult>({
    url: '/college/students/import',
    method: 'post',
    data: form,
  })
}

/** 学院列定义（各班的字段按 field_key 合并成一份） */
export function fetchCollegeFields() {
  return request<CollegeFieldList>({ url: '/college/fields', method: 'get' })
}

/**
 * 新增一列（**所有班各建一份，key 相同**）。
 *
 * `anchorKey` + `side` 指定插在哪：锚点列的前面（before）或后面（after）。
 * 不给锚点 = 追加到末尾。
 */
export function createCollegeField(data: {
  label: string
  type: StudentFieldType
  anchorKey?: string | null
  side?: 'before' | 'after'
}) {
  return request<{ key: string; label: string; type: string; classCount: number }>({
    url: '/college/fields',
    method: 'post',
    data,
  })
}

/** 改一列（所有班） */
export function updateCollegeField(
  key: string,
  data: { label?: string; type?: StudentFieldType },
) {
  return request<{ key: string; label: string; type: string; classCount: number }>({
    url: `/college/fields/${encodeURIComponent(key)}`,
    method: 'put',
    data,
  })
}

/** 停用一列（所有班，软删：已填的值保留） */
export function deleteCollegeField(key: string) {
  return request<{ key: string; classCount: number }>({
    url: `/college/fields/${encodeURIComponent(key)}`,
    method: 'delete',
  })
}

/**
 * 已停用的列（软删的值还在这里，可以一键恢复）。
 *
 * 没有这条路，误停用一列就等于把那一列的历史数据永远藏起来了。
 */
export function fetchCollegeDisabledFields() {
  return request<{ columns: CollegeStudentColumn[] }>({
    url: '/college/fields/disabled',
    method: 'get',
  })
}

/** 恢复一个被停用的列（所有班一起放回来，值原样还在） */
export function restoreCollegeField(key: string) {
  return request<{ key: string; label: string; classCount: number; restored: number }>({
    url: `/college/fields/${encodeURIComponent(key)}/restore`,
    method: 'post',
  })
}

/**
 * 彻底删除**已停用**的列（所有班一起删）：字段定义和值一起删，不可恢复。
 * 后端只放行所有班都已停用的 key——和停用/恢复一样，这条是跨班操作。
 */
export function purgeCollegeField(key: string) {
  return request<{ key: string; label: string; classCount: number; deletedValues: number }>({
    url: `/college/fields/${encodeURIComponent(key)}/purge`,
    method: 'delete',
  })
}

/** 改类型前的预览（不写库）。跨所有班汇总。 */
export function previewCollegeFieldRetype(key: string, toType: string) {
  return request<CollegeRetypePreview>({
    url: `/college/fields/${encodeURIComponent(key)}/retype-preview`,
    method: 'get',
    params: { toType },
  })
}

/** 确认改类型（所有班一起改） */
export function applyCollegeFieldRetype(
  key: string,
  toType: string,
  clearBad = false,
) {
  return request<{
    key: string
    label: string
    toType: string
    classCount: number
    convertedCount: number
    keptUnconvertibleCount: number
    clearedCount: number
  }>({
    url: `/college/fields/${encodeURIComponent(key)}/retype`,
    method: 'post',
    data: { toType, clearBad },
  })
}

/**
 * 就地改一格（或几格）——电子表格的保存。
 *
 * `values` 是 `{字段标识: 值}`。**整批原子**：任一格非法就整批不落库
 * （表格里一次改多格很常见，写一半会让界面显示的和库里不一致）。
 *
 * `name` / `studentNo` / `className` 改的是 `student_record` / `cls_class`
 * 上的几列（它们不在字段表里）：
 * - `className`：**按名字**改班级。后端会把他那些值**按列名搬到新班**
 *   （一个不丢），库里没这个班就**自动建一个**。
 */
export function updateCollegeCell(
  recordId: number,
  values: Record<string, string>,
  extra?: { name?: string; studentNo?: string; className?: string },
) {
  return request<{
    id: number
    updated: number
    name: string
    studentNo: string
    className: string | null
  }>({
    url: `/college/students/${recordId}`,
    method: 'put',
    data: { values, ...(extra ?? {}) },
  })
}

/**
 * 新建一个班（**仅院长**）。
 *
 * 新班是空班，字段模板复制调用者默认班那份，所以建完直接能用。
 * 同名班不会报错，后端把已有的那个返回来（`created=false`）。
 */
export function createCollegeClass(className: string, grade = '') {
  return request<{
    id: number
    className: string
    grade: string
    created: boolean
    fieldsCopied: number
  }>({
    url: '/college/classes',
    method: 'post',
    data: { className, grade },
  })
}

/**
 * 从学院名册里删行（**可批量**）。
 *
 * 删的是学生记录 + 他填过的所有字段值；**登录账号不动**（账号归「成员管理」）。
 * 不可撤销，调用前必须让用户确认过。
 */
export function deleteCollegeStudents(ids: number[]) {
  return request<{ deleted: number; ids: number[] }>({
    url: '/college/students',
    method: 'delete',
    params: { ids: ids.join(',') },
  })
}

/**
 * 转班：把一个学生挪到另一个班。
 *
 * ⚠ **不是「改一格」**：值表里存的是 `field_id`，而字段是**按班**定义的，
 * 所以后端必须按 `field_key` 把值搬到新班对应的字段上（目标班缺哪一列
 * 就按原样补建一列），不能只把 `class_id` 一改了事。
 */
export function transferCollegeStudent(recordId: number, classId: number) {
  return request<{
    id: number
    name: string
    studentNo: string
    fromClassName: string
    targetClassName: string
    movedValues: number
    createdFields: number
    userMoved: boolean
  }>({
    url: `/college/students/${recordId}/transfer`,
    method: 'post',
    data: { classId },
  })
}

/**
 * 学院视角的任务一览：跨班级。
 *
 * `scope` 决定看哪一类（第三十二轮）：
 * - `COLLEGE`：**学院任务**（院长发到全学院的，各班班主任应答）
 * - `CLASS`：**班主任发布的班级任务**（各班自己发的，同学应答）
 * - `ALL`：两类都看
 */
export function fetchCollegeTasks(params: {
  keyword?: string
  classId?: number | null
  onlyPinned?: boolean
  scope?: 'COLLEGE' | 'CLASS' | 'ALL'
}) {
  return request<CollegeTaskList>({
    url: '/college/tasks',
    method: 'get',
    params: {
      keyword: params.keyword || undefined,
      classId: params.classId ?? undefined,
      onlyPinned: params.onlyPinned || undefined,
      scope: params.scope ?? 'ALL',
    },
  })
}
