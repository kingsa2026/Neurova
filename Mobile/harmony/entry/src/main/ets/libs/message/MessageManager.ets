/**
 * MessageManager - 统一 UI 提示库
 *
 * 职责：统一管理应用所有消息提示（toast/success/error/warning/info），
 *       通过 EventBus 触发 'message:show' 事件供 UI 层订阅渲染
 * 设计：单例模式；默认委托 EventBus 分发，可通过 setHandler 注入自定义分发（测试用）；
 *       维护最近 100 条历史记录，每条记录 id 为递增数字字符串
 *
 * 用法：
 *   const mm = MessageManager.getInstance();
 *   mm.toast('保存成功');
 *   mm.error('网络异常');
 *
 *   // UI 层订阅渲染：
 *   EventBus.getInstance().on('message:show', (record) => { /* 渲染 toast *\/ });
 */

import { Logger } from '../logger/Logger';
import { EventBus } from '../bus/EventBus';

/** 消息类型 */
export enum MessageType {
  INFO = 'info',
  SUCCESS = 'success',
  WARNING = 'warning',
  ERROR = 'error',
}

/** 消息记录 */
export interface MessageRecord {
  id: string;           // 唯一标识（递增数字字符串）
  type: MessageType;    // 消息类型
  text: string;         // 消息文本
  duration: number;     // 显示时长（毫秒），0 表示需手动关闭
  createdAt: number;    // 创建时间戳（毫秒）
}

/** 自定义消息处理器（注入后替代 EventBus 分发） */
export type MessageHandler = (msg: MessageRecord) => void;

/** 历史记录上限 */
const MAX_HISTORY = 100;
/** 默认显示时长（毫秒） */
const DEFAULT_DURATION = 2000;
/** EventBus 消息事件名 */
const MESSAGE_EVENT = 'message:show';

export class MessageManager {
  private static instance: MessageManager;
  private history: MessageRecord[] = [];
  private seq: number = 0;
  private handler: MessageHandler | undefined = undefined;
  private logger: Logger = Logger.getInstance();
  private bus: EventBus = EventBus.getInstance();

  private constructor() {}

  static getInstance(): MessageManager {
    if (!MessageManager.instance) {
      MessageManager.instance = new MessageManager();
    }
    return MessageManager.instance;
  }

  /** toast 提示，默认 2000ms */
  toast(message: string, duration: number = DEFAULT_DURATION): void {
    this.show(MessageType.INFO, message, duration);
  }

  /** success 提示 */
  success(message: string): void {
    this.show(MessageType.SUCCESS, message, DEFAULT_DURATION);
  }

  /** error 提示 */
  error(message: string): void {
    this.show(MessageType.ERROR, message, DEFAULT_DURATION);
  }

  /** warning 提示 */
  warning(message: string): void {
    this.show(MessageType.WARNING, message, DEFAULT_DURATION);
  }

  /** info 提示 */
  info(message: string): void {
    this.show(MessageType.INFO, message, DEFAULT_DURATION);
  }

  /** 获取历史记录（只读副本） */
  getHistory(): MessageRecord[] {
    return this.history.slice();
  }

  /** 清空历史 */
  clearHistory(): void {
    this.history = [];
  }

  /** 注入自定义分发 handler；传入 undefined 清空，回退到 EventBus */
  setHandler(handler: MessageHandler | undefined): void {
    this.handler = handler;
  }

  /** 内部统一展示：创建记录 → 入历史 → 分发 */
  private show(type: MessageType, text: string, duration: number): void {
    const record: MessageRecord = {
      id: String(++this.seq),
      type,
      text,
      duration,
      createdAt: Date.now(),
    };

    // 记录历史，超出上限丢弃最旧
    this.history.push(record);
    if (this.history.length > MAX_HISTORY) {
      this.history.shift();
    }

    // 日志输出
    this.logger.info('MessageManager', `[${type}] ${text}`);

    // 分发：自定义 handler 优先，否则走 EventBus
    if (this.handler) {
      this.handler(record);
    } else {
      this.bus.emit(MESSAGE_EVENT, record);
    }
  }
}
