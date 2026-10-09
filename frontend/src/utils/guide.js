/**
 * 新手指引（步骤 28，FR-019）：5 步编排与判定纯逻辑。driver.js 封装在 GuideTour.vue。
 * 增删步骤只改 TOUR_STEPS；锚点用 data-tour 属性（挂在 SideNav 菜单项 / UserMenu 根元素上），
 * 不随菜单文案改动而失配；本模块零依赖，node:test 直测。
 */

/** 5 步编排：element 为锚点选择器，popover.title / description 为弹层文案（系统设计 §4.7）。
 *  结构直接对齐 driver.js 的 DriveStep（title/description 在 popover 子对象里，放顶层不会被渲染）。 */
export const TOUR_STEPS = [
  {
    element: '[data-tour="Applications"]',
    popover: {
      title: '投递管理',
      description: '投递全记这里：表单 / 悬浮球一句话 / 批量导入，三种录入方式。'
    }
  },
  {
    element: '[data-tour="JdAnalysis"]',
    popover: {
      title: 'JD 匹配分析',
      description: '粘贴 JD 出匹配报告：评分 + 差距 + 准备建议。'
    }
  },
  {
    element: '[data-tour="InterviewList"]',
    popover: {
      title: '模拟面试',
      description: '选一条投递发起面试，语音作答 + 逐题点评。'
    }
  },
  {
    element: '[data-tour="Practice"]',
    popover: {
      title: '八股陪练',
      description: '笔试备战主战场：答错的题自动进错题本（就在下方），按 1/3/7/15 天复习。'
    }
  },
  {
    element: '[data-tour="UserMenu"]',
    popover: {
      title: '用户菜单',
      description: 'AI 功能总开关：从这里进「AI 配置」填供应商 Key、选模型。'
    }
  }
]

/** 是否应自动启动：仅当账号未确认过引导。settings 为 null/undefined（拉取失败）→ 不启动。 */
export function shouldStartTour(settings) {
  if (!settings || typeof settings !== 'object') return false
  return settings.guide_done !== true
}

/** 过滤锚点不在 DOM 的步骤（元素缺失自动跳过）；全缺失返回空数组，调用方据此不启动。 */
export function filterAvailableSteps(steps, query = (sel) => document.querySelector(sel)) {
  return steps.filter((s) => Boolean(query(s.element)))
}
