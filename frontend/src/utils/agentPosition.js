/**
 * AI 助手悬浮球 / 浮窗的位置计算（纯函数，单测覆盖）。
 *
 * 位置模型：唯一的锚点是**悬浮球**（左上角坐标）——球可拖到任意位置并记忆；
 * 浮窗位置由锚点推导：球在哪半边，面板就朝屏幕中心方向展开，再钳进视口。
 * 拖动浮窗头部（面板跟手）结束后，用面板位置反向换算回锚点，两套交互共用一个位置。
 */
export const BALL_SIZE = 58 // 与 AgentFloatBall.vue 的 .agent-ball 尺寸一致
export const PANEL_W = 400 // 与 .agent-panel 宽度一致

const MARGIN = 8

/** 浮窗高度：与 CSS `height: min(620px, calc(100vh - 96px))` 保持一致。 */
export const panelHeight = (vh) => Math.min(620, vh - 96)

/** 球位置钳制：不出视口、四边留 MARGIN；视口小于球时收在左上角。 */
export function clampBallPos(x, y, vw, vh, margin = MARGIN) {
  const maxX = Math.max(margin, vw - BALL_SIZE - margin)
  const maxY = Math.max(margin, vh - BALL_SIZE - margin)
  return { x: Math.min(Math.max(x, margin), maxX), y: Math.min(Math.max(y, margin), maxY) }
}

/** 面板位置钳制（拖头部跟手时用）。 */
export function clampPanelRect(left, top, vw, vh, panelW, panelH, margin = MARGIN) {
  const maxLeft = Math.max(margin, vw - panelW - margin)
  const maxTop = Math.max(margin, vh - panelH - margin)
  return {
    left: Math.min(Math.max(left, margin), maxLeft),
    top: Math.min(Math.max(top, margin), maxTop)
  }
}

/** 由球锚点推导面板位置：球在左半屏面板左缘对齐、右半屏右缘对齐；上/下半屏同理（朝屏幕中心展开）。 */
export function panelRectFromBall(ball, vw, vh, panelW, panelH, margin = MARGIN) {
  const centerX = ball.x + BALL_SIZE / 2
  const centerY = ball.y + BALL_SIZE / 2
  const left = centerX <= vw / 2 ? ball.x : ball.x + BALL_SIZE - panelW
  const top = centerY <= vh / 2 ? ball.y : ball.y + BALL_SIZE - panelH
  return clampPanelRect(left, top, vw, vh, panelW, panelH, margin)
}

/** 面板位置 → 球锚点（拖面板结束后回写）：球落在面板右下角，再钳制。 */
export function ballFromPanel(rect, vw, vh, panelW, panelH, margin = MARGIN) {
  return clampBallPos(rect.left + panelW - BALL_SIZE, rect.top + panelH - BALL_SIZE, vw, vh, margin)
}
