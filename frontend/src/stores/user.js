/** 当前账号状态（系统设计 §4.2）：Token 持久化 + 用户信息 + 登录登出动作。 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { useAppStore } from './app'
import { useOverviewStore } from './overview'
import {
  loginApi, registerApi, meApi, updateAccountApi,
  uploadAvatarApi, resetAvatarApi
} from '../api/auth'
import { avatarUrl, defaultAvatar } from '../utils/avatar'

// 与路由守卫共用同一 key（守卫读 localStorage 以避免「路由 ↔ store」循环依赖）
const TOKEN_KEY = 'jobpilot_token'

export const useUserStore = defineStore('user', () => {
  const token = ref(localStorage.getItem(TOKEN_KEY) || '')
  const user = ref(null)

  const isLoggedIn = computed(() => !!token.value)
  const displayName = computed(() => user.value?.nickname || user.value?.username || '')
  const avatarImg = computed(() => (user.value?.avatar ? avatarUrl(user.value.avatar) : null))
  const fallbackAvatar = computed(() => defaultAvatar(displayName.value || '?'))

  function setToken(value) {
    token.value = value || ''
    if (value) localStorage.setItem(TOKEN_KEY, value)
    else localStorage.removeItem(TOKEN_KEY)
  }

  function applyAuth(data) {
    setToken(data.token)
    user.value = data.user
  }

  // config 透传 silent：登录/注册页自行在表单内展示错误，不要全局 toast（接口文档 1.3 前端动作）
  async function login(payload, config) {
    applyAuth(await loginApi(payload, config))
  }

  async function register(payload, config) {
    applyAuth(await registerApi(payload, config))
  }

  /** 拉取当前账号信息；silent 供 /welcome 预检使用（失败不弹错、不触发全局跳转） */
  async function fetchMe(config = {}) {
    user.value = await meApi(config)
    return user.value
  }

  async function updateAccount(payload) {
    user.value = await updateAccountApi(payload)
  }

  async function uploadAvatar(file) {
    const data = await uploadAvatarApi(file)
    if (user.value) user.value.avatar = data.avatar
  }

  async function resetAvatar() {
    await resetAvatarApi()
    if (user.value) user.value.avatar = null
  }

  /** 仅清本 store（供 401 拦截器使用；跳转由拦截器统一控制，避免 store 反向依赖 router） */
  function reset() {
    setToken('')
    user.value = null
  }

  /** 退出登录：清 Token + 重置其余 store（TC-66 账号切换无数据残留） */
  function logout() {
    reset()
    useAppStore().$reset()
    useOverviewStore().reset() // 概览数据同样按账号隔离，不得残留上一账号的统计
  }

  return {
    token, user, isLoggedIn, displayName, avatarImg, fallbackAvatar,
    login, register, fetchMe, updateAccount, uploadAvatar, resetAvatar, reset, logout
  }
})
