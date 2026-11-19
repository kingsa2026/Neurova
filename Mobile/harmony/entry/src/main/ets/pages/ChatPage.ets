/**
 * ChatPage - 对话页
 *
 * 职责：基于 WebSocket 流式协议的实时对话界面，支持流式消息渲染、停止生成
 * 设计：Column [TopNavMenu] + [List 消息列表 layoutWeight:1] + [输入区 Row]；
 *       进入页面通过 WebSocketAdapter 建立 WS 连接，订阅 EventBus 的 chat:chunk/done/error 事件；
 *       用户发送消息时创建 user 消息 + assistant 占位消息，通过 WS 下发 chat:send；
 *       收到 chunk 追加到占位消息，收到 done/error 结束流式状态；
 *       颜色统一走 StyleManager，配置走 ConfigManager，日志走 Logger，路由走 Router
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassInput、GlassButton、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（加载 Agent 列表）
 *   - ../libs/state/stores/AuthStore、AgentsStore：认证与 Agent 状态
 *   - ../libs/adapters/WebSocketAdapter：WS 连接/发送
 *   - ../libs/bus/EventBus：统一事件订阅
 *   - ../libs/config/ConfigManager：统一配置（ws_base_url）
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/types：WSChatChunk、Agent
 *   - ../routing/Router：统一路由返回
 *
 * 用法：
 *   由 Router.push(RouteNames.CHAT) 跳转进入；离开页面自动断开 WS 并取消事件订阅
 */

import { GlassInput } from '../components/glass';
import { AppIcon } from '../components/common/AppIcon';
import { IconBtn } from '../components/common/IconBtn';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AuthStore } from '../libs/state/stores/AuthStore';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { StateManager } from '../libs/state/StateManager';
import { WebSocketAdapter } from '../libs/adapters/WebSocketAdapter';
import { EventBus, EventHandler } from '../libs/bus/EventBus';
import { ConfigManager } from '../libs/config/ConfigManager';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { WSChatChunk, WSChatDone, Agent } from '../libs/types';
import { Router } from '../routing/Router';
import { ChunkBatcher } from '../libs/perf/ChunkBatcher';
import { SimpleDataSource } from '../libs/perf/SimpleDataSource';
import { ChatSession } from '../libs/api/modules/SessionsApi';

/** 对话消息视图模型（仅用于本页渲染） */
interface ChatMessageView {
  id: string;               // 消息唯一 ID
  role: 'user' | 'assistant'; // 角色
  content: string;          // 文本内容
  timestamp: number;        // 毫秒时间戳
  isStreaming: boolean;     // 是否正在流式生成
}

/** 日志标签 */
const TAG = 'ChatPage';

/** 会话抽屉分组（设计 F6 .grp：置顶/今天/更早） */
interface DrawerGroup {
  label: string;
  items: ChatSession[];
}

@Component
export struct ChatPage {
  // 消息列表（双向：user 右对齐，assistant 左对齐）
  @State messages: ChatMessageView[] = [];
  // 输入框文本
  @State inputText: string = '';
  // 是否正在生成（控制发送/停止按钮切换）
  @State isGenerating: boolean = false;
  // 当前会话 ID（会话列表进入时恢复，直接进入则生成新 ID）
  @State sessionId: string = 'session-' + Date.now();
  // 会话标题（头部展示；新会话为'新对话'）
  @State sessionTitle: string = '新对话';
  // 当前 Agent ID（从 AgentsStore 读取）
  @State currentAgentId: string = '';
  // Agent 列表（气泡署名与状态行展示用）
  @State agents: Agent[] = [];
  // 排队态（chat:queued 事件置位，done/error 清除；设计 F5 .queued 卡）
  @State queued: boolean = false;
  // 会话是否来自列表（可置顶/归档；新会话未落库，操作会 404）
  private fromList: boolean = false;
  // F6 会话抽屉开关（聊天页右上角 ⋯ 呼出，右缘滑出）
  @State drawerOpen: boolean = false;
  // 抽屉会话列表（GET /console/chat/sessions 全量摘要）
  @State drawerSessions: ChatSession[] = [];
  // 抽屉数据版本号：进 ForEach key 强制重建条目，防对象复用导致的标题滞留渲染
  @State drawerRev: number = 0;
  // 归档会话列表（GET /console/chat/sessions/archived）
  @State archivedSessions: ChatSession[] = [];
  // 归档区展开态（抽屉底部「查看 N 个归档会话」点击展开）
  @State archivedOpen: boolean = false;
  // 跨会话搜索词（已加载摘要的客户端过滤；后端无搜索端点，不设假联查）
  @State searchKeyword: string = '';
  // 重命名中的会话（非空时渲染居中重命名弹层）
  @State renamingSession: ChatSession | null = null;
  @State renameText: string = '';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private authStore = new AuthStore();
  private agentsStore = new AgentsStore();
  private ws = WebSocketAdapter.getInstance();
  private bus = EventBus.getInstance();
  private config = ConfigManager.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();
  private router = Router.getInstance();

  // List 滚动控制器：用于新消息到达时自动滚动到底部
  private scroller: Scroller = new Scroller();
  // 保存事件处理器引用，便于 aboutToDisappear 时精准取消订阅，避免重复绑定
  private chunkHandler: EventHandler = () => {};
  private doneHandler: EventHandler = () => {};
  private errorHandler: EventHandler = () => {};
  private queuedHandler: EventHandler = () => {};
  // M5.2.1 WS 流式 chunk 批量节流器：60ms 窗口累积 chunk 减少 UI 重渲染次数
  private batcher: ChunkBatcher = new ChunkBatcher({ interval: 60 });
  // M5.2.2 消息列表 LazyForEach 数据源（与 messages 数组双写同步）
  private messagesDs: SimpleDataSource<ChatMessageView> = new SimpleDataSource<ChatMessageView>();

  aboutToAppear() {
    // 1. 从 store 读取当前 Agent 与列表缓存
    this.currentAgentId = this.agentsStore.currentAgentId;
    this.agents = this.agentsStore.agents;
    // 2. 尝试拉取最新 Agent 列表（失败时降级使用缓存，不影响页面渲染）
    this.loadAgents();
    // 3. 恢复会话上下文（SessionListPage 进入时写入 StateManager）
    const state = StateManager.getInstance();
    const activeId = state.get<string>('chat:active_session_id', '');
    if (activeId.length > 0) {
      this.sessionId = activeId;
      this.sessionTitle = state.get<string>('chat:active_session_title', '会话');
      this.fromList = true;
      this.loadHistory();
    }
    // 清键：下次直接进对话页回到新会话
    state.set('chat:active_session_id', '');
    state.set('chat:active_session_title', '');
    // 4. 建立 WS 连接
    this.connectWs();
    // 4. 订阅聊天事件
    this.subscribeEvents();
  }

  aboutToDisappear() {
    // 取消事件订阅，避免再次进入页面时重复绑定导致 chunk 被多次追加
    this.bus.off('chat:chunk', this.chunkHandler);
    this.bus.off('chat:done', this.doneHandler);
    this.bus.off('chat:error', this.errorHandler);
    this.bus.off('chat:queued', this.queuedHandler);
    // 断开 WS（adapter 内部会清理心跳与重连定时器）
    this.ws.disconnect();
    // M5.2.1 清理 chunk 缓冲，避免下次进入页面残留旧数据
    this.batcher.reset();
  }

  /**
   * 加载 Agent 列表
   * 流程：调用 API 刷新 → 写回 store；失败时降级使用缓存
   */
  private async loadAgents(): Promise<void> {
    try {
      this.agents = await this.api.agents.list();
      this.agentsStore.setAgents(this.agents);
      // 若 store 中无当前 Agent，默认选中第一个
      if (!this.currentAgentId && this.agents.length > 0) {
        this.currentAgentId = this.agents[0].id;
      }
    } catch (e) {
      this.logger.warn(TAG, '加载 Agent 列表失败，使用缓存', e as Error);
    }
  }

  /**
   * 拉取会话历史（同源 PC：GET /console/chat/history），{role,content} → ChatMessageView
   * 失败静默（不影响流式输入），toast 提示由 MessageManager 统一
   */
  private async loadHistory(): Promise<void> {
    try {
      const res = await this.api.sessions.history(this.sessionId);
      if (res.code === 0 && res.data) {
        const views: ChatMessageView[] = [];
        const raw = res.data.messages;
        for (let i = 0; i < raw.length; i++) {
          const m = raw[i];
          const content = m.content;
          if (content.length === 0) {
            continue;
          }
          views.push({
            id: 'h-' + i.toString(),
            role: m.role === 'user' ? 'user' : 'assistant',
            content: content,
            timestamp: 0,
            isStreaming: false,
          });
        }
        this.messages = views;
        this.messagesDs.setData(views);
        this.scrollToBottom();
      }
    } catch (e) {
      this.logger.warn(TAG, '拉取会话历史失败', e as Error);
    }
  }

  /**
   * 建立 WebSocket 连接
   * 配置：从 ConfigManager 读取 ws_base_url，携带 AuthStore 中的 access_token
   */
  private async connectWs(): Promise<void> {
    // 地址与凭证都来自**配对那一次**（AuthStore 里存着 resolve 回来的 wsUrl 与
    // 一次性接入凭证）。原先这里是 `config.get('ws_base_url', 'ws://192.168.10.132:9527/...')`
    // ——一台开发机的局域网 IP 写死在源码里，换网络即全体失联，打包后也改不动；
    // 而且带的凭证是登录用的 accessToken，不是配对下发的 ticket：后端只会按 ticket 认设备，
    // 于是这条面从来连不上，而失败被一句"WS 连接失败"抹平（§6-126 那一族）。
    const wsUrl = this.authStore.wsUrl;
    const ticket = this.authStore.wsToken;
    if (!wsUrl || !ticket) {
      this.logger.warn(TAG, '未配对或凭证已失效，不发起连接');
      this.msg.warning('还没有可连的服务器：请先扫码配对');
      return;
    }
    try {
      await this.ws.connect(wsUrl, ticket);
      this.logger.info(TAG, 'WS 连接成功');
    } catch (e) {
      this.logger.error(TAG, 'WS 连接失败', e as Error);
    }
  }

  /**
   * 订阅聊天事件
   * - chat:chunk：将 content 累积到 batcher，按 60ms 时间窗口批量追加到 streaming assistant 消息
   *   （M5.2.1 节流：避免每个 token 触发一次 UI 重渲染）
   * - chat:done：强制刷新剩余缓冲，结束最后一条消息的 streaming 状态，关闭 isGenerating
   * - chat:error：丢弃缓冲，关闭 isGenerating，结束 streaming，记录日志
   */
  private subscribeEvents(): void {
    this.chunkHandler = (data: Object) => {
      const msg = data as WSChatChunk;
      this.adoptServerSession(msg.session_id);
      // M5.2.1 累积到 batcher
      this.batcher.push(msg.content);
      if (this.batcher.shouldFlush(Date.now())) {
        const chunk = this.batcher.flush(Date.now());
        const last = this.messages[this.messages.length - 1];
        if (last && last.role === 'assistant' && last.isStreaming) {
          last.content += chunk;
          // 重新赋值触发 ArkUI 响应式更新
          this.messages = [...this.messages];
          // M5.2.2 同步 LazyForEach 数据源（ChunkBatcher 已节流到 60ms 一次）
          this.messagesDs.setData(this.messages);
          this.scrollToBottom();
        }
      }
    };
    this.bus.on('chat:chunk', this.chunkHandler);

    this.doneHandler = (data: Object) => {
      // 服务端对未知/缺省会话 id 会当场铸真记录——先采纳权威 id 再收尾
      this.adoptServerSession((data as WSChatDone).session_id);
      // M5.2.1 流结束，强制刷新剩余缓冲
      const rest = this.batcher.forceFlush();
      const last = this.messages[this.messages.length - 1];
      if (last && last.role === 'assistant' && last.isStreaming) {
        if (rest.length > 0) {
          last.content += rest;
        }
        last.isStreaming = false;
        this.messages = [...this.messages];
        // M5.2.2 同步 LazyForEach 数据源
        this.messagesDs.setData(this.messages);
      }
      this.isGenerating = false;
      this.queued = false;
      // 清理 batcher 以备下次会话
      this.batcher.reset();
      // 会话摘要已变（新会话落库/最新消息预览）——广播列表页刷新（会话与 PC 同源可见）
      this.bus.emit('chat:sessions-changed', '');
    };
    this.bus.on('chat:done', this.doneHandler);

    this.errorHandler = (data: Object) => {
      this.isGenerating = false;
      this.queued = false;
      // M5.2.1 错误时丢弃缓冲（避免显示半截内容）
      this.batcher.reset();
      const last = this.messages[this.messages.length - 1];
      if (last) {
        last.isStreaming = false;
        this.messages = [...this.messages];
        // M5.2.2 同步 LazyForEach 数据源
        this.messagesDs.setData(this.messages);
      }
      this.logger.error(TAG, '聊天错误', undefined, data);
    };
    this.bus.on('chat:error', this.errorHandler);

    // 排队事件（后端 chat:queued）：展示排队卡（设计 F5 .queued）
    this.queuedHandler = () => {
      this.queued = true;
    };
    this.bus.on('chat:queued', this.queuedHandler);
  }

  /**
   * 发送消息
   * 流程：校验输入 → 创建 user + assistant 占位 → WS 下发 chat:send
   * 校验：空文本或生成中直接返回，不发起请求
   */
  private async sendMessage(): Promise<void> {
    const text = this.inputText.trim();
    if (!text || this.isGenerating) {
      return;
    }

    // 用户消息
    const userMsg: ChatMessageView = {
      id: 'u-' + Date.now(),
      role: 'user',
      content: text,
      timestamp: Date.now(),
      isStreaming: false,
    };
    // assistant 占位消息（等待流式填充）
    const assistantMsg: ChatMessageView = {
      id: 'a-' + Date.now(),
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      isStreaming: true,
    };
    this.messages.push(userMsg, assistantMsg);
    this.messages = [...this.messages];
    // M5.2.2 同步 LazyForEach 数据源
    this.messagesDs.setData(this.messages);
    this.inputText = '';
    this.isGenerating = true;
    this.scrollToBottom();

    // 通过 WS 下发 chat:send
    try {
      await this.ws.send(JSON.stringify({
        type: 'chat:send',
        content: text,
        session_id: this.sessionId,
        agent_id: this.currentAgentId,
      }));
    } catch (e) {
      this.logger.error(TAG, '发送消息失败', e as Error);
      this.isGenerating = false;
      const last = this.messages[this.messages.length - 1];
      if (last && last.role === 'assistant') {
        last.isStreaming = false;
        // 诚实标注失败原因：发送抛错＝连接不可用（WS 死态 send 必抛「未连接」），
        // 不是模型产出为空。此前留空被渲染成「（空回复）」，把断连误当模型没回复，
        // 排障方向被带偏（2026-11-19 真机实测）
        last.content = '（消息未送达：连接不可用，请检查网络或重新配对）';
        this.messages = [...this.messages];
        // M5.2.2 同步 LazyForEach 数据源
        this.messagesDs.setData(this.messages);
      }
    }
  }

  /**
   * 停止生成
   * 流程：WS 下发 chat:cancel，立即关闭 isGenerating
   */
  private async stopGeneration(): Promise<void> {
    try {
      await this.ws.send(JSON.stringify({
        type: 'chat:cancel',
        session_id: this.sessionId,
      }));
    } catch (e) {
      this.logger.error(TAG, '停止生成失败', e as Error);
    }
    this.isGenerating = false;
  }

  /** 滚动到消息列表底部（新消息到达时调用） */
  private scrollToBottom(): void {
    if (this.messages.length > 0) {
      this.scroller.scrollToIndex(this.messages.length - 1);
    }
  }

  /** 格式化时间戳为 HH:mm */
  private formatTime(ts: number): string {
    const d = new Date(ts);
    const h = d.getHours().toString().padStart(2, '0');
    const m = d.getMinutes().toString().padStart(2, '0');
    return `${h}:${m}`;
  }

  /** 获取当前 Agent 名称（用于 assistant 气泡署名，无则回退 '助手'） */
  private getAgentName(): string {
    const agent = this.agents.find(a => a.id === this.currentAgentId);
    return agent?.name ?? '助手';
  }

  /** 采纳服务端权威会话 id：后端对未知/缺省 id 会当场铸真记录并随事件回传——
   * 端上旧自铸 id 即刻弃用，后续 chat:send/stop/历史都改用权威 id（会话列表与 PC 同源） */
  private adoptServerSession(id: string): void {
    if (id.length > 0 && id !== this.sessionId) {
      this.sessionId = id;
      StateManager.getInstance().set('chat:active_session_id', id);
    }
  }

  // ===========================================================================
  // F6 会话抽屉（设计 .drawer-wrap：右缘滑出，与 PC 会话侧栏同端点同操作集）
  // ===========================================================================

  /** 呼出抽屉并拉取会话/归档两份列表 */
  private openDrawer(): void {
    this.drawerOpen = true;
    this.archivedOpen = false;
    this.searchKeyword = '';
    this.loadDrawerSessions();
  }

  /** 拉取会话摘要 + 归档列表（归档失败仅记日志，不阻塞主列表） */
  private async loadDrawerSessions(): Promise<void> {
    try {
      const res = await this.api.sessions.listAll('');
      if (res.code === 0 && res.data) {
        this.drawerSessions = res.data.sessions;
      }
    } catch (e) {
      this.msg.error('会话列表加载失败：' + (e as Error).message);
    }
    try {
      const arch = await this.api.sessions.listArchived('');
      if (arch.code === 0 && arch.data) {
        this.archivedSessions = arch.data.sessions;
      }
    } catch (e) {
      this.logger.warn(TAG, '归档会话加载失败', e as Error);
    }
    this.drawerRev += 1;
  }

  /** updated_at 是否为今天（本地时区；解析失败按非今天归入「更早」） */
  private isToday(dateStr: string): boolean {
    if (!dateStr || dateStr.length === 0) {
      return false;
    }
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) {
      return false;
    }
    const now = new Date();
    return d.getFullYear() === now.getFullYear()
      && d.getMonth() === now.getMonth()
      && d.getDate() === now.getDate();
  }

  /** 抽屉分组：置顶 → 今天 → 更早，组内按更新时间倒序；带搜索词过滤 */
  private drawerGroups(): DrawerGroup[] {
    const kw = this.searchKeyword.trim().toLowerCase();
    const pinned: ChatSession[] = [];
    const today: ChatSession[] = [];
    const earlier: ChatSession[] = [];
    for (const s of this.drawerSessions) {
      if (kw.length > 0 && s.title.toLowerCase().indexOf(kw) === -1) {
        continue;
      }
      if (s.pinned) {
        pinned.push(s);
      } else if (this.isToday(s.updated_at)) {
        today.push(s);
      } else {
        earlier.push(s);
      }
    }
    const byTime = (a: ChatSession, b: ChatSession): number => {
      const ta = new Date(a.updated_at).getTime();
      const tb = new Date(b.updated_at).getTime();
      return (isNaN(tb) ? 0 : tb) - (isNaN(ta) ? 0 : ta);
    };
    pinned.sort(byTime);
    today.sort(byTime);
    earlier.sort(byTime);
    const groups: DrawerGroup[] = [];
    if (pinned.length > 0) {
      groups.push({ label: '置顶', items: pinned });
    }
    if (today.length > 0) {
      groups.push({ label: '今天', items: today });
    }
    if (earlier.length > 0) {
      groups.push({ label: '更早', items: earlier });
    }
    return groups;
  }

  /** 抽屉内点击会话：切换当前会话并拉取历史 */
  private switchToSession(s: ChatSession): void {
    if (s.id === this.sessionId) {
      this.drawerOpen = false;
      return;
    }
    this.sessionId = s.id;
    this.sessionTitle = s.title;
    this.fromList = true;
    this.drawerOpen = false;
    this.messages = [];
    this.messagesDs.setData([]);
    this.loadHistory();
  }

  /** 新建会话：回到未落库的新会话态（首次发言后由后端建档） */
  private startNewSession(): void {
    this.drawerOpen = false;
    this.sessionId = 'session-' + Date.now().toString();
    this.sessionTitle = '新对话';
    this.fromList = false;
    this.isGenerating = false;
    this.messages = [];
    this.messagesDs.setData([]);
  }

  /** 置顶/取消置顶（后端 PinSessionRequest {pinned}；按翻转当前态提交） */
  private async togglePin(s: ChatSession): Promise<void> {
    try {
      await this.api.sessions.pin(s.id, !s.pinned);
      this.msg.success(s.pinned ? '已取消置顶' : '已置顶');
      this.loadDrawerSessions();
    } catch (e) {
      this.msg.error('置顶失败：' + (e as Error).message);
    }
  }

  private openRename(s: ChatSession): void {
    this.renamingSession = s;
    this.renameText = s.title;
  }

  private async confirmRename(): Promise<void> {
    const target = this.renamingSession;
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
      this.renamingSession = null;
      if (target.id === this.sessionId) {
        this.sessionTitle = title;
      }
      this.loadDrawerSessions();
    } catch (e) {
      this.msg.error('重命名失败：' + (e as Error).message);
    }
  }

  /** 单会话操作菜单：分叉 / 归档 / 删除（重命名走条目上的编辑图标） */
  private showItemActions(s: ChatSession): void {
    AlertDialog.show({
      title: s.title.length > 0 ? s.title : '会话操作',
      message: '选择会话操作',
      autoCancel: true,
      alignment: DialogAlignment.Center,
      buttons: [
        {
          value: '分叉',
          action: () => {
            this.forkSession(s);
          }
        },
        {
          value: '归档',
          action: () => {
            this.archiveById(s);
          }
        },
        {
          value: '删除',
          fontColor: this.sm.getColor('error'),
          action: () => {
            this.confirmDeleteSession(s);
          }
        }
      ]
    });
  }

  private async forkSession(s: ChatSession): Promise<void> {
    try {
      await this.api.sessions.fork(s.id);
      this.msg.success('已分叉出新会话');
      this.loadDrawerSessions();
    } catch (e) {
      this.msg.error('分叉失败：' + (e as Error).message);
    }
  }

  private async archiveById(s: ChatSession): Promise<void> {
    try {
      await this.api.sessions.archive(s.id);
      this.msg.success('已归档');
      if (s.id === this.sessionId) {
        // 当前会话被归档：回到新会话态，避免继续往归档会话里发言
        this.startNewSession();
      }
      this.loadDrawerSessions();
    } catch (e) {
      this.msg.error('归档失败：' + (e as Error).message);
    }
  }

  private confirmDeleteSession(s: ChatSession): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除会话"${s.title}"吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '删除',
        fontColor: this.sm.getColor('error'),
        action: () => {
          this.deleteSession(s);
        }
      }
    });
  }

  private async deleteSession(s: ChatSession): Promise<void> {
    try {
      await this.api.sessions.remove(s.id);
      this.msg.success('已删除');
      if (s.id === this.sessionId) {
        this.startNewSession();
      }
      this.loadDrawerSessions();
    } catch (e) {
      this.msg.error('删除失败：' + (e as Error).message);
    }
  }

  private async unarchiveSession(s: ChatSession): Promise<void> {
    try {
      await this.api.sessions.unarchive(s.id);
      this.msg.success('已恢复');
      this.loadDrawerSessions();
    } catch (e) {
      this.msg.error('恢复失败：' + (e as Error).message);
    }
  }

  /** 抽屉条目头像：按 agent_id 找名称首字，找不到回退「会」 */
  private getAgentInitial(agentId: string): string {
    for (const a of this.agents) {
      if (a.id === agentId && a.name.length > 0) {
        return a.name.slice(0, 1);
      }
    }
    return '会';
  }

  build() {
    Stack() {
      Column() {
        // 顶部玻璃头（原型 F5：返回 + Agent 头像 + 会话名/状态 + ⋯呼出会话抽屉）
        Row() {
          IconBtn({ name: 'back', onTap: () => { this.router.back(); } })
          Text(this.getAgentName().slice(0, 1))
            .fontSize(13)
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_on_primary'))
            .width(32)
            .height(32)
            .borderRadius(11)
            .textAlign(TextAlign.Center)
            .linearGradient({ angle: 135, colors: [[this.sm.getColor('secondary'), 0], [this.sm.getColor('primary'), 1]] })
            .margin({ left: 8 })
          Column() {
            Text(this.sessionTitle.length > 0 ? this.sessionTitle : '新对话')
              .fontSize(this.sm.getFontSize('card_title'))
              .fontWeight(FontWeight.Medium)
              .fontColor(this.sm.getColor('text_primary'))
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
            Text(this.getAgentName() + ' · ' + (this.isGenerating ? '生成中' : '就绪'))
              .fontSize(this.sm.getFontSize('badge'))
              .fontColor(this.isGenerating ? this.sm.getColor('success') : this.sm.getColor('text_tertiary'))
              .margin({ top: 1 })
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)
          .margin({ left: 8 })
          IconBtn({ name: 'more', onTap: () => { this.openDrawer(); } })
        }
        .width('100%')
        .padding({ left: 12, right: 12, top: 6, bottom: 8 })
        .backgroundColor(this.sm.getColor('surface_strong'))
        .border({ width: { bottom: 1 }, color: this.sm.getColor('divider') })
        .alignItems(VerticalAlign.Center)

        // Agent 切换器已按产品要求移出对话页顶部：会话列表走右缘抽屉，
        // 切 Agent 走智能体列表页发起会话（顶部只留标题 + 状态 + 抽屉入口）

        // 消息列表区
        if (this.messages.length === 0) {
          // 空状态：居中欢迎语
          Column() {
            Text('开始新对话')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          // 消息列表：纵向滚动，关闭滚动条
          // M5.2.2 改用 LazyForEach 惰性渲染，仅渲染可见区域 + 缓存项
          // key 必须带上内容长度：流式回复是**原地改写同一对象**（content 追加），
          // id 不变时 LazyForEach 按键复用组件、不重渲染该条目——这正是
          // 「流式回复只显示光标、文本永不出现」（空回复）的根因
          List({ space: this.sm.getSpacing('sm'), scroller: this.scroller }) {
            LazyForEach(this.messagesDs, (msg: ChatMessageView) => {
              ListItem() {
                this.buildMessage(msg)
              }
            }, (msg: ChatMessageView) => msg.id + '#' + msg.content.length.toString())
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

        // 会话进度卡（设计 F5 .prog：流式生成中展示；步骤数后端未下发，不做假进度）
        if (this.isGenerating) {
          Row() {
            AppIcon({ name: 'history', iconSize: 13, color: this.sm.getColor('accent') })
            Text('会话进行中 · 正在生成回复')
              .fontSize(this.sm.getFontSize('badge'))
              .fontWeight(FontWeight.Medium)
              .fontColor(this.sm.getColor('text_primary'))
              .margin({ left: 7 })
            LoadingProgress()
              .width(14)
              .height(14)
              .color(this.sm.getColor('accent'))
              .margin({ left: 6 })
          }
          .width('100%')
          .padding({ left: 13, right: 13, top: 10, bottom: 10 })
          .borderRadius(12)
          .backgroundColor(this.sm.getColor('glass'))
          .border({ width: 1, color: this.sm.getColor('border') })
          .margin({
            left: this.sm.getSpacing('md'),
            right: this.sm.getSpacing('md'),
            bottom: this.sm.getSpacing('sm'),
          })
        }

        // 排队卡（设计 F5 .queued：后端 chat:queued 事件驱动，黄色虚线框）
        if (this.queued) {
          Row() {
            AppIcon({ name: 'pause', iconSize: 14, color: this.sm.getColor('warning') })
            Text('消息已排队，等待 Agent 空闲…')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ left: 8 })
          }
          .width('100%')
          .padding({ left: 13, right: 13, top: 9, bottom: 9 })
          .borderRadius(14)
          .border({ width: 1, color: 'rgba(251,191,36,0.40)', style: BorderStyle.Dashed })
          .backgroundColor('rgba(251,191,36,0.08)')
          .margin({
            left: this.sm.getSpacing('md'),
            right: this.sm.getSpacing('md'),
            bottom: this.sm.getSpacing('sm'),
          })
        }

        // 输入区（设计 F5 .inputbar：附件/语音 + 胶囊输入框 + 圆形发送/停止）
        Row() {
          IconBtn({ name: 'clip', onTap: () => { this.msg.info('附件发送即将开放'); } })
          IconBtn({ name: 'mic', onTap: () => { this.msg.info('语音输入即将开放'); } })
            .margin({ left: 8 })

          GlassInput({
            placeholder: '输入消息...',
            value: this.inputText,
            type: 'text',
            cornerRadius: 999,
            onChange: (v: string) => { this.inputText = v; },
            onSubmit: () => { this.sendMessage(); }
          })
            .layoutWeight(1)
            .margin({ left: 8 })

          if (this.isGenerating) {
            // 生成中：红色圆形停止钮（设计 .sendbtn.stop）
            Column() {
              AppIcon({ name: 'stop', iconSize: 18, color: this.sm.getColor('error') })
            }
            .width(42)
            .height(42)
            .borderRadius(21)
            .backgroundColor('rgba(248,113,113,0.18)')
            .border({ width: 1, color: 'rgba(248,113,113,0.50)' })
            .justifyContent(FlexAlign.Center)
            .alignItems(HorizontalAlign.Center)
            .margin({ left: 8 })
            .onClick(() => { this.stopGeneration(); })
          } else {
            // 空闲：品牌渐变圆形发送钮（设计 .sendbtn）
            Column() {
              AppIcon({ name: 'send', iconSize: 18, color: '#FFFFFF' })
            }
            .width(42)
            .height(42)
            .borderRadius(21)
            .linearGradient({ angle: 135, colors: this.sm.getBrandGradient() })
            .shadow({ radius: 18, color: 'rgba(99,102,241,0.45)', offsetY: 6 })
            .justifyContent(FlexAlign.Center)
            .alignItems(HorizontalAlign.Center)
            .margin({ left: 8 })
            .opacity(this.inputText.trim().length === 0 ? 0.5 : 1)
            .onClick(() => { this.sendMessage(); })
          }
        }
        .width('100%')
        .padding(this.sm.getSpacing('md'))
        .alignItems(VerticalAlign.Center)
      }
      .width('100%')
      .height('100%')
      .backgroundColor(this.sm.getColor('background'))

      // F6 会话抽屉：右缘滑出 + 半透明遮罩（设计 .drawer-wrap）
      if (this.drawerOpen) {
        this.buildDrawer()
      }

      // 重命名弹层（抽屉条目编辑图标呼出；AlertDialog 无输入框故用页面内弹层）
      if (this.renamingSession !== null) {
        this.buildRenameOverlay()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // F6 会话抽屉构建器
  // ===========================================================================

  /** 抽屉层：遮罩（点击收起）+ 右缘抽屉本体（设计 .drawer：300px → 76% 上限 340） */
  @Builder
  buildDrawer() {
    Row() {
      Column()
        .layoutWeight(1)
        .height('100%')
        .backgroundColor('rgba(4,6,14,0.60)')
        .onClick(() => { this.drawerOpen = false; })

      Column() {
        // 头部：会话 + 计数 + 新建（设计 .dh；「运行中」计数后端未下发，只显示真实总数）
        Row() {
          Text('会话')
            .fontSize(16)
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
          Text(this.drawerSessions.length.toString() + ' 个')
            .fontSize(this.sm.getFontSize('badge'))
            .fontColor(this.sm.getColor('text_tertiary'))
            .margin({ left: 6 })
          Blank()
          Column() {
            AppIcon({ name: 'plus', iconSize: 14, color: this.sm.getColor('text_on_primary') })
          }
          .width(30)
          .height(30)
          .borderRadius(10)
          .linearGradient({ angle: 135, colors: this.sm.getBrandGradient() })
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
          .onClick(() => { this.startNewSession(); })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
        .padding({ left: 8, right: 8, bottom: 12 })

        // 跨会话搜索（已加载摘要的客户端过滤；后端无会话搜索端点，不设假联查）
        GlassInput({
          placeholder: '跨会话搜索',
          iconName: 'search',
          value: this.searchKeyword,
          onChange: (v: string) => { this.searchKeyword = v; }
        })
          .margin({ bottom: 12 })

        // 分组列表：置顶 → 今天 → 更早（设计 .grp/.di）
        Scroll() {
          Column() {
            ForEach(this.drawerGroups(), (group: DrawerGroup) => {
              Text(group.label)
                .fontSize(10.5)
                .fontColor(this.sm.getColor('text_tertiary'))
                .letterSpacing(1.5)
                .padding({ left: 10, top: 8, bottom: 4 })
              ForEach(group.items, (s: ChatSession) => {
                this.drawerItem(s)
              }, (s: ChatSession) => s.id + '#' + s.title + '#' + this.drawerRev.toString())
            }, (group: DrawerGroup) => group.label + '#' + this.drawerRev.toString())
          }
          .width('100%')
          .alignItems(HorizontalAlign.Start)
        }
        .layoutWeight(1)
        .width('100%')
        .scrollBar(BarState.Off)
        .align(Alignment.Top)

        // 底部：归档会话入口（GET /console/chat/sessions/archived 真数据；设计 .foot）
        Column() {
          Row() {
            AppIcon({ name: 'archive', iconSize: 14, color: this.sm.getColor('secondary') })
            Text('查看 ' + this.archivedSessions.length.toString() + ' 个归档会话')
              .fontSize(12)
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ left: 8 })
              .layoutWeight(1)
            AppIcon({ name: this.archivedOpen ? 'chev' : 'fork', iconSize: 12, color: this.sm.getColor('text_tertiary') })
          }
          .width('100%')
          .padding({ top: 12, bottom: 6 })
          .border({ width: { top: 1 }, color: this.sm.getColor('divider') })
          .alignItems(VerticalAlign.Center)
          .onClick(() => { this.archivedOpen = !this.archivedOpen; })

          if (this.archivedOpen) {
            Column() {
              if (this.archivedSessions.length === 0) {
                Text('暂无归档会话')
                  .fontSize(11.5)
                  .fontColor(this.sm.getColor('text_tertiary'))
                  .padding({ left: 8, top: 6, bottom: 6 })
              }
              ForEach(this.archivedSessions, (s: ChatSession) => {
                Row() {
                  Text(s.title.length > 0 ? s.title : '新对话')
                    .fontSize(12)
                    .fontColor(this.sm.getColor('text_secondary'))
                    .maxLines(1)
                    .textOverflow({ overflow: TextOverflow.Ellipsis })
                    .layoutWeight(1)
                  Text('恢复')
                    .fontSize(11)
                    .fontColor(this.sm.getColor('primary'))
                    .padding({ left: 10, right: 4, top: 4, bottom: 4 })
                    .onClick(() => { this.unarchiveSession(s); })
                }
                .width('100%')
                .padding({ left: 8, right: 8, top: 4, bottom: 4 })
                .alignItems(VerticalAlign.Center)
              }, (s: ChatSession) => s.id + '#' + s.title + '#' + this.drawerRev.toString())
            }
            .width('100%')
          }
        }
        .width('100%')
      }
      .width('76%')
      .constraintSize({ maxWidth: 340 })
      .height('100%')
      .backgroundColor(this.sm.getColor('surface_strong'))
      .border({ width: { left: 1 }, color: this.sm.getColor('border') })
      .padding({ left: 14, right: 14, top: 52, bottom: 14 })
    }
    .width('100%')
    .height('100%')
  }

  /** 抽屉单条会话（设计 .di：头像 + 标题 + pin/操作图标；当前会话高亮） */
  @Builder
  drawerItem(s: ChatSession) {
    Row() {
      Text(this.getAgentInitial(s.agent_id))
        .fontSize(11)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.sm.getColor('text_on_primary'))
        .width(26)
        .height(26)
        .borderRadius(9)
        .textAlign(TextAlign.Center)
        .linearGradient({ angle: 135, colors: [[this.sm.getColor('secondary'), 0], [this.sm.getColor('primary'), 1]] })
      Text(s.title.length > 0 ? s.title : '新对话')
        .fontSize(12.5)
        .fontColor(this.sm.getColor('text_primary'))
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
        .layoutWeight(1)
        .margin({ left: 10 })
      // 操作图标各自包容器承接点击（自定义组件不外链 onClick）
      Column() {
        AppIcon({ name: 'pin', iconSize: 13, color: s.pinned ? this.sm.getColor('primary') : this.sm.getColor('text_tertiary') })
      }
      .padding(3)
      .onClick(() => { this.togglePin(s); })
      if (s.pinned) {
        Column() {
          AppIcon({ name: 'edit', iconSize: 13, color: this.sm.getColor('text_tertiary') })
        }
        .padding(3)
        .margin({ left: 6 })
        .onClick(() => { this.openRename(s); })
      } else {
        Column() {
          AppIcon({ name: 'more', iconSize: 13, color: this.sm.getColor('text_tertiary') })
        }
        .padding(3)
        .margin({ left: 6 })
        .onClick(() => { this.showItemActions(s); })
      }
    }
    .width('100%')
    .padding({ left: 10, right: 10, top: 10, bottom: 10 })
    .borderRadius(12)
    .backgroundColor(s.id === this.sessionId ? 'rgba(99,102,241,0.16)' : 'rgba(0,0,0,0)')
    .border({
      width: 1,
      color: s.id === this.sessionId ? 'rgba(99,102,241,0.35)' : 'rgba(0,0,0,0)'
    })
    .margin({ bottom: 2 })
    .alignItems(VerticalAlign.Center)
    .onClick(() => { this.switchToSession(s); })
  }

  /** 重命名弹层：居中玻璃卡 + 输入 + 取消/保存 */
  @Builder
  buildRenameOverlay() {
    Column() {
      Column() {
        Text('重命名会话')
          .fontSize(15)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))
        GlassInput({
          placeholder: '会话标题',
          value: this.renameText,
          onChange: (v: string) => { this.renameText = v; },
          onSubmit: () => { this.confirmRename(); }
        })
          .margin({ top: 12 })
        Row() {
          Text('取消')
            .fontSize(13)
            .fontColor(this.sm.getColor('text_secondary'))
            .padding({ left: 14, right: 14, top: 8, bottom: 8 })
            .onClick(() => { this.renamingSession = null; })
          Text('保存')
            .fontSize(13)
            .fontWeight(FontWeight.Medium)
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 16, right: 16, top: 8, bottom: 8 })
            .borderRadius(10)
            .linearGradient({ angle: 135, colors: this.sm.getBrandGradient() })
            .margin({ left: 8 })
            .onClick(() => { this.confirmRename(); })
        }
        .width('100%')
        .justifyContent(FlexAlign.End)
        .margin({ top: 14 })
      }
      .width('82%')
      .constraintSize({ maxWidth: 320 })
      .padding(16)
      .borderRadius(16)
      .backgroundColor(this.sm.getColor('surface_strong'))
      .border({ width: 1, color: this.sm.getColor('border') })
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .height('100%')
    .backgroundColor('rgba(4,6,14,0.60)')
    .justifyContent(FlexAlign.Center)
    .alignItems(HorizontalAlign.Center)
  }

  // ===========================================================================
  // 消息气泡构建器
  // ===========================================================================

  /** 单条消息气泡：根据 role 选择右对齐（user）/ 左对齐（assistant） */
  @Builder
  buildMessage(msg: ChatMessageView) {
    if (msg.role === 'user') {
      // 用户消息：右对齐，品牌渐变背景，右下直角（设计 .bub.me）
      Row() {
        Column() {
          Text(msg.content)
            .fontSize(this.sm.getFontSize('body_sm'))
            .fontColor(this.sm.getColor('text_on_primary'))
          // 时间戳
          Text(this.formatTime(msg.timestamp))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .opacity(0.8)
            .margin({ top: 4 })
            .alignSelf(ItemAlign.End)
        }
        .padding({
          left: this.sm.getSpacing('md'),
          right: this.sm.getSpacing('md'),
          top: this.sm.getSpacing('sm'),
          bottom: this.sm.getSpacing('sm'),
        })
        .borderRadius({
          topLeft: 16,
          topRight: 16,
          bottomLeft: 16,
          bottomRight: 6
        })
        .linearGradient({ angle: 135, colors: this.sm.getBrandGradient() })
        // 限制气泡最大宽度，避免占满整行
        .constraintSize({ maxWidth: '75%' })
        .alignItems(HorizontalAlign.Start)
      }
      .width('100%')
      .justifyContent(FlexAlign.End)
    } else {
      // assistant 消息：左对齐，玻璃卡，左下直角（设计 .bub.ai）
      // 宽度直接定值 78%（constraintSize 与子 width('100%') 组合存在
      // 布局歧义——真机实测 GlassPanel 溢出左缘裁切，改定宽消除歧义）
      Row() {
        Column() {
          Column() {
            // Agent 署名
            Text(this.sessionTitle.length > 0 ? this.sessionTitle : this.getAgentName())
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ bottom: 4 })
            // 消息内容 + 流式光标
            Row() {
              Text(msg.content.length > 0 ? msg.content : (msg.isStreaming ? '' : '（空回复）'))
                .fontSize(this.sm.getFontSize('body_sm'))
                .fontColor(this.sm.getColor('text_primary'))
              // 流式生成中显示闪烁光标
              if (msg.isStreaming) {
                Text('▍')
                  .fontSize(this.sm.getFontSize('body_sm'))
                  .fontColor(this.sm.getColor('primary'))
                  .margin({ left: 2 })
              }
            }
            .alignItems(VerticalAlign.Bottom)
            // 时间戳
            Text(this.formatTime(msg.timestamp))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_disabled'))
              .margin({ top: 4 })
              .alignSelf(ItemAlign.End)
          }
          .alignItems(HorizontalAlign.Start)
          .width('100%')
          .padding(this.sm.getSpacing('md'))
          .borderRadius({
            topLeft: 16,
            topRight: 16,
            bottomLeft: 6,
            bottomRight: 16
          })
          .backgroundColor(this.sm.getColor('surface_strong'))
          .border({ width: 1, color: this.sm.getColor('border') })
        }
        .width('78%')
      }
      .width('100%')
      .justifyContent(FlexAlign.Start)
    }
  }
}
