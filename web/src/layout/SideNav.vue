<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import type { Role } from '@/types'

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
 * 「我的缴费」可见角色 = 全部角色减去班主任。
 *
 * 与后端 `batch_service._class_members` 同口径：缴费名单**只列 MEMBER**，运营角色
 * 不会被生成缴费行，也就不存在「我交没交」。班主任是 .env 声明的老师账号、不是学生，
 * 给他一个永远显示「你不属于缴费对象」的死胡同页面毫无意义（第二十轮移除）。
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
      // 「我的缴费」：回答「有没有班费要交 / 我交了吗 / 什么时候截止」，这三问
      // **只有缴费对象问得出来** —— 后端 `_class_members` 只给 MEMBER 生成缴费行，
      // 运营角色进去只会看到一句「你不属于缴费对象」的死胡同页面。
      // 班主任是老师、本就不是缴费对象（.env 声明的账号，不是学生），第二十轮起不给他这个入口。
      // 「成员缴费」（缴费名单）里有别人的姓名与学号，仍限运营角色。
      { index: '/my-fees', label: '我的缴费', icon: 'Wallet', roles: PAYABLE },
      { index: '/members', label: '成员缴费', icon: 'UserFilled', roles: STAFF },
      { index: '/batches', label: '收费批次', icon: 'Collection', roles: STAFF },
      { index: '/member-manage', label: '成员管理', icon: 'User', roles: STAFF },
      // 公告与班级信息：全员可读，发布/编辑由后端限定运营角色
      { index: '/notices', label: '班级公告', icon: 'Bell' },
      { index: '/class-info', label: '班级信息', icon: 'School' },
    ],
  },
  {
    // 第十五轮：个人信息全员可进（普通成员改自己的姓名/学号/手机号）
    title: '我的',
    items: [{ index: '/profile', label: '个人信息', icon: 'Postcard' }],
  },
]

/** 按角色过滤入口：用户信息未拉到时默认隐藏受限入口（角色不符 = 回仪表盘，服务端角色表兜底） */
function canSee(item: NavItem): boolean {
  if (item.disabled || !item.roles) return true
  if (!userStore.user) return false
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
