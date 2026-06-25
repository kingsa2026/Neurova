/**
 * WebSocketAdapter - WebSocket 适配层
 *
 * 职责：桥接上层与鸿蒙 @kit.NetworkKit 的 websocket 模块，将底层 WebSocket
 *      事件转译为 EventBus 事件分发；提供断线重连与心跳保活能力
 * 设计：单例模式，纯桥接层，不含业务逻辑；所有消息经 EventBus 统一分发
 *
 * 用法：
 *   const ws = WebSocketAdapter.getInstance();
 *   await ws.connect('ws://192.168.10.132:9527/v1/mobile/ws', 'tokenxxx');
 *   ws.onMessage((data) => { /* 处理原始文本 *\/ });
 *   await ws.send('{"type":"chat:send","content":"hi"}');
 *   await ws.disconnect();
 *
 * 事件分发（EventBus）：
 *   ws:connected      连接建立
 *   ws:disconnected   连接断开
 *   ws:message        收到原始消息（data 为原始字符串）
 *   ws:error          连接错误或收到 type=error 消息
 *   chat:chunk        流式 chunk
 *   chat:done         流式完成
 *   chat:error        聊天错误
 *   agent:switched    Agent 切换确认
 *   session:list      会话列表
 *   session:created   会话创建确认
 */

import { websocket } from '@kit.NetworkKit';
import { Logger } from '../logger/Logger';
import { EventBus } from '../bus/EventBus';
import { ConfigManager } from '../config/ConfigManager';
import { ErrorManager, ErrorCategory } from '../error/ErrorManager';
import { WSMessage } from '../types';

/** 日志标签 */
const TAG = 'WebSocketAdapter';
/** 心跳间隔（毫秒），固定 30s */
const HEARTBEAT_INTERVAL = 30000;
/** 最大重连次数 */
const MAX_RECONNECT = 10;
/** 默认重连间隔（毫秒），当 ConfigManager 未配置时使用 */
const DEFAULT_RECONNECT_INTERVAL = 5000;
/** 心跳消息内容 */
const HEARTBEAT_MESSAGE = '{"type":"ping"}';

/** close 事件回调数据结构（字段可选以兼容运行时差异） */
interface CloseEventData {
  code?: number;
  reason?: string;
}

/** error 事件回调数据结构（字段可选以兼容运行时差异） */
interface ErrorEventData {
  code?: number;
  message?: string;
}

export class WebSocketAdapter {
  private static instance: WebSocketAdapter;
  private logger: Logger = Logger.getInstance();
  private bus: EventBus = EventBus.getInstance();
  private config: ConfigManager = ConfigManager.getInstance();
  private errorManager: ErrorManager = ErrorManager.getInstance();

  /** 鸿蒙 WebSocket 实例 */
  private ws: websocket.WebSocket | null = null;
  /** 当前是否已连接 */
  private connected: boolean = false;
  /** 心跳定时器 ID（setTimeout 句柄） */
  private heartbeatTimerId: number = -1;
  /** 重连定时器 ID（setTimeout 句柄） */
  private reconnectTimerId: number = -1;
  /** 已重连次数 */
  private reconnectCount: number = 0;
  /** 最大重连次数 */
  private maxReconnect: number = MAX_RECONNECT;
  /** 最近一次连接的 URL（用于重连） */
  private lastUrl: string = '';
  /** 最近一次连接的 token（用于重连） */
  private lastToken: string = '';
  /** 是否为主动断开（主动断开时不触发自动重连） */
  private manualClose: boolean = false;
  /** 外部注册的原始消息处理器列表 */
  private messageHandlers: Array<(data: string) => void> = [];

  private constructor() {}

  /** 获取单例实例 */
  static getInstance(): WebSocketAdapter {
    if (!WebSocketAdapter.instance) {
      WebSocketAdapter.instance = new WebSocketAdapter();
    }
    return WebSocketAdapter.instance;
  }

  /**
   * 建立 WebSocket 连接
   * @param url    WebSocket 服务地址
   * @param token  可选鉴权 token，作为 query 参数附加到 URL
   */
  async connect(url: string, token?: string): Promise<void> {
    // 记录连接参数以便重连复用
    this.lastUrl = url;
    if (token !== undefined) {
      this.lastToken = token;
    }
    // 每次连接重置主动关闭标记
    this.manualClose = false;

    // 清理旧连接（解除旧事件回调，避免回调到已失效的上下文）
    this.cleanupWebSocket();

    // 创建新 WebSocket 实例并注册事件回调
    this.ws = websocket.createWebSocket();
    this.registerEvents();

    // 构造完整 URL（含 token query 参数）
    const fullUrl = this.buildUrl(url, token);
    this.logger.info(TAG, `正在连接 WebSocket: ${fullUrl}`);

    try {
      // 发起握手，header 中携带 Authorization
      await this.ws.connect(fullUrl, {
        header: {
          'Authorization': token ? `Bearer ${token}` : '',
        },
      });
      // 连接成功的状态由 on('open') 回调统一处理
    } catch (e) {
      const err = e as Error;
      this.logger.error(TAG, 'WebSocket 连接失败', err);
      this.errorManager.reportError(
        'ws_connect_failed',
        `WebSocket 连接失败: ${err.message}`,
        ErrorCategory.WEBSOCKET,
      );
      this.bus.emit('ws:error', { message: err.message, error: err });
      throw new Error(`[WebSocketAdapter] 连接失败: ${err.message}`);
    }
  }

  /** 主动断开连接：清除心跳与重连定时器，关闭底层 WebSocket */
  async disconnect(): Promise<void> {
    this.logger.info(TAG, '主动断开 WebSocket');
    // 标记主动关闭，阻止 on('close') 触发重连与重复事件
    this.manualClose = true;
    // 清除定时器
    this.stopHeartbeat();
    this.stopReconnect();
    // 重置重连计数
    this.reconnectCount = 0;
    this.connected = false;

    if (this.ws) {
      try {
        await this.ws.close();
      } catch (e) {
        this.logger.warn(TAG, '关闭 WebSocket 异常', e as Error);
      }
      this.cleanupWebSocket();
    }

    // 主动断开由此处统一发一次 disconnected 事件
    this.bus.emit('ws:disconnected', { reason: 'manual' });
  }

  /**
   * 发送文本消息
   * @param message 文本内容（通常为 JSON 字符串）
   */
  async send(message: string): Promise<void> {
    if (!this.connected || !this.ws) {
      throw new Error('[WebSocketAdapter] 未连接，无法发送消息');
    }
    try {
      await this.ws.send(message);
    } catch (e) {
      const err = e as Error;
      this.logger.error(TAG, `发送消息失败: ${message}`, err);
      throw new Error(`[WebSocketAdapter] 发送失败: ${err.message}`);
    }
  }

  /** 返回当前是否处于连接状态 */
  isConnected(): boolean {
    return this.connected;
  }

  /**
   * 注册原始消息处理器：收到任意消息时回调
   * @param handler 处理函数，接收原始文本
   */
  onMessage(handler: (data: string) => void): void {
    this.messageHandlers.push(handler);
  }

  // ===========================================================================
  // 事件注册与处理
  // ===========================================================================

  /** 注册底层 WebSocket 事件回调 */
  private registerEvents(): void {
    if (!this.ws) {
      return;
    }

    // 连接建立
    this.ws.on('open', (value: Object) => {
      this.connected = true;
      // 连接成功后重置重连计数
      this.reconnectCount = 0;
      this.logger.info(TAG, 'WebSocket 已连接');
      this.bus.emit('ws:connected', { url: this.lastUrl });
      // 启动心跳保活
      this.startHeartbeat();
    });

    // 收到消息
    this.ws.on('message', (value: string, data: ArrayBuffer) => {
      this.handleMessage(value);
    });

    // 连接关闭
    this.ws.on('close', (value: Object) => {
      this.connected = false;
      this.stopHeartbeat();
      const ev = value as CloseEventData;
      const code: number = ev.code ?? 0;
      const reason: string = ev.reason ?? '';
      this.logger.warn(TAG, `WebSocket 已关闭 code=${code} reason=${reason}`);

      if (this.manualClose) {
        // 主动关闭：由 disconnect() 负责发事件，此处不处理
        return;
      }
      this.bus.emit('ws:disconnected', { code, reason, manual: false });
      // 触发自动重连
      this.tryReconnect();
    });

    // 错误
    this.ws.on('error', (value: Object) => {
      const ev = value as ErrorEventData;
      const message: string = ev.message ?? '未知错误';
      this.logger.error(TAG, `WebSocket 错误: ${message}`);
      this.errorManager.reportError(
        'ws_error',
        `WebSocket 错误: ${message}`,
        ErrorCategory.WEBSOCKET,
      );
      this.bus.emit('ws:error', { message });
    });
  }

  /** 处理收到的消息：分发原始事件 + 调用注册处理器 + 按 type 路由到 EventBus */
  private handleMessage(raw: string): void {
    // 1. 发送原始消息事件
    this.bus.emit('ws:message', { data: raw });

    // 2. 调用外部注册的原始消息处理器（异常隔离）
    for (const handler of this.messageHandlers) {
      try {
        handler(raw);
      } catch (e) {
        this.logger.error(TAG, '消息处理器执行异常', e as Error);
      }
    }

    // 3. 解析 JSON 并按 type 字段分发到具体事件
    this.dispatchMessage(raw);
  }

  /** 解析消息并按 type 字段分发到 EventBus */
  private dispatchMessage(raw: string): void {
    let parsed: WSMessage;
    try {
      parsed = JSON.parse(raw) as WSMessage;
    } catch (e) {
      this.logger.warn(TAG, `消息非 JSON 格式: ${raw.slice(0, 200)}`);
      return;
    }

    const type: string = parsed.type;
    if (!type) {
      this.logger.warn(TAG, '消息缺少 type 字段');
      return;
    }

    const event: string = this.typeToEvent(type);
    if (event.length === 0) {
      this.logger.debug(TAG, `未识别的消息类型: ${type}`);
      return;
    }
    this.bus.emit(event, parsed);
  }

  /** 服务端消息 type → EventBus 事件名映射 */
  private typeToEvent(type: string): string {
    switch (type) {
      case 'chat:chunk':
        return 'chat:chunk';
      case 'chat:done':
        return 'chat:done';
      case 'chat:error':
        return 'chat:error';
      case 'agent:switched':
        return 'agent:switched';
      case 'session:list':
        return 'session:list';
      case 'session:created':
        return 'session:created';
      case 'error':
        return 'ws:error';
      default:
        return '';
    }
  }

  // ===========================================================================
  // 心跳保活
  // ===========================================================================

  /** 启动心跳：使用 setTimeout 递归实现，每 30s 发送一次 ping */
  private startHeartbeat(): void {
    this.stopHeartbeat();
    const beat = (): void => {
      this.send(HEARTBEAT_MESSAGE).catch((e: Error) => {
        this.logger.warn(TAG, '心跳发送失败', e);
      });
      // 递归调度下一次心跳
      this.heartbeatTimerId = setTimeout(beat, HEARTBEAT_INTERVAL);
    };
    // 首次延迟一个间隔后发送
    this.heartbeatTimerId = setTimeout(beat, HEARTBEAT_INTERVAL);
  }

  /** 停止心跳定时器 */
  private stopHeartbeat(): void {
    if (this.heartbeatTimerId !== -1) {
      clearTimeout(this.heartbeatTimerId);
      this.heartbeatTimerId = -1;
    }
  }

  // ===========================================================================
  // 断线重连
  // ===========================================================================

  /**
   * 触发自动重连：延迟一个重连间隔后尝试 connect
   * 使用 setTimeout 句柄实现，便于 disconnect 时取消
   */
  private tryReconnect(): void {
    if (this.reconnectCount >= this.maxReconnect) {
      this.logger.warn(TAG, `达到最大重连次数 ${this.maxReconnect}，停止重连`);
      return;
    }
    if (this.manualClose) {
      return;
    }
    this.reconnectCount++;
    const interval: number = this.config.get<number>('ws_reconnect_interval', DEFAULT_RECONNECT_INTERVAL);
    this.logger.info(TAG, `第 ${this.reconnectCount}/${this.maxReconnect} 次重连，${interval}ms 后尝试`);

    this.reconnectTimerId = setTimeout(() => {
      this.reconnectTimerId = -1;
      this.connect(this.lastUrl, this.lastToken).catch((e: Error) => {
        this.logger.error(TAG, '重连失败', e);
        // 递归尝试下一次重连
        this.tryReconnect();
      });
    }, interval);
  }

  /** 停止重连定时器 */
  private stopReconnect(): void {
    if (this.reconnectTimerId !== -1) {
      clearTimeout(this.reconnectTimerId);
      this.reconnectTimerId = -1;
    }
  }

  // ===========================================================================
  // 工具方法
  // ===========================================================================

  /** 构造完整 URL：将 token 作为 query 参数附加 */
  private buildUrl(url: string, token?: string): string {
    if (!token) {
      return url;
    }
    const sep: string = url.includes('?') ? '&' : '?';
    return `${url}${sep}token=${encodeURIComponent(token)}`;
  }

  /** 清理底层 WebSocket：解除事件回调并置空引用 */
  private cleanupWebSocket(): void {
    if (this.ws) {
      try {
        this.ws.off('open');
        this.ws.off('message');
        this.ws.off('close');
        this.ws.off('error');
      } catch (e) {
        // 清理阶段忽略异常
      }
      this.ws = null;
    }
  }
}
