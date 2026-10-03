/** 站内提醒接口封装（接口文档 §3.14）。 */
import request from './request'

// 提醒列表。
// 参数：date = remind_date 等于该日（YYYY-MM-DD，概览页取「今天生成」的提醒）；
//       checked = 是否已读；page / page_size = 分页。
// 响应按分页约定 {total, items}；items: {id, reminder_type, ref_id, ref_type, content, remind_date, checked}
export const listRemindersApi = (params = {}, config = {}) =>
  request.get('/reminders', { ...config, params })

// 标记已读（响应 data: null）
export const checkReminderApi = (id, config = {}) => request.put(`/reminders/${id}/check`, null, config)
