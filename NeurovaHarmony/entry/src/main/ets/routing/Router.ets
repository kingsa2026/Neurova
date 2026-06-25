/**
 * Router - 统一路由管理
 *
 * 职责：管理应用所有页面跳转、路由表、路由守卫
 * 设计：基于 ArkUI Navigation + NavPathStack
 *
 * 用法：
 *   const router = Router.getInstance();
 *   router.push('LoginPage', { redirect: 'Dashboard' });
 *   router.replace('DashboardPage');
 *   router.back();
 */

import { Logger } from '../logger/Logger';
import { AuthStore } from '../state/stores/AuthStore';

/** 路由名 → 页面组件映射（实际组件由 Navigation 的 navPath 属性绑定） */
export const RouteNames = {
  LOGIN: 'LoginPage',
  REGISTER: 'RegisterPage',
  DASHBOARD: 'DashboardPage',
  CHAT: 'ChatPage',
  AGENT_LIST: 'AgentListPage',
  AGENT_FORM: 'AgentFormPage',
  PAIRING: 'PairingPage',
  MEMORY: 'MemoryPage',
  KNOWLEDGE: 'KnowledgePage',
  MODEL: 'ModelPage',
  HEALTH: 'HealthPage',
  SETTINGS: 'SettingsPage',
  AGENT_CHANNEL: 'AgentChannelPage',
  // M4 P2 认知层
  EXPERIENCE_KNOWLEDGE: 'ExperienceKnowledgePage',
  KNOWLEDGE_GRAPH: 'KnowledgeGraphPage',
  METACOGNITION: 'MetacognitionPage',
  REFLECTION: 'ReflectionPage',
  GROWTH: 'GrowthPage',
  // M4 P2 能力层
  AGENT_RULE: 'AgentRulePage',
  AGENT_FILE: 'AgentFilePage',
  AGENT_MEDIA: 'AgentMediaPage',
  // M4 P2 个性层
  AGENT_EMOTION: 'AgentEmotionPage',
  AGENT_PERSONALITY: 'AgentPersonalityPage',
  // M4 P2 运行时层
  AGENT_SCHEDULER: 'AgentSchedulerPage',
  CONTEXT_CHANNEL: 'ContextChannelPage',
  AGENT_COMPUTER: 'AgentComputerPage',
  AGENT_TRACE: 'AgentTracePage',
  AGENT_TRAJECTORY: 'AgentTrajectoryPage',
  SLEEP_STATUS: 'SleepStatusPage',
  SLEEP_SETTINGS: 'SleepSettingsPage',
  AGENT_FIREWALL: 'AgentFirewallPage',
  // M4 P2 知识技能扩展
  SKILL_POOL: 'SkillPoolPage',
  SKILL_MARKET: 'SkillMarketPage',
  AIGC: 'AIGCPage',
  TOOL_LAYER: 'ToolLayerPage',
  // M4 P2 协作与工作流
  WORKFLOW: 'WorkflowPage',
  COLLABORATION: 'CollaborationPage',
  PROJECT: 'ProjectPage',
  TEAM: 'TeamPage',
  TASK: 'TaskPage',
  // M4 P2 渠道系统
  CHANNEL_INTEGRATION: 'ChannelIntegrationPage',
  SESSION_SYNC: 'SessionSyncPage',
  // M4 P2 监控与管理
  STATS: 'StatsPage',
  MONITOR: 'MonitorPage',
  LOG: 'LogPage',
  FILE: 'FilePage',
  NOTIFICATION: 'NotificationPage',
  NEURON: 'NeuronPage',
  // M5 P3 协作扩展与市场
  COLLABORATION_TEMPLATE: 'CollaborationTemplatePage',
  COLLABORATION_HISTORY: 'CollaborationHistoryPage',
  COLLABORATION_INITIATE: 'CollaborationInitiatePage',
  WEBHOOK: 'WebhookPage',
  MARKETPLACE: 'MarketplacePage',
  // M5 P3 系统监控扩展
  AUDIT: 'AuditPage',
  BENCHMARK: 'BenchmarkPage',
  SANDBOX: 'SandboxPage',
  FIREWALL: 'FirewallPage',
  ANALYTICS: 'AnalyticsPage',
  // M5 P3 用户与记忆扩展
  GROUP: 'GroupPage',
  ENHANCED_USER: 'EnhancedUserPage',
  AGENT_SKILL: 'AgentSkillPage',
  MEMORY_SETTINGS: 'MemorySettingsPage',
  MEMORY_SEARCH_SETTINGS: 'MemorySearchSettingsPage',
} as const;

/** 需要登录才能访问的受保护路由 */
const PROTECTED_ROUTES: string[] = [
  RouteNames.DASHBOARD,
  RouteNames.CHAT,
  RouteNames.AGENT_LIST,
  RouteNames.AGENT_FORM,
  RouteNames.MEMORY,
  RouteNames.KNOWLEDGE,
  RouteNames.MODEL,
  RouteNames.HEALTH,
  RouteNames.SETTINGS,
  RouteNames.AGENT_CHANNEL,
  // M4 P2 认知层（全部受保护）
  RouteNames.EXPERIENCE_KNOWLEDGE,
  RouteNames.KNOWLEDGE_GRAPH,
  RouteNames.METACOGNITION,
  RouteNames.REFLECTION,
  RouteNames.GROWTH,
  // M4 P2 能力 + 个性层（全部受保护）
  RouteNames.AGENT_RULE,
  RouteNames.AGENT_FILE,
  RouteNames.AGENT_MEDIA,
  RouteNames.AGENT_EMOTION,
  RouteNames.AGENT_PERSONALITY,
  // M4 P2 运行时层（全部受保护）
  RouteNames.AGENT_SCHEDULER,
  RouteNames.CONTEXT_CHANNEL,
  RouteNames.AGENT_COMPUTER,
  RouteNames.AGENT_TRACE,
  RouteNames.AGENT_TRAJECTORY,
  RouteNames.SLEEP_STATUS,
  RouteNames.SLEEP_SETTINGS,
  RouteNames.AGENT_FIREWALL,
  // M4 P2 知识技能扩展（全部受保护）
  RouteNames.SKILL_POOL,
  RouteNames.SKILL_MARKET,
  RouteNames.AIGC,
  RouteNames.TOOL_LAYER,
  // M4 P2 协作与工作流（全部受保护）
  RouteNames.WORKFLOW,
  RouteNames.COLLABORATION,
  RouteNames.PROJECT,
  RouteNames.TEAM,
  RouteNames.TASK,
  // M4 P2 渠道系统（全部受保护）
  RouteNames.CHANNEL_INTEGRATION,
  RouteNames.SESSION_SYNC,
  // M4 P2 监控与管理（全部受保护）
  RouteNames.STATS,
  RouteNames.MONITOR,
  RouteNames.LOG,
  RouteNames.FILE,
  RouteNames.NOTIFICATION,
  RouteNames.NEURON,
  // M5 P3 协作扩展与市场（全部受保护）
  RouteNames.COLLABORATION_TEMPLATE,
  RouteNames.COLLABORATION_HISTORY,
  RouteNames.COLLABORATION_INITIATE,
  RouteNames.WEBHOOK,
  RouteNames.MARKETPLACE,
  // M5 P3 系统监控扩展（全部受保护）
  RouteNames.AUDIT,
  RouteNames.BENCHMARK,
  RouteNames.SANDBOX,
  RouteNames.FIREWALL,
  RouteNames.ANALYTICS,
  // M5 P3 用户与记忆扩展（全部受保护）
  RouteNames.GROUP,
  RouteNames.ENHANCED_USER,
  RouteNames.AGENT_SKILL,
  RouteNames.MEMORY_SETTINGS,
  RouteNames.MEMORY_SEARCH_SETTINGS,
];

/** 路由守卫：检查是否允许跳转 */
function canNavigate(routeName: string, authStore: AuthStore): boolean {
  // 受保护路由需要登录
  if (PROTECTED_ROUTES.indexOf(routeName) >= 0) {
    if (!authStore.isAuthenticated) {
      return false;
    }
  }
  return true;
}

export class Router {
  private static instance: Router;
  private navStack: NavPathStack = new NavPathStack();
  private logger: Logger = Logger.getInstance();
  private authStore: AuthStore = new AuthStore();

  private constructor() {}

  static getInstance(): Router {
    if (!Router.instance) {
      Router.instance = new Router();
    }
    return Router.instance;
  }

  /** 获取 NavPathStack（供 Navigation 组件绑定） */
  getNavStack(): NavPathStack {
    return this.navStack;
  }

  /** 压入新页面 */
  push(routeName: string, params?: Record<string, Object>): boolean {
    if (!canNavigate(routeName, this.authStore)) {
      this.logger.warn('Router', `未授权访问 ${routeName}，跳转登录页`);
      this.navStack.replacePath({ name: RouteNames.LOGIN, param: { redirect: routeName } });
      return false;
    }
    this.navStack.pushPath({ name: routeName, param: params });
    this.logger.info('Router', `push → ${routeName}`);
    return true;
  }

  /** 替换当前页面（不可返回） */
  replace(routeName: string, params?: Record<string, Object>): boolean {
    if (!canNavigate(routeName, this.authStore)) {
      this.logger.warn('Router', `未授权访问 ${routeName}，跳转登录页`);
      this.navStack.replacePath({ name: RouteNames.LOGIN, param: { redirect: routeName } });
      return false;
    }
    this.navStack.replacePath({ name: routeName, param: params });
    this.logger.info('Router', `replace → ${routeName}`);
    return true;
  }

  /** 返回上一页 */
  back(): void {
    this.navStack.pop();
    this.logger.info('Router', 'back');
  }

  /** 返回到指定页面（清除中间页面） */
  backTo(routeName: string): void {
    this.navStack.popToName(routeName);
    this.logger.info('Router', `backTo → ${routeName}`);
  }

  /** 清空栈并跳转到指定页面 */
  resetTo(routeName: string): void {
    this.navStack.clear();
    this.navStack.replacePath({ name: routeName });
    this.logger.info('Router', `resetTo → ${routeName}`);
  }

  /** 获取当前页面参数 */
  getCurrentParam(): Object | undefined {
    const path = this.navStack.getAllPathName().length > 0
      ? this.navStack.getParamByIndex(this.navStack.size() - 1)
      : undefined;
    return path;
  }

  /** 获取栈深度 */
  getStackDepth(): number {
    return this.navStack.size();
  }
}
