<script setup lang="ts">
import { nextTick, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Lock, User } from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'
import { login } from '@/api/auth'
import { getErrorMessage } from '@/api/request'
import { useUserStore } from '@/stores/user'
import type { LoginRequest } from '@/types'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
/** 顶部错误摘要（role=alert，键盘/读屏可发现） */
const alertMessage = ref('')
const alertRef = ref<HTMLElement>()

const form = reactive<LoginRequest>({
  username: '',
  password: '',
})

const rules: FormRules<LoginRequest> = {
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 32, message: '密码长度需为 6-32 位', trigger: 'blur' },
  ],
}

/**
 * 只允许站内路径：redirect 来自 URL query，
 * 若放行 `//evil.com` 这类协议相对地址，会造成开放重定向（甚至让 pushState 抛异常）。
 */
function safeRedirect(): string {
  const raw = typeof route.query.redirect === 'string' ? route.query.redirect : ''
  const isSafe = raw.startsWith('/') && !raw.startsWith('//') && !raw.includes('\\')
  return isSafe ? raw : '/dashboard'
}

async function onSubmit() {
  if (!formRef.value) return

  // blur 即校验；这里提交时再统一校验一次
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) {
    alertMessage.value = '请按提示补全账号和密码'
    await nextTick()
    alertRef.value?.focus()
    return
  }

  if (loading.value) return
  loading.value = true
  alertMessage.value = ''
  try {
    const result = await login(form)
    userStore.setSession(result)
    await router.replace(safeRedirect())
  } catch (error) {
    alertMessage.value = getErrorMessage(error, '登录失败，请稍后重试')
    await nextTick()
    alertRef.value?.focus()
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <main class="login-card glass-card">
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">
          <el-icon :size="22"><Wallet /></el-icon>
        </div>
        <div>
          <h1>班费收支系统</h1>
          <p>公开 · 透明 · 可追溯</p>
        </div>
      </div>

      <!-- 提交失败的错误摘要：role=alert 并移入焦点 -->
      <div
        v-if="alertMessage"
        ref="alertRef"
        class="error-summary"
        role="alert"
        tabindex="-1"
      >
        <b>无法登录：</b>{{ alertMessage }}
      </div>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        size="large"
        @keyup.enter="onSubmit"
      >
        <el-form-item label="账号" prop="username">
          <el-input
            v-model.trim="form.username"
            :prefix-icon="User"
            placeholder="学号或登录名"
            autocomplete="username"
            clearable
          />
        </el-form-item>

        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            :prefix-icon="Lock"
            type="password"
            show-password
            placeholder="请输入密码"
            autocomplete="current-password"
          />
        </el-form-item>

        <el-button class="submit" type="primary" size="large" :loading="loading" @click="onSubmit">
          登 录
        </el-button>
      </el-form>

      <div class="demo-hint">
        <span>账号由老师在「成员管理」中创建，初始密码默认 123456</span>
      </div>
    </main>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: var(--space-lg) var(--space-md);
}

.login-card {
  width: min(420px, 100%);
  padding: 32px 28px 24px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 22px;
}

.brand-mark {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: var(--color-primary);
  color: var(--color-on-primary);
  display: grid;
  place-items: center;
  flex: none;
}

.brand h1 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  line-height: 1.3;
}

.brand p {
  margin: 2px 0 0;
  font-size: 12.5px;
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

.submit {
  width: 100%;
  margin-top: 4px;
}

.demo-hint {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px dashed var(--color-border);
  font-size: 12.5px;
  color: var(--color-muted-fg);
}

/* 「填入」是 link 按钮，默认只有 ~24px 高，移动端点不准（MASTER.md §8 触控 ≥40px） */
.demo-hint .el-button {
  min-height: 40px;
  min-width: 40px;
}
</style>
