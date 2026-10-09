<script setup>
/**
 * 新手指引（步骤 28，FR-019）：driver.js 封装。
 * 挂载在触发页（概览「自动启动」/ 个人中心「重看」）上，由页面 ref.start() 启动；
 * 页面卸载（跳走）即编程销毁 —— driver.js 的编程 destroy()（内部 v(false)）不触发
 * onDestroyStarted，用户交互关闭（完成 / X / ESC / 点遮罩，v(true)）才触发 ——
 * 因此「中断不写 guide_done、主动关闭才写」由该机理保证（勿改成手动标志位）。
 */
import { onUnmounted } from 'vue'
import { driver } from 'driver.js'
import 'driver.js/dist/driver.css'
import { TOUR_STEPS, filterAvailableSteps } from '../utils/guide'
import { updateSettingsApi } from '../api/settings'

const props = defineProps({
  /** 完成/跳过后是否写 guide_done；个人中心「重看」传 false（重播不回写，TC-68） */
  writeBack: { type: Boolean, default: true }
})

/** driver.js 实例（start 前先销毁旧实例，防重看连点叠两层） */
let tour = null

/** 写标记：静默——失败仅 console.warn（下次进首页可能重弹，不打扰用户） */
function markGuideDone() {
  if (!props.writeBack) return
  updateSettingsApi({ guide_done: true }).catch((e) =>
    console.warn('[guide] 标记写入失败：', e?.message)
  )
}

/** 用户主动结束的统一处理：onDestroyStarted（完成/X/ESC/点遮罩）与「跳过」按钮都走这里 */
function finishTour() {
  markGuideDone()
  tour?.destroy() // 编程销毁：不再触发 onDestroyStarted，直接完成
}

function start() {
  const steps = filterAvailableSteps(TOUR_STEPS)
  if (!steps.length) return // 锚点全缺失：不启动（防御，正常布局下不会发生）
  tour?.destroy()
  tour = driver({
    steps,
    skipMissingElement: true, // 运行中元素被移除时自动跳到下一个可用步骤（启动前已过滤，这是双保险）
    showProgress: true,
    progressText: '第 {{current}} / {{total}} 步',
    nextBtnText: '下一步',
    prevBtnText: '上一步',
    doneBtnText: '完成',
    closeBtnLabel: '跳过', // X 按钮的无障碍标签
    onPopoverRender: (popover) => {
      // driver.js 无内置「跳过」按钮：注入一个（TC-68「每步可跳过」）
      const skip = document.createElement('button')
      skip.type = 'button'
      skip.textContent = '跳过'
      skip.className = 'driver-popover-footer-btn guide-tour-skip'
      skip.addEventListener('click', finishTour)
      popover.footerButtons.prepend(skip)
    },
    onDestroyStarted: () => finishTour()
  })
  tour.drive()
}

onUnmounted(() => tour?.destroy()) // 跳走/卸载 = 中断：不写标记

defineExpose({ start })
</script>

<template><!-- 无渲染输出：引导由 driver.js 命令式驱动 --></template>
