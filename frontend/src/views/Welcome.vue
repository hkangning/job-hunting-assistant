<script>
/**
 * 会话内只播一次的内存标记（设计文档 §4.6 + TC-62）：SPA 内跳转不重播；刷新 /welcome
 * 或重新打开时重播（页面重新加载 → 模块重新求值）。
 *
 * 必须放在普通 <script> 块：<script setup> 的顶层代码属于 setup() 函数体，
 * 每次组件实例化都会执行一遍，写在那里等于"每次进页面都重置"，标记形同虚设。
 */
let played = false
</script>

<script setup>
/**
 * 入场动画页（系统设计 §4.6）：未登录用户的第一印象页，兼作登录态预检窗口。
 * 纯 CSS @keyframes 实现，不引第三方动画库；约 1.8s（含末段 0.4s 淡出），可点击/按键跳过。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../stores/user'

const router = useRouter()
const userStore = useUserStore()

// 时长参数：TOTAL_MS 为「进入到跳转」的总时长（进度条与它同长）；
// 末段 LEAVE_MS 是整体淡出，故动画计时器提前 TOTAL_MS - LEAVE_MS 收尾。
const TOTAL_MS = 1800
const LEAVE_MS = 400

const titleChars = [...'个人求职助手']
const leaving = ref(false)
let timer = null
let target = '/login'

function finish() {
  leaving.value = true // 触发整体淡出（.welcome--leaving 的 transition）
  timer = setTimeout(() => router.replace(target), LEAVE_MS)
}

function skip() {
  clearTimeout(timer)
  router.replace(target)
}

function onKeydown(event) {
  if (event.key !== 'Tab') skip() // 任意键跳过（Tab 除外，避免与焦点导航打架）
}

onMounted(() => {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches

  if (reduced || played) {
    skip() // 无障碍降级 / 本会话已播过：不播动画直接跳转
  } else {
    played = true
    timer = setTimeout(finish, TOTAL_MS - LEAVE_MS)
  }

  // 登录态预检与动画并行，不阻塞播放；失败时拦截器已清 Token（silent 不跳转），这里只改目标
  if (userStore.token) {
    userStore
      .fetchMe({ silent: true })
      .then(() => {
        target = '/'
      })
      .catch(() => {
        target = '/login'
      })
  }

  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  clearTimeout(timer)
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div
    class="welcome"
    :class="{ 'welcome--leaving': leaving }"
    :style="{ '--welcome-duration': TOTAL_MS + 'ms' }"
    @click="skip"
  >
    <div class="welcome__inner">
      <svg class="welcome__logo" viewBox="0 0 96 96" fill="none" aria-hidden="true">
        <!-- 靶心：命中目标 -->
        <circle cx="70" cy="30" r="14" stroke="rgba(255,255,255,.42)" stroke-width="3" />
        <circle cx="70" cy="30" r="5" fill="rgba(255,255,255,.9)" />
        <!-- 上升折线：求职进展 -->
        <path
          d="M12 76 L34 54 L48 64 L72 34"
          stroke="#fff"
          stroke-width="4.5"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>

      <h1 class="welcome__title">
        <span
          v-for="(char, index) in titleChars"
          :key="index"
          class="welcome__char"
          :style="{ animationDelay: 400 + index * 60 + 'ms' }"
          >{{ char }}</span
        >
      </h1>

      <p class="welcome__subtitle">AI 驱动的求职全流程工作台</p>

      <div class="welcome__progress"><i class="welcome__progress-bar"></i></div>
    </div>

    <p class="welcome__hint">点击任意处跳过</p>
  </div>
</template>

<style scoped>
.welcome {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  cursor: pointer;
  /* 品牌紫深色渐变，中央聚焦（设计文档 §4.6） */
  background:
    radial-gradient(120% 120% at 50% 42%, #5a4a93 0%, #3b3168 45%, #241f45 100%);
  animation: welcomeIn 0.4s ease-out both;
  transition: opacity 0.4s ease;
}
.welcome--leaving {
  opacity: 0;
}

.welcome__inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  transform: translateY(-4vh);
}

.welcome__logo {
  width: 96px;
  height: 96px;
  animation: logoIn 0.4s ease-out both;
}

.welcome__title {
  margin: 22px 0 0;
  font-size: 28px;
  font-weight: 700;
  letter-spacing: 3px;
  color: #fff;
}
.welcome__char {
  display: inline-block;
  opacity: 0;
  animation: charIn 0.35s ease-out both;
}

.welcome__subtitle {
  margin: 12px 0 0;
  font-size: 14px;
  letter-spacing: 1px;
  color: rgba(255, 255, 255, 0.72);
  opacity: 0;
  animation: fadeIn 0.35s ease-out 1000ms both;
}

.welcome__progress {
  width: 164px;
  height: 3px;
  margin-top: 26px;
  border-radius: var(--r-bar);
  background: rgba(255, 255, 255, 0.18);
  overflow: hidden;
}
.welcome__progress-bar {
  display: block;
  width: 100%;
  height: 100%;
  background: rgba(255, 255, 255, 0.9);
  transform-origin: left center;
  transform: scaleX(0);
  animation: grow var(--welcome-duration, 1.8s) linear both;
}

.welcome__hint {
  position: absolute;
  bottom: 40px;
  margin: 0;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.5);
  opacity: 0;
  animation: fadeIn 0.35s ease-out 1000ms both;
}

@keyframes welcomeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
@keyframes logoIn {
  from {
    opacity: 0;
    transform: scale(0.8);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}
@keyframes charIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
@keyframes fadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
@keyframes grow {
  from {
    transform: scaleX(0);
  }
  to {
    transform: scaleX(1);
  }
}
</style>
