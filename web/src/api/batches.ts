import { request } from '@/api/request'
import type {
  Batch,
  BatchDetail,
  BatchRequest,
  MemberQuery,
  MemberRow,
  MyBatch,
  PayRequest,
} from '@/types'

/** 批次列表（含人数与完成率，ADMIN） */
export function fetchBatches() {
  return request<Batch[]>({ url: '/batches', method: 'get' })
}

/**
 * 「我的缴费」：第十八轮新增。
 * 后端对非运营角色返回**精简 VO + 自己的缴费状态**（不含 createdBy、不含他人信息），
 * 运营角色拿到的是完整 VO —— 同一个接口，按角色裁剪，所以这里用联合类型。
 */
export function fetchMyBatches() {
  return request<MyBatch[]>({ url: '/batches', method: 'get' })
}

/** 新建批次（ADMIN/MONITOR/TEACHER） */
export function createBatch(data: BatchRequest) {
  return request<Batch>({ url: '/batches', method: 'post', data })
}

/** 批次详情：逐人缴费明细（ADMIN/MONITOR/TEACHER） */
export function fetchBatchDetail(id: number) {
  return request<BatchDetail>({ url: `/batches/${id}/payments`, method: 'get' })
}

/** 标记某人已交 → 后端同事务生成流水（ADMIN/MONITOR/TEACHER） */
export function payBatchMember(id: number, data: PayRequest) {
  return request<void>({ url: `/batches/${id}/pay`, method: 'post', data })
}

/** 关闭批次（ADMIN/MONITOR/TEACHER） */
export function closeBatch(id: number) {
  return request<void>({ url: `/batches/${id}/close`, method: 'post' })
}

/** 删除批次（ADMIN/MONITOR/TEACHER）：级联清理缴费状态与全部流水，正常流水余额回滚 */
export function deleteBatch(id: number) {
  return request<void>({ url: `/batches/${id}`, method: 'delete' })
}

/** 成员列表 + 缴费状态（ADMIN/MONITOR/TEACHER） */
export function fetchMembers(query: MemberQuery) {
  return request<MemberRow[]>({ url: '/members', method: 'get', params: query })
}
