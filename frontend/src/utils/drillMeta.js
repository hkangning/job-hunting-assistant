/**
 * 练习模式（drill，FR-020 / 接口文档 §3.15）的展示口径与纯函数。
 *
 * 与八股陪练（`practice`）无关——项目内 `practice` 专指 FR-009，练习模式一律 `drill`。
 * 纯函数（无 IO / 无 DOM），单测 `tests/drillMeta.test.js`。
 */

/** 题目来源六值（SRS §4.1）。RESUME / INTRO 目前不可导入（ref_id 语义未定，见问题记录），仅用于展示历史数据。 */
export const SOURCE_LABELS = {
  CUSTOM: '手动新建',
  INTRO: '自我介绍',
  RESUME: '画像经历',
  WRONG: '错题本',
  EXPERIENCE: '面经',
  JD: '投递记录'
}

/**
 * 可对比的六项指标。
 *
 * `better`：优劣方向——`up` 越大越好 / `down` 越小越好 / `null` 只作参考**不判优劣**
 * （语速属后者：SRS 给的 180~240 字/分是经验区间，不作评分依据）。
 * `format`：展示格式（`duration` 分秒 / `percent` 百分比 / 留空按原值）。
 */
export const METRICS = [
  { key: 'score', label: '得分', unit: '分', better: 'up' },
  { key: 'duration_ms', label: '时长', unit: '', better: 'down', format: 'duration' },
  { key: 'speech_rate', label: '语速', unit: '字/分', better: null },
  { key: 'filler_count', label: '填充词', unit: '处', better: 'down' },
  { key: 'pause_count', label: '停顿', unit: '处', better: 'down' },
  { key: 'speech_ratio', label: '有效时长占比', unit: '', better: 'up', format: 'percent' }
]

const METRIC_MAP = new Map(METRICS.map((m) => [m.key, m]))

/** 来源中文名；未知值原样返回（前端不因后端新增枚举而崩）。 */
export function sourceLabel(source) {
  if (!source) return ''
  return SOURCE_LABELS[source] || source
}

/** 毫秒 → `1分08秒` / `45秒`；空值 `—`。 */
export function durationText(ms) {
  if (ms == null) return '—'
  const total = Math.max(0, Math.round(Number(ms) / 1000))
  const min = Math.floor(total / 60)
  const sec = total % 60
  return min ? `${min}分${String(sec).padStart(2, '0')}秒` : `${sec}秒`
}

/** 单项指标的展示值（按 `format` 走；空值统一 `—`）。 */
export function metricValue(key, value) {
  if (value == null) return '—'
  const metric = METRIC_MAP.get(key)
  if (metric?.format === 'duration') return durationText(value)
  if (metric?.format === 'percent') return `${Math.round(Number(value) * 100)}%`
  return String(value)
}

/**
 * `12→4 ↓`：箭头表**变化方向**（不是好坏——好坏由 `deltaTone` 着色表达）。
 * 仅对「有优劣方向」的指标给箭头；语速这类只作参考的指标不带队头（避免被读成「升了就好」）。
 * 任一为空 → `—`。
 */
export function formatDelta(key, from, to) {
  if (from == null || to == null) return '—'
  const text = `${metricValue(key, from)}→${metricValue(key, to)}`
  if (!METRIC_MAP.get(key)?.better) return text
  if (Number(to) === Number(from)) return `${text} →`
  return `${text} ${Number(to) > Number(from) ? '↑' : '↓'}`
}

/** 变化的优劣判读（供 Delta 卡着色）：`good` / `bad` / `flat`；指标无优劣方向或值缺失 → `null`。 */
export function deltaTone(key, from, to) {
  if (from == null || to == null) return null
  const better = METRIC_MAP.get(key)?.better
  if (!better) return null
  if (Number(to) === Number(from)) return 'flat'
  const improved = better === 'up' ? Number(to) > Number(from) : Number(to) < Number(from)
  return improved ? 'good' : 'bad'
}

/**
 * 趋势折线的取点：按 `seq` 升序取该指标有值的遍次，缺值的 seq 记进 `skipped`
 * （界面据此标注「第 N 遍未产出表达指标」，而不是画一个假的 0 把曲线拽下去）。
 */
export function trendSeries(items, key) {
  const points = []
  const skipped = []
  for (const item of items || []) {
    const value = item?.[key]
    if (value == null) skipped.push(item?.seq)
    else points.push({ seq: item.seq, value })
  }
  return { points, skipped }
}
