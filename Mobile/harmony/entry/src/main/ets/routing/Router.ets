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

import { Logger } from '../libs/logger/Logger';
import { AuthStore } from '../libs/state/stores/AuthStore';

/** 未授权跳转登录页时携带的回跳参数 */
export interface RedirectParam {
  redirect: string;
}

/** 路由名 → 页面组件映射（实际组件由 Navigation 的 navPath 属性绑定） */
export class RouteNames {
  static readonly SHELL: string = 'ShellPage';
  static readonly LOGIN: string = 'LoginPage';
  static readonly REGISTER: string = 'RegisterPage';
  static readonly DASHBOARD: string = 'DashboardPage';
  static readonly CHAT: string = 'ChatPage';
  static readonly AGENT_LIST: string = 'AgentListPage';
  static readonly AGENT_FORM: string = 'AgentFormPage';
  static readonly AGENT_DETAIL: string = 'AgentDetailPage';
  static readonly KNOWLEDGE_IMPORT: string = 'KnowledgeImportPage';
  static readonly ENTERPRISE_SOURCES: string = 'EnterpriseSourcesPage';
  static readonly GRAPH_PREVIEW: string = 'GraphPreviewPage';
  static readonly ADMIN_USERS: string = 'AdminUsersPage';
  static readonly ADMIN_GROUPS: string = 'AdminGroupsPage';
  static readonly ADMIN_MARKET: string = 'AdminMarketPage';
  static readonly ADMIN_SETTINGS: string = 'AdminSettingsPage';
  static readonly PAIRING: string = 'PairingPage';
  static readonly CONNECTION: string = 'ConnectionPage';
  static readonly MEMORY: string = 'MemoryPage';
  static readonly KNOWLEDGE: string = 'KnowledgePage';
  static readonly MODEL: string = 'ModelPage';
  static readonly HEALTH: string = 'HealthPage';
  static readonly SETTINGS: string = 'SettingsPage';
  static readonly AGENT_CHANNEL: string = 'AgentChannelPage';
  // M4 P2 认知层
  static readonly EXPERIENCE_KNOWLEDGE: string = 'ExperienceKnowledgePage';
  static readonly KNOWLEDGE_GRAPH: string = 'KnowledgeGraphPage';
  static readonly METACOGNITION: string = 'MetacognitionPage';
  static readonly REFLECTION: string = 'ReflectionPage';
  static readonly GROWTH: string = 'GrowthPage';
  // M4 P2 能力层
  static readonly AGENT_RULE: string = 'AgentRulePage';
  static readonly AGENT_FILE: string = 'AgentFilePage';
  static readonly AGENT_MEDIA: string = 'AgentMediaPage';
  // M4 P2 运行时层
  static readonly AGENT_SCHEDULER: string = 'AgentSchedulerPage';
  static readonly CONTEXT_CHANNEL: string = 'ContextChannelPage';
  static readonly AGENT_COMPUTER: string = 'AgentComputerPage';
  static readonly AGENT_TRACE: string = 'AgentTracePage';
  static readonly AGENT_TRAJECTORY: string = 'AgentTrajectoryPage';
  static readonly SLEEP_STATUS: string = 'SleepStatusPage';
  static readonly SLEEP_SETTINGS: string = 'SleepSettingsPage';
  static readonly AGENT_FIREWALL: string = 'AgentFirewallPage';
  // M4 P2 知识技能扩展
  static readonly SKILL_POOL: string = 'SkillPoolPage';
  static readonly AIGC: string = 'AIGCPage';
  // M4 P2 协作与工作流
  static readonly WORKFLOW: string = 'WorkflowPage';
  static readonly WORKFLOW_EDIT: string = 'WorkflowEditPage';
  static readonly COLLABORATION: string = 'CollaborationPage';
  static readonly PROJECT: string = 'ProjectPage';
  static readonly TEAM: string = 'TeamPage';
  static readonly TASK: string = 'TaskPage';
  // M4 P2 渠道系统
  static readonly CHANNEL_INTEGRATION: string = 'ChannelIntegrationPage';
  static readonly SESSION_SYNC: string = 'SessionSyncPage';
  // M4 P2 监控与管理
  static readonly STATS: string = 'StatsPage';
  static readonly MONITOR: string = 'MonitorPage';
  static readonly LOG: string = 'LogPage';
  static readonly FILE: string = 'FilePage';
  static readonly NOTIFICATION: string = 'NotificationPage';
  static readonly NEURON: string = 'NeuronPage';
  // M5 P3 协作扩展与市场
  static readonly COLLABORATION_TEMPLATE: string = 'CollaborationTemplatePage';
  static readonly COLLABORATION_HISTORY: string = 'CollaborationHistoryPage';
  static readonly COLLABORATION_INITIATE: string = 'CollaborationInitiatePage';
  static readonly WEBHOOK: string = 'WebhookPage';
  static readonly MARKETPLACE: string = 'MarketplacePage';
  // M5 P3 系统监控扩展
  static readonly AUDIT: string = 'AuditPage';
  static readonly BENCHMARK: string = 'BenchmarkPage';
  static readonly SANDBOX: string = 'SandboxPage';
  static readonly FIREWALL: string = 'FirewallPage';
  // M5 P3 用户与记忆扩展
  // 录音纪要（B4-8：录音 → 纪要 → 问题/办事判定 → 办事落任务看板）
  static readonly VOICE_MINUTES: string = 'VoiceMinutesPage';
}

/** 需要登录才能访问的受保护路由 */
const PROTECTED_ROUTES: string[] = [
  RouteNames.SHELL,
  RouteNames.DASHBOARD,
  RouteNames.AGENT_DETAIL,
  RouteNames.KNOWLEDGE_IMPORT,
  RouteNames.ENTERPRISE_SOURCES,
  RouteNames.GRAPH_PREVIEW,
  RouteNames.ADMIN_USERS,
  RouteNames.ADMIN_GROUPS,
  RouteNames.ADMIN_MARKET,
  RouteNames.ADMIN_SETTINGS,
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
  // M4 P2 能力层（全部受保护）
  RouteNames.AGENT_RULE,
  RouteNames.AGENT_FILE,
  RouteNames.AGENT_MEDIA,
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
  RouteNames.AIGC,
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

  /** 路由栈是否已挂载（Navigation 进入页面后才有内容）——温启动深链据此分流 */
  hasNavStack(): boolean {
    return this.navStack.size() > 0;
  }

  /** 压入新页面 */
  push(routeName: string, params?: Record<string, Object>): boolean {
    if (!canNavigate(routeName, this.authStore)) {
      this.logger.warn('Router', `未授权访问 ${routeName}，跳转登录页`);
      const redirectParam: RedirectParam = { redirect: routeName };
      this.navStack.replacePath(new NavPathInfo(RouteNames.LOGIN, redirectParam));
      return false;
    }
    this.navStack.pushPath(new NavPathInfo(routeName, params));
    this.logger.info('Router', `push → ${routeName}`);
    return true;
  }

  /** 替换当前页面（不可返回） */
  replace(routeName: string, params?: Record<string, Object>): boolean {
    if (!canNavigate(routeName, this.authStore)) {
      this.logger.warn('Router', `未授权访问 ${routeName}，跳转登录页`);
      const redirectParam: RedirectParam = { redirect: routeName };
      this.navStack.replacePath(new NavPathInfo(RouteNames.LOGIN, redirectParam));
      return false;
    }
    this.navStack.replacePath(new NavPathInfo(routeName, params));
    this.logger.info('Router', `replace → ${routeName}`);
    return true;
  }

  /** 返回上一页（栈仅剩根页时不再弹出——防弹空落到无导航占位页） */
  back(): void {
    if (this.navStack.size() <= 1) {
      this.logger.info('Router', 'back at root — no-op');
      return;
    }
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
    if (this.navStack.getAllPathName().length > 0) {
      return this.navStack.getParamByIndex(this.navStack.size() - 1) as Object;
    }
    return undefined;
  }

  /** 获取栈深度 */
  getStackDepth(): number {
    return this.navStack.size();
  }
}
