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
          console.log(`[mock] ${method} ${route}`)

          const auth = AUTH_ROUTES.find(([m, p]) => m === method && p === route)
          if (auth) return sendJson(res, ...(await auth[2](req)))

          const extra = EXTRA_ROUTES[`${method} ${route}`]
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
