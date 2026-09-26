/** JD 分析报告接口封装（接口文档 §3.6）。 */
import request from './request'

/** 报告列表。params: { application_id?, page?, page_size? }（page_size 默认 10、上限 50） */
export function listReports(params) {
  return request.get('/jd-reports', { params })
}

/** 报告详情（含 jd_text 快照与 report_text 全文） */
export function getReport(id) {
  return request.get(`/jd-reports/${id}`)
}
