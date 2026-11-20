/**
 * AgentListPage - 智能体列表页
 *
 * 职责：展示用户所有智能体，支持进入对话、编辑、删除操作
 * 设计：Column [TopNavMenu(标题+创建按钮)] + [加载态/空态/列表]；
 *       列表项为 GlassCard，包含头像、名称、描述、状态、最后活跃时间、操作按钮；
 *       删除操作需二次确认（AlertDialog）；创建/编辑 M3 实现，当前提示"功能开发中"；
 *       颜色统一走 StyleManager，路由走 Router，API 走 ApiFacade，状态走 AgentsStore
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton
 *   - ../libs/api/ApiFacade：统一 API 门面（加载/删除 Agent）
 *   - ../libs/state/stores/AgentsStore：Agent 状态管理（写入列表、切换当前）
 *   - ../routing/Router：统一路由跳转 + RouteNames
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：Agent、AgentStatus
 *
 * 用法：
 *   由 Router.push(RouteNames.AGENT_LIST) 跳转进入；
 *   点击"对话"切换当前 Agent 并 replace 到 ChatPage；
 *   点击"创建"/"编辑"提示"功能开发中"（M3 实现）；
 *   点击"删除"弹出 AlertDialog 二次确认后调用 API 删除并刷新列表
 */

import { GlassButton } from '../components/glass';
import { AppIcon } from '../components/common/AppIcon';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router, RouteNames } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { Agent, AgentStatus } from '../libs/types';
import { SimpleDataSource } from '../libs/perf/SimpleDataSource';

/** 日志标签 */
const TAG = 'AgentListPage';

@Component
export struct AgentListPage {
  // 智能体列表数据源（M5.2.2 改为 LazyForEach + DataSource 惰性渲染）
  private agentsDs: SimpleDataSource<Agent> = new SimpleDataSource<Agent>();
  // 加载态（控制"加载中..."占位与列表的切换）
  @State loading: boolean = true;
  // 头部计数（@State 驱动：agentsDs 非 @State，直接读它页头不会刷新）
  @State agentTotal: number = 0;
  @State agentOnline: number = 0;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadAgents();
  }

  /**
   * 加载智能体列表
   * 流程：调用 API 获取列表 → 写回 store → 关闭 loading
   * 异常：记录日志并提示用户；无论成败 finally 关闭 loading
   */
  private async loadAgents(): Promise<void> {
    this.loading = true;
    try {
      const agents = await this.api.agents.list();
      this.agentsDs.setData(agents);
      this.agentsStore.setAgents(agents);
      this.agentTotal = agents.length;
      let online = 0;
      for (const a of agents) {
        if (a.status === 'active') {
          online += 1;
        }
      }
      this.agentOnline = online;
    } catch (e) {
      this.logger.error(TAG, '加载失败', e as Error);
      this.msg.error('加载智能体失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 切换到指定智能体并进入对话页
   * 流程：写入 store 当前 Agent → 路由 replace 到 ChatPage（不可返回列表，避免栈过深）
   */
  private switchAgent(agentId: string): void {
    this.agentsStore.switchAgent(agentId);
    this.router.replace(RouteNames.CHAT);
  }

  /**
   * 创建智能体（进 AgentFormPage create 模式）
   */
  private handleCreate(): void {
    this.router.push(RouteNames.AGENT_FORM, { 'mode': 'create' });
  }

  /**
   * 编辑智能体（进 AgentFormPage edit 模式并回填详情）
   */
  private handleEdit(agent: Agent): void {
    this.router.push(RouteNames.AGENT_FORM, { 'mode': 'edit', 'agentId': agent.id });
  }

  /**
   * 查看详情（进 AgentDetailPage 分节页）
   */
  private openDetail(agent: Agent): void {
    this.router.push(RouteNames.AGENT_DETAIL, { 'agentId': agent.id });
  }

  /**
   * 删除前二次确认
   * 使用 AlertDialog 弹窗，避免误删；确认后调用 deleteAgent
   */
  private confirmDelete(agent: Agent): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除智能体"${agent.name}"吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '删除',
        fontColor: this.sm.getColor('error'),
        action: () => { this.deleteAgent(agent.id); }
      }
    });
  }

  /**
   * 执行删除
   * 流程：调用 API 删除 → 成功后重新加载列表
   * 异常：记录日志并提示用户
   */
  private async deleteAgent(agentId: string): Promise<void> {
    try {
      const res = await this.api.agents.remove(agentId);
      if (res.code === 0) {
        this.msg.success('删除成功');
        this.loadAgents();
      } else {
        this.msg.error(res.message || '删除失败');
      }
    } catch (e) {
      this.logger.error(TAG, '删除失败', e as Error);
      this.msg.error('删除智能体失败');
    }
  }

  /** 获取状态对应颜色：active→绿，inactive→灰，sleeping→黄，error→红 */
  private getStatusColor(status: AgentStatus): string {
    switch (status) {
      case 'active':
        return this.sm.getColor('success');
      case 'inactive':
        return this.sm.getColor('text_disabled');
      case 'sleeping':
        return this.sm.getColor('warning');
      case 'error':
        return this.sm.getColor('error');
      default:
        return this.sm.getColor('text_disabled');
    }
  }

  /** 获取状态文案：active→在线，inactive→离线，sleeping→休眠，error→异常 */
  private getStatusLabel(status: AgentStatus): string {
    switch (status) {
      case 'active':
        return '在线';
      case 'inactive':
        return '离线';
      case 'sleeping':
        return '休眠';
      case 'error':
        return '异常';
      default:
        return '未知';
    }
  }

  /** 获取头像首字母（大写），空名回退 '?' */
  private getAvatarChar(name: string): string {
    if (!name || name.length === 0) return '?';
    return name.charAt(0).toUpperCase();
  }

  /** 格式化最后活跃时间（YYYY-MM-DD HH:mm），无值回退 '未知' */
  private formatLastActive(lastActiveAt?: string): string {
    if (!lastActiveAt) return '未知';
    const d = new Date(lastActiveAt);
    if (isNaN(d.getTime())) return '未知';
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    const hh = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd} ${hh}:${mm}`;
  }

  build() {
    Stack() {
      Column() {
        // 顶部导航栏：标题"智能体"（21/700）+ 数量/在线副标（右侧插槽）
        // 内联头（原型 F7：标题 + 「N 个 · M 在线」；创建入口收敛为右下 FAB）
        Row() {
          Text('智能体')
            .fontSize(this.sm.getFontSize('page_title'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
          Text(this.agentTotal.toString() + ' 个 · ' + this.agentOnline.toString() + ' 在线')
            .fontSize(this.sm.getFontSize('badge'))
            .fontColor(this.sm.getColor('text_tertiary'))
            .margin({ left: 8 })
            .alignSelf(ItemAlign.End)
            .padding({ bottom: 3 })
          Blank()
        }
        .width('100%')
        .padding({ left: 20, right: 20, top: 8, bottom: 10 })

      if (this.loading) {
        // 加载态：居中显示"加载中..."
        Column() {
          Text('加载中...')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else if (this.agentTotal === 0) {
        // 空列表：居中显示"暂无智能体"+ 创建按钮
        Column() {
          Text('暂无智能体')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ bottom: this.sm.getSpacing('md') })
          GlassButton({
            text: '创建智能体',
            type: 'gradient',
            btnSize: 'medium',
            onTap: () => { this.handleCreate(); }
          })
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else {
        // 智能体列表：纵向滚动，卡片间距 12，关闭滚动条
        // M5.2.2 改用 LazyForEach 惰性渲染，仅渲染可见区域 + 缓存项，长列表性能更优
        List({ space: 12 }) {
          // SimpleDataSource 的监听器签名与 SDK IDataSource 不完全一致，经 Object 桥接为 IDataSource
          LazyForEach(this.agentsDs as Object as IDataSource, (agent: Agent) => {
            ListItem() {
              this.buildAgentCard(agent)
            }
          }, (agent: Agent) => agent.id)
          // 底部预留空位：满滚时末张卡停在玻璃页签栏上方，可看可点（内容仍可滚过栏后）
          ListItem() {
            Column()
              .width('100%')
              .height(120)
          }
        }
        .layoutWeight(1)
        .width('100%')
        .scrollBar(BarState.Off)
        .padding({
          left: this.sm.getSpacing('md'),
          right: this.sm.getSpacing('md'),
          top: this.sm.getSpacing('sm'),
          bottom: this.sm.getSpacing('sm'),
        })
      }
      }
      .width('100%')
      .height('100%')

      // 右下角 FAB（设计 F7 .fab：54px 品牌渐变圆钮 → 创建智能体）
      Column() {
        AppIcon({ name: 'plus', iconSize: 22, color: '#FFFFFF' })
      }
      .width(54)
      .height(54)
      .borderRadius(27)
      .linearGradient({ angle: 135, colors: this.sm.getBrandGradient() })
      .shadow({ radius: 30, color: 'rgba(99,102,241,0.50)', offsetY: 10 })
      // y 取 78%：页面容器直通屏底后 85% 会落进透明玻璃页签栏区被遮住，上移到栏上方
      .position({ x: '80%', y: '78%' })
      .onClick(() => { this.handleCreate(); })
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 智能体卡片构建器
  // ===========================================================================

  /** 单个智能体卡片（设计 F7 .ag-card）：头像 + 名称/在线点 + 一行描述 + 标签行 + 右侧箭头；整卡进详情 */
  @Builder
  buildAgentCard(agent: Agent) {
    // ArkTS 解析器不允许尾随闭包组件调用后再链属性修饰，外包 Column 承接 .width
    Column() {
      Row() {
        // 头像：首字母 40x40，品牌渐变白字（休眠置灰）
        Text(this.getAvatarChar(agent.name))
          .fontSize(20)
          .fontColor(this.sm.getColor('text_on_primary'))
          .fontWeight(FontWeight.Bold)
          .width(40)
          .height(40)
          .borderRadius(14)
          .linearGradient({ angle: 135, colors: [[this.sm.getColor('secondary'), 0], [this.sm.getColor('primary'), 1]] })
          .textAlign(TextAlign.Center)
          .opacity(agent.status === 'sleeping' ? 0.5 : 1)

        // 信息列：名称(+状态点) / 描述 / 标签行
        Column() {
          Row() {
            Text(agent.name)
              .fontSize(this.sm.getFontSize('card_title'))
              .fontWeight(FontWeight.Medium)
              .fontColor(this.sm.getColor('text_primary'))
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
            if (agent.status === 'active') {
              // 在线绿点（设计 .ag-card .nm .st）
              Row()
                .width(6)
                .height(6)
                .borderRadius(3)
                .backgroundColor(this.sm.getColor('success'))
                .shadow({ radius: 8, color: 'rgba(52,211,153,0.80)' })
                .margin({ left: 7 })
            } else if (agent.status === 'sleeping') {
              Text('休眠中')
                .fontSize(this.sm.getFontSize('badge'))
                .fontColor(this.sm.getColor('text_tertiary'))
                .margin({ left: 7 })
            }
          }
          .alignItems(VerticalAlign.Center)

          Text(agent.description !== '' ? agent.description : '暂无描述')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .margin({ top: 3 })

          // 标签行：模型名 + 工具数（真实字段，等宽字体紫胶囊）
          Row() {
            if (agent.model !== undefined && agent.model !== '') {
              Text(agent.model)
                .fontSize(9)
                .fontFamily(this.sm.getMonoFont())
                .fontColor(this.sm.getColor('primary'))
                .backgroundColor(this.sm.getColor('primary_soft'))
                .border({ width: 1, color: this.sm.getColor('primary') })
                .borderRadius(5)
                .padding({ left: 7, right: 7, top: 2, bottom: 2 })
                .margin({ right: 6 })
            }
            if (agent.toolsCount !== undefined && agent.toolsCount > 0) {
              Text('工具 ' + agent.toolsCount.toString())
                .fontSize(9)
                .fontFamily(this.sm.getMonoFont())
                .fontColor(this.sm.getColor('primary'))
                .backgroundColor(this.sm.getColor('primary_soft'))
                .border({ width: 1, color: this.sm.getColor('primary') })
                .borderRadius(5)
                .padding({ left: 7, right: 7, top: 2, bottom: 2 })
            }
          }
          .margin({ top: 8 })
          .alignItems(VerticalAlign.Center)
        }
        .layoutWeight(1)
        .alignItems(HorizontalAlign.Start)
        .margin({ left: 13 })

        // 右侧：箭头（设计 .ag-card .rt2 → 简化为 chev）
        AppIcon({ name: 'chev', iconSize: 14, color: this.sm.getColor('text_tertiary') })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
    }
    .width('100%')
    .padding(15)
    .borderRadius(16)
    .backgroundColor(this.sm.getColor('glass'))
    .border({ width: 1, color: this.sm.getColor('border') })
    .opacity(agent.status === 'sleeping' ? 0.6 : 1)
    .onClick(() => { this.openDetail(agent); })
  }
}
