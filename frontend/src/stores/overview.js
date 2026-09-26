/**
 * 概览数据（系统设计 §4.2）。
 * 概览页与侧栏「今日待办」读同一份——两处各调一次会在同一屏发两个相同请求，且数值可能不一致。
 */
import { defineStore } from 'pinia'
import { getOverviewApi } from '../api/overview'

export const useOverviewStore = defineStore('overview', {
  state: () => ({
    data: null,
    loading: false,
    error: ''
  }),
  actions: {
    /** silent=true 用于 30s 轮询：不触发 loading，避免页面每隔半分钟闪一次 */
    async fetch(silent = false) {
      if (!silent) this.loading = true
      try {
        // 请求带 silent：概览是页面主体，失败由页面自己显示错误态 + 重试，不再叠一层全局 toast
        this.data = await getOverviewApi({ silent: true })
        this.error = ''
      } catch (err) {
        this.error = err.message || '概览加载失败'
      } finally {
        if (!silent) this.loading = false
      }
    },
    reset() {
      this.data = null
      this.loading = false
      this.error = ''
    }
  }
})
