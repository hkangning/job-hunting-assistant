<script setup>
/** 登录页：用户名 + 密码 + 「30 天免登录」（SRS §3.13.2）。错误统一在表单内提示，不弹全局 toast。 */
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Lock, User } from '@element-plus/icons-vue'
import AuthShell from '../components/AuthShell.vue'
import { useUserStore } from '../stores/user'

const router = useRouter()
const userStore = useUserStore()

const form = reactive({ username: '', password: '', remember_me: false })
const loading = ref(false)
const errorMsg = ref('')

async function submit() {
  errorMsg.value = ''
  if (!form.username || !form.password) {
    errorMsg.value = '请输入用户名和密码'
    return
  }

  loading.value = true
  try {
    // remember_me=true 签发 30 天 Token，false 为 1 天（接口文档 §3.2）
    await userStore.login({ ...form }, { silent: true })
    router.replace('/')
  } catch (err) {
    // 80004 统一文案（不区分账号不存在与密码错误）；80005 携带剩余锁定时间
    errorMsg.value = err.message || '登录失败，请稍后重试'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <AuthShell>
    <template #title>登录你的求职工作台</template>

    <el-form :model="form" @submit.prevent="submit">
      <el-form-item>
        <el-input v-model="form.username" size="large" placeholder="用户名" :prefix-icon="User" />
      </el-form-item>
      <el-form-item>
        <el-input
          v-model="form.password"
          type="password"
          size="large"
          placeholder="密码"
          show-password
          :prefix-icon="Lock"
          @keyup.enter="submit"
        />
      </el-form-item>

      <div class="login__row">
        <el-checkbox v-model="form.remember_me">30 天免登录</el-checkbox>
      </div>

      <p v-if="errorMsg" class="login__error">{{ errorMsg }}</p>

      <el-button
        type="primary"
        size="large"
        class="login__submit"
        :loading="loading"
        @click="submit"
        >登 录</el-button
      >
    </el-form>

    <p class="login__switch">还没有账号？<router-link to="/register">立即注册</router-link></p>
  </AuthShell>
</template>

<style scoped>
.login__row {
  margin: 2px 0 14px;
}
.login__error {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--el-color-danger);
  line-height: 1.5;
}
.login__submit {
  width: 100%;
}
.login__switch {
  margin: 18px 0 0;
  text-align: center;
  font-size: 12px;
  color: var(--c-text-2);
}
.login__switch a {
  color: var(--brand);
  text-decoration: none;
  font-weight: 700;
}
</style>
