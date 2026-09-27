import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import mockApi from './mock/index.js'

/** 启动后打印当前数据来源（台账 #61）：曾因「静默走 mock」把样例数据当成真系统排查了一轮。 */
function modeBanner(useMock) {
  return {
    name: 'jobpilot-mode-banner',
    apply: 'serve',
    configureServer(server) {
      server.httpServer?.once('listening', () => {
        const text = useMock
          ? '[模式] MOCK 内存数据（/__mock__/reset 可清场）'
          : '[模式] 真实后端 http://localhost:8000'
        server.config.logger.info(`  ➜  ${text}`)
      })
    }
  }
}

// 开发服务器：端口与后端 CORS 白名单一致
//
// mock 开关：dev 模式下**默认关闭**（连真实后端），显式设 VITE_USE_MOCK=true 才启用；生产构建永不启用。
//
// 两次默认值调整围绕同一件事——别让人**不知不觉**看到样例数据：
//   ① 默认值写在代码里、而非只放 .env.development：`.gitignore` 的 `.env.*` 会拦下该文件，
//      克隆仓库的人拿不到它，若开关只认环境变量，"想开 mock 的人"反而开不了；
//   ② 反过来，默认值曾设为"开"（后端 /auth 未就绪期的权宜之计），但后端步骤 5 早已交付，
//      收益归零而风险放大——换机 / 重新 clone 时 `.env.development` 一旦缺失，
//      dev server 就静默接管全部接口，样例数据被当成真系统（台账 #61 的三个误报即源于此）。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const useMock = mode === 'development' && env.VITE_USE_MOCK === 'true'

  return {
    plugins: [vue(), modeBanner(useMock), ...(useMock ? [mockApi()] : [])],
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
            // 头像静态文件（后端 StaticFiles 挂载 /uploads → backend/uploads/）
            '/uploads': {
              target: 'http://localhost:8000',
              changeOrigin: true
            }
          }
    }
  }
})
