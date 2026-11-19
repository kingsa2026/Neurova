/**
 * SessionListPage - 对话 Tab 根页：会话列表（对照原型 F4）
 *
 * 同源承诺：与 PC 端 ChatSessionSidebar 读同一份 /console/chat/sessions，
 * 置顶 / 归档 / 重命名 / 删除共用同一批端点；进入会话经 Router.push(CHAT)，
 * 会话上下文（id/标题）经 StateManager 传递给 ChatPage 拉历史。
 * 流式链路不变：仍走配对 WS 通道（chat:send / chat:chunk）。
 */

import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { StateManager } from '../libs/state/StateManager';
import { Router, RouteNames } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { MessageManager } from '../libs/message/MessageManager';
import { ChatSession } from '../libs/api/modules/SessionsApi';
import { EventBus, EventHandler } from '../libs/bus/EventBus';
import { Agent } from '../libs/types';
import { AppIcon } from '../components/common/AppIcon';
import { IconBtn } from '../components/common/IconBtn';

/** 筛选 Tab：全部 / 置顶 */
const FILTER_ALL = 0;
const FILTER_PINNED = 1;

@Component
export struct SessionListPage {
  @State private sessions: ChatSession[] = [];
  @State private loading: boolean = false;
  @State private filter: number = FILTER_ALL;
  // Agent 筛选下拉：'' = 全部 Agent；选中后列表仅显示该 agent 的会话
  @State private agentFilter: string = '';
  @State private agentFilterIdx: number = 0;
  @State private agents: Agent[] = [];
  // 搜索展开态与关键词（本地按标题过滤）
  @State showSearch: boolean = false;
  @State searchText: string = '';
  /** 重命名弹窗状态 */
  @State private renameTarget: ChatSession | undefined = undefined;
  @State private renameText: string = '';
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private state = StateManager.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private msg = MessageManager.getInstance();
  private bus = EventBus.getInstance();
  /** 聊天回合结束 → 会话摘要（新会话/最新预览）已变，刷新本列表 */
  private sessionsRefreshHandler: EventHandler = () => {
    this.loadSessions();
  };

  aboutToAppear(): void {
    this.loadSessions();
    this.loadAgents();
    // 聊天页回合结束广播：返回本页时列表不再停留在登录时的旧快照
    this.bus.on('chat:sessions-changed', this.sessionsRefreshHandler);
  }

  /** Agent 下拉选项数据（失败降级用 store 缓存，下拉退化为仅「全部 Agent」） */
  private async loadAgents(): Promise<void> {
    try {
      this.agents = await this.api.agents.list();
      this.agentsStore.setAgents(this.agents);
    } catch (e) {
      this.agents = this.agentsStore.agents;
    }
  }

  /** Agent 筛选下拉选项：首项「全部 Agent」不过滤，其余按 agents 顺序 */
  private agentOptions(): SelectOption[] {
    const opts: SelectOption[] = [{ value: '全部 Agent' }];
    for (const a of this.agents) {
      const so: SelectOption = { value: a.name };
      opts.push(so);
    }
    return opts;
  }

  aboutToDisappear(): void {
    this.bus.off('chat:sessions-changed', this.sessionsRefreshHandler);
  }

  private async loadSessions(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.sessions.listAll('');
      if (res.code === 0 && res.data) {
        this.sessions = res.data.sessions;
      } else {
        this.msg.error(res.message || '会话列表获取失败');
      }
    } catch (e) {
      this.msg.error('会话列表获取失败：' + (e as Error).message);
    }
    this.loading = false;
  }

  /** 按筛选 Tab、Agent 下拉与搜索词输出可见列表（置顶优先，其次按更新时间倒序） */
  private visible(): ChatSession[] {
    const kw = this.searchText.trim();
    const base = this.filter === FILTER_PINNED
      ? this.sessions.filter((s: ChatSession) => s.pinned)
      : this.sessions;
    const byAgent = this.agentFilter === ''
      ? base
      : base.filter((s: ChatSession) => s.agent_id === this.agentFilter);
    const filtered = kw.length === 0
      ? byAgent
      : byAgent.filter((s: ChatSession) => s.title.indexOf(kw) >= 0);
    const sorted = filtered.slice();
    sorted.sort((a: ChatSession, b: ChatSession) => {
      // 比较器三分支契约：a 应排前返回负数、b 应排前返回正数、相等返回 0——
      // 只返回 0/1 的写法对大部分输入等效"相等"，排序结果不稳定（审计 3.8-3）
      if (a.pinned !== b.pinned) {
        return a.pinned ? -1 : 1;
      }
      if (a.updated_at === b.updated_at) {
        return 0;
      }
      return a.updated_at > b.updated_at ? -1 : 1;
    });
    return sorted;
  }

  /** Agent 名（头像字与署名用） */
  private agentName(agentId: string): string {
    const agents: Agent[] = this.agentsStore.agents;
    const agent = agents.find((a: Agent) => a.id === agentId);
    return agent?.name ?? '会话';
  }

  /** 进入会话：上下文写入 StateManager，ChatPage 读取后拉历史 */
  private openSession(s: ChatSession): void {
    this.state.set('chat:active_session_id', s.id);
    this.state.set('chat:active_session_title', s.title);
    this.router.push(RouteNames.CHAT);
  }

  /** 新建对话：清上下文（ChatPage 生成新会话 ID） */
  private newSession(): void {
    this.state.set('chat:active_session_id', '');
    this.state.set('chat:active_session_title', '新对话');
    this.router.push(RouteNames.CHAT);
  }

  private async togglePin(s: ChatSession): Promise<void> {
    try {
      await this.api.sessions.pin(s.id);
      this.msg.success(s.pinned ? '已取消置顶' : '已置顶');
      this.loadSessions();
    } catch (e) {
      this.msg.error('置顶失败：' + (e as Error).message);
    }
  }

  private async archive(s: ChatSession): Promise<void> {
    try {
      await this.api.sessions.archive(s.id);
      this.msg.success('已归档');
      this.loadSessions();
    } catch (e) {
      this.msg.error('归档失败：' + (e as Error).message);
    }
  }

  private async remove(s: ChatSession): Promise<void> {
    try {
      await this.api.sessions.remove(s.id);
      this.msg.success('已删除');
      this.loadSessions();
    } catch (e) {
      this.msg.error('删除失败：' + (e as Error).message);
    }
  }

  private async submitRename(): Promise<void> {
    const target = this.renameTarget;
    if (!target) {
      return;
    }
    const title = this.renameText.trim();
    if (title.length === 0) {
      this.msg.warning('标题不能为空');
      return;
    }
    try {
      await this.api.sessions.rename(target.id, title);
      this.msg.success('已重命名');
      this.renameTarget = undefined;
      this.loadSessions();
    } catch (e) {
      this.msg.error('重命名失败：' + (e as Error).message);
    }
  }

  /** 会话时间（本地时区 MM-DD；服务端是 UTC ISO，直接切片晚间会显示成前一天） */
  private fmtTime(iso: string): string {
    if (iso.length >= 19) {
      const d = new Date(iso);
      if (!isNaN(d.getTime())) {
        return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(5, 10);
      }
    }
    return iso.slice(5, 10);
  }

  build() {
    Stack() {
      Column() {
        // 头部：标题（页题 21/700）+ 会话数副标 + 搜索 + 新建（设计 F4 .phead）
        Row() {
          Text('对话')
            .fontSize(this.sm.getFontSize('page_title'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
          Text(this.sessions.length.toString() + ' 个会话 · 与 PC 同源')
            .fontSize(this.sm.getFontSize('badge'))
            .fontColor(this.sm.getColor('text_tertiary'))
            .margin({ left: 8 })

          Blank()

          IconBtn({ name: 'search', onTap: () => { this.showSearch = !this.showSearch; } })

          Button() {
            Text('＋ 新对话')
              .fontSize(13)
              .fontColor(this.sm.getColor('text_on_primary'))
          }
          .buttonStyle(ButtonStyleMode.NORMAL)
          .linearGradient({ angle: 135, colors: [[this.sm.getColor('secondary'), 0], [this.sm.getColor('primary'), 1]] })
          .height(34)
          .margin({ left: 8 })
          .onClick(() => {
            this.newSession();
          })
        }
        .width('100%')
        .padding({ left: 20, right: 20, top: 8, bottom: 10 })
        .alignItems(VerticalAlign.Center)

        // 搜索行（展开时显示，按标题本地过滤）
        if (this.showSearch) {
          Row() {
            TextInput({ placeholder: '搜索会话标题…', text: this.searchText })
              .onChange((v: string) => {
                this.searchText = v;
              })
              .height(40)
              .layoutWeight(1)
              .borderRadius(12)
              .backgroundColor(this.sm.getColor('surface_strong'))
          }
          .width('100%')
          .padding({ left: 20, right: 20, bottom: 10 })
        }

        // 筛选：全部 N / 置顶 N（真实计数；归档会话不在列表接口返回中，不设假分段）
        Row() {
          ForEach(['全部 ' + this.sessions.length.toString(), '置顶 ' + this.sessions.filter((s: ChatSession) => s.pinned).length.toString()], (label: string, idx: number) => {
            Text(label)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.filter === idx ? this.sm.getColor('text_on_primary') : this.sm.getColor('text_secondary'))
              .padding({ left: 14, right: 14, top: 7, bottom: 7 })
              .borderRadius(999)
              .backgroundColor(this.filter === idx ? 'rgba(99,102,241,0.28)' : this.sm.getColor('glass'))
              .border({ width: 1, color: this.filter === idx ? this.sm.getColor('primary') : this.sm.getColor('border') })
              .margin({ right: 8 })
              .onClick(() => {
                this.filter = idx;
              })
          }, (label: string) => label)

          // Agent 筛选下拉：选中后列表仅显示该 agent 的会话
          Select(this.agentOptions())
            .selected(this.agentFilterIdx)
            .value(this.agentFilterIdx === 0 ? '全部 Agent' : this.agentName(this.agentFilter))
            .font({ size: this.sm.getFontSize('caption') })
            .fontColor(this.sm.getColor('text_secondary'))
            .selectedOptionFont({ size: this.sm.getFontSize('caption') })
            .optionFont({ size: this.sm.getFontSize('caption') })
            .fontColor(this.sm.getColor('text_secondary'))
            .backgroundColor(this.sm.getColor('glass'))
            .borderRadius(999)
            .border({ width: 1, color: this.sm.getColor('border') })
            .padding({ left: 12, right: 10, top: 5, bottom: 5 })
            .onSelect((index: number) => {
              this.agentFilterIdx = index;
              this.agentFilter = index === 0 ? '' : (this.agents[index - 1]?.id ?? '');
            })

          Blank()
        }
        .width('100%')
        .padding({ left: 20, right: 20, bottom: 10 })
        .alignItems(VerticalAlign.Center)

        // 列表
        Scroll() {
          Column() {
            if (this.visible().length === 0 && !this.loading) {
              Column() {
                Text('暂无会话')
                  .fontSize(14)
                  .fontColor(this.sm.getColor('text_tertiary'))
                Text('点右上角「＋ 新对话」开始')
                  .fontSize(12)
                  .fontColor(this.sm.getColor('text_tertiary'))
                  .margin({ top: 6 })
              }
              .width('100%')
              .margin({ top: 80 })
            }
            ForEach(this.visible(), (s: ChatSession) => {
              Row() {
                // Agent 头像（首字，渐变）
                Text(this.agentName(s.agent_id).slice(0, 1))
                  .fontSize(15)
                  .fontWeight(FontWeight.Bold)
                  .fontColor(this.sm.getColor('text_on_primary'))
                  .width(40)
                  .height(40)
                  .borderRadius(14)
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
                      .layoutWeight(1)
                    if (s.pinned) {
                      AppIcon({ name: 'pin', iconSize: 12, color: this.sm.getColor('primary') })
                        .margin({ left: 6 })
                    }
                  }
                  .width('100%')

                  Text(this.agentName(s.agent_id) + (s.channel_name !== '' ? ' · ' + s.channel_name : ''))
                    .fontSize(this.sm.getFontSize('caption'))
                    .fontColor(this.sm.getColor('text_tertiary'))
                    .margin({ top: 3 })
                    .maxLines(1)
                    .textOverflow({ overflow: TextOverflow.Ellipsis })
                }
                .layoutWeight(1)
                .alignItems(HorizontalAlign.Start)
                .margin({ left: 11 })

                // 右列：时间 + 操作（设计 F4 .rt）
                Column() {
                  Text(this.fmtTime(s.updated_at))
                    .fontSize(this.sm.getFontSize('badge'))
                    .fontColor(this.sm.getColor('text_tertiary'))
                  Text('⋯')
                    .fontSize(15)
                    .fontColor(this.sm.getColor('text_tertiary'))
                    .padding({ left: 6, right: 6, top: 2, bottom: 2 })
                    .margin({ top: 3 })
                    .onClick(() => {
                      // 操作菜单：重命名 / 置顶 / 归档 / 删除（同 PC 侧栏操作集）
                      this.renameTarget = s;
                      this.renameText = s.title;
                      AlertDialog.show({
                        title: s.title,
                        message: '选择会话操作',
                        autoCancel: true,
                        alignment: DialogAlignment.Center,
                        buttons: [
                          {
                            value: '重命名',
                            action: () => {
                              // 保持 renameTarget，转重命名输入层
                            }
                          },
                          {
                            value: s.pinned ? '取消置顶' : '置顶',
                            action: () => {
                              this.togglePin(s);
                            }
                          },
                          {
                            value: '归档',
                            action: () => {
                              this.archive(s);
                            }
                          },
                          {
                            value: '删除',
                            fontColor: this.sm.getColor('error'),
                            action: () => {
                              this.remove(s);
                            }
                          }
                        ]
                      });
                    })
                }
                .alignItems(HorizontalAlign.End)
              }
              .width('100%')
              .padding(13)
              .borderRadius(16)
              .backgroundColor(this.sm.getColor('glass'))
              .border({
                width: 1,
                color: s.pinned ? this.sm.getColor('primary') : this.sm.getColor('border')
              })
              .margin({ bottom: 8, left: 20, right: 20 })
              .onClick(() => {
                this.openSession(s);
              })
            }, (s: ChatSession) => s.id + s.updated_at)
          }
          .width('100%')
        }
        .layoutWeight(1)
        .scrollBar(BarState.Off)
        .width('100%')
      }
      .width('100%')
      .height('100%')

      // 重命名输入层
      if (this.renameTarget) {
        Column() {
          Column() {
            Text('重命名会话')
              .fontSize(16)
              .fontWeight(FontWeight.Medium)
              .fontColor(this.sm.getColor('text_primary'))
            TextInput({ text: this.renameText })
              .onChange((v: string) => {
                this.renameText = v;
              })
              .height(44)
              .borderRadius(12)
              .backgroundColor(this.sm.getColor('surface_strong'))
              .margin({ top: 14 })
            Row() {
              Button('取消')
                .layoutWeight(1)
                .height(40)
                .backgroundColor(this.sm.getColor('surface_strong'))
                .fontColor(this.sm.getColor('text_secondary'))
                .onClick(() => {
                  this.renameTarget = undefined;
                })
              Button('保存')
                .layoutWeight(1)
                .height(40)
                .backgroundColor(this.sm.getColor('primary'))
                .fontColor(this.sm.getColor('text_on_primary'))
                .margin({ left: 10 })
                .onClick(() => {
                  this.submitRename();
                })
            }
            .margin({ top: 14 })
          }
          .width('84%')
          .padding(20)
          .borderRadius(18)
          .backgroundColor(this.sm.getColor('surface'))
          .border({ width: 1, color: this.sm.getColor('border') })
        }
        .width('100%')
        .height('100%')
        .justifyContent(FlexAlign.Center)
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => {
          this.renameTarget = undefined;
        })
      }
    }
    .width('100%')
    .height('100%')
    
  }
}
