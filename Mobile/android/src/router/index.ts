import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { public: true } },
    { path: '/', name: 'chat', component: () => import('@/views/ChatView.vue') },
    { path: '/knowledge', name: 'knowledge', component: () => import('@/views/KnowledgeView.vue') },
    { path: '/tasks', name: 'tasks', component: () => import('@/views/TaskView.vue') },
    { path: '/files', name: 'files', component: () => import('@/views/FilesView.vue') },
    { path: '/profile', name: 'profile', component: () => import('@/views/ProfileView.vue') },
    { path: '/pairing', name: 'pairing', component: () => import('@/views/PairingView.vue') },
    { path: '/notifications', name: 'notifications', component: () => import('@/views/NotificationsView.vue') },
    { path: '/manage/models', name: 'manage-models', component: () => import('@/views/ModelManageView.vue') },
    { path: '/manage/memory', name: 'manage-memory', component: () => import('@/views/MemoryManageView.vue') },
    { path: '/manage/skills', name: 'manage-skills', component: () => import('@/views/SkillManageView.vue') },
    { path: '/manage/agents', name: 'manage-agents', component: () => import('@/views/AgentManageView.vue') },
    { path: '/servers', name: 'servers', component: () => import('@/views/ServerProfilesView.vue') },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.meta.public) return true
  if (!auth.isLoggedIn) {
    // restore 异常（桥偶发失败）不得中断导航——中断会让 router-view 停在空匹配
    // （实测表现为切页后整页残缺），失败按未登录处理跳登录页，可恢复。
    try {
      const ok = await auth.restore()
      if (!ok) return { name: 'login' }
    } catch {
      return { name: 'login' }
    }
  }
  return true
})

export default router
