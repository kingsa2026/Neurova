/**
 * ChatPage - 对话页
 *
 * 职责：基于 WebSocket 流式协议的实时对话界面，支持 Agent 切换、流式消息渲染、停止生成
 * 设计：Column [TopNavMenu] + [AgentSwitcher] + [List 消息列表 layoutWeight:1] + [输入区 Row]；
 *       进入页面通过 WebSocketAdapter 建立 WS 连接，订阅 EventBus 的 chat:chunk/done/error 事件；
 *       用户发送消息时创建 user 消息 + assistant 占位消息，通过 WS 下发 chat:send；
 *       收到 chunk 追加到占位消息，收到 done/error 结束流式状态；
 *       颜色统一走 StyleManager，配置走 ConfigManager，日志走 Logger，路由走 Router
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、AgentSwitcher、GlassInput、GlassButton、GlassPanel
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

import { TopNavMenu, AgentSwitcher, GlassInput, GlassButton, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AuthStore } from '../libs/state/stores/AuthStore';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { WebSocketAdapter } from '../libs/adapters/WebSocketAdapter';
import { EventBus, EventHandler } from '../libs/bus/EventBus';
import { ConfigManager } from '../libs/config/ConfigManager';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { WSChatChunk, Agent } from '../libs/types';
import { Router } from '../routing/Router';
import { ChunkBatcher } from '../libs/perf/ChunkBatcher';
import { SimpleDataSource } from '../libs/perf/SimpleDataSource';

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

@Component
export struct ChatPage {
  // 消息列表（双向：user 右对齐，assistant 左对齐）
  @State messages: ChatMessageView[] = [];
  // 输入框文本
  @State inputText: string = '';
  // 是否正在生成（控制发送/停止按钮切换）
  @State isGenerating: boolean = false;
  // 当前会话 ID（进入页面时生成）
  @State sessionId: string = 'session-' + Date.now();
  // 当前 Agent ID（从 AgentsStore 读取）
  @State currentAgentId: string = '';
  // Agent 列表（供 AgentSwitcher 渲染）
  @State agents: Agent[] = [];

  // 统一库单例
  private api = ApiFacade.getInstance();
  private authStore = new AuthStore();
  private agentsStore = new AgentsStore();
  private ws = WebSocketAdapter.getInstance();
  private bus = EventBus.getInstance();
  private config = ConfigManager.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private router = Router.getInstance();

  // List 滚动控制器：用于新消息到达时自动滚动到底部
  private scroller: Scroller = new Scroller();
  // 保存事件处理器引用，便于 aboutToDisappear 时精准取消订阅，避免重复绑定
  private chunkHandler: EventHandler = () => {};
  private doneHandler: EventHandler = () => {};
  private errorHandler: EventHandler = () => {};
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
    // 3. 建立 WS 连接
    this.connectWs();
    // 4. 订阅聊天事件
    this.subscribeEvents();
  }

  aboutToDisappear() {
    // 取消事件订阅，避免再次进入页面时重复绑定导致 chunk 被多次追加
    this.bus.off('chat:chunk', this.chunkHandler);
    this.bus.off('chat:done', this.doneHandler);
    this.bus.off('chat:error', this.errorHandler);
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
      const res = await this.api.agents.list({ page: 1, size: 100 });
      if (res.code === 0 && res.data) {
        this.agents = res.data.items;
        this.agentsStore.setAgents(this.agents);
        // 若 store 中无当前 Agent，默认选中第一个
        if (!this.currentAgentId && this.agents.length > 0) {
          this.currentAgentId = this.agents[0].id;
        }
      }
    } catch (e) {
      this.logger.warn(TAG, '加载 Agent 列表失败，使用缓存', e as Error);
    }
  }

  /**
   * 建立 WebSocket 连接
   * 配置：从 ConfigManager 读取 ws_base_url，携带 AuthStore 中的 access_token
   */
  private async connectWs(): Promise<void> {
    const wsUrl = this.config.get<string>('ws_base_url', 'ws://192.168.10.132:9527/v1/mobile/ws');
    const token = this.authStore.accessToken;
    try {
      await this.ws.connect(wsUrl, token);
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

    this.doneHandler = () => {
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
      // 清理 batcher 以备下次会话
      this.batcher.reset();
    };
    this.bus.on('chat:done', this.doneHandler);

    this.errorHandler = (data: Object) => {
      this.isGenerating = false;
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
      if (last) {
        last.isStreaming = false;
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

  /** Agent 切换：更新当前 ID 并写回 store */
  private onSwitchAgent(agentId: string): void {
    this.currentAgentId = agentId;
    this.agentsStore.switchAgent(agentId);
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

  build() {
    Column() {
      // 顶部导航栏：标题"对话"，显示返回按钮
      TopNavMenu({
        title: '对话',
        showBack: true,
        showMenu: false,
        onBack: () => { this.router.back(); }
      })

      // Agent 切换器：横向滚动胶囊列表
      AgentSwitcher({
        currentAgentId: this.currentAgentId,
        agents: this.agents,
        onSwitch: (id: string) => { this.onSwitchAgent(id); }
      })
        .margin({
          left: this.sm.getSpacing('md'),
          right: this.sm.getSpacing('md'),
          top: this.sm.getSpacing('sm'),
          bottom: this.sm.getSpacing('sm'),
        })

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
        List({ space: this.sm.getSpacing('sm'), scroller: this.scroller }) {
          LazyForEach(this.messagesDs, (msg: ChatMessageView) => {
            ListItem() {
              this.buildMessage(msg)
            }
          }, (msg: ChatMessageView) => msg.id)
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

      // 输入区：GlassInput 占满剩余空间 + 发送/停止按钮
      Row() {
        GlassInput({
          placeholder: '输入消息...',
          value: this.inputText,
          type: 'text',
          onChange: (v: string) => { this.inputText = v; },
          onSubmit: () => { this.sendMessage(); }
        })
          .layoutWeight(1)

        if (this.isGenerating) {
          // 生成中：显示停止按钮
          GlassButton({
            text: '停止',
            type: 'danger',
            size: 'medium',
            onClick: () => { this.stopGeneration(); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
        } else {
          // 空闲：显示发送按钮
          GlassButton({
            text: '发送',
            type: 'primary',
            size: 'medium',
            disabled: this.inputText.trim().length === 0,
            onClick: () => { this.sendMessage(); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
        }
      }
      .width('100%')
      .padding(this.sm.getSpacing('md'))
      .alignItems(VerticalAlign.Center)
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('background'))
  }

  // ===========================================================================
  // 消息气泡构建器
  // ===========================================================================

  /** 单条消息气泡：根据 role 选择右对齐（user）/ 左对齐（assistant） */
  @Builder
  buildMessage(msg: ChatMessageView) {
    if (msg.role === 'user') {
      // 用户消息：右对齐，primary 色背景，白色文字
      Row() {
        Column() {
          Text(msg.content)
            .fontSize(this.sm.getFontSize('body'))
            .fontColor('#ffffff')
          // 时间戳
          Text(this.formatTime(msg.timestamp))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor('rgba(255,255,255,0.8)')
            .margin({ top: 4 })
            .alignSelf(ItemAlign.End)
        }
        .padding({
          left: this.sm.getSpacing('md'),
          right: this.sm.getSpacing('md'),
          top: this.sm.getSpacing('sm'),
          bottom: this.sm.getSpacing('sm'),
        })
        .borderRadius(this.sm.getRadius('lg'))
        .backgroundColor(this.sm.getColor('primary'))
        // 限制气泡最大宽度，避免占满整行
        .constraintSize({ maxWidth: '75%' })
        .alignItems(HorizontalAlign.Start)
      }
      .width('100%')
      .justifyContent(FlexAlign.End)
    } else {
      // assistant 消息：左对齐，玻璃色背景
      Row() {
        GlassPanel({ variant: 'subtle', padding: this.sm.getSpacing('md'), radius: this.sm.getRadius('lg') }) {
          Column() {
            // Agent 署名
            Text(this.getAgentName())
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ bottom: 4 })
            // 消息内容 + 流式光标
            Row() {
              Text(msg.content.length > 0 ? msg.content : (msg.isStreaming ? '' : '（空回复）'))
                .fontSize(this.sm.getFontSize('body'))
                .fontColor(this.sm.getColor('text_primary'))
              // 流式生成中显示闪烁光标
              if (msg.isStreaming) {
                Text('▍')
                  .fontSize(this.sm.getFontSize('body'))
                  .fontColor(this.sm.getColor('primary'))
                  .margin({ left: 2 })
              }
            }
            .width('100%')
            .alignItems(VerticalAlign.Bottom)
            // 时间戳
            Text(this.formatTime(msg.timestamp))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_disabled'))
              .margin({ top: 4 })
              .alignSelf(ItemAlign.End)
          }
          .alignItems(HorizontalAlign.Start)
        }
        .constraintSize({ maxWidth: '75%' })
      }
      .width('100%')
      .justifyContent(FlexAlign.Start)
    }
  }
}
