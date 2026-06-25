/**
 * DashboardPage - 仪表盘页
 *
 * 职责：应用主入口页，展示用户欢迎信息、核心统计指标、快捷操作入口、最近会话
 * 设计：Column [TopNavMenu] + Scroll [Column [欢迎卡片] + [统计网格 2x2] + [快捷操作] + [最近会话]]；
 *       统计数据 M2 阶段硬编码，M3 接入真实 API；
 *       颜色统一走 StyleManager，路由跳转走 Router，日志走 Logger
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassStatCard、GlassButton
 *   - ../libs/api/ApiFacade：统一 API 门面（加载 Agent 列表）
 *   - ../libs/state/stores/AuthStore、AgentsStore：认证与 Agent 状态
 *   - ../routing/Router：统一路由跳转 + RouteNames
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/i18n/I18nManager：统一国际化
 */

import { TopNavMenu, GlassCard, GlassStatCard, GlassButton } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AuthStore } from '../libs/state/stores/AuthStore';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router, RouteNames } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { I18nManager } from '../libs/i18n/I18nManager';
import { Agent } from '../libs/types';

/** 仪表盘统计数据 */
interface DashboardStats {
  totalSessions: number;     // 总对话数
  totalMessages: number;     // 总消息数
  onlineAgents: number;      // 在线 Agent 数
  healthStatus: string;      // 系统健康状态：healthy / unhealthy
}

@Component
export struct DashboardPage {
  // 统计数据（M2 硬编码，M3 接入真实 API）
  @State stats: DashboardStats = {
    totalSessions: 42,
    totalMessages: 328,
    onlineAgents: 3,
    healthStatus: 'healthy'
  };
  // 加载态（控制是否显示"加载中..."占位）
  @State loading: boolean = true;
  // Agent 列表（用于欢迎卡片显示数量）
  @State agents: Agent[] = [];

  // 统一库单例
  private api = ApiFacade.getInstance();
  private authStore = new AuthStore();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private i18n = I18nManager.getInstance();

  aboutToAppear() {
    this.loadDashboard();
  }

  /**
   * 加载仪表盘数据
   * 流程：先用 store 缓存填充 agents → 尝试调用 API 刷新 → 关闭 loading
   * 异常：API 失败时降级使用缓存数据，不影响页面渲染
   * 说明：4 项统计指标 M2 阶段硬编码，M3 阶段在此接入真实 API
   */
  private async loadDashboard(): Promise<void> {
    // 1. 先用 store 缓存填充，保证页面快速渲染
    this.agents = this.agentsStore.agents;

    // 2. 尝试拉取最新 agent 列表（失败时降级使用缓存）
    try {
      const res = await this.api.agents.list({ page: 1, size: 100 });
      if (res.code === 0 && res.data) {
        this.agents = res.data.items;
        this.agentsStore.setAgents(this.agents);
      }
    } catch (e) {
      this.logger.warn('DashboardPage', '加载 agent 列表失败，使用缓存', e as Error);
    }

    this.loading = false;
  }

  /** 获取当前用户名（未登录时回退 '用户'） */
  private getUsername(): string {
    return this.authStore.user?.username ?? '用户';
  }

  /** 健康状态文案映射：healthy → 健康，其他 → 异常 */
  private getHealthLabel(): string {
    return this.stats.healthStatus === 'healthy' ? '健康' : '异常';
  }

  build() {
    Column() {
      // 顶部导航栏：标题"仪表盘"，不显示返回按钮
      TopNavMenu({ title: '仪表盘', showBack: false, showMenu: true })

      if (this.loading) {
        // 加载态：居中显示"加载中..."
        Column() {
          Text(this.i18n.t('common_loading'))
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else {
        // 内容滚动区
        Scroll() {
          Column() {
            // 1. 欢迎卡片：显示用户名 + Agent 数量
            GlassCard({ title: `欢迎，${this.getUsername()}` }) {
              Text(`你有 ${this.agents.length} 个智能体`)
                .fontSize(this.sm.getFontSize('body'))
                .fontColor(this.sm.getColor('text_secondary'))
            }
            .width('100%')
            .margin({ bottom: this.sm.getSpacing('md') })

            // 2. 统计卡片网格（2x2，Flex wrap 自适应窄屏）
            Flex({ wrap: FlexWrap.Wrap, justifyContent: FlexAlign.SpaceBetween }) {
              GlassStatCard({ label: '总对话', value: String(this.stats.totalSessions) })
                .width('48%')
                .margin({ bottom: this.sm.getSpacing('md') })

              GlassStatCard({ label: '总消息', value: String(this.stats.totalMessages) })
                .width('48%')
                .margin({ bottom: this.sm.getSpacing('md') })

              GlassStatCard({ label: '在线Agent', value: String(this.stats.onlineAgents) })
                .width('48%')
                .margin({ bottom: this.sm.getSpacing('md') })

              GlassStatCard({ label: '系统状态', value: this.getHealthLabel() })
                .width('48%')
                .margin({ bottom: this.sm.getSpacing('md') })
            }
            .width('100%')
            .margin({ bottom: this.sm.getSpacing('md') })

            // 3. 快捷操作：三个等宽按钮，跳转对应页面
            GlassCard({ title: '快捷操作' }) {
              Row() {
                GlassButton({
                  text: '新建对话',
                  type: 'default',
                  size: 'medium',
                  onClick: () => { this.router.push(RouteNames.CHAT); }
                })
                  .layoutWeight(1)

                GlassButton({
                  text: '管理 Agent',
                  type: 'default',
                  size: 'medium',
                  onClick: () => { this.router.push(RouteNames.AGENT_LIST); }
                })
                  .layoutWeight(1)
                  .margin({ left: this.sm.getSpacing('sm') })

                GlassButton({
                  text: '配对设备',
                  type: 'default',
                  size: 'medium',
                  onClick: () => { this.router.push(RouteNames.PAIRING); }
                })
                  .layoutWeight(1)
                  .margin({ left: this.sm.getSpacing('sm') })
              }
              .width('100%')
            }
            .width('100%')
            .margin({ bottom: this.sm.getSpacing('md') })

            // 4. 最近会话列表（M2 暂为空状态占位，M3 接入 sessions API）
            GlassCard({ title: '最近会话' }) {
              Column() {
                Text('暂无最近会话')
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('text_disabled'))
              }
              .width('100%')
              .alignItems(HorizontalAlign.Center)
              .padding(this.sm.getSpacing('lg'))
            }
            .width('100%')
          }
          .width('100%')
          .padding(this.sm.getSpacing('md'))
          .alignItems(HorizontalAlign.Start)
        }
        .layoutWeight(1)
        .width('100%')
        .scrollBar(BarState.Off)
        .align(Alignment.TopStart)
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('background'))
  }
}
