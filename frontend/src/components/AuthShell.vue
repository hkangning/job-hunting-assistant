<script setup>
/** 账号页外壳：深紫渐变全屏背景 + 居中白卡片（登录 / 注册共用，背景与入场动画同色系）。 */
</script>

<template>
  <div class="auth">
    <div class="auth__card">
      <div class="auth__brand">
        <span class="auth__mark">求</span>
        <span class="auth__name">个人求职助手</span>
      </div>
      <h1 class="auth__title"><slot name="title" /></h1>
      <slot />
    </div>
  </div>
</template>

<style scoped>
.auth {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100vw;
  height: 100vh;
  background: radial-gradient(120% 120% at 50% 40%, #5a4a93 0%, #3b3168 45%, #241f45 100%);
}

.auth__card {
  width: 380px;
  padding: 30px 32px 24px;
  background: var(--c-card);
  border-radius: var(--r-card);
  /* 卡片在深色背景上浮起——阴影只用于真正需要"浮起"的元素（设计文档 §4.5.4） */
  box-shadow: 0 18px 48px rgba(20, 14, 45, 0.32);
}

.auth__brand {
  display: flex;
  align-items: center;
  gap: 8px;
}
.auth__mark {
  width: 24px;
  height: 24px;
  border-radius: var(--r-control);
  background: var(--brand);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}
.auth__name {
  font-size: 13px;
  font-weight: 700;
  color: var(--brand);
  letter-spacing: 0.3px;
}

.auth__title {
  margin: 18px 0 20px;
  font-size: 19px;
  font-weight: 700;
  color: var(--c-text);
}
</style>
