/** 账号接口封装（接口文档 §3.2）。 */
import request from './request'

export const registerApi = (payload, config) => request.post('/auth/register', payload, config)
export const loginApi = (payload, config) => request.post('/auth/login', payload, config)
export const meApi = (config = {}) => request.get('/auth/me', config)
export const updateAccountApi = (payload, config) => request.put('/auth/profile', payload, config)
export const changePasswordApi = (payload, config) => request.put('/auth/password', payload, config)

export function uploadAvatarApi(file) {
  const form = new FormData()
  form.append('file', file, 'avatar.jpg')
  return request.post('/auth/avatar', form)
}

export const resetAvatarApi = () => request.delete('/auth/avatar')
