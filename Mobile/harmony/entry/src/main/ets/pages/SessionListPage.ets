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
import { Agent } from '../libs/types';

/** 筛选 Tab：全部 / 置顶 */
const FILTER_ALL = 0;
const FILTER_PINNED = 1;

@Component
export struct SessionListPage {
  @State private sessions: ChatSession[] = [];
  @State private loading: boolean = false;
  @State private filter: number = FILTER_ALL;
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

  aboutToAppear(): void {
    this.loadSessions();
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

  /** 按筛选 Tab 与搜索词输出可见列表（置顶优先，其次按更新时间倒序） */
  private visible(): ChatSession[] {
    const kw = this.searchText.trim();
    const base = this.filter === FILTER_PINNED
      ? this.sessions.filter((s: ChatSession) => s.pinned)
      : this.sessions;
    const filtered = kw.length === 0
      ? base
      : base.filter((s: ChatSession) => s.title.indexOf(kw) >= 0);
    const sorted = filtered.slice();
    sorted.sort((a: ChatSession, b: ChatSession) => {
      if (a.pinned !== b.pinned) {
        return a.pinned ? 0 : 1;
      }
      return a.updated_at > b.updated_at ? 0 : 1;
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

  private fmtTime(iso: string): string {
    if (iso.length >= 10) {
      return iso.slice(5, 10);
    }
    return iso;
  }

  build() {
    Stack() {
      Column() {
        // 头部：标题 + 新建
        Row() {
          Text('对话')
            .fontSize(21)
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
          Text('与 PC 同源')
            .fontSize(11)
            .fontColor(this.sm.getColor('text_tertiary'))
            .margin({ left: 8 })

          Blank()

          Stack() {
            Circle()
              .width(13)
              .height(13)
              .fillOpacity(0)
              .stroke(this.sm.getColor('text_secondary'))
              .strokeWidth(1.7)
            Path()
              .commands('M14.2 14.2 L18.2 18.2')
              .fillOpacity(0)
              .stroke(this.sm.getColor('text_secondary'))
              .strokeWidth(1.7)
              .strokeLineCap(LineCapStyle.Round)
              .width(20)
              .height(20)
          }
          .width(36)
          .height(36)
          .borderRadius(12)
          .backgroundColor(this.sm.getColor('surface_strong'))
          .border({ width: 1, color: this.sm.getColor('border') })
          .onClick(() => {
            this.showSearch = !this.showSearch;
          })

          Button() {
            Text('＋ 新对话')
              .fontSize(13)
              .fontColor(this.sm.getColor('text_on_primary'))
          }
          .buttonStyle(ButtonStyleMode.NORMAL)
          .linearGradient({ angle: 135, colors: [['#8b5cf6', 0], ['#6366f1', 1]] })
          .height(34)
          .margin({ left: 8 })
          .onClick(() => {
            this.newSession();
          })
        }
        .width('100%')
        .padding({ left: 20, right: 20, top: 8, bottom: 10 })

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

        // 筛选：全部 / 置顶
        Row() {
          ForEach(['全部', '置顶'], (label: string, idx: number) => {
            Text(label)
              .fontSize(12)
              .fontColor(this.filter === idx ? this.sm.getColor('text_on_primary') : this.sm.getColor('text_secondary'))
              .padding({ left: 14, right: 14, top: 6, bottom: 6 })
              .borderRadius(999)
              .backgroundColor(this.filter === idx ? this.sm.getColor('primary_soft') : this.sm.getColor('surface'))
              .border({ width: 1, color: this.filter === idx ? this.sm.getColor('primary') : this.sm.getColor('border') })
              .margin({ right: 8 })
              .onClick(() => {
                this.filter = idx;
              })
          }, (label: string) => label)
          Blank()
        }
        .width('100%')
        .padding({ left: 20, right: 20, bottom: 10 })

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
                // Agent 头像（首字）
                Text(this.agentName(s.agent_id).slice(0, 1))
                  .fontSize(15)
                  .fontWeight(FontWeight.Bold)
                  .fontColor(this.sm.getColor('text_on_primary'))
                  .width(40)
                  .height(40)
                  .borderRadius(14)
                  .textAlign(TextAlign.Center)
                  .linearGradient({ angle: 135, colors: [['#8b5cf6', 0], ['#6366f1', 1]] })

                Column() {
                  Row() {
                    Text(s.title)
                      .fontSize(14.5)
                      .fontWeight(FontWeight.Medium)
                      .fontColor(this.sm.getColor('text_primary'))
                      .maxLines(1)
                      .textOverflow({ overflow: TextOverflow.Ellipsis })
                      .layoutWeight(1)
                    if (s.pinned) {
                      Text('置顶')
                        .fontSize(9)
                        .fontColor(this.sm.getColor('primary'))
                        .padding({ left: 5, right: 5, top: 1, bottom: 1 })
                        .borderRadius(5)
                        .border({ width: 1, color: this.sm.getColor('primary') })
                        .margin({ left: 6 })
                    }
                  }
                  .width('100%')

                  Text(this.fmtTime(s.updated_at) + ' · ' + this.agentName(s.agent_id))
                    .fontSize(11)
                    .fontColor(this.sm.getColor('text_tertiary'))
                    .margin({ top: 3 })
                }
                .layoutWeight(1)
                .alignItems(HorizontalAlign.Start)
                .margin({ left: 11 })

                Text('⋯')
                  .fontSize(15)
                  .fontColor(this.sm.getColor('text_tertiary'))
                  .padding(6)
                  .onClick(() => {
                    // 操作菜单：重命名 / 置顶 / 删除（同 PC 侧栏操作集，AlertDialogParamWithOptions）
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
              .width('100%')
              .padding(13)
              .borderRadius(15)
              .backgroundBlurStyle(BlurStyle.COMPONENT_THIN)
              .backgroundColor(this.sm.getColor('surface_strong'))
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
