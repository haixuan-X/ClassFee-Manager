<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { fetchMe, fetchMyProfile, updateProfile } from '@/api/auth'
import { fetchClassChoices } from '@/api/class'
import { createCollegeClass } from '@/api/college'
import { getErrorMessage } from '@/api/request'
import { useUserStore } from '@/stores/user'
import { ROLE_TEXT, STAFF_ROLES } from '@/types'
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

const form = reactive({
  realName: '',
  studentNo: '',
  phone: '',
  deanOnly: false,
  /**
   * 第三十二轮：我带的班（班主任是班的多对多属性）。
   *
   * 里面可能临时混进**字符串**：下拉开了 `allow-create`，输入一个库里没有的
   * 班名回车，Element Plus 塞进来的是那个**班名**而不是 id。
   * `onClassIdsChange` 会把它拿去建班、换成真 id——保存前一定全是数字。
   */
  classIds: [] as (number | string)[],
})

/** 是不是院长——「职务范围」这一栏只对院长出现（别的角色没这一说） */
const isDean = computed(() => userStore.user?.role === 'DEAN')

/**
 * 有没有「学号」这一项。
 *
 * 学号是**学生**的标识（缴费名单、批次排序要用）；院长 / 班主任 / 访客
 * 是教职工或校方，本来就没有学号，给他们摆一个输入框只会让人以为要填。
 */
const showStudentNo = computed(() => {
  const r = userStore.user?.role
  return r === 'MEMBER' || r === 'ADMIN' || r === 'MONITOR'
})

/**
 * 是不是**纯院长**（第三十轮）：只管学院，不参与班级事务。
 *
 * 他一个班都不带，所以「我带的班」这一项对他不存在；
 * 「所在班级」那一行也该换成「职务范围」，写着一个他根本不去的班是骗人。
 */
const isPureDean = computed(
  () => userStore.user?.role === 'DEAN' && userStore.user.deanOnly === true,
)

/**
 * 能不能改「我带的班」——**只有运营角色**（生活委员/班长/班主任/院长）。
 *
 * 班主任是**班**的归属，普通同学跟这个没关系（他不是班主任），
 * 给普通同学一个「我带的班」的开关只会让人以为自己多了什么。
 *
 * ⚠ **纯院长没有这一项**（第三十轮）：他是「只管学院、不参与班级事务」的那一种，
 * 一个班都不带，摆一个「我带的班」给他就是**假的**——勾了也不生效
 * （纯院长的白名单里根本没有班级接口）。他在上面的「职务范围」里切回
 * 「院长 + 班主任」，这一项就回来了。
 */
const canManageClasses = computed(() => {
  const u = userStore.user
  if (!u) return false
  if (!STAFF_ROLES.includes(u.role)) return false
  // 用**表单当前值**判断：切一下上面的「职务范围」，这一项立刻出现/消失，
  // 不用先保存再刷新（保存了才变会让人以为「怎么没反应」）。
  if (u.role === 'DEAN' && form.deanOnly) return false
  return true
})

/**
 * 「所在班级」= **当前正在操作的那个班**（第三十二轮）。
 *
 * 之前写的是 `user.className`（默认班）——那是个**死数据**：
 * 一个老师管两个班、切换到另一个班之后，这一行还写着原来那个班。
 */
const currentClassName = computed(() => {
  const u = userStore.user
  if (!u) return '—'
  const ids = u.classIds?.length ? u.classIds : [u.classId]
  const idx = ids.indexOf(userStore.currentClassId ?? u.classId)
  return u.classNames?.[idx] ?? u.className ?? '—'
})

/** 所有启用的班（供「我带的班」多选） */
const allClasses = ref<{ id: number; className: string; grade: string }[]>([])

/**
 * 可选项 = 拉到的班 + **当前选着但没在列表里的班**。
 *
 * 少这层兜底时，只要 `/class/choices` 那一次没拉到（纯院长以前会被拦 403），
 * `el-select` 找不到对应选项就**直接显示裸 id**——「我带的班」里冒出
 * 「1 / 471 / 472」这种数字，看起来像坏了。宁可显示「班级 #471」，
 * 也不能让人对着三个数字猜。
 */
const classOptions = computed(() => {
  const known = new Set(allClasses.value.map((c) => c.id))
  const missing = form.classIds
    .filter((id): id is number => typeof id === 'number' && !known.has(id))
    .map((id) => ({ id, className: `班级 #${id}`, grade: '' }))
  return [...allClasses.value, ...missing]
})
/** 我的默认班（永远包含在「我带的班」里） */
const defaultClassName = computed(() => userStore.user?.className ?? '—')

/**
 * 能不能在下拉里**输入班名回车新建班**。
 *
 * 建班是学院层的事（后端 `POST /api/college/classes` 也只给院长），
 * 所以只有院长看到这个能力。老师只能从已有班里选——他要带的新班
 * 由院长在「班主任名册」里分配，那是本来就在走的路。
 */
const canCreateClass = computed(() => userStore.user?.role === 'DEAN')

/**
 * 把下拉里**还是班名的项**换成真 id：建班 → 记进选项 → 用它换掉那条字符串。
 *
 * `allow-create` 会把**字符串**塞进 `v-model`（其余项都是班级 id）。不换的话
 * 保存时后端只认整数，整条 400，所以变更的瞬间就要换掉。
 *
 * 失败**向上抛**：调用方决定怎么提示。半路吞掉错误会让「班没建出来」和
 * 「班建出来了但没勾上」看起来一模一样。
 */
async function resolveNewClassNames(): Promise<void> {
  const names = form.classIds.filter(
    (v): v is string => typeof v === 'string' && v.trim() !== '',
  )
  if (!names.length) return
  const ids = form.classIds.filter((v): v is number => typeof v === 'number')
  for (const raw of names) {
    const name = raw.trim()
    const c = await createCollegeClass(name)
    if (!allClasses.value.some((x) => x.id === c.id)) {
      allClasses.value = [
        ...allClasses.value,
        { id: c.id, className: c.className, grade: c.grade },
      ]
    }
    if (!ids.includes(c.id)) ids.push(c.id)
    ElMessage.success(
      c.created
        ? `已新建班级「${c.className}」，字段模板照着你的默认班复制了 ${c.fieldsCopied} 列`
        : `「${c.className}」已经有了，已加入`,
    )
  }
  form.classIds = ids
}

/**
 * 下拉变更：输入一个新班名回车 → 建班并选中。
 *
 * 新班是**空班**，字段模板由后端从我的默认班复制一份，
 * 建完直接能导入名单、能进「学生信息」。
 */
async function onClassIdsChange() {
  try {
    await resolveNewClassNames()
  } catch (e) {
    // 建班失败：把那几个字符串摘掉，别让它们卡在下拉里显示成「已选中」
    ElMessage.error(getErrorMessage(e, '新建班级失败，请稍后重试'))
    form.classIds = form.classIds.filter((v) => typeof v === 'number')
  }
}

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
    // 第三十二轮：职务范围（纯院长 ↔ 兼班主任）
    form.deanOnly = mine.deanOnly === true
    // 第三十二轮：我带的班
    form.classIds = [...(mine.managedClassIds ?? [mine.classId])]
    // 可选的班（运营角色以上才有；普通同学这栏是空的）
    //
    // 只有运营角色才去拉：同学用不上这份名单，凭空发一个请求只是多一次
    // 可能失败的机会（失败会被全局拦截器弹成红条）。
    if (STAFF_ROLES.includes(mine.role)) {
      try {
        allClasses.value = (await fetchClassChoices()).classes ?? []
      } catch {
        allClasses.value = []
      }
    }
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
  // ⚠ **先上锁，再校验**。
  //
  // 原来先 `await validate()`、校验过了才置 `saving`，中间那个 await 就是
  // 一个**窗口**：手快点两下「保存修改」，两次提交都从窗口里穿过去——
  // 一次改完弹两个「个人信息已更新」，后端那边还可能撞出「系统繁忙」。
  saving.value = true
  alertMessage.value = ''
  try {
    const valid = await formRef.value.validate().catch(() => false)
    if (!valid) {
      await showAlert('表单有未填写或格式不正确的项，请按下方提示修改')
      return
    }
    // 建班的请求可能**还在路上**（刚敲完班名就点保存）：这时 v-model 里那一条
    // 还是班名，不能直接拿去保存。等它换成 id 再走——否则界面上勾着新班，
    // 库里其实没存上（下一次登录就没了）。
    if (canManageClasses.value) await resolveNewClassNames()
    const updated = await updateProfile({
      realName: form.realName.trim(),
      // 沿用「空串=清空」语义（后端 None=不改）
      // 院长 / 班主任 / 访客没有学号：干脆不传，避免写一个空值
      studentNo: showStudentNo.value ? form.studentNo.trim() : undefined,
      phone: form.phone.trim(),
      // 第三十二轮：职务范围。只给院长传（别的角色传了后端会忽略）
      deanOnly: isDean.value ? form.deanOnly : undefined,
      // 第三十二轮：我带的班（**直接生效**）
      //
      // 只传数字：上面的 `resolveNewClassNames` 已经把班名换成 id 了，
      // 这里再滤一次是兜底——后端只认整数，混进一个字符串会整条 400。
      classIds: canManageClasses.value
        ? form.classIds.filter((v): v is number => typeof v === 'number')
        : undefined,
    })
    userStore.setUser(updated)
    if (detail.value) {
      detail.value = {
        ...detail.value,
        realName: updated.realName,
        studentNo: form.studentNo.trim() || null,
        phone: form.phone.trim() || null,
        deanOnly: updated.deanOnly,
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
        <p>
          这里改的是<strong>你自己</strong>的资料；角色、账号状态、登录名由运营在「成员管理」维护
          （<template v-if="isDean">你的<strong>职务范围</strong>下面可以自己改</template>），登录名创建后不可修改
        </p>
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
          <el-form-item v-if="showStudentNo" label="学号" prop="studentNo">
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

          <!--
            职务范围（第三十二轮）：**只有院长本人**能改。
            「纯院长」是第三十轮给院长加的一个**限制**（只管学院、不参与班级事务），
            「兼班主任」才是院长的默认状态——所以这一栏是「解除限制」，
            不是给自己发新权力。
          -->
          <el-form-item v-if="isDean" label="职务范围">
            <el-radio-group v-model="form.deanOnly">
              <el-radio :value="false">院长 + 班主任</el-radio>
              <el-radio :value="true">纯院长（只管学院）</el-radio>
            </el-radio-group>
            <div class="form-tip">
              「纯院长」= 只管学院这一层（全校名册、班主任名册、学院任务），
              <strong>不参与班级事务</strong>（记账、缴费、班级任务、班级成员）。
              改成「院长 + 班主任」就会<strong>开始参与</strong>你所在那个班的班级事务。
              <strong>改完立刻生效</strong>，不用重新登录。
            </div>
          </el-form-item>

          <!--
            我带的班（第三十二轮）：班主任是**班**的归属，一个老师可以带好几个班。
            改了立刻生效——登录后左侧就能切到这些班，各班的账目、成员、
            任务、学生信息**分开**，互不串。

            院长还能**就地建班**：输入一个库里没有的班名回车，直接建出来并勾上
            （第三十三轮，用户要的）。老师不行——建班是学院层的事，
            他要带的新班由院长在「班主任名册」里分配。
          -->
          <el-form-item v-if="canManageClasses" label="我带的班">
            <el-select
              v-model="form.classIds"
              multiple
              filterable
              :allow-create="canCreateClass"
              default-first-option
              :placeholder="
                canCreateClass
                  ? '选你带的班；输入新班名回车可直接新建'
                  : '选你带的班（不选就只带默认班）'
              "
              style="width: 100%"
              @change="onClassIdsChange"
            >
              <el-option
                v-for="c in classOptions"
                :key="c.id"
                :label="c.className"
                :value="c.id"
              />
            </el-select>
            <div class="form-tip">
              带上的班，登录后能在<strong>左侧切换</strong>；各班的账目、成员、任务、
              学生信息分开，互不串。<strong>改完立刻生效</strong>，不用重新登录。
              你的默认班（{{ defaultClassName }}）始终包含在内。
              <template v-if="canCreateClass">
                输入一个还没建过的班名<strong>回车即新建</strong>，新班的字段模板
                照着你的默认班复制。
              </template>
            </div>
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
          <div v-if="isPureDean" class="row">
            <dt>职务范围</dt>
            <dd>只管学院（不参与班级事务）</dd>
          </div>
          <div v-else class="row">
            <dt>所在班级</dt>
            <dd>{{ currentClassName }}</dd>
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

/**
 * 两栏塌成单列的断点。与仪表盘的 `.grid-2` **同口径**（1024px）：
 * 两页的侧栏一样宽，塌列的时机也应该一样——否则用户拖窗口时会看到
 * 「仪表盘塌了、个人中心没塌」这种自相矛盾的现象。
 */
@media (max-width: 1024px) {
  .grid-2 {
    grid-template-columns: 1fr;
  }
}
</style>
