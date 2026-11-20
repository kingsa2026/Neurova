/**
 * AsrStreamClient - 后端流式 ASR WebSocket 客户端（对照报告 B4-1 移动端适配）
 *
 * 职责：把 AudioCapturer 采到的 16k/mono/16bit PCM 以二进制帧送到
 *      后端 /api/v1/audio/asr/stream，接收 partial/final 转写事件
 * 设计：一次性会话客户端（非单例）：connect → sendPcm* → finish/stop → dispose；
 *      鉴权沿用全仓 WS 口径 ?token=<JWT>（该端点只认 query token，不走 header）
 *
 * 协议（与后端 neurova/api/endpoints/audio.py asr_stream 对齐）：
 *   上行：二进制帧 = PCM16LE 单声道 16kHz；文本帧 = JSON 控制（finish/stop）
 *   下行：ready / partial / final / error / pong
 *
 * 用法：
 *   const c = new AsrStreamClient();
 *   await c.connect('wss://host/api/v1/audio/asr/stream', jwt, {
 *     onReady: (engine) => {}, onPartial: (t) => {}, onFinal: (t) => {},
 *     onError: (code, msg) => {}, onClosed: () => {},
 *   });
 *   c.sendPcm(pcmBuffer);  // 采集回调里逐帧送
 *   c.finish();            // 按住说话松手时终结当前轮
 *   c.dispose();           // 取消/收尾
 */

import { webSocket } from '@kit.NetworkKit';
import { BusinessError } from '@ohos.base';
import { Logger } from '../logger/Logger';

const TAG = 'AsrStreamClient';

/** 服务端下行帧回调集 */
export interface AsrStreamCallbacks {
  onReady: (engine: string) => void;
  onPartial: (text: string, turnId: number) => void;
  onFinal: (text: string, turnId: number, reason: string) => void;
  onError: (code: string, message: string) => void;
  onClosed: () => void;
}

export class AsrStreamClient {
  private logger: Logger = Logger.getInstance();
  private ws: webSocket.WebSocket | null = null;
  private callbacks: AsrStreamCallbacks | null = null;
  private closedByUser: boolean = false;

  /**
   * 建立连接并注册事件回调。
   * @param url    形如 ws(s)://host/api/v1/audio/asr/stream
   * @param token  登录 JWT（query 携带，encodeURIComponent 转义）
   */
  async connect(url: string, token: string, callbacks: AsrStreamCallbacks): Promise<void> {
    this.closedByUser = false;
    this.callbacks = callbacks;
    this.ws = webSocket.createWebSocket();
    const fullUrl = url + (url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(token);

    this.ws.on('open', (value: Object) => {
      // 就绪以服务端下发的 ready 帧为准，此处仅记录传输层连通
      this.logger.info(TAG, 'ASR 流式传输层已连接');
    });
    this.ws.on('message', (err: BusinessError, data: string | ArrayBuffer) => {
      if (err) {
        this.logger.error(TAG, 'ASR 流式消息接收错误', err);
        return;
      }
      if (typeof data === 'string') {
        this.handleText(data);
      }
    });
    this.ws.on('close', (value: Object) => {
      this.logger.info(TAG, 'ASR 流式连接关闭');
      this.ws = null;
      this.callbacks?.onClosed();
    });
    this.ws.on('error', (err: BusinessError) => {
      this.logger.warn(TAG, 'ASR 流式连接错误: ' + err.message);
      this.callbacks?.onError('socket', err.message ?? '');
    });

    await this.ws.connect(fullUrl, { header: {} });
  }

  /** 解析服务端下行 JSON 帧（非 JSON 帧忽略） */
  private handleText(raw: string): void {
    let frame: Record<string, Object>;
    try {
      frame = JSON.parse(raw) as Record<string, Object>;
    } catch (e) {
      this.logger.warn(TAG, '忽略非 JSON 下行帧');
      return;
    }
    const type = String(frame['type'] ?? '');
    if (type === 'ready') {
      this.callbacks?.onReady(String(frame['engine'] ?? ''));
    } else if (type === 'partial') {
      this.callbacks?.onPartial(String(frame['text'] ?? ''), Number(frame['turn_id'] ?? 0));
    } else if (type === 'final') {
      this.callbacks?.onFinal(String(frame['text'] ?? ''), Number(frame['turn_id'] ?? 0), String(frame['reason'] ?? ''));
    } else if (type === 'error') {
      this.callbacks?.onError(String(frame['code'] ?? ''), String(frame['message'] ?? ''));
    }
  }

  /** 发送一帧 PCM16LE 音频（任意长度，服务端自切 10ms 子帧） */
  sendPcm(chunk: ArrayBuffer): void {
    if (this.ws) {
      this.ws.send(chunk);
    }
  }

  /** 终结当前轮（服务端回 final；连接保持） */
  finish(): void {
    if (this.ws) {
      this.ws.send('{"type":"finish"}');
    }
  }

  /** 终结当前轮并要求服务端关闭连接 */
  stop(): void {
    if (this.ws) {
      this.ws.send('{"type":"stop"}');
    }
  }

  /** 立即关闭（取消录音用；不终结当前轮） */
  dispose(): void {
    this.closedByUser = true;
    const client = this.ws;
    this.ws = null;
    if (client) {
      // 尽力而为关闭；close 返回的 Promise 不影响主流程
      client.close();
    }
  }
}
