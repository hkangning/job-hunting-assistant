import axios from 'axios'
import { ElMessage } from 'element-plus'

// 统一响应体：{ code, message, data }
const service = axios.create({
  baseURL: '/api/v1',
  timeout: 30000
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
    // silent：辅助性请求失败时不打扰用户，由调用方自行降级
    if (!error.config || !error.config.silent) {
      ElMessage.error({ message, grouping: true })
    }

    // 透传业务错误码与 HTTP 状态，供调用方分支处理
    const bizError = new Error(message)
    if (error.response && error.response.data) {
      bizError.code = error.response.data.code
      bizError.httpStatus = error.response.status
    }
    return Promise.reject(bizError)
  }
)

export default service
