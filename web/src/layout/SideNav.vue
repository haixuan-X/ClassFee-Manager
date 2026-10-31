<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchMe } from '@/api/auth'
import { fetchVersion } from '@/api/meta'
import { useUserStore } from '@/stores/user'
import type { GuestScope, Role } from '@/types'
import { GUEST_SCOPE_OPTIONS, STAFF_ROLES } from '@/types'

/** 四项全开。后端把库里的 NULL 展开成这个，前端拿不到 scope 时也用它兜底。 */
const ALL_GUEST_SCOPES: GuestScope[] = GUEST_SCOPE_OPTIONS.map((o) => o.value)

/** `v1.2.0`。拉不到就空串，模板不渲染——宁可少一行，不要挂个假版本号。 */
const versionLabel = ref('')
/**
 * 学院名（部署时在 `.env` 里声明 `CLASSFEE_COLLEGE_NAME`）。
 *
 * 拉不到就空串，界面上退回写「学院」两个字。
 */
const collegeName = ref('')

onMounted(async () => {
  try {
    const v = await fetchVersion()
    versionLabel.value = `v${v.version}`
    collegeName.value = v.collegeName || ''
  } catch {
    versionLabel.value = ''
    collegeName.value = ''
  }
})

/**
 * 侧栏顶部那行：显示**你这个人的管辖范围**。
 *
 * ## 为什么院长不能只显示班级名
 *
 * 院长的权限范围是**学院**（所有班级），不是他所在的那个班。
 * 顶上写「云计算2502」会让人以为他只管这个班——而他明明能管全校。
 *
 * | 身份 | 显示 |
 * |------|------|
 * | 班主任 / 同学 | `云计算2502` |
 * | 院长（兼班主任） | `智能汽车学院 云计算2502` |
 * | 纯院长（只管学院） | `智能汽车学院` |
 *
 * 纯院长**不参与班级事务**（第三十轮），所以那一行不该出现班级名。
 *
 * 第三十二轮：显示的是**当前正在操作的那个班**，不是默认班——
 * 切到「计科2201班」后，顶上就该跟着变。
 */
const scopeLabel = computed(() => {
  const u = userStore.user
  if (!u) return '未加入班级'
  // 当前班的名字（多班时跟着切换器走）
  const ids = u.classIds?.length ? u.classIds : [u.classId]
  const idx = ids.indexOf(userStore.currentClassId ?? u.classId)
  const className = u.classNames?.[idx] ?? u.className ?? ''
  if (u.role !== 'DEAN') return className || '未加入班级'
  const college = collegeName.value || '学院'
  // 纯院长不参与班级事务 → 只显示学院
  if (u.deanOnly) return college
  // 兼班主任的院长：学院在前、班级在后
  return className ? `${college} ${className}` : college
})

interface NavItem {
  index: string
  label: string
  icon: string
  disabled?: boolean
  /** 里程碑标记，说明该功能何时上线 */
  tag?: string
  /** 可访问该页面的角色；后端仍有 _STAFF_ROUTES 强制校验 */
  roles?: Role[]
}

/**
 * 抽拉式子分组（第三十轮）：一个可以展开/收起的入口组。
 *
 * 本身**不是链接**——它只是个开关，所以渲染成 `<button>` 而不是
 * `router-link`：给一个不导航的东西挂 href，键盘用户按下会「没反应」，
 * 读屏也会念成「链接」。
 */
interface NavSubGroup {
  /** 展开状态的唯一键（用 label 即可，同一屏内不重名） */
  key: string
  label: string
  icon: string
  items: NavItem[]
}

interface NavGroup {
  title: string
  items: NavItem[]
  /** 抽拉式子分组；为空则这一组只有平铺的 items */
  subs?: NavSubGroup[]
  /**
   * **只有这些角色**能看到这一组（第三十二轮）。
   *
   * 「学院」这一组就是它：**除了院长，谁都不展示**（用户口径）。
   * 组级过滤比逐条给 item 加 roles 可靠——加新入口时忘了标，
   * 就会漏在别人的侧栏里，而这里是一刀切。
   */
  roles?: Role[]
  /**
   * 纯院长**看不到**这一组（第三十轮）。
   *
   * 纯院长只管学院，班级那一套（账目、班级任务、班级信息、班级成员）
   * 归班主任和班委——侧栏里摆着它们只会让人点进去撞一堵 403 的墙。
   */
  hiddenForPureDean?: boolean
}

/**
 * 侧边导航：仪表盘/账本明细全员可读，收入/支出登记与班级功能仅运营角色
 * （生活委员/班长/班主任 = ADMIN/MONITOR/TEACHER，三者同权），其余入口按
 * docs/系统设计文档.md 的里程碑灰显，避免出现点了没反应的死链。
 *
 * 用原生 router-link（<a href>）而不是 el-menu：
 * el-menu-item 硬编码 tabindex="-1" 且不做键盘导航，键盘用户会完全走不进菜单。
 * 真链接自带 Tab 可达、Enter 激活、中键新开标签页，aria-current 由 router-link 自动带上。
 */
const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

/**
 * 运营角色。**从 `@/types` 的共享常量来**，不再在本文件里另写一份——
 * 加角色时只改 types 一处，侧栏、路由 meta.roles、成员管理按钮全部跟着对。
 * （原先三处各写一份字面量，加院长时只改一处，侧栏立刻少了 5 个入口。）
 */
const STAFF = STAFF_ROLES

/**
 * 访客能看到哪几个页面（用户口径：总览、账目、学生信息、我的，就这些；
 * 第二十五轮加了班级任务）。
 *
 * 用**路径**而不是路由 name，和这里其余 items 的 `index` 同一口径。
 * ⚠ 必须与 `router/index.ts` 的 `GUEST_ALLOWED` 保持一致，两处各写一份必然漂移。
 *
 * 这张表漏一项的后果：访客**侧栏里看不到入口但手输 URL 能进去**（路由守卫放行）
 * —— 是个半通不通的页面。所以改任何一边必须同时改另一边。
 */
/**
 * 访客能看到哪几个页面 —— **第二十六轮起按账号逐个定**，不再是写死的一张表。
 *
 * 用**路径**而不是路由 name，和这里其余 items 的 `index` 同一口径。
 * ⚠ 这张 scope→路径 映射必须与 `router/index.ts` 的 `GUEST_PAGE_SCOPE` 保持一致，
 * 两处各写一份必然漂移——漏掉的后果是「侧栏有入口但路由守卫拦掉」或反过来。
 *
 * 「个人信息」不在表里：访客自己的账号，没什么可限制的，永远可进。
 *
 * 收费批次（`/batches`）也不在表里——**即使访客勾了「账本明细」也不给入口**，
 * 因为那是记账的人用的页面。侧栏不给，后端却仍然放行（批次信息归 RECORDS 管，
 * 见 `security.required_guest_scope`），两边口径不同是有意的：批次那套接口本来
 * 就该跟着账目权限走，界面却不给它入口。真要收紧应该改后端，不是往这张表里加。
 */
const GUEST_SCOPE_OF_PATH: Record<string, GuestScope> = {
  '/dashboard': 'DASHBOARD',
  '/records': 'RECORDS',
  '/student-info': 'STUDENTS',
  '/tasks': 'TASKS',
  // 任务总览（第三十二轮）：统计的就是任务，和「班级任务」同源，
  // 所以跟着 TASKS 范围走（路由守卫那份表里也是同一个口径）。
  '/tasks/overview': 'TASKS',
}

/**
 * 访客（GUEST，第二十四轮）是**纯只读**，给领导/校方看情况用的。
 *
 * 用户口径：「能看见总览、账目、学生信息、还有我的，就这些」。
 * 这里**不需要为它写任何配置**——下面每个受限入口的 `roles` 白名单里本来就没有
 * GUEST，所以它天然只剩：仪表盘 / 账本明细 / 学生信息 / 班级任务 / 个人信息。
 *
 * 刻意不给它的、以及为什么：
 * - 收入登记 / 支出登记是**写表单**，给了就是个提交必报错的死页面
 * - 我的缴费 / 成员缴费 / 收费批次 / 成员管理 里全是别人的姓名学号和账号
 * - 班级信息 用户没提，不给
 *
 * 后端同样兜底：访客不在 `STAFF_ROLES`，所有记账/账号管理接口一律 403。
 * 路由守卫另有一张访客白名单（`router/index.ts` 的 `GUEST_ALLOWED`）。
 */

/**
 * 「我的缴费」可见角色 = 全部角色减去班主任和访客。
 *
 * 与后端 `batch_service._class_members` 同口径：缴费名单只列 MEMBER，运营角色
 * 不会被生成缴费行，也就不存在「我交没交」。班主任是 .env 声明的老师账号、不是学生，
 * 给他一个永远显示「你不属于缴费对象」的死胡同页面毫无意义（第二十轮移除）。
 *
 * 访客同理，而且更明确：领导不是本班学生，压根不该出现在缴费名单里。
 */
const PAYABLE: Role[] = ['ADMIN', 'MONITOR', 'MEMBER']

/**
 * 学院（第三十轮）：**仅院长**。
 *
 * 学院 = 全部班级的聚合视图：跨班级的学生名册、各班班主任名册、跨班级的
 * 任务一览。和「学生情况总览」同一道闸门（后端 `require_min_level`）。
 *
 * ⚠ 这里的 `roles` 是**入口层**的过滤，真正的边界在后端——手输 URL
 * 照样 403。两条腿都要走：只做后端，班主任会看到一排点进去就报「无权」的
 * 入口；只做前端，手输接口就穿透了。
 */
const DEAN_ONLY: Role[] = ['DEAN']

const groups: NavGroup[] = [
  {
    title: '总览',
    items: [{ index: '/dashboard', label: '仪表盘', icon: 'Odometer' }],
  },
  {
    // 学院（第三十轮）：位置在「总览」和「账目」之间。
    // 「班级管理」和「任务」做成**抽拉式**（可展开/收起），不是直接铺开的入口。
    //
    // ⚠ **这一组只有院长能看到**（用户口径：「学院这一栏，除了院长，谁都不展示」）。
    //  组级 `roles` 一刀切，比逐条给 item 加 roles 可靠——以后往这一组加新入口，
    //  忘了标角色也不会漏到别人的侧栏里。
    title: '学院',
    roles: DEAN_ONLY,
    items: [],
    subs: [
      {
        key: 'college-classes',
        label: '班级管理',
        icon: 'School',
        items: [
          // 学院的学生信息 = **所有班级**的学生（班级里那个只看本班）
          // ⚠ 叫「学生名册」而不是「学生信息」：侧栏里同时有「班级 > 学生信息」
          // （本班）和这一条（全校），同名的话两处都写着「学生信息」，
          // 谁也分不清点进去的是哪个。
          { index: '/college/students', label: '学生名册', icon: 'Postcard', roles: DEAN_ONLY },
          // 学院成员管理 = 各班**班主任（导员）**名册。
          // 标签写「班主任名册」而不是「成员管理」：侧栏里已经有一个班级层的
          // 「成员管理」（/member-manage），两处同名会让人以为是同一个页面
          // （实测：点侧栏「成员管理」，页面标题却是「班主任名册」，对不上）。
          { index: '/college/advisers', label: '班主任名册', icon: 'User', roles: DEAN_ONLY },
        ],
      },
      {
        key: 'college-tasks',
        label: '任务',
        icon: 'Bell',
        items: [
          // 任务总览（第三十二轮）：统计「现在什么状况」。
          // ⚠ **只有院长能看**（用户口径）——它挂在「学院」这一组下，
          // 而那一组除了院长谁都不展示。
          { index: '/tasks/overview', label: '任务总览', icon: 'DataLine' },
          // **学院任务**：院长发到**全学院**的，由各班班主任应答
          { index: '/college/tasks', label: '学院任务', icon: 'List', roles: DEAN_ONLY },
          // **班级任务**（学院视角）：查看**各班班主任发布的任务**（第三十二轮）。
          // ⚠ 和「班级 > 班级任务」同名但不是一回事：
          //   - 「班级 > 班级任务」= 本班的任务，能发布、能答题
          //   - 这一条 = 各班班主任发的任务的**只读**一览
          { index: '/college/class-tasks', label: '班级任务', icon: 'Bell', roles: DEAN_ONLY },
        ],
      },
    ],
  },
  {
    title: '账目',
    items: [
      { index: '/records', label: '账本明细', icon: 'Tickets' },
      { index: '/income', label: '收入登记', icon: 'Bottom', roles: STAFF },
      { index: '/expense', label: '支出登记', icon: 'Top', roles: STAFF },
    ],
    // 纯院长只管学院，班费是班级自己的账
    hiddenForPureDean: true,
  },
  {
    title: '班级',
    items: [
      // 学生信息（第二十三轮）：**全员可见**——默认只显示自己那一行，要看/改别人的
      // 走页面内的申请流程。路由不设 roles，拦在路由层会让同学连自己的信息都看不到。
      // 访客例外：他能看**全部**（服务端 scope 决定的），但一行都改不了。
      { index: '/student-info', label: '学生信息', icon: 'Postcard' },
      // 班级任务（第二十五轮）：**本班**的任务，能发布、能答题。
      // 全员可读（填答案是全员动作），访客也能看但只能看汇总。
      // 发布按钮在页面内按 `canPublish` 显示，这里不设 roles —— 和学生信息同理，
      // 拦在侧栏会让同学连题都看不到。真正的闸门在 task_service。
      //
      // ⚠ 和「学院 > 任务 > 班级任务」同名但不是一回事：
      //   - 这一条 = **本班**的任务，班主任/班长在这里发布、同学在这里填
      //   - 「学院 > 任务 > 班级任务」 = 各班班主任发的任务的**只读**一览（院长看）
      { index: '/tasks', label: '班级任务', icon: 'Bell' },
      // 「我的缴费」：回答「有没有班费要交 / 我交了吗 / 什么时候截止」，这三问
      // **只有缴费对象问得出来** —— 后端 `_class_members` 只给 MEMBER 生成缴费行，
      // 运营角色进去只会看到一句「你不属于缴费对象」的死胡同页面。
      // 班主任是老师、本就不是缴费对象（.env 声明的账号，不是学生），第二十轮起不给他这个入口。
      // 「成员缴费」（缴费名单）里有别人的姓名与学号，仍限运营角色。
      { index: '/my-fees', label: '我的缴费', icon: 'Wallet', roles: PAYABLE },
      { index: '/members', label: '成员缴费', icon: 'UserFilled', roles: STAFF },
      { index: '/batches', label: '收费批次', icon: 'Collection', roles: STAFF },
      { index: '/member-manage', label: '成员管理', icon: 'User', roles: STAFF },
      // 班级信息：全员可读，编辑由后端限定运营角色
      { index: '/class-info', label: '班级信息', icon: 'School' },
    ],
    // 纯院长只管学院，班级那一整组都不是他的
    hiddenForPureDean: true,
  },
  {
    // 第十五轮：个人信息全员可进（普通成员改自己的姓名/学号/手机号）
    title: '我的',
    items: [{ index: '/profile', label: '个人信息', icon: 'Postcard' }],
  },
]

/**
 * 按角色过滤入口：用户信息未拉到时默认隐藏受限入口（角色不符 = 回仪表盘，服务端角色表兜底）。
 *
 * 访客走的是**独立判断**而不是 `item.roles`：学生信息、班级任务、班级信息这类
 * 「全员可读」的入口本来就没有 roles 限制，光靠 `roles` 拦不住它们；
 * 访客能看哪几项是**班主任给这个账号单独勾的**（第二十六轮）。
 *
 * 这里是**入口层面**的过滤，不是安全边界——真正的边界在后端中间件
 * （`security.required_guest_scope`），手输 URL 也绕不过去。
 */
function canSee(item: NavItem): boolean {
  if (item.disabled) return true
  if (!userStore.user) return false
  if (userStore.user.role === 'GUEST') {
    const need = GUEST_SCOPE_OF_PATH[item.index]
    // ⚠ **默认必须是不给**。这张表是「受限页面 → 范围」的映射，
    // 没命中的页面（收入登记、成员管理、班级信息…）一律对访客隐藏，
    // 只有「个人信息」显式放行——那是访客自己的账号，没什么可限制的。
    //
    // 这里翻过一次车：写成「没命中 = 不受限 = 放行」之后，访客侧栏立刻冒出
    // 收入登记、成员管理，而他真正该看的仪表盘反被限掉了。**方向反了就全错。**
    if (need === undefined) return item.index === '/profile'
    return (userStore.user.guestScopes ?? ALL_GUEST_SCOPES).includes(need)
  }
  if (!item.roles) return true
  return item.roles.includes(userStore.user.role)
}

const visibleGroups = computed(() =>
  groups
    // 组级角色闸门（第三十二轮）：「学院」这一组**只有院长**能看到。
    // 组级一刀切比逐条给 item 加 roles 可靠——加新入口忘了标就会漏出去。
    .filter((group) => !group.roles || group.roles.includes(userStore.user?.role ?? 'MEMBER'))
    // 纯院长不参与班级事务：「账目」「班级」两组整个不出现（第三十轮）
    .filter((group) => !(group.hiddenForPureDean && userStore.isPureDean))
    .map((group) => ({
      ...group,
      items: group.items.filter(canSee),
      // 子分组也按角色过滤；一个子项都不剩的子分组**整个不渲染**——
      // 空壳分组点了没反应，比不渲染更糟。
      subs: (group.subs ?? [])
        .map((sub) => ({ ...sub, items: sub.items.filter(canSee) }))
        .filter((sub) => sub.items.length > 0),
    }))
    .filter((group) => group.items.length > 0 || (group.subs?.length ?? 0) > 0),
)

/**
 * 抽拉式子分组的展开状态。
 *
 * 用 `Set` 而不是对象：展开的子分组通常只有一两个，对象还得防「原型键」
 * （`expanded['constructor']` 是个函数，`in` 判断会永远为真）。
 *
 * ⚠ 初始为空 = **全部收起**。学院这一组默认展开会占掉半屏侧栏，
 * 而「总览」和「账目」是绝大多数人真正会用的入口。
 */
const expanded = ref<Set<string>>(new Set())

function isExpanded(key: string): boolean {
  return expanded.value.has(key)
}

function toggle(key: string) {
  const next = new Set(expanded.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expanded.value = next
}

/**
 * 切换器的选项：**id → 名字**。
 *
 * ⚠ 不靠「两个数组按下标配对」：`classIds` 和 `classNames` 长度一旦不一致
 * （后端只回了一部分名字），下标配对就会**张冠李戴**——切到 A 班却显示 B 班的名字。
 */
const switchableClasses = computed(() => {
  const u = userStore.user
  const ids = u?.classIds ?? []
  const names = u?.classNames ?? []
  return ids.map((id, i) => ({ id, name: names[i] ?? `班级 ${id}` }))
})

/**
 * 切换「当前班」（第三十二轮）。
 *
 * 一个班主任可能带好几个班（云计算2502 + 云计算2501）。切完之后
 * **所有**班级级页面（账目、成员、任务、学生信息）都跟着切——
 * 因为请求统一由 axios 拦截器带上 `classId`（见 `api/request.ts`），
 * 后端在鉴权中间件里把它当成「本次操作的班」。
 *
 * 切完要**刷新当前页面**：页面上已经加载的数据是上一个班的。
 */
const switching = ref(false)

async function switchClass(id: number) {
  if (id === userStore.currentClassId) return
  switching.value = true
  userStore.setCurrentClass(id)
  try {
    // 重新拉一次当前用户（classIds 可能变了）
    await fetchMe()
    // 整页重载最省事也最不容易漏：每个页面各自刷新容易漏掉某个
    await router.replace({ path: route.path, query: { ...route.query, t: Date.now() } })
    window.location.reload()
  } finally {
    switching.value = false
  }
}

/**
 * 当前路由落在哪个子分组里，就把它**自动展开**。
 *
 * 不这么做的话：点进「学院任务」→ 侧栏的「任务」是收起的 → 用户不知道自己在哪，
 * 也不知道怎么回去。返回时它又会自己收起，来回跳。
 */
watch(
  () => route.path,
  (path) => {
    for (const group of groups) {
      for (const sub of group.subs ?? []) {
        if (sub.items.some((it) => it.index === path)) {
          if (!expanded.value.has(sub.key)) {
            expanded.value = new Set([...expanded.value, sub.key])
          }
        }
      }
    }
  },
  { immediate: true },
)
</script>

<template>
  <div class="sidenav">
    <div class="brand">
      <div class="brand-mark" aria-hidden="true">
        <el-icon :size="18"><Wallet /></el-icon>
      </div>
      <div>
        <div class="brand-name">学生信息管理系统</div>
        <div class="brand-sub">{{ scopeLabel }}</div>
      </div>
    </div>

    <!--
      班级切换器（第三十二轮）：一个班主任可能带好几个班。
      只有**多班时**才渲染——只有一个班的人不需要看见这个控件。

      学院页面也照常给：它是「当前班」这个全局上下文，不是学院页的筛选器；
      学院那几页各有自己的「全部班级」下拉。
    -->
    <div v-if="userStore.canSwitchClass" class="class-switch">
      <el-select
        :model-value="userStore.currentClassId ?? undefined"
        size="small"
        class="class-switch-select"
        :disabled="switching"
        aria-label="切换班级"
        @change="switchClass"
      >
        <el-option
          v-for="c in switchableClasses"
          :key="c.id"
          :label="c.name"
          :value="c.id"
        />
      </el-select>
    </div>

    <nav v-for="group in visibleGroups" :key="group.title" class="nav-group" :aria-label="group.title">
      <div class="nav-label">{{ group.title }}</div>
      <ul class="nav-list">
        <li v-for="item in group.items" :key="item.index">
          <!-- 已上线：真链接，键盘与读屏都能用 -->
          <router-link
            v-if="!item.disabled"
            :to="item.index"
            class="nav-item"
            :class="{ 'is-active': route.path === item.index }"
          >
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
            <span v-if="item.tag" class="nav-tag">{{ item.tag }}</span>
          </router-link>

          <!-- 未上线：非交互元素 + aria-disabled，避免出现“能 Tab 到却没反应”的假链接 -->
          <span v-else class="nav-item is-disabled" aria-disabled="true">
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
            <span v-if="item.tag" class="nav-tag">{{ item.tag }}</span>
          </span>
        </li>
      </ul>

      <!--
        抽拉式子分组（第三十轮）：「班级管理」「任务」是可展开/收起的组。

        开关渲染成 `<button>` 而不是链接——它不导航，挂着 href 会让键盘和
        读屏用户以为按了会跳页（然后「没反应」）。
        `aria-expanded` + `aria-controls` 让读屏能播报「已展开/已收起」。
      -->
      <div v-for="sub in group.subs ?? []" :key="sub.key" class="nav-sub">
        <button
          type="button"
          class="nav-item nav-sub-toggle"
          :class="{ 'is-open': isExpanded(sub.key) }"
          :aria-expanded="isExpanded(sub.key)"
          :aria-controls="`nav-sub-${sub.key}`"
          @click="toggle(sub.key)"
        >
          <el-icon><component :is="sub.icon" /></el-icon>
          <span>{{ sub.label }}</span>
        </button>

        <!--
          抽拉动画：用 Element Plus 的 `el-collapse-transition` 做**高度过渡**。

          原来直接用 `:hidden` 切换 `display`，那是一下子出现的，没有过渡。
          `el-collapse-transition` 专门做这件事：进入时把高度从 0 过渡到内容
          实际高度（`scrollHeight`），离开时过渡回 0 再隐藏。

          ⚠ 它要求配 `v-show`（不是 `v-if`）——`v-if` 会把元素直接销毁，
          没有高度可过渡；`v-show` 保留元素，钩子才拿得到 scrollHeight。
        -->
        <el-collapse-transition>
          <ul
            :id="`nav-sub-${sub.key}`"
            v-show="isExpanded(sub.key)"
            class="nav-list nav-sub-list"
          >
            <li v-for="item in sub.items" :key="item.index">
              <router-link
                :to="item.index"
                class="nav-item nav-sub-item"
                :class="{ 'is-active': route.path === item.index }"
              >
                <span>{{ item.label }}</span>
              </router-link>
            </li>
          </ul>
        </el-collapse-transition>
      </div>
    </nav>

    <div class="sidenav-foot">
      <!--
        这里原来写的是「余额由流水实时对账」——那是班费系统的旧口径。
        系统定位已经改成学生信息管理，这句话挂在导航底下既没人看，
        又容易让人以为进错了系统；整行删掉，页脚只留版本号。
        与其硬凑一句不痛不痒的话，不如少说一句。

        版本号取自后端，不写死。以前这里是硬编码的 `v1.0`——每加一轮功能就
        忘了改，界面上挂着一个假版本号，比不显示还糟。拉不到就不渲染。
      -->
      <span v-if="versionLabel" class="num">{{ versionLabel }}</span>
    </div>
  </div>
</template>

<style scoped>
.sidenav {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 2px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px 18px;
}

.brand-mark {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  background: var(--color-primary);
  color: var(--color-on-primary);
  display: grid;
  place-items: center;
  flex: none;
}

.brand-name {
  font-weight: 600;
  font-size: 15px;
  letter-spacing: 0.2px;
}

.brand-sub {
  font-size: 11px;
  color: var(--color-muted-fg);
}

/* 班级切换器（第三十二轮） */
.class-switch {
  padding: 0 10px 8px;
}

.class-switch-select {
  width: 100%;
}

.nav-group + .nav-group {
  margin-top: 6px;
}

.nav-label {
  font-size: 11px;
  color: var(--color-muted-fg);
  padding: 12px 10px 4px;
  letter-spacing: 0.6px;
}

.nav-list {
  list-style: none;
  margin: 0;
  padding: 0 4px;
}

/* ============ 抽拉式子分组（第三十轮） ============ */

/* 开关按钮要完全长得像一个导航项，否则点它和点别的入口手感不一致 */
.nav-sub-toggle {
  width: 100%;
  border: 0;
  background: none;
  text-align: left;
  font-family: inherit;
}

/**
 * 子项：缩进一级，视觉上从属于上面的组。
 *
 * 原来这里还有一条 `border-left` 的竖线做层级标记，已按要求去掉——
 * 侧栏本来就窄，一道竖线夹在两项之间反而像分隔线，把「同一组的子项」
 * 读成了「两个并列的分组」。
 *
 * 缩进量也调小了：父项文字起点在 x=47（图标占 20px + 间距），
 * 子项原来在 x=62，差 15px；现在子项在 x=54，只差 7px——
 * 还是能看出从属关系，但不喧宾夺主。
 */
.nav-sub-list {
  margin-left: 6px;
  padding-left: 20px;
}

.nav-sub-item {
  height: 36px;
  font-size: 13px;
}

/**
 * 尊重「减少动态效果」的系统设置。
 *
 * Element Plus 的折叠动画自带 `transition: 0.3s height ...`，但**不看**
 * `prefers-reduced-motion`——对晕动症用户，展开菜单这种高度动画是要避开的。
 *
 * 这里把过渡关掉（动画本身还在，只是瞬间到位）。
 * 作用域要写成 `.collapse-transition`（不是 `:deep`）：那个类由 Element Plus
 * 动态加在**本组件模板里的那个 `<ul>`** 上，而 `<ul>` 本身带本组件的 scope
 * 属性，所以普通选择器就能命中，优先级还比 Element Plus 的高。
 */
@media (prefers-reduced-motion: reduce) {
  .collapse-transition {
    transition: none !important;
  }
}

/* 与原 el-menu 视觉保持一致：40px 高、左右 20px 内边距、8px 圆角 */
.nav-item {
  display: flex;
  align-items: center;
  height: 40px;
  padding: 0 20px;
  margin-bottom: 2px;
  border-radius: var(--radius);
  font-size: 14px;
  line-height: 1;
  color: var(--color-secondary);
  text-decoration: none;
  cursor: pointer;
  transition:
    background var(--duration) var(--ease),
    color var(--duration) var(--ease);
}

.nav-item .el-icon {
  margin-right: 5px;
}

.nav-item:hover {
  background: rgba(15, 23, 42, 0.05);
  color: var(--color-primary);
}

/* 焦点环：普通态 */
.nav-item:focus-visible {
  box-shadow: var(--ring);
}

.nav-item.is-active {
  background: var(--color-primary);
  color: var(--color-on-primary);
  box-shadow: var(--shadow-sm);
}

.nav-item.is-active:focus-visible {
  box-shadow: var(--shadow-sm), var(--ring);
}

/* 未上线入口：不用 opacity 灰显（会连同对比度一起打折，0.25 只剩 1.4:1），
   改用语义色 --color-muted-fg（白底 5.7:1），状态由 M2/M3/M4 标签表达 */
.nav-item.is-disabled {
  color: var(--color-muted-fg);
  cursor: not-allowed;
}

/* 禁用项不响应 hover：否则会给“点了有反应”的假暗示（hover 会变主题色） */
.nav-item.is-disabled:hover {
  background: transparent;
  color: var(--color-muted-fg);
}

.nav-tag {
  margin-left: auto;
  font-size: 10px;
  line-height: 1;
  padding: 3px 6px;
  border-radius: 999px;
  background: var(--color-muted);
  color: var(--color-muted-fg);
}

.nav-item.is-active .nav-tag {
  background: rgba(255, 255, 255, 0.18);
  color: var(--color-on-primary);
}

.sidenav-foot {
  margin-top: auto;
  padding: 10px;
  font-size: 12px;
  color: var(--color-muted-fg);
  border-top: 1px solid var(--color-border);
}
</style>
