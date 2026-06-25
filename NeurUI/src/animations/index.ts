/**
 * 统一动画预设
 *
 * 提供动画名称与持续时间的预设，供 JS/TS 代码使用。
 * 注意: name 应与 global.css 中的过渡类名前缀对应：
 *   - fade       ↔ .fade-enter-active
 *   - fade-slide ↔ .fade-slide-enter-active
 *   - scale      ↔ .scale-enter-active
 *
 * transitionPresets 提供 Vue <transition> 组件的 props 预设。
 */

export interface AnimationPreset {
  name: string
  duration: number // 毫秒
}

export const animations = {
  fade: { name: 'fade', duration: 250 },
  fadeSlide: { name: 'fade-slide', duration: 300 },
  scale: { name: 'scale', duration: 200 },
  slideUp: { name: 'slide-up', duration: 300 },
  slideDown: { name: 'slide-down', duration: 300 },
  slideLeft: { name: 'slide-left', duration: 300 },
  slideRight: { name: 'slide-right', duration: 300 },
} as const

// Vue <transition> 组件 props 预设
export const transitionPresets: Record<
  string,
  {
    enterActiveClass: string
    leaveActiveClass: string
    enterFromClass?: string
    leaveToClass?: string
  }
> = {
  fade: {
    enterActiveClass: 'transition-opacity duration-250',
    leaveActiveClass: 'transition-opacity duration-250',
    enterFromClass: 'opacity-0',
    leaveToClass: 'opacity-0',
  },
  fadeSlide: {
    enterActiveClass: 'transition-all duration-300',
    leaveActiveClass: 'transition-all duration-300',
    enterFromClass: 'opacity-0 translate-y-2',
    leaveToClass: 'opacity-0 translate-y-2',
  },
  scale: {
    enterActiveClass: 'transition-transform duration-200',
    leaveActiveClass: 'transition-transform duration-200',
    enterFromClass: 'scale-95',
    leaveToClass: 'scale-95',
  },
  slideUp: {
    enterActiveClass: 'transition-transform duration-300',
    leaveActiveClass: 'transition-transform duration-300',
    enterFromClass: 'translate-y-full',
    leaveToClass: 'translate-y-full',
  },
}

export default animations
