<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { fetchMe } from '@/api/auth'
import { fetchClassInfo, updateClassInfo } from '@/api/class'
import { getErrorMessage } from '@/api/request'
import { useModal } from '@/composables/useModal'
import { useUserStore } from '@/stores/user'
import type { ClassInfo } from '@/types'

/**
 * 班级信息（M4）：全员可读；班级名称 / 年级 / 班主任 仅运营角色（ADMIN/MONITOR/TEACHER）可编辑，
 * 与公告同一套权限口径（后端 _STAFF_ROUTES 强制校验）。余额是记账事务同步的冗余列，
 * 只读展示并可与仪表盘对账，**不开放手工修改**。
 *
 * 第十六轮补字段级口径：`headTeacher` 是**角色字段**，后端只允许 TEACHER 写。
 * 这里必须同步收敛，否则会出两种很糟的表现：① 班长/生活委员在表单里看到「班主任」
 * 输入框，填什么都存不进去（403）；② 更糟 —— 编辑表单**无条件提交 headTeacher**，
 * 于是他们连改「班级名称/年级」都会被后端 403 拒掉，整个编辑功能对低等级角色瘫掉。
 * 因此：`canEditHeadTeacher` 决定输入框是否渲染，且保存时非 TEACHER 一律不带该字段。
 */
const userStore = useUserStore()
const canWrite = computed(() => userStore.isStaff)
const canEditHeadTeacher = computed(() => userStore.user?.role === 'TEACHER')

const loading = ref(true)
const loadError = ref(false)
const info = ref<ClassInfo>()

async function load() {
  loading.value = true
  try {
    info.value = await fetchClassInfo()
    loadError.value = false
  } catch {
    info.value = undefined
    loadError.value = true
  } finally {
    loading.value = false
  }
}

/* ============================ 编辑 ============================ */

const editorVisible = ref(false)
const editorLoading = ref(false)
const editorFormRef = ref<FormInstance>()
const alertMessage = ref('')
const alertRef = ref<HTMLElement>()

const { restoreFocus } = useModal(editorVisible)

const editorForm = reactive({ className: '', grade: '', headTeacher: '' })

const editorRules: FormRules = {
  className: [
    { required: true, message: '请输入班级名称', trigger: 'blur' },
    { max: 50, message: '班级名称最多 50 字', trigger: 'blur' },
  ],
  grade: [{ max: 20, message: '年级最多 20 字', trigger: 'blur' }],
  headTeacher: [{ max: 50, message: '班主任姓名最多 50 字', trigger: 'blur' }],
}

async function showAlert(message: string) {
  alertMessage.value = message
  await nextTick()
  alertRef.value?.focus()
}

function openEditor() {
  if (!info.value) return
  editorForm.className = info.value.className
  editorForm.grade = info.value.grade ?? ''
  editorForm.headTeacher = info.value.headTeacher ?? ''
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
    const updated = await updateClassInfo({
      className: editorForm.className.trim(),
      grade: editorForm.grade.trim(),
      // 关键：非班主任**不能带这个字段**，否则后端 403 会把整个保存一起拒掉
      ...(canEditHeadTeacher.value ? { headTeacher: editorForm.headTeacher.trim() } : {}),
    })
    info.value = updated
    editorVisible.value = false
    ElMessage.success('班级信息已更新')
    // 侧边栏与仪表盘顶部的班级名来自登录态里的 className，改名后同步刷新
    try {
      userStore.setUser(await fetchMe())
    } catch {
      /* 刷新失败不影响本次保存结果，用户重新登录即可 */
    }
  } catch (error) {
    await showAlert(getErrorMessage(error, '保存失败，请稍后重试'))
  } finally {
    editorLoading.value = false
  }
}

function fmtBalance(value: number | undefined) {
  return Number(value ?? 0).toFixed(2)
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>班级信息</h2>
        <p>
          {{ canEditHeadTeacher
            ? '班级名称、年级与班主任由运营角色维护（班主任一栏仅班主任本人可改）'
            : canWrite
              ? '班级名称与年级由运营角色维护；班主任一栏仅班主任本人可修改'
              : '班级信息由运营角色维护，如需变更请联系生活委员、班长或班主任' }}
        </p>
      </div>
      <el-button v-if="canWrite && info" type="primary" @click="openEditor">编辑班级信息</el-button>
    </div>

    <section class="glass-card info-card" aria-label="班级信息" :aria-busy="loading">
      <div v-if="info" class="info-grid">
        <div class="field">
          <div class="field-label">班级名称</div>
          <div class="field-value strong">{{ info.className }}</div>
        </div>
        <div class="field">
          <div class="field-label">年级 / 届别</div>
          <div class="field-value">{{ info.grade ?? '未填写' }}</div>
        </div>
        <div class="field">
          <div class="field-label">班主任</div>
          <div class="field-value">{{ info.headTeacher ?? '未填写' }}</div>
        </div>
        <div class="field">
          <div class="field-label">当前余额（元）</div>
          <div class="field-value num" :class="Number(info.balance) < 0 ? 'amount-out' : 'amount-in'">
            {{ fmtBalance(info.balance) }}
          </div>
          <div class="field-hint">由收支流水实时计算并与账本对账，不可手工修改</div>
        </div>
      </div>

      <el-empty
        v-else-if="!loading"
        :description="loadError ? '班级信息加载失败，请检查网络后重试' : '暂无班级信息'"
        :image-size="80"
      >
        <el-button v-if="loadError" type="primary" @click="load()">重新加载</el-button>
      </el-empty>
    </section>

    <p v-if="!canWrite" class="readonly-hint">
      你当前是普通成员，以上信息只读；需要修改请联系生活委员、班长或班主任。
    </p>

    <!-- 编辑弹窗 -->
    <el-dialog
      v-model="editorVisible"
      title="编辑班级信息"
      width="min(480px, 92vw)"
      :close-on-press-escape="false"
      @closed="restoreFocus"
    >
      <div v-if="alertMessage" ref="alertRef" class="error-summary" role="alert" tabindex="-1">
        <b>无法保存：</b>{{ alertMessage }}
      </div>

      <el-form ref="editorFormRef" :model="editorForm" :rules="editorRules" label-position="top" @submit.prevent>
        <el-form-item label="班级名称" prop="className">
          <el-input
            v-model.trim="editorForm.className"
            aria-label="班级名称"
            maxlength="50"
            show-word-limit
            placeholder="如：计科2201班"
          />
        </el-form-item>
        <el-form-item label="年级 / 届别" prop="grade">
          <el-input
            v-model.trim="editorForm.grade"
            aria-label="年级"
            maxlength="20"
            placeholder="如：2022级（留空表示不填写）"
          />
        </el-form-item>
        <el-form-item v-if="canEditHeadTeacher" label="班主任" prop="headTeacher">
          <el-input
            v-model.trim="editorForm.headTeacher"
            aria-label="班主任"
            maxlength="50"
            placeholder="如：测试班主任（留空表示不填写）"
          />
        </el-form-item>
        <el-form-item v-else label="班主任">
          <span class="readonly-field">
            {{ info?.headTeacher ?? '未填写' }}
            <span class="readonly-tag">仅班主任可修改</span>
          </span>
        </el-form-item>
        <p class="hint">班级余额由记账流水自动计算，这里不提供手工修改入口。</p>
      </el-form>

      <template #footer>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="editorLoading" @click="submitEditor">保存</el-button>
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

.info-card {
  padding: var(--space-md);
  min-height: 200px;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--space-md);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.field-label {
  font-size: 12px;
  color: var(--color-muted-fg);
}

.field-value {
  font-size: 16px;
  overflow-wrap: anywhere;
}

.readonly-field {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  color: var(--color-muted-fg);
  min-height: 32px;
}

.readonly-tag {
  font-size: 12px;
  padding: 1px 6px;
  border-radius: 4px;
  border: 1px solid var(--color-border);
  color: var(--color-muted-fg);
  white-space: nowrap;
}

.field-value.strong {
  font-size: 20px;
  font-weight: 600;
}

.field-value.amount-in {
  color: var(--color-income);
}

.field-value.amount-out {
  color: var(--color-expense);
}

.field-hint {
  font-size: 12px;
  color: var(--color-muted-fg);
}

.readonly-hint {
  margin: 0;
  font-size: 12px;
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

.hint {
  margin: 0;
  font-size: 12px;
  color: var(--color-muted-fg);
}

@media (max-width: 768px) {
  .page-head h2 {
    font-size: 20px;
  }
}
</style>
