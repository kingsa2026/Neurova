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

import { GlassStatCard } from '../components/glass';
import { AppIcon } from '../components/common/AppIcon';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AuthStore } from '../libs/state/stores/AuthStore';
import { StateManager } from '../libs/state/StateManager';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router, RouteNames } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { I18nManager } from '../libs/i18n/I18nManager';
import { Agent } from '../libs/types';
import { ChatSession } from '../libs/api/modules/SessionsApi';
import { ServerProfiles } from '../libs/config/ServerProfiles';

/** 仪表盘统计卡数据（/home/data 真实统计映射） */
interface DashboardStats {
  conversations: number;     // 总对话数（stats.conversation_count）
  memories: number;          // 记忆条数（stats.memory_count）
  tokens: number;            // Token 消耗（stats.token_consumption）
  agents: number;            // Agent 数（stats.agent_count）
  onlineAgents: number;      // 在线 Agent 数（agents 列表 status=active 计数）
  backendOk: boolean;        // /home/data 是否成功（健康条唯一事实源，不写死）
}

/** 更多功能入口（2026-11-18 补入口：七域页面此前只有 PageMap 挂载、无导航入口） */
interface DashEntry {
  label: string;
  route: string;
}

/** 更多功能分组 */
interface DashGroup {
  title: string;
  entries: DashEntry[];
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
    backendOk: false
  };
  @State welcomeMessage: string = '';
  // 加载态（控制是否显示"加载中..."占位）
  @State loading: boolean = true;
  // Agent 列表（用于欢迎卡片显示数量）
  @State agents: Agent[] = [];
  // 最近会话（/console/chat/sessions 前 3 条，同源 PC）
  @State recentSessions: ChatSession[] = [];
  // 更多功能分组（七域页面导航入口；route 取 RouteNames 值，PageMap 按值匹配）
  private moreGroups: DashGroup[] = [
    {
      title: '协作', entries: [
        { label: '协作空间', route: RouteNames.COLLABORATION },
        { label: '工作流', route: RouteNames.WORKFLOW },
        { label: '项目', route: RouteNames.PROJECT },
        { label: '团队', route: RouteNames.TEAM },
        { label: '发起协作', route: RouteNames.COLLABORATION_INITIATE },
        { label: 'AIGC 任务', route: RouteNames.AIGC }
      ]
    },
    {
      title: '监控与运维', entries: [
        { label: '运行监控', route: RouteNames.MONITOR },
        { label: '统计', route: RouteNames.STATS },
        { label: '日志', route: RouteNames.LOG },
        { label: '神经元', route: RouteNames.NEURON },
        { label: '健康检查', route: RouteNames.HEALTH },
        { label: '审计', route: RouteNames.AUDIT },
        { label: '基准测试', route: RouteNames.BENCHMARK },
        { label: '沙箱', route: RouteNames.SANDBOX },
        { label: '防火墙', route: RouteNames.FIREWALL }
      ]
    },
    {
      title: '渠道与同步', entries: [
        { label: '渠道集成', route: RouteNames.CHANNEL_INTEGRATION },
        { label: '会话同步', route: RouteNames.SESSION_SYNC },
        { label: 'Webhook', route: RouteNames.WEBHOOK }
      ]
    }
  ];
  // 未读通知数（GET /notifications/unread-count；0 或失败不展示通知条）
  @State unreadCount: number = 0;

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
      this.stats.backendOk = true;
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
      }
    } catch (e) {
      this.logger.warn('DashboardPage', '工作台统计加载失败，保持 0 值', e as Error);
    }

    // 3. 尝试拉取最新 agent 列表（失败时降级使用缓存）；在线数按 status 真实计数
    try {
      this.agents = await this.api.agents.list();
      this.agentsStore.setAgents(this.agents);
    } catch (e) {
      this.logger.warn('DashboardPage', '加载 agent 列表失败，使用缓存', e as Error);
    }
    let online = 0;
    for (const a of this.agents) {
      if (a.status === 'active') {
        online += 1;
      }
    }
    this.stats.onlineAgents = online;

    // 4. 最近会话（同源 PC：/console/chat/sessions 前 3 条）
    try {
      const sres = await this.api.sessions.listAll('');
      if (sres.code === 0 && sres.data) {
        this.recentSessions = sres.data.sessions.slice(0, 3);
      }
    } catch (e) {
      this.logger.warn('DashboardPage', '最近会话加载失败', e as Error);
    }

    // 5. 未读通知数（fail-soft，>0 才展示通知条）
    try {
      const nres = await this.api.monitor.getUnreadCount();
      if (nres.code === 0 && nres.data !== undefined && nres.data !== null) {
        this.unreadCount = Number(nres.data);
      }
    } catch (e) {
      this.logger.warn('DashboardPage', '未读通知数加载失败', e as Error);
    }

    this.loading = false;
  }

  /** 打开最近会话（上下文写入 → CHAT 拉历史） */
  private openRecent(s: ChatSession): void {
    StateManager.getInstance().set('chat:active_session_id', s.id);
    StateManager.getInstance().set('chat:active_session_title', s.title);
    this.router.push(RouteNames.CHAT);
  }

  /** 头部日期行：M月D日 星期X */
  private dateLine(): string {
    const d = new Date();
    const week = ['日', '一', '二', '三', '四', '五', '六'][d.getDay()];
    return (d.getMonth() + 1).toString() + ' 月 ' + d.getDate().toString() + ' 日 星期' + week;
  }

  /** 服务端 UTC ISO → 本地时区 ISO（切片日期/时间前必须过这里，否则晚间会话显示成前一天） */
  private localIso(iso: string): string {
    if (iso.length < 19) {
      return iso;
    }
    const d = new Date(iso);
    if (isNaN(d.getTime())) {
      return iso;
    }
    return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString();
  }

  /** 工作区地址（档案地址去 /api/v1 尾缀） */
  private workspaceHost(): string {
    const base = ServerProfiles.getInstance().getActiveApiBase();
    if (base.length === 0) {
      return '未连接';
    }
    return base.replace('/api/v1', '').replace('http://', '').replace('https://', '');
  }

  /** 获取当前用户名（未登录时回退 '用户'） */
  private getUsername(): string {
    return this.authStore.user?.username ?? '用户';
  }

  /** 健康状态文案：/home/data 成功 → 良好（后端可达），失败 → 未知（不写死） */
  private getHealthLabel(): string {
    return this.stats.backendOk ? '良好' : '未知';
  }

  /** 切到对话 Tab（最近会话「全部」入口，经 AppStorage 与 ShellPage 同步） */
  private gotoSessionsTab(): void {
    AppStorage.setOrCreate('shellTab', 0);
  }

  /** 更多功能分组入口（补入口：七域页面可达性） */
  @Builder
  moreFunctionSection() {
    Row() {
      Text('更多功能')
        .fontSize(this.sm.getFontSize('caption'))
        .fontWeight(FontWeight.Medium)
        .fontColor(this.sm.getColor('text_primary'))
    }
    .width('100%')
    .padding({ left: 4, top: 12, bottom: 2 })

    ForEach(this.moreGroups, (g: DashGroup) => {
      Text(g.title)
        .fontSize(this.sm.getFontSize('badge'))
        .fontColor(this.sm.getColor('text_tertiary'))
        .padding({ left: 4, top: 8, bottom: 4 })
      Flex({ wrap: FlexWrap.Wrap, justifyContent: FlexAlign.SpaceBetween }) {
        ForEach(g.entries, (e: DashEntry) => {
          Row() {
            Text(e.label)
              .fontSize(this.sm.getFontSize('badge'))
              .fontColor(this.sm.getColor('text_secondary'))
            AppIcon({ name: 'chev', iconSize: 10, color: this.sm.getColor('text_tertiary') })
              .margin({ left: 3 })
          }
          .width('31%')
          .padding({ left: 9, right: 6, top: 9, bottom: 9 })
          .borderRadius(10)
          .backgroundColor(this.sm.getColor('glass'))
          .border({ width: 1, color: this.sm.getColor('border') })
          .margin({ bottom: 8 })
          .alignItems(VerticalAlign.Center)
          .onClick(() => { this.router.push(e.route); })
        }, (e: DashEntry) => e.label)
      }
      .width('100%')
    }, (g: DashGroup) => g.title)
  }

  build() {
    Column() {
      // 问候头（原型 F3：21/700 问候 + 日期/工作区 sub）
      Column() {
        Text(this.loading ? '工作台' : '早上好，' + this.getUsername())
          .fontSize(21)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))
        Text(this.dateLine() + ' · 工作区 ' + this.workspaceHost())
          .fontSize(11.5)
          .fontColor(this.sm.getColor('text_tertiary'))
          .margin({ top: 2 })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
      .padding({ left: 20, right: 20, top: 8, bottom: 4 })

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
            // 0. 健康条（原型 F3 hbar：盾牌图标 + 系统健康 + 在线数）
            Row() {
              AppIcon({ name: 'shield', iconSize: 14, color: this.sm.getColor('success') })
              Text('系统健康 ' + this.getHealthLabel() + ' · ' + this.stats.onlineAgents.toString() + ' 个 Agent 在线')
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .margin({ left: 8 })
            }
            .width('100%')
            .padding({ left: 14, right: 14, top: 9, bottom: 9 })
            .borderRadius(12)
            .backgroundColor('rgba(52,211,153,0.07)')
            .border({ width: 1, color: 'rgba(52,211,153,0.25)' })

            // 0.5 通知条（未读 >0 才展示；铃铛 + N 条未读）
            if (this.unreadCount > 0) {
              Row() {
                AppIcon({ name: 'bell', iconSize: 15, color: this.sm.getColor('accent') })
                Text(this.unreadCount.toString() + ' 条未读通知')
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('text_secondary'))
                  .margin({ left: 8 })
              }
              .width('100%')
              .padding({ left: 13, right: 13, top: 10, bottom: 10 })
              .borderRadius(12)
              .backgroundColor('rgba(34,211,238,0.06)')
              .border({ width: 1, color: 'rgba(34,211,238,0.22)' })
              .margin({ top: 10 })
            }

            // 1. 统计卡 2×2（真实统计：总对话/记忆条数/Token 消耗/在线 Agent）
            Flex({ wrap: FlexWrap.Wrap, justifyContent: FlexAlign.SpaceBetween }) {
              GlassStatCard({ label: '总对话', value: String(this.stats.conversations) })
                .width('48%')
                .margin({ bottom: this.sm.getSpacing('md') })

              GlassStatCard({ label: '记忆条数', value: String(this.stats.memories) })
                .width('48%')
                .margin({ bottom: this.sm.getSpacing('md') })

              GlassStatCard({ label: 'Token 消耗', value: String(this.stats.tokens) })
                .width('48%')
                .margin({ bottom: this.sm.getSpacing('md') })

              GlassStatCard({ label: '在线 Agent', value: String(this.stats.onlineAgents), trend: '共 ' + this.stats.agents.toString() + ' 个', trendNeutral: true })
                .width('48%')
                .margin({ bottom: this.sm.getSpacing('md') })
            }
            .width('100%')
            .margin({ bottom: this.sm.getSpacing('md') })

            // 2. 快捷操作（原型 F3 qa：四宫格带单线图标）
            Row() {
              Text('快捷操作')
                .fontSize(this.sm.getFontSize('caption'))
                .fontWeight(FontWeight.Medium)
                .fontColor(this.sm.getColor('text_primary'))
            }
            .width('100%')
            .padding({ left: 4, bottom: 8 })

            Row() {
              Column() {
                AppIcon({ name: 'chat', iconSize: 24, color: this.sm.getColor('primary') })
                Text('新建对话')
                  .fontSize(this.sm.getFontSize('badge'))
                  .fontColor(this.sm.getColor('text_secondary'))
                  .margin({ top: 6 })
              }
              .layoutWeight(1)
              .padding({ top: 12, bottom: 12 })
              .borderRadius(14)
              .backgroundColor(this.sm.getColor('glass'))
              .border({ width: 1, color: this.sm.getColor('border') })
              .onClick(() => {
                StateManager.getInstance().set('chat:active_session_id', '');
                this.router.push(RouteNames.CHAT);
              })

              Column() {
                AppIcon({ name: 'agent', iconSize: 24, color: this.sm.getColor('primary') })
                Text('创建智能体')
                  .fontSize(this.sm.getFontSize('badge'))
                  .fontColor(this.sm.getColor('text_secondary'))
                  .margin({ top: 6 })
              }
              .layoutWeight(1)
              .padding({ top: 12, bottom: 12 })
              .borderRadius(14)
              .backgroundColor(this.sm.getColor('glass'))
              .border({ width: 1, color: this.sm.getColor('border') })
              .margin({ left: 10 })
              .onClick(() => {
                this.router.push(RouteNames.AGENT_FORM);
              })

              Column() {
                AppIcon({ name: 'clip', iconSize: 24, color: this.sm.getColor('primary') })
                Text('上传文件')
                  .fontSize(this.sm.getFontSize('badge'))
                  .fontColor(this.sm.getColor('text_secondary'))
                  .margin({ top: 6 })
              }
              .layoutWeight(1)
              .padding({ top: 12, bottom: 12 })
              .borderRadius(14)
              .backgroundColor(this.sm.getColor('glass'))
              .border({ width: 1, color: this.sm.getColor('border') })
              .margin({ left: 10 })
              .onClick(() => {
                this.router.push(RouteNames.KNOWLEDGE_IMPORT);
              })

              Column() {
                AppIcon({ name: 'scan', iconSize: 24, color: this.sm.getColor('primary') })
                Text('扫码配对')
                  .fontSize(this.sm.getFontSize('badge'))
                  .fontColor(this.sm.getColor('text_secondary'))
                  .margin({ top: 6 })
              }
              .layoutWeight(1)
              .padding({ top: 12, bottom: 12 })
              .borderRadius(14)
              .backgroundColor(this.sm.getColor('glass'))
              .border({ width: 1, color: this.sm.getColor('border') })
              .margin({ left: 10 })
              .onClick(() => {
                this.router.push(RouteNames.PAIRING);
              })
            }
            .width('100%')

            // 3. 最近会话（原型 F3 mini-sess：标题 + 「全部›」入对话 Tab）
            Row() {
              Text('最近会话')
                .fontSize(this.sm.getFontSize('caption'))
                .fontWeight(FontWeight.Medium)
                .fontColor(this.sm.getColor('text_primary'))
              Row() {
                Text('全部')
                  .fontSize(this.sm.getFontSize('badge'))
                  .fontColor(this.sm.getColor('primary'))
                AppIcon({ name: 'chev', iconSize: 12, color: this.sm.getColor('primary') })
              }
              .alignItems(VerticalAlign.Center)
              .margin({ left: 'auto' })
              .onClick(() => { this.gotoSessionsTab(); })
            }
            .width('100%')
            .padding({ left: 4, bottom: 8 })

            Column() {
              if (this.recentSessions.length === 0) {
                Text('暂无会话')
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('text_tertiary'))
                  .padding(14)
              }
              ForEach(this.recentSessions, (s: ChatSession) => {
                Row() {
                  Text(s.title.slice(0, 1))
                    .fontSize(12)
                    .fontWeight(FontWeight.Bold)
                    .fontColor(this.sm.getColor('text_on_primary'))
                    .width(30)
                    .height(30)
                    .borderRadius(10)
                    .textAlign(TextAlign.Center)
                    .linearGradient({ angle: 135, colors: [[this.sm.getColor('secondary'), 0], [this.sm.getColor('primary'), 1]] })
                  Column() {
                    Row() {
                      Text(s.title)
                        .fontSize(this.sm.getFontSize('body_sm'))
                        .fontWeight(FontWeight.Medium)
                        .fontColor(this.sm.getColor('text_primary'))
                        .maxLines(1)
                        .textOverflow({ overflow: TextOverflow.Ellipsis })
                      if (s.pinned) {
                        AppIcon({ name: 'pin', iconSize: 12, color: this.sm.getColor('primary') })
                          .margin({ left: 5 })
                      }
                    }
                    .alignItems(VerticalAlign.Center)
                    Text((s.updated_at.length >= 10 ? this.localIso(s.updated_at).slice(5, 10) : s.updated_at) + ' · ' + s.agent_id)
                      .fontSize(this.sm.getFontSize('badge'))
                      .fontColor(this.sm.getColor('text_tertiary'))
                      .margin({ top: 2 })
                  }
                  .layoutWeight(1)
                  .alignItems(HorizontalAlign.Start)
                  .margin({ left: 10 })
                  Text(s.updated_at.length >= 10 ? this.localIso(s.updated_at).slice(11, 16) : '')
                    .fontSize(this.sm.getFontSize('badge'))
                    .fontColor(this.sm.getColor('text_tertiary'))
                }
                .width('100%')
                .padding(11)
                .borderRadius(13)
                .backgroundColor(this.sm.getColor('glass'))
                .border({ width: 1, color: s.pinned ? this.sm.getColor('primary') : this.sm.getColor('border') })
                .margin({ bottom: 8 })
                .onClick(() => {
                  this.openRecent(s);
                })
              }, (s: ChatSession) => s.id + s.updated_at)
            }
            .width('100%')

            // 4. 更多功能（七域页面导航入口，2026-11-18 补入口批）
            this.moreFunctionSection()
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
    
  }
}
