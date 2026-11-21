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
import { ModelInfoDto } from '../libs/api/modules/ProvidersApi';
import { AuthStore } from '../libs/state/stores/AuthStore';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { StateManager } from '../libs/state/StateManager';
import { WebSocketAdapter } from '../libs/adapters/WebSocketAdapter';
import { StorageAdapter } from '../libs/adapters/StorageAdapter';
import { EventBus, EventHandler } from '../libs/bus/EventBus';
import { ConfigManager } from '../libs/config/ConfigManager';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { WSChatChunk, WSChatDone, WSChatReasoning, WSChatSend, WSChatToolCall, WSChatToolResult, WSChatArtifact, WSChatPlanUpdate, WSChatUsage, WSChatApprovalRequired, WSModelListResult, WSContextCompositionResult, WSArtifactContentResult, Agent } from '../libs/types';
import { Router } from '../routing/Router';
import { ChunkBatcher } from '../libs/perf/ChunkBatcher';
import { SimpleDataSource } from '../libs/perf/SimpleDataSource';
import { ChatSession, ChatHistoryMessage } from '../libs/api/modules/SessionsApi';
import { MarkdownText } from '../components/chat/MarkdownText';
import { SwarmFlowPanel } from '../components/chat/SwarmFlowPanel';
import { speechRecognizer } from '@kit.CoreSpeechKit';
import { audio } from '@kit.AudioKit';
import { abilityAccessCtrl, Permissions } from '@kit.AbilityKit';
import { AsrStreamClient } from '../libs/adapters/AsrStreamClient';
import { HttpClient } from '../libs/api/HttpClient';
import { util } from '@kit.ArkTS';

/** 对话消息视图模型（仅用于本页渲染） */
interface ChatMessageView {
  id: string;               // 消息唯一 ID
  role: 'user' | 'assistant'; // 角色
  content: string;          // 文本内容
  timestamp: number;        // 毫秒时间戳
  isStreaming: boolean;     // 是否正在流式生成
  reasoning: string;        // 思考流累积（chat:reasoning）
  toolCalls: ToolCallView[]; // 工具调用/结果卡（chat:tool_call / chat:tool_result）
  artifacts: ArtifactView[]; // 产出物卡（chat:artifact，console 从 tool_result 派生）
  plan: PlanStepView[];     // 计划时间轴（chat:plan_update）
  approval: string;         // 最近一条治理审批请求摘要（chat:approval_required；裁决在 PC 端）
}

/** 工具调用卡片视图模型 */
interface ToolCallView {
  name: string;
  args: string;
  result: string;
}

/** 产出物卡片视图模型（chat:artifact.data 投影） */
interface ArtifactView {
  artifactId: string;
  name: string;
  kind: string;
  size: number;
}

/** 计划步骤视图模型（chat:plan_update.data.plan 投影） */
interface PlanStepView {
  step: string;
  status: string;
}

/** 日志标签 */
const TAG = 'ChatPage';

/** 会话抽屉分组（设计 F6 .grp：置顶/今天/更早） */
interface DrawerGroup {
  label: string;
  items: ChatSession[];
}

/** 胶囊菜单分组（模型菜单按服务商分组；header 为空串即无组头） */
interface PillMenuGroup {
  header: string;
  items: MenuElement[];
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
  // 蜂群协作图增量信号（车道F）：chat:done（回合终结）自增，触发 SwarmFlowPanel 静默重拉。
  // 移动端 WS 帧型不含 subagent_started/completed（那是 PC /sync 通道词汇），故借道回合终态。
  @State swarmRefreshTick: number = 0;
  // 会话是否来自列表（可置顶/归档；新会话未落库，操作会 404）。
  // adoptServerSession 采纳服务端铸真的会话 id 后同样置位——语义即「会话已落库」
  private fromList: boolean = false;
  // ── D3 steady 化：重连/快照重建期间的列表稳态记账 ──
  // 首连标记：首连的会话历史恢复走进页既有链路（aboutToAppear → loadHistory），
  // 只有**重连**（含 sync_snapshot_required 弃游标重连）才触发快照重同步，避免进页双拉
  private hasConnectedOnce: boolean = false;
  // 重连时有回合在途：此刻不能拿服务端时间线覆盖列表（在途 chunk 尚未落时间线，
  // 写入会清掉流式占位气泡）——先记账，待回合终态（done/error）后再补快照
  private pendingSnapshotResync: boolean = false;
  // 会话快照装载代次：仅最新一次装载可写视图，晚到的旧快照不覆盖新状态。
  // 页内无 seq/时间戳可判新旧，按事件到达序递增（同 SwarmFlowPanel.fetchSeq 形态）
  private historyLoadSeq: number = 0;
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

  // ── 对齐 PC 对话页五件套（模型/思考深度/权限模式/执行档位/上下文面板）──
  // 回合控制四字段：随 chat:send 下发（后端并入 turnMetadata，管线现成消费点）
  @State selectedModel: string = '';
  @State thinkingEffort: string = 'standard';
  @State permissionMode: string = '';
  @State taskProfile: string = '';
  // 模型候选（REST /models 预取为主；model:list WS 代理为兜底刷新）
  @State modelOptions: Array<Record<string, Object>> = [];
  @State modelOptionsLoaded: boolean = false;
  // 胶囊菜单当前分组数据：开菜单时快照进 @State——弹层 subtree 不随
  // modelOptions/pillMenuOpen 的后续变化重渲染（真机实证的冻结坑），故用
  // 「赋值替换数组」驱动 ForEach 重建
  @State pillGroups: PillMenuGroup[] = [];
  // 上下文面板（context:composition WS 代理 + chat:usage 累计）
  @State contextOpen: boolean = false;
  @State composition: Record<string, Object> | null = null;
  @State compositionReason: string = '';
  @State usageTotal: number = 0;
  // 产出物预览弹层（artifact:get WS 代理取内容）
  @State previewArtifact: ArtifactView | null = null;
  @State previewContent: string = '';
  @State previewEncoding: string = '';
  @State previewMime: string = '';
  @State previewLoading: boolean = false;
  // 胶囊菜单弹层：'' | model | effort | mode | profile
  @State pillMenuOpen: string = '';
  // 上下文面板派生读数（@Builder 内不做 Record 解析，直读 State）
  @State compTotal: number = 0;
  @State compWindow: number = 0;
  @State compMsgTokens: number = 0;
  @State compToolTokens: number = 0;
  @State compCacheRate: number = -1; // -1 = 无命中率数据

  // 统一库单例
  private api = ApiFacade.getInstance();
  private authStore = new AuthStore();
  private agentsStore = new AgentsStore();
  private ws = WebSocketAdapter.getInstance();
  // 远程驾驶可靠性（服务端指令记账的客户端配对）：在途指令记账，断线重连后
  // 以同一 command_id 重发——服务端按 (设备, 指令 id) 幂等，不会二次执行
  private inFlightCommandId: string = '';
  private inFlightPayload: string = '';
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
  private reasoningHandler: EventHandler = () => {};
  private toolCallHandler: EventHandler = () => {};
  private toolResultHandler: EventHandler = () => {};
  private artifactHandler: EventHandler = () => {};
  private planHandler: EventHandler = () => {};
  private usageHandler: EventHandler = () => {};
  private approvalHandler: EventHandler = () => {};
  private modelListHandler: EventHandler = () => {};
  private compositionHandler: EventHandler = () => {};
  private artifactContentHandler: EventHandler = () => {};
  private connectedHandler: EventHandler = () => {};
  // 语音输入（CoreSpeechKit 端侧识别 + AudioCapturer 采集喂入）
  @State voiceListening: boolean = false;
  private voiceEngine: speechRecognizer.SpeechRecognitionEngine | null = null;
  private voiceCapturer: audio.AudioCapturer | null = null;
  private voiceSessionId: string = '';
  // 后端流式 ASR 通道（端侧 CoreSpeechKit 不可用时的回落，对照报告 B4-1）
  private asrStream: AsrStreamClient | null = null;
  private backendVoiceActive: boolean = false;
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
    // 5. 模型候选预取（REST 同源 PC /models；失败留待开菜单时走 WS 兜底）
    this.fetchModelsRest();
  }

  aboutToDisappear() {
    // 取消事件订阅，避免再次进入页面时重复绑定导致 chunk 被多次追加
    this.bus.off('chat:chunk', this.chunkHandler);
    this.bus.off('chat:done', this.doneHandler);
    this.bus.off('chat:error', this.errorHandler);
    this.bus.off('chat:queued', this.queuedHandler);
    this.bus.off('chat:reasoning', this.reasoningHandler);
    this.bus.off('chat:tool_call', this.toolCallHandler);
    this.bus.off('chat:tool_result', this.toolResultHandler);
    this.bus.off('chat:artifact', this.artifactHandler);
    this.bus.off('chat:plan_update', this.planHandler);
    this.bus.off('chat:usage', this.usageHandler);
    this.bus.off('chat:approval_required', this.approvalHandler);
    this.bus.off('model:list_result', this.modelListHandler);
    this.bus.off('context:composition_result', this.compositionHandler);
    this.bus.off('artifact:content_result', this.artifactContentHandler);
    this.bus.off('ws:connected', this.connectedHandler);
    // 语音资源收尾（识别引擎/采集器可能仍在运行）
    this.stopVoice();
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
   *
   * D3 steady 化：本方法是会话消息列表的「快照装载」入口（进页/切会话/重连重同步共用）。
   * 装载全程不清空旧行、不进加载态；新快照在末尾经 applyHistorySnapshot 一次性原子替换。
   * @param scrollToLatest 写入成功后是否滚到底部（重连重同步传 false，避免拽动阅读位置）
   * @returns 是否真正写入视图（过期装载/取数失败返回 false，调用方据此决定是否补拉）
   */
  private async loadHistory(scrollToLatest: boolean = true): Promise<boolean> {
    // 会话身份与装载代次锚点：装载是异步链路，中途切会话 / 更新装载启动 /
    // 装载期间开新回合都会使本次结果过期——过期响应一律弃写，不覆盖当前视图
    // （对齐 SwarmFlowPanel「过期响应不写当前视图」纪律）。
    const sid = this.sessionId;
    const loadSeq = ++this.historyLoadSeq;
    const generatingAtStart = this.isGenerating;
    // 终端侧缓存 + 时间线增量同步：进页先上屏缓存，再只拉未加载的事件
    // （offset=已缓存条数），不再每次全量拉历史。时间线为空的旧会话退回
    // 纯文本历史（那之后产生的回合才有卡片可重放）。
    const cacheKey = 'chat_tl_cache_' + sid;
    const storage = StorageAdapter.getInstance();
    let views: ChatMessageView[] = [];
    let cachedCount = 0;
    try {
      const raw = await storage.get<string>(cacheKey, '');
      if (raw.length > 0) {
        const parsed = JSON.parse(raw) as Record<string, Object>;
        cachedCount = Number(parsed['eventCount'] ?? 0);
        const rawViews = (parsed['views'] ?? []) as Object[];
        for (const v of rawViews) {
          views.push(this.reviveView(v as Record<string, Object>));
        }
      }
    } catch (e) {
      this.logger.warn(TAG, '会话缓存解析失败，忽略缓存', e as Error);
      views = [];
      cachedCount = 0;
    }
    let newEvents: Array<Record<string, Object>> = [];
    let total = cachedCount;
    let timelineOk = false;
    try {
      const res = await this.api.sessions.timeline(sid, cachedCount);
      if (res.code === 0 && res.data) {
        newEvents = res.data.events ?? [];
        total = Number(res.data.total ?? cachedCount);
        timelineOk = true;
      }
    } catch (e) {
      this.logger.warn(TAG, '时间线增量拉取失败', e as Error);
    }
    if (!timelineOk && views.length === 0) {
      // 时间线不可用且无缓存：退回纯文本历史（旧会话兼容）；
      // 文本视图没有事件数可记，不落时间线缓存（防下次增量重算重复）
      const textViews = await this.fetchHistoryTextOnly(sid);
      if (textViews === null) {
        return false;
      }
      return await this.applyHistorySnapshot(sid, loadSeq, generatingAtStart,
        textViews, scrollToLatest, cacheKey, 0, false);
    }
    if (views.length === 0) {
      if (newEvents.length === 0) {
        // 时间线为空（功能上线前的旧会话）：文本历史 + 空缓存
        const textViews = await this.fetchHistoryTextOnly(sid);
        if (textViews === null) {
          return false;
        }
        return await this.applyHistorySnapshot(sid, loadSeq, generatingAtStart,
          textViews, scrollToLatest, cacheKey, 0, true);
      }
      const historyViews = await this.fetchHistoryViews(sid);
      const first = newEvents[0];
      const coversAll = String(first['type'] ?? '') === 'user_message'
        && historyViews.length > 0
        && historyViews[0].role === 'user'
        && historyViews[0].content === String(first['content'] ?? '');
      if (coversAll) {
        // 时间线覆盖全会话：直接重放（含用户消息与全部卡片）
        this.appendEventsToViews(views, newEvents);
      } else {
        // 旧会话中途接入：文本历史打底，时间线卡片按文本匹配回贴尾部
        for (const v of historyViews) {
          views.push(v);
        }
        this.attachTailCards(views, newEvents);
      }
    } else if (newEvents.length > 0) {
      this.appendEventsToViews(views, newEvents);
    }
    return await this.applyHistorySnapshot(sid, loadSeq, generatingAtStart,
      views, scrollToLatest, cacheKey, total, true);
  }

  /**
   * 快照写盘点（D3 steady 化）：先做过期判定，再一次性原子替换。
   * messages 与 LazyForEach 数据源同批落位，setData 只发一次 onDataReloaded——
   * 不逐行闪烁；过期装载（会话已切走/有更新装载/装载期间开了新回合）一律弃写，
   * 已显示的行保持原状（占位气泡等新增量不会被晚到快照覆盖）。
   */
  private async applyHistorySnapshot(sid: string, loadSeq: number, generatingAtStart: boolean,
    views: ChatMessageView[], scrollToLatest: boolean, cacheKey: string,
    timelineCount: number, persist: boolean): Promise<boolean> {
    const stale = this.sessionId !== sid || loadSeq !== this.historyLoadSeq
      || (this.isGenerating && !generatingAtStart);
    if (stale) {
      return false;
    }
    this.messages = views;
    this.messagesDs.setData(views);
    if (scrollToLatest) {
      this.scrollToBottom();
    }
    if (persist) {
      await this.persistHistoryCache(cacheKey, timelineCount, views);
    }
    return true;
  }

  /**
   * 旧路径兜底：仅文本历史（无卡片可重放）。
   * 取数失败返回 null 并保持当前视图（不清空已显示的行）。
   */
  private async fetchHistoryTextOnly(sid: string): Promise<ChatMessageView[] | null> {
    try {
      const res = await this.api.sessions.history(sid);
      if (res.code === 0 && res.data) {
        return this.fetchViewsFromHistory(res.data.messages);
      }
    } catch (e) {
      this.logger.warn(TAG, '拉取会话历史失败', e as Error);
    }
    return null;
  }

  /**
   * 重连后的首屏快照重同步（D3 steady 化）：以服务端时间线为权威快照恢复会话列表。
   * 装载期间旧行保持已显示状态、成功后一次性原子替换（loadHistory/applyHistorySnapshot 保证）；
   * 不强制滚动（scrollToLatest=false），内容一致时视觉零扰动。
   * 未落库的新会话（服务端尚无记录）没有可恢复的快照，直接清账不拉。
   * 快照写入被更新的增量顶掉（返回 false，如装载期间又开了新回合）时保留记账，
   * 待下个回合终态再补——直到快照真正落视图才算恢复完成。
   */
  private async resyncSessionSnapshot(): Promise<void> {
    if (!this.fromList) {
      this.pendingSnapshotResync = false;
      return;
    }
    this.logger.info(TAG, '重连后按服务端时间线重同步会话快照');
    const wrote = await this.loadHistory(false);
    if (wrote) {
      this.pendingSnapshotResync = false;
    }
  }

  private fetchViewsFromHistory(raw: ChatHistoryMessage[]): ChatMessageView[] {
    const views: ChatMessageView[] = [];
    for (let i = 0; i < raw.length; i++) {
      const m = raw[i];
      if (m.content.length === 0) {
        continue;
      }
      views.push(this.newHistoryView(m.role === 'user' ? 'user' : 'assistant', m.content, i));
    }
    return views;
  }

  /** 拉纯文本历史视图（旧会话兼容链路用）；会话 id 由调用方锚定，防中途切会话串数据 */
  private async fetchHistoryViews(sid: string): Promise<ChatMessageView[]> {
    try {
      const res = await this.api.sessions.history(sid);
      if (res.code === 0 && res.data) {
        return this.fetchViewsFromHistory(res.data.messages);
      }
    } catch (e) {
      this.logger.warn(TAG, '拉取会话历史失败', e as Error);
    }
    return [];
  }

  /** 时间线事件 → 视图（就地追加/合并到 views 尾部；chunk 归并到在写助手消息） */
  private appendEventsToViews(views: ChatMessageView[], events: Array<Record<string, Object>>): void {
    for (const ev of events) {
      const type = String(ev['type'] ?? '');
      if (type === 'user_message') {
        views.push(this.newHistoryView('user', String(ev['content'] ?? ''), views.length));
        continue;
      }
      if (type === 'chunk') {
        const text = String(ev['content'] ?? '');
        const last = views[views.length - 1];
        if (last && last.role === 'assistant') {
          last.content = last.content + text;
        } else {
          views.push(this.newHistoryView('assistant', text, views.length));
        }
        continue;
      }
      if (type === 'reasoning') {
        const last = this.ensureAssistant(views);
        last.reasoning = last.reasoning + String(ev['content'] ?? '');
        continue;
      }
      if (type === 'tool_call') {
        const last = this.ensureAssistant(views);
        const call: ToolCallView = {
          name: String(ev['name'] ?? '工具'),
          args: String(ev['arguments'] ?? ''),
          result: '',
        };
        last.toolCalls = [...(last.toolCalls ?? []), call];
        continue;
      }
      if (type === 'tool_result') {
        const last = this.ensureAssistant(views);
        const calls = last.toolCalls ?? [];
        if (calls.length > 0) {
          calls[calls.length - 1].result = String(ev['content'] ?? '');
          last.toolCalls = [...calls];
        }
        continue;
      }
      if (type === 'artifact') {
        const last = this.ensureAssistant(views);
        const d = (ev['data'] ?? {}) as Record<string, Object>;
        const artifactId = String(d['artifact_id'] ?? '');
        if (artifactId === '') {
          continue;
        }
        const view: ArtifactView = {
          artifactId: artifactId,
          name: String(d['name'] ?? ''),
          kind: String(d['kind'] ?? ''),
          size: Number(d['size'] ?? 0),
        };
        last.artifacts = [...(last.artifacts ?? []), view];
        continue;
      }
      if (type === 'plan_update') {
        const last = this.ensureAssistant(views);
        const d = (ev['data'] ?? {}) as Record<string, Object>;
        const rawPlan = (d['plan'] ?? []) as Object[];
        const steps: PlanStepView[] = [];
        for (const item of rawPlan) {
          const step = item as Record<string, Object>;
          steps.push({ step: String(step['step'] ?? ''), status: String(step['status'] ?? '') });
        }
        if (steps.length > 0) {
          last.plan = steps;
        }
        continue;
      }
      if (type === 'approval_required') {
        const last = this.ensureAssistant(views);
        const d = (ev['data'] ?? {}) as Record<string, Object>;
        const toolName = String(d['tool_name'] ?? '');
        const reason = String(d['reason'] ?? '');
        last.approval = `工具「${toolName}」等待审批${reason === '' ? '' : '：' + reason}（请在 PC 端裁决）`;
        continue;
      }
      // done/usage/其他：回合边界或记账事件，不产生视图
    }
  }

  /** 取最后一条助手消息，没有则现开一条（卡片事件总是挂在助手消息上） */
  private ensureAssistant(views: ChatMessageView[]): ChatMessageView {
    const last = views[views.length - 1];
    if (last && last.role === 'assistant') {
      return last;
    }
    const fresh = this.newHistoryView('assistant', '', views.length);
    views.push(fresh);
    return fresh;
  }

  private newHistoryView(role: 'user' | 'assistant', content: string, index: number): ChatMessageView {
    return {
      id: 'h-' + Date.now().toString() + '-' + index.toString(),
      role: role,
      content: content,
      timestamp: 0,
      isStreaming: false,
      reasoning: '',
      toolCalls: [],
      artifacts: [],
      plan: [],
      approval: '',
    };
  }

  /** 缓存 JSON → 视图（字段逐个归一，缺省不崩） */
  private reviveView(o: Record<string, Object>): ChatMessageView {
    const toolCalls: ToolCallView[] = [];
    const rawCalls = (o['toolCalls'] ?? []) as Object[];
    for (const c of rawCalls) {
      const rec = c as Record<string, Object>;
      toolCalls.push({
        name: String(rec['name'] ?? ''),
        args: String(rec['args'] ?? ''),
        result: String(rec['result'] ?? ''),
      });
    }
    const artifacts: ArtifactView[] = [];
    const rawArtifacts = (o['artifacts'] ?? []) as Object[];
    for (const a of rawArtifacts) {
      const rec = a as Record<string, Object>;
      artifacts.push({
        artifactId: String(rec['artifactId'] ?? ''),
        name: String(rec['name'] ?? ''),
        kind: String(rec['kind'] ?? ''),
        size: Number(rec['size'] ?? 0),
      });
    }
    const plan: PlanStepView[] = [];
    const rawPlan = (o['plan'] ?? []) as Object[];
    for (const p of rawPlan) {
      const rec = p as Record<string, Object>;
      plan.push({ step: String(rec['step'] ?? ''), status: String(rec['status'] ?? '') });
    }
    return {
      id: String(o['id'] ?? ''),
      role: o['role'] === 'user' ? 'user' : 'assistant',
      content: String(o['content'] ?? ''),
      timestamp: Number(o['timestamp'] ?? 0),
      isStreaming: false,
      reasoning: String(o['reasoning'] ?? ''),
      toolCalls: toolCalls,
      artifacts: artifacts,
      plan: plan,
      approval: String(o['approval'] ?? ''),
    };
  }

  /** 旧会话中途接入：时间线卡片按「助手文本完全一致」回贴到文本历史尾部 */
  private attachTailCards(views: ChatMessageView[], events: Array<Record<string, Object>>): void {
    const rebuilt: ChatMessageView[] = [];
    this.appendEventsToViews(rebuilt, events);
    for (let i = rebuilt.length - 1; i >= 0; i--) {
      const src = rebuilt[i];
      if (src.role !== 'assistant') {
        continue;
      }
      const hasCards = src.reasoning.length > 0 || (src.toolCalls?.length ?? 0) > 0
        || (src.artifacts?.length ?? 0) > 0 || (src.plan?.length ?? 0) > 0 || src.approval.length > 0;
      if (!hasCards) {
        continue;
      }
      for (let j = views.length - 1; j >= 0; j--) {
        const dst = views[j];
        if (dst.role === 'assistant' && dst.content === src.content) {
          dst.reasoning = src.reasoning;
          dst.toolCalls = src.toolCalls;
          dst.artifacts = src.artifacts;
          dst.plan = src.plan;
          dst.approval = src.approval;
          break;
        }
      }
    }
  }

  private async persistHistoryCache(key: string, eventCount: number, views: ChatMessageView[]): Promise<void> {
    try {
      const trimmed = views.length > 400 ? views.slice(views.length - 400) : views;
      const payload = JSON.stringify({ eventCount: eventCount, views: trimmed });
      if (payload.length > 2000000) {
        return; // 超限弃缓存：下次全量重建，不挡主链路
      }
      await StorageAdapter.getInstance().set(key, payload);
    } catch (e) {
      this.logger.warn(TAG, '会话缓存写入失败（忽略）', e as Error);
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
      this.msg.warning('还没有可连的终端：请先扫码配对');
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
      // 回合终态（直播或重放到达皆同）：在途指令已收敛，清除断线重发记账
      this.inFlightCommandId = '';
      this.inFlightPayload = '';
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
      // 蜂群协作图增量（车道F）：回合终结时子任务 run 可能已出生/到终态，触发面板重拉
      this.swarmRefreshTick++;
      // 清理 batcher 以备下次会话
      this.batcher.reset();
      // 会话摘要已变（新会话落库/最新消息预览）——广播列表页刷新（会话与 PC 同源可见）
      this.bus.emit('chat:sessions-changed', '');
      // D3 steady 化：重连期间在途的回合已收敛——若重连时因正在生成而推迟了
      // 快照重同步，此刻服务端时间线已含本回合全部事件，补做恢复
      if (this.pendingSnapshotResync) {
        this.resyncSessionSnapshot();
      }
    };
    this.bus.on('chat:done', this.doneHandler);

    this.errorHandler = (data: Object) => {
      // 回合终态：在途指令已收敛（失败也是终态），清除断线重发记账
      this.inFlightCommandId = '';
      this.inFlightPayload = '';
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
      // D3 steady 化：失败也是回合终态——时间线里已提交的事件照常补快照恢复
      if (this.pendingSnapshotResync) {
        this.resyncSessionSnapshot();
      }
    };
    this.bus.on('chat:error', this.errorHandler);

    // 重连补发（远程驾驶可靠性）：断线期间发出的指令若尚未收敛，重连成功后
    // 以同一 command_id 重发——服务端要么回放原终态（replayed=true）、要么
    // 报 running（其结果帧随后经重放/直播到达）、要么首次真正执行（发送本身
    // 在断线中丢失的情形）。三种走向都收敛到同一个回合，不会二次执行。
    this.connectedHandler = () => {
      // D3 steady 化：首连的历史恢复已由进页链路（aboutToAppear → loadHistory）
      // 负责，这里只在**重连**时做首屏快照重同步——含 sync_snapshot_required
      // 弃游标重连：服务端拒绝按旧游标补拉，断线窗口内丢的帧只能以服务端
      // 时间线快照整体恢复（chat:done 帧不带全文，重放也补不回丢掉的 chunk）。
      const firstConnect = !this.hasConnectedOnce;
      this.hasConnectedOnce = true;
      if (this.inFlightCommandId !== '' && this.inFlightPayload !== '') {
        this.logger.info(TAG, `重连后重发在途指令 ${this.inFlightCommandId}`);
        this.ws.send(this.inFlightPayload).catch((e: Error) => {
          this.logger.warn(TAG, '在途指令重发失败', e);
        });
      }
      if (firstConnect) {
        return;
      }
      if (this.isGenerating) {
        // 在途回合不打断：流式占位气泡是最新增量，服务端时间线还没有在途事件，
        // 此刻快照晚到不得覆盖——记账待回合终态后再恢复
        this.pendingSnapshotResync = true;
        return;
      }
      this.resyncSessionSnapshot();
    };
    this.bus.on('ws:connected', this.connectedHandler);

    // 排队事件（后端 chat:queued）：展示排队卡（设计 F5 .queued）
    this.queuedHandler = () => {
      this.queued = true;
    };
    this.bus.on('chat:queued', this.queuedHandler);

    // 思考流（后端 chat:reasoning）：累积到当前 streaming assistant 消息
    this.reasoningHandler = (data: Object) => {
      const ev = data as WSChatReasoning;
      this.adoptServerSession(ev.session_id);
      const last = this.messages[this.messages.length - 1];
      if (last && last.role === 'assistant' && last.isStreaming) {
        last.reasoning += (ev.content ?? '');
        this.messages = [...this.messages];
        this.messagesDs.setData(this.messages);
        this.scrollToBottom();
      }
    };
    this.bus.on('chat:reasoning', this.reasoningHandler);

    // 工具调用事件：追加工具卡
    this.toolCallHandler = (data: Object) => {
      const ev = data as WSChatToolCall;
      this.adoptServerSession(ev.session_id);
      const d = ev.data ?? {};
      const last = this.messages[this.messages.length - 1];
      if (last && last.role === 'assistant' && last.isStreaming) {
        const name = String(d['name'] ?? d['tool_name'] ?? '工具');
        const rawArgs = d['arguments'] ?? d['input'] ?? '';
        const args = typeof rawArgs === 'string' ? rawArgs : JSON.stringify(rawArgs);
        const call: ToolCallView = { name: name, args: args, result: '' };
        last.toolCalls = [...(last.toolCalls ?? []), call];
        this.messages = [...this.messages];
        this.messagesDs.setData(this.messages);
        this.scrollToBottom();
      }
    };
    this.bus.on('chat:tool_call', this.toolCallHandler);

    // 工具结果事件：回填到最后一张工具卡
    this.toolResultHandler = (data: Object) => {
      const ev = data as WSChatToolResult;
      const d = ev.data ?? {};
      const last = this.messages[this.messages.length - 1];
      if (last && last.role === 'assistant' && (last.toolCalls?.length ?? 0) > 0) {
        const raw = d['result'] ?? d['content'] ?? d;
        const text = typeof raw === 'string' ? raw : JSON.stringify(raw);
        const calls = last.toolCalls ?? [];
        calls[calls.length - 1].result = text;
        last.toolCalls = [...calls];
        this.messages = [...this.messages];
        this.messagesDs.setData(this.messages);
      }
    };
    this.bus.on('chat:tool_result', this.toolResultHandler);

    // ── 对齐 PC 对话页：产出物/计划/用量/审批/模型列表/上下文/产物内容 ──
    this.artifactHandler = (data: Object) => {
      const rec = (data as WSChatArtifact).data;
      const artifactId = typeof rec['artifact_id'] === 'string' ? rec['artifact_id'] as string : '';
      if (artifactId === '') {
        return;
      }
      const view: ArtifactView = {
        artifactId: artifactId,
        name: typeof rec['name'] === 'string' ? rec['name'] as string : '',
        kind: typeof rec['kind'] === 'string' ? rec['kind'] as string : '',
        size: typeof rec['size'] === 'number' ? rec['size'] as number : 0,
      };
      const last = this.messages[this.messages.length - 1];
      if (last && last.role === 'assistant') {
        last.artifacts = [...(last.artifacts ?? []), view];
        this.messages = [...this.messages];
        this.messagesDs.setData(this.messages);
      }
    };
    this.bus.on('chat:artifact', this.artifactHandler);

    this.planHandler = (data: Object) => {
      const rec = (data as WSChatPlanUpdate).data;
      const rawPlan = (rec['plan'] as Record<string, Object>[] | null) ?? [];
      const steps: PlanStepView[] = [];
      for (const item of rawPlan) {
        const step = item as Record<string, Object>;
        steps.push({
          step: typeof step['step'] === 'string' ? step['step'] as string : '',
          status: typeof step['status'] === 'string' ? step['status'] as string : '',
        });
      }
      const last = this.messages[this.messages.length - 1];
      if (last && last.role === 'assistant' && steps.length > 0) {
        last.plan = steps;
        this.messages = [...this.messages];
        this.messagesDs.setData(this.messages);
      }
    };
    this.bus.on('chat:plan_update', this.planHandler);

    this.usageHandler = (data: Object) => {
      const rec = (data as WSChatUsage).data;
      const total = typeof rec['total_tokens'] === 'number' ? rec['total_tokens'] as number : 0;
      this.usageTotal = this.usageTotal + total;
    };
    this.bus.on('chat:usage', this.usageHandler);

    this.approvalHandler = (data: Object) => {
      const rec = (data as WSChatApprovalRequired).data;
      const toolName = typeof rec['tool_name'] === 'string' ? rec['tool_name'] as string : '';
      const reason = typeof rec['reason'] === 'string' ? rec['reason'] as string : '';
      // Dreaming 判定面（项 7）：历史反馈的建议性提示随审批卡展示（只读转正规则）
      const hint = typeof rec['dreaming_hint'] === 'string' ? rec['dreaming_hint'] as string : '';
      const last = this.messages[this.messages.length - 1];
      if (last && last.role === 'assistant') {
        last.approval = `工具「${toolName}」等待审批${reason === '' ? '' : '：' + reason}（请在 PC 端裁决）`
          + (hint === '' ? '' : `\n${hint}`);
        this.messages = [...this.messages];
        this.messagesDs.setData(this.messages);
      }
    };
    this.bus.on('chat:approval_required', this.approvalHandler);

    this.modelListHandler = (data: Object) => {
      const res = data as WSModelListResult;
      this.modelOptions = res.models ?? [];
      this.modelOptionsLoaded = true;
      // 兜底刷新：菜单开着时数据才到，直接替换分组数组驱动弹层重渲染
      if (this.pillMenuOpen === 'model') {
        this.pillGroups = this.modelGroups();
      }
    };
    this.bus.on('model:list_result', this.modelListHandler);

    this.compositionHandler = (data: Object) => {
      const res = data as WSContextCompositionResult;
      this.composition = res.data ?? null;
      this.compositionReason = res.reason ?? '';
      // 派生展示读数（@Builder 直读 State，不在 builder 里解析 Record）
      this.compTotal = 0;
      this.compWindow = 0;
      this.compMsgTokens = 0;
      this.compToolTokens = 0;
      this.compCacheRate = -1;
      if (this.composition !== null) {
        this.compTotal = typeof this.composition['total_tokens'] === 'number'
          ? this.composition['total_tokens'] as number : 0;
        this.compWindow = typeof this.composition['context_window'] === 'number'
          ? this.composition['context_window'] as number : 0;
        const messages = this.composition['messages'] as Record<string, Object>;
        if (messages) {
          this.compMsgTokens = typeof messages['total_tokens'] === 'number'
            ? messages['total_tokens'] as number : 0;
        }
        const tools = this.composition['tools'] as Record<string, Object>;
        if (tools) {
          for (const key of ['system', 'mcp', 'skill']) {
            const bucket = tools[key] as Record<string, Object>;
            if (bucket && typeof bucket['tokens'] === 'number') {
              this.compToolTokens = this.compToolTokens + (bucket['tokens'] as number);
            }
          }
        }
        const rate = this.composition['cache_hit_rate'];
        this.compCacheRate = typeof rate === 'number' ? rate as number : -1;
      }
    };
    this.bus.on('context:composition_result', this.compositionHandler);

    this.artifactContentHandler = (data: Object) => {
      const res = data as WSArtifactContentResult;
      this.previewContent = res.content ?? '';
      this.previewEncoding = res.encoding ?? '';
      this.previewMime = res.mime_type ?? '';
      this.previewLoading = false;
    };
    this.bus.on('artifact:content_result', this.artifactContentHandler);
  }

  /**
   * 语音输入：点击麦克风开始/停止。
   * 实现：CoreSpeechKit 端侧识别引擎（zh-CN）+ AudioCapturer 采集 16k/mono/16bit
   * PCM，按 20ms 帧喂给引擎；最终识别结果直接作为消息发送。
   */
  private async toggleVoice(): Promise<void> {
    if (this.voiceListening) {
      this.stopVoice();
      return;
    }
    try {
      const atManager = abilityAccessCtrl.createAtManager();
      const grant = await atManager.requestPermissionsFromUser(getContext(this) as Context,
        ['ohos.permission.MICROPHONE'] as Array<Permissions>);
      let granted = false;
      for (const r of grant.authResults) {
        if (r === 0) {
          granted = true;
        }
      }
      if (!granted) {
        this.msg.warning('需要麦克风权限才能语音输入');
        return;
      }
      // 识别通道（B4-1）：asr_channel = auto|device|backend（设置页可选，默认 auto）
      const channel = this.config.get<string>('asr_channel', 'auto');
      if (channel === 'backend') {
        // 仅后端：跳过端侧引擎，直接走流式识别
        const backendOnlyOk = await this.startBackendVoice();
        if (!backendOnlyOk) {
          this.msg.error('后端语音识别通道未就绪');
        }
        return;
      }
      let engine: speechRecognizer.SpeechRecognitionEngine | null = null;
      try {
        engine = await speechRecognizer.createEngine({ language: 'zh-CN', online: 1 });
      } catch (engineErr) {
        // 端侧识别引擎不可用（部分设备/模拟器未部署 CoreSpeechKit 引擎）
        engine = null;
      }
      if (engine === null) {
        if (channel === 'device') {
          this.msg.error('设备端语音识别引擎不可用');
          return;
        }
        // auto：回落后端流式 ASR 通道（B4-1）：PCM 直送 /api/v1/audio/asr/stream
        const backendOk = await this.startBackendVoice();
        if (!backendOk) {
          this.msg.error('语音识别不可用：设备端引擎与后端通道均未就绪');
        }
        return;
      }
      this.voiceEngine = engine;
      this.voiceSessionId = 'voice-' + Date.now().toString();
      engine.setListener({
        onStart: (sessionId: string, eventMessage: string) => {
          this.voiceListening = true;
        },
        onEvent: (sessionId: string, eventCode: number, eventMessage: string) => {
        },
        onComplete: (sessionId: string, eventMessage: string) => {
          // 识别完成（一句话结束）：引擎会继续等下一句，无需处理
        },
        onResult: (sessionId: string, result: speechRecognizer.SpeechRecognitionResult) => {
          const text = result.result ?? '';
          if (text.trim().length > 0 && result.isFinal) {
            this.inputText = text.trim();
            this.stopVoice();
            this.sendMessage();
          }
        },
        onError: (sessionId: string, errorCode: number, errorMessage: string) => {
          this.logger.warn(TAG, `语音识别错误 ${errorCode}: ${errorMessage}`);
          this.stopVoice();
          this.msg.error('语音识别失败');
        }
      });
      engine.startListening({
        sessionId: this.voiceSessionId,
        audioInfo: { audioType: 'pcm', sampleRate: 16000, soundChannel: 1, sampleBit: 16 },
      });
      this.voiceListening = true;
      await this.startCapture(this.voiceSessionId);
    } catch (e) {
      this.stopVoice();
      this.msg.error('语音启动失败：' + (e as Error).message);
    }
  }

  /** AudioCapturer 采集 PCM 并按 640 字节帧喂给识别引擎 */
  private async startCapture(sessionId: string): Promise<void> {
    const streamInfo: audio.AudioStreamInfo = {
      samplingRate: 16000,
      channels: audio.AudioChannel.CHANNEL_1,
      sampleFormat: audio.AudioSampleFormat.SAMPLE_FORMAT_S16LE,
      encodingType: audio.AudioEncodingType.ENCODING_TYPE_RAW,
    };
    const capturerInfo: audio.AudioCapturerInfo = {
      source: audio.SourceType.SOURCE_TYPE_MIC,
      capturerFlags: 0,
    };
    const options: audio.AudioCapturerOptions = {
      streamInfo: streamInfo,
      capturerInfo: capturerInfo,
    };
    const capturer = await audio.createAudioCapturer(options);
    this.voiceCapturer = capturer;
    capturer.on('readData', (buffer: ArrayBuffer) => {
      if (buffer.byteLength <= 0) {
        return;
      }
      const bytes = new Uint8Array(buffer);
      // 引擎要求 640/1280 字节帧；按 640 切分喂入
      for (let off = 0; off + 640 <= bytes.length; off += 640) {
        this.voiceEngine?.writeAudio(sessionId, bytes.slice(off, off + 640));
      }
    });
      await capturer.start();
  }

  /**
   * 后端流式 ASR 通道（B4-1 移动端适配）：端侧 CoreSpeechKit 不可用时的回落。
   * AudioCapturer 采 16k/mono/16bit PCM 以二进制帧直送
   * /api/v1/audio/asr/stream；partial 实时上屏，final 成句即作为消息发送。
   * 返回 false 表示通道不可用（未登录/未配对/连接失败），调用方提示用户。
   */
  private async startBackendVoice(): Promise<boolean> {
    const httpClient = HttpClient.getInstance();
    const base = httpClient.getBaseUrl();
    const token = httpClient.getAuthToken();
    if (!base || !token) {
      this.msg.warning('请先登录并配对终端，再使用语音识别');
      return false;
    }
    const url = base.replace('http', 'ws') + '/audio/asr/stream';
    const client = new AsrStreamClient();
    try {
      await client.connect(url, token, {
        onReady: (engine: string) => {
          this.voiceListening = true;
          this.logger.info(TAG, '后端流式 ASR 就绪: ' + engine);
        },
        onPartial: (text: string, turnId: number) => {
          // 服务端 partial 为当轮累计文本：覆盖式实时上屏
          const trimmed = text.trim();
          if (trimmed.length > 0) {
            this.inputText = trimmed;
          }
        },
        onFinal: (text: string, turnId: number, reason: string) => {
          const trimmed = text.trim();
          if (trimmed.length > 0 && this.backendVoiceActive) {
            this.inputText = trimmed;
            this.stopVoice();
            this.sendMessage();
          }
        },
        onError: (code: string, message: string) => {
          this.logger.warn(TAG, `后端流式 ASR 错误 ${code}: ${message}`);
        },
        onClosed: () => {
        },
      });
    } catch (e) {
      this.logger.warn(TAG, '后端流式 ASR 连接失败', e as Error);
      this.asrStream = null;
      return false;
    }
    this.asrStream = client;
    this.backendVoiceActive = true;
    const streamInfo: audio.AudioStreamInfo = {
      samplingRate: 16000,
      channels: audio.AudioChannel.CHANNEL_1,
      sampleFormat: audio.AudioSampleFormat.SAMPLE_FORMAT_S16LE,
      encodingType: audio.AudioEncodingType.ENCODING_TYPE_RAW,
    };
    const capturerInfo: audio.AudioCapturerInfo = {
      source: audio.SourceType.SOURCE_TYPE_MIC,
      capturerFlags: 0,
    };
    const options: audio.AudioCapturerOptions = {
      streamInfo: streamInfo,
      capturerInfo: capturerInfo,
    };
    const capturer = await audio.createAudioCapturer(options);
    this.voiceCapturer = capturer;
    capturer.on('readData', (buffer: ArrayBuffer) => {
      if (buffer.byteLength <= 0) {
        return;
      }
      // 整帧直发：服务端自切 10ms 子帧，无需按 640 字节预切
      this.asrStream?.sendPcm(buffer);
    });
    await capturer.start();
    return true;
  }

  /** 停止语音：采集器与识别引擎一并收尾 */
  private stopVoice(): void {
    this.voiceListening = false;
    this.backendVoiceActive = false;
    if (this.asrStream) {
      const client = this.asrStream;
      this.asrStream = null;
      // 先终结当前轮再关闭（final 已送达时 stop 帧无副作用）
      client.stop();
      client.dispose();
    }
    try {
      this.voiceCapturer?.stop();
      this.voiceCapturer?.release();
    } catch (e) {
      // 采集器释放失败不影响主流程
    }
    this.voiceCapturer = null;
    try {
      if (this.voiceEngine !== null && this.voiceSessionId !== '') {
        this.voiceEngine.cancel(this.voiceSessionId);
        this.voiceEngine.shutdown();
      }
    } catch (e) {
      // 引擎可能已随会话结束
    }
    this.voiceEngine = null;
    this.voiceSessionId = '';
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
      reasoning: '',
      toolCalls: [],
      artifacts: [],
      plan: [],
      approval: '',
    };
    // assistant 占位消息（等待流式填充）
    const assistantMsg: ChatMessageView = {
      id: 'a-' + Date.now(),
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      isStreaming: true,
      reasoning: '',
      toolCalls: [],
      artifacts: [],
      plan: [],
      approval: '',
    };
    this.messages.push(userMsg, assistantMsg);
    this.messages = [...this.messages];
    // M5.2.2 同步 LazyForEach 数据源
    this.messagesDs.setData(this.messages);
    this.inputText = '';
    this.isGenerating = true;
    this.scrollToBottom();

    // 通过 WS 下发 chat:send（对齐 PC：回合控制四字段随请求下发）。
    // 远程驾驶可靠性：客户端生成 command_id（服务端按 设备+指令 id 记账幂等），
    // 在途记账供断线重连后重发——同 id 不会产生第二次真实执行。
    const commandId = util.generateRandomUUID(true);
    this.inFlightCommandId = commandId;
    this.inFlightPayload = JSON.stringify({
      type: 'chat:send',
      command_id: commandId,
      content: text,
      session_id: this.sessionId,
      agent_id: this.currentAgentId,
      model: this.selectedModel !== '' ? this.selectedModel : undefined,
      thinking_effort: this.thinkingEffort !== '' ? this.thinkingEffort : undefined,
      permission_mode: this.permissionMode !== '' ? this.permissionMode : undefined,
      task_profile: this.taskProfile !== '' ? this.taskProfile : undefined,
    } as WSChatSend);
    try {
      await this.ws.send(this.inFlightPayload);
    } catch (e) {
      // send 抛错＝指令确定未发出（WS 死态），清在途记账（重连后不重发）
      this.inFlightCommandId = '';
      this.inFlightPayload = '';
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
    // 用户已主动放弃本回合：清在途记账（重连后不重发被取消的指令）
    this.inFlightCommandId = '';
    this.inFlightPayload = '';
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
      // 服务端已为该会话铸真记录：视为已落库（可置顶/归档；重连快照重同步也以此为准）
      this.fromList = true;
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

  /** 拉取会话摘要 + 归档列表（归档失败仅记日志，不阻塞主列表）。
   * 抽屉只展示当前 agent 的会话历史（用户拍板：归属哪个 agent 就只看该 agent 的对话） */
  private async loadDrawerSessions(): Promise<void> {
    try {
      const res = await this.api.sessions.listAll('');
      if (res.code === 0 && res.data) {
        this.drawerSessions = res.data.sessions.filter((s: ChatSession) => s.agent_id === this.currentAgentId);
      }
    } catch (e) {
      this.msg.error('会话列表加载失败：' + (e as Error).message);
    }
    try {
      const arch = await this.api.sessions.listArchived('');
      if (arch.code === 0 && arch.data) {
        this.archivedSessions = arch.data.sessions.filter((s: ChatSession) => s.agent_id === this.currentAgentId);
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

  /** 抽屉内点击会话：切换当前会话并拉取历史（当前 agent 跟随会话归属，抽屉过滤口径一致） */
  private switchToSession(s: ChatSession): void {
    if (s.id === this.sessionId) {
      this.drawerOpen = false;
      return;
    }
    this.sessionId = s.id;
    this.sessionTitle = s.title;
    if (s.agent_id !== '') {
      this.currentAgentId = s.agent_id;
    }
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

        // 蜂群协作过程视图（车道F，对齐 PC ChatPage 消息区底部的 SwarmFlowPanel 位）：
        // 本会话子任务 run 的委派/依赖分层拓扑 + 审批/候选徽标卡；无协作运行显示诚实
        // 空态；读面失败 fail-soft（错误态 + 重试），不崩聊天页。
        SwarmFlowPanel({ sessionId: this.sessionId, refreshTick: this.swarmRefreshTick })

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

        // 对齐 PC Composer 工具条：模型/思考深度/权限模式/执行档位/上下文面板入口
        // 底部工具条仅用图标标识（用户拍板）：当前取值在菜单选中态里体现，不在此重复文字
        Scroll() {
          Row() {
            Row() {
              AppIcon({ name: 'model', iconSize: 16, color: this.sm.getColor('text_secondary') })
            }
            .padding({ left: 10, right: 10, top: 8, bottom: 8 })
            .borderRadius(999)
            .backgroundColor('rgba(0,0,0,0.25)')
            .border({ width: 1, color: this.sm.getColor('border') })
            .margin({ right: 8 })
            .onClick(() => { this.requestModelList(); this.openPillMenu('model'); })

            Row() {
              AppIcon({ name: 'spark', iconSize: 16, color: this.sm.getColor('text_secondary') })
            }
            .padding({ left: 10, right: 10, top: 8, bottom: 8 })
            .borderRadius(999)
            .backgroundColor('rgba(0,0,0,0.25)')
            .border({ width: 1, color: this.sm.getColor('border') })
            .margin({ right: 8 })
            .onClick(() => { this.openPillMenu('effort'); })

            Row() {
              AppIcon({ name: 'shield', iconSize: 16, color: this.sm.getColor('text_secondary') })
            }
            .padding({ left: 10, right: 10, top: 8, bottom: 8 })
            .borderRadius(999)
            .backgroundColor('rgba(0,0,0,0.25)')
            .border({ width: 1, color: this.sm.getColor('border') })
            .margin({ right: 8 })
            .onClick(() => { this.openPillMenu('mode'); })

            Row() {
              AppIcon({ name: 'gear', iconSize: 16, color: this.sm.getColor('text_secondary') })
            }
            .padding({ left: 10, right: 10, top: 8, bottom: 8 })
            .borderRadius(999)
            .backgroundColor('rgba(0,0,0,0.25)')
            .border({ width: 1, color: this.sm.getColor('border') })
            .margin({ right: 8 })
            .onClick(() => { this.openPillMenu('profile'); })

            Row() {
              AppIcon({ name: 'archive', iconSize: 16, color: this.sm.getColor('text_secondary') })
            }
            .padding({ left: 10, right: 10, top: 8, bottom: 8 })
            .borderRadius(999)
            .backgroundColor('rgba(0,0,0,0.25)')
            .border({ width: 1, color: this.sm.getColor('border') })
            .onClick(() => { this.contextOpen = true; this.requestComposition(); })
          }
        }
        .scrollable(ScrollDirection.Horizontal)
        .width('100%')
        .padding({ left: 12, right: 12 })
        // Scroll 缺 .scrollable(Horizontal) 横向内容不可滚（真机实证过的坑）

        // 输入区（设计 F5 .inputbar：附件/语音 + 胶囊输入框 + 圆形发送/停止）
        Row() {
          IconBtn({ name: 'clip', onTap: () => { this.msg.info('附件发送即将开放'); } })
          IconBtn({ name: 'mic', onTap: () => { this.toggleVoice(); } })
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

      // 上下文面板：底部滑出（对齐 PC ContextUsageIndicator 明细面板）
      if (this.contextOpen) {
        this.buildContextPanel()
      }

      // 产出物预览弹层（artifact:get WS 代理取回内容）
      if (this.previewArtifact !== null) {
        this.buildArtifactPreview()
      }

      // 胶囊菜单底部弹层（bindMenu 贴底展开出屏，改用自绘弹层）
      if (this.pillMenuOpen !== '') {
        this.buildPillMenu()
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
  // ── Composer 菜单/取数（对齐 PC 对话页五件套）──

  /** 模型候选预取：REST /models 与 PC 同源；失败不置位，开菜单时走 WS 兜底 */
  private fetchModelsRest(): void {
    this.api.providers.listModels()
      .then((models: ModelInfoDto[]) => {
        const out: Array<Record<string, Object>> = [];
        for (const m of models) {
          const rec: Record<string, Object> = {
            'model_id': m.model_id,
            'provider': m.provider,
            'connectable': m.connectable,
          };
          out.push(rec);
        }
        if (out.length === 0) {
          return;
        }
        this.modelOptions = out;
        this.modelOptionsLoaded = true;
        if (this.pillMenuOpen === 'model') {
          this.pillGroups = this.modelGroups();
        }
      })
      .catch((e: Error) => {
        this.logger.warn(TAG, '模型候选 REST 预取失败，开菜单时走 WS 兜底: ' + e.message);
      });
  }

  private requestModelList(): void {
    if (this.modelOptionsLoaded) {
      return;
    }
    try {
      this.ws.send(JSON.stringify({ type: 'model:list' }));
    } catch (e) {
      // WS 未连上时打开菜单无候选，属可重试态：不弹错，下次展开再取
      this.logger.warn(TAG, 'model:list 未发送（连接未就绪）');
    }
  }

  private requestComposition(): void {
    try {
      this.ws.send(JSON.stringify({ type: 'context:composition',
        agent_id: this.currentAgentId, session_id: this.sessionId }));
    } catch (e) {
      this.logger.warn(TAG, 'context:composition 未发送（连接未就绪）');
    }
  }

  private openArtifact(a: ArtifactView): void {
    this.previewArtifact = a;
    this.previewContent = '';
    this.previewEncoding = '';
    this.previewMime = '';
    this.previewLoading = true;
    try {
      this.ws.send(JSON.stringify({ type: 'artifact:get', artifact_id: a.artifactId }));
    } catch (e) {
      this.previewLoading = false;
      this.msg.warning('连接未就绪，无法取回产出物内容');
    }
  }

  /** 模型菜单：仅收录可用（connectable）模型并按服务商分组（用户拍板） */
  private modelGroups(): PillMenuGroup[] {
    const groups: PillMenuGroup[] = [];
    groups.push({ header: '', items: [{ value: '自动', action: () => { this.selectedModel = ''; } }] });
    const byProvider = new Map<string, MenuElement[]>();
    for (const m of this.modelOptions) {
      const modelId = typeof m['model_id'] === 'string' ? m['model_id'] as string : '';
      if (modelId === '' || m['connectable'] !== true) {
        continue;
      }
      const provider = typeof m['provider'] === 'string' && (m['provider'] as string) !== ''
        ? m['provider'] as string : '其他';
      const bucket = byProvider.get(provider) ?? [];
      if (bucket.length === 0) {
        byProvider.set(provider, bucket);
      }
      bucket.push({ value: modelId, action: () => { this.selectedModel = modelId; } });
    }
    byProvider.forEach((items: MenuElement[], provider: string) => {
      groups.push({ header: provider, items: items });
    });
    return groups;
  }

  private effortMenu(): MenuElement[] {
    return [
      { value: '轻量', action: () => { this.thinkingEffort = 'light'; } },
      { value: '标准', action: () => { this.thinkingEffort = 'standard'; } },
      { value: '深度', action: () => { this.thinkingEffort = 'deep'; } },
    ];
  }

  private modeMenu(): MenuElement[] {
    return [
      { value: '默认', action: () => { this.permissionMode = ''; } },
      { value: '计划', action: () => { this.permissionMode = 'plan'; } },
      { value: '编辑', action: () => { this.permissionMode = 'edit'; } },
      { value: '放行', action: () => { this.permissionMode = 'yolo'; } },
      { value: '审慎', action: () => { this.permissionMode = 'guarded'; } },
      { value: '自动', action: () => { this.permissionMode = 'auto'; } },
    ];
  }

  private profileMenu(): MenuElement[] {
    return [
      { value: '自动', action: () => { this.taskProfile = ''; } },
      { value: '轻档', action: () => { this.taskProfile = 'lite'; } },
      { value: '标准', action: () => { this.taskProfile = 'standard'; } },
      { value: '重载', action: () => { this.taskProfile = 'heavy'; } },
    ];
  }

  private kindIcon(kind: string): string {
    if (kind === 'image') { return 'eye'; }
    if (kind === 'html') { return 'globe'; }
    return 'book';
  }

  private formatSize(bytes: number): string {
    if (bytes <= 0) { return ''; }
    if (bytes < 1024) { return bytes.toString() + ' B'; }
    if (bytes < 1024 * 1024) { return (bytes / 1024).toFixed(1) + ' KB'; }
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  }

  /** 上下文面板：底部滑出（用量环读数 + 组成明细，PC ContextUsageIndicator 同源数据） */
  @Builder
  buildContextPanel() {
    Row() {
      Column()
        .layoutWeight(1)
        .height('100%')
        .backgroundColor('rgba(4,6,14,0.60)')
        .onClick(() => { this.contextOpen = false; })
      Column() {
        Row() {
          Text('上下文')
            .fontSize(16)
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
          Blank()
          Text('✕')
            .fontSize(16)
            .fontColor(this.sm.getColor('text_secondary'))
            .onClick(() => { this.contextOpen = false; })
        }
        .width('100%')
        .padding({ bottom: 8 })

        Text('本会话累计用量 ' + this.usageTotal.toString() + ' tokens')
          .fontSize(13)
          .fontColor(this.sm.getColor('text_secondary'))
          .width('100%')
          .padding({ bottom: 10 })

        if (this.composition !== null) {
          Text('最近一轮上下文组成（实测）')
            .fontSize(12)
            .fontColor(this.sm.getColor('text_tertiary'))
            .width('100%')
            .padding({ bottom: 6 })
          Row() {
            Text('消息').fontSize(13).fontColor(this.sm.getColor('text_primary'))
            Blank()
            Text(this.compMsgTokens.toString() + ' tokens')
              .fontSize(13).fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          Progress({ value: this.compMsgTokens, total: Math.max(this.compTotal, 1) })
            .color(this.sm.getColor('primary'))
            .width('100%')
            .margin({ bottom: 8 })
          Row() {
            Text('工具（系统+MCP+技能）').fontSize(13).fontColor(this.sm.getColor('text_primary'))
            Blank()
            Text(this.compToolTokens.toString() + ' tokens')
              .fontSize(13).fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          Progress({ value: this.compToolTokens, total: Math.max(this.compTotal, 1) })
            .color(this.sm.getColor('primary'))
            .width('100%')
            .margin({ bottom: 8 })
          Row() {
            Text('缓存命中率').fontSize(13).fontColor(this.sm.getColor('text_primary'))
            Blank()
            Text(this.compCacheRate >= 0 ? (this.compCacheRate * 100).toFixed(0) + '%' : '—')
              .fontSize(13).fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .margin({ bottom: 8 })
          Row() {
            Text('上下文窗口').fontSize(13).fontColor(this.sm.getColor('text_primary'))
            Blank()
            Text(this.compWindow > 0
              ? this.compTotal.toString() + ' / ' + this.compWindow.toString()
                  + '（' + (this.compTotal / Math.max(this.compWindow, 1) * 100).toFixed(1) + '%）'
              : this.compTotal.toString() + ' tokens（窗口未知）')
              .fontSize(13)
              .fontColor(this.compWindow > 0 && this.compTotal > this.compWindow * 0.9
                ? this.sm.getColor('error') : this.sm.getColor('text_secondary'))
          }
          .width('100%')
        } else if (this.compositionReason === 'no_data') {
          Text('暂无实测快照——该会话先发送一条消息后再查看')
            .fontSize(13)
            .fontColor(this.sm.getColor('text_tertiary'))
            .width('100%')
        } else {
          Text(this.compositionReason === 'query_failed' ? '查询失败，请稍后重试' : '取数中…')
            .fontSize(13)
            .fontColor(this.sm.getColor('text_tertiary'))
            .width('100%')
        }
      }
      .width('86%')
      .height('46%')
      .padding(16)
      .borderRadius(16)
      .backgroundColor(this.sm.getColor('surface'))
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .height('100%')
  }

  /** 产出物预览弹层：取回内容按类型渲染（md/text 走 MarkdownText，图片走 base64） */
  @Builder
  buildArtifactPreview() {
    Row() {
      Column()
        .layoutWeight(1)
        .height('100%')
        .backgroundColor('rgba(4,6,14,0.60)')
        .onClick(() => { this.previewArtifact = null; })
      Column() {
        Row() {
          Text(this.previewArtifact === null ? '' : this.previewArtifact.name)
            .fontSize(15)
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)
          Text('✕')
            .fontSize(16)
            .fontColor(this.sm.getColor('text_secondary'))
            .onClick(() => { this.previewArtifact = null; })
        }
        .width('100%')
        .padding({ bottom: 6 })

        Text((this.previewArtifact === null ? '' : this.previewArtifact.kind)
          + (this.previewArtifact !== null && this.previewArtifact.size > 0
            ? ' · ' + this.formatSize(this.previewArtifact.size) : ''))
          .fontSize(12)
          .fontColor(this.sm.getColor('text_tertiary'))
          .width('100%')
          .padding({ bottom: 8 })

        if (this.previewLoading) {
          Text('取回中…')
            .fontSize(13)
            .fontColor(this.sm.getColor('text_tertiary'))
            .width('100%')
        } else if (this.previewEncoding === 'utf8') {
          Scroll() {
            Column() {
              MarkdownText({ content: this.previewContent })
            }
            .width('100%')
            .alignItems(HorizontalAlign.Start)
          }
          .scrollable(ScrollDirection.Vertical)
          .align(Alignment.Top)
          .layoutWeight(1)
          .width('100%')
        } else if (this.previewEncoding === 'base64' && this.previewMime.startsWith('image/')) {
          Image('data:' + this.previewMime + ';base64,' + this.previewContent)
            .objectFit(ImageFit.Contain)
            .layoutWeight(1)
            .width('100%')
        } else {
          Text('该类型暂不支持移动端预览，请在 PC 端查看')
            .fontSize(13)
            .fontColor(this.sm.getColor('text_tertiary'))
            .width('100%')
        }
      }
      .width('86%')
      .height('86%')
      .padding(16)
      .borderRadius(16)
      .backgroundColor(this.sm.getColor('surface'))
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .height('100%')
  }

  /** 胶囊菜单弹层：行项目随 pillMenuOpen 切换（模型/思考/权限/档位）。
   *  无左侧遮罩暗影（用户拍板）：左边只放透明点击区负责「点外部关闭」，
   *  卡片右上角提供 ✕ 关闭。 */
  @Builder
  buildPillMenu() {
    Row() {
      Column()
        .layoutWeight(1)
        .height('100%')
        .onClick(() => { this.pillMenuOpen = ''; })
      Column() {
        Row() {
          Text(this.pillMenuOpen === 'model' ? '选择模型' : this.pillMenuOpen === 'effort' ? '思考深度'
            : this.pillMenuOpen === 'mode' ? '权限模式' : '执行档位')
            .fontSize(15)
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
          Blank()
          Text('✕')
            .fontSize(16)
            .fontColor(this.sm.getColor('text_secondary'))
            .padding({ left: 8, right: 4, top: 4, bottom: 4 })
            .onClick(() => { this.pillMenuOpen = ''; })
        }
        .width('100%')
        .padding({ bottom: 8 })
        Scroll() {
          Column() {
            ForEach(this.pillGroups, (g: PillMenuGroup) => {
              Column() {
                if (g.header !== '') {
                  Text(g.header)
                    .fontSize(12)
                    .fontColor(this.sm.getColor('text_secondary'))
                    .width('100%')
                    .padding({ top: 10, bottom: 4, left: 8 })
                }
                ForEach(g.items, (item: MenuElement) => {
                  Text(item.value)
                    .fontSize(14)
                    .fontColor(this.sm.getColor('text_primary'))
                    .width('100%')
                    .padding({ top: 12, bottom: 12, left: 8, right: 8 })
                    .borderRadius(8)
                    .onClick(() => {
                      item.action();
                      this.pillMenuOpen = '';
                    })
                }, (item: MenuElement) => item.value as string)
              }
              .width('100%')
              .alignItems(HorizontalAlign.Start)
            }, (g: PillMenuGroup) => g.header)
          }
          .width('100%')
          .alignItems(HorizontalAlign.Start)
        }
        .scrollable(ScrollDirection.Vertical)
        .layoutWeight(1)
        .width('100%')
      }
      .width('78%')
      .height('52%')
      .padding(16)
      .borderRadius(16)
      .backgroundColor(this.sm.getColor('surface'))
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .height('100%')
  }

  /** 开胶囊菜单：先快照分组数据再置开态，保证弹层首帧即带全量选项 */
  private openPillMenu(menuType: string): void {
    this.pillMenuOpen = menuType;
    this.pillGroups = this.pillMenuGroupsFor(menuType);
  }

  private pillMenuGroupsFor(menuType: string): PillMenuGroup[] {
    if (menuType === 'model') { return this.modelGroups(); }
    if (menuType === 'effort') { return [{ header: '', items: this.effortMenu() }]; }
    if (menuType === 'mode') { return [{ header: '', items: this.modeMenu() }]; }
    if (menuType === 'profile') { return [{ header: '', items: this.profileMenu() }]; }
    return [];
  }

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
          // 气泡左上方：当前 agent 圆形头像 + 名称（用户指定圆形头像；
          // 行宽撑满气泡——Column 默认居中会把这行挤到正中，须显式左对齐）
          Row() {
            Text(this.getAgentName().slice(0, 1))
              .fontSize(11)
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_on_primary'))
              .width(22)
              .height(22)
              .borderRadius(11)
              .textAlign(TextAlign.Center)
              .linearGradient({ angle: 135, colors: [[this.sm.getColor('secondary'), 0], [this.sm.getColor('primary'), 1]] })
            Text(this.getAgentName())
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ left: 6 })
          }
          .width('100%')
          .alignItems(VerticalAlign.Center)
          .justifyContent(FlexAlign.Start)
          .margin({ bottom: 4 })

          // 思考流卡片（chat:reasoning 累积；深底与气泡区分）
          if (msg.reasoning !== '') {
            Column() {
              Row() {
                AppIcon({ name: 'spark', iconSize: 12, color: this.sm.getColor('primary') })
                Text('思考中')
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('text_secondary'))
                  .margin({ left: 5 })
              }
              .width('100%')
              Text(msg.reasoning)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .width('100%')
                .maxLines(8)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
                .margin({ top: 4 })
            }
            .width('100%')
            .alignItems(HorizontalAlign.Start)
            .padding(8)
            .borderRadius(8)
            .backgroundColor('rgba(0,0,0,0.25)')
            .border({ width: 1, color: this.sm.getColor('border') })
            .margin({ bottom: 6 })
          }

          // 工具调用/结果卡片（chat:tool_call / chat:tool_result）
          if ((msg.toolCalls?.length ?? 0) > 0) {
            Column() {
              ForEach(msg.toolCalls, (tc: ToolCallView) => {
                Column() {
                  Row() {
                    AppIcon({ name: 'gear', iconSize: 12, color: this.sm.getColor('primary') })
                    Text('调用工具 ' + tc.name)
                      .fontSize(this.sm.getFontSize('caption'))
                      .fontColor(this.sm.getColor('text_secondary'))
                      .margin({ left: 5 })
                      .layoutWeight(1)
                    Text(tc.result !== '' ? '✓ 已完成' : '执行中…')
                      .fontSize(this.sm.getFontSize('caption'))
                      .fontColor(tc.result !== '' ? this.sm.getColor('success') : this.sm.getColor('text_tertiary'))
                  }
                  .width('100%')
                  if (tc.args !== '') {
                    Text(tc.args)
                      .fontFamily('monospace')
                      .fontSize(11)
                      .fontColor(this.sm.getColor('text_tertiary'))
                      .width('100%')
                      .maxLines(3)
                      .textOverflow({ overflow: TextOverflow.Ellipsis })
                      .margin({ top: 3 })
                  }
                  if (tc.result !== '') {
                    Text(tc.result)
                      .fontFamily('monospace')
                      .fontSize(11)
                      .fontColor(this.sm.getColor('text_tertiary'))
                      .width('100%')
                      .maxLines(5)
                      .textOverflow({ overflow: TextOverflow.Ellipsis })
                      .margin({ top: 3 })
                  }
                }
                .width('100%')
                .alignItems(HorizontalAlign.Start)
                .padding(7)
                .borderRadius(8)
                .backgroundColor('rgba(0,0,0,0.25)')
                .border({ width: 1, color: this.sm.getColor('border') })
                .margin({ bottom: 5 })
              }, (tc: ToolCallView) => tc.name + tc.args + tc.result)
            }
            .width('100%')
            .margin({ bottom: 6 })
          }

          // 计划时间轴卡（chat:plan_update，PC PlanPanel 的气泡内轻量版）
          if ((msg.plan?.length ?? 0) > 0) {
            Column() {
              ForEach(msg.plan, (ps: PlanStepView) => {
                Row() {
                  Text(ps.status === 'done' ? '✓' : (ps.status === 'in_progress' ? '●' : '○'))
                    .fontSize(12)
                    .fontColor(ps.status === 'done' ? this.sm.getColor('success') : this.sm.getColor('primary'))
                  Text(ps.step)
                    .fontSize(this.sm.getFontSize('caption'))
                    .fontColor(this.sm.getColor('text_secondary'))
                    .margin({ left: 6 })
                    .layoutWeight(1)
                }
                .width('100%')
                .margin({ bottom: 3 })
              }, (ps: PlanStepView) => ps.step + ps.status)
            }
            .width('100%')
            .alignItems(HorizontalAlign.Start)
            .padding(8)
            .borderRadius(8)
            .backgroundColor('rgba(0,0,0,0.25)')
            .border({ width: 1, color: this.sm.getColor('border') })
            .margin({ bottom: 6 })
          }

          // 产出物卡（chat:artifact——console 从 tool_result 派生；点击经 WS 代理取内容预览）
          if ((msg.artifacts?.length ?? 0) > 0) {
            Column() {
              ForEach(msg.artifacts, (a: ArtifactView) => {
                Row() {
                  AppIcon({ name: this.kindIcon(a.kind), iconSize: 13, color: this.sm.getColor('primary') })
                  Text(a.name)
                    .fontSize(this.sm.getFontSize('caption'))
                    .fontColor(this.sm.getColor('text_primary'))
                    .margin({ left: 6 })
                    .layoutWeight(1)
                    .maxLines(1)
                    .textOverflow({ overflow: TextOverflow.Ellipsis })
                  if (a.size > 0) {
                    Text(this.formatSize(a.size))
                      .fontSize(11)
                      .fontColor(this.sm.getColor('text_tertiary'))
                      .margin({ right: 6 })
                  }
                  Text('打开')
                    .fontSize(11)
                    .fontColor(this.sm.getColor('primary'))
                }
                .width('100%')
                .padding(7)
                .borderRadius(8)
                .backgroundColor('rgba(0,0,0,0.25)')
                .border({ width: 1, color: this.sm.getColor('border') })
                .margin({ bottom: 5 })
                .onClick(() => { this.openArtifact(a); })
              }, (a: ArtifactView) => a.artifactId + a.name)
            }
            .width('100%')
            .margin({ bottom: 6 })
          }

          // 治理审批请求卡（移动端只读展示，裁决走 PC 端治理面）
          if (msg.approval !== '') {
            Row() {
              AppIcon({ name: 'shield', iconSize: 13, color: this.sm.getColor('error') })
              Text(msg.approval)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .margin({ left: 6 })
                .layoutWeight(1)
            }
            .width('100%')
            .padding(8)
            .borderRadius(8)
            .backgroundColor('rgba(248,113,113,0.12)')
            .border({ width: 1, color: 'rgba(248,113,113,0.40)' })
            .margin({ bottom: 6 })
          }

          Column() {
            // 消息内容（Markdown 渲染）+ 流式光标
            if (msg.content.length > 0) {
              Row() {
                MarkdownText({ content: msg.content })
                  .layoutWeight(1)
                if (msg.isStreaming) {
                  Text('▍')
                    .fontSize(this.sm.getFontSize('body_sm'))
                    .fontColor(this.sm.getColor('primary'))
                    .margin({ left: 2 })
                }
              }
              .width('100%')
              .alignItems(VerticalAlign.Bottom)
            } else if (!msg.isStreaming) {
              Text('（空回复）')
                .fontSize(this.sm.getFontSize('body_sm'))
                .fontColor(this.sm.getColor('text_primary'))
            }
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
