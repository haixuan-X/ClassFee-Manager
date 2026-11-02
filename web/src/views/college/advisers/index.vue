<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getErrorMessage } from '@/api/request'
import {
  createCollegeTeacher,
  deleteCollegeClasses,
  downloadAdviserTemplate,
  fetchCollegeAdvisers,
  fetchCollegeTeacherCandidates,
  importCollegeAdvisers,
  setCollegeClassTeacher,
} from '@/api/college'
import type { CollegeAdviserList, CollegeAdviserRow } from '@/types'

/**
 * 学院成员管理 = **班主任（导员）名册**（第三十轮）。
 *
 * ## 一班一行，不是全院账号列表
 *
 * 用户口径：「成员管理里面就存班主任（导员）的」。所以这里列的是
 * **各班的班主任**，不是院里的全部账号——普通同学、班长、生活委员
 * 都不在这份名册里。
 *
 * ## 班主任是**班**的属性（第三十二轮），**一个班一个**（第五十一轮收紧）
 *
 * 以前是「`sys_user.class_id` 里有他 = 他是这个班的班主任」——一个账号只能
 * 属于一个班，于是「一个老师带两个班」在系统里**表达不出来**。
 * 现在是 `sys_user_class`（人 ↔ 班多对多）：
 * - 院长在这里能**改**每个班的班主任（**一个班一位**，换人=顶替）
 * - 班主任本人在「个人信息」里能改「我带的班」（撞车会 400，指路这里）
 * - 导入的 Excel 里带「班主任」列时，也会按名字自动配上（撞车的行跳过）
 *
 * 「一个老师带好几个班」不受影响——那是**人**的属性；只有「一个班几个
 * 班主任」被收成了一位（用户口径：一个班不可能有两个班主任）。
 *
 * ## 两个来源都给出
 *
 * - 班级信息里登记的班主任**姓名**（`cls_class.head_teacher`）
 * - 该班的**班主任账号**：能登录、有手机号
 *
 * 两者可能对不上（登记了名字没建号，或建了号没填班级信息）。
 * 硬合成一个字段就会丢信息：名字对了但没有账号（没法通知），
 * 或者有账号但班级信息没填（名字是空的）。所以**两列分开摆**，
 * 缺哪个就留空，不编一个「待定」出来。
 *
 * ## 批量删除班主任账号（第五十三轮）
 *
 * 用户口径：名册上勾几行就能清掉误建/离职的班主任。删的是**登录账号**，
 * 不是班级——那个班仍然占一行，只是回到「未建账号」。
 *
 * 为什么不做「批量删除班级」：班级是学生/任务/账目的归属，删一个班要
 * 连带处理的东西太多，不能从一个「班主任名册」页顺手做掉。
 */
const list = ref<CollegeAdviserList | null>(null)
const loading = ref(true)
const loadError = ref(false)

/** 改班主任的弹窗 */
const editOpen = ref(false)
const editSaving = ref(false)
/** 每个班选中的班主任账号 id（第五十一轮：一个班一个，null=暂无） */
const editPicks = ref<Record<number, number | null>>({})
/** 可被选的账号 */
const candidates = ref<{ id: number; username: string; realName: string; role: string }[]>([])

async function load() {
  loading.value = true
  try {
    list.value = await fetchCollegeAdvisers()
    loadError.value = false
    // 勾选状态跟着名册走：别处删掉的班不能还留在选择里，
    // 否则「已选 3 个」点下去只删了 2 个，用户还得自己数。
    const alive = new Set((list.value?.rows ?? []).map((r) => r.classId))
    selectedClassIds.value = selectedClassIds.value.filter((id) => alive.has(id))
  } catch {
    list.value = null
    loadError.value = true
  } finally {
    loading.value = false
  }
}

/**
 * 名册的默认顺序：**年级从新到旧，同年级按班名排**。
 *
 * 后端 `advisers()` 按 `_active_classes`（建班先后）给，于是「检测2406、
 * 大数据2402、检测2402…」年级一样却交错着排，看着像没排过。
 *
 * 排序放在展示层、不改后端，是因为 `_active_classes` 还被全站的班级下拉
 * 和筛选共用——动它会连带改掉别处的顺序，那不在这次要修的范围内。
 * 年级空着的排最后：它表示「还不知道」，不是「最老」。
 *
 * 班级名用 `zh-Hans-CN` + `numeric`：中文按拼音、数字按大小，
 * 这样「检测2402」排在「检测2410」前面（默认字典序会反过来）。
 */
const rows = computed(() => {
  const gradeOf = (r: CollegeAdviserRow): number => {
    const n = Number.parseInt(r.grade, 10)
    return Number.isNaN(n) ? Number.NEGATIVE_INFINITY : n
  }
  return [...(list.value?.rows ?? [])].sort((a, b) => {
    const ga = gradeOf(a)
    const gb = gradeOf(b)
    if (ga !== gb) return gb - ga
    return a.className.localeCompare(b.className, 'zh-Hans-CN', { numeric: true })
  })
})

/**
 * 有班主任账号的班级数 / 总班级数。
 *
 * 现在是**一人一行**（一个班有几个班主任就占几行），所以班级数要**去重**算，
 * 不能拿行数当班级数。
 */
const classCount = computed(() => new Set(rows.value.map((r) => r.classId)).size)
const covered = computed(
  () => new Set(rows.value.filter((r) => r.teacherId !== null).map((r) => r.classId)).size,
)

/** 一个班都没有班主任账号/登记姓名——这是名册最该被看见的问题 */
const uncovered = computed(() => {
  const seen = new Set<string>()
  const out: CollegeAdviserRow[] = []
  for (const r of rows.value) {
    if (seen.has(String(r.classId))) continue
    seen.add(String(r.classId))
    if (r.teacherId === null && !r.headTeacher) out.push(r)
  }
  return out
})

/* ==================== 勾选 + 批量删除班级（第五十六轮） ==================== */

/**
 * 勾的是**班级**（一行一个班），不是账号。
 *
 * 上一版按账号勾：一个老师带两个班，点一行会把两行一起勾上——用户
 * 「明明只选了一个」。删班级是按班删的，所以勾选状态就该存 `classId`。
 */
const selectedClassIds = ref<number[]>([])

/** 名册里出现过的班（一个老师带两班 = 两行，班只算一个） */
const selectableClassIds = computed(() => {
  const out: number[] = []
  for (const r of rows.value) {
    if (!out.includes(r.classId)) out.push(r.classId)
  }
  return out
})

const allSelected = computed(
  () =>
    selectableClassIds.value.length > 0 &&
    selectedClassIds.value.length === selectableClassIds.value.length,
)
const isIndeterminate = computed(
  () =>
    selectedClassIds.value.length > 0 &&
    selectedClassIds.value.length < selectableClassIds.value.length,
)

function toggleAllClasses() {
  selectedClassIds.value = allSelected.value ? [] : [...selectableClassIds.value]
}

function toggleClass(cid: number) {
  const i = selectedClassIds.value.indexOf(cid)
  if (i >= 0) selectedClassIds.value.splice(i, 1)
  else selectedClassIds.value.push(cid)
}

function isPickedClass(cid: number): boolean {
  return selectedClassIds.value.includes(cid)
}

const deleting = ref(false)

/**
 * 删除勾中的**班级**（连同它的字段模板）。
 *
 * 只有空班删得掉：有学生/账目/任务/账号挂着的，后端跳过并给原因，
 * 界面把原因逐条列出来——不然用户只会看到「少删了几个」而不知道为什么。
 */
async function deleteSelectedClasses() {
  const ids = [...selectedClassIds.value]
  if (!ids.length || deleting.value) return
  const names = uniqueClasses.value
    .filter((c) => ids.includes(c.classId))
    .map((c) => c.className)
  try {
    await ElMessageBox.confirm(
      `将删除 ${ids.length} 个班级：${names.join('、')}。\n` +
        '连同这些班的学生、字段模板、任务一起删。' +
        '班里还有学生、账目或账号的会被跳过。删除后不能撤销。',
      '删除班级',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    return // 用户取消
  }
  deleting.value = true
  try {
    const r = await deleteCollegeClasses(ids)
    if (r.deleted > 0) ElMessage.success(`已删除 ${r.deleted} 个班级`)
    if (r.skipped.length > 0) {
      await ElMessageBox.alert(
        r.skipped.map((s) => `${s.className || `#${s.classId}`}：${s.reason}`).join('\n'),
        `${r.skipped.length} 个班没删掉`,
        { confirmButtonText: '知道了' },
      )
    }
    selectedClassIds.value = []
    await load()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '删除失败'))
  } finally {
    deleting.value = false
  }
}

/* ==================== 新增班主任（第五十六轮） ====================
 *
 * 用户口径：演示班清掉之后，班主任由院长自己建——而且要知道
 * 「这个班从哪来」：就从名册里现有的班中选。
 *
 * 建完**当场就是这个班的班主任**（后端一班一位，已有人会 400 指路
 * 「改班主任安排」），省掉「去成员管理建号 → 回来安排」两步。
 */

const createOpen = ref(false)
const creating = ref(false)
const createForm = ref({
  classId: null as number | null,
  realName: '',
  username: '',
  password: '',
  phone: '',
})

/** 可选的班：名册里现有的班（**优先给还没建账号的班**，那是最常见的情形） */
const createClassOptions = computed(() => {
  const has = new Set(rows.value.filter((r) => r.teacherId !== null).map((r) => r.classId))
  return uniqueClasses.value
    .map((c) => ({ id: c.classId, name: c.className, taken: has.has(c.classId) }))
    .sort((a, b) => Number(a.taken) - Number(b.taken))
})

function openCreate() {
  createForm.value = { classId: null, realName: '', username: '', password: '', phone: '' }
  createOpen.value = true
}

async function submitCreate() {
  const f = createForm.value
  const realName = f.realName.trim()
  const username = f.username.trim()
  const password = f.password.trim()
  const phone = f.phone.trim()
  // 前端先挡一遍明显问题，省一次往返；真正的边界（登录名唯一、一班一位、
  // 密码长度）仍在后端，两边不是重复实现，是同一套规则的两道门。
  if (!f.classId) {
    ElMessage.warning('请选择这个班主任带的班')
    return
  }
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
  creating.value = true
  try {
    await createCollegeTeacher({
      classId: f.classId,
      realName,
      username,
      password: password || undefined,
      phone: phone || undefined,
    })
    ElMessage.success(password ? '班主任已创建' : '班主任已创建，初始密码 123456')
    createOpen.value = false
    await load()
  } catch (e) {
    // 登录名重复、该班已有班主任等：后端文案已经够具体，直接透出
    ElMessage.error(getErrorMessage(e))
  } finally {
    creating.value = false
  }
}

/** 改班主任：打开弹窗，预填每个班现在的人 */
async function openArrange() {
  editOpen.value = true
  try {
    const res = await fetchCollegeTeacherCandidates()
    candidates.value = res.teachers ?? []
  } catch {
    candidates.value = []
  }
  // 预填：一个班一位（第五十一轮），没建账号的班是 null
  const picks: Record<number, number | null> = {}
  for (const r of uniqueClasses.value) {
    picks[r.classId] = r.teacherId
  }
  editPicks.value = picks
}

/** 逐班保存（一个班一个请求——一次改多个班要半途失败时状态很难讲清） */
async function saveArrange() {
  editSaving.value = true
  try {
    for (const [cid, id] of Object.entries(editPicks.value)) {
      // el-select 点「清空」后 model 是 ''（不是 null），Number('') === 0 会
      // 把 teacherId=0 发给后端 → 400。统一按 falsy 归成 null = 暂无班主任。
      await setCollegeClassTeacher(Number(cid), id ? Number(id) : null)
    }
    editOpen.value = false
    ElMessage.success('班主任安排已保存')
    await load()
  } catch {
    ElMessage.error('保存失败，请稍后重试')
  } finally {
    editSaving.value = false
  }
}

/* ==================== 导入班主任（方案 A） ==================== */
const importing = ref(false)
const templateLoading = ref(false)
const fileInput = ref<HTMLInputElement>()

function pickFile() {
  fileInput.value?.click()
}

async function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  input.value = ''
  if (!f) return
  importing.value = true
  try {
    const r = await importCollegeAdvisers(f)
    ElMessage.success(
      `导入完成：新增 ${r.created} 人，更新 ${r.updated} 人` +
        (r.skipped ? `，跳过 ${r.skipped} 行` : ''),
    )
    if (r.errors?.length) {
      await ElMessageBox.alert(r.errors.join('\n'), '部分行未导入', {
        confirmButtonText: '知道了',
      })
    }
    await load()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '导入失败'))
  } finally {
    importing.value = false
  }
}

async function onDownloadTemplate() {
  templateLoading.value = true
  try {
    await downloadAdviserTemplate()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '下载模板失败'))
  } finally {
    templateLoading.value = false
  }
}

/** 班级去重（一班一行）——名册是「一个班有几个班主任就几行」 */
const uniqueClasses = computed(() => {
  const seen = new Set<number>()
  const out: CollegeAdviserRow[] = []
  for (const r of rows.value) {
    if (seen.has(r.classId)) continue
    seen.add(r.classId)
    out.push(r)
  }
  return out
})

function fmtTime(value: string | null | undefined): string {
  return value ? value.slice(0, 16) : '—'
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>班主任名册</h2>
        <p>
          各班班主任（导员）一览。<strong>一个老师可以带好几个班</strong>，
          班主任本人也能在「个人信息」里改「我带的班」。
          点「新增班主任」选一个班建号；勾选左侧复选框可以批量删除空班。
        </p>
      </div>
      <div style="display: flex; gap: 8px; flex-wrap: wrap">
        <el-button type="primary" @click="openCreate">新增班主任</el-button>
        <el-button :loading="templateLoading" @click="onDownloadTemplate">下载模板</el-button>
        <el-button :loading="importing" @click="pickFile">导入班主任</el-button>
        <el-button @click="openArrange">改班主任安排</el-button>
        <el-button
          type="danger"
          plain
          :disabled="selectedClassIds.length === 0"
          :loading="deleting"
          @click="deleteSelectedClasses"
        >
          {{
            selectedClassIds.length > 0
              ? `删除选中的班级（${selectedClassIds.length}）`
              : '删除选中的班级'
          }}
        </el-button>
        <input
          ref="fileInput"
          type="file"
          accept=".xlsx,.xls"
          style="display: none"
          @change="onFileChange"
        />
      </div>
    </div>

    <section class="glass-card" aria-label="班主任名册" :aria-busy="loading">
      <div v-if="rows.length > 0" class="table-wrap">
        <table class="roster">
          <thead>
            <tr>
              <th scope="col" class="pick">
                <el-checkbox
                  :model-value="allSelected"
                  :indeterminate="isIndeterminate"
                  :disabled="selectableClassIds.length === 0"
                  aria-label="全选班级"
                  @change="toggleAllClasses"
                />
              </th>
              <th scope="col">班级</th>
              <th scope="col">年级</th>
              <th scope="col">登记班主任</th>
              <th scope="col">班主任</th>
              <th scope="col">登录名</th>
              <th scope="col">手机号</th>
              <th scope="col">账号状态</th>
              <th scope="col">最近登录</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in rows" :key="`${row.classId}-${row.teacherId ?? 'none'}-${i}`">
              <td class="pick">
                <el-checkbox
                  :model-value="isPickedClass(row.classId)"
                  :aria-label="`选择 ${row.className}`"
                  @change="toggleClass(row.classId)"
                />
              </td>
              <td>{{ row.className }}</td>
              <td>{{ row.grade || '—' }}</td>
              <td>
                <span v-if="row.headTeacher">{{ row.headTeacher }}</span>
                <span v-else class="muted">未登记</span>
              </td>
              <td>
                <span v-if="row.realName">{{ row.realName }}</span>
                <span v-else class="muted">未建账号</span>
              </td>
              <td class="num">{{ row.username || '—' }}</td>
              <td class="num">{{ row.phone || '—' }}</td>
              <td>
                <el-tag
                  v-if="row.status !== null"
                  size="small"
                  effect="plain"
                  :type="row.status === 1 ? 'success' : 'info'"
                >
                  {{ row.status === 1 ? '启用' : '停用' }}
                </el-tag>
                <span v-else class="muted">—</span>
              </td>
              <td class="num">{{ fmtTime(row.lastLoginAt) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <el-empty
        v-else-if="!loading"
        :description="loadError ? '名册加载失败，请检查网络后重试' : '还没有班级'"
        :image-size="80"
      >
        <el-button v-if="loadError" type="primary" @click="load">重新加载</el-button>
      </el-empty>
    </section>

    <p v-if="rows.length > 0" class="hint">
      共 {{ classCount }} 个班级、{{ rows.filter((r) => r.teacherId !== null).length }} 位班主任，
      其中 {{ covered }} 个班有班主任账号。
      <span v-if="uncovered.length > 0">
        <b>{{ uncovered.length }}</b> 个班级既没登记班主任姓名、也没有班主任账号
        （{{ uncovered.map((c) => c.className).join('、') }}）。
      </span>
    </p>

    <!-- 改班主任：一行一个班，**一个班一位**（第五十一轮：换人=顶替） -->
    <el-dialog v-model="editOpen" title="改班主任安排" width="560px" append-to-body>
      <p class="hint" style="margin: 0 0 12px">
        班主任是<strong>班</strong>的归属：一个老师可以同时带好几个班，
        但<strong>一个班只有一位班主任</strong>——换人直接重新选择（会顶替原来的安排）。
        选中的老师登录后就能在左侧切换这些班。
      </p>
      <div v-for="r in uniqueClasses" :key="r.classId" class="arrange-row">
        <span class="arrange-name">{{ r.className }}</span>
        <el-select
          v-model="editPicks[r.classId]"
          clearable
          filterable
          placeholder="暂无班主任"
          style="flex: 1"
        >
          <el-option
            v-for="t in candidates"
            :key="t.id"
            :label="`${t.realName}（${t.username}）`"
            :value="t.id"
          />
        </el-select>
      </div>
      <template #footer>
        <el-button @click="editOpen = false">取消</el-button>
        <el-button type="primary" :loading="editSaving" @click="saveArrange">保存</el-button>
      </template>
    </el-dialog>

    <!-- 新增班主任（第五十六轮）：先选班，再填人。
         建完当场就是这个班的班主任——省掉「去成员管理建号 → 回来安排」两步 -->
    <el-dialog v-model="createOpen" title="新增班主任" width="480px" append-to-body>
      <p class="hint" style="margin: 0 0 14px">
        新账号<strong>当场就是所选班级的班主任</strong>（一个班只有一位）。
        班级还没建的，先在「班级管理 → 新建班级」里建好再回来。
      </p>
      <el-form label-width="80px" @submit.prevent>
        <el-form-item label="带的班" required>
          <el-select v-model="createForm.classId" filterable placeholder="从现有班级里选" style="width: 100%">
            <el-option
              v-for="c in createClassOptions"
              :key="c.id"
              :label="c.taken ? `${c.name}（已有班主任）` : c.name"
              :value="c.id"
              :disabled="c.taken"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="姓名" required>
          <el-input v-model="createForm.realName" maxlength="32" placeholder="班主任姓名" />
        </el-form-item>
        <el-form-item label="登录名" required>
          <el-input v-model="createForm.username" maxlength="32" placeholder="用于登录，全局唯一" />
        </el-form-item>
        <el-form-item label="初始密码">
          <el-input
            v-model="createForm.password"
            maxlength="32"
            show-password
            placeholder="留空 = 123456"
          />
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="createForm.phone" maxlength="20" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button>
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

.table-wrap {
  overflow-x: auto;
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

/* 勾选列：窄、居中，且不参与「点行跳转」那种交互（这里本来就没有） */
.roster th.pick,
.roster td.pick {
  width: 40px;
  padding-right: 0;
  text-align: center;
  white-space: nowrap;
}

.muted {
  color: var(--color-muted-fg);
}

.hint {
  margin: 0;
  font-size: 12px;
  color: var(--color-muted-fg);
}

/* 改班主任：每个班一行 */
.arrange-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 0;
}

.arrange-name {
  flex: none;
  width: 110px;
  font-size: 13px;
}
</style>
