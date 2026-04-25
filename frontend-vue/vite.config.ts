import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// dev server：/api/* 代理到 host 上的 backend（Phase 2 後端 docker 尚未整合 compose 前，走 host 連 8000）
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api':    { target: 'http://localhost:8000', changeOrigin: true },
      '/static': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
