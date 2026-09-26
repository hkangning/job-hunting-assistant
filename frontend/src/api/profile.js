/** 画像接口封装（接口文档 §3.12）。设置接口在步骤 8 拆出为独立的 settings.js。 */
import request from './request'

export const getProfileApi = () => request.get('/profile')
export const updateProfileApi = (payload) => request.put('/profile', payload)
