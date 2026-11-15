/**
 * EventBus - 统一事件总线
 *
 * 职责：统一管理应用所有事件的订阅、发布、取消订阅
 * 设计：单例模式，发布-订阅模式，handler 异常隔离
 *
 * 用法：
 *   const bus = EventBus.getInstance();
 *   bus.on('chat:message', (data) => { /* ... *\/ });
 *   bus.emit('chat:message', { text: 'hello' });
 *   bus.off('chat:message', handler);
 */

import { Logger } from '../logger/Logger';

/** 事件处理器函数 */
export type EventHandler = (data: Object) => void;

export class EventBus {
  private static instance: EventBus;
  /** 事件名 → 处理器列表 */
  private handlers: Map<string, EventHandler[]> = new Map();
  private logger: Logger = Logger.getInstance();

  private constructor() {}

  static getInstance(): EventBus {
    if (!EventBus.instance) {
      EventBus.instance = new EventBus();
    }
    return EventBus.instance;
  }

  /** 订阅事件 */
  on(event: string, handler: EventHandler): void {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, []);
    }
    this.handlers.get(event)!.push(handler);
  }

  /** 一次性订阅：触发后自动移除 */
  once(event: string, handler: EventHandler): void {
    const wrapper: EventHandler = (data: Object) => {
      this.off(event, wrapper);
      handler(data);
    };
    this.on(event, wrapper);
  }

  /** 取消订阅（仅移除指定 handler） */
  off(event: string, handler: EventHandler): void {
    const list = this.handlers.get(event);
    if (!list) return;
    const idx = list.indexOf(handler);
    if (idx >= 0) {
      list.splice(idx, 1);
    }
    if (list.length === 0) {
      this.handlers.delete(event);
    }
  }

  /** 发布事件：依次调用所有订阅者，异常隔离 */
  emit(event: string, data: Object): void {
    const list = this.handlers.get(event);
    if (!list || list.length === 0) return;
    // 复制一份，避免 once 在迭代中修改原数组
    const snapshot = list.slice();
    for (const handler of snapshot) {
      try {
        handler(data);
      } catch (e) {
        this.logger.error('EventBus', `事件 "${event}" 处理器异常`, e as Error);
      }
    }
  }

  /** 清除指定事件的全部订阅 */
  clear(event: string): void {
    this.handlers.delete(event);
  }

  /** 清除所有事件订阅 */
  clearAll(): void {
    this.handlers.clear();
  }

  /** 返回指定事件的订阅者数量 */
  listenerCount(event: string): number {
    return this.handlers.get(event)?.length ?? 0;
  }
}
