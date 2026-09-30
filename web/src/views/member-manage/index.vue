<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { getErrorMessage } from '@/api/request'
import { createUser, deleteUser, fetchUsers, updateUser } from '@/api/users'
import { useModal } from '@/composables/useModal'
import { useUserStore } from '@/stores/user'
import type { Role, UserAccount } from '@/types'
import { ROLE_TEXT } from '@/types'

/**
 * 成员管理（第七轮：老师建班）：新增账号 / 编辑资料与学号 / 重置密码 / 停用启用 / 删除。
 * 仅运营角色（生活委员 ADMIN / 班长 MONITOR / 班主任 TEACHER）可见，后端 /api/users 同口径强制校验；
 * 停用即禁止登录但保留历史；**删除仅限「零引用」账号**（无流水 / 缴费 / 公告 / 批次），
 * 有历史引用时后端 400 拒绝并引导改用停用。
 */
const userStore = useUserStore()

const loading = ref(true)
const listLoading = ref(false)
const users = ref<UserAccount[]>([])
const keyword = ref('')
/** 请求序号：连点查询时丢弃过期响应 */
let seq = 0

/** 弹窗级错误摘要（MASTER §8：就地错误之外再给 SR 可播报的 role="alert" 汇总） */
const alertMessage = ref('')
const alertRef = ref<HTMLElement>()

async function showAlert(message: string) {
  alertMessage.value = message
  await nextTick()
  alertRef.value?.focus()
}

async function load() {
  const s = ++seq
  listLoading.value = true
  try {
    const data = await fetchUsers(keyword.value.trim() || undefined)
    if (s !== seq) return
    users.value = data
  } catch {
    if (s === seq) users.value = []
  } finally {
    if (s === seq) listLoading.value = false
  }
}

function applyFilters() {
  load()
}

function resetFilters() {
  keyword.value = ''
  load()
}

/* ============================ 新增 ============================ */

const createVisible = ref(false)
const createLoading = ref(false)
const createFormRef = ref<FormInstance>()
// Esc 走捕获阶段兜底（EP 原生 close-on-press-escape 关不掉焦点在 select 上的弹窗），关闭后焦点还原
const { restoreFocus: restoreCreateFocus } = useModal(createVisible)
const createForm = reactive({
  username: '',
  realName: '',
  studentNo: '',
  password: '',
  phone: '',
  role: 'MEMBER' as Role,
})

const createRules: FormRules = {
  username: [
    { required: true, message: '请输入登录名', trigger: 'blur' },
    { max: 32, message: '登录名最多 32 字', trigger: 'blur' },
  ],
  realName: [
    { required: true, message: '请输入姓名', trigger: 'blur' },
    { max: 32, message: '姓名最多 32 字', trigger: 'blur' },
  ],
  studentNo: [{ max: 20, message: '学号最多 20 字', trigger: 'blur' }],
  password: [
    {
      validator: (_rule, value: string, callback) => {
        if (value && (value.length < 6 || value.length > 32)) {
          callback(new Error('密码长度需为 6-32 位'))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
  phone: [{ max: 20, message: '手机号最多 20 位', trigger: 'blur' }],
}

function openCreate() {
  createForm.username = ''
  createForm.realName = ''
  createForm.studentNo = ''
  createForm.password = ''
  createForm.phone = ''
  createForm.role = 'MEMBER'
  alertMessage.value = ''
  createVisible.value = true
}

async function submitCreate() {
  if (!createFormRef.value) return
  try {
    await createFormRef.value.validate()
  } catch {
    await showAlert('表单有未填写或格式不正确的项，请按下方提示修改')
    return
  }
  createLoading.value = true
  alertMessage.value = ''
  try {
    const created = await createUser({
      username: createForm.username.trim(),
      realName: createForm.realName.trim(),
      studentNo: createForm.studentNo.trim() || undefined,
      password: createForm.password.trim() || undefined,
      phone: createForm.phone.trim() || undefined,
      role: createForm.role,
    })
    ElMessage.success(
      `已创建「${created.realName}」，登录名 ${created.username}，初始密码 ${createForm.password.trim() || '123456'}，请转告本人登录后修改`,
    )
    createVisible.value = false
    await load()
  } catch (error) {
    // 拦截器已统一 toast（400 账号已存在 / 学号重复 / 403 无权限）；摘要留在弹窗内供 SR 播报
    await showAlert(getErrorMessage(error, '创建失败，请稍后重试'))
  } finally {
    createLoading.value = false
  }
}

/* ============================ 编辑 ============================ */

const editVisible = ref(false)
const editLoading = ref(false)
const editFormRef = ref<FormInstance>()
const { restoreFocus: restoreEditFocus } = useModal(editVisible)
const editTarget = ref<UserAccount | null>(null)
const editForm = reactive({ realName: '', studentNo: '', phone: '' })

const editRules: FormRules = {
  realName: [
    { required: true, message: '请输入姓名', trigger: 'blur' },
    { max: 32, message: '姓名最多 32 字', trigger: 'blur' },
  ],
  studentNo: [{ max: 20, message: '学号最多 20 字', trigger: 'blur' }],
  phone: [{ max: 20, message: '手机号最多 20 位', trigger: 'blur' }],
}

function openEdit(row: UserAccount) {
  editTarget.value = row
  editForm.realName = row.realName
  editForm.studentNo = row.studentNo ?? ''
  editForm.phone = row.phone ?? ''
  alertMessage.value = ''
  editVisible.value = true
}

async function submitEdit() {
  if (!editTarget.value || !editFormRef.value) return
  try {
    await editFormRef.value.validate()
  } catch {
    await showAlert('表单有未填写或格式不正确的项，请按下方提示修改')
    return
  }
  editLoading.value = true
  alertMessage.value = ''
  try {
    await updateUser(editTarget.value.id, {
      realName: editForm.realName.trim(),
      // 学号/手机号沿用「空串=清空」语义（后端 None=不改）
      studentNo: editForm.studentNo.trim(),
      phone: editForm.phone.trim(),
    })
    ElMessage.success(`已保存「${editForm.realName.trim()}」的资料`)
    editVisible.value = false
    await load()
  } catch (error) {
    await showAlert(getErrorMessage(error, '保存失败，请稍后重试'))
  } finally {
    editLoading.value = false
  }
}

/* ============================ 重置密码 ============================ */

const resetVisible = ref(false)
const resetLoading = ref(false)
const resetFormRef = ref<FormInstance>()
const { restoreFocus: restoreResetFocus } = useModal(resetVisible)
const resetTarget = ref<UserAccount | null>(null)
const resetForm = reactive({ password: '123456' })

const resetRules: FormRules = {
  password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, max: 32, message: '密码长度需为 6-32 位', trigger: 'blur' },
  ],
}

function openReset(row: UserAccount) {
  resetTarget.value = row
  resetForm.password = '123456'
  alertMessage.value = ''
  resetVisible.value = true
}

async function submitReset() {
  if (!resetTarget.value || !resetFormRef.value) return
  try {
    await resetFormRef.value.validate()
  } catch {
    await showAlert('表单有未填写或格式不正确的项，请按下方提示修改')
    return
  }
  resetLoading.value = true
  alertMessage.value = ''
  try {
    const pwd = resetForm.password.trim()
    await updateUser(resetTarget.value.id, { password: pwd })
    ElMessage.success(`已重置「${resetTarget.value.realName}」的密码为 ${pwd}，原密码立即失效`)
    resetVisible.value = false
  } catch (error) {
    await showAlert(getErrorMessage(error, '重置失败，请稍后重试'))
  } finally {
    resetLoading.value = false
  }
}

/* ============================ 停用 / 启用 ============================ */

async function toggleStatus(row: UserAccount) {
  const disabling = row.status === 1
  if (disabling) {
    if (row.id === userStore.user?.id) {
      ElMessage.warning('不能停用自己的账号')
      return
    }
    try {
      await ElMessageBox.confirm(
        `停用后「${row.realName}」将无法登录，其历史流水与缴费记录保持不变。确定停用？`,
        '停用账号',
        { type: 'warning', confirmButtonText: '停用', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
  }
  try {
    const next = disabling ? 0 : 1
    await updateUser(row.id, { status: next })
    ElMessage.success(disabling ? `已停用「${row.realName}」` : `已启用「${row.realName}」`)
    await load()
  } catch {
    /* 拦截器已统一提示 */
  }
}

/* ============================ 删除（第十二轮） ============================ */

/** 删除账号：后端只放行「零引用」账号；有流水/缴费/公告/批次历史时 400，提示改用停用。 */
async function onDelete(row: UserAccount) {
  if (isSelf(row)) {
    ElMessage.warning('不能删除自己的账号')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认删除「${row.realName}」（登录名 ${row.username}）？删除后该账号立即消失且不可恢复。` +
        '若他已有流水、缴费或公告记录，系统会拒绝删除——那种情况请改用「停用」保留历史。',
      '删除账号',
      { type: 'error', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteUser(row.id)
    ElMessage.success(`已删除「${row.realName}」`)
    await load()
  } catch (error) {
    // 拦截器已提示（被引用 400 / 无权限 403 / 不存在 400）
    if (getErrorMessage(error, '').includes('已关联')) {
      await load()
    }
  }
}

/* ============================ 文案与权限等级 ============================ */

const isSelf = (row: UserAccount) => row.id === userStore.user?.id

/**
 * 账号管理权限等级（第十五轮）：班主任 > 班长 > 生活委员 > 普通成员。
 * 与后端 `security.ROLE_LEVEL` 同口径 —— 前端据此**隐藏越权按钮**，
 * 后端 `require_role_higher` 才是最终边界（前端隐藏不算安全边界）。
 */
const ROLE_LEVEL: Record<Role, number> = {
  MEMBER: 0,
  ADMIN: 1, // 生活委员
  MONITOR: 2, // 班长
  TEACHER: 3, // 班主任
}
const myLevel = computed(() => ROLE_LEVEL[userStore.user?.role ?? 'MEMBER'])

/** 我能否对这一行做「账号管理」动作（编辑/重置密码/停用/删除） */
function canManage(row: UserAccount): boolean {
  if (isSelf(row)) return false // 自己那行本来就不显示这些按钮
  return myLevel.value > (ROLE_LEVEL[row.role] ?? 0)
}

/** 新建成员时可选的角色：**不高于自己**的那些（与后端 create_user 的等级校验同口径） */
const assignableRoles = computed<Role[]>(() =>
  (Object.keys(ROLE_LEVEL) as Role[]).filter((r) => ROLE_LEVEL[r] <= myLevel.value),
)

const roleTagType = (role: Role): 'success' | 'warning' | 'primary' | 'info' => {
  if (role === 'ADMIN') return 'success'
  if (role === 'TEACHER') return 'primary'
  if (role === 'MONITOR') return 'warning'
  return 'info'
}

const emptyText = '暂无账号，点击右上角「新增成员」创建登录账号'

onMounted(async () => {
  loading.value = true
  try {
    await load()
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>成员管理</h2>
        <p>为全班创建登录账号、维护资料与密码；停用后无法登录，历史数据保留</p>
      </div>
      <el-button type="primary" @click="openCreate">新增成员</el-button>
    </div>

    <!-- 筛选栏 -->
    <section class="glass-card filters" aria-label="筛选条件">
      <el-input
        v-model="keyword"
        class="f-keyword"
        placeholder="搜索姓名 / 登录名 / 学号 / 手机号"
        clearable
        aria-label="关键字"
        @keyup.enter="applyFilters"
        @clear="applyFilters"
      />
      <el-button type="primary" plain @click="applyFilters">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
    </section>

    <!-- 桌面：表格 -->
    <section
      class="glass-card table-wrap desktop-only"
      aria-label="账号列表"
      :aria-busy="loading || listLoading"
      v-loading="loading || listLoading"
    >
      <el-table :data="users" :empty-text="emptyText">
        <el-table-column label="成员" min-width="180">
          <template #default="{ row }">
            <div class="who">
              <b>{{ row.realName }}</b>
              <el-tag v-if="isSelf(row)" size="small" type="warning" effect="plain">我</el-tag>
            </div>
            <span class="muted sn">{{ row.username }}</span>
            <!-- 学号与登录名不同时单列一行（缴费名单、批次排序用学号） -->
            <span v-if="row.studentNo && row.studentNo !== row.username" class="muted sn">
              学号 {{ row.studentNo }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="角色" width="110">
          <template #default="{ row }">
            <el-tag :type="roleTagType(row.role)" size="small" effect="light">
              {{ ROLE_TEXT[row.role as Role] }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="手机号" width="130">
          <template #default="{ row }">
            <span class="muted">{{ row.phone ?? '—' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="88">
          <template #default="{ row }">
            <el-tag
              :type="row.status === 1 ? 'success' : 'info'"
              size="small"
              effect="light"
            >
              {{ row.status === 1 ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="最近登录" width="150">
          <template #default="{ row }">
            <span class="muted">{{ row.lastLoginAt ?? '—' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="248" align="right">
          <template #default="{ row }">
            <!-- 账号管理动作（编辑/重置密码/停用/删除）全部按权限等级收敛：
                 班主任 > 班长 > 生活委员 > 普通成员，低等级看不到高等级行的任何按钮 -->
            <el-button v-if="canManage(row)" size="small" link type="primary" @click="openEdit(row)">
              编辑
            </el-button>
            <el-button v-if="canManage(row)" size="small" link type="primary" @click="openReset(row)">
              重置密码
            </el-button>
            <el-button
              v-if="row.status === 1 && canManage(row)"
              size="small"
              link
              type="warning"
              @click="toggleStatus(row)"
            >
              停用
            </el-button>
            <el-button
              v-else-if="row.status === 0 && canManage(row)"
              size="small"
              link
              type="success"
              @click="toggleStatus(row)"
            >
              启用
            </el-button>
            <el-button
              v-if="canManage(row)"
              size="small"
              link
              type="danger"
              :aria-label="`删除账号：${row.realName}`"
              @click="onDelete(row)"
            >
              删除
            </el-button>
            <span v-else class="muted self-hint">当前账号</span>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <!-- 移动端：卡片（不横向滚动，MASTER §4） -->
    <div
      class="cards mobile-only"
      :class="{ 'is-loading': loading || listLoading }"
      aria-label="账号列表"
      :aria-busy="loading || listLoading"
      v-loading="loading || listLoading"
    >
      <div v-for="row in users" :key="row.id" class="glass-card card">
        <div class="card-top">
          <div class="who">
            <b>{{ row.realName }}</b>
            <el-tag v-if="isSelf(row)" size="small" type="warning" effect="plain">我</el-tag>
            <el-tag :type="roleTagType(row.role)" size="small" effect="light">
              {{ ROLE_TEXT[row.role as Role] }}
            </el-tag>
          </div>
          <el-tag :type="row.status === 1 ? 'success' : 'info'" size="small" effect="light">
            {{ row.status === 1 ? '启用' : '停用' }}
          </el-tag>
        </div>
        <span class="muted sn">{{ row.username }}</span>
        <span v-if="row.studentNo && row.studentNo !== row.username" class="muted sn">
          学号 {{ row.studentNo }}
        </span>
        <div class="card-mid">
          <span class="muted">{{ row.phone ?? '未留手机号' }}</span>
          <span class="muted">最近登录 {{ row.lastLoginAt ?? '—' }}</span>
        </div>
        <div class="card-actions">
          <el-button v-if="canManage(row)" size="small" link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="canManage(row)" size="small" link type="primary" @click="openReset(row)">重置密码</el-button>
          <el-button
            v-if="row.status === 1 && canManage(row)"
            size="small"
            link
            type="warning"
            @click="toggleStatus(row)"
          >
            停用
          </el-button>
          <el-button
            v-else-if="row.status === 0 && canManage(row)"
            size="small"
            link
            type="success"
            @click="toggleStatus(row)"
          >
            启用
          </el-button>
          <el-button
            v-if="canManage(row)"
            size="small"
            link
            type="danger"
            :aria-label="`删除账号：${row.realName}`"
            @click="onDelete(row)"
          >
            删除
          </el-button>
        </div>
      </div>

      <div v-if="users.length === 0 && !loading" class="glass-card card empty-card">
        <p class="muted">{{ emptyText }}</p>
      </div>
    </div>

    <!-- 新增成员 -->
    <el-dialog
      v-model="createVisible"
      title="新增成员"
      width="min(440px, 92vw)"
      destroy-on-close
      :close-on-press-escape="false"
      @closed="restoreCreateFocus"
    >
      <div
        v-if="alertMessage"
        ref="alertRef"
        class="error-summary"
        role="alert"
        tabindex="-1"
      >
        <b>无法创建：</b>{{ alertMessage }}
      </div>
      <el-form
        ref="createFormRef"
        :model="createForm"
        :rules="createRules"
        label-width="88px"
        @submit.prevent
      >
        <el-form-item label="登录名" prop="username">
          <el-input
            v-model="createForm.username"
            placeholder="学号或自定义登录名"
            maxlength="32"
            autocomplete="off"
          />
        </el-form-item>
        <el-form-item label="学号" prop="studentNo">
          <el-input
            v-model.trim="createForm.studentNo"
            placeholder="选填，留空默认与登录名相同"
            maxlength="20"
            show-word-limit
            autocomplete="off"
          />
          <div class="form-tip">学号用于缴费名单与批次排序，同班不可重复</div>
        </el-form-item>
        <el-form-item label="姓名" prop="realName">
          <el-input v-model="createForm.realName" placeholder="成员姓名" maxlength="32" />
        </el-form-item>
        <el-form-item label="初始密码" prop="password">
          <el-input
            v-model="createForm.password"
            placeholder="留空则为 123456"
            maxlength="32"
            show-password
            autocomplete="new-password"
          />
        </el-form-item>
        <el-form-item label="手机号" prop="phone">
          <el-input v-model="createForm.phone" placeholder="选填" maxlength="20" />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-select v-model="createForm.role" aria-label="角色">
            <el-option
              v-for="r in assignableRoles"
              :key="r"
              :label="ROLE_TEXT[r]"
              :value="r"
            />
          </el-select>
          <div class="form-tip">
            普通成员只看账本、不能记账；生活委员 / 班长 / 班主任都可记账、缴费、管成员与发公告。<br />
            管理权限按 <strong>班主任 &gt; 班长 &gt; 生活委员 &gt; 普通成员</strong> 分级：
            只能管理比自己低级的账号，也不能创建比自己高级的角色。
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="createLoading" @click="submitCreate">
          创建
        </el-button>
      </template>
    </el-dialog>

    <!-- 编辑资料 -->
    <el-dialog
      v-model="editVisible"
      :title="`编辑资料 · ${editTarget?.realName ?? ''}`"
      width="min(420px, 92vw)"
      destroy-on-close
      :close-on-press-escape="false"
      @closed="restoreEditFocus"
    >
      <div
        v-if="alertMessage"
        ref="alertRef"
        class="error-summary"
        role="alert"
        tabindex="-1"
      >
        <b>无法保存：</b>{{ alertMessage }}
      </div>
      <el-form
        ref="editFormRef"
        :model="editForm"
        :rules="editRules"
        label-width="88px"
        @submit.prevent
      >
        <el-form-item label="姓名" prop="realName">
          <el-input v-model="editForm.realName" maxlength="32" />
        </el-form-item>
        <el-form-item label="学号" prop="studentNo">
          <el-input
            v-model.trim="editForm.studentNo"
            placeholder="留空则清空学号"
            maxlength="20"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="手机号" prop="phone">
          <el-input v-model="editForm.phone" placeholder="留空则清空" maxlength="20" />
        </el-form-item>
        <div class="form-tip">登录名创建后不可修改；学号可随时更正（同班不可重复）</div>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editLoading" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 重置密码 -->
    <el-dialog
      v-model="resetVisible"
      :title="`重置密码 · ${resetTarget?.realName ?? ''}`"
      width="min(420px, 92vw)"
      destroy-on-close
      :close-on-press-escape="false"
      @closed="restoreResetFocus"
    >
      <div
        v-if="alertMessage"
        ref="alertRef"
        class="error-summary"
        role="alert"
        tabindex="-1"
      >
        <b>无法重置：</b>{{ alertMessage }}
      </div>
      <el-form
        ref="resetFormRef"
        :model="resetForm"
        :rules="resetRules"
        label-width="88px"
        @submit.prevent
      >
        <el-form-item label="新密码" prop="password">
          <el-input
            v-model="resetForm.password"
            maxlength="32"
            show-password
            autocomplete="new-password"
          />
        </el-form-item>
        <div class="form-tip">
          重置后原密码立即失效（登录名 {{ resetTarget?.username ?? '' }}）；本人也可登录后在右上角自行修改
        </div>
      </el-form>
      <template #footer>
        <el-button @click="resetVisible = false">取消</el-button>
        <el-button type="primary" :loading="resetLoading" @click="submitReset">
          重置
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

/* 筛选栏 */
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-sm);
  padding: var(--space-md);
  align-items: center;
}

.f-keyword {
  width: 260px;
}

.table-wrap {
  padding: var(--space-md);
  min-height: 320px;
  overflow: hidden;
}

.who {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.sn {
  display: block;
  font-size: 12px;
}

.muted {
  color: var(--color-muted-fg);
}

.self-hint {
  font-size: 12px;
}

/* 移动端卡片 */
.cards {
  display: none;
  flex-direction: column;
  gap: var(--space-sm);
}

.cards.is-loading {
  min-height: 320px;
}

.card {
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.card-mid {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 13px;
}

.card-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-sm);
  margin-top: 4px;
}

.empty-card {
  padding: var(--space-md);
  text-align: center;
}

.empty-card p {
  margin: 0;
  font-size: 13px;
}

.form-tip {
  font-size: 12px;
  color: var(--color-muted-fg);
  line-height: 1.5;
  margin-top: 2px;
}

/* 弹窗错误摘要（与 BatchPayDialog 等同款样式） */
.error-summary {
  border: 1px solid rgba(220, 38, 38, 0.35);
  background: rgba(220, 38, 38, 0.06);
  color: var(--color-destructive-text);
  border-radius: var(--radius);
  padding: 11px 13px;
  margin-bottom: 16px;
  font-size: 13px;
}

/* ≤1023 切卡片列表（卡片携带全部字段），不出现横向滚动 */
@media (max-width: 1023px) {
  .desktop-only {
    display: none;
  }

  .cards {
    display: flex;
  }
}

@media (max-width: 768px) {
  .page-head h2 {
    font-size: 20px;
  }

  .f-keyword {
    width: 100%;
    max-width: none;
  }
}
</style>
