/** 画像与设置接口封装（接口文档 §3.14）。 */
import request from './request'

export const getProfileApi = () => request.get('/profile')
export const updateProfileApi = (payload) => request.put('/profile', payload)
export const getSettingsApi = () => request.get('/settings')
export const updateSettingsApi = (payload) => request.put('/settings', payload)
