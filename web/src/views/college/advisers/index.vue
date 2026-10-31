<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getErrorMessage } from '@/api/request'
import {
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
  } catch {
    list.value = null
    loadError.value = true
  } finally {
    loading.value = false
  }
}

const rows = computed(() => list.value?.rows ?? [])

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
          班主任本人也能在「个人信息」里改「我带的班」。账号的增删改请到「班级 → 成员管理」。
        </p>
      </div>
      <div style="display: flex; gap: 8px; flex-wrap: wrap">
        <el-button :loading="templateLoading" @click="onDownloadTemplate">下载模板</el-button>
        <el-button :loading="importing" @click="pickFile">导入班主任</el-button>
        <el-button type="primary" @click="openArrange">改班主任安排</el-button>
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
