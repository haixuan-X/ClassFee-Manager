<script setup lang="ts">
import { nextTick, reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { changePassword } from '@/api/auth'
import { getErrorMessage } from '@/api/request'

const visible = defineModel<boolean>({ required: true })

const formRef = ref<FormInstance>()
const loading = ref(false)
const alertMessage = ref('')
const alertRef = ref<HTMLElement>()

const form = reactive({
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
})

const rules: FormRules<typeof form> = {
  oldPassword: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, max: 32, message: '新密码长度需为 6-32 位', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (value !== form.newPassword) {
          callback(new Error('两次输入的密码不一致'))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
}

/** 打开弹窗时的触发元素；关闭后要把焦点还回去，否则键盘用户会“掉”到 body */
let opener: HTMLElement | null = null

/** 关闭动画结束后由 el-dialog 的 close-auto-focus / closed 触发（EP 的 focus-trap 会先“误还”给已销毁的菜单项） */
function restoreFocus() {
  const usable = (el: HTMLElement | null): el is HTMLElement =>
    !!el && el.isConnected && el.getClientRects().length > 0
  const target = usable(opener)
    ? opener
    : document.querySelector<HTMLElement>('[data-restore-focus]')
  target?.focus()
}

// 打开时重置，避免上次的错误提示残留
watch(visible, async (open) => {
  if (!open) return
  opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
  alertMessage.value = ''
  formRef.value?.resetFields()
  await nextTick()
  // 焦点移到第一个输入框（限定在本弹窗的 form 内，不命中页面上其他 .el-dialog）
  const formEl = formRef.value?.$el as HTMLElement | undefined
  formEl?.querySelector<HTMLElement>('.el-input__inner')?.focus()
})

async function onSubmit() {
  if (!formRef.value) return
  if (loading.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) {
    alertMessage.value = '表单有未填写或格式不正确的项，请按下方提示修改'
    await nextTick()
    alertRef.value?.focus()
    return
  }

  loading.value = true
  alertMessage.value = ''
  try {
    await changePassword({
      oldPassword: form.oldPassword,
      newPassword: form.newPassword,
    })
    ElMessage.success('密码已修改，下次登录请使用新密码')
    visible.value = false
  } catch (error) {
    alertMessage.value = getErrorMessage(error, '修改失败，请稍后重试')
    await nextTick()
    alertRef.value?.focus()
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    title="修改密码"
    width="min(480px, 92vw)"
    destroy-on-close
    @close-auto-focus="restoreFocus"
    @closed="restoreFocus"
  >
    <div
      v-if="alertMessage"
      ref="alertRef"
      class="error-summary"
      role="alert"
      tabindex="-1"
    >
      {{ alertMessage }}
    </div>

    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="onSubmit">
      <el-form-item label="原密码" prop="oldPassword">
        <el-input
          v-model="form.oldPassword"
          type="password"
          show-password
          placeholder="请输入当前密码"
          autocomplete="current-password"
        />
      </el-form-item>
      <el-form-item label="新密码" prop="newPassword">
        <el-input
          v-model="form.newPassword"
          type="password"
          show-password
          placeholder="6-32 位"
          autocomplete="new-password"
        />
      </el-form-item>
      <el-form-item label="确认新密码" prop="confirmPassword">
        <el-input
          v-model="form.confirmPassword"
          type="password"
          show-password
          placeholder="再次输入新密码"
          autocomplete="new-password"
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="loading" @click="onSubmit">确认修改</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.error-summary {
  border: 1px solid rgba(220, 38, 38, 0.35);
  background: rgba(220, 38, 38, 0.06);
  color: var(--color-destructive-text);
  border-radius: var(--radius);
  padding: 11px 13px;
  margin-bottom: 16px;
  font-size: 13px;
}
</style>
