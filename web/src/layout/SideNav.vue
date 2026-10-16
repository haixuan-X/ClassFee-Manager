<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import type { GuestScope, Role } from '@/types'
import { GUEST_SCOPE_OPTIONS } from '@/types'

/** 四项全开。后端把库里的 NULL 展开成这个，前端拿不到 scope 时也用它兜底。 */
const ALL_GUEST_SCOPES: GuestScope[] = GUEST_SCOPE_OPTIONS.map((o) => o.value)

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

interface NavGroup {
  title: string
  items: NavItem[]
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
const userStore = useUserStore()

/** 运营角色（与后端 _STAFF_ROUTES 同口径：生活委员 / 班长 / 班主任） */
const STAFF: Role[] = ['ADMIN', 'MONITOR', 'TEACHER']

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

const groups: NavGroup[] = [
  {
    title: '总览',
    items: [{ index: '/dashboard', label: '仪表盘', icon: 'Odometer' }],
  },
  {
    title: '账目',
    items: [
      { index: '/records', label: '账本明细', icon: 'Tickets' },
      { index: '/income', label: '收入登记', icon: 'Bottom', roles: STAFF },
      { index: '/expense', label: '支出登记', icon: 'Top', roles: STAFF },
    ],
  },
  {
    title: '班级',
    items: [
      // 学生信息（第二十三轮）：**全员可见**——默认只显示自己那一行，要看/改别人的
      // 走页面内的申请流程。路由不设 roles，拦在路由层会让同学连自己的信息都看不到。
      // 访客例外：他能看**全部**（服务端 scope 决定的），但一行都改不了。
      { index: '/student-info', label: '学生信息', icon: 'Postcard' },
      // 班级任务（第二十五轮）：全员可读（填答案是全员动作），访客也能看但只能看汇总。
      // 发布按钮在页面内按 `canPublish` 显示，这里不设 roles —— 和学生信息同理，
      // 拦在侧栏会让同学连题都看不到。真正的闸门在 task_service。
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
    .map((group) => ({ ...group, items: group.items.filter(canSee) }))
    .filter((group) => group.items.length > 0),
)
</script>

<template>
  <div class="sidenav">
    <div class="brand">
      <div class="brand-mark" aria-hidden="true">
        <el-icon :size="18"><Wallet /></el-icon>
      </div>
      <div>
        <div class="brand-name">班费收支系统</div>
        <div class="brand-sub">{{ userStore.user?.className ?? '未加入班级' }}</div>
      </div>
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
    </nav>

    <div class="sidenav-foot">
      余额由流水实时对账<br />
      <span class="num">v1.0</span>
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
