/** AI 供应商配置接口封装（接口文档 §3.3）。 */
import request from './request'

// 列表：注册表全部 12 项 + 当前激活标识
export const listProvidersApi = (config) => request.get('/llm-providers', config)

// 保存（部分更新：只传需要变更的字段）
export const saveProviderApi = (provider, payload) =>
  request.put(`/llm-providers/${provider}`, payload)

// 删除该供应商的全部配置（Key / base_url / model / 模型缓存）
export const deleteProviderApi = (provider) => request.delete(`/llm-providers/${provider}`)

// 设为当前使用
export const activateProviderApi = (provider) =>
  request.post(`/llm-providers/${provider}/activate`)

// 模型列表（refresh=true 绕过 24h 缓存强制重拉）
export const listModelsApi = (provider, refresh = false, config = {}) =>
  request.get(`/llm-providers/${provider}/models`, {
    ...config,
    ...(refresh ? { params: { refresh: true } } : {})
  })

// 连通性测试（不落库、不保存配置）
export const testProviderApi = (payload, config) =>
  request.post('/llm-providers/test', payload, config)
