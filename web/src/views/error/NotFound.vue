<script setup lang="ts">
import { useUserStore } from '@/stores/user'

/**
 * 未知地址兜底页：此前 catch-all 直接 redirect 到首页，
 * 地址打错会“悄悄”落到仪表盘，用户完全不知道自己走错了。
 */
const userStore = useUserStore()
</script>

<template>
  <main class="not-found">
    <div class="glass-card card">
      <div class="code num" aria-hidden="true">404</div>
      <h1>页面不存在</h1>
      <p>地址可能输入有误，或该功能还没有上线。</p>
      <router-link class="back" :to="userStore.isLogin ? '/dashboard' : '/login'">
        {{ userStore.isLogin ? '返回仪表盘' : '去登录' }}
      </router-link>
    </div>
  </main>
</template>

<style scoped>
.not-found {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: var(--space-lg) var(--space-md);
}

.card {
  width: min(420px, 100%);
  padding: 36px 28px;
  text-align: center;
}

.code {
  font-size: 56px;
  font-weight: 600;
  line-height: 1;
  letter-spacing: 2px;
  color: var(--color-muted-fg);
}

h1 {
  margin: 14px 0 6px;
  font-size: 20px;
  font-weight: 600;
}

p {
  margin: 0;
  font-size: 13.5px;
  color: var(--color-muted-fg);
}

.back {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 40px;
  margin-top: 20px;
  padding: 0 22px;
  border-radius: var(--radius);
  background: var(--color-primary);
  color: var(--color-on-primary);
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
  transition: background var(--duration) var(--ease), box-shadow var(--duration) var(--ease);
}

.back:hover {
  background: var(--el-color-primary-dark-2);
  box-shadow: var(--shadow-sm);
}
</style>
