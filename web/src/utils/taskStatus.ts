/**
 * 把任务的**状态原文**归到「返校情况」的几个桶里（第四十八轮）。
 *
 * 任务的状态值是**发布人自己填的**——可以是「是/否」，也可以是
 * 「到校/未到/请假」，后端只存原文、不认语义（`_display_value` 原样返回）。
 * 院长要看的却是「谁没返校」，所以得把任意文案翻成固定几个桶。
 *
 * ## 口径（定过的，不是拍脑袋）
 *
 * | 桶 | 包含什么 |
 * |---|---|
 * | `absent` 未返校 | 填了否定状态（否 / 未到 / 缺席…）**+ 还没填的** |
 * | `excused` 请假 | 请假 / 病假 / 事假 —— **不算未返校**（没到校但有正当理由，单独一栏） |
 * | `returned` 已返校 | 是 / 到校 / 已返校 / 正常… |
 * | `other` 其它状态 | **认不出来的文案**，单独一栏 |
 *
 * `other` 那一栏看着多余，其实是最要紧的一条：猜不准的**绝不硬塞**进上面三个桶。
 * 塞错了，院长会拿着错的名单去催人——「你孩子没返校」结果人家到了。
 * 认不出就摆出来，让人自己看图例判断。
 *
 * ## 判定顺序不能换：请假 → 未返校 → 已返校
 *
 * 「未到校」同时含「未到」和「到校」，「未返校」同时含「未返」和「返校」。
 * 先判否定词，这两个才归得到未返校；反过来先匹配「到校」，
 * 「未到校」会被算成已到——那正是要防的那个错。
 *
 * 同理「请假未到」按顺序先落请假桶：既没到校，又不是无故缺席。
 */

/** 返校情况的四个桶 */
export type ReturnBucket = 'returned' | 'absent' | 'excused' | 'other'

/** 每个桶给人看的名字和颜色基调（颜色另配，见组件里的 `--tone-*`） */
export const BUCKET_META: Record<ReturnBucket, { label: string; tone: 'ok' | 'bad' | 'warn' | 'muted' }> = {
  returned: { label: '已返校', tone: 'ok' },
  absent: { label: '未返校', tone: 'bad' },
  excused: { label: '请假', tone: 'warn' },
  other: { label: '其它状态', tone: 'muted' },
}

/** 请假 / 准假（**先**判，避免「请假未到」落进未返校桶） */
const EXCUSED_WORDS = ['请假', '病假', '事假', '假条', '休假', '准假']

/** 否定 / 未到（**第二**判，压过下面的「到校」「返校」） */
const ABSENT_WORDS = [
  '未到', '不到', '没到',
  '未返', '没返', '未回', '没回',
  '缺席', '未在校', '离校', '未归',
]

/** 肯定 / 已到（**第三**判——只能匹配到没被上面命中的） */
const RETURNED_WORDS = ['已到', '到校', '已返', '返校', '已回', '在校', '正常', '报到']

/**
 * 把一行的 `value` 归桶。**`null` / 空串 = 还没填，按口径算未返校**。
 *
 * 先判「是/否」两个精确值（BOOLEAN 题型走的就是这条，命中后不必再扫关键词），
 * 再扫关键词，都认不出就 `other`。
 */
export function classifyStatus(value: string | null | undefined): ReturnBucket {
  const v = (value ?? '').trim()
  if (!v) return 'absent' // 没填 = 还没点名 = 未返校

  // BOOLEAN 题型的两个固定答案（后端已翻成「是/否」）
  if (v === '是' || v === 'true') return 'returned'
  if (v === '否' || v === 'false') return 'absent'

  if (EXCUSED_WORDS.some((w) => v.includes(w))) return 'excused'
  if (ABSENT_WORDS.some((w) => v.includes(w))) return 'absent'
  if (RETURNED_WORDS.some((w) => v.includes(w))) return 'returned'
  return 'other'
}

/**
 * 明细里的状态显示文字。空值统一显示成「未填」，
 * 这样图例、列表、卡片三处叫法一致（不然一会儿「—」一会儿「未填」）。
 */
export function statusLabel(value: string | null | undefined): string {
  const v = (value ?? '').trim()
  return v || '未填'
}
