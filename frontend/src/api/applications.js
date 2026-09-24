// 投递管理接口（接口文档 §3.3）
import request from './request'

/** 投递列表（筛选 + 分页）。params: { status, city, company, page, page_size } */
export function listApplications(params) {
  return request.get('/applications', { params })
}

/** 投递详情（含备注全文） */
export function getApplication(id) {
  return request.get(`/applications/${id}`)
}

/** 新增投递 */
export function createApplication(data) {
  return request.post('/applications', data)
}

/** 编辑投递（全量更新，未传的可选字段按空处理；status 不由此接口变更） */
export function updateApplication(id, data) {
  return request.put(`/applications/${id}`, data)
}

/** 删除投递 */
export function deleteApplication(id) {
  return request.delete(`/applications/${id}`)
}

/** 状态流转。data: { status, event_at?, remark? } */
export function changeStatus(id, data) {
  return request.patch(`/applications/${id}/status`, data)
}

/** 批量导入（multipart） */
export function importApplications(file) {
  const form = new FormData()
  form.append('file', file)
  return request.post('/applications/import', form)
}

/** 下载导入模板（xlsx 文件流，拦截器已对 blob 直通） */
export function downloadTemplate() {
  return request.get('/applications/template', { responseType: 'blob' })
}

/** 投递趋势（最近 days 天，含 0 值日期；days 默认 30，上限 90） */
export function getTrend(days = 30) {
  return request.get('/applications/trend', { params: { days } })
}
