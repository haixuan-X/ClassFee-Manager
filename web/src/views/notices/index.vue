<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import dayjs from 'dayjs'
import { createNotice, deleteNotice, fetchNotices, updateNotice } from '@/api/notices'
import { getErrorMessage } from '@/api/request'
import { useModal } from '@/composables/useModal'
import { useUserStore } from '@/stores/user'
import type { Notice } from '@/types'

/**
 * 班级公告（M4）：全员可读；发布 / 编辑 / 置顶 / 下架恢复 / 彻底删除仅运营角色
 * （ADMIN/MONITOR/TEACHER，与后端 _STAFF_ROUTES 同口径）。下架即软删除（成员不可见、可恢复），
 * 彻底删除要求先下架，避免误删无从找回。
 */
const userStore = useUserStore()
const canWrite = computed(() => userStore.isStaff)

/** 第十七轮归属权（A 方案）：置顶/下架/编辑/彻底删除只对发布人开放 */
const isMine = (row: Notice) => row.createdBy === userStore.user?.id

const loading = ref(true)
const listLoading = ref(false)
const notices = ref<Notice[]>([])
const keyword = ref('')
/** 1=已发布 0=已下架 all=全部；成员只保留「已发布」选项（后端也会按角色降级） */
const statusFilter = ref<'1' | '0' | 'all'>('1')
/** 请求序号：连点查询时丢弃过期响应 */
let seq = 0

const statusOptions = computed(() =>
  canWrite.value
    ? [
        { value: '1', label: '已发布' },
        { value: '0', label: '已下架' },
        { value: 'all', label: '全部' },
      ]
    : [{ value: '1', label: '已发布' }],
)

/** 加载失败标记：区分「没有公告」与「接口出错」的空态 */
const loadError = ref(false)

async function load() {
  const s = ++seq
  listLoading.value = true
  try {
    notices.value = await fetchNotices({
      status: statusFilter.value,
      keyword: keyword.value.trim() || undefined,
    })
    loadError.value = false
  } catch {
    if (s === seq) {
      notices.value = []
      loadError.value = true
    }
  } finally {
    if (s === seq) listLoading.value = false
  }
}

function applyFilters() {
  load()
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = '1'
  load()
}

/** 长正文默认折叠 3 行，点「展开全文 / 收起」切换 */
const expanded = ref<Set<number>>(new Set())
function toggleExpand(id: number) {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
}

function fmtTime(value: string | null) {
  return value ? dayjs(value).format('MM-DD HH:mm') : '—'
}

/* ============================ 发布 / 编辑 ============================ */

const editorVisible = ref(false)
const editorLoading = ref(false)
const editorMode = ref<'create' | 'edit'>('create')
const editorId = ref<number>()
const editorFormRef = ref<FormInstance>()
/** 弹窗级错误摘要（MASTER §8：role="alert" + 焦点，键盘/读屏可发现） */
const alertMessage = ref('')
const alertRef = ref<HTMLElement>()

// Esc 关闭兜底 + 关闭后焦点还原
const { restoreFocus } = useModal(editorVisible)

const editorForm = reactive({ title: '', content: '', pinned: 0 })

const editorRules: FormRules = {
  title: [
    { required: true, message: '请输入公告标题', trigger: 'blur' },
    { max: 80, message: '标题最多 80 字', trigger: 'blur' },
  ],
  content: [
    { required: true, message: '请输入公告内容', trigger: 'blur' },
    { max: 2000, message: '内容最多 2000 字', trigger: 'blur' },
  ],
}

async function showAlert(message: string) {
  alertMessage.value = message
  await nextTick()
  alertRef.value?.focus()
}

function openCreate() {
  editorMode.value = 'create'
  editorId.value = undefined
  editorForm.title = ''
  editorForm.content = ''
  editorForm.pinned = 0
  alertMessage.value = ''
  editorVisible.value = true
}

function openEdit(row: Notice) {
  editorMode.value = 'edit'
  editorId.value = row.id
  editorForm.title = row.title
  editorForm.content = row.content
  editorForm.pinned = row.pinned
  alertMessage.value = ''
  editorVisible.value = true
}

async function submitEditor() {
  if (!editorFormRef.value || editorLoading.value) return
  try {
    await editorFormRef.value.validate()
  } catch {
    await showAlert('表单有未填写或格式不正确的项，请按下方提示修改')
    return
  }
  editorLoading.value = true
  alertMessage.value = ''
  try {
    const payload = {
      title: editorForm.title.trim(),
      content: editorForm.content.trim(),
      pinned: editorForm.pinned,
    }
    if (editorMode.value === 'create') {
      await createNotice(payload)
      ElMessage.success('公告已发布')
    } else {
      await updateNotice(editorId.value!, payload)
      ElMessage.success('公告已更新')
    }
    editorVisible.value = false
    await load()
  } catch (error) {
    await showAlert(getErrorMessage(error, '保存失败，请稍后重试'))
  } finally {
    editorLoading.value = false
  }
}

/* ============================ 行内操作 ============================ */

const acting = ref<number>()

async function onTogglePin(row: Notice) {
  acting.value = row.id
  try {
    await updateNotice(row.id, { pinned: row.pinned === 1 ? 0 : 1 })
    ElMessage.success(row.pinned === 1 ? '已取消置顶' : '已置顶，仪表盘同步展示')
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    acting.value = undefined
  }
}

async function onToggleStatus(row: Notice) {
  const next = row.status === 1 ? 0 : 1
  try {
    await ElMessageBox.confirm(
      next === 0
        ? `确认下架「${row.title}」？下架后班级成员将看不到这条公告，可随时恢复。`
        : `确认恢复「${row.title}」？恢复后全班可见。`,
      next === 0 ? '下架确认' : '恢复确认',
      { type: 'warning', confirmButtonText: next === 0 ? '确认下架' : '确认恢复', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  acting.value = row.id
  try {
    await updateNotice(row.id, { status: next })
    ElMessage.success(next === 0 ? '已下架（成员不可见）' : '已恢复发布')
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    acting.value = undefined
  }
}

async function onDelete(row: Notice) {
  try {
    await ElMessageBox.confirm(
      `确认彻底删除「${row.title}」？删除后不可恢复（误删请优先用「下架」保留痕迹）。`,
      '删除确认',
      { type: 'error', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  acting.value = row.id
  try {
    await deleteNotice(row.id)
    ElMessage.success('公告已彻底删除')
    await load()
  } catch {
    /* 拦截器已提示（含「仍在发布状态」的 400） */
  } finally {
    acting.value = undefined
  }
}

onMounted(async () => {
  await load()
  loading.value = false
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>班级公告</h2>
        <p>{{ canWrite ? '发布班级通知，可置顶到仪表盘；下架后成员不可见但可恢复' : '仅生活委员 / 班长 / 班主任可发布公告，这里可以查看班级通知' }}</p>
      </div>
      <el-button v-if="canWrite" type="primary" @click="openCreate">发布公告</el-button>
    </div>

    <!-- 筛选栏 -->
    <section class="glass-card filters" aria-label="筛选条件">
      <el-input
        v-model="keyword"
        class="f-keyword"
        placeholder="搜索标题 / 正文"
        clearable
        aria-label="公告关键字"
        @keyup.enter="applyFilters"
        @clear="applyFilters"
      />
      <el-select
        v-if="canWrite"
        v-model="statusFilter"
        class="f-status"
        aria-label="公告状态"
        @change="applyFilters"
      >
        <el-option v-for="opt in statusOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>
      <el-button class="f-search" type="primary" plain @click="applyFilters">查询</el-button>
      <el-button class="f-reset" @click="resetFilters">重置</el-button>
    </section>

    <!-- 卡片列表 -->
    <section class="list" aria-label="公告列表" :aria-busy="listLoading">
      <article v-for="row in notices" :key="row.id" class="glass-card notice" :class="{ off: row.status === 0 }">
        <header class="notice-head">
          <h4 class="notice-title">
            <el-tag v-if="row.pinned === 1" type="warning" size="small" effect="dark">置顶</el-tag>
            <el-tag v-if="row.status === 0" type="info" size="small" effect="plain">已下架</el-tag>
            <span :class="{ voided: row.status === 0 }">{{ row.title }}</span>
          </h4>
          <div class="notice-meta">
            {{ row.createdByName ?? '—' }} · {{ fmtTime(row.publishedAt ?? row.createdAt) }}
            <!-- 第十九轮审计：谁发的与谁最后改的是两条独立的线，都摆出来。
                 条件只看「有没有编辑过」，不看是不是同一个人改的 —— 就算作者自己改，
                 「内容比发布时间新」这条信息读者也需要。 -->
            <span v-if="row.updatedByName" class="edited-by">
              · 最后由 {{ row.updatedByName }} 编辑于 {{ fmtTime(row.updatedAt) }}
            </span>
          </div>
        </header>

        <p class="notice-content" :class="{ expanded: expanded.has(row.id) }">{{ row.content }}</p>

        <div class="notice-foot">
          <el-button
            link
            type="primary"
            size="small"
            :aria-expanded="expanded.has(row.id)"
            @click="toggleExpand(row.id)"
          >
            {{ expanded.has(row.id) ? '收起' : '展开全文' }}
          </el-button>

          <!-- 第十七轮归属权（A 方案）：置顶 / 下架 / 编辑 / 彻底删除只对**发布人**开放。
               后端 require_ownership 是硬边界，这里隐藏按钮避免让人点了才吃 403。
               他人发的公告照常显示（公告是公开的）。 -->
          <template v-if="canWrite && isMine(row)">
            <el-button
              link
              type="primary"
              size="small"
              :loading="acting === row.id"
              :aria-label="`${row.pinned === 1 ? '取消置顶' : '置顶'}公告：${row.title}`"
              @click="onTogglePin(row)"
            >
              {{ row.pinned === 1 ? '取消置顶' : '置顶' }}
            </el-button>
            <el-button
              link
              :type="row.status === 1 ? 'warning' : 'success'"
              size="small"
              :loading="acting === row.id"
              :aria-label="`${row.status === 1 ? '下架' : '恢复'}公告：${row.title}`"
              @click="onToggleStatus(row)"
            >
              {{ row.status === 1 ? '下架' : '恢复' }}
            </el-button>
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <!-- 只有已下架的才给彻底删除（后端同样要求先下架） -->
            <el-button
              v-if="row.status === 0"
              link
              type="danger"
              size="small"
              :loading="acting === row.id"
              :aria-label="`彻底删除公告：${row.title}`"
              @click="onDelete(row)"
            >
              彻底删除
            </el-button>
          </template>
          <span v-else-if="canWrite" class="muted other-author">
            {{ row.createdByName ?? '他人' }} 发布的
          </span>
        </div>
      </article>

      <el-empty
        v-if="!listLoading && notices.length === 0"
        :description="
          loadError
            ? '公告加载失败，请检查网络后重试'
            : statusFilter === '0'
              ? '没有已下架的公告'
              : '暂无公告'
        "
        :image-size="80"
      >
        <el-button v-if="loadError" type="primary" @click="load()">重新加载</el-button>
        <el-button v-else-if="canWrite && statusFilter === '1'" type="primary" @click="openCreate">
          发布第一条公告
        </el-button>
      </el-empty>
    </section>

    <!-- 发布 / 编辑弹窗 -->
    <el-dialog
      v-model="editorVisible"
      :title="editorMode === 'create' ? '发布公告' : '编辑公告'"
      width="min(560px, 92vw)"
      :close-on-press-escape="false"
      @closed="restoreFocus"
    >
      <div v-if="alertMessage" ref="alertRef" class="error-summary" role="alert" tabindex="-1">
        <b>无法保存：</b>{{ alertMessage }}
      </div>

      <el-form ref="editorFormRef" :model="editorForm" :rules="editorRules" label-position="top" @submit.prevent>
        <el-form-item label="标题" prop="title">
          <el-input
            v-model.trim="editorForm.title"
            aria-label="公告标题"
            maxlength="80"
            show-word-limit
            placeholder="如：本周五班会通知"
          />
        </el-form-item>
        <el-form-item label="内容" prop="content">
          <el-input
            v-model="editorForm.content"
            aria-label="公告内容"
            type="textarea"
            :rows="6"
            maxlength="2000"
            show-word-limit
            placeholder="通知正文，支持换行"
          />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="editorForm.pinned" :true-value="1" :false-value="0">
            置顶到仪表盘
          </el-checkbox>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="editorLoading" @click="submitEditor">
          {{ editorMode === 'create' ? '发布' : '保存' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}

.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.page-head h2 {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
  line-height: 1.3;
}

.page-head p {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--color-muted-fg);
}

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-sm);
  padding: var(--space-md);
  align-items: center;
}

.f-keyword {
  width: 240px;
}

.f-status {
  width: 140px;
}

.list {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  min-height: 320px;
}

.notice {
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.notice.off {
  opacity: 0.75;
}

.notice-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.notice-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}

.notice-meta {
  font-size: 12px;
  color: var(--color-muted-fg);
  white-space: nowrap;
}

.notice-content {
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  color: var(--color-foreground);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  /* 折叠 3 行：-webkit-line-clamp 需配合 display:-webkit-box */
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.notice-content.expanded {
  display: block;
  -webkit-line-clamp: unset;
  line-clamp: unset;
  overflow: visible;
}

.voided {
  text-decoration: line-through;
  color: var(--color-muted-fg);
}

.notice-foot {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

/* 第十七轮归属权：他人发的公告，页脚显示「谁发布的」而不是空白 */
.other-author {
  font-size: 12px;
}

/* 第十九轮审计：公告被他人编辑过时的提示 */
.edited-by {
  color: var(--color-muted-fg);
}

.error-summary {
  border: 1px solid rgba(220, 38, 38, 0.35);
  background: rgba(220, 38, 38, 0.06);
  color: var(--color-destructive-text);
  border-radius: var(--radius);
  padding: 11px 13px;
  margin-bottom: 16px;
  font-size: 13px;
}

@media (max-width: 768px) {
  .page-head h2 {
    font-size: 20px;
  }

  .f-keyword,
  .f-status {
    width: 100%;
  }
}
</style>
