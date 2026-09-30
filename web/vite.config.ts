import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    // 开发时把 /api 转发到后端
    // 用 127.0.0.1 而不是 localhost：Windows 上 localhost 先解析 ::1，而 uvicorn
    // 只监听 IPv4（0.0.0.0:8080），IPv6 连接要干等 ~2s 才回退，实测每个请求多 2 秒。
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
      },
    },
  },
  build: {
    // Element Plus 全量引入时 chunk 较大，仅提示不阻断
    chunkSizeWarningLimit: 1600,
  },
})
