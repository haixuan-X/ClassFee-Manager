<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'
import { fetchMyBatches } from '@/api/batches'
import { useUserStore } from '@/stores/user'
import type { MyBatch } from '@/types'
import { BATCH_STATUS_TEXT } from '@/types'

/**
 * 我的缴费（第十八轮新增，第二十轮把班主任移出）。
 *
 * 为什么有这个页面：普通成员能看账本、能在仪表盘上看到「缴费完成率 50%」，却**没有任何
 * 入口知道自己交没交** —— 那三个问题（有没有班费要交 / 我交了吗 / 什么时候截止）本来
 * 不需要缴费名单就能回答，之前被 `GET /api/batches` 的运营专属 403 一起挡掉了。
 *
 * 数据来自同一个 `GET /api/batches`：后端按角色裁剪，非运营角色只拿到批次基本信息 +
 * **自己**的缴费状态（`myStatus` / `myAmount` / `myPaidAt`）。
 * **别人的姓名与学号仍然看不到** —— 缴费名单在「成员缴费」页，那页限运营角色。
 *
 * 第二十轮：班主任不再有这个入口。缴费对象只有 MEMBER（`_class_members`），班主任是
 * .env 声明的老师账号不是学生，进来只会看到一句「你不属于缴费对象」的死胡同。
 *
 * 缴费是「代为登记」：同学自己不能操作，页面把这一点说清楚，而不是给一个点不动的按钮。
 */
const router = useRouter()
const userStore = useUserStore()

const loading = ref(true)
const loadError = ref(false)
const batches = ref<MyBatch[]>([])

async function load() {
  loading.value = true
  loadError.value = false
  try {
    batches.value = await fetchMyBatches()
  } catch {
    // 拦截器已统一提示；这里把列表清空并标错，避免把「加载失败」显示成「暂无班费」
    batches.value = []
    loadError.value = true
  } finally {
    loading.value = false
  }
}

onMounted(load)

/**
 * 我是否属于缴费对象。
 *
 * 缴费名单只列 MEMBER（后端 `_class_members`），所以只有普通成员拿得到 `myStatus`；
 * 运营角色拿到的批次里 `myStatus` 恒为 null（契约对所有角色稳定存在，见第十八轮）。
 */
const iAmPayable = computed(() => batches.value.some((b) => b.myStatus != null))

/**
 * 非缴费对象进来时给一句实话，而不是空白页。
 *
 * 第二十轮：班主任已从侧栏与路由移出（`roles` 不含 TEACHER），进不到这一页；
 * 这段文案现在只可能对生活委员 / 班长 出现。
 */
const notPayableHint = computed(() =>
  userStore.isStaff
    ? '你的角色是运营角色（生活委员 / 班长），不是缴费对象。代为登记请到「成员缴费」。'
    : '',
)

/** 进行中且我还没交的排最前 —— 那是最需要人行动的一条 */
const sorted = computed(() =>
  [...batches.value].sort((a, b) => rank(a) - rank(b) || b.id - a.id),
)

const pendingCount = computed(() => sorted.value.filter((b) => b.myStatus === 'UNPAID').length)

/**
 * 排序：**需要人行动的排前面**，已搞定（已缴 / 已退款）沉底。
 * 特别注意「已关闭但没缴」也算要行动 —— 第一版把它排在「进行中且已缴」之后，
 * 看起来像是「只有一条未缴提醒在催我」，实际是「我有一条已缴的 + 一条没缴的」，
 * 反而弱化了真正欠费的那条。
 */
const rank = (b: MyBatch) => {
  if (b.myStatus === 'UNPAID') return b.status === 'OPEN' ? 0 : 1
  if (b.myAmountDue) return 2
  if (b.myStatus === 'REFUNDED') return 3
  if (b.myStatus === 'PAID') return 4
  return 5
}

type Row = {
  badge: string
  badgeType: 'success' | 'warning' | 'danger' | 'info'
  detail: string
  urgent: string
}

/** 把「我的状态」翻译成人话 */
function describe(b: MyBatch): Row {
  // 用 `== null` 同时兜住 null 与 undefined：后端对所有角色都返回这组键（无缴费行为
  // null），但万一将来某个角色路径漏了，undefined 也必须落到「不在缴费名单」而不是
  // 一路掉到最后显示成「未缴费」。
  if (b.myStatus == null) {
    return {
      badge: '不在缴费名单',
      badgeType: 'info',
      detail: userStore.isStaff
        ? '你的角色是运营角色，不属于缴费对象'
        : '你是在这个批次创建之后才入班的，请联系生活委员 / 班长补登记',
      urgent: '',
    }
  }
  if (b.myStatus === 'PAID') {
    return {
      badge: '已缴费',
      badgeType: 'success',
      detail: `实收 ${Number(b.myAmount ?? 0).toFixed(2)} 元${b.myPaidAt ? ` · ${dayjs(b.myPaidAt).format('YYYY-MM-DD HH:mm')}` : ''}`,
      urgent: '',
    }
  }
  if (b.myStatus === 'REFUNDED') {
    return {
      badge: '已退款',
      badgeType: 'warning',
      detail: '这笔班费已退回，请确认是否需要重新缴纳',
      urgent: '',
    }
  }
  // UNPAID
  const base = '尚未缴纳，由生活委员 / 班长 / 班主任代为登记'
  if (b.myAmountDue) {
    return {
      badge: '待重新登记',
      badgeType: 'danger',
      detail: `${base}；上一笔流水已被作废，费用还没回来`,
      urgent: '这笔需要重新登记',
    }
  }
  if (b.status !== 'OPEN') {
    return {
      badge: '未缴费',
      badgeType: 'danger',
      detail: `${base}；该批次已关闭，请联系生活委员 / 班长确认`,
      urgent: '该批次已关闭',
    }
  }
  if (b.deadline) {
    const days = dayjs(b.deadline).startOf('day').diff(dayjs().startOf('day'), 'day')
    if (days < 0) {
      return {
        badge: '已逾期',
        badgeType: 'danger',
        detail: `${base}；截止日 ${b.deadline} 已过`,
        urgent: `已逾期 ${Math.abs(days)} 天`,
      }
    }
    if (days <= 3) {
      return {
        badge: '未缴费',
        badgeType: 'danger',
        detail: `${base}；截止日 ${b.deadline}`,
        urgent: days === 0 ? '今天截止' : `还剩 ${days} 天`,
      }
    }
    return {
      badge: '未缴费',
      badgeType: 'warning',
      detail: `${base}；截止日 ${b.deadline}`,
      urgent: `还剩 ${days} 天`,
    }
  }
  return { badge: '未缴费', badgeType: 'warning', detail: base, urgent: '' }
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>我的缴费</h2>
        <p v-if="!iAmPayable && !loading">
          {{ notPayableHint || '本班暂无收费批次' }}
        </p>
        <p v-else>
          这里只显示<strong>你自己</strong>的缴费情况；全班名单与代为登记由生活委员 / 班长 / 班主任在「成员缴费」处理。
        </p>
      </div>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>

    <el-alert
      v-if="loadError"
      type="error"
      show-icon
      :closable="false"
      title="缴费信息加载失败"
      description="请检查网络后点右上角「刷新」重试。"
    />

    <template v-else>
      <el-alert
        v-if="pendingCount > 0"
        type="warning"
        show-icon
        :closable="false"
        class="pending-alert"
        :title="`你还有 ${pendingCount} 个批次的班费没有缴`"
        description="本系统不提供自助缴费，由生活委员 / 班长 / 班主任核对现金或转账后代为登记；如有减免请提前说明。"
      />

      <ul v-loading="loading" class="fee-list" aria-label="我的缴费批次">
        <li v-for="b in sorted" :key="b.id" class="fee-card">
          <div class="fee-head">
            <div class="fee-title">
              <span class="name">{{ b.name }}</span>
              <el-tag size="small" effect="plain" :type="b.status === 'OPEN' ? 'primary' : 'info'">
                {{ BATCH_STATUS_TEXT[b.status] }}
              </el-tag>
              <el-tag size="small" :type="describe(b).badgeType" effect="dark">
                {{ describe(b).badge }}
              </el-tag>
              <el-tag v-if="describe(b).urgent" size="small" type="danger" effect="plain">
                {{ describe(b).urgent }}
              </el-tag>
            </div>
            <div class="fee-amount">
              <span class="label">每人应收</span>
              <span class="value">¥{{ Number(b.amount).toFixed(2) }}</span>
            </div>
          </div>

          <dl class="fee-meta">
            <div>
              <dt>截止日</dt>
              <dd>{{ b.deadline ?? '未设置' }}</dd>
            </div>
            <div>
              <dt>我的状态</dt>
              <dd>{{ describe(b).detail }}</dd>
            </div>
            <div>
              <dt>全班进度</dt>
              <dd>已缴 {{ b.paidCount }} / {{ b.total }} 人</dd>
            </div>
          </dl>
        </li>
      </ul>

      <el-empty
        v-if="!loading && !loadError && batches.length === 0"
        :description="
          userStore.isStaff
            ? '本班还没有收费批次'
            : '本班暂时没有班费批次，收到通知后再来查看'
        "
      />
      <el-empty
        v-else-if="!loading && !loadError && batches.length > 0 && !iAmPayable"
        :description="notPayableHint"
      />

      <p v-if="iAmPayable" class="tip">
        疑问请直接找生活委员 / 班长 / 班主任核对；本页数据来自账本实时计算，与「成员缴费」页一致。
      </p>
      <el-button
        v-if="userStore.isStaff"
        class="tip"
        text
        type="primary"
        @click="router.push('/members')"
      >
        去「成员缴费」代为登记
      </el-button>
    </template>
  </div>
</template>

<style scoped>
.pending-alert {
  margin-bottom: var(--space-md);
}

.fee-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-sm);
}

.fee-card {
  border: 1px solid var(--color-border);
  border-radius: 12px;
  background: var(--color-surface);
  padding: var(--space-md);
}

.fee-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-sm);
  flex-wrap: wrap;
}

.fee-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.name {
  font-size: 16px;
  font-weight: 600;
}

.fee-amount {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.fee-amount .label {
  font-size: 12px;
  color: var(--color-muted-fg);
}

.fee-amount .value {
  font-size: 20px;
  font-weight: 600;
  color: var(--color-accent-text);
}

.fee-meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--space-sm);
  margin: var(--space-sm) 0 0;
}

.fee-meta dt {
  font-size: 12px;
  color: var(--color-muted-fg);
}

.fee-meta dd {
  margin: 2px 0 0;
  font-size: 14px;
}

.tip {
  display: block;
  margin-top: var(--space-sm);
  font-size: 12px;
  color: var(--color-muted-fg);
}
</style>
