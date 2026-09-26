<script setup>
/**
 * 注册页（SRS §3.13.1）。密码强度只提示、不拦截提交；用户名重复由后端 80003 回传后标红。
 * 注册成功即自动登录（后端直接返回 Token），进首页。
 */
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import AuthShell from '../components/AuthShell.vue'
import { useUserStore } from '../stores/user'

const USERNAME_RE = /^[A-Za-z0-9_]{3,20}$/
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

const router = useRouter()
const userStore = useUserStore()

const form = reactive({ username: '', password: '', confirm: '', nickname: '', email: '' })
const loading = ref(false)
const errorMsg = ref('')
const usernameError = ref('')
const passwordError = ref('')

const STRENGTH_LABEL = [
  { text: '至少 6 位', color: 'var(--el-color-danger)' },
  { text: '弱', color: 'var(--s-interview)' },
  { text: '中', color: 'var(--s-applied)' },
  { text: '强', color: 'var(--s-offer)' },
  { text: '很强', color: 'var(--s-offer)' }
]

/** 强度仅为提示（SRS 明确「页面给出强度提示但不拦截提交」）——长度达标即至少 1 分。 */
const strength = computed(() => {
  const pwd = form.password || ''
  if (!pwd) return null
  if (pwd.length < 6) return { level: 0, ...STRENGTH_LABEL[0] }

  let score = 1
  if (/[a-z]/.test(pwd) && /[A-Z]/.test(pwd)) score += 1
  if (/\d/.test(pwd)) score += 1
  if (/[^A-Za-z0-9]/.test(pwd)) score += 1
  return { level: score, ...STRENGTH_LABEL[score] }
})

async function submit() {
  errorMsg.value = ''
  usernameError.value = ''
  passwordError.value = ''

  // 格式与一致性校验：这些是"填错了"，拦截提交；强度不在此列
  if (!USERNAME_RE.test(form.username)) {
    usernameError.value = '用户名需为 3~20 位字母、数字或下划线'
    return
  }
  if (form.password.length < 6) {
    passwordError.value = '密码不能少于 6 位'
    return
  }
  if (form.password !== form.confirm) {
    errorMsg.value = '两次输入的密码不一致'
    return
  }
  if (form.email && !EMAIL_RE.test(form.email)) {
    errorMsg.value = '邮箱格式不正确'
    return
  }

  loading.value = true
  try {
    const payload = { username: form.username, password: form.password }
    if (form.nickname) payload.nickname = form.nickname
    if (form.email) payload.email = form.email
    await userStore.register(payload, { silent: true })
    router.replace('/')
  } catch (err) {
    if (err.code === 80003) usernameError.value = err.message
    else if (err.code === 80006) passwordError.value = err.message
    else errorMsg.value = err.message || '注册失败，请稍后重试'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <AuthShell>
    <template #title>创建你的账号</template>

    <el-form :model="form" @submit.prevent="submit">
      <el-form-item :error="usernameError">
        <el-input v-model="form.username" size="large" placeholder="用户名（3~20 位字母/数字/下划线）" />
      </el-form-item>

      <el-form-item :error="passwordError">
        <el-input v-model="form.password" type="password" size="large" placeholder="密码（至少 6 位）" show-password />
      </el-form-item>

      <div v-if="strength" class="reg__strength">
        <i
          v-for="seg in 4"
          :key="seg"
          class="reg__seg"
          :style="{ background: seg <= strength.level ? strength.color : 'var(--c-divider)' }"
        ></i>
        <span class="reg__strength-text" :style="{ color: strength.color }">{{ strength.text }}</span>
      </div>

      <el-form-item>
        <el-input
          v-model="form.confirm"
          type="password"
          size="large"
          placeholder="确认密码"
          show-password
          @keyup.enter="submit"
        />
      </el-form-item>

      <el-form-item>
        <el-input v-model="form.nickname" size="large" placeholder="昵称（选填，默认取用户名）" />
      </el-form-item>

      <el-form-item>
        <el-input v-model="form.email" size="large" placeholder="邮箱（选填）" @keyup.enter="submit" />
      </el-form-item>

      <p v-if="errorMsg" class="reg__error">{{ errorMsg }}</p>

      <el-button type="primary" size="large" class="reg__submit" :loading="loading" @click="submit">
        注册并登录
      </el-button>
    </el-form>

    <p class="reg__switch">已有账号？<router-link to="/login">去登录</router-link></p>
  </AuthShell>
</template>

<style scoped>
.reg__strength {
  display: flex;
  align-items: center;
  gap: 5px;
  margin: -8px 0 16px;
}
.reg__seg {
  width: 34px;
  height: 4px;
  border-radius: var(--r-bar);
  transition: background 0.2s ease;
}
.reg__strength-text {
  margin-left: 4px;
  font-size: var(--fs-xs);
}
.reg__error {
  margin: 0 0 12px;
  font-size: var(--fs-sm);
  color: var(--el-color-danger);
  line-height: 1.5;
}
.reg__submit {
  width: 100%;
}
.reg__switch {
  margin: 18px 0 0;
  text-align: center;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}
.reg__switch a {
  color: var(--brand);
  text-decoration: none;
  font-weight: 700;
}
</style>
