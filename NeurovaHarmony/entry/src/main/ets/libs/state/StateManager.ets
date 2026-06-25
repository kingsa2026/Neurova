/**
 * StateManager - 统一状态管理库
 *
 * 职责：统一管理应用所有状态（key-value 存储 + 订阅通知）
 * 设计：单例模式，发布-订阅；可作为 ArkUI AppStorage 的补充，用于非 UI 响应式状态
 *
 * 用法：
 *   const sm = StateManager.getInstance();
 *   sm.set('user', userObj);
 *   const user = sm.get<User>('user');
 *   const unsub = sm.subscribe('user', (u) => { /* ... *\/ });
 *   unsub();  // 取消订阅
 */

import { Logger } from '../logger/Logger';

/** 订阅回调 */
export type StateSubscriber = (value: Object) => void;

export class StateManager {
  private static instance: StateManager;
  private state: Map<string, Object> = new Map();
  private subscribers: Map<string, Set<StateSubscriber>> = new Map();
  private logger: Logger = Logger.getInstance();

  private constructor() {}

  static getInstance(): StateManager {
    if (!StateManager.instance) {
      StateManager.instance = new StateManager();
    }
    return StateManager.instance;
  }

  /** 获取值 */
  get<T>(key: string): T | undefined;
  get<T>(key: string, defaultValue: T): T;
  get<T>(key: string, defaultValue?: T): T | undefined {
    if (this.state.has(key)) {
      return this.state.get(key) as T;
    }
    return defaultValue;
  }

  /** 设置值并通知订阅者 */
  set<T>(key: string, value: T): void {
    this.state.set(key, value as Object);
    this.notify(key, value as Object);
  }

  /** 订阅 key 的变更，返回取消订阅函数 */
  subscribe(key: string, subscriber: StateSubscriber): () => void {
    if (!this.subscribers.has(key)) {
      this.subscribers.set(key, new Set());
    }
    this.subscribers.get(key)!.add(subscriber);
    return () => {
      const set = this.subscribers.get(key);
      if (set) {
        set.delete(subscriber);
        if (set.size === 0) {
          this.subscribers.delete(key);
        }
      }
    };
  }

  /** 判断 key 是否存在 */
  has(key: string): boolean {
    return this.state.has(key);
  }

  /** 移除 key（不通知订阅者） */
  remove(key: string): void {
    this.state.delete(key);
  }

  /** 清空所有状态和订阅 */
  clearAll(): void {
    this.state.clear();
    this.subscribers.clear();
  }

  /** 返回所有 key */
  keys(): string[] {
    return Array.from(this.state.keys());
  }

  /** 通知指定 key 的所有订阅者 */
  private notify(key: string, value: Object): void {
    const set = this.subscribers.get(key);
    if (!set || set.size === 0) return;
    const snapshot = Array.from(set);
    for (const fn of snapshot) {
      try {
        fn(value);
      } catch (e) {
        this.logger.error('StateManager', `订阅者异常 (key=${key})`, e as Error);
      }
    }
  }
}
