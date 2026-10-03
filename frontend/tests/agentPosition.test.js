import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  BALL_SIZE,
  ballFromPanel,
  clampBallPos,
  clampPanelRect,
  panelRectFromBall
} from '../src/utils/agentPosition.js'

const VW = 1440
const VH = 900
const PANEL_W = 400
const PANEL_H = 620

test('clampBallPos：越界钳到边距内，界内原样返回', () => {
  assert.deepEqual(clampBallPos(-50, -50, VW, VH), { x: 8, y: 8 })
  assert.deepEqual(clampBallPos(9999, 9999, VW, VH), { x: VW - BALL_SIZE - 8, y: VH - BALL_SIZE - 8 })
  assert.deepEqual(clampBallPos(100, 200, VW, VH), { x: 100, y: 200 })
})

test('panelRectFromBall：球在右下角 → 面板从球的左上展开（与现行右下角浮窗视觉一致）', () => {
  const ball = clampBallPos(9999, 9999, VW, VH)
  const r = panelRectFromBall(ball, VW, VH, PANEL_W, PANEL_H)
  assert.equal(r.left, ball.x + BALL_SIZE - PANEL_W)
  assert.equal(r.top, ball.y + BALL_SIZE - PANEL_H)
})

test('panelRectFromBall：球在左上角 → 面板向右下展开、贴边不出界', () => {
  const r = panelRectFromBall({ x: 8, y: 8 }, VW, VH, PANEL_W, PANEL_H)
  assert.equal(r.left, 8)
  assert.equal(r.top, 8)
})

test('panelRectFromBall：球在右上角 → 面板右对齐、向下展开', () => {
  const ball = clampBallPos(9999, 0, VW, VH)
  const r = panelRectFromBall(ball, VW, VH, PANEL_W, PANEL_H)
  assert.equal(r.left, VW - 8 - PANEL_W)
  assert.equal(r.top, 8)
})

test('panelRectFromBall：视口小于面板 → 仍钳在边距内（不产生负坐标）', () => {
  const r = panelRectFromBall({ x: 8, y: 8 }, 420, 300, PANEL_W, 260)
  assert.ok(r.left >= 8 && r.top >= 8)
})

test('clampPanelRect：拖出视口被钳回，界内原样', () => {
  assert.deepEqual(clampPanelRect(-100, -100, VW, VH, PANEL_W, PANEL_H), { left: 8, top: 8 })
  assert.deepEqual(clampPanelRect(9999, 9999, VW, VH, PANEL_W, PANEL_H), {
    left: VW - PANEL_W - 8,
    top: VH - PANEL_H - 8
  })
  assert.deepEqual(clampPanelRect(200, 150, VW, VH, PANEL_W, PANEL_H), { left: 200, top: 150 })
})

test('ballFromPanel：面板位置换算回球锚点（取面板右下角）并钳制', () => {
  const ball = ballFromPanel({ left: 100, top: 100 }, VW, VH, PANEL_W, PANEL_H)
  assert.deepEqual(ball, clampBallPos(100 + PANEL_W - BALL_SIZE, 100 + PANEL_H - BALL_SIZE, VW, VH))
  // 极端值（面板在左上原点）也不出界
  const edge = ballFromPanel({ left: -500, top: -500 }, VW, VH, PANEL_W, PANEL_H)
  assert.ok(edge.x >= 8 && edge.y >= 8)
})
