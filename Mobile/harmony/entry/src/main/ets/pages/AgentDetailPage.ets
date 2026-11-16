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

  private statusLabel(): string {
    if (this.agent && this.agent.status.length > 0) {
      return this.agent.status;
    }
    if (this.sleep && this.sleep.is_sleeping) {
      return '休眠中';
    }
    return '在线';
  }

  build() {
    Column() {
      // 头部：返回 + 标题 + 设置位
      Row() {
        Text('‹')
          .fontSize(22)
          .fontColor(this.sm.getColor('text_secondary'))
          .padding(8)
          .onClick(() => {
            this.router.back();
          })
        Text('智能体详情')
          .fontSize(17)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.sm.getColor('text_primary'))
          .layoutWeight(1)
          .textAlign(TextAlign.Center)
        Text('编辑')
          .fontSize(14)
          .fontColor(this.sm.getColor('primary'))
          .padding(8)
          .onClick(() => {
            this.openEdit();
          })
      }
      .width('100%')
      .padding({ left: 12, right: 12, top: 6, bottom: 8 })

      Scroll() {
        Column() {
          // 头像 + 名称 + 状态
          Column() {
            Text(this.agent ? this.agent.name.slice(0, 1) : 'A')
              .fontSize(22)
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_on_primary'))
              .width(62)
              .height(62)
              .borderRadius(20)
              .textAlign(TextAlign.Center)
              .backgroundColor(this.sm.getColor('primary'))
            Text(this.agent ? this.agent.name : '…')
              .fontSize(18)
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .margin({ top: 10 })
            Row() {
              Circle()
                .width(6)
                .height(6)
                .fill(this.sleep && this.sleep.is_sleeping ? this.sm.getColor('warning') : this.sm.getColor('success'))
              Text(this.statusLabel())
                .fontSize(12)
                .fontColor(this.sm.getColor('text_secondary'))
                .margin({ left: 6 })
            }
            .margin({ top: 4 })

            Row() {
              Button() {
                Text('发消息')
                  .fontSize(13.5)
                  .fontColor(this.sm.getColor('text_on_primary'))
              }
              .backgroundColor(this.sm.getColor('primary'))
              .height(38)
              .layoutWeight(1)
              .onClick(() => {
                this.openChat();
              })
            }
            .margin({ top: 14 })
            .width('100%')
          }
          .width('100%')
          .alignItems(HorizontalAlign.Center)
          .padding({ top: 8, bottom: 14 })

          // 概览分节
          Column() {
            Text('概览')
              .fontSize(12.5)
              .fontWeight(FontWeight.Medium)
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ bottom: 8 })
            this.kvRow('描述', this.agent && this.agent.description && this.agent.description.length > 0 ? this.agent.description : '—')
            this.kvRow('模型', this.agent && this.agent.model && this.agent.model.length > 0 ? this.agent.model : '默认')
          }
          .width('100%')
          .padding(14)
          .borderRadius(16)
          .backgroundColor(this.sm.getColor('surface'))
          .border({ width: 1, color: this.sm.getColor('border') })

          // 记忆分节
          Column() {
            Row() {
              Text('记忆')
                .fontSize(12.5)
                .fontWeight(FontWeight.Medium)
                .fontColor(this.sm.getColor('text_secondary'))
                .layoutWeight(1)
              Text('查看全部 ' + this.memoryCount.toString() + ' 条 ›')
                .fontSize(11)
                .fontColor(this.sm.getColor('primary'))
                .onClick(() => {
                  this.openMemories();
                })
            }
            .width('100%')
            Text(this.memoryCount > 0
              ? '该智能体已有 ' + this.memoryCount.toString() + ' 条长期记忆，点击右上角查看全部'
              : '暂无长期记忆；对话中的稳定事实会自动沉淀')
              .fontSize(12)
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ top: 8 })
          }
          .width('100%')
          .padding(14)
          .borderRadius(16)
          .backgroundColor(this.sm.getColor('surface'))
          .border({ width: 1, color: this.sm.getColor('border') })
          .margin({ top: 10 })

          // 睡眠分节
          Column() {
            Text('睡眠')
              .fontSize(12.5)
              .fontWeight(FontWeight.Medium)
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ bottom: 8 })
            this.kvRow('当前阶段', this.sleep ? this.sleep.sleep_phase : '—')
            this.kvRow('休眠周期', this.sleep ? this.sleep.sleep_cycles.toString() : '0')
          }
          .width('100%')
          .padding(14)
          .borderRadius(16)
          .backgroundColor(this.sm.getColor('surface'))
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
        .fontSize(12.5)
        .fontColor(this.sm.getColor('text_secondary'))
      Blank()
      Text(v)
        .fontSize(12.5)
        .fontColor(this.sm.getColor('text_primary'))
        .textAlign(TextAlign.End)
        .constraintSize({ maxWidth: '62%' })
    }
    .width('100%')
    .padding({ top: 6, bottom: 6 })
    .border({ width: { bottom: 1 }, color: this.sm.getColor('divider') })
  }
}
