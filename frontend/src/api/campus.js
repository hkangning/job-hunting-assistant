/**
 * 校招情报接口（接口文档 §3.16 / §3.4）：宣讲会/双选会、岗位、投喂、订阅规则、日历、采集源。
 *
 * 全部走 request.js（自动解包 data、注入 Token、非 silent 时统一弹错）；
 * 查询类需要页内错误态时由调用方追加 `config` 传 `{ silent: true }`（照 reminders.js）。
 */
import request from './request'

// ---------- 宣讲会 / 双选会 ----------
export function listCampusEvents(params, config = {}) {
  return request.get('/campus-events', { ...config, params })
}

// ---------- 岗位 ----------
export function listJobPostings(params, config = {}) {
  return request.get('/job-postings', { ...config, params })
}

/** 投喂抽取预览（不入库）：{text} 或 {url} 二选一；未配 AI → 10012、抽取失败 / 链接被拒 → 70003。 */
export function ingestJobPosting(payload) {
  return request.post('/job-postings/ingest', payload)
}

/** 确认入库：title / company 必填；raw_excerpt 回传原文供日后校对（仅投喂通道保存）。 */
export function createJobPosting(payload) {
  return request.post('/job-postings', payload)
}

/** 删除投喂岗位；自动抓取的公共岗位不可删（10001）、他人与不存在 → 404 + 10002。 */
export function deleteJobPosting(id) {
  return request.delete(`/job-postings/${id}`)
}

// ---------- 订阅规则 ----------
export function listSubscriptions(config = {}) {
  return request.get('/subscriptions', config)
}

export function createSubscription(payload) {
  return request.post('/subscriptions', payload)
}

/** 部分更新：未传字段保持原值，传空数组 = 清空该维度。 */
export function updateSubscription(id, payload) {
  return request.put(`/subscriptions/${id}`, payload)
}

export function deleteSubscription(id) {
  return request.delete(`/subscriptions/${id}`)
}

// ---------- 日历 ----------
/** 四类事件聚合；按整月下发（start = 月初 / end = 月末），空区间返回空数组。 */
export function listCalendar(params, config = {}) {
  return request.get('/calendar', { ...config, params })
}

// ---------- 采集源 ----------
export function listCrawlSources(config = {}) {
  return request.get('/crawl-sources', config)
}

export function createCrawlSource(payload) {
  return request.post('/crawl-sources', payload)
}

/** 部分更新；编辑成功会重置该源采集状态（后端清 last_status / last_error）。 */
export function updateCrawlSource(id, payload) {
  return request.put(`/crawl-sources/${id}`, payload)
}

export function deleteCrawlSource(id) {
  return request.delete(`/crawl-sources/${id}`)
}

/**
 * 手动触发采集（强制刷新，不受每日开关限制）：不传 source_id = 全部启用源，整体 200 + 逐源结果；
 * 指定单源且该源失败 → 502 + 70002（message 为该源失败原因）。
 */
export function runCrawl(payload = {}, config = {}) {
  return request.post('/crawl-sources/run', payload, config)
}
