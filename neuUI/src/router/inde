import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
// 懒加载页面
const LoginPage = () =&gt; import('@/pages/LoginPage.vue')
const RegisterPage = () =&gt; import('@/pages/RegisterPage.vue')
const MainLayout = () =&gt; import('@/layouts/MainLayout.vue')
const DashboardPage = () =&gt; import('@/pages/DashboardPage.vue')
const SettingPage = () =&gt; import('@/pages/SettingPage.vue')
const AgentListPage = () =&gt; import('@/pages/AgentListPage.vue')
const AgentFormPage = () =&gt; import('@/pages/AgentFormPage.vue')
const ChatPage = () =&gt; import('@/pages/ChatPage.vue')
const MemoryPage = () =&gt; import('@/pages/MemoryPage.vue')
const KnowledgePage = () =&gt; import('@/pages/KnowledgePage.vue')
const SkillMarketPage = () =&gt; import('@/pages/SkillMarketPage.vue')
const WorkflowPage = () =&gt; import('@/pages/WorkflowPage.vue')
const ExperienceKnowledgePage = () =&gt; import('@/pages/ExperienceKnowledgePage.vue')
const KnowledgeGraphPage = () =&gt; import('@/pages/KnowledgeGraphPage.vue')
const MetacognitionPage = () =&gt; import('@/pages/MetacognitionPage.vue')
const ReflectionPage = () =&gt; import('@/pages/ReflectionPage.vue')
const GrowthPage = () =&gt; import('@/pages/GrowthPage.vue')
const AgentSkillPage = () =&gt; import('@/pages/AgentSkillPage.vue')
const SkillPoolPage = () =&gt; import('@/pages/SkillPoolPage.vue')
const AIGCPage = () =&gt; import('@/pages/AIGCPage.vue')
const AgentFilePage = () =&gt; import('@/pages/AgentFilePage.vue')
const AgentMediaPage = () =&gt; import('@/pages/AgentMediaPage.vue')
const CollaborationPage = () =&gt; import('@/pages/CollaborationPage.vue')
const ProjectPage = () =&gt; import('@/pages/ProjectPage.vue')
const TeamPage = () =&gt; import('@/pages/TeamPage.vue')
const AgentSchedulerPage = () =&gt; import('@/pages/AgentSchedulerPage.vue')
const TaskPage = () =&gt; import('@/pages/TaskPage.vue')
const AgentRulePage = () =&gt; import('@/pages/AgentRulePage.vue')
const ModelPage = () =&gt; import('@/pages/ModelPage.vue')
const AnalyticsPage = () =&gt; import('@/pages/AnalyticsPage.vue')
const AgentEmotionPage = () =&gt; import('@/pages/AgentEmotionPage.vue')
const AgentPersonalityPage = () =&gt; import('@/pages/AgentPersonalityPage.vue')
const AgentFirewallPage = () =&gt; import('@/pages/AgentFirewallPage.vue')
const AuditPage = () =&gt; import('@/pages/AuditPage.vue')
const BenchmarkPage = () =&gt; import('@/pages/BenchmarkPage.vue')
const NotificationPage = () =&gt; import('@/pages/NotificationPage.vue')
const HealthPage = () =&gt; import('@/pages/HealthPage.vue')
const CollaborationTemplatePage = () =&gt; import('@/pages/CollaborationTemplatePage.vue')
const CollaborationInitiatePage = () =&gt; import('@/pages/CollaborationInitiatePage.vue')
const CollaborationHistoryPage = () =&gt; import('@/pages/CollaborationHistoryPage.vue')
const AgentSleepPage = () =&gt; import('@/pages/AgentSleepPage.vue')
const SleepStatusPage = () =&gt; import('@/pages/SleepStatusPage.vue')
const SleepSettingsPage = () =&gt; import('@/pages/SleepSettingsPage.vue')
const MemorySearchSettingsPage = () =&gt; import('@/pages/MemorySearchSettingsPage.vue')
const AgentTrajectoryPage = () =&gt; import('@/pages/AgentTrajectoryPage.vue')
const AgentTracePage = () =&gt; import('@/pages/AgentTracePage.vue')
const AgentChannelPage = () =&gt; import('@/pages/AgentChannelPage.vue')
const AgentComputerPage = () =&gt; import('@/pages/AgentComputerPage.vue')
const MarketplacePage = () =&gt; import('@/pages/MarketplacePage.vue')
const ToolLayerPage = () =&gt; import('@/pages/ToolLayerPage.vue')
const ContextChannelPage = () =&gt; import('@/pages/ContextChannelPage.vue')
const WebhookPage = () =&gt; import('@/pages/WebhookPage.vue')
const SandboxPage = () =&gt; import('@/pages/SandboxPage.vue')
const StatsPage = () =&gt; import('@/pages/StatsPage.vue')
const MonitorPage = () =&gt; import('@/pages/MonitorPage.vue')
const LogPage = () =&gt; import('@/pages/LogPage.vue')
const GroupPage = () =&gt; import('@/pages/GroupPage.vue')
const EnhancedUserPage = () =&gt; import('@/pages/EnhancedUserPage.vue')
const PlaceholderPage = () =&gt; import('@/pages/PlaceholderPage.vue')
const routes: RouteRecordRaw[] = [
  // ========== 公开路由 ==========
  {
    path: '/login',
    name: 'Login',
    component: LoginPage,
    meta: { requiresAuth: false },
  },
  {
    path: '/register',
    name: 'Register',
    component: RegisterPage,
    meta: { requiresAuth: false },
  },
  // ========== 受保护路由 ==========
  {
    path: '/',
    component: MainLayout,
    meta: { requiresAuth: true },
    redirect: '/dashboard',
    children: [
      // ─── 模块14: 首页看板 ───
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: DashboardPage,
        meta: { title: '首页看板', module: 'dashboard' },
      },
      // ─── 模块2: Agent 管理核心 ───
      {
        path: 'agents',
        name: 'AgentList',
        component: AgentListPage,
        meta: { title: 'Agent 列表', module: 'agents' },
      },
      {
        path: 'agents/create',
        name: 'AgentCreate',
        component: AgentFormPage,
        meta: { title: '创建 Agent', module: 'agents' },
      },
      {
        path: 'agents/:id',
        name: 'AgentEdit',
        component: AgentFormPage,
        meta: { title: '编辑 Agent', module: 'agents' },
      },
      // ─── 模块3: 记忆与认知系统 (Agent级) ───
      {
        path: 'agent/:agentId/memory',
        name: 'AgentMemory',
        component: MemoryPage,
        meta: { title: '记忆管理', module: 'memory' },
      },
      {
        path: 'agent/:agentId/experience-knowledge',
        name: 'AgentExperience',
        component: ExperienceKnowledgePage,
        meta: { title: '经验知识库', module: 'memory' },
      },
      {
        path: 'agent/:agentId/knowledge-graph',
        name: 'AgentKnowledgeGraph',
        component: KnowledgeGraphPage,
        meta: { title: '知识图谱', module: 'memory' },
      },
      {
        path: 'agent/:agentId/metacognition',
        name: 'AgentMetacognition',
        component: MetacognitionPage,
        meta: { title: '元认知', module: 'memory' },
      },
      {
        path: 'agent/:agentId/reflection',
        name: 'AgentReflection',
        component: ReflectionPage,
        meta: { title: '反思管理', module: 'memory' },
      },
      {
        path: 'agent/:agentId/growth',
        name: 'AgentGrowth',
        component: GrowthPage,
        meta: { title: '成长系统', module: 'memory' },
      },
      // ─── 模块2: 聊天 (Agent级) ───
      {
        path: 'agent/:agentId/chat',
        name: 'AgentChat',
        component: ChatPage,
        meta: { title: '聊天', module: 'chat' },
      },
      {
        path: 'chat',
        name: 'ChatRedirect',
        redirect: () =&gt; {
          const agentId = localStorage.getItem('currentAgentId')
          return agentId &amp;&amp; agentId !== 'default' ? `/agent/${agentId}/chat` : '/agents'
        },
        meta: { title: '聊天', module: 'chat' },
      },
      // ─── 模块4: 技能与学习系统 (Agent级) ───
      {
        path: 'agent/:agentId/skills',
        name: 'AgentSkills',
        component: AgentSkillPage,
        meta: { title: 'Agent 技能', module: 'skills' },
      },
      {
        path: 'marketplace/skills',
        name: 'SkillMarket',
        component: SkillMarketPage,
        meta: { title: '技能市场', module: 'skills' },
      },
      {
        path: 'skill-pool',
        name: 'SkillPool',
        component: SkillPoolPage,
        meta: { title: '技能池', module: 'skills' },
      },
      {
        path: 'aigc',
        name: 'AIGC',
        component: AIGCPage,
        meta: { title: 'AIGC 生成', module: 'skills' },
      },
      // ─── 模块5: 知识库与文档 ───
      {
        path: 'knowledge',
        name: 'Knowledge',
        component: KnowledgePage,
        meta: { title: '知识库', module: 'knowledge' },
      },
      {
        path: 'agent/:agentId/files',
        name: 'AgentFiles',
        component: AgentFilePage,
        meta: { title: '文件管理', module: 'knowledge' },
      },
      {
        path: 'agent/:agentId/media',
        name: 'AgentMedia',
        component: AgentMediaPage,
        meta: { title: '媒体处理', module: 'knowledge' },
      },
      // ─── 模块6: 工作流与协作 ───
      {
        path: 'workflows',
        name: 'Workflows',
        component: WorkflowPage,
        meta: { title: '工作流设计器', module: 'workflows' },
      },
      {
        path: 'collaboration',
        name: 'Collaboration',
        component: CollaborationPage,
        meta: { title: '协作概览', module: 'collaboration' },
      },
      {
        path: 'collaboration/templates',
        name: 'CollaborationTemplates',
        component: CollaborationTemplatePage,
        meta: { title: '协作模板', module: 'collaboration' },
      },
      {
        path: 'collaboration/initiate',
        name: 'CollaborationInitiate',
        component: CollaborationInitiatePage,
        meta: { title: '发起协作', module: 'collaboration' },
      },
      {
        path: 'collaboration/history',
        name: 'CollaborationHistory',
        component: CollaborationHistoryPage,
        meta: { title: '协作历史', module: 'collaboration' },
      },
      {
        path: 'projects',
        name: 'Projects',
        component: ProjectPage,
        meta: { title: '项目管理', module: 'collaboration' },
      },
      {
        path: 'teams',
        name: 'Teams',
        component: TeamPage,
        meta: { title: '团队管理', module: 'collaboration' },
      },
      // ─── 模块7: 调度与自动化 ───
      {
        path: 'agent/:agentId/scheduler',
        name: 'AgentScheduler',
        component: AgentSchedulerPage,
        meta: { title: '调度器', module: 'scheduler' },
      },
      {
        path: 'tasks',
        name: 'Tasks',
        component: TaskPage,
        meta: { title: '任务管理', module: 'scheduler' },
      },
      {
        path: 'agent/:agentId/rules',
        name: 'AgentRules',
        component: AgentRulePage,
        meta: { title: '规则管理', module: 'scheduler' },
      },
      // ─── 模块8: 模型与提供商 ───
      {
        path: 'models',
        name: 'Models',
        component: ModelPage,
        meta: { title: '模型管理', module: 'models' },
      },
      {
        path: 'providers',
        redirect: '/models',
      },
      {
        path: 'tool-layers',
        name: 'ToolLayers',
        component: ToolLayerPage,
        meta: { title: '工具层管理', module: 'models' },
      },
      // ─── 模块9: 情感与人格 (Agent级) ───
      {
        path: 'agent/:agentId/emotion',
        name: 'AgentEmotion',
        component: AgentEmotionPage,
        meta: { title: '情绪分析', module: 'emotion' },
      },
      {
        path: 'agent/:agentId/personality',
        name: 'AgentPersonality',
        component: AgentPersonalityPage,
        meta: { title: '人格配置', module: 'emotion' },
      },
      // ─── 睡眠管理 (Agent级) ───
      {
        path: 'agent/:agentId/sleep/status',
        name: 'SleepStatus',
        component: SleepStatusPage,
        meta: { title: '睡眠状态', module: 'sleep' },
      },
      {
        path: 'agent/:agentId/sleep/settings',
        name: 'SleepSettings',
        component: SleepSettingsPage,
        meta: { title: '睡眠设置', module: 'sleep' },
      },
      {
        path: 'memory/search-settings',
        name: 'MemorySearchSettings',
        component: MemorySearchSettingsPage,
        meta: { title: '记忆检索设置', module: 'memory' },
      },
      // ─── 模块10: 安全与合规 ───
      {
        path: 'agent/:agentId/firewall',
        name: 'AgentFirewall',
        component: AgentFirewallPage,
        meta: { title: '防火墙与合规', module: 'security' },
      },
      {
        path: 'audit',
        name: 'Audit',
        component: AuditPage,
        meta: { title: '审计日志', module: 'security' },
      },
      // ─── 模块11: 轨迹与调试 ───
      {
        path: 'agent/:agentId/trajectory',
        name: 'AgentTrajectory',
        component: AgentTrajectoryPage,
      },
      {
        path: 'agent/:agentId/trace',
        name: 'AgentTrace',
        component: AgentTracePage,
      },
      {
        path: 'benchmark',
        name: 'Benchmark',
        component: BenchmarkPage,
        meta: { title: '基准测试', module: 'trace' },
      },
      // ─── 模块14: 渠道与通信 ───
      {
        path: 'agent/:agentId/channel',
        name: 'AgentChannel',
        component: AgentChannelPage,
        meta: { title: '渠道管理', module: 'channels' },
      },
      {
        path: 'agent/:agentId/channel-sharing',
        name: 'AgentChannelSharing',
        component: ContextChannelPage,
        meta: { title: '上下文共享', module: 'channels' },
      },
      {
        path: 'webhooks',
        name: 'Webhooks',
        component: WebhookPage,
        meta: { title: 'Webhook 管理', module: 'channels' },
      },
      // ─── 模块13: 计算机使用 ───
      {
        path: 'agent/:agentId/computer',
        name: 'AgentComputer',
        component: AgentComputerPage,
      },
      {
        path: 'sandbox',
        name: 'Sandbox',
        component: SandboxPage,
        meta: { title: '沙箱管理', module: 'computer' },
      },
      // ─── 模块14: 分析与监控 ───
      {
        path: 'analytics',
        name: 'Analytics',
        component: AnalyticsPage,
        meta: { title: '分析统计', module: 'analytics' },
      },
      {
        path: 'stats',
        name: 'Stats',
        component: StatsPage,
        meta: { title: '统计', module: 'analytics' },
      },
      {
        path: 'monitor',
        name: 'Monitor',
        component: MonitorPage,
        meta: { title: '监控', module: 'analytics' },
      },
      {
        path: 'logs',
        name: 'Logs',
        component: LogPage,
        meta: { title: '日志管理', module: 'analytics' },
      },
      {
        path: 'health',
        name: 'Health',
        component: HealthPage,
        meta: { title: '健康管理', module: 'analytics' },
      },
      // ─── 模块15: 市场与发现 ───
      {
        path: 'marketplace',
        name: 'Marketplace',
        component: MarketplacePage,
      },
      // ─── 模块1: 用户系统 ───
      {
        path: 'settings',
        name: 'Settings',
        component: SettingPage,
        meta: { title: '系统设置', module: 'system' },
      },
      {
        path: 'notifications',
        name: 'Notifications',
        component: NotificationPage,
        meta: { title: '通知管理', module: 'system' },
      },
      {
        path: 'groups',
        name: 'Groups',
        component: GroupPage,
        meta: { title: '用户组管理', module: 'system', requireAdmin: true },
      },
      {
        path: 'enhanced-users',
        name: 'EnhancedUsers',
        component: EnhancedUserPage,
        meta: { title: '增强用户', module: 'system', requireAdmin: true },
      },
    ],
  },
  // 404
  {
    path: '/:pathMatch(.*)*',
    redirect: '/dashboard',
  },
]
const router = createRouter({
  history: createWebHistory(),
  routes,
})
// 安全的存储工具（与 auth.ts store 保持一致）
function secureGetToken(): string | null {
  try {
    return localStorage.getItem('token')
  } catch {
    return null
  }
}
/**
 * 解析 JWT payload（仅解码 base64，不验证签名）
 * 返回 null 如果 token 格式无效或已过期
 */
function parseJwtPayload(token: string): Record&lt;string, unknown&gt; | null {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null
    const payload = JSON.parse(atob(parts[1]))
    // 检查过期时间
    if (payload.exp &amp;&amp; Date.now() &gt;= payload.exp * 1000) {
      return null
    }
    return payload
  } catch {
    return null
  }
}
// 路由守卫
router.beforeEach((to, _from, next) =&gt; {
  const token = secureGetToken()
  const needAuth = to.matched.some(r =&gt; r.meta.requiresAuth)
  const requireAdmin = to.matched.some(r =&gt; r.meta.requireAdmin)
  if (needAuth &amp;&amp; !token) {
    next('/login')
    return
  }
  if (needAuth &amp;&amp; token) {
    // 验证 token 是否有效（格式正确且未过期）
    const payload = parseJwtPayload(token)
    if (!payload) {
      // token 无效或已过期，清除并跳转登录
      localStorage.removeItem('token')
      localStorage.removeItem('refresh_token')
      localStorage.removeItem('user')
      next('/login')
      return
    }
    // 检查管理员权限
    if (requireAdmin) {
      const userRole = payload.role as string | undefined
      if (userRole !== 'admin') {
        next('/dashboard')
        return
      }
    }
  }
  if ((to.path === '/login' || to.path === '/register') &amp;&amp; token) {
    // 已登录用户访问登录页时，也验证 token 有效性
    const payload = parseJwtPayload(token)
    if (payload) {
      next('/dashboard')
      return
    }
    // token 无效，允许访问登录页
  }
  next()
})
export default router
&nbsp;