// 投递状态常量：中文名 / 色值 / 合法流转的唯一出处
// 依据：数据库设计文档 §5（枚举码）、系统设计文档 §4.5.1（状态色）、
//       后端 application_service.LEGAL_TRANSITIONS（SRS FR-004 状态机）
// 注意：枚举码与色值的映射不得改动（设计文档 §4.5.1）

export const APPLICATION_STATUSES = [
  { value: 'APPLIED', label: '已投递', color: 'var(--s-applied)' },
  { value: 'WRITTEN', label: '待笔试', color: 'var(--s-written)' },
  { value: 'INTERVIEW', label: '面试中', color: 'var(--s-interview)' },
  { value: 'OFFER', label: '已获 offer', color: 'var(--s-offer)' },
  { value: 'CLOSED', label: '已结束', color: 'var(--s-closed)' }
]

export const STATUS_LABELS = Object.fromEntries(
  APPLICATION_STATUSES.map((s) => [s.value, s.label])
)

export const STATUS_COLORS = Object.fromEntries(
  APPLICATION_STATUSES.map((s) => [s.value, s.color])
)

// 合法流转（SRS FR-004 v1.3）：已投递→待笔试→面试中→已获 offer；
// 除「已结束」外任意状态均可流转至「已结束」（含已获 offer——拒 offer / offer 撤回 / 谈崩）；
// 只能沿链前进或终止，不可回退
export const LEGAL_TRANSITIONS = {
  APPLIED: ['WRITTEN', 'CLOSED'],
  WRITTEN: ['INTERVIEW', 'CLOSED'],
  INTERVIEW: ['OFFER', 'CLOSED'],
  OFFER: ['CLOSED'],
  CLOSED: []
}

/** 判断状态能否从 from 流转到 to（看板拖拽落点预判用） */
export function canTransit(from, to) {
  return (LEGAL_TRANSITIONS[from] || []).includes(to)
}
