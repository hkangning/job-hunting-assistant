/** AI 供应商配置接口封装（接口文档 §3.3）。 */
import request from './request'

// 列表：注册表全部 13 项 + 当前激活标识
export const listProvidersApi = (config) => request.get('/llm-providers', config)

// 免费模型清单（接口文档 §3.3）：两类来源并列——公开免 Key 服务（不受平台配置影响）
// + 平台共享 Key（只含已配的家）。选中即生效、无需账号自备 Key。
export const listFreeModelsApi = (config) => request.get('/llm-providers/free-models', config)

// 选用免费模型：保存与生效一步完成（服务端置 use_shared=1 + 激活位），不清账号已存的 Key
export const selectFreeModelApi = (payload, config) =>
  request.put('/llm-providers/free-model', payload, config)

// 保存（部分更新：只传需要变更的字段）
export const saveProviderApi = (provider, payload) =>
  request.put(`/llm-providers/${provider}`, payload)

// 删除该供应商的全部配置（Key / base_url / model / 模型缓存）
export const deleteProviderApi = (provider) => request.delete(`/llm-providers/${provider}`)

// 设为当前使用
export const activateProviderApi = (provider) =>
  request.post(`/llm-providers/${provider}/activate`)

// 模型列表（接口文档 §3.3）。refresh=true 绕过 24h 缓存强制重拉。
// apiKey / baseUrl 为「临时探测」参数（接口 v1.13）：仅在配置**尚未保存**时携带，
// 传任一即不读不写缓存——结果属于未保存的配置，写进缓存会污染已存 Key 的模型列表。
export const listModelsApi = (
  provider,
  { refresh = false, apiKey = '', baseUrl = '' } = {},
  config = {}
) => {
  const params = {}
  if (refresh) params.refresh = true
  if (apiKey) params.api_key = apiKey
  if (baseUrl) params.base_url = baseUrl
  return request.get(`/llm-providers/${provider}/models`, { ...config, params })
}

// 连通性测试（不落库、不保存配置）
export const testProviderApi = (payload, config) =>
  request.post('/llm-providers/test', payload, config)
