import { createRouter, createWebHistory } from 'vue-router'

// meta 约定：
//   title      顶栏标题 + 菜单文案
//   group      菜单分组名（侧栏按此分组渲染，保持声明顺序）
//   color      模块色（CSS 变量名，用于侧栏色点与该模块强调元素）
//   hidden     true 时不进菜单
//   activeMenu 高亮指向的菜单 path
const routes = [
  {
    path: '/',
    name: 'Overview',
    component: () => import('../views/Overview.vue'),
    meta: { title: '今日概览', group: '求职流程', color: 'var(--brand)' }
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
    path: '/settings',
    name: 'Settings',
    component: () => import('../views/Settings.vue'),
    meta: { title: '系统设置', group: '系统', color: 'var(--m-system)' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
