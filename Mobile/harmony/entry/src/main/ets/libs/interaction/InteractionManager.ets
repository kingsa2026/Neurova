/**
 * InteractionManager - 统一交互管理库
 *
 * 职责：统一管理应用所有交互行为（防抖、节流、长按判定、滑动方向判定）
 * 设计：单例模式，所有交互判定集中管理，避免散落在各组件中
 *
 * 用法：
 *   const im = InteractionManager.getInstance();
 *   const debounced = im.debounce(() => doSomething(), 200);
 *   const throttled = im.throttle(() => onScroll(), 100);
 *   if (im.isLongPress(pressDuration)) { ... }
 *   const dir = im.detectSwipe(dx, dy);
 */

import { Logger } from '../logger/Logger';

/** 日志标签 */
const TAG = 'InteractionManager';

/** 默认长按阈值（毫秒） */
const DEFAULT_LONG_PRESS_THRESHOLD = 500;

/** 滑动方向判定最小位移阈值（像素） */
const SWIPE_THRESHOLD = 30;

/** 滑动方向类型 */
export type SwipeDirection = 'left' | 'right' | 'up' | 'down';

export class InteractionManager {
  private static instance: InteractionManager;
  /** 长按阈值（毫秒） */
  private longPressThreshold: number = DEFAULT_LONG_PRESS_THRESHOLD;
  /** debounce 内部 timer 句柄映射（按函数引用） */
  private debounceTimers: Map<Function, number> = new Map();
  /** throttle 内部上次执行时间映射（按函数引用） */
  private throttleLastTime: Map<Function, number> = new Map();

  private constructor() {}

  /** 获取单例实例 */
  static getInstance(): InteractionManager {
    if (!InteractionManager.instance) {
      InteractionManager.instance = new InteractionManager();
    }
    return InteractionManager.instance;
  }

  /**
   * 防抖：在 wait 毫秒内多次调用只执行最后一次
   * 实现：每次调用清掉之前的 timer，重新计时
   *
   * @param fn 目标函数
   * @param wait 等待毫秒
   * @returns 包装后的函数
   */
  debounce<T extends (...args: Object[]) => void>(fn: T, wait: number): T {
    const self = this;
    const debounced = function (...args: Object[]) {
      // 清掉之前的 timer
      const prevTimer = self.debounceTimers.get(fn);
      if (prevTimer !== undefined) {
        clearTimeout(prevTimer);
      }
      // 重新计时
      const timer = setTimeout(() => {
        self.debounceTimers.delete(fn);
        fn(...args);
      }, wait);
      self.debounceTimers.set(fn, timer);
    } as T;
    return debounced;
  }

  /**
   * 节流：在 wait 毫秒内只执行第一次调用
   * 实现：记录上次执行时间，未到 wait 跳过
   *
   * @param fn 目标函数
   * @param wait 等待毫秒
   * @returns 包装后的函数
   */
  throttle<T extends (...args: Object[]) => void>(fn: T, wait: number): T {
    const self = this;
    const throttled = function (...args: Object[]) {
      const now = Date.now();
      const lastTime = self.throttleLastTime.get(fn) ?? 0;
      if (now - lastTime >= wait) {
        self.throttleLastTime.set(fn, now);
        fn(...args);
      }
    } as T;
    return throttled;
  }

  /**
   * 长按判定：给定按下时长是否达到长按阈值
   *
   * @param durationMs 按下持续时长（毫秒）
   * @returns true 表示达到长按阈值
   */
  isLongPress(durationMs: number): boolean {
    return durationMs >= this.longPressThreshold;
  }

  /**
   * 滑动方向判定：根据 dx/dy 位移返回主方向
   * 规则：若 |dx| 与 |dy| 均小于阈值 30 返回 null；否则比较 |dx| 与 |dy| 决定主方向
   *
   * @param dx 水平位移（正值向右，负值向左）
   * @param dy 垂直位移（正值向下，负值向上）
   * @returns 方向枚举或 null
   */
  detectSwipe(dx: number, dy: number): SwipeDirection | null {
    const absDx = Math.abs(dx);
    const absDy = Math.abs(dy);

    // 位移太小，不构成滑动
    if (absDx < SWIPE_THRESHOLD && absDy < SWIPE_THRESHOLD) {
      return null;
    }

    // 比较主方向：水平 vs 垂直
    if (absDx >= absDy) {
      return dx > 0 ? 'right' : 'left';
    } else {
      return dy > 0 ? 'down' : 'up';
    }
  }

  /**
   * 设置长按阈值
   *
   * @param ms 阈值毫秒
   */
  setLongPressThreshold(ms: number): void {
    if (ms <= 0) {
      Logger.getInstance().warn(TAG, `setLongPressThreshold 收到非正数 ${ms}，已忽略`);
      return;
    }
    this.longPressThreshold = ms;
  }

  /**
   * 获取当前长按阈值
   *
   * @returns 阈值毫秒
   */
  getLongPressThreshold(): number {
    return this.longPressThreshold;
  }
}
