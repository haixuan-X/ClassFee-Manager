<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { fetchMe, fetchMyProfile, updateProfile } from '@/api/auth'
import { getErrorMessage } from '@/api/request'
import { useUserStore } from '@/stores/user'
import { ROLE_TEXT } from '@/types'
import type { Role, UserAccount } from '@/types'

/**
 * 个人信息（第十五轮）：**全员可用**，普通成员也能改自己的姓名 / 学号 / 手机号。
 *
 * 边界（后端 `PUT /api/auth/profile` 强制，不靠前端隐藏）：
 * - 改谁由登录令牌决定，请求体不接受 id → 结构上改不到别人
 * - 角色、启用状态只能由运营在「成员管理」改；登录名创建后不可改；改密走顶栏「修改密码」
 * - 学号同班唯一（重号后端 400），空串=清空
 *
 * 保存成功后把返回的 `UserInfo` 写回 store，顶栏的姓名/角色/班级立即同步。
 */
const userStore = useUserStore()

const loading = ref(true)
const saving = ref(false)
const loadError = ref(false)
/** 账号详情（含学号/手机号，/auth/me 不返回这两个字段） */
const detail = ref<UserAccount | null>(null)

const formRef = ref<FormInstance>()
const alertMessage = ref('')
const alertRef = ref<HTMLElement>()

const form = reactive({ realName: '', studentNo: '', phone: '' })

const rules: FormRules<typeof form> = {
  realName: [
    { required: true, message: '请输入姓名', trigger: 'blur' },
    { max: 32, message: '姓名最多 32 字', trigger: 'blur' },
  ],
  studentNo: [{ max: 20, message: '学号最多 20 字', trigger: 'blur' }],
  phone: [{ max: 20, message: '手机号最多 20 位', trigger: 'blur' }],
}

const roleText = computed<Role | ''>(() => userStore.user?.role ?? '')

/**
 * 加载我的账号详情。
 *
 * 走 `GET /auth/profile`（只认登录令牌、只能读自己），**不**用 `GET /api/users`
 * 找自己那一行——那是运营角色的成员管理列表，普通成员读会 403，
 * 页面就填不出自己的学号（更糟的是若据此回填空值，用户一点保存就把学号清掉）。
 */
async function load() {
  loading.value = true
  try {
    const mine = await fetchMyProfile()
    detail.value = mine
    form.realName = mine.realName
    form.studentNo = mine.studentNo ?? ''
    form.phone = mine.phone ?? ''
    // 顶栏的角色/班级也一并刷新（可能刚被运营改过）
    userStore.setUser(await fetchMe())
    loadError.value = false
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
}

async function showAlert(message: string) {
  alertMessage.value = message
  await nextTick()
  alertRef.value?.focus()
}

function fillFromStore() {
  const me = userStore.user
  if (!me) return
  form.realName = me.realName
  if (detail.value) {
    form.studentNo = detail.value.studentNo ?? ''
    form.phone = detail.value.phone ?? ''
  }
}

async function onSubmit() {
  if (!formRef.value || saving.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) {
    await showAlert('表单有未填写或格式不正确的项，请按下方提示修改')
    return
  }
  saving.value = true
  alertMessage.value = ''
  try {
    const updated = await updateProfile({
      realName: form.realName.trim(),
      // 沿用「空串=清空」语义（后端 None=不改）
      studentNo: form.studentNo.trim(),
      phone: form.phone.trim(),
    })
    userStore.setUser(updated)
    if (detail.value) {
      detail.value = {
        ...detail.value,
        realName: updated.realName,
        studentNo: form.studentNo.trim() || null,
        phone: form.phone.trim() || null,
      }
    }
    ElMessage.success('个人信息已更新')
  } catch (error) {
    await showAlert(getErrorMessage(error, '保存失败，请稍后重试'))
  } finally {
    saving.value = false
  }
}

function onReset() {
  formRef.value?.clearValidate()
  alertMessage.value = ''
  fillFromStore()
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>个人信息</h2>
        <p>这里改的是<strong>你自己</strong>的资料；角色与账号状态由运营在「成员管理」维护，登录名创建后不可修改</p>
      </div>
    </div>

    <section class="grid-2">
      <!-- 可编辑的资料 -->
      <article class="glass-card">
        <div class="card-head">
          <h3>我的资料</h3>
          <span class="hint">姓名必填；学号同班不可重复，留空表示不填</span>
        </div>

        <div
          v-if="alertMessage"
          ref="alertRef"
          class="error-summary"
          role="alert"
          tabindex="-1"
        >
          {{ alertMessage }}
        </div>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          :disabled="loading"
          @submit.prevent="onSubmit"
        >
          <el-form-item label="姓名" prop="realName">
            <el-input
              v-model="form.realName"
              placeholder="请输入真实姓名"
              maxlength="32"
              show-word-limit
            />
          </el-form-item>
          <el-form-item label="学号" prop="studentNo">
            <el-input
              v-model="form.studentNo"
              placeholder="选填，用于缴费名单与批次排序"
              maxlength="20"
            />
            <div class="form-tip">同班不可与其他成员重复；留空则不设置学号</div>
          </el-form-item>
          <el-form-item label="手机号" prop="phone">
            <el-input
              v-model="form.phone"
              placeholder="选填"
              maxlength="20"
              inputmode="tel"
            />
          </el-form-item>

          <div class="form-actions">
            <el-button @click="onReset">重置</el-button>
            <el-button type="primary" :loading="saving" @click="onSubmit">
              保存修改
            </el-button>
          </div>
        </el-form>
      </article>

      <!-- 只读的账号信息 -->
      <article class="glass-card">
        <div class="card-head">
          <h3>账号信息</h3>
          <span class="hint">这些由运营维护，如需变更请联系生活委员、班长或班主任</span>
        </div>

        <dl class="detail-list" :aria-busy="loading">
          <div class="row">
            <dt>登录名</dt>
            <dd class="strong">{{ userStore.user?.username ?? '—' }}</dd>
          </div>
          <div class="row">
            <dt>角色</dt>
            <dd>
              <el-tag size="small" effect="light">{{ roleText ? ROLE_TEXT[roleText] : '—' }}</el-tag>
            </dd>
          </div>
          <div class="row">
            <dt>所在班级</dt>
            <dd>{{ userStore.user?.className ?? '—' }}</dd>
          </div>
          <div class="row">
            <dt>账号状态</dt>
            <dd>
              <el-tag
                v-if="detail"
                :type="detail.status === 1 ? 'success' : 'info'"
                size="small"
                effect="light"
              >
                {{ detail.status === 1 ? '启用' : '已停用' }}
              </el-tag>
              <span v-else>—</span>
            </dd>
          </div>
          <div class="row">
            <dt>创建时间</dt>
            <dd>{{ detail?.createdAt ?? '—' }}</dd>
          </div>
          <div class="row">
            <dt>最近登录</dt>
            <dd>{{ detail?.lastLoginAt ?? '—' }}</dd>
          </div>
        </dl>

        <p class="readonly-hint">
          修改密码请用右上角头像菜单里的「修改密码」（需验证原密码）。
        </p>
      </article>
    </section>
  </div>
</template>

<style scoped>
.page-head h2 {
  margin: 0;
  font-size: 20px;
}

.page-head p {
  margin: var(--space-xs) 0 0;
  font-size: 13px;
  color: var(--color-muted-fg);
}

/* 与仪表盘 .grid-2 同口径：两列 + var(--space-md) 间距 */
.grid-2 {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  gap: var(--space-md);
  align-items: start;
}

/* 卡片内边距跟仪表盘 .stat / .panel 一致（--space-md），
   圆角/描边/阴影由全局 .glass-card 提供（--radius-lg = 12px），这里不要覆盖 */
.glass-card {
  padding: var(--space-md);
}

.card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-sm);
  margin-bottom: var(--space-md);
  padding-bottom: var(--space-sm);
  border-bottom: 1px solid var(--color-border);
  flex-wrap: wrap;
}

.card-head h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}

.hint {
  font-size: 12px;
  color: var(--color-muted-fg);
}

.error-summary {
  border: 1px solid rgba(220, 38, 38, 0.35);
  background: rgba(220, 38, 38, 0.06);
  color: var(--color-destructive-text);
  border-radius: var(--radius);
  padding: var(--space-sm) var(--space-md);
  margin-bottom: var(--space-md);
  font-size: 13px;
}

.form-tip {
  font-size: 12px;
  color: var(--color-muted-fg);
  line-height: 1.5;
  margin-top: var(--space-xs);
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-sm);
  margin-top: var(--space-sm);
}

.detail-list {
  margin: 0;
  display: flex;
  flex-direction: column;
}

.detail-list .row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
  padding: var(--space-sm) 0;
  border-bottom: 1px dashed var(--color-border);
}

.detail-list .row:last-child {
  border-bottom: none;
}

.detail-list dt {
  color: var(--color-muted-fg);
  font-size: 13px;
  flex: none;
}

.detail-list dd {
  margin: 0;
  font-size: 14px;
  text-align: right;
  min-width: 0;
  overflow-wrap: anywhere;
}

.strong {
  font-weight: 600;
}

.readonly-hint {
  margin: var(--space-md) 0 0;
  padding: var(--space-sm) var(--space-md);
  background: var(--color-muted);
  border-radius: var(--radius);
  font-size: 12px;
  color: var(--color-muted-fg);
  line-height: 1.6;
}

@media (max-width: 900px) {
  .grid-2 {
    grid-template-columns: 1fr;
  }
}
</style>
