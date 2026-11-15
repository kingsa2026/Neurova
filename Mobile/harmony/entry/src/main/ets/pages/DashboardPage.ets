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

/** 仪表盘统计卡数据（/home/data 真实统计映射） */
interface DashboardStats {
  conversations: number;     // 总对话数（stats.conversation_count）
  memories: number;          // 记忆条数（stats.memory_count）
  tokens: number;            // Token 消耗（stats.token_consumption）
  agents: number;            // Agent 数（stats.agent_count）
  onlineAgents: number;      // 在线 Agent 数（agents 列表加载后填充）
  healthStatus: string;      // 系统健康状态：healthy / unhealthy
}

@Component
export struct DashboardPage {
  // 统计数据（GET /home/data 真实统计；加载期 0 值占位）
  @State stats: DashboardStats = {
    conversations: 0,
    memories: 0,
    tokens: 0,
    agents: 0,
    onlineAgents: 0,
    healthStatus: 'healthy'
  };
  @State welcomeMessage: string = '';
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
   * 流程：先用 store 缓存填充 agents → 并行拉 /home/data 真实统计与 agent 列表
   * 异常：API 失败时降级使用缓存数据（0 值），不影响页面渲染
   */
  private async loadDashboard(): Promise<void> {
    // 1. 先用 store 缓存填充，保证页面快速渲染
    this.agents = this.agentsStore.agents;

    // 2. /home/data 真实统计（home.py：stats.{conversation_count,memory_count,
    //    token_consumption,agent_count}；quick_stats 为逐调用者口径）
    try {
      const home = await this.api.home.data();
      this.welcomeMessage = home.welcome_message;
      const st = home.stats;
      if (st['conversation_count']) {
        this.stats.conversations = Number(st['conversation_count']);
      }
      if (st['memory_count']) {
        this.stats.memories = Number(st['memory_count']);
      }
      if (st['token_consumption']) {
        this.stats.tokens = Number(st['token_consumption']);
      }
      if (st['agent_count']) {
        this.stats.agents = Number(st['agent_count']);
        this.stats.onlineAgents = Number(st['agent_count']);
      }
    } catch (e) {
      this.logger.warn('DashboardPage', '工作台统计加载失败，保持 0 值', e as Error);
    }

    // 3. 尝试拉取最新 agent 列表（失败时降级使用缓存）
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
            Column() {
              GlassCard({ title: `欢迎，${this.getUsername()}` }) {
                Text(`你有 ${this.agents.length} 个智能体`)
                  .fontSize(this.sm.getFontSize('body'))
                  .fontColor(this.sm.getColor('text_secondary'))
              }
            }
            .width('100%')
            .margin({ bottom: this.sm.getSpacing('md') })

            // 2. 统计卡片网格（2x2，Flex wrap 自适应窄屏）
            Flex({ wrap: FlexWrap.Wrap, justifyContent: FlexAlign.SpaceBetween }) {
              GlassStatCard({ label: '总对话', value: String(this.stats.conversations) })
                .width('48%')
                .margin({ bottom: this.sm.getSpacing('md') })

              GlassStatCard({ label: '记忆条数', value: String(this.stats.memories) })
                .width('48%')
                .margin({ bottom: this.sm.getSpacing('md') })

              GlassStatCard({ label: '在线Agent', value: String(this.stats.onlineAgents) })
              GlassStatCard({ label: 'Agent 总数', value: String(this.stats.agents) })
                .width('48%')
                .margin({ bottom: this.sm.getSpacing('md') })

              GlassStatCard({ label: '系统状态', value: this.getHealthLabel() })
                .width('48%')
                .margin({ bottom: this.sm.getSpacing('md') })
            }
            .width('100%')
            .margin({ bottom: this.sm.getSpacing('md') })

            // 3. 快捷操作：三个等宽按钮，跳转对应页面
            Column() {
              GlassCard({ title: '快捷操作' }) {
                Row() {
                  GlassButton({
                    text: '新建对话',
                    type: 'default',
                    btnSize: 'medium',
                    onTap: () => { this.router.push(RouteNames.CHAT); }
                  })
                    .layoutWeight(1)

                  GlassButton({
                    text: '管理 Agent',
                    type: 'default',
                    btnSize: 'medium',
                    onTap: () => { this.router.push(RouteNames.AGENT_LIST); }
                  })
                    .layoutWeight(1)
                    .margin({ left: this.sm.getSpacing('sm') })

                  GlassButton({
                    text: '配对设备',
                    type: 'default',
                    btnSize: 'medium',
                    onTap: () => { this.router.push(RouteNames.PAIRING); }
                  })
                    .layoutWeight(1)
                    .margin({ left: this.sm.getSpacing('sm') })
                }
                .width('100%')
              }
            }
            .width('100%')
            .margin({ bottom: this.sm.getSpacing('md') })

            // 4. 最近会话列表（M2 暂为空状态占位，M3 接入 sessions API）
            Column() {
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
