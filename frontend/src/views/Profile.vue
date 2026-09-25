<script setup>
/**
 * 个人中心（SRS §3.14 / 设计文档 §6.4）：账号信息卡 + 数据概览 + 修改密码 + 求职画像。
 * 入口在顶栏用户菜单，不进侧栏。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '../stores/user'
import { changePasswordApi } from '../api/auth'
import { getProfileApi, updateProfileApi } from '../api/profile'
import { getOverviewApi } from '../api/overview'
import { compressTo256 } from '../utils/avatar'

const ROLE_LABEL = { ADMIN: '管理员', USER: '普通用户' }

const router = useRouter()
const userStore = useUserStore()

const account = reactive({ nickname: '', email: '' })
const avatarUploading = ref(false)
const savingAccount = ref(false)

const stats = ref(null)
const profile = reactive({
  name: '', school: '', major: '', degree: '', gpa: '', english_level: '', resume_text: '',
  target_position: '', target_city: '', skills: '', weaknesses: '', note: ''
})
const savingProfile = ref(false)

const pwd = reactive({ old_password: '', new_password: '', confirm: '' })
const pwdError = ref('')
const savingPwd = ref(false)

const roleLabel = computed(() => ROLE_LABEL[userStore.user?.role] || '—')

function syncAccountForm() {
  account.nickname = userStore.user?.nickname || ''
  account.email = userStore.user?.email || ''
}

onMounted(async () => {
  // user 可能为空（直接刷新本页）：先拉一次，再回填表单项
  if (!userStore.user) await userStore.fetchMe({ silent: true }).catch(() => {})
  syncAccountForm()

  Object.assign(profile, await getProfileApi().catch(() => ({})))
  const overview = await getOverviewApi().catch(() => null)
  stats.value = overview?.stats || null
})

// ---------- 账号信息 ----------

async function saveAccount() {
  savingAccount.value = true
  try {
    await userStore.updateAccount({ nickname: account.nickname, email: account.email })
    ElMessage.success('资料已更新')
  } finally {
    savingAccount.value = false
  }
}

async function onPickAvatar(uploadFile) {
  const raw = uploadFile?.raw
  if (!raw) return
  avatarUploading.value = true
  try {
    // 前端先压成 256×256 再上传（后端仍会校验类型与体积）
    const blob = await compressTo256(raw)
    await userStore.uploadAvatar(blob)
    ElMessage.success('头像已更新')
  } catch (err) {
    ElMessage.error(err.message || '头像上传失败')
  } finally {
    avatarUploading.value = false
  }
}

async function onResetAvatar() {
  if (!userStore.user?.avatar) {
    ElMessage.info('当前已是默认头像')
    return
  }
  try {
    await ElMessageBox.confirm('恢复默认头像？当前自定义头像将被删除。', '提示', {
      type: 'warning',
      confirmButtonText: '恢复默认',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  await userStore.resetAvatar()
  ElMessage.success('已恢复默认头像')
}

// ---------- 修改密码 ----------

async function savePassword() {
  pwdError.value = ''
  if (!pwd.old_password) {
    pwdError.value = '请输入原密码'
    return
  }
  if (pwd.new_password.length < 6) {
    pwdError.value = '新密码不能少于 6 位'
    return
  }
  if (pwd.new_password !== pwd.confirm) {
    pwdError.value = '两次输入的新密码不一致'
    return
  }

  savingPwd.value = true
  try {
    await changePasswordApi(
      { old_password: pwd.old_password, new_password: pwd.new_password },
      { silent: true }
    )
    // 改密后当前 Token 立即失效（含 30 天免登录的旧 Token）→ 清状态回登录页
    userStore.reset()
    ElMessage.success('密码已修改，请重新登录')
    router.replace('/login')
  } catch (err) {
    pwdError.value = err.message || '修改失败，请稍后重试'
  } finally {
    savingPwd.value = false
  }
}

// ---------- 求职画像 ----------

async function saveProfile() {
  savingProfile.value = true
  try {
    Object.assign(profile, await updateProfileApi({ ...profile }))
    ElMessage.success('求职画像已保存')
  } finally {
    savingProfile.value = false
  }
}
</script>

<template>
  <div class="profile">
    <!-- 账号信息 -->
    <el-card shadow="never" class="profile__card">
      <div class="account">
        <div class="account__avatar">
          <img v-if="userStore.avatarImg" :src="userStore.avatarImg" alt="头像" />
          <span
            v-else
            class="account__avatar-fallback"
            :style="{ background: userStore.fallbackAvatar.color }"
            >{{ userStore.fallbackAvatar.text }}</span
          >
          <div class="account__avatar-actions">
            <el-upload
              :auto-upload="false"
              :show-file-list="false"
              accept="image/png,image/jpeg,image/webp"
              :on-change="onPickAvatar"
            >
              <el-button size="small" :loading="avatarUploading">更换头像</el-button>
            </el-upload>
            <el-button size="small" text @click="onResetAvatar">恢复默认</el-button>
          </div>
        </div>

        <div class="account__fields">
          <div class="account__row">
            <span class="account__label">昵称</span>
            <el-input v-model="account.nickname" placeholder="昵称" />
            <span class="account__label">角色</span>
            <el-tag size="small" type="info" effect="plain">{{ roleLabel }}</el-tag>
          </div>
          <div class="account__row">
            <span class="account__label">邮箱</span>
            <el-input v-model="account.email" placeholder="选填" />
          </div>
          <div class="account__meta">
            <span>用户名 <b>{{ userStore.user?.username }}</b>（注册后不可修改）</span>
            <span>注册于 {{ userStore.user?.created_at || '—' }}</span>
            <span>上次登录 {{ userStore.user?.last_login_at || '—' }}</span>
          </div>
          <div>
            <el-button type="primary" :loading="savingAccount" @click="saveAccount">保存修改</el-button>
          </div>
        </div>
      </div>
    </el-card>

    <div class="profile__grid">
      <!-- 数据概览 -->
      <el-card shadow="never" class="profile__card">
        <h3 class="profile__title">数据概览</h3>
        <div class="stats">
          <div class="stats__item">
            <span class="stats__num">{{ stats ? stats.application_count : '—' }}</span>
            <span class="stats__label">投递</span>
          </div>
          <div class="stats__item">
            <span class="stats__num">{{ stats ? stats.wrong_question_count : '—' }}</span>
            <span class="stats__label">错题</span>
          </div>
          <div class="stats__item">
            <span class="stats__num">{{ stats ? stats.interview_count : '—' }}</span>
            <span class="stats__label">面试</span>
          </div>
        </div>
      </el-card>

      <!-- 修改密码 -->
      <el-card shadow="never" class="profile__card">
        <h3 class="profile__title">修改密码</h3>
        <el-form :model="pwd" label-width="82px" @submit.prevent="savePassword">
          <el-form-item label="原密码">
            <el-input v-model="pwd.old_password" type="password" show-password placeholder="当前密码" />
          </el-form-item>
          <el-form-item label="新密码">
            <el-input v-model="pwd.new_password" type="password" show-password placeholder="至少 6 位" />
          </el-form-item>
          <el-form-item label="确认密码">
            <el-input
              v-model="pwd.confirm"
              type="password"
              show-password
              placeholder="再次输入新密码"
              @keyup.enter="savePassword"
            />
          </el-form-item>
          <p v-if="pwdError" class="profile__error">{{ pwdError }}</p>
          <el-button type="primary" :loading="savingPwd" @click="savePassword">修改密码</el-button>
          <span class="profile__hint">修改成功后需重新登录</span>
        </el-form>
      </el-card>
    </div>

    <!-- 求职画像 -->
    <el-card shadow="never" class="profile__card">
      <h3 class="profile__title">求职画像</h3>
      <el-form :model="profile" label-width="82px" @submit.prevent="saveProfile">
        <div class="profile__form-grid">
          <el-form-item label="姓名"><el-input v-model="profile.name" /></el-form-item>
          <el-form-item label="学校"><el-input v-model="profile.school" /></el-form-item>
          <el-form-item label="专业"><el-input v-model="profile.major" /></el-form-item>
          <el-form-item label="学历">
            <el-select v-model="profile.degree" placeholder="请选择" clearable>
              <el-option label="本科" value="本科" />
              <el-option label="硕士" value="硕士" />
            </el-select>
          </el-form-item>
          <el-form-item label="GPA"><el-input v-model="profile.gpa" placeholder="如 3.6/4.0" /></el-form-item>
          <el-form-item label="英语水平">
            <el-input v-model="profile.english_level" placeholder="如 CET-6 441" />
          </el-form-item>
          <el-form-item label="目标岗位"><el-input v-model="profile.target_position" /></el-form-item>
          <el-form-item label="目标城市"><el-input v-model="profile.target_city" /></el-form-item>
        </div>

        <el-form-item label="技能栈">
          <el-input v-model="profile.skills" placeholder="逗号分隔，如 Java,Spring Boot,Redis" />
        </el-form-item>
        <el-form-item label="弱项">
          <el-input v-model="profile.weaknesses" placeholder="逗号分隔" />
        </el-form-item>
        <el-form-item label="简历全文">
          <el-input v-model="profile.resume_text" type="textarea" :rows="5" placeholder="JD 匹配分析的核心输入" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="profile.note" type="textarea" :rows="2" />
        </el-form-item>

        <el-button type="primary" :loading="savingProfile" @click="saveProfile">保存画像</el-button>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.profile {
  display: flex;
  flex-direction: column;
  gap: var(--card-gap);
}
.profile__card {
  border-radius: var(--r-card);
  border-color: var(--c-border);
}
.profile__grid {
  display: grid;
  grid-template-columns: minmax(280px, 1fr) minmax(360px, 1.4fr);
  gap: var(--card-gap);
}
.profile__title {
  margin: 0 0 14px;
  font-size: 13px;
  font-weight: 700;
  color: var(--c-text);
}
.profile__error {
  margin: 0 0 10px;
  font-size: 12px;
  color: var(--el-color-danger);
}
.profile__hint {
  margin-left: 10px;
  font-size: 11.5px;
  color: var(--c-text-3);
}
.profile__form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 18px;
}

/* 账号信息卡 */
.account {
  display: flex;
  gap: 22px;
}
.account__avatar {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.account__avatar img,
.account__avatar-fallback {
  width: 128px;
  height: 128px;
  border-radius: 50%;
  object-fit: cover;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 44px;
  font-weight: 700;
  color: #fff;
}
.account__avatar-actions {
  display: flex;
  align-items: center;
  gap: 2px;
}
.account__fields {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.account__row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.account__row :deep(.el-input) {
  max-width: 220px;
}
.account__label {
  width: 44px;
  flex-shrink: 0;
  font-size: 12.5px;
  color: var(--c-text-2);
}
.account__meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--c-text-3);
}
.account__meta b {
  color: var(--c-text-2);
}

/* 数据概览 */
.stats {
  display: flex;
  gap: 12px;
}
.stats__item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 12px 0;
  background: var(--c-bg);
  border-radius: var(--r-control);
}
.stats__num {
  font-size: 22px;
  font-weight: 700;
  color: var(--brand);
}
.stats__label {
  font-size: 11.5px;
  color: var(--c-text-2);
}
</style>
