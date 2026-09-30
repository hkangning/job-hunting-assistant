<script setup>
/**
 * 个人中心（SRS §3.14 / 设计文档 §6.4）：账号信息卡 + 数据概览 + 修改密码 + 求职画像。
 * 入口在顶栏用户菜单，不进侧栏。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload } from '@element-plus/icons-vue'
import { useUserStore } from '../stores/user'
import { changePasswordApi } from '../api/auth'
import { getProfileApi, parseResumeApi, updateProfileApi } from '../api/profile'
import { getOverviewApi } from '../api/overview'
import { APPLICATION_STATUSES } from '../constants/application'
import { compressTo256 } from '../utils/avatar'

const ROLE_LABEL = { ADMIN: '管理员', USER: '普通用户' }

const router = useRouter()
const userStore = useUserStore()

const account = reactive({ nickname: '', email: '' })
const avatarUploading = ref(false)
const savingAccount = ref(false)

const stats = ref(null)
const appStats = ref(null) // 投递五状态计数（概览接口的 application_stats）
const profile = reactive({
  name: '', school: '', major: '', degree: '', gpa: '', english_level: '', experiences: [],
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
  if (!Array.isArray(profile.experiences)) profile.experiences = []
  const overview = await getOverviewApi().catch(() => null)
  stats.value = overview?.stats || null
  appStats.value = overview?.application_stats || null
})

/** 投递进展：非零状态的分段（宽 = 占比）——与投递页统计条同一视觉语言。 */
const appSegments = computed(() => {
  const counts = appStats.value || {}
  const total = Object.values(counts).reduce((sum, n) => sum + (n || 0), 0)
  if (!total) return []
  return APPLICATION_STATUSES.filter((s) => (counts[s.value] || 0) > 0).map((s) => ({
    ...s,
    count: counts[s.value],
    percent: (counts[s.value] / total) * 100
  }))
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

const resumeParsing = ref(false)
const RESUME_EXTS = ['.pdf', '.docx']
const RESUME_MAX_MB = 10

/** 上传简历：解析后**填入表单**（不直接落库），用户核对修改后自行保存。 */
async function onPickResume(uploadFile) {
  const raw = uploadFile?.raw
  if (!raw) return
  const name = (raw.name || '').toLowerCase()
  if (!RESUME_EXTS.some((ext) => name.endsWith(ext))) {
    ElMessage.warning('仅支持 PDF 或 Word（.docx）格式')
    return
  }
  if (raw.size > RESUME_MAX_MB * 1024 * 1024) {
    ElMessage.warning(`文件不能超过 ${RESUME_MAX_MB}MB`)
    return
  }
  resumeParsing.value = true
  try {
    const data = await parseResumeApi(raw)
    if (!data?.extracted) {
      // 契约：未配 Key / 抽取失败时 extracted 为 null——提示手填，不报错
      ElMessage.warning('未能自动解析简历内容，请在下方手动填写')
      return
    }
    const filled = applyResume(data)
    ElMessage.success(`已从简历解析并填入 ${filled} 项，请核对修改后保存`)
  } catch (error) {
    // 只透出可操作的两种：未配 Key 与通用失败——后端 message 在此场景可能误导
    ElMessage.error(
      error?.code === 10012 ? '未配置 AI 密钥，请前往 AI 配置页配置后重试' : '简历解析失败，请稍后重试'
    )
  } finally {
    resumeParsing.value = false
  }
}

/** 经历条目类型（接口文档 v1.36 §3.12）。 */
const EXPERIENCE_TYPES = [
  { value: 'PROJECT', label: '项目' },
  { value: 'INTERNSHIP', label: '实习' },
  { value: 'CAMPUS', label: '校园' }
]
const EXPERIENCE_LIMIT = 10
const experiencesError = ref('')

function addExperience() {
  if (profile.experiences.length >= EXPERIENCE_LIMIT) return
  profile.experiences.push({ type: 'PROJECT', title: '', org: '', role: '', period: '', description: '' })
}

function removeExperience(index) {
  profile.experiences.splice(index, 1)
}

/** 提交前校验并归一：标题必填（契约 strip 后非空），空则定位到该条并拦截；空串字段转 null。 */
function normalizeExperiences() {
  for (const [i, e] of profile.experiences.entries()) {
    if (!e.title?.trim()) {
      experiencesError.value = `第 ${i + 1} 条经历的「名称」不能为空`
      return null
    }
  }
  experiencesError.value = ''
  return profile.experiences.map((e) => ({
    type: e.type || 'PROJECT',
    title: e.title.trim(),
    org: e.org?.trim() || null,
    role: e.role?.trim() || null,
    period: e.period?.trim() || null,
    description: e.description?.trim() || null
  }))
}

/**
 * 解析结果 → 表单：只填「有值」的字段（不动其他项，用户已填的不被空值覆盖）。
 * `extracted` 为 null（LLM 未提取，如未配 Key）时什么都不填，提示手填。
 * 经历条目非空时**整体替换**（简历是经历的完整来源），空则不覆盖。
 */
function applyResume(data) {
  if (!data) return 0
  let filled = 0
  const fill = (key, value) => {
    if (!value) return
    profile[key] = Array.isArray(value) ? value.join(',') : value
    filled += 1
  }
  const extracted = data.extracted || {}
  for (const key of ['name', 'school', 'major', 'degree', 'gpa', 'english_level', 'skills']) {
    fill(key, extracted[key])
  }
  const list = Array.isArray(extracted.experiences) ? extracted.experiences : []
  if (list.length) {
    profile.experiences = list.slice(0, EXPERIENCE_LIMIT).map((e) => ({
      type: EXPERIENCE_TYPES.some((t) => t.value === e?.type) ? e.type : 'PROJECT',
      title: (e?.title || '').slice(0, 100),
      org: (e?.org || '').slice(0, 100),
      role: (e?.role || '').slice(0, 50),
      period: (e?.period || '').slice(0, 50),
      description: (e?.description || '').slice(0, 2000)
    }))
    filled += 1
  }
  return filled
}

async function saveProfile() {
  const experiences = normalizeExperiences()
  if (!experiences) return
  savingProfile.value = true
  try {
    Object.assign(profile, await updateProfileApi({ ...profile, experiences }))
    if (!Array.isArray(profile.experiences)) profile.experiences = []
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
              <el-button :loading="avatarUploading">更换头像</el-button>
            </el-upload>
            <el-button text @click="onResetAvatar">恢复默认</el-button>
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
        <h3 class="profile__title dot-title">数据概览</h3>
        <div class="stats">
          <div class="stats__item" @click="router.push('/applications')">
            <span class="stats__num">{{ stats ? stats.application_count : '—' }}</span>
            <span class="stats__label">投递</span>
          </div>
          <div class="stats__item" @click="router.push('/wrong-questions')">
            <span class="stats__num">{{ stats ? stats.wrong_question_count : '—' }}</span>
            <span class="stats__label">错题</span>
          </div>
          <div class="stats__item" @click="router.push('/interview')">
            <span class="stats__num">{{ stats ? stats.interview_count : '—' }}</span>
            <span class="stats__label">面试</span>
          </div>
        </div>

        <!-- 投递进展：五个状态的分布——比三个总数更有信息量，也让卡片不再空半截 -->
        <div v-if="appSegments.length" class="board">
          <div class="board__head">
            <span class="board__title">投递进展</span>
            <span class="board__total">共 {{ stats?.application_count ?? 0 }} 条</span>
          </div>
          <div class="board__bar">
            <div
              v-for="seg in appSegments"
              :key="seg.value"
              class="board__seg"
              :style="{ width: seg.percent + '%', background: seg.color }"
              :title="`${seg.label} ${seg.count} 条`"
            />
          </div>
          <div class="board__legend">
            <span v-for="seg in appSegments" :key="seg.value" class="board__legend-item">
              <span class="board__dot" :style="{ background: seg.color }" />{{ seg.label }}
              <b>{{ seg.count }}</b>
            </span>
          </div>
        </div>
        <p v-else class="board__empty">还没有投递记录——去投递管理记一笔吧</p>
      </el-card>

      <!-- 修改密码 -->
      <el-card shadow="never" class="profile__card">
        <h3 class="profile__title dot-title">修改密码</h3>
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
      <h3 class="profile__title dot-title">求职画像</h3>

      <!-- 上传简历：解析结果只填入表单，核对修改后由用户自行保存 -->
      <div class="resume">
        <el-upload
          :auto-upload="false"
          :show-file-list="false"
          accept=".pdf,.docx"
          :on-change="onPickResume"
        >
          <el-button type="primary" plain :icon="Upload" :loading="resumeParsing">
            {{ resumeParsing ? '解析中…' : '上传简历' }}
          </el-button>
        </el-upload>
        <div class="resume__text">
          <p class="resume__title">上传简历，自动填充下方画像</p>
          <p class="resume__hint">
            支持 PDF / Word（≤10MB）——解析结果填入表单，核对修改后保存；面试的「项目深挖」环节会依据经历出题
          </p>
        </div>
      </div>

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
        <el-form-item label="经历">
          <div class="exp">
            <p v-if="!profile.experiences.length" class="exp__empty">
              还没有经历条目——上传简历自动解析，或手动添加；面试的「项目深挖」环节会依据经历出题
            </p>
            <div v-for="(exp, i) in profile.experiences" :key="i" class="exp__item">
              <div class="exp__row">
                <el-select v-model="exp.type" style="width: 92px">
                  <el-option v-for="t in EXPERIENCE_TYPES" :key="t.value" :label="t.label" :value="t.value" />
                </el-select>
                <el-input v-model="exp.title" maxlength="100" class="exp__title" placeholder="名称（必填），如：企业管理系统开发" />
                <el-button link type="danger" class="exp__remove" @click="removeExperience(i)">删除</el-button>
              </div>
              <div class="exp__row">
                <el-input v-model="exp.org" maxlength="100" placeholder="公司 / 组织（选填）" />
                <el-input v-model="exp.role" maxlength="50" placeholder="角色（选填）" />
                <el-input v-model="exp.period" maxlength="50" placeholder="时间（选填），如 2026-07 ~ 2026-09" />
              </div>
              <el-input
                v-model="exp.description"
                type="textarea"
                :autosize="{ minRows: 2, maxRows: 5 }"
                maxlength="2000"
                placeholder="做了什么、用到什么（选填）"
              />
            </div>
            <div class="exp__foot">
              <el-button :disabled="profile.experiences.length >= EXPERIENCE_LIMIT" @click="addExperience">
                添加经历
              </el-button>
              <span class="exp__limit">最多 {{ EXPERIENCE_LIMIT }} 条</span>
            </div>
            <p v-if="experiencesError" class="profile__error">{{ experiencesError }}</p>
          </div>
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
  font-size: var(--fs-title);
  font-weight: 700;
  color: var(--c-text);
}
.profile__error {
  margin: 0 0 10px;
  font-size: var(--fs-sm);
  color: var(--el-color-danger);
}
.profile__hint {
  margin-left: 10px;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.profile__form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 18px;
}

/* 经历条目：一张卡片一条，行内分组（身份行 / 组织行 / 描述） */
.exp__empty {
  margin: 0 0 10px;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}
.exp__item {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  margin-bottom: 10px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-control);
}
.exp__row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.exp__title {
  flex: 1;
}
.exp__remove {
  flex: none;
}
.exp__foot {
  display: flex;
  align-items: center;
  gap: 10px;
}
.exp__limit {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

/* 上传简历：画像卡的引导条——低干扰但一眼可见 */
.resume {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 14px;
  margin-bottom: 16px;
  background: var(--c-bg);
  border-radius: var(--r-control);
}
.resume__text {
  flex: 1;
  min-width: 0;
}
.resume__title {
  margin: 0;
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--c-text);
}
.resume__hint {
  margin: 3px 0 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
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
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}
.account__meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--fs-sm);
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
  cursor: pointer;
  transition: background 0.15s;
}
.stats__item:hover {
  background: var(--c-divider);
}
.stats__num {
  font-size: 22px;
  font-weight: 700;
  color: var(--brand);
}
.stats__label {
  font-size: var(--fs-xs);
  color: var(--c-text-2);
}

/* 投递进展：与投递页统计条同一视觉语言（堆叠条 + 圆点图例） */
.board {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--c-divider);
}
.board__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 8px;
}
.board__title {
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}
.board__total {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.board__bar {
  display: flex;
  height: 6px;
  border-radius: var(--r-bar);
  overflow: hidden;
  background: var(--c-divider);
}
.board__seg {
  height: 100%;
  transition: width 0.25s ease;
}
.board__legend {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  margin-top: 8px;
}
.board__legend-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--fs-xs);
  color: var(--c-text-2);
}
.board__legend-item b {
  color: var(--c-text);
}
.board__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex: none;
}
.board__empty {
  margin: 12px 0 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
</style>
