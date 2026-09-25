/** 全局设置与提示（最小版，步骤 8/9 扩充）。用 options 写法以获得 $reset。 */
import { defineStore } from 'pinia'

export const useAppStore = defineStore('app', {
  state: () => ({
    settings: {}
  }),
  actions: {
    setSettings(value) {
      this.settings = value || {}
    }
  }
})
