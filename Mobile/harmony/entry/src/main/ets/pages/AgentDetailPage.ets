/**
 * AgentDetailPage - 智能体详情页（对照原型 F8：认知域在移动端的分节收纳）
 *
 * 数据（端点均经后端源码核对）：
 *   GET /v1/agents/{agent_id}      概览（agent.py AgentInfo：name/description/model/status/tools_count）
 *   GET /v1/memory?agent_id=&limit=1    记忆总数（count）
 *   GET /v1/sleep/{agent_id}/status     睡眠状态（is_sleeping/sleep_phase/sleep_cycles）
 * 操作：发消息（写入会话上下文 → CHAT）/ 编辑（AGENT_FORM edit 模式）/
 *       记忆全量（MEMORY，agentsStore 切当前 Agent）。
 */

import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { StateManager } from '../libs/state/StateManager';
import { Router, RouteNames } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { MessageManager } from '../libs/message/MessageManager';
import { SleepStatusDto } from '../libs/api/modules/RuntimeApi';
import { Agent } from '../libs/types';
import { AppIcon } from '../components/common/AppIcon';
import { IconBtn } from '../components/common/IconBtn';

/** 详情分节胶囊（设计 F8 .chiprow；情绪域无移动端页面，不设假入口） */
interface DetailChip {
  label: string;
  route: string;
}

@Component
export struct AgentDetailPage {
  @State private agentId: string = '';
  @State private agent: Agent | null = null;
  @State private memoryCount: number = 0;
  @State private sleep: SleepStatusDto | null = null;
  @State private loading: boolean = true;
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private state = StateManager.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private msg = MessageManager.getInstance();
  // 分节胶囊清单（概览为当前页；其余路由跳转）。
  // route 一律取 RouteNames 值（PageMap 按值匹配）——此前这里写的是常量名
  // （'MEMORY' 等），push 进 Router 落到 fallback 占位页，六个入口全是坏的。
  // 2026-11-18 补入口：扩展 agent 域全部次级页（原 13 条孤儿路由由此可达）。
  private chips: DetailChip[] = [
    { label: '概览', route: '' },
    { label: '记忆', route: RouteNames.MEMORY },
    { label: '技能', route: RouteNames.SKILL_POOL },
    { label: '成长', route: RouteNames.GROWTH },
    { label: '睡眠', route: RouteNames.SLEEP_STATUS },
    { label: '文件', route: RouteNames.AGENT_FILE },
    { label: '渠道', route: RouteNames.AGENT_CHANNEL },
    { label: '规则', route: RouteNames.AGENT_RULE },
    { label: '媒体', route: RouteNames.AGENT_MEDIA },
    { label: '调度', route: RouteNames.AGENT_SCHEDULER },
    { label: '上下文', route: RouteNames.CONTEXT_CHANNEL },
    { label: '电脑', route: RouteNames.AGENT_COMPUTER },
    { label: '轨迹', route: RouteNames.AGENT_TRACE },
    { label: '轨迹点', route: RouteNames.AGENT_TRAJECTORY },
    { label: '睡眠设置', route: RouteNames.SLEEP_SETTINGS },
    { label: '防火墙', route: RouteNames.AGENT_FIREWALL },
    { label: '经验库', route: RouteNames.EXPERIENCE_KNOWLEDGE },
    { label: '图谱', route: RouteNames.KNOWLEDGE_GRAPH },
    { label: '反思', route: RouteNames.REFLECTION },
    { label: '元认知', route: RouteNames.METACOGNITION },
  ];

  aboutToAppear(): void {
    // 路由参数优先（AgentListPage 传入），回退到 store 的当前 Agent
    const params = this.router.getCurrentParam() as Record<string, Object> | undefined;
    if (params && params['agentId']) {
      this.agentId = params['agentId'] as string;
    } else {
      this.agentId = this.agentsStore.currentAgentId;
    }
    this.loadAll();
  }

  private async loadAll(): Promise<void> {
    this.loading = true;
    try {
      this.agent = await this.api.agents.get(this.agentId);
      const memRes = await this.api.memory.list(this.agentId, undefined, 1);
      if (memRes.code === 0 && memRes.data) {
        this.memoryCount = memRes.data.total;
      }
      const sleepRes = await this.api.runtime.getSleepStatusDto(this.agentId);
      if (sleepRes.code === 0 && sleepRes.data) {
        this.sleep = sleepRes.data;
      }
    } catch (e) {
      this.msg.error('详情加载失败：' + (e as Error).message);
    }
    this.loading = false;
  }

  /** 发消息：写入会话上下文（无既有会话 → 新会话）后进对话 */
  private openChat(): void {
    this.state.set('chat:active_session_id', '');
    this.state.set('chat:active_session_title', '与 ' + (this.agent ? this.agent.name : 'Agent') + ' 的新对话');
    if (this.agent) {
      this.agentsStore.switchAgent(this.agent.id);
    }
    this.router.push(RouteNames.CHAT);
  }

  private openMemories(): void {
    if (this.agent) {
      this.agentsStore.switchAgent(this.agent.id);
    }
    this.router.push(RouteNames.MEMORY);
  }

  private openEdit(): void {
    this.router.push(RouteNames.AGENT_FORM, { 'mode': 'edit', 'agentId': this.agentId });
  }

  /** 顶栏齿轮 → 操作菜单：编辑 / 删除（F7 卡片操作收敛至此） */
  private showActions(): void {
    AlertDialog.show({
      title: this.agent ? this.agent.name : '智能体操作',
      message: '选择操作',
      autoCancel: true,
      alignment: DialogAlignment.Center,
      buttons: [
        {
          value: '编辑',
          action: () => {
            this.openEdit();
          }
        },
        {
          value: '删除',
          fontColor: this.sm.getColor('error'),
          action: () => {
            this.confirmDelete();
          }
        }
      ]
    });
  }

  private async confirmDelete(): Promise<void> {
    try {
      await this.api.agents.remove(this.agentId);
      this.msg.success('已删除');
      this.router.back();
    } catch (e) {
      this.msg.error('删除失败：' + (e as Error).message);
    }
  }

  /** 分节胶囊点击：概览停留本页，其余先切当前 Agent 再跳路由 */
  private openChip(chip: DetailChip): void {
    if (chip.route === '') {
      return;
    }
    if (this.agent) {
      this.agentsStore.switchAgent(this.agent.id);
    }
    this.router.push(chip.route);
  }

  private statusLabel(): string {
    if (this.agent && this.agent.status.length > 0) {
      // 后端状态归一值 → 中文（与列表页状态口径一致）
      if (this.agent.status === 'active') {
        return '在线';
      }
      if (this.agent.status === 'sleeping') {
        return '休眠中';
      }
      if (this.agent.status === 'error') {
        return '异常';
      }
      return this.agent.status;
    }
    if (this.sleep && this.sleep.is_sleeping) {
      return '休眠中';
    }
    return '在线';
  }

  build() {
    Column() {
      // 头部：返回 + 标题 + 齿轮（操作菜单：编辑/删除）
      Row() {
        IconBtn({ name: 'back', onTap: () => { this.router.back(); } })
        Text('智能体详情')
          .fontSize(17)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.sm.getColor('text_primary'))
          .layoutWeight(1)
          .textAlign(TextAlign.Center)
        IconBtn({ name: 'gear', onTap: () => { this.showActions(); } })
      }
      .width('100%')
      .padding({ left: 12, right: 12, top: 6, bottom: 8 })
      .alignItems(VerticalAlign.Center)

      Scroll() {
        Column() {
          // 居中头部（设计 F8 .deth：64px 渐变头像 + 名称 + 状态行 + 操作行）
          Column() {
            Text(this.agent ? this.agent.name.slice(0, 1) : 'A')
              .fontSize(24)
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_on_primary'))
              .width(64)
              .height(64)
              .borderRadius(20)
              .textAlign(TextAlign.Center)
              .linearGradient({ angle: 135, colors: [[this.sm.getColor('secondary'), 0], [this.sm.getColor('primary'), 1]] })
            Text(this.agent ? this.agent.name : '…')
              .fontSize(19)
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .margin({ top: 10 })
            Row() {
              Row()
                .width(6)
                .height(6)
                .borderRadius(3)
                .backgroundColor(this.sleep && this.sleep.is_sleeping ? this.sm.getColor('warning') : this.sm.getColor('success'))
                .shadow({ radius: 8, color: 'rgba(52,211,153,0.80)' })
              Text(this.statusLabel() + (this.agent && this.agent.model ? ' · ' + this.agent.model : '') + (this.agent && this.agent.toolsCount ? ' · 工具 ' + this.agent.toolsCount.toString() : ''))
                .fontSize(12)
                .fontColor(this.sm.getColor('text_secondary'))
                .margin({ left: 6 })
            }
            .margin({ top: 4 })

            // 操作行：渐变发消息（flex）+ 玻璃编辑方钮（设计 .deth .btns）
            Row() {
              Row() {
                AppIcon({ name: 'chat', iconSize: 15, color: this.sm.getColor('text_on_primary') })
                Text('发消息')
                  .fontSize(13)
                  .fontWeight(FontWeight.Medium)
                  .fontColor(this.sm.getColor('text_on_primary'))
                  .margin({ left: 7 })
              }
              .height(40)
              .borderRadius(12)
              .linearGradient({ angle: 135, colors: this.sm.getBrandGradient() })
              .layoutWeight(1)
              .justifyContent(FlexAlign.Center)
              .onClick(() => {
                this.openChat();
              })

              Column() {
                AppIcon({ name: 'edit', iconSize: 16, color: this.sm.getColor('text_secondary') })
              }
              .width(40)
              .height(40)
              .borderRadius(12)
              .backgroundColor(this.sm.getColor('glass'))
              .border({ width: 1, color: this.sm.getColor('border') })
              .justifyContent(FlexAlign.Center)
              .margin({ left: 9 })
              .onClick(() => {
                this.openEdit();
              })
            }
            .margin({ top: 14 })
            .width('100%')
            .alignItems(VerticalAlign.Center)
          }
          .width('100%')
          .alignItems(HorizontalAlign.Center)
          .padding({ top: 8, bottom: 14 })

          // 分节胶囊（设计 F8 .chiprow：横滑；概览=当前，其余路由）
          Scroll() {
            Row() {
              ForEach(this.chips, (chip: DetailChip) => {
                Text(chip.label)
                  .fontSize(12)
                  .fontColor(chip.route === '' ? this.sm.getColor('text_on_primary') : this.sm.getColor('text_secondary'))
                  .padding({ left: 14, right: 14, top: 7, bottom: 7 })
                  .borderRadius(999)
                  .backgroundColor(chip.route === '' ? 'rgba(99,102,241,0.28)' : this.sm.getColor('glass'))
                  .border({ width: 1, color: chip.route === '' ? this.sm.getColor('primary') : this.sm.getColor('border') })
                  .margin({ right: 7 })
                  .onClick(() => {
                    this.openChip(chip);
                  })
              }, (chip: DetailChip) => chip.label)
            }
          }
          .width('100%')
          .scrollable(ScrollDirection.Horizontal)
          .scrollBar(BarState.Off)
          .padding({ bottom: 10 })

          // 概览分节
          Column() {
            Row() {
              AppIcon({ name: 'spark', iconSize: 14, color: this.sm.getColor('primary') })
              Text('概览')
                .fontSize(this.sm.getFontSize('caption'))
                .fontWeight(FontWeight.Medium)
                .fontColor(this.sm.getColor('text_primary'))
                .margin({ left: 7 })
            }
            .margin({ bottom: 8 })
            .alignItems(VerticalAlign.Center)
            this.kvRow('描述', this.agent && this.agent.description && this.agent.description.length > 0 ? this.agent.description : '—')
            this.kvRow('模型', this.agent && this.agent.model && this.agent.model.length > 0 ? this.agent.model : '默认')
            this.kvRow('已挂载工具', this.agent && this.agent.toolsCount ? this.agent.toolsCount.toString() : '0')
          }
          .width('100%')
          .padding(14)
          .borderRadius(16)
          .backgroundColor(this.sm.getColor('glass'))
          .border({ width: 1, color: this.sm.getColor('border') })

          // 记忆分节（含「查看全部 N 条 ›」）
          Column() {
            Row() {
              AppIcon({ name: 'book', iconSize: 14, color: this.sm.getColor('primary') })
              Text('记忆')
                .fontSize(this.sm.getFontSize('caption'))
                .fontWeight(FontWeight.Medium)
                .fontColor(this.sm.getColor('text_primary'))
                .margin({ left: 7 })
                .layoutWeight(1)
              Text('查看全部 ' + this.memoryCount.toString() + ' 条 ›')
                .fontSize(this.sm.getFontSize('badge'))
                .fontColor(this.sm.getColor('primary'))
                .onClick(() => {
                  this.openMemories();
                })
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
            Text(this.memoryCount > 0
              ? '该智能体已有 ' + this.memoryCount.toString() + ' 条长期记忆，点击右上角查看全部'
              : '暂无长期记忆；对话中的稳定事实会自动沉淀')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ top: 8 })
          }
          .width('100%')
          .padding(14)
          .borderRadius(16)
          .backgroundColor(this.sm.getColor('glass'))
          .border({ width: 1, color: this.sm.getColor('border') })
          .margin({ top: 10 })

          // 睡眠分节
          Column() {
            Row() {
              AppIcon({ name: 'moon', iconSize: 14, color: this.sm.getColor('primary') })
              Text('睡眠')
                .fontSize(this.sm.getFontSize('caption'))
                .fontWeight(FontWeight.Medium)
                .fontColor(this.sm.getColor('text_primary'))
                .margin({ left: 7 })
            }
            .margin({ bottom: 8 })
            .alignItems(VerticalAlign.Center)
            this.kvRow('当前阶段', this.sleep ? this.sleep.sleep_phase : '—')
            this.kvRow('休眠周期', this.sleep ? this.sleep.sleep_cycles.toString() : '0')
          }
          .width('100%')
          .padding(14)
          .borderRadius(16)
          .backgroundColor(this.sm.getColor('glass'))
          .border({ width: 1, color: this.sm.getColor('border') })
          .margin({ top: 10 })
        }
        .width('100%')
        .padding({ left: 20, right: 20, bottom: 24 })
      }
      .layoutWeight(1)
      .scrollBar(BarState.Off)
      .width('100%')
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('background'))
  }

  @Builder
  kvRow(k: string, v: string) {
    Row() {
      Text(k)
        .fontSize(this.sm.getFontSize('caption'))
        .fontColor(this.sm.getColor('text_secondary'))
      Blank()
      Text(v)
        .fontSize(this.sm.getFontSize('caption'))
        .fontColor(this.sm.getColor('text_primary'))
        .textAlign(TextAlign.End)
        .constraintSize({ maxWidth: '62%' })
    }
    .width('100%')
    .padding({ top: 6, bottom: 6 })
    .border({ width: { bottom: 1 }, color: this.sm.getColor('divider') })
  }
}
