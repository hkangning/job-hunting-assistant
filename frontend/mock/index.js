/**
 * dev-only mock：`VITE_USE_MOCK=true` 时接管全部 /api/v1/*（vite.config.js 同时关闭代理，二者互斥）。
 * 生产构建不引用本目录，删除或改开关均不影响产物。
 */
import { AUTH_ROUTES } from './auth.js'
import { db } from './db.js'
import {
  getProfile, putProfile, getSettings, putSettings, overview,
  emptyData, health, staticAvatar, fail404
} from './misc.js'

/** 返回**硬编码样例数据**的接口（非真实业务数据）——日志里明确标注。
 *  台账 #61 的三个误报全部源于此：样例被当成真系统的数据去排查。 */
const SAMPLE_ROUTES = new Set(['/overview'])

const EXTRA_ROUTES = {
  'GET /profile': getProfile,
  'PUT /profile': putProfile,
  'GET /settings': getSettings,
  'PUT /settings': putSettings,
  'GET /overview': overview,
  'GET /health': health
}

/** 注意参数顺序：handler 统一返回 [body, status]，展开即 (res, body, status)。 */
const sendJson = (res, body, status = 200) => {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json; charset=utf-8')
  res.end(JSON.stringify(body))
}

const sendBytes = (res, bytes) => {
  res.statusCode = 200
  res.setHeader('Content-Type', 'image/png')
  res.end(bytes)
}

export default function mockApi() {
  return {
    name: 'jobpilot-mock-api',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const path = req.url.split('?')[0]
        const method = req.method.toUpperCase()

        // 头像静态文件（与后端一致：/uploads/avatars/<file>）
        if (path.startsWith('/uploads/avatars/')) {
          const [bytes, status] = staticAvatar(req)
          return status === 404 ? next() : sendBytes(res, bytes)
        }

        // 内存库重置（仅 dev mock 提供）：供断言脚本与演示前清场，可重复执行
        if (method === 'POST' && path === '/__mock__/reset') {
          db.users.length = 0
          db.profiles.clear()
          db.configs.clear()
          db.avatars.clear()
          db.seq = 0
          return sendJson(res, { code: 0, message: 'ok', data: null })
        }

        if (!path.startsWith('/api/v1/')) return next()

        // 兜底捕获：mock 内部异常降级为 500 响应，不能让一个坏请求带崩整个 dev server
        try {
          const route = path.slice('/api/v1'.length)
          const auth = AUTH_ROUTES.find(([m, p]) => m === method && p === route)
          const extra = EXTRA_ROUTES[`${method} ${route}`]

          // 日志带上数据来源标注：样例数据 / 未实现，二者都容易被误读为真系统行为
          const tag = auth
            ? ''
            : extra
              ? SAMPLE_ROUTES.has(route)
                ? '（样例数据，非真实业务数据）'
                : ''
              : '（未单独实现，返回空数据）'
          console.log(`[mock] ${method} ${route}${tag}`)

          if (auth) return sendJson(res, ...(await auth[2](req)))
          if (extra) return sendJson(res, ...(await extra(req)))

          // 未单独实现的业务接口：鉴权通过则空数据成功，否则 401
          sendJson(res, ...(await emptyData(req)))
        } catch (err) {
          console.error('[mock] handler error:', err)
          sendJson(res, { code: 10000, message: 'mock 内部错误：' + err.message, data: null }, 500)
        }
      })
    }
  }
}
