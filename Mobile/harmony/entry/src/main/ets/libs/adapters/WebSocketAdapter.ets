/**
 * WebSocketAdapter - WebSocket 适配层
 *
 * 职责：桥接上层与鸿蒙 @kit.NetworkKit 的 websocket 模块，将底层 WebSocket
 *      事件转译为 EventBus 事件分发；提供断线重连与心跳保活能力；
 *      支持出站账本游标续传（sync_resume）与快照重同步（sync_snapshot_required）
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

import { webSocket } from '@kit.NetworkKit';
import { BusinessError } from '@ohos.base';
import { Logger } from '../logger/Logger';
import { EventBus } from '../bus/EventBus';
import { AuthStore } from '../state/stores/AuthStore';
import { ApiFacade } from '../api/ApiFacade';
import { ErrorManager, ErrorCategory } from '../error/ErrorManager';
import { WSMessage, WsConnectionRuntimeContract } from '../types';
import { resolveTunnelAuthFrame, randomNonceHex } from '../protocol/TunnelTokenCrypto';

/** 日志标签 */
const TAG = 'WebSocketAdapter';
/** 心跳间隔（毫秒），固定 30s */
const HEARTBEAT_INTERVAL = 30000;
/** 最大重连次数 */
const MAX_RECONNECT = 10;
/** 重连退避基数（毫秒）：min(0.5s * 2^n, 30s)，n 从 0 计 */
const RECONNECT_BASE_MS = 500;
/** 重连退避上限（毫秒）：封顶在抖动之前生效 */
const RECONNECT_CAP_MS = 30000;
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

/** ws:connected 事件负载 */
interface WsConnectedPayload {
  url: string;
}

/** ws:disconnected 事件负载（字段可选以兼容两条派发路径） */
interface WsDisconnectedPayload {
  code?: number;
  reason?: string;
  manual?: boolean;
}

/** ws:error 事件负载 */
interface WsErrorPayload {
  message: string;
  error?: Error;
}

/** ws:message 事件负载 */
interface WsMessagePayload {
  data: string;
}

/** sync_resume 请求（远程驾驶可靠性：断线重连按游标补拉缺失帧） */
interface SyncResumeRequest {
  type: string;
  last_seq: number;
  scope?: string;      // D-5 按需订阅范围：session / thread（global 缺省不带）
  scope_key?: string;  // 范围归属键：session/thread 时必填（服务端越权防线校验）
}

/** sync_snapshot_required 通告（服务端判定游标不可续传，要求弃游标按快照重同步） */
interface SyncSnapshotRequiredNotice {
  type: string;
  reason?: string;   // 机器可读原因：cursor_pruned / cursor_ahead_of_head / cursor_invalid / no_cursor / budget_exhausted
  note?: string;     // 服务端诚实标注（供日志与排查）
  head_seq?: number; // 服务端当前账本头（仅诊断用，不可当本地游标——中间帧本端未收到）
}

export class WebSocketAdapter {
  private static instance: WebSocketAdapter;
  private logger: Logger = Logger.getInstance();
  private bus: EventBus = EventBus.getInstance();
  private errorManager: ErrorManager = ErrorManager.getInstance();
  private authStore: AuthStore = new AuthStore();
  private apiFacade: ApiFacade = ApiFacade.getInstance();

  /** 鸿蒙 WebSocket 实例 */
  private ws: webSocket.WebSocket | null = null;
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
  /**
   * D-5 三端契约对齐：连接契约（服务端 pong 帧 connection_runtime，G4 单源）
   * 到达后覆盖以下取值；未到达前保持既有缺省（行为零变化）。
   */
  private heartbeatIntervalMs: number = HEARTBEAT_INTERVAL;
  private reconnectBaseMs: number = RECONNECT_BASE_MS;
  private reconnectCapMs: number = RECONNECT_CAP_MS;
  /** D-5 按需订阅范围（页面经 setSubscriptionScope 设置；缺省 global 全收） */
  private subscriptionScope: string = 'global';
  private subscriptionScopeKey: string = '';
  /** 最近一次连接的 URL（用于重连） */
  private lastUrl: string = '';
  /** 最近一次连接的 token（用于重连） */
  private lastToken: string = '';
  /**
   * relay 模式（wsUrl 含 /t/ 路由前缀，与 ServerProfiles.entryMode 同判据）。
   * U9.1：连接建立后**首条**消息必须是 auth 帧（含 nv1 信封 token）——
   * 中继默认 fail-closed 拒绝 URL 携 token 旧形态。直连模式不发 auth 帧（行为不变）。
   */
  private relayMode: boolean = false;
  /** auth 首帧已发出、尚未收到任何回帧：此窗口内服务端 unknown_type 回执按握手噪声记日志 */
  private authFrameInFlight: boolean = false;
  /** 是否为主动断开（主动断开时不触发自动重连） */
  private manualClose: boolean = false;
  /** 外部注册的原始消息处理器列表 */
  private messageHandlers: Array<(data: string) => void> = [];
  /** 服务端账本游标：已收到的最大帧 seq（远程驾驶可靠性，重连补拉用；仅内存，不跨启动） */
  private lastServerSeq: number = 0;

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
   * @param token  可选鉴权 token，作为 header 凭证
   *
   * 根因修复（2026-11-18 模拟器实测）：配对下发的 connect_ticket 是**一次性且
   * 短时效（60s）**的凭证——ChatPage 进入时距配对/上次续签往往已超过时效，
   * 直接拿存量 ticket 握手必吃 403（服务端拒绝在 accept 之前），表现为
   * 「未配对或凭证已失效/空回复」。因此只要持有长期设备身份
   * （pairingId + deviceSecret），连接前**先续签换新 ticket** 再握手；
   * 续签失败不阻断（回落传入 ticket，由握手结果自然暴露）。
   */
  async connect(url: string, token?: string, skipRefresh: boolean = false): Promise<void> {
    // 记录连接参数以便重连复用
    this.lastUrl = url;
    // relay 模式判定：中继入口是 /t/<routeId> 前缀（ServerProfiles.entryMode 同一判据）。
    // 判定取**传入 URL**——重连时 lastUrl 即原始入参，口径一致。
    this.relayMode = url.indexOf('/t/') >= 0;
    if (token !== undefined) {
      this.lastToken = token;
    }
    let effectiveToken = token;
    if (!skipRefresh && this.authStore.pairingId !== '' && this.authStore.deviceSecret !== '') {
      try {
        const res = await this.apiFacade.mobilePairing.refresh({
          pairingId: this.authStore.pairingId,
          deviceSecret: this.authStore.deviceSecret,
          challenge: `${Date.now()}`,
        });
        if (res.code === 0 && res.data && res.data.connectTicket) {
          effectiveToken = res.data.connectTicket;
          this.lastToken = effectiveToken;
        } else {
          this.logger.warn(TAG, '连接前续签未通过，回落存量凭证握手');
        }
      } catch (e) {
        this.logger.warn(TAG, '连接前续签失败，回落存量凭证握手', e as Error);
      }
    }
    // 每次连接重置主动关闭标记
    this.manualClose = false;

    // 清理旧连接（解除旧事件回调，避免回调到已失效的上下文）
    this.cleanupWebSocket();

    // 创建新 WebSocket 实例并注册事件回调
    this.ws = webSocket.createWebSocket();
    this.registerEvents();

    // 构造完整 URL（凭证走 header，不进 URL）
    const fullUrl = this.buildUrl(url);
    this.logger.info(TAG, `正在连接 WebSocket: ${fullUrl}`);

    try {
      // 发起握手，header 中携带 Authorization
      await this.ws.connect(fullUrl, {
        header: {
          'Authorization': effectiveToken ? `Bearer ${effectiveToken}` : '',
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
      const payload: WsErrorPayload = { message: err.message, error: err };
      this.bus.emit('ws:error', payload);
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
    const payload: WsDisconnectedPayload = { reason: 'manual' };
    this.bus.emit('ws:disconnected', payload);
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
      const payload: WsConnectedPayload = { url: this.lastUrl };
      this.bus.emit('ws:connected', payload);
      // relay 模式先发 auth 首帧，再起心跳/补拉（U9.1：auth 前不接受任何其他帧）
      this.onConnectionOpened();
    });

    // 收到消息：SDK 签名为 AsyncCallback<string | ArrayBuffer>，即 (err, data) 两参回调；
    // 文本帧按 JSON 消息分发，二进制帧不在本适配层处理范围
    this.ws.on('message', (err: BusinessError, data: string | ArrayBuffer) => {
      if (err) {
        this.logger.error(TAG, 'WebSocket 消息接收错误', err);
        return;
      }
      if (typeof data === 'string') {
        this.handleMessage(data);
      }
    });

    // 连接关闭
    this.ws.on('close', (value: Object) => {
      this.connected = false;
      this.stopHeartbeat();
      // close 事件载荷可能缺省（2026-11-19 11:53 实测崩溃 undefined.code）——可选链兜底
      const ev = value as CloseEventData | undefined;
      const code: number = ev?.code ?? 0;
      const reason: string = ev?.reason ?? '';
      this.logger.warn(TAG, `WebSocket 已关闭 code=${code} reason=${reason}`);

      if (this.manualClose) {
        // 主动关闭：由 disconnect() 负责发事件，此处不处理
        return;
      }
      if (code === 4401 || code === 4403) {
        // relay 鉴权被拒（4401=凭据/首帧不合规，4403=令牌型进错通道）：
        // 同一凭据重试必然再拒——诚实上报并停止自动重连，不拖成重连风暴
        this.logger.error(TAG, `relay 鉴权被拒 code=${code} reason=${reason}`);
        this.errorManager.reportError(
          'relay_auth_rejected',
          `中继准入被拒（${code}）：${reason}`,
          ErrorCategory.WEBSOCKET,
        );
        const authPayload: WsErrorPayload = { message: 'relay_auth_rejected: ' + reason };
        this.bus.emit('ws:error', authPayload);
        return;
      }
      const payload: WsDisconnectedPayload = { code, reason, manual: false };
      this.bus.emit('ws:disconnected', payload);
      if (code === 4001) {
        // 凭证失效（一次性 ticket 已消费/过期）：先续签再重连；
        // 设备被解除时 refresh 会拒绝 → 发 device_deregistered 并停止（唯一重扫路径）
        this.reauthAndReconnect();
        return;
      }
      // 触发自动重连（重连前同样先续签，ticket 60s 时效重连时几乎必过期）
      this.reauthAndReconnect();
    });

    // 错误
    this.ws.on('error', (value: Object) => {
      // 全量打出事件原值：ErrorEventData 只有可选 message，漏掉 code/stack 会把
      // 真因（如 TLS/握手细节）吞成「未知错误」，真机排查无从下手
      this.logger.error(TAG, `WebSocket 错误原值: ${JSON.stringify(value)}`);
      const ev = value as ErrorEventData | undefined;
      const message: string = ev?.message ?? '未知错误';
      this.logger.error(TAG, `WebSocket 错误: ${message}`);
      this.errorManager.reportError(
        'ws_error',
        `WebSocket 错误: ${message}`,
        ErrorCategory.WEBSOCKET,
      );
      const payload: WsErrorPayload = { message };
      this.bus.emit('ws:error', payload);
      // 握手期失败（如 ticket 过期 403）不一定伴随 close 事件：不触发自愈，
      // 连接就停在死态，后续 send 全部抛「未连接」（12:10 实测的空回复根因之一）
      if (!this.connected) {
        this.reauthAndReconnect();
      }
    });
  }

  /** 处理收到的消息：分发原始事件 + 调用注册处理器 + 按 type 路由到 EventBus */
  private handleMessage(raw: string): void {
    // 1. 发送原始消息事件
    const payload: WsMessagePayload = { data: raw };
    this.bus.emit('ws:message', payload);

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
    // 服务端 unknown_type 回执：auth 首帧窗口内是预期噪声（当前后端不在移动入口
    // 消费 auth 帧，中继也不经手手机侧帧），窗口外是调用方拼错类型——都只记日志，
    // 不当聊天失败上抛（误触发 isGenerating 复位与错误文案）。
    if (type === 'error') {
      const rec = parsed as Object as Record<string, Object>;
      if (String(rec['code'] ?? '') === 'unknown_type') {
        if (this.authFrameInFlight) {
          this.logger.debug(TAG, 'auth 首帧被对端按 unknown_type 回执（预期：入口未启用 auth 帧校验）');
        } else {
          this.logger.warn(TAG, `服务端未知消息类型回执: ${raw.slice(0, 200)}`);
        }
        return;
      }
    }
    // 任何非 unknown_type 帧（含 pong/业务帧）到达即说明 auth 交换期已过
    this.authFrameInFlight = false;
    // 服务端快照重同步通告：游标过旧/非法/预算耗尽时增量必不完整——
    // 立即弃游标并复用既有重连路径，以首屏快照恢复（不做会漏帧的部分重放）
    if (type === 'sync_snapshot_required') {
      this.handleSnapshotRequired(raw);
      return;
    }
    // D-5 三端契约对齐：pong 携带 connection_runtime 契约（G4 单源），到达即
    // 覆盖心跳/退避取值；无该字段的 pong（旧后端）保持现行为。
    if (type === 'pong' && parsed.connection_runtime !== undefined) {
      this.applyConnectionRuntime(parsed.connection_runtime);
    }
    // 服务端帧带单调 seq（先落账再发送）：推进游标（重放帧按原 seq 计，幂等）
    if (parsed.seq !== undefined && parsed.seq > this.lastServerSeq) {
      this.lastServerSeq = parsed.seq;
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
      case 'chat:reasoning':
        // 思考流：服务端在 content 之前推送；UI 侧暂未消费，但必须按契约分发
        // （此前落 default 被当「未识别」丢弃，11:41 实测每帧都打未识别日志）
        return 'chat:reasoning';
      case 'chat:tool_call':
        // 工具调用/结果事件：会话页工具卡数据源（对齐 PC）
        return 'chat:tool_call';
      case 'chat:tool_result':
        return 'chat:tool_result';
      case 'chat:artifact':
        // 产出物事件：会话页产出物卡数据源（console 从 tool_result 派生，对齐 PC）
        return 'chat:artifact';
      case 'chat:plan_update':
        // 计划时间轴事件（update_plan 结果派生）
        return 'chat:plan_update';
      case 'chat:usage':
        // 回合用量事件（上下文环读数）
        return 'chat:usage';
      case 'chat:approval_required':
        // 治理审批请求（移动端只读展示）
        return 'chat:approval_required';
      case 'model:list_result':
      case 'context:composition_result':
      case 'artifact:content_result':
        // WS 代理查询回帧（模型候选/上下文组成/产物内容）
        return type;
      case 'chat:queued':
        return 'chat:queued';
      case 'chat:retry':
        return 'chat:retry';
      case 'chat:cancelled':
        return 'chat:cancelled';
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
  // 断线重连补拉（远程驾驶可靠性）
  // ===========================================================================

  /**
   * 连接建立后的首帧序列：relay 模式先 auth（服务端 5s 窗），再心跳与补拉。
   *
   * U9.1/U16：中继对 agent 通道 fail-closed——连接建立后首条消息必须是
   * `{"type":"auth","token":...,"tokenType":...}`。token 已是 nv1 信封则原样用；
   * 裸密钥则按 protocol.signTunnelToken 口径本地签 nv1:agent 信封（凭据全文不进帧）。
   * 直连模式不发 auth 帧（行为不变）。
   */
  private async onConnectionOpened(): Promise<void> {
    if (this.relayMode && this.lastToken !== '') {
      this.authFrameInFlight = true;
      try {
        const nonce = await randomNonceHex(8);
        const frame = await resolveTunnelAuthFrame(
          this.lastToken, Math.floor(Date.now() / 1000), nonce);
        await this.send(JSON.stringify(frame));
        this.logger.info(TAG, `relay auth 首帧已发送（tokenType=${frame.tokenType}）`);
      } catch (e) {
        this.authFrameInFlight = false;
        const err = e as Error;
        this.logger.error(TAG, 'relay auth 首帧发送失败', err);
        const payload: WsErrorPayload = { message: 'relay_auth_send_failed: ' + err.message };
        this.bus.emit('ws:error', payload);
        // auth 都发不出去：不起心跳，不把未认证连接当可用连接用
        return;
      }
    }
    // 启动心跳保活
    this.startHeartbeat();
    // 远程驾驶可靠性：重连后按游标补拉断线期间错过的帧（首次连接游标为 0 不发）
    this.resumeMissedFrames();
  }

  /** 重连后按游标补拉：服务端出站帧先落账再发送（带单调 seq），发 sync_resume
   * 让服务端补发 lastServerSeq 之后的帧（带 replay 标记）。首次连接游标为 0
   * 不发——不注入额外首帧，保持既有契约。游标仅存内存：应用重启后走会话
   * 历史恢复，不重放旧帧（避免与历史加载双份渲染）。 */
  private resumeMissedFrames(): void {
    if (this.lastServerSeq <= 0) {
      return;
    }
    const req: SyncResumeRequest = { type: 'sync_resume', last_seq: this.lastServerSeq };
    // D-5 按需订阅：非 global 范围随补拉请求下发（服务端只推范围内帧；
    // 范围由页面经 setSubscriptionScope 设置，缺省 global 不带参数=全量）
    if (this.subscriptionScope !== 'global' && this.subscriptionScopeKey !== '') {
      req.scope = this.subscriptionScope;
      req.scope_key = this.subscriptionScopeKey;
    }
    this.send(JSON.stringify(req)).catch((e: Error) => {
      this.logger.warn(TAG, 'sync_resume 补拉发送失败（连接可能再次断开）', e);
    });
  }

  /**
   * D-5 按需订阅：设置订阅范围（看一个线程不付全部线程的账）。
   * scope ∈ session/thread/global；session/thread 须带非空 scopeKey
   * （与服务端 parseSubscriptionScope 同规，非法输入保持原范围不变）。
   * 断线重连的 sync_resume 会自动携带该范围。
   */
  setSubscriptionScope(scope: string, scopeKey: string): void {
    const normalized: string = scope.trim().toLowerCase();
    if (normalized !== 'session' && normalized !== 'thread' && normalized !== 'global') {
      this.logger.warn(TAG, `非法订阅范围: ${scope}，保持 ${this.subscriptionScope}`);
      return;
    }
    if (normalized !== 'global' && scopeKey.trim() === '') {
      this.logger.warn(TAG, `${normalized} 范围缺少 scope_key，保持 ${this.subscriptionScope}`);
      return;
    }
    this.subscriptionScope = normalized;
    this.subscriptionScopeKey = normalized === 'global' ? '' : scopeKey.trim();
  }

  /**
   * 处理 sync_snapshot_required（服务端 → 客户端）：本地游标已不可续传
   * （过旧被修剪 / 非法 / 重放预算耗尽），服务端拒绝部分重放，要求按快照重同步。
   *
   * 端上动作：
   *   1. lastServerSeq 归零——重连成功后 resumeMissedFrames 不再携带旧游标，
   *      连接按首连语义以首屏快照恢复（会话历史走既有加载链路）；
   *   2. 主动关闭当前连接，经 on('close') 复用既有 reauthAndReconnect() 退避重连，
   *      不另起第二条重连路径。
   *
   * 注意：head_seq 只是服务端当前账本头，不能拿来当本地游标——(cursor, head]
   * 之间的帧本端并未收到，拿它续传正是要避免的漏帧。
   */
  private handleSnapshotRequired(raw: string): void {
    let reason: string = '';
    let note: string = '';
    let headSeq: number = 0;
    try {
      const notice = JSON.parse(raw) as SyncSnapshotRequiredNotice;
      reason = notice.reason ?? '';
      note = notice.note ?? '';
      headSeq = notice.head_seq ?? 0;
    } catch (e) {
      this.logger.warn(TAG, 'sync_snapshot_required 解析失败，按未知原因弃游标重同步', e as Error);
    }
    this.logger.info(TAG, `服务端要求快照重同步：弃用本地游标 reason=${reason} head_seq=${headSeq} note=${note}`);
    // 弃游标：重连后不发 sync_resume，按首连语义走首屏快照恢复
    this.lastServerSeq = 0;
    // 复用既有重连流程：主动关闭当前连接，由 on('close') → reauthAndReconnect() 接管
    if (this.ws) {
      try {
        this.ws.close().catch((e: Error) => {
          this.logger.warn(TAG, '快照重同步关闭旧连接失败（连接可能已断开）', e);
        });
      } catch (e) {
        this.logger.warn(TAG, '快照重同步关闭旧连接异常（连接可能已断开）', e as Error);
      }
    }
  }

  // ===========================================================================
  // 心跳保活
  // ===========================================================================

  /** 启动心跳：使用 setTimeout 递归实现，周期取连接契约（缺省 30s，契约到达后跟随服务端） */
  private startHeartbeat(): void {
    this.stopHeartbeat();
    const beat = (): void => {
      this.send(HEARTBEAT_MESSAGE).catch((e: Error) => {
        this.logger.warn(TAG, '心跳发送失败', e);
      });
      // 递归调度下一次心跳
      this.heartbeatTimerId = setTimeout(beat, this.heartbeatIntervalMs);
    };
    // 首次延迟一个间隔后发送
    this.heartbeatTimerId = setTimeout(beat, this.heartbeatIntervalMs);
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
    this.reauthAndReconnect();
  }

  /**
   * 续签后重连（M2 免扫码判据）：设备身份（pairingId+deviceSecret）换新一次性
   * ticket 再连；设备被解除（refresh 403/410）→ 发 device_deregistered 并停止重连。
   */
  private reauthAndReconnect(): void {
    if (this.reconnectCount >= this.maxReconnect) {
      this.logger.warn(TAG, `达到最大重连次数 ${this.maxReconnect}，停止重连`);
      return;
    }
    if (this.manualClose) {
      return;
    }
    this.reconnectCount++;
    const delayMs: number = this.nextReconnectDelayMs();
    this.logger.info(TAG, `第 ${this.reconnectCount}/${this.maxReconnect} 次重连，${Math.round(delayMs)}ms 后尝试`);

    this.reconnectTimerId = setTimeout(() => {
      this.reconnectTimerId = -1;
      this.refreshTicketThenConnect().catch((e: Error) => {
        this.logger.error(TAG, '重连失败', e);
        this.tryReconnect();
      });
    }, delayMs);
  }

  /**
   * 下次重连退避时延（毫秒）：min(base * 2^n, cap) 后乘 ±20% 抖动。
   * base/cap 取连接契约（D-5：服务端 connection_runtime.reconnect 单源下发，
   * 到达后覆盖）；缺省 0.5s/30s 与服务端常量同值。
   * n 从 0 计：首次重连 0.5s 起步（reconnectCount 已先行自增，故取 n = 次数 - 1）。
   */
  private nextReconnectDelayMs(): number {
    const attempt: number = Math.max(0, this.reconnectCount - 1);
    const cappedMs: number = Math.min(this.reconnectBaseMs * Math.pow(2, attempt), this.reconnectCapMs);
    const jitter: number = 0.8 + Math.random() * 0.4;
    return cappedMs * jitter;
  }

  /**
   * D-5 三端契约对齐：应用服务端 pong 帧携带的 connection_runtime 契约——
   * 心跳周期与重连退避 base/cap 从单源契约取值；字段缺失/非法时保持现值
   * （旧后端 pong 无该字段 = 行为零变化）。
   */
  private applyConnectionRuntime(contract: WsConnectionRuntimeContract): void {
    const intervalS: number | undefined = contract.heartbeat?.interval_s;
    if (intervalS !== undefined && intervalS > 0) {
      this.heartbeatIntervalMs = Math.min(Math.max(intervalS * 1000, 100), 300000);
    }
    const baseS: number | undefined = contract.reconnect?.backoff_base_s;
    if (baseS !== undefined && baseS > 0) {
      this.reconnectBaseMs = Math.min(Math.max(baseS * 1000, 100), 60000);
    }
    const capS: number | undefined = contract.reconnect?.backoff_cap_s;
    if (capS !== undefined && capS > 0) {
      this.reconnectCapMs = Math.max(capS * 1000, this.reconnectBaseMs);
    }
  }

  /** 用长期设备身份换新 ticket 再连；无设备身份（未配对）时按旧 token 直连 */
  private async refreshTicketThenConnect(): Promise<void> {
    let ticket: string = this.lastToken;
    if (this.authStore.pairingId !== '' && this.authStore.deviceSecret !== '') {
      const res = await this.apiFacade.mobilePairing.refresh({
        pairingId: this.authStore.pairingId,
        deviceSecret: this.authStore.deviceSecret,
        challenge: `${Date.now()}`,
      });
      if (res.code !== 0 || !res.data || !res.data.connectTicket) {
        // 设备已解除/不在册：停止重连并点名（唯一需要重新配对的路径）
        this.logger.warn(TAG, '续签被拒，设备可能已解除配对');
        const payload: WsErrorPayload = { message: 'device_deregistered' };
        this.bus.emit('ws:error', payload);
        this.errorManager.reportError(
          'device_deregistered',
          '设备配对已失效，请重新扫码配对',
          ErrorCategory.WEBSOCKET,
        );
        return;
      }
      ticket = res.data.connectTicket;
      this.lastToken = ticket;
    }
    // 已在此处续签过：skipRefresh 避免连接前重复续签
    await this.connect(this.lastUrl, ticket, true);
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

  /** 构造完整 URL：**凭证不进 URL**。

   * 接入凭证是一次性的，挂在 query 上会随每一次中转（含中继）落进访问日志；
   * 它只经 `Authorization` 头送出（见 connect() 里的 header）。
   * 这里保留方法本身：URL 归一（去尾斜杠）仍然要用。
   */
  private buildUrl(url: string, token?: string): string {
    if (token) {
      // 刻意不把 token 拼进 URL；留着这条签名是为了不改调用面，行为改在此处
      this.logger.debug(TAG, '凭证经 header 送出，不写入 URL');
    }
    return url;
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
