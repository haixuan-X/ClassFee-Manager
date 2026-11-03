<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createCollegeDean, fetchCollegeDeans, fetchCollegeFields } from '@/api/college'
import { getErrorMessage } from '@/api/request'
import type { CollegeClassChoice, CollegeDeanList } from '@/types'

/**
 * 院长账号（第五十二轮）。
 *
 * ## 为什么单独一页，而不是复用「班级 → 成员管理」
 *
 * 纯院长不参与班级事务：后端白名单里没有 `/api/users`，侧栏也不给
 * 「班级」这一组。但「再开一个院长」是**学院级**的事，不能因此没有入口，
 * 否则院长账号只能靠改库或部署声明新增。
 *
 * 而成员管理是**班级视角**：列表按「我能管的班」过滤、建号默认落在当前班。
 * 把纯院长塞进去，他会看到一屏学生账号，还能顺手建班主任——和
 * 「纯院长只管学院」直接矛盾。所以这里只列院长、只建院长。
 *
 * ## 新院长：纯院长还是「院长 + 班主任」
 *
 * 建出来的院长**默认是纯院长**（只管学院）——这是院长账号页最常见的用途。
 * 需要兼班主任的，建号时选「院长 + 班主任」并勾选要带的班：
 * 他**真当那几个班的班主任**（占名额，名册里看得见）；一个班一位，
 * 被占的班会被后端拒绝并提示「已有班主任，请到「改班主任安排」改人」。
 */
const list = ref<CollegeDeanList | null>(null)
const loading = ref(true)
const loadError = ref(false)
const rows = computed(() => list.value?.rows ?? [])

/** 新增弹窗 */
const open = ref(false)
const saving = ref(false)
const form = reactive({
  realName: '',
  username: '',
  password: '',
  phone: '',
  /** true = 纯院长（默认）；false = 院长 + 班主任 */
  deanOnly: true,
  /** 「院长 + 班主任」时要带的班（下拉里勾选；可多选） */
  classIds: [] as number[],
})

/** 全部启用的班（下拉选项） */
const allClasses = ref<CollegeClassChoice[]>([])

async function load() {
  loading.value = true
  try {
    list.value = await fetchCollegeDeans()
    loadError.value = false
  } catch {
    list.value = null
    loadError.value = true
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.realName = ''
  form.username = ''
  form.password = ''
  form.phone = ''
  form.deanOnly = true
  form.classIds = []
  open.value = true
}

async function submit() {
  const realName = form.realName.trim()
  const username = form.username.trim()
  const password = form.password.trim()
  const phone = form.phone.trim()
  const deanOnly = form.deanOnly
  const classIds = [...form.classIds]
  // 前端先挡一遍明显问题，省一次往返；真正的边界（登录名唯一、密码长度、
  // 班级冲突）仍在后端，两边不是重复实现，是同一套规则的两道门。
  if (!realName) {
    ElMessage.warning('请输入姓名')
    return
  }
  if (!username) {
    ElMessage.warning('请输入登录名')
    return
  }
  if (username.length > 32) {
    ElMessage.warning('登录名最多 32 字')
    return
  }
  if (password && password.length < 6) {
    ElMessage.warning('密码长度需为 6-32 位')
    return
  }
  if (!deanOnly && classIds.length === 0) {
    ElMessage.warning('「院长 + 班主任」至少要选一个他要带的班')
    return
  }
  saving.value = true
  try {
    await createCollegeDean({
      username,
      realName,
      password: password || undefined,
      phone: phone || undefined,
      deanOnly,
      classIds: deanOnly ? undefined : classIds,
    })
    ElMessage.success(password ? '院长账号已创建' : '院长账号已创建，初始密码 123456')
    open.value = false
    await load()
  } catch (e) {
    // 登录名重复、班级冲突、权限不足等：后端文案已经足够具体，直接透出
    ElMessage.error(getErrorMessage(e))
  } finally {
    saving.value = false
  }
}

function fmtTime(value: string | null | undefined): string {
  return value ? value.slice(0, 16) : '—'
}

async function fetchClasses() {
  try {
    allClasses.value = (await fetchCollegeFields()).classes
  } catch {
    allClasses.value = []
  }
}

onMounted(() => {
  void fetchClasses()
  void load()
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>院长账号</h2>
        <p>
          可以有多位院长，彼此同级。新账号默认是<strong>纯院长</strong>（只管学院）；
          需要兼班主任的，建号时选<strong>「院长 + 班主任」</strong>并勾选他要带的班，
          也可以由本人登录后在「个人信息 → 职务范围」切换。
        </p>
      </div>
      <el-button type="primary" @click="openCreate">新增院长</el-button>
    </div>

    <section class="glass-card" aria-label="院长账号" :aria-busy="loading">
      <div v-loading="loading" class="table-wrap">
        <table v-if="rows.length > 0" class="roster">
          <thead>
            <tr>
              <th scope="col">姓名</th>
              <th scope="col">登录名</th>
              <th scope="col">手机号</th>
              <th scope="col">职务范围</th>
              <th scope="col">账号状态</th>
              <th scope="col">最近登录</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td>
                <span v-if="row.realName">{{ row.realName }}</span>
                <span v-else class="muted">未填姓名</span>
              </td>
              <td class="num">{{ row.username }}</td>
              <td class="num">{{ row.phone || '—' }}</td>
              <td>
                <el-tag size="small" effect="plain" :type="row.deanOnly ? 'info' : 'danger'">
                  {{ row.deanOnly ? '纯院长' : '院长 + 班主任' }}
                </el-tag>
              </td>
              <td>
                <el-tag size="small" effect="plain" :type="row.status === 1 ? 'success' : 'info'">
                  {{ row.status === 1 ? '启用' : '停用' }}
                </el-tag>
              </td>
              <td class="num">{{ fmtTime(row.lastLoginAt) }}</td>
            </tr>
          </tbody>
        </table>

        <el-empty
          v-else-if="!loading"
          :description="loadError ? '院长账号加载失败，请检查网络后重试' : '还没有院长账号'"
          :image-size="80"
        >
          <el-button v-if="loadError" type="primary" @click="load">重新加载</el-button>
        </el-empty>
      </div>
    </section>

    <p v-if="rows.length > 0" class="hint">
      共 {{ rows.length }} 位院长。院长之间同级：不能互相停用、重置密码或删除。
    </p>

    <el-dialog v-model="open" title="新增院长" width="480px" append-to-body>
      <p class="hint" style="margin: 0 0 14px">
        新账号默认<strong>纯院长</strong>：全校学生名册、班主任名册、学院任务、
        学生情况总览。<strong>「院长 + 班主任」</strong>会让他真当班主任——
        一个班只能有一位，建号前先在下面勾好他要带的班；名册上他占他带的班主任名额。
      </p>
      <el-form label-width="80px" @submit.prevent>
        <el-form-item label="姓名" required>
          <el-input v-model="form.realName" maxlength="32" placeholder="院长姓名" />
        </el-form-item>
        <el-form-item label="登录名" required>
          <el-input v-model="form.username" maxlength="32" placeholder="用于登录，全局唯一" />
        </el-form-item>
        <el-form-item label="初始密码">
          <el-input
            v-model="form.password"
            maxlength="32"
            show-password
            placeholder="留空 = 123456"
          />
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="form.phone" maxlength="20" placeholder="选填" />
        </el-form-item>
        <el-form-item label="职责范围" required>
          <el-radio-group v-model="form.deanOnly">
            <el-radio :value="true">纯院长（只管学院）</el-radio>
            <el-radio :value="false">院长 + 班主任</el-radio>
          </el-radio-group>
          <div class="form-tip">
            「院长 + 班主任」= 他真当班主任（占班主任名额）——负责账目、缴费、班级成员、
            学生信息、任务。下方勾选他要带的班，建号后立刻生效。
          </div>
        </el-form-item>
        <el-form-item v-if="!form.deanOnly" label="带的班" required>
          <el-select
            v-model="form.classIds"
            multiple
            filterable
            style="width: 100%"
            placeholder="勾选他要带的班"
          >
            <el-option
              v-for="c in allClasses"
              :key="c.id"
              :label="(c.grade ? c.grade + ' · ' : '') + c.className"
              :value="c.id"
            />
          </el-select>
          <div class="form-tip">
            至少勾选一个；每个班只能有一位班主任，被占的班会被后端拒绝并提示
            「到「班主任名册 → 改班主任安排」改人」。
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="open = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">创建</el-button>
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

.table-wrap {
  overflow-x: auto;
  min-height: 80px;
}

.roster {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.roster th,
.roster td {
  padding: 9px 12px;
  border-bottom: 1px solid var(--color-border);
  text-align: left;
  white-space: nowrap;
}

.roster thead th {
  background: var(--color-surface, #fff);
  font-weight: 600;
  color: var(--color-foreground);
}

.muted {
  color: var(--color-muted-fg);
}

.hint {
  margin: 0;
  font-size: 12px;
  color: var(--color-muted-fg);
}

.form-tip {
  margin-top: 6px;
  font-size: 12px;
  color: var(--color-muted-fg);
  line-height: 1.6;
}
</style>
