/**
 * MainLayout - 主布局
 *
 * 职责：应用主框架，含侧边栏 + 顶部栏 + 内容区
 * 设计：响应式（手机/平板），手机时侧边栏隐藏抽屉式
 */

import { GlassNav, GlassNavItem, TopNavMenu } from '../components/glass';
import { Router, RouteNames } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { AppStore } from '../libs/state/stores/AppStore';
import { Logger } from '../libs/logger/Logger';

@Component
export struct MainLayout {
  @State currentRoute: string = RouteNames.DASHBOARD;
  @State sidebarCollapsed: boolean = false;
  private sm: StyleManager = StyleManager.getInstance();
  private appStore: AppStore = new AppStore();
  private logger: Logger = Logger.getInstance();

  aboutToAppear() {
    this.sidebarCollapsed = this.appStore.sidebarCollapsed;
  }

  private navigateTo(route: string): void {
    this.currentRoute = route;
    Router.getInstance().replace(route);
    this.logger.info('MainLayout', `导航到 ${route}`);
  }

  @Builder
  navItems() {
    GlassNavItem({ label: '仪表盘', active: this.currentRoute === RouteNames.DASHBOARD, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.DASHBOARD))
    GlassNavItem({ label: '对话', active: this.currentRoute === RouteNames.CHAT, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.CHAT))
    GlassNavItem({ label: '智能体', active: this.currentRoute === RouteNames.AGENT_LIST, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.AGENT_LIST))
    GlassNavItem({ label: '记忆', active: this.currentRoute === RouteNames.MEMORY, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.MEMORY))
    GlassNavItem({ label: '知识库', active: this.currentRoute === RouteNames.KNOWLEDGE, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.KNOWLEDGE))
    GlassNavItem({ label: '模型', active: this.currentRoute === RouteNames.MODEL, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.MODEL))
    GlassNavItem({ label: '渠道', active: this.currentRoute === RouteNames.AGENT_CHANNEL, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.AGENT_CHANNEL))
    GlassNavItem({ label: '健康', active: this.currentRoute === RouteNames.HEALTH, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.HEALTH))
    // M4 P2 认知层
    GlassNavItem({ label: '经验知识', active: this.currentRoute === RouteNames.EXPERIENCE_KNOWLEDGE, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.EXPERIENCE_KNOWLEDGE))
    GlassNavItem({ label: '知识图谱', active: this.currentRoute === RouteNames.KNOWLEDGE_GRAPH, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.KNOWLEDGE_GRAPH))
    GlassNavItem({ label: '元认知', active: this.currentRoute === RouteNames.METACOGNITION, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.METACOGNITION))
    GlassNavItem({ label: '反思', active: this.currentRoute === RouteNames.REFLECTION, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.REFLECTION))
    GlassNavItem({ label: '成长', active: this.currentRoute === RouteNames.GROWTH, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.GROWTH))
    // M4 P2 能力层
    GlassNavItem({ label: '规则', active: this.currentRoute === RouteNames.AGENT_RULE, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.AGENT_RULE))
    GlassNavItem({ label: '文件', active: this.currentRoute === RouteNames.AGENT_FILE, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.AGENT_FILE))
    GlassNavItem({ label: '媒体', active: this.currentRoute === RouteNames.AGENT_MEDIA, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.AGENT_MEDIA))
    // M4 P2 个性层
    GlassNavItem({ label: '情绪', active: this.currentRoute === RouteNames.AGENT_EMOTION, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.AGENT_EMOTION))
    GlassNavItem({ label: '个性', active: this.currentRoute === RouteNames.AGENT_PERSONALITY, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.AGENT_PERSONALITY))
    // M4 P2 运行时层
    GlassNavItem({ label: '调度', active: this.currentRoute === RouteNames.AGENT_SCHEDULER, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.AGENT_SCHEDULER))
    GlassNavItem({ label: '上下文', active: this.currentRoute === RouteNames.CONTEXT_CHANNEL, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.CONTEXT_CHANNEL))
    GlassNavItem({ label: '计算机', active: this.currentRoute === RouteNames.AGENT_COMPUTER, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.AGENT_COMPUTER))
    GlassNavItem({ label: '追踪', active: this.currentRoute === RouteNames.AGENT_TRACE, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.AGENT_TRACE))
    GlassNavItem({ label: '轨迹', active: this.currentRoute === RouteNames.AGENT_TRAJECTORY, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.AGENT_TRAJECTORY))
    GlassNavItem({ label: '休眠状态', active: this.currentRoute === RouteNames.SLEEP_STATUS, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.SLEEP_STATUS))
    GlassNavItem({ label: '休眠设置', active: this.currentRoute === RouteNames.SLEEP_SETTINGS, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.SLEEP_SETTINGS))
    GlassNavItem({ label: '防火墙', active: this.currentRoute === RouteNames.AGENT_FIREWALL, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.AGENT_FIREWALL))
    // M4 P2 知识技能扩展
    GlassNavItem({ label: '技能池', active: this.currentRoute === RouteNames.SKILL_POOL, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.SKILL_POOL))
    GlassNavItem({ label: '技能市场', active: this.currentRoute === RouteNames.SKILL_MARKET, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.SKILL_MARKET))
    GlassNavItem({ label: 'AIGC', active: this.currentRoute === RouteNames.AIGC, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.AIGC))
    GlassNavItem({ label: '工具层', active: this.currentRoute === RouteNames.TOOL_LAYER, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.TOOL_LAYER))
    // M4 P2 协作与工作流
    GlassNavItem({ label: '工作流', active: this.currentRoute === RouteNames.WORKFLOW, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.WORKFLOW))
    GlassNavItem({ label: '协作', active: this.currentRoute === RouteNames.COLLABORATION, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.COLLABORATION))
    GlassNavItem({ label: '项目', active: this.currentRoute === RouteNames.PROJECT, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.PROJECT))
    GlassNavItem({ label: '团队', active: this.currentRoute === RouteNames.TEAM, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.TEAM))
    GlassNavItem({ label: '任务', active: this.currentRoute === RouteNames.TASK, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.TASK))
    // M4 P2 渠道系统
    GlassNavItem({ label: '渠道集成', active: this.currentRoute === RouteNames.CHANNEL_INTEGRATION, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.CHANNEL_INTEGRATION))
    GlassNavItem({ label: '会话同步', active: this.currentRoute === RouteNames.SESSION_SYNC, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.SESSION_SYNC))
    // M4 P2 监控与管理
    GlassNavItem({ label: '统计', active: this.currentRoute === RouteNames.STATS, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.STATS))
    GlassNavItem({ label: '监控', active: this.currentRoute === RouteNames.MONITOR, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.MONITOR))
    GlassNavItem({ label: '日志', active: this.currentRoute === RouteNames.LOG, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.LOG))
    GlassNavItem({ label: '文件', active: this.currentRoute === RouteNames.FILE, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.FILE))
    GlassNavItem({ label: '通知', active: this.currentRoute === RouteNames.NOTIFICATION, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.NOTIFICATION))
    GlassNavItem({ label: '神经元', active: this.currentRoute === RouteNames.NEURON, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.NEURON))
    // M5 P3 协作扩展与市场
    GlassNavItem({ label: '协作模板', active: this.currentRoute === RouteNames.COLLABORATION_TEMPLATE, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.COLLABORATION_TEMPLATE))
    GlassNavItem({ label: '协作历史', active: this.currentRoute === RouteNames.COLLABORATION_HISTORY, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.COLLABORATION_HISTORY))
    GlassNavItem({ label: '发起协作', active: this.currentRoute === RouteNames.COLLABORATION_INITIATE, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.COLLABORATION_INITIATE))
    GlassNavItem({ label: 'Webhook', active: this.currentRoute === RouteNames.WEBHOOK, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.WEBHOOK))
    GlassNavItem({ label: '市场', active: this.currentRoute === RouteNames.MARKETPLACE, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.MARKETPLACE))
    // M5 P3 系统监控扩展
    GlassNavItem({ label: '审计', active: this.currentRoute === RouteNames.AUDIT, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.AUDIT))
    GlassNavItem({ label: '基准测试', active: this.currentRoute === RouteNames.BENCHMARK, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.BENCHMARK))
    GlassNavItem({ label: '沙箱', active: this.currentRoute === RouteNames.SANDBOX, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.SANDBOX))
    GlassNavItem({ label: '系统防火墙', active: this.currentRoute === RouteNames.FIREWALL, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.FIREWALL))
    GlassNavItem({ label: '分析', active: this.currentRoute === RouteNames.ANALYTICS, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.ANALYTICS))
    // M5 P3 用户与记忆扩展
    GlassNavItem({ label: '用户组', active: this.currentRoute === RouteNames.GROUP, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.GROUP))
    GlassNavItem({ label: '增强用户', active: this.currentRoute === RouteNames.ENHANCED_USER, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.ENHANCED_USER))
    GlassNavItem({ label: '智能体技能', active: this.currentRoute === RouteNames.AGENT_SKILL, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.AGENT_SKILL))
    GlassNavItem({ label: '记忆设置', active: this.currentRoute === RouteNames.MEMORY_SETTINGS, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.MEMORY_SETTINGS))
    GlassNavItem({ label: '记忆检索设置', active: this.currentRoute === RouteNames.MEMORY_SEARCH_SETTINGS, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.MEMORY_SEARCH_SETTINGS))
    GlassNavItem({ label: '配对', active: this.currentRoute === RouteNames.PAIRING, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.PAIRING))
    GlassNavItem({ label: '设置', active: this.currentRoute === RouteNames.SETTINGS, collapsed: this.sidebarCollapsed })
      .onClick(() => this.navigateTo(RouteNames.SETTINGS))
  }

  build() {
    Row() {
      // 侧边栏（平板/桌面显示）
      if (this.sidebarCollapsed) {
        GlassNav({ title: 'Neurova', collapsed: true, width: 240 }) {
          this.navItems();
        }
        .width(120)
      } else {
        GlassNav({ title: 'Neurova', collapsed: false, width: 240 }) {
          this.navItems();
        }
        .width(240)
      }

      // 主内容区
      Column() {
        // 顶部栏
        TopNavMenu({
          title: this.currentRouteName(),
          showBack: false,
          showMenu: true,
          onMenu: () => {
            this.sidebarCollapsed = !this.sidebarCollapsed;
            this.appStore.setSidebarCollapsed(this.sidebarCollapsed);
          }
        })

        // 路由出口（NavDestination 由 Router 控制）
        Navigation(Router.getInstance().getNavStack()) {
          // 默认占位
          Column() {
            Text('加载中...')
              .fontSize(16)
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .height('100%')
          .justifyContent(FlexAlign.Center)
        }
        .hideTitleBar(true)
        .mode(NavigationMode.Stack)
        .layoutWeight(1)
      }
      .layoutWeight(1)
      .height('100%')
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('background'))
  }

  private currentRouteName(): string {
    const map: Record<string, string> = {
      [RouteNames.DASHBOARD]: '仪表盘',
      [RouteNames.CHAT]: '对话',
      [RouteNames.AGENT_LIST]: '智能体',
      [RouteNames.AGENT_FORM]: '智能体表单',
      [RouteNames.MEMORY]: '记忆',
      [RouteNames.KNOWLEDGE]: '知识库',
      [RouteNames.MODEL]: '模型',
      [RouteNames.AGENT_CHANNEL]: '渠道',
      [RouteNames.HEALTH]: '健康',
      // M4 P2 认知层
      [RouteNames.EXPERIENCE_KNOWLEDGE]: '经验知识',
      [RouteNames.KNOWLEDGE_GRAPH]: '知识图谱',
      [RouteNames.METACOGNITION]: '元认知',
      [RouteNames.REFLECTION]: '反思',
      [RouteNames.GROWTH]: '成长',
      // M4 P2 能力层
      [RouteNames.AGENT_RULE]: '规则',
      [RouteNames.AGENT_FILE]: '文件',
      [RouteNames.AGENT_MEDIA]: '媒体',
      // M4 P2 个性层
      [RouteNames.AGENT_EMOTION]: '情绪',
      [RouteNames.AGENT_PERSONALITY]: '个性',
      // M4 P2 运行时层
      [RouteNames.AGENT_SCHEDULER]: '调度',
      [RouteNames.CONTEXT_CHANNEL]: '上下文',
      [RouteNames.AGENT_COMPUTER]: '计算机',
      [RouteNames.AGENT_TRACE]: '追踪',
      [RouteNames.AGENT_TRAJECTORY]: '轨迹',
      [RouteNames.SLEEP_STATUS]: '休眠状态',
      [RouteNames.SLEEP_SETTINGS]: '休眠设置',
      [RouteNames.AGENT_FIREWALL]: '防火墙',
      // M4 P2 知识技能扩展
      [RouteNames.SKILL_POOL]: '技能池',
      [RouteNames.SKILL_MARKET]: '技能市场',
      [RouteNames.AIGC]: 'AIGC',
      [RouteNames.TOOL_LAYER]: '工具层',
      // M4 P2 协作与工作流
      [RouteNames.WORKFLOW]: '工作流',
      [RouteNames.COLLABORATION]: '协作',
      [RouteNames.PROJECT]: '项目',
      [RouteNames.TEAM]: '团队',
      [RouteNames.TASK]: '任务',
      // M4 P2 渠道系统
      [RouteNames.CHANNEL_INTEGRATION]: '渠道集成',
      [RouteNames.SESSION_SYNC]: '会话同步',
      // M4 P2 监控与管理
      [RouteNames.STATS]: '统计',
      [RouteNames.MONITOR]: '监控',
      [RouteNames.LOG]: '日志',
      [RouteNames.FILE]: '文件',
      [RouteNames.NOTIFICATION]: '通知',
      [RouteNames.NEURON]: '神经元',
      // M5 P3 协作扩展与市场
      [RouteNames.COLLABORATION_TEMPLATE]: '协作模板',
      [RouteNames.COLLABORATION_HISTORY]: '协作历史',
      [RouteNames.COLLABORATION_INITIATE]: '发起协作',
      [RouteNames.WEBHOOK]: 'Webhook',
      [RouteNames.MARKETPLACE]: '市场',
      // M5 P3 系统监控扩展
      [RouteNames.AUDIT]: '审计',
      [RouteNames.BENCHMARK]: '基准测试',
      [RouteNames.SANDBOX]: '沙箱',
      [RouteNames.FIREWALL]: '系统防火墙',
      [RouteNames.ANALYTICS]: '分析',
      // M5 P3 用户与记忆扩展
      [RouteNames.GROUP]: '用户组',
      [RouteNames.ENHANCED_USER]: '增强用户',
      [RouteNames.AGENT_SKILL]: '智能体技能',
      [RouteNames.MEMORY_SETTINGS]: '记忆设置',
      [RouteNames.MEMORY_SEARCH_SETTINGS]: '记忆检索设置',
      [RouteNames.PAIRING]: '配对',
      [RouteNames.SETTINGS]: '设置',
      [RouteNames.LOGIN]: '登录',
      [RouteNames.REGISTER]: '注册',
    };
    return map[this.currentRoute] ?? 'Neurova';
  }
}
