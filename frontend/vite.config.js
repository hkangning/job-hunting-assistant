import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发服务器：端口与后端 CORS 白名单一致；/api 代理到本机后端
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      // 后端路径本身即 /api/v1/*，不做 rewrite
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  }
})
