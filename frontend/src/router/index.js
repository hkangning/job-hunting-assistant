import { createRouter, createWebHistory } from 'vue-router'

// meta 约定：
//   title      顶栏标题 + 菜单文案
//   group      菜单分组名（侧栏按此分组渲染，保持声明顺序）
//   color      模块色（CSS 变量名，用于侧栏色点与该模块强调元素）
//   hidden     true 时不进菜单
//   activeMenu 高亮指向的菜单 path
//   layout     'blank' 时走全屏壳（无侧栏无顶栏），用于账号页
const routes = [
  // ---------- 账号页（全屏壳，免登录） ----------
  {
    path: '/welcome',
    name: 'Welcome',
    component: () => import('../views/Welcome.vue'),
    meta: { title: '欢迎', layout: 'blank', hidden: true }
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/Login.vue'),
    meta: { title: '登录', layout: 'blank', hidden: true }
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('../views/Register.vue'),
    meta: { title: '注册', layout: 'blank', hidden: true }
  },
  // ---------- 账号与配置页（用户菜单入口，不进侧栏） ----------
  {
    path: '/profile',
    name: 'Profile',
    component: () => import('../views/Profile.vue'),
    meta: { title: '个人中心', hidden: true }
  },
  {
    path: '/ai-config',
    name: 'AiConfig',
    component: () => import('../views/AiConfig.vue'),
    meta: { title: 'AI 配置', hidden: true }
  },

  // ---------- 业务页（默认壳） ----------
  {
    path: '/',
    name: 'Overview',
    component: () => import('../views/Overview.vue'),
    meta: { title: '今日概览', group: '求职流程', color: 'var(--brand)' }
  },
  {
    // 位置依系统设计 §4.4 的菜单分组：求职流程组、概览之后、投递之前（找机会 → 记录进度）
    path: '/campus',
    name: 'Campus',
    component: () => import('../views/Campus.vue'),
    meta: { title: '校招情报', group: '求职流程', color: 'var(--m-campus)' }
  },
  {
    path: '/applications',
    name: 'Applications',
    component: () => import('../views/Applications.vue'),
    meta: { title: '投递管理', group: '求职流程', color: 'var(--m-application)' }
  },
  {
    path: '/jd-analysis',
    name: 'JdAnalysis',
    component: () => import('../views/JdAnalysis.vue'),
    meta: { title: 'JD 匹配分析', group: '求职流程', color: 'var(--m-jd)' }
  },
  {
    path: '/interview',
    name: 'InterviewList',
    component: () => import('../views/InterviewList.vue'),
    meta: { title: '模拟面试', group: '求职流程', color: 'var(--m-interview)' }
  },
  {
    path: '/interview/:sessionId',
    name: 'InterviewChat',
    component: () => import('../views/InterviewChat.vue'),
    meta: {
      title: '面试会话',
      group: '求职流程',
      color: 'var(--m-interview)',
      hidden: true,
      activeMenu: '/interview'
    }
  },
  {
    path: '/practice',
    name: 'Practice',
    component: () => import('../views/Practice.vue'),
    meta: { title: '八股陪练', group: '能力提升', color: 'var(--m-practice)' }
  },
  {
    path: '/wrong-questions',
    name: 'WrongQuestions',
    component: () => import('../views/WrongQuestions.vue'),
    meta: { title: '错题本', group: '能力提升', color: 'var(--m-wrong)' }
  },
  {
    path: '/experiences',
    name: 'Experiences',
    component: () => import('../views/Experiences.vue'),
    meta: { title: '面经整理', group: '能力提升', color: 'var(--m-experience)' }
  },
  {
    // 设置迁入右上角用户菜单，不进侧栏（设计文档 v1.5 §4.4）
    path: '/settings',
    name: 'Settings',
    component: () => import('../views/Settings.vue'),
    meta: { title: '系统设置', hidden: true }
  },
  {
    // 流式协议调试页：不进侧边导航，只能手输 URL 访问（步骤 11）
    path: '/dev/stream',
    name: 'DevStream',
    component: () => import('../views/DevStream.vue'),
    meta: { title: '流式调试', hidden: true }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 免登录白名单（接口文档 1.1：/health、/auth/register、/auth/login 免鉴权；/welcome 为入口页）
const PUBLIC_PAGES = ['/welcome', '/login', '/register']

// 路由守卫（系统设计 §4.1）：显式白名单，不做"反向推断"，避免新增页面时漏判
router.beforeEach((to) => {
  // 读 localStorage 而非 store：避免「路由模块 ↔ store 模块」循环依赖；Token 唯一写入点是 useUserStore.setToken
  const token = localStorage.getItem('jobpilot_token')

  if (PUBLIC_PAGES.includes(to.path)) {
    if (token && (to.path === '/login' || to.path === '/register')) return '/'
    return true
  }
  return token ? true : '/welcome'
})

export default router
