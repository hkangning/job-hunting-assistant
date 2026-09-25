import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import mockApi from './mock/index.js'

// 开发服务器：端口与后端 CORS 白名单一致
//
// mock 开关：dev 模式下**默认开启**（后端 /auth 未就绪期间），显式设 VITE_USE_MOCK=false 关闭；
// 生产构建永不启用。
//
// 默认值为何写在代码里而不只放 .env.development：仓库 .gitignore 的 `.env.*` 规则会拦下该文件，
// 克隆仓库的人拿不到它——若开关只认环境变量，新人拉下代码就会连上尚不存在的后端而报错。
// 故 `.env.development` 仅作**显式覆盖**用（本地可见"开关在哪"），真正的兜底默认值在此。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const useMock = mode === 'development' && env.VITE_USE_MOCK !== 'false'

  return {
    plugins: [vue(), ...(useMock ? [mockApi()] : [])],
    server: {
      port: 5173,
      proxy: useMock
        ? {}
        : {
            // 后端路径本身即 /api/v1/*，不做 rewrite
            '/api': {
              target: 'http://localhost:8000',
              changeOrigin: true
            },
            // 头像静态文件（后端 StaticFiles 挂载 /static/avatars）
            '/static': {
              target: 'http://localhost:8000',
              changeOrigin: true
            }
          }
    }
  }
})
