/**
 * presets - 内置动画预设库
 *
 * 职责：定义并注册所有内置动画预设到 AnimationManager
 * 设计：函数式注册，调用 registerBuiltInPresets() 完成全部内置预设注册
 *
 * 用法：
 *   import { registerBuiltInPresets } from '../animation/presets';
 *   registerBuiltInPresets();  // 一次性注册所有内置预设
 */

import { AnimationManager, AnimationPreset, EasingType } from './AnimationManager';

/** fade-in：淡入 */
const FADE_IN: AnimationPreset = {
  name: 'fade-in',
  duration: 300,
  easing: EasingType.EASE_OUT,
  from: { opacity: 0 },
  to: { opacity: 1 },
};

/** fade-out：淡出 */
const FADE_OUT: AnimationPreset = {
  name: 'fade-out',
  duration: 300,
  easing: EasingType.EASE_IN,
  from: { opacity: 1 },
  to: { opacity: 0 },
};

/** slide-up：向上滑入 */
const SLIDE_UP: AnimationPreset = {
  name: 'slide-up',
  duration: 300,
  easing: EasingType.EASE_OUT,
  from: { translateY: 100 },
  to: { translateY: 0 },
};

/** slide-down：向下滑出 */
const SLIDE_DOWN: AnimationPreset = {
  name: 'slide-down',
  duration: 300,
  easing: EasingType.EASE_IN,
  from: { translateY: 0 },
  to: { translateY: 100 },
};

/** scale-in：缩放进入 */
const SCALE_IN: AnimationPreset = {
  name: 'scale-in',
  duration: 200,
  easing: EasingType.SPRING,
  from: { scale: 0.8 },
  to: { scale: 1 },
};

/** scale-out：缩放退出 */
const SCALE_OUT: AnimationPreset = {
  name: 'scale-out',
  duration: 200,
  easing: EasingType.EASE_IN,
  from: { scale: 1 },
  to: { scale: 0.8 },
};

/** glass-blur：玻璃模糊 */
const GLASS_BLUR: AnimationPreset = {
  name: 'glass-blur',
  duration: 500,
  easing: EasingType.EASE_OUT,
  from: { blur: 0 },
  to: { blur: 20 },
};

/** 全部内置预设清单 */
const BUILT_IN_PRESETS: AnimationPreset[] = [
  FADE_IN,
  FADE_OUT,
  SLIDE_UP,
  SLIDE_DOWN,
  SCALE_IN,
  SCALE_OUT,
  GLASS_BLUR,
];

/**
 * 注册所有内置动画预设到 AnimationManager 单例
 * 幂等：重复调用会覆盖同名预设，无副作用
 */
export function registerBuiltInPresets(): void {
  const am = AnimationManager.getInstance();
  for (const preset of BUILT_IN_PRESETS) {
    am.registerPreset(preset);
  }
}
