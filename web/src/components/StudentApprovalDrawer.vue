<script setup lang="ts">
/**
 * 学生信息 · 审批收件箱与授权清单（第二十三轮，**仅班主任**）。
 *
 * 两块内容：
 * 1. 待审批申请：同意 → 写入授权（立即生效）；不同��� → 只留申请流水。
 * 2. 已生效授权：可以随时撤销（撤销后申请人不只是看不到新数据，已缓存的页面需要刷新）。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  fetchPendingRequests,
  fetchStudentGrants,
  handleStudentRequest,
  revokeStudentGrant,
} from '@/api/students'
import { getErrorMessage } from '@/api/request'
import { ROLE_TEXT } from '@/types'
import type { StudentAccessRequest, StudentGrant } from '@/types'

const visible = defineModel<boolean>({ default: false })
const emit = defineEmits<{ (e: 'handled'): void }>()

const loading = ref(false)
const busy = ref<number | null>(null)
const pending = ref<StudentAccessRequest[]>([])
const grants = ref<StudentGrant[]>([])

const isEmpty = computed(
  () => !loading.value && pending.value.length === 0 && grants.value.length === 0,
)

async function load() {
  loading.value = true
  try {
    const [p, g] = await Promise.all([fetchPendingRequests(), fetchStudentGrants()])
    pending.value = p
    grants.value = g
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '读取申请失败'))
  } finally {
    loading.value = false
  }
}

async function decide(r: StudentAccessRequest, approve: boolean) {
  let reply = ''
  if (!approve) {
    try {
      const res = await ElMessageBox.prompt(
        `「${r.userName}」申请了${r.scopeText}。写一句理由，申请人会看到。`,
        '拒绝申请',
        {
          confirmButtonText: '确认拒绝',
          cancelButtonText: '取消',
          inputPlaceholder: '例如：暂时不需要，请找班主任直接处理',
          inputValidator: (v: string) => (v.length <= 255 ? true : '最多 255 字'),
        },
      )
      reply = res.value || ''
    } catch {
      return
    }
  }
  busy.value = r.id
  try {
    await handleStudentRequest(r.id, approve, reply || undefined)
    ElMessage.success(approve ? `已同意「${r.userName}」的申请` : '已拒绝')
    await load()
    emit('handled')
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '操作失败'))
  } finally {
    busy.value = null
  }
}

async function revoke(g: StudentGrant) {
  try {
    await ElMessageBox.confirm(
      `撤销后，${g.userName} 将不能再${g.scopeText.includes('编辑') ? '编辑' : '查看'}，需要重新申请。`,
      '确认撤销授权？',
      { type: 'warning', confirmButtonText: '确认撤销', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await revokeStudentGrant(g.userId, g.scope)
    ElMessage.success('已撤销')
    await load()
    emit('handled')
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '撤销失败'))
  }
}

/**
 * 每次打开都重新拉取。
 *
 * 只 `defineExpose({ load })` 是不够的——父组件拿不到 ref 就永远不会调它，
 * 抽屉打开会是一片空白（第一次就是这么错的）。watch 才是「打开即加载」的正确位置。
 */
watch(visible, (v) => {
  if (v) void load()
})

defineExpose({ load })
</script>

<template>
  <el-drawer v-model="visible" title="学生信息访问授权" size="560px">
    <section v-if="pending.length">
      <h3>待审批（{{ pending.length }}）</h3>
      <ul class="list">
        <li v-for="r in pending" :key="r.id" class="req">
          <div class="req-info">
            <div class="req-head">
              <strong>{{ r.userName }}</strong>
              <el-tag size="small" effect="plain">{{ ROLE_TEXT[r.role ?? 'MEMBER'] }}</el-tag>
              <span class="scope">{{ r.scopeText }}</span>
            </div>
            <div v-if="r.reason" class="reason">理由：{{ r.reason }}</div>
            <div v-if="r.createdAt" class="time">{{ r.createdAt }}</div>
          </div>
          <div class="ops">
            <el-button
              size="small"
              type="primary"
              :loading="busy === r.id"
              @click="decide(r, true)"
            >
              同意
            </el-button>
            <el-button size="small" :loading="busy === r.id" @click="decide(r, false)">
              拒绝
            </el-button>
          </div>
        </li>
      </ul>
    </section>

    <section>
      <h3>已生效的授权（{{ grants.length }}）</h3>
      <ul v-if="grants.length" class="list">
        <li v-for="g in grants" :key="g.id" class="req">
          <div class="req-info">
            <div class="req-head">
              <strong>{{ g.userName }}</strong>
              <el-tag size="small" effect="plain">{{ ROLE_TEXT[g.role] }}</el-tag>
              <span class="scope">{{ g.scopeText }}</span>
            </div>
            <div class="time">
              由 {{ g.grantedByName }} 于 {{ g.grantedAt ?? '—' }} 授予
            </div>
          </div>
          <el-button size="small" text type="danger" @click="revoke(g)">撤销</el-button>
        </li>
      </ul>
      <p v-else class="none">还没有给任何人授权。</p>
    </section>

    <el-empty v-if="isEmpty" description="没有待处理的申请，也没有已生效的授权" />
  </el-drawer>
</template>

<style scoped>
h3 {
  margin: 0 0 8px;
  font-size: 14px;
}

section {
  margin-bottom: 22px;
}

.list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.req {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 4px;
  border-bottom: 1px solid var(--color-border);
}

.req-info {
  min-width: 0;
}

.req-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.scope {
  font-size: 13px;
}

.reason {
  margin-top: 4px;
  font-size: 13px;
  color: var(--color-muted-fg);
}

.time {
  margin-top: 2px;
  font-size: 12px;
  color: var(--color-muted-fg);
}

.ops {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

.none {
  margin: 0;
  font-size: 13px;
  color: var(--color-muted-fg);
}
</style>