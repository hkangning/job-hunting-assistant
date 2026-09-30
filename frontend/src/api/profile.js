/** 画像接口封装（接口文档 §3.12）。设置接口在步骤 8 拆出为独立的 settings.js。 */
import request from './request'

export const getProfileApi = () => request.get('/profile')
export const updateProfileApi = (payload) => request.put('/profile', payload)

/**
 * 上传简历解析（multipart：.pdf / .docx，≤10MB）。
 * **纯解析、不落库**——返回 `{extracted|null}`（含结构化经历条目），用户核对修改后走 `updateProfileApi` 保存。
 */
export function parseResumeApi(file) {
  const form = new FormData()
  form.append('file', file)
  return request.post('/profile/resume', form)
}
