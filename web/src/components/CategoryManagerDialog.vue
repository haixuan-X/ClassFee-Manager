<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createCategory, deleteCategory, fetchCategories, updateCategory } from '@/api/records'
import { useModal } from '@/composables/useModal'
import type { Category, RecordType } from '@/types'
import { TYPE_TEXT } from '@/types'

/**
 * 类别字典维护（ADMIN，登记抽屉内入口）：新增 / 改名 / 删除当前方向的类别。
 * 被流水引用的类别后端会拒绝删除（历史账目要能还原）——所以必须能**改名**继续用，
 * 否则用户只能被卡住（第十六轮：原来提示写着「可改名」，界面上却没有改名入口）。
 */
const props = defineProps<{ kind: RecordType }>()
const visible = defineModel<boolean>({ required: true })
const emit = defineEmits<{ changed: [] }>()

const loading = ref(false)
const adding = ref(false)
const categories = ref<Category[]>([])
const name = ref('')

/** 正在改名的类别 id；非 null 时该行显示输入框 */
const renamingId = ref<number | null>(null)
const renamingName = ref('')
const renaming = ref(false)
const renameInputRef = ref<{ focus: () => void }>()

/** 弹层内根元素：供 useModal 判定本对话框是否处于最上层（Esc 归谁消费） */
const bodyEl = ref<HTMLElement>()

/** Esc 关闭兜底 + 关闭后焦点还原 */
const { restoreFocus } = useModal(visible, bodyEl)

async function loadList() {
  loading.value = true
  try {
    categories.value = await fetchCategories(props.kind)
  } catch {
    /* 拦截器已提示；列表为空不阻塞维护操作 */
  } finally {
    loading.value = false
  }
}

watch(visible, (open) => {
  if (!open) return
  name.value = ''
  renamingId.value = null
  renamingName.value = ''
  loadList()
})

async function onAdd() {
  const value = name.value.trim()
  if (!value) {
    ElMessage.warning('请输入类别名称')
    return
  }
  adding.value = true
  try {
    await createCategory({ kind: props.kind, name: value })
    ElMessage.success(`已新增类别「${value}」`)
    name.value = ''
    await loadList()
    emit('changed')
  } catch {
    // 同名/超长由后端 400 拒绝，拦截器已提示
  } finally {
    adding.value = false
  }
}

function startRename(cat: Category) {
  renamingId.value = cat.id
  renamingName.value = cat.name
  nextTick(() => renameInputRef.value?.focus())
}

function cancelRename() {
  renamingId.value = null
  renamingName.value = ''
}

async function onRename(cat: Category) {
  const value = renamingName.value.trim()
  if (!value) {
    ElMessage.warning('请输入类别名称')
    return
  }
  if (value === cat.name) {
    cancelRename()
    return
  }
  renaming.value = true
  try {
    // 只传 name：后端「不传=不修改」，sort/kind 保持原样
    await updateCategory(cat.id, { name: value })
    ElMessage.success(`类别已改名为「${value}」`)
    cancelRename()
    await loadList()
    emit('changed')
  } catch {
    // 同名/超长由后端 400 拒绝，拦截器已提示；保留输入框让用户直接改
  } finally {
    renaming.value = false
  }
}

async function onDelete(cat: Category) {
  try {
    await ElMessageBox.confirm(
      `删除类别「${cat.name}」？未被流水引用的类别会直接移除；已被引用的会被拒绝。`,
      '删除类别',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
  } catch {
    return // 用户取消
  }
  try {
    await deleteCategory(cat.id)
    ElMessage.success(`类别「${cat.name}」已删除`)
    await loadList()
    emit('changed')
  } catch {
    // 被引用时后端 400：「已有 N 笔流水，不能删除；可改名继续使用」，拦截器已提示
  }
}
</script>

<template>
  <!-- Esc 由 useModal 统一接管（捕获阶段 + 最上层判定），见 RecordFormDrawer 同款说明 -->
  <el-dialog
    v-model="visible"
    :title="`管理${TYPE_TEXT[kind]}类别`"
    width="min(480px, 92vw)"
    :close-on-press-escape="false"
    @closed="restoreFocus"
  >
    <div ref="bodyEl" class="add-row">
      <el-input
        v-model.trim="name"
        aria-label="新类别名称"
        maxlength="30"
        show-word-limit
        :placeholder="`新${TYPE_TEXT[kind]}类别名称，如：${kind === 'INCOME' ? '活动经费' : '活动物资'}`"
        @keyup.enter="onAdd"
      />
      <el-button type="primary" :loading="adding" @click="onAdd">新增</el-button>
    </div>

    <ul v-loading="loading" class="cat-list" aria-label="类别列表">
      <li v-for="cat in categories" :key="cat.id" class="cat-item">
        <template v-if="renamingId === cat.id">
          <el-input
            ref="renameInputRef"
            v-model.trim="renamingName"
            class="rename-input"
            aria-label="新的类别名称"
            maxlength="30"
            show-word-limit
            @keyup.enter="onRename(cat)"
            @keyup.esc="cancelRename"
            @blur="cancelRename"
          />
          <el-button link type="primary" size="small" :loading="renaming" @click="onRename(cat)">
            保存
          </el-button>
          <el-button link size="small" @click="cancelRename">取消</el-button>
        </template>
        <template v-else>
          <span class="cat-name">{{ cat.name }}</span>
          <el-button link type="primary" size="small" @click="startRename(cat)">改名</el-button>
          <el-button link type="danger" size="small" @click="onDelete(cat)">删除</el-button>
        </template>
      </li>
    </ul>

    <p v-if="!loading && categories.length === 0" class="hint">
      暂无{{ TYPE_TEXT[kind] }}类别，请先在上方新增。
    </p>
    <p class="hint">已被流水引用的类别不能删除（历史账目要能还原），可改名后继续使用。</p>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.add-row {
  display: flex;
  gap: 8px;
}

.cat-list {
  list-style: none;
  margin: 16px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  max-height: 300px;
  overflow-y: auto;
}

.cat-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 40px;
  padding: 4px;
  border-bottom: 1px solid var(--color-border);
}

.cat-item:last-child {
  border-bottom: none;
}

.cat-name {
  font-size: 14px;
}

.rename-input {
  flex: 1;
  min-width: 0;
}

.hint {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--color-muted-fg);
}
</style>
