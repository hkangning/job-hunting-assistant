import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '../router'
import { useUserStore } from '../stores/user'

// 统一响应体：{ code, message, data }
const service = axios.create({
  baseURL: '/api/v1',
  timeout: 30000
})

// 请求拦截器：注入当前账号 Token（接口文档 1.1 鉴权约定）
service.interceptors.request.use((config) => {
  const { token } = useUserStore()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

service.interceptors.response.use(
  (response) => {
    // 二进制响应直通（步骤 4 的模板下载用）
    if (response.config.responseType === 'blob') {
      return response.data
    }
    const body = response.data
    // 防御分支：后端当前不会返回「HTTP 200 + code≠0」，此处兜底
    if (body && typeof body === 'object' && 'code' in body && body.code !== 0) {
      const err = new Error(body.message || '请求失败')
      err.code = body.code
      err.httpStatus = response.status
      if (!response.config.silent) {
        ElMessage.error({ message: err.message, grouping: true })
      }
      return Promise.reject(err)
    }
    // 解包：调用方直接拿业务数据，无需再解构 code / message
    return body.data
  },
  (error) => {
    let message
    if (error.code === 'ECONNABORTED') {
      message = '请求超时，请稍后重试'
    } else if (error.response && error.response.data && error.response.data.message) {
      message = error.response.data.message
    } else {
      message = '网络异常，请检查后端服务是否已启动'
    }

    const code = error.response && error.response.data ? error.response.data.code : undefined
    // 登录态失效：80001 未登录/Token 无效、80002 已过期（接口文档 1.3）
    const isTokenError = code === 80001 || code === 80002

    // silent：辅助性请求失败时不打扰用户，由调用方自行降级；token 失效走下面的统一提示
    if (!isTokenError && (!error.config || !error.config.silent)) {
      ElMessage.error({ message, grouping: true })
    }

    // 透传业务错误码与 HTTP 状态，供调用方分支处理
    const bizError = new Error(message)
    if (error.response && error.response.data) {
      bizError.code = error.response.data.code
      bizError.httpStatus = error.response.status
      // 错误响应携带的业务明细（如导入全行非法时 20002 的行级错误清单）
      bizError.data = error.response.data.data
    }

    // 全局登出：清状态 + 跳登录页。/welcome 的 Token 预检带 silent，只清状态不跳转（由该页自行决定目标）
    if (isTokenError) {
      useUserStore().reset()
      if (!error.config || !error.config.silent) {
        ElMessage.error({ message: '登录状态已失效，请重新登录', grouping: true })
        router.replace('/login')
      }
    }

    return Promise.reject(bizError)
  }
)

export default service
