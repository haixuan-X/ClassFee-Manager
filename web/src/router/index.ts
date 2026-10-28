import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { fetchMe } from '@/api/auth'
import { useUserStore } from '@/stores/user'
import type { GuestScope } from '@/types'
import { GUEST_SCOPE_OPTIONS, STAFF_ROLES } from '@/types'

/** 四项全开。后端把库里的 NULL 展开成这个；前端拿不到 scope 时也用它兜底。 */
const ALL_GUEST_SCOPES: GuestScope[] = GUEST_SCOPE_OPTIONS.map((o) => o.value)

/**
 * 路由表：M2 起接入记账页面（账本明细 / 收入登记 / 支出登记），
 * M3 接入成员/批次/账号管理，M4 接入班级信息（见 docs/系统设计文档.md 第 8 节）。
 *
 * 第二十四轮删掉了班级公告，第二十五轮换成了班级任务（发出去还要回收答案）。
 *
 * 角色受限页（登记/成员/批次/成员管理）走 meta.roles；**全员可读但只有特定角色能写**
 * 的页面（学生信息、班级任务、班级信息）不设 roles——写操作由后端 service 逐条判，
 * 页面内再按角色隐藏按钮。拦在路由层会造成「同学连题都看不到」。
 */

/**
 * 访客（GUEST，第二十四轮）能进的页面**白名单**。
 *
 * 用户口径：「能看见总览、账目、学生信息、还有我的，就这些」，
 * 第二十五轮加了班级任务（领导要看「返校率怎么样」，但看不到「谁没返校」）。
 *
 * 刻意用白名单而不是逐页 `roles` 排除：往反了写的话，以后新加一个页面
 * 忘了加 `roles`，访客就能进——白名单的默认方向是「关」，漏掉的是新页面，
 * 代价是访客少看一个页面（可发现、可补）；反向的漏是静默放行（不可发现）。
 *
 * 后端同样兜底：访客不在 `STAFF_ROLES`，所有记账/账号管理接口一律 403；
 * 访客答题由 `task_service.can_answer` 拦掉。任务这里放行是**只读**的：
 * 后端对非发布人一律只返回汇总，明细端点 403。
 */
/**
 * 访客可见范围 -> 路由 name（第二十六轮）。
 *
 * ⚠ 必须与 `layout/SideNav.vue` 的 `GUEST_SCOPE_OF_PATH` 保持一致，
 * 两处各写一份必然漂移。漏一项的后果是「侧栏有入口但这里拦掉」或反过来。
 *
 * 不在这张表里的路由（`login`、`profile`）对访客永远放行——
 * 个人信息是他自己的账号，没什么可限制的。
 *
 * 这只是**界面层**的第一道门。后端 `security` 中间件同样按访客范围拦接口，
 * 手输 URL 或直接调接口都绕不过去——前端这套的作用是「不给一个点进去就报错的入口」。
 */
const GUEST_PAGE_SCOPE: Record<string, GuestScope> = {
  dashboard: 'DASHBOARD',
  records: 'RECORDS',
  'student-info': 'STUDENTS',
  tasks: 'TASKS',
  'tasks-overview': 'TASKS',
}

/**
 * 纯院长（第三十轮）能进的页面。
 *
 * 纯院长只管学院，班级事务一概不参与。侧栏里不给他「账目」「班级」两组，
 * 这里再堵上「手输 URL」这一路——两条腿都要走。
 *
 * ⚠ 与后端 `security._PURE_DEAN_ALLOWED` 是**同一个口径**的两端：
 * 后端按路径前缀放行，这里按路由名放行。改任何一边都要看另一边。
 */
const COLLEGE_FREE_PATHS = new Set([
  'dashboard',
  'college-students',
  'college-advisers',
  'college-tasks',
  // 学院视角的班级任务（第三十二轮）：各班班主任发布的任务一览，
  // 和「学院任务」一样是学院事务，纯院长能看。
  'college-class-tasks',
  // 任务总览（第三十二轮）：统计的是**全校**的任务，属学院事务，
  // 纯院长能看。后端 `security._PURE_DEAN_ALLOWED` 同样放行 /api/tasks/overview。
  'tasks-overview',
  'profile',
])
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
        meta: { title: '收入登记', type: 'INCOME', roles: STAFF_ROLES },
      },
      {
        path: 'expense',
        name: 'expense',
        component: () => import('@/views/records/index.vue'),
        meta: { title: '支出登记', type: 'EXPENSE', roles: STAFF_ROLES },
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
        // 学生信息（第二十三轮）：**全员可进**，因为每个人都要看自己的那一行。
        // 行级可见范围由后端裁剪（默认只有自己那行，要看别人必须申请），
        // 前端路由不设 roles——拦在路由层会导致「同学连自己的信息都看不到」。
        // 侧栏放在「班级」分组内（用户口径：加在班级菜单里，不另开分组）。
        path: 'student-info',
        name: 'student-info',
        component: () => import('@/views/student-info/index.vue'),
        meta: { title: '学生信息' },
      },
      {
        // 任务总览（第三十二轮）：统计「现在什么状况」——
        // 多少条、还开着几条、回收率、按班/按发布人的分布。
        // ⚠ **只有院长能看**（用户口径）：它属于「学院」这一组，
        // 而那一组除了院长谁都不展示。路由不设 roles 的话手输 URL 能进，
        // 所以这里要设——入口和直达两条路都堵上。
        path: 'tasks/overview',
        name: 'tasks-overview',
        component: () => import('@/views/tasks/overview.vue'),
        meta: { title: '任务总览', roles: ['DEAN'] },
      },
      {
        // 班级任务（第二十五轮）：发出去还要回收答案，所以三个"看"分得很开——
        // 任务列表全员可读（但只到汇总）、明细只有发布人和班主任、答题访客被拦。
        // 路由不设 roles：同学要能答题，拦在路由层会连题都看不到。
        path: 'tasks',
        name: 'tasks',
        component: () => import('@/views/tasks/index.vue'),
        meta: { title: '班级任务' },
      },
      {
        // 成员缴费与收费批次都直接动钱，仅运营角色（后端另有 _STAFF_ROUTES 强制校验）
        path: 'members',
        name: 'members',
        component: () => import('@/views/members/index.vue'),
        meta: { title: '成员缴费', roles: STAFF_ROLES },
      },
      {
        path: 'batches',
        name: 'batches',
        component: () => import('@/views/batches/index.vue'),
        meta: { title: '收费批次', roles: STAFF_ROLES },
      },
      {
        // 账号管理：老师建班（新增/编辑/重置密码/停用启用），后端 /api/users 仅运营角色
        path: 'member-manage',
        name: 'member-manage',
        component: () => import('@/views/member-manage/index.vue'),
        meta: { title: '成员管理', roles: STAFF_ROLES },
      },
      {
        // 班级信息：全员可读；班级名/年级/班主任的编辑仅运营角色
        path: 'class-info',
        name: 'class-info',
        component: () => import('@/views/class-info/index.vue'),
        meta: { title: '班级信息' },
      },
      {
        // 学院（第三十轮）：**仅院长**。
        // 学院 = 全部班级的聚合视图：跨班级的学生名册、各班班主任名册、
        // 跨班级的任务一览。放在「总览」和「账目」之间的「学院」分组里，
        // 「班级管理」和「任务」是可展开/收起的抽拉式子分组。
        //
        // ⚠ meta.roles 只是**入口层**的闸门，真正的边界在后端
        // （`require_min_level(user, "DEAN", ...)` → 403）。两条腿都要走：
        // 只做后端，班主任会看到一排点进去就报「无权」的入口；
        // 只做前端，手输 URL 就穿透了。
        path: 'college/students',
        name: 'college-students',
        component: () => import('@/views/college/students/index.vue'),
        meta: { title: '学院学生信息', roles: ['DEAN'] },
      },
      {
        path: 'college/advisers',
        name: 'college-advisers',
        component: () => import('@/views/college/advisers/index.vue'),
        meta: { title: '班主任名册', roles: ['DEAN'] },
      },
      {
        // 学院任务（第三十二轮）：**院长发的**任务一览（scope=COLLEGE），
        // 全学院可见、由各班班主任应答。同一页面组件按 scope 参数切换视图。
        // 班主任也进得来（他要应答学院任务）；后端 `require_min_level(user, "TEACHER")` 兜底。
        path: 'college/tasks',
        name: 'college-tasks',
        component: () => import('@/views/college/tasks/index.vue'),
        props: { scope: 'COLLEGE' },
        meta: { title: '学院任务', roles: ['DEAN'] },
      },
      {
        // 学院视角的**班级任务**（第三十二轮）：**班主任发的**任务一览
        // （scope=CLASS）。和上面那个是同一批任务的两类，所以共用页面组件。
        path: 'college/class-tasks',
        name: 'college-class-tasks',
        component: () => import('@/views/college/tasks/index.vue'),
        props: { scope: 'CLASS' },
        meta: { title: '班级任务', roles: ['DEAN'] },
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

/**
 * `/auth/me` 的**刷新节流**。
 *
 * 原来是「每次进路由都拉一次」：点 50 下菜单 = 50 个 `/auth/me`，
 * 而且 `setUser` 每次都会换掉 `user` 对象 → 侧栏（按角色渲染菜单）跟着整棵重渲染，
 * 再叠上 localStorage 写一次。数据量大、机器内存吃紧时，这就是肉眼可见的卡顿。
 *
 * 缓存里的用户信息只用来渲染首屏，**权限边界永远在后端**（`_STAFF_ROUTES`），
 * 所以这里放宽到「5 分钟最多刷新一次」不影响安全：角色被降级时最迟 5 分钟后
 * 界面就收敛了，真出事由后端 401/403 兜底。
 */
const ME_REFRESH_MS = 5 * 60 * 1000
/** 0 = 首屏一定先拉一次（缓存可能是上次会话留下的），之后才进入节流窗口 */
let lastMeSyncAt = 0

router.beforeEach(async (to) => {
  const userStore = useUserStore()

  document.title = to.meta.title ? `${to.meta.title} · 学生信息管理系统` : '学生信息管理系统'

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
        lastMeSyncAt = Date.now()
      } catch {
        /* token 失效由请求拦截器统一处理（清会话跳登录） */
      }
    } else if (Date.now() - lastMeSyncAt >= ME_REFRESH_MS) {
      // ⚠ 时间戳在**发起前**就打上，失败也不回退：
      // 后端挂掉时若「失败即重置」，就变回「每切一次页面重试一次」，
      // 而那次重试要等 10s 超时——正是「点什么都没反应」的那种卡。
      lastMeSyncAt = Date.now()
      void fetchMe()
        .then((info) => userStore.setUser(info))
        .catch(() => {
          /* 后台刷新失败不阻塞导航，5 分钟后自然再试 */
        })
    }
  }
  if (roles && userStore.user && !roles.includes(userStore.user.role)) {
    return { path: '/dashboard' }
  }
  // 纯院长（第三十轮）：不参与班级事务，班级那几个页面连入口都不给。
  // 后端也会 403（`security` 中间件的纯院长白名单），这里是把「手输 URL」
  // 这一路也堵上——两条腿都要走。
  if (userStore.user?.role === 'DEAN' && userStore.user.deanOnly === true) {
    if (!COLLEGE_FREE_PATHS.has(String(to.name ?? ''))) {
      return { path: '/dashboard' }
    }
  }
  // 访客范围（第二十六轮）：meta.roles 拦不住「不设 roles 的全员可读页」
  // （学生信息、班级任务、班级信息），所以对 GUEST 按**他自己账号的范围**判断。
  if (userStore.user?.role === 'GUEST') {
    const name = String(to.name ?? '')
    const need = GUEST_PAGE_SCOPE[name]
    // ⚠ **默认必须是不给**，与 `SideNav.vue` 同一条规则、同一个方向。
    // 两处都翻过一次车：写成「没命中 = 放行」之后，访客能进收入登记、成员管理，
    // 而真正该看、也确实勾了的仪表盘反被限掉——白名单方向反了就是这种结果。
    // 只有 `profile` 显式放行（访客自己的账号，没什么可限制的）。
    const scopes = userStore.user.guestScopes ?? ALL_GUEST_SCOPES
    const allowed = need === undefined ? name === 'profile' : scopes.includes(need)

    if (!allowed) {
      // ⚠ 也不能一律弹 /dashboard：访客可能恰恰没勾仪表盘，
      // 那会把他弹进一个自己同样进不去的页面，在守卫里反复弹、看起来像卡死。
      // 弹到他**第一个有权进的**页面（顺序 = GUEST_PAGE_SCOPE 的定义序）。
      const home = (Object.keys(GUEST_PAGE_SCOPE) as string[]).find((n) =>
        scopes.includes(GUEST_PAGE_SCOPE[n]),
      )
      // 四个路由名和路径本来就一一相同（dashboard/records/student-info/tasks），
      // 直接拼路径即可。一个范围都没勾时兜底到个人信息——那个永远开着。
      return { path: home ? `/${home}` : '/profile' }
    }
  }

  // 已登录访问登录页 → 直接进后台
  if (to.path === '/login' && userStore.isLogin) {
    return { path: '/dashboard' }
  }

  return true
})

export default router
