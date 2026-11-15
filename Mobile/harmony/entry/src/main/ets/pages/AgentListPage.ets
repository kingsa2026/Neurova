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

import { TopNavMenu, GlassCard, GlassButton } from '../components/glass';
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
      const res = await this.api.agents.list();
      if (res.code === 0 && res.data) {
        this.agentsDs.setData(res.data.items);
        this.agentsStore.setAgents(this.agentsDs.getAll());
      }
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
   * 创建智能体（M3 实现，当前提示"功能开发中"）
   */
  private handleCreate(): void {
    this.msg.info('功能开发中');
  }

  /**
   * 编辑智能体（M3 实现，当前提示"功能开发中"）
   */
  private handleEdit(agent: Agent): void {
    this.msg.info('功能开发中');
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
    Column() {
      // 顶部导航栏：标题"智能体" + 返回按钮 + 创建按钮（右侧插槽）
      TopNavMenu({
        title: '智能体',
        showBack: true,
        showMenu: false,
        onBack: () => { this.router.back(); }
      }) {
        GlassButton({
          text: '创建',
          type: 'primary',
          size: 'small',
          onClick: () => { this.handleCreate(); }
        })
      }

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
      } else if (this.agentsDs.totalCount() === 0) {
        // 空列表：居中显示"暂无智能体"+ 创建按钮
        Column() {
          Text('暂无智能体')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ bottom: this.sm.getSpacing('md') })
          GlassButton({
            text: '创建智能体',
            type: 'primary',
            size: 'medium',
            onClick: () => { this.handleCreate(); }
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
          LazyForEach(this.agentsDs, (agent: Agent) => {
            ListItem() {
              this.buildAgentCard(agent)
            }
          }, (agent: Agent) => agent.id)
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
    .backgroundColor(this.sm.getColor('background'))
  }

  // ===========================================================================
  // 智能体卡片构建器
  // ===========================================================================

  /** 单个智能体卡片：头像 + 信息列 + 状态行 + 操作按钮 */
  @Builder
  buildAgentCard(agent: Agent) {
    GlassCard() {
      Column() {
        // 上部：头像 + 名称/描述/状态
        Row() {
          // 头像：首字母圆形，40x40，primary 色背景白字
          Text(this.getAvatarChar(agent.name))
            .fontSize(20)
            .fontColor('#ffffff')
            .fontWeight(FontWeight.Bold)
            .width(40)
            .height(40)
            .borderRadius(20)
            .backgroundColor(this.sm.getColor('primary'))
            .textAlign(TextAlign.Center)

          // 信息列：名称、描述、状态行
          Column() {
            // 名称
            Text(agent.name)
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })

            // 描述（空值回退"暂无描述"）
            Text(agent.description ?? '暂无描述')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .maxLines(2)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
              .margin({ top: 4 })

            // 状态行：圆点 + 状态文案 + 分隔符 + 最后活跃时间
            Row() {
              // 状态圆点 8x8（Row + borderRadius 实现圆形）
              Row()
                .width(8)
                .height(8)
                .borderRadius(4)
                .backgroundColor(this.getStatusColor(agent.status))
              Text(this.getStatusLabel(agent.status))
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .margin({ left: 4 })
              Text('·')
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_disabled'))
                .margin({ left: 4, right: 4 })
              Text(this.formatLastActive(agent.stats?.lastActiveAt))
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_disabled'))
            }
            .margin({ top: 8 })
            .alignItems(VerticalAlign.Center)
          }
          .layoutWeight(1)
          .alignItems(HorizontalAlign.Start)
          .margin({ left: this.sm.getSpacing('sm') })
        }
        .width('100%')
        .alignItems(VerticalAlign.Top)

        // 下部：操作按钮（右对齐）
        Row() {
          GlassButton({
            text: '对话',
            type: 'primary',
            size: 'small',
            onClick: () => { this.switchAgent(agent.id); }
          })
          GlassButton({
            text: '编辑',
            type: 'default',
            size: 'small',
            onClick: () => { this.handleEdit(agent); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
          GlassButton({
            text: '删除',
            type: 'danger',
            size: 'small',
            onClick: () => { this.confirmDelete(agent); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
        }
        .width('100%')
        .justifyContent(FlexAlign.End)
        .margin({ top: this.sm.getSpacing('md') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
  }
}
