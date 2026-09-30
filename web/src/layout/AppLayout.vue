<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchMe } from '@/api/auth'
import { useUserStore } from '@/stores/user'
import { ROLE_TEXT } from '@/types'
import SideNav from '@/layout/SideNav.vue'
import PasswordDialog from '@/layout/PasswordDialog.vue'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const drawerOpen = ref(false)
const passwordVisible = ref(false)

/** 顶栏标题取自路由 meta */
const pageTitle = computed(() => (route.meta.title as string) || '班费收支系统')

const roleText = computed(() =>
  userStore.user ? ROLE_TEXT[userStore.user.role] : '未登录',
)

/** 刷新后内存中的用户信息为空，进来先拉一次 /auth/me */
onMounted(async () => {
  if (userStore.isLogin && !userStore.user) {
    try {
      userStore.setUser(await fetchMe())
    } catch {
      /* 401 已由拦截器统一处理（跳登录） */
    }
  }
})

function onCommand(command: string | number | object) {
  if (command === 'password') {
    passwordVisible.value = true
  } else if (command === 'profile') {
    router.push('/profile')
  } else if (command === 'logout') {
    userStore.clear()
    router.replace('/login')
  }
}
</script>

<template>
  <div class="layout">
    <!-- 桌面端固定侧栏 -->
    <aside class="sidebar" aria-label="主导航">
      <SideNav />
    </aside>
    <div v-if="drawerOpen" class="overlay" @click="drawerOpen = false" />

    <div class="main">
      <header class="topbar">
        <button
          class="icon-btn hamburger"
          type="button"
          aria-label="打开导航菜单"
          :aria-expanded="drawerOpen"
          @click="drawerOpen = true"
        >
          <el-icon :size="20"><Menu /></el-icon>
        </button>

        <div class="topbar-title">
          <div class="crumb">首页 / {{ pageTitle }}</div>
          <h1>{{ pageTitle }}</h1>
        </div>

        <div class="spacer" />

        <el-dropdown trigger="click" @command="onCommand">
          <button class="user-chip" type="button" data-restore-focus>
            <span class="avatar" aria-hidden="true">{{ userStore.displayName.slice(0, 1) }}</span>
            <span class="user-text">
              <span class="user-name">{{ userStore.displayName }}</span>
              <small>{{ roleText }}</small>
            </span>
            <el-icon :size="14"><ArrowDown /></el-icon>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="password">
                <el-icon><Lock /></el-icon>修改密码
              </el-dropdown-item>
              <el-dropdown-item command="profile">
                <el-icon><Postcard /></el-icon>个人信息
              </el-dropdown-item>
              <el-dropdown-item divided command="logout">
                <el-icon><SwitchButton /></el-icon>退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </header>

      <main class="content">
        <router-view />
      </main>
    </div>

    <!-- 移动端抽屉 -->
    <el-drawer
      v-model="drawerOpen"
      direction="ltr"
      :with-header="false"
      size="260px"
      aria-label="主导航"
    >
      <SideNav />
    </el-drawer>

    <PasswordDialog v-model="passwordVisible" />
  </div>
</template>

<style scoped>
.layout {
  min-height: 100vh;
  display: flex;
}

.sidebar {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: 40;
  width: 220px;
  padding: var(--space-md) var(--space-sm);
  background: var(--color-card);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-right: 1px solid var(--color-border);
  overflow-y: auto;
}

.main {
  flex: 1;
  min-width: 0;
  margin-left: 220px;
  display: flex;
  flex-direction: column;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 30;
  height: 60px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 var(--space-xl);
  background: rgba(245, 247, 251, 0.8);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--color-border);
}

.topbar-title h1 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  line-height: 1.3;
}

.crumb {
  font-size: 12px;
  color: var(--color-muted-fg);
}

.spacer {
  flex: 1;
}

/* 桌面隐藏汉堡：必须写成双类选择器，
   否则会被后面 .icon-btn 的 display:grid 覆盖（同类特指度按源顺序取胜） */
.icon-btn.hamburger {
  display: none;
}

.icon-btn {
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  border-radius: var(--radius);
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-secondary);
  cursor: pointer;
  transition: background var(--duration) var(--ease), box-shadow var(--duration) var(--ease);
}

.icon-btn:hover {
  background: var(--color-muted);
  box-shadow: var(--shadow-sm);
}

.user-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px 4px 4px;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  cursor: pointer;
  transition: box-shadow var(--duration) var(--ease);
}

.user-chip:hover {
  box-shadow: var(--shadow-sm);
}

.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--color-accent), var(--color-primary));
  color: var(--color-on-primary);
  display: grid;
  place-items: center;
  font-size: 13px;
  font-weight: 600;
  flex: none;
}

.user-text {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  line-height: 1.2;
}

.user-name {
  font-size: 13px;
  font-weight: 600;
}

.user-text small {
  font-size: 11px;
  color: var(--color-muted-fg);
}

.content {
  flex: 1;
  width: 100%;
  max-width: 1440px;
  margin: 0 auto;
  padding: var(--space-xl);
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
}

.overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.4);
  z-index: 45;
}

@media (max-width: 768px) {
  .sidebar {
    display: none;
  }

  .main {
    margin-left: 0;
  }

  .icon-btn.hamburger {
    display: grid;
  }

  .topbar {
    height: 56px;
    padding: 0 var(--space-md);
  }

  .content {
    padding: var(--space-md);
    gap: var(--space-md);
  }

  .user-text {
    display: none;
  }
}
</style>
