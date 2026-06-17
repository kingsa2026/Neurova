import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  // ---------------------------------------------------------------------------
  // Public routes (guest only)
  // ---------------------------------------------------------------------------
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/pages/LoginPage.vue'),
    meta: { guest: true },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/pages/RegisterPage.vue'),
    meta: { guest: true },
  },

  // ---------------------------------------------------------------------------
  // Protected routes under MainLayout
  // ---------------------------------------------------------------------------
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      // Default redirect
      { path: '', redirect: '/dashboard' },
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/pages/DashboardPage.vue'),
      },

      // ----- Agents -----
      {
        path: 'agents',
        name: 'AgentList',
        component: () => import('@/pages/AgentListPage.vue'),
      },
      {
        path: 'agents/create',
        name: 'AgentCreate',
        component: () => import('@/pages/AgentFormPage.vue'),
      },
      {
        path: 'agents/:id',
        name: 'AgentEdit',
        component: () => import('@/pages/AgentFormPage.vue'),
        props: true,
      },

      // ----- Agent-scoped routes (under agent/:agentId) -----
      {
        path: 'agent/:agentId/memory',
        name: 'AgentMemory',
        component: () => import('@/pages/MemoryPage.vue'),
        props: true,
      },
      {
        path: 'agent/:agentId/experience-knowledge',
        name: 'AgentExperience',
        component: () => import('@/pages/ExperienceKnowledgePage.vue'),
        props: true,
      },
      {
        path: 'agent/:agentId/knowledge-graph',
        name: 'AgentKnowledgeGraph',
        component: () => import('@/pages/KnowledgeGraphPage.vue'),
        props: true,
      },
      {
        path: 'agent/:agentId/metacognition',
        name: 'AgentMetacognition',
        component: () => import('@/pages/MetacognitionPage.vue'),
        props: true,
      },
      {
        path: 'agent/:agentId/reflection',
        name: 'AgentReflection',
        component: () => import('@/pages/ReflectionPage.vue'),
        props: true,
      },
      {
        path: 'agent/:agentId/growth',
        name: 'AgentGrowth',
        component: () => import('@/pages/GrowthPage.vue'),
        props: true,
      },
      {
        path: 'agent/:agentId/skills',
        name: 'AgentSkills',
        component: () => import('@/pages/AgentSkillPage.vue'),
        props: true,
      },
      {
        path: 'agent/:agentId/files',
        name: 'AgentFiles',
        component: () => import('@/pages/AgentFilePage.vue'),
        props: true,
      },
      {
        path: 'agent/:agentId/media',
        name: 'AgentMedia',
        component: () => import('@/pages/AgentMediaPage.vue'),
        props: true,
      },
      {
        path: 'agent/:agentId/scheduler',
        name: 'AgentScheduler',
        component: () => import('@/pages/AgentSchedulerPage.vue'),
        props: true,
      },
      {
        path: 'agent/:agentId/rules',
        name: 'AgentRules',
        component: () => import('@/pages/AgentRulePage.vue'),
        props: true,
      },
      {
        path: 'agent/:agentId/emotion',
        name: 'AgentEmotion',
        component: () => import('@/pages/AgentEmotionPage.vue'),
        props: true,
      },
      {
        path: 'agent/:agentId/personality',
        name: 'AgentPersonality',
        component: () => import('@/pages/AgentPersonalityPage.vue'),
        props: true,
      },
      {
        path: 'agent/:agentId/sleep/status',
        name: 'SleepStatus',
        component: () => import('@/pages/SleepStatusPage.vue'),
        props: true,
      },
      {
        path: 'agent/:agentId/sleep/settings',
        name: 'SleepSettings',
        component: () => import('@/pages/SleepSettingsPage.vue'),
        props: true,
      },
      {
        path: 'agent/:agentId/firewall',
        name: 'AgentFirewall',
        component: () => import('@/pages/AgentFirewallPage.vue'),
        props: true,
      },
      {
        path: 'agent/:agentId/trajectory',
        name: 'AgentTrajectory',
        component: () => import('@/pages/AgentTrajectoryPage.vue'),
        props: true,
      },
      {
        path: 'agent/:agentId/trace',
        name: 'AgentTrace',
        component: () => import('@/pages/AgentTracePage.vue'),
        props: true,
      },
      {
        path: 'agent/:agentId/channel',
        name: 'AgentChannel',
        component: () => import('@/pages/AgentChannelPage.vue'),
        props: true,
      },
      {
        path: 'agent/:agentId/channel-sharing',
        name: 'AgentChannelSharing',
        component: () => import('@/pages/ContextChannelPage.vue'),
        props: true,
      },
      {
        path: 'agent/:agentId/computer',
        name: 'AgentComputer',
        component: () => import('@/pages/AgentComputerPage.vue'),
        props: true,
      },

      // ----- NEURON 系统路由 -----
      {
        path: 'neuron',
        name: 'Neuron',
        component: () => import('@/views/NeuronPage.vue'),
      },

      // ----- Global routes -----
      {
        path: 'chat',
        name: 'Chat',
        component: () => import('@/pages/ChatPage.vue'),
        props: { layoutMode: 'main' },
      },
      {
        path: 'channels',
        name: 'Channels',
        component: () => import('@/pages/ChannelIntegrationPage.vue'),
      },
      {
        path: 'knowledge',
        name: 'Knowledge',
        component: () => import('@/pages/KnowledgePage.vue'),
      },
      {
        path: 'memory/search-settings',
        name: 'MemorySearchSettings',
        component: () => import('@/pages/MemorySearchSettingsPage.vue'),
      },
      {
        path: 'memory/settings',
        name: 'MemorySettings',
        component: () => import('@/pages/MemorySettingsPage.vue'),
      },

      // ----- Skills & AIGC -----
      {
        path: 'marketplace/skills',
        name: 'SkillMarket',
        component: () => import('@/pages/SkillMarketPage.vue'),
      },
      {
        path: 'skill-pool',
        name: 'SkillPool',
        component: () => import('@/pages/SkillPoolPage.vue'),
      },
      {
        path: 'aigc',
        name: 'AIGC',
        component: () => import('@/pages/AIGCPage.vue'),
      },

      // ----- Models & Tools -----
      {
        path: 'models',
        name: 'Models',
        component: () => import('@/pages/ModelPage.vue'),
      },
      {
        path: 'tool-layers',
        name: 'ToolLayers',
        component: () => import('@/pages/ToolLayerPage.vue'),
      },

      // ----- Workflows -----
      {
        path: 'workflows',
        name: 'Workflows',
        component: () => import('@/workflow/WorkflowPage.vue'),
      },

      // ----- Collaboration -----
      {
        path: 'collaboration',
        name: 'Collaboration',
        component: () => import('@/pages/CollaborationPage.vue'),
      },
      {
        path: 'collaboration/templates',
        name: 'CollaborationTemplates',
        component: () => import('@/pages/CollaborationTemplatePage.vue'),
      },
      {
        path: 'collaboration/history',
        name: 'CollaborationHistory',
        component: () => import('@/pages/CollaborationHistoryPage.vue'),
      },
      {
        path: 'projects',
        name: 'Projects',
        component: () => import('@/pages/ProjectPage.vue'),
      },
      {
        path: 'teams',
        name: 'Teams',
        component: () => import('@/pages/TeamPage.vue'),
      },
      {
        path: 'tasks',
        name: 'Tasks',
        component: () => import('@/pages/TaskPage.vue'),
      },

      // ----- Channels -----
      {
        path: 'session-sync',
        name: 'SessionSync',
        component: () => import('@/pages/SessionSyncPage.vue'),
      },
      {
        path: 'webhooks',
        name: 'Webhooks',
        component: () => import('@/pages/WebhookPage.vue'),
      },

      // ----- System -----
      {
        path: 'sandbox',
        name: 'Sandbox',
        component: () => import('@/pages/SandboxPage.vue'),
      },
      {
        path: 'stats',
        name: 'Stats',
        component: () => import('@/pages/StatsPage.vue'),
      },
      {
        path: 'monitor',
        name: 'Monitor',
        component: () => import('@/pages/MonitorPage.vue'),
      },
      {
        path: 'logs',
        name: 'Logs',
        component: () => import('@/pages/LogPage.vue'),
      },
      {
        path: 'health',
        name: 'Health',
        component: () => import('@/pages/HealthPage.vue'),
      },
      {
        path: 'audit',
        name: 'Audit',
        component: () => import('@/pages/AuditPage.vue'),
      },
      {
        path: 'benchmark',
        name: 'Benchmark',
        component: () => import('@/pages/BenchmarkPage.vue'),
      },
      {
        path: 'marketplace',
        name: 'Marketplace',
        component: () => import('@/pages/MarketplacePage.vue'),
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('@/pages/SettingPage.vue'),
      },
      {
        path: 'notifications',
        name: 'Notifications',
        component: () => import('@/pages/NotificationPage.vue'),
      },
      {
        path: 'groups',
        name: 'Groups',
        component: () => import('@/pages/GroupPage.vue'),
      },
      {
        path: 'enhanced-users',
        name: 'EnhancedUsers',
        component: () => import('@/pages/EnhancedUserPage.vue'),
      },
      {
        path: 'files',
        name: 'Files',
        component: () => import('@/pages/FilePage.vue'),
      },
      {
        path: 'firewall',
        name: 'Firewall',
        component: () => import('@/pages/FirewallPage.vue'),
      },
    ],
  },

  // ---------------------------------------------------------------------------
  // Legacy chat route → redirect to unified MainLayout chat
  // ---------------------------------------------------------------------------
  {
    path: '/agent/:agentId/chat',
    redirect: '/chat',
  },

  // ---------------------------------------------------------------------------
  // 404 catch-all
  // ---------------------------------------------------------------------------
  {
    path: '/:pathMatch(.*)*',
    redirect: '/dashboard',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(_to, _from, savedPosition) {
    return savedPosition || { top: 0 }
  },
})

// ---------------------------------------------------------------------------
// Navigation guard
// ---------------------------------------------------------------------------
router.beforeEach((to, _from, next) => {
  const authStore = useAuthStore()

  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    // Redirect unauthenticated users to login, preserving the intended destination
    next({ name: 'Login', query: { redirect: to.fullPath } })
  } else if (to.meta.guest && authStore.isAuthenticated) {
    // Redirect already-authenticated users away from guest-only pages
    next({ name: 'Dashboard' })
  } else {
    next()
  }
})

export default router
