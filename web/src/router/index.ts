import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { fetchMe } from '@/api/auth'
import { useUserStore } from '@/stores/user'

/**
 * 路由表：M2 起接入记账页面（账本明细 / 收入登记 / 支出登记），
 * M3 接入成员/批次/账号管理，M4 接入班级公告与班级信息（见 docs/系统设计文档.md 第 8 节）。
 *
 * 角色受限页（登记/成员/批次/成员管理）走 meta.roles；**全员可读但只有运营角色能写**
 * 的页面（公告、班级信息）不设 roles——写操作由后端 `_STAFF_ROUTES` 兜底，页面内按角色隐藏按钮。
 */
const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/login/index.vue'),
    meta: { title: '登录', public: true },
  },
  {
    path: '/',
    component: () => import('@/layout/AppLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/dashboard/index.vue'),
        meta: { title: '仪表盘' },
      },
      {
        path: 'records',
        name: 'records',
        component: () => import('@/views/records/index.vue'),
        meta: { title: '账本明细' },
      },
      {
        // 登记入口仅运营角色可见（后端另有 _STAFF_ROUTES 强制校验）
        path: 'income',
        name: 'income',
        component: () => import('@/views/records/index.vue'),
        meta: { title: '收入登记', type: 'INCOME', roles: ['ADMIN', 'MONITOR', 'TEACHER'] },
      },
      {
        path: 'expense',
        name: 'expense',
        component: () => import('@/views/records/index.vue'),
        meta: { title: '支出登记', type: 'EXPENSE', roles: ['ADMIN', 'MONITOR', 'TEACHER'] },
      },
      {
        // 我的缴费（第十八轮）：回答普通同学的三个问题 —— 有没有班费要交 / 我交了吗 /
        // 什么时候截止。缴费名单（views/members）仍限运营角色，因为里面有别人的姓名与学号。
        //
        // 第二十轮：班主任移出。缴费对象只有 MEMBER（后端 `_class_members` 只给 MEMBER
        // 生成缴费行），班主任是 .env 声明的老师账号、不是学生，给他这个入口只会看到
        // 一句「你不属于缴费对象」的死胡同。**roles 缺 TEACHER 是一道前端导航闸**，
        // 挡住的是「找不到入口」；真正的权限边界仍在后端。
        path: 'my-fees',
        name: 'my-fees',
        component: () => import('@/views/my-fees/index.vue'),
        meta: { title: '我的缴费', roles: ['ADMIN', 'MONITOR', 'MEMBER'] },
      },
      {
        // 成员缴费与收费批次都直接动钱，仅运营角色（后端另有 _STAFF_ROUTES 强制校验）
        path: 'members',
        name: 'members',
        component: () => import('@/views/members/index.vue'),
        meta: { title: '成员缴费', roles: ['ADMIN', 'MONITOR', 'TEACHER'] },
      },
      {
        path: 'batches',
        name: 'batches',
        component: () => import('@/views/batches/index.vue'),
        meta: { title: '收费批次', roles: ['ADMIN', 'MONITOR', 'TEACHER'] },
      },
      {
        // 账号管理：老师建班（新增/编辑/重置密码/停用启用），后端 /api/users 仅运营角色
        path: 'member-manage',
        name: 'member-manage',
        component: () => import('@/views/member-manage/index.vue'),
        meta: { title: '成员管理', roles: ['ADMIN', 'MONITOR', 'TEACHER'] },
      },
      {
        // 班级公告：全员可读；发布/编辑/置顶/下架/删除仅运营角色（后端 _STAFF_ROUTES 强制校验）
        path: 'notices',
        name: 'notices',
        component: () => import('@/views/notices/index.vue'),
        meta: { title: '班级公告' },
      },
      {
        // 班级信息：全员可读；班级名/年级/班主任的编辑仅运营角色
        path: 'class-info',
        name: 'class-info',
        component: () => import('@/views/class-info/index.vue'),
        meta: { title: '班级信息' },
      },
      {
        // 个人信息：全员可访问（普通成员也能改自己的姓名/学号/手机号）。
        // 不声明 meta.roles = 任何登录角色都能进；后端 /auth/profile 同样不进 _STAFF_ROUTES。
        path: 'profile',
        name: 'profile',
        component: () => import('@/views/profile/index.vue'),
        meta: { title: '个人信息' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/error/NotFound.vue'),
    meta: { title: '页面不存在' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach(async (to) => {
  const userStore = useUserStore()

  document.title = to.meta.title ? `${to.meta.title} · 班费收支系统` : '班费收支系统'

  // 未登录访问受保护页面 → 跳登录并带上回跳地址
  if (!to.meta.public && !userStore.isLogin) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  // 角色受限页面（收入/支出登记、成员缴费、收费批次、成员管理）：已登录但角色不符 → 回仪表盘。
  // 第十六轮：用户信息改为随 token 一起持久化后，这里要分两种情况——
  //   ① 没有缓存（首次使用 / 缓存被清）→ 必须**等** /auth/me 回来才能判角色
  //   ② 有缓存 → 首屏立刻按缓存渲染（否则会闪一下「未登录」且侧栏少一半入口），
  //      同时**后台**再拉一次权威数据收敛（班主任被降级成普通成员时界面能跟上）。
  // 缓存只用于首屏展示，真正的权限边界永远在后端 _STAFF_ROUTES。
  const roles = to.meta.roles as string[] | undefined
  if (userStore.isLogin) {
    if (!userStore.user) {
      try {
        userStore.setUser(await fetchMe())
      } catch {
        /* token 失效由请求拦截器统一处理（清会话跳登录） */
      }
    } else {
      void fetchMe()
        .then((info) => userStore.setUser(info))
        .catch(() => {
          /* 后台刷新失败不阻塞导航，下次进页面再试 */
        })
    }
  }
  if (roles && userStore.user && !roles.includes(userStore.user.role)) {
    return { path: '/dashboard' }
  }

  // 已登录访问登录页 → 直接进后台
  if (to.path === '/login' && userStore.isLogin) {
    return { path: '/dashboard' }
  }

  return true
})

export default router
