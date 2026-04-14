import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // 开发模式：将 /api/xxx 直接转发至后端（不做 rewrite，保持 /api 前缀）
      '/api': {
        target: 'http://localhost:17843',
        changeOrigin: true,
      },
    },
  },
})
