/**
 * 日期选择器的「可选范围」判定。
 *
 * `el-date-picker` 的 `disabled-date` 只拿得到 Date，拿不到时分，
 * 所以这里只管**整天**：
 * - 截止时间不能选昨天及以前（`disablePastDates`）
 * - 发生时间/缴费时间不能选明天及以后（`disableFutureDates`）
 *
 * 今天的具体时分由表单 validator 再卡一次（`isPastDateTime` / `isFutureDateTime`），
 * 否则「今天 00:00」在下午仍然选得中。
 */
import dayjs from 'dayjs'

/** 今天之前的日期不可选（截止时间用） */
export function disablePastDates(date: Date): boolean {
  return dayjs(date).isBefore(dayjs(), 'day')
}

/** 今天之后的日期不可选（发生时间、缴费时间用） */
export function disableFutureDates(date: Date): boolean {
  return dayjs(date).isAfter(dayjs(), 'day')
}

/** 已经过去（含此刻）：截止时间必须晚于它 */
export function isPastDateTime(value: string | null | undefined): boolean {
  return !!value && !dayjs(value).isAfter(dayjs())
}

/** 还没到（此刻之后）：发生时间不能晚于现在 */
export function isFutureDateTime(value: string | null | undefined): boolean {
  return !!value && dayjs(value).isAfter(dayjs())
}
