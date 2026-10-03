/**
 * 模型列表拉取的「临时探测」参数组装（接口文档 §3.3，v1.13 起的 api_key / base_url 查询参数）。
 *
 * 取值口径：**表单当前值优先**——用户往表单里填了新 Key / 改了端点，就是想拿这套配置去探；
 * 传任一参数即「临时探测」：后端跳过 24h 缓存、不读不写不落库。表单未填（或端点与已存
 * 相同）的字段不传，由后端回落到当前账号已存配置。
 *
 * 为什么单列此函数（2026-10-03 修复口径）：原实现把「仅未保存过该供应商时才携带」写死在
 * 组件里，于是编辑态「填新 Key → 刷新列表」这条最常用的路径反而继续用旧 Key 探测，失败
 * 信息残留后与新 Key 的测试连通结果同屏矛盾（用户反馈「测通了还显示 Key 无效」）。
 * 口径收敛到本函数后由单测锁定。
 */
export function probeParams(form, item) {
  const savedUrl = item?.base_url || ''
  return {
    apiKey: form.api_key || '',
    baseUrl: form.base_url && form.base_url !== savedUrl ? form.base_url : ''
  }
}
