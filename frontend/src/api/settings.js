/** 设置接口封装（接口文档 §3.12）：账号级偏好 + 系统级抓取配置。 */
import request from './request'

export const getSettingsApi = (config) => request.get('/settings', config)

// 部分更新语义：只提交需要变更的字段（PUT 返回更新后的完整设置）
export const updateSettingsApi = (payload) => request.put('/settings', payload)
