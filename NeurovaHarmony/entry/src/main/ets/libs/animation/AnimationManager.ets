/**
 * AnimationManager - 统一动画库
 *
 * 职责：统一管理应用所有动画预设、时长、缓动曲线
 * 设计：单例模式，支持预设注册、查询、ArkUI 缓动曲线映射
 *
 * 用法：
 *   const am = AnimationManager.getInstance();
 *   const preset = am.getPreset('fade-in');
 *   const curve = am.getEasingCurve(EasingType.EASE_OUT);
 */

import { Logger } from '../logger/Logger';

/** 日志标签 */
const TAG = 'AnimationManager';

/** 动画时长预设（毫秒） */
export enum AnimationDuration {
  FAST = 150,
  NORMAL = 300,
  SLOW = 500,
}

/** 缓动类型 */
export enum EasingType {
  EASE_IN,
  EASE_OUT,
  SPRING,
  LINEAR,
}

/** 缓动类型 → ArkUI 缓动曲线字符串映射 */
const EASING_CURVES: Record<number, string> = {
  [EasingType.EASE_IN]: 'ease-in',
  [EasingType.EASE_OUT]: 'ease-out',
  [EasingType.SPRING]: 'spring({damping: 0.7, stiffness: 100})',
  [EasingType.LINEAR]: 'linear',
};

/** 动画预设 */
export interface AnimationPreset {
  /** 预设名称 */
  name: string;
  /** 时长（毫秒） */
  duration: number;
  /** 缓动类型 */
  easing: EasingType;
  /** 起始属性 */
  from: Record<string, Object>;
  /** 结束属性 */
  to: Record<string, Object>;
}

export class AnimationManager {
  private static instance: AnimationManager;
  private logger: Logger = Logger.getInstance();
  /** 预设名 → 预设对象 */
  private presets: Map<string, AnimationPreset> = new Map();

  private constructor() {
    this.logger.info(TAG, 'AnimationManager 初始化');
  }

  static getInstance(): AnimationManager {
    if (!AnimationManager.instance) {
      AnimationManager.instance = new AnimationManager();
    }
    return AnimationManager.instance;
  }

  /** 获取时长枚举对应的毫秒数 */
  getDuration(d: AnimationDuration): number {
    return d;
  }

  /** 获取缓动类型对应的 ArkUI 缓动曲线字符串 */
  getEasingCurve(e: EasingType): string {
    return EASING_CURVES[e] ?? 'linear';
  }

  /** 注册动画预设 */
  registerPreset(preset: AnimationPreset): void {
    this.presets.set(preset.name, preset);
    this.logger.debug(TAG, `注册动画预设: ${preset.name}`);
  }

  /** 查询动画预设，未知名返回 undefined */
  getPreset(name: string): AnimationPreset | undefined {
    return this.presets.get(name);
  }

  /** 列出所有已注册的预设名 */
  listPresets(): string[] {
    return Array.from(this.presets.keys());
  }
}
